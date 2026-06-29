"""
insight_generator.py  (v3)
──────────────────────────
Two narrative generators:

1. generate_standard_insight()
   Explains what the standard learned from all historical indents —
   including the interrelationships between documents and categories.

2. generate_indent_insight()
   The centerpiece: compares THIS indent's document interrelationships
   against what the standard expects those relationships to look like.

   The key insight is not just "BOQ is missing total rows" but:
   "The standard shows that in Civil indents, the BOQ and Technical Spec
   always have matching scope. In this indent, the BOQ covers drain
   installation but the Technical Spec covers RCC foundations — this
   mismatch means vendors will price the wrong work."
"""

import json
import sys
import io


STANDARD_INSIGHT_PROMPT = """
You are a senior procurement governance expert at Tata Steel.

You are given a best_practice_standard derived from analysis of
multiple historical procurement indents across procurement categories.

Write a comprehensive narrative covering:

### Overview
How many indents were analysed, what procurement categories emerged,
and the overall maturity of procurement practices observed.

### What Good Indents Do Well
The most consistent good practices. Be specific — name the document types
and what they do well in combination with each other.

### How Documents Relate to Each Other in Good Indents
This is the most important section. In well-structured indents:
- How does the BOQ scope relate to the Technical Specification scope?
- How does the Procurement Tracker's cost estimate align with the BOQ total?
- How does the Safety document address the specific risks described in the scope?
- How does the vendor panel size relate to whether a single-party approval exists?
- What cross-document consistency patterns appear in the best indents?

Use the category_specific_patterns and category_document_patterns data
to explain these interrelationships concretely.

### Common Weaknesses
The most frequent failures. Explain not just what is missing but
WHY the absence of that element breaks the integrity of the indent
as a whole document set.

### Mandatory Requirements
What every indent must have. Why each requirement matters.

### Top Recommendations
The 5 most impactful things procurement managers can do right now.

Write in clear professional prose. Use markdown ### headers for sections.
No bullet points — flowing paragraphs. Length: 600–800 words.
"""


INDENT_INSIGHT_PROMPT = """
You are a senior procurement auditor at Tata Steel.

You are given:
- indent_data: extracted content from a NEW procurement indent
- standard_patterns: the interrelationship patterns the standard learned
  from analysing all historical indents
- comparison_result: how this indent scored against the standard

YOUR MOST IMPORTANT TASK is to compare the INTERRELATIONSHIPS between
documents in this new indent against the interrelationship PATTERNS
the standard expects.

Do not just list what is missing. Explain HOW the document relationships
in this indent compare to what good indents look like.

Examples of what this means:
- "The standard shows that in Civil indents, the BOQ scope and Technical
  Spec scope always describe the same work. In this indent, the BOQ
  (BOQ_S_UploadedData.xlsx) covers precast drain installation while the
  Technical Spec (TS-Installations.docx) describes RCC foundation work.
  This misalignment means vendors will price different work than what
  the specification requires — a significant procurement risk."

- "The standard shows that when job risk is High, the Safety document
  always includes specific hazard identification and risk ratings.
  In this indent, the Safety Term Sheet is present but contains only
  generic responsibilities without hazard-specific controls — inadequate
  for the civil excavation work described in the scope."

- "The standard shows that the Procurement Tracker cost field and BOQ
  total should be consistent. In this indent, the Tracker lists estimated
  cost as 'Mayank Shekhar' (a person's name, not a value) while the BOQ
  has no total row — meaning there is no reliable cost figure anywhere
  in this indent."

Use THIS structure:

### Indent Overview
What is being procured, where, estimated cost, documents present.
One short paragraph.

### Score: {score}/100 — Why This Indent Scored {grade}
Explain specifically what drove the score. How many mandatory practices
were met vs missing. Which categories pulled the score down most.
Reference the score_breakdown (mandatory={mandatory_pts}/{mandatory_max},
documentation={doc_pts}/{doc_max}, etc.) to explain the weighting.

### Document Interrelationship Analysis
This is the core section — compare this indent's document relationships
against what the standard expects.

For each pair of documents that should relate to each other, answer:
1. What relationship does the standard expect between these documents?
2. What is the actual relationship in THIS indent?
3. Does it match? If not, what is the specific consequence?

Always reference actual document names from the indent.
Always reference actual content (field values, section names, scope text).

Cover at minimum:
- BOQ vs Technical Specification (scope alignment)
- Procurement Tracker vs BOQ (cost consistency)
- Safety document vs Scope of work (risk coverage)
- Vendor panel size vs Single-party approval (commercial integrity)
- Any other relevant pairs present in this indent

### Strengths — What This Indent Does Well
Specific evidence from documents. Reference actual document names.

### Weaknesses — Impact Analysis
For each weakness, explain not just WHAT is missing but WHY it breaks
the integrity of the indent as a document set. What specific procurement
risk does it create? What could go wrong during tendering or execution?

### Comparison with Standard Patterns
How does this indent's document relationship quality compare to what
the standard expects for this procurement category?
Is this indent above or below average for its category?

### Priority Actions Before Submission
Three to five specific, concrete actions. Be precise — name the document
and the exact change needed.

Write in professional prose. Use ### headers. No bullet points.
Reference actual document names and field values throughout.
Length: 800–1000 words.
"""


def generate_standard_insight(standard: dict) -> str:
    """Generate narrative summary of the standard and its patterns."""
    from src.llm_client import LLMClient

    trimmed = {
        "source_indents":             standard.get("_metadata", {}).get("source_indents"),
        "mandatory_practices":        standard.get("mandatory_practices", []),
        "recommended_practices":      standard.get("recommended_practices", [])[:5],
        "common_good_practices":      standard.get("common_good_practices", [])[:8],
        "common_weak_practices":      standard.get("common_weak_practices", [])[:8],
        "risk_controls":              standard.get("risk_controls", [])[:6],
        "documentation_requirements": standard.get("documentation_requirements", []),
        "document_structure_standards": standard.get(
            "document_structure_standards", []
        )[:6],
        "category_specific_patterns": standard.get(
            "category_specific_patterns", []
        )[:10],
        "category_document_patterns": standard.get(
            "category_document_patterns", []
        )[:10],
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
    """
    Generate deep narrative analysis focused on document interrelationships.

    The core question: how do the relationships between documents in this
    indent compare to the relationship patterns the standard expects?
    """
    from src.llm_client import LLMClient

    ps = extraction.get("procurement_summary", {}) or {}

    # ── Per-document detail ───────────────────────────────────────────────────
    doc_details = []
    for doc in extraction.get("documents", []):
        ds = doc.get("document_structure", {}) or {}
        ki = doc.get("key_information", {}) or {}
        doc_details.append({
            "name":              doc.get("document_name"),
            "type":              doc.get("document_type"),
            "summary":           doc.get("document_summary"),
            "structure_quality": ds.get("structure_quality"),
            "sections_found":    ds.get("sections_found", [])[:8],
            "missing_sections":  ds.get("missing_sections", []),
            "notable_pattern":   ds.get("notable_pattern"),
            "logical_sequence":  ds.get("logical_sequence"),
            # Key fields extracted from this specific document
            "scope_of_work":        ki.get("scope_of_work"),
            "estimated_cost":       ki.get("estimated_cost_crores"),
            "vendor_panel":         ki.get("vendor_panel"),
            "technical_spec":       ki.get("technical_spec_attached"),
            "hse_plan":             ki.get("hse_plan_available"),
            "is_single_party":      ki.get("is_single_party"),
            "approval_authority":   ki.get("approval_authority"),
            "good_practices": [
                p.get("practice") if isinstance(p, dict) else p
                for p in doc.get("good_practices_observed", [])
            ],
            "weak_items": [
                {
                    "issue":    w.get("issue") if isinstance(w, dict) else w,
                    "reason":   w.get("reason", "") if isinstance(w, dict) else "",
                }
                for w in doc.get("weak_or_missing_items", [])
            ],
        })

    # ── Cross-document patterns from the extraction itself ────────────────────
    category_doc_patterns = extraction.get("category_document_patterns", [])

    # ── Score breakdown with labels ───────────────────────────────────────────
    bd = report.score_breakdown or {}
    score_breakdown_explained = {
        "total_score":   report.overall_score,
        "grade":         report.overall_grade,
        "mandatory":     {
            "earned":  bd.get("mandatory", 0),
            "max":     40,
            "meaning": "Most critical — mandatory practices from standard",
        },
        "documentation": {
            "earned":  bd.get("documentation", 0),
            "max":     20,
            "meaning": "Required document types present",
        },
        "risk":          {
            "earned":  bd.get("risk", 0),
            "max":     20,
            "meaning": "Risk controls addressed",
        },
        "vendor":        {
            "earned":  bd.get("vendor", 0),
            "max":     10,
            "meaning": "Vendor requirements met",
        },
        "approval":      {
            "earned":  bd.get("approval", 0),
            "max":     10,
            "meaning": "Approval chain present",
        },
    }

    # ── What the standard expects for this procurement type ───────────────────
    proc_type = (ps.get("procurement_type") or "").lower()

    # Filter category patterns relevant to this procurement type
    relevant_patterns = [
        p for p in standard.get("category_specific_patterns", [])
        if not proc_type or
        any(
            word in p.get("procurement_type", "").lower()
            for word in proc_type.split()
            if len(word) > 3
        )
    ][:8]

    # Document relationship expectations from standard
    doc_relationship_standards = standard.get(
        "document_structure_standards", []
    )[:6]

    # Cross-document patterns from all historical indents
    historical_cross_doc = standard.get(
        "category_document_patterns", []
    )[:8]

    # ── Findings summary ──────────────────────────────────────────────────────
    mandatory_met = [
        f.title for f in report.mandatory_findings
        if f.status == "pass"
    ]
    mandatory_missing = [
        f.title for f in report.mandatory_findings
        if f.status == "fail"
    ]
    doc_missing = [
        f.title for f in report.documentation_findings
        if f.status == "fail"
    ]
    structure_issues = [
        {"doc": f.title, "issue": f.detail}
        for f in report.structure_findings
        if f.status in ("fail", "warning")
    ]

    # ── Build payload ─────────────────────────────────────────────────────────
    payload = {
        "indent_data": {
            "indent_id":           extraction.get("indent_id"),
            "procurement_type":    ps.get("procurement_type"),
            "package_description": ps.get("package_description"),
            "scope_of_work":       (ps.get("scope_of_work") or "")[:600],
            "location":            ps.get("location"),
            "estimated_cost":      ps.get("estimated_cost_crores"),
            "vendor_panel":        ps.get("vendor_panel"),
            "vendor_count":        ps.get("vendor_count"),
            "is_single_party":     ps.get("is_single_party"),
            "hse_plan":            ps.get("hse_plan_available"),
            "technical_spec":      ps.get("technical_spec_attached"),
            "job_risk":            ps.get("job_risk_category"),
            "approval_authority":  ps.get("approval_authority"),
            "document_types_present": ps.get("document_types_present", []),
            "missing_documents":   ps.get("missing_documents", []),
        },
        "documents":                  doc_details,
        "cross_doc_patterns_in_indent": category_doc_patterns,
        "cross_doc_issues_found":     report.cross_doc_issues,
        "good_practices_found": [
            p.get("practice") if isinstance(p, dict) else p
            for p in extraction.get("good_practices", [])[:6]
        ],
        "weak_items_found": [
            w.get("issue") if isinstance(w, dict) else w
            for w in extraction.get("weak_items", [])[:6]
        ],
        "score_breakdown":            score_breakdown_explained,
        "mandatory_met":              mandatory_met,
        "mandatory_missing":          mandatory_missing,
        "documents_missing":          doc_missing,
        "structure_issues":           structure_issues,
        "strengths":                  report.strengths,
        "gaps":                       report.gaps,
        "recommendations":            report.recommendations,
        "standard_patterns": {
            "what_standard_expects_for_this_category": relevant_patterns,
            "document_relationship_expectations":      doc_relationship_standards,
            "cross_document_patterns_from_history":    historical_cross_doc,
            "mandatory_practices":   standard.get("mandatory_practices", [])[:6],
            "common_weak_practices": standard.get("common_weak_practices", [])[:5],
        },
    }

    # Inject score values into prompt
    prompt = INDENT_INSIGHT_PROMPT.replace(
        "{score}",         str(report.overall_score)
    ).replace(
        "{grade}",         report.overall_grade
    ).replace(
        "{mandatory_pts}", str(bd.get("mandatory", 0))
    ).replace(
        "{mandatory_max}", "40"
    ).replace(
        "{doc_pts}",       str(bd.get("documentation", 0))
    ).replace(
        "{doc_max}",       "20"
    )

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user",   "content": json.dumps(payload, indent=2, default=str)},
    ]

    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        llm    = LLMClient()
        result = llm.chat(messages=messages, max_tokens=2500)
    finally:
        sys.stdout = old_stdout

    return result
