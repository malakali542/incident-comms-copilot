# Incident Data Files

This directory contains anonymized raw data from a production incident. All timestamps, service names, and identifiers have been sanitized.

**Important**: This data represents RAW technical signals. You will need to analyze and synthesize this information to determine customer impact and craft appropriate external communications. Customer impact is NOT pre-computed - deriving it from these technical signals is part of the exercise.

## Files

### incident_context.txt
Freeform text containing:
- Slack thread excerpts from the #incidents channel
- Engineer notes and observations during the incident
- Timeline markers (e.g., "Started around 2:23 PM PT")
- Root cause hypotheses from the incident response team
- List of affected services and systems

**Format**: Plain text with section headers (===, ---)

**Note**: This contains internal engineering discussions. Your job is to translate these technical details into clear, customer-appropriate communications.

### cloudwatch_logs.json
Application logs from CloudWatch with structured error messages.

**Schema**:
```json
{
  "logs": [
    {
      "timestamp": "ISO 8601 timestamp (UTC)",
      "level": "ERROR | WARN | INFO",
      "service": "service name",
      "message": "log message",
      "context": {
        "key": "value",
        "nested": { "data": "..." }
      }
    }
  ]
}
```

**Key Fields**:
- `timestamp`: When the log entry was created (UTC)
- `level`: Log severity (ERROR, WARN, INFO)
- `service`: Which service emitted the log
- `message`: Human-readable log message
- `context`: Structured metadata (e.g., connection pool size, wait times)

**Usage for Communications**: Error frequency and timing help determine incident scope and duration for status updates.

### prometheus_metrics.json
Time-series metrics from Prometheus showing system health indicators.

**Schema**:
```json
{
  "metrics": [
    {
      "metric_name": "metric identifier",
      "labels": {"key": "value"},
      "values": [
        {"timestamp": "ISO 8601 (UTC)", "value": 0.0}
      ]
    }
  ]
}
```

**Key Fields**:
- `metric_name`: Prometheus metric name (e.g., `http_request_duration_seconds`)
- `labels`: Metric labels for filtering (e.g., `service`, `quantile`)
- `values`: Array of timestamp-value pairs showing metric over time

**Common Metrics**:
- `http_request_duration_seconds`: API request latency (with `quantile` label for p50, p99)
- `database_connection_pool_utilization`: Connection pool usage (0.0-1.0 scale)
- `http_requests_total`: Request count by status code

**Usage for Communications**: Latency spikes and error rates translate to customer-facing issues like "slow API responses" or "intermittent errors".

### pagerduty_incident.json
PagerDuty incident record with alert lifecycle events.

**Schema**:
```json
{
  "incident": {
    "id": "incident ID",
    "title": "incident title",
    "status": "triggered | acknowledged | resolved",
    "urgency": "high | low",
    "severity": "SEV-0 | SEV-1 | SEV-2 | SEV-3",
    "created_at": "ISO 8601 (UTC)",
    "acknowledged_at": "ISO 8601 (UTC)",
    "resolved_at": "ISO 8601 (UTC)",
    "service": "affected service",
    "assigned_to": "email",
    "timeline": [
      {
        "timestamp": "ISO 8601 (UTC)",
        "type": "trigger | acknowledge | resolve",
        "user": "email (for acknowledge/resolve)",
        "message": "timeline entry message"
      }
    ]
  }
}
```

**Key Fields**:
- `assigned_to`: Engineer who received the page
- `timeline`: Alert lifecycle (trigger, acknowledgment, resolution)
- `severity`: Incident severity rating
- `status`: Current incident status

**Usage for Communications**: Timing data helps establish incident start/end times for status page updates.

### github_deployments.json
Deployment history from GitHub with PR details and code changes.

**Schema**:
```json
{
  "deployments": [
    {
      "timestamp": "ISO 8601 (UTC)",
      "service": "service name",
      "pr_number": 12345,
      "commit_sha": "git commit SHA",
      "author": "email",
      "title": "PR title",
      "description": "PR description",
      "files_changed": ["file paths"],
      "diff_snippet": "git diff snippet (optional)"
    }
  ]
}
```

**Key Fields**:
- `timestamp`: When the deployment occurred
- `pr_number`: GitHub pull request number
- `description`: What the PR changed and why
- `diff_snippet`: Sample of code changes (if available)

**Usage for Communications**: Deployment timing helps identify root cause, but technical details should be abstracted for customer communications (e.g., "configuration change" vs "increased HTTP timeout from 10s to 30s").

## Usage Tips for Incident Communications

1. **Derive Customer Impact**: You need to analyze the technical signals to determine:
   - What functionality was affected? (API calls, specific features, entire service?)
   - How severe was the impact? (degraded performance vs complete outage)
   - When did it start and end? (incident window)
   - Who was impacted? (all customers, subset, specific regions?)

2. **Cross-reference timestamps**: The incident timeline spans multiple data sources. Look for correlated events across logs, metrics, and deployments to build a complete picture.

3. **Parse ISO 8601 timestamps**: All timestamps are in UTC. You may need to convert to Pacific Time (PT) for timeline presentation.

4. **Translate technical to customer-friendly**: 
   - "Database connection pool exhausted" → "API performance degradation"
   - "p99 latency 15s" → "significantly slower response times"
   - "500 errors" → "intermittent service errors"

5. **Filter by severity**: Not all technical details belong in customer communications. Focus on:
   - What customers experienced (not internal system states)
   - Duration and scope of impact
   - Resolution status and next steps

6. **Handle missing fields**: Some entries may have optional fields (e.g., `diff_snippet`). Your code should gracefully handle missing data.
