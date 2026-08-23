"""Unit and integration tests for media engines and external services."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.models import AspectRatio
from media.audio_tts import AudioEngine
from media.svg_animator import SvgAnimator
from media.video_assembler import VideoAssembler
from services.telegram_bot import TelegramBotService
from services.youtube_publisher import YouTubePublisher


@pytest.mark.asyncio
async def test_audio_engine_gemini_tts_mocked(
    mock_settings, sample_video_script, tmp_path
):
    """Test AudioEngine synthesis using mocked Gemini audio response."""
    audio_engine = AudioEngine(settings=mock_settings)
    scene_1 = sample_video_script.scenes[0]

    # Create dummy 16-bit PCM audio (24000 samples = 1 second at 24kHz)
    dummy_pcm = b"\x00\x00" * 24000

    mock_resp = MagicMock()
    mock_part = MagicMock()
    mock_part.inline_data.data = dummy_pcm
    mock_part.inline_data.mime_type = "audio/pcm;rate=24000"

    mock_candidate = MagicMock()
    mock_candidate.content.parts = [mock_part]
    mock_resp.candidates = [mock_candidate]

    audio_engine.client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    updated_scene = await audio_engine.synthesize_scene(
        scene=scene_1,
        output_dir=tmp_path / "audio",
    )

    assert updated_scene.audio_path is not None
    assert updated_scene.audio_path.endswith(".wav")
    assert (tmp_path / "audio").exists()
    assert updated_scene.duration_seconds >= 1.0


def test_audio_engine_voice_selection(mock_settings):
    """Test voice selection logic when configured or random."""
    mock_settings.tts_voice = "random"
    audio_engine = AudioEngine(settings=mock_settings)

    voice_1 = audio_engine.get_voice()
    assert voice_1 is not None and len(voice_1) > 0

    # Specific voice overrides random setting
    voice_2 = audio_engine.get_voice("Charon")
    assert voice_2 == "Charon"


@pytest.mark.asyncio
async def test_audio_engine_synthesize_fallback(
    mock_settings, sample_video_script, tmp_path
):
    """Test AudioEngine fallback synthesis when Gemini API call fails."""
    audio_engine = AudioEngine(settings=mock_settings)
    audio_engine.client.aio.models.generate_content = AsyncMock(
        side_effect=RuntimeError("API Network Error")
    )
    scene_1 = sample_video_script.scenes[0]

    updated_scene = await audio_engine.synthesize_scene(
        scene=scene_1,
        output_dir=tmp_path / "audio",
    )

    assert updated_scene.audio_path is not None
    assert updated_scene.duration_seconds >= 2.5
    assert (tmp_path / "audio").exists()


@pytest.mark.asyncio
async def test_svg_animator_rendering(mock_settings, sample_video_script, tmp_path):
    """Test SVG frame generation for both landscape (16:9) and vertical (9:16) shorts."""
    animator = SvgAnimator(settings=mock_settings)
    scene_1 = sample_video_script.scenes[0]
    scene_1.duration_seconds = 2.0  # 2.0s * 10 fps = 20 frames

    # 1. Landscape 16:9 render
    landscape_frames = await animator.render_scene_frames(
        scene=scene_1,
        output_dir=tmp_path / "landscape",
        fps=10,
        aspect_ratio=AspectRatio.LANDSCAPE_16_9,
    )
    assert len(landscape_frames) == 20
    assert landscape_frames[0].exists()

    # 2. Vertical 9:16 short render
    short_frames = await animator.render_scene_frames(
        scene=scene_1,
        output_dir=tmp_path / "short",
        fps=10,
        aspect_ratio=AspectRatio.VERTICAL_9_16,
    )
    assert len(short_frames) == 20
    assert short_frames[0].exists()


@pytest.mark.asyncio
async def test_video_assembler_render_and_concat(
    mock_settings, sample_video_script, tmp_path
):
    """Test VideoAssembler rendering scene clips and concatenating master video."""
    animator = SvgAnimator(settings=mock_settings)
    audio_engine = AudioEngine(settings=mock_settings)

    # Mock audio generation response to prevent any real API network call
    mock_resp = MagicMock()
    mock_part = MagicMock()
    mock_part.inline_data.data = b"\x00\x00" * 24000
    mock_part.inline_data.mime_type = "audio/pcm;rate=24000"
    mock_candidate = MagicMock()
    mock_candidate.content.parts = [mock_part]
    mock_resp.candidates = [mock_candidate]
    audio_engine.client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    assembler = VideoAssembler(settings=mock_settings)

    scene = sample_video_script.scenes[0]
    scene.duration_seconds = 2.0

    # Prepare frames & audio
    await audio_engine.synthesize_scene(scene, tmp_path / "audio")
    await animator.render_scene_frames(scene, tmp_path / "frames", fps=10)

    # Render scene clip
    clip_1 = tmp_path / "clip_1.mp4"
    rendered_clip = await assembler.render_scene_clip(
        scene=scene, output_clip_path=clip_1, fps=10
    )
    assert rendered_clip.exists()

    # Assemble full video from clips
    master_video = tmp_path / "master.mp4"
    assembled = await assembler.assemble_full_video(
        scene_clip_paths=[clip_1],
        output_video_path=master_video,
    )
    assert assembled.exists()


@pytest.mark.asyncio
async def test_youtube_publisher_simulation(mock_settings, tmp_path):
    """Test YouTubePublisher fallback simulation mode when client secrets are missing."""
    publisher = YouTubePublisher(settings=mock_settings)

    test_video = tmp_path / "test.mp4"
    test_video.write_bytes(b"dummy video data")

    url = await publisher.upload_video(
        video_path=test_video,
        title="Sample Video Title",
        description="Sample Description",
        tags=["sample", "test"],
    )
    assert url.startswith("https://youtu.be/sim_")


@pytest.mark.asyncio
async def test_telegram_bot_authorization(mock_settings, memory_db):
    """Test TelegramBotService authorization check with user ID and username."""
    mock_settings.telegram_allowed_users = [999, "dimitreoliveira"]
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)

    assert bot_service._is_user_authorized(999) is True
    assert bot_service._is_user_authorized(None, username="dimitreoliveira") is True
    assert bot_service._is_user_authorized(None, username="@dimitreoliveira") is True
    assert bot_service._is_user_authorized(123) is False
    assert bot_service._is_user_authorized(123, username="otheruser") is False


@pytest.mark.asyncio
async def test_telegram_bot_build_application(mock_settings, memory_db):
    """Test TelegramBotService building PTB Application."""
    mock_settings.telegram_bot_token = "123456789:TEST_BOT_TOKEN_FOR_BUILDING"
    bot_service = TelegramBotService(settings=mock_settings, db=memory_db)

    app = await bot_service.build_application()
    assert app is not None
    assert bot_service.app is not None
