"""
procurement_tracker_extractor.py  (v3)
───────────────────────────────────────
Converts raw Procurement Tracker PDF text into compact structured
key:value text for the LLM.

Changes from v2:
  - Validation logic now imported from schemas.py so both layers
    use identical rules — extractor and Pydantic model agree
  - Three-layer defence:
      Layer 1: regex extracts field values
      Layer 2: extractor validates by field type (this file)
      Layer 3: Pydantic ProcurementSummary validates LLM output
  - specific_spec_attached: bare dates rejected
  - hse_plan_available: term sheet names (B Class, C Class) rejected
  - boq_surplus_checked: term sheet names rejected
"""

import re
from typing import Optional

# ── Import validation helpers from schemas ────────────────────────────────────
# Same functions used by Pydantic validators — single source of truth
try:
    from src.schemas import (
        _clean_yesno,
        _clean_numeric,
        _clean_date,
        _clean_technical_spec,
        _is_term_sheet_value,
        _has_digits,
    )
except ImportError:
    # Fallback if schemas not importable (e.g. running standalone)
    def _has_digits(v):
        return any(c.isdigit() for c in v)

    def _is_term_sheet_value(v):
        lower = v.lower()
        return any(s in lower for s in [
            "term sheet", "class civil", "class a", "class b",
            "class c", "b class", "a class", "c class",
        ])

    def _clean_yesno(v):
        if not v: return None
        v = v.strip()
        if _is_term_sheet_value(v): return None
        if re.search(r"\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}", v): return None
        if len(v) > 60:
            m = re.search(
                r"\b(yes|no|na|n/a|not\s+applicable|attached|"
                r"available|not\s+available|not\s+attached)\b",
                v.lower()
            )
            return m.group(0).title() if m else None
        yesno = ["yes","no","na","n/a","not applicable","attached",
                 "available","not available","not attached","applicable"]
        if any(w in v.lower() for w in yesno): return v
        return v if len(v) <= 30 else None

    def _clean_numeric(v):
        if not v: return None
        v = v.strip()
        if not _has_digits(v): return None
        if _is_term_sheet_value(v): return None
        return v

    def _clean_date(v):
        if not v: return None
        v = v.strip()
        return v if _has_digits(v) else None

    def _clean_technical_spec(v):
        if not v: return None
        v = v.strip()
        lower = v.lower()
        if _is_term_sheet_value(v): return None
        is_bare_date = (
            re.search(r"\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}", v)
            and len(v) <= 12
        )
        if is_bare_date: return None
        if any(w in lower for w in [
            "yes","no","na","n/a","attached","not attached","available"
        ]): return v
        if any(ext in lower for ext in [
            ".pdf",".docx",".xlsx",".doc",".xls","/"
        ]): return v
        return v if len(v) <= 40 else None


# ── Field definitions ─────────────────────────────────────────────────────────
# (label, patterns, field_type)
# field_type maps to a validation function

FIELD_PATTERNS = [
    # Basic Information
    ("Indent No",           [r"indent\s*no[:\s]+([^\n]+)"],              "text"),
    ("RFQ No",              [r"rfq\s*no[:\s]+([^\n]+)"],                 "text"),
    ("Submission Date",     [r"indent\s*submission\s*date[:\s]+([^\n]+)"], "date"),
    ("Indentor",            [r"indentor[:\s]+([^\n]+)"],                 "text"),
    ("Location",            [r"\*?location\s*:[:\s]+([^\n]+)"],          "text"),
    ("Ensafe Location",     [r"\*?ensafe\s*location\s*:[:\s]+([^\n]+)"], "text"),
    ("Project Name",        [r"\*?project\s*name\s*:[:\s]+([^\n]+)"],    "text"),
    ("Package Description", [r"\*?package\s*description\s*:[:\s]+([^\n]+)"], "text"),
    ("Brief Scope of Work", [
        r"\*?brief\s*scope\s*of\s*work\s*:[:\s]+([\s\S]{10,300}?)"
        r"(?=\*?background|font|size|\Z)"
    ], "multiline"),
    ("Background", [
        r"\*?background\s*&?\s*essentially?\s*:[:\s]+([\s\S]{10,400}?)"
        r"(?=\*?type of indent|primavera|\Z)"
    ], "multiline"),

    # Sourcing & Commercial
    ("Type of Indent",     [r"\*?type\s*of\s*indent\s*:[:\s]+([^\n]+)"],       "text"),
    ("Discipline",         [r"\*?discipline\s*:[:\s]+([^\n]+)"],               "text"),
    ("Order/ARC",          [r"\*?order\s*/?\s*arc\s*:[:\s]+([^\n]+)"],         "text"),
    ("ARC Type",           [r"arc\s*type\s*:[:\s]+([^\n]+)"],                  "text"),
    ("Period of Contract", [r"\*?period\s*of\s*contract[^:]*:[:\s]+([^\n]+)"], "text"),
    ("Contract Ceiling Value", [
        r"\*?contract\s*ceiling\s*value[^:]*:[:\s]+([^\n]+)"
    ], "numeric"),
    ("Package Type",       [r"\*?package\s*type\s*:[:\s]+([^\n]+)"],   "text"),
    ("FEL Based Ordering", [r"\*?fel\s*based\s*ordering\s*:[:\s]+([^\n]+)"], "yesno"),
    ("Sourcing",           [r"\*?sourcing\s*:[:\s]+([^\n]+)"],         "text"),
    ("Job Risk Category",  [r"\*?job\s*risk\s*category\s*:[:\s]+([^\n]+)"], "text"),
    ("Job Risk Type",      [r"\*?job\s*risk\s*type\s*:[:\s]+([^\n]+)"], "text"),
    ("Account Assignment", [r"\*?account\s*assignment\s*:[:\s]+([^\n]+)"], "text"),
    ("Item Category",      [r"\*?item\s*category\s*:[:\s]+([^\n]+)"],  "text"),
    ("Item Sub-Category",  [r"\*?item\s*sub-?category\s*:[:\s]+([^\n]+)"], "text"),

    # Dates
    ("Order Reqd Date", [
        r"\*?order\s*req[d]?\s*date\s*:[:\s]+([^\n]+)"
    ], "date"),
    ("Material/Service Reqd At Site", [
        r"\*?material\s*/\s*service\s*req[d]?\s*at\s*site[^:]*:[:\s]+([^\n]+)"
    ], "date"),

    # Cost
    ("Estimated Cost (Cr)", [
        r"\*?estimated\s*cost[^:]*:[:\s]+([^\n]+)"
    ], "numeric"),

    # PR Checklist — strictly validated
    ("Spot Tender",        [r"\*?spot\s*tender[^:]*:[:\s]+([^\n]+)"],         "yesno"),
    ("HSE Plan Available", [r"\*?hse\s*plan\s*document[^:]*:[:\s]+([^\n]+)"], "yesno"),
    ("BOQ Surplus Check",  [
        r"\*?boq\s*prepared[^:]*surplus[^:]*:[:\s]+([^\n]+)"
    ], "yesno"),
    ("Single Party",       [
        r"\*?is\s*it\s*a\s*single\s*party[?]?\s*:[:\s]+([^\n]+)"
    ], "yesno"),
    ("Class A Vendor",     [r"\*?class\s*a\s*vendor[?]?\s*:[:\s]+([^\n]+)"],  "yesno"),

    # Technical Spec — special validation (rejects bare dates)
    ("Technical Spec File",[r"\*?technical\s*spec[^:]*:[:\s]+([^\n]+)"], "tech_spec"),

    # Term Sheet — accept the name, it belongs here
    ("Term Sheet",         [r"\*?term\s*sheet\s*:[:\s]+([^\n]+)"], "text"),

    # Approvals
    ("Engineering Manager",[r"\*?engineering\s*manager\s*:[:\s]+([^\n]+)"],  "text"),
    ("Project Manager",    [r"\*?project\s*manager\s*:[:\s]+([^\n]+)"],      "text"),
    ("Dept Chief/Head",    [r"\*?dept\s*chief[^:]*:[:\s]+([^\n]+)"],         "text"),
    ("Indent Approval",    [r"indent\s*approval\s*\n([^\n]+)"],              "text"),
    ("Indent Approval Date",[r"indent\s*approval\s*date\s*:[:\s]+([^\n]+)"], "date"),
    ("Procurement Head",   [r"\*?procurement\s*head\s*:[:\s]+([^\n]+)"],     "text"),
    ("Procurement Manager",[r"procurement\s*manager\s*:[:\s]+([^\n]+)"],     "text"),
    ("Priority",           [r"\*?priority\s*:[:\s]+([^\n]+)"],               "text"),
    ("Performance Guarantee", [
        r"\*?applicability\s*of\s*performance\s*guarantee[^:]*:[:\s]+([^\n]+)"
    ], "yesno"),
]


# ── Validation dispatcher ─────────────────────────────────────────────────────

def _validate(label: str, value: str, field_type: str) -> Optional[str]:
    """
    Validate extracted value by field type.
    Routes to the same validation functions used by Pydantic validators
    in ProcurementSummary — single source of truth.
    """
    value = value.strip()
    if len(value) < 2:        return None
    if value.endswith(":"):   return None

    # Skip UI navigation artifacts
    if value.lower() in {
        "click here", "download", "upload", "submit",
        "save", "cancel", "back", "next", "home",
    }:
        return None

    if field_type == "numeric":
        return _clean_numeric(value)

    if field_type == "date":
        return _clean_date(value)

    if field_type == "yesno":
        return _clean_yesno(value)

    if field_type == "tech_spec":
        return _clean_technical_spec(value)

    if field_type == "multiline":
        cleaned = re.sub(r"\s+", " ", value).strip()
        return cleaned[:500] if cleaned else None

    # Default: text
    value = re.sub(r"\s*\|\s*\d+\s*$", "", value).strip()
    value = re.sub(r"\s+", " ", value).strip()
    return value[:300] if value else None


# ── Sidebar stripping ─────────────────────────────────────────────────────────

_SIDEBAR_RE = re.compile("|".join([
    r"procurement hierarchy",
    r"dashboard",
    r"tslist",
    r"auto grn",
    r"claim request",
    r"contracting",
    r"online certificate",
    r"\(profile\)",
    r"\(user\.aspx\)",
]), re.IGNORECASE)


def _strip_sidebar(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines()
        if not _SIDEBAR_RE.search(line.strip())
    )


# ── Vendor panel extraction ───────────────────────────────────────────────────

def _extract_vendor_panel(text: str) -> Optional[str]:
    match = re.search(
        r"proposed\s*vendor\s*panel\s*:?\s*\n([\s\S]{20,800}?)"
        r"(?=cost\s*estimate|sourcing\s*&|pr\s*check|\Z)",
        text, re.IGNORECASE,
    )
    if not match:
        return None
    vendor_section = match.group(1)
    rows = re.findall(
        r"(\d+)\s+([A-Z0-9]{2,8})\s+"
        r"([A-Z][A-Z\s&./()]{3,50}?)(?:\s+\d|\s+NA|\s*\n)",
        vendor_section, re.IGNORECASE,
    )
    if rows:
        return "\n".join(
            f"  {r[0]}. [{r[1]}] {r[2].strip()}" for r in rows[:8]
        )
    return vendor_section[:300].strip() or None


# ── Remarks extraction ────────────────────────────────────────────────────────

def _extract_remarks(text: str) -> Optional[str]:
    match = re.search(
        r"remarks\s*\n([\s\S]{10,600}?)(?=primavera|$)",
        text, re.IGNORECASE,
    )
    if not match:
        return None
    lines = [l.strip() for l in match.group(1).splitlines() if l.strip()]
    meaningful = [
        l for l in lines
        if len(l) > 8 and
        not re.match(r"^(version|date|user|download|files)$", l, re.I)
    ]
    return " | ".join(meaningful[:5]) if meaningful else None


# ── Cross-field validation ────────────────────────────────────────────────────

def _cross_validate(extracted: dict) -> None:
    """
    Final pass — catch any values that slipped through per-field validation.
    Belt-and-suspenders check using the same helpers from schemas.py.
    """
    # Yes/no fields must not contain term sheet names or dates
    yesno_fields = [
        "HSE Plan Available", "BOQ Surplus Check", "Single Party",
        "Class A Vendor", "FEL Based Ordering", "Spot Tender",
        "Performance Guarantee",
    ]
    for field in yesno_fields:
        if field not in extracted:
            continue
        result = _clean_yesno(extracted[field])
        if result is None:
            del extracted[field]
        else:
            extracted[field] = result

    # Cost and ceiling must have digits
    for field in ["Estimated Cost (Cr)", "Contract Ceiling Value"]:
        if field in extracted and not _has_digits(extracted[field]):
            del extracted[field]

    # Date fields must have digits
    for field in [
        "Indent Approval Date", "Order Reqd Date",
        "Submission Date", "Material/Service Reqd At Site",
    ]:
        if field in extracted:
            result = _clean_date(extracted[field])
            if result is None:
                del extracted[field]

    # Technical spec — apply special validation
    if "Technical Spec File" in extracted:
        result = _clean_technical_spec(extracted["Technical Spec File"])
        if result is None:
            del extracted["Technical Spec File"]


# ── Main entry point ──────────────────────────────────────────────────────────

def extract_tracker_fields(raw_text: str) -> str:
    """
    Main entry point.
    Takes raw Procurement Tracker PDF text.
    Returns compact validated key:value string for the LLM.
    """
    text = _strip_sidebar(raw_text)
    text = re.sub(r"[ \t]+", " ", text)

    extracted = {}

    for label, patterns, field_type in FIELD_PATTERNS:
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                raw_value = (
                    match.group(1).strip()
                    if match.lastindex
                    else match.group(0).strip()
                )
                raw_value = re.sub(r"\s+", " ", raw_value).strip()
                validated = _validate(label, raw_value, field_type)
                if validated:
                    extracted[label] = validated
                    break

    vendor_panel = _extract_vendor_panel(text)
    if vendor_panel:
        extracted["Proposed Vendor Panel"] = vendor_panel

    remarks = _extract_remarks(text)
    if remarks:
        extracted["Remarks/History"] = remarks

    _cross_validate(extracted)

    if not extracted:
        return text[:3000].strip()

    lines = ["=== PROCUREMENT TRACKER (Extracted Fields) ==="]
    for label, value in extracted.items():
        lines.append(f"{label}: {value}")

    return "\n".join(lines)


# ── Document detection ────────────────────────────────────────────────────────

def is_procurement_tracker_doc(
    document_name: str,
    document_text: str,
) -> bool:
    """Detect Procurement Tracker portal export by content signature."""
    text_sample = document_text[:4000].lower()
    signals = [
        "procurement tracker", "indent no", "rfq no",
        "indentor", "indent submission", "wrench project",
        "fel based ordering", "proposed vendor panel",
        "pr checklist", "pr checklists",
    ]
    return sum(1 for s in signals if s in text_sample) >= 3
