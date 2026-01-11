# prompts.py
from failure_library import get_taxonomy_prompt_text

ANALYSIS_PROMPT = """You are a reasoning quality analyzer.

Your task is to evaluate the QUALITY and STRUCTURE of reasoning in the document — not factual accuracy, persuasion, or writing style.

You must identify EVERY reasoning failure that is justified by the text.

DOCUMENT TO ANALYZE:
{document}

REASONING FAILURE TAXONOMY (AUTHORITATIVE):
{taxonomy}

FAILURE ENUMERATION RULES (STRICT):
- You MUST return an EXHAUSTIVE list of reasoning failures present in the text.
- Do NOT return only the top or most obvious issues.
- Return ALL failures that are justified by the document.
- If no failures exist, return an empty list.
- Every failure MUST include:
  - type (must exactly match one of the allowed failure types)
  - location (exact quote or precise pointer)
  - explanation (1–3 concrete sentences explaining the reasoning flaw)
- Do NOT invent failures.
- Do NOT speculate beyond the text.
- Do NOT collapse multiple failures into one entry.

ANALYSIS FRAMEWORK:

1. THESIS IDENTIFICATION
   - Identify the primary conclusion or recommendation.
   - State whether it is explicit, implicit, or unclear.

2. CLAIM EXTRACTION
   - Enumerate all major supporting claims.
   - Classify each as:
     - evidenced (supported by explicit evidence),
     - assumed (treated as true without support),
     - asserted (stated confidently without proof).

3. LOGICAL STRUCTURE MAPPING
   - Trace the reasoning path from claims to conclusion.
   - Explicitly list inferential steps (A → B → C → Conclusion).
   - Identify where logical jumps or breaks occur.

4. REASONING FAILURE DETECTION (CRITICAL)
   - Evaluate the reasoning against the taxonomy.
   - For failures_detected[].type you MUST select ONLY from the allowed list.
   - Return ALL applicable failures.
   - Quote the exact phrase or section where the failure occurs.
   - Distinguish carefully between:
     - “This claim is false” (NOT your job)
     - “This claim is unsupported, overextended, or misused” (YOUR job)

5. STRESS TESTING
   - Identify counterfactual tests:
     - “If X assumption is wrong, what breaks?”
   - Identify which assumptions are most load-bearing.

6. ASSUMPTION SENSITIVITY
   - Rank the most critical assumptions by impact if wrong.
   - Explain why each assumption matters to the conclusion.

7. STRENGTH IDENTIFICATION
   - Identify genuine reasoning strengths such as:
     - Explicit assumptions
     - Clear causal mechanisms
     - Consideration of alternatives
     - Bounded or falsifiable claims

OUTPUT FORMAT REQUIREMENTS (MANDATORY):

Return ONLY valid JSON.
NO commentary.
NO markdown.
NO code fences.

The JSON MUST match this schema exactly:

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
  "failures_detected": [
    {
      "type": "MUST be from allowed list",
      "location": "exact quote or precise pointer",
      "explanation": "1–3 sentences explaining the reasoning failure"
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
    "summary": "2–3 sentence reasoning-focused assessment"
  }
}

FINAL CONSTRAINTS:
- Return ONLY the JSON object.
- Do NOT add explanations outside the JSON.
- Do NOT use markdown formatting.
- Use ONLY the provided failure taxonomy.
- Be precise, exhaustive, and disciplined.
"""

def build_prompt(document: str) -> str:
    taxonomy = get_taxonomy_prompt_text()
    return ANALYSIS_PROMPT.format(
        document=document,
        taxonomy=taxonomy
    )
