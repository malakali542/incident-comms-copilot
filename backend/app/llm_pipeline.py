# app/llm_pipeline.py
from __future__ import annotations

import json
import os
from typing import Any, Dict

from openai import OpenAI

from .models import (
    IncidentTimeline,
    IncidentFacts,
    GeneratedMessages,
    RiskFlag,
    RiskScanResult,
)
from .llm_prompts import (
    STRUCTURED_EXTRACTION_SYSTEM_PROMPT,
    GENERATION_SYSTEM_PROMPT,
    BRAND_RISK_SCAN_SYSTEM_PROMPT,
)


class LLMClient:
    """
    Thin wrapper around the OpenAI chat completions API.
    Set OPENAI_API_KEY in your environment.
    """

    def __init__(self, model_name: str = "gpt-4.1"):
        self.model_name = model_name
        self.client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

    def structured_completion(
        self, system_prompt: str, user_content: str
    ) -> Dict[str, Any]:
        """
        Call the LLM, requesting JSON output, and parse the response.
        """
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)


class IncidentLLMPipeline:
    """
    Orchestrates the 3-stage LLM pipeline:
    1) Structured extraction  – raw timeline → IncidentFacts JSON
    2) Template generation    – facts + stage → internal summary + external update
    3) Brand risk & compliance scan – external update → risk flags
    """

    def __init__(self, client: LLMClient):
        self.client = client

    # ------------------------------------------------------------------
    # Stage 1: Structured Extraction
    # ------------------------------------------------------------------

    def extract_facts(self, timeline: IncidentTimeline) -> IncidentFacts:
        """
        Run Model 1: convert the unified timeline to structured incident facts.
        """
        timeline_payload = self._timeline_to_model_payload(timeline)
        raw = self.client.structured_completion(
            STRUCTURED_EXTRACTION_SYSTEM_PROMPT,
            user_content=timeline_payload,
        )
        return IncidentFacts(**raw)

    # ------------------------------------------------------------------
    # Stage 2: Template-Based Generation
    # ------------------------------------------------------------------

    def generate_messages(
        self, facts: IncidentFacts, stage: str
    ) -> GeneratedMessages:
        """
        Run Model 2: take structured facts + stage and generate
        internal + external messages.
        """
        payload = json.dumps(
            {
                "incident_facts": facts.__dict__,
                "stage": stage,
            },
            default=str,
        )
        raw = self.client.structured_completion(
            GENERATION_SYSTEM_PROMPT,
            user_content=payload,
        )
        return GeneratedMessages(**raw)

    # ------------------------------------------------------------------
    # Stage 3: Brand Risk & Compliance Scan
    # ------------------------------------------------------------------

    def scan_risk(self, external_update: str) -> RiskScanResult:
        """
        Run Model 3: brand risk scan — flag risky phrases in external message.
        """
        raw = self.client.structured_completion(
            BRAND_RISK_SCAN_SYSTEM_PROMPT,
            user_content=external_update,
        )
        flags = [
            RiskFlag(
                text=f["text"],
                category=f["category"],
                reason=f["reason"],
            )
            for f in raw.get("flags", [])
        ]
        return RiskScanResult(
            risk_score=raw["risk_score"],
            flags=flags,
            recommendations=raw.get("recommendations", ""),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _timeline_to_model_payload(self, timeline: IncidentTimeline) -> str:
        """
        Convert the IncidentTimeline into a compact JSON string for the LLM.
        """
        payload = {
            "incident_id": timeline.incident_id,
            "service": timeline.service,
            "severity": timeline.severity,
            "window_start": timeline.window_start.isoformat(),
            "window_end": (
                timeline.window_end.isoformat() if timeline.window_end else None
            ),
            "events": [
                {
                    "timestamp": e.timestamp.isoformat(),
                    "type": e.type,
                    "source": e.source,
                    "summary": e.summary,
                    "structured_data": e.structured_data,
                }
                for e in timeline.events
            ],
        }
        return json.dumps(payload, indent=2)
