# Curiosity On Demand - Agent Instructions

## Project Purpose (The WHY)
Curiosity On Demand is an automated educational video research, scripting, narration synthesis, animation, and publishing pipeline controlled via Telegram. It takes a user-submitted topic, performs grounded web research using Gemini with Google Search Grounding, enables interactive human review and feedback, generates scene-by-scene narration scripts, synthesizes natural-language voiceovers via Gemini TTS, renders dynamic HTML5 Canvas animations, assembles master MP4 videos with synchronized audio, and publishes to YouTube.

## Tech Stack & Structure (The WHAT)
- **Language & Runtime:** Python 3.12+, AsyncIO.
- **AI, Grounding & Audio:** Google GenAI SDK (Gemini with Google Search Grounding, Structured Outputs, and Gemini TTS).
- **Animation & Rendering:** Playwright (Headless Chromium Canvas/SVG execution) and FFmpeg.
- **Publishing & Tracking:** YouTube Data API v3, granular token & USD cost tracking.
- **Bot & Flow:** `python-telegram-bot` (v22+ async), custom state machine with SQLite/SQLAlchemy.
- **Tooling:** `uv` for fast dependency management, Docker, `ruff`, `ty`, `codespell`.

**Key Components:**
- `main.py`: Application entrypoint running startup diagnostics and the bot.
- `agents/`: Autonomous agents (`base.py`, `researcher.py`, `evaluator.py`, `script_writer.py`, `narration_planner.py`, `narration_generator.py`, `animation_planner.py`, `scene_animator.py`).
- `core/`: FSM transitions (`state_machine.py`), Pydantic schemas (`models.py`), DB models (`database.py`), and cost tracking (`cost_tracker.py`).
- `services/`: Telegram bot (`telegram_bot.py`), video rendering (`renderer.py`), and YouTube publishing (`youtube_publisher.py`).
- `notebooks/`: Testing and diagnostic notebooks (`agent_testing.ipynb`, `database_explorer.ipynb`).

## Development Workflow (The HOW)
This project uses `uv` for environment management and `make` for automation.

**Environment Setup:**
Always activate the virtual environment before testing or running:
`source .venv/bin/activate`

**Core Commands:**
- `make setup`: Install dependencies using `uv sync`.
- `make run`: Start the Telegram bot service.
- `make test`: Run `pytest` unit and integration tests. Run this after finishing any code edits.
- `make lint`: Format and lint the codebase (`ruff format`, `ruff check`, `ty`). Run this after finishing any code edits.

## Agent Guidelines & Guardrails
- **Non-Blocking Operations:** LLM queries and web research are network heavy. Always dispatch these to background tasks to prevent blocking the Telegram bot's async event loop.
- **Strict Structured Outputs:** All agent research must strictly validate through Pydantic models in `core/models.py`.
- **Stateless Agent Nodes:** Keep agent modules pure and idempotent. State transitions must be managed exclusively by `core/state_machine.py`.
- **Keep it Updated:** When modifying database schemas, pipeline stages, or dependencies, update `README.md` and `.env.example` immediately.