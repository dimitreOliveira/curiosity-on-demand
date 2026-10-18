"""Unit tests for YouTubePublisher service."""

from unittest.mock import MagicMock, patch

import pytest

from config.settings import Settings
from core.models import (
    AnimationStoryboard,
    AnimationStyle,
    SceneAnimation,
    Script,
    ScriptScene,
)
from services.youtube_publisher import (
    YouTubeAuthenticationError,
    YouTubePublisher,
    clean_topic_title,
    format_timestamp,
)


def test_clean_topic_title():
    """Test cleaning topic string by removing video duration tags and metadata artifacts."""
    assert clean_topic_title("The History of Coffee - 60s") == "The History of Coffee"
    assert clean_topic_title("Quantum Computing — 5 min") == "Quantum Computing"
    assert clean_topic_title("Deep Sea Mysteries - 3-minute") == "Deep Sea Mysteries"
    assert clean_topic_title("Black Holes") == "Black Holes"
    # Parenthesized duration artifacts
    assert (
        clean_topic_title("Why Do Cats Purr? (2 minute video)") == "Why Do Cats Purr?"
    )
    assert (
        clean_topic_title(
            "The different levels of space civilizations (2 minute video)"
        )
        == "The different levels of space civilizations"
    )
    assert clean_topic_title("Why Do Cats Purr? (2 min)") == "Why Do Cats Purr?"
    assert clean_topic_title("Quantum Computers [5 min video]") == "Quantum Computers"
    assert clean_topic_title("Solar Flares (Shorts)") == "Solar Flares"
    assert clean_topic_title("How Engines Work: 2 minute video") == "How Engines Work"
    assert clean_topic_title("Why Do Cats Purr? - 2 min video") == "Why Do Cats Purr?"
    assert clean_topic_title("History of Rome in 15 minutes") == "History of Rome"
    assert clean_topic_title("Black holes 2m short") == "Black holes"
    assert (
        clean_topic_title("Why is the sky blue? (in 2 minutes)")
        == "Why is the sky blue?"
    )
    assert (
        clean_topic_title('"Why Do Cats Purr?" (2 minute video)') == "Why Do Cats Purr?"
    )
    assert clean_topic_title("A 3-min video about dinosaurs") == "Dinosaurs"
    assert clean_topic_title("Quick 45-second overview of gravity") == "Gravity"
    assert clean_topic_title("2 minute video on black holes") == "Black holes"
    assert clean_topic_title("Mars Exploration (video)") == "Mars Exploration"


def test_format_timestamp():
    """Test MM:SS and HH:MM:SS timestamp formatting."""
    assert format_timestamp(0) == "00:00"
    assert format_timestamp(45) == "00:45"
    assert format_timestamp(75) == "01:15"
    assert format_timestamp(3665) == "01:01:05"


def test_youtube_publisher_is_configured(tmp_path):
    """Test configuration detection via direct tokens, token file, and unconfigured state."""
    # 1. Unconfigured
    settings_empty = Settings(
        youtube_client_id="",
        youtube_client_secret="",
        youtube_refresh_token="",
        youtube_token_file=tmp_path / "non_existent_token.json",
    )
    publisher = YouTubePublisher(settings=settings_empty)
    assert not publisher.is_configured()

    # 2. Configured via direct env tokens
    settings_direct = Settings(
        youtube_client_id="test_client_id",
        youtube_client_secret="test_client_secret",
        youtube_refresh_token="test_refresh_token",
        youtube_token_file=tmp_path / "non_existent_token.json",
    )
    assert YouTubePublisher(settings=settings_direct).is_configured()

    # 3. Configured via token file
    token_file = tmp_path / "token.json"
    token_file.write_text("{}", encoding="utf-8")
    settings_file = Settings(
        youtube_client_id="",
        youtube_client_secret="",
        youtube_refresh_token="",
        youtube_token_file=token_file,
    )
    assert YouTubePublisher(settings=settings_file).is_configured()


def test_youtube_publisher_get_credentials_unconfigured(tmp_path):
    """Test that get_credentials raises YouTubeAuthenticationError when not configured."""
    settings = Settings(
        youtube_client_id="",
        youtube_client_secret="",
        youtube_refresh_token="",
        youtube_token_file=tmp_path / "missing.json",
    )
    publisher = YouTubePublisher(settings=settings)
    with pytest.raises(YouTubeAuthenticationError, match="not configured"):
        publisher.get_credentials()


def test_youtube_publisher_get_credentials_direct():
    """Test building Google OAuth Credentials from direct settings tokens."""
    settings = Settings(
        youtube_client_id="cid_123",
        youtube_client_secret="csec_456",
        youtube_refresh_token="rtoken_789",
    )
    publisher = YouTubePublisher(settings=settings)

    with patch("google.oauth2.credentials.Credentials.refresh") as mock_refresh:
        creds = publisher.get_credentials()
        assert creds.client_id == "cid_123"
        assert creds.client_secret == "csec_456"
        assert creds.refresh_token == "rtoken_789"
        mock_refresh.assert_called_once()


def test_youtube_publisher_format_metadata_horizontal():
    """Test metadata formatting for horizontal video with clickable chapter timestamps."""
    settings = Settings()
    publisher = YouTubePublisher(settings=settings)

    script = Script(
        topic="The Secret Life of Bees",
        summary="An educational overview of honeybee behavior and communication.",
        scenes=[
            ScriptScene(
                scene_number=1,
                title="Introduction to Hive Mind",
                summary="Intro",
                narration="Bees are incredible.",
                duration_seconds=15,
            ),
            ScriptScene(
                scene_number=2,
                title="The Waggle Dance",
                summary="Waggle dance explained",
                narration="They dance to signal flowers.",
                duration_seconds=20,
            ),
        ],
    )
    storyboard = AnimationStoryboard(
        topic="The Secret Life of Bees",
        style=AnimationStyle(
            style_name="Warm Vector",
            visual_description="warm",
            animation_guidelines="smooth",
        ),
        scenes=[
            SceneAnimation(
                scene_number=1,
                title="Introduction to Hive Mind",
                html_content="<svg></svg>",
                duration_seconds=15.0,
            ),
            SceneAnimation(
                scene_number=2,
                title="The Waggle Dance",
                html_content="<svg></svg>",
                duration_seconds=20.0,
            ),
        ],
    )

    title, description, tags = publisher.format_metadata(
        topic="The Secret Life of Bees - 60s",
        script=script,
        storyboard=storyboard,
        is_vertical=False,
    )

    assert title == "The Secret Life of Bees"
    assert "00:00 - Introduction to Hive Mind" in description
    assert "00:15 - The Waggle Dance" in description
    assert "#CuriosityOnDemand" in description
    assert "CuriosityOnDemand" in tags
    assert "Education" in tags


def test_youtube_publisher_format_metadata_vertical_shorts():
    """Test metadata formatting for vertical video (Shorts format)."""
    settings = Settings()
    publisher = YouTubePublisher(settings=settings)

    title, description, tags = publisher.format_metadata(
        topic="Why Do Cats Purr? - 45s",
        script=None,
        storyboard=None,
        is_vertical=True,
    )

    assert title.endswith("#Shorts")
    assert "Why Do Cats Purr?" in title
    assert "#Shorts" in description
    assert "CuriosityOnDemand" in tags


@pytest.mark.asyncio
async def test_youtube_publisher_publish_video_missing_file(tmp_path):
    """Test that publishing a non-existent video file raises FileNotFoundError."""
    settings = Settings(
        youtube_client_id="cid",
        youtube_client_secret="csec",
        youtube_refresh_token="rtoken",
    )
    publisher = YouTubePublisher(settings=settings)
    missing_video = tmp_path / "ghost_video.mp4"

    with pytest.raises(FileNotFoundError):
        await publisher.publish_video(
            video_path=missing_video,
            topic="Ghost Video",
        )


@pytest.mark.asyncio
async def test_youtube_publisher_publish_video_success(tmp_path):
    """Test successful video upload and URL generation for horizontal video and Short."""
    settings = Settings(
        youtube_client_id="cid",
        youtube_client_secret="csec",
        youtube_refresh_token="rtoken",
    )
    publisher = YouTubePublisher(settings=settings)

    test_video = tmp_path / "test_video.mp4"
    test_video.write_bytes(b"dummy video data")

    mock_insert_req = MagicMock()
    # Simulate resumable chunk progress: first chunk 50%, second chunk finished
    mock_status = MagicMock()
    mock_status.progress.return_value = 0.5
    mock_insert_req.next_chunk.side_effect = [
        (mock_status, None),
        (None, {"id": "yt_video_123"}),
    ]

    mock_service = MagicMock()
    mock_service.videos().insert.return_value = mock_insert_req

    with (
        patch.object(publisher, "get_credentials") as mock_get_creds,
        patch("services.youtube_publisher.build", return_value=mock_service),
    ):
        mock_get_creds.return_value = MagicMock()

        # 1. Test Horizontal Video
        res_horizontal = await publisher.publish_video(
            video_path=test_video,
            topic="Ancient Rome Architecture",
            is_vertical=False,
            privacy_status="unlisted",
        )

        assert res_horizontal.video_id == "yt_video_123"
        assert res_horizontal.video_url == "https://youtu.be/yt_video_123"
        assert res_horizontal.privacy_status == "unlisted"
        assert not res_horizontal.is_short

        # Reset chunk mock
        mock_insert_req.next_chunk.side_effect = [
            (None, {"id": "yt_short_456"}),
        ]

        # 2. Test Vertical Short
        res_short = await publisher.publish_video(
            video_path=test_video,
            topic="Quick Brain Fact",
            is_vertical=True,
            privacy_status="public",
        )

        assert res_short.video_id == "yt_short_456"
        assert res_short.video_url == "https://www.youtube.com/shorts/yt_short_456"
        assert res_short.is_short
        assert res_short.title.endswith("#Shorts")


def test_caption_utils_format_and_generate_srt(
    tmp_path, sample_script, sample_narration_storyboard
):
    """Test formatting SRT timestamps, stripping audio tags, and generating synchronized SRT files."""
    from core.caption_utils import (
        format_srt_timestamp,
        generate_srt_content,
        save_srt_subtitles,
        split_text_into_caption_cues,
        strip_audio_tags,
    )

    assert format_srt_timestamp(0.0) == "00:00:00,000"
    assert format_srt_timestamp(1.25) == "00:00:01,250"
    assert format_srt_timestamp(83.5) == "00:01:23,500"
    assert format_srt_timestamp(3661.005) == "01:01:01,005"

    assert (
        strip_audio_tags("[whispers] Hello [pause] world! [excitedly]")
        == "Hello world!"
    )
    assert (
        strip_audio_tags("<whispers> Hello <long pause> world! <gasp>")
        == "Hello world!"
    )

    cues = split_text_into_caption_cues(
        "<short pause> Imagine a light switch that is not just ON or OFF, <gasp> but pointing in every direction simultaneously.",
        max_words_per_cue=8,
    )
    assert len(cues) >= 2
    assert "<short pause>" not in " ".join(cues)
    assert "<gasp>" not in " ".join(cues)

    srt_text = generate_srt_content(
        script=sample_script,
        narration_storyboard=sample_narration_storyboard,
    )
    assert "1\n00:00:00,000 -->" in srt_text
    # sample_narration_storyboard has 3 scenes of 1.0s each -> total duration ends at 00:00:03,000
    assert "--> 00:00:03,000" in srt_text

    srt_file = tmp_path / "captions.srt"
    saved = save_srt_subtitles(
        output_path=srt_file,
        script=sample_script,
        narration_storyboard=sample_narration_storyboard,
    )
    assert saved == srt_file
    assert srt_file.exists()
    assert srt_file.read_text(encoding="utf-8") == srt_text


@pytest.mark.asyncio
async def test_youtube_publisher_publish_video_with_captions(tmp_path):
    """Test uploading video with synchronized .srt captions file to YouTube."""
    settings = Settings(
        youtube_client_id="cid",
        youtube_client_secret="csec",
        youtube_refresh_token="rtoken",
    )
    publisher = YouTubePublisher(settings=settings)

    test_video = tmp_path / "video.mp4"
    test_video.write_bytes(b"dummy video data")
    test_srt = tmp_path / "captions.srt"
    test_srt.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nHello world\n", encoding="utf-8"
    )

    mock_insert_req = MagicMock()
    mock_insert_req.next_chunk.return_value = (None, {"id": "yt_captioned_789"})

    mock_captions_insert_req = MagicMock()
    mock_captions_insert_req.execute.return_value = {"id": "cap_track_1"}

    mock_service = MagicMock()
    mock_service.videos().insert.return_value = mock_insert_req
    mock_service.captions().insert.return_value = mock_captions_insert_req

    with (
        patch.object(publisher, "get_credentials", return_value=MagicMock()),
        patch("services.youtube_publisher.build", return_value=mock_service),
    ):
        res = await publisher.publish_video(
            video_path=test_video,
            topic="Quantum Mechanics",
            captions_path=test_srt,
        )

        assert res.video_id == "yt_captioned_789"
        assert res.captions_uploaded is True
        mock_service.captions().insert.assert_called_once()
        cap_call_kwargs = mock_service.captions().insert.call_args[1]
        assert cap_call_kwargs["body"]["snippet"]["videoId"] == "yt_captioned_789"
        assert cap_call_kwargs["body"]["snippet"]["language"] == "en"
