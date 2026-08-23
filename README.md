# Curiosity On Demand

Curiosity On Demand is an automated, end-to-end video creation pipeline orchestrated via Telegram. It takes a user-submitted topic or inquiry, runs an iterative multi-agent research and verification loop using Gemini 3.7 Flash with Google Search Grounding, seeks human review on the script pitch via Telegram inline buttons, generates scene-by-scene structured scripts with programmatic SVG animation blueprints, renders narration and rasterized SVG keyframes into synchronized MP4 clips, stitches them with FFmpeg, and publishes to YouTube.

---

## High-Level Architecture

```text
                                  +-----------------------+
                                  |     Telegram User     |
                                  +-----------+-----------+
                                              |
                                              v (Submit Topic)
                                  +-----------+-----------+
                                  |  Telegram Bot Handler |
                                  +-----------+-----------+
                                              |
                                              v
+---------------------------------------------+----------------------------------------------+
|                         Multi-Agent Research & Script Loop                                  |
|                                                                                            |
|   +-------------------+          +------------------+          +-----------------------+   |
|   |  ResearcherAgent  | -------> |  VerifierAgent   | -------> |    SummarizerAgent    |   |
|   | (Gemini 3.7 Flash | <------- | (Fact Inspection | (Pass)   |  (Pitch Concept with  |   |
|   |  + Search Tool)   | (Retry)  | & Quality Gate)  |          |   Review Narrative)   |   |
|   +-------------------+          +------------------+          +-----------+-----------+   |
|                                                                            |               |
+----------------------------------------------------------------------------|---------------+
                                                                             |
                                                                             v
                                                              +--------------+--------------+
                                                              |  Human-in-the-Loop Review   |
                                                              |  [✅ Approve] [✏️ Revise]   |
                                                              +--------------+--------------+
                                                                             |
                                                                             v (Approved)
                                                              +--------------+--------------+
                                                              |      ScriptWriterAgent      |
                                                              | (Scenes + SVG Blueprints)   |
                                                              +--------------+--------------+
                                                                             |
                                                                             v
+----------------------------------------------------------------------------+---------------+
|                                Media Engine & Publishing                                   |
|                                                                                            |
|   +-------------------+          +------------------+          +-----------------------+   |
|   |  Voice TTS Engine |          |   SVG Animator   |          |    Video Assembler    |   |
|   |    (Gemini TTS    |          |    (CairoSVG +   | -------> |     (FFmpeg Multi-    |   |
|   |  google-genai SDK)|          |  Pillow Frames)  |          |     Track Stitcher)   |   |
|   +---------+---------+          +--------+---------+          +-----------+-----------+   |
|             |                             |                                |               |
|             +-----------------------------+                                v               |
|                                                                +-----------+-----------+   |
|                                                                |   YouTube Publisher   |   |
|                                                                | (YouTube Data API v3) |   |
|                                                                +-----------------------+   |
+--------------------------------------------------------------------------------------------+
```

---

## Tech Stack

- **Language & Runtime:** Python 3.12+, AsyncIO
- **AI & LLM Grounding:** Google GenAI SDK (`google-genai` 2.0+) using `gemini-3.7-flash` with native Google Search tool
- **Data Validation & Settings:** `pydantic` v2, `pydantic-settings`
- **Persistence & State:** SQLAlchemy 2.0 async + SQLite (`aiosqlite`)
- **Bot Framework:** `python-telegram-bot` (v22+ async)
- **Media Engine:** CairoSVG, Pillow, FFmpeg (`ffmpeg-python`)
- **Publishing:** YouTube Data API v3 (`google-api-python-client`, `google-auth-oauthlib`)
- **Development Tooling:** `uv`, `pytest`, `pytest-asyncio`, `ruff`, `ty`, `codespell`

---

## Getting Started

### 1. Prerequisites
- **Python 3.12+**
- **uv**: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **FFmpeg**: `brew install ffmpeg` (macOS) or `sudo apt install ffmpeg` (Linux)
- **Cairo**: `brew install cairo pango gdk-pixbuf` (macOS) or `sudo apt install libcairo2 libpango-1.0-0` (Linux)

### 2. Installation
Clone the repository and install dependencies with `uv`:
```bash
uv sync
```

### 3. Environment Configuration
Copy the example environment file and configure your API keys:
```bash
cp .env.example .env
```

Key environment variables:
- `GEMINI_API_KEY`: API key from [Google AI Studio](https://aistudio.google.com/)
- `GEMINI_MODEL`: `gemini-3.7-flash`
- `RESEARCH_MODEL`: `gemini-3.7-flash`
- `TELEGRAM_BOT_TOKEN`: Telegram bot token from [@BotFather](https://t.me/BotFather)
- `YOUTUBE_CLIENT_SECRETS_FILE`: Path to OAuth2 credentials JSON from Google Cloud Console

---

## Development Commands

```bash
# Run test suite
make test

# Run code formatters and linters (codespell, ruff, ty)
make lint
```

---

## Directory Structure

```text
curiosity-on-demand/
├── .env.example
├── README.md
├── pyproject.toml
├── Makefile
├── config/
│   ├── __init__.py
│   └── settings.py              # Pydantic BaseSettings & path configuration
├── core/
│   ├── __init__.py
│   ├── database.py              # Async SQLite/SQLAlchemy ORM models and CRUD
│   ├── models.py                # Pydantic schemas (Research, Pitch, Scene, Script)
│   └── state_machine.py         # Pipeline finite state machine
├── agents/
│   ├── __init__.py
│   ├── base.py                  # Base agent wrapping google-genai SDK
│   ├── researcher.py            # Grounded research with Google Search
│   ├── verifier.py              # Quality evaluation and gap detection
│   ├── summarizer.py            # Video concept pitch & user feedback revision
│   └── scriptwriter.py          # Structured scenes with SVG animation code
├── media/                       # Media engine (Phase 2)
├── services/                    # Bot & YouTube integrations (Phase 2)
├── templates/                   # SVG templates (Phase 2)
└── tests/
    ├── conftest.py              # Pytest fixtures and mocks
    ├── test_models.py           # Schema and serialization unit tests
    ├── test_database_and_state.py # DB persistence & state machine tests
    └── test_agents.py           # Agent unit tests with mock GenAI client
```