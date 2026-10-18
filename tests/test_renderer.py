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


@pytest.mark.asyncio
async def test_renderer_create_video_preview_stream_copy_success(
    mock_settings, tmp_path
):
    """Test create_video_preview executing fast stream-copy successfully within size limits."""
    renderer = AnimationRenderer(settings=mock_settings)
    source_mp4 = tmp_path / "full_video.mp4"
    source_mp4.write_bytes(b"FullVideoContent")
    preview_mp4 = tmp_path / "preview.mp4"

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"", b"")

    async def mock_ffmpeg(*cmd, **kwargs):
        # Write 10KB dummy preview file
        preview_mp4.write_bytes(b"A" * 10240)
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_ffmpeg) as mock_exec:
        result = await renderer.create_video_preview(
            video_path=source_mp4,
            output_path=preview_mp4,
            max_duration_seconds=180.0,
            max_file_size_bytes=50 * 1024 * 1024,
        )
        assert result == preview_mp4
        assert preview_mp4.exists()
        assert mock_exec.call_count == 1
        # Assert -c copy was used in the first call
        first_cmd = mock_exec.call_args_list[0][0]
        assert "copy" in first_cmd


@pytest.mark.asyncio
async def test_renderer_create_video_preview_fallback_on_large_size(
    mock_settings, tmp_path
):
    """Test create_video_preview falling back to re-encode when stream-copy exceeds size limit."""
    renderer = AnimationRenderer(settings=mock_settings)
    source_mp4 = tmp_path / "full_video.mp4"
    source_mp4.write_bytes(b"FullVideoContent")
    preview_mp4 = tmp_path / "preview.mp4"

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"", b"")

    call_count = 0

    async def mock_ffmpeg(*cmd, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call (stream-copy): produce file that exceeds max size (2000 bytes > 1000 bytes)
            preview_mp4.write_bytes(b"B" * 2000)
        else:
            # Second call (re-encode): produce compressed file (500 bytes <= 1000 bytes)
            preview_mp4.write_bytes(b"C" * 500)
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_ffmpeg) as mock_exec:
        result = await renderer.create_video_preview(
            video_path=source_mp4,
            output_path=preview_mp4,
            max_duration_seconds=180.0,
            max_file_size_bytes=1000,
        )
        assert result == preview_mp4
        assert preview_mp4.stat().st_size == 500
        # Should have executed stream-copy first, then fallback re-encode
        assert mock_exec.call_count == 2
        second_cmd = mock_exec.call_args_list[1][0]
        assert "libx264" in second_cmd


@pytest.mark.asyncio
async def test_renderer_create_video_preview_validation(mock_settings, tmp_path):
    """Test create_video_preview parameter validations."""
    renderer = AnimationRenderer(settings=mock_settings)
    non_existent = tmp_path / "missing.mp4"
    out_path = tmp_path / "preview.mp4"

    with pytest.raises(FileNotFoundError, match="Source video for preview not found"):
        await renderer.create_video_preview(non_existent, out_path)

    existing = tmp_path / "exists.mp4"
    existing.write_bytes(b"content")

    with pytest.raises(ValueError, match="max_duration_seconds must be positive"):
        await renderer.create_video_preview(
            existing, out_path, max_duration_seconds=0.0
        )


@pytest.mark.asyncio
async def test_renderer_render_scenes_parallel_shared_browser(
    mock_settings, tmp_path, sample_scene_animation
):
    """Test render_scenes_parallel launches Chromium once and shares it across scenes."""
    renderer = AnimationRenderer(settings=mock_settings)
    out_dir = tmp_path / "scenes_shared_browser"

    scene_2 = sample_scene_animation.model_copy(deep=True)
    scene_2.scene_number = 2
    scene_2.title = "Scene Two"

    mock_browser = AsyncMock()
    mock_playwright = AsyncMock()
    mock_playwright.chromium.launch.return_value = mock_browser

    async def mock_record(browser, html_content, output_video_path, **kwargs):
        assert browser is mock_browser
        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        output_video_path.write_bytes(f"Rendered_{output_video_path.name}".encode())
        return output_video_path

    renderer._record_and_transcode = AsyncMock(side_effect=mock_record)

    with patch("services.renderer.async_playwright") as mock_ap:
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_playwright
        mock_cm.__aexit__.return_value = None
        mock_ap.return_value = mock_cm

        paths = await renderer.render_scenes_parallel(
            scenes=[sample_scene_animation, scene_2],
            output_dir=out_dir,
            concurrency=2,
        )

        assert len(paths) == 2
        # Verify Chromium was launched once and closed once
        mock_playwright.chromium.launch.assert_called_once_with(headless=True)
        mock_browser.close.assert_called_once()
        assert renderer._record_and_transcode.call_count == 2


@pytest.mark.asyncio
async def test_renderer_assemble_video_parallel_muxing(mock_settings, tmp_path):
    """Test assemble_video concurrently muxes all scenes and preserves scene ordering."""
    renderer = AnimationRenderer(settings=mock_settings)

    scenes = []
    audios = []
    for i in range(1, 4):
        v = tmp_path / f"scene_{i}.mp4"
        v.write_bytes(f"FakeScene{i}".encode())
        a = tmp_path / f"audio_{i}.wav"
        a.write_bytes(f"FakeAudio{i}".encode())
        scenes.append(v)
        audios.append(a)

    out_mp4 = tmp_path / "final_parallel.mp4"

    async def mock_mux(video_path, audio_path, output_path, **kwargs):
        output_path.write_bytes(f"Synced_{video_path.name}_{audio_path.name}".encode())
        return output_path

    renderer.mux_scene_audio_video = AsyncMock(side_effect=mock_mux)

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"", b"")

    async def mock_concat(*args, **kwargs):
        out_mp4.write_bytes(b"ConcatenatedMaster")
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_concat):
        result = await renderer.assemble_video(
            scene_video_paths=scenes,
            output_video_path=out_mp4,
            scene_audio_paths=audios,
        )

        assert result == out_mp4
        assert out_mp4.exists()
        assert renderer.mux_scene_audio_video.call_count == 3


@pytest.mark.asyncio
async def test_renderer_render_sample_frame_vertical(mock_settings, tmp_path):
    """Test render_sample_frame with vertical dimensions (720x1280)."""
    renderer = AnimationRenderer(settings=mock_settings)
    out_img = tmp_path / "renders" / "sample_vertical.png"

    mock_page = AsyncMock()
    mock_browser = AsyncMock()
    mock_browser.new_page.return_value = mock_page
    mock_playwright = AsyncMock()
    mock_playwright.chromium.launch.return_value = mock_browser

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
            html_content="<html><body>Test Vertical</body></html>",
            output_image_path=out_img,
            width=720,
            height=1280,
        )

        assert res == out_img
        assert out_img.exists()
        # Check viewport width and height passed to browser.new_page
        mock_browser.new_page.assert_called_once_with(
            viewport={"width": 720, "height": 1280},
            device_scale_factor=1,
        )


@pytest.mark.asyncio
async def test_renderer_render_scenes_parallel_with_custom_dimensions(
    mock_settings, tmp_path, sample_scene_animation
):
    """Test render_scenes_parallel forwards vertical dimensions (720x1280) to render_scene_video."""
    renderer = AnimationRenderer(settings=mock_settings)
    out_dir = tmp_path / "renders_vertical"

    scene_2 = sample_scene_animation.model_copy(
        update={"scene_number": 2, "duration_seconds": 15}
    )

    async def mock_render_video(
        html_content, output_video_path, duration_seconds, width, height, **kwargs
    ):
        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        output_video_path.write_bytes(f"FakeScene_{width}x{height}".encode())
        return output_video_path

    renderer.render_scene_video = AsyncMock(side_effect=mock_render_video)

    paths = await renderer.render_scenes_parallel(
        scenes=[sample_scene_animation, scene_2],
        output_dir=out_dir,
        concurrency=2,
        width=720,
        height=1280,
    )

    assert len(paths) == 2
    assert renderer.render_scene_video.call_count == 2
    call_kwargs_1 = renderer.render_scene_video.call_args_list[0][1]
    assert call_kwargs_1["width"] == 720
    assert call_kwargs_1["height"] == 1280


@pytest.mark.asyncio
async def test_renderer_deterministic_frame_stepping_and_single_pass_audio(
    mock_settings, tmp_path, sample_wav_file
):
    """Test _record_and_transcode injects DETERMINISTIC_TIME_SHIM, steps virtual frames, and muxes audio in a single FFmpeg pass."""
    from unittest.mock import MagicMock

    renderer = AnimationRenderer(settings=mock_settings)
    out_video = tmp_path / "single_pass_scene.mp4"

    # Mock audio duration to 0.2s at 10fps -> 2 frames
    renderer.get_media_duration = AsyncMock(return_value=0.2)

    mock_page = AsyncMock()
    mock_page.screenshot.return_value = b"\xff\xd8\xff\xe0FakeJpegFrame"

    mock_context = AsyncMock()
    mock_context.new_page.return_value = mock_page

    mock_browser = AsyncMock()
    mock_browser.new_context.return_value = mock_context

    mock_stdin = MagicMock()
    mock_stdin.write = MagicMock()
    mock_stdin.drain = AsyncMock()
    mock_stdin.close = MagicMock()

    mock_proc = AsyncMock()
    mock_proc.stdin = mock_stdin
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"", b"")

    executed_cmd = []

    async def mock_create_subprocess(*args, **kwargs):
        nonlocal executed_cmd
        executed_cmd = list(args)
        out_video.parent.mkdir(parents=True, exist_ok=True)
        out_video.write_bytes(b"SinglePassEncodedMP4")
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_create_subprocess):
        res = await renderer.render_scene_video(
            html_content="<html><body><canvas></canvas></body></html>",
            output_video_path=out_video,
            duration_seconds=1.0,  # native duration 1.0s scaled to 0.2s audio
            width=1280,
            height=720,
            fps=10,
            browser=mock_browser,
            audio_path=sample_wav_file,
        )

    assert res == out_video
    assert out_video.exists()
    # Virtual time shim was injected into context
    mock_context.add_init_script.assert_called_once()
    # 0.2s * 10 fps = 2 frames stepped deterministically
    assert mock_page.evaluate.call_count == 2
    assert (
        "window.__stepVirtualFrame(0.0)" in mock_page.evaluate.call_args_list[0][0][0]
    )
    assert (
        "window.__stepVirtualFrame(500.0)" in mock_page.evaluate.call_args_list[1][0][0]
    )
    assert mock_page.screenshot.call_count == 2
    assert mock_stdin.write.call_count == 2

    # Verify FFmpeg command used lossless png image2pipe, crf 18, animation tuning, and included the audio file in a single pass
    cmd_str = " ".join(executed_cmd)
    assert "-f image2pipe" in cmd_str
    assert "-vcodec png" in cmd_str
    assert "-tune animation" in cmd_str
    assert "-crf 18" in cmd_str
    assert str(sample_wav_file.resolve()) in cmd_str
    assert "-c:a aac" in cmd_str
    assert "-b:a 192k" in cmd_str
    mock_page.screenshot.assert_called_with(type="png", full_page=False)


@pytest.mark.asyncio
async def test_renderer_assemble_video_scenes_pre_muxed_skips_reencode(
    mock_settings, tmp_path
):
    """Test assemble_video with scenes_pre_muxed=True concatenates directly via stream copy without calling mux_scene_audio_video."""
    renderer = AnimationRenderer(settings=mock_settings)

    scene_1 = tmp_path / "scene_1.mp4"
    scene_1.write_bytes(b"PreMuxedScene1")
    scene_2 = tmp_path / "scene_2.mp4"
    scene_2.write_bytes(b"PreMuxedScene2")

    audio_1 = tmp_path / "audio_1.wav"
    audio_1.write_bytes(b"Audio1")
    audio_2 = tmp_path / "audio_2.wav"
    audio_2.write_bytes(b"Audio2")

    out_mp4 = tmp_path / "master_pre_muxed.mp4"

    renderer.mux_scene_audio_video = AsyncMock()

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"", b"")

    executed_cmd = []

    async def mock_concat(*args, **kwargs):
        nonlocal executed_cmd
        executed_cmd = list(args)
        out_mp4.write_bytes(b"FastConcatMaster")
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_concat):
        res = await renderer.assemble_video(
            scene_video_paths=[scene_1, scene_2],
            output_video_path=out_mp4,
            scene_audio_paths=[audio_1, audio_2],
            scenes_pre_muxed=True,
        )

    assert res == out_mp4
    assert out_mp4.exists()
    # Must NOT re-encode per scene when scenes_pre_muxed=True
    renderer.mux_scene_audio_video.assert_not_called()
    assert "-c" in executed_cmd
    assert "copy" in executed_cmd
