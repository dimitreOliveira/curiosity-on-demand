"""Audio narration synthesis engine using Google Cloud TTS with robust fallbacks."""

import asyncio
import logging
import math
import os
import struct
import wave
from pathlib import Path

from google.api_core.exceptions import GoogleAPIError
from google.auth.exceptions import GoogleAuthError

from config.settings import Settings, get_settings
from core.models import Scene, VideoScript

logger = logging.getLogger(__name__)


class AudioEngine:
    """Handles voiceover narration synthesis for video scenes."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._tts_client = None

    def _get_tts_client(self):
        """Lazy-initialize Google Cloud TextToSpeechClient."""
        if self._tts_client is None:
            try:
                from google.cloud import texttospeech

                # If GOOGLE_APPLICATION_CREDENTIALS points to a file, set environ
                if self.settings.google_application_credentials:
                    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = (
                        self.settings.google_application_credentials
                    )

                self._tts_client = texttospeech.TextToSpeechClient()
                logger.info("Initialized Google Cloud TextToSpeechClient")
            except (
                ImportError,
                GoogleAPIError,
                GoogleAuthError,
                OSError,
                ValueError,
                RuntimeError,
            ) as e:
                logger.warning(
                    "Google Cloud TTS client could not be initialized (%s). Using fallback audio synthesizer.",
                    e,
                )
                self._tts_client = None
        return self._tts_client

    async def synthesize_scene(
        self,
        scene: Scene,
        output_dir: Path,
        voice_name: str = "en-US-Neural2-F",
        speaking_rate: float = 1.05,
    ) -> Scene:
        """Synthesize narration audio for an individual scene and update its duration."""
        output_dir.mkdir(parents=True, exist_ok=True)
        audio_file = output_dir / f"scene_{scene.scene_id}_narration.mp3"
        wav_file = output_dir / f"scene_{scene.scene_id}_narration.wav"

        duration = await asyncio.to_thread(
            self._synthesize_sync,
            scene.narration,
            audio_file,
            wav_file,
            voice_name,
            speaking_rate,
        )

        scene.audio_path = str(audio_file if audio_file.exists() else wav_file)
        scene.duration_seconds = max(2.5, round(duration, 2))
        return scene

    def _synthesize_sync(
        self,
        text: str,
        mp3_path: Path,
        wav_fallback_path: Path,
        voice_name: str,
        speaking_rate: float,
    ) -> float:
        """Synchronous synthesis implementation dispatched to worker thread."""
        client = self._get_tts_client()

        if client:
            try:
                from google.cloud import texttospeech

                synthesis_input = texttospeech.SynthesisInput(text=text)
                voice = texttospeech.VoiceSelectionParams(
                    language_code="en-US",
                    name=voice_name,
                )
                audio_config = texttospeech.AudioConfig(
                    audio_encoding=texttospeech.AudioEncoding.MP3,
                    speaking_rate=speaking_rate,
                )

                response = client.synthesize_speech(
                    input=synthesis_input,
                    voice=voice,
                    audio_config=audio_config,
                )

                with open(mp3_path, "wb") as out:
                    out.write(response.audio_content)

                # Estimate duration from words or MP3 file size
                words_count = len(text.split())
                duration = max(2.5, (words_count / (2.4 * speaking_rate)))
                logger.info(
                    "Synthesized %d words with GCP TTS to %s (approx %.1fs)",
                    words_count,
                    mp3_path.name,
                    duration,
                )
                return duration
            except (
                GoogleAPIError,
                GoogleAuthError,
                OSError,
                RuntimeError,
                ValueError,
            ) as err:
                logger.warning(
                    "GCP TTS synthesis failed: %s. Falling back to synthetic audio generation.",
                    err,
                )

        # Fallback synthesizer: Generate clean synthetic audio tone/silence WAV
        return self._generate_fallback_wav(text, wav_fallback_path)

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
                # Soft 220Hz harmonic with modulation
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
    ) -> VideoScript:
        """Synthesize all scene voiceovers and update script timings."""
        audio_dir = project_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        tasks = [self.synthesize_scene(scene, audio_dir) for scene in script.scenes]
        updated_scenes = await asyncio.gather(*tasks)

        script.scenes = list(updated_scenes)
        script.total_duration_seconds = round(
            sum(s.duration_seconds for s in script.scenes), 2
        )
        return script
