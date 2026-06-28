"""
insight_generator.py
─────────────────────
Two LLM-powered narrative generators:

1. generate_standard_insight()
   - Reads best_practice_standard.json
   - Generates natural language summary of what the standard says
   - Called once per domain (cached)

2. generate_indent_insight()
   - Reads indent extraction + comparison report
   - Generates deep narrative analysis of the new indent
   - Called after each new indent is compared
"""

import json
from typing import Optional


# ── Prompt 1: Standard Practice Narrative ────────────────────────────────────
STANDARD_INSIGHT_PROMPT = """
You are a senior procurement governance expert at Tata Steel.

You are given a best_practice_standard derived from analysis of multiple
historical procurement indents across different categories.

Write a comprehensive, natural language narrative that explains:

1. OVERVIEW
   - How many indents were analysed and what procurement categories emerged
   - The overall quality and maturity of procurement practices observed

2. WHAT GOOD INDENTS DO WELL
   - The most common good practices observed across indents
   - Which categories consistently produce well-structured indents
   - Specific document structure patterns that work well

3. COMMON WEAKNESSES AND GAPS
   - The most frequent issues found across indents
   - Which document types are most commonly poorly structured
   - Cross-document inconsistencies that appear repeatedly

4. INTERRELATIONSHIPS BETWEEN DOCUMENTS AND CATEGORIES
   - How the procurement category shapes the way documents are written
   - For example: how a Civil BOQ differs from a Supply BOQ
   - How safety documents differ by work type
   - Pattern of how scope in Technical Spec relates to BOQ items

5. MANDATORY REQUIREMENTS
   - What every indent must have to be compliant
   - Critical risk controls that must be addressed

6. RECOMMENDATIONS FOR PROCUREMENT MANAGERS
   - Top 5 most impactful improvements they can make
   - Which document types need the most attention

Write in clear, professional prose. Use specific examples from the data.
Do NOT use bullet points — write in flowing paragraphs.
Length: 600-800 words.
Tone: Expert, authoritative, constructive.
"""


# ── Prompt 2: Deep Indent Analysis Narrative ─────────────────────────────────
INDENT_INSIGHT_PROMPT = """
You are a senior procurement auditor at Tata Steel.

You are given:
1. indent_extraction — the extracted data from a new indent
2. comparison_report — how this indent compares against the standard
3. best_practice_standard — the gold standard for procurement

Write a deep, comprehensive narrative analysis of this specific indent.
This is NOT a generic report — it must be specific to THIS indent's documents,
procurement type, and findings.

Structure your analysis as follows:

1. INDENT OVERVIEW
   - What is being procured, for which location, estimated cost
   - What documents are present and their quality
   - Overall procurement type and category

2. DOCUMENT INTERRELATIONSHIP ANALYSIS
   - How do the documents in this indent relate to each other?
   - Does the BOQ scope match the Technical Specification scope?
   - Does the Safety document address the specific risks of this work type?
   - Are there gaps between what the Tracker says and what documents show?
   - Be very specific — reference actual document names and content

3. STRENGTHS — WHAT THIS INDENT DOES WELL
   - Specific good practices with evidence from the documents
   - How this indent compares to the best examples in the standard
   - Which aspects are exemplary

4. WEAKNESSES AND GAPS — DEEP ANALYSIS
   - For each weakness found, explain WHY it matters for this specific work
   - How does missing a rate column in the BOQ affect this particular project?
   - What are the procurement risks created by each gap?
   - Cross-document inconsistencies and their implications

5. COMPARISON WITH STANDARD PRACTICES
   - How does this indent compare to the established standard?
   - Which mandatory practices are met and which are missing?
   - Is this indent above or below average for its procurement category?

6. SPECIFIC RECOMMENDATIONS
   - Concrete, actionable improvements for this specific indent
   - Priority order — what must be fixed before submission
   - What would make this indent exemplary

Write in clear, professional prose. Be specific and reference actual content
from the indent — document names, values, specific issues found.
Do NOT use bullet points — write in flowing paragraphs.
Length: 700-900 words.
Tone: Expert, direct, constructive, specific.
"""


def generate_standard_insight(standard: dict) -> str:
    """
    Generate natural language narrative of the standard practice.
    Summarises what was learned from all historical indents.
    """
    from src.llm_client import LLMClient
    import sys
    import io

    # Trim standard to key sections for token efficiency
    standard_trimmed = {
        "total_indents":               standard.get("_metadata", {}).get("source_indents"),
        "procurement_type_breakdown":  standard.get("_metadata", {}),
        "mandatory_practices":         standard.get("mandatory_practices", []),
        "recommended_practices":       standard.get("recommended_practices", [])[:5],
        "common_good_practices":       standard.get("common_good_practices", [])[:8],
        "common_weak_practices":       standard.get("common_weak_practices", [])[:8],
        "risk_controls":               standard.get("risk_controls", [])[:6],
        "documentation_requirements":  standard.get("documentation_requirements", []),
        "document_structure_standards": standard.get("document_structure_standards", [])[:5],
        "category_specific_patterns":  standard.get("category_specific_patterns", [])[:8],
        "representative_best_examples": standard.get("representative_best_examples", [])[:2],
        "representative_worst_examples": standard.get("representative_worst_examples", [])[:2],
    }

    messages = [
        {"role": "system", "content": STANDARD_INSIGHT_PROMPT},
        {"role": "user",   "content": json.dumps(standard_trimmed, indent=2)},
    ]

    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        llm    = LLMClient()
        result = llm.chat(messages=messages, max_tokens=2000)
    finally:
        sys.stdout = old_stdout

    return result


def generate_indent_insight(
    extraction: dict,
    report,
    standard: dict,
) -> str:
    """
    Generate deep natural language analysis of a specific indent.
    Explains interrelationships, strengths, weaknesses, recommendations.
    """
    from src.llm_client import LLMClient
    import sys
    import io

    ps = extraction.get("procurement_summary", {}) or {}

    # Build focused payload
    indent_summary = {
        "indent_id":           extraction.get("indent_id"),
        "procurement_type":    ps.get("procurement_type"),
        "package_description": ps.get("package_description"),
        "scope_of_work":       ps.get("scope_of_work"),
        "location":            ps.get("location"),
        "estimated_cost":      ps.get("estimated_cost_crores"),
        "vendor_panel":        ps.get("vendor_panel"),
        "hse_plan":            ps.get("hse_plan_available"),
        "technical_spec":      ps.get("technical_spec_attached"),
        "job_risk":            ps.get("job_risk_category"),
        "is_single_party":     ps.get("is_single_party"),
        "approval_authority":  ps.get("approval_authority"),
        "document_types":      ps.get("document_types_present", []),
        "missing_documents":   ps.get("missing_documents", []),
    }

    # Per-document summaries
    doc_summaries = []
    for doc in extraction.get("documents", []):
        ds = doc.get("document_structure", {}) or {}
        doc_summaries.append({
            "name":             doc.get("document_name"),
            "type":             doc.get("document_type"),
            "summary":          doc.get("document_summary"),
            "structure_quality": ds.get("structure_quality"),
            "missing_sections": ds.get("missing_sections", []),
            "notable_pattern":  ds.get("notable_pattern"),
            "good_practices":   [
                p.get("practice") if isinstance(p, dict) else p
                for p in doc.get("good_practices_observed", [])
            ],
            "weak_items": [
                w.get("issue") if isinstance(w, dict) else w
                for w in doc.get("weak_or_missing_items", [])
            ],
        })

    comparison_summary = {
        "overall_score":   report.overall_score,
        "overall_grade":   report.overall_grade,
        "strengths":       report.strengths,
        "gaps":            report.gaps,
        "recommendations": report.recommendations,
        "cross_doc_issues": report.cross_doc_issues,
        "mandatory_fails": [
            f.title for f in report.mandatory_findings
            if f.status == "fail"
        ],
        "doc_fails": [
            f.title for f in report.documentation_findings
            if f.status == "fail"
        ],
        "structure_issues": [
            f"{f.title}: {f.detail}"
            for f in report.structure_findings
            if f.status in ("fail", "warning")
        ],
    }

    # Relevant standard context
    standard_context = {
        "mandatory_practices":    standard.get("mandatory_practices", [])[:5],
        "common_weak_practices":  standard.get("common_weak_practices", [])[:5],
        "category_patterns": [
            p for p in standard.get("category_specific_patterns", [])
            if ps.get("procurement_type", "").lower() in
               p.get("procurement_type", "").lower()
        ][:5],
    }

    payload = {
        "indent_summary":    indent_summary,
        "documents":         doc_summaries,
        "comparison_report": comparison_summary,
        "standard_context":  standard_context,
        "good_practices":    extraction.get("good_practices", [])[:5],
        "weak_items":        extraction.get("weak_items", [])[:5],
        "category_document_patterns": extraction.get(
            "category_document_patterns", []
        )[:5],
    }

    messages = [
        {"role": "system", "content": INDENT_INSIGHT_PROMPT},
        {"role": "user",   "content": json.dumps(payload, indent=2, default=str)},
    ]

    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        llm    = LLMClient()
        result = llm.chat(messages=messages, max_tokens=2000)
    finally:
        sys.stdout = old_stdout

    return result
