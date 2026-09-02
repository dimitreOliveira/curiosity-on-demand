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
        # Simulate creating the output file
        output_mp4.write_bytes(b"FakeAssembledVideo")
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
