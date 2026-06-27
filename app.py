"""
app.py — Procurement Indent Analyser  (v5)
─────────────────────────────────────────
Based on v3 (working) + new features:
  - Domain selector: Civil / Electromechanical
  - Standard Practice viewer
  - LLM-based comparison
  - Pre-auth fix for WinError 233
  - 8 tabs including Good Practices + Weak Areas
"""

import streamlit as st
import streamlit.components.v1 as components
import json
import tempfile
import base64
import os
import sys
from pathlib import Path

# ── Fix working directory ─────────────────────────────────────────────────────
os.chdir(Path(__file__).parent)
sys.path.insert(0, str(Path(__file__).parent))

# ── Load environment variables ────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv()

st.set_page_config(
    page_title="Procurement Indent Analyser",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Domain configuration ──────────────────────────────────────────────────────
DOMAINS = {
    "🏗 Civil": {
        "key":           "civil",
        "display":       "Civil Indents",
        "standard_path": "pipeline_outputs/05_standard/best_practice_standard.json",
        "description":   "Civil construction, supply, ARC, and related indents",
    },
    "⚡ Electromechanical": {
        "key":           "electromechanical",
        "display":       "Electromechanical Indents",
        "standard_path": "pipeline_outputs_electromechnical/05_standard/best_practice_standard.json",
        "description":   "Electrical, mechanical, instrumentation, and related indents",
    },
}

# ── Styling ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp { background-color: #F7F8FA; }

.app-header {
    background: linear-gradient(135deg, #1B2A4A 0%, #2D4A7A 100%);
    padding: 2rem 2.5rem;
    border-radius: 12px;
    margin-bottom: 1.5rem;
    color: white;
}
.app-header h1 {
    font-size:1.8rem;font-weight:700;
    margin:0 0 0.4rem 0;letter-spacing:-0.02em;
}
.app-header p { font-size:0.9rem;opacity:0.72;margin:0; }

.score-card {
    background:white;border-radius:12px;padding:1.5rem;
    text-align:center;box-shadow:0 1px 4px rgba(0,0,0,0.08);
    border:1px solid #E8EBF0;
}
.score-number {
    font-size:3.5rem;font-weight:700;line-height:1;
    font-family:'JetBrains Mono',monospace;
}
.score-grade {
    font-size:0.95rem;font-weight:600;margin-top:0.5rem;
    padding:0.3rem 0.8rem;border-radius:20px;display:inline-block;
}
.metric-tile {
    background:white;border-radius:10px;padding:1rem 1.25rem;
    border:1px solid #E8EBF0;box-shadow:0 1px 3px rgba(0,0,0,0.05);
}
.metric-value {
    font-size:1.6rem;font-weight:700;
    font-family:'JetBrains Mono',monospace;
}
.metric-label {
    font-size:0.72rem;color:#6B7280;font-weight:500;
    text-transform:uppercase;letter-spacing:0.05em;
}
.practice-card {
    background:white;border-radius:10px;
    padding:1rem 1.25rem;margin-bottom:0.75rem;
    border:1px solid #E8EBF0;
    box-shadow:0 1px 3px rgba(0,0,0,0.04);
}
.practice-title {
    font-size:0.9rem;font-weight:600;color:#111827;
    margin-bottom:0.3rem;
}
.practice-reason { font-size:0.8rem;color:#6B7280; }
.practice-freq {
    display:inline-block;background:#F3F4F6;
    border-radius:20px;padding:0.15rem 0.6rem;
    font-size:0.72rem;color:#374151;
    font-family:'JetBrains Mono',monospace;
    margin-top:0.4rem;
}
.rec-item {
    background:#EFF6FF;border-left:3px solid #3B82F6;
    padding:0.6rem 0.9rem;border-radius:0 6px 6px 0;
    margin-bottom:0.5rem;font-size:0.875rem;color:#1E40AF;
}
.issue-item {
    background:#FFF7ED;border-left:3px solid #F97316;
    padding:0.6rem 0.9rem;border-radius:0 6px 6px 0;
    margin-bottom:0.5rem;font-size:0.875rem;color:#9A3412;
}
.good-item {
    background:#F0FDF4;border-left:3px solid #22C55E;
    padding:0.6rem 0.9rem;border-radius:0 6px 6px 0;
    margin-bottom:0.5rem;font-size:0.875rem;color:#166534;
}
.weak-item {
    background:#FFF1F2;border-left:3px solid #F43F5E;
    padding:0.6rem 0.9rem;border-radius:0 6px 6px 0;
    margin-bottom:0.5rem;font-size:0.875rem;color:#881337;
}
.file-chip {
    display:inline-block;background:#F3F4F6;border-radius:20px;
    padding:0.25rem 0.75rem;font-size:0.75rem;color:#374151;
    margin:0.2rem;font-family:'JetBrains Mono',monospace;
}
.section-header {
    font-size:1rem;font-weight:600;color:#1B2A4A;
    padding:0.5rem 0;border-bottom:2px solid #E8EBF0;
    margin-bottom:1rem;
}
</style>
""", unsafe_allow_html=True)


# ── Folder upload component ───────────────────────────────────────────────────
def folder_upload_component(key: str = "folder_upload"):
    component_html = """
    <style>
    * { box-sizing:border-box;font-family:'Inter','Segoe UI',sans-serif; }
    .folder-zone {
        border:2px dashed #D1D5DB;border-radius:12px;
        padding:2rem;text-align:center;background:white;
        cursor:pointer;transition:all 0.2s;
    }
    .folder-zone:hover,.folder-zone.dragover {
        border-color:#3B82F6;background:#EFF6FF;
    }
    .folder-icon { font-size:2rem;margin-bottom:0.5rem; }
    .folder-title {font-size:0.95rem;font-weight:600;color:#111827;}
    .folder-sub   {font-size:0.78rem;color:#6B7280;}
    .folder-btn {
        display:inline-block;margin-top:0.75rem;
        padding:0.4rem 1rem;background:#1B2A4A;color:white;
        border-radius:8px;font-size:0.85rem;cursor:pointer;
    }
    .folder-btn:hover { background:#2D4A7A; }
    .file-list {
        margin-top:0.75rem;text-align:left;
        max-height:150px;overflow-y:auto;
    }
    .file-row {
        display:flex;align-items:center;gap:0.5rem;
        padding:0.3rem 0.4rem;border-radius:6px;
        font-size:0.78rem;color:#374151;
    }
    .file-row:hover { background:#F3F4F6; }
    .file-ext {
        font-size:0.68rem;background:#E5E7EB;
        padding:0.1rem 0.35rem;border-radius:4px;
        font-family:monospace;color:#4B5563;
        min-width:34px;text-align:center;
    }
    .progress-bar {
        height:3px;background:#E5E7EB;border-radius:2px;
        margin-top:0.75rem;overflow:hidden;display:none;
    }
    .progress-fill {
        height:100%;
        background:linear-gradient(90deg,#3B82F6,#1D4ED8);
        transition:width 0.3s;width:0%;
    }
    .status-msg {
        font-size:0.78rem;color:#6B7280;
        margin-top:0.4rem;display:none;
    }
    </style>

    <input type="file" id="folderInput" webkitdirectory directory multiple
           accept=".pdf,.docx,.xlsx,.xls,.xlsm,.txt"
           style="display:none;">

    <div class="folder-zone" id="dropZone"
         onclick="document.getElementById('folderInput').click()">
        <div class="folder-icon">📁</div>
        <div class="folder-title">Click to select indent folder</div>
        <div class="folder-sub">Chrome / Edge only</div>
        <div class="folder-btn"
             onclick="event.stopPropagation();
                      document.getElementById('folderInput').click()">
            Browse Folder
        </div>
        <div class="progress-bar" id="progressBar">
            <div class="progress-fill" id="progressFill"></div>
        </div>
        <div class="status-msg" id="statusMsg"></div>
        <div class="file-list"  id="fileList"></div>
    </div>

    <script>
    const ALLOWED=['pdf','docx','xlsx','xls','xlsm','txt'];
    function getExt(n){return n.split('.').pop().toLowerCase();}
    function fmtSize(b){
        if(b<1024)return b+' B';
        if(b<1048576)return (b/1024).toFixed(1)+' KB';
        return (b/1048576).toFixed(1)+' MB';
    }
    async function processFiles(files){
        const filtered=Array.from(files).filter(
            f=>ALLOWED.includes(getExt(f.name))
        );
        if(!filtered.length){
            document.getElementById('statusMsg').style.display='block';
            document.getElementById('statusMsg').textContent=
                'No supported files found.';
            return;
        }
        const bar=document.getElementById('progressBar');
        const fill=document.getElementById('progressFill');
        const msg=document.getElementById('statusMsg');
        const list=document.getElementById('fileList');
        bar.style.display='block';msg.style.display='block';
        list.innerHTML='';
        const results=[];
        for(let i=0;i<filtered.length;i++){
            const file=filtered[i];
            msg.textContent=
                `Reading ${file.name}... (${i+1}/${filtered.length})`;
            fill.style.width=((i+1)/filtered.length*100)+'%';
            const b64=await new Promise(resolve=>{
                const r=new FileReader();
                r.onload=e=>{
                    const a=new Uint8Array(e.target.result);
                    let s='';
                    for(let j=0;j<a.byteLength;j++)
                        s+=String.fromCharCode(a[j]);
                    resolve(btoa(s));
                };
                r.readAsArrayBuffer(file);
            });
            results.push({
                name:file.name,content_b64:b64,
                size:file.size,ext:getExt(file.name)
            });
            const ext=getExt(file.name).toUpperCase();
            list.innerHTML+=`
                <div class="file-row">
                    <span class="file-ext">${ext}</span>
                    <span>${file.name}</span>
                    <span style="margin-left:auto;color:#9CA3AF;
                                 font-size:0.7rem;">
                        ${fmtSize(file.size)}
                    </span>
                </div>`;
        }
        msg.textContent=`✓ ${filtered.length} file(s) ready`;
        window.parent.postMessage(
            {type:'streamlit:setComponentValue',value:results},'*'
        );
    }
    document.getElementById('folderInput').addEventListener(
        'change',e=>processFiles(e.target.files)
    );
    const zone=document.getElementById('dropZone');
    zone.addEventListener('dragover',e=>{
        e.preventDefault();zone.classList.add('dragover');
    });
    zone.addEventListener('dragleave',
        ()=>zone.classList.remove('dragover')
    );
    zone.addEventListener('drop',e=>{
        e.preventDefault();zone.classList.remove('dragover');
        const files=[];
        if(e.dataTransfer.items){
            for(let i of e.dataTransfer.items)
                if(i.kind==='file')files.push(i.getAsFile());
        }else{
            for(let f of e.dataTransfer.files)files.push(f);
        }
        processFiles(files);
    });
    </script>
    """
    return components.html(component_html, height=320, scrolling=False)


# ── Helpers ───────────────────────────────────────────────────────────────────
@st.cache_data
def load_standard_practice(path: str):
    p = Path(path)
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
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
            '<p style="color:#9CA3AF;font-size:0.85rem;">'
            'No findings.</p>',
            unsafe_allow_html=True
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
                    border-bottom:1px solid #F3F4F6;
                    align-items:flex-start;">
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
            '<p style="color:#9CA3AF;font-size:0.85rem;">'
            'No items found.</p>',
            unsafe_allow_html=True
        )
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        title  = item.get(key_field, "")
        reason = item.get(reason_field, "")
        freq   = item.get(freq_field, 0)
        st.markdown(f"""
        <div class="practice-card">
            <div class="practice-title">{title}</div>
            <div class="practice-reason">{reason}</div>
            <span class="practice-freq">
                Seen in {freq} indent(s)
            </span>
        </div>""", unsafe_allow_html=True)


def render_weak_practice_list(items):
    if not items:
        st.markdown(
            '<p style="color:#9CA3AF;font-size:0.85rem;">'
            'No items found.</p>',
            unsafe_allow_html=True
        )
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        issue  = item.get("issue", "")
        impact = item.get("impact", "")
        fix    = item.get("how_to_fix", "")
        freq   = item.get("source_frequency", 0)
        types  = ", ".join(item.get("procurement_types", []))
        st.markdown(f"""
        <div class="practice-card"
             style="border-left:3px solid #F43F5E;">
            <div class="practice-title" style="color:#881337;">
                ⚠ {issue}
            </div>
            {f'<div class="practice-reason"><b>Impact:</b> {impact}</div>'
             if impact else ''}
            {f'<div class="practice-reason" style="color:#059669;">'
             f'<b>Fix:</b> {fix}</div>' if fix else ''}
            {f'<div class="practice-reason"><b>Types:</b> {types}</div>'
             if types else ''}
            <span class="practice-freq">
                Seen in {freq} indent(s)
            </span>
        </div>""", unsafe_allow_html=True)


def render_category_patterns(items):
    if not items:
        st.markdown(
            '<p style="color:#9CA3AF;font-size:0.85rem;">'
            'No patterns found.</p>',
            unsafe_allow_html=True
        )
        return
    grouped: dict = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        pt = item.get("procurement_type", "Other")
        grouped.setdefault(pt, []).append(item)

    for pt, patterns in grouped.items():
        st.markdown(
            f'<div class="section-header">📦 {pt}</div>',
            unsafe_allow_html=True
        )
        for p in patterns:
            doc_type = p.get("document_type", "")
            pattern  = p.get("pattern", "")
            rec      = p.get("recommendation", "")
            st.markdown(f"""
            <div class="practice-card">
                <div class="practice-title">📄 {doc_type}</div>
                <div class="practice-reason">{pattern}</div>
                {f'<div class="practice-reason" style="color:#1E40AF;">'
                 f'→ {rec}</div>' if rec else ''}
            </div>""", unsafe_allow_html=True)


def run_pipeline(file_items, indent_name):
    """Parse, clean, classify and extract from uploaded files."""
    from src.document_parser   import parse_file
    from src.text_cleaner      import clean_document_text
    from src.document_analyzer import DocumentAnalyzer

    analyzer  = DocumentAnalyzer()
    documents = []
    progress  = st.progress(0)
    status    = st.empty()
    total     = len(file_items)

    with tempfile.TemporaryDirectory() as tmpdir:
        for i, item in enumerate(file_items):
            if hasattr(item, "name"):
                fname   = item.name
                content = item.getvalue()
            else:
                fname   = item["name"]
                content = base64.b64decode(item["content_b64"])

            status.markdown(
                f'<p style="font-size:0.875rem;color:#6B7280;">'
                f'Processing <b>{fname}</b>...</p>',
                unsafe_allow_html=True
            )

            tmp_path = Path(tmpdir) / fname
            with open(tmp_path, "wb") as f:
                f.write(content)

            try:
                text, metadata = parse_file(tmp_path)
                cleaned        = clean_document_text(text)

                if len(cleaned.strip()) < 50:
                    st.warning(
                        f"⚠️ {fname} — too short after cleaning, skipping."
                    )
                    progress.progress((i + 1) / total)
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
            except Exception as e:
                st.warning(f"⚠️ Failed to process {fname}: {e}")

            progress.progress((i + 1) / total)

    status.empty()
    progress.empty()

    if not documents:
        return {}

    spinner_msg = st.empty()
    spinner_msg.markdown(
        '<p style="font-size:0.875rem;color:#374151;font-weight:500;">'
        '🤖 Extracting indent data (1 LLM call)...</p>',
        unsafe_allow_html=True
    )

    result = {}
    for attempt in range(3):
        try:
            extraction = analyzer.extract_indent(
                indent_id=indent_name.replace(" ", "_"),
                indent_title=indent_name,
                documents=documents,
            )
            result = extraction.model_dump()
            break
        except Exception as e:
            if attempt < 2:
                spinner_msg.markdown(
                    f'<p style="font-size:0.875rem;color:#D97706;">'
                    f'⚠️ Attempt {attempt+1} failed — retrying... </p>',
                    unsafe_allow_html=True
                )
                import time
                time.sleep(2)
            else:
                st.error(f"LLM extraction failed after 3 attempts: {e}")
                result = {}

    spinner_msg.empty()
    return result


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("## ⚙️ Settings")
    st.markdown("---")

    st.markdown("### 📂 Procurement Domain")
    selected_domain_key = st.radio(
        "Select domain",
        options=list(DOMAINS.keys()),
        label_visibility="collapsed",
    )
    domain_config = DOMAINS[selected_domain_key]

    st.markdown(
        f'<p style="font-size:0.78rem;color:#6B7280;">'
        f'{domain_config["description"]}</p>',
        unsafe_allow_html=True
    )

    st.markdown("---")

    st.markdown("### 🗂 Navigation")
    page = st.radio(
        "Go to",
        options=["📊 Standard Practice", "🔍 Analyse New Indent"],
        label_visibility="collapsed",
    )

    st.markdown("---")
    st.markdown(
        '<p style="font-size:0.72rem;color:#9CA3AF;">'
        'Procurement Intelligence System<br>'
        'Tata Steel — Civil &amp; EM Indents</p>',
        unsafe_allow_html=True
    )


# ── Load standard ─────────────────────────────────────────────────────────────
standard = load_standard_practice(domain_config["standard_path"])

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="app-header">
    <h1>📋 Procurement Indent Analyser</h1>
    <p>{selected_domain_key} — {domain_config["description"]}</p>
</div>
""", unsafe_allow_html=True)

if not standard:
    st.warning(
        f"⚠️ Standard practice not yet generated for "
        f"**{domain_config['display']}**.\n\n"
        f"Expected at: `{domain_config['standard_path']}`\n\n"
        f"Run `python run_steps34.py` to generate it."
    )
    if page == "🔍 Analyse New Indent":
        st.stop()

# ── Stats bar ─────────────────────────────────────────────────────────────────
if standard:
    meta = standard.get("_metadata", {})
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    for col, val, label in [
        (c1, meta.get("source_indents", "?"),
             "Indents in Standard"),
        (c2, len(standard.get("mandatory_practices", [])),
             "Mandatory Practices"),
        (c3, len(standard.get("documentation_requirements", [])),
             "Doc Requirements"),
        (c4, len(standard.get("risk_controls", [])),
             "Risk Controls"),
        (c5, len(standard.get("common_good_practices", [])),
             "Good Practices"),
        (c6, len(standard.get("common_weak_practices", [])),
             "Known Weak Areas"),
    ]:
        with col:
            st.markdown(f"""
            <div class="metric-tile">
                <div class="metric-value"
                     style="color:#1B2A4A;">{val}</div>
                <div class="metric-label">{label}</div>
            </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — STANDARD PRACTICE VIEWER
# ══════════════════════════════════════════════════════════════════════════════

if page == "📊 Standard Practice":

    st.markdown(
        f"## 📊 Standard Practice — {domain_config['display']}"
    )

    if not standard:
        st.info("Run the pipeline to generate the standard practice.")
        st.stop()

    (stab1, stab2, stab3, stab4,
     stab5, stab6, stab7, stab8) = st.tabs([
        f"✅ Mandatory ({len(standard.get('mandatory_practices', []))})",
        f"👍 Recommended ({len(standard.get('recommended_practices', []))})",
        f"⭐ Good Practices ({len(standard.get('common_good_practices', []))})",
        f"⚠️ Weak Areas ({len(standard.get('common_weak_practices', []))})",
        f"🛡 Risk Controls ({len(standard.get('risk_controls', []))})",
        f"📁 Doc Requirements ({len(standard.get('documentation_requirements', []))})",
        f"🏗 Structure Standards ({len(standard.get('document_structure_standards', []))})",
        f"🔗 Category Patterns ({len(standard.get('category_specific_patterns', []))})",
    ])

    with stab1:
        st.markdown("**Must be present in every indent.**")
        render_practice_list(standard.get("mandatory_practices", []))

    with stab2:
        st.markdown("**Improve quality — should be present.**")
        render_practice_list(standard.get("recommended_practices", []))

    with stab3:
        st.markdown("**What good indents consistently do well.**")
        render_practice_list(
            standard.get("common_good_practices", []),
            key_field="practice",
            reason_field="why_it_matters",
        )

    with stab4:
        st.markdown("**Most frequent weaknesses — with fixes.**")
        render_weak_practice_list(standard.get("common_weak_practices", []))

    with stab5:
        st.markdown("**Risk areas and their controls.**")
        for item in standard.get("risk_controls", []):
            if not isinstance(item, dict):
                continue
            area    = item.get("risk_area", "")
            control = item.get("control", "")
            reason  = item.get("reason", "")
            freq    = item.get("source_frequency", 0)
            st.markdown(f"""
            <div class="practice-card">
                <div class="practice-title">
                    🛡 {area}: {control}
                </div>
                <div class="practice-reason">{reason}</div>
                <span class="practice-freq">
                    Seen in {freq} indent(s)
                </span>
            </div>""", unsafe_allow_html=True)

    with stab6:
        st.markdown("**Required document types.**")
        render_practice_list(
            standard.get("documentation_requirements", []),
            key_field="requirement",
        )

    with stab7:
        st.markdown("**How each document should be structured.**")
        for item in standard.get("document_structure_standards", []):
            if not isinstance(item, dict):
                continue
            doc_type = item.get("document_type", "")
            category = item.get("procurement_category", "")
            sections = item.get("recommended_sections", [])
            guidance = item.get("structure_guidance", "")
            freq     = item.get("source_frequency", 0)
            st.markdown(f"""
            <div class="practice-card">
                <div class="practice-title">
                    📄 {doc_type}
                    {f'<span style="color:#6B7280;font-weight:400;"> — {category}</span>'
                     if category else ''}
                </div>
                {f'<div class="practice-reason">{guidance}</div>'
                 if guidance else ''}
                {f'<div class="practice-reason">'
                 f'<b>Sections:</b> {", ".join(sections)}</div>'
                 if sections else ''}
                <span class="practice-freq">
                    Seen in {freq} indent(s)
                </span>
            </div>""", unsafe_allow_html=True)

    with stab8:
        st.markdown(
            "**How procurement category affects document structure.**"
        )
        render_category_patterns(
            standard.get("category_specific_patterns", [])
        )

    st.markdown("<br>", unsafe_allow_html=True)
    st.download_button(
        f"⬇️ Download {domain_config['display']} Standard (JSON)",
        data=json.dumps(standard, indent=2),
        file_name=f"{domain_config['key']}_best_practice_standard.json",
        mime="application/json",
    )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — ANALYSE NEW INDENT
# ══════════════════════════════════════════════════════════════════════════════

elif page == "🔍 Analyse New Indent":

    st.markdown(
        f"## 🔍 Analyse New Indent — {domain_config['display']}"
    )

    st.markdown("### Upload Indent Documents")

    mode = st.radio(
        "Upload method",
        options=[
            "📁 Folder Upload",
            "📄 Multi-File Upload",
            "🗂 Single File",
        ],
        horizontal=True,
        label_visibility="collapsed",
    )

    indent_name = st.text_input(
        "Indent name (optional)",
        placeholder="e.g. Indent - 36156 - Precast Drains",
    )
    if not indent_name:
        indent_name = "New Indent"

    st.markdown("<br>", unsafe_allow_html=True)

    file_items  = []
    files_ready = False

    if mode == "📁 Folder Upload":
        st.markdown("""
        <div style="background:#FFFBEB;border:1px solid #FDE68A;
                    border-radius:8px;padding:0.6rem 1rem;
                    font-size:0.8rem;color:#92400E;margin-bottom:1rem;">
            💡 <b>Chrome / Edge only.</b>
            If Analyse button stays greyed out after selecting files,
            use <b>Multi-File Upload</b> instead.
        </div>
        """, unsafe_allow_html=True)

        folder_data = folder_upload_component(key="folder_uploader")
        if (folder_data and isinstance(folder_data, list)
                and len(folder_data) > 0):
            file_items  = folder_data
            files_ready = True
            chips = "".join(
                f'<span class="file-chip">📄 {f["name"]}</span>'
                for f in file_items
            )
            st.markdown(
                f'<div style="margin-top:0.75rem;">{chips}</div>',
                unsafe_allow_html=True
            )
            st.caption(f"{len(file_items)} file(s) loaded")

    elif mode == "📄 Multi-File Upload":
        st.markdown("""
        <div style="font-size:0.82rem;color:#6B7280;margin-bottom:0.5rem;">
            Open indent folder → <b>Ctrl+A</b> to select all
            → drag into uploader below.
        </div>
        """, unsafe_allow_html=True)
        uploaded = st.file_uploader(
            "Select files",
            type=["pdf", "docx", "xlsx", "xls", "xlsm", "txt"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )
        if uploaded:
            file_items  = uploaded
            files_ready = True
            chips = "".join(
                f'<span class="file-chip">📄 {f.name}</span>'
                for f in uploaded
            )
            st.markdown(
                f'<div style="margin-top:0.5rem;">{chips}</div>',
                unsafe_allow_html=True
            )
            st.caption(f"{len(uploaded)} file(s) selected")

    else:
        single = st.file_uploader(
            "Select document",
            type=["pdf", "docx", "xlsx", "xls", "xlsm", "txt"],
            accept_multiple_files=False,
            label_visibility="collapsed",
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
    )

    st.markdown("---")

    if analyse_btn and files_ready:
        with st.spinner(""):
            extraction = run_pipeline(file_items, indent_name)

        if not extraction:
            st.error(
                "Extraction failed. Check your documents and retry."
            )
            st.stop()

        from src.indent_comparator import compare_indent_to_standard

        compare_msg = st.empty()
        compare_msg.markdown(
            '<p style="font-size:0.875rem;color:#374151;'
            'font-weight:500;">'
            '🔍 Comparing against standard (1 LLM call)...</p>',
            unsafe_allow_html=True
        )
        report = compare_indent_to_standard(extraction, standard)
        compare_msg.empty()

        st.session_state["report"]     = report
        st.session_state["extraction"] = extraction

    if "report" in st.session_state:
        report     = st.session_state["report"]
        extraction = st.session_state["extraction"]

        st.markdown(
            f"## Analysis: {report.indent_id.replace('_', ' ')}"
        )

        c_score, c_type, c_recs, c_gaps = st.columns([1, 2, 2, 2])
        with c_score:
            st.markdown(f"""
            <div class="score-card">
                <div class="score-number"
                     style="color:{score_color(report.overall_score)};">
                    {report.overall_score}
                </div>
                <div style="font-size:0.72rem;color:#9CA3AF;
                            margin-top:0.25rem;">out of 100</div>
                <div class="score-grade" style="
                    background:{grade_color(report.overall_grade)}22;
                    color:{grade_color(report.overall_grade)};">
                    {report.overall_grade}
                </div>
            </div>""", unsafe_allow_html=True)
        with c_type:
            st.markdown(f"""
            <div class="metric-tile" style="height:100%;">
                <div class="metric-label">Procurement Type</div>
                <div style="font-size:0.95rem;font-weight:600;
                            color:#111827;margin-top:0.4rem;">
                    {report.procurement_type}
                </div>
            </div>""", unsafe_allow_html=True)
        with c_recs:
            st.markdown(f"""
            <div class="metric-tile" style="height:100%;">
                <div class="metric-label">Recommendations</div>
                <div class="metric-value" style="color:#DC2626;">
                    {len(report.recommendations)}
                </div>
            </div>""", unsafe_allow_html=True)
        with c_gaps:
            st.markdown(f"""
            <div class="metric-tile" style="height:100%;">
                <div class="metric-label">Gaps Found</div>
                <div class="metric-value" style="color:#D97706;">
                    {len(report.gaps)}
                </div>
            </div>""", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        if report.strengths:
            st.markdown("### ⭐ Strengths")
            for s in report.strengths:
                st.markdown(
                    f'<div class="good-item">✓ {s}</div>',
                    unsafe_allow_html=True
                )
            st.markdown("<br>", unsafe_allow_html=True)

        if report.recommendations:
            st.markdown("### 🎯 Recommendations")
            for rec in report.recommendations:
                st.markdown(
                    f'<div class="rec-item">→ {rec}</div>',
                    unsafe_allow_html=True
                )
            st.markdown("<br>", unsafe_allow_html=True)

        if report.cross_doc_issues:
            st.markdown("### ⚠️ Cross-Document Issues")
            for issue in report.cross_doc_issues:
                st.markdown(
                    f'<div class="issue-item">⚠ {issue}</div>',
                    unsafe_allow_html=True
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
        with st.expander("📊 Extracted Procurement Summary",
                         expanded=False):
            ps = extraction.get("procurement_summary", {}) or {}
            fields = [
                ("Package Description",      ps.get("package_description")),
                ("Scope of Work",            ps.get("scope_of_work")),
                ("Procurement Type",         ps.get("procurement_type")),
                ("Location",                 ps.get("location")),
                ("Discipline",               ps.get("discipline")),
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
                        value
                        if value and str(value).lower()
                        not in ("null", "none", "")
                        else "—"
                    )
                    color = "#111827" if display != "—" else "#D1D5DB"
                    st.markdown(f"""
                    <div style="padding:0.4rem 0;
                                border-bottom:1px solid #F3F4F6;">
                        <span style="font-size:0.72rem;color:#9CA3AF;
                                     text-transform:uppercase;
                                     letter-spacing:0.05em;">
                            {label}</span><br>
                        <span style="font-size:0.875rem;
                                     font-weight:500;color:{color};">
                            {display}</span>
                    </div>""", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        dl1, dl2 = st.columns(2)
        with dl1:
            st.download_button(
                "⬇️ Download Extraction JSON",
                data=json.dumps(extraction, indent=2, default=str),
                file_name=f"{report.indent_id}_extraction.json",
                mime="application/json",
            )
        with dl2:
            st.download_button(
                "⬇️ Download Comparison Report",
                data=json.dumps({
                    "indent_id":        report.indent_id,
                    "procurement_type": report.procurement_type,
                    "overall_score":    report.overall_score,
                    "overall_grade":    report.overall_grade,
                    "recommendations":  report.recommendations,
                    "gaps":             report.gaps,
                    "cross_doc_issues": report.cross_doc_issues,
                    "strengths":        report.strengths,
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
