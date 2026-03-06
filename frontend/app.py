"""
Incident Communications Copilot – Streamlit frontend.

Deploy on Streamlit Community Cloud.
Set BACKEND_URL in st.secrets (or as an environment variable) to point at the
Render-hosted API, e.g.:
    BACKEND_URL = "https://your-app.onrender.com"
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

import requests
import streamlit as st


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

try:
    DEFAULT_BACKEND_URL = st.secrets.get("BACKEND_URL") or os.environ.get("BACKEND_URL", "http://localhost:8000")
except Exception:
    DEFAULT_BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_bundle_from_zip(uploaded_file) -> dict:
    """Extract the zip and read each file's contents into a dict payload."""
    tmp = Path(tempfile.mkdtemp())
    zip_path = tmp / "bundle.zip"
    zip_path.write_bytes(uploaded_file.getvalue())

    extract_dir = tmp / "bundle"
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)

    candidates = list(extract_dir.rglob("pagerduty_incident.json"))
    bundle_dir = candidates[0].parent if candidates else extract_dir

    payload: dict = {}

    pd_path = bundle_dir / "pagerduty_incident.json"
    if pd_path.exists():
        payload["pagerduty_incident"] = json.loads(pd_path.read_text())

    for key, filename in [
        ("prometheus_metrics", "prometheus_metrics.json"),
        ("cloudwatch_logs", "cloudwatch_logs.json"),
        ("github_deployments", "github_deployments.json"),
    ]:
        p = bundle_dir / filename
        if p.exists():
            payload[key] = json.loads(p.read_text())

    slack_path = bundle_dir / "incident_context.txt"
    if slack_path.exists():
        payload["incident_context"] = slack_path.read_text()

    shutil.rmtree(tmp, ignore_errors=True)
    return payload


def _render_risk_badge(risk_score: str):
    color_map = {"low": "🟢", "medium": "🟡", "high": "🔴"}
    icon = color_map.get(risk_score, "⚪")
    st.markdown(f"### {icon} Brand Risk Score: **{risk_score.upper()}**")


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Incident Comms",
    page_icon="🧠",
    layout="wide",
)

# ---- Sidebar ----
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/bot.png", width=64)
    st.title("⚙️ Settings")
    api_url = st.text_input("API URL", value=DEFAULT_BACKEND_URL)
    model_name = st.text_input("OpenAI model", value="gpt-4.1")
    st.markdown("---")
    st.caption("Abnormal Security – AI Incident Comms")

# ---- Header ----
st.title("🧠 Incident Communications")
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
        index=3,
    )

if uploaded_file is None:
    st.info("👆 Upload the provided incident bundle (.zip) to get started.")
    st.stop()

# ---- Generate ----
if st.button("🚀 Generate Draft", type="primary", use_container_width=True):
    with st.status("Running AI pipeline…", expanded=True) as status:
        st.write("📦 Extracting bundle…")
        payload = _read_bundle_from_zip(uploaded_file)

        st.write("🤖 Calling API — running 3-stage LLM pipeline…")
        try:
            response = requests.post(
                f"{api_url}/generate",
                json={**payload, "stage": stage, "model": model_name},
                timeout=120,
            )
            response.raise_for_status()
        except requests.exceptions.ConnectionError:
            st.error(
                f"Could not connect to the API at `{api_url}`. "
                "Check that the backend is running and the API URL is correct."
            )
            status.update(label="❌ Connection failed", state="error")
            st.stop()
        except requests.exceptions.HTTPError as exc:
            st.error(f"API error {exc.response.status_code}: {exc.response.text}")
            status.update(label="❌ API error", state="error")
            st.stop()

        data = response.json()
        status.update(label="✅ Pipeline complete!", state="complete")

    st.session_state["data"] = data

# ---- Display results ----
if "data" not in st.session_state:
    st.stop()

data = st.session_state["data"]

st.markdown("---")

# ---- Split panel ----
left, right = st.columns(2)

with left:
    st.subheader("📋 Internal Summary")
    st.text_area(
        "Internal (editable)",
        value=data["internal_summary"],
        height=350,
        key="internal_edit",
    )

    with st.expander("🔍 Extracted Incident Facts (JSON)"):
        st.json(data["facts"])

with right:
    st.subheader("📣 Customer-Facing Draft")
    _render_risk_badge(data["risk_score"])

    st.text_area(
        "External update (editable)",
        value=data["external_update"],
        height=350,
        key="external_edit",
    )

    flags = data["flags"]
    if flags:
        st.warning(f"⚠️ {len(flags)} brand risk flag(s) detected:")
        for flag in flags:
            st.markdown(
                f"- **`{flag['text']}`** — _{flag['category']}_ — {flag['reason']}"
            )

    if data["recommendations"]:
        st.info(f"💡 **Recommendation:** {data['recommendations']}")

    st.button("📋 Copy to clipboard", help="Copy the external update text")

# ---- Timeline viewer ----
with st.expander("🕐 Unified Incident Timeline"):
    icon_map = {
        "alert": "🚨",
        "metric_spike": "📈",
        "error_burst": "💥",
        "deployment": "🚀",
        "slack_message": "💬",
        "note": "📝",
    }
    for event in data.get("timeline_events", []):
        icon = icon_map.get(event["type"], "•")
        st.markdown(f"`{event['timestamp']}` {icon} **[{event['source']}]** {event['summary']}")

# ---- Bottom tab: Brand Risk ----
st.markdown("---")
st.subheader("🛡️ Brand Risk Details")

_render_risk_badge(data["risk_score"])

col_score, col_flags = st.columns([1, 2])
with col_score:
    st.metric("Risk Score", data["risk_score"].upper())
    st.metric("Flags Detected", len(flags))

with col_flags:
    if flags:
        st.markdown("#### Flagged Phrases")
        for i, flag in enumerate(flags, 1):
            with st.container():
                st.markdown(
                    f"**{i}. `{flag['text']}`**  \n"
                    f"Category: _{flag['category']}_  \n"
                    f"Reason: {flag['reason']}"
                )
                st.divider()
    else:
        st.success("✅ No brand risk flags — the external message looks clean.")

if data["recommendations"]:
    st.info(f"💡 **Recommendations:** {data['recommendations']}")

st.markdown("#### Full External Message (scanned)")
st.code(data["external_update"], language=None)
