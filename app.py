# app.py
import hashlib
import hmac
import streamlit as st


# Bump this when analyzer implementation changes (forces cache refresh)
ANALYZER_VERSION = "openai-2026-01-11-v3"

# Bump this when prompt/taxonomy/failure library changes (forces doc-result cache refresh)
TAXONOMY_VERSION = "v3"


@st.cache_resource
def get_analyzer(version: str):
    # version param intentionally unused in body — it's for cache busting
    from analyzer import ValidityAnalyzer
    return ValidityAnalyzer()


analyzer = get_analyzer(ANALYZER_VERSION)

# Debug visibility: confirm which module is actually being imported on Streamlit Cloud
try:
    import analyzer as _a
    st.caption(f"Analyzer loaded from: {_a.__file__} | analyzer_version: {ANALYZER_VERSION} | taxonomy_version: {TAXONOMY_VERSION}")
except Exception:
    st.caption(f"Analyzer loaded | analyzer_version: {ANALYZER_VERSION} | taxonomy_version: {TAXONOMY_VERSION}")


def stable_hash(text: str) -> str:
    """Stable hash that doesn't change between runs"""
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def check_password() -> bool:
    """Returns True if the user entered the correct password."""
    def password_entered():
        if hmac.compare_digest(st.session_state.get("password", ""), st.secrets.get("APP_PASSWORD", "")):
            st.session_state["password_correct"] = True
            if "password" in st.session_state:
                del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    st.text_input("Password", type="password", on_change=password_entered, key="password")

    if "password_correct" in st.session_state and not st.session_state["password_correct"]:
        st.error("😕 Password incorrect")

    return False


# --- Guard: password required ---
if not check_password():
    st.stop()


# --- Session state init ---
if "is_running" not in st.session_state:
    st.session_state["is_running"] = False
if "doc_text" not in st.session_state:
    st.session_state["doc_text"] = ""
if "last_result" not in st.session_state:
    st.session_state["last_result"] = None
if "last_doc_hash" not in st.session_state:
    st.session_state["last_doc_hash"] = None


# --- Header ---
st.title("🔍 Validity")
st.caption("Reasoning quality verification — infrastructure for high-stakes decisions")


# --- Helpers ---
def reset_session():
    st.session_state["is_running"] = False
    st.session_state["doc_text"] = ""
    st.session_state["last_result"] = None
    st.session_state["last_doc_hash"] = None
    st.rerun()


# Top bar controls
top_left, top_right = st.columns([1, 1])
with top_left:
    st.write("")
with top_right:
    if st.button("↻ Reset session", use_container_width=True):
        reset_session()


tab1, tab2 = st.tabs(["Analyze", "Examples"])

with tab1:
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("Input Document")

        st.text_area(
            "Paste text to analyze",
            key="doc_text",
            height=380,
            placeholder="Investment memo, legal brief, policy document, etc."
        )

        uploaded = st.file_uploader("...or upload a .txt/.md file", type=["txt", "md"])
        if uploaded:
            st.session_state["is_running"] = False
            st.session_state["doc_text"] = uploaded.read().decode("utf-8", errors="ignore")
            st.session_state["last_result"] = None
            st.session_state["last_doc_hash"] = None
            st.rerun()

        run = st.button(
            "🔍 Analyze Reasoning",
            type="primary",
            use_container_width=True,
            disabled=st.session_state["is_running"]
        )

    with col2:
        st.subheader("Analysis Results")

        if run:
            MAX_CHARS = 80_000
            document_text = st.session_state.get("doc_text", "")

            # Safety reset in case Streamlit rerun left stale lock
            st.session_state["is_running"] = False

            if not document_text or len(document_text.strip()) < 50:
                st.error("Please provide at least 50 characters of text.")
                st.stop()

            if len(document_text) > MAX_CHARS:
                st.error(
                    f"Document too long ({len(document_text):,} chars). Max is {MAX_CHARS:,}. "
                    "Trim the input or analyze a smaller section."
                )
                st.stop()

            MODEL = getattr(analyzer, "model", "unknown")
            doc_hash = stable_hash(f"{TAXONOMY_VERSION}|{MODEL}|{document_text}")

            is_cached = (st.session_state["last_doc_hash"] == doc_hash and st.session_state["last_result"] is not None)

            if is_cached:
                result = st.session_state["last_result"]
                st.caption("⚡ Showing cached result for identical input")
            else:
                st.session_state["is_running"] = True
                try:
                    with st.spinner("Analyzing reasoning structure..."):
                        result = analyzer.analyze(document_text)
                    st.session_state["last_result"] = result
                    st.session_state["last_doc_hash"] = doc_hash
                except Exception as e:
                    st.error(f"Analysis crashed: {e}")
                    st.stop()
                finally:
                    st.session_state["is_running"] = False

            # Defensive handling
            if not isinstance(result, dict):
                st.error("Analysis failed: Analyzer returned an invalid response (not a dict).")
                st.stop()

            if not result.get("success"):
                st.error(f"Analysis failed: {result.get('error', 'Unknown error')}")
                st.stop()

            data = result.get("analysis") or {}
            if not isinstance(data, dict):
                st.error("Analysis failed: Analyzer returned invalid analysis payload.")
                st.stop()

            # --- Summary metrics ---
            score = data.get("reasoning_score", "N/A")
            risk = (data.get("decision_risk") or "low").upper()

            if isinstance(score, (int, float)):
                if score >= 80:
                    score_color = "🟢"
                elif score >= 60:
                    score_color = "🟡"
                else:
                    score_color = "🔴"
            else:
                score_color = "⚪"

            st.metric("Reasoning Score", f"{score_color} {score}/100")

            risk_colors = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}
            st.write(f"**Decision Risk:** {risk_colors.get(risk, '⚪')} {risk}")

            flags = data.get("top_risk_flags", [])
            if flags:
                flags_formatted = ", ".join([str(f).replace("_", " ").title() for f in flags])
                st.write(f"**Top Risk Flags:** {flags_formatted}")
            else:
                st.write("**Top Risk Flags:** None")

            # Chunk stats (if analyzer uses chunking)
            chunks_total = result.get("chunks_analyzed", 0)
            chunks_ok = result.get("chunks_succeeded", 0)
            chunks_fail = result.get("chunks_failed", 0)
            analysis_time = result.get("analysis_time", 0)

            if chunks_total and chunks_total > 1:
                stats = f"Analyzed {chunks_ok}/{chunks_total} sections"
                if chunks_fail:
                    stats += f" ({chunks_fail} failed)"
                stats += f" in {analysis_time}s"
                st.caption(stats)

            st.divider()

            # --- Findings: show ALL failures returned ---
            failures = data.get("failures_detected", [])
            if not isinstance(failures, list):
                failures = []

            total_failures = data.get("total_failures_detected", len(failures))

            if not failures:
                st.success("✅ No reasoning failures detected from taxonomy")
            else:
                header = f"### Findings ({len(failures)} shown"
                if total_failures > len(failures):
                    header += f" of {total_failures} total"
                header += ")"
                st.write(header)

                for i, f in enumerate(failures, 1):
                    if not isinstance(f, dict):
                        continue

                    sev = (f.get("severity") or "medium").upper()
                    action = (f.get("actionability") or "review").upper()
                    ftype = (f.get("type") or "").replace("_", " ").title()
                    location = f.get("location") or "Location not specified"
                    explanation = f.get("explanation") or "No explanation provided"

                    severity_icon = "🔴" if sev == "CRITICAL" else "🟠" if sev == "HIGH" else "🟡"

                    with st.expander(f"{severity_icon} {i}. {ftype} — {sev} — [{action}]"):
                        st.write("**Location in text:**")
                        st.info(location)
                        st.write("**Why this matters:**")
                        st.write(explanation)

            st.divider()

            with st.expander("📄 View full formatted report"):
                try:
                    formatted = analyzer.format_output(result)
                except Exception:
                    formatted = str(result)

                st.code(formatted, language=None)

                st.download_button(
                    label="📥 Download Full Report",
                    data=formatted,
                    file_name="validity_analysis.txt",
                    mime="text/plain"
                )

        else:
            st.info("👈 Paste a document and click 'Analyze Reasoning' to begin")


with tab2:
    st.subheader("Example Documents")
    st.write("Try these examples to see how Validity detects reasoning failures:")

    example = st.selectbox(
        "Select an example:",
        ["Flawed Investment Memo", "Sound Policy Recommendation", "Mixed Market Analysis"],
    )

    examples = {
        "Flawed Investment Memo": """Investment Thesis: AcmeCorp

We should invest $5M in AcmeCorp because they are disrupting the enterprise software market.

Market Opportunity: The enterprise software market is worth $500B and growing at 15% annually.
If AcmeCorp captures just 1% of this market, they will generate $5B in revenue.

Competitive Advantage: AcmeCorp has a unique approach that competitors cannot replicate.
Their team has deep expertise in the space, having worked at major tech companies.

Traction: Customer acquisition costs have been rising over the past 6 months, demonstrating
strong product-market fit. The company has shown consistent growth in user signups.

Therefore, we recommend a $5M investment at a $50M valuation.""",

        "Sound Policy Recommendation": """Recommendation: Implement Variable Speed Limits in School Zones

Problem: Current fixed 25mph speed limits in school zones are enforced 24/7, including
nights, weekends, and holidays when no children are present.

Evidence: Traffic analysis shows:
- 89% of speeding violations occur outside school hours
- Average speeds during school hours: 28mph (slight violation)
- Average speeds at night: 42mph (significant violation)
- Zero child pedestrian incidents have occurred outside 7am-4pm in past 5 years

Proposed Solution: Variable speed limits:
- 15mph during school arrival/dismissal (7-9am, 2-4pm)
- 25mph during school hours (9am-2pm)
- 35mph outside school hours

Expected Outcomes:
- Reduced speeding violations (addresses actual high-speed behavior)
- Maintained child safety during relevant hours
- Improved compliance through reasonable restrictions

Counterfactual Considered: Maintaining status quo would continue high violation rates
without additional safety benefit. Alternative of increased enforcement was rejected
due to resource constraints and limited impact on nighttime speeding.""",

        "Mixed Market Analysis": """Q4 2024 Market Analysis: Renewable Energy Sector

Thesis: Renewable energy stocks will outperform the S&P 500 in 2025.

Supporting Factors:
1. Government policy: New federal tax credits provide 30% subsidy for solar installations
2. Technology trends: Solar panel efficiency has improved 40% since 2020
3. Market demand: Corporate renewable commitments have doubled year-over-year

However, the sector faces headwinds:
- Interest rates remain elevated, increasing project financing costs
- Supply chain constraints persist for key components
- Some analysts predict oversupply in 2025

Despite these challenges, the long-term outlook remains positive because governments
globally are committed to carbon reduction. This means renewable energy is the future.

Recommendation: Overweight renewable energy stocks by 15% relative to market cap weight.""",
    }

    st.code(examples[example], language=None)

    if st.button("Load this example into analyzer"):
        st.session_state["doc_text"] = examples[example]
        st.session_state["last_result"] = None
        st.session_state["last_doc_hash"] = None
        st.rerun()
