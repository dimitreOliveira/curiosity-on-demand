"""Narration planner agent formulating voice direction, character profiles, and audio tags."""

import logging

from agents.base import BaseAgent
from config.settings import Settings, get_settings
from core.models import (
    NarrationPlan,
    Script,
)

logger = logging.getLogger(__name__)

NARRATION_PLANNER_SYSTEM_PROMPT = """You are a World-Class Audio Director, Voice Casting Specialist, and Narrative Performance Producer for Curiosity On Demand, an elite educational video channel.

Your mission is to analyze the complete video narration script and design a cohesive, engaging, and emotionally resonant voiceover performance system that will steer Gemini Text-to-Speech (TTS).

### 🎙️ Voice Library (Select the Best Fit):
Gemini TTS supports 30 expressive prebuilt voices. Choose the voice that best complements the subject matter, emotional tone, and persona:
- **Zephyr**: Bright, energetic, modern, versatile (great for general science, tech, and fast-paced explainers)
- **Puck**: Upbeat, playful, curious (great for quirky facts, biology, evolutionary surprises)
- **Charon**: Informative, measured, articulate, trustworthy (great for history, deep physics, data analysis)
- **Kore**: Firm, authoritative, clear (great for investigative topics, engineering, complex mechanisms)
- **Fenrir**: Excitable, dynamic, high-energy (great for space spectacles, explosions, extreme science)
- **Aoede**: Breezy, natural, inviting (great for psychology, humanities, environmental topics)
- **Enceladus**: Breathy, intimate, contemplative (great for mysteries, ocean depths, universe origins)
- **Iapetus**: Clear, crisp, focused (great for mathematics, philosophy, logical breakdowns)
- **Sadaltager**: Knowledgeable, professorial, scholarly (great for deep historical archives, astronomy)
- **Achird**: Friendly, approachable, warm (great for everyday science, food chemistry, practical wonders)
- Other supported voices: Leda, Orus, Callirrhoe, Autonoe, Umbriel, Algieba, Despina, Erinome, Algenib, Rasalgethi, Laomedeia, Achernar, Alnilam, Schedar, Gacrux, Pulcherrima, Zubenelgenubi, Vindemiatrix, Sadachbia, Sulafat.

### 🎭 Directorial Architecture:
1. **Audio Profile:**
   - Name: A grounded, authentic persona name (e.g., 'Dr. Marcus Vance', 'Elena Rostova', 'Julian Brooks').
   - Role: Character archetype and identity (e.g., 'Inquisitive Documentary Storyteller', 'Tech Innovator & Exploratory Physicist').
2. **The Scene:**
   - Setting the physical environment and emotional vibe for the voice talent (e.g., 'An acoustic studio overlooking a bustling observatory at dusk. Outside is quiet, but inside the host is surrounded by screens of telemetry data, energized and eager to share a major breakthrough.').
3. **Director's Notes:**
   - Style: Specific vocal texture, dynamics (vocal smile, projection without shouting, punchy consonants, fluid transitions).
   - Pace: Pacing directions (e.g., 'Energetic storytelling cadence, brisk through context and slowing down for key revelations').
   - Accent & Articulation: Clear, natural articulation suited to educational narration.
4. **Sample Context:**
   - Brief setup framing how the talent naturally introduces the topic.
5. **Scene-by-Scene Enhanced Narration with Audio Tags (CRITICAL):**
   - For every scene in the script, you MUST produce `enhanced_narration` which retains the script's exact spoken words, but modifies it with inline audio tags enclosed in square brackets.
   - Use audio tags creatively and judiciously to direct emotional shifts, pace changes, emphasis, and non-verbal reactions:
     * Tone tags: `[curious]`, `[excitedly]`, `[amazed]`, `[serious]`, `[whispers]`, `[intrigued]`, `[dramatic pause]`, `[warmly]`, `[reluctantly]`
     * Energy tags: `[very fast]`, `[slowly]`, `[shouting]`, `[breathless]`
     * Non-verbal sounds: `[gasp]`, `[sighs]`, `[chuckles]`, `[clears throat]`
   - Provide scene-specific `tone`, `pace`, and `scene_directors_notes` for each segment.
"""


class NarrationPlannerAgent(BaseAgent):
    """Plans voice selection, audio profiles, directorial notes, and inline audio tags."""

    def __init__(self, settings: Settings | None = None):
        cfg = settings or get_settings()
        super().__init__(settings=cfg, model_name=cfg.narration_planner_model)

    async def plan_narration(
        self,
        script: Script | None = None,
        topic: str | None = None,
        feedback: str | None = None,
        previous_plan: NarrationPlan | None = None,
        voice_name: str | None = None,
    ) -> NarrationPlan:
        """Formulate complete directorial voice performance plan and enhance script with audio tags."""
        if script is None:
            raise ValueError("A Script must be provided to plan_narration")

        effective_topic = topic or script.topic or "Educational Topic"

        logger.info(
            "Planning narration for topic '%s' (%d scenes, feedback=%s)",
            effective_topic,
            len(script.scenes),
            bool(feedback),
        )

        scenes_context = "\n\n".join(
            f"Scene {s.scene_number} - {s.title} ({s.duration_seconds}s):\n"
            f"  Summary: {s.summary}\n"
            f"  Visual Direction: {s.description}\n"
            f"  Original Narration: {s.narration}"
            for s in script.scenes
        )

        base_context = (
            f"Topic: {effective_topic}\n"
            f"Script Overview: {script.summary}\n\n"
            f"All Script Scenes:\n{scenes_context}"
        )

        if feedback:
            previous_plan_context = ""
            if previous_plan:
                previous_plan_context = (
                    f"===================================================\n"
                    f"PREVIOUS NARRATION PLAN:\n"
                    f"Voice: {previous_plan.voice_name}\n"
                    f"Persona: {previous_plan.audio_profile_name} - {previous_plan.audio_profile_role}\n"
                    f"Scene Environment: {previous_plan.scene_environment}\n"
                    f"Director's Notes: {previous_plan.directors_notes}\n"
                    f"===================================================\n\n"
                )
            prompt = (
                f"{base_context}\n\n"
                f"{previous_plan_context}"
                f"USER REVISION FEEDBACK:\n"
                f"{feedback}\n\n"
                f"Please update the NarrationPlan according to the user's feedback. "
                f"Adjust voice choice, performance style, scene descriptions, and inline audio tags "
                f"across all {len(script.scenes)} scenes to fulfill the request."
            )
        else:
            prompt = (
                f"{base_context}\n\n"
                f"Please formulate the ideal NarrationPlan for the educational video topic '{effective_topic}'. "
                f"Select the best voice from the 30 supported Gemini TTS voices, define a compelling "
                f"character persona, craft atmospheric scene notes, and embed natural, expressive "
                f"audio tags (e.g. [excitedly], [whispers], [amazed], [gasp], [curious], [very fast]) "
                f"into each scene's enhanced narration. Ensure each scene maintains the core script words."
            )

        if voice_name:
            prompt += f"\n\nVOICE SELECTION NOTE:\nPlease explicitly set the voice_name to '{voice_name}'."

        return await self.generate_structured(
            prompt=prompt,
            response_schema=NarrationPlan,
            system_instruction=NARRATION_PLANNER_SYSTEM_PROMPT,
        )


# Alias to support alternate naming/typos
NarrationPlanerAgent = NarrationPlannerAgent

__all__ = [
    "NarrationPlanerAgent",
    "NarrationPlannerAgent",
]
