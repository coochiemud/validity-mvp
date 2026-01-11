# failure_library.py

ALLOWED_FAILURE_TYPES = [
    "circular_reasoning",
    "causal_leap",
    "unfalsifiable_claim",
    "missing_counterfactual",
    "assumption_stacking",
    "contradictory_claims",
    "evidence_mismatch",
    "false_dichotomy",
]

REASONING_FAILURES = {
    "circular_reasoning": {
        "name": "Circular Reasoning",
        "description": "Conclusion assumes the premise",
        "example": "This company will succeed because it has a winning strategy. We know it's a winning strategy because the company will succeed.",
        "severity": "high",
        "actionability": "review",
    },
    "causal_leap": {
        "name": "Unjustified Causal Leap",
        "description": "Claims X causes Y without establishing mechanism or evidence",
        "example": "User growth is accelerating, therefore revenue will triple.",
        "severity": "high",
        "actionability": "review",
    },
    "unfalsifiable_claim": {
        "name": "Unfalsifiable Claim",
        "description": "Statement that cannot be tested or disproven",
        "example": "The team has unique insights that competitors lack.",
        "severity": "medium",
        "actionability": "monitor",
    },
    "missing_counterfactual": {
        "name": "Missing Counterfactual",
        "description": "Fails to consider alternative explanations",
        "example": "Sales increased after hiring the new VP, proving their impact.",
        "severity": "medium",
        "actionability": "monitor",
    },
    "assumption_stacking": {
        "name": "Unstated Assumption Stacking",
        "description": "Conclusion depends on multiple unstated critical assumptions",
        "example": "If we capture 1% of the market, we'll reach $100M revenue.",
        "severity": "high",
        "actionability": "review",
    },
    "contradictory_claims": {
        "name": "Internal Contradiction",
        "description": "Document makes mutually exclusive claims",
        "example": "Market is highly competitive... We face no significant competitors.",
        "severity": "critical",
        "actionability": "block",
    },
    "evidence_mismatch": {
        "name": "Evidence-Claim Mismatch",
        "description": "Stated evidence doesn't support the conclusion drawn",
        "example": "Customer interviews show interest, therefore product-market fit is proven.",
        "severity": "high",
        "actionability": "review",
    },
    "false_dichotomy": {
        "name": "False Dichotomy",
        "description": "Presents only two options when more exist",
        "example": "Either we raise prices or we go bankrupt.",
        "severity": "medium",
        "actionability": "monitor",
    },
}


def get_taxonomy_prompt_text() -> str:
    lines = ["ALLOWED FAILURE TYPES (you MUST use exactly these):"]
    for ftype in ALLOWED_FAILURE_TYPES:
        failure = REASONING_FAILURES[ftype]
        lines.append(f"\n- {ftype}: {failure['description']}")
        lines.append(f"  Example: {failure['example']}")
    return "\n".join(lines)