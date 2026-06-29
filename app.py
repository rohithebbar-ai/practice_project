"""
app.py — Procurement Indent Analyser (v8)
Professional redesign — Tata Steel procurement intelligence platform.

Design system:
  - Primary:    #0F1F3D  (deep navy — steel industry authority)
  - Accent:     #C8973A  (brass/gold — quality mark)
  - Surface:    #FFFFFF  (white)
  - Background: #F4F5F7  (off-white)
  - Border:     #E1E4E8
  - Text:       #1A1D23  (near-black)
  - Muted:      #6B7280
  - Pass:       #1A7F4B
  - Fail:       #B91C1C
  - Warning:    #B45309
  - Type:       Inter (body), JetBrains Mono (data)
"""

import streamlit as st
import streamlit.components.v1 as components
import json
import tempfile
import base64
import sys
import io
from pathlib import Path

st.set_page_config(
    page_title="Procurement Intelligence — Tata Steel",
    page_icon="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' fill='%230F1F3D'/><rect x='8' y='8' width='16' height='2' fill='%23C8973A'/><rect x='8' y='13' width='12' height='2' fill='%23C8973A'/><rect x='8' y='18' width='14' height='2' fill='%23C8973A'/><rect x='8' y='23' width='10' height='2' fill='%23C8973A'/></svg>",
    layout="wide",
    initial_sidebar_state="expanded",
)

_APP_DIR = Path(__file__).parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

DOMAINS = {
    "Civil": {
        "key":         "civil",
        "display":     "Civil",
        "standard":    "pipeline_outputs/05_standard/best_practice_standard.json",
        "description": "Civil construction, supply, ARC and related indents",
    },
    "Electromechanical": {
        "key":         "electromechanical",
        "display":     "Electromechanical",
        "standard":    "pipeline_outputs_electromechanical/05_standard/best_practice_standard.json",
        "description": "Electrical, mechanical and instrumentation indents",
    },
}

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── Reset ──────────────────────────────────────────────────────────────── */
html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, sans-serif;
    color: #1A1D23;
}
.stApp { background: #F4F5F7; }
.block-container { padding-top: 0 !important; }

/* ── Hide Streamlit chrome ───────────────────────────────────────────────── */
#MainMenu, footer, header { visibility: hidden; }
.stDeployButton { display: none; }

/* ── Sidebar ─────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background: #0F1F3D !important;
    border-right: none;
}
[data-testid="stSidebar"] * { color: #E8ECF4 !important; }
[data-testid="stSidebar"] .stRadio label {
    font-size: 0.85rem !important;
    padding: 0.4rem 0 !important;
    cursor: pointer;
}
[data-testid="stSidebar"] hr {
    border-color: rgba(255,255,255,0.1) !important;
    margin: 1rem 0 !important;
}
[data-testid="stSidebar"] p {
    font-size: 0.75rem !important;
    opacity: 0.5;
    line-height: 1.6;
}

/* ── Top bar ─────────────────────────────────────────────────────────────── */
.top-bar {
    background: #0F1F3D;
    padding: 0 2rem;
    height: 56px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin: -1rem -1rem 1.5rem -1rem;
    position: sticky;
    top: 0;
    z-index: 100;
}
.top-bar-brand {
    font-size: 0.875rem;
    font-weight: 600;
    color: white;
    letter-spacing: 0.02em;
}
.top-bar-domain {
    font-size: 0.75rem;
    color: #C8973A;
    font-weight: 500;
    letter-spacing: 0.06em;
    text-transform: uppercase;
}

/* ── Page title ──────────────────────────────────────────────────────────── */
.page-title {
    font-size: 1.5rem;
    font-weight: 700;
    color: #0F1F3D;
    letter-spacing: -0.02em;
    margin: 0 0 0.25rem 0;
}
.page-subtitle {
    font-size: 0.85rem;
    color: #6B7280;
    margin: 0 0 1.5rem 0;
}

/* ── Stat tiles ──────────────────────────────────────────────────────────── */
.stat-tile {
    background: white;
    border-radius: 6px;
    padding: 1rem 1.25rem;
    border: 1px solid #E1E4E8;
    border-top: 3px solid #0F1F3D;
}
.stat-value {
    font-size: 1.75rem;
    font-weight: 700;
    color: #0F1F3D;
    font-family: 'JetBrains Mono', monospace;
    line-height: 1;
}
.stat-label {
    font-size: 0.7rem;
    color: #6B7280;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-top: 0.35rem;
}

/* ── Score card ──────────────────────────────────────────────────────────── */
.score-card {
    background: white;
    border-radius: 8px;
    padding: 1.75rem 1.5rem;
    border: 1px solid #E1E4E8;
    text-align: center;
}
.score-number {
    font-size: 4rem;
    font-weight: 700;
    line-height: 1;
    font-family: 'JetBrains Mono', monospace;
}
.score-label {
    font-size: 0.75rem;
    color: #6B7280;
    margin-top: 0.25rem;
    letter-spacing: 0.04em;
}
.grade-badge {
    display: inline-block;
    margin-top: 0.75rem;
    padding: 0.3rem 0.9rem;
    border-radius: 3px;
    font-size: 0.8rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}

/* ── Info tiles ──────────────────────────────────────────────────────────── */
.info-tile {
    background: white;
    border-radius: 8px;
    padding: 1.25rem;
    border: 1px solid #E1E4E8;
    height: 100%;
}
.info-tile-label {
    font-size: 0.68rem;
    color: #6B7280;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 0.4rem;
}
.info-tile-value {
    font-size: 0.95rem;
    font-weight: 600;
    color: #0F1F3D;
}
.info-tile-number {
    font-size: 1.75rem;
    font-weight: 700;
    font-family: 'JetBrains Mono', monospace;
}

/* ── Score breakdown ─────────────────────────────────────────────────────── */
.breakdown-row {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.6rem 0;
    border-bottom: 1px solid #F4F5F7;
}
.breakdown-label {
    font-size: 0.8rem;
    color: #374151;
    width: 160px;
    flex-shrink: 0;
}
.breakdown-bar-track {
    flex: 1;
    height: 6px;
    background: #E1E4E8;
    border-radius: 3px;
    overflow: hidden;
}
.breakdown-bar-fill {
    height: 100%;
    border-radius: 3px;
    transition: width 0.4s ease;
}
.breakdown-pts {
    font-size: 0.78rem;
    font-weight: 600;
    font-family: 'JetBrains Mono', monospace;
    color: #374151;
    width: 60px;
    text-align: right;
    flex-shrink: 0;
}

/* ── Finding rows ────────────────────────────────────────────────────────── */
.finding-item {
    display: flex;
    gap: 0.75rem;
    padding: 0.8rem 1rem;
    margin-bottom: 0.4rem;
    border-radius: 4px;
    align-items: flex-start;
    border-left: 3px solid transparent;
}
.finding-status {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    margin-top: 0.45rem;
    flex-shrink: 0;
}
.finding-content { flex: 1; }
.finding-title {
    font-size: 0.85rem;
    font-weight: 600;
    color: #1A1D23;
    margin-bottom: 0.15rem;
}
.finding-badge {
    display: inline-block;
    font-size: 0.65rem;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    padding: 0.1rem 0.5rem;
    border-radius: 2px;
    margin-left: 0.4rem;
    vertical-align: middle;
}
.finding-detail {
    font-size: 0.78rem;
    color: #6B7280;
    line-height: 1.5;
}

/* ── Practice cards ──────────────────────────────────────────────────────── */
.practice-card {
    background: white;
    border-radius: 6px;
    padding: 0.9rem 1.1rem;
    margin-bottom: 0.5rem;
    border: 1px solid #E1E4E8;
}
.practice-title {
    font-size: 0.875rem;
    font-weight: 600;
    color: #0F1F3D;
    margin-bottom: 0.2rem;
}
.practice-body {
    font-size: 0.78rem;
    color: #6B7280;
    line-height: 1.5;
}
.practice-meta {
    font-size: 0.68rem;
    color: #9CA3AF;
    font-family: 'JetBrains Mono', monospace;
    margin-top: 0.35rem;
}

/* ── Alert strips ────────────────────────────────────────────────────────── */
.alert-strip {
    padding: 0.65rem 1rem;
    border-radius: 4px;
    margin-bottom: 0.4rem;
    font-size: 0.85rem;
    display: flex;
    gap: 0.6rem;
    align-items: flex-start;
    border-left: 3px solid transparent;
}
.alert-dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    margin-top: 0.45rem;
    flex-shrink: 0;
}

/* ── Section header ──────────────────────────────────────────────────────── */
.section-header {
    font-size: 1rem;
    font-weight: 700;
    color: #0F1F3D;
    letter-spacing: -0.01em;
    padding-bottom: 0.5rem;
    border-bottom: 2px solid #E1E4E8;
    margin-bottom: 1rem;
}

/* ── Legend ──────────────────────────────────────────────────────────────── */
.legend-bar {
    display: flex;
    gap: 1.5rem;
    align-items: center;
    background: white;
    border: 1px solid #E1E4E8;
    border-radius: 4px;
    padding: 0.6rem 1rem;
    margin-bottom: 1rem;
    flex-wrap: wrap;
}
.legend-item {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.75rem;
    color: #374151;
}
.legend-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
}

/* ── Summary table ───────────────────────────────────────────────────────── */
.summary-row {
    padding: 0.45rem 0;
    border-bottom: 1px solid #F4F5F7;
    display: flex;
    flex-direction: column;
}
.summary-row-label {
    font-size: 0.68rem;
    font-weight: 600;
    color: #9CA3AF;
    text-transform: uppercase;
    letter-spacing: 0.07em;
}
.summary-row-value {
    font-size: 0.875rem;
    font-weight: 500;
    color: #0F1F3D;
    margin-top: 0.1rem;
}
.summary-row-empty {
    font-size: 0.875rem;
    color: #D1D5DB;
}

/* ── Upload area ─────────────────────────────────────────────────────────── */
.stFileUploader > div {
    border: 1.5px dashed #C8973A !important;
    border-radius: 6px !important;
    background: white !important;
}

/* ── Buttons ─────────────────────────────────────────────────────────────── */
.stButton > button[kind="primary"] {
    background: #0F1F3D !important;
    color: white !important;
    border: none !important;
    border-radius: 4px !important;
    font-weight: 600 !important;
    font-size: 0.875rem !important;
    padding: 0.6rem 1.5rem !important;
    letter-spacing: 0.02em !important;
}
.stButton > button[kind="primary"]:hover {
    background: #1a3366 !important;
}
.stButton > button:not([kind="primary"]) {
    border: 1px solid #E1E4E8 !important;
    border-radius: 4px !important;
    font-size: 0.85rem !important;
    color: #374151 !important;
}

/* ── Tabs ────────────────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    border-bottom: 2px solid #E1E4E8 !important;
    gap: 0 !important;
}
.stTabs [data-baseweb="tab"] {
    font-size: 0.8rem !important;
    font-weight: 500 !important;
    color: #6B7280 !important;
    border-bottom: 2px solid transparent !important;
    padding: 0.6rem 1rem !important;
    margin-bottom: -2px !important;
}
.stTabs [aria-selected="true"] {
    color: #0F1F3D !important;
    border-bottom-color: #C8973A !important;
    font-weight: 600 !important;
}

/* ── Insights block ──────────────────────────────────────────────────────── */
.insight-block {
    background: white;
    border: 1px solid #E1E4E8;
    border-radius: 6px;
    padding: 1.75rem 2rem;
    font-size: 0.9rem;
    line-height: 1.85;
    color: #1A1D23;
}
.insight-block h3 {
    font-size: 0.8rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: #C8973A;
    margin: 1.5rem 0 0.5rem 0;
    padding-bottom: 0.3rem;
    border-bottom: 1px solid #F4F5F7;
}
.insight-block h3:first-child { margin-top: 0; }
.insight-block p { margin: 0 0 0.75rem 0; }

/* ── Divider ─────────────────────────────────────────────────────────────── */
.divider {
    height: 1px;
    background: #E1E4E8;
    margin: 1.5rem 0;
}

/* ── Expander ────────────────────────────────────────────────────────────── */
.streamlit-expanderHeader {
    font-size: 0.85rem !important;
    font-weight: 600 !important;
    color: #0F1F3D !important;
}

/* ── Caption ─────────────────────────────────────────────────────────────── */
.stCaption { font-size: 0.75rem !important; color: #9CA3AF !important; }

/* ── Progress ────────────────────────────────────────────────────────────── */
.stProgress > div > div { background: #C8973A !important; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

@st.cache_data
def load_standard(path: str):
    p = _APP_DIR / path
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def _grade_colors(grade: str) -> tuple:
    return {
        "Strong":            ("#1A7F4B", "#F0FDF4"),
        "Adequate":          ("#B45309", "#FFFBEB"),
        "Needs Improvement": ("#B91C1C", "#FFF1F2"),
        "Weak":              ("#7F1D1D", "#FFF1F2"),
    }.get(grade, ("#6B7280", "#F9FAFB"))


def _score_color(score: int) -> str:
    if score >= 80: return "#1A7F4B"
    if score >= 60: return "#B45309"
    if score >= 40: return "#B91C1C"
    return "#7F1D1D"


def _bar_color(pct: float) -> str:
    if pct >= 0.75: return "#1A7F4B"
    if pct >= 0.50: return "#B45309"
    return "#B91C1C"


def render_findings(findings):
    if not findings:
        st.markdown(
            '<p style="font-size:0.82rem;color:#9CA3AF;'
            'padding:0.75rem 0;">No findings for this category.</p>',
            unsafe_allow_html=True,
        )
        return

    STATUS_CONFIG = {
        "pass": {
            "dot":    "#1A7F4B",
            "bg":     "#F0FDF4",
            "border": "#1A7F4B",
            "badge_bg":    "#DCFCE7",
            "badge_color": "#166534",
            "label": "Confirmed",
        },
        "fail": {
            "dot":    "#B91C1C",
            "bg":     "#FFF1F2",
            "border": "#B91C1C",
            "badge_bg":    "#FFE4E6",
            "badge_color": "#9F1239",
            "label": "Missing from standard",
        },
        "warning": {
            "dot":    "#B45309",
            "bg":     "#FFFBEB",
            "border": "#B45309",
            "badge_bg":    "#FEF3C7",
            "badge_color": "#92400E",
            "label": "Partially met",
        },
        "info": {
            "dot":    "#6B7280",
            "bg":     "#F9FAFB",
            "border": "#9CA3AF",
            "badge_bg":    "#F3F4F6",
            "badge_color": "#374151",
            "label": "Info",
        },
    }

    for f in findings:
        cfg = STATUS_CONFIG.get(f.status, STATUS_CONFIG["info"])
        st.markdown(f"""
        <div class="finding-item" style="background:{cfg['bg']};
             border-left-color:{cfg['border']};">
            <div class="finding-status"
                 style="background:{cfg['dot']};"></div>
            <div class="finding-content">
                <div class="finding-title">
                    {f.title}
                    <span class="finding-badge"
                          style="background:{cfg['badge_bg']};
                                 color:{cfg['badge_color']};">
                        {cfg['label']}
                    </span>
                </div>
                <div class="finding-detail">{f.detail}</div>
            </div>
        </div>""", unsafe_allow_html=True)


def render_legend():
    st.markdown("""
    <div class="legend-bar">
        <div class="legend-item">
            <div class="legend-dot" style="background:#1A7F4B;"></div>
            <span><strong>Confirmed</strong> — present in this indent</span>
        </div>
        <div class="legend-item">
            <div class="legend-dot" style="background:#B91C1C;"></div>
            <span><strong>Missing from standard</strong> — required but not found</span>
        </div>
        <div class="legend-item">
            <div class="legend-dot" style="background:#B45309;"></div>
            <span><strong>Partially met</strong> — present but incomplete</span>
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_practice_list(items, key_field="practice",
                          reason_field="reason",
                          freq_field="source_frequency"):
    if not items:
        st.markdown(
            '<p style="font-size:0.82rem;color:#9CA3AF;'
            'padding:0.75rem 0;">No items found.</p>',
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
        <div class="practice-card">
            <div class="practice-title">{title}</div>
            {f'<div class="practice-body">{reason}</div>' if reason else ''}
            <div class="practice-meta">Observed in {freq} indent(s)</div>
        </div>""", unsafe_allow_html=True)


def render_weak_list(items):
    if not items:
        st.markdown(
            '<p style="font-size:0.82rem;color:#9CA3AF;'
            'padding:0.75rem 0;">No items found.</p>',
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
        <div class="practice-card"
             style="border-left:3px solid #B91C1C;">
            <div class="practice-title" style="color:#B91C1C;">{issue}</div>
            {f'<div class="practice-body"><strong>Impact:</strong> {impact}</div>' if impact else ''}
            {f'<div class="practice-body" style="color:#1A7F4B;margin-top:0.2rem;"><strong>Resolution:</strong> {fix}</div>' if fix else ''}
            <div class="practice-meta">Observed in {freq} indent(s)</div>
        </div>""", unsafe_allow_html=True)


def folder_upload_component(key="folder_upload"):
    html = """
    <style>
    *{box-sizing:border-box;font-family:'Inter',-apple-system,sans-serif;}
    .fz{
        border:1.5px dashed #C8973A;border-radius:6px;padding:2rem;
        text-align:center;background:white;cursor:pointer;transition:all 0.15s;
    }
    .fz:hover,.fz.over{background:#FFFBEB;border-color:#B45309;}
    .fz-title{font-size:0.9rem;font-weight:600;color:#0F1F3D;margin-bottom:0.25rem;}
    .fz-sub{font-size:0.75rem;color:#9CA3AF;}
    .fz-btn{
        display:inline-block;margin-top:0.75rem;padding:0.45rem 1.25rem;
        background:#0F1F3D;color:white;border-radius:4px;font-size:0.8rem;
        font-weight:600;letter-spacing:0.02em;cursor:pointer;
        transition:background 0.15s;
    }
    .fz-btn:hover{background:#1a3366;}
    .fl{margin-top:0.75rem;text-align:left;max-height:140px;overflow-y:auto;}
    .fr{
        display:flex;align-items:center;gap:0.5rem;padding:0.3rem 0.4rem;
        border-radius:3px;font-size:0.78rem;color:#374151;
    }
    .fr:hover{background:#F4F5F7;}
    .fe{
        font-size:0.65rem;background:#E1E4E8;padding:0.1rem 0.35rem;
        border-radius:2px;font-family:'JetBrains Mono',monospace;
        color:#374151;min-width:32px;text-align:center;letter-spacing:0.04em;
    }
    .pb{height:2px;background:#E1E4E8;border-radius:1px;margin-top:0.75rem;
        overflow:hidden;display:none;}
    .pf{height:100%;background:#C8973A;transition:width 0.3s;width:0%;}
    .sm{font-size:0.72rem;color:#9CA3AF;margin-top:0.35rem;display:none;}
    </style>
    <input type="file" id="fi" webkitdirectory directory multiple
           accept=".pdf,.docx,.xlsx,.xls,.xlsm,.txt" style="display:none;">
    <div class="fz" id="fz" onclick="document.getElementById('fi').click()">
        <div class="fz-title">Select indent folder</div>
        <div class="fz-sub">Chrome and Edge only</div>
        <div class="fz-btn"
             onclick="event.stopPropagation();
                      document.getElementById('fi').click()">
            Browse
        </div>
        <div class="pb" id="pb"><div class="pf" id="pf"></div></div>
        <div class="sm" id="sm"></div>
        <div class="fl" id="fl"></div>
    </div>
    <script>
    const AL=['pdf','docx','xlsx','xls','xlsm','txt'];
    const ext=n=>n.split('.').pop().toLowerCase();
    const sz=b=>b<1024?b+'B':b<1048576?(b/1024).toFixed(1)+'KB':(b/1048576).toFixed(1)+'MB';
    async function go(files){
        const f=Array.from(files).filter(x=>AL.includes(ext(x.name)));
        if(!f.length){
            const sm=document.getElementById('sm');
            sm.style.display='block';sm.textContent='No supported files found.';
            return;
        }
        const pb=document.getElementById('pb'),pf=document.getElementById('pf'),
              sm=document.getElementById('sm'),fl=document.getElementById('fl');
        pb.style.display='block';sm.style.display='block';fl.innerHTML='';
        const res=[];
        for(let i=0;i<f.length;i++){
            const x=f[i];
            sm.textContent='Reading '+x.name+' ('+(i+1)+'/'+f.length+')';
            pf.style.width=((i+1)/f.length*100)+'%';
            const b64=await new Promise(r=>{
                const rd=new FileReader();
                rd.onload=e=>{
                    const a=new Uint8Array(e.target.result);
                    let s='';for(let j=0;j<a.byteLength;j++)
                        s+=String.fromCharCode(a[j]);r(btoa(s));
                };
                rd.readAsArrayBuffer(x);
            });
            res.push({name:x.name,content_b64:b64,size:x.size,ext:ext(x.name)});
            fl.innerHTML+='<div class="fr"><span class="fe">'+
                ext(x.name).toUpperCase()+'</span><span>'+x.name+
                '</span><span style="margin-left:auto;color:#9CA3AF;'+
                'font-size:0.7rem;font-family:monospace;">'+sz(x.size)+
                '</span></div>';
        }
        sm.textContent=f.length+' file(s) ready';
        window.parent.postMessage({type:'streamlit:setComponentValue',value:res},'*');
    }
    document.getElementById('fi').addEventListener('change',e=>go(e.target.files));
    const fz=document.getElementById('fz');
    fz.addEventListener('dragover',e=>{e.preventDefault();fz.classList.add('over');});
    fz.addEventListener('dragleave',()=>fz.classList.remove('over'));
    fz.addEventListener('drop',e=>{
        e.preventDefault();fz.classList.remove('over');
        const f=[];
        if(e.dataTransfer.items){for(let i of e.dataTransfer.items)
            if(i.kind==='file')f.push(i.getAsFile());}
        else{for(let x of e.dataTransfer.files)f.push(x);}
        go(f);
    });
    </script>
    """
    return components.html(html, height=280, scrolling=False)


def run_analysis(file_items, indent_name):
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
                    fname, content = item.name, item.getvalue()
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
                        document_name=fname, document_text=cleaned,
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
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        from src.indent_comparator import compare_indent_to_standard
        report = compare_indent_to_standard(extraction, standard)
    finally:
        sys.stdout = old_stdout
    return report


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("""
    <div style="padding:1.5rem 0 0.5rem 0;">
        <div style="font-size:0.65rem;font-weight:700;letter-spacing:0.12em;
                    text-transform:uppercase;color:#C8973A;margin-bottom:0.5rem;">
            Tata Steel
        </div>
        <div style="font-size:1rem;font-weight:700;color:white;line-height:1.3;">
            Procurement<br>Intelligence
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown(
        '<div style="font-size:0.65rem;font-weight:700;letter-spacing:0.1em;'
        'text-transform:uppercase;color:#8896B3;margin-bottom:0.5rem;">'
        'Domain</div>',
        unsafe_allow_html=True,
    )

    selected = st.radio(
        "domain",
        options=list(DOMAINS.keys()),
        label_visibility="collapsed",
    )
    domain = DOMAINS[selected]

    if st.session_state.get("active_domain") != domain["key"]:
        for key in list(st.session_state.keys()):
            if key not in ["active_domain"]:
                del st.session_state[key]
        st.session_state["active_domain"] = domain["key"]

    st.markdown("---")
    st.markdown(
        '<div style="font-size:0.65rem;font-weight:700;letter-spacing:0.1em;'
        'text-transform:uppercase;color:#8896B3;margin-bottom:0.5rem;">'
        'View</div>',
        unsafe_allow_html=True,
    )

    page = st.radio(
        "page",
        options=["Standard Practice", "Analyse New Indent"],
        label_visibility="collapsed",
    )

    st.markdown("---")
    st.markdown(
        '<p style="font-size:0.7rem;color:#4B5E82;line-height:1.6;">'
        'Procurement Intelligence System<br>'
        'Civil &amp; Electromechanical<br>'
        'Tata Steel — Internal Use Only</p>',
        unsafe_allow_html=True,
    )


# ── Load standard ─────────────────────────────────────────────────────────────
standard = load_standard(domain["standard"])

# ── Top bar ───────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="top-bar">
    <div class="top-bar-brand">Procurement Intelligence System</div>
    <div class="top-bar-domain">{domain['display']} Domain</div>
</div>
""", unsafe_allow_html=True)

if not standard:
    st.markdown(f"""
    <div style="background:white;border:1px solid #E1E4E8;border-radius:6px;
                padding:2rem;border-left:3px solid #B91C1C;">
        <div style="font-size:0.9rem;font-weight:600;color:#B91C1C;
                    margin-bottom:0.5rem;">Standard not available</div>
        <div style="font-size:0.85rem;color:#6B7280;">
            No standard practice file found for the {domain['display']} domain.<br>
            Expected at: <code>{domain['standard']}</code><br>
            Run <code>python run_steps34.py</code> to generate it.
        </div>
    </div>
    """, unsafe_allow_html=True)
    if page == "Analyse New Indent":
        st.stop()

# ── Stats bar ─────────────────────────────────────────────────────────────────
if standard:
    meta = standard.get("_metadata", {})
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    for col, val, label in [
        (c1, meta.get("source_indents", "—"),                     "Indents analysed"),
        (c2, len(standard.get("mandatory_practices", [])),        "Mandatory practices"),
        (c3, len(standard.get("documentation_requirements", [])), "Document requirements"),
        (c4, len(standard.get("risk_controls", [])),              "Risk controls"),
        (c5, len(standard.get("common_good_practices", [])),      "Good practice patterns"),
        (c6, len(standard.get("common_weak_practices", [])),      "Known weak areas"),
    ]:
        with col:
            st.markdown(f"""
            <div class="stat-tile">
                <div class="stat-value">{val}</div>
                <div class="stat-label">{label}</div>
            </div>""", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — STANDARD PRACTICE
# ══════════════════════════════════════════════════════════════════════════════

if page == "Standard Practice":

    st.markdown(f"""
    <div class="page-title">{domain['display']} Standard Practice</div>
    <div class="page-subtitle">
        Derived from {meta.get('source_indents', '?')} historical indents
        — defines what every procurement indent should contain.
    </div>
    """, unsafe_allow_html=True)

    if not standard:
        st.info("Run the pipeline to generate the standard practice.")
        st.stop()

    tabs = st.tabs([
        f"Mandatory ({len(standard.get('mandatory_practices',[]))})",
        f"Recommended ({len(standard.get('recommended_practices',[]))})",
        f"Good Practices ({len(standard.get('common_good_practices',[]))})",
        f"Weak Areas ({len(standard.get('common_weak_practices',[]))})",
        f"Risk Controls ({len(standard.get('risk_controls',[]))})",
        f"Documents ({len(standard.get('documentation_requirements',[]))})",
        f"Structure ({len(standard.get('document_structure_standards',[]))})",
        f"Patterns ({len(standard.get('category_specific_patterns',[]))})",
    ])

    with tabs[0]:
        st.markdown(
            '<div style="font-size:0.82rem;color:#6B7280;margin-bottom:1rem;">'
            'These practices must be present in every indent. '
            'When a new indent is analysed, any missing items '
            'will be flagged as <strong>Missing from standard</strong>.'
            '</div>',
            unsafe_allow_html=True,
        )
        render_practice_list(standard.get("mandatory_practices", []))

    with tabs[1]:
        st.markdown(
            '<div style="font-size:0.82rem;color:#6B7280;margin-bottom:1rem;">'
            'Practices that improve quality and should be present where applicable.'
            '</div>',
            unsafe_allow_html=True,
        )
        render_practice_list(standard.get("recommended_practices", []))

    with tabs[2]:
        st.markdown(
            '<div style="font-size:0.82rem;color:#6B7280;margin-bottom:1rem;">'
            'Patterns consistently observed in high-quality indents.'
            '</div>',
            unsafe_allow_html=True,
        )
        render_practice_list(
            standard.get("common_good_practices", []),
            key_field="practice",
            reason_field="why_it_matters",
        )

    with tabs[3]:
        st.markdown(
            '<div style="font-size:0.82rem;color:#6B7280;margin-bottom:1rem;">'
            'Most frequent weaknesses found across indents, with resolution guidance.'
            '</div>',
            unsafe_allow_html=True,
        )
        render_weak_list(standard.get("common_weak_practices", []))

    with tabs[4]:
        for item in standard.get("risk_controls", []):
            if not isinstance(item, dict):
                continue
            st.markdown(f"""
            <div class="practice-card" style="border-left:3px solid #0F1F3D;">
                <div class="practice-title">
                    {item.get('risk_area','')} — {item.get('control','')}
                </div>
                <div class="practice-body">{item.get('reason','')}</div>
                <div class="practice-meta">
                    Observed in {item.get('source_frequency',0)} indent(s)
                </div>
            </div>""", unsafe_allow_html=True)

    with tabs[5]:
        st.markdown(
            '<div style="font-size:0.82rem;color:#6B7280;margin-bottom:1rem;">'
            'Document types required. Missing documents will be flagged '
            'when a new indent is analysed.'
            '</div>',
            unsafe_allow_html=True,
        )
        render_practice_list(
            standard.get("documentation_requirements", []),
            key_field="requirement",
        )

    with tabs[6]:
        for item in standard.get("document_structure_standards", []):
            if not isinstance(item, dict):
                continue
            sections = item.get("recommended_sections", [])
            st.markdown(f"""
            <div class="practice-card">
                <div class="practice-title">
                    {item.get('document_type','')}
                    <span style="font-weight:400;color:#6B7280;font-size:0.8rem;">
                        — {item.get('procurement_category','')}
                    </span>
                </div>
                <div class="practice-body">
                    {item.get('structure_guidance','')}
                </div>
                {f'<div class="practice-body" style="margin-top:0.3rem;"><strong>Required sections:</strong> {", ".join(sections)}</div>' if sections else ''}
            </div>""", unsafe_allow_html=True)

    with tabs[7]:
        grouped: dict = {}
        for item in standard.get("category_specific_patterns", []):
            if not isinstance(item, dict):
                continue
            pt = item.get("procurement_type", "Other")
            grouped.setdefault(pt, []).append(item)
        for pt, patterns in grouped.items():
            st.markdown(
                f'<div class="section-header">{pt}</div>',
                unsafe_allow_html=True,
            )
            for p in patterns:
                st.markdown(f"""
                <div class="practice-card">
                    <div class="practice-title">
                        {p.get('document_type','')}
                    </div>
                    <div class="practice-body">{p.get('pattern','')}</div>
                    {f'<div class="practice-body" style="color:#0F1F3D;margin-top:0.3rem;"><strong>Recommendation:</strong> {p.get("recommendation","")}</div>' if p.get('recommendation') else ''}
                </div>""", unsafe_allow_html=True)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    st.download_button(
        f"Download {domain['display']} Standard (JSON)",
        data=json.dumps(standard, indent=2),
        file_name=f"{domain['key']}_best_practice_standard.json",
        mime="application/json",
    )

    # ── Standard Insights ─────────────────────────────────────────────────────
    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="page-title" style="font-size:1.2rem;">
        Standard Insights
    </div>
    <div class="page-subtitle">
        Natural language summary of what was learned from all
        {meta.get('source_indents','?')} historical indents.
    </div>
    """, unsafe_allow_html=True)

    insight_key = f"standard_insight_{domain['key']}"
    if insight_key not in st.session_state:
        if st.button("Generate insights", key=f"gen_std_{domain['key']}"):
            with st.spinner("Generating — this takes 10–15 seconds..."):
                old_stdout = sys.stdout
                sys.stdout = io.StringIO()
                try:
                    from src.insight_generator import generate_standard_insight
                    insight = generate_standard_insight(standard)
                finally:
                    sys.stdout = old_stdout
                st.session_state[insight_key] = insight
            st.rerun()
    else:
        insight = st.session_state[insight_key]
        st.markdown(
            f'<div class="insight-block">{insight}</div>',
            unsafe_allow_html=True,
        )
        st.markdown("<br>", unsafe_allow_html=True)
        c1, c2 = st.columns([1, 5])
        with c1:
            st.download_button(
                "Download",
                data=insight,
                file_name=f"{domain['key']}_standard_insights.txt",
                mime="text/plain",
                key=f"dl_std_{domain['key']}",
            )
        with c2:
            if st.button("Regenerate", key=f"regen_std_{domain['key']}"):
                del st.session_state[insight_key]
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — ANALYSE NEW INDENT
# ══════════════════════════════════════════════════════════════════════════════

elif page == "Analyse New Indent":

    st.markdown(f"""
    <div class="page-title">Analyse New Indent</div>
    <div class="page-subtitle">
        Upload documents from an indent folder to compare against
        the {domain['display']} standard.
    </div>
    """, unsafe_allow_html=True)

    # Upload section
    st.markdown(
        '<div class="section-header">Upload Documents</div>',
        unsafe_allow_html=True,
    )

    col_name, col_mode = st.columns([2, 1])
    with col_name:
        indent_name = st.text_input(
            "Indent name",
            placeholder="e.g. Indent-36156 Precast Drains Kalinganagar",
            label_visibility="visible",
            key=f"name_{domain['key']}",
        ) or "New Indent"
    with col_mode:
        mode = st.selectbox(
            "Upload method",
            options=["Multi-File Upload", "Folder Upload", "Single File"],
            key=f"mode_{domain['key']}",
        )

    st.markdown("<br>", unsafe_allow_html=True)

    file_items  = []
    files_ready = False

    if mode == "Folder Upload":
        st.markdown(
            '<div style="font-size:0.78rem;color:#9CA3AF;'
            'margin-bottom:0.75rem;">Chrome and Edge only. '
            'If the Analyse button stays disabled, use Multi-File Upload.'
            '</div>',
            unsafe_allow_html=True,
        )
        folder_data = folder_upload_component(key=f"folder_{domain['key']}")
        if (folder_data and isinstance(folder_data, list)
                and len(folder_data) > 0):
            file_items  = folder_data
            files_ready = True
            st.caption(f"{len(file_items)} file(s) loaded from folder")

    elif mode == "Multi-File Upload":
        st.markdown(
            '<div style="font-size:0.78rem;color:#9CA3AF;'
            'margin-bottom:0.5rem;">'
            'Open the indent folder, select all files (Ctrl+A), '
            'then drag into the area below or click Browse.'
            '</div>',
            unsafe_allow_html=True,
        )
        uploaded = st.file_uploader(
            "Drop files here",
            type=["pdf", "docx", "xlsx", "xls", "xlsm", "txt"],
            accept_multiple_files=True,
            label_visibility="collapsed",
            key=f"multi_{domain['key']}",
        )
        if uploaded:
            file_items  = uploaded
            files_ready = True
            st.caption(f"{len(uploaded)} file(s) selected")

    else:
        single = st.file_uploader(
            "Select document",
            type=["pdf", "docx", "xlsx", "xls", "xlsm", "txt"],
            accept_multiple_files=False,
            label_visibility="collapsed",
            key=f"single_{domain['key']}",
        )
        if single:
            file_items  = [single]
            files_ready = True
            st.caption(f"1 file selected: {single.name}")

    if files_ready:
        names = (
            [f["name"] for f in file_items]
            if file_items and isinstance(file_items[0], dict)
            else [f.name for f in file_items]
        )
        st.markdown(
            '<div style="display:flex;flex-wrap:wrap;gap:0.3rem;'
            'margin:0.5rem 0 1rem 0;">'
            + "".join(
                f'<span style="background:white;border:1px solid #E1E4E8;'
                f'border-radius:3px;padding:0.2rem 0.6rem;font-size:0.72rem;'
                f'color:#374151;font-family:monospace;">{n}</span>'
                for n in names
            )
            + "</div>",
            unsafe_allow_html=True,
        )

    analyse_btn = st.button(
        "Run Analysis",
        type="primary",
        disabled=not files_ready,
        key=f"analyse_{domain['key']}",
    )

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    # ── Run ───────────────────────────────────────────────────────────────────
    if analyse_btn and files_ready:
        with st.spinner("Extracting indent data — 1 LLM call..."):
            extraction = run_analysis(file_items, indent_name)

        if "_error" in extraction:
            st.error(f"Extraction failed: {extraction['_error']}")
            st.stop()
        if not extraction:
            st.error("No content extracted. Check your documents and try again.")
            st.stop()

        with st.spinner("Comparing against standard..."):
            report = run_comparison(extraction, standard)

        # Clear old indent insight
        old_key = f"indent_insight_{st.session_state.get('last_indent_id','')}"
        if old_key in st.session_state:
            del st.session_state[old_key]

        st.session_state["report"]         = report
        st.session_state["extraction"]     = extraction
        st.session_state["last_indent_id"] = report.indent_id

    # ── Display ───────────────────────────────────────────────────────────────
    if "report" in st.session_state:
        report     = st.session_state["report"]
        extraction = st.session_state["extraction"]

        grade_color, grade_bg = _grade_colors(report.overall_grade)

        # Score row
        st.markdown(
            f'<div class="page-title" style="font-size:1.1rem;">'
            f'Results — {report.indent_id.replace("_", " ")}'
            f'</div>',
            unsafe_allow_html=True,
        )

        c1, c2, c3, c4 = st.columns([1, 2, 1, 1])
        with c1:
            st.markdown(f"""
            <div class="score-card">
                <div class="score-number"
                     style="color:{_score_color(report.overall_score)};">
                    {report.overall_score}
                </div>
                <div class="score-label">Score out of 100</div>
                <div class="grade-badge"
                     style="background:{grade_bg};color:{grade_color};">
                    {report.overall_grade}
                </div>
            </div>""", unsafe_allow_html=True)

        with c2:
            # Score breakdown bars
            bd   = report.score_breakdown or {}
            rows = [
                ("Mandatory",     "mandatory",     40),
                ("Documentation", "documentation", 20),
                ("Risk controls", "risk",          20),
                ("Vendor",        "vendor",        10),
                ("Approval",      "approval",      10),
            ]
            breakdown_html = '<div style="background:white;border:1px solid #E1E4E8;border-radius:8px;padding:1.25rem;">'
            breakdown_html += '<div style="font-size:0.68rem;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;color:#9CA3AF;margin-bottom:0.75rem;">Score breakdown</div>'
            for label, key, max_pts in rows:
                earned = bd.get(key, max_pts)
                pct    = earned / max_pts if max_pts else 0
                color  = _bar_color(pct)
                breakdown_html += f"""
                <div class="breakdown-row">
                    <div class="breakdown-label">{label}</div>
                    <div class="breakdown-bar-track">
                        <div class="breakdown-bar-fill"
                             style="width:{pct*100:.0f}%;background:{color};">
                        </div>
                    </div>
                    <div class="breakdown-pts">
                        {earned:.0f}/{max_pts}
                    </div>
                </div>"""
            breakdown_html += "</div>"
            st.markdown(breakdown_html, unsafe_allow_html=True)

        with c3:
            missing = len([f for f in (
                report.mandatory_findings +
                report.documentation_findings
            ) if f.status == "fail"])
            st.markdown(f"""
            <div class="info-tile">
                <div class="info-tile-label">Missing from standard</div>
                <div class="info-tile-number"
                     style="color:#B91C1C;">{missing}</div>
            </div>""", unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown(f"""
            <div class="info-tile">
                <div class="info-tile-label">Recommendations</div>
                <div class="info-tile-number"
                     style="color:#B45309;">
                    {len(report.recommendations)}
                </div>
            </div>""", unsafe_allow_html=True)

        with c4:
            st.markdown(f"""
            <div class="info-tile">
                <div class="info-tile-label">Procurement type</div>
                <div class="info-tile-value"
                     style="margin-top:0.5rem;font-size:0.85rem;">
                    {report.procurement_type}
                </div>
            </div>""", unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)
            # Cache status
            cache_dir  = _APP_DIR / "results_cache"
            is_cached  = any(cache_dir.glob("*.json")) if cache_dir.exists() else False
            cache_label = "Score locked — cached" if is_cached else "Not cached"
            cache_color = "#1A7F4B" if is_cached else "#9CA3AF"
            st.markdown(f"""
            <div class="info-tile">
                <div class="info-tile-label">Cache status</div>
                <div style="font-size:0.8rem;font-weight:600;
                            color:{cache_color};margin-top:0.4rem;">
                    {cache_label}
                </div>
            </div>""", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # Strengths, recommendations, cross-doc issues
        if report.strengths or report.recommendations or report.cross_doc_issues:
            col_s, col_r = st.columns(2)
            with col_s:
                if report.strengths:
                    st.markdown(
                        '<div class="section-header">Strengths</div>',
                        unsafe_allow_html=True,
                    )
                    for s in report.strengths:
                        st.markdown(f"""
                        <div class="alert-strip"
                             style="background:#F0FDF4;
                                    border-left-color:#1A7F4B;">
                            <div class="alert-dot"
                                 style="background:#1A7F4B;"></div>
                            <span style="font-size:0.85rem;color:#166534;">
                                {s}
                            </span>
                        </div>""", unsafe_allow_html=True)

            with col_r:
                if report.recommendations:
                    st.markdown(
                        '<div class="section-header">Recommendations</div>',
                        unsafe_allow_html=True,
                    )
                    for r in report.recommendations:
                        st.markdown(f"""
                        <div class="alert-strip"
                             style="background:#F8F9FF;
                                    border-left-color:#0F1F3D;">
                            <div class="alert-dot"
                                 style="background:#0F1F3D;"></div>
                            <span style="font-size:0.85rem;color:#1A1D23;">
                                {r}
                            </span>
                        </div>""", unsafe_allow_html=True)

            if report.cross_doc_issues:
                st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
                st.markdown(
                    '<div class="section-header">Cross-Document Issues</div>',
                    unsafe_allow_html=True,
                )
                for issue in report.cross_doc_issues:
                    st.markdown(f"""
                    <div class="alert-strip"
                         style="background:#FFFBEB;
                                border-left-color:#B45309;">
                        <div class="alert-dot"
                             style="background:#B45309;"></div>
                        <span style="font-size:0.85rem;color:#92400E;">
                            {issue}
                        </span>
                    </div>""", unsafe_allow_html=True)

        # Detailed findings
        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="section-header">Detailed Findings</div>',
            unsafe_allow_html=True,
        )
        render_legend()

        tabs2 = st.tabs([
            f"Mandatory ({len(report.mandatory_findings)})",
            f"Documents ({len(report.documentation_findings)})",
            f"Risk Controls ({len(report.risk_findings)})",
            f"Vendor ({len(report.vendor_findings)})",
            f"Approvals ({len(report.approval_findings)})",
            f"Structure ({len(report.structure_findings)})",
            f"Good Practices ({len(report.good_practice_findings)})",
            f"Weak Areas ({len(report.weak_practice_findings)})",
        ])

        captions = [
            "Mandatory practices from the standard — any missing items reduce the score significantly.",
            "Required document types — missing documents are flagged as Missing from standard.",
            "Risk controls from the standard checked against this indent.",
            "Vendor panel and vendor requirements.",
            "Approval chain and authority requirements.",
            "Document structure quality compared to standard expectations.",
            "Good practices observed in this indent.",
            "Weak areas identified in this indent.",
        ]

        findings_list = [
            report.mandatory_findings,
            report.documentation_findings,
            report.risk_findings,
            report.vendor_findings,
            report.approval_findings,
            report.structure_findings,
            report.good_practice_findings,
            report.weak_practice_findings,
        ]

        for i, (tab, caption, findings) in enumerate(
            zip(tabs2, captions, findings_list)
        ):
            with tab:
                st.markdown(
                    f'<div style="font-size:0.78rem;color:#9CA3AF;'
                    f'margin-bottom:0.75rem;">{caption}</div>',
                    unsafe_allow_html=True,
                )
                render_findings(findings)

        # Procurement summary
        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        with st.expander("Extracted Procurement Summary", expanded=False):
            ps = extraction.get("procurement_summary", {}) or {}
            fields = [
                ("Package description",      ps.get("package_description")),
                ("Scope of work",            ps.get("scope_of_work")),
                ("Procurement type",         ps.get("procurement_type")),
                ("Location",                 ps.get("location")),
                ("Estimated cost (Cr)",      ps.get("estimated_cost_crores")),
                ("Contract period (months)", ps.get("contract_period_months")),
                ("Order required date",      ps.get("order_required_date")),
                ("Job risk category",        ps.get("job_risk_category")),
                ("Single party",             ps.get("is_single_party")),
                ("Vendor panel",             ps.get("vendor_panel")),
                ("Vendor count",             ps.get("vendor_count")),
                ("Term sheet type",          ps.get("term_sheet_type")),
                ("Technical spec attached",  ps.get("technical_spec_attached")),
                ("HSE plan available",       ps.get("hse_plan_available")),
                ("BOQ surplus checked",      ps.get("boq_surplus_checked")),
                ("Approval authority",       ps.get("approval_authority")),
                ("Approval date",            ps.get("indent_approval_date")),
                ("Procurement head",         ps.get("procurement_head")),
            ]
            ca, cb = st.columns(2)
            for i, (label, value) in enumerate(fields):
                col = ca if i % 2 == 0 else cb
                with col:
                    display = (
                        value if value and
                        str(value).lower() not in ("null", "none", "")
                        else None
                    )
                    st.markdown(f"""
                    <div class="summary-row">
                        <div class="summary-row-label">{label}</div>
                        {f'<div class="summary-row-value">{display}</div>'
                         if display else
                         '<div class="summary-row-empty">Not found</div>'}
                    </div>""", unsafe_allow_html=True)

        # Downloads
        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        d1, d2, _ = st.columns([1, 1, 2])
        with d1:
            st.download_button(
                "Download extraction (JSON)",
                data=json.dumps(extraction, indent=2, default=str),
                file_name=f"{report.indent_id}_extraction.json",
                mime="application/json",
            )
        with d2:
            st.download_button(
                "Download report (JSON)",
                data=json.dumps({
                    "indent_id":        report.indent_id,
                    "score":            report.overall_score,
                    "grade":            report.overall_grade,
                    "score_breakdown":  report.score_breakdown,
                    "recommendations":  report.recommendations,
                    "gaps":             report.gaps,
                    "strengths":        report.strengths,
                    "cross_doc_issues": report.cross_doc_issues,
                }, indent=2),
                file_name=f"{report.indent_id}_report.json",
                mime="application/json",
            )

        # ── Indent Insights ───────────────────────────────────────────────────
        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        st.markdown(f"""
        <div class="page-title" style="font-size:1.2rem;">
            Indent Insights
        </div>
        <div class="page-subtitle">
            Deep narrative analysis — document interrelationships,
            why this indent scored {report.overall_score}/100,
            and specific recommendations for improvement.
        </div>
        """, unsafe_allow_html=True)

        ikey = f"indent_insight_{report.indent_id}"
        if ikey not in st.session_state:
            if st.button(
                "Generate insights",
                key=f"gen_indent_{report.indent_id}",
            ):
                with st.spinner(
                    "Generating deep analysis — 15–20 seconds..."
                ):
                    old_stdout = sys.stdout
                    sys.stdout = io.StringIO()
                    try:
                        from src.insight_generator import generate_indent_insight
                        insight = generate_indent_insight(
                            extraction, report, standard
                        )
                    finally:
                        sys.stdout = old_stdout
                    st.session_state[ikey] = insight
                st.rerun()
        else:
            insight = st.session_state[ikey]
            st.markdown(
                f'<div class="insight-block">{insight}</div>',
                unsafe_allow_html=True,
            )
            st.markdown("<br>", unsafe_allow_html=True)
            c1, c2, _ = st.columns([1, 1, 4])
            with c1:
                st.download_button(
                    "Download insights",
                    data=insight,
                    file_name=f"{report.indent_id}_insights.txt",
                    mime="text/plain",
                    key=f"dl_indent_{report.indent_id}",
                )
            with c2:
                if st.button(
                    "Regenerate",
                    key=f"regen_indent_{report.indent_id}",
                ):
                    del st.session_state[ikey]
                    st.rerun()

    else:
        st.markdown("""
        <div style="text-align:center;padding:4rem 2rem;color:#9CA3AF;">
            <div style="font-size:0.9rem;font-weight:500;color:#6B7280;
                        margin-bottom:0.5rem;">
                No indent analysed yet
            </div>
            <div style="font-size:0.8rem;line-height:1.6;">
                Select an upload method above, add your documents,
                and click Run Analysis.
            </div>
        </div>
        """, unsafe_allow_html=True)
