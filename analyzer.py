# analyzer.py
import json
import os
import re
import time
from typing import List, Dict

from openai import OpenAI
from dotenv import load_dotenv

from prompts import build_prompt
from failure_library import REASONING_FAILURES, ALLOWED_FAILURE_TYPES

load_dotenv()


class ValidityAnalyzer:
    """
    Core reasoning analysis engine for Validity.

    Responsibilities:
    - Call OpenAI with a strict JSON contract
    - Analyse reasoning quality (not content quality)
    - Normalise failures against a fixed taxonomy
    - Compute deterministic scores and risk flags
    """

    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")

        self.client = OpenAI(api_key=api_key)
        self.model = os.getenv("MODEL_NAME", "gpt-4o-mini")

        # Hard limits (defensive)
        self.MAX_FAILURES_RETURNED = 10
        self.MAX_SYNTHESIS_ITEMS = 5

    # ---------------------------------------------------------------------
    # Utilities
    # ---------------------------------------------------------------------

    def _normalize_text(self, text: str) -> str:
        text = text.replace("\x00", "")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _severity_rank(self, sev: str) -> int:
        return {"critical": 3, "high": 2, "medium": 1}.get(sev, 0)

    # ---------------------------------------------------------------------
    # OpenAI interaction
    # ---------------------------------------------------------------------

    def _call_model(self, prompt: str) -> Dict:
        """
        Single, hardened OpenAI call that guarantees JSON or raises.
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=4000,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        return json.loads(content)

    # ---------------------------------------------------------------------
    # Chunk analysis
    # ---------------------------------------------------------------------

    def _chunk_document(self, document: str, max_words: int = 2000) -> List[str]:
        words = document.split()
        if len(words) <= max_words:
            return [document]

        chunks = []
        current = []
        for word in words:
            current.append(word)
            if len(current) >= max_words:
                chunks.append(" ".join(current))
                current = []
        if current:
            chunks.append(" ".join(current))

        return chunks

    def _analyze_chunk(self, chunk: str) -> Dict:
        prompt = build_prompt(chunk)
        return self._call_model(prompt)

    # ---------------------------------------------------------------------
    # Synthesis
    # ---------------------------------------------------------------------

    def _synthesize(self, analyses: List[Dict]) -> Dict:
        if len(analyses) == 1:
            return analyses[0]

        prompt = f"""
You are merging multiple Validity reasoning analyses into ONE final analysis.

Rules:
- Return ONLY valid JSON
- Deduplicate claims and failures
- Keep highest-signal items only
- Choose the single strongest thesis
- No commentary

INPUT:
{json.dumps(analyses, indent=2)}
"""
        return self._call_model(prompt)

    # ---------------------------------------------------------------------
    # Failure normalisation + scoring
    # ---------------------------------------------------------------------

    def _normalize_failures(self, failures: List[Dict]) -> List[Dict]:
        clean = []
        for f in failures:
            ftype = f.get("type")
            if ftype not in ALLOWED_FAILURE_TYPES:
                continue
            meta = REASONING_FAILURES.get(ftype)
            if meta:
                f["severity"] = meta["severity"]
                f["actionability"] = meta["actionability"]
            clean.append(f)
        return clean

    def _compute_score(self, failures: List[Dict]) -> int:
        score = 100
        for f in failures:
            sev = f.get("severity")
            if sev == "critical":
                score -= 35
            elif sev == "high":
                score -= 20
            elif sev == "medium":
                score -= 10
        return max(0, min(100, score))

    def _compute_decision_risk(self, failures: List[Dict]) -> str:
        if any(f.get("severity") == "critical" for f in failures):
            return "critical"
        highs = sum(1 for f in failures if f.get("severity") == "high")
        if highs >= 3:
            return "high"
        if highs >= 1:
            return "medium"
        return "low"

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------

    def analyze(self, document: str, timeout_seconds: int = 60) -> Dict:
        start = time.time()

        document = self._normalize_text(document)
        if len(document) < 50:
            return {"success": False, "error": "Document too short"}

        chunks = self._chunk_document(document)
        results = []

        for i, chunk in enumerate(chunks, start=1):
            if time.time() - start > timeout_seconds:
                return {
                    "success": False,
                    "error": f"Timeout after {timeout_seconds}s",
                }
            try:
                results.append(self._analyze_chunk(chunk))
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Model error on chunk {i}: {e}",
                }

        final = self._synthesize(results)

        failures = final.get("failures_detected", [])
        failures = self._normalize_failures(failures)
        failures = sorted(
            failures,
            key=lambda f: (-self._severity_rank(f.get("severity")), f.get("type", "")),
        )

        total_failures = len(failures)
        failures = failures[: self.MAX_FAILURES_RETURNED]

        final["failures_detected"] = failures
        final["total_failures_detected"] = total_failures
        final["reasoning_score"] = self._compute_score(failures)
        final["decision_risk"] = self._compute_decision_risk(failures)
        final["top_risk_flags"] = [f["type"] for f in failures[:3]]

        return {
            "success": True,
            "analysis": final,
            "chunks_analyzed": len(chunks),
            "analysis_time": round(time.time() - start, 2),
        }

        return text.strip()
    
    def _clean_json_response(self, text: str) -> str:
        """Remove markdown code fences and clean response"""
        cleaned = text.strip()
        
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        
        return cleaned.strip()
    
    def _repair_json(self, bad_json: str) -> str:
        """Attempt to repair invalid JSON using OpenAI (one attempt only)"""
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
        """Drop any failures not in allowed taxonomy, with type safety"""
        if not isinstance(failures, list):
            return []
        return [
            f for f in failures 
            if isinstance(f, dict) and f.get("type") in ALLOWED_FAILURE_TYPES
        ]
    
    def _normalize_failures(self, failures: list) -> list:
        """Override severity/actionability from taxonomy"""
        normalized = []
        for f in failures:
            ftype = f.get("type")
            if ftype in REASONING_FAILURES:
                f["severity"] = REASONING_FAILURES[ftype]["severity"]
                f["actionability"] = REASONING_FAILURES[ftype]["actionability"]
            normalized.append(f)
        return normalized
    
    def _severity_rank(self, sev: str) -> int:
        return {"critical": 3, "high": 2, "medium": 1}.get(sev, 0)
    
    def _sorted_failures(self, failures: list) -> list:
        """Sort failures by severity then type"""
        return sorted(
            failures,
            key=lambda f: (-self._severity_rank(f.get("severity", "medium")), f.get("type", "")),
        )
    
    def _compute_score(self, failures: list) -> int:
        """Deterministic reasoning score based on failures"""
        score = 100
        for f in failures:
            sev = f.get("severity", "medium")
            if sev == "critical":
                score -= 35
            elif sev == "high":
                score -= 20
            elif sev == "medium":
                score -= 10
        return max(0, min(100, score))
    
    def _compute_decision_risk(self, failures: list) -> str:
        """Deterministic risk level based on failures"""
        if any(f.get("severity") == "critical" for f in failures):
            return "critical"
        
        high_count = sum(1 for f in failures if f.get("severity") == "high")
        if high_count >= 3:
            return "high"
        elif high_count >= 1:
            return "medium"
        
        medium_count = sum(1 for f in failures if f.get("severity") == "medium")
        if medium_count >= 5:
            return "medium"
        elif medium_count >= 2:
            return "low"
        
        return "low" if failures else "low"
    
    def _compute_review_priority(self, failures: list) -> dict:
        """Categorize failures by action priority"""
        priorities = {
            "must_fix": [],
            "should_fix": [],
            "nice_to_have": []
        }
        
        for f in failures:
            sev = f.get("severity", "medium")
            if sev == "critical":
                priorities["must_fix"].append(f)
            elif sev == "high":
                priorities["should_fix"].append(f)
            else:
                priorities["nice_to_have"].append(f)
        
        return priorities
    
    def _chunk_document(self, document: str, max_words: int = 2000) -> list:
        """Split document into chunks for long documents"""
        words = document.split()
        
        if len(words) <= max_words:
            return [document]
        
        chunks = []
        current_chunk = []
        
        for word in words:
            current_chunk.append(word)
            if len(current_chunk) >= max_words:
                chunks.append(" ".join(current_chunk))
                current_chunk = []
        
        if current_chunk:
            chunks.append(" ".join(current_chunk))
        
        return chunks
    
    def _analyze_chunk(self, chunk: str) -> dict:
        """Analyze a single chunk (with fallback on parse failure)"""
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
            analysis = json.loads(cleaned)
            return analysis
        except json.JSONDecodeError:
            # Try repair once
            try:
                repaired = self._repair_json(cleaned)
                analysis = json.loads(repaired)
                return analysis
            except Exception:
                # Return minimal valid structure with parse_failed flag
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
        """Merge multiple chunk analyses into one coherent result"""
        # Filter out _meta fields before synthesis
        clean_chunks = []
        for chunk in chunk_results:
            clean_chunk = {k: v for k, v in chunk.items() if k != "_meta"}
            clean_chunks.append(clean_chunk)
        
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
                    # Fallback: use first chunk if synthesis fails
                    result = clean_chunks[0]
        
        # Apply all normalization and computation
        failures = result.get("failures_detected", [])
        failures = self._enforce_allowed_failure_types(failures)
        failures = self._normalize_failures(failures)
        failures = self._sorted_failures(failures)
        
        # Track total before capping
        total_failures = len(failures)
        
        # Cap to top N failures
        failures = failures[:self.MAX_FAILURES_RETURNED]
        result["failures_detected"] = failures
        result["total_failures_detected"] = total_failures
        
        # Compute deterministic fields
        result["reasoning_score"] = self._compute_score(failures)
        result["decision_risk"] = self._compute_decision_risk(failures)
        result["review_priorities"] = self._compute_review_priority(failures)
        result["top_risk_flags"] = [f["type"] for f in failures[:3]]
        
        # Cap other arrays
        if "claims" in result:
            result["claims"] = result["claims"][:self.MAX_SYNTHESIS_ITEMS * 2]
        if "counterfactual_tests" in result:
            result["counterfactual_tests"] = result["counterfactual_tests"][:self.MAX_SYNTHESIS_ITEMS]
        if "assumption_sensitivity" in result:
            result["assumption_sensitivity"] = result["assumption_sensitivity"][:self.MAX_SYNTHESIS_ITEMS]
        if "strengths_detected" in result:
            result["strengths_detected"] = result["strengths_detected"][:self.MAX_SYNTHESIS_ITEMS]
        
        return result
    
    def _validate_schema(self, analysis: dict) -> bool:
        """Validate the analysis has required fields"""
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
    
    def analyze(self, document: str, timeout_seconds: int = 60) -> dict:
        """
        Analyzes a document for reasoning quality.
        Returns structured analysis as a dictionary.
        Handles long documents via chunking with timeout protection.
        """
        start_time = time.time()
        
        try:
            document = self._normalize_text(document)
            
            if len(document) < 50:
                return {
                    "success": False,
                    "error": "Document too short (minimum 50 characters)"
                }
            
            chunks = self._chunk_document(document, max_words=2000)
            
            chunk_results = []
            chunk_failures = 0
            
            for i, chunk in enumerate(chunks, start=1):
                # Check timeout
                if time.time() - start_time > timeout_seconds:
                    return {
                        "success": False,
                        "error": f"Analysis timeout after {timeout_seconds}s (succeeded {len(chunk_results)}/{len(chunks)} chunks)"
                    }
                
                try:
                    result = self._analyze_chunk(chunk)
                    
                    # Check if parse failed - if so, count it but don't append
                    if isinstance(result, dict) and result.get("_meta", {}).get("parse_failed"):
                        chunk_failures += 1
                        continue
                    
                    chunk_results.append(result)
                    
                except Exception:
                    chunk_failures += 1
                    continue
            
            if not chunk_results:
                return {
                    "success": False,
                    "error": "All chunks failed to analyze"
                }
            
            analysis = self._synthesize(chunk_results)
            
            if not self._validate_schema(analysis):
                return {
                    "success": False,
                    "error": "Analysis failed schema validation"
                }
            
            return {
                "success": True,
                "analysis": analysis,
                "chunks_analyzed": len(chunks),
                "chunks_succeeded": len(chunk_results),
                "chunks_failed": chunk_failures,
                "analysis_time": round(time.time() - start_time, 2)
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def format_output(self, analysis: dict) -> str:
        """Formats the analysis into human-readable text"""
        if not analysis.get("success"):
            return f"❌ Analysis failed: {analysis.get('error')}"
        
        data = analysis["analysis"]
        
        output = []
        output.append("=" * 80)
        output.append("VALIDITY REASONING ANALYSIS")
        output.append("=" * 80)
        output.append("")
        
        # SUMMARY
        output.append("📊 SUMMARY")
        output.append(f"   Reasoning Score: {data.get('reasoning_score', 'N/A')}/100")
        output.append(f"   Decision Risk: {data.get('decision_risk', 'N/A').upper()}")
        
        top_flags = data.get('top_risk_flags', [])
        if top_flags:
            flags_formatted = [f.replace('_', ' ').title() for f in top_flags]
            output.append(f"   Top Risk Flags: {', '.join(flags_formatted)}")
        
        chunks = analysis.get('chunks_analyzed', 1)
        if chunks > 1:
            output.append(f"   (Analyzed in {chunks} sections)")
        
        output.append("")
        output.append("=" * 80)
        output.append("")
        
        # REVIEW PRIORITIES
        priorities = data.get('review_priorities', {})
        if priorities:
            output.append("🎯 REVIEW PRIORITIES")
            
            must_fix = priorities.get('must_fix', [])
            if must_fix:
                output.append(f"   🔴 MUST FIX ({len(must_fix)} critical)")
                for f in must_fix[:3]:
                    output.append(f"      - {f['type'].replace('_', ' ').title()}")
            
            should_fix = priorities.get('should_fix', [])
            if should_fix:
                output.append(f"   🟠 SHOULD FIX ({len(should_fix)} high-severity)")
            
            nice_to_have = priorities.get('nice_to_have', [])
            if nice_to_have:
                output.append(f"   🟡 NICE TO HAVE ({len(nice_to_have)} medium)")
            
            output.append("")
        
        # DETAILED FAILURES
        failures = data.get('failures_detected', [])
        total_failures = data.get('total_failures_detected', len(failures))
        
        if failures:
            header = f"🚨 DETAILED FINDINGS ({len(failures)} shown"
            if total_failures > len(failures):
                header += f" of {total_failures} total"
            header += ")"
            output.append(header)
            
            for i, failure in enumerate(failures, 1):
                severity_icon = "🔴" if failure['severity'] == "critical" else "🟠" if failure['severity'] == "high" else "🟡"
                action = failure.get('actionability', 'review').upper()
                
                output.append(f"   {i}. {severity_icon} {failure['type'].upper().replace('_', ' ')} [{action}]")
                output.append(f"      Location: {failure.get('location', 'Not specified')}")
                output.append(f"      Issue: {failure.get('explanation', 'No explanation')}")
                output.append("")
        else:
            output.append("✅ No reasoning failures detected")
            output.append("")
        
        output.append("=" * 80)
        
        return "\n".join(output)