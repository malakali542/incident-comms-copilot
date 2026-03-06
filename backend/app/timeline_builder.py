# app/timeline_builder.py
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from .models import IncidentTimeline, IncidentEvent, IncidentSeverity


def parse_iso(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp, normalizing trailing Z to +00:00."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def build_timeline_from_dict(payload: dict) -> IncidentTimeline:
    """
    Build a unified IncidentTimeline from a dict payload (used by the API).

    Expected keys:
    - pagerduty_incident: dict  (required)
    - prometheus_metrics: dict  (optional)
    - cloudwatch_logs: dict     (optional)
    - github_deployments: dict  (optional)
    - incident_context: str     (optional, raw Slack-style text)
    """
    pd_data = payload["pagerduty_incident"]["incident"]
    incident_id: str = pd_data["id"]
    service: str = pd_data["service"]
    severity: IncidentSeverity = pd_data.get("severity", "SEV-2")
    window_start = parse_iso(pd_data["created_at"])
    window_end = parse_iso(pd_data["resolved_at"]) if pd_data.get("resolved_at") else None

    timeline = IncidentTimeline(
        incident_id=incident_id,
        service=service,
        severity=severity,
        window_start=window_start,
        window_end=window_end,
    )

    # PagerDuty lifecycle events
    for entry in pd_data.get("timeline", []):
        timeline.events.append(
            IncidentEvent(
                timestamp=parse_iso(entry["timestamp"]),
                type="alert",
                source="pagerduty",
                summary=entry["message"],
                structured_data={"pagerduty_type": entry["type"], "user": entry.get("user")},
            )
        )

    # Prometheus metrics
    for series in payload.get("prometheus_metrics", {}).get("metrics", []):
        metric_name = series["metric_name"]
        labels = series.get("labels", {})
        quantile = labels.get("quantile")
        for pt in series.get("values", []):
            ts = parse_iso(pt["timestamp"])
            val = pt["value"]
            spike, summary = False, ""
            if metric_name == "http_request_duration_seconds" and quantile == "0.99":
                if val >= _LATENCY_P99_THRESHOLD:
                    spike, summary = True, f"p99 latency spike: {val}s (threshold {_LATENCY_P99_THRESHOLD}s)"
            elif metric_name == "http_request_duration_seconds" and quantile == "0.50":
                if val >= _LATENCY_P50_THRESHOLD:
                    spike, summary = True, f"p50 latency elevated: {val}s"
            elif metric_name == "database_connection_pool_utilization":
                if val >= _POOL_UTIL_THRESHOLD:
                    spike, summary = True, f"DB connection pool utilization at {val*100:.0f}%"
            elif metric_name == "http_requests_total" and labels.get("status") == "500":
                if val >= _HTTP_500_THRESHOLD:
                    spike, summary = True, f"HTTP 500 errors: {int(val)} in interval"
            if spike:
                timeline.events.append(
                    IncidentEvent(
                        timestamp=ts,
                        type="metric_spike",
                        source="prometheus",
                        summary=summary,
                        structured_data={"metric_name": metric_name, "labels": labels, "value": val},
                    )
                )

    # CloudWatch logs
    for entry in payload.get("cloudwatch_logs", {}).get("logs", []):
        ts = parse_iso(entry["timestamp"])
        level = entry.get("level", "INFO")
        timeline.events.append(
            IncidentEvent(
                timestamp=ts,
                type="error_burst" if level == "ERROR" else "note",  # type: ignore[arg-type]
                source="cloudwatch",
                summary=f"[{level}] {entry['message']}",
                structured_data=entry.get("context", {}),
            )
        )

    # GitHub deployments
    for dep in payload.get("github_deployments", {}).get("deployments", []):
        ts = parse_iso(dep["timestamp"])
        title = dep.get("title", "unknown deployment")
        svc = dep.get("service", "unknown")
        pr = dep.get("pr_number")
        timeline.events.append(
            IncidentEvent(
                timestamp=ts,
                type="deployment",
                source="github",
                summary=f"Deployed to {svc}: {title}" + (f" (PR #{pr})" if pr else ""),
                structured_data={
                    "service": svc,
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

    # Slack / incident_context (raw text)
    slack_text: str = payload.get("incident_context", "") or ""
    if slack_text:
        base_date = window_start.date()
        for match in _SLACK_LINE_RE.finditer(slack_text):
            time_str, user, message = match.groups()
            try:
                local_time = datetime.strptime(time_str.strip(), "%I:%M %p")
            except ValueError:
                continue
            utc_hour = local_time.hour + 8
            ts = datetime(
                base_date.year, base_date.month, base_date.day,
                utc_hour % 24, local_time.minute,
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

    timeline.events.sort(key=lambda e: e.timestamp)
    return timeline


def build_timeline_from_bundle(bundle_dir: Path) -> IncidentTimeline:
    """
    Build a unified IncidentTimeline from the provided incident bundle directory.

    Expected files (as in the take-home dataset):
    - pagerduty_incident.json
    - prometheus_metrics.json
    - cloudwatch_logs.json
    - github_deployments.json
    - incident_context.txt
    """
    pagerduty_path = bundle_dir / "pagerduty_incident.json"
    metrics_path = bundle_dir / "prometheus_metrics.json"
    logs_path = bundle_dir / "cloudwatch_logs.json"
    deployments_path = bundle_dir / "github_deployments.json"
    slack_path = bundle_dir / "incident_context.txt"

    incident_id, service, severity, window_start, window_end = _parse_pagerduty(
        pagerduty_path
    )

    timeline = IncidentTimeline(
        incident_id=incident_id,
        service=service,
        severity=severity,
        window_start=window_start,
        window_end=window_end,
    )

    _add_pagerduty_timeline_events(timeline, pagerduty_path)
    _add_metric_events(timeline, metrics_path)
    _add_log_events(timeline, logs_path)
    _add_deployment_events(timeline, deployments_path)
    _add_slack_events(timeline, slack_path, window_start)

    # Sort all events chronologically
    timeline.events.sort(key=lambda e: e.timestamp)
    return timeline


# ---------------------------------------------------------------------------
# PagerDuty
# ---------------------------------------------------------------------------

def _parse_pagerduty(
    path: Path,
) -> Tuple[str, str, IncidentSeverity, datetime, Optional[datetime]]:
    with path.open() as f:
        data = json.load(f)["incident"]

    incident_id: str = data["id"]
    service: str = data["service"]
    severity: IncidentSeverity = data.get("severity", "SEV-2")
    window_start = parse_iso(data["created_at"])
    window_end = parse_iso(data["resolved_at"]) if data.get("resolved_at") else None
    return incident_id, service, severity, window_start, window_end


def _add_pagerduty_timeline_events(timeline: IncidentTimeline, path: Path) -> None:
    """Add PagerDuty lifecycle events (trigger, acknowledge, resolve)."""
    with path.open() as f:
        data = json.load(f)["incident"]

    for entry in data.get("timeline", []):
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
# Prometheus Metrics
# ---------------------------------------------------------------------------

# Thresholds for detecting notable metric events
_LATENCY_P99_THRESHOLD = 1.0  # seconds
_LATENCY_P50_THRESHOLD = 0.5
_POOL_UTIL_THRESHOLD = 0.9
_HTTP_500_THRESHOLD = 1  # any 500s are notable


def _add_metric_events(timeline: IncidentTimeline, path: Path) -> None:
    """Detect spikes in Prometheus metrics and emit metric_spike events."""
    if not path.exists():
        return
    with path.open() as f:
        data = json.load(f)

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
# CloudWatch Logs
# ---------------------------------------------------------------------------

def _add_log_events(timeline: IncidentTimeline, path: Path) -> None:
    """Parse CloudWatch logs and emit error_burst / note events."""
    if not path.exists():
        return
    with path.open() as f:
        data = json.load(f)

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
# GitHub Deployments
# ---------------------------------------------------------------------------

def _add_deployment_events(timeline: IncidentTimeline, path: Path) -> None:
    """Add deployment events from github_deployments.json."""
    if not path.exists():
        return
    with path.open() as f:
        data = json.load(f)

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
# Slack / incident_context.txt
# ---------------------------------------------------------------------------

# Pattern matches lines like: [2:23 PM] @alice.engineer: Some message
_SLACK_LINE_RE = re.compile(
    r"\[(\d{1,2}:\d{2}\s*[APap][Mm])\]\s+@([\w.\-]+):\s*(.*)"
)


def _add_slack_events(
    timeline: IncidentTimeline, path: Path, incident_date_ref: datetime
) -> None:
    """
    Parse the Slack-style incident_context.txt and add slack_message events.

    Timestamps in the file are local times like '2:23 PM'. We anchor them
    to the same UTC date as the incident start (good enough for a single-day
    incident). For this dataset the Slack times are Pacific but the metrics
    are UTC; the file header says 'around 2:23 PM Pacific Time' which maps
    to 14:23 UTC on this particular January day (UTC-8).  We store them as
    UTC by adding 8 hours to the parsed local time.
    """
    if not path.exists():
        return

    text = path.read_text(encoding="utf-8")
    base_date = incident_date_ref.date()

    for match in _SLACK_LINE_RE.finditer(text):
        time_str, user, message = match.groups()

        # Parse "2:23 PM" -> hour/minute
        try:
            local_time = datetime.strptime(time_str.strip(), "%I:%M %p")
        except ValueError:
            continue

        # Anchor to incident date.  Slack times are Pacific (UTC-8 in January).
        # Convert to UTC by adding 8 hours.
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
