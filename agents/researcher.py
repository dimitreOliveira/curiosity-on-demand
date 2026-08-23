"""Researcher agent powered by Gemini 3.7 Flash with Google Search grounding."""

import logging

from google.genai import types

from agents.base import BaseAgent
from config.settings import Settings, get_settings
from core.models import ResearchReport, ResearchSource

logger = logging.getLogger(__name__)

RESEARCHER_SYSTEM_PROMPT = """You are a Principal Research Analyst for a high-production educational video channel ("Curiosity On Demand").
Your mission is to perform thorough, fact-checked, deep investigation into the requested topic.

Guidelines:
1. Focus on verified facts, recent discoveries, concrete statistics, historical context, and counter-intuitive insights.
2. Ensure every major claim has specific context and, if possible, real-world data points.
3. Identify compelling storylines, intriguing paradoxes, and memorable examples that will captivate visual video audiences.
4. Always prioritize factual accuracy and clarity over sensationalism.
"""


class ResearcherAgent(BaseAgent):
    """Conducts iterative web-grounded research using Gemini and Google Search."""

    def __init__(self, settings: Settings | None = None):
        cfg = settings or get_settings()
        super().__init__(settings=cfg, model_name=cfg.research_model)

    async def conduct_research(
        self,
        topic: str,
        follow_up_queries: list[str] | None = None,
        previous_report: ResearchReport | None = None,
        iteration: int = 1,
    ) -> ResearchReport:
        """Execute grounded research query against Gemini with Google Search tool."""
        logger.info(
            "Conducting research on topic '%s' (Iteration %d)",
            topic,
            iteration,
        )

        # Build research query prompt
        if follow_up_queries and previous_report:
            queries_str = "\n- ".join(follow_up_queries)
            prompt = (
                f"We are expanding our research for the video topic: '{topic}'.\n\n"
                f"Previous research summary:\n{previous_report.summary}\n\n"
                f"Please specifically investigate the following missing areas and follow-up questions:\n"
                f"- {queries_str}\n\n"
                f"Use Google Search grounding to find precise data points, verified facts, sources, and explanations."
            )
        else:
            prompt = (
                f"Please conduct deep, fact-checked research on the topic: '{topic}'.\n"
                f"Search for recent findings, foundational context, notable figures, numerical metrics, "
                f"and engaging narrative hooks suitable for a dynamic 60-second to 3-minute educational video."
            )

        # 1. Step 1: Query Gemini with Google Search tool
        search_tool = types.Tool(google_search=types.GoogleSearch())
        grounded_response = await self.client.aio.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=RESEARCHER_SYSTEM_PROMPT,
                tools=[search_tool],
            ),
        )

        raw_research_text = (
            (grounded_response.text or "").strip() if grounded_response else ""
        )

        # Extract grounding metadata (citations & search sources)
        extracted_sources: list[ResearchSource] = []
        if (
            grounded_response
            and grounded_response.candidates
            and len(grounded_response.candidates) > 0
        ):
            candidate = grounded_response.candidates[0]
            grounding_meta = getattr(candidate, "grounding_metadata", None)
            if grounding_meta:
                grounding_chunks = getattr(grounding_meta, "grounding_chunks", [])
                if grounding_chunks:
                    for chunk in grounding_chunks:
                        web = getattr(chunk, "web", None)
                        if web:
                            title = getattr(web, "title", "Source Webpage")
                            uri = getattr(web, "uri", "")
                            if uri and not any(s.url == uri for s in extracted_sources):
                                extracted_sources.append(
                                    ResearchSource(
                                        title=title or "Web Reference",
                                        url=uri,
                                        snippet=None,
                                    )
                                )

        # 2. Step 2: Structure grounded knowledge into strong Pydantic schema
        structuring_prompt = (
            f"Here is the raw grounded research material collected on topic '{topic}':\n\n"
            f"{raw_research_text}\n\n"
            f"Please structure this research into a comprehensive ResearchReport. "
            f"Extract individual findings with topic labels, claims, detailed explanations, and confidence scores. "
            f"Write an overall synthesis summary."
        )

        structured_report = await self.generate_structured(
            prompt=structuring_prompt,
            response_schema=ResearchReport,
            system_instruction="You are a data structuring assistant. Format research into the exact JSON schema provided.",
        )

        # Combine with discovered sources and previous findings if this is an iteration
        combined_sources = list(structured_report.sources)
        for s in extracted_sources:
            if not any(existing.url == s.url for existing in combined_sources):
                combined_sources.append(s)

        combined_findings = list(structured_report.findings)
        if previous_report:
            for old_s in previous_report.sources:
                if not any(existing.url == old_s.url for existing in combined_sources):
                    combined_sources.append(old_s)
            for old_f in previous_report.findings:
                if not any(
                    existing.claim == old_f.claim for existing in combined_findings
                ):
                    combined_findings.append(old_f)

        return ResearchReport(
            topic=topic,
            findings=combined_findings,
            sources=combined_sources,
            summary=structured_report.summary,
            raw_notes=raw_research_text,
            iteration=iteration,
        )
