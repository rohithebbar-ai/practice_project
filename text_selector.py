"""
text_selector.py
────────────────
Replaces head truncation (text[:N]) with keyword-scored paragraph selection.

Instead of blindly taking the first N characters, we:
1. Split text into paragraphs
2. Score each paragraph by procurement signal keywords (per document type)
3. Keep top-scoring paragraphs up to token budget
4. Preserve reading order of selected paragraphs

This ensures we capture content from page 18 of a 20-page spec just as
readily as content from page 1.
"""

import re
from typing import List, Tuple
from src.schemas import DocumentType


# ── Keyword sets per document type ───────────────────────────────────────────
# Each keyword hit adds to the paragraph score.
# Longer/more specific phrases score higher than single words.

KEYWORDS = {
    DocumentType.BOQ: [
        ("bill of quantity", 3),
        ("bill of quantities", 3),
        ("item description", 2),
        ("unit rate", 2),
        ("unit of measure", 2),
        ("quantity", 2),
        ("total amount", 2),
        ("lump sum", 2),
        ("material", 1),
        ("labour", 1),
        ("equipment", 1),
        ("rate", 1),
        ("nos", 1),
        ("sqm", 1),
        ("rmt", 1),
        ("cum", 1),
        ("kg", 1),
        ("mt", 1),
    ],
    DocumentType.TECHNICAL_SPECIFICATION: [
        ("scope of work", 3),
        ("scope of services", 3),
        ("technical requirement", 3),
        ("specification", 2),
        ("shall be", 2),
        ("must be", 2),
        ("deliverable", 2),
        ("inspection", 2),
        ("compliance", 2),
        ("standard", 2),
        ("material requirement", 2),
        ("quality", 2),
        ("testing", 2),
        ("acceptance criteria", 3),
        ("payment milestone", 3),
        ("payment schedule", 3),
        ("time and payment", 3),
        ("completion", 2),
        ("objective", 2),
        ("introduction", 1),
        ("annexure", 1),
    ],
    DocumentType.SAFETY_DOCUMENT: [
        ("health, safety", 3),
        ("safety requirement", 3),
        ("hse requirement", 3),
        ("hazard", 2),
        ("risk assessment", 2),
        ("ppe", 2),
        ("personal protective equipment", 3),
        ("safety procedure", 2),
        ("emergency", 2),
        ("incident", 2),
        ("permit to work", 3),
        ("contractor obligation", 2),
        ("safety plan", 2),
        ("safety term", 2),
        ("compliance", 1),
    ],
    DocumentType.TERMSHEET: [
        ("payment term", 3),
        ("commercial term", 3),
        ("delivery obligation", 3),
        ("penalty", 2),
        ("liquidated damage", 3),
        ("warranty", 2),
        ("guarantee", 2),
        ("retention", 2),
        ("mobilization", 2),
        ("advance payment", 2),
        ("milestone", 2),
        ("invoice", 2),
        ("tax", 1),
        ("gst", 1),
        ("applicable law", 2),
    ],
    DocumentType.APPROVAL_NOTE: [
        ("approved by", 3),
        ("approval authority", 3),
        ("justification", 3),
        ("single party", 3),
        ("single source", 3),
        ("proprietary", 2),
        ("emergency procurement", 2),
        ("deviation", 2),
        ("rationale", 2),
        ("recommendation", 2),
        ("committee", 2),
        ("authority", 1),
    ],
    DocumentType.VENDOR_DOCUMENT: [
        ("qualification", 3),
        ("experience", 2),
        ("certification", 2),
        ("eligibility", 2),
        ("credential", 2),
        ("turnover", 2),
        ("past order", 2),
        ("similar work", 2),
        ("msme", 2),
        ("registration", 2),
        ("license", 2),
    ],
    DocumentType.RFQ_INDENT: [
        ("package description", 3),
        ("scope of work", 3),
        ("background", 2),
        ("estimated cost", 2),
        ("contract ceiling", 2),
        ("vendor panel", 2),
        ("order required date", 2),
        ("pr checklist", 3),
        ("hse plan", 2),
        ("term sheet", 2),
        ("technical specification", 2),
        ("single party", 3),
        ("approval", 2),
        ("indentor", 1),
    ],
}

# Generic procurement keywords — used as fallback for OTHER type
# and as a base boost for all types
GENERIC_KEYWORDS = [
    ("procurement", 1),
    ("contract", 1),
    ("vendor", 1),
    ("supplier", 1),
    ("purchase", 1),
    ("order", 1),
    ("indent", 1),
    ("requirement", 1),
    ("scope", 1),
    ("cost", 1),
    ("price", 1),
    ("delivery", 1),
    ("timeline", 1),
    ("approval", 1),
]

# Section headers that always indicate important content
HIGH_VALUE_HEADERS = [
    "scope of work",
    "scope of services",
    "technical requirement",
    "specification",
    "deliverable",
    "payment",
    "commercial term",
    "approval",
    "vendor panel",
    "pr checklist",
    "background",
    "objective",
    "boq",
    "bill of quantity",
    "annexure",
    "safety requirement",
    "hse",
    "penalty",
    "warranty",
]


def _is_header_line(line: str) -> bool:
    """Detect section header lines."""
    stripped = line.strip().lower()
    # Numbered headers: "1.", "1.1", "Section 3"
    if re.match(r"^\d+[\.\d]*\s+\w", stripped):
        return True
    # ALL CAPS short lines
    if stripped.isupper() and 3 < len(stripped) < 60:
        return True
    # Known header phrases
    for header in HIGH_VALUE_HEADERS:
        if stripped.startswith(header) or stripped == header:
            return True
    return False


def _score_paragraph(
    paragraph: str,
    doc_type: DocumentType,
) -> float:
    """Score a paragraph by procurement relevance."""
    text = paragraph.lower()
    score = 0.0

    # Type-specific keywords
    type_keywords = KEYWORDS.get(doc_type, [])
    for keyword, weight in type_keywords:
        if keyword in text:
            score += weight * text.count(keyword)

    # Generic procurement keywords (always apply)
    for keyword, weight in GENERIC_KEYWORDS:
        if keyword in text:
            score += weight

    # Header bonus
    lines = paragraph.strip().splitlines()
    if lines and _is_header_line(lines[0]):
        score += 3.0

    # Length normalization — very short paragraphs are usually noise
    word_count = len(text.split())
    if word_count < 5:
        score *= 0.2   # heavy penalty for single-word or label-only lines
    elif word_count < 15:
        score *= 0.6   # mild penalty for very short paragraphs
    elif word_count > 300:
        score *= 0.8   # slight penalty for extremely long paragraphs

    # Boost if paragraph contains numbers (quantities, costs, dates)
    number_count = len(re.findall(r"\b\d+[\.,]?\d*\b", text))
    if number_count > 3:
        score += min(number_count * 0.2, 2.0)

    return score


def _split_into_paragraphs(text: str) -> List[str]:
    """
    Split text into meaningful paragraphs.
    Treats blank lines as paragraph boundaries.
    Also splits on section headers even without blank lines.
    """
    # First split on blank lines
    raw_paragraphs = re.split(r"\n\s*\n", text)

    paragraphs = []
    for raw in raw_paragraphs:
        raw = raw.strip()
        if not raw:
            continue

        # Further split on lines that look like section headers
        lines = raw.splitlines()
        current_chunk = []

        for line in lines:
            if _is_header_line(line) and current_chunk:
                # Save current chunk, start new one with this header
                chunk_text = "\n".join(current_chunk).strip()
                if chunk_text:
                    paragraphs.append(chunk_text)
                current_chunk = [line]
            else:
                current_chunk.append(line)

        if current_chunk:
            chunk_text = "\n".join(current_chunk).strip()
            if chunk_text:
                paragraphs.append(chunk_text)

    return paragraphs


def select_relevant_text(
    text: str,
    doc_type: DocumentType,
    char_budget: int,
) -> Tuple[str, dict]:
    """
    Select the most procurement-relevant paragraphs from text,
    staying within char_budget.

    Returns
    -------
    selected_text : str
        Paragraphs in their original reading order, joined by blank lines.
    stats : dict
        Metadata about the selection for logging/debugging.
    """
    if not text or not text.strip():
        return "", {"total_paragraphs": 0, "selected_paragraphs": 0}

    # If text is already within budget, return as-is
    if len(text) <= char_budget:
        return text, {
            "total_paragraphs": 1,
            "selected_paragraphs": 1,
            "method": "no_truncation_needed",
        }

    paragraphs = _split_into_paragraphs(text)

    if not paragraphs:
        return text[:char_budget], {
            "total_paragraphs": 0,
            "selected_paragraphs": 0,
            "method": "fallback_head_truncation",
        }

    # Score all paragraphs
    scored: List[Tuple[float, int, str]] = []
    for i, para in enumerate(paragraphs):
        score = _score_paragraph(para, doc_type)
        scored.append((score, i, para))

    # Sort by score descending, then by original position for ties
    scored_sorted = sorted(scored, key=lambda x: (-x[0], x[1]))

    # Greedily select top paragraphs until budget is exhausted
    selected_indices = set()
    chars_used = 0

    for score, idx, para in scored_sorted:
        para_len = len(para) + 2  # +2 for separator
        if chars_used + para_len <= char_budget:
            selected_indices.add(idx)
            chars_used += para_len
        elif score == 0:
            # Once we reach zero-score paragraphs, stop trying
            break

    # If nothing selected (all paragraphs too large), take the top-scored one
    if not selected_indices and scored_sorted:
        _, idx, para = scored_sorted[0]
        selected_indices.add(idx)

    # Reconstruct in ORIGINAL READING ORDER
    selected_paragraphs = [
        paragraphs[i]
        for i in sorted(selected_indices)
    ]

    selected_text = "\n\n".join(selected_paragraphs)

    stats = {
        "total_paragraphs": len(paragraphs),
        "selected_paragraphs": len(selected_indices),
        "chars_before": len(text),
        "chars_after": len(selected_text),
        "method": "keyword_scored_selection",
        "doc_type": doc_type.value,
    }

    return selected_text, stats