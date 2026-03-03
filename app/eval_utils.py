# app/eval_utils.py
"""
Offline evaluation utilities for the Incident Communications Copilot.

Compares LLM-extracted IncidentFacts against golden expected values,
checks for hallucinations, and scores brand risk scanner precision/recall.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from .models import IncidentFacts, RiskScanResult


# ---------------------------------------------------------------------------
# Fields we evaluate (deterministic comparison)
# ---------------------------------------------------------------------------

EVAL_FIELDS = [
    "incident_id",
    "service",
    "severity",
    "start_time",
    "end_time",
    "impact_type",
    "deployment_related",
]


# ---------------------------------------------------------------------------
# Field-level accuracy
# ---------------------------------------------------------------------------

def compare_facts_to_expected(
    facts: IncidentFacts, expected: Dict[str, Any]
) -> Tuple[int, int, List[str]]:
    """
    Compare selected fields of IncidentFacts to an expected dict.

    Returns:
        correct  – number of matching fields
        total    – total fields compared
        mismatches – human-readable list of discrepancies
    """
    correct = 0
    mismatches: List[str] = []

    for f in EVAL_FIELDS:
        actual = getattr(facts, f, None)
        exp = expected.get(f)

        # Skip fields not present in expected (allows partial golden sets)
        if exp is None:
            continue

        if _fields_match(f, actual, exp):
            correct += 1
        else:
            mismatches.append(f"{f}: actual={actual!r}, expected={exp!r}")

    total = len([f for f in EVAL_FIELDS if expected.get(f) is not None])
    return correct, total, mismatches


def _normalize(value: Any) -> str:
    """Lowercase string representation for fuzzy matching."""
    return str(value).lower().strip()


def _normalize_timestamp(ts: str) -> str:
    """Normalize ISO timestamps so +00:00 and Z are equivalent."""
    s = ts.strip()
    s = s.replace("+00:00", "Z").replace("+0000", "Z")
    if not s.endswith("Z"):
        s = s + "Z"  # best-effort
    return s.lower()


def _normalize_slug(text: str) -> str:
    """
    Convert natural-language text to a comparable slug.
    'Degraded performance and errors' → 'degraded_performance_and_errors'
    'performance_degradation_and_errors' stays the same.
    """
    import re
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = s.strip("_")
    return s


# Semantic equivalence groups for impact_type
_IMPACT_TYPE_SYNONYMS = [
    {"degraded_performance", "degraded_performance_and_errors",
     "elevated_latency_and_errors", "performance_degradation",
     "performance_degradation_and_errors", "elevated_latency_and_minor_errors",
     "high_latency_and_errors", "latency_and_errors"},
    {"service_outage", "degraded_payments", "payment_failures", "outage",
     "payment_processing_failure"},
    {"minor_transient_latency", "transient_latency_spike", "transient_spike",
     "brief_latency_spike", "elevated_latency_and_minor_errors"},
    {"errors_and_latency", "elevated_errors_and_latency", "elevated_error_rate",
     "errors_and_elevated_latency", "high_error_rate_and_latency"},
]


def _impact_types_equivalent(a: str, b: str) -> bool:
    """Check if two impact_type values are semantically equivalent."""
    slug_a = _normalize_slug(a)
    slug_b = _normalize_slug(b)
    if slug_a == slug_b:
        return True
    for group in _IMPACT_TYPE_SYNONYMS:
        if slug_a in group and slug_b in group:
            return True
    return False


def _fields_match(field_name: str, actual: Any, expected: Any) -> bool:
    """Smart field comparison with type-aware normalization."""
    # Exact match (fast path)
    if _normalize(actual) == _normalize(expected):
        return True

    # Timestamp fields: normalize Z vs +00:00
    if field_name in ("start_time", "end_time"):
        return _normalize_timestamp(str(actual)) == _normalize_timestamp(str(expected))

    # Slug-style fields: normalize spaces/hyphens to underscores
    if field_name == "impact_type":
        return _impact_types_equivalent(str(actual), str(expected))

    if field_name == "root_cause_confidence":
        return _normalize_slug(str(actual)) == _normalize_slug(str(expected))

    return False


# ---------------------------------------------------------------------------
# Hallucination checks
# ---------------------------------------------------------------------------

def check_hallucinations(
    facts: IncidentFacts, expected: Dict[str, Any]
) -> List[str]:
    """
    Check for hallucinated facts that contradict the golden expected values.

    Returns a list of hallucination descriptions.  An empty list is good.
    """
    hallucinations: List[str] = []

    # 1. Fabricated deployment correlation
    exp_deploy = expected.get("deployment_related")
    if exp_deploy is not None:
        if _normalize(facts.deployment_related) != _normalize(exp_deploy):
            hallucinations.append(
                f"deployment_related hallucinated: got {facts.deployment_related!r}, "
                f"expected {exp_deploy!r}"
            )

    # 2. Wrong severity
    exp_sev = expected.get("severity")
    if exp_sev is not None and _normalize(facts.severity) != _normalize(exp_sev):
        hallucinations.append(
            f"severity hallucinated: got {facts.severity!r}, expected {exp_sev!r}"
        )

    # 3. Wrong service
    exp_svc = expected.get("service")
    if exp_svc is not None and _normalize(facts.service) != _normalize(exp_svc):
        hallucinations.append(
            f"service hallucinated: got {facts.service!r}, expected {exp_svc!r}"
        )

    return hallucinations


# ---------------------------------------------------------------------------
# Brand risk scanner precision / recall
# ---------------------------------------------------------------------------

def evaluate_risk_flags(
    risk_result: RiskScanResult,
    expected_flags: List[str],
) -> Dict[str, Any]:
    """
    Evaluate brand risk scanner output against expected flagged phrases.

    Args:
        risk_result    – the RiskScanResult from Model 3
        expected_flags – list of substrings that *should* be flagged

    Returns dict with precision, recall, true_positives, false_positives, false_negatives.
    """
    flagged_texts = [f.text.lower() for f in risk_result.flags]

    true_pos = 0
    false_neg: List[str] = []

    for exp in expected_flags:
        if any(exp.lower() in ft for ft in flagged_texts):
            true_pos += 1
        else:
            false_neg.append(exp)

    false_pos = len(flagged_texts) - true_pos
    false_pos = max(false_pos, 0)

    precision = true_pos / (true_pos + false_pos) if (true_pos + false_pos) > 0 else 1.0
    recall = true_pos / len(expected_flags) if expected_flags else 1.0

    return {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "true_positives": true_pos,
        "false_positives": false_pos,
        "false_negatives": false_neg,
    }


# ---------------------------------------------------------------------------
# Golden set helpers
# ---------------------------------------------------------------------------

def list_golden_incidents(golden_dir: Path) -> List[Path]:
    """Return sorted list of golden incident directories (G1, G2, …)."""
    if not golden_dir.exists():
        return []
    return sorted(
        [d for d in golden_dir.iterdir() if d.is_dir() and (d / "expected_facts.json").exists()]
    )


def validate_golden_incident(incident_dir: Path) -> Tuple[bool, List[str]]:
    """
    Check that a golden incident directory has the required files.

    Returns (valid, missing_files).
    """
    required_bundle_files = [
        "pagerduty_incident.json",
        "prometheus_metrics.json",
        "cloudwatch_logs.json",
        "github_deployments.json",
    ]
    missing: List[str] = []

    bundle_dir = incident_dir / "bundle"
    if not bundle_dir.exists():
        missing.append("bundle/")

    for fname in required_bundle_files:
        if not (bundle_dir / fname).exists():
            missing.append(f"bundle/{fname}")

    if not (incident_dir / "expected_facts.json").exists():
        missing.append("expected_facts.json")

    return len(missing) == 0, missing


# ---------------------------------------------------------------------------
# Default golden expected for quick UI eval (G1)
# ---------------------------------------------------------------------------

GOLDEN_EXPECTED = {
    "incident_id": "PXXX123",
    "service": "api-gateway",
    "severity": "SEV-2",
    "start_time": "2025-01-15T14:23:00Z",
    "end_time": "2025-01-15T16:45:00Z",
    "impact_type": "performance_degradation_and_errors",
    "deployment_related": "True",
}
