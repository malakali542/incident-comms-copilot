# app/timeline_builder.py
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import IncidentTimeline, IncidentEvent, IncidentSeverity


def parse_iso(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp, normalizing trailing Z to +00:00."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def build_timeline_from_bundle(bundle_dir: Path) -> IncidentTimeline:
    """
    Build a unified IncidentTimeline from a bundle directory on disk.
    Reads each file into a dict, then delegates to build_timeline_from_payload.
    """
    payload: Dict[str, Any] = {}

    pd_path = bundle_dir / "pagerduty_incident.json"
    if pd_path.exists():
        with pd_path.open() as f:
            payload["pagerduty"] = json.load(f)

    metrics_path = bundle_dir / "prometheus_metrics.json"
    if metrics_path.exists():
        with metrics_path.open() as f:
            payload["prometheus_metrics"] = json.load(f)

    logs_path = bundle_dir / "cloudwatch_logs.json"
    if logs_path.exists():
        with logs_path.open() as f:
            payload["cloudwatch_logs"] = json.load(f)

    deployments_path = bundle_dir / "github_deployments.json"
    if deployments_path.exists():
        with deployments_path.open() as f:
            payload["github_deployments"] = json.load(f)

    context_path = bundle_dir / "incident_context.txt"
    if context_path.exists():
        payload["incident_context"] = context_path.read_text(encoding="utf-8")

    return build_timeline_from_payload(payload)


def build_timeline_from_payload(payload: Dict[str, Any]) -> IncidentTimeline:
    """
    Build a unified IncidentTimeline from a raw payload dict.

    All keys are optional — the builder gracefully handles missing sources.

    Expected keys:
        pagerduty          – dict with "incident" key (PagerDuty schema)
        prometheus_metrics – dict with "metrics" key
        cloudwatch_logs    – dict with "logs" key
        github_deployments – dict with "deployments" key
        incident_context   – plain text string (Slack thread)
    """
    pd_data = payload.get("pagerduty")
    metrics_data = payload.get("prometheus_metrics")
    logs_data = payload.get("cloudwatch_logs")
    deploys_data = payload.get("github_deployments")
    context_text = payload.get("incident_context")

    # Extract incident metadata — PagerDuty is authoritative but optional
    incident_id, service, severity, window_start, window_end = _extract_metadata(
        pd_data, metrics_data, logs_data,
    )

    timeline = IncidentTimeline(
        incident_id=incident_id,
        service=service,
        severity=severity,
        window_start=window_start,
        window_end=window_end,
    )

    if pd_data:
        _add_pagerduty_events(timeline, pd_data)
    if metrics_data:
        _add_metric_events(timeline, metrics_data)
    if logs_data:
        _add_log_events(timeline, logs_data)
    if deploys_data:
        _add_deployment_events(timeline, deploys_data)
    if context_text and window_start:
        _add_slack_events(timeline, context_text, window_start)

    timeline.events.sort(key=lambda e: e.timestamp)
    return timeline


# ---------------------------------------------------------------------------
# Metadata extraction with fallback
# ---------------------------------------------------------------------------

def _extract_metadata(
    pd_data: Optional[Dict[str, Any]],
    metrics_data: Optional[Dict[str, Any]],
    logs_data: Optional[Dict[str, Any]],
) -> Tuple[str, str, IncidentSeverity, datetime, Optional[datetime]]:
    """
    Extract incident_id, service, severity, window_start, window_end.
    PagerDuty is authoritative; falls back to metrics/logs timestamps if absent.
    """
    if pd_data:
        inc = pd_data["incident"]
        incident_id = inc["id"]
        service = inc["service"]
        severity: IncidentSeverity = inc.get("severity", "SEV-2")
        window_start = parse_iso(inc["created_at"])
        window_end = parse_iso(inc["resolved_at"]) if inc.get("resolved_at") else None
        return incident_id, service, severity, window_start, window_end

    # Fallback: infer from available timestamps
    timestamps: List[datetime] = []
    service = "unknown"

    if metrics_data:
        for series in metrics_data.get("metrics", []):
            svc = series.get("labels", {}).get("service")
            if svc:
                service = svc
            for pt in series.get("values", []):
                timestamps.append(parse_iso(pt["timestamp"]))

    if logs_data:
        for entry in logs_data.get("logs", []):
            timestamps.append(parse_iso(entry["timestamp"]))
            svc = entry.get("service")
            if svc:
                service = svc

    if timestamps:
        window_start = min(timestamps)
        window_end = max(timestamps)
    else:
        window_start = datetime.now(timezone.utc)
        window_end = None

    return "unknown", service, "SEV-2", window_start, window_end


# ---------------------------------------------------------------------------
# PagerDuty events (from dict)
# ---------------------------------------------------------------------------

def _add_pagerduty_events(timeline: IncidentTimeline, pd_data: Dict[str, Any]) -> None:
    """Add PagerDuty lifecycle events from a parsed dict."""
    inc = pd_data.get("incident", {})
    for entry in inc.get("timeline", []):
        timeline.events.append(
            IncidentEvent(
                timestamp=parse_iso(entry["timestamp"]),
                type="alert",
                source="pagerduty",
                summary=entry["message"],
                structured_data={
                    "pagerduty_type": entry["type"],
                    "user": entry.get("user"),
                },
            )
        )


# ---------------------------------------------------------------------------
# Prometheus Metrics (from dict)
# ---------------------------------------------------------------------------

_LATENCY_P99_THRESHOLD = 1.0
_LATENCY_P50_THRESHOLD = 0.5
_POOL_UTIL_THRESHOLD = 0.9
_HTTP_500_THRESHOLD = 1


def _add_metric_events(timeline: IncidentTimeline, data: Dict[str, Any]) -> None:
    """Detect spikes in Prometheus metrics and emit metric_spike events."""
    for series in data.get("metrics", []):
        metric_name = series["metric_name"]
        labels = series.get("labels", {})
        quantile = labels.get("quantile")

        for pt in series.get("values", []):
            ts = parse_iso(pt["timestamp"])
            val = pt["value"]

            spike = False
            summary = ""

            if metric_name == "http_request_duration_seconds" and quantile == "0.99":
                if val >= _LATENCY_P99_THRESHOLD:
                    spike = True
                    summary = f"p99 latency spike: {val}s (threshold {_LATENCY_P99_THRESHOLD}s)"

            elif metric_name == "http_request_duration_seconds" and quantile == "0.50":
                if val >= _LATENCY_P50_THRESHOLD:
                    spike = True
                    summary = f"p50 latency elevated: {val}s"

            elif metric_name == "database_connection_pool_utilization":
                if val >= _POOL_UTIL_THRESHOLD:
                    spike = True
                    summary = f"DB connection pool utilization at {val*100:.0f}%"

            elif metric_name == "http_requests_total" and labels.get("status") == "500":
                if val >= _HTTP_500_THRESHOLD:
                    spike = True
                    summary = f"HTTP 500 errors: {int(val)} in interval"

            if spike:
                timeline.events.append(
                    IncidentEvent(
                        timestamp=ts,
                        type="metric_spike",
                        source="prometheus",
                        summary=summary,
                        structured_data={
                            "metric_name": metric_name,
                            "labels": labels,
                            "value": val,
                        },
                    )
                )


# ---------------------------------------------------------------------------
# CloudWatch Logs (from dict)
# ---------------------------------------------------------------------------

def _add_log_events(timeline: IncidentTimeline, data: Dict[str, Any]) -> None:
    """Parse CloudWatch logs and emit error_burst / note events."""
    for entry in data.get("logs", []):
        ts = parse_iso(entry["timestamp"])
        level = entry.get("level", "INFO")
        event_type: str = "error_burst" if level == "ERROR" else "note"

        timeline.events.append(
            IncidentEvent(
                timestamp=ts,
                type=event_type,  # type: ignore[arg-type]
                source="cloudwatch",
                summary=f"[{level}] {entry['message']}",
                structured_data=entry.get("context", {}),
            )
        )


# ---------------------------------------------------------------------------
# GitHub Deployments (from dict)
# ---------------------------------------------------------------------------

def _add_deployment_events(timeline: IncidentTimeline, data: Dict[str, Any]) -> None:
    """Add deployment events from a parsed dict."""
    for dep in data.get("deployments", []):
        ts = parse_iso(dep["timestamp"])
        title = dep.get("title", "unknown deployment")
        service = dep.get("service", "unknown")
        pr = dep.get("pr_number")

        timeline.events.append(
            IncidentEvent(
                timestamp=ts,
                type="deployment",
                source="github",
                summary=f"Deployed to {service}: {title}" + (f" (PR #{pr})" if pr else ""),
                structured_data={
                    "service": service,
                    "pr_number": pr,
                    "commit_sha": dep.get("commit_sha"),
                    "author": dep.get("author"),
                    "title": title,
                    "description": dep.get("description"),
                    "files_changed": dep.get("files_changed", []),
                    "diff_snippet": dep.get("diff_snippet"),
                },
            )
        )


# ---------------------------------------------------------------------------
# Slack / incident_context (from string)
# ---------------------------------------------------------------------------

_SLACK_LINE_RE = re.compile(
    r"\[(\d{1,2}:\d{2}\s*[APap][Mm])\]\s+@([\w.\-]+):\s*(.*)"
)


def _add_slack_events(
    timeline: IncidentTimeline, text: str, incident_date_ref: datetime
) -> None:
    """
    Parse Slack-style incident context text and add slack_message events.

    Timestamps are local times like '2:23 PM'. We anchor them to the
    incident date and convert Pacific (UTC-8) to UTC by adding 8 hours.
    """
    base_date = incident_date_ref.date()

    for match in _SLACK_LINE_RE.finditer(text):
        time_str, user, message = match.groups()

        try:
            local_time = datetime.strptime(time_str.strip(), "%I:%M %p")
        except ValueError:
            continue

        utc_hour = local_time.hour + 8
        ts = datetime(
            base_date.year,
            base_date.month,
            base_date.day,
            utc_hour % 24,
            local_time.minute,
            tzinfo=timezone.utc,
        )

        timeline.events.append(
            IncidentEvent(
                timestamp=ts,
                type="slack_message",
                source="slack",
                summary=f"@{user}: {message.strip()}",
                structured_data={"user": user, "raw": message.strip()},
            )
        )
