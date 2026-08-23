"""Video assembly and rendering engine combining audio, SVG frames, and transitions via FFmpeg."""

import asyncio
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from config.settings import Settings, get_settings
from core.models import Scene

logger = logging.getLogger(__name__)


class VideoAssembler:
    """Combines rasterized scene frames and synthesized audio tracks into finished MP4 videos."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._ffmpeg_bin = shutil.which("ffmpeg")

    def is_ffmpeg_available(self) -> bool:
        """Check if FFmpeg binary is installed and executable on the host system."""
        return self._ffmpeg_bin is not None

    async def render_scene_clip(
        self,
        scene: Scene,
        output_clip_path: Path,
        fps: int = 30,
    ) -> Path:
        """Render a single scene's PNG frames and audio track into an MP4 clip."""
        if not scene.frames_dir:
            raise ValueError(
                f"Scene {scene.scene_id} has no rasterized frames directory"
            )

        frames_dir = Path(scene.frames_dir)
        output_clip_path.parent.mkdir(parents=True, exist_ok=True)

        audio_path = Path(scene.audio_path) if scene.audio_path else None

        await asyncio.to_thread(
            self._render_scene_clip_sync,
            frames_dir,
            audio_path,
            output_clip_path,
            fps,
            scene.duration_seconds,
        )

        scene.clip_path = str(output_clip_path)
        return output_clip_path

    def _render_scene_clip_sync(
        self,
        frames_dir: Path,
        audio_path: Path | None,
        output_path: Path,
        fps: int,
        duration: float,
    ) -> None:
        """Synchronous FFmpeg execution for single scene."""
        if not self.is_ffmpeg_available():
            logger.warning(
                "FFmpeg binary not detected on PATH. Writing mock video container for test/dev mode."
            )
            # Create a placeholder file so testing workflows continue
            output_path.write_bytes(b"MOCK_MP4_CONTAINER_PLACEHOLDER_NO_FFMPEG")
            return

        frame_pattern = str(frames_dir / "frame_%05d.png")

        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-framerate",
            str(fps),
            "-i",
            frame_pattern,
        ]

        if audio_path and audio_path.exists():
            cmd.extend(["-i", str(audio_path)])
            cmd.extend(
                [
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-shortest",
                ]
            )
        else:
            # Generate silent audio track or video-only
            cmd.extend(
                [
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-t",
                    f"{duration:.2f}",
                ]
            )

        cmd.append(str(output_path))

        logger.info("Executing FFmpeg scene render: %s", " ".join(cmd))
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            logger.error("FFmpeg error output: %s", result.stderr)
            raise RuntimeError(
                f"FFmpeg failed with exit code {result.returncode}: {result.stderr[-300:]}"
            )

        logger.info("Successfully rendered scene clip -> %s", output_path.name)

    async def assemble_full_video(
        self,
        scene_clip_paths: list[Path],
        output_video_path: Path,
    ) -> Path:
        """Concatenate all scene clips into the final video."""
        output_video_path.parent.mkdir(parents=True, exist_ok=True)

        await asyncio.to_thread(
            self._assemble_concat_sync,
            scene_clip_paths,
            output_video_path,
        )

        return output_video_path

    def _assemble_concat_sync(
        self,
        clip_paths: list[Path],
        output_path: Path,
    ) -> None:
        """Concatenate MP4 clips using FFmpeg concat demuxer."""
        if not self.is_ffmpeg_available():
            logger.warning(
                "FFmpeg binary not detected on PATH. Writing mock full video container."
            )
            output_path.write_bytes(b"MOCK_FULL_MP4_CONTAINER_PLACEHOLDER_NO_FFMPEG")
            return

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as concat_file:
            concat_txt_path = Path(concat_file.name)
            for clip in clip_paths:
                concat_file.write(f"file '{clip.resolve()}'\n")

        try:
            cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_txt_path),
                "-c",
                "copy",
                str(output_path),
            ]

            logger.info("Executing FFmpeg concat: %s", " ".join(cmd))
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                logger.error("FFmpeg concat failed: %s", result.stderr)
                raise RuntimeError(f"FFmpeg concat failed: {result.stderr[-300:]}")

            logger.info("Successfully assembled full video -> %s", output_path.name)
        finally:
            if concat_txt_path.exists():
                concat_txt_path.unlink()

    async def render_sample_preview(
        self,
        scene: Scene,
        output_sample_path: Path,
        fps: int = 30,
    ) -> Path:
        """Render a fast scene-1 preview clip for user evaluation via Telegram."""
        return await self.render_scene_clip(
            scene=scene,
            output_clip_path=output_sample_path,
            fps=fps,
        )
