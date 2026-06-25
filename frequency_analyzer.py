"""
frequency_analyzer.py  (v3.1)
──────────────────────────────
Added vs v3:
  - Counts document structure quality per doc type
  - Aggregates category_document_patterns across all indents
  - Passes both to standard_practice_generator
"""

from pathlib import Path
from collections import Counter, defaultdict

from src.storage import load_json, save_json


INDENT_LEVEL_DIR = Path("data/extracted_json/indent_level")
OUTPUT_DIR       = Path("data/outputs")

EXAMPLES_PER_CATEGORY = 1
MAX_TOTAL_EXAMPLES    = 10


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

    # Bonus for having structure analysis on documents
    structure_bonus = sum(
        1 for doc in data.get("documents", [])
        if doc.get("document_structure") is not None
    )

    return (good_count * 2) + field_bonus + confidence_bonus + structure_bonus - (weak_count * 1.5)


def _get_procurement_type(data: dict) -> str:
    ps = data.get("procurement_summary", {}) or {}
    pt = ps.get("procurement_type")
    if pt and isinstance(pt, str) and pt.strip():
        return pt.strip().split(" - ")[0].strip().title()
    return "Uncategorised"


def _summarize_indent(data: dict, indent_id: str) -> dict:
    ps = data.get("procurement_summary", {}) or {}
    ec = data.get("extraction_confidence", {}) or {}

    # Include structure quality summary per document
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
        "indent_id":              indent_id,
        "procurement_type":       ps.get("procurement_type"),
        "package_description":    ps.get("package_description"),
        "scope_of_work":          (ps.get("scope_of_work") or "")[:200],
        "estimated_cost":         ps.get("estimated_cost_crores"),
        "location":               ps.get("location"),
        "document_types":         ps.get("document_types_present", []),
        "missing_documents":      ps.get("missing_documents", []),
        "extraction_confidence":  ec.get("level"),
        "document_structures":    doc_structures,          # ← NEW
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


def analyze_frequencies() -> None:
    extraction_files = list(INDENT_LEVEL_DIR.glob("*_extraction.json"))
    print(f"Found {len(extraction_files)} indent extraction files")

    practice_counter         = Counter()
    weak_counter             = Counter()
    risk_counter             = Counter()
    document_type_counter    = Counter()
    procurement_type_counter = Counter()

    # ── NEW: structure quality counters ──────────────────────────────────────
    # structure_quality_counter[doc_type][quality] = count
    structure_quality_counter: dict = defaultdict(Counter)

    # ── NEW: category-document pattern aggregation ────────────────────────────
    # patterns[procurement_type][document_type] = list of pattern strings
    pattern_aggregator: dict = defaultdict(lambda: defaultdict(list))

    total_indents = 0
    by_category: dict = defaultdict(list)

    for extraction_file in extraction_files:
        data      = load_json(extraction_file)
        indent_id = data.get("indent_id", extraction_file.stem)
        total_indents += 1

        # Good practices
        for p in data.get("good_practices", []):
            text = p.get("practice", "") if isinstance(p, dict) else str(p)
            if text:
                practice_counter[text] += 1

        # Weak items
        for w in data.get("weak_items", []):
            text = w.get("issue", "") if isinstance(w, dict) else str(w)
            if text:
                weak_counter[text] += 1

        # Risk controls
        for rc in data.get("risk_controls", []):
            if isinstance(rc, dict):
                area = rc.get("risk_area", "")
                ctrl = rc.get("control", "")
                key  = f"{area}: {ctrl}" if area and ctrl else area or ctrl
                if key:
                    risk_counter[key] += 1

        # Document types
        ps = data.get("procurement_summary", {}) or {}
        for dt in ps.get("document_types_present", []):
            if dt:
                document_type_counter[dt] += 1

        # Procurement type
        ptype = _get_procurement_type(data)
        procurement_type_counter[ptype] += 1

        # ── NEW: structure quality per document type ──────────────────────────
        for doc in data.get("documents", []):
            doc_type = doc.get("document_type", "")
            ds       = doc.get("document_structure")
            if ds and isinstance(ds, dict):
                quality = ds.get("structure_quality")
                if quality and doc_type:
                    structure_quality_counter[doc_type][quality] += 1

        # ── NEW: category-document patterns ──────────────────────────────────
        for pattern in data.get("category_document_patterns", []):
            if not isinstance(pattern, dict):
                continue
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

        # Score for representative selection
        score = _score_indent(data)
        by_category[ptype].append((score, indent_id, data))

    # ── Frequency report ──────────────────────────────────────────────────────

    # Summarise structure quality: for each doc type, what % is well structured?
    structure_quality_summary = []
    for doc_type, quality_counts in structure_quality_counter.items():
        total = sum(quality_counts.values())
        structure_quality_summary.append({
            "document_type":      doc_type,
            "total_analysed":     total,
            "well_structured":    quality_counts.get("Well structured", 0),
            "partially_structured": quality_counts.get("Partially structured", 0),
            "unstructured":       quality_counts.get("Unstructured", 0),
        })

    # Summarise category-document patterns: most common pattern per type/doc combo
    category_doc_pattern_summary = []
    for ptype, doc_patterns in pattern_aggregator.items():
        for doc_type, patterns in doc_patterns.items():
            # Keep up to 3 representative patterns for this combo
            sampled = patterns[:3]
            category_doc_pattern_summary.append({
                "procurement_type":  ptype,
                "document_type":     doc_type,
                "occurrence_count":  len(patterns),
                "sample_patterns":   [p["pattern"] for p in sampled],
                "sample_recommendations": [
                    p["recommendation"] for p in sampled
                    if p.get("recommendation")
                ],
            })

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
        "weak_item_frequency": [
            {"issue": k, "count": v}
            for k, v in weak_counter.most_common()
        ],
        "risk_control_frequency": [
            {"control": k, "count": v}
            for k, v in risk_counter.most_common()
        ],
        "structure_quality_frequency":    structure_quality_summary,      # ← NEW
        "category_document_patterns":     category_doc_pattern_summary,   # ← NEW
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    save_json(report, OUTPUT_DIR / "practice_frequency_report.json")

    print(f"\nFrequency report saved: {total_indents} indents")
    print(f"  Procurement types       : {len(procurement_type_counter)}")
    print(f"  Good practices          : {len(practice_counter)}")
    print(f"  Weak items              : {len(weak_counter)}")
    print(f"  Risk controls           : {len(risk_counter)}")
    print(f"  Document types          : {len(document_type_counter)}")
    print(f"  Structure quality rows  : {len(structure_quality_summary)}")
    print(f"  Category-doc patterns   : {len(category_doc_pattern_summary)}")

    # ── Representative examples ───────────────────────────────────────────────
    best_examples  = []
    worst_examples = []

    sorted_categories = sorted(
        by_category.items(),
        key=lambda x: -len(x[1])
    )

    for category, indents in sorted_categories:
        if len(best_examples) >= MAX_TOTAL_EXAMPLES // 2:
            break
        indents_sorted = sorted(indents, key=lambda x: -x[0])
        best           = indents_sorted[0]
        worst          = indents_sorted[-1]

        best_examples.append(_summarize_indent(best[2], best[1]))
        if worst[1] != best[1]:
            worst_examples.append(_summarize_indent(worst[2], worst[1]))

    representative = {
        "selection_method": (
            "Best and worst per procurement_type category. "
            "Score = (good*2) + field_bonus + confidence_bonus "
            "+ structure_bonus - (weak*1.5)"
        ),
        "categories_found":              list(procurement_type_counter.keys()),
        "representative_best_examples":  best_examples,
        "representative_worst_examples": worst_examples,
    }

    save_json(representative, OUTPUT_DIR / "representative_examples.json")

    print(f"\nRepresentative examples saved:")
    print(f"  Categories : {list(procurement_type_counter.keys())}")
    print(f"  Best       : {[e['indent_id'] for e in best_examples]}")
    print(f"  Worst      : {[e['indent_id'] for e in worst_examples]}")


if __name__ == "__main__":
    analyze_frequencies()