# app.py
import hashlib
import hmac
import streamlit as st
import PyPDF2
import io

ANALYZER_VERSION = "openai-2026-01-11-v3"
TAXONOMY_VERSION = "v3"  # bump when prompts/taxonomy changes

def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

# -----------------------------
# Password protection
# -----------------------------
def check_password() -> bool:
    def password_entered():
        if hmac.compare_digest(st.session_state["password"], st.secrets["APP_PASSWORD"]):
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    st.text_input("Password", type="password", on_change=password_entered, key="password")

    if "password_correct" in st.session_state and not st.session_state["password_correct"]:
        st.error("😕 Password incorrect")

    return False

# IMPORTANT: gate everything behind password so secrets/analyzer aren't touched first
if not check_password():
    st.stop()

# -----------------------------
# Analyzer (cached)
# -----------------------------
@st.cache_resource
def get_analyzer(version: str):
    from analyzer import ValidityAnalyzer
    return ValidityAnalyzer()

try:
    analyzer = get_analyzer(ANALYZER_VERSION)
except Exception as e:
    st.error("Analyzer failed to initialize. Check Streamlit logs for the traceback.")
    st.exception(e)
    st.stop()

# Optional: quick visibility of what got deployed
import analyzer as _a
st.caption(f"Analyzer loaded from: {_a.__file__} | version: {ANALYZER_VERSION}")

# -----------------------------
# Session state
# -----------------------------
if "is_running" not in st.session_state:
    st.session_state["is_running"] = False
if "last_result" not in st.session_state:
    st.session_state["last_result"] = None
if "last_doc_hash" not in st.session_state:
    st.session_state["last_doc_hash"] = None
if "doc_text" not in st.session_state:
    st.session_state["doc_text"] = ""

# -----------------------------
# UI
# -----------------------------
st.title("🔍 Validity")
st.caption("Reasoning quality verification — infrastructure for high-stakes decisions")

tab1, tab2 = st.tabs(["Analyze", "Examples"])

with tab1:
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("Input Document")

        # Handle file upload FIRST, before text_area
        uploaded = st.file_uploader("Upload a .txt/.md/.pdf file", type=["txt", "md", "pdf"])
        
        # Process uploaded file
        uploaded_text = None
        if uploaded:
            if uploaded.type == "application/pdf":
                try:
                    pdf_reader = PyPDF2.PdfReader(io.BytesIO(uploaded.read()))
                    text = ""
                    for page in pdf_reader.pages:
                        text += page.extract_text() + "\n"
                    uploaded_text = text
                    st.success(f"✅ PDF loaded ({len(text)} characters)")
                except Exception as e:
                    st.error(f"Error reading PDF: {str(e)}")
                    st.stop()
            else:
                # Handle text files
                text = uploaded.read().decode("utf-8", errors="ignore")
                uploaded_text = text
                st.success(f"✅ File loaded ({len(text)} characters)")
        
        # Show text area with uploaded content or existing content
        if uploaded_text:
            default_text = uploaded_text
        else:
            default_text = st.session_state.get("doc_text", "")
        
        doc_input = st.text_area(
            "Or paste text to analyze",
            value=default_text,
            height=380,
            placeholder="Investment memo, legal brief, policy document, etc.",
        )
        
        # Store the current text
        st.session_state["doc_text"] = doc_input

        run = st.button(
            "🔍 Analyze Reasoning",
            type="primary",
            use_container_width=True,
            disabled=st.session_state["is_running"],
        )

    with col2:
        st.subheader("Analysis Results")

        if run:
            MAX_CHARS = 80_000
            document_text = st.session_state.get("doc_text", "")

            # Safety reset (prevents "stuck loading" from reruns)
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

            is_cached = (
                st.session_state["last_doc_hash"] == doc_hash
                and st.session_state["last_result"] is not None
            )

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
                finally:
                    st.session_state["is_running"] = False

            if not result.get("success"):
                st.error(f"Analysis failed: {result.get('error', 'Unknown error')}")
                # Show debug errors if analyzer provided them
                dbg = result.get("debug_errors")
                if dbg:
                    with st.expander("Debug (first errors)"):
                        for x in dbg:
                            st.code(str(x))
                st.stop()

            data = result["analysis"]

            score = data.get("reasoning_score", "N/A")
            risk = (data.get("decision_risk") or "low").upper()

            if isinstance(score, (int, float)):
                score_color = "🟢" if score >= 80 else "🟡" if score >= 60 else "🔴"
            else:
                score_color = "⚪"

            st.metric("Reasoning Score", f"{score_color} {score}/100")

            risk_colors = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}
            st.write(f"**Decision Risk:** {risk_colors.get(risk, '⚪')} {risk}")

            flags = data.get("top_risk_flags", [])
            if flags:
                flags_formatted = ", ".join([f.replace("_", " ").title() for f in flags])
                st.write(f"**Top Risk Flags:** {flags_formatted}")
            else:
                st.write("**Top Risk Flags:** None")

            chunks_total = result.get("chunks_analyzed", 0)
            chunks_ok = result.get("chunks_succeeded", 0)
            chunks_fail = result.get("chunks_failed", 0)
            analysis_time = result.get("analysis_time", 0)

            if chunks_total > 1:
                stats = f"Analyzed {chunks_ok}/{chunks_total} sections"
                if chunks_fail > 0:
                    stats += f" ({chunks_fail} failed)"
                stats += f" in {analysis_time}s"
                st.caption(stats)

            st.divider()

            failures = data.get("failures_detected", [])
            total_failures = data.get("total_failures_detected", len(failures))

            if not failures:
                st.success("✅ No reasoning failures detected from taxonomy")
            else:
                st.write(f"### Findings ({len(failures)} shown of {total_failures} total)")
                for i, f in enumerate(failures, 1):
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
                formatted = analyzer.format_output(result)
                st.code(formatted, language=None)
                st.download_button(
                    label="📥 Download Full Report",
                    data=formatted,
                    file_name="validity_analysis.txt",
                    mime="text/plain",
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
        st.rerun()