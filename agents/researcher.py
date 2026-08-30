"""Researcher agent powered by Gemini with Google Search grounding."""

import logging

from google.genai import types

from agents.base import BaseAgent
from config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

RESEARCHER_SYSTEM_PROMPT = """You are a Research Agent for Curiosity On Demand, an educational video channel.
Your mission is to perform thorough, fact-checked research on the requested topic using Google Search to gather rich information for creating an engaging video.

Guidelines:
1. Conduct active Google Searches to uncover verified facts, clear explanations of mechanisms, historical context, concrete examples, statistics, and counter-intuitive insights.
2. Structure your findings clearly with rich descriptions, narrative hooks, and storytelling angles suitable for visual video content.
3. If specific feedback or missing research areas are requested, focus heavily on searching for and answering those exact inquiries.
"""


class ResearcherAgent(BaseAgent):
    """Conducts web-grounded research using Gemini and Google Search without schema constraints."""

    def __init__(self, settings: Settings | None = None):
        cfg = settings or get_settings()
        super().__init__(settings=cfg, model_name=cfg.research_model)

    async def conduct_research(
        self,
        topic: str,
        feedback: str | None = None,
        previous_research: str | None = None,
        target_duration: str | None = None,
    ) -> str:
        """Execute grounded research query using Google Search and return rich raw text findings."""
        logger.info(
            "Conducting research on topic '%s' (Guided: %s)",
            topic,
            bool(feedback),
        )

        duration_context = (
            f"The video target duration is {target_duration}.\n"
            if target_duration
            else ""
        )

        if feedback and previous_research:
            search_prompt = (
                f"We are continuing research for an educational video on: '{topic}'.\n"
                f"{duration_context}"
                f"Previous research collected:\n{previous_research}\n\n"
                f"CRITICAL FEEDBACK & MISSING AREAS TO INVESTIGATE:\n{feedback}\n\n"
                f"Please conduct targeted Google Searches to gather comprehensive facts, answers, data, "
                f"and deep context addressing the feedback above."
            )
        else:
            search_prompt = (
                f"Please conduct comprehensive, fact-checked research on the topic: '{topic}' "
                f"with the goal of creating an educational video.\n"
                f"{duration_context}"
                f"Use Google Search to find accurate facts, explanations of key mechanisms, historical context, "
                f"notable figures or events, engaging paradoxes, and memorable storytelling hooks.\n"
                f"Provide detailed explanatory notes broken down by subtopics."
            )

        search_tool = types.Tool(google_search=types.GoogleSearch())
        raw_research = await self.generate_text(
            prompt=search_prompt,
            system_instruction=RESEARCHER_SYSTEM_PROMPT,
            tools=[search_tool],
        )

        return raw_research
