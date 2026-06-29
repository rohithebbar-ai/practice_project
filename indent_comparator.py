"""
indent_comparator.py  (v5)
──────────────────────────
LLM-based semantic comparison with disk caching.

Flow:
  1. Check disk cache — if found, return cached result (same score always)
  2. Build structured prompt with indent + standard
  3. Single LLM call → structured JSON evaluation
  4. Parse into IndentComparisonReport
  5. Save to disk cache

Weighted scoring:
  Mandatory     = 40 pts
  Documentation = 20 pts
  Risk controls = 20 pts
  Vendor        = 10 pts
  Approval      = 10 pts
"""

import json
import hashlib
import logging
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

CACHE_DIR = Path("results_cache")

WEIGHTS = {
    "mandatory":     40,
    "documentation": 20,
    "risk":          20,
    "vendor":        10,
    "approval":      10,
}

# ── Comparison prompt ─────────────────────────────────────────────────────────
COMPARISON_PROMPT = """
You are a senior procurement auditor at Tata Steel.

You are given:
1. indent_data — extracted data from a new procurement indent
2. standard — the best practice standard derived from historical indents

Your task: evaluate how well this indent meets the standard.

For each category, evaluate EVERY item in the standard against the indent.
Use semantic understanding — do not just match keywords.

For example:
- "Detailed scope of work provided" matches "Comprehensive description of civil works..."
- "HSE plan available" matches "Safety Term Sheet is attached = Yes"
- "Vendor panel documented" matches "Three vendors listed in Tracker"

Status values:
- "pass"    = clearly present and adequate in the indent
- "fail"    = required by standard but missing or absent from indent
- "warning" = partially present or unclear — needs review

For each finding include:
- title: the standard practice/requirement being checked
- status: pass / fail / warning
- detail: one specific sentence explaining WHY — reference actual document
  names or field values from the indent where possible

Cross-document issues: note any inconsistencies between documents
e.g. BOQ scope doesn't match Technical Spec, single vendor without approval.

Recommendations: specific actionable improvements for this indent.
Reference actual document names and missing content.

Return ONLY valid JSON in exactly this structure:
{
  "mandatory_findings": [
    {"title": "", "status": "pass|fail|warning", "detail": ""}
  ],
  "documentation_findings": [
    {"title": "", "status": "pass|fail|warning", "detail": ""}
  ],
  "risk_findings": [
    {"title": "", "status": "pass|fail|warning", "detail": ""}
  ],
  "vendor_findings": [
    {"title": "", "status": "pass|fail|warning", "detail": ""}
  ],
  "approval_findings": [
    {"title": "", "status": "pass|fail|warning", "detail": ""}
  ],
  "structure_findings": [
    {"title": "", "status": "pass|fail|warning", "detail": ""}
  ],
  "good_practice_findings": [
    {"title": "", "status": "pass", "detail": ""}
  ],
  "weak_practice_findings": [
    {"title": "", "status": "warning", "detail": ""}
  ],
  "strengths": [""],
  "gaps": [""],
  "recommendations": [""],
  "cross_doc_issues": [""]
}

Rules:
- Evaluate ALL items from each standard section
- Be specific — mention actual document names from the indent
- strengths: top things this indent does well (max 5)
- gaps: practices required by standard but missing (concise phrases)
- recommendations: actionable improvements (max 8)
- Return only the JSON object, no markdown, no preamble
"""


@dataclass
class ComparisonFinding:
    category: str
    status: str
    title: str
    detail: str
    source: Optional[str] = None


@dataclass
class IndentComparisonReport:
    indent_id: str
    procurement_type: str
    overall_score: int
    overall_grade: str
    score_breakdown: dict = field(default_factory=dict)

    mandatory_findings:     List[ComparisonFinding] = field(default_factory=list)
    documentation_findings: List[ComparisonFinding] = field(default_factory=list)
    risk_findings:          List[ComparisonFinding] = field(default_factory=list)
    vendor_findings:        List[ComparisonFinding] = field(default_factory=list)
    approval_findings:      List[ComparisonFinding] = field(default_factory=list)
    structure_findings:     List[ComparisonFinding] = field(default_factory=list)
    good_practice_findings: List[ComparisonFinding] = field(default_factory=list)
    weak_practice_findings: List[ComparisonFinding] = field(default_factory=list)

    strengths:        List[str] = field(default_factory=list)
    gaps:             List[str] = field(default_factory=list)
    recommendations:  List[str] = field(default_factory=list)
    cross_doc_issues: List[str] = field(default_factory=list)


# ── Weighted scoring ──────────────────────────────────────────────────────────

def _category_score(findings: list, weight: int) -> float:
    if not findings:
        return float(weight)
    total  = len(findings)
    earned = sum(
        1.0 if f.status == "pass"
        else 0.5 if f.status == "warning"
        else 0.0
        for f in findings
    )
    return round((earned / total) * weight, 1)


def _calculate_score(
    mandatory, documentation, risk, vendor, approval
) -> tuple:
    breakdown = {
        "mandatory":     _category_score(mandatory,     WEIGHTS["mandatory"]),
        "documentation": _category_score(documentation, WEIGHTS["documentation"]),
        "risk":          _category_score(risk,          WEIGHTS["risk"]),
        "vendor":        _category_score(vendor,        WEIGHTS["vendor"]),
        "approval":      _category_score(approval,      WEIGHTS["approval"]),
    }
    score = min(100, int(round(sum(breakdown.values()))))
    if score >= 80:   grade = "Strong"
    elif score >= 60: grade = "Adequate"
    elif score >= 40: grade = "Needs Improvement"
    else:             grade = "Weak"
    return score, grade, breakdown


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _make_cache_key(indent_extraction: dict, standard: dict) -> str:
    ps   = indent_extraction.get("procurement_summary", {}) or {}
    docs = indent_extraction.get("documents", []) or []
    fingerprint = {
        "indent_id":        indent_extraction.get("indent_id", ""),
        "procurement_type": ps.get("procurement_type", ""),
        "scope":            (ps.get("scope_of_work") or "")[:200],
        "doc_names": sorted([
            d.get("document_name", "") for d in docs
        ]),
        "standard_version": standard.get("_metadata", {}).get(
            "prompt_version", "unknown"
        ),
        "source_indents": standard.get("_metadata", {}).get(
            "source_indents", 0
        ),
    }
    return hashlib.md5(
        json.dumps(fingerprint, sort_keys=True).encode()
    ).hexdigest()[:16]


def _load_cache(cache_key: str) -> Optional[dict]:
    cache_path = CACHE_DIR / f"{cache_key}.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _save_cache(cache_key: str, data: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{cache_key}.json").write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"[CACHE] Save failed: {e}")


def _findings_to_list(findings: list) -> list:
    return [
        {
            "category": f.category,
            "status":   f.status,
            "title":    f.title,
            "detail":   f.detail,
            "source":   f.source,
        }
        for f in findings
    ]


def _list_to_findings(items: list, category: str) -> List[ComparisonFinding]:
    return [
        ComparisonFinding(
            category=category,
            status=f.get("status", "info"),
            title=f.get("title", ""),
            detail=f.get("detail", ""),
            source=f.get("source"),
        )
        for f in (items or [])
    ]


def _report_to_dict(report: IndentComparisonReport) -> dict:
    return {
        "indent_id":              report.indent_id,
        "procurement_type":       report.procurement_type,
        "overall_score":          report.overall_score,
        "overall_grade":          report.overall_grade,
        "score_breakdown":        report.score_breakdown,
        "mandatory_findings":     _findings_to_list(report.mandatory_findings),
        "documentation_findings": _findings_to_list(report.documentation_findings),
        "risk_findings":          _findings_to_list(report.risk_findings),
        "vendor_findings":        _findings_to_list(report.vendor_findings),
        "approval_findings":      _findings_to_list(report.approval_findings),
        "structure_findings":     _findings_to_list(report.structure_findings),
        "good_practice_findings": _findings_to_list(report.good_practice_findings),
        "weak_practice_findings": _findings_to_list(report.weak_practice_findings),
        "strengths":              report.strengths,
        "gaps":                   report.gaps,
        "recommendations":        report.recommendations,
        "cross_doc_issues":       report.cross_doc_issues,
    }


def _report_from_dict(data: dict) -> IndentComparisonReport:
    return IndentComparisonReport(
        indent_id=data.get("indent_id", "Unknown"),
        procurement_type=data.get("procurement_type", "Unknown"),
        overall_score=data.get("overall_score", 0),
        overall_grade=data.get("overall_grade", "Unknown"),
        score_breakdown=data.get("score_breakdown", {}),
        mandatory_findings=_list_to_findings(
            data.get("mandatory_findings", []), "mandatory"),
        documentation_findings=_list_to_findings(
            data.get("documentation_findings", []), "documentation"),
        risk_findings=_list_to_findings(
            data.get("risk_findings", []), "risk"),
        vendor_findings=_list_to_findings(
            data.get("vendor_findings", []), "vendor"),
        approval_findings=_list_to_findings(
            data.get("approval_findings", []), "approval"),
        structure_findings=_list_to_findings(
            data.get("structure_findings", []), "structure"),
        good_practice_findings=_list_to_findings(
            data.get("good_practice_findings", []), "good_practice"),
        weak_practice_findings=_list_to_findings(
            data.get("weak_practice_findings", []), "weak_practice"),
        strengths=data.get("strengths", []),
        gaps=data.get("gaps", []),
        recommendations=data.get("recommendations", []),
        cross_doc_issues=data.get("cross_doc_issues", []),
    )


# ── Build LLM payload ─────────────────────────────────────────────────────────

def _build_payload(indent_extraction: dict, standard: dict) -> dict:
    """Build a focused payload for the LLM — trim to fit token budget."""
    ps   = indent_extraction.get("procurement_summary", {}) or {}
    docs = indent_extraction.get("documents", []) or []

    # Per-document summary
    doc_summaries = []
    for doc in docs:
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

    indent_data = {
        "indent_id":           indent_extraction.get("indent_id"),
        "procurement_summary": {
            "procurement_type":      ps.get("procurement_type"),
            "package_description":   ps.get("package_description"),
            "scope_of_work":         (ps.get("scope_of_work") or "")[:400],
            "location":              ps.get("location"),
            "estimated_cost_crores": ps.get("estimated_cost_crores"),
            "vendor_panel":          ps.get("vendor_panel"),
            "vendor_count":          ps.get("vendor_count"),
            "is_single_party":       ps.get("is_single_party"),
            "hse_plan_available":    ps.get("hse_plan_available"),
            "technical_spec_attached": ps.get("technical_spec_attached"),
            "term_sheet_type":       ps.get("term_sheet_type"),
            "boq_surplus_checked":   ps.get("boq_surplus_checked"),
            "approval_authority":    ps.get("approval_authority"),
            "indent_approval_date":  ps.get("indent_approval_date"),
            "job_risk_category":     ps.get("job_risk_category"),
            "document_types_present": ps.get("document_types_present", []),
            "missing_documents":     ps.get("missing_documents", []),
        },
        "documents":      doc_summaries,
        "good_practices": [
            (p.get("practice") if isinstance(p, dict) else p)
            for p in indent_extraction.get("good_practices", [])[:6]
        ],
        "weak_items": [
            (w.get("issue") if isinstance(w, dict) else w)
            for w in indent_extraction.get("weak_items", [])[:6]
        ],
        "approval_flow": indent_extraction.get("approval_flow", [])[:3],
        "risk_controls": [
            f"{r.get('risk_area','')}: {r.get('control','')}"
            if isinstance(r, dict) else r
            for r in indent_extraction.get("risk_controls", [])[:5]
        ],
        "cross_doc_patterns": indent_extraction.get(
            "category_document_patterns", []
        )[:3],
    }

    # Procurement type for filtering relevant standard sections
    proc_type = (ps.get("procurement_type") or "").lower()

    standard_data = {
        "mandatory_practices":        standard.get("mandatory_practices", []),
        "documentation_requirements": standard.get("documentation_requirements", []),
        "risk_controls":              standard.get("risk_controls", [])[:8],
        "vendor_requirements":        standard.get("vendor_requirements", []),
        "approval_requirements":      standard.get("approval_requirements", []),
        "common_good_practices":      standard.get("common_good_practices", [])[:6],
        "common_weak_practices":      standard.get("common_weak_practices", [])[:6],
        "document_structure_standards": [
            s for s in standard.get("document_structure_standards", [])
        ][:6],
        "category_specific_patterns": [
            p for p in standard.get("category_specific_patterns", [])
            if not proc_type or
            proc_type.split("-")[0].strip() in
            p.get("procurement_type", "").lower()
        ][:5],
    }

    return {
        "indent_data": indent_data,
        "standard":    standard_data,
    }


# ── Main entry point ──────────────────────────────────────────────────────────

def compare_indent_to_standard(
    indent_extraction: dict,
    standard: dict,
    use_cache: bool = True,
) -> IndentComparisonReport:
    """
    LLM-based semantic comparison with disk caching.
    Same indent + same standard = same result every time.
    """
    indent_id        = indent_extraction.get("indent_id", "Unknown")
    ps               = indent_extraction.get("procurement_summary", {}) or {}
    procurement_type = (
        ps.get("procurement_type") or
        ps.get("procurment_type") or
        "Unknown"
    )

    # ── Cache check ───────────────────────────────────────────────────────────
    cache_key = _make_cache_key(indent_extraction, standard)
    if use_cache:
        cached = _load_cache(cache_key)
        if cached:
            logger.info(f"[COMPARE] Cache hit for {indent_id}")
            return _report_from_dict(cached)

    logger.info(f"[COMPARE] Running LLM comparison for {indent_id}...")

    # ── LLM call ──────────────────────────────────────────────────────────────
    payload  = _build_payload(indent_extraction, standard)
    result   = {}

    try:
        from src.llm_client import LLMClient
        llm      = LLMClient()
        messages = [
            {"role": "system", "content": COMPARISON_PROMPT},
            {"role": "user",   "content": json.dumps(payload, indent=2,
                                                      default=str)},
        ]
        result = llm.chat_json(messages=messages, max_tokens=4000)
        logger.info(f"[COMPARE] LLM call successful for {indent_id}")
    except Exception as e:
        logger.error(f"[COMPARE] LLM failed: {e} — using rule-based fallback")
        result = _rule_based_fallback(indent_extraction, standard)

    # ── Parse findings ────────────────────────────────────────────────────────
    def _parse(items, category) -> List[ComparisonFinding]:
        findings = []
        for item in (items or []):
            if not isinstance(item, dict):
                continue
            findings.append(ComparisonFinding(
                category=category,
                status=item.get("status", "info"),
                title=item.get("title", ""),
                detail=item.get("detail", ""),
            ))
        return findings

    mandatory_findings      = _parse(result.get("mandatory_findings", []),      "mandatory")
    documentation_findings  = _parse(result.get("documentation_findings", []),  "documentation")
    risk_findings           = _parse(result.get("risk_findings", []),           "risk")
    vendor_findings         = _parse(result.get("vendor_findings", []),         "vendor")
    approval_findings       = _parse(result.get("approval_findings", []),       "approval")
    structure_findings      = _parse(result.get("structure_findings", []),      "structure")
    good_practice_findings  = _parse(result.get("good_practice_findings", []),  "good_practice")
    weak_practice_findings  = _parse(result.get("weak_practice_findings", []),  "weak_practice")

    # ── Weighted score ────────────────────────────────────────────────────────
    score, grade, breakdown = _calculate_score(
        mandatory_findings,
        documentation_findings,
        risk_findings,
        vendor_findings,
        approval_findings,
    )

    report = IndentComparisonReport(
        indent_id=indent_id,
        procurement_type=procurement_type,
        overall_score=score,
        overall_grade=grade,
        score_breakdown=breakdown,
        mandatory_findings=mandatory_findings,
        documentation_findings=documentation_findings,
        risk_findings=risk_findings,
        vendor_findings=vendor_findings,
        approval_findings=approval_findings,
        structure_findings=structure_findings,
        good_practice_findings=good_practice_findings,
        weak_practice_findings=weak_practice_findings,
        strengths=[
            s for s in result.get("strengths", [])
            if isinstance(s, str)
        ],
        gaps=[
            g for g in result.get("gaps", [])
            if isinstance(g, str)
        ],
        recommendations=[
            r for r in result.get("recommendations", [])
            if isinstance(r, str)
        ],
        cross_doc_issues=[
            c for c in result.get("cross_doc_issues", [])
            if isinstance(c, str)
        ],
    )

    # ── Save to cache ─────────────────────────────────────────────────────────
    _save_cache(cache_key, _report_to_dict(report))
    logger.info(f"[COMPARE] Cached result for {indent_id} → key {cache_key}")

    return report


# ── Rule-based fallback ───────────────────────────────────────────────────────

def _rule_based_fallback(
    indent_extraction: dict,
    standard: dict,
) -> dict:
    """
    Simple rule-based fallback if LLM fails.
    Returns dict in same format as LLM response.
    """
    ps               = indent_extraction.get("procurement_summary", {}) or {}
    docs             = indent_extraction.get("documents", []) or []
    good             = indent_extraction.get("good_practices", []) or []
    weak             = indent_extraction.get("weak_items", []) or []
    risks            = indent_extraction.get("risk_controls", []) or []
    approval         = indent_extraction.get("approval_flow", []) or []
    recs             = indent_extraction.get("recommendations", []) or []

    good_texts = set()
    for p in good:
        t = p.get("practice", "") if isinstance(p, dict) else str(p)
        if t: good_texts.add(t.lower())

    doc_types = set(dt.lower() for dt in ps.get("document_types_present", []))
    for doc in docs:
        dt = doc.get("document_type", "")
        if dt: doc_types.add(dt.lower())

    mandatory_findings = []
    for item in standard.get("mandatory_practices", []):
        practice = item.get("practice", "") if isinstance(item, dict) else item
        matched  = any(_fuzzy_match(practice.lower(), gp) for gp in good_texts)
        mandatory_findings.append({
            "title":  practice,
            "status": "pass" if matched else "fail",
            "detail": (
                "Confirmed present in this indent."
                if matched else
                "Required by standard but not confirmed in this indent."
            ),
        })

    documentation_findings = []
    for item in standard.get("documentation_requirements", []):
        req     = item.get("requirement", "") if isinstance(item, dict) else item
        matched = any(_fuzzy_match(req.lower(), dt) for dt in doc_types)
        documentation_findings.append({
            "title":  req,
            "status": "pass" if matched else "fail",
            "detail": (
                "Document type present."
                if matched else
                "Required document type missing from indent."
            ),
        })

    return {
        "mandatory_findings":     mandatory_findings,
        "documentation_findings": documentation_findings,
        "risk_findings":          [],
        "vendor_findings":        [],
        "approval_findings":      [],
        "structure_findings":     [],
        "good_practice_findings": [
            {"title": p.get("practice", "") if isinstance(p, dict) else p,
             "status": "pass", "detail": ""}
            for p in good[:5]
        ],
        "weak_practice_findings": [
            {"title": w.get("issue", "") if isinstance(w, dict) else w,
             "status": "warning", "detail": ""}
            for w in weak[:5]
        ],
        "strengths":        [
            p.get("practice", "") if isinstance(p, dict) else p
            for p in good[:4]
        ],
        "gaps":             [
            f.get("title", "") for f in mandatory_findings
            if f["status"] == "fail"
        ][:5],
        "recommendations":  [r for r in recs if isinstance(r, str)][:5],
        "cross_doc_issues": [],
    }


def _fuzzy_match(needle: str, haystack: str) -> bool:
    stops = {"a", "an", "the", "in", "of", "for", "and", "or",
             "is", "are", "to", "with", "on", "at", "by", "be"}
    n = set(needle.lower().split()) - stops
    h = set(haystack.lower().split()) - stops
    if not n:
        return False
    return len(n & h) / len(n) >= 0.4
