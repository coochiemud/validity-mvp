# analyzer.py
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI

from prompts import build_prompt

load_dotenv()


@dataclass
class ChunkResult:
    ok: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ValidityAnalyzer:
    """
    Core reasoning analyzer.
    Keep this module PURE (no Streamlit, no caching, no side effects).
    """

    def __init__(self, model: Optional[str] = None):
        self.client = OpenAI()
        self.model = model or os.getenv("MODEL_NAME", "gpt-4o")
        self.max_chunk_chars = 12_000

    # -----------------------------
    # Public API
    # -----------------------------

    def analyze(self, document_text: str) -> Dict[str, Any]:
        start = time.time()

        chunks = self._chunk_text(document_text)
        results: List[ChunkResult] = []

        for chunk in chunks:
            results.append(self._analyze_chunk(chunk))

        merged = self._merge_results(results)

        return {
            "success": merged.get("success", False),
            "analysis": merged.get("analysis"),
            "error": merged.get("error"),
            "chunks_analyzed": len(chunks),
            "chunks_succeeded": sum(1 for r in results if r.ok),
            "chunks_failed": sum(1 for r in results if not r.ok),
            "analysis_time": round(time.time() - start, 2),
        }

    def format_output(self, result: Dict[str, Any]) -> str:
        """Human-readable report"""
        return json.dumps(result, indent=2)

    # -----------------------------
    # Internal helpers
    # -----------------------------

    def _analyze_chunk(self, text: str) -> ChunkResult:
        try:
            prompt = build_prompt(text)

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a reasoning quality auditor. "
                            "Return ONLY valid JSON. No markdown. No commentary."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                response_format={"type": "json_object"},  # strict JSON
            )

            raw = response.choices[0].message.content or ""

            # Primary: strict parse
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                # Fallback: extract first {...} block if model emits extra text
                start = raw.find("{")
                end = raw.rfind("}")
                if start == -1 or end == -1 or end <= start:
                    raise ValueError(
                        f"Model did not return JSON. Raw starts: {raw[:200]!r}"
                    )
                data = json.loads(raw[start : end + 1])

            return ChunkResult(ok=True, data=data)

        except Exception as e:
            return ChunkResult(ok=False, error=repr(e))

    def _merge_results(self, results: List[ChunkResult]) -> Dict[str, Any]:
        failures: List[Dict[str, Any]] = []
        scores: List[int] = []
        risks: List[str] = []

        for r in results:
            if not r.ok or not r.data:
                continue

            s = r.data.get("reasoning_score")
            if isinstance(s, (int, float)):
                scores.append(int(s))

            risks.append(str(r.data.get("decision_risk", "low")).lower())

            fd = r.data.get("failures_detected", [])
            if isinstance(fd, list):
                failures.extend(fd)

        if not scores:
            first_err = next(
                (r.error for r in results if r.error),
                "All chunks failed (no error captured).",
            )
            return {"success": False, "error": first_err}

        avg_score = round(sum(scores) / len(scores))
        highest_risk = self._max_risk(risks)

        return {
            "success": True,
            "analysis": {
                "reasoning_score": avg_score,
                "decision_risk": highest_risk,
                "failures_detected": failures[:25],
                "total_failures_detected": len(failures),
                "top_risk_flags": self._top_risk_flags(failures),
            },
        }

    def _chunk_text(self, text: str) -> List[str]:
        if len(text) <= self.max_chunk_chars:
            return [text]

        chunks: List[str] = []
        start = 0

        while start < len(text):
            end = start + self.max_chunk_chars
            chunks.append(text[start:end])
            start = end

        return chunks

    @staticmethod
    def _max_risk(risks: List[str]) -> str:
        order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        best = "low"
        best_val = -1
        for r in risks:
            val = order.get(str(r).strip().lower(), 0)
            if val > best_val:
                best_val = val
                best = str(r).strip().lower()
        return best

    @staticmethod
    def _top_risk_flags(failures: List[Dict[str, Any]]) -> List[str]:
        flags: List[str] = []
        for f in failures:
            t = f.get("type")
            if isinstance(t, str) and t:
                flags.append(t)

        seen = set()
        out: List[str] = []
        for x in flags:
            if x not in seen:
                seen.add(x)
                out.append(x)
            if len(out) >= 5:
                break
        return out
