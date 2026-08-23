"""Pytest fixtures and configuration for unit and integration testing."""

import pytest
import pytest_asyncio

from config.settings import Settings
from core.database import DatabaseManager
from core.models import (
    AnimationType,
    AspectRatio,
    PitchSummary,
    ResearchFinding,
    ResearchReport,
    ResearchSource,
    Scene,
    SceneVisualBlueprint,
    VideoScript,
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
    media_dir = storage_dir / "media"
    db_path = storage_dir / "test.db"

    return Settings(
        GEMINI_API_KEY="test_api_key",
        GEMINI_MODEL="gemini-3.7-flash",
        RESEARCH_MODEL="gemini-3.7-flash",
        STORAGE_DIR=storage_dir,
        MEDIA_OUTPUT_DIR=media_dir,
        SQLITE_DB_PATH=db_path,
        MAX_RESEARCH_ITERATIONS=2,
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
        findings=[
            ResearchFinding(
                topic="Qubits & Superposition",
                claim="Quantum computers use qubits that can exist in multiple states simultaneously.",
                detail="Unlike classical bits (0 or 1), superposition allows exponential computational scale.",
                source_url="https://example.com/quantum-basics",
                confidence_score=0.98,
            ),
            ResearchFinding(
                topic="Entanglement",
                claim="Quantum entanglement links qubits regardless of physical distance.",
                detail="Einstein famously referred to this phenomenon as 'spooky action at a distance'.",
                source_url="https://example.com/entanglement",
                confidence_score=0.95,
            ),
        ],
        sources=[
            ResearchSource(
                title="Quantum Physics Overview",
                url="https://example.com/quantum-basics",
            ),
            ResearchSource(
                title="Entanglement Deep Dive",
                url="https://example.com/entanglement",
            ),
        ],
        summary="Quantum computing harnesses superposition and entanglement to solve problems intractable for classical computers.",
        iteration=1,
    )


@pytest.fixture
def sample_pitch_summary():
    """Sample PitchSummary for testing."""
    return PitchSummary(
        topic="How Quantum Computers Work",
        title_options=[
            "Why Quantum Computing Changes Everything",
            "The Mind-Bending Physics of Qubits",
            "Are Quantum Computers Truly Limitless?",
        ],
        hook="What if a single computer could calculate more possibilities in seconds than there are atoms in the universe?",
        target_audience="Curious science and tech enthusiasts",
        key_takeaways=[
            "Difference between classical bits and qubits",
            "Power of superposition and entanglement",
            "Real-world impact on cryptography and medicine",
        ],
        core_narrative="Start with classical vs quantum contrast, introduce superposition visually, explain entanglement, conclude with real-world applications.",
        estimated_scenes_count=3,
        estimated_duration_seconds=45.0,
    )


@pytest.fixture
def sample_video_script():
    """Sample VideoScript for testing."""
    scenes = [
        Scene(
            scene_id=1,
            narration="Every device you use right now processes information using binary bits: ones and zeros.",
            visual_description="A glowing stream of binary zeros and ones pulsing through circuit boards.",
            svg_source='<svg viewBox="0 0 1920 1080" xmlns="http://www.w3.org/2000/svg"><rect width="1920" height="1080" fill="#0f172a"/><text x="960" y="540" fill="#38bdf8" font-size="64" text-anchor="middle">0 1 0 1</text></svg>',
            duration_seconds=5.0,
            visual_blueprint=SceneVisualBlueprint(
                animation_type=AnimationType.FADE_SCALE,
                primary_text="Binary vs Qubits",
            ),
            is_suitable_for_short=True,
        ),
        Scene(
            scene_id=2,
            narration="Quantum computers, however, use qubits that can exist as both a zero and a one simultaneously.",
            visual_description="A 3D Bloch sphere representation showing quantum superposition in vivid cyan and purple.",
            svg_source='<svg viewBox="0 0 1920 1080" xmlns="http://www.w3.org/2000/svg"><rect width="1920" height="1080" fill="#0f172a"/><circle cx="960" cy="540" r="200" stroke="#818cf8" stroke-width="4" fill="none"/></svg>',
            duration_seconds=6.0,
            visual_blueprint=SceneVisualBlueprint(
                animation_type=AnimationType.DATA_COUNTER,
                primary_text="Superposition",
            ),
            is_suitable_for_short=False,
        ),
    ]

    return VideoScript(
        title="Why Quantum Computing Changes Everything",
        description="Explore the mind-bending reality of quantum computing.",
        tags=["quantum", "computing", "science", "physics"],
        scenes=scenes,
        total_duration_seconds=11.0,
        aspect_ratio=AspectRatio.LANDSCAPE_16_9,
        highlighted_short_scene_ids=[1],
    )
