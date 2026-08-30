"""ScriptWriter agent generating scene-by-scene narration scripts from structured research."""

import logging

from agents.base import BaseAgent
from config.settings import Settings, get_settings
from core.models import ResearchReport, Script

logger = logging.getLogger(__name__)

SCRIPT_WRITER_SYSTEM_PROMPT = """You are a Master Scriptwriter and Educational Storyteller for Curiosity On Demand, a high-production educational channel.
Your mission is to transform structured research into an engaging, scene-by-scene narration script.

Your principles:
1. Narrative Flow & Pacing:
   - Scene 1 (The Hook): Hook the audience immediately with an intriguing premise, paradox, visual thought experiment, or high-stakes question.
   - Middle Scenes (The Core Journey): Walk the viewer through key mechanisms, historical context, surprising insights, and intuitive analogies based on the research.
   - Final Scene (The Resolution): Deliver a memorable conclusion, profound takeaway, or philosophical perspective that ties everything together.
2. Scene Breakdown:
   - Divide the script into distinct, logical scenes or segments (typically 4 to 8 scenes depending on the target duration).
   - For each scene, provide:
     * scene_number: Sequential integer (1, 2, 3...)
     * title: Catchy, descriptive scene title
     * summary: Clear summary of what this segment covers
     * narration: The exact, conversational, punchy voiceover script to be spoken aloud.
3. Tone & Cadence:
   - Engaging, clear, accessible, and intellectually stimulating (in the style of Veritasium, Kurzgesagt, or 3Blue1Brown).
   - Use natural transitions between scenes.
4. Handling Feedback & Revisions:
   - When previous script and user feedback are provided, modify or rewrite scenes to address the feedback while maintaining consistent tone and cohesive narrative flow.
"""


class ScriptWriterAgent(BaseAgent):
    """Generates structured scene-by-scene narration scripts from research reports."""

    def __init__(self, settings: Settings | None = None):
        cfg = settings or get_settings()
        super().__init__(settings=cfg, model_name=cfg.script_model)

    async def generate_script(
        self,
        topic: str,
        research_report: ResearchReport,
        target_duration: str = "~10 minutes",
        feedback: str | None = None,
        previous_script: Script | None = None,
    ) -> Script:
        """Generate or revise a structured narration script based on research notes and optional feedback."""
        logger.info(
            "Generating script for topic '%s' (Guided feedback: %s, Duration: %s)",
            topic,
            bool(feedback),
            target_duration,
        )

        sections_text = "\n\n".join(
            f"### Subtopic: {s.topic}\n{s.content}" for s in research_report.sections
        )

        research_context = (
            f"Topic: {topic}\n"
            f"Target Video Duration: {target_duration}\n\n"
            f"Research Summary:\n{research_report.summary}\n\n"
            f"Researched Subtopics & Knowledge Base:\n"
            f"{sections_text}"
        )

        if feedback and previous_script:
            prev_scenes_text = "\n\n".join(
                f"Scene {s.scene_number} - {s.title}:\nSummary: {s.summary}\nNarration: {s.narration}"
                for s in previous_script.scenes
            )
            prompt = (
                f"{research_context}\n\n"
                f"===================================================\n"
                f"PREVIOUS SCRIPT:\n"
                f"Summary: {previous_script.summary}\n\n"
                f"{prev_scenes_text}\n"
                f"===================================================\n\n"
                f"CRITICAL USER FEEDBACK & REVISION INSTRUCTIONS:\n"
                f"{feedback}\n\n"
                f"Please produce a revised Script schema addressing the user's feedback while preserving "
                f"the strong elements of the narration and adhering to the {target_duration} target."
            )
        else:
            prompt = (
                f"{research_context}\n\n"
                f"Please craft a complete, engaging scene-by-scene narration Script for a {target_duration} educational video. "
                f"Break down the topic into logical scenes, providing a summary and full spoken narration for each scene."
            )

        script = await self.generate_structured(
            prompt=prompt,
            response_schema=Script,
            system_instruction=SCRIPT_WRITER_SYSTEM_PROMPT,
        )

        # Guarantee topic matches
        script.topic = topic
        return script
