# Curiosity On Demand

Curiosity On Demand is a video research pipeline orchestrated via Telegram. It takes a user-submitted topic or inquiry, executes grounded web research using Gemini 3.7 Flash with Google Search Grounding to gather rich facts and concepts for video creation, stores the structured research in SQLite, and delivers the research report directly back to the user via Telegram.

---

## High-Level Architecture

```text
+-----------------------+
|     Telegram User     |
+-----------+-----------+
            |
            v (Submit Topic + Optional Duration)
+-----------+-----------+
|  Telegram Bot Service |
+-----------+-----------+
            |
            v (Async Dispatch)
+-----------+-----------+ <------------------------+
|    ResearcherAgent    |                         |
|   (Gemini 3.7 Flash   |                         |
|   + Google Search)    |                         |
+-----------+-----------+                         |
            |                                     |
            v (Raw Research Notes)                | Feedback & Missing Areas
+-----------+-----------+                         | (If insufficient & < max rounds)
|    EvaluatorAgent     |                         |
| (Filter, Structure &  | ------------------------+
|   Assess Sufficiency) |
+-----------+-----------+
            |
            v (Structured ResearchReport)
+-----------+-----------+
|   SQLite & SQLAlchemy |
|    (ProjectRecord)    |
+-----------+-----------+
            |
            v (Formatted Markdown)
+-----------+-----------+
|     Telegram User     |
+-----------------------+
```

---

## Tech Stack

- **Language & Runtime:** Python 3.12+, AsyncIO
- **AI & LLM Grounding:** Google GenAI SDK (`google-genai` 2.0+) using `gemini-3.7-flash` with native Google Search tool
- **Data Validation & Settings:** `pydantic` v2, `pydantic-settings`
- **Persistence & State:** SQLAlchemy 2.0 async + SQLite (`aiosqlite`)
- **Bot Framework:** `python-telegram-bot` (v22+ async)
- **Development Tooling:** `uv`, `pytest`, `pytest-asyncio`, `ruff`, `ty`, `codespell`

---

## Getting Started

### 1. Prerequisites

- **Python 3.12+**
- **uv**: Fast Python package manager
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

---

### 2. Environment Configuration

Copy the example environment file and add your credentials:
```bash
cp .env.example .env
```

Edit `.env` and configure:
```dotenv
GEMINI_API_KEY=your_gemini_api_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
```

---

### 3. Setup & Running Locally

Install dependencies:
```bash
make setup
```

Run the Telegram bot service:
```bash
make run
```

Run the automated test suite:
```bash
make test
```

Run code formatting and linting:
```bash
make lint
```

---

## Testing Notebooks

Jupyter notebooks are available in `notebooks/`:
- **`notebooks/agent_testing.ipynb`**: Interactive testing of `ResearcherAgent` with Gemini and Google Search grounding.
- **`notebooks/database_explorer.ipynb`**: Inspect stored project sessions and structured research reports.

Launch Jupyter via Docker:
```bash
make docker-notebook
```
or locally:
```bash
uv run jupyter lab
```