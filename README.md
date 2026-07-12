# CareerOS — Campus IQ

AI-powered career and academic companion for Texas A&M students.
Dallas AI Group 6 | 2026 Summer Cohort.

---

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) — Python package manager
- Node.js 20+ for the React/Vite frontend
- An OpenRouter API key for the primary Campus IQ AI path

---

## Setup

```bash
# 1. Install backend dependencies
uv sync

# 2. Configure your API key
cp .env.example .env
# then edit .env and replace "your-key-here" with your actual key

# 3. Install frontend dependencies
cd frontend
npm install
cd ..
```

---

## Running the app

The app is two processes — a Python backend and a React frontend — run in
separate terminals. Both need to be running for the dashboard's live
analysis calls (FIT/GAP/PROFESSOR_COMMENTS) to work.

**Terminal 1 — backend** (FastAPI bridge, port 8000):

```bash
uv run uvicorn CampusIQ_career.api:app --reload --port 8000
```

**Terminal 2 — frontend** (Vite dev server):

```bash
cd frontend
npm run dev
```

Vite prints a local URL (typically `http://localhost:5173`). Open it in a
browser — you'll land on the login page with a student dropdown
(mock/profile-select auth, no real credentials). Pick a student to enter
the dashboard. The Vite dev server proxies `/api/*` requests to
`localhost:8000` (configured in `frontend/vite.config.ts`), which is why
the backend has to be running too.

### Node version

The frontend requires **Node.js 20+** (pinned in `frontend/.nvmrc` and
`frontend/package.json`'s `engines` field). If you use
[nvm](https://github.com/nvm-sh/nvm), run `nvm use` from the `frontend/`
directory to switch automatically, or `nvm use 20` from anywhere.

Running `npm run dev` on an older Node version (e.g. 16 or 18) fails with
a cryptic error rather than a clear version check:

```
TypeError: crypto$2.getRandomValues is not a function
```

If you see this, it means your active Node is too old — run `node --version`
to check, then switch to Node 20+ and retry.

---

## Validating data

```bash
uv run python data/validate_catalog.py
uv run python data/students/validate_students.py
```

## Unified student profile

All academic and career features should build on the same JSON record in
`data/students/`. The schema contract lives in
`data/reference/unified_student_schema.md`.

The student validator checks the shared foundation fields, including academic
record counts, career fields, and profile completeness gates used by the
dashboard and future prompt/UI code.

---

## Other commands

| Command                                      | What it does                          |
|----------------------------------------------|---------------------------------------|
| `uv run python data/scrape_catalog.py`       | Re-scrape the TAMU course catalog     |
| `uv run python data/build_catalog.py`        | Rebuild catalog JSON from scrape output |

## AI Architecture

Campus IQ uses OpenRouter as the primary app AI gateway.

### Role-Based Model Routing

Model routing is centralized in `CampusIQ_career/ai/model_config.py` and can be
overridden with `CAMPUSIQ_MODEL_*` environment variables.

| Role | Purpose | Default model family |
|---------|---------|---------|
| orchestrator | Workflow orchestration | Deepseek R1 |
| career | FIT / GAP / SHIFT career analysis | Qwen3 235B A22B Thinking 2507 OR DeepSeek R1 |
| academic | Academic analysis features | Qwen3 235B A22B Thinking 2507 |
| parsing | JSON normalization and cleanup | Qwen3 32B |
| chat | Student chat responses | TODO |
| report | Report synthesis | Gemini 2.5 Flash Lite |

### Environment Variables

Required for the primary app AI path:

```bash
OPENROUTER_API_KEY=your-openrouter-key-here
```

Optional role overrides:

```bash
CAMPUSIQ_MODEL_ORCHESTRATOR=
CAMPUSIQ_MODEL_CAREER=
CAMPUSIQ_MODEL_ACADEMIC=
CAMPUSIQ_MODEL_PARSING=
CAMPUSIQ_MODEL_CHAT=
CAMPUSIQ_MODEL_REPORT=
```

Supabase is documented in the workflow architecture, but no Supabase client,
schema, or runtime path is implemented in the current code.
