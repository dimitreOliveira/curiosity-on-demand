"""Audio narration synthesis engine using Gemini TTS via Google GenAI SDK."""

import asyncio
import logging
import math
import mimetypes
import random
import struct
import wave
from pathlib import Path

from google import genai
from google.genai import types

from config.settings import Settings, get_settings
from core.models import Scene, VideoScript

logger = logging.getLogger(__name__)

# Complete list of prebuilt voices supported by the Gemini TTS models
AVAILABLE_TTS_VOICES: list[str] = [
    "Zephyr",
    "Puck",
    "Charon",
    "Kore",
    "Fenrir",
    "Leda",
    "Orus",
    "Aoede",
    "Callirrhoe",
    "Autonoe",
    "Enceladus",
    "Iapetus",
    "Umbriel",
    "Algieba",
    "Despina",
    "Erinome",
    "Algenib",
    "Rasalgethi",
    "Laomedeia",
    "Achernar",
    "Alnilam",
    "Schedar",
    "Gacrux",
    "Pulcherrima",
    "Achird",
    "Zubenelgenubi",
    "Vindemiatrix",
    "Sadachbia",
    "Sadaltager",
    "Sulafat",
]


def parse_audio_mime_type(mime_type: str) -> dict[str, int]:
    """Parse bits per sample and sample rate from an audio MIME type string."""
    bits_per_sample = 16
    rate = 24000

    parts = mime_type.split(";")
    for param in parts:
        param = param.strip()
        if param.lower().startswith("rate="):
            try:
                rate = int(param.split("=", 1)[1])
            except (ValueError, IndexError):
                pass
        elif "audio/l" in param.lower():
            try:
                # E.g. audio/L16 or audio/L24
                bits_per_sample = int(param.lower().split("audio/l", 1)[1])
            except (ValueError, IndexError):
                pass

    return {"bits_per_sample": bits_per_sample, "rate": rate}


def convert_to_wav(audio_data: bytes, mime_type: str) -> bytes:
    """Generate a standard RIFF WAV container header for raw PCM audio data."""
    params = parse_audio_mime_type(mime_type)
    bits_per_sample = params["bits_per_sample"]
    sample_rate = params["rate"]
    num_channels = 1
    data_size = len(audio_data)
    bytes_per_sample = bits_per_sample // 8
    block_align = num_channels * bytes_per_sample
    byte_rate = sample_rate * block_align
    chunk_size = 36 + data_size

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        chunk_size,
        b"WAVE",
        b"fmt ",
        16,  # Subchunk1Size (16 for PCM)
        1,  # AudioFormat (1 for PCM)
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    return header + audio_data


class AudioEngine:
    """Handles voiceover narration synthesis using Gemini TTS."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

        if self.settings.gemini_api_key:
            self.client = genai.Client(api_key=self.settings.gemini_api_key)
        else:
            self.client = genai.Client()

    def get_voice(self, voice_name: str | None = None) -> str:
        """Select a specified voice or pick one randomly for the creation."""
        candidate = voice_name or self.settings.tts_voice
        if not candidate or candidate.strip().lower() in ("random", "auto"):
            return random.choice(AVAILABLE_TTS_VOICES)
        return candidate

    def _build_tts_prompt(self, scene: Scene) -> str:
        """Build structured director's prompt for steering Gemini TTS tone and pacing."""
        scene_context = (
            scene.visual_description
            if scene.visual_description
            else "A clear explanatory documentary scene."
        )

        return (
            "Read the following transcript based on the audio profile and director's note.\n\n"
            "# Audio Profile\n"
            "An articulate, engaging, and authoritative documentary narrator.\n\n"
            "# Director's note\n"
            "Style: Professional, clear articulation, captivating broadcast cadence. "
            "Pace: Natural, liquid, measured with deliberate pauses at transitions. "
            "Accent: American (Standard).\n\n"
            f"## Scene Context:\n{scene_context}\n\n"
            f"## Transcript:\n{scene.narration}"
        )

    async def synthesize_scene(
        self,
        scene: Scene,
        output_dir: Path,
        voice_name: str | None = None,
        model_name: str | None = None,
    ) -> Scene:
        """Synthesize narration audio for an individual scene using Gemini TTS."""
        output_dir.mkdir(parents=True, exist_ok=True)
        wav_file = output_dir / f"scene_{scene.scene_id}_narration.wav"
        mp3_file = output_dir / f"scene_{scene.scene_id}_narration.mp3"

        voice = self.get_voice(voice_name)
        model = model_name or self.settings.tts_model

        try:
            config = types.GenerateContentConfig(
                temperature=1.0,
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice
                        )
                    )
                ),
            )

            prompt = self._build_tts_prompt(scene)

            response = await self.client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )

            audio_chunks: list[bytes] = []
            mime_type = "audio/pcm;rate=24000"

            if response and response.candidates:
                candidate = response.candidates[0]
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if part.inline_data and part.inline_data.data:
                            audio_chunks.append(part.inline_data.data)
                            if part.inline_data.mime_type:
                                mime_type = part.inline_data.mime_type

            if audio_chunks:
                audio_bytes = b"".join(audio_chunks)
                extension = mimetypes.guess_extension(mime_type)

                if extension == ".mp3" or "mp3" in mime_type.lower():
                    mp3_file.write_bytes(audio_bytes)
                    words_count = len(scene.narration.split())
                    duration = max(2.5, words_count / 2.4)
                    scene.audio_path = str(mp3_file)
                else:
                    # Treat as raw PCM or WAV
                    if "pcm" in mime_type.lower() or "audio/l" in mime_type.lower():
                        wav_data = convert_to_wav(audio_bytes, mime_type)
                    else:
                        wav_data = audio_bytes

                    wav_file.write_bytes(wav_data)

                    try:
                        with wave.open(str(wav_file), "rb") as wf:
                            duration = wf.getnframes() / float(wf.getframerate())
                    except (wave.Error, OSError, EOFError):
                        words_count = len(scene.narration.split())
                        duration = max(2.5, words_count / 2.4)

                    scene.audio_path = str(wav_file)

                scene.duration_seconds = max(2.5, round(duration, 2))
                logger.info(
                    "Synthesized scene %d narration with Gemini TTS ('%s') -> %s (%.2fs)",
                    scene.scene_id,
                    voice,
                    Path(scene.audio_path).name,
                    scene.duration_seconds,
                )
                return scene

            logger.warning(
                "Gemini TTS returned no audio data for scene %d. Falling back to synthetic audio.",
                scene.scene_id,
            )

        except Exception as err:  # noqa: BLE001
            logger.warning(
                "Gemini TTS synthesis failed for scene %d: %s. Using fallback audio synthesizer.",
                scene.scene_id,
                err,
            )

        # Fallback synthesizer: Generate clean synthetic audio tone WAV
        duration = await asyncio.to_thread(
            self._generate_fallback_wav, scene.narration, wav_file
        )
        scene.audio_path = str(wav_file)
        scene.duration_seconds = max(2.5, round(duration, 2))
        return scene

    def _generate_fallback_wav(self, text: str, output_wav: Path) -> float:
        """Generate a valid WAV audio file proportional to narration text length."""
        words_count = len(text.split())
        duration_seconds = max(3.0, (words_count / 2.3))

        sample_rate = 24000
        num_samples = int(sample_rate * duration_seconds)

        with wave.open(str(output_wav), "wb") as wav:
            wav.setnchannels(1)  # Mono
            wav.setsampwidth(2)  # 16-bit
            wav.setframerate(sample_rate)

            # Generate gentle modulated background carrier tone
            audio_bytes = bytearray()
            for i in range(num_samples):
                t = i / sample_rate
                val = int(
                    math.sin(2 * math.pi * 220 * t)
                    * 1500
                    * (0.5 + 0.5 * math.sin(2 * math.pi * 1.5 * t))
                )
                audio_bytes.extend(struct.pack("<h", val))

            wav.writeframes(audio_bytes)

        logger.info(
            "Created fallback WAV (%d words, %.2fs) -> %s",
            words_count,
            duration_seconds,
            output_wav.name,
        )
        return duration_seconds

    async def batch_synthesize_script(
        self,
        script: VideoScript,
        project_dir: Path,
        voice_name: str | None = None,
    ) -> VideoScript:
        """Synthesize all scene voiceovers with a consistent chosen voice and update timings."""
        audio_dir = project_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        chosen_voice = self.get_voice(voice_name)
        logger.info(
            "Synthesizing script '%s' (%d scenes) with voice '%s'",
            script.title,
            len(script.scenes),
            chosen_voice,
        )

        tasks = [
            self.synthesize_scene(scene, audio_dir, voice_name=chosen_voice)
            for scene in script.scenes
        ]
        updated_scenes = await asyncio.gather(*tasks)

        script.scenes = list(updated_scenes)
        script.total_duration_seconds = round(
            sum(s.duration_seconds for s in script.scenes), 2
        )
        return script
