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

Your mission is to generate standalone, executable, high-fidelity HTML5 Canvas / SVG animations that strictly implement the project's visual style and dynamically illustrate each scene's narrative.

### 📐 Creative Coding Architecture & Visual Pillars (CRITICAL):
Every generated canvas animation MUST incorporate the following 6 structural pillars:

1. **Decoupled Delta-Time Loop & Continuous Living Motion (CRITICAL):**
   - Always decouple physics/state updates from drawing:
     `function update(dt) { ... }` and modular render passes `drawBackground()`, `drawEnvironment()`, `drawActors()`, `drawFX()`, `drawHUD()`.
   - Use standard `requestAnimationFrame(loop)` with delta-time: `const dt = Math.min((now - lastTime) / 1000, 0.1);`.
   - Structure narrative progression using an explicit state machine (e.g. `state = 'intro' | 'action' | 'climax' | 'resolution'`).
   - **STRICT NON-FREEZING MANDATE:** The canvas animation must NEVER stop updating, freeze, or hold a static frame. If the narrative timeline or keyframes conclude, the scene must:
     a) Seamlessly loop its narrative cycle (`time = time % DURATION`), or
     b) Transition into continuous, living procedural idle motion (ambient particles, breathing character rigs, pulsating glows, oscillating waves, subtle camera drifts) so the canvas is ALWAYS actively moving at every single frame.
   - Use normalized progress: `const progress = Math.min(time / DURATION, 1.0);` combined with continuous ambient oscillators `Math.sin(time * speed)` so physics and ambient FX never freeze even after narrative progress reaches 1.0.
   - NEVER call `cancelAnimationFrame` or write early `return` statements that stop drawing.

2. **Articulated Procedural Rigging & Trigonometry:**
   - Draw characters, animals, humans, machines, anatomical diagrams, or celestial objects procedurally using `ctx.save()`, `ctx.translate(x, y)`, `ctx.rotate(angle)`, and `ctx.restore()`.
   - Use harmonic oscillation (`Math.sin(time * speed + phase) * amplitude`) for natural, fluid secondary motion (e.g., swinging limbs, flapping wings, pulsating membranes, breathing, rotating dials, bouncing steps).
   - Render multi-segment body parts using geometric primitives (`ctx.roundRect`, `ctx.arc`, `ctx.ellipse`, `ctx.beginPath()`, `ctx.stroke()`, `ctx.fill()`).
   - Always cast dynamic soft drop shadow ellipses under moving entities (`ctx.ellipse(x, groundY, radiusX, radiusY, 0, 0, Math.PI * 2)` with subtle alpha).

3. **Atmospheric & Volumetric Lighting:**
   - Never use flat, single-color backgrounds. Build multi-stop linear or radial gradients (`createLinearGradient`, `createRadialGradient`) matching the style palette for atmospheric skies, deep cosmic voids, or spotlight vignettes.
   - Include volumetric lighting elements: spotlight cones, sunlight rays, light bulb racks, or glowing halos with soft alpha falloff (`rgba(..., 0.4)` to `rgba(..., 0)`).
   - Add environmental texture (e.g., subtle coordinate grids, starry dust motes, or textured lines).

4. **Kinematics & Physics Engine:**
   - Implement realistic motion physics: true velocity vectors (`vx`, `vy`), gravity acceleration (`vy += gravity * dt`), air/ground friction damping (`vx *= 0.98`), angular spin (`rot += vrot * dt`), and reactive easing.

5. **Dynamic Particle Systems & Visual FX ("Juice"):**
   - Implement array-based particle lifecycles with velocity, gravity, angular spin, color palettes, alpha decay, and filtering (`particles = particles.filter(p => p.life > 0)`).
   - **Motion Blur / Glowing Trails:** Maintain a historical coordinate queue (`trail.unshift({x, y, alpha: 1.0})`) for fast-moving entities and render decaying glowing paths.
   - **Impact Flashes & Screen Shake:** Trigger coordinate shakes (`ctx.translate(Math.sin(time * 30) * shake, 0)`) and full-screen translucent white flashes on climax moments or collisions.
   - **Secondary FX:** Floating ambient particles, spark emitters, shockwaves, or energy bursts.

6. **Kinetic Typography & Styled Highlights:**
   - For key titles, metrics, or climax callouts, use dynamic scaling, glowing drop shadows (`ctx.shadowColor`, `ctx.shadowBlur`), stroke outlines, and multi-color gradient fills.

### 🔇 Text & Typographic Restraint (CRITICAL):
- Audio narration will play over the animation as voiceover. DO NOT render full narrative sentences, subtitles, or voiceover transcripts on screen.
- Include ONLY purposeful, minimal text: essential diagram labels (e.g., "Nucleus", "1905", "100°C"), key quantitative metrics/counters, or concise subject callouts that directly clarify the visuals.

### ⚙️ Output Format & Standards:
- Return ONLY the complete, self-contained, valid HTML document (`<!DOCTYPE html><html><head>...<style>...</style></head><body><canvas id="stage"></canvas><script>...</script></body></html>`).
- Resolution: Standard 16:9 widescreen `1280x720` canvas with responsive CSS (`width: 100%; height: 100%; object-fit: contain; margin: 0; overflow: hidden; background: ...`).
- Pure Vanilla Web Technologies (Canvas 2D/WebGL, SVG, Vanilla JS). NO external CDNs or external script tags.
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
        logger.info(
            "Generating animation code for Scene %d ('%s', %.2fs) in style '%s'",
            scene.scene_number,
            scene.title,
            target_duration,
            style.style_name,
        )

        palette_str = (
            ", ".join(style.color_palette) if style.color_palette else "Theme Default"
        )
        prompt = (
            f"Topic: {topic}\n\n"
            f"Visual Design System:\n"
            f"- Style Name: {style.style_name}\n"
            f"- Art Direction & Tone: {style.visual_description}\n"
            f"- Color Palette: {palette_str}\n"
            f"- Typography: {style.font_family}\n"
            f"- Motion & Animation Guidelines: {style.animation_guidelines}\n\n"
            f"Target Scene Specification:\n"
            f"- Scene Number: {scene.scene_number}\n"
            f"- Title: {scene.title}\n"
            f"- Concept Summary: {scene.summary}\n"
            f"- Visual Description: {scene.description}\n"
            f"- Spoken Narration (for pacing/context only): {scene.narration}\n"
            f"- Playback Duration: {target_duration:.2f} seconds (timed to match voiceover narration)\n\n"
            f"Instructions:\n"
            f"Generate the complete, standalone, high-fidelity HTML5 Canvas animation for this scene. "
            f"Strictly reflect the chosen visual style and color palette. "
            f"Implement procedural entity rigging, multi-layer volumetric lighting, physics kinematics, "
            f"dynamic particle emitters/trails, and a decoupled delta-time state machine calibrated for {target_duration:.2f} seconds. "
            f"REMINDER: Voiceover narration will play as spoken audio. DO NOT put narration sentences or subtitles on screen. "
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
    ) -> AnimationStoryboard:
        """Generate animations for all scenes in parallel using native animation durations.

        Visual animations are rendered at their native duration (100% active motion).
        The video renderer then stretches or compresses playback speed via FFmpeg
        to perfectly match the narration audio duration with zero frozen frames.
        """
        max_concurrency = concurrency or self.DEFAULT_CONCURRENCY
        logger.info(
            "Generating storyboard (%d scenes, concurrency=%d) for topic '%s' in style '%s'",
            len(script.scenes),
            max_concurrency,
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
