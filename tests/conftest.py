"""Pytest fixtures and configuration for unit and integration testing."""

import pytest
import pytest_asyncio

from config.settings import Settings
from core.database import DatabaseManager
from core.models import ResearchReport, ResearchSection, Script, ScriptScene


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
                narration="Imagine a light switch that is not just ON or OFF, but pointing in every direction simultaneously. Welcome to quantum physics.",
            ),
            ScriptScene(
                scene_number=2,
                title="Superposition & Entanglement",
                summary="Explains the core physics mechanisms.",
                narration="In a classical computer, each bit is a binary 0 or 1. But a qubit can exist in a superposition of both.",
            ),
            ScriptScene(
                scene_number=3,
                title="The Quantum Horizon",
                summary="Wrap-up on real-world applications and future implications.",
                narration="While quantum computers won't replace your laptop, they will unlock simulations once thought impossible.",
            ),
        ],
    )
