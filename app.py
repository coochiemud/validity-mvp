# app.py
from __future__ import annotations

import hashlib
import io
import json
import time
from typing import Any, Dict

import streamlit as st

from analyzer import ValidityAnalyzer

# Optional PDF extraction (works if installed)
try:
    from pypdf import PdfReader  # type: ignore
except Exception:
    PdfReader = None  # type: ignore

# Optional: PDF export styling
try:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.styles import ParagraphStyle
except Exception:
    LETTER = None  # type: ignore


# -----------------------------
# Config
# -----------------------------

APP_NAME = "Validity"
MODEL = "gpt-4o"  # display only; actual model comes from secrets/env in analyzer.py
TAXONOMY_VERSION = "v2"  # bump when prompt/taxonomy changes to invalidate caches

# Safe analysis limits
RECOMMENDED_MAX_CHARS = 80_000
HARD_MAX_CHARS = 500_000  # hard-stop extreme inputs


# -----------------------------
# Helpers
# -----------------------------

def stable_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    if PdfReader is None:
        raise RuntimeError("PDF extraction requires pypdf. Install with: pip install pypdf")

    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            parts.append("")
    text = "\n".join(parts)
    # Basic cleanup for repeated whitespace
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return text


def build_markdown_report(analysis: Dict[str, Any], meta: Dict[str, Any]) -> str:
    thesis = analysis.get("thesis", {}) or {}
    logical_chain = analysis.get("logical_chain", {}) or {}
    micro = analysis.get("micro_failures", analysis.get("failures_detected", [])) or []
    structural = analysis.get("structural_failures", []) or []
    strengths = analysis.get("strengths_detected", []) or []
    overall = analysis.get("overall_assessment", {}) or {}

    md = []
    md.append("# Validity Report\n\n")
    md.append(f"**Generated:** {meta.get('generated_at', '')}\n\n")
    md.append(
        f"**Chunks analyzed:** {meta.get('chunks_analyzed', '')} "
        f"(succeeded: {meta.get('chunks_succeeded', '')}, failed: {meta.get('chunks_failed', '')})\n\n"
    )
    md.append(f"**Decision risk:** {analysis.get('decision_risk', '')}\n\n")
    md.append(f"**Reasoning score:** {analysis.get('reasoning_score', '')}\n\n")
    md.append("\n---\n\n")

    md.append("## Thesis\n\n")
    md.append(f"- **Statement:** {thesis.get('statement', '')}\n")
    md.append(f"- **Explicitness:** {thesis.get('explicitness', 'unclear')}\n\n")

    md.append("## Logical Chain\n\n")
    steps = logical_chain.get("steps", []) or []
    if steps:
        for i, s in enumerate(steps, 1):
            md.append(f"{i}. {s}\n")
    md.append(f"\n**Conclusion:** {logical_chain.get('conclusion','')}\n\n")

    breaks = logical_chain.get("breaks", []) or []
    if breaks:
        md.append("**Breaks / gaps:**\n")
        for b in breaks:
            md.append(f"- {b}\n")
        md.append("\n")

    md.append("## Structural Failures (Document-Level)\n\n")
    if not structural:
        md.append("- None detected.\n\n")
    else:
        for f in structural:
            md.append(f"### {f.get('type','')}\n")
            md.append(f"- **Severity:** {f.get('severity','')}\n")
            md.append(f"- **Confidence:** {f.get('confidence','')}\n")
            if f.get("location_hint"):
                md.append(f"- **Location:** {f.get('location_hint')}\n")
            if f.get("why_it_matters"):
                md.append(f"- **Why it matters:** {f.get('why_it_matters')}\n")
            ev = f.get("evidence", []) or []
            if ev:
                md.append("- **Evidence:**\n")
                for e in ev:
                    md.append(f"  - “{e}”\n")
            if f.get("fix"):
                md.append(f"- **Fix:** {f.get('fix')}\n")
            md.append("\n")

    md.append("## Micro Failures (Local)\n\n")
    if not micro:
        md.append("- None detected.\n\n")
    else:
        for f in micro:
            md.append(f"- **{f.get('type','')}**\n")
            if f.get("location"):
                md.append(f"  - Location: “{f.get('location')}”\n")
            if f.get("explanation"):
                md.append(f"  - Explanation: {f.get('explanation')}\n")
            md.append("\n")

    md.append("## Strengths Detected\n\n")
    if not strengths:
        md.append("- None listed.\n\n")
    else:
        for s in strengths:
            md.append(f"- **{s.get('type','')}**: {s.get('description','')}\n")
        md.append("\n")

    md.append("## Overall Assessment\n\n")
    md.append(f"- **Confidence:** {overall.get('confidence','')}\n")
    md.append(f"- **Summary:** {overall.get('summary','')}\n")

    return "".join(md)


def markdown_to_pdf_bytes(md: str, title: str = "Validity Report") -> bytes:
    if LETTER is None:
        raise RuntimeError("PDF export requires reportlab. Install with: pip install reportlab")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title=title,
    )

    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        name="Body",
        parent=styles["BodyText"],
        fontSize=10.5,
        leading=13,
        alignment=TA_LEFT,
    )
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    h3 = styles["Heading3"]

    story = []
    for raw_line in md.splitlines():
        line = raw_line.strip()
        if not line:
            story.append(Spacer(1, 8))
            continue
        if line.startswith("# "):
            story.append(Paragraph(line[2:], h1))
            story.append(Spacer(1, 8))
        elif line.startswith("## "):
            story.append(Paragraph(line[3:], h2))
            story.append(Spacer(1, 6))
        elif line.startswith("### "):
            story.append(Paragraph(line[4:], h3))
            story.append(Spacer(1, 4))
        elif line.startswith("- "):
            story.append(Paragraph("• " + line[2:], body))
        elif line[:2].isdigit() and line[2:4] == ". ":
            story.append(Paragraph(line, body))
        else:
            # Light bold conversion: first **pair** only
            safe = line
            if safe.count("**") >= 2:
                safe = safe.replace("**", "<b>", 1).replace("**", "</b>", 1)
            story.append(Paragraph(safe, body))

    doc.build(story)
    return buf.getvalue()


def render_failures_table_structural(structural: list[dict]) -> None:
    for f in structural:
        title = (
            f"{f.get('type','')}  •  "
            f"{f.get('severity','')} severity  •  "
            f"{f.get('confidence','')} confidence"
        )
        with st.expander(title, expanded=False):
            if f.get("why_it_matters"):
                st.markdown(f"**Why it matters:** {f.get('why_it_matters')}")
            if f.get("location_hint"):
                st.markdown(f"**Location:** {f.get('location_hint')}")
            ev = f.get("evidence", []) or []
            if ev:
                st.markdown("**Evidence:**")
                for e in ev:
                    st.markdown(f"- “{e}”")
            if f.get("fix"):
                st.markdown(f"**Fix:** {f.get('fix')}")


def render_failures_table_micro(micro: list[dict]) -> None:
    for f in micro:
        with st.expander(f"{f.get('type','')}", expanded=False):
            if f.get("location"):
                st.markdown(f"**Location:** “{f.get('location')}”")
            if f.get("explanation"):
                st.markdown(f"**Explanation:** {f.get('explanation')}")


# -----------------------------
# Streamlit UI
# -----------------------------

st.set_page_config(page_title=APP_NAME, layout="wide")

st.markdown(
    f"""
    <div style="display:flex;align-items:center;justify-content:space-between;">
      <div style="font-size:28px;font-weight:700;">{APP_NAME}</div>
      <div style="opacity:0.75;">Reasoning audit • {TAXONOMY_VERSION}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Session state
if "doc_text" not in st.session_state:
    st.session_state["doc_text"] = ""
if "doc_hash" not in st.session_state:
    st.session_state["doc_hash"] = ""
if "analysis_cache" not in st.session_state:
    st.session_state["analysis_cache"] = {}
if "last_result" not in st.session_state:
    st.session_state["last_result"] = None
if "is_running" not in st.session_state:
    st.session_state["is_running"] = False
if "full_width" not in st.session_state:
    st.session_state["full_width"] = False

# Layout controls
toolbar = st.container()
with toolbar:
    c1, c2, c3, c4 = st.columns([2, 2, 2, 6])
    with c1:
        st.session_state["full_width"] = st.toggle("Full-width results", value=st.session_state["full_width"])
    with c2:
        st.caption("Recommended max")
        st.write(f"{RECOMMENDED_MAX_CHARS:,} chars")
    with c3:
        st.caption("Hard stop")
        st.write(f"{HARD_MAX_CHARS:,} chars")

# Main layout
if st.session_state["full_width"]:
    left_col = None
    right_col = st.container()
else:
    left_col, right_col = st.columns([1, 1.4], gap="large")


def left_panel(container: st.delta_generator.DeltaGenerator) -> None:
    with container:
        st.subheader("Document Input")

        uploaded = st.file_uploader("Upload a PDF or TXT", type=["pdf", "txt"])
        if uploaded is not None:
            try:
                if uploaded.type == "application/pdf":
                    pdf_bytes = uploaded.read()
                    text = extract_text_from_pdf(pdf_bytes)
                    st.session_state["doc_text"] = text
                else:
                    st.session_state["doc_text"] = uploaded.read().decode("utf-8", errors="ignore")
                st.success("Document loaded.")
            except Exception as e:
                st.error(f"Failed to read file: {e}")

        st.markdown("Or paste text:")
        doc_text = st.text_area(
            "Document text",
            value=st.session_state.get("doc_text", ""),
            height=340,
            label_visibility="collapsed",
            placeholder="Paste the document here…",
        )
        st.session_state["doc_text"] = doc_text

        n_chars = len((doc_text or ""))
        st.info(f"Length: {n_chars:,} characters")

        if n_chars > HARD_MAX_CHARS:
            st.error("Document exceeds the hard limit. Please trim before analyzing.")
            st.stop()

        if n_chars > RECOMMENDED_MAX_CHARS:
            st.warning(
                "This document exceeds the recommended analysis length. "
                "Validity will analyze it in sections. "
                "Best results are achieved by trimming boilerplate, tables, and appendices."
            )
            st.caption("Note: Clicking Analyze will still process the full document in chunks unless you trim it.")

            colA, colB = st.columns([1, 1])
            with colA:
                if st.button("Auto-trim to recommended length", use_container_width=True):
                    st.session_state["doc_text"] = (doc_text or "")[:RECOMMENDED_MAX_CHARS]
                    st.rerun()
            with colB:
                st.caption("You can still analyze, but quality and stability may degrade.")

        st.divider()

        run = st.button("Analyze", type="primary", use_container_width=True)
        if run:
            st.session_state["is_running"] = False  # safety reset

            text = st.session_state.get("doc_text", "")
            if not text or len(text.strip()) < 50:
                st.error("Please provide a longer document (at least ~50 characters).")
                return

            doc_hash = stable_hash(f"{TAXONOMY_VERSION}|{text}")
            st.session_state["doc_hash"] = doc_hash

            if doc_hash in st.session_state["analysis_cache"]:
                st.session_state["last_result"] = st.session_state["analysis_cache"][doc_hash]
                st.success("Loaded cached analysis.")
                st.rerun()

            st.session_state["is_running"] = True
            with st.spinner("Analyzing…"):
                try:
                    analyzer = ValidityAnalyzer()
                    result = analyzer.analyze(text)
                    st.session_state["analysis_cache"][doc_hash] = result
                    st.session_state["last_result"] = result
                except Exception as e:
                    st.session_state["last_result"] = {
                        "success": False,
                        "analysis": None,
                        "error": str(e),
                        "chunks_analyzed": 0,
                        "chunks_succeeded": 0,
                        "chunks_failed": 0,
                        "analysis_time": 0,
                    }
                finally:
                    st.session_state["is_running"] = False

            st.rerun()


def results_panel(container: st.delta_generator.DeltaGenerator) -> None:
    with container:
        st.subheader("Analysis Results")

        result = st.session_state.get("last_result")
        if not result:
            st.caption("Run an analysis to see results here.")
            return

        if not result.get("success"):
            st.error(result.get("error") or "Analysis failed.")
            return

        analysis = result.get("analysis") or {}
        n_chars = len(st.session_state.get("doc_text", "") or "")

        s1, s2, s3, s4 = st.columns([1, 1, 1, 2])
        with s1:
            st.metric("Decision risk", analysis.get("decision_risk", ""))
        with s2:
            st.metric("Reasoning score", analysis.get("reasoning_score", ""))
        with s3:
            st.metric("Failures", analysis.get("total_failures_detected", 0))
        with s4:
            st.caption(
                f"Doc length: {n_chars:,} chars • "
                f"Chunks: {result.get('chunks_analyzed')} • "
                f"Time: {result.get('analysis_time')}s"
            )

        st.divider()

        meta = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "chunks_analyzed": result.get("chunks_analyzed"),
            "chunks_succeeded": result.get("chunks_succeeded"),
            "chunks_failed": result.get("chunks_failed"),
        }
        md = build_markdown_report(analysis, meta)

        exp1, exp2, exp3 = st.columns([1, 1, 6])
        with exp1:
            st.download_button(
                "Download Markdown",
                data=md.encode("utf-8"),
                file_name="validity_report.md",
                mime="text/markdown",
                use_container_width=True,
            )
        with exp2:
            if LETTER is None:
                st.button(
                    "Download PDF",
                    disabled=True,
                    use_container_width=True,
                    help="Install reportlab to enable PDF export.",
                )
            else:
                try:
                    pdf_bytes = markdown_to_pdf_bytes(md)
                    st.download_button(
                        "Download PDF",
                        data=pdf_bytes,
                        file_name="validity_report.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                    )
                except Exception:
                    st.button(
                        "Download PDF",
                        disabled=True,
                        use_container_width=True,
                        help="PDF export unavailable (reportlab error).",
                    )

        st.divider()

        thesis = analysis.get("thesis", {}) or {}
        with st.expander("Thesis", expanded=True):
            st.markdown(f"**Statement:** {thesis.get('statement','')}")
            st.markdown(f"**Explicitness:** {thesis.get('explicitness','unclear')}")

        overall = analysis.get("overall_assessment", {}) or {}
        with st.expander("Overall Assessment", expanded=True):
            st.markdown(f"**Confidence:** {overall.get('confidence','')}")
            st.markdown(overall.get("summary", ""))

        structural = analysis.get("structural_failures", []) or []
        with st.expander(f"Structural Failures ({len(structural)})", expanded=True):
            if not structural:
                st.caption("None detected.")
            else:
                render_failures_table_structural(structural)

        micro = analysis.get("micro_failures", analysis.get("failures_detected", [])) or []
        with st.expander(f"Micro Failures ({len(micro)})", expanded=False):
            if not micro:
                st.caption("None detected.")
            else:
                render_failures_table_micro(micro)

        with st.expander("Raw JSON (debug)", expanded=False):
            st.code(json.dumps(result, indent=2))


# Render panels
if left_col is not None:
    left_panel(left_col)

results_panel(right_col if right_col is not None else st.container())
