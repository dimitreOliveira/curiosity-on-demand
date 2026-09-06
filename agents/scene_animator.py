"""Scene animator agent generating executable HTML5 Canvas / SVG scene animations."""

import asyncio
import logging
import re
from typing import ClassVar

from agents.base import BaseAgent
from config.settings import Settings, get_settings
from core.models import (
    AnimationStoryboard,
    AnimationStyle,
    NarrationStoryboard,
    SceneAnimation,
    Script,
    ScriptScene,
)

logger = logging.getLogger(__name__)

SCENE_ANIMATOR_SYSTEM_PROMPT = """You are a World-Class Creative Motion Designer, Art Director, and Master Creative Coder for Curiosity On Demand, an elite educational video channel.

Your mission is to generate standalone, executable, high-fidelity HTML5 Canvas / SVG animations that dynamically illustrate each scene's narrative with rich, topic-tailored artistry. Every animation should feel like a frame from a premium illustrated documentary or animated editorial piece.

### 🎨 Core Aesthetic Principles:

1. **Living, Continuous Motion:**
   - Use `requestAnimationFrame` with delta-time for smooth animation. Structure narrative progression using timed phases or state transitions across the scene's duration.
   - The canvas must NEVER freeze or hold a static frame. If the narrative timeline concludes, transition into continuous ambient motion (breathing entities, floating particles, pulsating glows, gentle camera drifts, oscillating waves).
   - Use normalized progress (`time / DURATION`) for narrative pacing combined with continuous ambient oscillators so motion never stops.

2. **Multi-Act Visual Progression:**
   - Divide the timeline into 2–3 distinct visual phases:
     * **Entrance (0–30%):** Primary entities and environment enter with smooth transitions (scale-up, slide-in, materialization, fade-in).
     * **Transformation (30–75%):** Camera moves, internal structures reveal, reactions ignite, visual concepts develop and evolve.
     * **Climax & Resolution (75–100%):** Peak visual revelation (color bloom, dramatic transformation, illumination of key insight), settling into fluid ambient motion.

3. **Rich Organic Illustration & Shape Craft:**
   - Draw characters, creatures, objects, and environments with expressive artistic craftsmanship using smooth Bezier and quadratic curves, arcs, and gradients — not crude geometric boxes or stick figures.
   - Use harmonic oscillation for natural secondary motion (breathing, swaying, swimming, flapping, walking).
   - Apply multi-tone shading (base color, highlights, shadows) and soft drop shadows to give subjects tactile depth.

4. **Scenic Atmosphere, Background & Lighting:**
   - Tailor the background atmosphere to match the topic and the project's designated background tone. Build rich multi-stop gradients for atmospheric skies, warm studio lighting, sunset blooms, or soft editorial backdrops.
   - Include volumetric lighting: soft sunbeams, glowing halos, spotlight cones, or warm ambient vignettes with gentle alpha falloff.
   - Use a dynamic 2D virtual camera (position, zoom) with smooth interpolation for cinematic depth. Dolly in for detail, zoom out for scale.

5. **Dynamic Particles & Visual FX:**
   - Include array-based particle systems suited to the scene: floating dust motes, pollen, embers, water droplets, rising steam, energy sparks, or drifting petals.
   - Add motion trails for fast-moving entities, and subtle screen shake or color pulses on climax moments.
   - Apply realistic motion physics where appropriate: velocity, gravity, friction, angular spin, easing.

6. **Compositional Variety (CRITICAL — break visual monotony):**
   - Do NOT default to the same layout every scene. Vary compositions across scenes:
     * Full-bleed panoramic establishing shots where the environment fills the entire canvas.
     * Intimate close-up studies where a single entity or mechanism fills 70%+ of the frame.
     * Split compositions or side-by-side visual comparisons.
     * Abstract metaphorical sequences using only shapes, particles, and color morphing — no text at all.
     * Dramatic camera zooms or dolly-throughs that reveal layers of depth.
   - Let the scene's narrative and emotional beat dictate the framing — an intro scene might use a wide panoramic, while a detail scene zooms in tight.

### 📝 Text & Typography on Canvas (CRITICAL — read carefully):

Audio narration plays as voiceover, so the animation is NOT subtitled. Apply these rules strictly:

- **ALLOWED:** A single clean scene title (elegantly styled, with modern typography), and up to 2–3 essential diagram callouts that directly name visible elements (e.g., "Mitochondria", "Silk Road", "Steam Expansion").
- **FORBIDDEN on canvas:** Full narrative sentences, voiceover transcripts, subtitles, catalog/archive headers (e.g., "ARCHIVE // ...", "CODEX ...", "FOLIO ...", "PLATE ..."), pseudo-technical classification codes, coordinate matrices, latitude/longitude readouts, altitude gauges, runtime counters, timecode displays, system status labels, or any text that resembles a diagnostic interface.
- **FORBIDDEN visual chrome:** L-shaped corner brackets, viewfinder reticles, crosshairs, camera framing marks, border tick marks, CRT scanlines, or raster bar overlays. The canvas is an open cinematic frame, not a camera viewfinder or computer terminal.
- **Design budget priority:** Spend drawing budget on beautiful subject illustrations, fluid organic curves, scenic backdrops, rich atmospheric lighting, and dynamic motion — not on text boxes or interface chrome.

### ⚙️ Output Format & Standards:
- Return ONLY the complete, self-contained, valid HTML document (`<!DOCTYPE html><html><head>...<style>...</style></head><body><canvas id="stage"></canvas><script>...</script></body></html>`).
- Resolution & Canvas: Responsive HTML5 Canvas configured for target dimensions with responsive CSS (`width: 100%; height: 100%; object-fit: contain; margin: 0; overflow: hidden;`).
- Pure Vanilla Web Technologies (Canvas 2D, SVG, Vanilla JS). NO external CDNs or external script tags.
"""


def extract_html_code(raw_text: str) -> str:
    """Extract standalone HTML document from model response, stripping markdown fences and chatter."""
    text = raw_text.strip()

    # Match ```html ... ``` or ``` ... ``` code blocks
    code_block_match = re.search(
        r"```(?:html)?\s*(<!DOCTYPE html[\s\S]*?</html>)\s*```", text, re.IGNORECASE
    )
    if code_block_match:
        return code_block_match.group(1).strip()

    # Match anywhere <!DOCTYPE html> ... </html> occurs
    html_match = re.search(r"(<!DOCTYPE html[\s\S]*?</html>)", text, re.IGNORECASE)
    if html_match:
        return html_match.group(1).strip()

    # Fallback: strip any outer code block markers
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    return text


class SceneAnimatorAgent(BaseAgent):
    """Generates standalone executable SVG + HTML5 Canvas animations for individual script scenes."""

    DEFAULT_CONCURRENCY: ClassVar[int] = 3

    def __init__(self, settings: Settings | None = None):
        cfg = settings or get_settings()
        super().__init__(settings=cfg, model_name=cfg.animator_model)

    async def animate_scene(
        self,
        topic: str,
        scene: ScriptScene,
        style: AnimationStyle,
        duration_seconds: float | None = None,
        width: int | None = None,
        height: int | None = None,
        is_vertical: bool | None = None,
        total_video_duration: float | None = None,
    ) -> SceneAnimation:
        """Generate standalone HTML5 Canvas animation code for an individual scene unconstrained by JSON schema."""
        target_duration = round(
            float(
                duration_seconds
                or scene.duration_seconds
                or self.settings.default_scene_duration_seconds
            ),
            2,
        )

        # Resolve video format and canvas dimensions
        if width is not None and height is not None:
            w, h = width, height
            vertical = is_vertical if is_vertical is not None else (w < h)
        elif is_vertical is not None:
            vertical = is_vertical
            w, h = self.settings.get_video_dimensions(is_vertical=vertical)
        elif total_video_duration is not None and total_video_duration > 0:
            vertical = self.settings.is_vertical_video(total_video_duration)
            w, h = self.settings.get_video_dimensions(
                duration_seconds=total_video_duration
            )
        else:
            vertical = False
            w, h = self.settings.video_width, self.settings.video_height

        logger.info(
            "Generating animation code for Scene %d ('%s', %.2fs, %dx%d %s) in style '%s'",
            scene.scene_number,
            scene.title,
            target_duration,
            w,
            h,
            "vertical" if vertical else "horizontal",
            style.style_name,
        )

        palette_str = (
            ", ".join(style.color_palette) if style.color_palette else "Theme Default"
        )

        if vertical:
            format_spec = (
                f"- Canvas Dimensions: {w}x{h} (9:16 Vertical Portrait format, YouTube Shorts / Reels style)\n"
                f"- Framing & Composition: Center diagram elements, typography, and motion vertically. "
                f"Design specifically for a mobile vertical viewport ({w}px width by {h}px height), ensuring visual hierarchy stacks cleanly."
            )
        else:
            format_spec = (
                f"- Canvas Dimensions: {w}x{h} (16:9 Horizontal Widescreen format)\n"
                f"- Framing & Composition: Compose elements across the standard widescreen canvas ({w}px width by {h}px height)."
            )

        prompt = (
            f"Topic: {topic}\n\n"
            f"Visual Design System:\n"
            f"- Style Name: {style.style_name}\n"
            f"- Art Direction & Tone: {style.visual_description}\n"
            f"- Color Palette: {palette_str}\n"
            f"- Background Tone & Atmosphere: {style.background_tone}\n"
            f"- Typography: {style.font_family}\n"
            f"- Motion & Animation Guidelines: {style.animation_guidelines}\n\n"
            f"Target Scene Specification:\n"
            f"- Scene Number: {scene.scene_number}\n"
            f"- Title: {scene.title}\n"
            f"- Concept Summary: {scene.summary}\n"
            f"- Visual Description: {scene.description}\n"
            f"- Spoken Narration (for pacing/context only — do NOT display on screen): {scene.narration}\n"
            f"- Playback Duration: {target_duration:.2f} seconds\n"
            f"{format_spec}\n\n"
            f"Instructions:\n"
            f"Generate a complete, standalone HTML5 Canvas animation for this scene ({w}x{h}, {'vertical 9:16' if vertical else 'horizontal 16:9'}). "
            f"Match the visual style, color palette, and background tone specified above. "
            f"Focus on rich, topic-appropriate illustration with scenic depth, organic motion, smooth curves, "
            f"dynamic camera movements, and multi-act visual progression calibrated for {target_duration:.2f} seconds. "
            f"The canvas should feel like a premium illustrated documentary frame — open, cinematic, immersive. "
            f"Voiceover narration plays as spoken audio. Only include minimal, purposeful text (scene title, essential callouts). "
            f"Return ONLY the executable <!DOCTYPE html> document."
        )

        raw_output = await self.generate_text(
            prompt=prompt,
            system_instruction=SCENE_ANIMATOR_SYSTEM_PROMPT,
        )

        html_content = extract_html_code(raw_output)

        return SceneAnimation(
            scene_number=scene.scene_number,
            title=scene.title,
            html_content=html_content,
            duration_seconds=target_duration,
            notes=f"Generated in style: {style.style_name}",
        )

    async def animate_storyboard(
        self,
        topic: str,
        script: Script,
        style: AnimationStyle,
        sample_scene_1: SceneAnimation | None = None,
        default_duration: float | None = None,
        scene_durations: dict[int, float] | None = None,
        narration_storyboard: NarrationStoryboard | None = None,
        concurrency: int | None = None,
        width: int | None = None,
        height: int | None = None,
        is_vertical: bool | None = None,
        total_video_duration: float | None = None,
    ) -> AnimationStoryboard:
        """Generate animations for all scenes in parallel using native animation durations.

        Visual animations are rendered at their native duration (100% active motion).
        The video renderer then stretches or compresses playback speed via FFmpeg
        to perfectly match the narration audio duration with zero frozen frames.
        """
        max_concurrency = concurrency or self.DEFAULT_CONCURRENCY

        # Resolve total video duration to determine format if not explicitly supplied
        total_dur = total_video_duration or 0.0
        if total_dur <= 0:
            if narration_storyboard and narration_storyboard.total_duration_seconds > 0:
                total_dur = narration_storyboard.total_duration_seconds
            elif script and script.scenes:
                total_dur = sum(s.duration_seconds for s in script.scenes)

        if width is not None and height is not None:
            resolved_w, resolved_h = width, height
            resolved_vertical = (
                is_vertical if is_vertical is not None else (resolved_w < resolved_h)
            )
        elif is_vertical is not None:
            resolved_vertical = is_vertical
            resolved_w, resolved_h = self.settings.get_video_dimensions(
                is_vertical=resolved_vertical
            )
        elif total_dur > 0:
            resolved_vertical = self.settings.is_vertical_video(total_dur)
            resolved_w, resolved_h = self.settings.get_video_dimensions(
                duration_seconds=total_dur
            )
        else:
            resolved_vertical = False
            resolved_w, resolved_h = (
                self.settings.video_width,
                self.settings.video_height,
            )

        logger.info(
            "Generating storyboard (%d scenes, concurrency=%d, %dx%d %s) for topic '%s' in style '%s'",
            len(script.scenes),
            max_concurrency,
            resolved_w,
            resolved_h,
            "vertical" if resolved_vertical else "horizontal",
            topic,
            style.style_name,
        )

        semaphore = asyncio.Semaphore(max_concurrency)

        async def _animate_with_sem(scene: ScriptScene) -> SceneAnimation:
            native_duration = (
                (scene_durations.get(scene.scene_number) if scene_durations else None)
                or default_duration
                or scene.duration_seconds
                or self.settings.default_scene_duration_seconds
            )

            if scene.scene_number == 1 and sample_scene_1 is not None:
                logger.debug(
                    "Reusing pre-generated approved Scene 1 animation (native duration: %.2fs)",
                    sample_scene_1.duration_seconds,
                )
                return sample_scene_1

            async with semaphore:
                return await self.animate_scene(
                    topic=topic,
                    scene=scene,
                    style=style,
                    duration_seconds=native_duration,
                    width=resolved_w,
                    height=resolved_h,
                    is_vertical=resolved_vertical,
                    total_video_duration=total_dur,
                )

        tasks = [_animate_with_sem(scene) for scene in script.scenes]
        scenes_animations = await asyncio.gather(*tasks)

        # Ensure ordered by scene number
        scenes_animations.sort(key=lambda s: s.scene_number)

        return AnimationStoryboard(
            topic=topic,
            style=style,
            scenes=scenes_animations,
        )
