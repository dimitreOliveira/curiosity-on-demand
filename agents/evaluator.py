"""Evaluator agent assessing research quality, filtering noise, and structuring output."""

import logging

from agents.base import BaseAgent
from config.settings import Settings, get_settings
from core.models import EvaluationResult

logger = logging.getLogger(__name__)

EVALUATOR_SYSTEM_PROMPT = """You are a Senior Content Evaluator and Fact-Checker for Curiosity On Demand, a high-production educational video channel.
Your mission is to evaluate gathered research notes, filter noise/duplicates, organize the research into a clean structured report, and determine if the content is sufficient for video production.

Your responsibilities:
1. Filter & Curate: Remove duplicate, irrelevant, speculative, or low-quality claims. Keep verified, fascinating facts, clear explanations of mechanisms, and engaging storytelling angles.
2. Structure: Format the curated findings into the required ResearchReport schema (topic, overall summary, and detailed subtopic sections).
3. Evaluate Sufficiency for Target Duration:
   - Carefully consider the requested target video duration.
   - For short videos (~1-3 minutes): Needs a punchy hook, concise explanation of the core concept, and a memorable takeaway.
   - For standard/longer videos (~5-15 minutes, default ~10 minutes): Requires rich foundational background, step-by-step mechanical explanations, historical experiments or context, paradoxes or intriguing facts, and visual analogies.
4. Actionable Guidance:
   - If the research is insufficient and more rounds remain, set is_sufficient=false and provide specific, actionable feedback_for_researcher detailing exact questions or subtopics to search for.
   - If the content is comprehensive and sufficient, or if this is the final iteration round, set is_sufficient=true and feedback_for_researcher=null.
"""


class EvaluatorAgent(BaseAgent):
    """Evaluates raw research notes, filters noise, structures reports, and directs further research."""

    def __init__(self, settings: Settings | None = None):
        cfg = settings or get_settings()
        super().__init__(settings=cfg, model_name=cfg.evaluator_model)

    async def evaluate_research(
        self,
        topic: str,
        accumulated_research: str,
        target_duration: str = "~10 minutes",
        iteration: int = 1,
        max_iterations: int = 3,
    ) -> EvaluationResult:
        """Evaluate accumulated research notes against target video duration and return structured EvaluationResult."""
        logger.info(
            "Evaluating research for topic '%s' (Iteration %d/%d, Target Duration: %s)",
            topic,
            iteration,
            max_iterations,
            target_duration,
        )

        is_final_round = iteration >= max_iterations
        round_instruction = (
            "This is the FINAL research round. You MUST synthesize and format the best possible report from all available notes, "
            "setting is_sufficient=true and feedback_for_researcher=null."
            if is_final_round
            else f"This is iteration round {iteration} of {max_iterations}. Assess if additional research is needed for a {target_duration} video."
        )

        eval_prompt = (
            f"Topic: '{topic}'\n"
            f"Target Video Duration: {target_duration}\n"
            f"Iteration Status: {round_instruction}\n\n"
            f"Accumulated Research Notes:\n"
            f"---------------------------\n"
            f"{accumulated_research}\n"
            f"---------------------------\n\n"
            f"Please review the research notes above:\n"
            f"1. Discard bad, duplicate, speculative, or irrelevant information.\n"
            f"2. Structure the remaining high-quality knowledge into the ResearchReport schema (topic, comprehensive summary, and detailed sections with subtopic and content).\n"
            f"3. Decide whether the gathered material has sufficient depth, clarity, and narrative appeal for a {target_duration} educational video.\n"
            f"4. If insufficient and not in the final round, set is_sufficient=false and provide specific search guidance in feedback_for_researcher. Otherwise set is_sufficient=true."
        )

        result = await self.generate_structured(
            prompt=eval_prompt,
            response_schema=EvaluationResult,
            system_instruction=EVALUATOR_SYSTEM_PROMPT,
        )

        # Ensure topic consistency
        result.report.topic = topic

        # Force sufficiency on final round
        if is_final_round:
            result.is_sufficient = True
            result.feedback_for_researcher = None

        return result
