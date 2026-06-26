"""
indent_comparator.py  (v3)
───────────────────────────
Compares a new IndentExtraction against best_practice_standard.json
using a single LLM call for semantic understanding.

Changes from v2:
  - Passes common_good_practices and common_weak_practices to LLM
  - Richer comparison using full standard including new sections
  - Better fallback with improved scoring
"""

import json
import os
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass, field


# ── Comparison prompt ─────────────────────────────────────────────────────────
COMPARISON_PROMPT = """
You are a senior procurement auditor at Tata Steel.

You are given:
1. best_practice_standard — the gold standard for procurement practices
   derived from analysis of multiple historical indents. It includes:
   - mandatory_practices: must be present in every indent
   - recommended_practices: should be present for quality
   - common_good_practices: what good indents consistently do well
   - common_weak_practices: what bad indents consistently do wrong
   - documentation_requirements: required documents
   - risk_controls: risks that must be addressed
   - vendor_requirements: vendor panel requirements
   - approval_requirements: approval chain requirements
   - document_structure_standards: how each doc type should be structured
   - category_specific_patterns: patterns per procurement category

2. indent_extraction — a new indent to evaluate against the standard.

Your job is to compare the new indent against EVERY section of the standard
and produce a structured evaluation report.

COMPARISON RULES:
- Use semantic understanding, not keyword matching.
- "4 vendors listed with codes" SATISFIES "vendor panel with minimum 3 vendors"
- "HSE plan attached: Yes" SATISFIES "safety document must be present"
- "Approval authority: Niraj Kumar" SATISFIES "approval chain documented"
- Check procurement_summary, good_practices, documents, weak_items,
  risk_controls in the extraction for evidence.
- Cross-reference common_weak_practices — if the indent has issues
  that match known weak practices, flag them explicitly.
- Be fair but critical — if evidence is genuinely absent, mark as fail.

SCORING:
- Start at 100, deduct for each failure:
  Mandatory practice fail:        -8 points
  Documentation requirement fail: -5 points
  Risk control unaddressed:       -4 points
  Vendor requirement fail:        -4 points
  Approval requirement fail:      -5 points
  Structure issue (unstructured): -2 points
- Minimum score: 0

GRADES:
- 80-100: Strong
- 60-79:  Adequate
- 40-59:  Needs Improvement
- 0-39:   Weak

Return ONLY valid JSON. No markdown. No preamble. No trailing text.

{
  "overall_score": number,
  "overall_grade": "Strong" | "Adequate" | "Needs Improvement" | "Weak",
  "procurement_type": string,
  "mandatory_findings": [
    {"status": "pass"|"fail"|"warning", "title": string, "detail": string}
  ],
  "documentation_findings": [
    {"status": "pass"|"fail"|"warning", "title": string, "detail": string}
  ],
  "risk_findings": [
    {"status": "pass"|"fail"|"warning", "title": string, "detail": string}
  ],
  "vendor_findings": [
    {"status": "pass"|"fail"|"warning", "title": string, "detail": string}
  ],
  "approval_findings": [
    {"status": "pass"|"fail"|"warning", "title": string, "detail": string}
  ],
  "structure_findings": [
    {"status": "pass"|"fail"|"warning", "title": string, "detail": string}
  ],
  "good_practice_findings": [
    {"status": "pass"|"fail"|"warning", "title": string, "detail": string}
  ],
  "weak_practice_findings": [
    {"status": "pass"|"fail"|"warning", "title": string, "detail": string}
  ],
  "strengths": [string],
  "gaps": [string],
  "recommendations": [string],
  "cross_doc_issues": [string]
}
"""


@dataclass
class ComparisonFinding:
    category: str
    status:   str
    title:    str
    detail:   str
    source:   Optional[str] = None


@dataclass
class IndentComparisonReport:
    indent_id:        str
    procurement_type: str
    overall_score:    int
    overall_grade:    str

    mandatory_findings:      List[ComparisonFinding] = field(default_factory=list)
    documentation_findings:  List[ComparisonFinding] = field(default_factory=list)
    risk_findings:           List[ComparisonFinding] = field(default_factory=list)
    vendor_findings:         List[ComparisonFinding] = field(default_factory=list)
    approval_findings:       List[ComparisonFinding] = field(default_factory=list)
    structure_findings:      List[ComparisonFinding] = field(default_factory=list)
    good_practice_findings:  List[ComparisonFinding] = field(default_factory=list)
    weak_practice_findings:  List[ComparisonFinding] = field(default_factory=list)

    strengths:        List[str] = field(default_factory=list)
    gaps:             List[str] = field(default_factory=list)
    recommendations:  List[str] = field(default_factory=list)
    cross_doc_issues: List[str] = field(default_factory=list)


def _parse_findings(
    raw_findings: list,
    category: str
) -> List[ComparisonFinding]:
    findings = []
    for f in raw_findings:
        if not isinstance(f, dict):
            continue
        findings.append(ComparisonFinding(
            category = category,
            status   = f.get("status", "info"),
            title    = f.get("title", ""),
            detail   = f.get("detail", ""),
        ))
    return findings


def compare_indent_to_standard(
    indent_extraction: dict,
    standard: dict,
) -> IndentComparisonReport:
    """
    Compare an IndentExtraction dict against best_practice_standard dict.
    Uses a single LLM call for semantic comparison.
    """
    from src.llm_client import LLMClient

    indent_id        = indent_extraction.get("indent_id", "Unknown")
    ps               = indent_extraction.get("procurement_summary", {}) or {}
    procurement_type = (
        ps.get("procurement_type") or
        ps.get("procurment_type") or
        "Unknown"
    )

    # ── Build trimmed standard for LLM ───────────────────────────────────────
    standard_trimmed = {
        "mandatory_practices":         standard.get("mandatory_practices", []),
        "recommended_practices":       standard.get("recommended_practices", []),
        "common_good_practices":       standard.get("common_good_practices", []),
        "common_weak_practices":       standard.get("common_weak_practices", []),
        "documentation_requirements":  standard.get("documentation_requirements", []),
        "risk_controls":               standard.get("risk_controls", []),
        "vendor_requirements":         standard.get("vendor_requirements", []),
        "approval_requirements":       standard.get("approval_requirements", []),
        "document_structure_standards": standard.get("document_structure_standards", []),
        "category_specific_patterns":  [
            p for p in standard.get("category_specific_patterns", [])
            if procurement_type.lower() in
               p.get("procurement_type", "").lower()
               or not procurement_type or procurement_type == "Unknown"
        ][:10],  # only relevant category patterns
    }

    # ── Build trimmed extraction for LLM ─────────────────────────────────────
    extraction_trimmed = {
        "indent_id":           indent_id,
        "procurement_summary": ps,
        "good_practices":      indent_extraction.get("good_practices", []),
        "weak_items":          indent_extraction.get("weak_items", []),
        "risk_controls":       indent_extraction.get("risk_controls", []),
        "approval_flow":       indent_extraction.get("approval_flow", []),
        "documents": [
            {
                "document_name":           d.get("document_name"),
                "document_type":           d.get("document_type"),
                "document_summary":        d.get("document_summary"),
                "document_structure":      d.get("document_structure"),
                "good_practices_observed": d.get("good_practices_observed", []),
                "weak_or_missing_items":   d.get("weak_or_missing_items", []),
            }
            for d in indent_extraction.get("documents", [])
        ],
    }

    user_content = json.dumps({
        "best_practice_standard": standard_trimmed,
        "indent_extraction":      extraction_trimmed,
    }, indent=2)

    messages = [
        {"role": "system", "content": COMPARISON_PROMPT},
        {"role": "user",   "content": user_content},
    ]

    # ── LLM call ──────────────────────────────────────────────────────────────
    print(f"  [COMPARE] Running LLM comparison for {indent_id}...")
    try:
        llm    = LLMClient()
        result = llm.chat_json(messages=messages, max_tokens=4000)
    except Exception as e:
        print(f"  [ERROR] LLM comparison failed: {e}")
        print(f"  [FALLBACK] Using rule-based comparison...")
        return _fallback_comparison(indent_extraction, standard)

    # ── Parse result ──────────────────────────────────────────────────────────
    score = int(result.get("overall_score", 50))
    score = max(0, min(100, score))

    grade = result.get("overall_grade", "")
    if grade not in ("Strong", "Adequate", "Needs Improvement", "Weak"):
        grade = _score_to_grade(score)

    return IndentComparisonReport(
        indent_id        = indent_id,
        procurement_type = result.get("procurement_type", procurement_type),
        overall_score    = score,
        overall_grade    = grade,
        mandatory_findings     = _parse_findings(
            result.get("mandatory_findings", []),     "mandatory"),
        documentation_findings = _parse_findings(
            result.get("documentation_findings", []), "documentation"),
        risk_findings          = _parse_findings(
            result.get("risk_findings", []),          "risk"),
        vendor_findings        = _parse_findings(
            result.get("vendor_findings", []),        "vendor"),
        approval_findings      = _parse_findings(
            result.get("approval_findings", []),      "approval"),
        structure_findings     = _parse_findings(
            result.get("structure_findings", []),     "structure"),
        good_practice_findings = _parse_findings(
            result.get("good_practice_findings", []), "good_practice"),
        weak_practice_findings = _parse_findings(
            result.get("weak_practice_findings", []), "weak_practice"),
        strengths        = [s for s in result.get("strengths", [])
                            if isinstance(s, str)],
        gaps             = [g for g in result.get("gaps", [])
                            if isinstance(g, str)],
        recommendations  = [r for r in result.get("recommendations", [])
                            if isinstance(r, str)],
        cross_doc_issues = [c for c in result.get("cross_doc_issues", [])
                            if isinstance(c, str)],
    )


def _score_to_grade(score: int) -> str:
    if score >= 80: return "Strong"
    if score >= 60: return "Adequate"
    if score >= 40: return "Needs Improvement"
    return "Weak"


def _fallback_comparison(
    indent_extraction: dict,
    standard: dict,
) -> IndentComparisonReport:
    """Rule-based fallback if LLM comparison fails."""
    ps       = indent_extraction.get("procurement_summary", {}) or {}
    docs     = indent_extraction.get("documents", []) or []
    good     = indent_extraction.get("good_practices", []) or []
    weak     = indent_extraction.get("weak_items", []) or []
    risks    = indent_extraction.get("risk_controls", []) or []
    approval = indent_extraction.get("approval_flow", []) or []

    indent_id        = indent_extraction.get("indent_id", "Unknown")
    procurement_type = (
        ps.get("procurement_type") or
        ps.get("procurment_type") or
        "Unknown"
    )

    good_texts = {
        (p.get("practice", "") if isinstance(p, dict) else str(p)).lower()
        for p in good
    }
    doc_types = {
        dt.lower()
        for dt in ps.get("document_types_present", [])
    }
    for doc in docs:
        if doc.get("document_type"):
            doc_types.add(doc["document_type"].lower())

    mandatory_findings     = []
    documentation_findings = []
    risk_findings          = []
    vendor_findings        = []
    approval_findings      = []
    structure_findings     = []
    good_practice_findings = []
    weak_practice_findings = []
    strengths              = []
    gaps                   = []
    recommendations        = []
    cross_doc_issues       = []

    # Mandatory
    for item in standard.get("mandatory_practices", []):
        practice = item.get("practice", "") if isinstance(item, dict) else str(item)
        matched  = any(_fuzzy_match(practice.lower(), gp) for gp in good_texts)
        if not matched:
            matched = _check_summary_field(practice.lower(), ps)
        status = "pass" if matched else "fail"
        mandatory_findings.append(ComparisonFinding(
            category="mandatory", status=status, title=practice,
            detail="Observed." if matched else "Not observed — review documents.",
        ))
        if matched: strengths.append(practice)
        else:
            gaps.append(practice)
            recommendations.append(f"Address: {practice}")

    # Documentation
    for item in standard.get("documentation_requirements", []):
        req     = item.get("requirement", "") if isinstance(item, dict) else str(item)
        matched = any(_fuzzy_match(req.lower(), dt) for dt in doc_types)
        status  = "pass" if matched else "fail"
        documentation_findings.append(ComparisonFinding(
            category="documentation", status=status, title=req,
            detail="Present." if matched else "Missing.",
        ))
        if not matched:
            gaps.append(f"Missing: {req}")
            recommendations.append(f"Include: {req}")

    # Common good practices
    for item in standard.get("common_good_practices", []):
        practice = item.get("practice", "") if isinstance(item, dict) else str(item)
        matched  = any(_fuzzy_match(practice.lower(), gp) for gp in good_texts)
        status   = "pass" if matched else "warning"
        good_practice_findings.append(ComparisonFinding(
            category="good_practice", status=status, title=practice,
            detail="Observed." if matched else "Not observed.",
        ))

    # Common weak practices
    weak_texts = {
        (w.get("issue", "") if isinstance(w, dict) else str(w)).lower()
        for w in weak
    }
    for item in standard.get("common_weak_practices", []):
        issue   = item.get("issue", "") if isinstance(item, dict) else str(item)
        fix     = item.get("how_to_fix", "") if isinstance(item, dict) else ""
        matched = any(_fuzzy_match(issue.lower(), wt) for wt in weak_texts)
        if matched:
            weak_practice_findings.append(ComparisonFinding(
                category="weak_practice", status="fail",
                title=issue,
                detail=f"This weakness was found. Fix: {fix}" if fix else issue,
            ))
            recommendations.append(f"Fix: {fix}" if fix else f"Address: {issue}")

    # Risk controls
    risk_texts = set()
    for r in risks:
        if isinstance(r, dict):
            risk_texts.add(r.get("control", "").lower())
            risk_texts.add(r.get("risk_area", "").lower())

    for item in standard.get("risk_controls", []):
        control   = item.get("control", "") if isinstance(item, dict) else str(item)
        risk_area = item.get("risk_area", "") if isinstance(item, dict) else ""
        matched   = any(_fuzzy_match(control.lower(), rt) for rt in risk_texts)
        status    = "pass" if matched else "warning"
        risk_findings.append(ComparisonFinding(
            category="risk", status=status,
            title=f"{risk_area}: {control}" if risk_area else control,
            detail="Addressed." if matched else "Could not confirm.",
        ))

    # Vendor
    vendor_count_raw = ps.get("vendor_count")
    try:
        vendor_count = int(str(vendor_count_raw).split()[0])
    except Exception:
        vendor_count = 0
    is_single = str(ps.get("is_single_party", "")).lower()

    for item in standard.get("vendor_requirements", []):
        req     = item.get("requirement", "") if isinstance(item, dict) else str(item)
        matched = bool(ps.get("vendor_panel")) and vendor_count > 0
        status  = "pass" if matched else "warning"
        vendor_findings.append(ComparisonFinding(
            category="vendor", status=status, title=req,
            detail="Met." if matched else "Review vendor documentation.",
        ))

    if vendor_count == 1 and is_single not in ("yes", "true"):
        vendor_findings.append(ComparisonFinding(
            category="vendor", status="fail",
            title="Single vendor without justification",
            detail="Only 1 vendor but no single-party approval found.",
        ))
        cross_doc_issues.append("Vendor panel has 1 vendor — single-party approval missing.")
        recommendations.append("Add more vendors or provide single-party justification.")

    # Approvals
    has_approval = (
        bool(approval) or
        bool(ps.get("approval_authority")) or
        bool(ps.get("indent_approval_date"))
    )
    for item in standard.get("approval_requirements", []):
        req    = item.get("requirement", "") if isinstance(item, dict) else str(item)
        status = "pass" if has_approval else "fail"
        approval_findings.append(ComparisonFinding(
            category="approval", status=status, title=req,
            detail="Documented." if has_approval else "Missing.",
        ))
        if not has_approval:
            recommendations.append(f"Ensure: {req}")

    # Structure
    for doc in docs:
        ds      = doc.get("document_structure")
        if not ds or not isinstance(ds, dict):
            continue
        quality = ds.get("structure_quality", "")
        missing = ds.get("missing_sections", [])
        name    = doc.get("document_name", "")
        dtype   = doc.get("document_type", "")
        if quality == "Well structured":
            structure_findings.append(ComparisonFinding(
                category="structure", status="pass",
                title=f"{dtype}: {name}",
                detail=ds.get("logical_sequence", "Well structured."),
            ))
        elif quality == "Partially structured":
            detail = "Partially structured."
            if missing:
                detail += f" Missing: {', '.join(missing)}."
            structure_findings.append(ComparisonFinding(
                category="structure", status="warning",
                title=f"{dtype}: {name}", detail=detail,
            ))
            if missing:
                recommendations.append(
                    f"Improve {name}: add {', '.join(missing)}"
                )
        elif quality == "Unstructured":
            structure_findings.append(ComparisonFinding(
                category="structure", status="fail",
                title=f"{dtype}: {name}",
                detail="Unstructured — lacks clear sections.",
            ))
            recommendations.append(f"Restructure {name}.")

    # Score
    all_findings = (
        mandatory_findings + documentation_findings +
        risk_findings + vendor_findings + approval_findings
    )
    if all_findings:
        passes   = sum(1 for f in all_findings if f.status == "pass")
        warnings = sum(1 for f in all_findings if f.status == "warning")
        total    = len(all_findings)
        score    = int(((passes + warnings * 0.5) / total) * 100)
    else:
        score = 50

    seen   = set()
    deduped = []
    for r in recommendations:
        if r.lower() not in seen:
            seen.add(r.lower())
            deduped.append(r)

    return IndentComparisonReport(
        indent_id=indent_id,
        procurement_type=procurement_type,
        overall_score=score,
        overall_grade=_score_to_grade(score),
        mandatory_findings=mandatory_findings,
        documentation_findings=documentation_findings,
        risk_findings=risk_findings,
        vendor_findings=vendor_findings,
        approval_findings=approval_findings,
        structure_findings=structure_findings,
        good_practice_findings=good_practice_findings,
        weak_practice_findings=weak_practice_findings,
        strengths=strengths,
        gaps=gaps,
        recommendations=deduped,
        cross_doc_issues=cross_doc_issues,
    )


def _fuzzy_match(needle: str, haystack: str) -> bool:
    needle_words   = set(needle.lower().split())
    haystack_words = set(haystack.lower().split())
    stops = {
        "a", "an", "the", "in", "of", "for", "and", "or",
        "is", "are", "to", "with", "on", "at", "by", "be"
    }
    needle_words   -= stops
    haystack_words -= stops
    if not needle_words:
        return False
    overlap = needle_words & haystack_words
    return len(overlap) / len(needle_words) >= 0.4


def _check_summary_field(practice_lower: str, ps: dict) -> bool:
    field_map = {
        "scope":        ps.get("scope_of_work"),
        "vendor":       ps.get("vendor_panel"),
        "hse":          ps.get("hse_plan_available"),
        "safety":       ps.get("hse_plan_available"),
        "technical":    ps.get("technical_spec_attached"),
        "approval":     ps.get("approval_authority") or ps.get("indent_approval_date"),
        "cost":         ps.get("estimated_cost_crores"),
        "boq":          ps.get("boq_surplus_checked"),
        "surplus":      ps.get("boq_surplus_checked"),
        "term sheet":   ps.get("term_sheet_type"),
        "single party": ps.get("is_single_party"),
    }
    for keyword, value in field_map.items():
        if keyword in practice_lower and value and \
                str(value).lower() not in ("null", "none", ""):
            return True
    return False
