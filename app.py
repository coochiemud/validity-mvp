# analyzer.py
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI
from dotenv import load_dotenv

from prompts import build_prompt

load_dotenv()


@dataclass
class ChunkResult:
    ok: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ValidityAnalyzer:
    """
    ValidityAnalyzer
    - Calls OpenAI with a strict JSON response format
    - Splits long documents into chunks
    - Merges chunk-level analyses into one combined report
    - Returns a stable result object expected by app.py
    """

    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY not found. Set it as an environment variable or Streamlit secret."
            )

        self.client = OpenAI(api_key=api_key)

        # Let Streamlit Secrets / env override model name
        self.model = os.getenv("MODEL_NAME", "gpt-4o")

        # Chunking + safety
        self.MAX_DOC_CHARS = 80_000          # app.py already enforces this
        self.CHUNK_SIZE_CHARS = 18_000       # keep prompts safe
        self.CHUNK_OVERLAP_CHARS = 800

        # “Return all failures” mode
        self.RETURN_ALL_FAILURES = True
        self.MAX_FAILURES_HARD_CAP = 200     # prevents insane outputs

    # -----------------------------
    # Public API expected by app.py
    # -----------------------------
    def analyze(self, document_text: str) -> Dict[str, Any]:
        t0 = time.time()

        document_text = self._normalize_text(document_text)
        if not document_text or len(document_text.strip()) < 50:
            return self._fail("Document too short to analyze.")

        chunks = self._chunk_text(document_text)
        chunk_results: List[ChunkResult] = []

        for idx, chunk in enumerate(chunks, start=1):
            try:
                prompt = build_prompt(chunk)
                data = self._call_openai_json(prompt)
                chunk_results.append(ChunkResult(ok=True, data=data))
            except Exception as e:
                chunk_results.append(ChunkResult(ok=False, error=f"Chunk {idx}: {e}"))

        ok_chunks = [cr for cr in chunk_results if cr.ok and cr.data]
        failed_chunks = [cr for cr in chunk_results if not cr.ok]

        if not ok_chunks:
            # IMPORTANT: surface the first couple of errors so you can debug
            sample_errors = [cr.error for cr in failed_chunks[:3] if cr.error]
            return {
                "success": False,
                "error": "All chunks failed to analyze",
                "analysis": None,
                "chunks_analyzed": len(chunks),
                "chunks_succeeded": 0,
                "chunks_failed": len(chunks),
                "analysis_time": int(time.time() - t0),
                "debug_errors": sample_errors,
            }

        combined = self._merge_analyses([cr.data for cr in ok_chunks if cr.data])

        analysis_time = int(time.time() - t0)
        return {
            "success": True,
            "analysis": combined,
            "chunks_analyzed": len(chunks),
            "chunks_succeeded": len(ok_chunks),
            "chunks_failed": len(failed_chunks),
            "analysis_time": analysis_time,
        }

    def format_output(self, result: Dict[str, Any]) -> str:
        if not result["success"]:
    st.error(f"Analysis failed: {result.get('error', 'Unknown error')}")
    debug = result.get("debug_errors")
    if debug:
        st.caption("Debug (first errors):")
        st.code("\n".join([d for d in debug if d]), language=None)
\n\nDebug: {result.get('debug_errors','')}\n"

        a = result["analysis"]
        lines = []
        lines.append("VALIDITY — Reasoning Quality Report")
        lines.append("=" * 34)
        lines.append("")

        thesis = a.get("thesis", {})
        lines.append("THESIS")
        lines.append(f"- Statement: {thesis.get('statement','')}")
        lines.append(f"- Explicitness: {thesis.get('explicitness','')}")
        lines.append("")

        lines.append("CLAIMS")
        for i, c in enumerate(a.get("claims", []), start=1):
            lines.append(f"{i}. {c.get('claim','')}")
            lines.append(f"   - Support: {c.get('support_type','')}")
            d = c.get("details")
            if d:
                lines.append(f"   - Notes: {d}")
        lines.append("")

        lc = a.get("logical_chain", {})
        lines.append("LOGICAL CHAIN")
        for s in lc.get("steps", []):
            lines.append(f"- {s}")
        if lc.get("breaks"):
            lines.append("Breaks:")
            for b in lc.get("breaks", []):
                lines.append(f"- {b}")
        lines.append("")

        fails = a.get("failures_detected", [])
        lines.append(f"FAILURES DETECTED ({len(fails)})")
        for i, f in enumerate(fails, start=1):
            lines.append(f"{i}. {f.get('type','')}")
            lines.append(f"   - Location: {f.get('location','')}")
            lines.append(f"   - Why: {f.get('explanation','')}")
        lines.append("")

        lines.append("COUNTERFACTUAL TESTS")
        for t in a.get("counterfactual_tests", []):
            lines.append(f"- Assumption: {t.get('assumption','')}")
            lines.append(f"  Impact: {t.get('impact_if_wrong','')}")
        lines.append("")

        lines.append("ASSUMPTION SENSITIVITY")
        for s in a.get("assumption_sensitivity", []):
            lines.append(f"- Rank {s.get('impact_rank','')}: {s.get('assumption','')}")
            lines.append(f"  Reason: {s.get('reasoning','')}")
        lines.append("")

        lines.append("STRENGTHS")
        for s in a.get("strengths_detected", []):
            lines.append(f"- {s.get('type','')}: {s.get('description','')}")
        lines.append("")

        oa = a.get("overall_assessment", {})
        lines.append("OVERALL ASSESSMENT")
        lines.append(f"- Confidence: {oa.get('confidence','')}")
        lines.append(f"- Summary: {oa.get('summary','')}")
        lines.append("")

        return "\n".join(lines)

    # -----------------------------
    # Internals
    # -----------------------------
    def _normalize_text(self, text: str) -> str:
        text = text.replace("\x00", "")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _chunk_text(self, text: str) -> List[str]:
        if len(text) <= self.CHUNK_SIZE_CHARS:
            return [text]

        chunks = []
        start = 0
        n = len(text)

        while start < n:
            end = min(start + self.CHUNK_SIZE_CHARS, n)
            chunk = text[start:end]

            # add overlap for continuity
            if end < n:
                overlap_start = max(0, end - self.CHUNK_OVERLAP_CHARS)
                chunk = text[start:end]  # main
                # next chunk will start earlier due to overlap
                next_start = overlap_start
            else:
                next_start = n

            chunks.append(chunk)
            if next_start <= start:
                break
            start = next_start

        return chunks

    def _call_openai_json(self, prompt: str) -> Dict[str, Any]:
        """
        Strict JSON output.
        If the model still returns extra text (rare), we attempt to extract the JSON object.
        """
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[
                {"role": "system", "content": "Return ONLY valid JSON. No markdown. No commentary."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )

        content = resp.choices[0].message.content or ""
        content = content.strip()

        # With response_format=json_object this should already be valid JSON,
        # but keep a belt-and-suspenders parser anyway.
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            extracted = self._extract_first_json_object(content)
            if not extracted:
                raise ValueError(f"Model did not return valid JSON. Raw: {content[:400]}")
            return json.loads(extracted)

    def _extract_first_json_object(self, text: str) -> Optional[str]:
        """
        Finds the first top-level JSON object in a string by brace matching.
        """
        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None

    def _merge_analyses(self, analyses: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Merge strategy:
        - thesis: first non-empty
        - claims: concat, lightly dedupe by claim text
        - logical_chain: concat steps, concat breaks
        - failures_detected: concat, dedupe by (type, location)
        - counterfactual_tests: concat, dedupe by assumption
        - assumption_sensitivity: take best ranked items, re-rank
        - strengths_detected: concat, dedupe by (type, description)
        - overall_assessment: prefer first, but if missing build minimal
        """

        def first_non_empty(path: str) -> Any:
            for a in analyses:
                v = a
                for key in path.split("."):
                    v = v.get(key, None) if isinstance(v, dict) else None
                if v:
                    return v
            return None

        thesis = first_non_empty("thesis") or {"statement": "", "explicitness": "unclear"}

        claims_all = []
        seen_claims = set()
        for a in analyses:
            for c in a.get("claims", []) or []:
                ct = (c.get("claim") or "").strip()
                if not ct:
                    continue
                key = ct.lower()
                if key in seen_claims:
                    continue
                seen_claims.add(key)
                claims_all.append(c)

        lc_steps = []
        lc_breaks = []
        lc_conclusion = ""
        for a in analyses:
            lc = a.get("logical_chain", {}) or {}
            for s in lc.get("steps", []) or []:
                if s and s not in lc_steps:
                    lc_steps.append(s)
            for b in lc.get("breaks", []) or []:
                if b and b not in lc_breaks:
                    lc_breaks.append(b)
            if not lc_conclusion and lc.get("conclusion"):
                lc_conclusion = lc.get("conclusion")

        failures_all = []
        seen_fail = set()
        for a in analyses:
            for f in a.get("failures_detected", []) or []:
                ftype = (f.get("type") or "").strip()
                loc = (f.get("location") or "").strip()
                if not ftype or not loc:
                    continue
                key = (ftype.lower(), loc.lower())
                if key in seen_fail:
                    continue
                seen_fail.add(key)
                failures_all.append(f)

        if self.RETURN_ALL_FAILURES and len(failures_all) > self.MAX_FAILURES_HARD_CAP:
            failures_all = failures_all[: self.MAX_FAILURES_HARD_CAP]

        counter_all = []
        seen_assump = set()
        for a in analyses:
            for t in a.get("counterfactual_tests", []) or []:
                ass = (t.get("assumption") or "").strip()
                if not ass:
                    continue
                key = ass.lower()
                if key in seen_assump:
                    continue
                seen_assump.add(key)
                counter_all.append(t)

        sens_all = []
        seen_sens = set()
        for a in analyses:
            for s in a.get("assumption_sensitivity", []) or []:
                ass = (s.get("assumption") or "").strip()
                if not ass:
                    continue
                key = ass.lower()
                if key in seen_sens:
                    continue
                seen_sens.add(key)
                sens_all.append(s)

        # Sort by impact_rank if present, else keep order; then renumber cleanly
        def rank_val(x: Dict[str, Any]) -> int:
            r = x.get("impact_rank")
            try:
                return int(r)
            except Exception:
                return 9999

        sens_all.sort(key=rank_val)
        for i, s in enumerate(sens_all, start=1):
            s["impact_rank"] = i

        strengths_all = []
        seen_strength = set()
        for a in analyses:
            for s in a.get("strengths_detected", []) or []:
                st = (s.get("type") or "").strip()
                desc = (s.get("description") or "").strip()
                if not st or not desc:
                    continue
                key = (st.lower(), desc.lower())
                if key in seen_strength:
                    continue
                seen_strength.add(key)
                strengths_all.append(s)

        overall = first_non_empty("overall_assessment") or {
            "confidence": "medium",
            "summary": "Aggregate reasoning assessment compiled across document sections."
        }

        combined = {
            "thesis": thesis,
            "claims": claims_all,
            "logical_chain": {
                "steps": lc_steps,
                "conclusion": lc_conclusion,
                "breaks": lc_breaks,
            },
            "failures_detected": failures_all,
            "total_failures_detected": len(failures_all),
            "top_risk_flags": self._top_flags_from_failures(failures_all),
            "decision_risk": self._decision_risk_from_failures(failures_all),
            "counterfactual_tests": counter_all,
            "assumption_sensitivity": sens_all,
            "strengths_detected": strengths_all,
            "overall_assessment": overall,
            "reasoning_score": self._score_from_failures(failures_all),
        }

        return combined

    def _decision_risk_from_failures(self, failures: List[Dict[str, Any]]) -> str:
        # Simple heuristic; you can refine later
        n = len(failures)
        if n >= 10:
            return "high"
        if n >= 3:
            return "medium"
        return "low"

    def _score_from_failures(self, failures: List[Dict[str, Any]]) -> int:
        # Simple starting heuristic: 100 - (10 * failures), bounded
        score = 100 - (10 * len(failures))
        return max(0, min(100, score))

    def _top_flags_from_failures(self, failures: List[Dict[str, Any]]) -> List[str]:
        # Return the most frequent failure types (up to 5)
        counts: Dict[str, int] = {}
        for f in failures:
            t = (f.get("type") or "").strip()
            if not t:
                continue
            counts[t] = counts.get(t, 0) + 1
        ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        return [k for (k, _) in ranked[:5]]

    def _fail(self, msg: str) -> Dict[str, Any]:
        return {
            "success": False,
            "error": msg,
            "analysis": None,
            "chunks_analyzed": 0,
            "chunks_succeeded": 0,
            "chunks_failed": 0,
            "analysis_time": 0,
        }
