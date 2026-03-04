#!/usr/bin/env python3
"""
Offline Golden-Set Evaluation for the Incident Communications Copilot.

Runs the full LLM pipeline against each golden incident in golden/,
compares extracted facts to expected values, checks for hallucinations,
and prints a structured report.

Usage:
    python run_evals.py                     # run all golden incidents
    python run_evals.py --only G1           # run a single golden incident
    python run_evals.py --model gpt-4.1     # specify model
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from app.timeline_builder import build_timeline_from_bundle
from app.llm_pipeline import LLMClient, IncidentLLMPipeline
from app.eval_utils import (
    compare_facts_to_expected,
    check_hallucinations,
    list_golden_incidents,
    validate_golden_incident,
)

GOLDEN_DIR = Path("golden")

# Field → human-readable interpretation hint for mismatches
_FIELD_INTERPRETATIONS: Dict[str, str] = {
    "incident_id": "Incorrect incident identifier — possible cross-incident confusion",
    "service": "Wrong service attribution — may indicate multi-service confusion",
    "severity": "Severity level misclassified — affects triage priority",
    "start_time": "Incorrect incident start time — timeline anchoring error",
    "end_time": "Incorrect incident end time — resolution window miscalculated",
    "impact_type": "Misclassification of degradation severity or impact category",
    "deployment_related": "Incorrect deployment causality — critical for root cause analysis",
}


# ---------------------------------------------------------------------------
# Per-incident evaluation (computation only — no printing)
# ---------------------------------------------------------------------------

def evaluate_incident(
    incident_dir: Path,
    pipeline: IncidentLLMPipeline,
) -> Dict[str, Any]:
    """
    Run the pipeline on a single golden incident and return a result dict.
    """
    incident_id = incident_dir.name
    bundle_dir = incident_dir / "bundle"
    expected_path = incident_dir / "expected_facts.json"

    # Validate structure
    valid, missing = validate_golden_incident(incident_dir)
    if not valid:
        return {
            "incident_id": incident_id,
            "status": "SKIP",
            "reason": f"Missing files: {missing}",
        }

    # Load expected
    with expected_path.open() as f:
        expected = json.load(f)

    # Build timeline
    timeline = build_timeline_from_bundle(bundle_dir)

    # Stage 1: Extract facts
    start = time.time()
    facts = pipeline.extract_facts(timeline)
    extraction_time = round(time.time() - start, 2)

    # Field accuracy
    correct, total, mismatches = compare_facts_to_expected(facts, expected)
    accuracy = correct / total if total > 0 else 0.0

    # Hallucination check
    hallucinations = check_hallucinations(facts, expected)

    # Stage 2: Generate messages (for brand risk scan)
    start = time.time()
    messages = pipeline.generate_messages(facts, stage="resolved")
    generation_time = round(time.time() - start, 2)

    # Stage 3: Brand risk scan
    start = time.time()
    risk = pipeline.scan_risk(messages.external_update, facts=facts)
    risk_time = round(time.time() - start, 2)

    return {
        "incident_id": incident_id,
        "status": "OK",
        "description": expected.get("_description", ""),
        "correct": correct,
        "total": total,
        "accuracy": round(accuracy, 3),
        "mismatches": mismatches,
        "hallucinations": hallucinations,
        "risk_score": risk.risk_score,
        "risk_flags": [
            {"text": f.text, "category": f.category, "reason": f.reason}
            for f in risk.flags
        ],
        "extraction_time_s": extraction_time,
        "generation_time_s": generation_time,
        "risk_scan_time_s": risk_time,
        "extracted_facts": facts.__dict__,
        "external_update": messages.external_update,
    }


# ---------------------------------------------------------------------------
# Structured report: per-incident
# ---------------------------------------------------------------------------

def print_incident_report(result: Dict[str, Any]) -> None:
    """Print a structured evaluation report for one golden incident."""
    iid = result["incident_id"]

    print(f"\n{'=' * 60}")
    print(f"  INCIDENT EVALUATION: {iid}")
    print(f"{'=' * 60}")

    # -- Scenario --
    desc = result.get("description", "")
    if desc:
        print(f"\n📝 Scenario:")
        print(f"  {desc}")

    # -- Structured Extraction --
    correct = result["correct"]
    total = result["total"]
    pct = result["accuracy"] * 100
    print(f"\n📊 Structured Extraction")
    print(f"  Field Accuracy: {correct}/{total} ({pct:.0f}%)")

    mismatches: List[str] = result.get("mismatches", [])
    if mismatches:
        print(f"\n  ❌ Field Mismatches:")
        for raw in mismatches:
            # raw format: "field_name: actual=..., expected=..."
            field_name = raw.split(":")[0].strip()
            # Parse out actual/expected for clean display
            parts = raw.split(": actual=")
            if len(parts) == 2:
                vals = parts[1]
                actual_str, expected_str = vals.split(", expected=")
            else:
                actual_str, expected_str = "?", "?"

            print(f"    Field:    {field_name}")
            print(f"    Expected: {expected_str}")
            print(f"    Actual:   {actual_str}")

            interp = _FIELD_INTERPRETATIONS.get(field_name, "Unexpected value")
            print(f"    → {interp}")
            print()

    # -- Hallucination Check --
    hallucinations: List[str] = result.get("hallucinations", [])
    print(f"\n🔍 Hallucination Check")
    if hallucinations:
        print(f"  ❌ Hallucinations detected:")
        for h in hallucinations:
            print(f"    - {h}")
    else:
        print(f"  ✅ No contradictions with golden dataset")

    # -- Brand & Communications Risk --
    risk_score = result.get("risk_score", "n/a")
    flags = result.get("risk_flags", [])
    print(f"\n🛡️  Brand & Communications Risk")
    print(f"  Risk Score: {risk_score}")
    print(f"  Flags:      {len(flags)}")
    if flags:
        for flag in flags:
            print(f"    • [{flag['category']}] \"{flag['text']}\"")
            print(f"      → {flag['reason']}")

    # -- Pipeline Latency --
    ext_t = result.get("extraction_time_s", 0)
    gen_t = result.get("generation_time_s", 0)
    risk_t = result.get("risk_scan_time_s", 0)
    total_t = round(ext_t + gen_t + risk_t, 2)

    print(f"\n⏱️  Pipeline Latency")
    print(f"  Extraction: {ext_t:.2f}s")
    print(f"  Generation: {gen_t:.2f}s")
    print(f"  Risk Scan:  {risk_t:.2f}s")
    print(f"  Total:      {total_t:.2f}s")

    # -- Verdict --
    has_mismatches = len(mismatches) > 0
    has_hallucinations = len(hallucinations) > 0

    print(f"\nVerdict:")
    if has_hallucinations:
        print(f"  🔴 FAILED — hallucination or major regression")
    elif has_mismatches:
        print(f"  🟡 PARTIAL — minor field mismatches")
    else:
        print(f"  🟢 PASSED — no mismatches, no hallucinations")


# ---------------------------------------------------------------------------
# Structured report: overall summary
# ---------------------------------------------------------------------------

def print_summary_report(results: List[Dict[str, Any]]) -> None:
    """Print an aggregate summary report across all evaluated incidents."""
    ok_results = [r for r in results if r["status"] == "OK"]
    if not ok_results:
        return

    total_correct = sum(r["correct"] for r in ok_results)
    total_fields = sum(r["total"] for r in ok_results)
    overall_accuracy = total_correct / total_fields if total_fields > 0 else 0.0

    incidents_with_hallucinations = sum(
        1 for r in ok_results if r["hallucinations"]
    )

    risk_scores = [r.get("risk_score", "low") for r in ok_results]
    total_flags = sum(len(r.get("risk_flags", [])) for r in ok_results)

    total_latencies = [
        r.get("extraction_time_s", 0) + r.get("generation_time_s", 0) + r.get("risk_scan_time_s", 0)
        for r in ok_results
    ]
    avg_latency = sum(total_latencies) / len(total_latencies)

    # Compute average risk score (low=1, medium=2, high=3)
    _score_map = {"low": 1, "medium": 2, "high": 3}
    numeric_scores = [_score_map.get(s, 1) for s in risk_scores]
    avg_numeric = sum(numeric_scores) / len(numeric_scores)
    _reverse_map = {1: "low", 2: "medium", 3: "high"}
    avg_risk_label = _reverse_map.get(round(avg_numeric), "low")

    print(f"\n{'=' * 60}")
    print(f"  EVALUATION SUMMARY")
    print(f"{'=' * 60}")

    # -- Structured Extraction Accuracy --
    print(f"\n📊 Structured Extraction Accuracy")
    print(f"  Total Fields Evaluated: {total_fields}")
    print(f"  Correct:                {total_correct}")
    print(f"  Accuracy:               {overall_accuracy * 100:.1f}%")

    # -- Hallucination Rate --
    print(f"\n🔍 Hallucination Rate")
    print(f"  Incidents with hallucinations: {incidents_with_hallucinations} / {len(ok_results)}")

    # -- Brand Risk --
    print(f"\n🛡️  Brand Risk")
    print(f"  Average risk score: {avg_risk_label}")
    print(f"  Total flags across incidents: {total_flags}")

    # -- Average Latency --
    print(f"\n⏱️  Average Latency")
    print(f"  Average total pipeline time: {avg_latency:.2f}s")

    # -- Final Verdict --
    passed = overall_accuracy >= 0.9 and incidents_with_hallucinations == 0

    print(f"\nFinal Verdict:")
    if passed:
        print(f"  ✅ EVAL PASSED")
        print(f"     Accuracy ≥ 90% and 0 hallucinated incidents")
    else:
        print(f"  ❌ EVAL FAILED")
        if overall_accuracy < 0.9:
            print(f"     Accuracy {overall_accuracy * 100:.1f}% < 90% target")
        if incidents_with_hallucinations > 0:
            print(f"     {incidents_with_hallucinations} incident(s) with hallucinations")


# ---------------------------------------------------------------------------
# Run all evals
# ---------------------------------------------------------------------------

def run_all_evals(
    model_name: str = "gpt-4.1",
    only: str | None = None,
) -> List[Dict[str, Any]]:
    """
    Iterate over golden incidents, run the pipeline, and collect results.
    """
    client = LLMClient(model_name=model_name)
    pipeline = IncidentLLMPipeline(client)

    incidents = list_golden_incidents(GOLDEN_DIR)
    if not incidents:
        print(f"❌ No golden incidents found in {GOLDEN_DIR.resolve()}")
        return []

    if only:
        incidents = [d for d in incidents if d.name == only]
        if not incidents:
            print(f"❌ Golden incident '{only}' not found.")
            return []

    print(f"\n{'=' * 60}")
    print(f"  Offline Eval: {len(incidents)} golden incident(s) | model={model_name}")
    print(f"{'=' * 60}")

    results: List[Dict[str, Any]] = []

    for incident_dir in incidents:
        print(f"\n⏳ Running pipeline on {incident_dir.name}...")
        result = evaluate_incident(incident_dir, pipeline)
        results.append(result)

        if result["status"] == "SKIP":
            print(f"  ⏭️  SKIPPED: {result['reason']}")
            continue

        print_incident_report(result)

    # Print aggregate summary
    print_summary_report(results)

    # Save detailed results
    output_path = Path("eval_results.json")
    with output_path.open("w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n📄 Detailed results saved to {output_path}")

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run offline golden-set evaluation for Incident Comms Copilot"
    )
    parser.add_argument(
        "--model", default="gpt-4.1",
        help="OpenAI model name (default: gpt-4.1)"
    )
    parser.add_argument(
        "--only", default=None,
        help="Run only a specific golden incident (e.g., G1)"
    )
    args = parser.parse_args()

    results = run_all_evals(model_name=args.model, only=args.only)

    # Exit with non-zero if eval failed
    ok_results = [r for r in results if r["status"] == "OK"]
    if ok_results:
        total_correct = sum(r["correct"] for r in ok_results)
        total_fields = sum(r["total"] for r in ok_results)
        hallucinations = sum(1 for r in ok_results if r["hallucinations"])
        accuracy = total_correct / total_fields if total_fields > 0 else 0.0

        if accuracy < 0.9 or hallucinations > 0:
            sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
