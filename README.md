<p align="center">
  <img src="assets/project_header.jpg" alt="Curiosity On Demand Banner" width="100%">
</p>

# Curiosity On Demand

Curiosity On Demand is an automated educational video research, scripting, narration synthesis, and SVG/Canvas animation pipeline orchestrated via Telegram. It takes a user-submitted topic, performs grounded web research using Gemini with Google Search Grounding, enables interactive human-in-the-loop review of research findings, synthesizes scene-by-scene narration scripts, plans voice talent direction with inline vocal audio tags, synthesizes natural-language speech via Gemini TTS (`gemini-3.8-flash-tts`) with sample voice review, designs visual styles with sample frame review, generates SVG + HTML5 Canvas animations for all scenes, and renders and concatenates them into a finished master MP4 video with synchronized voiceover.

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
                                            [ State: AWAITING_PUBLISH_APPROVAL ] --------------------------------------------------------------+
                                                     | (Sends video preview, cost badge & resource report to Telegram)
                                                     +---> Skip / Don't Publish? ---> [ State: COMPLETED ]
                                                     |
                                                     +---> Approved?
                                                              |
                                                              v (Async Dispatch: State PUBLISHING)
                                                     +--------------------+
                                                     |  YouTubePublisher  | (Uploads master MP4/Shorts to YouTube via Data API v3)
                                                     +--------------------+
                                                              |
                                                              v
                                                     [ State: COMPLETED ]
                                                     (Sends live YouTube URL to user via Telegram)
```

---

## Tech Stack

- **Language & Runtime:** Python 3.12+, AsyncIO
- **AI & LLM Grounding:** Google GenAI SDK (`google-genai` 2.0+) using `gemini-3.7-flash` / `gemini-3.8-flash` with native Google Search tool and structured JSON schemas
- **Voiceover Speech Generation:** Gemini TTS (`gemini-3.8-flash-tts`) with natural-language directorial prompts and inline angle-bracket vocal/pause tags (`<short pause>`, `<long pause>`, `<gasp>`, `<sigh>`)
- **Animation & Rendering:** Playwright (Headless Chromium for deterministic SVG + HTML5 Canvas frame-stepping) and `imageio-ffmpeg` for single-pass MP4 video encoding and audio multiplexing
- **YouTube Publishing & Captions:** Google YouTube Data API v3 (`google-api-python-client`, `google-auth-oauthlib`) with automatic chapter timestamps, synchronized `.srt` subtitle generation and upload, hashtags, and Shorts format support
- **Cost & Token Tracking:** Granular per-component usage logging (input/output tokens, search grounding queries, TTS audio duration, and estimated USD cost) with automatic Telegram breakdown reports
- **Data Validation & Settings:** `pydantic` v2, `pydantic-settings`
- **Persistence & State:** SQLAlchemy 2.0 async + SQLite (`aiosqlite`)
- **Bot Framework:** `python-telegram-bot` (v22+ async)
- **Development Tooling:** `uv`, `pytest`, `pytest-asyncio`, `ruff`, `ty`, `codespell`, GitHub Actions CI


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
# Optional: Set to true if using a Vertex AI API key (Express Mode)
GEMINI_USE_VERTEXAI=false
GOOGLE_CLOUD_PROJECT=
GOOGLE_CLOUD_LOCATION=global
TELEGRAM_BOT_TOKEN=your_telegram_bot_token

# Optional: Concurrency tuning (adjust to your machine/quota)
RENDER_CONCURRENCY=3
TTS_CONCURRENCY=3
ANIMATION_CONCURRENCY=3
FFMPEG_CONCURRENCY=4

# Video Format & Dimensions (Videos <= 2 min are automatically generated in vertical 9:16 format)
VIDEO_WIDTH=1920
VIDEO_HEIGHT=1080
VERTICAL_VIDEO_WIDTH=1080
VERTICAL_VIDEO_HEIGHT=1920
VERTICAL_VIDEO_THRESHOLD_SECONDS=120
TELEGRAM_PREVIEW_MAX_DURATION_SECONDS=60.0
TELEGRAM_UPLOAD_TIMEOUT_SECONDS=300.0
TELEGRAM_REQUEST_TIMEOUT_SECONDS=60.0

# YouTube Data API Publishing (Optional)
# Configure direct tokens (recommended for servers/Docker) or token file:
YOUTUBE_CLIENT_ID=your_client_id
YOUTUBE_CLIENT_SECRET=your_client_secret
YOUTUBE_REFRESH_TOKEN=your_refresh_token
YOUTUBE_DEFAULT_PRIVACY_STATUS=public
```

#### YouTube Publishing Setup
Curiosity On Demand can automatically upload videos as standard videos or YouTube Shorts upon your approval in Telegram.

For complete step-by-step instructions on creating Google Cloud OAuth credentials and generating tokens, see the [YouTube Setup Guide](docs/youtube_setup.md).

**Quick Setup:**
1. Download OAuth 2.0 desktop client credentials (`client_secrets.json`) from [Google Cloud Console](https://console.cloud.google.com/).
2. Run the interactive authorization helper:
   ```bash
   python -m services.youtube_publisher --client-secrets client_secrets.json
   ```
3. Follow the browser prompt to authorize your channel. The tool saves `storage/youtube_token.json` and prints the `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, and `YOUTUBE_REFRESH_TOKEN` to paste directly into `.env`.

---

### 3. Setup & Running Locally

Install dependencies and Playwright Chromium:
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

### 4. Running with Docker

Curiosity On Demand includes complete Docker Compose support for headless containerized deployment:

1. **Build the container image:**
   ```bash
   make docker-build
   ```

2. **Start the bot service:**
   ```bash
   # Run in the background (daemon mode)
   docker compose up -d

   # Or run in the foreground
   make docker-start
   ```

3. **View live logs:**
   ```bash
   docker compose logs -f app
   ```

4. **Stop the service:**
   ```bash
   make docker-stop
   ```

> [!NOTE]
> The `./storage` directory is mounted into the container as `/app/storage`. Your SQLite database (`storage/curiosity.db`), rendered video outputs, and YouTube authorization tokens (`storage/youtube_token.json`) persist across container rebuilds and restarts.

---

## Telegram Bot Guide & Workflow

### 1. Bot Commands
The bot registers native command auto-completion with Telegram:
- `/start` — Welcome message and comprehensive pipeline overview.
- `/help` — Complete guide explaining duration syntax, aspect ratios, and review stages.
- `/status` — Real-time active project tracking (stage, topic, project ID, last update).
- `/cancel` — Cancel the active project workflow.

### 2. Starting a Project & Duration Syntax
Send any curiosity or educational topic directly to the bot in Telegram:
- **Default Duration:** If no duration is specified, the default duration from settings (5 minutes) is used.
- **Specifying Duration:** Include duration tags in your topic, such as `How do black holes evaporate? (2 min short)` or `Quantum computing explained (5 min)`.
- **Automatic Aspect Ratio (Shorts vs Widescreen):**
  - **Vertical 9:16 (YouTube Shorts):** Videos with duration &le; 2 minutes (120 seconds) are automatically styled, coded, and rendered in vertical 9:16 Full HD resolution (`1080x1920`).
  - **Horizontal 16:9 (Standard Video):** Videos longer than 2 minutes are rendered in horizontal 16:9 Full HD widescreen (`1920x1080`).

### 3. Human-in-the-Loop Review Stages
Curiosity On Demand gives you full creative control at every milestone. Tap **Approve** to advance to the next stage, or reply with feedback to refine:
1. **Research Findings Review:** Inspect grounded facts, key concepts, sources, and narrative angles gathered via Google Search.
2. **Narration Script Review:** Review the scene breakdown, spoken narration, visual directions, and estimated timings.
3. **Voice Direction & Preview:** Listen to an inline audio voice sample synthesized with Gemini TTS. Request tone or voice talent adjustments if desired.
4. **Visual Style Frame Preview:** Review a high-resolution rendered frame snapshot and color palette of Scene 1. Request animation style adjustments before batch rendering.
5. **Video Preview & YouTube Publishing:** Review the final rendered MP4 video preview alongside a granular token, query, duration, and USD cost breakdown. Tap **Publish to YouTube** to upload directly as a video or Short.

### 4. Startup Diagnostics & Access Control
- **Pre-Flight Validation:** Upon launch, the system validates that mandatory credentials (`GEMINI_API_KEY` and `TELEGRAM_BOT_TOKEN`) are configured.
- **Diagnostic Logging:** Startup logs report detected model configurations, FFmpeg binary paths, YouTube publishing readiness, and access control restrictions.
- **Access Control:** Restrict bot usage by adding authorized user IDs or usernames to `TELEGRAM_ALLOWED_USERS` in `.env` (leave blank to allow all users).

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

---

## License

This project is licensed under the terms of the [MIT License](LICENSE).