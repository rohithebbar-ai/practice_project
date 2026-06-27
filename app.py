"""
app.py — Procurement Indent Analyser (v6)
─────────────────────────────────────────
Features:
  - Domain selector: Civil / Electromechanical
  - Standard Practice viewer
  - Upload + compare new indent
  - stdout redirect fix for WinError 233
  - Session state cleared on domain switch
  - Folder upload + multi-file upload
"""

import streamlit as st
import streamlit.components.v1 as components
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
    initial_sidebar_state="expanded",
)

# ── Path setup ────────────────────────────────────────────────────────────────
_APP_DIR = Path(__file__).parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

# ── Domain configuration ──────────────────────────────────────────────────────
DOMAINS = {
    "🏗 Civil": {
        "key":         "civil",
        "display":     "Civil Indents",
        "standard":    "pipeline_outputs/05_standard/best_practice_standard.json",
        "description": "Civil construction, supply, ARC, and related indents",
    },
    "⚡ Electromechanical": {
        "key":         "electromechanical",
        "display":     "Electromechanical Indents",
        "standard":    "pipeline_outputs_electromechanical/05_standard/best_practice_standard.json",
        "description": "Electrical, mechanical, instrumentation, and related indents",
    },
}

# ── Helpers ───────────────────────────────────────────────────────────────────
@st.cache_data
def load_standard(path: str):
    p = _APP_DIR / path
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def status_icon(status):
    return {
        "pass":    "✅",
        "fail":    "❌",
        "warning": "⚠️",
        "info":    "ℹ️",
    }.get(status, "•")


def grade_color(grade):
    return {
        "Strong":            "#059669",
        "Adequate":          "#D97706",
        "Needs Improvement": "#DC2626",
        "Weak":              "#7F1D1D",
    }.get(grade, "#6B7280")


def score_color(score):
    if score >= 80: return "#059669"
    if score >= 60: return "#D97706"
    if score >= 40: return "#EF4444"
    return "#7F1D1D"


def render_findings(findings):
    if not findings:
        st.markdown(
            '<p style="color:#9CA3AF;font-size:0.85rem;">No findings.</p>',
            unsafe_allow_html=True,
        )
        return
    for f in findings:
        icon  = status_icon(f.status)
        color = {
            "pass":    "#059669",
            "fail":    "#DC2626",
            "warning": "#D97706",
            "info":    "#6B7280",
        }.get(f.status, "#6B7280")
        st.markdown(f"""
        <div style="display:flex;gap:0.6rem;padding:0.55rem 0;
                    border-bottom:1px solid #F3F4F6;align-items:flex-start;">
            <span style="font-size:1rem;margin-top:0.05rem;">{icon}</span>
            <div>
                <div style="font-size:0.875rem;font-weight:500;
                            color:#111827;">{f.title}</div>
                <div style="font-size:0.78rem;color:#6B7280;
                            margin-top:0.1rem;">{f.detail}</div>
            </div>
        </div>""", unsafe_allow_html=True)


def render_practice_list(items, key_field="practice",
                          reason_field="reason",
                          freq_field="source_frequency"):
    if not items:
        st.markdown(
            '<p style="color:#9CA3AF;font-size:0.85rem;">No items.</p>',
            unsafe_allow_html=True,
        )
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        title  = item.get(key_field, "")
        reason = item.get(reason_field, "")
        freq   = item.get(freq_field, 0)
        st.markdown(f"""
        <div style="background:white;border-radius:10px;
                    padding:1rem 1.25rem;margin-bottom:0.75rem;
                    border:1px solid #E8EBF0;">
            <div style="font-size:0.9rem;font-weight:600;
                        color:#111827;margin-bottom:0.3rem;">{title}</div>
            <div style="font-size:0.8rem;color:#6B7280;">{reason}</div>
            <span style="display:inline-block;background:#F3F4F6;
                         border-radius:20px;padding:0.15rem 0.6rem;
                         font-size:0.72rem;color:#374151;margin-top:0.4rem;">
                Seen in {freq} indent(s)
            </span>
        </div>""", unsafe_allow_html=True)


def render_weak_list(items):
    if not items:
        st.markdown(
            '<p style="color:#9CA3AF;font-size:0.85rem;">No items.</p>',
            unsafe_allow_html=True,
        )
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        issue  = item.get("issue", "")
        impact = item.get("impact", "")
        fix    = item.get("how_to_fix", "")
        freq   = item.get("source_frequency", 0)
        st.markdown(f"""
        <div style="background:white;border-radius:10px;
                    padding:1rem 1.25rem;margin-bottom:0.75rem;
                    border:1px solid #E8EBF0;
                    border-left:3px solid #F43F5E;">
            <div style="font-size:0.9rem;font-weight:600;
                        color:#881337;margin-bottom:0.3rem;">⚠ {issue}</div>
            {f'<div style="font-size:0.8rem;color:#6B7280;"><b>Impact:</b> {impact}</div>' if impact else ''}
            {f'<div style="font-size:0.8rem;color:#059669;"><b>Fix:</b> {fix}</div>' if fix else ''}
            <span style="display:inline-block;background:#F3F4F6;
                         border-radius:20px;padding:0.15rem 0.6rem;
                         font-size:0.72rem;color:#374151;margin-top:0.4rem;">
                Seen in {freq} indent(s)
            </span>
        </div>""", unsafe_allow_html=True)


def run_analysis(file_items, indent_name):
    """Extract indent — stdout redirected to fix WinError 233."""
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
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


def run_comparison(extraction, standard):
    """Compare — stdout redirected to fix WinError 233."""
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        from src.indent_comparator import compare_indent_to_standard
        report = compare_indent_to_standard(extraction, standard)
    finally:
        sys.stdout = old_stdout
    return report


# ── Folder upload component ───────────────────────────────────────────────────
def folder_upload_component(key="folder_upload"):
    html = """
    <style>
    *{box-sizing:border-box;font-family:'Segoe UI',sans-serif;}
    .fz{border:2px dashed #D1D5DB;border-radius:12px;padding:2rem;
        text-align:center;background:white;cursor:pointer;transition:all 0.2s;}
    .fz:hover,.fz.over{border-color:#3B82F6;background:#EFF6FF;}
    .fi{font-size:2rem;margin-bottom:0.5rem;}
    .ft{font-size:0.95rem;font-weight:600;color:#111827;}
    .fs{font-size:0.78rem;color:#6B7280;}
    .fb{display:inline-block;margin-top:0.75rem;padding:0.4rem 1rem;
        background:#1B2A4A;color:white;border-radius:8px;
        font-size:0.85rem;cursor:pointer;}
    .fb:hover{background:#2D4A7A;}
    .fl{margin-top:0.75rem;text-align:left;max-height:150px;overflow-y:auto;}
    .fr{display:flex;align-items:center;gap:0.5rem;padding:0.3rem 0.4rem;
        border-radius:6px;font-size:0.78rem;color:#374151;}
    .fr:hover{background:#F3F4F6;}
    .fe{font-size:0.68rem;background:#E5E7EB;padding:0.1rem 0.35rem;
        border-radius:4px;font-family:monospace;color:#4B5563;
        min-width:34px;text-align:center;}
    .pb{height:3px;background:#E5E7EB;border-radius:2px;
        margin-top:0.75rem;overflow:hidden;display:none;}
    .pf{height:100%;background:linear-gradient(90deg,#3B82F6,#1D4ED8);
        transition:width 0.3s;width:0%;}
    .sm{font-size:0.78rem;color:#6B7280;margin-top:0.4rem;display:none;}
    </style>
    <input type="file" id="fi" webkitdirectory directory multiple
           accept=".pdf,.docx,.xlsx,.xls,.xlsm,.txt" style="display:none;">
    <div class="fz" id="fz" onclick="document.getElementById('fi').click()">
        <div class="fi">📁</div>
        <div class="ft">Click to select indent folder</div>
        <div class="fs">Chrome / Edge only — or use Multi-File Upload</div>
        <div class="fb" onclick="event.stopPropagation();
             document.getElementById('fi').click()">Browse Folder</div>
        <div class="pb" id="pb"><div class="pf" id="pf"></div></div>
        <div class="sm" id="sm"></div>
        <div class="fl" id="fl"></div>
    </div>
    <script>
    const AL=['pdf','docx','xlsx','xls','xlsm','txt'];
    function ext(n){return n.split('.').pop().toLowerCase();}
    function sz(b){
        if(b<1024)return b+'B';
        if(b<1048576)return(b/1024).toFixed(1)+'KB';
        return(b/1048576).toFixed(1)+'MB';
    }
    async function go(files){
        const f=Array.from(files).filter(x=>AL.includes(ext(x.name)));
        if(!f.length){
            document.getElementById('sm').style.display='block';
            document.getElementById('sm').textContent='No supported files.';
            return;
        }
        const pb=document.getElementById('pb');
        const pf=document.getElementById('pf');
        const sm=document.getElementById('sm');
        const fl=document.getElementById('fl');
        pb.style.display='block';sm.style.display='block';fl.innerHTML='';
        const res=[];
        for(let i=0;i<f.length;i++){
            const x=f[i];
            sm.textContent=`Reading ${x.name}... (${i+1}/${f.length})`;
            pf.style.width=((i+1)/f.length*100)+'%';
            const b64=await new Promise(r=>{
                const rd=new FileReader();
                rd.onload=e=>{
                    const a=new Uint8Array(e.target.result);
                    let s='';for(let j=0;j<a.byteLength;j++)s+=String.fromCharCode(a[j]);
                    r(btoa(s));
                };
                rd.readAsArrayBuffer(x);
            });
            res.push({name:x.name,content_b64:b64,size:x.size,ext:ext(x.name)});
            fl.innerHTML+=`<div class="fr">
                <span class="fe">${ext(x.name).toUpperCase()}</span>
                <span>${x.name}</span>
                <span style="margin-left:auto;color:#9CA3AF;font-size:0.7rem;">${sz(x.size)}</span>
            </div>`;
        }
        sm.textContent=`✓ ${f.length} file(s) ready`;
        window.parent.postMessage({type:'streamlit:setComponentValue',value:res},'*');
    }
    document.getElementById('fi').addEventListener('change',e=>go(e.target.files));
    const fz=document.getElementById('fz');
    fz.addEventListener('dragover',e=>{e.preventDefault();fz.classList.add('over');});
    fz.addEventListener('dragleave',()=>fz.classList.remove('over'));
    fz.addEventListener('drop',e=>{
        e.preventDefault();fz.classList.remove('over');
        const f=[];
        if(e.dataTransfer.items){for(let i of e.dataTransfer.items)if(i.kind==='file')f.push(i.getAsFile());}
        else{for(let x of e.dataTransfer.files)f.push(x);}
        go(f);
    });
    </script>
    """
    return components.html(html, height=300, scrolling=False)


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("## ⚙️ Settings")
    st.markdown("---")
    st.markdown("### 📂 Procurement Domain")

    selected = st.radio(
        "domain",
        options=list(DOMAINS.keys()),
        label_visibility="collapsed",
    )
    domain = DOMAINS[selected]
    st.caption(domain["description"])

    # ── Clear session when domain changes ─────────────────────────────────────
    if st.session_state.get("active_domain") != domain["key"]:
        # Domain switched — clear everything
        for key in ["report", "extraction", "file_items"]:
            if key in st.session_state:
                del st.session_state[key]
        st.session_state["active_domain"] = domain["key"]

    st.markdown("---")
    st.markdown("### 🗂 Navigation")
    page = st.radio(
        "page",
        options=["📊 Standard Practice", "🔍 Analyse New Indent"],
        label_visibility="collapsed",
    )
    st.markdown("---")
    st.caption("Procurement Intelligence System\nTata Steel")


# ── Load standard ─────────────────────────────────────────────────────────────
standard = load_standard(domain["standard"])

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div style="background:linear-gradient(135deg,#1B2A4A 0%,#2D4A7A 100%);
            padding:2rem 2.5rem;border-radius:12px;
            margin-bottom:1.5rem;color:white;">
    <h1 style="font-size:1.8rem;font-weight:700;margin:0 0 0.4rem 0;">
        📋 Procurement Indent Analyser
    </h1>
    <p style="font-size:0.9rem;opacity:0.72;margin:0;">
        {selected} — {domain["description"]}
    </p>
</div>
""", unsafe_allow_html=True)

if not standard:
    st.warning(
        f"⚠️ Standard not found for **{domain['display']}**.\n\n"
        f"Expected at: `{domain['standard']}`\n\n"
        f"Run `python run_steps34.py` to generate it."
    )
    if page == "🔍 Analyse New Indent":
        st.stop()

# ── Stats bar ─────────────────────────────────────────────────────────────────
if standard:
    meta = standard.get("_metadata", {})
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    for col, val, label in [
        (c1, meta.get("source_indents", "?"),                        "Indents"),
        (c2, len(standard.get("mandatory_practices", [])),           "Mandatory"),
        (c3, len(standard.get("documentation_requirements", [])),    "Doc Req"),
        (c4, len(standard.get("risk_controls", [])),                 "Risks"),
        (c5, len(standard.get("common_good_practices", [])),         "Good Practices"),
        (c6, len(standard.get("common_weak_practices", [])),         "Weak Areas"),
    ]:
        with col:
            st.markdown(f"""
            <div style="background:white;border-radius:10px;
                        padding:1rem 1.25rem;border:1px solid #E8EBF0;">
                <div style="font-size:1.6rem;font-weight:700;
                            color:#1B2A4A;">{val}</div>
                <div style="font-size:0.72rem;color:#6B7280;
                            font-weight:500;text-transform:uppercase;
                            letter-spacing:0.05em;">{label}</div>
            </div>""", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — STANDARD PRACTICE VIEWER
# ══════════════════════════════════════════════════════════════════════════════

if page == "📊 Standard Practice":
    st.markdown(f"## 📊 Standard Practice — {domain['display']}")

    if not standard:
        st.info("Run the pipeline to generate the standard practice.")
        st.stop()

    (t1, t2, t3, t4, t5, t6, t7, t8) = st.tabs([
        f"✅ Mandatory ({len(standard.get('mandatory_practices',[]))})",
        f"👍 Recommended ({len(standard.get('recommended_practices',[]))})",
        f"⭐ Good Practices ({len(standard.get('common_good_practices',[]))})",
        f"⚠️ Weak Areas ({len(standard.get('common_weak_practices',[]))})",
        f"🛡 Risks ({len(standard.get('risk_controls',[]))})",
        f"📁 Docs ({len(standard.get('documentation_requirements',[]))})",
        f"🏗 Structure ({len(standard.get('document_structure_standards',[]))})",
        f"🔗 Patterns ({len(standard.get('category_specific_patterns',[]))})",
    ])

    with t1:
        st.markdown("**Must be present in every indent.**")
        render_practice_list(standard.get("mandatory_practices", []))

    with t2:
        st.markdown("**Improve quality — should be present.**")
        render_practice_list(standard.get("recommended_practices", []))

    with t3:
        st.markdown("**What good indents consistently do well.**")
        render_practice_list(
            standard.get("common_good_practices", []),
            key_field="practice",
            reason_field="why_it_matters",
        )

    with t4:
        st.markdown("**Most frequent weaknesses — with fixes.**")
        render_weak_list(standard.get("common_weak_practices", []))

    with t5:
        for item in standard.get("risk_controls", []):
            if not isinstance(item, dict):
                continue
            st.markdown(f"""
            <div style="background:white;border-radius:10px;
                        padding:1rem 1.25rem;margin-bottom:0.75rem;
                        border:1px solid #E8EBF0;">
                <div style="font-size:0.9rem;font-weight:600;color:#111827;">
                    🛡 {item.get('risk_area','')}: {item.get('control','')}
                </div>
                <div style="font-size:0.8rem;color:#6B7280;">
                    {item.get('reason','')}
                </div>
                <span style="display:inline-block;background:#F3F4F6;
                             border-radius:20px;padding:0.15rem 0.6rem;
                             font-size:0.72rem;color:#374151;margin-top:0.4rem;">
                    Seen in {item.get('source_frequency',0)} indent(s)
                </span>
            </div>""", unsafe_allow_html=True)

    with t6:
        render_practice_list(
            standard.get("documentation_requirements", []),
            key_field="requirement",
        )

    with t7:
        for item in standard.get("document_structure_standards", []):
            if not isinstance(item, dict):
                continue
            sections = item.get("recommended_sections", [])
            st.markdown(f"""
            <div style="background:white;border-radius:10px;
                        padding:1rem 1.25rem;margin-bottom:0.75rem;
                        border:1px solid #E8EBF0;">
                <div style="font-size:0.9rem;font-weight:600;color:#111827;">
                    📄 {item.get('document_type','')}
                    <span style="color:#6B7280;font-weight:400;">
                        — {item.get('procurement_category','')}
                    </span>
                </div>
                <div style="font-size:0.8rem;color:#6B7280;">
                    {item.get('structure_guidance','')}
                </div>
                {f'<div style="font-size:0.8rem;color:#374151;margin-top:0.3rem;"><b>Sections:</b> {", ".join(sections)}</div>' if sections else ''}
            </div>""", unsafe_allow_html=True)

    with t8:
        grouped: dict = {}
        for item in standard.get("category_specific_patterns", []):
            if not isinstance(item, dict):
                continue
            pt = item.get("procurement_type", "Other")
            grouped.setdefault(pt, []).append(item)
        for pt, patterns in grouped.items():
            st.markdown(f"**📦 {pt}**")
            for p in patterns:
                st.markdown(f"""
                <div style="background:white;border-radius:10px;
                            padding:1rem 1.25rem;margin-bottom:0.75rem;
                            border:1px solid #E8EBF0;">
                    <div style="font-size:0.9rem;font-weight:600;
                                color:#111827;">
                        📄 {p.get('document_type','')}
                    </div>
                    <div style="font-size:0.8rem;color:#6B7280;">
                        {p.get('pattern','')}
                    </div>
                    {f'<div style="font-size:0.8rem;color:#1E40AF;">→ {p.get("recommendation","")}</div>' if p.get('recommendation') else ''}
                </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.download_button(
        f"⬇️ Download {domain['display']} Standard (JSON)",
        data=json.dumps(standard, indent=2),
        file_name=f"{domain['key']}_best_practice_standard.json",
        mime="application/json",
    )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — ANALYSE NEW INDENT
# ══════════════════════════════════════════════════════════════════════════════

elif page == "🔍 Analyse New Indent":
    st.markdown(f"## 🔍 Analyse New Indent — {domain['display']}")

    st.markdown("### Upload Indent Documents")

    mode = st.radio(
        "Upload method",
        options=["📁 Folder Upload", "📄 Multi-File Upload", "🗂 Single File"],
        horizontal=True,
        label_visibility="collapsed",
        key=f"upload_mode_{domain['key']}",  # unique key per domain
    )

    indent_name = st.text_input(
        "Indent name (optional)",
        placeholder="e.g. Indent - 36156 - Precast Drains",
        key=f"indent_name_{domain['key']}",  # unique key per domain
    ) or "New Indent"

    st.markdown("<br>", unsafe_allow_html=True)

    file_items  = []
    files_ready = False

    if mode == "📁 Folder Upload":
        st.markdown("""
        <div style="background:#FFFBEB;border:1px solid #FDE68A;
                    border-radius:8px;padding:0.6rem 1rem;
                    font-size:0.8rem;color:#92400E;margin-bottom:1rem;">
            💡 <b>Chrome / Edge only.</b>
            If Analyse button stays greyed out, switch to
            <b>Multi-File Upload</b>.
        </div>
        """, unsafe_allow_html=True)

        folder_data = folder_upload_component(
            key=f"folder_{domain['key']}"
        )
        if (folder_data and isinstance(folder_data, list)
                and len(folder_data) > 0):
            file_items  = folder_data
            files_ready = True
            chips = "".join(
                f'<span style="display:inline-block;background:#F3F4F6;'
                f'border-radius:20px;padding:0.25rem 0.75rem;'
                f'font-size:0.75rem;color:#374151;margin:0.2rem;">'
                f'📄 {f["name"]}</span>'
                for f in file_items
            )
            st.markdown(
                f'<div style="margin-top:0.75rem;">{chips}</div>',
                unsafe_allow_html=True,
            )
            st.caption(f"{len(file_items)} file(s) loaded")

    elif mode == "📄 Multi-File Upload":
        st.markdown(
            '<div style="font-size:0.82rem;color:#6B7280;'
            'margin-bottom:0.5rem;">'
            'Open indent folder → <b>Ctrl+A</b> → drag into uploader.'
            '</div>',
            unsafe_allow_html=True,
        )
        uploaded = st.file_uploader(
            "Select files",
            type=["pdf", "docx", "xlsx", "xls", "xlsm", "txt"],
            accept_multiple_files=True,
            label_visibility="collapsed",
            key=f"multi_{domain['key']}",  # unique key per domain
        )
        if uploaded:
            file_items  = uploaded
            files_ready = True
            chips = "".join(
                f'<span style="display:inline-block;background:#F3F4F6;'
                f'border-radius:20px;padding:0.25rem 0.75rem;'
                f'font-size:0.75rem;color:#374151;margin:0.2rem;">'
                f'📄 {f.name}</span>'
                for f in uploaded
            )
            st.markdown(
                f'<div style="margin-top:0.5rem;">{chips}</div>',
                unsafe_allow_html=True,
            )
            st.caption(f"{len(uploaded)} file(s) selected")

    else:
        single = st.file_uploader(
            "Select document",
            type=["pdf", "docx", "xlsx", "xls", "xlsm", "txt"],
            accept_multiple_files=False,
            label_visibility="collapsed",
            key=f"single_{domain['key']}",  # unique key per domain
        )
        if single:
            file_items  = [single]
            files_ready = True
            st.caption(f"📄 {single.name}")

    st.markdown("<br>", unsafe_allow_html=True)
    analyse_btn = st.button(
        "🔍  Analyse Indent",
        type="primary",
        disabled=not files_ready,
        key=f"analyse_{domain['key']}",  # unique key per domain
    )
    st.markdown("---")

    # ── Run ───────────────────────────────────────────────────────────────────
    if analyse_btn and files_ready:
        with st.spinner("🤖 Extracting indent data (1 LLM call)..."):
            extraction = run_analysis(file_items, indent_name)

        if "_error" in extraction:
            st.error(f"Extraction failed: {extraction['_error']}")
            st.stop()

        if not extraction:
            st.error("Extraction returned empty. Check documents.")
            st.stop()

        with st.spinner("🔍 Comparing against standard (1 LLM call)..."):
            report = run_comparison(extraction, standard)

        st.session_state["report"]     = report
        st.session_state["extraction"] = extraction

    # ── Display ───────────────────────────────────────────────────────────────
    if "report" in st.session_state:
        report     = st.session_state["report"]
        extraction = st.session_state["extraction"]

        st.markdown(
            f"## Analysis: {report.indent_id.replace('_', ' ')}"
        )

        c1, c2, c3, c4 = st.columns([1, 2, 2, 2])
        with c1:
            st.markdown(f"""
            <div style="background:white;border-radius:12px;
                        padding:1.5rem;text-align:center;
                        box-shadow:0 1px 4px rgba(0,0,0,0.08);
                        border:1px solid #E8EBF0;">
                <div style="font-size:3.5rem;font-weight:700;line-height:1;
                            color:{score_color(report.overall_score)};">
                    {report.overall_score}
                </div>
                <div style="font-size:0.72rem;color:#9CA3AF;
                            margin-top:0.25rem;">out of 100</div>
                <div style="font-size:0.95rem;font-weight:600;
                            margin-top:0.5rem;padding:0.3rem 0.8rem;
                            border-radius:20px;display:inline-block;
                            background:{grade_color(report.overall_grade)}22;
                            color:{grade_color(report.overall_grade)};">
                    {report.overall_grade}
                </div>
            </div>""", unsafe_allow_html=True)
        with c2:
            st.markdown(f"""
            <div style="background:white;border-radius:10px;
                        padding:1rem 1.25rem;border:1px solid #E8EBF0;
                        height:100%;">
                <div style="font-size:0.72rem;color:#6B7280;
                            text-transform:uppercase;">
                    Procurement Type</div>
                <div style="font-size:0.95rem;font-weight:600;
                            color:#111827;margin-top:0.4rem;">
                    {report.procurement_type}
                </div>
            </div>""", unsafe_allow_html=True)
        with c3:
            st.markdown(f"""
            <div style="background:white;border-radius:10px;
                        padding:1rem 1.25rem;border:1px solid #E8EBF0;
                        height:100%;">
                <div style="font-size:0.72rem;color:#6B7280;
                            text-transform:uppercase;">
                    Recommendations</div>
                <div style="font-size:1.6rem;font-weight:700;
                            color:#DC2626;">
                    {len(report.recommendations)}
                </div>
            </div>""", unsafe_allow_html=True)
        with c4:
            st.markdown(f"""
            <div style="background:white;border-radius:10px;
                        padding:1rem 1.25rem;border:1px solid #E8EBF0;
                        height:100%;">
                <div style="font-size:0.72rem;color:#6B7280;
                            text-transform:uppercase;">Gaps Found</div>
                <div style="font-size:1.6rem;font-weight:700;
                            color:#D97706;">
                    {len(report.gaps)}
                </div>
            </div>""", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        if report.strengths:
            st.markdown("### ⭐ Strengths")
            for s in report.strengths:
                st.markdown(
                    f'<div style="background:#F0FDF4;border-left:3px solid '
                    f'#22C55E;padding:0.6rem 0.9rem;border-radius:0 6px 6px 0;'
                    f'margin-bottom:0.5rem;font-size:0.875rem;color:#166534;">'
                    f'✓ {s}</div>',
                    unsafe_allow_html=True,
                )
            st.markdown("<br>", unsafe_allow_html=True)

        if report.recommendations:
            st.markdown("### 🎯 Recommendations")
            for r in report.recommendations:
                st.markdown(
                    f'<div style="background:#EFF6FF;border-left:3px solid '
                    f'#3B82F6;padding:0.6rem 0.9rem;border-radius:0 6px 6px 0;'
                    f'margin-bottom:0.5rem;font-size:0.875rem;color:#1E40AF;">'
                    f'→ {r}</div>',
                    unsafe_allow_html=True,
                )
            st.markdown("<br>", unsafe_allow_html=True)

        if report.cross_doc_issues:
            st.markdown("### ⚠️ Cross-Document Issues")
            for issue in report.cross_doc_issues:
                st.markdown(
                    f'<div style="background:#FFF7ED;border-left:3px solid '
                    f'#F97316;padding:0.6rem 0.9rem;border-radius:0 6px 6px 0;'
                    f'margin-bottom:0.5rem;font-size:0.875rem;color:#9A3412;">'
                    f'⚠ {issue}</div>',
                    unsafe_allow_html=True,
                )
            st.markdown("<br>", unsafe_allow_html=True)

        st.markdown("### Detailed Findings")
        (tab1, tab2, tab3, tab4,
         tab5, tab6, tab7, tab8) = st.tabs([
            f"✅ Mandatory ({len(report.mandatory_findings)})",
            f"📁 Documents ({len(report.documentation_findings)})",
            f"🛡 Risks ({len(report.risk_findings)})",
            f"🏢 Vendors ({len(report.vendor_findings)})",
            f"📋 Approvals ({len(report.approval_findings)})",
            f"🏗 Structure ({len(report.structure_findings)})",
            f"⭐ Good Practices ({len(report.good_practice_findings)})",
            f"⚠️ Weak Areas ({len(report.weak_practice_findings)})",
        ])
        with tab1: render_findings(report.mandatory_findings)
        with tab2: render_findings(report.documentation_findings)
        with tab3: render_findings(report.risk_findings)
        with tab4: render_findings(report.vendor_findings)
        with tab5: render_findings(report.approval_findings)
        with tab6: render_findings(report.structure_findings)
        with tab7: render_findings(report.good_practice_findings)
        with tab8: render_findings(report.weak_practice_findings)

        st.markdown("<br>", unsafe_allow_html=True)
        with st.expander("📊 Extracted Procurement Summary", expanded=False):
            ps = extraction.get("procurement_summary", {}) or {}
            fields = [
                ("Package Description",      ps.get("package_description")),
                ("Scope of Work",            ps.get("scope_of_work")),
                ("Procurement Type",         ps.get("procurement_type")),
                ("Location",                 ps.get("location")),
                ("Estimated Cost (Cr)",      ps.get("estimated_cost_crores")),
                ("Contract Period (months)", ps.get("contract_period_months")),
                ("Order Required Date",      ps.get("order_required_date")),
                ("Job Risk Category",        ps.get("job_risk_category")),
                ("Is Single Party",          ps.get("is_single_party")),
                ("Vendor Panel",             ps.get("vendor_panel")),
                ("Vendor Count",             ps.get("vendor_count")),
                ("Term Sheet Type",          ps.get("term_sheet_type")),
                ("Technical Spec Attached",  ps.get("technical_spec_attached")),
                ("HSE Plan Available",       ps.get("hse_plan_available")),
                ("BOQ Surplus Checked",      ps.get("boq_surplus_checked")),
                ("Approval Authority",       ps.get("approval_authority")),
                ("Approval Date",            ps.get("indent_approval_date")),
                ("Procurement Head",         ps.get("procurement_head")),
            ]
            ca, cb = st.columns(2)
            for i, (label, value) in enumerate(fields):
                col = ca if i % 2 == 0 else cb
                with col:
                    display = (
                        value if value and
                        str(value).lower() not in ("null", "none", "")
                        else "—"
                    )
                    color = "#111827" if display != "—" else "#D1D5DB"
                    st.markdown(f"""
                    <div style="padding:0.4rem 0;
                                border-bottom:1px solid #F3F4F6;">
                        <span style="font-size:0.72rem;color:#9CA3AF;
                                     text-transform:uppercase;
                                     letter-spacing:0.05em;">{label}</span>
                        <br>
                        <span style="font-size:0.875rem;font-weight:500;
                                     color:{color};">{display}</span>
                    </div>""", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        d1, d2 = st.columns(2)
        with d1:
            st.download_button(
                "⬇️ Download Extraction JSON",
                data=json.dumps(extraction, indent=2, default=str),
                file_name=f"{report.indent_id}_extraction.json",
                mime="application/json",
            )
        with d2:
            st.download_button(
                "⬇️ Download Comparison Report",
                data=json.dumps({
                    "indent_id":       report.indent_id,
                    "score":           report.overall_score,
                    "grade":           report.overall_grade,
                    "recommendations": report.recommendations,
                    "gaps":            report.gaps,
                    "strengths":       report.strengths,
                    "cross_doc_issues": report.cross_doc_issues,
                }, indent=2),
                file_name=f"{report.indent_id}_report.json",
                mime="application/json",
            )

    else:
        st.markdown("""
        <div style="text-align:center;padding:3rem;color:#9CA3AF;">
            <div style="font-size:3rem;margin-bottom:1rem;">📂</div>
            <div style="font-size:1rem;font-weight:500;color:#6B7280;">
                Select upload method, add files, then click Analyse
            </div>
            <div style="font-size:0.85rem;margin-top:0.5rem;">
                Supports BOQ, Procurement Tracker, Technical Spec,
                Safety Term Sheet, Approval Notes
            </div>
        </div>
        """, unsafe_allow_html=True)
