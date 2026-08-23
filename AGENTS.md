# Curiosity On Demand - Agent Instructions

## Project Purpose (The WHY)
Curiosity On Demand is an automated, end-to-end video creation pipeline controlled via Telegram. It takes a user-submitted topic, runs an iterative multi-agent research and verification loop using Gemini and Google Search, seeks human approval on the script via Telegram, and automatically renders narration, SVG-based animations, and stitched MP4 videos before publishing them to YouTube.

## Tech Stack & Structure (The WHAT)
- **Language & Runtime:** Python 3.12+, AsyncIO.
- **AI & TTS:** Google GenAI SDK (Gemini / with Google Search Grounding), Google Cloud Text-to-Speech.
- **Bot & Flow:** `python-telegram-bot` (v20+ async), custom state machine with SQLite/SQLAlchemy.
- **Media Engine:** CairoSVG, Pillow, FFmpeg (`ffmpeg-python` or `moviepy`).
- **Publishing:** YouTube Data API v3 (`google-api-python-client`).
- **Tooling:** `uv` for fast dependency management, Docker, `ruff`, `ty`.

**Key Components:**
- `main.py`: Application entrypoint running the bot and background task workers.
- `agents/`: Autonomous agent nodes (`researcher.py`, `verifier.py`, `summarizer.py`, `scriptwriter.py`).
- `core/`: FSM transitions (`state_machine.py`), Pydantic schemas, and DB models (`models.py`).
- `media/`: Asset generators (`audio_tts.py`, `svg_animator.py`, `video_assembler.py`).
- `services/`: External integrations (`telegram_bot.py`, `youtube_publisher.py`).

## Development Workflow (The HOW)
This project uses `uv` for environment management and `make` for automation.

**Environment Setup:**
Always activate the virtual environment before testing or running:
`source .venv/bin/activate`

**Core Commands:**
- `make setup`: Install dependencies using `uv sync`.
- `make run`: Start the Telegram bot and media worker.
- `make test`: Run `pytest` unit and integration tests. Run this after finishing any code edits.
- `make lint`: Format and lint the codebase (`ruff format`, `ruff check`, `ty`). Run this after finishing any code edits.

## Agent Guidelines & Guardrails
- **Non-Blocking Operations:** Media generation (rendering SVG frames, assembling FFmpeg video) and LLM queries are CPU/network heavy. Always dispatch these to background worker threads/tasks to prevent blocking the Telegram bot's async event loop.
- **Strict Structured Outputs:** All agent inter-communication (especially script generation) must strictly validate through Pydantic models in `core/models.py`.
- **Stateless Agent Nodes:** Keep agent modules pure and idempotent. State transitions (e.g., waiting for user approval) must be managed exclusively by `core/state_machine.py`.
- **SVG Animation Contract:** SVG templates must be cleanly parameterizable and compatible with headless rasterization via `cairosvg`.
- **Keep it Updated:** When modifying database schemas, pipeline stages, or dependencies, update `README.md` and `.env.example` immediately.