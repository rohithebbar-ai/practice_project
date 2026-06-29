"""
frequency_analyzer.py  (v5)
────────────────────────────
Reads from:  pipeline_outputs/03_extractions/
Writes to:   pipeline_outputs/04_frequency/

Changes from v4:
  - Counts null/missing key fields as common weaknesses
    (absence of data is a signal, not just presence of bad practices)
  - Threshold: field missing in >30% of indents → flagged as weakness
"""

from pathlib import Path
from collections import Counter, defaultdict

from src.storage import load_json, save_json
from src.pipeline_paths import PATHS


EXAMPLES_PER_CATEGORY = 1
MAX_TOTAL_EXAMPLES    = 10

# ── Fields to monitor for null values ────────────────────────────────────────
# If a field is null in more than NULL_THRESHOLD of indents,
# it becomes a common weakness in the standard.

NULL_THRESHOLD = 0.30  # 30% of indents

KEY_FIELDS_TO_MONITOR = {
    "estimated_cost_crores":   "Estimated cost not documented",
    "scope_of_work":           "Scope of work not clearly defined",
    "vendor_panel":            "Vendor panel not documented",
    "hse_plan_available":      "HSE plan status not recorded",
    "technical_spec_attached": "Technical specification attachment status missing",
    "boq_surplus_checked":     "BOQ surplus check not recorded",
    "approval_authority":      "Approval authority not defined",
    "indent_approval_date":    "Approval date not recorded",
    "job_risk_category":       "Job risk category not specified",
    "is_single_party":         "Single party status not documented",
    "order_required_date":     "Order required date not specified",
    "term_sheet_type":         "Term sheet type not specified",
    "contract_period_months":  "Contract period not specified",
}


def _score_indent(data: dict) -> float:
    good_count = len(data.get("good_practices", []))
    weak_count = len(data.get("weak_items", []))
    ps         = data.get("procurement_summary", {}) or {}

    field_bonus = sum(1 for field in [
        "scope_of_work", "estimated_cost_crores", "vendor_panel",
        "technical_spec_attached", "hse_plan_available",
        "approval_authority", "indent_approval_date",
        "term_sheet_type", "boq_surplus_checked", "procurement_type",
    ] if ps.get(field) not in (None, "", "null"))

    ec = data.get("extraction_confidence", {}) or {}
    confidence_bonus = {"High": 2, "Medium": 1, "Low": 0}.get(
        ec.get("level", ""), 0
    )
    structure_bonus = sum(
        1 for doc in data.get("documents", [])
        if doc.get("document_structure") is not None
    )
    return (
        (good_count * 2) + field_bonus + confidence_bonus +
        structure_bonus - (weak_count * 1.5)
    )


def _get_procurement_type(data: dict) -> str:
    ps = data.get("procurement_summary", {}) or {}
    pt = ps.get("procurement_type") or ps.get("procurment_type")
    if pt and isinstance(pt, str) and pt.strip():
        return pt.strip().split(" - ")[0].strip().title()
    return "Uncategorised"


def _summarize_indent(data: dict, indent_id: str) -> dict:
    ps  = data.get("procurement_summary", {}) or {}
    ec  = data.get("extraction_confidence", {}) or {}
    doc_structures = []
    for doc in data.get("documents", []):
        ds = doc.get("document_structure")
        if ds:
            doc_structures.append({
                "document_type":     doc.get("document_type"),
                "structure_quality": ds.get("structure_quality"),
                "sections_found":    ds.get("sections_found", [])[:5],
                "notable_pattern":   ds.get("notable_pattern"),
            })
    return {
        "indent_id":             indent_id,
        "procurement_type":      ps.get("procurement_type") or
                                 ps.get("procurment_type"),
        "package_description":   ps.get("package_description"),
        "scope_of_work":         (ps.get("scope_of_work") or "")[:200],
        "estimated_cost":        ps.get("estimated_cost_crores"),
        "location":              ps.get("location"),
        "document_types":        ps.get("document_types_present", []),
        "missing_documents":     ps.get("missing_documents", []),
        "extraction_confidence": ec.get("level"),
        "document_structures":   doc_structures,
        "good_practices": [
            (p.get("practice") if isinstance(p, dict) else p)
            for p in data.get("good_practices", [])
        ][:4],
        "weak_items": [
            (w.get("issue") if isinstance(w, dict) else w)
            for w in data.get("weak_items", [])
        ][:4],
        "risk_controls": [
            f"{rc.get('risk_area','')}: {rc.get('control','')}"
            if isinstance(rc, dict) else rc
            for rc in data.get("risk_controls", [])
        ][:3],
        "recommendations": data.get("recommendations", [])[:3],
    }


def _count_null_fields(
    all_data: list,
    total_indents: int,
) -> list:
    """
    Count how many indents have null/missing values for key fields.
    Returns list of weak_item entries for fields missing in many indents.

    This turns absence of data into a signal — if 64% of indents
    have no estimated cost, the standard should flag this.
    """
    null_counts = {field: 0 for field in KEY_FIELDS_TO_MONITOR}

    for data in all_data:
        ps = data.get("procurement_summary", {}) or {}
        for field in KEY_FIELDS_TO_MONITOR:
            val = ps.get(field)
            if not val or str(val).lower() in (
                "null", "none", "", "not found", "na"
            ):
                null_counts[field] += 1

    null_weaknesses = []
    for field, count in null_counts.items():
        if total_indents == 0:
            continue
        pct = count / total_indents
        if pct >= NULL_THRESHOLD:
            null_weaknesses.append({
                "issue": (
                    f"{KEY_FIELDS_TO_MONITOR[field]} "
                    f"(absent in {count}/{total_indents} indents, "
                    f"{pct*100:.0f}%)"
                ),
                "count": count,
            })

    # Sort by most missing first
    null_weaknesses.sort(key=lambda x: -x["count"])
    return null_weaknesses


def analyze_frequencies() -> None:
    PATHS.ensure_all()

    resolved = PATHS.extractions.resolve()
    print(f"Looking in: {resolved}")

    if not PATHS.extractions.exists():
        print(f"[ERROR] Directory does not exist: {resolved}")
        return

    extraction_files = list(PATHS.extractions.rglob("*_extraction.json"))
    print(f"Found {len(extraction_files)} indent extraction files")

    if len(extraction_files) == 0:
        all_files = list(PATHS.extractions.rglob("*"))
        print(f"  Files in directory: {len(all_files)}")
        for f in all_files[:10]:
            print(f"    {f}")
        return

    for f in extraction_files:
        print(f"  Processing: {f.name}")

    practice_counter         = Counter()
    weak_counter             = Counter()
    risk_counter             = Counter()
    document_type_counter    = Counter()
    procurement_type_counter = Counter()
    structure_quality_counter: dict = defaultdict(Counter)
    pattern_aggregator: dict = defaultdict(lambda: defaultdict(list))

    total_indents  = 0
    by_category: dict = defaultdict(list)
    all_valid_data: list = []  # for null field analysis

    for extraction_file in extraction_files:
        try:
            data = load_json(extraction_file)
        except Exception as e:
            print(f"  [SKIP] Failed to load {extraction_file.name}: {e}")
            continue

        indent_id = data.get("indent_id", extraction_file.stem)
        ps        = data.get("procurement_summary", {}) or {}
        docs      = data.get("documents", [])

        has_content = any([
            ps.get("scope_of_work"),
            ps.get("package_description"),
            any(d.get("document_summary") for d in docs),
            len(data.get("good_practices", [])) > 0,
        ])
        if not has_content:
            print(f"  [SKIP] {indent_id} — empty extraction")
            continue

        total_indents += 1
        all_valid_data.append(data)

        for p in data.get("good_practices", []):
            text = p.get("practice", "") if isinstance(p, dict) else str(p)
            if text: practice_counter[text] += 1

        for w in data.get("weak_items", []):
            text = w.get("issue", "") if isinstance(w, dict) else str(w)
            if text: weak_counter[text] += 1

        for rc in data.get("risk_controls", []):
            if isinstance(rc, dict):
                area = rc.get("risk_area", "")
                ctrl = rc.get("control", "")
                key  = f"{area}: {ctrl}" if area and ctrl else area or ctrl
                if key: risk_counter[key] += 1

        for dt in ps.get("document_types_present", []):
            if dt: document_type_counter[dt] += 1

        ptype = _get_procurement_type(data)
        procurement_type_counter[ptype] += 1

        for doc in data.get("documents", []):
            doc_type = doc.get("document_type", "")
            ds       = doc.get("document_structure")
            if ds and isinstance(ds, dict):
                quality = ds.get("structure_quality")
                if quality and doc_type:
                    structure_quality_counter[doc_type][quality] += 1

        for pattern in data.get("category_document_patterns", []):
            if not isinstance(pattern, dict): continue
            pt       = pattern.get("procurement_type", "")
            dt       = pattern.get("document_type", "")
            observed = pattern.get("pattern_observed", "")
            if pt and dt and observed:
                pattern_aggregator[pt][dt].append({
                    "pattern":        observed,
                    "quality":        pattern.get("quality_assessment"),
                    "recommendation": pattern.get("recommendation"),
                    "indent_id":      indent_id,
                })

        score = _score_indent(data)
        by_category[ptype].append((score, indent_id, data))

    if total_indents == 0:
        print("[WARN] No valid indent extractions found.")
        return

    structure_quality_summary = [
        {
            "document_type":        doc_type,
            "total_analysed":       sum(qc.values()),
            "well_structured":      qc.get("Well structured", 0),
            "partially_structured": qc.get("Partially structured", 0),
            "unstructured":         qc.get("Unstructured", 0),
        }
        for doc_type, qc in structure_quality_counter.items()
    ]

    category_doc_pattern_summary = []
    for ptype, doc_patterns in pattern_aggregator.items():
        for doc_type, patterns in doc_patterns.items():
            sampled = patterns[:3]
            category_doc_pattern_summary.append({
                "procurement_type":       ptype,
                "document_type":          doc_type,
                "occurrence_count":       len(patterns),
                "sample_patterns":        [p["pattern"] for p in sampled],
                "sample_recommendations": [
                    p["recommendation"] for p in sampled
                    if p.get("recommendation")
                ],
            })

    # ── Existing weak items from LLM extraction ───────────────────────────────
    existing_weak = [
        {"issue": k, "count": v}
        for k, v in weak_counter.most_common()
    ]

    # ── Null field weaknesses ─────────────────────────────────────────────────
    # These are fields missing in many indents — absence of data is a signal
    null_weak = _count_null_fields(all_valid_data, total_indents)

    if null_weak:
        print(f"\n  [NULL FIELDS] Found {len(null_weak)} fields missing "
              f"in >{NULL_THRESHOLD*100:.0f}% of indents:")
        for nw in null_weak:
            print(f"    - {nw['issue']}")

    # Merge: LLM-detected weak items first, then null field weaknesses
    combined_weak = existing_weak + null_weak

    report = {
        "total_indents": total_indents,
        "procurement_type_breakdown": [
            {"procurement_type": k, "count": v}
            for k, v in procurement_type_counter.most_common()
        ],
        "document_type_frequency": [
            {"document_type": k, "count": v}
            for k, v in document_type_counter.most_common()
        ],
        "good_practice_frequency": [
            {"practice": k, "count": v}
            for k, v in practice_counter.most_common()
        ],
        "weak_item_frequency":        combined_weak,
        "risk_control_frequency": [
            {"control": k, "count": v}
            for k, v in risk_counter.most_common()
        ],
        "structure_quality_frequency":  structure_quality_summary,
        "category_document_patterns":   category_doc_pattern_summary,
        "null_field_analysis": null_weak,  # separate key for visibility
    }

    save_json(report, PATHS.frequency_report)

    print(f"\nFrequency report saved → {PATHS.frequency_report}")
    print(f"  Total indents         : {total_indents}")
    print(f"  Procurement types     : {len(procurement_type_counter)}")
    print(f"  Good practices        : {len(practice_counter)}")
    print(f"  Weak items (LLM)      : {len(existing_weak)}")
    print(f"  Weak items (null)     : {len(null_weak)}")
    print(f"  Risk controls         : {len(risk_counter)}")
    print(f"  Document types        : {len(document_type_counter)}")
    print(f"  Structure quality rows: {len(structure_quality_summary)}")
    print(f"  Category-doc patterns : {len(category_doc_pattern_summary)}")

    # Representative examples
    best_examples  = []
    worst_examples = []
    for category, indents in sorted(
        by_category.items(), key=lambda x: -len(x[1])
    ):
        if len(best_examples) >= MAX_TOTAL_EXAMPLES // 2:
            break
        indents_sorted = sorted(indents, key=lambda x: -x[0])
        best           = indents_sorted[0]
        worst          = indents_sorted[-1]
        best_examples.append(_summarize_indent(best[2], best[1]))
        if worst[1] != best[1]:
            worst_examples.append(_summarize_indent(worst[2], worst[1]))

    representative = {
        "selection_method":              "Best and worst per procurement_type category",
        "categories_found":              list(procurement_type_counter.keys()),
        "representative_best_examples":  best_examples,
        "representative_worst_examples": worst_examples,
    }
    save_json(representative, PATHS.representative_examples)

    print(f"\nRepresentative examples saved → {PATHS.representative_examples}")
    print(f"  Categories : {list(procurement_type_counter.keys())}")
    print(f"  Best       : {[e['indent_id'] for e in best_examples]}")
    print(f"  Worst      : {[e['indent_id'] for e in worst_examples]}")


if __name__ == "__main__":
    analyze_frequencies()
