# app/api.py
"""
Incident Communications Copilot — REST API

Endpoints:
    POST /analyze  – Accept raw telemetry payload, run pipeline, return results
    GET  /status   – Return the latest processed incident status

Run with:  uvicorn app.api:app --reload
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .timeline_builder import build_timeline_from_bundle, build_timeline_from_payload
from .llm_pipeline import LLMClient, IncidentLLMPipeline

app = FastAPI(
    title="Incident Comms Copilot API",
    version="0.2.0",
    description="Transforms raw incident telemetry into customer-ready communications.",
)

# In-memory store for the latest processed incident
_latest_status: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    """
    Raw incident telemetry payload. All telemetry fields are optional —
    the pipeline gracefully handles missing sources.
    """
    pagerduty: Optional[Dict[str, Any]] = Field(
        None, description="PagerDuty incident record (dict with 'incident' key)"
    )
    prometheus_metrics: Optional[Dict[str, Any]] = Field(
        None, description="Prometheus metrics (dict with 'metrics' key)"
    )
    cloudwatch_logs: Optional[Dict[str, Any]] = Field(
        None, description="CloudWatch logs (dict with 'logs' key)"
    )
    github_deployments: Optional[Dict[str, Any]] = Field(
        None, description="GitHub deployments (dict with 'deployments' key)"
    )
    incident_context: Optional[str] = Field(
        None, description="Freeform incident context / Slack thread text"
    )
    stage: str = Field(
        "resolved",
        description="Incident stage: initial | identified | monitoring | resolved",
    )
    model: str = Field("gpt-4.1", description="OpenAI model name")


# ---------------------------------------------------------------------------
# Core analysis function (shared by API and Streamlit)
# ---------------------------------------------------------------------------

def analyze_incident(payload: Dict[str, Any], stage: str = "resolved", model: str = "gpt-4.1") -> Dict[str, Any]:
    """
    Run the full 3-stage pipeline on a telemetry payload dict.

    Args:
        payload: dict with optional keys: pagerduty, prometheus_metrics,
                 cloudwatch_logs, github_deployments, incident_context
        stage:   incident stage for message generation
        model:   OpenAI model name

    Returns:
        dict with extracted facts, generated messages, and risk flags
    """
    timeline = build_timeline_from_payload(payload)

    client = LLMClient(model_name=model)
    pipeline = IncidentLLMPipeline(client)

    facts = pipeline.extract_facts(timeline)
    messages = pipeline.generate_messages(facts, stage=stage)
    risk = pipeline.scan_risk(messages.external_update, facts=facts)

    return {
        "incident_id": facts.incident_id,
        "service": facts.service,
        "severity": facts.severity,
        "start_time": facts.start_time,
        "end_time": facts.end_time,
        "impact_type": facts.impact_type,
        "customer_impact_summary": facts.customer_impact_summary,
        "scope": facts.scope,
        "deployment_related": facts.deployment_related,
        "root_cause_confidence": facts.root_cause_confidence,
        "mitigation_summary": facts.mitigation_summary,
        "knowns": facts.knowns,
        "unknowns": facts.unknowns,
        "notes_for_internal_use": facts.notes_for_internal_use,
        "stage": stage,
        "external_update": messages.external_update,
        "internal_summary": messages.internal_summary,
        "risk_score": risk.risk_score,
        "risk_flags": [
            {"text": f.text, "category": f.category, "reason": f.reason}
            for f in risk.flags
        ],
        "recommendations": risk.recommendations,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/analyze")
def analyze(request: AnalyzeRequest):
    """
    Analyze raw incident telemetry and generate communications.

    Accepts a JSON body with optional telemetry sources (pagerduty,
    prometheus_metrics, cloudwatch_logs, github_deployments, incident_context).
    At least one source should be provided.

    Returns extracted facts, internal summary, customer-facing draft,
    and communications risk flags.
    """
    global _latest_status

    telemetry = request.model_dump(exclude={"stage", "model"}, exclude_none=True)

    if not telemetry:
        return JSONResponse(
            status_code=400,
            content={"detail": "At least one telemetry source must be provided."},
        )

    result = analyze_incident(telemetry, stage=request.stage, model=request.model)
    _latest_status = result
    return result


@app.get("/status")
def get_status():
    """Return the latest processed incident status."""
    if _latest_status is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "No incident has been processed yet. POST to /analyze first."},
        )
    return _latest_status
