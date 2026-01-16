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


def env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except Exception:
        return default


class ValidityAnalyzer:
    def __init__(self):
        api_key = None
        model_name = "gpt-4o"

        try:
            import streamlit as st
            api_key = st.secrets.get("OPENAI_API_KEY")
            model_name = st.secrets.get("MODEL_NAME", "gpt-4o")
        except Exception:
            api_key = os.getenv("OPENAI_API_KEY")
            model_name = os.getenv("MODEL_NAME", "gpt-4o")

        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not found in Streamlit secrets or environment variables")

        self.client = OpenAI(api_key=api_key)
        self.model = model_name

        self.MAX_FAILURES_RETURNED = 10
        self.MAX_SYNTHESIS_ITEMS = 5

        # Env-driven chunking (characters, not words)
        # Keep this in the 12k–20k range for stability.
        self.CHUNK_SIZE_CHARS = env_int("VALIDITY_CHUNK_SIZE", 15000)

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

    def _repair_json(self, bad_json: str) -> str:
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
            model=self.model,
            messages=[{"role": "user", "content": repair_prompt}],
            max_tokens=4000,
            temperature=0
        )
        repaired = response.choices[0].message.content
        return self._clean_json_response(repaired)

    def _enforce_allowed_failure_types(self, failures) -> list:
        if not isinstance(failures, list):
            return []
        return [
            f for f in failures
            if isinstance(f, dict) and f.get("type") in ALLOWED_FAILURE_TYPES
        ]

    def _normalize_failures(self, failures: list) -> list:
        normalized = []
        for f in failures:
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
        elif high_count >= 1:
            return "medium"

        medium_count = sum(1 for f in failures if (f.get("severity") or "").lower() == "medium")
        if medium_count >= 5:
            return "medium"
        elif medium_count >= 2:
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

    # -----------------------------
    # Chunking: char-based, env-driven
    # -----------------------------
    def _chunk_document(self, document: str) -> list:
        size = max(3000, int(self.CHUNK_SIZE_CHARS))
        if len(document) <= size:
            return [document]
        return [document[i:i + size] for i in range(0, len(document), size)]

    def _analyze_chunk(self, chunk: str) -> dict:
        prompt = build_prompt(chunk)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0
        )

        response_text = response.choices[0].message.content
        cleaned = self._clean_json_response(response_text)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            try:
                repaired = self._repair_json(cleaned)
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
                    "_meta": {"parse_failed": True}
                }

    def _synthesize(self, chunk_results: list) -> dict:
        clean_chunks = []
        for chunk in chunk_results:
            clean_chunks.append({k: v for k, v in chunk.items() if k != "_meta"})

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
{json.dumps(clean_chunks, indent=2)}

Return the synthesized JSON:"""

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4000,
                temperature=0
            )

            cleaned = self._clean_json_response(response.choices[0].message.content)

            try:
                result = json.loads(cleaned)
            except json.JSONDecodeError:
                try:
                    repaired = self._repair_json(cleaned)
                    result = json.loads(repaired)
                except Exception:
                    result = clean_chunks[0]

        failures = result.get("failures_detected", [])
        failures = self._enforce_allowed_failure_types(failures)
        failures = self._normalize_failures(failures)
        failures = self._sorted_failures(failures)

        total_failures = len(failures)
        failures = failures[:self.MAX_FAILURES_RETURNED]

        result["failures_detected"] = failures
        result["total_failures_detected"] = total_failures

        result["reasoning_score"] = self._compute_score(failures)
        result["decision_risk"] = self._compute_decision_risk(failures)
        result["review_priorities"] = self._compute_review_priority(failures)
        result["top_risk_flags"] = [f["type"] for f in failures[:3]]

        if "claims" in result:
            result["claims"] = result["claims"][: self.MAX_SYNTHESIS_ITEMS * 2]
        if "counterfactual_tests" in result:
            result["counterfactual_tests"] = result["counterfactual_tests"][: self.MAX_SYNTHESIS_ITEMS]
        if "assumption_sensitivity" in result:
            result["assumption_sensitivity"] = result["assumption_sensitivity"][: self.MAX_SYNTHESIS_ITEMS]
        if "strengths_detected" in result:
            result["strengths_detected"] = result["strengths_detected"][: self.MAX_SYNTHESIS_ITEMS]

        return result

    def _validate_schema(self, analysis: dict) -> bool:
        required = [
            "thesis", "claims", "failures_detected",
            "overall_assessment", "decision_risk", "reasoning_score"
        ]
        if not all(k in analysis for k in required):
            return False
        if analysis["decision_risk"] not in ["critical", "high", "medium", "low"]:
            return False
        if not isinstance(analysis["reasoning_score"], (int, float)):
            return False
        return True

    # -----------------------------
    # Public API: partial-success behavior
    # -----------------------------
    def analyze(self, document: str, timeout_seconds: int = 180) -> dict:
        start_time = time.time()

        try:
            document = self._normalize_text(document)
            if len(document) < 50:
                return {"success": False, "error": "Document too short (minimum 50 characters)"}

            chunks = self._chunk_document(document)

            chunk_results = []
            chunk_failures = 0
            timed_out = False

            for chunk in chunks:
                if time.time() - start_time > timeout_seconds:
                    timed_out = True
                    break

                try:
                    result = self._analyze_chunk(chunk)
                    if isinstance(result, dict) and result.get("_meta", {}).get("parse_failed"):
                        chunk_failures += 1
                        continue
                    chunk_results.append(result)
                except Exception:
                    chunk_failures += 1
                    continue

            if not chunk_results:
                return {"success": False, "error": "All chunks failed to analyze"}

            analysis = self._synthesize(chunk_results)

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
                "timeout_seconds": timeout_seconds,
                "chunk_size_chars": int(self.CHUNK_SIZE_CHARS),
            }

        except Exception as e:
            return {"success": False, "error": str(e)}
