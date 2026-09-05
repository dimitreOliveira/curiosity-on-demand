"""Unit tests for AnimationRenderer service."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from services.renderer import AnimationRenderer


@pytest.mark.asyncio
async def test_renderer_render_sample_frame_mocked(mock_settings, tmp_path):
    """Test render_sample_frame interacting with Playwright page screenshot."""
    renderer = AnimationRenderer(settings=mock_settings)
    out_img = tmp_path / "renders" / "sample.png"

    mock_page = AsyncMock()
    mock_browser = AsyncMock()
    mock_browser.new_page.return_value = mock_page
    mock_playwright = AsyncMock()
    mock_playwright.chromium.launch.return_value = mock_browser

    # Mock screenshot to actually create a small file
    async def mock_screenshot(path, **kwargs):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x89PNG\r\n\x1a\nFakePngData")

    mock_page.screenshot.side_effect = mock_screenshot

    with patch("services.renderer.async_playwright") as mock_ap:
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_playwright
        mock_cm.__aexit__.return_value = None
        mock_ap.return_value = mock_cm

        res = await renderer.render_sample_frame(
            html_content="<html><body>Test</body></html>",
            output_image_path=out_img,
            width=1280,
            height=720,
        )

        assert res == out_img
        assert out_img.exists()
        mock_page.set_content.assert_called_once()
        mock_page.screenshot.assert_called_once()


@pytest.mark.asyncio
async def test_renderer_assemble_video_single_file(mock_settings, tmp_path):
    """Test assemble_video with a single scene video simply copies it."""
    renderer = AnimationRenderer(settings=mock_settings)

    scene_1 = tmp_path / "scene_1.mp4"
    scene_1.write_bytes(b"FakeVideoBytesScene1")
    output_mp4 = tmp_path / "final.mp4"

    res = await renderer.assemble_video([scene_1], output_mp4)
    assert res == output_mp4
    assert output_mp4.exists()
    assert output_mp4.read_bytes() == b"FakeVideoBytesScene1"


@pytest.mark.asyncio
async def test_renderer_assemble_video_multiple_files_mocked(mock_settings, tmp_path):
    """Test assemble_video executing ffmpeg concat command."""
    renderer = AnimationRenderer(settings=mock_settings)

    scene_1 = tmp_path / "scene_1.mp4"
    scene_1.write_bytes(b"FakeScene1")
    scene_2 = tmp_path / "scene_2.mp4"
    scene_2.write_bytes(b"FakeScene2")

    output_mp4 = tmp_path / "final.mp4"

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"", b"")

    async def mock_create_subprocess_exec(*args, **kwargs):
        # Simulate creating the destination file specified in FFmpeg arguments
        Path(args[-1]).write_bytes(b"FakeAssembledVideo")
        return mock_proc

    with patch(
        "asyncio.create_subprocess_exec", side_effect=mock_create_subprocess_exec
    ):
        res = await renderer.assemble_video([scene_1, scene_2], output_mp4)
        assert res == output_mp4
        assert output_mp4.exists()
        assert output_mp4.read_bytes() == b"FakeAssembledVideo"


@pytest.mark.asyncio
async def test_renderer_assemble_video_empty_raises(mock_settings, tmp_path):
    """Test assemble_video raising ValueError when given empty list."""
    renderer = AnimationRenderer(settings=mock_settings)
    out_mp4 = tmp_path / "out.mp4"

    with pytest.raises(ValueError, match="No scene video paths provided"):
        await renderer.assemble_video([], out_mp4)


@pytest.mark.asyncio
async def test_renderer_render_scenes_parallel(
    mock_settings, tmp_path, sample_scene_animation
):
    """Test render_scenes_parallel concurrently rendering multiple scene animations."""
    renderer = AnimationRenderer(settings=mock_settings)
    out_dir = tmp_path / "scenes_parallel"

    scene_2 = sample_scene_animation.model_copy(deep=True)
    scene_2.scene_number = 2
    scene_2.title = "Scene Two"

    async def mock_render_single(html_content, output_video_path, **kwargs):
        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        output_video_path.write_bytes(f"Rendered_{output_video_path.name}".encode())
        return output_video_path

    renderer.render_scene_video = AsyncMock(side_effect=mock_render_single)

    paths = await renderer.render_scenes_parallel(
        scenes=[sample_scene_animation, scene_2],
        output_dir=out_dir,
        concurrency=2,
    )

    assert len(paths) == 2
    assert paths[0].name == "scene_1.mp4"
    assert paths[1].name == "scene_2.mp4"
    assert renderer.render_scene_video.call_count == 2


@pytest.mark.asyncio
async def test_renderer_mux_audio_to_video(mock_settings, tmp_path):
    """Test mux_audio_to_video invoking FFmpeg to merge video and audio."""
    renderer = AnimationRenderer(settings=mock_settings)

    video_in = tmp_path / "in.mp4"
    video_in.write_bytes(b"FakeVideoBytes")
    audio_in = tmp_path / "in.wav"
    audio_in.write_bytes(b"FakeAudioBytes")
    video_out = tmp_path / "muxed.mp4"

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"", b"")

    async def mock_subprocess(*args, **kwargs):
        video_out.write_bytes(b"MuxedVideoWithAudio")
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
        res = await renderer.mux_audio_to_video(
            video_path=video_in,
            audio_path=audio_in,
            output_path=video_out,
        )
        assert res == video_out
        assert video_out.exists()
        assert video_out.read_bytes() == b"MuxedVideoWithAudio"


@pytest.mark.asyncio
async def test_renderer_assemble_video_single_file_with_audio(mock_settings, tmp_path):
    """Test assemble_video with a single scene video calling mux_audio_to_video."""
    renderer = AnimationRenderer(settings=mock_settings)

    scene_1 = tmp_path / "scene_1.mp4"
    scene_1.write_bytes(b"FakeScene1")
    audio_file = tmp_path / "narration.wav"
    audio_file.write_bytes(b"FakeAudio")
    output_mp4 = tmp_path / "final_with_audio.mp4"

    renderer.mux_audio_to_video = AsyncMock(return_value=output_mp4)

    res = await renderer.assemble_video([scene_1], output_mp4, audio_path=audio_file)
    assert res == output_mp4
    renderer.mux_audio_to_video.assert_called_once_with(
        video_path=scene_1,
        audio_path=audio_file,
        output_path=output_mp4,
    )


@pytest.mark.asyncio
async def test_renderer_get_video_duration(mock_settings, tmp_path):
    """Test get_video_duration parsing duration from FFmpeg output."""
    renderer = AnimationRenderer(settings=mock_settings)
    video_p = tmp_path / "test.mp4"
    video_p.write_bytes(b"dummy")

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (
        b"",
        (
            b"Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'test.mp4':\n"
            b"  Duration: 00:01:23.45, start: 0.000000, bitrate: 1234 kb/s\n"
        ),
    )

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        dur = await renderer.get_video_duration(video_p)
        assert dur == 83.45


@pytest.mark.asyncio
async def test_renderer_adjust_video_duration(mock_settings, tmp_path):
    """Test adjust_video_duration applying setpts speed scaling filter."""
    renderer = AnimationRenderer(settings=mock_settings)
    video_in = tmp_path / "in.mp4"
    video_in.write_bytes(b"dummy")
    video_out = tmp_path / "adjusted.mp4"

    renderer.get_media_duration = AsyncMock(return_value=10.0)

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"", b"")

    executed_cmd = []

    async def mock_exec(*args, **kwargs):
        nonlocal executed_cmd
        executed_cmd = list(args)
        video_out.write_bytes(b"adjusted_video_bytes")
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        res = await renderer.adjust_video_duration(
            video_path=video_in,
            target_duration=12.5,
            output_path=video_out,
        )
        assert res == video_out
        assert video_out.exists()
        # pts_factor = 12.5 / 10.0 = 1.25
        assert "setpts=1.250000*PTS" in " ".join(executed_cmd)


@pytest.mark.asyncio
async def test_renderer_mux_scene_audio_video(mock_settings, tmp_path):
    """Test mux_scene_audio_video synchronizing video duration to audio and muxing."""
    renderer = AnimationRenderer(settings=mock_settings)
    video_in = tmp_path / "in.mp4"
    video_in.write_bytes(b"dummy_video")
    audio_in = tmp_path / "in.wav"
    audio_in.write_bytes(b"dummy_audio")
    output_p = tmp_path / "synced.mp4"

    # Video is 10.0s, Audio is 7.5s (speed up by factor 0.75)
    async def mock_dur(path):
        return 7.5 if Path(path).suffix == ".wav" else 10.0

    renderer.get_media_duration = AsyncMock(side_effect=mock_dur)

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"", b"")

    executed_cmd = []

    async def mock_exec(*args, **kwargs):
        nonlocal executed_cmd
        executed_cmd = list(args)
        output_p.write_bytes(b"synced_scene_bytes")
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        res = await renderer.mux_scene_audio_video(
            video_path=video_in,
            audio_path=audio_in,
            output_path=output_p,
        )
        assert res == output_p
        assert output_p.exists()
        assert "setpts=0.750000*PTS" in " ".join(executed_cmd)


@pytest.mark.asyncio
async def test_renderer_assemble_video_per_scene_sync(mock_settings, tmp_path):
    """Test assemble_video synchronizing and muxing each scene individually."""
    renderer = AnimationRenderer(settings=mock_settings)

    scene_1 = tmp_path / "scene_1.mp4"
    scene_1.write_bytes(b"FakeScene1")
    scene_2 = tmp_path / "scene_2.mp4"
    scene_2.write_bytes(b"FakeScene2")

    audio_1 = tmp_path / "audio_1.wav"
    audio_1.write_bytes(b"FakeAudio1")
    audio_2 = tmp_path / "audio_2.wav"
    audio_2.write_bytes(b"FakeAudio2")

    output_mp4 = tmp_path / "final_synced.mp4"

    async def mock_mux_scene(video_path, audio_path, output_path, **kwargs):
        output_path.write_bytes(f"Synced_{video_path.name}_{audio_path.name}".encode())
        return output_path

    renderer.mux_scene_audio_video = AsyncMock(side_effect=mock_mux_scene)

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"", b"")

    async def mock_concat(*args, **kwargs):
        output_mp4.write_bytes(b"MasterConcatVideo")
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_concat):
        res = await renderer.assemble_video(
            scene_video_paths=[scene_1, scene_2],
            output_video_path=output_mp4,
            scene_audio_paths=[audio_1, audio_2],
        )
        assert res == output_mp4
        assert output_mp4.exists()
        assert renderer.mux_scene_audio_video.call_count == 2
