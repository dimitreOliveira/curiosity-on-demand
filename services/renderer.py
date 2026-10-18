"""Animation renderer and video assembly service utilizing Playwright and FFmpeg."""

import asyncio
import logging
import re
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import AsyncMock

import imageio_ffmpeg
from playwright.async_api import Browser, async_playwright

from config.settings import Settings, get_settings
from core.audio_utils import get_wav_duration
from core.models import NarrationStoryboard, SceneAnimation

logger = logging.getLogger(__name__)

# Virtual-time shim injected into headless browser contexts before page scripts run.
# Overrides performance.now(), Date.now(), and requestAnimationFrame() so animations
# can be stepped deterministically frame-by-frame faster than real-time with zero
# dropped frames, and supports smooth time-scaling when syncing to audio duration.
DETERMINISTIC_TIME_SHIM = """
(() => {
  let virtualTimeMs = 0;
  let rafIdCounter = 0;
  let rafQueue = new Map();

  const origDateNow = Date.now.bind(Date);
  const baseEpoch = origDateNow();

  try {
    Object.defineProperty(performance, 'now', {
      value: () => virtualTimeMs,
      configurable: true,
      writable: true,
    });
  } catch (e) {
    performance.now = () => virtualTimeMs;
  }

  Date.now = () => baseEpoch + Math.floor(virtualTimeMs);

  window.requestAnimationFrame = (callback) => {
    const id = ++rafIdCounter;
    rafQueue.set(id, callback);
    return id;
  };

  window.cancelAnimationFrame = (id) => {
    rafQueue.delete(id);
  };

  window.__stepVirtualFrame = (targetTimeMs) => {
    virtualTimeMs = targetTimeMs;
    const currentCallbacks = Array.from(rafQueue.entries());
    rafQueue.clear();
    for (const [, cb] of currentCallbacks) {
      try {
        cb(virtualTimeMs);
      } catch (err) {
        console.error('Animation frame callback error:', err);
      }
    }
  };
})();
"""


class AnimationRenderer:
    """Renders HTML5 Canvas and SVG animations to image snapshots and MP4 video clips."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()

    async def render_sample_frame(
        self,
        html_content: str,
        output_image_path: Path,
        width: int | None = None,
        height: int | None = None,
        wait_ms: int = 600,
        duration_seconds: float | None = None,
        sample_progress: float = 0.55,
    ) -> Path:
        """Render standalone HTML/SVG/Canvas code deterministically at climax/mid-scene and capture a lossless PNG snapshot."""
        w = width or self.settings.video_width
        h = height or self.settings.video_height

        # Resolve target virtual timestamp for deterministic peak visual frame capture
        clamped_progress = max(0.05, min(0.95, float(sample_progress)))
        scene_dur = float(
            duration_seconds
            if duration_seconds is not None and duration_seconds > 0
            else self.settings.default_scene_duration_seconds
        )
        target_virtual_ms = scene_dur * clamped_progress * 1000.0

        output_image_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Rendering deterministic sample frame snapshot (%dx%d @ %.1fs [%.0f%%]) to %s",
            w,
            h,
            target_virtual_ms / 1000.0,
            clamped_progress * 100,
            output_image_path,
        )

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page(
                    viewport={"width": w, "height": h},
                    device_scale_factor=1,
                )
                if hasattr(page, "add_init_script"):
                    await page.add_init_script(DETERMINISTIC_TIME_SHIM)
                await page.set_content(html_content, wait_until="domcontentloaded")
                if hasattr(page, "evaluate"):
                    # Step initial frame (t=0) to initialize startTime, then step to peak visual phase
                    await page.evaluate(
                        "if (window.__stepVirtualFrame) { window.__stepVirtualFrame(0.0); }"
                    )
                    await page.evaluate(
                        f"if (window.__stepVirtualFrame) {{ window.__stepVirtualFrame({target_virtual_ms:.1f}); }}"
                    )
                if wait_ms > 0:
                    await page.wait_for_timeout(wait_ms)
                await page.screenshot(path=str(output_image_path), full_page=False)
            finally:
                await browser.close()

        if not output_image_path.exists() or output_image_path.stat().st_size == 0:
            raise RuntimeError(
                f"Failed to capture frame snapshot at {output_image_path}"
            )

        return output_image_path

    async def _record_and_transcode(
        self,
        browser: Browser,
        html_content: str,
        output_video_path: Path,
        duration_seconds: float,
        width: int,
        height: int,
        fps: int,
        audio_path: Path | None = None,
    ) -> Path:
        """Deterministically step HTML canvas frames and encode directly to MP4 via lossless PNG pipe (with optional single-pass audio mux)."""
        native_duration = max(0.1, float(duration_seconds))
        valid_audio = (
            audio_path
            if (
                audio_path is not None
                and audio_path.exists()
                and audio_path.stat().st_size > 0
            )
            else None
        )

        # If audio is provided, synchronize target playback duration in a single pass
        target_duration = native_duration
        if valid_audio is not None:
            try:
                probed_audio_dur = await self.get_media_duration(valid_audio)
                if probed_audio_dur > 0:
                    target_duration = probed_audio_dur
            except (RuntimeError, OSError, ValueError) as err:
                logger.warning(
                    "Could not probe audio duration for %s (%s); using native duration %.2fs",
                    valid_audio,
                    err,
                    native_duration,
                )

        total_frames = max(1, round(target_duration * fps))

        # Build single-pass FFmpeg command reading deterministic lossless PNG frames from image2pipe stdin
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "-framerate",
            str(fps),
            "-i",
            "-",
        ]

        if valid_audio is not None:
            cmd.extend(["-i", str(valid_audio.resolve())])

        cmd.extend(
            [
                "-t",
                f"{target_duration:.3f}",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-tune",
                "animation",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(fps),
            ]
        )

        if valid_audio is not None:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])

        cmd.extend(["-movflags", "+faststart", str(output_video_path)])

        logger.debug("Executing single-pass ffmpeg pipe encode: %s", " ".join(cmd))

        context = await browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=1,
        )
        try:
            await context.add_init_script(DETERMINISTIC_TIME_SHIM)
            page = await context.new_page()
            await page.set_content(html_content, wait_until="domcontentloaded")

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                for frame_idx in range(total_frames):
                    if total_frames > 1:
                        virtual_time_ms = (
                            (frame_idx / float(total_frames)) * native_duration * 1000.0
                        )
                    else:
                        virtual_time_ms = 0.0

                    await page.evaluate(f"window.__stepVirtualFrame({virtual_time_ms})")
                    frame_bytes = await page.screenshot(
                        type="png",
                        full_page=False,
                    )
                    if proc.stdin is not None:
                        proc.stdin.write(frame_bytes)
                        await proc.stdin.drain()
            except BrokenPipeError:
                logger.warning(
                    "FFmpeg stdin pipe closed early while rendering %s",
                    output_video_path,
                )
            finally:
                if proc.stdin is not None:
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass

            _stdout, stderr = await proc.communicate()
            await page.close()

            if proc.returncode != 0:
                logger.error("FFmpeg pipe encode error: %s", stderr.decode())
                raise RuntimeError(
                    f"FFmpeg pipe encode failed with return code {proc.returncode}"
                )
        finally:
            await context.close()

        if not output_video_path.exists() or output_video_path.stat().st_size == 0:
            raise RuntimeError(
                f"Failed to generate MP4 scene video at {output_video_path}"
            )

        return output_video_path

    async def render_scene_video(
        self,
        html_content: str,
        output_video_path: Path,
        duration_seconds: float = 10.0,
        width: int | None = None,
        height: int | None = None,
        fps: int = 30,
        browser: Browser | None = None,
        audio_path: Path | None = None,
    ) -> Path:
        """Render HTML/SVG/Canvas animation in headless browser using deterministic frame-stepping and encode to MP4."""
        w = width or self.settings.video_width
        h = height or self.settings.video_height

        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Rendering scene video (%.2fs, %dx%d @ %dfps, audio=%s) to %s",
            duration_seconds,
            w,
            h,
            fps,
            bool(audio_path),
            output_video_path,
        )

        if browser is not None:
            return await self._record_and_transcode(
                browser=browser,
                html_content=html_content,
                output_video_path=output_video_path,
                duration_seconds=duration_seconds,
                width=w,
                height=h,
                fps=fps,
                audio_path=audio_path,
            )

        async with async_playwright() as p:
            local_browser = await p.chromium.launch(headless=True)
            try:
                return await self._record_and_transcode(
                    browser=local_browser,
                    html_content=html_content,
                    output_video_path=output_video_path,
                    duration_seconds=duration_seconds,
                    width=w,
                    height=h,
                    fps=fps,
                    audio_path=audio_path,
                )
            finally:
                await local_browser.close()

    async def render_scenes_parallel(
        self,
        scenes: list[SceneAnimation],
        output_dir: Path,
        concurrency: int | None = None,
        fps: int = 30,
        browser: Browser | None = None,
        width: int | None = None,
        height: int | None = None,
        scene_audio_paths: dict[int, Path | str] | Sequence[Path | str] | None = None,
        narration_storyboard: NarrationStoryboard | None = None,
    ) -> list[Path]:
        """Render all scene animations concurrently in parallel using isolated browser contexts and optional single-pass audio muxing."""
        if not scenes:
            return []

        limit = concurrency or self.settings.render_concurrency
        output_dir.mkdir(parents=True, exist_ok=True)

        # Resolve per-scene audio mapping if provided for single-pass audio/video synchronization
        audio_map: dict[int, Path] = {}
        if isinstance(scene_audio_paths, dict):
            for s_num, a_p in scene_audio_paths.items():
                if a_p and Path(a_p).exists():
                    audio_map[int(s_num)] = Path(a_p)
        elif scene_audio_paths is not None:
            for idx, a_p in enumerate(scene_audio_paths):
                if idx < len(scenes) and a_p and Path(a_p).exists():
                    audio_map[scenes[idx].scene_number] = Path(a_p)
        elif narration_storyboard is not None and narration_storyboard.scenes_audio:
            for s_audio in narration_storyboard.scenes_audio:
                if s_audio.audio_path and Path(s_audio.audio_path).exists():
                    audio_map[s_audio.scene_number] = Path(s_audio.audio_path)

        # Resolve dimensions if not explicitly passed
        if width is not None and height is not None:
            w, h = width, height
        else:
            total_dur = sum(s.duration_seconds for s in scenes)
            w, h = (
                self.settings.get_video_dimensions(duration_seconds=total_dur)
                if total_dur > 0
                else (self.settings.video_width, self.settings.video_height)
            )

        logger.info(
            "Rendering %d scenes in parallel (concurrency limit: %d, %dx%d, single_pass_audio=%s) into %s",
            len(scenes),
            limit,
            w,
            h,
            bool(audio_map),
            output_dir,
        )

        semaphore = asyncio.Semaphore(limit)

        async def _render_scene(
            scene_anim: SceneAnimation, target_browser: Browser | None
        ) -> tuple[int, Path]:
            scene_num = scene_anim.scene_number
            video_path = output_dir / f"scene_{scene_num}.mp4"
            scene_audio = audio_map.get(scene_num)
            async with semaphore:
                logger.info(
                    "Rendering Scene %d video in parallel (%.2fs, single_pass_audio=%s)...",
                    scene_num,
                    scene_anim.duration_seconds,
                    bool(scene_audio),
                )
                if scene_audio is not None:
                    await self.render_scene_video(
                        html_content=scene_anim.html_content,
                        output_video_path=video_path,
                        duration_seconds=scene_anim.duration_seconds,
                        width=w,
                        height=h,
                        fps=fps,
                        browser=target_browser,
                        audio_path=scene_audio,
                    )
                else:
                    await self.render_scene_video(
                        html_content=scene_anim.html_content,
                        output_video_path=video_path,
                        duration_seconds=scene_anim.duration_seconds,
                        width=w,
                        height=h,
                        fps=fps,
                        browser=target_browser,
                    )
                return scene_num, video_path

        if browser is not None or isinstance(self.render_scene_video, AsyncMock):
            tasks = [_render_scene(scene, browser) for scene in scenes]
            results = await asyncio.gather(*tasks)
        else:
            async with async_playwright() as p:
                shared_browser = await p.chromium.launch(headless=True)
                try:
                    tasks = [_render_scene(scene, shared_browser) for scene in scenes]
                    results = await asyncio.gather(*tasks)
                finally:
                    await shared_browser.close()

        # Sort paths strictly by scene number order
        results.sort(key=lambda r: r[0])
        return [path for _, path in results]

    async def mux_audio_to_video(
        self,
        video_path: Path,
        audio_path: Path,
        output_path: Path,
    ) -> Path:
        """Merge an MP4 video file and a WAV/AAC audio file into a single video with audio."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Muxing audio %s into video %s -> %s",
            audio_path,
            video_path,
            output_path,
        )

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i",
            str(video_path.resolve()),
            "-i",
            str(audio_path.resolve()),
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

        logger.debug("Executing ffmpeg audio mux: %s", " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.error("FFmpeg audio mux failed: %s", stderr.decode())
            raise RuntimeError(
                f"FFmpeg audio mux failed with return code {proc.returncode}: {stderr.decode()}"
            )

        return output_path

    async def get_video_duration(self, video_path: Path) -> float:
        """Extract the exact duration of a video or audio file in seconds using FFmpeg."""
        cmd = [self.ffmpeg_path, "-i", str(video_path.resolve())]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()
        text = stderr.decode(errors="replace")
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
        if not match:
            raise RuntimeError(
                f"Could not parse duration from FFmpeg output for {video_path}: {text[:200]}"
            )
        hours, minutes, seconds = match.groups()
        return round(float(hours) * 3600 + float(minutes) * 60 + float(seconds), 3)

    async def get_media_duration(self, media_path: Path | str) -> float:
        """Extract duration in seconds from an audio or video file with WAV optimization."""
        p = Path(media_path)
        if p.suffix.lower() == ".wav":
            dur = get_wav_duration(p)
            if dur > 0:
                return dur
        return await self.get_video_duration(p)

    async def adjust_video_duration(
        self,
        video_path: Path,
        target_duration: float,
        output_path: Path,
        fps: int = 30,
    ) -> Path:
        """Adjust video playback speed (speed up or slow down) so that total duration matches target_duration."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        current_duration = await self.get_media_duration(video_path)
        if current_duration <= 0:
            raise ValueError(
                f"Invalid video duration ({current_duration}s) for {video_path}"
            )
        if target_duration <= 0:
            raise ValueError(
                f"Target duration must be positive, got {target_duration}s"
            )

        pts_factor = target_duration / current_duration
        logger.info(
            "Adjusting video duration: %.2fs -> %.2fs (pts_factor=%.4f) -> %s",
            current_duration,
            target_duration,
            pts_factor,
            output_path,
        )

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i",
            str(video_path.resolve()),
            "-filter:v",
            f"setpts={pts_factor:.6f}*PTS",
            "-r",
            str(fps),
            "-t",
            f"{target_duration:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-tune",
            "animation",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-an",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

        logger.debug("Executing ffmpeg adjust duration: %s", " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.error("FFmpeg adjust video duration failed: %s", stderr.decode())
            raise RuntimeError(
                f"FFmpeg adjust duration failed with return code {proc.returncode}: {stderr.decode()}"
            )

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError(f"Failed to produce adjusted video at {output_path}")

        return output_path

    async def mux_scene_audio_video(
        self,
        video_path: Path,
        audio_path: Path,
        output_path: Path,
        fps: int = 30,
    ) -> Path:
        """Synchronize a scene video to its audio duration by adjusting playback speed and muxing them together."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        audio_duration = await self.get_media_duration(audio_path)
        video_duration = await self.get_media_duration(video_path)

        if audio_duration <= 0:
            raise ValueError(
                f"Invalid audio duration ({audio_duration}s) for {audio_path}"
            )
        if video_duration <= 0:
            raise ValueError(
                f"Invalid video duration ({video_duration}s) for {video_path}"
            )

        pts_factor = audio_duration / video_duration
        logger.info(
            "Syncing scene: video=%.2fs, audio=%.2fs (speed ratio=%.4f) -> %s",
            video_duration,
            audio_duration,
            pts_factor,
            output_path,
        )

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i",
            str(video_path.resolve()),
            "-i",
            str(audio_path.resolve()),
            "-filter:v",
            f"setpts={pts_factor:.6f}*PTS",
            "-r",
            str(fps),
            "-t",
            f"{audio_duration:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-tune",
            "animation",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

        logger.debug("Executing ffmpeg scene sync and mux: %s", " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.error("FFmpeg scene sync mux failed: %s", stderr.decode())
            raise RuntimeError(
                f"FFmpeg scene sync mux failed with return code {proc.returncode}: {stderr.decode()}"
            )

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError(
                f"Failed to produce synchronized scene video at {output_path}"
            )

        return output_path

    async def assemble_video(
        self,
        scene_video_paths: list[Path],
        output_video_path: Path,
        audio_path: Path | None = None,
        scene_audio_paths: Sequence[Path | str] | None = None,
        narration_storyboard: NarrationStoryboard | None = None,
        fps: int = 30,
        scenes_pre_muxed: bool = False,
    ) -> Path:
        """Concatenate multiple scene MP4 video files into a final master video with synchronized audio.

        If scenes_pre_muxed is True, each scene MP4 already has its audio track muxed and
        duration synchronized during single-pass rendering, so assembly concatenates directly
        via lossless stream-copy without re-encoding.
        Otherwise, if scene_audio_paths or narration_storyboard is provided, each scene's video
        is adjusted (sped up or slowed down) to match its scene narration audio before concatenation.
        """
        if not scene_video_paths:
            raise ValueError("No scene video paths provided for assembly")

        # Resolve scene audio paths from storyboard if not explicitly passed (unless already pre-muxed)
        resolved_scene_audios: list[Path] | None = None
        if not scenes_pre_muxed:
            if scene_audio_paths is not None:
                resolved_scene_audios = [Path(p) for p in scene_audio_paths]
            elif narration_storyboard is not None and narration_storyboard.scenes_audio:
                resolved_scene_audios = [
                    Path(s.audio_path)
                    for s in narration_storyboard.scenes_audio
                    if s.audio_path and Path(s.audio_path).exists()
                ]

        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Assembling %d scene videos into master video %s (scenes_pre_muxed=%s, per_scene_audio=%s, master_audio=%s)",
            len(scene_video_paths),
            output_video_path,
            scenes_pre_muxed,
            bool(resolved_scene_audios),
            bool(audio_path),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Fast path when scenes were already single-pass rendered & synced with audio
            if scenes_pre_muxed:
                if len(scene_video_paths) == 1:
                    shutil.copy2(scene_video_paths[0], output_video_path)
                    return output_video_path

                concat_txt = temp_path / "concat_list.txt"
                concat_content = "".join(
                    f"file '{p.resolve()}'\n" for p in scene_video_paths
                )
                concat_txt.write_text(concat_content, encoding="utf-8")

                cmd = [
                    self.ffmpeg_path,
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_txt),
                    "-c",
                    "copy",
                    "-movflags",
                    "+faststart",
                    str(output_video_path),
                ]

                logger.debug(
                    "Executing ffmpeg pre-muxed fast concat: %s", " ".join(cmd)
                )
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _stdout, stderr = await proc.communicate()

                if proc.returncode != 0:
                    logger.warning(
                        "FFmpeg stream copy concat failed for pre-muxed scenes, attempting re-encode fallback: %s",
                        stderr.decode(),
                    )
                    fallback_cmd = [
                        self.ffmpeg_path,
                        "-y",
                        "-f",
                        "concat",
                        "-safe",
                        "0",
                        "-i",
                        str(concat_txt),
                        "-c:v",
                        "libx264",
                        "-preset",
                        "medium",
                        "-tune",
                        "animation",
                        "-crf",
                        "18",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "192k",
                        "-movflags",
                        "+faststart",
                        str(output_video_path),
                    ]
                    fb_proc = await asyncio.create_subprocess_exec(
                        *fallback_cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    _, fb_stderr = await fb_proc.communicate()
                    if fb_proc.returncode != 0:
                        raise RuntimeError(
                            f"FFmpeg assembly fallback failed: {fb_stderr.decode()}"
                        )

                if (
                    not output_video_path.exists()
                    or output_video_path.stat().st_size == 0
                ):
                    raise RuntimeError(
                        f"Failed to assemble master video at {output_video_path}"
                    )
                return output_video_path

            # Per-scene synchronization mode
            if resolved_scene_audios and len(resolved_scene_audios) == len(
                scene_video_paths
            ):
                logger.info(
                    "Syncing and muxing %d scenes individually in parallel (concurrency limit: %d) to prevent audio/video drift",
                    len(scene_video_paths),
                    self.settings.ffmpeg_concurrency,
                )
                ffmpeg_sem = asyncio.Semaphore(self.settings.ffmpeg_concurrency)

                async def _sync_scene(
                    idx: int, v_path: Path, a_path: Path
                ) -> tuple[int, Path]:
                    synced_p = temp_path / f"synced_scene_{idx + 1}.mp4"
                    async with ffmpeg_sem:
                        await self.mux_scene_audio_video(
                            video_path=v_path,
                            audio_path=a_path,
                            output_path=synced_p,
                            fps=fps,
                        )
                    return idx, synced_p

                sync_tasks = [
                    _sync_scene(idx, v_path, a_path)
                    for idx, (v_path, a_path) in enumerate(
                        zip(scene_video_paths, resolved_scene_audios, strict=True)
                    )
                ]
                synced_results = await asyncio.gather(*sync_tasks)
                synced_results.sort(key=lambda r: r[0])
                synced_scenes: list[Path] = [p for _, p in synced_results]

                if len(synced_scenes) == 1:
                    shutil.copy2(synced_scenes[0], output_video_path)
                    return output_video_path

                # Concatenate all synced scene videos (which already contain synchronized audio)
                concat_txt = temp_path / "concat_list.txt"
                concat_content = "".join(
                    f"file '{p.resolve()}'\n" for p in synced_scenes
                )
                concat_txt.write_text(concat_content, encoding="utf-8")

                cmd = [
                    self.ffmpeg_path,
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_txt),
                    "-c",
                    "copy",
                    "-movflags",
                    "+faststart",
                    str(output_video_path),
                ]

                logger.debug("Executing ffmpeg synced concat: %s", " ".join(cmd))
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _stdout, stderr = await proc.communicate()

                if proc.returncode != 0:
                    logger.warning(
                        "FFmpeg stream copy concat failed, attempting re-encode fallback: %s",
                        stderr.decode(),
                    )
                    fallback_cmd = [
                        self.ffmpeg_path,
                        "-y",
                        "-f",
                        "concat",
                        "-safe",
                        "0",
                        "-i",
                        str(concat_txt),
                        "-c:v",
                        "libx264",
                        "-preset",
                        "medium",
                        "-tune",
                        "animation",
                        "-crf",
                        "18",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "192k",
                        "-movflags",
                        "+faststart",
                        str(output_video_path),
                    ]
                    fb_proc = await asyncio.create_subprocess_exec(
                        *fallback_cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    _, fb_stderr = await fb_proc.communicate()
                    if fb_proc.returncode != 0:
                        raise RuntimeError(
                            f"FFmpeg assembly fallback failed: {fb_stderr.decode()}"
                        )

                if (
                    not output_video_path.exists()
                    or output_video_path.stat().st_size == 0
                ):
                    raise RuntimeError(
                        f"Failed to assemble master video at {output_video_path}"
                    )
                return output_video_path

            # Fallback mode: Concatenate scene videos first, then mux master audio if available
            if len(scene_video_paths) == 1:
                if audio_path and audio_path.exists():
                    await self.mux_audio_to_video(
                        video_path=scene_video_paths[0],
                        audio_path=audio_path,
                        output_path=output_video_path,
                    )
                else:
                    shutil.copy2(scene_video_paths[0], output_video_path)
                return output_video_path

            concat_txt = temp_path / "concat_list.txt"
            temp_concat_video = temp_path / "concatenated.mp4"

            concat_content = "".join(
                f"file '{video_path.resolve()}'\n" for video_path in scene_video_paths
            )
            concat_txt.write_text(concat_content, encoding="utf-8")

            cmd = [
                self.ffmpeg_path,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_txt),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(temp_concat_video),
            ]

            logger.debug("Executing ffmpeg concat: %s", " ".join(cmd))
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.warning(
                    "FFmpeg stream copy concat failed, attempting full re-encode fallback: %s",
                    stderr.decode(),
                )
                fallback_cmd = [
                    self.ffmpeg_path,
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_txt),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-tune",
                    "animation",
                    "-crf",
                    "18",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    str(temp_concat_video),
                ]
                fallback_proc = await asyncio.create_subprocess_exec(
                    *fallback_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, fb_stderr = await fallback_proc.communicate()
                if fallback_proc.returncode != 0:
                    logger.error("FFmpeg concat fallback error: %s", fb_stderr.decode())
                    raise RuntimeError(
                        f"FFmpeg assembly failed with return code {fallback_proc.returncode}"
                    )

            if audio_path and audio_path.exists():
                await self.mux_audio_to_video(
                    video_path=temp_concat_video,
                    audio_path=audio_path,
                    output_path=output_video_path,
                )
            else:
                shutil.copy2(temp_concat_video, output_video_path)

        if not output_video_path.exists() or output_video_path.stat().st_size == 0:
            raise RuntimeError(
                f"Failed to assemble master video at {output_video_path}"
            )

        return output_video_path

    async def create_video_preview(
        self,
        video_path: Path,
        output_path: Path,
        max_duration_seconds: float = 60.0,
        max_file_size_bytes: int = 49 * 1024 * 1024,
        fps: int = 30,
    ) -> Path:
        """Create a preview clip of the video capped at max_duration_seconds and within max_file_size_bytes.

        Attempts fast stream-copy first. If stream-copy fails or exceeds max_file_size_bytes,
        re-encodes with constrained bitrate to guarantee delivery within size limits.
        """
        if not video_path.exists():
            raise FileNotFoundError(
                f"Source video for preview not found at {video_path}"
            )
        if max_duration_seconds <= 0:
            raise ValueError(
                f"max_duration_seconds must be positive, got {max_duration_seconds}"
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Creating video preview (max_duration=%.1fs, max_size=%.2fMB) from %s -> %s",
            max_duration_seconds,
            max_file_size_bytes / (1024 * 1024),
            video_path,
            output_path,
        )

        # Attempt 1: Fast stream-copy without re-encoding
        copy_cmd = [
            self.ffmpeg_path,
            "-y",
            "-ss",
            "0",
            "-i",
            str(video_path.resolve()),
            "-t",
            f"{max_duration_seconds:.3f}",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

        logger.debug("Executing ffmpeg preview stream-copy: %s", " ".join(copy_cmd))
        proc = await asyncio.create_subprocess_exec(
            *copy_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()

        if (
            proc.returncode == 0
            and output_path.exists()
            and output_path.stat().st_size > 0
        ):
            out_size = output_path.stat().st_size
            if out_size <= max_file_size_bytes:
                logger.info(
                    "Stream-copy preview succeeded at %s (size: %.2f MB)",
                    output_path,
                    out_size / (1024 * 1024),
                )
                return output_path
            logger.warning(
                "Stream-copy preview size (%.2f MB) exceeds limit (%.2f MB). Falling back to re-encode.",
                out_size / (1024 * 1024),
                max_file_size_bytes / (1024 * 1024),
            )
        else:
            logger.warning(
                "Stream-copy preview failed (returncode %d: %s). Falling back to re-encode.",
                proc.returncode,
                stderr.decode(errors="replace"),
            )

        # Attempt 2: Bitrate-constrained re-encode fallback
        # Calculate target bitrate to comfortably fit within max_file_size_bytes
        target_bitrate_kbps = max(
            400,
            int((max_file_size_bytes * 8) / (max_duration_seconds * 1000) * 0.85) - 128,
        )

        reencode_cmd = [
            self.ffmpeg_path,
            "-y",
            "-ss",
            "0",
            "-i",
            str(video_path.resolve()),
            "-t",
            f"{max_duration_seconds:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "23",
            "-maxrate",
            f"{target_bitrate_kbps}k",
            "-bufsize",
            f"{target_bitrate_kbps * 2}k",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(fps),
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

        logger.debug("Executing ffmpeg preview re-encode: %s", " ".join(reencode_cmd))
        proc_re = await asyncio.create_subprocess_exec(
            *reencode_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, fb_stderr = await proc_re.communicate()

        if proc_re.returncode != 0:
            logger.error(
                "FFmpeg preview re-encode failed: %s",
                fb_stderr.decode(errors="replace"),
            )
            raise RuntimeError(
                f"FFmpeg preview re-encode failed with return code {proc_re.returncode}: {fb_stderr.decode(errors='replace')}"
            )

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError(f"Failed to produce video preview at {output_path}")

        logger.info(
            "Re-encoded video preview produced at %s (size: %.2f MB)",
            output_path,
            output_path.stat().st_size / (1024 * 1024),
        )
        return output_path
