# app/models.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional


IncidentSeverity = Literal["SEV-0", "SEV-1", "SEV-2", "SEV-3"]
IncidentStage = Literal["initial", "identified", "monitoring", "resolved"]

EventType = Literal[
    "alert",
    "metric_spike",
    "error_burst",
    "deployment",
    "slack_message",
    "note",
]


@dataclass
class IncidentEvent:
    """
    A single time-indexed event in the unified incident timeline.
    """
    timestamp: datetime
    type: EventType
    source: str
    summary: str
    structured_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class IncidentTimeline:
    """
    Unified incident view built from PagerDuty, metrics, logs, deployments, and Slack.
    """
    incident_id: str
    service: str
    severity: IncidentSeverity
    window_start: datetime
    window_end: Optional[datetime]
    events: List[IncidentEvent] = field(default_factory=list)


@dataclass
class IncidentFacts:
    """
    Structured facts extracted by the LLM (Model 1) from the unified timeline.
    This is the JSON object we described in the PRD.
    """
    incident_id: str
    service: str
    severity: str
    start_time: str
    end_time: Optional[str]
    impact_type: str
    customer_impact_summary: str
    scope: str
    mitigation_summary: str
    deployment_related: bool
    root_cause_confidence: str
    knowns: List[str]
    unknowns: List[str]
    notes_for_internal_use: str


@dataclass
class GeneratedMessages:
    """
    Text outputs from the generation model (Model 2).
    """
    internal_summary: str
    external_update: str


@dataclass
class RiskFlag:
    text: str
    category: str
    reason: str


@dataclass
class RiskScanResult:
    """
    Output of the brand risk & compliance model (Model 3).
    """
    risk_score: Literal["low", "medium", "high"]
    flags: List[RiskFlag]
    recommendations: str
