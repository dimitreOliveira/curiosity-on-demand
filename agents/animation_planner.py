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
  * Nature, Wildlife & Biology: Organic palettes, cellular/botanical textures, anatomical sketches, animal locomotion, fluid ecosystem dynamics.
  * People, Society & History: Expressive character silhouettes, archival parchment, cultural motifs, dynamic maps, period aesthetics.
  * Food & Culinary Science: Warm appetizing palettes, fluid textures, cooking chemistry, molecular transformations.
  * Data, Math & Economics: Crisp minimalist infographics, clean isometric layouts, geometric grids, flowcharts, metric counters.
  * Physics, Space & Sci-Fi: Atmospheric cosmic lighting, orbital trajectories, relativistic spacetime grids, particle systems.
  * Abstract Concepts & Philosophy: Metaphorical visual storytelling, morphing geometric shapes, evocative fluid transitions.

### 📐 Design System Pillars:
1. **Style Name:** A clear, punchy name representing the visual aesthetic (e.g., 'Atmospheric Quantum Hologram', 'Warm Botanical Illustrated Guide').
2. **Visual Description:** Thorough guidance on lighting, atmosphere, scene depth, background tone (light, dark, pastel, warm, or monochrome), and entity rendering style.
3. **Color Palette:** 3–6 curated hex colors with clear contrast between background, primary objects, accents, and highlights.
4. **Typography:** Font stack suited for clean diagram labels and metric callouts (e.g., 'Inter, sans-serif', 'Space Grotesk, sans-serif').
5. **Animation Guidelines:** Motion design principles (easing, pacing, particle density, camera feel, state transitions).
6. **Visual Continuity & Metaphors:** Specific visual motifs, metaphors, or character/diagram designs that must remain consistent across scenes.
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
    ) -> AnimationStyle:
        """Analyze script, formulate best-fitting visual design system, and handle revisions."""
        logger.info(
            "Planning animation visual style for topic '%s' (Guided feedback: %s)",
            topic,
            bool(feedback),
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
            f"Script Overview: {script.summary}\n\n"
            f"All Script Scenes:\n{scenes_summary}"
        )

        if feedback and previous_style:
            prompt = (
                f"{base_context}\n\n"
                f"===================================================\n"
                f"PREVIOUS VISUAL STYLE:\n"
                f"Name: {previous_style.style_name}\n"
                f"Description: {previous_style.visual_description}\n"
                f"Palette: {', '.join(previous_style.color_palette)}\n"
                f"Typography: {previous_style.font_family}\n"
                f"Guidelines: {previous_style.animation_guidelines}\n"
                f"===================================================\n\n"
                f"USER REVISION FEEDBACK:\n"
                f"{feedback}\n\n"
                f"Please update the AnimationStyle according to the user's feedback. "
                f"Ensure the revised design system, color palette, and animation guidelines provide complete clarity "
                f"for creative coders implementing scene-by-scene HTML5 Canvas animations."
            )
        else:
            prompt = (
                f"{base_context}\n\n"
                f"Please formulate the ideal, bespoke AnimationStyle that uniquely complements the topic '{topic}'. "
                f"Select the palette, mood, background tone, typography, and motion guidelines completely freely to best serve the subject matter. "
                f"Ensure the design system ensures visual continuity and narrative impact across all {len(script.scenes)} scenes."
            )

        return await self.generate_structured(
            prompt=prompt,
            response_schema=AnimationStyle,
            system_instruction=ANIMATION_PLANNER_SYSTEM_PROMPT,
        )
