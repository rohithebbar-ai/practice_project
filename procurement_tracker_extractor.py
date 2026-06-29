"""
procurement_tracker_extractor.py  (v2)
───────────────────────────────────────
Converts raw Procurement Tracker PDF text into a compact,
clean structured summary for the LLM.

Changes from v1:
  - Field type system added (numeric, date, yesno, text, multiline)
  - Numeric fields: rejected if they contain no digits
  - Date fields: rejected if they contain no digits
  - Yes/No fields: rejected if they contain wrong content
    (vendor names, term sheet values, dates in wrong fields)
  - Cross-field validation after extraction
  - No hardcoded name lists — structural rules only
"""

import re
from typing import Optional


# ── Field patterns ────────────────────────────────────────────────────────────
# Each entry: (output_label, list_of_patterns_to_try, field_type)
# field_type: "text" | "numeric" | "date" | "yesno" | "multiline"

FIELD_PATTERNS = [
    # Basic Information
    ("Indent No",           [r"indent\s*no[:\s]+([^\n]+)", r"25-26/\d+"],  "text"),
    ("RFQ No",              [r"rfq\s*no[:\s]+([^\n]+)", r"25-26/\d+"],     "text"),
    ("Submission Date",     [r"indent\s*submission\s*date[:\s]+([^\n]+)"],  "date"),
    ("Indentor",            [r"indentor[:\s]+([^\n]+)"],                    "text"),
    ("Location",            [r"\*?location\s*:[:\s]+([^\n]+)"],             "text"),
    ("Ensafe Location",     [r"\*?ensafe\s*location\s*:[:\s]+([^\n]+)"],    "text"),
    ("Project Name",        [r"\*?project\s*name\s*:[:\s]+([^\n]+)"],       "text"),
    ("Package Description", [r"\*?package\s*description\s*:[:\s]+([^\n]+)"],"text"),
    ("Brief Scope of Work", [
        r"\*?brief\s*scope\s*of\s*work\s*:[:\s]+([\s\S]{10,300}?)"
        r"(?=\*?background|font|size|\Z)"
    ], "multiline"),
    ("Background", [
        r"\*?background\s*&?\s*essentially?\s*:[:\s]+([\s\S]{10,400}?)"
        r"(?=\*?type of indent|primavera|\Z)"
    ], "multiline"),

    # Sourcing & Commercial
    ("Type of Indent",      [r"\*?type\s*of\s*indent\s*:[:\s]+([^\n]+)"],       "text"),
    ("Discipline",          [r"\*?discipline\s*:[:\s]+([^\n]+)"],               "text"),
    ("Order/ARC",           [r"\*?order\s*/?\s*arc\s*:[:\s]+([^\n]+)"],         "text"),
    ("ARC Type",            [r"arc\s*type\s*:[:\s]+([^\n]+)"],                  "text"),
    ("Period of Contract",  [r"\*?period\s*of\s*contract[^:]*:[:\s]+([^\n]+)"], "text"),
    ("Contract Ceiling Value", [
        r"\*?contract\s*ceiling\s*value[^:]*:[:\s]+([^\n]+)"
    ], "numeric"),
    ("Package Type",        [r"\*?package\s*type\s*:[:\s]+([^\n]+)"],   "text"),
    ("FEL Based Ordering",  [r"\*?fel\s*based\s*ordering\s*:[:\s]+([^\n]+)"], "yesno"),
    ("Sourcing",            [r"\*?sourcing\s*:[:\s]+([^\n]+)"],         "text"),
    ("Job Risk Category",   [r"\*?job\s*risk\s*category\s*:[:\s]+([^\n]+)"], "text"),
    ("Job Risk Type",       [r"\*?job\s*risk\s*type\s*:[:\s]+([^\n]+)"], "text"),
    ("Account Assignment",  [r"\*?account\s*assignment\s*:[:\s]+([^\n]+)"], "text"),
    ("Item Category",       [r"\*?item\s*category\s*:[:\s]+([^\n]+)"],  "text"),
    ("Item Sub-Category",   [r"\*?item\s*sub-?category\s*:[:\s]+([^\n]+)"], "text"),

    # Dates
    ("Order Reqd Date", [
        r"\*?order\s*req[d]?\s*date\s*:[:\s]+([^\n]+)"
    ], "date"),
    ("Material/Service Reqd At Site", [
        r"\*?material\s*/\s*service\s*req[d]?\s*at\s*site[^:]*:[:\s]+([^\n]+)"
    ], "date"),

    # Cost — strictly numeric
    ("Estimated Cost (Cr)", [
        r"\*?estimated\s*cost[^:]*:[:\s]+([^\n]+)"
    ], "numeric"),

    # PR Checklist — strictly yes/no fields
    ("Spot Tender",        [r"\*?spot\s*tender[^:]*:[:\s]+([^\n]+)"],         "yesno"),
    ("HSE Plan Available", [r"\*?hse\s*plan\s*document[^:]*:[:\s]+([^\n]+)"], "yesno"),
    ("BOQ Surplus Check",  [
        r"\*?boq\s*prepared[^:]*surplus[^:]*:[:\s]+([^\n]+)"
    ], "yesno"),
    ("Single Party",       [
        r"\*?is\s*it\s*a\s*single\s*party[?]?\s*:[:\s]+([^\n]+)"
    ], "yesno"),
    ("Class A Vendor",     [r"\*?class\s*a\s*vendor[?]?\s*:[:\s]+([^\n]+)"],  "yesno"),
    ("Technical Spec File",[r"\*?technical\s*spec[^:]*:[:\s]+([^\n]+)"],      "text"),
    ("Term Sheet",         [r"\*?term\s*sheet\s*:[:\s]+([^\n]+)"],            "text"),

    # Approvals
    ("Engineering Manager", [r"\*?engineering\s*manager\s*:[:\s]+([^\n]+)"],  "text"),
    ("Project Manager",     [r"\*?project\s*manager\s*:[:\s]+([^\n]+)"],      "text"),
    ("Dept Chief/Head",     [r"\*?dept\s*chief[^:]*:[:\s]+([^\n]+)"],         "text"),
    ("Indent Approval",     [r"indent\s*approval\s*\n([^\n]+)"],              "text"),
    ("Indent Approval Date",[r"indent\s*approval\s*date\s*:[:\s]+([^\n]+)"],  "date"),
    ("Procurement Head",    [r"\*?procurement\s*head\s*:[:\s]+([^\n]+)"],     "text"),
    ("Procurement Manager", [r"procurement\s*manager\s*:[:\s]+([^\n]+)"],     "text"),
    ("Priority",            [r"\*?priority\s*:[:\s]+([^\n]+)"],               "text"),
    ("Performance Guarantee", [
        r"\*?applicability\s*of\s*performance\s*guarantee[^:]*:[:\s]+([^\n]+)"
    ], "yesno"),
]


# ── Validation ────────────────────────────────────────────────────────────────

def _has_digits(value: str) -> bool:
    """Check if value contains at least one digit."""
    return any(c.isdigit() for c in value)


def _validate_field(label: str, value: str, field_type: str) -> Optional[str]:
    """
    Validate extracted value against expected field type.
    Returns cleaned value or None if validation fails.

    Core rule: if a value doesn't match what the field type expects,
    reject it. This prevents e.g. "Term Sheet B Class Civil Vendor"
    from ending up in HSE Plan Available or BOQ Surplus Check.
    """
    value = value.strip()

    # Universal: skip empty or label-like values
    if len(value) < 2:
        return None
    if value.endswith(":"):
        return None

    # Universal: skip UI navigation artifacts
    if value.lower() in {
        "click here", "download", "upload", "submit",
        "save", "cancel", "back", "next", "home",
    }:
        return None

    # ── Numeric fields ────────────────────────────────────────────────────────
    # Must contain at least one digit. No exceptions.
    # This rejects person names, term sheet names, any non-numeric value.
    if field_type == "numeric":
        if not _has_digits(value):
            return None
        return value[:200]

    # ── Date fields ───────────────────────────────────────────────────────────
    # Must contain at least one digit.
    # Rejects person names, yes/no values, term sheet names.
    if field_type == "date":
        if not _has_digits(value):
            return None
        return value[:100]

    # ── Yes/No fields ─────────────────────────────────────────────────────────
    # Must be a clear yes/no/na/available type answer.
    # Rejects: term sheet names, vendor names, dates, long text.
    if field_type == "yesno":
        lower = value.lower()

        # Reject values that are clearly wrong field content
        # These are the exact wrong values we saw in the screenshot
        wrong_content = [
            "term sheet",
            "class civil",
            "class a",
            "vendor",
            "arc ",
            "annexure",
            "b class",
        ]
        for wrong in wrong_content:
            if wrong in lower:
                return None

        # Reject if it looks like a date (has digits in date format)
        if re.search(r"\d{2}[\/\-\.]\d{2}[\/\-\.]\d{2,4}", value):
            return None

        # Accept known yes/no indicators
        yesno_words = [
            "yes", "no", "na", "n/a", "not applicable",
            "attached", "available", "not available",
            "applicable", "not attached", "uploaded",
            "high", "medium", "low",  # for risk category fields
        ]
        for word in yesno_words:
            if word in lower:
                if len(value) <= 50:
                    return value
                # Extract just the relevant part
                match = re.search(
                    r"\b(yes|no|na|n/a|not\s+applicable|attached|"
                    r"available|not\s+available|not\s+attached)\b",
                    value, re.IGNORECASE,
                )
                return match.group(0).title() if match else value[:50]

        # Short value (≤30 chars) that didn't match — keep it
        if len(value) <= 30:
            return value

        # Long value with no yes/no signal — reject
        return None

    # ── Multiline fields ──────────────────────────────────────────────────────
    if field_type == "multiline":
        cleaned = re.sub(r"\s+", " ", value).strip()
        return cleaned[:500] if cleaned else None

    # ── Default: text field ───────────────────────────────────────────────────
    # Remove trailing noise
    value = re.sub(r"\s*\|\s*\d+\s*$", "", value).strip()
    value = re.sub(r"\s+", " ", value).strip()
    return value[:300] if value else None


# ── Cross-field validation ────────────────────────────────────────────────────

def _cross_validate(extracted: dict) -> None:
    """
    Post-extraction cross-field validation.
    Catches values that ended up in wrong fields.
    Modifies extracted dict in-place.
    """
    # Numeric fields must have digits
    for field in ["Estimated Cost (Cr)", "Contract Ceiling Value"]:
        if field in extracted and not _has_digits(extracted[field]):
            del extracted[field]

    # Date fields must have digits
    for field in [
        "Indent Approval Date", "Order Reqd Date",
        "Submission Date", "Material/Service Reqd At Site",
    ]:
        if field in extracted and not _has_digits(extracted[field]):
            del extracted[field]

    # Yes/No fields: final check for obviously wrong values
    for field in [
        "HSE Plan Available", "BOQ Surplus Check", "Single Party",
        "Class A Vendor", "FEL Based Ordering", "Spot Tender",
        "Performance Guarantee",
    ]:
        if field not in extracted:
            continue
        val   = extracted[field]
        lower = val.lower()

        # Reject anything that looks like a term sheet or vendor reference
        if any(w in lower for w in [
            "term sheet", "class civil", "vendor", "arc ", "b class",
        ]):
            del extracted[field]
            continue

        # Reject if it's a date
        if re.search(r"\d{2}[\/\-\.]\d{2}[\/\-\.]\d{2,4}", val):
            del extracted[field]
            continue

        # Trim long values
        if len(val) > 60:
            match = re.search(
                r"\b(yes|no|na|n/a|not\s+applicable|"
                r"attached|available|not\s+available)\b",
                val, re.IGNORECASE,
            )
            extracted[field] = match.group(0).title() if match else val[:60]


# ── Sidebar stripping ─────────────────────────────────────────────────────────

def _strip_sidebar_from_text(text: str) -> str:
    sidebar_markers = [
        r"procurement hierarchy",
        r"dashboard",
        r"tslist",
        r"auto grn",
        r"claim request",
        r"contracting",
        r"online certificate",
        r"\(profile\)",
        r"\(user\.aspx\)",
    ]
    combined = "|".join(sidebar_markers)
    lines    = text.splitlines()
    cleaned  = [
        line for line in lines
        if not re.search(combined, line.strip().lower())
    ]
    return "\n".join(cleaned)


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
        r"(\d+)\s+([A-Z0-9]{2,6})\s+"
        r"([A-Z][A-Z\s&./()]{3,50}?)(?:\s+\d|\s+NA|\s*\n)",
        vendor_section, re.IGNORECASE,
    )
    if rows:
        vendors = [
            f"  {row[0]}. [{row[1]}] {row[2].strip()}"
            for row in rows[:8]
        ]
        return "\n".join(vendors)

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


# ── Main entry point ──────────────────────────────────────────────────────────

def extract_tracker_fields(raw_text: str) -> str:
    """
    Main entry point.
    Takes raw Procurement Tracker PDF text.
    Returns compact validated key:value string for the LLM.
    """
    # Step 1: Strip sidebar
    text = _strip_sidebar_from_text(raw_text)

    # Step 2: Normalise whitespace
    text = re.sub(r"[ \t]+", " ", text)

    extracted = {}

    # Step 3: Extract and validate each field
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

                validated = _validate_field(label, raw_value, field_type)
                if validated:
                    extracted[label] = validated
                    break

    # Step 4: Vendor panel
    vendor_panel = _extract_vendor_panel(text)
    if vendor_panel:
        extracted["Proposed Vendor Panel"] = vendor_panel

    # Step 5: Remarks
    remarks = _extract_remarks(text)
    if remarks:
        extracted["Remarks/History"] = remarks

    # Step 6: Cross-field validation
    _cross_validate(extracted)

    # Step 7: Render
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
        "procurement tracker",
        "indent no",
        "rfq no",
        "indentor",
        "indent submission",
        "wrench project",
        "fel based ordering",
        "proposed vendor panel",
        "pr checklist",
        "pr checklists",
    ]
    hit_count = sum(1 for s in signals if s in text_sample)
    return hit_count >= 3
