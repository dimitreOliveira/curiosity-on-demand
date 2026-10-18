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
    SceneVisualDirection,
    Script,
    ScriptScene,
)

logger = logging.getLogger(__name__)

DEFAULT_COMPOSITION_ARCHETYPES: tuple[tuple[str, str], ...] = (
    (
        "Full-Bleed Panoramic Establishing Shot",
        "Slow, sweeping dolly push-in across layered atmospheric depth",
    ),
    (
        "Intimate Macro Close-Up Study",
        "Tight focus filling 75%+ of the viewport with subtle orbital drift and internal mechanism reveal",
    ),
    (
        "Dynamic Split-Screen / Side-by-Side Comparison",
        "Synchronized dual-frame contrast with smooth lateral camera balance",
    ),
    (
        "Isometric / Cross-Section Process Cutaway",
        "Clean architectural cutaway with progressive zoom across interconnected stages",
    ),
    (
        "Abstract Metaphorical & Particle Flow Sequence",
        "Fluid camera tracking following morphing geometry, field lines, and luminous particle currents",
    ),
)

SCENE_ANIMATOR_SYSTEM_PROMPT = """You are a World-Class Creative Motion Designer, Art Director, and Master Creative Coder for Curiosity On Demand, an elite educational video channel.

Your mission is to generate standalone, executable, high-fidelity HTML5 Canvas / SVG animations that dynamically illustrate each scene's narrative with rich, topic-tailored artistry. Every animation should feel like a frame from a premium illustrated documentary or animated editorial piece.

### 🎨 Core Aesthetic Principles:

1. **Living, Continuous Motion & Strict Delta-Time / Elapsed-Time Physics (CRITICAL):**
   - Use `requestAnimationFrame` with true delta-time (`dt = Math.min(0.1, (timestamp - lastTimestamp) / 1000)`) and total elapsed seconds (`elapsed = (timestamp - startTime) / 1000`).
   - **NEVER use fixed per-frame increments** like `p.x += p.vx`, `angle += 0.02`, or `pkt.t += 0.016` that assume a hardcoded 60fps tick rate! Because scenes are rendered via deterministic virtual-time stepping and time-scaled to match voiceover audio, unscaled per-frame increments cause severe speed warping.
   - Instead, ALL motion, particle velocities, wave oscillations, and physics updates MUST either be pure deterministic functions of `elapsed` (e.g., `const x = ( p.baseX + p.vx * elapsed ) % W`) or explicitly multiplied by `dt` in seconds (`p.x += p.vx * dt`, where `vx` is in pixels per second).
   - The canvas must NEVER freeze or hold a static frame. If the narrative timeline concludes, transition into continuous ambient motion (breathing entities, floating particles, pulsating glows, gentle camera drifts, oscillating waves).
   - Use normalized progress (`progress = Math.min(1.0, elapsed / DURATION)`) for narrative pacing combined with `elapsed`-driven oscillators so motion never stops.

2. **Multi-Act Visual Progression:**
   - Divide the timeline into 2–3 distinct visual phases:
     * **Entrance (0–30%):** Primary entities and environment enter with smooth transitions (scale-up, slide-in, materialization, fade-in).
     * **Transformation (30–75%):** Camera moves, internal structures reveal, reactions ignite, visual concepts develop and evolve.
     * **Climax & Resolution (75–100%):** Peak visual revelation (color bloom, dramatic transformation, illumination of key insight), settling into fluid ambient motion.

3. **Rich Organic Illustration & Shape Craft:**
   - Draw characters, creatures, objects, and environments with expressive artistic craftsmanship using smooth Bezier and quadratic curves, arcs, and gradients — not crude geometric boxes or stick figures.
   - Use harmonic oscillation (`Math.sin(elapsed * freq + phase)`) for natural secondary motion (breathing, swaying, swimming, flapping, walking).
   - Apply multi-tone shading (base color, highlights, shadows) and soft drop shadows to give subjects tactile depth.

4. **Scenic Atmosphere, Background & Lighting:**
   - Tailor the background atmosphere to match the topic and the project's designated background tone. Build rich multi-stop gradients for atmospheric skies, warm studio lighting, sunset blooms, or soft editorial backdrops.
   - Include volumetric lighting: soft sunbeams, glowing halos, spotlight cones, or warm ambient vignettes with gentle alpha falloff.
   - Use a dynamic 2D virtual camera (position, zoom) with smooth interpolation for cinematic depth. Dolly in for detail, zoom out for scale.

5. **Dynamic Particles & Visual FX:**
   - Include array-based particle systems suited to the scene: floating dust motes, pollen, embers, water droplets, rising steam, energy sparks, or drifting petals — all updated strictly using `dt` (in seconds) or `elapsed`.
   - Add motion trails for fast-moving entities, and subtle screen shake or color pulses on climax moments.
   - Apply realistic time-based motion physics where appropriate: velocity (`px/s`), gravity (`px/s²`), damping, angular velocity (`rad/s`), and smooth easing.

6. **Compositional Variety & Cross-Scene Continuity (CRITICAL — break visual monotony):**
   - Strictly follow the assigned **Scene Compositional Blueprint** (`composition_type` and `camera_movement`) provided in the prompt so adjacent scenes never repeat the same layout.
   - Honor the **Adjacent Scene Context** (Previous Scene and Next Scene) to maintain visual continuity of recurring metaphors, entities, and color motifs while making the framing of the current scene feel fresh and purposeful.

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
- **Zero Code Comments & Concise Token Efficiency (CRITICAL for generation speed):** Write ZERO JavaScript, CSS, or HTML comments (`//`, `/* */`, `<!-- -->`). Avoid verbose boilerplate, redundant helper wrappers, or unused variables. Keep the implementation compact, clean, and high-density so 100% of the output token budget goes directly toward rich visual rendering and smooth animation physics.
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


def resolve_scene_direction(
    scene: ScriptScene,
    style: AnimationStyle,
) -> SceneVisualDirection:
    """Resolve explicit or fallback compositional blueprint for a specific scene."""
    if style.scene_directions:
        for direction in style.scene_directions:
            if direction.scene_number == scene.scene_number:
                return direction

    archetype_idx = (max(1, scene.scene_number) - 1) % len(
        DEFAULT_COMPOSITION_ARCHETYPES
    )
    comp_type, cam_move = DEFAULT_COMPOSITION_ARCHETYPES[archetype_idx]
    return SceneVisualDirection(
        scene_number=scene.scene_number,
        composition_type=comp_type,
        camera_movement=cam_move,
        focal_subject=scene.title,
        transition_hook="Maintain visual motif continuity while shifting camera framing from adjacent scenes.",
    )


class SceneAnimatorAgent(BaseAgent):
    """Generates standalone executable SVG + HTML5 Canvas animations for individual script scenes."""

    DEFAULT_CONCURRENCY: ClassVar[int] = 6

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
        previous_scene: ScriptScene | None = None,
        next_scene: ScriptScene | None = None,
        scene_direction: SceneVisualDirection | None = None,
        total_scenes: int | None = None,
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

        resolved_direction = scene_direction or resolve_scene_direction(scene, style)

        logger.info(
            "Generating animation code for Scene %d ('%s', %.2fs, %dx%d %s, composition='%s') in style '%s'",
            scene.scene_number,
            scene.title,
            target_duration,
            w,
            h,
            "vertical" if vertical else "horizontal",
            resolved_direction.composition_type,
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

        # Build concise cross-scene continuity context without duplicating full adjacent scene descriptions
        continuity_lines: list[str] = []
        if previous_scene is not None:
            prev_dir = resolve_scene_direction(previous_scene, style)
            continuity_lines.append(
                f"- Previous Scene (Scene {previous_scene.scene_number} - '{previous_scene.title}'): "
                f"Subject: {prev_dir.focal_subject} "
                f"[Used composition: {prev_dir.composition_type} — DO NOT repeat this exact layout]"
            )
        else:
            continuity_lines.append("- Previous Scene: None (Opening hook scene).")

        if next_scene is not None:
            next_dir = resolve_scene_direction(next_scene, style)
            continuity_lines.append(
                f"- Next Scene (Scene {next_scene.scene_number} - '{next_scene.title}'): "
                f"Subject: {next_dir.focal_subject} [Upcoming composition: {next_dir.composition_type}]"
            )
        else:
            continuity_lines.append("- Next Scene: None (Final resolution scene).")

        continuity_block = "\n".join(continuity_lines)
        scene_position_str = (
            f"{scene.scene_number} of {total_scenes}"
            if total_scenes
            else str(scene.scene_number)
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
            f"Scene Compositional Blueprint:\n"
            f"- Assigned Composition Archetype: {resolved_direction.composition_type}\n"
            f"- Assigned 2D Camera Choreography: {resolved_direction.camera_movement}\n"
            f"- Primary Focal Hero Subject: {resolved_direction.focal_subject}\n"
            f"- Visual Continuity & Transition Hook: {resolved_direction.transition_hook or 'Smoothly bridge visual motifs across adjacent scenes.'}\n\n"
            f"Cross-Scene Narrative Continuity:\n"
            f"{continuity_block}\n\n"
            f"Target Scene Specification:\n"
            f"- Scene Position: {scene_position_str}\n"
            f"- Title: {scene.title}\n"
            f"- Concept Summary: {scene.summary}\n"
            f"- Visual Description: {scene.description}\n"
            f"- Exact Playback Duration: {target_duration:.2f} seconds\n"
            f"{format_spec}\n\n"
            f"Instructions:\n"
            f"Generate a complete, standalone HTML5 Canvas animation for this scene ({w}x{h}, {'vertical 9:16' if vertical else 'horizontal 16:9'}). "
            f"Match the visual style, color palette, background tone, and the assigned '{resolved_direction.composition_type}' composition. "
            f"Calibrate the multi-act progression (`const DURATION = {target_duration:.2f};`) to match the exact {target_duration:.2f}s duration. "
            f"Use true delta-time (`dt` in seconds) or `elapsed` (in seconds) for ALL particle velocities, oscillations, and physics updates — never use hardcoded per-frame increments. "
            f"Voiceover narration plays as spoken audio. Only include minimal, purposeful text (scene title, essential callouts). "
            f"Write ZERO code comments (no //, /* */, or <!-- -->) and keep the JavaScript/Canvas code compact and free of boilerplate. "
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
            notes=f"Generated in style: {style.style_name} ({resolved_direction.composition_type})",
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
        """Generate animations for all scenes in parallel calibrated to synthesized audio durations."""
        max_concurrency = concurrency or self.DEFAULT_CONCURRENCY

        # Build per-scene duration lookup prioritizing explicit scene_durations and synthesized TTS audio durations
        resolved_scene_durations: dict[int, float] = {}
        if narration_storyboard and narration_storyboard.scenes_audio:
            for s_audio in narration_storyboard.scenes_audio:
                if s_audio.duration_seconds and s_audio.duration_seconds > 0:
                    resolved_scene_durations[s_audio.scene_number] = float(
                        s_audio.duration_seconds
                    )
        if scene_durations:
            for s_num, s_dur in scene_durations.items():
                if s_dur and s_dur > 0:
                    resolved_scene_durations[int(s_num)] = float(s_dur)

        # Resolve total video duration to determine format if not explicitly supplied
        total_dur = total_video_duration or 0.0
        if total_dur <= 0:
            if narration_storyboard and narration_storyboard.total_duration_seconds > 0:
                total_dur = narration_storyboard.total_duration_seconds
            elif resolved_scene_durations and script and script.scenes:
                total_dur = sum(
                    resolved_scene_durations.get(s.scene_number, s.duration_seconds)
                    for s in script.scenes
                )
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

        total_scenes = len(script.scenes)
        logger.info(
            "Generating storyboard (%d scenes, concurrency=%d, %dx%d %s, audio_synced_durations=%s) for topic '%s' in style '%s'",
            total_scenes,
            max_concurrency,
            resolved_w,
            resolved_h,
            "vertical" if resolved_vertical else "horizontal",
            bool(resolved_scene_durations),
            topic,
            style.style_name,
        )

        semaphore = asyncio.Semaphore(max_concurrency)

        async def _animate_with_sem(idx: int, scene: ScriptScene) -> SceneAnimation:
            native_duration = (
                resolved_scene_durations.get(scene.scene_number)
                or default_duration
                or scene.duration_seconds
                or self.settings.default_scene_duration_seconds
            )

            if scene.scene_number == 1 and sample_scene_1 is not None:
                logger.debug(
                    "Reusing pre-generated approved Scene 1 animation (native duration: %.2fs)",
                    sample_scene_1.duration_seconds,
                )
                if resolved_scene_durations.get(1):
                    sample_scene_1.duration_seconds = round(
                        float(resolved_scene_durations[1]), 2
                    )
                return sample_scene_1

            prev_scene = script.scenes[idx - 1] if idx > 0 else None
            nxt_scene = script.scenes[idx + 1] if idx + 1 < total_scenes else None
            direction = resolve_scene_direction(scene, style)

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
                    previous_scene=prev_scene,
                    next_scene=nxt_scene,
                    scene_direction=direction,
                    total_scenes=total_scenes,
                )

        tasks = [
            _animate_with_sem(idx, scene) for idx, scene in enumerate(script.scenes)
        ]
        scenes_animations = await asyncio.gather(*tasks)

        # Ensure ordered by scene number
        scenes_animations.sort(key=lambda s: s.scene_number)

        return AnimationStoryboard(
            topic=topic,
            style=style,
            scenes=scenes_animations,
        )
