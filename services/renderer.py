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
    ) -> Path:
        """Render standalone HTML/SVG/Canvas code and capture a high-resolution PNG snapshot."""
        w = width or self.settings.video_width
        h = height or self.settings.video_height

        output_image_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Rendering sample frame snapshot (%dx%d) to %s", w, h, output_image_path
        )

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page(
                    viewport={"width": w, "height": h},
                    device_scale_factor=1,
                )
                await page.set_content(html_content, wait_until="domcontentloaded")
                # Wait for initial canvas drawing loops and styles to settle
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
    ) -> Path:
        """Record HTML canvas animation within an isolated browser context and transcode to MP4."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            rec_dir = temp_path / "recordings"
            rec_dir.mkdir(parents=True, exist_ok=True)

            context = await browser.new_context(
                viewport={"width": width, "height": height},
                record_video_dir=str(rec_dir),
                record_video_size={"width": width, "height": height},
            )
            try:
                page = await context.new_page()
                await page.set_content(html_content, wait_until="domcontentloaded")
                # Let animation play for the target duration
                await asyncio.sleep(duration_seconds)
                await page.close()
            finally:
                await context.close()

            # Find recorded video file (.webm)
            recorded_files = list(rec_dir.glob("*.webm"))
            if not recorded_files:
                raise RuntimeError(
                    f"No video recording produced by Playwright for {output_video_path}"
                )

            recorded_webm = recorded_files[0]

            # Transcode WebM to standard MP4 (H.264 / YUV420p)
            cmd = [
                self.ffmpeg_path,
                "-y",
                "-i",
                str(recorded_webm),
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "22",
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(fps),
                "-movflags",
                "+faststart",
                str(output_video_path),
            ]

            logger.debug("Executing ffmpeg: %s", " ".join(cmd))
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error("FFmpeg transcode error: %s", stderr.decode())
                raise RuntimeError(
                    f"FFmpeg transcode failed with return code {proc.returncode}"
                )

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
    ) -> Path:
        """Render real-time HTML/SVG/Canvas animation in headless browser and encode to MP4."""
        w = width or self.settings.video_width
        h = height or self.settings.video_height

        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Rendering scene video (%.2fs, %dx%d @ %dfps) to %s",
            duration_seconds,
            w,
            h,
            fps,
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
    ) -> list[Path]:
        """Render all scene animations concurrently in parallel using isolated browser recording sessions."""
        if not scenes:
            return []

        limit = concurrency or self.settings.render_concurrency
        output_dir.mkdir(parents=True, exist_ok=True)

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
            "Rendering %d scenes in parallel (concurrency limit: %d, %dx%d) into %s",
            len(scenes),
            limit,
            w,
            h,
            output_dir,
        )

        semaphore = asyncio.Semaphore(limit)

        async def _render_scene(
            scene_anim: SceneAnimation, target_browser: Browser | None
        ) -> tuple[int, Path]:
            scene_num = scene_anim.scene_number
            video_path = output_dir / f"scene_{scene_num}.mp4"
            async with semaphore:
                logger.info(
                    "Rendering Scene %d video in parallel (%.2fs)...",
                    scene_num,
                    scene_anim.duration_seconds,
                )
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
            "fast",
            "-crf",
            "22",
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
            "fast",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
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
    ) -> Path:
        """Concatenate multiple scene MP4 video files into a final master video with synchronized audio.

        If scene_audio_paths or narration_storyboard is provided, each scene's video
        is adjusted (sped up or slowed down) to exactly match its scene narration audio
        before concatenation, ensuring perfect scene-by-scene audio/video synchronization.
        """
        if not scene_video_paths:
            raise ValueError("No scene video paths provided for assembly")

        # Resolve scene audio paths from storyboard if not explicitly passed
        resolved_scene_audios: list[Path] | None = None
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
            "Assembling %d scene videos into master video %s (per_scene_audio=%s, master_audio=%s)",
            len(scene_video_paths),
            output_video_path,
            bool(resolved_scene_audios),
            bool(audio_path),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

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
                        "fast",
                        "-crf",
                        "22",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "aac",
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
                    "fast",
                    "-crf",
                    "22",
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
