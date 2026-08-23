"""Scriptwriter agent generating scene-by-scene narration and programmatic SVG blueprints."""

import logging

from agents.base import BaseAgent
from config.settings import Settings, get_settings
from core.models import PitchSummary, ResearchReport, VideoScript

logger = logging.getLogger(__name__)

SCRIPTWRITER_SYSTEM_PROMPT = """You are an Elite Video Scriptwriter and Visual Motion Designer for Curiosity On Demand.
Your task is to transform an approved video pitch and research report into a scene-by-scene script with executable SVG graphics.

SVG Graphic Rules:
1. Every scene must have a complete, valid, standalone `<svg viewBox="0 0 1920 1080" xmlns="http://www.w3.org/2000/svg">...</svg>` in `svg_source`.
2. Design Aesthetics:
   - Use sleek modern dark themes (e.g. background gradients between `#0a0f1d` and `#1e293b`).
   - Use high-contrast, beautiful accent colors (`#38bdf8`, `#818cf8`, `#34d399`, `#f472b6`, `#fbbf24`).
   - Typography: Clean sans-serif fonts (`font-family="system-ui, -apple-system, sans-serif"`).
   - Layout: Centered or balanced grid/card compositions, prominent headline metrics, clean badges, subtle decorative grid lines or circles.
   - Compatibility: Must render cleanly via CairoSVG (avoid external CSS imports or unsupported filter chains; use standard SVG linearGradient, rect, circle, path, text, and g elements).
3. Narration Timing:
   - Calculate narration duration realistically (~2.5 words per second).
   - Ensure `duration_seconds` matches narration length.
4. Shorts Compatibility:
   - Mark standout, high-curiosity scenes with `is_suitable_for_short=True` and list their IDs in `highlighted_short_scene_ids`.
"""


class ScriptWriterAgent(BaseAgent):
    """Generates complete multi-scene scripts with TTS voiceover text and SVG animation source."""

    def __init__(self, settings: Settings | None = None):
        cfg = settings or get_settings()
        super().__init__(settings=cfg, model_name=cfg.gemini_model)

    async def generate_script(
        self,
        pitch: PitchSummary,
        report: ResearchReport | None = None,
        custom_instructions: str | None = None,
    ) -> VideoScript:
        """Generate structured scene-by-scene VideoScript from approved pitch."""
        logger.info(
            "Generating full video script for pitch topic '%s'",
            pitch.topic,
        )

        research_context = ""
        if report:
            research_context = "\n\nKey Verified Facts:\n" + "\n".join(
                f"- {f.claim}: {f.detail}" for f in report.findings
            )

        prompt = (
            f"Approved Video Concept:\n"
            f"Topic: {pitch.topic}\n"
            f"Selected Title Option: {pitch.title_options[0] if pitch.title_options else pitch.topic}\n"
            f"Hook: {pitch.hook}\n"
            f"Target Audience: {pitch.target_audience}\n"
            f"Key Takeaways: {', '.join(pitch.key_takeaways)}\n"
            f"Narrative Arc: {pitch.core_narrative}\n"
            f"Planned Scene Count: {pitch.estimated_scenes_count}\n"
            f"{research_context}\n"
        )

        if custom_instructions:
            prompt += f"\nSpecial Instructions:\n{custom_instructions}\n"

        prompt += (
            f"\nGenerate the complete VideoScript JSON schema with {pitch.estimated_scenes_count} scenes. "
            f"Ensure each scene has engaging narration and valid, standalone 1920x1080 SVG code in svg_source."
        )

        script = await self.generate_structured(
            prompt=prompt,
            response_schema=VideoScript,
            system_instruction=SCRIPTWRITER_SYSTEM_PROMPT,
            temperature=0.6,
        )

        # Post-process: ensure durations and IDs are normalized
        total_duration = 0.0
        short_candidates = []
        for i, scene in enumerate(script.scenes, start=1):
            scene.scene_id = i
            # Calculate duration if unreasonably small
            words = len(scene.narration.split())
            calculated_duration = max(3.0, round(words / 2.4, 1))
            if scene.duration_seconds < 2.0:
                scene.duration_seconds = calculated_duration
            total_duration += scene.duration_seconds

            if scene.is_suitable_for_short:
                short_candidates.append(scene.scene_id)

        script.total_duration_seconds = round(total_duration, 1)
        if not script.highlighted_short_scene_ids:
            # Default to scene 1 or marked scenes
            script.highlighted_short_scene_ids = short_candidates or [1]

        return script
