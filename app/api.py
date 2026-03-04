# app/api.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .llm_pipeline import IncidentLLMPipeline, LLMClient
from .timeline_builder import build_timeline_from_dict

app = FastAPI(
    title="Incident Comms Copilot",
    description="Generate customer-ready incident status updates from raw telemetry data.",
    version="0.1.0",
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    stage: str
    """Incident stage: initial | identified | monitoring | resolved"""

    pagerduty_incident: Dict[str, Any]
    prometheus_metrics: Optional[Dict[str, Any]] = None
    cloudwatch_logs: Optional[Dict[str, Any]] = None
    github_deployments: Optional[Dict[str, Any]] = None
    incident_context: Optional[str] = None
    """Raw Slack-style incident thread text."""

    model: str = "gpt-4.1"


class RiskFlagOut(BaseModel):
    text: str
    category: str
    reason: str


class GenerateResponse(BaseModel):
    external_update: str
    """Customer-facing status page message."""

    internal_summary: str
    """Internal engineering summary."""

    risk_score: str
    """low | medium | high"""

    flags: List[RiskFlagOut]
    recommendations: str
    facts: Dict[str, Any]
    """Structured incident facts extracted by Stage 1."""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest) -> GenerateResponse:
    """
    Run the 3-stage LLM pipeline on the provided incident telemetry and
    return a customer-ready status page update alongside an internal summary.
    """
    try:
        timeline = build_timeline_from_dict(req.model_dump())
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid incident payload: {exc}")

    pipeline = IncidentLLMPipeline(LLMClient(model_name=req.model))
    facts = pipeline.extract_facts(timeline)
    messages = pipeline.generate_messages(facts, req.stage)
    risk = pipeline.scan_risk(messages.external_update)

    return GenerateResponse(
        external_update=messages.external_update,
        internal_summary=messages.internal_summary,
        risk_score=risk.risk_score,
        flags=[
            RiskFlagOut(text=f.text, category=f.category, reason=f.reason)
            for f in risk.flags
        ],
        recommendations=risk.recommendations,
        facts=json.loads(json.dumps(facts.__dict__, default=str)),
    )
