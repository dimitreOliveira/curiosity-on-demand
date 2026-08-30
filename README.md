# Curiosity On Demand

Curiosity On Demand is an automated video research and narration scripting pipeline orchestrated via Telegram. It takes a user-submitted topic, performs grounded web research using Gemini with Google Search Grounding, enables interactive human-in-the-loop review of research findings, synthesizes scene-by-scene narration scripts via `ScriptWriterAgent`, and presents scenes for interactive user feedback and approval.

---

## High-Level Architecture

```text
+-----------------------------------------------------------------------------------+
|                                  Telegram User                                    |
+-----------------------------------------------------------------------------------+
       | (1. Submit Topic)                     ^ (3. Review Summary)  ^ (5. Review Scenes)
       v                                       |                      |
+--------------------+                         |                      |
|  Telegram Bot      |                         |                      |
|  Service           |                         |                      |
+--------------------+                         |                      |
       |                                       |                      |
       v (Async Dispatch)                      |                      |
+--------------------+                         |                      |
|  ResearcherAgent   |<-----+                  |                      |
|  (Search Grounded) |      |                  |                      |
+--------------------+      | (Internal loop)  |                      |
       |                    |                  |                      |
       v                    |                  |                      |
+--------------------+      |                  |                      |
|   EvaluatorAgent   |------+                  |                      |
| (Filter/Structure) |                         |                      |
+--------------------+                         |                      |
       | (Sufficient)                          |                      |
       v                                       |                      |
[ State: AWAITING_RESEARCH_APPROVAL ] ---------+                      |
       |                                                              |
       +---> User Feedback? ---> Re-run Researcher & Evaluator        |
       |                                                              |
       +---> Approved?                                                |
                |                                                     |
                v (Async Dispatch)                                    |
       +--------------------+                                         |
       | ScriptWriterAgent  |<----------------------------------------+
       | (Scene Breakdown)  | (Re-run on User Feedback with prev script)
       +--------------------+
                |
                v (Script Generated)
       [ State: AWAITING_SCRIPT_APPROVAL ]
                |
                +---> User Feedback? ---> Re-run ScriptWriter with feedback
                |
                +---> Approved? ---> [ State: COMPLETED ]
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