# failure_library.py

# -------------------------------------------------
# MICRO (LOCAL) REASONING FAILURES
# -------------------------------------------------

ALLOWED_MICRO_FAILURE_TYPES = [
    "circular_reasoning",
    "causal_leap",
    "unfalsifiable_claim",
    "missing_counterfactual",
    "assumption_stacking",
    "contradictory_claims",
    "evidence_mismatch",
    "false_dichotomy",
]

MICRO_REASONING_FAILURES = {
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
        "name": "Evidence–Claim Mismatch",
        "description": "Stated evidence does not support the conclusion drawn",
        "example": "Customer interviews show interest, therefore product–market fit is proven.",
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

# Backwards compatibility (if referenced elsewhere)
ALLOWED_FAILURE_TYPES = ALLOWED_MICRO_FAILURE_TYPES
REASONING_FAILURES = MICRO_REASONING_FAILURES


# -------------------------------------------------
# STRUCTURAL (DOCUMENT-LEVEL) REASONING FAILURES
# -------------------------------------------------

ALLOWED_STRUCTURAL_FAILURE_TYPES = [
    "OBJECTIVE_OVERLOADING",
    "MEANS_ENDS_MISMATCH",
    "UNBOUNDED_DEFINITIONS",
    "SAFEGUARD_DILUTION",
    "TEMPORAL_INCOHERENCE",
]

STRUCTURAL_REASONING_FAILURES = {
    "OBJECTIVE_OVERLOADING": {
        "name": "Objective Overloading",
        "description": (
            "A single stated objective is used to justify multiple heterogeneous "
            "interventions without demonstrating necessity for each."
        ),
        "severity": "high",
        "actionability": "fix_now",
    },
    "MEANS_ENDS_MISMATCH": {
        "name": "Means–Ends Mismatch",
        "description": (
            "The proposed mechanism does not plausibly or directly advance the stated "
            "objective, or the causal chain is missing."
        ),
        "severity": "high",
        "actionability": "needs_research",
    },
    "UNBOUNDED_DEFINITIONS": {
        "name": "Unbounded Definitions",
        "description": (
            "Key terms are defined expansively without limiting principles, thresholds, "
            "or boundary tests, creating over-capture risk."
        ),
        "severity": "high",
        "actionability": "fix_now",
    },
    "SAFEGUARD_DILUTION": {
        "name": "Safeguard Dilution",
        "description": (
            "Procedural protections are reduced or removed without justification "
            "addressing necessity, proportionality, or error costs."
        ),
        "severity": "high",
        "actionability": "fix_now",
    },
    "TEMPORAL_INCOHERENCE": {
        "name": "Temporal Incoherence",
        "description": (
            "Past conduct is captured or reclassified through present standards "
            "without explicit transitional reasoning."
        ),
        "severity": "medium",
        "actionability": "needs_research",
    },
}


# -------------------------------------------------
# PROMPT TAXONOMY TEXT
# -------------------------------------------------

def get_taxonomy_prompt_text() -> str:
    """
    Returns the full taxonomy text injected into the analysis prompt.
    This text defines the ONLY allowed failure types the model may use.
    """

    lines = []

    lines.append("ALLOWED MICRO REASONING FAILURE TYPES (sentence- or paragraph-level):")

    for ftype in ALLOWED_MICRO_FAILURE_TYPES:
        failure = MICRO_REASONING_FAILURES[ftype]
        lines.append(f"\n- {ftype}: {failure['description']}")
        lines.append(f"  Example: {failure['example']}")

    lines.append("\n\nALLOWED STRUCTURAL REASONING FAILURE TYPES (document-level):")

    for ftype in ALLOWED_STRUCTURAL_FAILURE_TYPES:
        failure = STRUCTURAL_REASONING_FAILURES[ftype]
        lines.append(f"\n- {ftype}: {failure['description']}")

    return "\n".join(lines)
