"""Unified NarratorAgent coordinating narration planning and speech generation."""

import logging
from pathlib import Path

from agents.base import BaseAgent
from agents.narration_generator import NarrationGeneratorAgent
from agents.narration_planner import NarrationPlannerAgent
from config.settings import Settings, get_settings
from core.models import (
    NarrationPlan,
    NarrationStoryboard,
    SceneAudio,
    SceneNarrationPlan,
    Script,
)

logger = logging.getLogger(__name__)


class NarratorAgent(BaseAgent):
    """Coordinating narration agent delegating to NarrationPlannerAgent and NarrationGeneratorAgent."""

    def __init__(self, settings: Settings | None = None):
        cfg = settings or get_settings()
        super().__init__(settings=cfg, model_name=cfg.tts_model)
        self.planner = NarrationPlannerAgent(settings=cfg)
        self.generator = NarrationGeneratorAgent(settings=cfg)

    async def determine_plan_and_sample(
        self,
        topic: str,
        script: Script,
        feedback: str | None = None,
        previous_plan: NarrationPlan | None = None,
        output_dir: Path | None = None,
    ) -> tuple[NarrationPlan, SceneAudio]:
        """Formulate complete narration plan and synthesize Scene 1 voice sample for user approval."""
        from core.cost_tracker import (
            PipelineComponent,
            current_project_id,
            track_component,
        )

        proj_id = current_project_id.get() or ""

        with track_component(proj_id, PipelineComponent.NARRATION_PLANNING):
            plan = await self.planner.plan_narration(
                topic=topic,
                script=script,
                feedback=feedback,
                previous_plan=previous_plan,
            )

        if not plan.scenes:
            raise RuntimeError(
                "Cannot generate narration sample: narration plan contains no scenes."
            )

        target_dir = output_dir or (self.settings.audio_dir / "samples")
        target_dir.mkdir(parents=True, exist_ok=True)
        sample_path = target_dir / "scene_1_sample.wav"

        scene_1_plan = plan.scenes[0]
        with track_component(proj_id, PipelineComponent.VOICE_SYNTHESIS):
            sample_audio = await self.generator.generate_scene_audio(
                topic=topic,
                plan=plan,
                scene=scene_1_plan,
                output_path=sample_path,
            )

        return plan, sample_audio

    async def generate_scene_audio(
        self,
        topic: str,
        plan: NarrationPlan,
        scene: SceneNarrationPlan,
        output_path: Path,
    ) -> SceneAudio:
        """Synthesize voiceover audio for an individual scene."""
        return await self.generator.generate_scene_audio(
            topic=topic,
            plan=plan,
            scene=scene,
            output_path=output_path,
        )

    async def generate_full_narration(
        self,
        topic: str,
        plan: NarrationPlan,
        output_dir: Path | None = None,
        sample_scene_1: SceneAudio | None = None,
        concurrency: int | None = None,
    ) -> NarrationStoryboard:
        """Generate audio clips for all scenes in parallel using NarrationGeneratorAgent."""
        from core.cost_tracker import (
            PipelineComponent,
            current_project_id,
            track_component,
        )

        proj_id = current_project_id.get() or ""
        target_dir = output_dir or (self.settings.audio_dir / "storyboard")

        with track_component(proj_id, PipelineComponent.VOICE_SYNTHESIS):
            return await self.generator.generate_storyboard_audio(
                topic=topic,
                plan=plan,
                output_dir=target_dir,
                sample_scene_1=sample_scene_1,
                concurrency=concurrency,
            )


__all__ = [
    "NarrationGeneratorAgent",
    "NarrationPlannerAgent",
    "NarratorAgent",
]
