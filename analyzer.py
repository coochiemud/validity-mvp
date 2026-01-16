# analyzer.py
from openai import OpenAI
import json
import os
import re
import time
from dotenv import load_dotenv
from prompts import build_prompt
from failure_library import REASONING_FAILURES, ALLOWED_FAILURE_TYPES

load_dotenv()


class ValidityAnalyzer:
    def __init__(self):
        # Try Streamlit secrets first, fall back to environment variable
        api_key = None
        model_name = "gpt-4o"

        try:
            import streamlit as st
            api_key = st.secrets.get("OPENAI_API_KEY")
            model_name = st.secrets.get("MODEL_NAME", "gpt-4o")
            # Optional faster model for large mode
            self.model_large = st.secrets.get("MODEL_NAME_LARGE", None)
        except Exception:
            api_key = os.getenv("OPENAI_API_KEY")
            model_name = os.getenv("MODEL_NAME", "gpt-4o")
            self.model_large = os.getenv("MODEL_NAME_LARGE", None)

        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not found in Streamlit secrets or environment variables")

        self.client = OpenAI(api_key=api_key)
        self.model = model_name

        # Production limits
        self.MAX_FAILURES_RETURNED = 10
        self.MAX_SYNTHESIS_ITEMS = 5

        # Tunables (override via env)
        self.DEFAULT_TIMEOUT_SECONDS = int(os.getenv("VALIDITY_TIMEOUT_SECONDS", "600"))
        self.DEFAULT_CHUNK_WORDS = int(os.getenv("VALIDITY_CHUNK_WORDS", "6000"))
        self.SYNTH_BATCH_SIZE = int(os.getenv("VALIDITY_SYNTH_BATCH", "4"))

    def _normalize_text(self, text: str) -> str:
        text = text.replace("\x00", "")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _clean_json_response(self, text: str) -> str:
        cleaned = text.strip()

        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]

        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]

        return cleaned.strip()

    def _repair_json(self, bad_json: str, model: str) -> str:
        repair_prompt = f"""The following is invalid JSON. Fix it and return ONLY valid JSON matching the original structure.

Rules:
- Return ONLY the JSON object
- No commentary
- No markdown code fences
- Fix any syntax errors (trailing commas, quotes, etc)

INVALID JSON:
{bad_json}

Return the corrected JSON:"""

        response = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": repair_prompt}],
            max_tokens=4000,
            temperature=0,
        )

        repaired = response.choices[0].message.content or ""
        return self._clean_json_response(repaired)

    def _enforce_allowed_failure_types(self, failures) -> list:
        if not isinstance(failures, list):
            return []
        return [f for f in failures if isinstance(f, dict) and f.get("type") in ALLOWED_FAILURE_TYPES]

    def _normalize_failures(self, failures: list) -> list:
        normalized = []
        for f in failures:
            if not isinstance(f, dict):
                continue
            ftype = f.get("type")
            if ftype in REASONING_FAILURES:
                f["severity"] = REASONING_FAILURES[ftype]["severity"]
                f["actionability"] = REASONING_FAILURES[ftype]["actionability"]
            normalized.append(f)
        return normalized

    def _severity_rank(self, sev: str) -> int:
        return {"critical": 3, "high": 2, "medium": 1}.get((sev or "").lower(), 0)

    def _sorted_failures(self, failures: list) -> list:
        return sorted(
            failures,
            key=lambda f: (-self._severity_rank(f.get("severity", "medium")), f.get("type", "")),
        )

    def _compute_score(self, failures: list) -> int:
        if not failures:
            return 100

        score = 100
        for f in failures:
            sev = (f.get("severity") or "medium").lower()
            if sev == "critical":
                score -= 35
            elif sev == "high":
                score -= 20
            elif sev == "medium":
                score -= 10

        return max(0, min(100, score))

    def _compute_decision_risk(self, failures: list) -> str:
        if any((f.get("severity") or "").lower() == "critical" for f in failures):
            return "critical"

        high_count = sum(1 for f in failures if (f.get("severity") or "").lower() == "high")
        if high_count >= 3:
            return "high"
        if high_count >= 1:
            return "medium"

        medium_count = sum(1 for f in failures if (f.get("severity") or "").lower() == "medium")
        if medium_count >= 5:
            return "medium"
        if medium_count >= 2:
            return "low"

        return "low"

    def _compute_review_priority(self, failures: list) -> dict:
        priorities = {"must_fix": [], "should_fix": [], "nice_to_have": []}
        for f in failures:
            sev = (f.get("severity") or "medium").lower()
            if sev == "critical":
                priorities["must_fix"].append(f)
            elif sev == "high":
                priorities["should_fix"].append(f)
            else:
                priorities["nice_to_have"].append(f)
        return priorities

    def _chunk_document(self, document: str, max_words: int) -> list:
        words = document.split()
        if len(words) <= max_words:
            return [document]

        chunks = []
        current = []

        for w in words:
            current.append(w)
            if len(current) >= max_words:
                chunks.append(" ".join(current))
                current = []

        if current:
            chunks.append(" ".join(current))

        return chunks

    def _analyze_chunk(self, chunk: str, model: str) -> dict:
        prompt = build_prompt(chunk)

        response = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0,
        )

        response_text = response.choices[0].message.content or ""
        cleaned = self._clean_json_response(response_text)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            try:
                repaired = self._repair_json(cleaned, model=model)
                return json.loads(repaired)
            except Exception:
                return {
                    "thesis": {"statement": "Parse failed", "explicitness": "unclear"},
                    "claims": [],
                    "logical_chain": {"steps": [], "conclusion": "", "breaks": []},
                    "failures_detected": [],
                    "counterfactual_tests": [],
                    "assumption_sensitivity": [],
                    "strengths_detected": [],
                    "overall_assessment": {"confidence": "low", "summary": "Parse error occurred"},
                    "_meta": {"parse_failed": True},
                }

    def _trim_for_synthesis(self, chunk: dict) -> dict:
        """
        Keep synthesis input small and high-signal so merges don't explode in tokens/time.
        """
        if not isinstance(chunk, dict):
            return {}
        out = {}
        out["thesis"] = chunk.get("thesis", {})
        out["overall_assessment"] = chunk.get("overall_assessment", {})
        out["failures_detected"] = chunk.get("failures_detected", [])[: self.MAX_SYNTHESIS_ITEMS * 2]
        out["claims"] = chunk.get("claims", [])[: self.MAX_SYNTHESIS_ITEMS * 2]
        out["counterfactual_tests"] = chunk.get("counterfactual_tests", [])[: self.MAX_SYNTHESIS_ITEMS]
        out["assumption_sensitivity"] = chunk.get("assumption_sensitivity", [])[: self.MAX_SYNTHESIS_ITEMS]
        out["strengths_detected"] = chunk.get("strengths_detected", [])[: self.MAX_SYNTHESIS_ITEMS]
        return out

    def _synthesize(self, chunk_results: list, model: str) -> dict:
        clean_chunks = []
        for chunk in chunk_results:
            c = {k: v for k, v in chunk.items() if k != "_meta"}
            clean_chunks.append(self._trim_for_synthesis(c))

        if len(clean_chunks) == 1:
            result = clean_chunks[0]
        else:
            prompt = f"""You are merging multiple Validity chunk analyses into ONE final analysis.

Rules:
- Return ONLY valid JSON matching the schema
- Deduplicate claims and failures (keep unique, highest-signal items)
- Choose a single best thesis statement
- Keep only the most defensible, highest-signal items
- No commentary, no markdown

CHUNK_RESULTS:
{json.dumps(clean_chunks, ensure_ascii=False)}

Return the synthesized JSON:"""

            response = self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4000,
                temperature=0,
            )

            cleaned = self._clean_json_response(response.choices[0].message.content or "")

            try:
                result = json.loads(cleaned)
            except json.JSONDecodeError:
                try:
                    repaired = self._repair_json(cleaned, model=model)
                    result = json.loads(repaired)
                except Exception:
                    result = clean_chunks[0]

        failures = result.get("failures_detected", [])
        failures = self._enforce_allowed_failure_types(failures)
        failures = self._normalize_failures(failures)
        failures = self._sorted_failures(failures)

        total_failures = len(failures)
        failures = failures[: self.MAX_FAILURES_RETURNED]

        result["failures_detected"] = failures
        result["total_failures_detected"] = total_failures

        result["reasoning_score"] = self._compute_score(failures)
        result["decision_risk"] = self._compute_decision_risk(failures)
        result["review_priorities"] = self._compute_review_priority(failures)
        result["top_risk_flags"] = [f["type"] for f in failures[:3] if isinstance(f, dict) and f.get("type")]

        # Clip lists
        if "claims" in result:
            result["claims"] = (result["claims"] or [])[: self.MAX_SYNTHESIS_ITEMS * 2]
        if "counterfactual_tests" in result:
            result["counterfactual_tests"] = (result["counterfactual_tests"] or [])[: self.MAX_SYNTHESIS_ITEMS]
        if "assumption_sensitivity" in result:
            result["assumption_sensitivity"] = (result["assumption_sensitivity"] or [])[: self.MAX_SYNTHESIS_ITEMS]
        if "strengths_detected" in result:
            result["strengths_detected"] = (result["strengths_detected"] or [])[: self.MAX_SYNTHESIS_ITEMS]

        return result

    def _synthesize_batched(self, chunk_results: list, model: str) -> dict:
        """
        Avoid one massive synthesis call. Merge in batches, then merge the batch outputs.
        """
        if not chunk_results:
            return {}

        if len(chunk_results) == 1:
            return self._synthesize(chunk_results, model=model)

        batch_size = max(2, self.SYNTH_BATCH_SIZE)
        partials = []

        for i in range(0, len(chunk_results), batch_size):
            batch = chunk_results[i : i + batch_size]
            partials.append(self._synthesize(batch, model=model))

        # If we created multiple partial syntheses, merge them too
        if len(partials) == 1:
            return partials[0]

        return self._synthesize(partials, model=model)

    def _validate_schema(self, analysis: dict) -> bool:
        required = ["thesis", "claims", "failures_detected", "overall_assessment", "decision_risk", "reasoning_score"]
        if not isinstance(analysis, dict):
            return False
        if not all(k in analysis for k in required):
            return False
        if analysis["decision_risk"] not in ["critical", "high", "medium", "low"]:
            return False
        if not isinstance(analysis["reasoning_score"], (int, float)):
            return False
        return True

    def analyze(self, document: str, timeout_seconds: int | None = None, large_mode: bool = False) -> dict:
        """
        Analyzes a document for reasoning quality.

        - timeout_seconds: overall wall-clock budget (default from env, typically 600s)
        - large_mode: uses larger chunk size and optional faster model for large docs
        """
        start_time = time.time()

        try:
            document = self._normalize_text(document)

            if len(document) < 50:
                return {"success": False, "error": "Document too short (minimum 50 characters)"}

            # Timeout: default to env-based value if not provided
            if timeout_seconds is None:
                timeout_seconds = self.DEFAULT_TIMEOUT_SECONDS

            # Chunk sizing: fewer chunks in large mode
            max_words = self.DEFAULT_CHUNK_WORDS * (2 if large_mode else 1)
            chunks = self._chunk_document(document, max_words=max_words)

            # Model selection
            model = self.model_large if (large_mode and self.model_large) else self.model

            chunk_results = []
            chunk_failures = 0
            timed_out = False

            for i, chunk in enumerate(chunks, start=1):
                if time.time() - start_time > timeout_seconds:
                    timed_out = True
                    break

                try:
                    result = self._analyze_chunk(chunk, model=model)

                    if isinstance(result, dict) and result.get("_meta", {}).get("parse_failed"):
                        chunk_failures += 1
                        continue

                    chunk_results.append(result)

                except Exception:
                    chunk_failures += 1
                    continue

            if not chunk_results:
                return {"success": False, "error": "All chunks failed to analyze"}

            # Synthesize (batched)
            analysis = self._synthesize_batched(chunk_results, model=model)

            if not self._validate_schema(analysis):
                return {"success": False, "error": "Analysis failed schema validation"}

            return {
                "success": True,
                "analysis": analysis,
                "chunks_analyzed": len(chunks),
                "chunks_succeeded": len(chunk_results),
                "chunks_failed": chunk_failures,
                "analysis_time": round(time.time() - start_time, 2),
                "partial": bool(timed_out),
                "warning": (
                    f"Partial analysis: timed out after {timeout_seconds}s "
                    f"({len(chunk_results)}/{len(chunks)} chunks completed)."
                    if timed_out
                    else None
                ),
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def format_output(self, analysis: dict) -> str:
        if not analysis.get("success"):
            return f"❌ Analysis failed: {analysis.get('error')}"

        data = analysis["analysis"]
        output = []

        output.append("=" * 80)
        output.append("VALIDITY REASONING ANALYSIS")
        output.append("=" * 80)
        output.append("")

        if analysis.get("partial"):
            output.append(f"⚠️  {analysis.get('warning')}")
            output.append("")

        output.append("📊 SUMMARY")
        output.append(f"   Reasoning Score: {data.get('reasoning_score', 'N/A')}/100")
        output.append(f"   Decision Risk: {data.get('decision_risk', 'N/A').upper()}")

        top_flags = data.get("top_risk_flags", [])
        if top_flags:
            flags_formatted = [f.replace("_", " ").title() for f in top_flags]
            output.append(f"   Top Risk Flags: {', '.join(flags_formatted)}")

        chunks = analysis.get("chunks_analyzed", 1)
        if chunks > 1:
            output.append(f"   (Analyzed in {chunks} sections)")

        output.append("")
        output.append("=" * 80)
        output.append("")

        priorities = data.get("review_priorities", {})
        if priorities:
            output.append("🎯 REVIEW PRIORITIES")

            must_fix = priorities.get("must_fix", [])
            if must_fix:
                output.append(f"   🔴 MUST FIX ({len(must_fix)} critical)")
                for f in must_fix[:3]:
                    output.append(f"      - {f['type'].replace('_', ' ').title()}")

            should_fix = priorities.get("should_fix", [])
            if should_fix:
                output.append(f"   🟠 SHOULD FIX ({len(should_fix)} high-severity)")

            nice_to_have = priorities.get("nice_to_have", [])
            if nice_to_have:
                output.append(f"   🟡 NICE TO HAVE ({len(nice_to_have)} medium)")

            output.append("")

        failures = data.get("failures_detected", [])
        total_failures = data.get("total_failures_detected", len(failures))

        if failures:
            header = f"🚨 DETAILED FINDINGS ({len(failures)} shown"
            if total_failures > len(failures):
                header += f" of {total_failures} total"
            header += ")"
            output.append(header)

            for i, failure in enumerate(failures, 1):
                sev = (failure.get("severity") or "medium").lower()
                severity_icon = "🔴" if sev == "critical" else "🟠" if sev == "high" else "🟡"
                action = (failure.get("actionability") or "review").upper()

                output.append(f"   {i}. {severity_icon} {failure['type'].upper().replace('_', ' ')} [{action}]")
                output.append(f"      Location: {failure.get('location', 'Not specified')}")
                output.append(f"      Issue: {failure.get('explanation', 'No explanation')}")
                output.append("")
        else:
            output.append("✅ No reasoning failures detected")
            output.append("")

        output.append("=" * 80)
        return "\n".join(output)
