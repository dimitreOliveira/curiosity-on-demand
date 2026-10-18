"""Unit tests for Gemini TTS narration planning, speech synthesis, and narrator agent."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.narration_generator import NarrationGeneratorAgent, build_speech_prompt
from agents.narration_planner import NarrationPlanerAgent, NarrationPlannerAgent
from agents.narrator import NarratorAgent
from core.audio_utils import (
    combine_wav_files,
    convert_to_wav,
    format_duration,
    get_wav_duration,
    normalize_inline_audio_tags,
    parse_audio_mime_type,
)

# ---------------------------------------------------------------------------
# 1. Audio Utilities Tests
# ---------------------------------------------------------------------------


def test_parse_audio_mime_type():
    """Test extracting audio container format and sample rate from MIME type strings."""
    params = parse_audio_mime_type("audio/L16;rate=24000")
    assert params["bits_per_sample"] == 16
    assert params["rate"] == 24000

    params = parse_audio_mime_type("audio/L16; rate=16000")
    assert params["bits_per_sample"] == 16
    assert params["rate"] == 16000

    params = parse_audio_mime_type("audio/x-wav")
    assert params["bits_per_sample"] == 16
    assert params["rate"] == 24000  # Default fallback

    params = parse_audio_mime_type(None)
    assert params["bits_per_sample"] == 16
    assert params["rate"] == 24000


def test_convert_to_wav_raw_pcm():
    """Test converting raw L16 PCM bytes to a valid WAV file with RIFF header."""
    raw_pcm = b"\x00\x00" * 24000  # 1 second of 16-bit silence at 24kHz
    wav_bytes = convert_to_wav(raw_pcm, "audio/L16;rate=24000")

    assert wav_bytes.startswith(b"RIFF")
    assert b"WAVE" in wav_bytes[:16]
    # Header is 44 bytes, plus 48000 bytes data
    assert len(wav_bytes) == 44 + len(raw_pcm)


def test_convert_to_wav_idempotent():
    """Test that existing RIFF WAV bytes are returned as-is without duplicate headers."""
    existing_wav = b"RIFF" + b"\x00" * 40 + b"DATA"
    result = convert_to_wav(existing_wav)
    assert result == existing_wav


def test_get_wav_duration(sample_wav_file):
    """Test measuring playback duration of a standard WAV file."""
    duration = get_wav_duration(sample_wav_file)
    assert pytest.approx(duration, 0.01) == 1.0


def test_combine_wav_files(tmp_path, sample_wav_file):
    """Test combining multiple sequential WAV files into a single unified WAV."""
    out_combined = tmp_path / "combined.wav"
    combined_path = combine_wav_files(
        [sample_wav_file, sample_wav_file, sample_wav_file],
        out_combined,
    )
    assert combined_path == out_combined
    assert out_combined.exists()

    combined_duration = get_wav_duration(combined_path)
    assert pytest.approx(combined_duration, 0.05) == 3.0


def test_combine_wav_files_empty_raises(tmp_path):
    """Test that combining an empty list of files raises ValueError."""
    with pytest.raises(ValueError, match="No valid.*WAV files provided"):
        combine_wav_files([], tmp_path / "empty.wav")


def test_format_duration():
    """Test formatting seconds into readable duration strings."""
    assert format_duration(0) == "0m 00s"
    assert format_duration(45) == "0m 45s"
    assert format_duration(65) == "1m 05s"
    assert format_duration(180) == "3m 00s"
    assert format_duration(324) == "5m 24s"
    assert format_duration(3665) == "1h 01m 05s"


def test_normalize_inline_audio_tags():
    """Test converting square-bracket and alias tags to Gemini 3.8 TTS angle-bracket format."""
    text = (
        "[whispers] Imagine a switch, [dramatic pause] pointing everywhere! "
        "[excitedly] [gasp] That is quantum physics. [pause] [clears throat] Incredible."
    )
    normalized = normalize_inline_audio_tags(text)
    assert normalized == (
        "<whispers> Imagine a switch, <long pause> pointing everywhere! "
        "<gasp> That is quantum physics. <short pause> <throat-clearing> Incredible."
    )
    assert "[dramatic pause]" not in normalized
    assert "[excitedly]" not in normalized
    assert (
        normalize_inline_audio_tags("Wait... <dramatic pause> really?")
        == "Wait... <long pause> really?"
    )


# ---------------------------------------------------------------------------
# 2. NarrationPlannerAgent Tests
# ---------------------------------------------------------------------------


def test_narration_planner_alias():
    """Ensure the alias NarrationPlanerAgent matches NarrationPlannerAgent."""
    assert NarrationPlanerAgent is NarrationPlannerAgent


@pytest.mark.asyncio
async def test_narration_planner_plan_narration(
    mock_settings, sample_script, sample_narration_plan
):
    """Test NarrationPlannerAgent successfully generating structured NarrationPlan."""
    planner = NarrationPlannerAgent(settings=mock_settings)

    mock_response = MagicMock()
    mock_response.parsed = sample_narration_plan

    planner.client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    plan = await planner.plan_narration(
        script=sample_script,
        feedback="Make the intro more mysterious and breathless.",
        voice_name="Zephyr",
    )

    assert plan is not None
    assert plan.voice_name == "Zephyr"
    assert len(plan.scenes) == 3
    assert "<whispers>" in plan.scenes[0].enhanced_narration
    assert planner.client.aio.models.generate_content.call_count == 1

    call_args = planner.client.aio.models.generate_content.call_args
    prompt_sent = call_args.kwargs["contents"]
    assert "Make the intro more mysterious and breathless." in prompt_sent
    assert sample_script.topic in prompt_sent


@pytest.mark.asyncio
async def test_narration_planner_raises_on_empty_response(mock_settings, sample_script):
    """Test NarrationPlannerAgent raising RuntimeError when structured output is None."""
    planner = NarrationPlannerAgent(settings=mock_settings)

    mock_response = MagicMock()
    mock_response.parsed = None
    mock_response.text = ""

    planner.client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with pytest.raises(RuntimeError, match="Empty or unparsable response"):
        await planner.plan_narration(script=sample_script)


@pytest.mark.asyncio
async def test_narration_planner_minimizes_whisper_prompt(
    mock_settings, sample_script, sample_narration_plan
):
    """Test that NarrationPlannerAgent instructs the model to minimize whisper tags."""
    from agents.narration_planner import NARRATION_PLANNER_SYSTEM_PROMPT

    # Verify system prompt contains whisper minimization rule and angle-bracket tag rule
    assert (
        "Minimize the use of `<whispers>` / `<whispering>`"
        in NARRATION_PLANNER_SYSTEM_PROMPT
    )
    assert "Whisper Tag Rule (IMPORTANT)" in NARRATION_PLANNER_SYSTEM_PROMPT
    assert "<short pause>" in NARRATION_PLANNER_SYSTEM_PROMPT
    assert "<long pause>" in NARRATION_PLANNER_SYSTEM_PROMPT

    planner = NarrationPlannerAgent(settings=mock_settings)
    mock_response = MagicMock()
    mock_response.parsed = sample_narration_plan
    planner.client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    await planner.plan_narration(script=sample_script)

    call_args = planner.client.aio.models.generate_content.call_args
    prompt_sent = call_args.kwargs["contents"]
    assert "Minimize whisper tags" in prompt_sent


# ---------------------------------------------------------------------------
# 3. NarrationGeneratorAgent Tests
# ---------------------------------------------------------------------------


def test_narration_generator_build_speech_prompt(sample_narration_plan):
    """Test speech prompt formatting matching Google Gemini TTS guidelines."""
    scene_plan = sample_narration_plan.scenes[0]
    prompt = build_speech_prompt(plan=sample_narration_plan, scene=scene_plan)

    assert "# AUDIO PROFILE" in prompt
    assert sample_narration_plan.audio_profile_name in prompt
    assert "## THE SCENE" in prompt
    assert "### DIRECTOR'S NOTES" in prompt
    assert scene_plan.scene_directors_notes in prompt
    assert "#### TRANSCRIPT" in prompt
    assert scene_plan.enhanced_narration in prompt

    # Verify legacy square-bracket tags are automatically normalized in build_speech_prompt
    legacy_prompt = build_speech_prompt(
        plan=sample_narration_plan,
        transcript="Hold on... [dramatic pause] [gasp] [excitedly] Look at that!",
    )
    assert "Hold on... <long pause> <gasp> Look at that!" in legacy_prompt
    assert "[dramatic pause]" not in legacy_prompt
    assert "[excitedly]" not in legacy_prompt


@pytest.mark.asyncio
async def test_narration_generator_generate_speech_audio(mock_settings, tmp_path):
    """Test low-level Gemini TTS API invocation with audio modalities and speech config."""
    generator = NarrationGeneratorAgent(settings=mock_settings)
    out_file = tmp_path / "speech.wav"

    raw_pcm = b"\x00\x00" * 24000
    mock_inline_data = MagicMock()
    mock_inline_data.data = raw_pcm
    mock_inline_data.mime_type = "audio/L16;rate=24000"

    mock_part = MagicMock()
    mock_part.inline_data = mock_inline_data

    mock_candidate = MagicMock()
    mock_candidate.content.parts = [mock_part]

    mock_response = MagicMock()
    mock_response.candidates = [mock_candidate]
    mock_response.parts = [mock_part]
    mock_response.text = ""

    generator.client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    res_path = await generator.generate_speech_audio(
        prompt="Sample Speech Prompt",
        voice_name="Zephyr",
        output_path=out_file,
    )

    assert res_path == out_file
    assert out_file.exists()
    assert out_file.read_bytes().startswith(b"RIFF")
    assert generator.client.aio.models.generate_content.call_count == 1

    call_kwargs = generator.client.aio.models.generate_content.call_args.kwargs
    assert call_kwargs["model"] == "gemini-3.1-flash-tts-preview"
    assert call_kwargs["config"].response_modalities == ["audio"]
    assert (
        call_kwargs[
            "config"
        ].speech_config.voice_config.prebuilt_voice_config.voice_name
        == "Zephyr"
    )


@pytest.mark.asyncio
async def test_narration_generator_generate_speech_audio_missing_data(
    mock_settings, tmp_path
):
    """Test error handling when Gemini TTS response contains no inline audio data."""
    generator = NarrationGeneratorAgent(settings=mock_settings)
    dummy_out = tmp_path / "dummy.wav"

    mock_response = MagicMock()
    mock_response.candidates = []

    generator.client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with pytest.raises(RuntimeError, match="returned no audio data"):
        await generator.generate_speech_audio(
            prompt="Prompt", voice_name="Zephyr", output_path=dummy_out
        )


@pytest.mark.asyncio
async def test_narration_generator_generate_scene_audio(
    mock_settings, sample_narration_plan, tmp_path
):
    """Test synthesising, converting to WAV, and measuring duration for a single scene."""
    generator = NarrationGeneratorAgent(settings=mock_settings)
    out_wav = tmp_path / "audio" / "scene_1.wav"

    async def mock_speech(prompt, voice_name, output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        raw_pcm = b"\x00\x00" * 48000
        output_path.write_bytes(convert_to_wav(raw_pcm))
        return output_path

    generator.generate_speech_audio = AsyncMock(side_effect=mock_speech)

    scene_audio = await generator.generate_scene_audio(
        topic="Quantum Computing",
        plan=sample_narration_plan,
        scene=sample_narration_plan.scenes[0],
        output_path=out_wav,
    )

    assert scene_audio.scene_number == 1
    assert scene_audio.audio_path == str(out_wav)
    assert pytest.approx(scene_audio.duration_seconds, 0.05) == 2.0
    assert out_wav.exists()
    assert out_wav.read_bytes().startswith(b"RIFF")


@pytest.mark.asyncio
async def test_narration_generator_generate_storyboard_audio(
    mock_settings, sample_narration_plan, tmp_path
):
    """Test generating full narration audio storyboard across all scenes concurrently."""
    generator = NarrationGeneratorAgent(settings=mock_settings)
    out_dir = tmp_path / "storyboard_audio"

    async def mock_speech(prompt, voice_name, output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        raw_pcm = b"\x00\x00" * 24000
        output_path.write_bytes(convert_to_wav(raw_pcm))
        return output_path

    generator.generate_speech_audio = AsyncMock(side_effect=mock_speech)

    storyboard = await generator.generate_storyboard_audio(
        topic="Quantum Computing",
        plan=sample_narration_plan,
        output_dir=out_dir,
    )

    assert storyboard.topic == "Quantum Computing"
    assert len(storyboard.scenes_audio) == 3
    assert pytest.approx(storyboard.total_duration_seconds, 0.05) == 3.0
    assert (out_dir / "scene_1.wav").exists()
    assert (out_dir / "scene_2.wav").exists()
    assert (out_dir / "scene_3.wav").exists()


# ---------------------------------------------------------------------------
# 4. NarratorAgent Coordinator Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_narrator_determine_plan_and_sample(
    mock_settings, sample_script, sample_narration_plan, sample_scene_audio
):
    """Test NarratorAgent generating narration plan and sample Scene 1 audio."""
    narrator = NarratorAgent(settings=mock_settings)
    narrator.planner.plan_narration = AsyncMock(return_value=sample_narration_plan)
    narrator.generator.generate_scene_audio = AsyncMock(return_value=sample_scene_audio)

    plan, sample_audio = await narrator.determine_plan_and_sample(
        topic="Quantum Computing",
        script=sample_script,
        feedback="More energy!",
    )

    assert plan == sample_narration_plan
    assert sample_audio == sample_scene_audio
    narrator.planner.plan_narration.assert_called_once_with(
        topic="Quantum Computing",
        script=sample_script,
        feedback="More energy!",
        previous_plan=None,
    )
    narrator.generator.generate_scene_audio.assert_called_once()


@pytest.mark.asyncio
async def test_narrator_generate_full_narration(
    mock_settings, sample_narration_plan, sample_narration_storyboard
):
    """Test NarratorAgent generating full storyboard audio."""
    narrator = NarratorAgent(settings=mock_settings)
    narrator.generator.generate_storyboard_audio = AsyncMock(
        return_value=sample_narration_storyboard
    )

    storyboard = await narrator.generate_full_narration(
        topic="Quantum Computing",
        plan=sample_narration_plan,
    )

    assert storyboard == sample_narration_storyboard
    assert len(storyboard.scenes_audio) == 3
