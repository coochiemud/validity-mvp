# app.py
import os
import hashlib
import hmac
import io

import streamlit as st
import PyPDF2

ANALYZER_VERSION = "openai-2026-01-11-v3"
TAXONOMY_VERSION = "v3"  # bump when prompts/taxonomy changes


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


# -----------------------------
# Custom CSS for Validity branding - EXACT match to landing page
# -----------------------------
st.markdown(
    """
<style>
    /* Import fonts */
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Inter:wght@400;500;600;700&family=Sora:wght@400;600;700&display=swap');
    
    /* Main app styling */
    .stApp {
        background: #0a1628;
        color: #f8fafc;
        font-family: 'Inter', sans-serif;
    }
    
    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* Headers */
    h1, h2, h3 {
        font-family: 'Sora', sans-serif !important;
        color: #f8fafc !important;
        letter-spacing: -0.02em !important;
    }
    
    /* Text input for password */
    .stTextInput input {
        background: rgba(30, 47, 72, 0.4) !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        color: #f8fafc !important;
    }
    
    /* Validity Analysis Container - matches landing page exactly */
    .validity-container {
        background: rgba(22, 34, 56, 0.6);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 16px;
        padding: 3rem;
        position: relative;
        overflow: hidden;
        backdrop-filter: blur(10px);
        margin-top: 2rem;
    }
    
    .validity-container::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 4px;
        background: linear-gradient(90deg, #ef4444, #f59e0b, #10b981);
    }
    
    .output-header {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.85rem;
        text-transform: uppercase;
        letter-spacing: 0.15em;
        color: #94a3b8;
        margin-bottom: 2.5rem;
        padding-bottom: 1.5rem;
        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    }
    
    .output-meta {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 2rem;
        margin-bottom: 3rem;
    }
    
    .meta-item {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }
    
    .meta-label {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: #64748b;
    }
    
    .meta-value {
        font-size: 1.1rem;
        font-weight: 600;
        color: #f8fafc;
    }
    
    .risk-badge {
        display: inline-flex;
        align-items: center;
        gap: 0.5rem;
        background: rgba(245, 158, 11, 0.15);
        color: #f59e0b;
        padding: 0.5rem 1rem;
        border-radius: 6px;
        border: 1px solid rgba(245, 158, 11, 0.3);
        font-size: 0.95rem;
        width: fit-content;
    }
    
    .score-value {
        font-size: 2.5rem;
        font-weight: 700;
        background: linear-gradient(135deg, #ef4444, #f59e0b);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        line-height: 1;
    }
    
    .score-bar {
        width: 200px;
        height: 8px;
        background: rgba(255, 255, 255, 0.1);
        border-radius: 4px;
        overflow: hidden;
        margin-top: 0.5rem;
    }
    
    .score-fill {
        height: 100%;
        background: linear-gradient(90deg, #ef4444, #f59e0b);
        border-radius: 4px;
    }
    
    .issues-section {
        margin-top: 2.5rem;
    }
    
    .issues-title {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.85rem;
        text-transform: uppercase;
        letter-spacing: 0.15em;
        color: #f8fafc;
        margin-bottom: 1.5rem;
        font-weight: 600;
    }
    
    .issue-item {
        background: rgba(10, 22, 40, 0.5);
        border-left: 3px solid var(--issue-color);
        border-radius: 6px;
        padding: 1.5rem;
        margin-bottom: 1rem;
    }
    
    .issue-header {
        display: flex;
        align-items: center;
        gap: 1rem;
        margin-bottom: 0.75rem;
    }
    
    .severity-badge {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.7rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        padding: 0.35rem 0.75rem;
        border-radius: 4px;
    }
    
    .severity-high {
        background: rgba(239, 68, 68, 0.2);
        color: #ef4444;
    }
    
    .severity-medium {
        background: rgba(245, 158, 11, 0.2);
        color: #f59e0b;
    }

    .severity-low {
        background: rgba(148, 163, 184, 0.16);
        color: #94a3b8;
    }

    .severity-critical {
        background: rgba(239, 68, 68, 0.28);
        color: #ef4444;
    }
    
    .issue-title {
        font-size: 1.1rem;
        font-weight: 600;
        color: #f8fafc;
        margin: 0;
    }
    
    .issue-description {
        color: #cbd5e1;
        line-height: 1.6;
        font-size: 0.95rem;
    }
    
    /* Input section styling */
    .stTextArea textarea {
        background: rgba(30, 47, 72, 0.4) !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 8px !important;
        color: #f8fafc !important;
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.9rem !important;
    }
    
    .stFileUploader {
        background: rgba(30, 47, 72, 0.4) !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 12px !important;
        padding: 1.5rem !important;
    }
    
    .stButton > button {
        background: rgba(255, 255, 255, 0.08) !important;
        color: #f8fafc !important;
        border: 1px solid rgba(255, 255, 255, 0.4) !important;
        border-radius: 4px !important;
        padding: 1rem 2rem !important;
        font-weight: 600 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.05em !important;
        font-family: 'Inter', sans-serif !important;
        width: 100% !important;
    }
    
    .stButton > button:hover {
        background: rgba(255, 255, 255, 0.12) !important;
        border-color: rgba(255, 255, 255, 0.6) !important;
    }
    
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 2rem;
        background: transparent !important;
        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    }
    
    .stTabs [data-baseweb="tab"] {
        background: transparent !important;
        color: #94a3b8 !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 600 !important;
        font-size: 1rem !important;
        padding: 1rem 0 !important;
    }
    
    .stTabs [aria-selected="true"] {
        color: #f8fafc !important;
        border-bottom: 2px solid #ef4444 !important;
    }
</style>
""",
    unsafe_allow_html=True,
)


# -----------------------------
# Password protection
# -----------------------------
def check_password() -> bool:
    def password_entered():
        if hmac.compare_digest(
            st.session_state.get("password", ""),
            st.secrets.get("APP_PASSWORD", ""),
        ):
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
if "large_mode" not in st.session_state:
    st.session_state["large_mode"] = False


# -----------------------------
# Helpers (chunking + merge)
# -----------------------------
def chunk_text(text: str, size: int):
    return [text[i : i + size] for i in range(0, len(text), size)]


def risk_rank(r: str) -> int:
    r = (r or "").lower()
    return {"low": 1, "medium": 2, "high": 3, "critical": 4}.get(r, 2)


def sev_rank(s: str) -> int:
    s = (s or "").lower()
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(s, 2)


def merge_analyses(analyses: list) -> dict:
    """Simple, safe merge: avg score, worst risk, concat failures sorted by severity."""
    if not analyses:
        return {}

    avg_score = int(sum(a.get("reasoning_score", 0) for a in analyses) / len(analyses))
    worst = max(analyses, key=lambda a: risk_rank(a.get("decision_risk")))
    worst_risk = (worst.get("decision_risk") or "medium").lower()

    all_failures = []
    for a in analyses:
        all_failures.extend(a.get("failures_detected", []) or [])
    all_failures.sort(key=lambda f: sev_rank(f.get("severity")), reverse=True)

    merged = dict(analyses[0])
    merged["reasoning_score"] = avg_score
    merged["decision_risk"] = worst_risk
    merged["failures_detected"] = all_failures
    merged["total_failures_detected"] = len(all_failures)
    return merged


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

        uploaded = st.file_uploader("Upload a .txt/.md/.pdf file", type=["txt", "md", "pdf"])

        uploaded_text = None
        if uploaded:
            if uploaded.type == "application/pdf":
                try:
                    pdf_reader = PyPDF2.PdfReader(io.BytesIO(uploaded.read()))
                    text = ""
                    for page in pdf_reader.pages:
                        text += (page.extract_text() or "") + "\n"
                    uploaded_text = text
                    st.success(f"✅ PDF loaded ({len(text):,} characters)")
                except Exception as e:
                    st.error(f"Error reading PDF: {str(e)}")
                    st.stop()
            else:
                text = uploaded.read().decode("utf-8", errors="ignore")
                uploaded_text = text
                st.success(f"✅ File loaded ({len(text):,} characters)")

        default_text = uploaded_text if uploaded_text else st.session_state.get("doc_text", "")

        doc_input = st.text_area(
            "Or paste text to analyze",
            value=default_text,
            height=380,
            placeholder="Investment memo, legal brief, policy document, etc.",
        )

        st.session_state["doc_text"] = doc_input

        wc = len((doc_input or "").split())
        st.caption(f"Length: ~{wc:,} words • {len(doc_input):,} characters")

        st.session_state["large_mode"] = st.toggle(
            "Large Document Mode (slower, higher cost)",
            value=st.session_state.get("large_mode", False),
            help="Enables analysis of much larger documents. Large docs will be split into chunks and merged.",
        )

        run = st.button(
            "🔍 Analyze Reasoning",
            type="primary",
            disabled=st.session_state["is_running"],
        )

    with col2:
        st.subheader("Analysis Results")

        if run:
            # Configurable caps:
            # - Standard: 300k chars by default
            # - Absolute: 1.2M chars hard stop safety
            STANDARD_MAX_CHARS = int(os.getenv("VALIDITY_MAX_CHARS", "300000"))
            ABSOLUTE_MAX_CHARS = int(os.getenv("VALIDITY_ABSOLUTE_MAX_CHARS", "1200000"))
            CHUNK_SIZE = int(os.getenv("VALIDITY_CHUNK_SIZE", "25000"))

            document_text = st.session_state.get("doc_text", "")

            # Safety reset (prevents stale lock from causing a rerun loop)
            st.session_state["is_running"] = False

            if not document_text or len(document_text.strip()) < 50:
                st.error("Please provide at least 50 characters of text.")
                st.stop()

            doc_len = len(document_text)

            # Absolute hard stop
            if doc_len > ABSOLUTE_MAX_CHARS:
                st.error(
                    f"Document too long ({doc_len:,} chars). Absolute max is {ABSOLUTE_MAX_CHARS:,}. "
                    "Please shorten or split the document."
                )
                st.stop()

            # Standard cap unless Large Mode enabled
            if (not st.session_state.get("large_mode", False)) and doc_len > STANDARD_MAX_CHARS:
                st.error(
                    f"Document too long for standard mode ({doc_len:,} chars). "
                    f"Standard max is {STANDARD_MAX_CHARS:,}. "
                    "Enable **Large Document Mode** to analyze bigger documents."
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
            else:
                st.session_state["is_running"] = True
                try:
                    with st.spinner("Analyzing reasoning structure..."):
                        # Chunk only when large mode AND doc exceeds standard cap
                        if st.session_state.get("large_mode", False) and doc_len > STANDARD_MAX_CHARS:
                            chunks = chunk_text(document_text, CHUNK_SIZE)
                            st.warning(
                                f"Large document mode enabled. Splitting into {len(chunks)} chunks "
                                f"(~{CHUNK_SIZE:,} chars each)."
                            )

                            analyses = []
                            failed = 0

                            for ch in chunks:
                                r = analyzer.analyze(ch)
                                if r.get("success") and r.get("analysis"):
                                    analyses.append(r["analysis"])
                                else:
                                    failed += 1

                            if not analyses:
                                result = {"success": False, "error": "All chunks failed to analyze."}
                            else:
                                merged = merge_analyses(analyses)
                                result = {"success": True, "analysis": merged, "error": None}
                                if failed:
                                    st.info(f"Note: {failed} chunk(s) failed and were skipped.")
                        else:
                            result = analyzer.analyze(document_text)

                    st.session_state["last_result"] = result
                    st.session_state["last_doc_hash"] = doc_hash
                finally:
                    st.session_state["is_running"] = False

            if not result.get("success"):
                st.error(f"Analysis failed: {result.get('error', 'Unknown error')}")
                st.stop()

            data = result["analysis"]
            score = int(data.get("reasoning_score", 0) or 0)
            risk = (data.get("decision_risk") or "medium").upper()
            failures = data.get("failures_detected", []) or []

            # Display in landing page format
            st.markdown(
                f"""
            <div class="validity-container">
                <div class="output-header">VALIDITY ANALYSIS — EXECUTIVE SUMMARY (AUTOMATED LOGIC AUDIT)</div>
                
                <div class="output-meta">
                    <div class="meta-item">
                        <div class="meta-label">Document Type</div>
                        <div class="meta-value">Investment Memorandum</div>
                    </div>
                    <div class="meta-item">
                        <div class="meta-label">Risk Classification</div>
                        <div class="meta-value">
                            <span class="risk-badge">
                                <span>⚠️</span>
                                <span>{risk.title()}</span>
                            </span>
                        </div>
                    </div>
                    <div class="meta-item">
                        <div class="meta-label">Reasoning Quality</div>
                        <div class="meta-value">
                            <div class="score-value">{score}/100</div>
                            <div class="score-bar">
                                <div class="score-fill" style="width: {max(0, min(100, score))}%;"></div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="issues-section">
                    <div class="issues-title">Critical Issues Identified</div>
            """,
                unsafe_allow_html=True,
            )

            if not failures:
                st.markdown(
                    '<p style="color: #10b981;">✅ No critical reasoning failures detected</p>',
                    unsafe_allow_html=True,
                )
            else:
                for f in failures[:3]:
                    sev = (f.get("severity") or "medium").upper()
                    ftype = (f.get("type") or "").replace("_", " ").title()
                    explanation = f.get("explanation") or "No explanation provided"

                    border_color = "#ef4444" if sev in ("HIGH", "CRITICAL") else "#f59e0b"

                    st.markdown(
                        f"""
                    <div class="issue-item" style="--issue-color: {border_color};">
                        <div class="issue-header">
                            <span class="severity-badge severity-{sev.lower()}">{sev}</span>
                            <h4 class="issue-title">{ftype}</h4>
                        </div>
                        <p class="issue-description">{explanation}</p>
                    </div>
                    """,
                        unsafe_allow_html=True,
                    )

            st.markdown("</div></div>", unsafe_allow_html=True)

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
