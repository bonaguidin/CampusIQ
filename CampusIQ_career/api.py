"""FastAPI bridge exposing the career/academic orchestrator to the React dashboard.

This is the first HTTP entrypoint for the project — no web framework existed
before this file (pyproject.toml had no FastAPI/Flask/uvicorn), so FastAPI was
added as a new dependency. Covers all four feature runners (GAP, FIT, SHIFT,
PROFESSOR_COMMENTS) — each route is a thin wrapper around run_feature().

Student identity here is the dashboard "slug" (e.g. "jordanReyes"), matching
frontend/src/data/dataAdapter.ts's `/data/student_${slug}.json` convention —
not the numeric `student.id` inside the JSON, which has no filesystem mapping.
"""

import json
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from CampusIQ_career.ai.errors import AIConfigError
from CampusIQ_career.ai.openrouter_client import OpenRouterClient
from CampusIQ_career.features.orchestrator import run_feature

load_dotenv()

STUDENTS_DIR = Path(__file__).resolve().parents[1] / "data" / "students"

app = FastAPI(title="Campus IQ AI Bridge")

# Dev-only: Vite runs on a different origin than uvicorn. Tighten this before
# any real deployment — "*" is fine for a local demo, not for production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def load_student_profile(student_slug: str) -> dict:
    path = STUDENTS_DIR / f"student_{student_slug}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Unknown student '{student_slug}'.")
    return json.loads(path.read_text(encoding="utf-8"))


def build_client() -> OpenRouterClient:
    try:
        # DeepSeek R1's reasoning traces routinely run 100-200s+ (confirmed via
        # real validation calls) — the library default of 30s is too short for
        # this bridge specifically. Scoped here, not in openrouter_client.py,
        # since other callers may have different latency tolerances.
        return OpenRouterClient(timeout=300.0)
    except AIConfigError as exc:
        # Surface as a FeatureResult-shaped failure so the frontend's single
        # "failed" branch handles both "AI call failed" and "server misconfigured"
        # without needing a second error shape.
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/students/{student_slug}/analyze/gap")
def analyze_gap(student_slug: str) -> dict:
    profile = load_student_profile(student_slug)
    client = build_client()
    return run_feature("GAP", profile, client)


@app.post("/api/students/{student_slug}/analyze/fit")
def analyze_fit(student_slug: str) -> dict:
    profile = load_student_profile(student_slug)
    client = build_client()
    return run_feature("FIT", profile, client)


@app.post("/api/students/{student_slug}/analyze/shift")
def analyze_shift(student_slug: str) -> dict:
    profile = load_student_profile(student_slug)
    client = build_client()
    return run_feature("SHIFT", profile, client)


@app.post("/api/students/{student_slug}/analyze/professor-comments")
def analyze_professor_comments(student_slug: str) -> dict:
    profile = load_student_profile(student_slug)
    client = build_client()
    return run_feature("PROFESSOR_COMMENTS", profile, client)
