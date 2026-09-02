"""Animation renderer and video assembly service utilizing Playwright and FFmpeg."""

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path

import imageio_ffmpeg
from playwright.async_api import async_playwright

from config.settings import Settings, get_settings
from core.models import SceneAnimation

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

    async def render_scene_video(
        self,
        html_content: str,
        output_video_path: Path,
        duration_seconds: int = 10,
        width: int | None = None,
        height: int | None = None,
        fps: int = 30,
    ) -> Path:
        """Render real-time HTML/SVG/Canvas animation in headless browser and encode to MP4."""
        w = width or self.settings.video_width
        h = height or self.settings.video_height

        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Rendering scene video (%ds, %dx%d @ %dfps) to %s",
            duration_seconds,
            w,
            h,
            fps,
            output_video_path,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            rec_dir = temp_path / "recordings"
            rec_dir.mkdir(parents=True, exist_ok=True)

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                try:
                    context = await browser.new_context(
                        viewport={"width": w, "height": h},
                        record_video_dir=str(rec_dir),
                        record_video_size={"width": w, "height": h},
                    )
                    page = await context.new_page()
                    await page.set_content(html_content, wait_until="domcontentloaded")
                    # Let animation play for the target duration
                    await asyncio.sleep(duration_seconds)
                    await page.close()
                    await context.close()
                finally:
                    await browser.close()

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

    async def render_scenes_parallel(
        self,
        scenes: list[SceneAnimation],
        output_dir: Path,
        concurrency: int = 3,
        fps: int = 30,
    ) -> list[Path]:
        """Render all scene animations concurrently in parallel using isolated browser recording sessions."""
        if not scenes:
            return []

        output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Rendering %d scenes in parallel (concurrency limit: %d) into %s",
            len(scenes),
            concurrency,
            output_dir,
        )

        semaphore = asyncio.Semaphore(concurrency)

        async def _render_scene(scene_anim: SceneAnimation) -> tuple[int, Path]:
            scene_num = scene_anim.scene_number
            video_path = output_dir / f"scene_{scene_num}.mp4"
            async with semaphore:
                logger.info(
                    "Rendering Scene %d video in parallel (%ds)...",
                    scene_num,
                    scene_anim.duration_seconds,
                )
                await self.render_scene_video(
                    html_content=scene_anim.html_content,
                    output_video_path=video_path,
                    duration_seconds=scene_anim.duration_seconds,
                    fps=fps,
                )
                return scene_num, video_path

        tasks = [_render_scene(scene) for scene in scenes]
        results = await asyncio.gather(*tasks)

        # Sort paths strictly by scene number order
        results.sort(key=lambda r: r[0])
        return [path for _, path in results]

    async def assemble_video(
        self,
        scene_video_paths: list[Path],
        output_video_path: Path,
    ) -> Path:
        """Concatenate multiple scene MP4 video files into a final master video."""
        if not scene_video_paths:
            raise ValueError("No scene video paths provided for assembly")

        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Assembling %d scene videos into master video %s",
            len(scene_video_paths),
            output_video_path,
        )

        if len(scene_video_paths) == 1:
            shutil.copy2(scene_video_paths[0], output_video_path)
            return output_video_path

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            concat_txt = temp_path / "concat_list.txt"

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
                str(output_video_path),
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
                # Fallback to re-encoding concat if codecs differ slightly
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
                    str(output_video_path),
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

        if not output_video_path.exists() or output_video_path.stat().st_size == 0:
            raise RuntimeError(
                f"Failed to assemble master video at {output_video_path}"
            )

        return output_video_path
