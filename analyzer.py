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
    This module must remain PURE (no Streamlit, no caching, no side effects).
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
            "success": merged["success"],
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
                    {"role": "system", "content": "You are a reasoning quality auditor."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
            )

            raw = response.choices[0].message.content
            data = json.loads(raw)

            return ChunkResult(ok=True, data=data)

        except Exception as e:
            return ChunkResult(ok=False, error=str(e))

    def _merge_results(self, results: List[ChunkResult]) -> Dict[str, Any]:
        failures: List[Dict[str, Any]] = []
        scores: List[int] = []
        risks: List[str] = []

        for r in results:
            if not r.ok or not r.data:
                continue

            scores.append(r.data.get("reasoning_score", 0))
            risks.append(r.data.get("decision_risk", "low"))

            failures.extend(r.data.get("failures_detected", []))

        if not scores:
            return {
                "success": False,
                "error": "All chunks failed to analyze",
            }

        avg_score = round(sum(scores) / len(scores))

        highest_risk = self._max_risk(risks)

        return {
            "success": True,
            "analysis": {
                "reasoning_score": avg_score,
                "decision_risk": highest_risk,
                "failures_detected": failures[:25],
                "total_failures_detected": len(failures),
            },
        }

    def _chunk_text(self, text: str) -> List[str]:
        if len(text) <= self.max_chunk_chars:
            return [text]

        chunks = []
        start = 0

        while start < len(text):
            end = start + self.max_chunk_chars
            chunks.append(text[start:end])
            start = end

        return chunks

    @staticmethod
    def _max_risk(risks: List[str]) -> str:
        order = ["low", "medium", "high", "critical"]
        return max(risks, key=lambda r: order.index(r) if r in order else 0)
