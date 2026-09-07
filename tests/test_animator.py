"""Unit tests for AnimationPlannerAgent and SceneAnimatorAgent."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.animation_planner import AnimationPlannerAgent
from agents.scene_animator import SceneAnimatorAgent, extract_html_code
from core.models import AnimationStoryboard, AnimationStyle, SceneAnimation


def test_extract_html_code():
    """Test extracting clean HTML from various LLM response formats."""
    # With ```html code fence
    markdown_html = 'Here is the animation:\n```html\n<!DOCTYPE html><html><head></head><body><canvas id="stage"></canvas><script>console.log(1);</script></body></html>\n```\nEnjoy!'
    extracted = extract_html_code(markdown_html)
    assert extracted.startswith("<!DOCTYPE html>")
    assert extracted.endswith("</html>")
    assert '<canvas id="stage">' in extracted

    # Direct raw html
    raw = "<!DOCTYPE html><html><body><canvas></canvas></body></html>"
    assert extract_html_code(raw) == raw

    # Generic code block
    generic = "```\n<!DOCTYPE html><html><body><canvas></canvas></body></html>\n```"
    extracted_generic = extract_html_code(generic)
    assert (
        extracted_generic
        == "<!DOCTYPE html><html><body><canvas></canvas></body></html>"
    )


@pytest.mark.asyncio
async def test_animation_planner_plan_style(
    mock_settings, sample_script, sample_animation_style
):
    """Test AnimationPlannerAgent formulating visual style."""
    agent = AnimationPlannerAgent(settings=mock_settings)

    mock_resp = MagicMock()
    mock_resp.parsed = sample_animation_style
    agent.client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    style = await agent.plan_style(
        topic="How Quantum Computers Work",
        script=sample_script,
    )

    assert isinstance(style, AnimationStyle)
    assert style.style_name == "Dark Neon Quantum Blueprint"
    assert len(style.color_palette) >= 3
    agent.client.aio.models.generate_content.assert_called_once()


@pytest.mark.asyncio
async def test_animation_planner_plan_style_with_feedback(
    mock_settings, sample_script, sample_animation_style
):
    """Test AnimationPlannerAgent revising style based on user feedback."""
    agent = AnimationPlannerAgent(settings=mock_settings)

    revised_style = sample_animation_style.model_copy(deep=True)
    revised_style.style_name = "Minimalist White Blueprint"
    revised_style.color_palette = ["#FFFFFF", "#0066FF", "#333333"]

    mock_resp = MagicMock()
    mock_resp.parsed = revised_style
    agent.client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    style = await agent.plan_style(
        topic="How Quantum Computers Work",
        script=sample_script,
        feedback="Make it a bright white background with clean blue lines.",
        previous_style=sample_animation_style,
    )

    assert style.style_name == "Minimalist White Blueprint"
    assert style.color_palette[0] == "#FFFFFF"
    agent.client.aio.models.generate_content.assert_called_once()


@pytest.mark.asyncio
async def test_scene_animator_animate_scene(
    mock_settings, sample_script, sample_animation_style
):
    """Test SceneAnimatorAgent generating unconstrained HTML5 Canvas animation code."""
    agent = SceneAnimatorAgent(settings=mock_settings)

    raw_html_response = (
        "```html\n"
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head><style>body { margin: 0; }</style></head>\n"
        "<body>\n"
        '<canvas id="stage" width="1280" height="720"></canvas>\n'
        "<script>\n"
        "const canvas = document.getElementById('stage');\n"
        "const ctx = canvas.getContext('2d');\n"
        "let lastTime = 0;\n"
        "function loop(t) {\n"
        "  requestAnimationFrame(loop);\n"
        "}\n"
        "requestAnimationFrame(loop);\n"
        "</script>\n"
        "</body>\n"
        "</html>\n"
        "```"
    )

    mock_resp = MagicMock()
    mock_resp.text = raw_html_response
    agent.client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    result = await agent.animate_scene(
        topic="How Quantum Computers Work",
        scene=sample_script.scenes[0],
        style=sample_animation_style,
        duration_seconds=12,
    )

    assert isinstance(result, SceneAnimation)
    assert result.scene_number == 1
    assert result.duration_seconds == 12
    assert '<canvas id="stage"' in result.html_content
    assert result.html_content.startswith("<!DOCTYPE html>")
    assert result.html_content.endswith("</html>")
    agent.client.aio.models.generate_content.assert_called_once()


@pytest.mark.asyncio
async def test_scene_animator_animate_storyboard(
    mock_settings, sample_script, sample_animation_style, sample_scene_animation
):
    """Test SceneAnimatorAgent generating storyboard in parallel with Scene 1 reuse."""
    agent = SceneAnimatorAgent(settings=mock_settings)

    mock_scene = sample_scene_animation.model_copy(deep=True)
    agent.animate_scene = AsyncMock(return_value=mock_scene)

    storyboard = await agent.animate_storyboard(
        topic="How Quantum Computers Work",
        script=sample_script,
        style=sample_animation_style,
        sample_scene_1=sample_scene_animation,
    )

    assert isinstance(storyboard, AnimationStoryboard)
    assert storyboard.topic == "How Quantum Computers Work"
    assert len(storyboard.scenes) == len(sample_script.scenes)
    # Scene 1 was passed as sample_scene_1, so animate_scene is called only for scenes 2 and 3
    assert agent.animate_scene.call_count == len(sample_script.scenes) - 1


@pytest.mark.asyncio
async def test_scene_animator_animate_scene_vertical(
    mock_settings, sample_script, sample_animation_style
):
    """Test SceneAnimatorAgent generating vertical 9:16 animation for short videos."""
    agent = SceneAnimatorAgent(settings=mock_settings)

    raw_html_response = (
        "```html\n"
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head><style>body { margin: 0; }</style></head>\n"
        "<body>\n"
        '<canvas id="stage" width="1080" height="1920"></canvas>\n'
        "<script>\n"
        "const canvas = document.getElementById('stage');\n"
        "const ctx = canvas.getContext('2d');\n"
        "</script>\n"
        "</body>\n"
        "</html>\n"
        "```"
    )

    mock_resp = MagicMock()
    mock_resp.text = raw_html_response
    agent.client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    result = await agent.animate_scene(
        topic="Quick Quantum Intro (60s)",
        scene=sample_script.scenes[0],
        style=sample_animation_style,
        duration_seconds=15,
        total_video_duration=60,
    )

    assert isinstance(result, SceneAnimation)
    assert '<canvas id="stage" width="1080" height="1920">' in result.html_content
    agent.client.aio.models.generate_content.assert_called_once()
    # Check prompt passed to generate_content
    call_args = agent.client.aio.models.generate_content.call_args
    prompt_used = call_args[1].get("contents", "")
    assert "9:16 Vertical Portrait" in prompt_used
    assert "1080x1920" in prompt_used


@pytest.mark.asyncio
async def test_scene_animator_animate_storyboard_vertical(
    mock_settings, sample_animation_style
):
    """Test SceneAnimatorAgent auto-detecting vertical format for storyboard with duration <= 120s."""
    from core.models import Script, ScriptScene

    short_script = Script(
        topic="Neutron Stars in 60s",
        summary="Short video",
        scenes=[
            ScriptScene(
                scene_number=1,
                title="Scene 1",
                summary="Intro",
                description="Intro visuals",
                duration_seconds=30,
                narration="Welcome to neutron stars.",
            ),
            ScriptScene(
                scene_number=2,
                title="Scene 2",
                summary="Climax",
                description="Collapse visuals",
                duration_seconds=30,
                narration="A massive core collapses.",
            ),
        ],
    )

    agent = SceneAnimatorAgent(settings=mock_settings)
    mock_anim = SceneAnimation(
        scene_number=1,
        title="Scene 1",
        html_content="<!DOCTYPE html><html><body><canvas width='1080' height='1920'></canvas></body></html>",
        duration_seconds=30,
    )
    agent.animate_scene = AsyncMock(return_value=mock_anim)

    storyboard = await agent.animate_storyboard(
        topic="Neutron Stars in 60s",
        script=short_script,
        style=sample_animation_style,
    )

    assert isinstance(storyboard, AnimationStoryboard)
    assert len(storyboard.scenes) == 2
    assert agent.animate_scene.call_count == 2
    # Verify vertical dimensions were passed down
    call_kwargs = agent.animate_scene.call_args_list[0][1]
    assert call_kwargs["is_vertical"] is True
    assert call_kwargs["width"] == 1080
    assert call_kwargs["height"] == 1920
