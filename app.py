"""
app.py — Procurement Indent Analyser (basic)
"""

import streamlit as st
import json
import tempfile
import base64
import sys
import io
from pathlib import Path

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Procurement Indent Analyser",
    page_icon="📋",
    layout="wide",
)

# ── Path setup ────────────────────────────────────────────────────────────────
_APP_DIR = Path(__file__).parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

# ── Load standard practice ────────────────────────────────────────────────────
@st.cache_data
def load_standard():
    p = _APP_DIR / "pipeline_outputs" / "05_standard" / "best_practice_standard.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def status_icon(status):
    return {"pass": "✅", "fail": "❌", "warning": "⚠️"}.get(status, "•")


def render_findings(findings):
    if not findings:
        st.write("No findings.")
        return
    for f in findings:
        icon = status_icon(f.status)
        st.markdown(f"**{icon} {f.title}**")
        st.caption(f.detail)
        st.divider()


def run_analysis(file_items, indent_name):
    """
    Parse files, extract indent, compare against standard.
    All stdout redirected to avoid WinError 233.
    """
    # Redirect stdout to avoid Windows pipe error
    old_stdout = sys.stdout
    sys.stdout  = io.StringIO()

    result = {}
    try:
        from src.document_parser   import parse_file
        from src.text_cleaner      import clean_document_text
        from src.document_analyzer import DocumentAnalyzer

        analyzer  = DocumentAnalyzer()
        documents = []

        with tempfile.TemporaryDirectory() as tmpdir:
            for item in file_items:
                if hasattr(item, "name"):
                    fname   = item.name
                    content = item.getvalue()
                else:
                    fname   = item["name"]
                    content = base64.b64decode(item["content_b64"])

                tmp_path = Path(tmpdir) / fname
                tmp_path.write_bytes(content)

                try:
                    text, metadata = parse_file(tmp_path)
                    cleaned        = clean_document_text(text)
                    if len(cleaned.strip()) < 50:
                        continue
                    classification = analyzer.classify_rule_based(
                        document_name=fname,
                        document_text=cleaned,
                    )
                    documents.append({
                        "document_name":   fname,
                        "document_text":   cleaned,
                        "classification":  classification,
                        "parser_metadata": metadata,
                    })
                except Exception:
                    continue

        if documents:
            extraction = analyzer.extract_indent(
                indent_id=indent_name.replace(" ", "_"),
                indent_title=indent_name,
                documents=documents,
            )
            result = extraction.model_dump()

    except Exception as e:
        result = {"_error": str(e)}
    finally:
        sys.stdout = old_stdout

    return result


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

st.title("📋 Procurement Indent Analyser")

# Load standard
standard = load_standard()
if not standard:
    st.error(
        "Standard practice file not found. "
        "Run the pipeline first."
    )
    st.stop()

meta = standard.get("_metadata", {})
st.caption(
    f"Standard based on {meta.get('source_indents','?')} indents | "
    f"{len(standard.get('mandatory_practices',[]))} mandatory practices | "
    f"{len(standard.get('risk_controls',[]))} risk controls"
)

st.divider()

# Upload
st.subheader("Upload Indent Documents")
indent_name = st.text_input(
    "Indent name",
    placeholder="e.g. Indent - 36156 - Precast Drains"
) or "New Indent"

uploaded = st.file_uploader(
    "Select all files from the indent folder",
    type=["pdf", "docx", "xlsx", "xls", "xlsm", "txt"],
    accept_multiple_files=True,
)

if uploaded:
    st.caption(f"{len(uploaded)} file(s) selected")

analyse_btn = st.button(
    "🔍 Analyse Indent",
    type="primary",
    disabled=not uploaded,
)

st.divider()

# Run
if analyse_btn and uploaded:
    with st.spinner("Extracting indent data (1 LLM call)..."):
        extraction = run_analysis(uploaded, indent_name)

    if "_error" in extraction:
        st.error(f"Extraction failed: {extraction['_error']}")
        st.stop()

    if not extraction:
        st.error("Extraction returned empty. Check your documents.")
        st.stop()

    with st.spinner("Comparing against standard (1 LLM call)..."):
        from src.indent_comparator import compare_indent_to_standard
        report = compare_indent_to_standard(extraction, standard)

    st.session_state["report"]     = report
    st.session_state["extraction"] = extraction

# Display
if "report" in st.session_state:
    report     = st.session_state["report"]
    extraction = st.session_state["extraction"]

    st.subheader(f"Results: {report.indent_id.replace('_',' ')}")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Score",           f"{report.overall_score}/100")
    col2.metric("Grade",           report.overall_grade)
    col3.metric("Recommendations", len(report.recommendations))
    col4.metric("Gaps",            len(report.gaps))

    st.divider()

    if report.recommendations:
        st.subheader("🎯 Recommendations")
        for r in report.recommendations:
            st.write(f"→ {r}")

    if report.gaps:
        st.subheader("❌ Gaps Found")
        for g in report.gaps:
            st.write(f"• {g}")

    if report.strengths:
        st.subheader("✅ Strengths")
        for s in report.strengths:
            st.write(f"• {s}")

    st.divider()
    st.subheader("Detailed Findings")

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        f"✅ Mandatory ({len(report.mandatory_findings)})",
        f"📁 Documents ({len(report.documentation_findings)})",
        f"🛡 Risks ({len(report.risk_findings)})",
        f"🏢 Vendors ({len(report.vendor_findings)})",
        f"📋 Approvals ({len(report.approval_findings)})",
    ])
    with tab1: render_findings(report.mandatory_findings)
    with tab2: render_findings(report.documentation_findings)
    with tab3: render_findings(report.risk_findings)
    with tab4: render_findings(report.vendor_findings)
    with tab5: render_findings(report.approval_findings)

    # Download
    st.divider()
    st.download_button(
        "⬇️ Download Report JSON",
        data=json.dumps({
            "indent_id":       report.indent_id,
            "score":           report.overall_score,
            "grade":           report.overall_grade,
            "recommendations": report.recommendations,
            "gaps":            report.gaps,
            "strengths":       report.strengths,
        }, indent=2),
        file_name=f"{report.indent_id}_report.json",
        mime="application/json",
    )
