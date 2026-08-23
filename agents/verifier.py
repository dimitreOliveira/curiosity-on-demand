"""Verifier agent evaluating research completeness and recommending targeted follow-ups."""

import logging

from agents.base import BaseAgent
from config.settings import Settings, get_settings
from core.models import ResearchReport, VerificationResult

logger = logging.getLogger(__name__)

VERIFIER_SYSTEM_PROMPT = """You are a Lead Fact-Checker and Editorial Director for Curiosity On Demand.
Your job is to critically evaluate research findings before approving them for video scriptwriting.

Review Criteria:
1. Factual Depth: Are there specific details, concrete data points, metrics, and historical/scientific clarity?
2. Narrative Substance: Is there sufficient substance to tell a captivating, educational story across multiple scenes?
3. Source Quality & Grounding: Are claims credible and well-substantiated?
4. Completeness: Are critical questions left unanswered?

If the research is incomplete, provide up to 3 concise, high-yield search queries to fill the gaps.
If the research is rich and ready for scriptwriting, set is_complete=True.
"""


class VerifierAgent(BaseAgent):
    """Inspects research reports for gaps, depth, and factual completeness."""

    def __init__(self, settings: Settings | None = None):
        cfg = settings or get_settings()
        super().__init__(settings=cfg, model_name=cfg.research_model)

    async def verify_research(
        self,
        report: ResearchReport,
        iteration: int = 1,
    ) -> VerificationResult:
        """Analyze research report and return verification decision."""
        logger.info(
            "Verifying research report for topic '%s' (Iteration %d/%d)",
            report.topic,
            iteration,
            self.settings.max_research_iterations,
        )

        prompt = (
            f"Topic: '{report.topic}'\n\n"
            f"Current Research Summary:\n{report.summary}\n\n"
            f"Key Findings ({len(report.findings)} claims):\n"
            + "\n".join(
                f"- [{f.topic}] {f.claim}: {f.detail} (Confidence: {f.confidence_score})"
                for f in report.findings
            )
            + f"\n\nSources ({len(report.sources)} references):\n"
            + "\n".join(f"- {s.title} ({s.url})" for s in report.sources)
            + f"\n\nThis is iteration {iteration} of a maximum {self.settings.max_research_iterations} allowable research loops."
        )

        result = await self.generate_structured(
            prompt=prompt,
            response_schema=VerificationResult,
            system_instruction=VERIFIER_SYSTEM_PROMPT,
        )

        # Force completion if maximum allowable iterations have been reached
        if (
            iteration >= self.settings.max_research_iterations
            and not result.is_complete
        ):
            logger.info(
                "Max research iterations reached (%d). Forcing completion.",
                iteration,
            )
            result.is_complete = True
            result.critique += (
                " (Approved: reached maximum research iterations threshold)."
            )

        return result
