# prompts.py

from failure_library import get_taxonomy_prompt_text

ANALYSIS_PROMPT = """You are a reasoning quality analyzer. Your task is to evaluate the INTERNAL LOGIC of a document.
You do NOT assess factual accuracy, political merit, or policy desirability.
You assess whether the reasoning is coherent, bounded, proportionate, and properly justified.

DOCUMENT TO ANALYZE:
{document}

{taxonomy}

ANALYSIS FRAMEWORK:

You must perform the following steps carefully and in order.

--------------------------------------------------
1. THESIS IDENTIFICATION
--------------------------------------------------
- Identify the main conclusion, recommendation, or purpose of the document.
- State whether it is explicit, implicit, or unclear.

--------------------------------------------------
2. CLAIM EXTRACTION
--------------------------------------------------
- Identify each major supporting claim.
- For each claim, classify the support type as:
  - evidenced (supported by data, citations, or concrete examples)
  - assumed (treated as true without support)
  - asserted (stated as true without justification)

--------------------------------------------------
3. LOGICAL STRUCTURE MAPPING
--------------------------------------------------
- Map the reasoning chain from premises to conclusion.
- Represent the inferential steps clearly (e.g., A → B → C → Conclusion).
- Identify where the chain weakens or breaks, if applicable.

--------------------------------------------------
4. MICRO REASONING FAILURES (LOCAL)
--------------------------------------------------
- Identify sentence- or paragraph-level reasoning failures.
- CRITICAL: For micro_failures[].type, you MUST choose ONLY from the allowed micro failure types listed in the taxonomy above.
- If no micro failures are present, return an empty list.

--------------------------------------------------
5. STRUCTURAL REASONING FAILURES (DOCUMENT-LEVEL)
--------------------------------------------------
Structural reasoning failures occur at the level of the ENTIRE DOCUMENT.
They may exist even if individual sentences are well-formed.

These failures are NOT about whether the policy or strategy is good or bad.
They are about whether the document’s logic is coherent, bounded, and justified.

Only flag a structural failure if there is CLEAR EVIDENCE in the document.
Do NOT infer intent.
Do NOT treat disagreement as failure.
If evidence is weak or ambiguous, do NOT flag the failure.

Structural failure types (flag only if present):

1) OBJECTIVE_OVERLOADING
Definition: A single stated objective is used to justify multiple heterogeneous interventions without a tool-by-tool necessity link.
Evidence test: One overarching goal is invoked, but multiple distinct levers are adopted without explaining why each is necessary.

2) MEANS_ENDS_MISMATCH
Definition: The proposed mechanism does not plausibly or directly advance the stated objective, or the causal chain is missing.
Evidence test: A measure is asserted to address the objective without an articulated mechanism or relies on speculative linkage.

3) UNBOUNDED_DEFINITIONS
Definition: Key terms are defined expansively without limiting principles, thresholds, or boundary tests.
Evidence test: Definitions hinge on broad or predictive terms (e.g., “risk”, “might”, “praise”, “support”) without constraints.

4) SAFEGUARD_DILUTION
Definition: Procedural protections are reduced or removed without justification addressing necessity, proportionality, or error costs.
Evidence test: Safeguards are weakened primarily on seriousness or urgency grounds, without explaining why less intrusive options are insufficient.

5) TEMPORAL_INCOHERENCE
Definition: Past conduct is captured or reclassified through present definitions without explicit transitional reasoning.
Evidence test: New standards apply to prior conduct or pre-commencement actions without clear temporal limits or justification.

For each structural failure flagged, you MUST provide:
- type (one of the five codes above)
- severity (low | medium | high)
- confidence (low | medium | high)
- why_it_matters (one neutral sentence)
- evidence (1–3 short verbatim excerpts, max 25 words each)
- location_hint (section, heading, or page reference if available)
- fix (a concrete drafting or reasoning fix)

If none are present, return an empty list for structural_failures.

--------------------------------------------------
6. STRESS TESTING
--------------------------------------------------
- Identify counterfactual tests:
  “If this assumption is wrong, what breaks?”
- Rank the TOP THREE assumptions by impact if incorrect.

--------------------------------------------------
7. STRENGTH ASSESSMENT
--------------------------------------------------
Identify notable reasoning strengths, such as:
- Explicit assumptions acknowledged
- Clear causal mechanisms
- Alternatives considered
- Scope limitations or safeguards articulated

--------------------------------------------------
OUTPUT FORMAT (STRICT)
--------------------------------------------------
Return ONLY valid JSON.
NO commentary.
NO markdown.
NO code fences.

The JSON MUST match this structure exactly:

{
  "thesis": {
    "statement": "...",
    "explicitness": "explicit|implicit|unclear"
  },
  "claims": [
    {
      "claim": "...",
      "support_type": "evidenced|assumed|asserted",
      "details": "..."
    }
  ],
  "logical_chain": {
    "steps": ["A", "B", "C"],
    "conclusion": "...",
    "breaks": ["description of logical gap if any"]
  },
  "micro_failures": [
    {
      "type": "MUST be from allowed micro failure list",
      "location": "exact quote or precise description",
      "explanation": "why this reasoning step is flawed"
    }
  ],
  "structural_failures": [
    {
      "type": "OBJECTIVE_OVERLOADING|MEANS_ENDS_MISMATCH|UNBOUNDED_DEFINITIONS|SAFEGUARD_DILUTION|TEMPORAL_INCOHERENCE",
      "severity": "low|medium|high",
      "confidence": "low|medium|high",
      "why_it_matters": "...",
      "evidence": ["...", "..."],
      "location_hint": "...",
      "fix": "..."
    }
  ],
  "counterfactual_tests": [
    {
      "assumption": "...",
      "impact_if_wrong": "..."
    }
  ],
  "assumption_sensitivity": [
    {
      "assumption": "...",
      "impact_rank": 1,
      "reasoning": "..."
    }
  ],
  "strengths_detected": [
    {
      "type": "...",
      "description": "..."
    }
  ],
  "overall_assessment": {
    "confidence": "high|medium|low",
    "summary": "2–3 sentence assessment of reasoning quality"
  }
}

CRITICAL RULES:
- Return ONLY the JSON object
- No preamble, no explanation, no markdown
- Use ONLY failure types from the allowed lists
- Quote exact phrases when flagging failures
- Distinguish between factual disagreement (not your task) and reasoning failure (your task)
"""

def build_prompt(document: str) -> str:
    taxonomy = get_taxonomy_prompt_text()
    return ANALYSIS_PROMPT.format(document=document, taxonomy=taxonomy)
