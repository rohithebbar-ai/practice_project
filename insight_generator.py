"""
insight_generator.py
─────────────────────
Two narrative generators:
1. generate_standard_insight() — what the standard says
2. generate_indent_insight()   — deep analysis of a specific indent
"""

import json
import sys
import io


STANDARD_INSIGHT_PROMPT = """
You are a senior procurement governance expert at Tata Steel.

You are given a best_practice_standard derived from analysis of multiple
historical procurement indents.

Write a comprehensive natural language narrative covering:

1. OVERVIEW
   How many indents were analysed, what procurement categories emerged,
   and the overall quality of procurement practices observed.

2. WHAT GOOD INDENTS DO WELL
   The most common good practices. Which categories produce well-structured
   indents. Specific document patterns that work well.

3. COMMON WEAKNESSES
   The most frequent issues. Which document types are most poorly structured.
   Cross-document inconsistencies that appear repeatedly.

4. HOW CATEGORY SHAPES DOCUMENTS
   How the procurement category changes the way documents are written.
   For example: how a Civil BOQ differs from a Supply BOQ.
   How safety documents differ by work type.

5. MANDATORY REQUIREMENTS
   What every indent must have. Critical risk controls that must be addressed.

6. TOP RECOMMENDATIONS FOR PROCUREMENT MANAGERS
   The 5 most impactful improvements they can make right now.

Write in clear professional prose. No bullet points — flowing paragraphs.
Use markdown headers (###) for each section.
Length: 600-800 words.
Tone: Expert, authoritative, constructive.
"""


INDENT_INSIGHT_PROMPT = """
You are a senior procurement auditor at Tata Steel.

You are given:
1. indent_summary — key fields from the indent
2. documents — each document with its structure, good practices, weaknesses
3. comparison_report — score, grade, what passed and what failed
4. standard_context — relevant standard practices for this category

The comparison_report contains:
- overall_score (0-100): the indent's score against the standard
- overall_grade: Strong / Adequate / Needs Improvement / Weak
- mandatory_fails: mandatory practices from the standard that are MISSING
- doc_fails: required document types that are MISSING
- gaps: all gaps found
- strengths: what this indent does well
- structure_issues: document structure problems found

Write a deep, specific narrative analysis of THIS indent.
Reference actual document names and specific content from the data.

Use these markdown sections:

### Indent Overview
What is being procured, location, estimated cost, documents present.

### Score Explanation
This indent scored {score}/100 ({grade}). Explain specifically WHY —
which mandatory practices are missing, which documents have gaps,
which cross-document issues pulled the score down.
Be specific: name the exact practices from mandatory_fails and doc_fails.

### Document Interrelationship Analysis
How do the documents relate to each other?
Does the BOQ scope match the Technical Spec?
Does the Safety document address the specific risks of this work?
Are there gaps between what the Tracker says and what documents show?
Reference actual document names.

### Strengths
What this indent does well. Specific evidence from documents.

### Weaknesses — Deep Analysis
For each weakness, explain WHY it matters for this specific work type.
What procurement risk does it create?
Reference actual document names and missing content.

### Comparison with Standard
How does this indent compare to the established standard for this category?
Which mandatory practices are met and which are missing?

### Specific Recommendations
Concrete, prioritised actions before submission.
What would raise the score and what would make this indent exemplary.

Write in professional prose. No bullet points — flowing paragraphs under
each ### heading. Be specific and reference actual content from the indent.
Length: 700-900 words.
"""


def generate_standard_insight(standard: dict) -> str:
    """Generate narrative summary of the standard practice."""
    from src.llm_client import LLMClient

    trimmed = {
        "source_indents":              standard.get("_metadata", {}).get("source_indents"),
        "mandatory_practices":         standard.get("mandatory_practices", []),
        "recommended_practices":       standard.get("recommended_practices", [])[:5],
        "common_good_practices":       standard.get("common_good_practices", [])[:8],
        "common_weak_practices":       standard.get("common_weak_practices", [])[:8],
        "risk_controls":               standard.get("risk_controls", [])[:6],
        "documentation_requirements":  standard.get("documentation_requirements", []),
        "document_structure_standards": standard.get("document_structure_standards", [])[:5],
        "category_specific_patterns":  standard.get("category_specific_patterns", [])[:8],
    }

    messages = [
        {"role": "system", "content": STANDARD_INSIGHT_PROMPT},
        {"role": "user",   "content": json.dumps(trimmed, indent=2)},
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
    """Generate deep narrative analysis of a specific indent."""
    from src.llm_client import LLMClient

    ps = extraction.get("procurement_summary", {}) or {}

    # Per-document summaries
    doc_summaries = []
    for doc in extraction.get("documents", []):
        ds = doc.get("document_structure", {}) or {}
        doc_summaries.append({
            "name":              doc.get("document_name"),
            "type":              doc.get("document_type"),
            "summary":           doc.get("document_summary"),
            "structure_quality": ds.get("structure_quality"),
            "missing_sections":  ds.get("missing_sections", []),
            "notable_pattern":   ds.get("notable_pattern"),
            "good_practices": [
                p.get("practice") if isinstance(p, dict) else p
                for p in doc.get("good_practices_observed", [])
            ],
            "weak_items": [
                w.get("issue") if isinstance(w, dict) else w
                for w in doc.get("weak_or_missing_items", [])
            ],
        })

    # Build comparison summary with clear score context
    mandatory_fails = [
        f.title for f in report.mandatory_findings
        if f.status == "fail"
    ]
    doc_fails = [
        f.title for f in report.documentation_findings
        if f.status == "fail"
    ]
    structure_issues = [
        f"{f.title}: {f.detail}"
        for f in report.structure_findings
        if f.status in ("fail", "warning")
    ]

    total_checks = (
        len(report.mandatory_findings) +
        len(report.documentation_findings) +
        len(report.risk_findings) +
        len(report.vendor_findings) +
        len(report.approval_findings)
    )
    met     = sum(1 for f in (
        report.mandatory_findings + report.documentation_findings +
        report.risk_findings + report.vendor_findings +
        report.approval_findings
    ) if f.status == "pass")
    missing = sum(1 for f in (
        report.mandatory_findings + report.documentation_findings +
        report.risk_findings + report.vendor_findings +
        report.approval_findings
    ) if f.status == "fail")

    comparison_summary = {
        "overall_score":   report.overall_score,
        "overall_grade":   report.overall_grade,
        "score_breakdown": (
            f"{met} of {total_checks} standard checks passed, "
            f"{missing} missing from standard"
        ),
        "mandatory_fails":  mandatory_fails,
        "doc_fails":        doc_fails,
        "structure_issues": structure_issues,
        "strengths":        report.strengths,
        "gaps":             report.gaps,
        "recommendations":  report.recommendations,
        "cross_doc_issues": report.cross_doc_issues,
    }

    # Relevant standard context for this procurement type
    proc_type = ps.get("procurement_type", "").lower()
    category_patterns = [
        p for p in standard.get("category_specific_patterns", [])
        if proc_type and proc_type.split("-")[0].strip() in
           p.get("procurement_type", "").lower()
    ][:5]

    payload = {
        "indent_summary": {
            "indent_id":           extraction.get("indent_id"),
            "procurement_type":    ps.get("procurement_type"),
            "package_description": ps.get("package_description"),
            "scope_of_work":       (ps.get("scope_of_work") or "")[:500],
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
        },
        "documents":              doc_summaries,
        "comparison_report":      comparison_summary,
        "good_practices_found":   [
            (p.get("practice") if isinstance(p, dict) else p)
            for p in extraction.get("good_practices", [])[:5]
        ],
        "weak_items_found":       [
            (w.get("issue") if isinstance(w, dict) else w)
            for w in extraction.get("weak_items", [])[:5]
        ],
        "category_doc_patterns":  extraction.get(
            "category_document_patterns", []
        )[:5],
        "standard_context": {
            "mandatory_practices":   standard.get("mandatory_practices", [])[:5],
            "common_weak_practices": standard.get("common_weak_practices", [])[:5],
            "category_patterns":     category_patterns,
        },
    }

    # Inject score into prompt
    prompt = INDENT_INSIGHT_PROMPT.replace(
        "{score}", str(report.overall_score)
    ).replace(
        "{grade}", report.overall_grade
    )

    messages = [
        {"role": "system", "content": prompt},
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
