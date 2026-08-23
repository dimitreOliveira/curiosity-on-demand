"""Summarizer agent synthesizing research into an engaging video pitch for human review."""

import logging

from agents.base import BaseAgent
from config.settings import Settings, get_settings
from core.models import PitchSummary, ResearchReport

logger = logging.getLogger(__name__)

SUMMARIZER_SYSTEM_PROMPT = """You are a Master Creative Director and Video Showrunner for Curiosity On Demand.
Your role is to synthesize complex, verified research findings into a snappy, irresistible video pitch for audience review.

Guidelines:
1. Hook: Write a magnetic hook (5-10 seconds) that poses a mystery, counter-intuitive fact, or high-stakes question.
2. Titles: Propose 3 high-CTR, curiosity-inducing YouTube title options.
3. Narrative Arc: Structure a crisp story progression (Hook -> Context/Conflict -> Insight/Revelation -> Climax/Takeaway).
4. Pacing: Aim for an educational video of ~45-75 seconds (typically 4-6 visual scenes).
"""


class SummarizerAgent(BaseAgent):
    """Creates concise video concepts and pitches for human review via Telegram."""

    def __init__(self, settings: Settings | None = None):
        cfg = settings or get_settings()
        super().__init__(settings=cfg, model_name=cfg.gemini_model)

    async def create_pitch(
        self,
        report: ResearchReport,
        user_feedback: str | None = None,
        previous_pitch: PitchSummary | None = None,
    ) -> PitchSummary:
        """Generate or revise a structured video pitch summary from research findings."""
        logger.info(
            "Synthesizing pitch summary for topic '%s' (Revision feedback: %s)",
            report.topic,
            bool(user_feedback),
        )

        findings_text = "\n".join(f"- {f.claim}: {f.detail}" for f in report.findings)

        prompt = (
            f"Topic: '{report.topic}'\n\n"
            f"Verified Research Summary:\n{report.summary}\n\n"
            f"Verified Findings:\n{findings_text}\n"
        )

        if user_feedback and previous_pitch:
            prompt += (
                f"\n--- USER REVISION REQUEST ---\n"
                f"Previous Hook: {previous_pitch.hook}\n"
                f"Previous Narrative: {previous_pitch.core_narrative}\n"
                f"User Feedback / Adjustments Requested:\n'{user_feedback}'\n\n"
                f"Please revise the video pitch to directly address the user's feedback while preserving accurate facts."
            )
        else:
            prompt += "\nPlease craft a compelling, educational video pitch based on this research."

        pitch = await self.generate_structured(
            prompt=prompt,
            response_schema=PitchSummary,
            system_instruction=SUMMARIZER_SYSTEM_PROMPT,
            temperature=0.7,
        )

        if user_feedback:
            pitch.revision_notes = user_feedback

        return pitch
