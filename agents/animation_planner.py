"""Animation planner agent formulating visual design direction, color palettes, and motion guidelines."""

import logging

from agents.base import BaseAgent
from config.settings import Settings, get_settings
from core.models import (
    AnimationStyle,
    Script,
)

logger = logging.getLogger(__name__)

ANIMATION_PLANNER_SYSTEM_PROMPT = """You are a World-Class Art Director and Creative Visual Strategist for Curiosity On Demand, an elite educational video channel.

Your mission is to analyze the entire video narrative script and design a cohesive, bespoke, and visually stunning aesthetic system that all animated scenes will follow.

### 🎨 Art Direction & Visual Identity:
- Match the visual language, palette, composition, and artistic medium freely and deliberately to the subject matter:
  * Nature, Wildlife & Biology: Organic palettes, cellular/botanical textures, warm earthy tones, animal locomotion, fluid ecosystem dynamics. Backgrounds: soft green canopies, warm golden hour light, gentle watercolor washes.
  * People, Society & History: Expressive character silhouettes, archival parchment, cultural motifs, dynamic maps, period aesthetics. Backgrounds: aged paper warmth, period-specific color grading, soft sepia or muted editorial tones.
  * Food & Culinary Science: Warm appetizing palettes (golden ambers, terracottas, fresh greens), fluid textures, cooking chemistry, sensory richness. Backgrounds: warm kitchen studio lighting, buttery golden ambiance, appetizing depth of field.
  * Data, Science & Technology: Crisp modern infographics, clean isometric layouts, elegant geometric vectors, flowing process diagrams. Backgrounds: clean white or soft grey studio, pastel accent gradients, airy modern editorial.
  * Physics, Space & Cosmology: Atmospheric cosmic gradients, planetary scale, orbital trajectories, luminous stellar glows, particle dynamics. Backgrounds: deep space gradients with rich blues, purples, and nebula warmth.
  * Abstract Concepts & Philosophy: Metaphorical visual storytelling, morphing geometric shapes, evocative fluid transitions, editorial minimalism. Backgrounds: soft gradients, contemplative neutral tones, dreamy pastels.

### 🌈 Background Tone & Atmosphere (CRITICAL):
- The `background_tone` field is one of the most impactful creative decisions. Choose it deliberately to match the emotional register of the topic:
  * Most topics should use warm, bright, or pastel backgrounds. Only deep cosmic or horror/thriller topics should use truly dark backgrounds.
  * Examples: 'warm parchment' (#F7F3E9), 'soft morning sky' (light blue-pink gradient), 'clean white studio', 'golden hour warmth', 'deep oceanic blue', 'sunset coral gradient', 'cool dark atmospheric' (only when justified).
- The chosen background tone must harmonize with the color_palette — backgrounds and foreground elements need contrast for readability.

### 🎬 Compositional Diversity & Per-Scene Blueprints (CRITICAL):
- A great video avoids visual monotony by varying the composition and camera framing from scene to scene.
- Populate `scene_directions` with an entry for EVERY scene in the script, assigning a distinct `composition_type`, `camera_movement`, `focal_subject`, and `transition_hook` so that no two adjacent scenes share the same framing or layout.
- Alternate across diverse compositional archetypes such as:
  * Full-bleed panoramic establishing shots (environment fills the entire canvas)
  * Intimate close-up character or object studies (entity fills 70%+ of frame)
  * Split compositions or side-by-side comparisons
  * Abstract metaphorical sequences (shapes, particles, color morphs — no text)
  * Diagram or process-flow cutaway layouts with clean infographic framing
  * Dramatic camera dolly or zoom-through transitions
- Scenes should NOT all follow the same "title header at top → centered entity → annotation at bottom" layout.

### 🖼️ Visual Identity (Premium Documentary Illustration):
- Every animation should feel like a frame from a premium illustrated documentary or animated editorial — never like a system interface, diagnostic monitor, archival catalog plate, or HUD readout.
- The canvas should be an open, immersive, cinematic frame dedicated to beautiful subject illustration and atmospheric storytelling.
- Text on screen should be minimal and purposeful: only clean scene titles and essential diagram callouts. No pseudo-technical headers, classification codes, catalog references, coordinate readouts, or runtime displays.

### 📐 Design System Pillars:
1. **Style Name:** A clear, evocative name representing the visual aesthetic (e.g., 'Warm Botanical Illustrated Guide', 'Vibrant Editorial Motion Graphics', 'Luminous Deep-Space Narrative', 'Sensory Culinary Watercolor & Vector', 'Kinetic Geometric Infographic').
2. **Visual Description:** Thorough guidance on lighting, atmosphere, scene depth, entity rendering style, and the overall feeling viewers should experience.
3. **Color Palette:** 3–6 curated hex colors with clear contrast between background, primary objects, accents, and highlights. The palette must complement the chosen background_tone.
4. **Typography:** Font stack suited for clean, beautiful title cards and diagram callouts (e.g., 'Inter, sans-serif', 'Outfit, sans-serif', 'Cinzel, Georgia, serif', 'Playfair Display, Georgia, serif').
5. **Animation Guidelines:** Motion design principles (easing, pacing, particle density, camera feel, state transitions) plus compositional variety guidance for scene-to-scene diversity.
6. **Background Tone:** The overall mood and brightness of the background atmosphere (e.g., 'warm parchment', 'soft pastel gradient', 'clean white studio', 'deep atmospheric'). This is crucial for setting the right emotional register.
7. **Scene Directions (`scene_directions`):** A complete per-scene list mapping each `scene_number` to a bespoke `composition_type`, `camera_movement`, `focal_subject`, and `transition_hook` that links the visual journey across scenes.
"""


class AnimationPlannerAgent(BaseAgent):
    """Formulates cohesive visual styles, palettes, and motion design systems for video scripts."""

    def __init__(self, settings: Settings | None = None):
        cfg = settings or get_settings()
        super().__init__(settings=cfg, model_name=cfg.animator_model)

    async def plan_style(
        self,
        topic: str,
        script: Script,
        feedback: str | None = None,
        previous_style: AnimationStyle | None = None,
        is_vertical: bool | None = None,
    ) -> AnimationStyle:
        """Analyze script, formulate best-fitting visual design system, and handle revisions."""
        logger.info(
            "Planning animation visual style for topic '%s' (Guided feedback: %s)",
            topic,
            bool(feedback),
        )

        total_dur = (
            sum(s.duration_seconds for s in script.scenes)
            if script and script.scenes
            else 0
        )
        vertical = (
            is_vertical
            if is_vertical is not None
            else self.settings.is_vertical_video(total_dur)
        )
        format_info = (
            "Target Format: 9:16 Vertical Portrait (YouTube Shorts / mobile video format). "
            "Prioritize vertical visual balance, vertically stacked diagram layouts, and mobile-optimized contrast."
            if vertical
            else "Target Format: 16:9 Horizontal Widescreen."
        )

        scenes_summary = "\n".join(
            f"Scene {s.scene_number} - {s.title} ({s.duration_seconds}s):\n"
            f"  Summary: {s.summary}\n"
            f"  Visual Description: {s.description}\n"
            f"  Narration: '{s.narration[:120]}...'"
            for s in script.scenes
        )

        base_context = (
            f"Topic: {topic}\n"
            f"Format: {format_info}\n"
            f"Script Overview: {script.summary}\n\n"
            f"All Script Scenes:\n{scenes_summary}"
        )

        if feedback and previous_style:
            prev_directions = "\n".join(
                f"  - Scene {d.scene_number}: [{d.composition_type}] Camera: {d.camera_movement} | Subject: {d.focal_subject}"
                for d in previous_style.scene_directions
            )
            prompt = (
                f"{base_context}\n\n"
                f"===================================================\n"
                f"PREVIOUS VISUAL STYLE:\n"
                f"Name: {previous_style.style_name}\n"
                f"Description: {previous_style.visual_description}\n"
                f"Palette: {', '.join(previous_style.color_palette)}\n"
                f"Typography: {previous_style.font_family}\n"
                f"Guidelines: {previous_style.animation_guidelines}\n"
                f"Scene Directions:\n{prev_directions or '  (None)'}\n"
                f"===================================================\n\n"
                f"USER REVISION FEEDBACK:\n"
                f"{feedback}\n\n"
                f"Please update the AnimationStyle (including `scene_directions` for all {len(script.scenes)} scenes) "
                f"according to the user's feedback. Ensure the revised design system, color palette, and per-scene "
                f"compositional blueprints provide complete clarity for creative coders implementing HTML5 Canvas animations."
            )
        else:
            prompt = (
                f"{base_context}\n\n"
                f"Please formulate the ideal, bespoke AnimationStyle that uniquely complements the topic '{topic}'. "
                f"Select the palette, mood, background tone, typography, and motion guidelines completely freely to best serve the subject matter. "
                f"Provide `scene_directions` for all {len(script.scenes)} scenes, ensuring varied compositional archetypes, "
                f"dynamic camera movements, and seamless visual continuity across adjacent scenes."
            )

        return await self.generate_structured(
            prompt=prompt,
            response_schema=AnimationStyle,
            system_instruction=ANIMATION_PLANNER_SYSTEM_PROMPT,
        )
