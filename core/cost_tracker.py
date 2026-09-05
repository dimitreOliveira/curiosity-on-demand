"""Cost and token usage tracking across the Curiosity On Demand pipeline."""

import logging
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from enum import Enum
from typing import TYPE_CHECKING, Any

from core.models import ComponentUsage, ProjectUsageSummary

if TYPE_CHECKING:
    from core.database import DatabaseManager

logger = logging.getLogger(__name__)

# Context variables for non-invasive component execution attribution
current_project_id: ContextVar[str | None] = ContextVar(
    "current_project_id", default=None
)
current_component: ContextVar[str | None] = ContextVar(
    "current_component", default=None
)


class PipelineComponent(str, Enum):
    """Pipeline stages and agents that consume LLM, search, or compute resources."""

    RESEARCH = "Research & Grounding"
    EVALUATION = "Research Evaluation"
    SCRIPT_WRITING = "Narration Scriptwriting"
    NARRATION_PLANNING = "Audio Direction & Planning"
    VOICE_SYNTHESIS = "Voice Synthesis (TTS)"
    STYLE_PLANNING = "Visual Style Planning"
    SCENE_ANIMATION = "Scene Canvas Coding"
    VIDEO_RENDERING = "Video Rendering & Assembly"


# Pricing rates based on Google GenAI API (rates per 1,000,000 tokens / per unit)
DEFAULT_PRICING: dict[str, dict[str, float]] = {
    # Gemini LLM
    ## Flash-lite
    "gemini-3.5-flash-lite": {
        "prompt_rate_per_m": 0.30,
        "output_rate_per_m": 2.50,
    },
    ## Flash
    "gemini-3.8-flash": {
        "prompt_rate_per_m": 0.75,  # 1.50,
        "output_rate_per_m": 3.75,  # 7.50,
    },
    "gemini-3.7-flash": {
        "prompt_rate_per_m": 0.75,  # 1.50,
        "output_rate_per_m": 3.75,  # 7.50,
    },
    ## Pro
    "gemini-3.1-pro-preview": {
        "prompt_rate_per_m": 2.00,
        "output_rate_per_m": 12.00,
    },
    # Gemini TTS
    ## Flash
    "gemini-3.1-flash-tts-preview": {
        "prompt_rate_per_m": 1.00,
        "output_rate_per_m": 20.00,  # Audio candidate tokens
    },
    ## Pro
    "gemini-2.5-pro-preview-tts": {
        "prompt_rate_per_m": 1.00,
        "output_rate_per_m": 20.00,  # Audio candidate tokens
    },
}

# Fallback rates for unspecified models
DEFAULT_FALLBACK_RATES: dict[str, float] = {
    "prompt_rate_per_m": 0.10,
    "output_rate_per_m": 0.40,
}

# Google Search Grounding: $35.00 per 1,000 queries ($0.035 / query)
GROUNDING_QUERY_RATE: float = 35.0 / 1000.0


@contextmanager
def track_component(
    project_id: str, component: PipelineComponent | str
) -> Generator[None, None, None]:
    """Context manager to attribute LLM and API calls to a specific project and component."""
    comp_val = (
        component.value if isinstance(component, PipelineComponent) else str(component)
    )
    tok_proj = current_project_id.set(project_id)
    tok_comp = current_component.set(comp_val)
    try:
        yield
    finally:
        current_project_id.reset(tok_proj)
        current_component.reset(tok_comp)


@asynccontextmanager
async def async_track_component(
    project_id: str, component: PipelineComponent | str
) -> AsyncGenerator[None, None]:
    """Async context manager to attribute LLM and API calls to a specific project and component."""
    comp_val = (
        component.value if isinstance(component, PipelineComponent) else str(component)
    )
    tok_proj = current_project_id.set(project_id)
    tok_comp = current_component.set(comp_val)
    try:
        yield
    finally:
        current_project_id.reset(tok_proj)
        current_component.reset(tok_comp)


class CostTracker:
    """Tracks token consumption, search queries, and calculates costs across pipeline components."""

    def __init__(
        self,
        db_manager: "DatabaseManager | None" = None,
        pricing: dict[str, dict[str, float]] | None = None,
        grounding_rate: float = GROUNDING_QUERY_RATE,
    ):
        self.db = db_manager
        self.pricing = pricing or DEFAULT_PRICING
        self.grounding_rate = grounding_rate
        # In-memory storage for testing or offline mode
        self._in_memory_logs: dict[str, list[dict[str, Any]]] = {}

    def calculate_cost(
        self,
        model_name: str,
        prompt_tokens: int,
        output_tokens: int,
        grounding_queries: int = 0,
        audio_duration_seconds: float = 0.0,
    ) -> float:
        """Calculate estimated cost in USD based on model pricing rate card."""
        normalized_name = model_name.lower().strip()
        rates = self.pricing.get(normalized_name, DEFAULT_FALLBACK_RATES)

        prompt_rate = rates.get("prompt_rate_per_m", 0.10)
        output_rate = rates.get("output_rate_per_m", 0.40)

        token_cost = (prompt_tokens * prompt_rate / 1_000_000.0) + (
            output_tokens * output_rate / 1_000_000.0
        )

        grounding_cost = grounding_queries * self.grounding_rate
        total_cost = token_cost + grounding_cost
        return round(total_cost, 6)

    async def record_usage(
        self,
        project_id: str,
        component: PipelineComponent | str,
        model_name: str,
        prompt_tokens: int = 0,
        output_tokens: int = 0,
        grounding_queries: int = 0,
        audio_duration_seconds: float = 0.0,
    ) -> ComponentUsage:
        """Record an API usage event to database and in-memory accumulator."""
        comp_str = (
            component.value
            if isinstance(component, PipelineComponent)
            else str(component)
        )
        cost_usd = self.calculate_cost(
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            grounding_queries=grounding_queries,
            audio_duration_seconds=audio_duration_seconds,
        )

        record_dict = {
            "project_id": project_id,
            "component": comp_str,
            "model_name": model_name,
            "prompt_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "total_tokens": prompt_tokens + output_tokens,
            "grounding_queries": grounding_queries,
            "audio_duration_seconds": audio_duration_seconds,
            "cost_usd": cost_usd,
        }

        # Store in-memory
        if project_id not in self._in_memory_logs:
            self._in_memory_logs[project_id] = []
        self._in_memory_logs[project_id].append(record_dict)

        # Store in database if DB manager is connected
        if self.db is not None:
            try:
                await self.db.record_usage(
                    project_id=project_id,
                    component=comp_str,
                    model_name=model_name,
                    prompt_tokens=prompt_tokens,
                    output_tokens=output_tokens,
                    grounding_queries=grounding_queries,
                    audio_duration_seconds=audio_duration_seconds,
                    cost_usd=cost_usd,
                )
            except Exception as err:  # noqa: BLE001
                logger.warning(
                    "Failed to record usage in database for project %s: %s",
                    project_id,
                    err,
                )

        logger.debug(
            "Recorded usage for %s [%s]: %d prompt, %d output, %d searches, $%.5f",
            project_id,
            comp_str,
            prompt_tokens,
            output_tokens,
            grounding_queries,
            cost_usd,
        )

        return ComponentUsage(
            component=comp_str,
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            total_tokens=prompt_tokens + output_tokens,
            grounding_queries=grounding_queries,
            audio_duration_seconds=audio_duration_seconds,
            estimated_cost_usd=cost_usd,
            call_count=1,
        )

    async def get_project_summary(self, project_id: str) -> ProjectUsageSummary:
        """Aggregate all component usages for a project session into a ProjectUsageSummary."""
        # Query DB if available
        if self.db is not None:
            try:
                return await self.db.get_project_usage_summary(project_id)
            except Exception as err:  # noqa: BLE001
                logger.warning(
                    "Failed to retrieve usage summary from DB for %s: %s",
                    project_id,
                    err,
                )

        # Fallback to in-memory logs
        logs = self._in_memory_logs.get(project_id, [])
        components_map: dict[str, ComponentUsage] = {}

        for entry in logs:
            comp_name = entry["component"]
            if comp_name not in components_map:
                components_map[comp_name] = ComponentUsage(
                    component=comp_name,
                    model_name=entry["model_name"],
                    prompt_tokens=0,
                    output_tokens=0,
                    total_tokens=0,
                    grounding_queries=0,
                    audio_duration_seconds=0.0,
                    estimated_cost_usd=0.0,
                    call_count=0,
                )
            c = components_map[comp_name]
            c.prompt_tokens += entry["prompt_tokens"]
            c.output_tokens += entry["output_tokens"]
            c.total_tokens += entry["total_tokens"]
            c.grounding_queries += entry["grounding_queries"]
            c.audio_duration_seconds += entry["audio_duration_seconds"]
            c.estimated_cost_usd += entry["cost_usd"]
            c.call_count += 1

        components_list = list(components_map.values())
        total_cost = sum(c.estimated_cost_usd for c in components_list)
        total_prompt = sum(c.prompt_tokens for c in components_list)
        total_output = sum(c.output_tokens for c in components_list)
        total_tokens = total_prompt + total_output
        total_queries = sum(c.grounding_queries for c in components_list)
        total_audio = sum(c.audio_duration_seconds for c in components_list)
        total_calls = sum(c.call_count for c in components_list)

        return ProjectUsageSummary(
            project_id=project_id,
            total_cost_usd=round(total_cost, 4),
            total_prompt_tokens=total_prompt,
            total_output_tokens=total_output,
            total_tokens=total_tokens,
            total_grounding_queries=total_queries,
            total_audio_duration_seconds=round(total_audio, 1),
            total_calls=total_calls,
            components=components_list,
        )

    def format_short_badge(self, summary: ProjectUsageSummary) -> str:
        """Format a single-line summary badge suitable for Telegram video captions."""
        return (
            f"💰 *Est. Cost:* `${summary.total_cost_usd:.4f}` "
            f"({summary.total_tokens:,} tokens)"
        )

    def format_telegram_report(
        self, summary: ProjectUsageSummary, include_free_render: bool = True
    ) -> str:
        """Format an aesthetic, detailed Markdown cost breakdown message for Telegram."""
        lines = [
            "📊 *Video Generation Resource & Cost Breakdown*",
            "",
        ]

        component_emojis = {
            PipelineComponent.RESEARCH.value: "🔍",
            PipelineComponent.EVALUATION.value: "📋",
            PipelineComponent.SCRIPT_WRITING.value: "✍️",
            PipelineComponent.NARRATION_PLANNING.value: "🎙️",
            PipelineComponent.VOICE_SYNTHESIS.value: "🗣️",
            PipelineComponent.STYLE_PLANNING.value: "🎨",
            PipelineComponent.SCENE_ANIMATION.value: "🎬",
            PipelineComponent.VIDEO_RENDERING.value: "⚙️",
        }

        if not summary.components:
            lines.append("_No billable API calls recorded for this session._")
        else:
            for comp in summary.components:
                emoji = component_emojis.get(comp.component, "🔹")
                details: list[str] = []

                if comp.grounding_queries > 0:
                    details.append(f"{comp.grounding_queries} searches")
                if comp.audio_duration_seconds > 0:
                    details.append(f"{comp.audio_duration_seconds:.1f}s audio")
                if comp.total_tokens > 0:
                    details.append(f"{comp.total_tokens:,} tok")

                details_str = f" ({', '.join(details)})" if details else ""
                lines.append(
                    f"{emoji} *{comp.component}:* `${comp.estimated_cost_usd:.4f}`{details_str}"
                )

        if include_free_render:
            lines.append("⚙️ *Video Assembly (FFmpeg):* `$0.0000` (Local compute)")

        lines.extend(
            [
                "━━━━━━━━━━━━━━━━━━━━━",
                f"💵 *Total Estimated Cost:* `${summary.total_cost_usd:.4f}`",
                (
                    f"📈 *Total Tokens Consumed:* {summary.total_tokens:,} "
                    f"({summary.total_prompt_tokens:,} in / {summary.total_output_tokens:,} out)"
                ),
            ]
        )

        if summary.total_grounding_queries > 0:
            lines.append(
                f"🌐 *Google Search Queries:* {summary.total_grounding_queries}"
            )
        if summary.total_audio_duration_seconds > 0:
            lines.append(
                f"⏱️ *Generated Voiceover Audio:* {summary.total_audio_duration_seconds:.1f}s"
            )

        return "\n".join(lines)


# Global singleton instance
_global_cost_tracker: CostTracker | None = None


def get_cost_tracker() -> CostTracker:
    """Retrieve global CostTracker instance."""
    global _global_cost_tracker
    if _global_cost_tracker is None:
        _global_cost_tracker = CostTracker()
    return _global_cost_tracker


def set_global_cost_tracker(tracker: CostTracker) -> None:
    """Set global CostTracker instance."""
    global _global_cost_tracker
    _global_cost_tracker = tracker
