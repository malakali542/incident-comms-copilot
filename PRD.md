# AI-Enhanced Incident Communications Copilot

**Product Requirements Document**

---

# 1. Executive Summary

During customer-impacting incidents, Abnormal must communicate clearly, quickly, and consistently via its status page. Today, these updates are manually drafted by incident commanders and support engineers under high cognitive load. This results in delays, inconsistent tone, and risk of over-sharing internal technical details.

This proposal introduces an **AI-native Incident Communications Copilot** that transforms raw multi-source incident data (logs, metrics, alerts, deployments, Slack discussions) into structured, customer-ready communications with built-in guardrails.

The Copilot reduces drafting time, standardizes messaging, and ensures clarity around customer impact while preserving human oversight.

---

# 2. Problem Statement

When a Sev-1 or Sev-2 incident occurs:

* Engineers are debugging and coordinating mitigation.
* Customer-facing communications must be drafted in parallel.
* Raw signals are distributed across multiple systems:

| Source                  | File |
| ----------------------- | ---- |
| PagerDuty alerts        |      |
| Prometheus metrics      |      |
| CloudWatch logs         |      |
| GitHub deployments      |      |
| Slack #incident threads |      |
| Context documentation   |      |

### Pain Points

**Time-to-first-update is slow**
Engineers must manually synthesize fragmented data before drafting.

**Inconsistent messaging**
Tone, structure, and level of technical detail vary by author.

**Risk of over- or under-communication**
Internal speculation or infrastructure identifiers may leak into customer-facing copy.

**Cognitive overload**
Engineers context-switch from debugging to drafting communications.

---

### Core Problem

There is no structured system that translates technical incident signals into customer-appropriate communications in real time.

---

# 3. Vision & North Star

## Vision

Create an AI-native Copilot embedded into the incident lifecycle that:

* Synthesizes multi-source technical signals
* Extracts structured incident facts
* Generates clear, compliant customer updates
* Highlights communication risks
* Keeps humans in the loop

## North Star Metric

Reduce **Time-to-First External Update** for Sev-1/2 incidents by 60% while improving communication consistency and reducing messaging-related risk.

---

# 4. Key Product Insight

All incident data sources share a common abstraction:

> An incident is a time-bounded, service-scoped collection of correlated technical signals.

Each system contributes time-indexed events:

| Source      | Contribution                                    |
| ----------- | ----------------------------------------------- |
| PagerDuty   | Incident metadata, severity, official timeline  |
| Metrics     | Customer-facing performance degradation         |
| Logs        | Failure signatures & recovery signals           |
| Deployments | Potential causal changes                        |
| Slack       | Human validation & mitigation notes             |

The Copilot normalizes these into a **Unified Incident Timeline Model**, which becomes the grounded input to the AI system.

---

# 5. Product Scope

## In Scope (Crawl Phase / Prototype)

* Manual upload of incident bundle (zip containing logs, metrics, Slack, deployments, PagerDuty)
* Auto-detection of:

  * Incident ID
  * Service
  * Severity
  * Incident window
* Structured incident fact extraction (JSON-first)
* Customer-ready draft generation
* Risk/compliance highlighting
* Editable draft with human review

## Out of Scope (V1)

* Automated publishing to status page
* Full Slack/PagerDuty API integration
* Postmortem automation
* Legal approval workflows

---

# 6. User Personas

## Primary: Incident Commander (Engineering/SRE)

Goals:

* Reduce drafting time
* Maintain factual accuracy
* Avoid compliance mistakes
* Maintain confidence in communications

## Secondary: Support / Customer Success

Goals:

* Reuse standardized messaging
* Clearly communicate impact to customers
* Reduce back-and-forth clarification

---

# 7. User Experience

## Crawl Phase Flow

1. User uploads incident bundle.
2. System auto-detects:

   * Incident ID
   * Service
   * Severity
   * Time window
3. User selects incident stage:

   * Initial
   * Identified
   * Monitoring
   * Resolved
4. System generates:

   * Internal structured summary
   * Customer-facing draft
   * Risk flags
5. User edits and copies to status page.

## Key UX Principles

* AI proposes; human approves.
* Structured templates, not freeform prose.
* Risk highlighting is visible but non-blocking.
* Minimal clicks during high-severity events.

---

# 8. Technical Architecture

## 8.1 Unified Incident Timeline Builder

All sources are normalized into:

```json
{
  "incident_id": "...",
  "service": "...",
  "severity": "...",
  "window": { "start": "...", "end": "..." },
  "events": [...]
}
```

Each event includes:

* timestamp
* type (alert, metric_spike, error_burst, deployment, slack_message)
* summary
* source
* structured_data

PagerDuty defines official start/end time.
Metrics quantify degradation.
Logs confirm failure signatures.

---

## 8.2 AI Pipeline

### Step 1: Structured Extraction (Grounded JSON)

LLM extracts:

* Customer impact summary
* Affected services
* Incident start/end
* Current status
* Known vs unknown factors
* Mitigation steps
* Root cause confidence
* Deployment correlation (boolean)
* Confidence score

Output is structured JSON.

---

### Step 2: Template-Based Generation

Second LLM pass transforms structured JSON into:

* Internal summary
* External customer update

Templates vary by:

* Severity level
* Incident stage

This ensures consistency and prevents over-creativity.

---

### Step 3: Risk & Compliance Pass

Third LLM pass flags:

* Internal-only identifiers (PR numbers, DB names)
* Speculative root cause claims
* Excessive technical jargon
* Sensitive infrastructure details

Flagged phrases are highlighted in UI before publication.

---

# 9. Crawl → Walk → Run Evolution

## Crawl (Pilot)

* Manual incident bundle upload
* Limited to Sev-1/2
* Validate AI extraction and generation
* Human review mandatory

## Walk (API-Connected Bundle Builder)

Introduce backend service:

Given `incident_id`, system queries:

* PagerDuty API
* Slack API
* Metrics backend
* Logging system
* GitHub API

Unified timeline built automatically.

User selects incident ID; no manual upload required.

## Run (Fully Integrated & Triggered)

* Incident declared → auto-trigger bundle builder
* Draft appears directly in incident management UI
* Updates regenerate as new signals arrive
* One-click publish to status page
* Continuous regression evaluation runs in background

---

# 10. Evaluation Strategy

Because this system generates customer-facing content, evaluation is mandatory.

We evaluate across three dimensions:

---

## 10.1 Structured Extraction Accuracy

Required fields:

* incident_id
* service
* severity
* start_time
* end_time
* impact_type
* mitigation_summary

Metric:

```python
accuracy = correct_fields / total_required_fields
```

Target: ≥ 90% accuracy across golden dataset.

---

## 10.2 Hallucination Detection

We explicitly test for:

* Fabricated deployments
* Invented database names
* Incorrect timelines
* Speculative claims unsupported by data

Metric:

* % of incidents with zero hallucinated fields
  Target: 100% on golden set.

---

## 10.3 Communication Quality

Human-rated rubric (1–5):

* Clarity
* Accuracy
* Tone alignment
* Completeness
* Signal-to-noise

Target: ≥ 4.0 average score.

---

## 10.4 Compliance & Risk Precision

Evaluate:

* % of internal-only terms correctly flagged
* False positive rate
* Precision / Recall for risk detection

---

# 11. Golden Evaluation Dataset

We introduce a small golden dataset of synthetic incidents covering diverse failure modes.

### G1 – Deployment Regression

Tests deployment correlation and rollback detection.

Expected:

* deployment_related = true
* impact_type = performance_degradation_and_errors

---

### G2 – External Dependency Failure

No deployment present.

Expected:

* deployment_related = false
* root_cause_confidence = external_dependency

---

### G3 – Transient Spike

Brief latency increase only.

Expected:

* impact_type = minor_transient_latency
* requires_status_page_update = false

---

### G4 – Partial Data

Missing Slack and incomplete logs.

Expected:

* root_cause_confidence = unknown
* Conservative customer wording

Each golden incident contains:

* Synthetic incident bundle
* Expected structured JSON output
* Expected risk flags

Model versions must pass regression before deployment.

---

# 12. Success Metrics

Operational:

* 60% reduction in time-to-first-update
* ≥ 70% Sev-1/2 adoption
* < 10% major rewrite rate

Quality:

* ≥ 90% structured extraction accuracy
* 0 hallucinated deployments
* ≥ 4.0 communication quality rating

Risk:

* 0 published incidents with internal detail leakage

---

# 13. Why This Works

This system:

* Grounds AI in structured signals
* Separates extraction from generation
* Introduces guardrails before publication
* Embeds evaluation discipline
* Scales via unified incident abstraction

It evolves cleanly from manual ingestion (crawl) to full automation (run) without changing the AI core architecture.
