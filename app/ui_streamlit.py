# app/ui_streamlit.py
"""
Streamlit UI for the Incident Communications Copilot.

Run with:  streamlit run main.py
"""
from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path

import streamlit as st

from .timeline_builder import build_timeline_from_bundle
from .llm_pipeline import LLMClient, IncidentLLMPipeline
from .eval_utils import compare_facts_to_expected, check_hallucinations, GOLDEN_EXPECTED


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_zip_to_tmpdir(uploaded_file) -> Path:
    """Save the uploaded zip to a temp dir, extract it, and return the bundle root."""
    tmp = Path(tempfile.mkdtemp())
    zip_path = tmp / "bundle.zip"
    zip_path.write_bytes(uploaded_file.getvalue())

    extract_dir = tmp / "bundle"
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)

    # The zip may contain a top-level folder; find the dir with the json files.
    candidates = [
        d
        for d in extract_dir.rglob("pagerduty_incident.json")
    ]
    if candidates:
        return candidates[0].parent
    return extract_dir


def _render_risk_badge(risk_score: str):
    """Render a colored badge for the brand risk score."""
    color_map = {"low": "🟢", "medium": "🟡", "high": "🔴"}
    icon = color_map.get(risk_score, "⚪")
    st.markdown(f"### {icon} Brand Risk Score: **{risk_score.upper()}**")


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

def run_app():
    st.set_page_config(
        page_title="Incident Comms Copilot",
        page_icon="🧠",
        layout="wide",
    )

    # ---- Sidebar ----
    with st.sidebar:
        st.image("https://img.icons8.com/fluency/96/bot.png", width=64)
        st.title("⚙️ Settings")
        model_name = st.text_input("OpenAI model", value="gpt-4.1")
        st.markdown("---")
        st.caption("Abnormal Security – AI Incident Comms Copilot")

    # ---- Header ----
    st.title("🧠 Incident Communications Copilot")
    st.markdown(
        "Upload an incident bundle → get a structured summary, "
        "customer-ready draft, and brand risk flags in seconds."
    )

    # ---- Upload + Stage ----
    col_upload, col_stage = st.columns([3, 1])
    with col_upload:
        uploaded_file = st.file_uploader(
            "Upload incident bundle (.zip)",
            type=["zip"],
            help="Zip containing pagerduty_incident.json, prometheus_metrics.json, "
            "cloudwatch_logs.json, github_deployments.json, incident_context.txt",
        )
    with col_stage:
        stage = st.selectbox(
            "Incident stage",
            options=["initial", "identified", "monitoring", "resolved"],
            index=3,  # default to 'resolved' for the sample data
        )

    if uploaded_file is None:
        st.info("👆 Upload the provided incident bundle (.zip) to get started.")
        return

    # ---- Generate ----
    if st.button("🚀 Generate Draft", type="primary", use_container_width=True):
        with st.status("Running AI pipeline…", expanded=True) as status:
            # Step 0: Extract
            st.write("📦 Extracting bundle…")
            bundle_dir = _extract_zip_to_tmpdir(uploaded_file)

            # Step 1: Build timeline
            st.write("🔗 Building unified incident timeline…")
            timeline = build_timeline_from_bundle(bundle_dir)
            st.write(
                f"  ✅ Timeline built: **{len(timeline.events)} events**, "
                f"service=`{timeline.service}`, severity=`{timeline.severity}`"
            )

            # Step 2: LLM Stage 1 – Structured extraction
            st.write("🤖 Stage 1 / 3 — Extracting structured facts…")
            client = LLMClient(model_name=model_name)
            pipeline = IncidentLLMPipeline(client)
            facts = pipeline.extract_facts(timeline)

            # Step 3: LLM Stage 2 – Generation
            st.write("✍️  Stage 2 / 3 — Generating messages…")
            messages = pipeline.generate_messages(facts, stage=stage)

            # Step 4: LLM Stage 3 – Brand risk scan
            st.write("🛡️  Stage 3 / 3 — Scanning for brand risks…")
            risk = pipeline.scan_risk(messages.external_update)

            status.update(label="✅ Pipeline complete!", state="complete")

        # ---- Store results in session state for editing ----
        st.session_state["facts"] = facts
        st.session_state["messages"] = messages
        st.session_state["risk"] = risk
        st.session_state["timeline"] = timeline

        # Clean up temp dir
        try:
            shutil.rmtree(bundle_dir.parent.parent, ignore_errors=True)
        except Exception:
            pass

    # ---- Display results ----
    if "facts" not in st.session_state:
        return

    facts = st.session_state["facts"]
    messages = st.session_state["messages"]
    risk = st.session_state["risk"]
    timeline = st.session_state["timeline"]

    st.markdown("---")

    # ---- Split panel ----
    left, right = st.columns(2)

    with left:
        st.subheader("📋 Internal Summary")
        st.text_area(
            "Internal (editable)",
            value=messages.internal_summary,
            height=350,
            key="internal_edit",
        )

        with st.expander("🔍 Extracted Incident Facts (JSON)"):
            import json
            st.json(json.loads(json.dumps(facts.__dict__, default=str)))

    with right:
        st.subheader("📣 Customer-Facing Draft")
        _render_risk_badge(risk.risk_score)

        external_text = st.text_area(
            "External update (editable)",
            value=messages.external_update,
            height=350,
            key="external_edit",
        )

        if risk.flags:
            st.warning(f"⚠️ {len(risk.flags)} brand risk flag(s) detected:")
            for flag in risk.flags:
                st.markdown(
                    f"- **`{flag.text}`** — _{flag.category}_ — {flag.reason}"
                )

        if risk.recommendations:
            st.info(f"💡 **Recommendation:** {risk.recommendations}")

        st.button("📋 Copy to clipboard", help="Copy the external update text")

    # ---- Timeline viewer ----
    with st.expander("🕐 Unified Incident Timeline"):
        for event in timeline.events:
            ts_str = event.timestamp.strftime("%H:%M:%S UTC")
            icon = {
                "alert": "🚨",
                "metric_spike": "📈",
                "error_burst": "💥",
                "deployment": "🚀",
                "slack_message": "💬",
                "note": "📝",
            }.get(event.type, "•")
            st.markdown(f"`{ts_str}` {icon} **[{event.source}]** {event.summary}")

    # ---- Bottom tabs: Brand Risk | Eval (internal) ----
    st.markdown("---")
    tab_risk, tab_eval = st.tabs(["🛡️ Brand Risk Details", "🧪 Eval (internal)"])

    # ---- Brand Risk tab ----
    with tab_risk:
        _render_risk_badge(risk.risk_score)

        col_score, col_flags = st.columns([1, 2])

        with col_score:
            st.metric("Risk Score", risk.risk_score.upper())
            st.metric("Flags Detected", len(risk.flags))

        with col_flags:
            if risk.flags:
                st.markdown("#### Flagged Phrases")
                for i, flag in enumerate(risk.flags, 1):
                    with st.container():
                        st.markdown(
                            f"**{i}. `{flag.text}`**  \n"
                            f"Category: _{flag.category}_  \n"
                            f"Reason: {flag.reason}"
                        )
                        st.divider()
            else:
                st.success("✅ No brand risk flags — the external message looks clean.")

        if risk.recommendations:
            st.info(f"💡 **Recommendations:** {risk.recommendations}")

        st.markdown("#### Full External Message (scanned)")
        st.code(messages.external_update, language=None)

    # ---- Eval tab ----
    with tab_eval:
        st.caption("🔒 Internal use — compare pipeline output against golden expected values.")

        correct, total, mismatches = compare_facts_to_expected(
            facts, GOLDEN_EXPECTED
        )
        accuracy = correct / total if total > 0 else 0.0

        e_col1, e_col2, e_col3 = st.columns(3)
        with e_col1:
            st.metric("Field Accuracy", f"{correct}/{total}")
        with e_col2:
            st.metric("Accuracy %", f"{accuracy * 100:.0f}%")
        with e_col3:
            hallucinations = check_hallucinations(facts, GOLDEN_EXPECTED)
            st.metric("Hallucinations", len(hallucinations))

        if mismatches:
            st.warning(f"❌ {len(mismatches)} field mismatch(es):")
            for m in mismatches:
                st.markdown(f"- {m}")
        else:
            st.success("All checked fields match the golden expected values! ✅")

        if hallucinations:
            st.error("🚨 Hallucinations detected:")
            for h in hallucinations:
                st.markdown(f"- {h}")
        else:
            st.success("No hallucinations — output is consistent with golden data. ✅")

        # Verdict
        if not mismatches and not hallucinations:
            st.markdown("### 🟢 Verdict: PASSED")
        elif hallucinations:
            st.markdown("### 🔴 Verdict: FAILED")
        else:
            st.markdown("### 🟡 Verdict: PARTIAL")
