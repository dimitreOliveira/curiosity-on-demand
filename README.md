# Curiosity On Demand

Curiosity On Demand is an automated educational video research, scripting, narration synthesis, and SVG/Canvas animation pipeline orchestrated via Telegram. It takes a user-submitted topic, performs grounded web research using Gemini with Google Search Grounding, enables interactive human-in-the-loop review of research findings, synthesizes scene-by-scene narration scripts, plans voice talent direction with emotional audio tags, synthesizes natural-language speech via Gemini TTS (`gemini-3.1-flash-tts-preview`) with sample voice review, designs visual styles with sample frame review, generates SVG + HTML5 Canvas animations for all scenes, and renders and concatenates them into a finished master MP4 video with synchronized voiceover.

---

## High-Level Architecture

```text
+-----------------------------------------------------------------------------------------------------------------------+
|                                                     Telegram User                                                     |
+-----------------------------------------------------------------------------------------------------------------------+
       | (1. Submit Topic)                     ^ (3. Review Summary)  ^ (5. Review Script)  ^ (7. Voice Sample)  ^ (9. Style Frame)  ^ (10. Final Video)
       v                                       |                      |                     |                     |                   |
+--------------------+                         |                      |                     |                     |                   |
|  Telegram Bot      |                         |                      |                     |                     |                   |
|  Service           |                         |                      |                     |                     |                   |
+--------------------+                         |                      |                     |                     |                   |
       |                                       |                      |                     |                     |                   |
       v (Async Dispatch)                      |                      |                     |                     |                   |
+--------------------+                         |                      |                     |                     |                   |
|  ResearcherAgent   |<-----+                  |                      |                     |                     |                   |
|  (Search Grounded) |      |                  |                      |                     |                     |                   |
+--------------------+      | (Internal loop)  |                      |                     |                     |                   |
       |                    |                  |                      |                     |                     |                   |
       v                    |                  |                      |                     |                     |                   |
+--------------------+      |                  |                      |                     |                     |                   |
|   EvaluatorAgent   |------+                  |                      |                     |                     |                   |
| (Filter/Structure) |                         |                      |                     |                     |                   |
+--------------------+                         |                      |                     |                     |                   |
       | (Sufficient)                          |                      |                     |                     |                   |
       v                                       |                      |                     |                     |                   |
[ State: AWAITING_RESEARCH_APPROVAL ] ---------+                      |                     |                     |                   |
       |                                                              |                     |                     |                   |
       +---> User Feedback? ---> Re-run Researcher & Evaluator        |                     |                     |                   |
       |                                                              |                     |                     |                   |
       +---> Approved?                                                |                     |                     |                   |
                |                                                     |                     |                     |                   |
                v (Async Dispatch)                                    |                     |                     |                   |
       +--------------------+                                         |                     |                     |                   |
       | ScriptWriterAgent  |<----------------------------------------+                     |                     |                   |
       | (Scene Breakdown)  | (Re-run on User Feedback with prev script)                    |                     |                   |
       +--------------------+                                                               |                     |                   |
                |                                                                           |                     |                   |
                v (Script Generated)                                                        |                     |                   |
       [ State: AWAITING_SCRIPT_APPROVAL ]                                                  |                     |                   |
                |                                                                           |                     |                   |
                +---> User Feedback? ---> Re-run ScriptWriter with feedback                 |                     |                   |
                |                                                                           |                     |                   |
                +---> Approved?                                                             |                     |                   |
                          |                                                                 |                     |                   |
                          v (Async Dispatch: State NARRATING)                               |                     |                   |
                 +------------------------+                                                 |                     |                   |
                 | NarrationPlannerAgent  | (Formulates Persona, Voice & Audio Tags)        |                     |                   |
                 | NarrationGeneratorAgent| (Synthesizes Scene 1 Voice Preview via TTS)     |                     |                   |
                 +------------------------+                                                 |                     |                   |
                          |                                                                 |                     |                   |
                          v                                                                 |                     |                   |
                 [ State: AWAITING_NARRATION_APPROVAL ] ------------------------------------+                     |                   |
                          |                                                                                       |                   |
                          +---> User Feedback? ---> Re-plan Voice & Re-synthesize Sample                          |                   |
                          |                                                                                       |                   |
                          +---> Approved?                                                                         |                   |
                                   |                                                                              |                   |
                                   v (Async Dispatch: State STYLING)                                              |                   |
                          +------------------------+                                                              |                   |
                          | AnimationPlannerAgent  | (Formulates Visual Style & Palette)                           |                   |
                          |   SceneAnimatorAgent   | (Generates Unconstrained HTML5 Canvas Scene 1)                |                   |
                          |   AnimationRenderer    | (Renders Scene 1 PNG Snapshot)                                |                   |
                          +------------------------+                                                              |                   |
                                   |                                                                              |                   |
                                   v                                                                              |                   |
                          [ State: AWAITING_STYLE_APPROVAL ] -----------------------------------------------------+                   |
                                   |                                                                                                  |
                                   +---> User Feedback? ---> Re-plan Style & Re-render Scene 1                                        |
                                   |                                                                                                  |
                                   +---> Approved?                                                                                    |
                                            |                                                                                         |
                                            v (Async Dispatch: State ANIMATING)                                                       |
                                   +-------------------------+                                                                        |
                                   |   SceneAnimatorAgent    | (Generates all scene HTML animations in parallel)                      |
                                   | NarrationGeneratorAgent | (Synthesizes all scene audios in parallel via Gemini TTS)              |
                                   |    AnimationRenderer    | (Renders Chromium video clips & muxes master MP4 with audio)           |
                                   +-------------------------+                                                                        |
                                            |                                                                                         |
                                            v                                                                                         |
                                   [ State: COMPLETED ] ------------------------------------------------------------------------------+
                                                          (Sends final master MP4 video, cost badge, & detailed resource breakdown to Telegram)
```

---

## Tech Stack

- **Language & Runtime:** Python 3.12+, AsyncIO
- **AI & LLM Grounding:** Google GenAI SDK (`google-genai` 2.0+) using `gemini-3.7-flash` with native Google Search tool and structured JSON schemas
- **Voiceover Speech Generation:** Gemini TTS (`gemini-3.1-flash-tts-preview`) with natural-language directorial prompts and inline emotional audio tags
- **Animation & Rendering:** Playwright (Headless Chromium for SVG + HTML5 Canvas execution) and `imageio-ffmpeg` for MP4 video assembly and audio multiplexing
- **Cost & Token Tracking:** Granular per-component usage logging (input/output tokens, search grounding queries, TTS audio duration, and estimated USD cost) with automatic Telegram breakdown reports
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

# Optional: Concurrency tuning (adjust to your machine/quota)
RENDER_CONCURRENCY=3
TTS_CONCURRENCY=3
ANIMATION_CONCURRENCY=3
FFMPEG_CONCURRENCY=4
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