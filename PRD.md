# AI-Enhanced Incident Communications Copilot

**Product Requirements Document**

---

# 1. Executive Summary

During customer-impacting incidents, Abnormal must communicate clearly, quickly, and consistently via its status page. Today, these updates are manually drafted by incident commanders and support engineers under high cognitive load. This results in delays, inconsistent tone, and risk of over-sharing internal technical details.

This proposal introduces an **AI-native Incident Communications Copilot** that transforms raw multi-source incident data (logs, metrics, alerts, deployments, Slack discussions) into structured, customer-ready communications with built-in guardrails.

The Copilot reduces drafting time, standardizes messaging, and ensures clarity around customer impact while preserving human oversight.

---

# 2. Key Assumptions

The following assumptions inform the product design and scoping decisions:

### About the Current Process
* Incident communications are drafted **manually** by whoever is on-call — there is no templating system or AI assistance in place today.
* The primary bottleneck is **synthesis, not writing** — engineers have the data but struggle to distill it into customer-appropriate language under time pressure.
* Multiple data sources (PagerDuty, Prometheus, CloudWatch, GitHub, Slack) are already captured during incidents but are **not consolidated** into a single view.
* Status page updates follow an informal structure that varies by author; there is no enforced template or style guide.

### About Stakeholders & Users
* The **Incident Commander** (typically a senior engineer or SRE) owns the decision to publish external communications and is the primary user of this tool.
* **Technical Support / Customer Success** teams are secondary consumers who need consistent, pre-approved language to relay to customers through other channels (email, chat).
* There is **no dedicated communications team** reviewing status page updates during incidents — the engineer who publishes is the final reviewer.
* Leadership and legal review is post-hoc, not blocking — meaning guardrails must be built **into** the tool, not added as a manual approval step.

### About AI & Technical Constraints
* LLM-generated content must **never be auto-published** — a human must review and approve every external message.
* Structured extraction (JSON) before generation reduces hallucination risk compared to end-to-end text generation.
* The tool must work with **incomplete data** — not every incident will have all five data sources available (e.g., Slack threads may be missing for off-hours incidents).
* Latency of the full AI pipeline (extraction + generation + risk scan) must stay **under 30 seconds** to be useful during active incidents.

---

# 3. Problem Statement

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

## Primary User: Incident Commander (Engineering/SRE)

The IC is the person who owns the incident end-to-end. They are typically a senior engineer or SRE who was paged, and they are simultaneously debugging, coordinating, and responsible for external communications.

**Context of use:** High-stress, time-sensitive. The IC has 5–10 browser tabs open, is on a Zoom bridge, and needs to push a status page update within minutes — not hours.

**Goals:**
* Draft a customer update in **under 2 minutes** instead of 15–20
* Avoid accidentally leaking internal details (PR numbers, DB names, engineer names)
* Feel confident the message is accurate and appropriately scoped
* Not have to context-switch from debugging to "marketing-style writing"

**Key frustration:** "I know what happened, but I don't have time to wordsmith it for customers right now."

## Secondary User: Technical Support / Customer Success

Support engineers receive inbound customer inquiries during incidents. They need consistent, approved language they can reference or forward.

**Context of use:** Reactive — responding to customer tickets and escalations during/after incidents.

**Goals:**
* Access a pre-approved customer-facing summary without chasing the IC
* Communicate impact clearly without needing deep technical context
* Reduce back-and-forth clarification with engineering

**Key frustration:** "Engineering says 'we're working on it' but I need specifics to tell the customer."

---

# 7. User Experience

## User Flow (Crawl Phase)

```
┌─────────────────────────────────────────────────────────────┐
│  IC is paged → opens Copilot in browser                     │
│                                                             │
│  Step 1: UPLOAD                                             │
│  ├── User input: Drag & drop incident bundle (.zip)         │
│  └── Contains: PagerDuty, metrics, logs, deploys, Slack     │
│                                                             │
│  Step 2: AUTO-DETECT (no user input required)               │
│  ├── System extracts: Incident ID, Service, Severity        │
│  ├── System determines: Time window (start → end)           │
│  └── System builds: Unified timeline from all sources       │
│                                                             │
│  Step 3: SELECT STAGE                                       │
│  ├── User input: Picks incident stage from dropdown         │
│  └── Options: Initial | Identified | Monitoring | Resolved  │
│                                                             │
│  Step 4: AI GENERATES (3-stage pipeline, ~10-15s)           │
│  ├── Output 1: Internal structured summary (for eng team)   │
│  ├── Output 2: Customer-facing status page draft            │
│  └── Output 3: Brand risk flags with explanations           │
│                                                             │
│  Step 5: REVIEW & EDIT                                      │
│  ├── User reviews side-by-side (internal | external)        │
│  ├── User edits the external draft directly in-browser      │
│  ├── Risk flags highlight phrases to reconsider             │
│  └── User copies final text → pastes to status page         │
└─────────────────────────────────────────────────────────────┘
```

### What the user provides (inputs)
* **Incident bundle** (.zip) — the only required input. Contains raw data files that are already generated during normal incident response.
* **Incident stage** — a single dropdown selection that controls the tone and structure of the generated message (e.g., "initial" = emphasize investigation in progress; "resolved" = past tense, focus on resolution).

### What the user receives (outputs)
* **Internal summary** — technical details suitable for engineering Slack channels and postmortem docs. May include PR numbers, DB names, and root cause hypotheses.
* **Customer-facing draft** — structured update with sections: Summary, Impact, Scope & Duration, Current Status, Next Steps. Written in plain language with no internal identifiers.
* **Risk flags** — specific phrases highlighted with category (internal identifier / speculation / overly technical) and recommended action. Non-blocking — the user decides whether to edit.

### Why this flow works
* **One file upload, not five** — the IC doesn't have to manually copy data from each system.
* **Stage selection is the only decision** — everything else is inferred from data.
* **AI proposes; human approves** — the IC maintains full control and can edit freely.
* **Side-by-side layout** — mirrors how ICs think: "what do we know internally?" vs. "what do we tell customers?"

## Key UX Principles

* **AI proposes; human approves.** No auto-publishing, ever.
* **Structured templates, not freeform prose.** Consistency comes from structure, not instructions.
* **Risk highlighting is visible but non-blocking.** Flags inform; they don't gate.
* **Minimal clicks during high-severity events.** Upload → select stage → generate. Three actions.

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
