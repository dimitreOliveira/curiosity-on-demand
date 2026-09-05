"""Unified AnimatorAgent orchestrating visual style planning and scene-by-scene animation."""

import logging

from agents.animation_planner import AnimationPlannerAgent
from agents.base import BaseAgent
from agents.scene_animator import SceneAnimatorAgent
from config.settings import Settings, get_settings
from core.models import (
    AnimationStoryboard,
    AnimationStyle,
    SceneAnimation,
    Script,
    ScriptScene,
)

logger = logging.getLogger(__name__)


class AnimatorAgent(BaseAgent):
    """Coordinating animator agent delegating to AnimationPlannerAgent and SceneAnimatorAgent."""

    def __init__(self, settings: Settings | None = None):
        cfg = settings or get_settings()
        super().__init__(settings=cfg, model_name=cfg.animator_model)
        self.planner = AnimationPlannerAgent(settings=cfg)
        self.scene_animator = SceneAnimatorAgent(settings=cfg)

    async def determine_style_and_sample(
        self,
        topic: str,
        script: Script,
        feedback: str | None = None,
        previous_style: AnimationStyle | None = None,
    ) -> tuple[AnimationStyle, SceneAnimation]:
        """Formulate visual style via AnimationPlannerAgent and generate Scene 1 animation code."""
        from core.cost_tracker import (
            PipelineComponent,
            current_project_id,
            track_component,
        )

        proj_id = current_project_id.get() or ""

        with track_component(proj_id, PipelineComponent.STYLE_PLANNING):
            style = await self.planner.plan_style(
                topic=topic,
                script=script,
                feedback=feedback,
                previous_style=previous_style,
            )

        scene_1 = script.scenes[0] if script.scenes else None
        if not scene_1:
            raise RuntimeError(
                "Cannot generate animation sample: script contains no scenes."
            )

        with track_component(proj_id, PipelineComponent.SCENE_ANIMATION):
            scene_1_anim = await self.scene_animator.animate_scene(
                topic=topic,
                scene=scene_1,
                style=style,
                duration_seconds=scene_1.duration_seconds,
            )

        return style, scene_1_anim

    async def generate_scene_animation(
        self,
        topic: str,
        scene: ScriptScene,
        style: AnimationStyle,
        duration_seconds: int | None = None,
    ) -> SceneAnimation:
        """Generate standalone HTML/SVG/Canvas animation code for an individual scene."""
        from core.cost_tracker import (
            PipelineComponent,
            current_project_id,
            track_component,
        )

        proj_id = current_project_id.get() or ""
        with track_component(proj_id, PipelineComponent.SCENE_ANIMATION):
            return await self.scene_animator.animate_scene(
                topic=topic,
                scene=scene,
                style=style,
                duration_seconds=duration_seconds,
            )

    async def generate_full_storyboard(
        self,
        topic: str,
        script: Script,
        style: AnimationStyle,
        sample_scene_1: SceneAnimation | None = None,
        default_duration: int | None = None,
    ) -> AnimationStoryboard:
        """Generate animations for all scenes using SceneAnimatorAgent in parallel."""
        from core.cost_tracker import (
            PipelineComponent,
            current_project_id,
            track_component,
        )

        proj_id = current_project_id.get() or ""
        with track_component(proj_id, PipelineComponent.SCENE_ANIMATION):
            return await self.scene_animator.animate_storyboard(
                topic=topic,
                script=script,
                style=style,
                sample_scene_1=sample_scene_1,
                default_duration=default_duration,
            )


__all__ = [
    "AnimationPlannerAgent",
    "AnimatorAgent",
    "SceneAnimatorAgent",
]
