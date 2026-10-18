"""Narration planner agent formulating voice direction, character profiles, and audio tags."""

import logging

from agents.base import BaseAgent
from config.settings import Settings, get_settings
from core.audio_utils import normalize_inline_audio_tags
from core.models import (
    NarrationPlan,
    Script,
)

logger = logging.getLogger(__name__)

NARRATION_PLANNER_SYSTEM_PROMPT = """You are a World-Class Audio Director, Voice Casting Specialist, and Narrative Performance Producer for Curiosity On Demand, an elite educational video channel.

Your mission is to analyze the complete video narration script and design a cohesive, engaging, and emotionally resonant voiceover performance system that will steer Gemini Text-to-Speech (`gemini-3.8-flash-tts`).

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
5. **Scene-by-Scene Enhanced Narration with Inline Audio Tags (CRITICAL):**
   - For every scene in the script, you MUST produce `enhanced_narration` which retains the script's exact spoken words, enhanced ONLY with valid **angle-bracket (`<...>`)** inline point-in-time vocal and pause tags supported by `gemini-3.8-flash-tts`.
   - **NEVER use square brackets (`[...]`)** or invent arbitrary inline stage directions (like `[dramatic pause]`, `[curious]`, `[excitedly]`, or `[very fast]`), because `gemini-3.8-flash-tts` treats the transcript as verbatim text and will read square-bracketed or non-vocal tags aloud!
   - **Supported Angle-Bracket Inline Tags (`<...>`)**:
     * **Pauses**: `<short pause>` (for a brief beat or hesitation), `<long pause>` (for a dramatic pause or major reveal)
     * **Breaths & sighs**: `<breath>`, `<heavy breath>`, `<exhales>`, `<sigh>`, `<sighs>`, `<phew>`
     * **Non-speech vocal reactions**: `<gasp>`, `<chuckle>`, `<chuckles>`, `<laugh>`, `<laughter>`, `<giggle>`, `<throat-clearing>`, `<cough>`, `<tsk>`, `<groan>`
     * **Hushed delivery (sparingly)**: `<whispers>`, `<whispering>`
   - **Sustained Style vs. Inline Tags**:
     * Place sustained emotional delivery, vocal attitude, and speed/pacing (e.g., curious, excited, amazed, serious, thoughtful, warm, brisk, slow) into the scene's `tone`, `pace`, and `scene_directors_notes` fields—NOT as inline tags in `enhanced_narration`.
     * For word-level emphasis inside `enhanced_narration`, CAPITALIZE key words (e.g., `"This is a VERY important point!"`) and use natural punctuation (`...`, `--`, `!`, `?`) paired with `<short pause>` or `<long pause>`.
   - **Whisper Tag Rule (IMPORTANT):** Minimize the use of `<whispers>` / `<whispering>` (and `[whisper]` / `[whispers]`) tags. In text-to-speech synthesis, whispering often sounds muffled, unclear, or unnatural in practice. DO NOT use `<whispers>` casually or as a default introductory tone. ONLY use `<whispers>` when the context makes a quiet whisper strictly necessary and genuinely compelling (e.g. sharing a confidential secret or a hushed dramatic mystery). Favor clear inline pauses (`<short pause>`, `<long pause>`) and subtle vocal reactions (`<gasp>`, `<breath>`, `<sigh>`) instead.
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
                f"Adjust voice choice, performance style, scene descriptions, and inline angle-bracket vocal tags "
                f"(e.g. <short pause>, <long pause>, <gasp>, <sigh>, <chuckles>, <breath>) "
                f"across all {len(script.scenes)} scenes to fulfill the request. "
                f"Never use square brackets [...]; put sustained emotional tone and pace in tone/pace/scene_directors_notes. "
                f"Remember to minimize whisper tags (<whispers>/<whispering> and [whisper]/[whispers]), reserving them only for when "
                f"a quiet whisper makes profound sense."
            )
        else:
            prompt = (
                f"{base_context}\n\n"
                f"Please formulate the ideal NarrationPlan for the educational video topic '{effective_topic}'. "
                f"Select the best voice from the 30 supported Gemini TTS voices, define a compelling "
                f"character persona, craft atmospheric scene notes, and embed natural, point-in-time "
                f"angle-bracket inline audio tags (ONLY valid tags such as <short pause>, <long pause>, <gasp>, "
                f"<sigh>, <chuckles>, <breath>, <heavy breath>, <throat-clearing>) into each scene's enhanced narration. "
                f"Never use square brackets [...] or inline tone adjectives; place sustained tone and pace in each scene's "
                f"tone, pace, and scene_directors_notes fields. Minimize whisper tags (<whispers>/<whispering> and [whisper]/[whispers]), "
                f"only using them when the scene context makes a quiet whisper strictly necessary. "
                f"Ensure each scene maintains the core script words."
            )

        if voice_name:
            prompt += f"\n\nVOICE SELECTION NOTE:\nPlease explicitly set the voice_name to '{voice_name}'."

        plan = await self.generate_structured(
            prompt=prompt,
            response_schema=NarrationPlan,
            system_instruction=NARRATION_PLANNER_SYSTEM_PROMPT,
        )

        for scene in plan.scenes:
            scene.enhanced_narration = normalize_inline_audio_tags(
                scene.enhanced_narration
            )

        return plan


# Alias to support alternate naming/typos
NarrationPlanerAgent = NarrationPlannerAgent

__all__ = [
    "NarrationPlanerAgent",
    "NarrationPlannerAgent",
]
