# analyzer.py
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI

from prompts import build_prompt

# Updated failure library supports both old + new names
from failure_library import (
    ALLOWED_MICRO_FAILURE_TYPES,
    ALLOWED_STRUCTURAL_FAILURE_TYPES,
    MICRO_REASONING_FAILURES,
    STRUCTURAL_REASONING_FAILURES,
)

load_dotenv()


# ---------------------------
# Helpers
# ---------------------------

SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
CONFIDENCE_RANK = {"low": 1, "medium": 2, "high": 3}


def _best_by_rank(a: str, b: str, rank_map: dict) -> str:
    a = (a or "").lower()
    b = (b or "").lower()
    if rank_map.get(b, 0) > rank_map.get(a, 0):
        return b
    return a or b


def _dedupe_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in items or []:
        if not x:
            continue
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def normalize_schema(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Backwards-compatible adapter:
    - Old schema: failures_detected[]
    - New schema: micro_failures[], structural_failures[]
    """
    if "micro_failures" not in data:
        data["micro_failures"] = data.get("failures_detected", [])
    if "structural_failures" not in data:
        data["structural_failures"] = []
    return data


def validate_micro_failures(micro: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for f in micro or []:
        ftype = (f.get("type") or "").strip()
        if ftype not in set(ALLOWED_MICRO_FAILURE_TYPES):
            # Drop unknown types to avoid UI crashes / schema drift
            continue
        out.append(
            {
                "type": ftype,
                "location": f.get("location") or "",
                "explanation": f.get("explanation") or "",
            }
        )
    return out


def validate_structural_failures(structural: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    allowed = set(ALLOWED_STRUCTURAL_FAILURE_TYPES)
    out = []
    for f in structural or []:
        ftype = (f.get("type") or "").strip()
        if ftype not in allowed:
            continue

        severity = (f.get("severity") or "medium").lower()
        if severity not in ("low", "medium", "high"):
            severity = "medium"

        confidence = (f.get("confidence") or "medium").lower()
        if confidence not in ("low", "medium", "high"):
            confidence = "medium"

        evidence = f.get("evidence") or []
        if not isinstance(evidence, list):
            evidence = []
        evidence = [str(x) for x in evidence if x]
        evidence = _dedupe_preserve_order(evidence)[:3]

        out.append(
            {
                "type": ftype,
                "severity": severity,
                "confidence": confidence,
                "why_it_matters": f.get("why_it_matters") or "",
                "evidence": evidence,
                "location_hint": f.get("location_hint") or "",
                "fix": f.get("fix") or "",
            }
        )
    return out


def merge_structural_failures(all_structural: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Dedupe structural failures across chunks.
    Key = (type, location_hint) if location_hint exists else (type, "")
    Merge severity/confidence upward; merge evidence (max 3).
    """
    merged: Dict[tuple, Dict[str, Any]] = {}

    for f in all_structural or []:
        ftype = (f.get("type") or "").strip()
        if not ftype:
            continue

        loc = (f.get("location_hint") or "").strip()
        key = (ftype, loc) if loc else (ftype, "")

        if key not in merged:
            merged[key] = {
                "type": ftype,
                "severity": (f.get("severity") or "medium").lower(),
                "confidence": (f.get("confidence") or "medium").lower(),
                "why_it_matters": f.get("why_it_matters") or "",
                "evidence": _dedupe_preserve_order(list(f.get("evidence") or []))[:3],
                "location_hint": loc,
                "fix": f.get("fix") or "",
            }
            continue

        cur = merged[key]
        cur["severity"] = _best_by_rank(cur["severity"], f.get("severity"), SEVERITY_RANK)
        cur["confidence"] = _best_by_rank(cur["confidence"], f.get("confidence"), CONFIDENCE_RANK)

        if (not cur.get("why_it_matters")) and f.get("why_it_matters"):
            cur["why_it_matters"] = f.get("why_it_matters")
        if (not cur.get("fix")) and f.get("fix"):
            cur["fix"] = f.get("fix")

        ev = cur.get("evidence") or []
        more = f.get("evidence") or []
        merged_ev = _dedupe_preserve_order([*(ev or []), *(more or [])])[:3]
        cur["evidence"] = merged_ev

    out = list(merged.values())
    out.sort(key=lambda x: (-SEVERITY_RANK.get(x["severity"], 0), x["type"]))
    return out


def decision_risk_from_failures(micro: List[Dict[str, Any]], structural: List[Dict[str, Any]]) -> str:
    """
    Conservative mapping for backwards compatibility with your UI.
    """
    worst = 0

    # Micro uses library severities (including critical)
    for f in micro or []:
        meta = MICRO_REASONING_FAILURES.get(f["type"], {})
        sev = (meta.get("severity") or "medium").lower()
        worst = max(worst, SEVERITY_RANK.get(sev, 2))

    # Structural uses low/medium/high
    for f in structural or []:
        sev = (f.get("severity") or "medium").lower()
        worst = max(worst, SEVERITY_RANK.get(sev, 2))

    if worst >= 4:
        return "high"
    if worst == 3:
        return "medium"
    return "low"


def reasoning_score_from_risk(risk: str) -> int:
    # Keep your existing 1–5-ish feel (higher = better)
    risk = (risk or "").lower()
    if risk == "high":
        return 2
    if risk == "medium":
        return 3
    return 4


def top_risk_flags(micro: List[Dict[str, Any]], structural: List[Dict[str, Any]], k: int = 3) -> List[str]:
    counts: Dict[str, int] = {}
    for f in micro or []:
        counts[f["type"]] = counts.get(f["type"], 0) + 1
    for f in structural or []:
        counts[f["type"]] = counts.get(f["type"], 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [name for name, _ in ranked[:k]]


def chunk_text(text: str, max_chars: int = 80_000, overlap: int = 1_500) -> List[str]:
    """
    Chunk by characters with overlap. Keeps it simple and robust.
    """
    text = text or ""
    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(0, end - overlap)
    return chunks


def extract_json(text: str) -> str:
    """
    Attempts to extract the first JSON object from a model response.
    Works around occasional stray text.
    """
    text = text.strip()
    # If already looks like JSON
    if text.startswith("{") and text.endswith("}"):
        return text

    # Try to find a JSON object region
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in model response.")
    return m.group(0)


# ---------------------------
# Data container
# ---------------------------

@dataclass
class ChunkResult:
    ok: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# ---------------------------
# Analyzer
# ---------------------------

class ValidityAnalyzer:
    """
    ValidityAnalyzer
    - Calls OpenAI with a strict JSON response format expectation
    - Splits long documents into chunks
    - Merges chunk-level analyses into one combined report
    - Returns a stable result object expected by app.py (backwards compatible)
    """

    def __init__(self):
        api_key = None
        model_name = "gpt-4o"

        try:
            import streamlit as st  # type: ignore
            api_key = st.secrets.get("OPENAI_API_KEY")
            model_name = st.secrets.get("MODEL_NAME", "gpt-4o")
        except Exception:
            api_key = os.getenv("OPENAI_API_KEY")
            model_name = os.getenv("MODEL_NAME", "gpt-4o")

        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not found in Streamlit secrets or environment variables")

        self.client = OpenAI(api_key=api_key)
        self.model = model_name

        self.max_chars = int(os.getenv("MAX_CHARS", "80000"))
        self.overlap = int(os.getenv("CHUNK_OVERLAP", "1500"))
        self.temperature = float(os.getenv("TEMPERATURE", "0"))

    def _call_model(self, prompt: str) -> str:
        """
        Uses Responses API if available; falls back to chat.completions.
        """
        # Newer OpenAI python SDK supports client.responses.create
        if hasattr(self.client, "responses"):
            resp = self.client.responses.create(
                model=self.model,
                input=prompt,
                temperature=self.temperature,
            )
            # Extract text
            out_text = ""
            for item in getattr(resp, "output", []) or []:
                for c in getattr(item, "content", []) or []:
                    if getattr(c, "type", None) == "output_text":
                        out_text += getattr(c, "text", "") or ""
            return out_text.strip()

        # Fallback
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.temperature,
        )
        return (resp.choices[0].message.content or "").strip()

    def analyze(self, document_text: str) -> Dict[str, Any]:
        t0 = time.time()

        chunks = chunk_text(document_text, max_chars=self.max_chars, overlap=self.overlap)

        chunk_results: List[ChunkResult] = []
        for chunk in chunks:
            prompt = build_prompt(chunk)

            try:
                raw = self._call_model(prompt)
                json_str = extract_json(raw)
                data = json.loads(json_str)
                data = normalize_schema(data)

                # Validate + sanitize
                data["micro_failures"] = validate_micro_failures(data.get("micro_failures", []))
                data["structural_failures"] = validate_structural_failures(data.get("structural_failures", []))

                chunk_results.append(ChunkResult(ok=True, data=data))
            except Exception as e:
                chunk_results.append(ChunkResult(ok=False, error=str(e)))

        succeeded = [cr for cr in chunk_results if cr.ok and cr.data]
        failed = [cr for cr in chunk_results if not cr.ok]

        if not succeeded:
            return {
                "success": False,
                "analysis": None,
                "error": failed[0].error if failed else "All chunks failed",
                "chunks_analyzed": len(chunks),
                "chunks_succeeded": 0,
                "chunks_failed": len(failed),
                "analysis_time": round(time.time() - t0, 2),
            }

        # ---------------------------
        # Merge chunk-level results
        # ---------------------------
        all_micro: List[Dict[str, Any]] = []
        all_structural: List[Dict[str, Any]] = []

        # Keep a representative thesis/summary from the first successful chunk
        representative = succeeded[0].data or {}

        for cr in succeeded:
            data = cr.data or {}
            all_micro.extend(data.get("micro_failures", []))
            all_structural.extend(data.get("structural_failures", []))

        merged_structural = merge_structural_failures(all_structural)

        # Backwards-compatible fields your UI likely expects
        decision_risk = decision_risk_from_failures(all_micro, merged_structural)
        reasoning_score = reasoning_score_from_risk(decision_risk)

        combined = {
            # New schema (preferred)
            "thesis": representative.get("thesis", {"statement": "", "explicitness": "unclear"}),
            "claims": representative.get("claims", []),
            "logical_chain": representative.get("logical_chain", {"steps": [], "conclusion": "", "breaks": []}),
            "micro_failures": all_micro,
            "structural_failures": merged_structural,
            "counterfactual_tests": representative.get("counterfactual_tests", []),
            "assumption_sensitivity": representative.get("assumption_sensitivity", []),
            "strengths_detected": representative.get("strengths_detected", []),
            "overall_assessment": representative.get(
                "overall_assessment",
                {"confidence": "medium", "summary": ""},
            ),

            # Legacy schema (kept so app.py doesn’t break)
            "failures_detected": all_micro,  # legacy name
            "decision_risk": decision_risk,
            "reasoning_score": reasoning_score,
            "total_failures_detected": len(all_micro) + len(merged_structural),
            "top_risk_flags": top_risk_flags(all_micro, merged_structural, k=3),
        }

        return {
            "success": True,
            "analysis": combined,
            "error": None,
            "chunks_analyzed": len(chunks),
            "chunks_succeeded": len(succeeded),
            "chunks_failed": len(failed),
            "analysis_time": round(time.time() - t0, 2),
        }
