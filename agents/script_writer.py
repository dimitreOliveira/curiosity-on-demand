"""ScriptWriter agent generating scene-by-scene narration scripts from structured research."""

import logging
import re

from agents.base import BaseAgent
from config.settings import Settings, get_settings
from core.models import ResearchReport, Script

logger = logging.getLogger(__name__)


def parse_duration_to_seconds(target_duration: str, default_seconds: int = 600) -> int:
    """Parse duration string into total duration in seconds.

    Supports formats like '5 minutes', '2 min', '30 seconds', '90s', '~10 minutes'.
    """
    if not target_duration:
        return default_seconds

    text = target_duration.lower().strip()

    # Match MM:SS or M:SS e.g. "1:30", "01:30", "0:45", "2:00"
    mmss_match = re.search(r"(?:^|[^\w:])(\d{1,2}):(\d{2})(?!\d)", text)
    if mmss_match:
        m, s = int(mmss_match.group(1)), int(mmss_match.group(2))
        return max(10, m * 60 + s)

    # Match composite min + sec e.g. "1m 30s", "1 min 30 sec", "1m30s"
    min_sec_match = re.search(
        r"(?<!:)\b(\d+)\s*(?:minutes?|mins?|m)\s*(\d+)\s*(?:seconds?|secs?|s)\b",
        text,
    )
    if min_sec_match:
        m, s = int(min_sec_match.group(1)), int(min_sec_match.group(2))
        return max(10, m * 60 + s)

    # Match seconds e.g. "30s", "45 seconds", "90 sec", "45-second"
    sec_match = re.search(r"(?<!:)\b(\d+(?:\.\d+)?)[-\s]*(?:seconds?|secs?|s)\b", text)
    if sec_match:
        return max(10, int(float(sec_match.group(1))))

    # Match minutes e.g. "5m", "2 min", "10 minutes", "~5 mins", "3-minute"
    min_match = re.search(r"(?<!:)\b(\d+(?:\.\d+)?)[-\s]*(?:minutes?|mins?|m)\b", text)
    if min_match:
        return max(10, int(float(min_match.group(1)) * 60))

    # Match raw numbers assuming minutes if small (<=60), seconds if large (>60)
    num_match = re.search(r"(\d+(?:\.\d+)?)", text)
    if num_match:
        val = float(num_match.group(1))
        if val > 60:
            return int(val)
        return max(10, int(val * 60))

    return default_seconds


def calculate_scene_budget(
    target_seconds: int,
    ideal_scene_seconds: int = 30,
    min_scenes: int = 4,
    max_scenes: int = 30,
) -> tuple[int, int, int]:
    """Calculate (min_scenes, max_scenes, target_scene_duration_seconds) for a target video duration.

    Aimed at multi-act educational visual storytelling with rich 3-act scenes every 25-35 seconds.
    """
    if target_seconds <= 0:
        target_seconds = 600

    raw_target_scenes = round(target_seconds / ideal_scene_seconds)
    target_scene_count = max(min_scenes, min(max_scenes, raw_target_scenes))

    lower_bound = max(min_scenes, target_scene_count - 1)
    upper_bound = min(max_scenes, target_scene_count + 1)
    upper_bound = max(upper_bound, lower_bound)

    avg_duration = max(10, round(target_seconds / target_scene_count))
    return lower_bound, upper_bound, avg_duration


SCRIPT_WRITER_SYSTEM_PROMPT = """You are a Master Scriptwriter and Educational Storyteller for Curiosity On Demand, a high-production educational channel.
Your mission is to transform structured research into an engaging, scene-by-scene narration script with detailed, cinematic visual choreography and accurate pacing for animators.

Your principles:
1. Narrative Flow & Pacing:
   - Scene 1 (The Hook): Hook the audience immediately with an intriguing premise, paradox, visual thought experiment, or high-stakes question.
   - Middle Scenes (The Core Journey): Walk the viewer through key mechanisms, historical context, surprising insights, and intuitive analogies based on the research. Keep the narrative progression brisk, introducing a new visual metaphor, mechanism, or perspective in each scene.
   - Final Scene (The Resolution): Deliver a memorable conclusion, profound takeaway, or philosophical perspective that ties everything together.
2. Scene Breakdown & Dynamic Pacing (CRITICAL):
   - Each animated scene is rendered as a complete 3-act visual sequence (Entrance, Transformation, Climax) lasting approximately 25 to 35 seconds (~45 to 60 spoken words).
   - YOU MUST STRICTLY COMPLY with the requested Target Scene Count range. Do NOT collapse longer videos into only 3 or 4 scenes. For example, a 5-minute video MUST be budgeted across 9 to 11 distinct scenes (~28–30s each).
   - Spoken educational voiceover proceeds at roughly 100–120 words per minute (~1.7–2.0 words per second) to accommodate natural articulation, emphasis, and pauses. For each scene, tightly calibrate the narration word count directly to its duration_seconds (e.g., ~48–55 words for a 28–30 second scene). Do NOT exceed this word count, or the spoken audio will run longer than the budgeted scene duration.
   - For each scene, provide:
     * scene_number: Sequential integer (1, 2, 3...)
     * title: Catchy, descriptive scene title
     * summary: Clear summary of what this segment covers conceptually
     * description: Rich, cinematic visual choreography. Specify:
       - Focal Entities & Rigging: Specific actors, diagrams, machines, or metaphors and how their components move (e.g., oscillating limbs, rotating gears, pulsing energy fields).
       - Environment & Lighting: Depth layers, background gradients, light beam sources, and color shifts.
       - Dynamic Action & Climax: Motion trajectories, particle bursts, screen shakes, cinematic title reveals, or illustrative transformations that trigger at key moments in the scene.
     * duration_seconds: Integer estimated duration for this scene in seconds based on narration length and total target duration (budgeted at 25–35s per scene).
     * narration: The exact, conversational, punchy voiceover script to be spoken aloud. Provide sufficient narration depth to fill the scene's duration. Write pure spoken words only—do NOT embed bracketed stage directions like [pause] or [dramatic pause] in the base narration (vocal tags are added later by the audio director).
3. Tone & Cadence:
   - Engaging, clear, accessible, and intellectually stimulating (in the style of Veritasium, Kurzgesagt, or 3Blue1Brown).
   - Use natural transitions between scenes to smoothly link adjacent concepts.
4. Handling Feedback & Revisions:
   - When previous script and user feedback are provided, modify or rewrite scenes to address the feedback while maintaining consistent tone, timing, dynamic scene count, and cohesive narrative flow.
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
        target_seconds = parse_duration_to_seconds(target_duration)
        min_scenes, max_scenes, avg_scene_dur = calculate_scene_budget(target_seconds)

        logger.info(
            "Generating script for topic '%s' (Guided feedback: %s, Duration: %s [%ds], Scenes: %d-%d [%ds/scene])",
            topic,
            bool(feedback),
            target_duration,
            target_seconds,
            min_scenes,
            max_scenes,
            avg_scene_dur,
        )

        sections_text = "\n\n".join(
            f"### Subtopic: {s.topic}\n{s.content}" for s in research_report.sections
        )

        research_context = (
            f"Topic: {topic}\n"
            f"Target Video Duration: {target_duration} (~{target_seconds} seconds total)\n"
            f"Target Scene Count: Exactly {min_scenes} to {max_scenes} scenes\n"
            f"Average Scene Duration: ~{avg_scene_dur} seconds (25–35s each)\n\n"
            f"Research Summary:\n{research_report.summary}\n\n"
            f"Researched Subtopics & Knowledge Base:\n"
            f"{sections_text}"
        )

        if feedback and previous_script:
            prev_scenes_text = "\n\n".join(
                f"Scene {s.scene_number} - {s.title} ({s.duration_seconds}s):\n"
                f"Summary: {s.summary}\n"
                f"Visual Description: {s.description}\n"
                f"Narration: {s.narration}"
                for s in previous_script.scenes
            )
            prompt = (
                f"{research_context}\n\n"
                f"===================================================\n"
                f"PACING & SCENE BUDGET INSTRUCTIONS:\n"
                f"- Video Duration: {target_duration} (~{target_seconds}s total)\n"
                f"- Required Scenes: Exactly {min_scenes} to {max_scenes} distinct scenes\n"
                f"- Duration per Scene: ~{avg_scene_dur}s (25–35s each)\n"
                f"===================================================\n\n"
                f"PREVIOUS SCRIPT:\n"
                f"Summary: {previous_script.summary}\n\n"
                f"{prev_scenes_text}\n"
                f"===================================================\n\n"
                f"CRITICAL USER FEEDBACK & REVISION INSTRUCTIONS:\n"
                f"{feedback}\n\n"
                f"Please produce a revised Script schema addressing the user's feedback while preserving "
                f"the strong elements of the narration and budgeting scene duration_seconds to meet the {target_duration} target "
                f"across {min_scenes} to {max_scenes} dynamic scenes."
            )
        else:
            prompt = (
                f"{research_context}\n\n"
                f"===================================================\n"
                f"PACING & SCENE BUDGET INSTRUCTIONS (CRITICAL):\n"
                f"- Video Duration: {target_duration} (~{target_seconds}s total)\n"
                f"- Required Scenes: Exactly {min_scenes} to {max_scenes} distinct scenes\n"
                f"- Duration per Scene: ~{avg_scene_dur}s (25–35s each, ~45–60 words of narration per scene calibrated at ~1.7–2.0 words/second)\n"
                f"===================================================\n\n"
                f"Please craft a complete, engaging scene-by-scene narration Script for a {target_duration} educational video. "
                f"Break down the topic into exactly {min_scenes} to {max_scenes} logical, visually dynamic scenes. "
                f"For each scene, provide a summary, detailed visual description for animators, "
                f"duration_seconds (~{avg_scene_dur}s), and full spoken narration."
            )

        script = await self.generate_structured(
            prompt=prompt,
            response_schema=Script,
            system_instruction=SCRIPT_WRITER_SYSTEM_PROMPT,
        )

        # Guarantee topic matches and ensure valid positive duration_seconds per scene
        script.topic = topic
        for scene in script.scenes:
            if scene.duration_seconds <= 0:
                words = len(scene.narration.split())
                scene.duration_seconds = max(5, int(words / 2.3) + 2)

        return script
