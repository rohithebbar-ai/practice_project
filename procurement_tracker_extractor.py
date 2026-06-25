"""
procurement_tracker_extractor.py
─────────────────────────────────
Converts a raw Procurement Tracker PDF text (any filename, any page count)
into a compact, clean structured summary for the LLM.

The Procurement Tracker is a portal-rendered PDF from Tata Steel's IPMS system.
It has a consistent field structure but comes with heavy sidebar/navigation noise
that repeats on every page.

Instead of sending 30,000–80,000 raw chars to the LLM, this extractor produces
~500–1,200 chars of clean key-value text covering all procurement-relevant fields.
"""

import re
from typing import Optional


# ── Fields we want to extract ────────────────────────────────────────────────
# Each entry: (output_label, list_of_patterns_to_try)
# Patterns use re.search on the cleaned line sequence.

FIELD_PATTERNS = [
    # Basic Information
    ("Indent No",           [r"indent\s*no[:\s]+([^\n]+)", r"25-26/\d+"]),
    ("RFQ No",              [r"rfq\s*no[:\s]+([^\n]+)", r"25-26/\d+"]),
    ("Submission Date",     [r"indent\s*submission\s*date[:\s]+([^\n]+)"]),
    ("Indentor",            [r"indentor[:\s]+([^\n]+)"]),
    ("Location",            [r"\*?location\s*:[:\s]+([^\n]+)"]),
    ("Ensafe Location",     [r"\*?ensafe\s*location\s*:[:\s]+([^\n]+)"]),
    ("Project Name",        [r"\*?project\s*name\s*:[:\s]+([^\n]+)"]),
    ("Package Description", [r"\*?package\s*description\s*:[:\s]+([^\n]+)"]),
    ("Brief Scope of Work", [r"\*?brief\s*scope\s*of\s*work\s*:[:\s]+([\s\S]{10,300}?)(?=\*?background|font|size|\Z)"]),
    ("Background",          [r"\*?background\s*&?\s*essentially?\s*:[:\s]+([\s\S]{10,400}?)(?=\*?type of indent|primavera|\Z)"]),

    # Sourcing & Commercial
    ("Type of Indent",      [r"\*?type\s*of\s*indent\s*:[:\s]+([^\n]+)"]),
    ("Discipline",          [r"\*?discipline\s*:[:\s]+([^\n]+)"]),
    ("Order/ARC",           [r"\*?order\s*/?\s*arc\s*:[:\s]+([^\n]+)"]),
    ("ARC Type",            [r"arc\s*type\s*:[:\s]+([^\n]+)"]),
    ("Period of Contract",  [r"\*?period\s*of\s*contract[^:]*:[:\s]+([^\n]+)"]),
    ("Contract Ceiling Value", [r"\*?contract\s*ceiling\s*value[^:]*:[:\s]+([^\n]+)"]),
    ("Package Type",        [r"\*?package\s*type\s*:[:\s]+([^\n]+)"]),
    ("FEL Based Ordering",  [r"\*?fel\s*based\s*ordering\s*:[:\s]+([^\n]+)"]),
    ("Sourcing",            [r"\*?sourcing\s*:[:\s]+([^\n]+)"]),
    ("Job Risk Category",   [r"\*?job\s*risk\s*category\s*:[:\s]+([^\n]+)"]),
    ("Job Risk Type",       [r"\*?job\s*risk\s*type\s*:[:\s]+([^\n]+)"]),
    ("Account Assignment",  [r"\*?account\s*assignment\s*:[:\s]+([^\n]+)"]),
    ("Item Category",       [r"\*?item\s*category\s*:[:\s]+([^\n]+)"]),
    ("Item Sub-Category",   [r"\*?item\s*sub-?category\s*:[:\s]+([^\n]+)"]),

    # Dates
    ("Order Reqd Date",     [r"\*?order\s*req[d]?\s*date\s*:[:\s]+([^\n]+)"]),
    ("Material/Service Reqd At Site", [r"\*?material\s*/\s*service\s*req[d]?\s*at\s*site[^:]*:[:\s]+([^\n]+)"]),
    ("Estimated Cost (Cr)", [r"\*?estimated\s*cost[^:]*:[:\s]+([^\n]+)"]),

    # PR Checklist
    ("Spot Tender",         [r"\*?spot\s*tender[^:]*:[:\s]+([^\n]+)"]),
    ("HSE Plan Available",  [r"\*?hse\s*plan\s*document[^:]*:[:\s]+([^\n]+)"]),
    ("BOQ Surplus Check",   [r"\*?boq\s*prepared[^:]*surplus[^:]*:[:\s]+([^\n]+)"]),
    ("Single Party",        [r"\*?is\s*it\s*a\s*single\s*party[?]?\s*:[:\s]+([^\n]+)"]),
    ("Class A Vendor",      [r"\*?class\s*a\s*vendor[?]?\s*:[:\s]+([^\n]+)"]),
    ("Technical Spec File", [r"\*?technical\s*spec[^:]*:[:\s]+([^\n]+)"]),
    ("Term Sheet",          [r"\*?term\s*sheet\s*:[:\s]+([^\n]+)"]),

    # Approvals
    ("Engineering Manager", [r"\*?engineering\s*manager\s*:[:\s]+([^\n]+)"]),
    ("Project Manager",     [r"\*?project\s*manager\s*:[:\s]+([^\n]+)"]),
    ("Dept Chief/Head",     [r"\*?dept\s*chief[^:]*:[:\s]+([^\n]+)"]),
    ("Indent Approval",     [r"indent\s*approval\s*\n([^\n]+)"]),
    ("Indent Approval Date",[r"indent\s*approval\s*date\s*:[:\s]+([^\n]+)"]),
    ("Procurement Head",    [r"\*?procurement\s*head\s*:[:\s]+([^\n]+)"]),
    ("Procurement Manager", [r"procurement\s*manager\s*:[:\s]+([^\n]+)"]),
    ("Priority",            [r"\*?priority\s*:[:\s]+([^\n]+)"]),
    ("Performance Guarantee",[r"\*?applicability\s*of\s*performance\s*guarantee[^:]*:[:\s]+([^\n]+)"]),
]


def _strip_sidebar_from_text(text: str) -> str:
    """
    Remove the repeating left-sidebar navigation block.
    The sidebar appears as a cluster of short lines before the main content
    on each page. We detect and strip it using known sidebar phrases.
    """
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
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        if re.search(combined, line.strip().lower()):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def _extract_vendor_panel(text: str) -> Optional[str]:
    """Extract vendor panel table as clean text."""
    # Look for the vendor panel section
    match = re.search(
        r"proposed\s*vendor\s*panel\s*:?\s*\n([\s\S]{20,800}?)(?=cost\s*estimate|sourcing\s*&|pr\s*check|\Z)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None

    vendor_section = match.group(1)
    # Extract rows with vendor code and name patterns
    vendors = []
    # Pattern: number, vendor code (3-4 chars), vendor name
    rows = re.findall(
        r"(\d+)\s+([A-Z0-9]{2,6})\s+([A-Z][A-Z\s&./()]{3,50}?)(?:\s+\d|\s+NA|\s*\n)",
        vendor_section,
        re.IGNORECASE,
    )
    for row in rows[:8]:  # cap at 8 vendors
        vendors.append(f"  {row[0]}. [{row[1]}] {row[2].strip()}")

    if vendors:
        return "\n".join(vendors)

    # Fallback: just return first 300 chars of section
    return vendor_section[:300].strip()


def _extract_remarks(text: str) -> Optional[str]:
    """Extract the remarks/version history table."""
    match = re.search(
        r"remarks\s*\n([\s\S]{10,600}?)(?=primavera|$)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    remarks_text = match.group(1).strip()
    # Keep only lines that look like actual remarks (not headers)
    lines = [l.strip() for l in remarks_text.splitlines() if l.strip()]
    meaningful = [
        l for l in lines
        if len(l) > 8
        and not re.match(r"^(version|date|user|download|files)$", l, re.I)
    ]
    return " | ".join(meaningful[:5]) if meaningful else None


def extract_tracker_fields(raw_text: str) -> str:
    """
    Main entry point.
    Takes raw (or lightly cleaned) Procurement Tracker text.
    Returns a compact structured string of key: value pairs.
    """
    # Step 1: strip sidebar navigation
    text = _strip_sidebar_from_text(raw_text)

    # Step 2: normalize whitespace but keep structure
    text = re.sub(r"[ \t]+", " ", text)
    text_lower = text.lower()

    extracted = {}

    # Step 3: extract each field
    for label, patterns in FIELD_PATTERNS:
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = match.group(1).strip() if match.lastindex else match.group(0).strip()
                # Clean up the value
                value = re.sub(r"\s+", " ", value).strip()
                # Skip empty or very short values
                if len(value) < 2:
                    continue
                # Skip if it looks like a field label itself
                if value.endswith(":"):
                    continue
                extracted[label] = value[:300]  # cap individual field length
                break

    # Step 4: vendor panel (special table extraction)
    vendor_panel = _extract_vendor_panel(text)
    if vendor_panel:
        extracted["Proposed Vendor Panel"] = vendor_panel

    # Step 5: remarks
    remarks = _extract_remarks(text)
    if remarks:
        extracted["Remarks/History"] = remarks

    # Step 6: render as clean structured text
    if not extracted:
        # Fallback: return first 3000 chars of sidebar-stripped text
        return text[:3000].strip()

    lines = ["=== PROCUREMENT TRACKER (Extracted Fields) ==="]
    for label, value in extracted.items():
        lines.append(f"{label}: {value}")

    return "\n".join(lines)


def is_procurement_tracker_doc(document_name: str, document_text: str) -> bool:
    """
    Detect whether a document is a Procurement Tracker portal export,
    regardless of filename.
    Works by content signature — the portal always emits the same header fields.
    """
    # Filename hints (non-exhaustive, used as fast path)
    name_lower = document_name.lower()
    if any(hint in name_lower for hint in ["procurement tracker", "indent_rfq", "rfq"]):
        # Still verify by content
        pass

    # Content signature: must have multiple tracker-specific fields
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