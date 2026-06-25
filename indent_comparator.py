"""
indent_comparator.py
────────────────────
Compares a new IndentExtraction against best_practice_standard.json
and produces structured recommendations.
"""

from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass, field


@dataclass
class ComparisonFinding:
    category: str        # "mandatory" | "recommended" | "risk" | "documentation" | "approval" | "vendor"
    status: str          # "pass" | "fail" | "warning" | "info"
    title: str
    detail: str
    source: Optional[str] = None   # which standard practice this came from


@dataclass
class IndentComparisonReport:
    indent_id: str
    procurement_type: str
    overall_score: int              # 0-100
    overall_grade: str              # "Strong" | "Adequate" | "Needs Improvement" | "Weak"

    mandatory_findings:    List[ComparisonFinding] = field(default_factory=list)
    documentation_findings: List[ComparisonFinding] = field(default_factory=list)
    risk_findings:         List[ComparisonFinding] = field(default_factory=list)
    vendor_findings:       List[ComparisonFinding] = field(default_factory=list)
    approval_findings:     List[ComparisonFinding] = field(default_factory=list)
    structure_findings:    List[ComparisonFinding] = field(default_factory=list)

    strengths:       List[str] = field(default_factory=list)
    gaps:            List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    cross_doc_issues: List[str] = field(default_factory=list)


def compare_indent_to_standard(
    indent_extraction: dict,
    standard: dict,
) -> IndentComparisonReport:
    """
    Compare an IndentExtraction dict against best_practice_standard dict.
    Returns a structured report with findings per category.
    """
    ps      = indent_extraction.get("procurement_summary", {}) or {}
    docs    = indent_extraction.get("documents", []) or []
    good    = indent_extraction.get("good_practices", []) or []
    weak    = indent_extraction.get("weak_items", []) or []
    risks   = indent_extraction.get("risk_controls", []) or []
    approval = indent_extraction.get("approval_flow", []) or []
    recs    = indent_extraction.get("recommendations", []) or []

    indent_id       = indent_extraction.get("indent_id", "Unknown")
    procurement_type = ps.get("procurement_type") or ps.get("procurment_type") or "Unknown"

    mandatory_findings    = []
    documentation_findings = []
    risk_findings         = []
    vendor_findings       = []
    approval_findings     = []
    structure_findings    = []
    strengths             = []
    gaps                  = []
    recommendations_out   = []
    cross_doc_issues      = []

    # ── Good practices from indent as a flat set for matching ─────────────────
    good_practice_texts = set()
    for p in good:
        if isinstance(p, dict):
            good_practice_texts.add(p.get("practice", "").lower())
        else:
            good_practice_texts.add(str(p).lower())

    # ── Weak items from indent ─────────────────────────────────────────────────
    weak_issue_texts = set()
    for w in weak:
        if isinstance(w, dict):
            weak_issue_texts.add(w.get("issue", "").lower())
        else:
            weak_issue_texts.add(str(w).lower())

    # ── Document types present ────────────────────────────────────────────────
    doc_types_present = set(
        dt.lower() for dt in ps.get("document_types_present", [])
    )
    # Also collect from documents list
    for doc in docs:
        dt = doc.get("document_type", "")
        if dt:
            doc_types_present.add(dt.lower())

    # ══════════════════════════════════════════════════════════════════════════
    # 1. MANDATORY PRACTICES
    # ══════════════════════════════════════════════════════════════════════════
    for practice_item in standard.get("mandatory_practices", []):
        practice = practice_item if isinstance(practice_item, str) else \
                   practice_item.get("practice", "")
        if not practice:
            continue

        practice_lower = practice.lower()
        # Check if any good practice from indent matches this
        matched = any(
            _fuzzy_match(practice_lower, gp)
            for gp in good_practice_texts
        )
        # Also check key summary fields
        if not matched:
            matched = _check_summary_field(practice_lower, ps)

        if matched:
            mandatory_findings.append(ComparisonFinding(
                category="mandatory",
                status="pass",
                title=practice,
                detail="This practice is evident in the indent documents.",
                source="mandatory_practices",
            ))
            strengths.append(practice)
        else:
            mandatory_findings.append(ComparisonFinding(
                category="mandatory",
                status="fail",
                title=practice,
                detail=f"This mandatory practice was not clearly observed. "
                       f"Review your documents to ensure this is addressed.",
                source="mandatory_practices",
            ))
            gaps.append(practice)
            recommendations_out.append(
                f"Address mandatory practice: {practice}"
            )

    # ══════════════════════════════════════════════════════════════════════════
    # 2. DOCUMENTATION REQUIREMENTS
    # ══════════════════════════════════════════════════════════════════════════
    for req_item in standard.get("documentation_requirements", []):
        req = req_item if isinstance(req_item, str) else \
              req_item.get("requirement", "")
        if not req:
            continue

        req_lower = req.lower()
        # Check if document type is present
        matched = any(_fuzzy_match(req_lower, dt) for dt in doc_types_present)

        if matched:
            documentation_findings.append(ComparisonFinding(
                category="documentation",
                status="pass",
                title=req,
                detail="Document type is present in this indent.",
            ))
        else:
            documentation_findings.append(ComparisonFinding(
                category="documentation",
                status="fail",
                title=req,
                detail=f"This document type appears to be missing. "
                       f"Ensure it is included before submission.",
            ))
            gaps.append(f"Missing document: {req}")
            recommendations_out.append(f"Include required document: {req}")

    # ══════════════════════════════════════════════════════════════════════════
    # 3. RISK CONTROLS
    # ══════════════════════════════════════════════════════════════════════════
    for rc_item in standard.get("risk_controls", []):
        if isinstance(rc_item, str):
            risk_area = rc_item
            control   = rc_item
        else:
            risk_area = rc_item.get("risk_area", "")
            control   = rc_item.get("control", "")

        if not control:
            continue

        control_lower = control.lower()
        # Check if this risk is already controlled in the indent
        indent_risk_controls = set()
        for r in risks:
            if isinstance(r, dict):
                indent_risk_controls.add(r.get("control", "").lower())
                indent_risk_controls.add(r.get("risk_area", "").lower())

        matched = any(_fuzzy_match(control_lower, rc) for rc in indent_risk_controls)

        # Also check if this weak item appears in the indent (means risk is uncontrolled)
        uncontrolled = any(_fuzzy_match(control_lower, wi) for wi in weak_issue_texts)

        if uncontrolled:
            risk_findings.append(ComparisonFinding(
                category="risk",
                status="fail",
                title=f"{risk_area}: {control}",
                detail="This risk was flagged as uncontrolled in your indent documents.",
            ))
            recommendations_out.append(
                f"Address uncontrolled risk — {risk_area}: {control}"
            )
        elif matched:
            risk_findings.append(ComparisonFinding(
                category="risk",
                status="pass",
                title=f"{risk_area}: {control}",
                detail="Risk control is addressed in this indent.",
            ))
        else:
            risk_findings.append(ComparisonFinding(
                category="risk",
                status="warning",
                title=f"{risk_area}: {control}",
                detail="Could not confirm this risk control is in place. Review your documents.",
            ))

    # ══════════════════════════════════════════════════════════════════════════
    # 4. VENDOR REQUIREMENTS
    # ══════════════════════════════════════════════════════════════════════════
    vendor_panel = ps.get("vendor_panel", "")
    vendor_count_raw = ps.get("vendor_count")
    try:
        vendor_count = int(str(vendor_count_raw).replace("None", "0").split()[0])
    except Exception:
        vendor_count = 0

    is_single_party = str(ps.get("is_single_party", "")).lower()

    for req_item in standard.get("vendor_requirements", []):
        req = req_item if isinstance(req_item, str) else \
              req_item.get("requirement", "")
        if not req:
            continue

        req_lower = req.lower()
        matched   = False

        if "vendor panel" in req_lower or "vendor" in req_lower:
            matched = bool(vendor_panel) and vendor_count > 0

        if not matched:
            matched = any(_fuzzy_match(req_lower, gp) for gp in good_practice_texts)

        if matched:
            vendor_findings.append(ComparisonFinding(
                category="vendor",
                status="pass",
                title=req,
                detail="Vendor requirement appears to be met.",
            ))
        else:
            vendor_findings.append(ComparisonFinding(
                category="vendor",
                status="warning",
                title=req,
                detail="Review vendor documentation to confirm this requirement is met.",
            ))

    # Specific vendor panel check
    if vendor_count == 1 and is_single_party not in ("yes", "true"):
        vendor_findings.append(ComparisonFinding(
            category="vendor",
            status="fail",
            title="Single vendor without single-party justification",
            detail=f"Only 1 vendor in panel but no single-party approval found. "
                   f"This is a procurement risk.",
        ))
        cross_doc_issues.append(
            "Vendor panel has only 1 vendor but no single-party approval document found."
        )
        recommendations_out.append(
            "Either add more vendors to the panel or provide single-party justification."
        )

    # ══════════════════════════════════════════════════════════════════════════
    # 5. APPROVAL REQUIREMENTS
    # ══════════════════════════════════════════════════════════════════════════
    has_approval = bool(approval) or bool(ps.get("approval_authority")) or \
                   bool(ps.get("indent_approval_date"))

    for req_item in standard.get("approval_requirements", []):
        req = req_item if isinstance(req_item, str) else \
              req_item.get("requirement", "")
        if not req:
            continue

        if has_approval:
            approval_findings.append(ComparisonFinding(
                category="approval",
                status="pass",
                title=req,
                detail="Approval information is present in this indent.",
            ))
        else:
            approval_findings.append(ComparisonFinding(
                category="approval",
                status="fail",
                title=req,
                detail="Approval chain is missing or incomplete.",
            ))
            recommendations_out.append(f"Ensure approval requirement is met: {req}")

    # ══════════════════════════════════════════════════════════════════════════
    # 6. DOCUMENT STRUCTURE CHECKS
    # ══════════════════════════════════════════════════════════════════════════
    for doc in docs:
        doc_name = doc.get("document_name", "")
        doc_type = doc.get("document_type", "")
        ds       = doc.get("document_structure")
        if not ds or not isinstance(ds, dict):
            continue

        quality  = ds.get("structure_quality", "")
        missing  = ds.get("missing_sections", [])
        pattern  = ds.get("notable_pattern", "")

        if quality == "Well structured":
            structure_findings.append(ComparisonFinding(
                category="structure",
                status="pass",
                title=f"{doc_type}: {doc_name}",
                detail=ds.get("logical_sequence", "Well structured document."),
            ))
        elif quality == "Partially structured":
            detail = f"Partially structured."
            if missing:
                detail += f" Missing sections: {', '.join(missing)}."
            if pattern:
                detail += f" Note: {pattern}"
            structure_findings.append(ComparisonFinding(
                category="structure",
                status="warning",
                title=f"{doc_type}: {doc_name}",
                detail=detail,
            ))
            if missing:
                recommendations_out.append(
                    f"Improve {doc_name}: add missing sections — {', '.join(missing)}"
                )
        elif quality == "Unstructured":
            structure_findings.append(ComparisonFinding(
                category="structure",
                status="fail",
                title=f"{doc_type}: {doc_name}",
                detail=f"Document is unstructured. {pattern or ''}",
            ))
            recommendations_out.append(
                f"Restructure {doc_name} — it lacks clear sections and logical flow."
            )

    # ══════════════════════════════════════════════════════════════════════════
    # 7. CROSS-DOCUMENT ISSUES from extraction
    # ══════════════════════════════════════════════════════════════════════════
    for rec in recs:
        cross_doc_issues.append(rec)

    # ══════════════════════════════════════════════════════════════════════════
    # SCORING
    # ══════════════════════════════════════════════════════════════════════════
    all_findings = (
        mandatory_findings + documentation_findings +
        risk_findings + vendor_findings + approval_findings
    )
    if all_findings:
        passes   = sum(1 for f in all_findings if f.status == "pass")
        fails    = sum(1 for f in all_findings if f.status == "fail")
        warnings = sum(1 for f in all_findings if f.status == "warning")
        total    = len(all_findings)
        score    = int(((passes + warnings * 0.5) / total) * 100)
    else:
        score = 50

    if score >= 80:
        grade = "Strong"
    elif score >= 60:
        grade = "Adequate"
    elif score >= 40:
        grade = "Needs Improvement"
    else:
        grade = "Weak"

    # Deduplicate recommendations
    seen = set()
    deduped_recs = []
    for r in recommendations_out:
        if r.lower() not in seen:
            seen.add(r.lower())
            deduped_recs.append(r)

    return IndentComparisonReport(
        indent_id=indent_id,
        procurement_type=procurement_type,
        overall_score=score,
        overall_grade=grade,
        mandatory_findings=mandatory_findings,
        documentation_findings=documentation_findings,
        risk_findings=risk_findings,
        vendor_findings=vendor_findings,
        approval_findings=approval_findings,
        structure_findings=structure_findings,
        strengths=strengths,
        gaps=gaps,
        recommendations=deduped_recs,
        cross_doc_issues=cross_doc_issues,
    )


def _fuzzy_match(needle: str, haystack: str) -> bool:
    """Simple keyword overlap match — no external dependencies needed."""
    needle_words   = set(needle.lower().split())
    haystack_words = set(haystack.lower().split())
    # Remove stopwords
    stops = {"a", "an", "the", "in", "of", "for", "and", "or",
             "is", "are", "to", "with", "on", "at", "by", "be"}
    needle_words   -= stops
    haystack_words -= stops
    if not needle_words:
        return False
    overlap = needle_words & haystack_words
    return len(overlap) / len(needle_words) >= 0.4


def _check_summary_field(practice_lower: str, ps: dict) -> bool:
    """Check if a practice is addressed by procurement summary fields."""
    field_map = {
        "scope":       ps.get("scope_of_work"),
        "vendor":      ps.get("vendor_panel"),
        "hse":         ps.get("hse_plan_available"),
        "safety":      ps.get("hse_plan_available"),
        "technical":   ps.get("technical_spec_attached"),
        "approval":    ps.get("approval_authority") or ps.get("indent_approval_date"),
        "cost":        ps.get("estimated_cost_crores"),
        "boq":         ps.get("boq_surplus_checked"),
        "surplus":     ps.get("boq_surplus_checked"),
        "term sheet":  ps.get("term_sheet_type"),
        "single party": ps.get("is_single_party"),
    }
    for keyword, value in field_map.items():
        if keyword in practice_lower and value and str(value).lower() not in ("null", "none", ""):
            return True
    return False