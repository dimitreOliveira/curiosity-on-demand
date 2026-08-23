"""SVG animation and keyframe rasterization engine."""

import asyncio
import logging
import math
import re
from pathlib import Path

from PIL import Image, ImageDraw

from config.settings import Settings, get_settings
from core.models import AnimationType, AspectRatio, Scene

logger = logging.getLogger(__name__)


class SvgAnimator:
    """Renders programmatic animated SVG sequences and rasterizes them into video frames."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._has_cairo: bool | None = None

    def _check_cairo_available(self) -> bool:
        """Check if native Cairo libraries are available on the system."""
        if self._has_cairo is None:
            try:
                import cairosvg

                # Test a tiny SVG conversion
                test_svg = b'<svg width="10" height="10" xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10" fill="#000"/></svg>'
                cairosvg.svg2png(bytestring=test_svg)
                self._has_cairo = True
                logger.info("CairoSVG native rendering engine is available.")
            except (ImportError, OSError, RuntimeError, ValueError) as e:
                logger.warning(
                    "CairoSVG native library is not available (%s). Using Pillow visual rasterizer.",
                    e,
                )
                self._has_cairo = False
        return self._has_cairo

    async def render_scene_frames(
        self,
        scene: Scene,
        output_dir: Path,
        fps: int = 30,
        aspect_ratio: AspectRatio = AspectRatio.LANDSCAPE_16_9,
    ) -> list[Path]:
        """Render all animated keyframes for a single scene to PNG images."""
        scene_frames_dir = output_dir / f"scene_{scene.scene_id}_frames"
        scene_frames_dir.mkdir(parents=True, exist_ok=True)

        frames = await asyncio.to_thread(
            self._render_frames_sync,
            scene,
            scene_frames_dir,
            fps,
            aspect_ratio,
        )

        scene.frames_dir = str(scene_frames_dir)
        return frames

    def _render_frames_sync(
        self,
        scene: Scene,
        frames_dir: Path,
        fps: int,
        aspect_ratio: AspectRatio,
    ) -> list[Path]:
        """Synchronous frame generation loop."""
        total_frames = max(1, int(scene.duration_seconds * fps))
        intro_frames = min(30, int(fps * 0.8))  # 0.8s transition

        is_vertical = aspect_ratio == AspectRatio.VERTICAL_9_16
        width = (
            self.settings.short_video_width
            if is_vertical
            else self.settings.default_video_width
        )
        height = (
            self.settings.short_video_height
            if is_vertical
            else self.settings.default_video_height
        )

        anim_type = (
            scene.visual_blueprint.animation_type
            if scene.visual_blueprint
            else AnimationType.FADE_SCALE
        )

        frame_paths: list[Path] = []
        cairo_ready = self._check_cairo_available()

        # Extract numeric values if this is a data counter animation
        target_number = None
        if anim_type == AnimationType.DATA_COUNTER:
            nums = re.findall(r"\d+", scene.narration)
            if nums:
                target_number = int(nums[0])

        for frame_idx in range(total_frames):
            progress = min(1.0, frame_idx / intro_frames) if intro_frames > 0 else 1.0
            # Smooth ease-out cubic
            ease_out = 1.0 - math.pow(1.0 - progress, 3)

            # Continuous subtle breathing / pulse for the remainder of scene
            time_sec = frame_idx / fps
            pulse = math.sin(time_sec * 2.0) * 0.02  # +- 2% scale pulse

            current_scale = (0.88 + 0.12 * ease_out) + (pulse if progress >= 1.0 else 0)
            current_opacity = ease_out

            frame_filename = frames_dir / f"frame_{frame_idx:05d}.png"

            if cairo_ready and scene.svg_source:
                # Modify SVG parameters dynamically
                animated_svg = self._interpolate_svg(
                    svg_markup=scene.svg_source,
                    scale=current_scale,
                    opacity=current_opacity,
                    target_number=target_number,
                    progress=ease_out,
                    width=width,
                    height=height,
                )
                self._rasterize_cairo(animated_svg, frame_filename, width, height)
            else:
                # High-fidelity Pillow direct canvas rendering
                self._render_pillow_frame(
                    scene=scene,
                    output_path=frame_filename,
                    scale=current_scale,
                    opacity=current_opacity,
                    width=width,
                    height=height,
                    frame_idx=frame_idx,
                    total_frames=total_frames,
                    target_number=target_number,
                    progress=ease_out,
                )

            frame_paths.append(frame_filename)

        logger.info(
            "Rendered %d frames for scene %d at %dx%d (%s) -> %s",
            len(frame_paths),
            scene.scene_id,
            width,
            height,
            aspect_ratio.value,
            frames_dir.name,
        )
        return frame_paths

    def _interpolate_svg(
        self,
        svg_markup: str,
        scale: float,
        opacity: float,
        target_number: int | None,
        progress: float,
        width: int,
        height: int,
    ) -> str:
        """Inject transformation and opacity styling into raw SVG markup."""
        # Ensure viewBox
        if 'viewBox="' not in svg_markup:
            svg_markup = svg_markup.replace(
                "<svg", f'<svg viewBox="0 0 {width} {height}"', 1
            )

        # Update counter numbers if applicable
        if target_number is not None:
            current_val = int(target_number * progress)
            svg_markup = re.sub(rf"\b{target_number}\b", str(current_val), svg_markup)

        # Wrap inner contents with animated transform group
        cx = width / 2
        cy = height / 2
        transform = f'transform="translate({cx}, {cy}) scale({scale:.4f}) translate(-{cx}, -{cy})" opacity="{opacity:.3f}"'

        # Insert transform group inside root <svg>
        svg_markup = re.sub(r"(<svg[^>]*>)", rf"\1<g {transform}>", svg_markup, count=1)
        svg_markup = svg_markup.replace("</svg>", "</g></svg>")

        return svg_markup

    def _rasterize_cairo(
        self, svg_text: str, output_path: Path, width: int, height: int
    ) -> None:
        """Rasterize SVG XML using CairoSVG."""
        import cairosvg

        cairosvg.svg2png(
            bytestring=svg_text.encode("utf-8"),
            write_to=str(output_path),
            output_width=width,
            output_height=height,
        )

    def _render_pillow_frame(
        self,
        scene: Scene,
        output_path: Path,
        scale: float,
        opacity: float,
        width: int,
        height: int,
        frame_idx: int,
        total_frames: int,
        target_number: int | None,
        progress: float,
    ) -> None:
        """Render high-contrast, modern graphic frame directly with Pillow."""
        # Create dark gradient background image
        bg = Image.new("RGBA", (width, height), (15, 23, 42, 255))
        draw = ImageDraw.Draw(bg)

        # Decorative background grid dots
        grid_step = 60
        for gx in range(0, width, grid_step):
            for gy in range(0, height, grid_step):
                draw.rectangle([gx, gy, gx + 2, gy + 2], fill=(30, 41, 59, 200))

        # Visual blueprint details
        bp = scene.visual_blueprint
        primary_text = bp.primary_text if bp else f"Scene {scene.scene_id}"
        accent_hex = bp.accent_color if bp else "#38bdf8"
        accent_rgb = self._hex_to_rgb(accent_hex)

        # Draw central card with transform scale
        card_w = int(width * 0.75 * scale)
        card_h = int(height * 0.55 * scale)
        cx = width // 2
        cy = height // 2

        x0 = cx - (card_w // 2)
        y0 = cy - (card_h // 2)
        x1 = cx + (card_w // 2)
        y1 = cy + (card_h // 2)

        alpha = int(255 * opacity)
        card_bg = (30, 41, 59, alpha)
        border_color = (
            accent_rgb[0],
            accent_rgb[1],
            accent_rgb[2],
            int(180 * opacity),
        )

        # Card body and accent outline
        draw.rounded_rectangle(
            [x0, y0, x1, y1], radius=24, fill=card_bg, outline=border_color, width=3
        )

        # Scene badge
        badge_text = f"CURIOSITY ON DEMAND • SCENE {scene.scene_id:02d}"
        draw.text(
            (cx, y0 + 40),
            badge_text,
            fill=(148, 163, 184, alpha),
            anchor="mm",
        )

        # Main text / Counter display
        display_text = primary_text
        if target_number is not None:
            current_val = int(target_number * progress)
            display_text = f"{primary_text}: {current_val:,}"

        draw.text(
            (cx, cy - 20),
            display_text,
            fill=(255, 255, 255, alpha),
            anchor="mm",
        )

        # Narration subtitle snippet at bottom of card
        words = scene.narration.split()
        snippet = " ".join(words[:12]) + ("..." if len(words) > 12 else "")
        draw.text(
            (cx, y1 - 50),
            snippet,
            fill=(203, 213, 225, int(220 * opacity)),
            anchor="mm",
        )

        # Progress bar at bottom of the frame
        bar_progress = frame_idx / max(1, total_frames - 1)
        bar_w = int(width * bar_progress)
        draw.rectangle(
            [0, height - 6, bar_w, height],
            fill=(accent_rgb[0], accent_rgb[1], accent_rgb[2], 255),
        )

        # Save to PNG
        bg.convert("RGB").save(output_path, "PNG", optimize=True)

    @staticmethod
    def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
        """Convert '#rrggbb' to (r, g, b) tuple."""
        clean = hex_color.lstrip("#")
        if len(clean) == 6:
            r = int(clean[0:2], 16)
            g = int(clean[2:4], 16)
            b = int(clean[4:6], 16)
            return (r, g, b)
        return (56, 189, 248)  # Default cyan
