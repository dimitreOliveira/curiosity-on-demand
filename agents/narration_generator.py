"""Narration generator agent synthesizing natural-language directed speech via Gemini TTS."""

import asyncio
import base64
import logging
import mimetypes
from pathlib import Path
from typing import ClassVar

from google.genai import types

from agents.base import BaseAgent
from config.settings import Settings, get_settings
from core.audio_utils import (
    combine_wav_files,
    convert_to_wav,
    get_wav_duration,
    normalize_inline_audio_tags,
)
from core.models import (
    NarrationPlan,
    NarrationStoryboard,
    SceneAudio,
    SceneNarrationPlan,
)

logger = logging.getLogger(__name__)


def build_speech_prompt(
    plan: NarrationPlan,
    scene: SceneNarrationPlan | None = None,
    transcript: str | None = None,
) -> str:
    """Construct directorial Gemini TTS prompt incorporating Audio Profile, Scene, Director's Notes, and Transcript."""
    raw_text = transcript or (scene.enhanced_narration if scene else "")
    text_to_speak = normalize_inline_audio_tags(raw_text)

    scene_tone_line = f"Scene Tone: {scene.tone}" if scene and scene.tone else ""
    scene_pace_line = f"Scene Pace: {scene.pace}" if scene and scene.pace else ""
    scene_notes_line = (
        f"Specific Directorial Guidance: {scene.scene_directors_notes}"
        if scene and scene.scene_directors_notes
        else ""
    )

    directors_notes_block = "\n".join(
        line
        for line in [
            plan.directors_notes,
            scene_tone_line,
            scene_pace_line,
            scene_notes_line,
        ]
        if line
    )

    prompt = (
        f"# AUDIO PROFILE: {plan.audio_profile_name}\n"
        f'## "{plan.audio_profile_role}"\n\n'
        f"## THE SCENE: {plan.scene_environment}\n\n"
        f"### DIRECTOR'S NOTES\n"
        f"{directors_notes_block}\n\n"
        f"### SAMPLE CONTEXT\n"
        f"{plan.sample_context}\n\n"
        f"#### TRANSCRIPT\n"
        f"{text_to_speak}"
    )
    return prompt.strip()


class NarrationGeneratorAgent(BaseAgent):
    """Synthesizes expressive voiceover audio using Gemini TTS (gemini-3.8-flash-tts)."""

    DEFAULT_CONCURRENCY: ClassVar[int] = 3

    def __init__(self, settings: Settings | None = None):
        cfg = settings or get_settings()
        super().__init__(settings=cfg, model_name=cfg.tts_model)
        self.tts_model = cfg.tts_model

    async def generate_speech_audio(
        self,
        prompt: str,
        voice_name: str,
        output_path: Path,
        temperature: float = 1.0,
    ) -> Path:
        """Call Gemini TTS API and persist generated speech as a WAV audio file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        target_voice = voice_name or self.settings.default_tts_voice

        logger.info(
            "Generating speech audio with model '%s' (voice='%s') -> %s",
            self.tts_model,
            target_voice,
            output_path,
        )

        generate_content_config = types.GenerateContentConfig(
            temperature=temperature,
            response_modalities=["audio"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=target_voice
                    )
                )
            ),
        )

        response = await self.client.aio.models.generate_content(
            model=self.tts_model,
            contents=prompt,
            config=generate_content_config,
        )

        if not response:
            raise RuntimeError(
                f"No response returned from Gemini TTS model '{self.tts_model}'"
            )

        # Extract audio payload from response parts
        audio_buffer = bytearray()
        mime_type = "audio/L16;rate=24000"

        parts = getattr(response, "parts", None) or []
        candidates = getattr(response, "candidates", None)
        if not parts and candidates:
            for cand in candidates:
                if cand.content and cand.content.parts:
                    parts.extend(cand.content.parts)

        for part in parts:
            inline = getattr(part, "inline_data", None)
            if inline and inline.data:
                chunk = inline.data
                if isinstance(chunk, str):
                    chunk = base64.b64decode(chunk)
                audio_buffer.extend(chunk)
                if getattr(inline, "mime_type", None):
                    mime_type = inline.mime_type

        if not audio_buffer:
            # Fallback: check if text error was returned instead
            text_err = getattr(response, "text", "")
            raise RuntimeError(
                f"Gemini TTS returned no audio data. Response message: {text_err or 'Empty response'}"
            )

        data_bytes = bytes(audio_buffer)

        # Ensure valid WAV container format
        ext = mimetypes.guess_extension(mime_type)
        if ext != ".wav" or not data_bytes.startswith(b"RIFF"):
            data_bytes = convert_to_wav(data_bytes, mime_type)

        output_path.write_bytes(data_bytes)
        logger.info(
            "Speech audio saved to %s (%d bytes)",
            output_path,
            len(data_bytes),
        )

        # Record TTS speech generation usage
        try:
            audio_duration = get_wav_duration(output_path)
            await self._record_response_usage(
                response=response,
                model_name=self.tts_model,
                audio_duration_seconds=audio_duration,
            )
        except Exception as err:  # noqa: BLE001
            logger.debug("Failed to record TTS usage: %s", err)

        return output_path

    async def generate_scene_audio(
        self,
        topic: str,
        plan: NarrationPlan,
        scene: SceneNarrationPlan,
        output_path: Path,
    ) -> SceneAudio:
        """Synthesize voiceover narration for an individual scene."""
        prompt = build_speech_prompt(plan=plan, scene=scene)
        await self.generate_speech_audio(
            prompt=prompt,
            voice_name=plan.voice_name,
            output_path=output_path,
        )

        duration = get_wav_duration(output_path)
        file_size = output_path.stat().st_size if output_path.exists() else 0

        return SceneAudio(
            scene_number=scene.scene_number,
            audio_path=str(output_path),
            duration_seconds=duration,
            mime_type="audio/wav",
            file_size_bytes=file_size,
        )

    async def generate_storyboard_audio(
        self,
        topic: str,
        plan: NarrationPlan,
        output_dir: Path,
        sample_scene_1: SceneAudio | None = None,
        concurrency: int | None = None,
    ) -> NarrationStoryboard:
        """Synthesize narration audio for all scenes in parallel, assembling a complete storyboard."""
        max_concurrency = concurrency or self.DEFAULT_CONCURRENCY
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "Generating speech storyboard (%d scenes, concurrency=%d) for topic '%s'",
            len(plan.scenes),
            max_concurrency,
            topic,
        )

        semaphore = asyncio.Semaphore(max_concurrency)

        async def _synthesize_scene(scene: SceneNarrationPlan) -> SceneAudio:
            if (
                scene.scene_number == 1
                and sample_scene_1 is not None
                and Path(sample_scene_1.audio_path).exists()
            ):
                logger.debug("Reusing pre-generated approved Scene 1 sample audio")
                return sample_scene_1

            scene_path = output_dir / f"scene_{scene.scene_number}.wav"
            async with semaphore:
                return await self.generate_scene_audio(
                    topic=topic,
                    plan=plan,
                    scene=scene,
                    output_path=scene_path,
                )

        tasks = [_synthesize_scene(scene) for scene in plan.scenes]
        scenes_audio = await asyncio.gather(*tasks)
        scenes_audio.sort(key=lambda s: s.scene_number)

        # Concatenate into full master audio if multiple scenes exist
        full_audio_path: str | None = None
        if scenes_audio:
            try:
                master_wav = output_dir / "narration_full.wav"
                scene_wav_paths = [Path(s.audio_path) for s in scenes_audio]
                combine_wav_files(scene_wav_paths, master_wav)
                full_audio_path = str(master_wav)
            except (OSError, ValueError, RuntimeError) as err:
                logger.warning("Could not combine scene WAV files: %s", err)

        total_duration = sum(s.duration_seconds for s in scenes_audio)
        sample_path = (
            scenes_audio[0].audio_path
            if scenes_audio
            else (sample_scene_1.audio_path if sample_scene_1 else None)
        )

        return NarrationStoryboard(
            topic=topic,
            plan=plan,
            scenes_audio=scenes_audio,
            sample_audio_path=sample_path,
            full_audio_path=full_audio_path,
            total_duration_seconds=round(total_duration, 3),
        )


__all__ = [
    "NarrationGeneratorAgent",
    "build_speech_prompt",
]
