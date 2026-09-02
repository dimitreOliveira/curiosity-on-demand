"""Pytest fixtures and configuration for unit and integration testing."""

import pytest
import pytest_asyncio

from config.settings import Settings
from core.database import DatabaseManager
from core.models import (
    AnimationStoryboard,
    AnimationStyle,
    ResearchReport,
    ResearchSection,
    SceneAnimation,
    Script,
    ScriptScene,
)


@pytest.fixture(autouse=True)
def prevent_unmocked_api_calls(monkeypatch):
    """Guard fixture ensuring no real Gemini API network calls are ever made in tests."""

    async def forbidden_async_call(*args, **kwargs):
        raise RuntimeError(
            "Forbidden unmocked async Gemini API call attempted during test suite execution!"
        )

    def forbidden_sync_call(*args, **kwargs):
        raise RuntimeError(
            "Forbidden unmocked sync Gemini API call attempted during test suite execution!"
        )

    monkeypatch.setattr(
        "google.genai.models.AsyncModels.generate_content", forbidden_async_call
    )
    monkeypatch.setattr(
        "google.genai.models.Models.generate_content", forbidden_sync_call
    )


@pytest.fixture
def mock_settings(tmp_path):
    """Provide a test Settings instance with temporary directories."""
    storage_dir = tmp_path / "storage"
    db_path = storage_dir / "test.db"

    return Settings(
        _env_file=None,
        GEMINI_API_KEY="test_api_key",
        GEMINI_MODEL="gemini-3.7-flash",
        RESEARCH_MODEL="gemini-3.7-flash",
        EVALUATOR_MODEL="gemini-3.7-flash",
        SCRIPT_MODEL="gemini-3.7-flash",
        ANIMATOR_MODEL="gemini-3.7-flash",
        VIDEO_WIDTH=1280,
        VIDEO_HEIGHT=720,
        DEFAULT_SCENE_DURATION_SECONDS=10,
        TELEGRAM_BOT_TOKEN="test_token",
        TELEGRAM_ALLOWED_USERS=[],
        STORAGE_DIR=storage_dir,
        SQLITE_DB_PATH=db_path,
    )


@pytest_asyncio.fixture
async def memory_db():
    """Create an in-memory SQLite database manager for isolated testing."""
    db = DatabaseManager(db_url="sqlite+aiosqlite:///:memory:")
    await db.init_db()
    return db


@pytest.fixture
def sample_research_report():
    """Sample ResearchReport for testing."""
    return ResearchReport(
        topic="How Quantum Computers Work",
        summary="Quantum computing harnesses superposition and entanglement to solve problems intractable for classical computers.",
        sections=[
            ResearchSection(
                topic="Qubits & Superposition",
                content="Unlike classical bits (0 or 1), superposition allows exponential computational scale where qubits represent combinations of states.",
            ),
            ResearchSection(
                topic="Quantum Entanglement",
                content="Quantum entanglement links pairs of qubits so that the state of one instantly dictates the state of another, enabling massive parallel operations.",
            ),
            ResearchSection(
                topic="Video Storytelling Angles",
                content="Start with a visual metaphor comparing a single light switch to a sphere of infinite switch positions.",
            ),
        ],
    )


@pytest.fixture
def sample_script():
    """Sample Script for testing."""
    return Script(
        topic="How Quantum Computers Work",
        summary="A 5-minute educational journey into quantum computing, exploring superposition, entanglement, and future impact.",
        scenes=[
            ScriptScene(
                scene_number=1,
                title="The Light Switch Dilemma",
                summary="Hook introducing the limit of classical bits versus quantum states.",
                description="A visual metaphor featuring a mechanical light switch toggling between 0 and 1, which seamlessly transforms into a luminous glowing Bloch sphere with spinning quantum state vectors.",
                duration_seconds=45,
                narration="Imagine a light switch that is not just ON or OFF, but pointing in every direction simultaneously. Welcome to quantum physics.",
            ),
            ScriptScene(
                scene_number=2,
                title="Superposition & Entanglement",
                summary="Explains the core physics mechanisms.",
                description="Split screen comparing binary silicon transistors with two entangled glowing particles linked by vibrating geometric SVG energy beams.",
                duration_seconds=60,
                narration="In a classical computer, each bit is a binary 0 or 1. But a qubit can exist in a superposition of both.",
            ),
            ScriptScene(
                scene_number=3,
                title="The Quantum Horizon",
                summary="Wrap-up on real-world applications and future implications.",
                description="A futuristic crystalline quantum computing core surrounded by orbiting molecular simulations and complex cryptographic lock animations.",
                duration_seconds=50,
                narration="While quantum computers won't replace your laptop, they will unlock simulations once thought impossible.",
            ),
        ],
    )


@pytest.fixture
def sample_animation_style():
    """Sample AnimationStyle for testing."""
    return AnimationStyle(
        style_name="Dark Neon Quantum Blueprint",
        visual_description="Sleek dark background (#0B0F19) with glowing cyan (#00F0FF) and magenta (#FF0055) vector schematics, particle orbits, and crisp mathematical coordinate grids.",
        color_palette=["#0B0F19", "#00F0FF", "#FF0055", "#FFFFFF"],
        font_family="Inter, sans-serif",
        animation_guidelines="Smooth continuous rotation for quantum state vectors, pulsating energy nodes, dynamic SVG line tracing for entanglement links.",
    )


@pytest.fixture
def sample_scene_animation():
    """Sample SceneAnimation for testing."""
    return SceneAnimation(
        scene_number=1,
        title="The Light Switch Dilemma",
        html_content="""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body { margin: 0; background: #0B0F19; display: flex; justify-content: center; align-items: center; height: 100vh; overflow: hidden; font-family: sans-serif; }
  #canvas { width: 1280px; height: 720px; }
</style>
</head>
<body>
<canvas id="canvas" width="1280" height="720"></canvas>
<script>
  const ctx = document.getElementById('canvas').getContext('2d');
  ctx.fillStyle = '#00F0FF';
  ctx.font = '36px sans-serif';
  ctx.fillText('Quantum State Vector', 100, 100);
</script>
</body>
</html>""",
        duration_seconds=10,
        notes="Introductory visual hook illustrating classical switch vs Bloch sphere.",
    )


@pytest.fixture
def sample_storyboard(sample_animation_style, sample_scene_animation):
    """Sample AnimationStoryboard for testing."""
    scene_2 = SceneAnimation(
        scene_number=2,
        title="Superposition & Entanglement",
        html_content="""<!DOCTYPE html><html><body><canvas id="c" width="1280" height="720"></canvas></body></html>""",
        duration_seconds=10,
    )
    scene_3 = SceneAnimation(
        scene_number=3,
        title="The Quantum Horizon",
        html_content="""<!DOCTYPE html><html><body><canvas id="c" width="1280" height="720"></canvas></body></html>""",
        duration_seconds=10,
    )
    return AnimationStoryboard(
        topic="How Quantum Computers Work",
        style=sample_animation_style,
        scenes=[sample_scene_animation, scene_2, scene_3],
    )
