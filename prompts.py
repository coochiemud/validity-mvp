# prompts.py
from failure_library import get_taxonomy_prompt_text

ANALYSIS_PROMPT = """You are a reasoning quality analyzer. Your job is to evaluate the logical structure of arguments, not their factual accuracy.

DOCUMENT TO ANALYZE:
{document}

{taxonomy}

ANALYSIS FRAMEWORK:
1. THESIS IDENTIFICATION
   - What is the main conclusion or recommendation?
   - Is it stated explicitly or implied?

2. CLAIM EXTRACTION
   - List each major supporting claim
   - Note whether each is evidenced, assumed, or asserted

3. LOGICAL STRUCTURE
   - Map the reasoning chain: How does the author get from evidence to conclusion?
   - Identify the inferential steps (A → B → C → Conclusion)

4. REASONING QUALITY CHECKS
   CRITICAL: For failures_detected[].type, you MUST choose ONLY from the allowed types listed above.
   If none apply, return an empty list for failures_detected.

5. STRESS TESTING
   - Identify counterfactual tests: "If X assumption is wrong, what breaks?"
   - Rank top 3 assumptions by sensitivity/impact

6. STRENGTH ASSESSMENT
   Note reasoning strengths:
   - Explicit assumptions stated and tested
   - Clear causal mechanisms provided
   - Alternative explanations considered
   - Falsifiable predictions made

OUTPUT FORMAT:
Return ONLY valid JSON with NO commentary, NO markdown, NO code fences:

{{
  "thesis": {{
    "statement": "...",
    "explicitness": "explicit|implicit|unclear"
  }},
  "claims": [
    {{
      "claim": "...",
      "support_type": "evidenced|assumed|asserted",
      "details": "..."
    }}
  ],
  "logical_chain": {{
    "steps": ["A", "B", "C"],
    "conclusion": "...",
    "breaks": ["description of logical gap if any"]
  }},
  "failures_detected": [
    {{
      "type": "MUST be from allowed list",
      "location": "quote or description",
      "explanation": "why this is problematic"
    }}
  ],
  "counterfactual_tests": [
    {{
      "assumption": "...",
      "impact_if_wrong": "..."
    }}
  ],
  "assumption_sensitivity": [
    {{
      "assumption": "...",
      "impact_rank": 1,
      "reasoning": "..."
    }}
  ],
  "strengths_detected": [
    {{
      "type": "...",
      "description": "..."
    }}
  ],
  "overall_assessment": {{
    "confidence": "high|medium|low",
    "summary": "2-3 sentence assessment"
  }}
}}

CRITICAL RULES:
- Return ONLY the JSON object
- No preamble, no explanation, no markdown
- Use only the failure types from the allowed list
- Quote exact phrases when flagging issues
- Distinguish between "this claim is false" (not your job) and "this reasoning is flawed" (your job)
"""

def build_prompt(document: str) -> str:
    taxonomy = get_taxonomy_prompt_text()
    return ANALYSIS_PROMPT.format(document=document, taxonomy=taxonomy)