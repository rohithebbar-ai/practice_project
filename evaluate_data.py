"""
evaluate_extraction.py
───────────────────────
Evaluates extraction quality across all parsed documents.

Reads from:
  pipeline_outputs/01_parsed/     ← what the parser produced
  pipeline_outputs/03_extractions/ ← what the LLM extracted

Produces a quality report showing:
  - Which files parsed well vs poorly
  - Which indents have good/bad extraction
  - Field completion rates
  - Common failure patterns

Run:
  python evaluate_extraction.py
  python evaluate_extraction.py --indent "indent_id"  (single indent)
  python evaluate_extraction.py --csv                  (export to CSV)
"""

import json
import sys
import argparse
from pathlib import Path
from collections import defaultdict


# ── Config ────────────────────────────────────────────────────────────────────
PIPELINE_ROOT  = Path("pipeline_outputs")
PARSED_DIR     = PIPELINE_ROOT / "01_parsed"
EXTRACTIONS_DIR = PIPELINE_ROOT / "03_extractions"

# Key fields we expect to be populated in a good extraction
KEY_FIELDS = [
    "procurement_type",
    "package_description",
    "scope_of_work",
    "location",
    "estimated_cost_crores",
    "order_required_date",
    "job_risk_category",
    "vendor_panel",
    "hse_plan_available",
    "technical_spec_attached",
    "approval_authority",
    "indent_approval_date",
]

# Fields that must NEVER contain wrong values
VALIDATED_FIELDS = {
    "hse_plan_available":    ["yes", "no", "na", "attached", "not attached",
                               "available", "not available"],
    "boq_surplus_checked":   ["yes", "no", "na", "checked"],
    "is_single_party":       ["yes", "no", "na"],
    "technical_spec_attached": ["yes", "no", "na", "attached"],
}


def _pct(count, total):
    if total == 0:
        return "0%"
    return f"{count/total*100:.0f}%"


def evaluate_parsed_file(txt_path: Path) -> dict:
    """
    Evaluate quality of a single parsed text file.
    Returns dict with quality signals.
    """
    try:
        text = txt_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return {"status": "error", "error": str(e), "path": str(txt_path)}

    char_count  = len(text)
    line_count  = len(text.splitlines())
    word_count  = len(text.split())

    # Quality signals
    is_empty        = char_count < 50
    is_very_short   = char_count < 200
    has_garbled     = _check_garbled(text)
    has_sidebar_noise = _check_sidebar_noise(text)
    extraction_type = _guess_extraction_type(txt_path.name)

    # Score 0-100
    score = 100
    if is_empty:        score = 0
    elif is_very_short: score -= 40
    if has_garbled:     score -= 30
    if has_sidebar_noise: score -= 10

    return {
        "status":             "ok" if not is_empty else "empty",
        "file":               txt_path.name,
        "chars":              char_count,
        "lines":              line_count,
        "words":              word_count,
        "is_empty":           is_empty,
        "is_very_short":      is_very_short,
        "has_garbled_text":   has_garbled,
        "has_sidebar_noise":  has_sidebar_noise,
        "extraction_type":    extraction_type,
        "quality_score":      max(0, score),
    }


def _check_garbled(text: str) -> bool:
    """Check for signs of OCR garbling or encoding issues."""
    # High ratio of non-ASCII or replacement characters
    non_ascii = sum(1 for c in text if ord(c) > 127)
    if len(text) > 0 and non_ascii / len(text) > 0.15:
        return True
    # Common OCR garbling patterns
    garble_patterns = ["â€™", "â€œ", "Ã©", "ï¿½", "\ufffd"]
    return any(p in text for p in garble_patterns)


def _check_sidebar_noise(text: str) -> bool:
    """Check if Procurement Tracker sidebar noise is present."""
    sidebar_signals = [
        "procurement hierarchy",
        "dashboard",
        "tslist",
        "auto grn",
        "(profile)",
    ]
    lower = text[:2000].lower()
    hits  = sum(1 for s in sidebar_signals if s in lower)
    return hits >= 2


def _guess_extraction_type(filename: str) -> str:
    """Guess how this file was originally parsed."""
    name = filename.lower()
    if name.endswith(".pdf.txt"):
        return "pdf"
    if any(name.endswith(f".{ext}.txt") for ext in
           ["xlsx", "xls", "xlsm", "xlsb"]):
        return "excel"
    if name.endswith(".docx.txt") or name.endswith(".doc.txt"):
        return "docx"
    return "unknown"


def evaluate_extraction(extraction_path: Path) -> dict:
    """
    Evaluate quality of a single indent extraction JSON.
    """
    try:
        data = json.loads(
            extraction_path.read_text(encoding="utf-8")
        )
    except Exception as e:
        return {
            "indent_id": extraction_path.stem,
            "status":    "parse_error",
            "error":     str(e),
        }

    indent_id = data.get("indent_id", extraction_path.stem)
    ps        = data.get("procurement_summary", {}) or {}
    docs      = data.get("documents", []) or []
    ec        = data.get("extraction_confidence", {}) or {}

    # ── Field completion ──────────────────────────────────────────────────────
    populated   = []
    missing     = []
    wrong_value = []

    for field in KEY_FIELDS:
        val = ps.get(field)
        if val and str(val).lower() not in ("null", "none", ""):
            populated.append(field)
        else:
            missing.append(field)

    # ── Validated field check ─────────────────────────────────────────────────
    for field, valid_values in VALIDATED_FIELDS.items():
        val = ps.get(field)
        if val and str(val).lower() not in ("null", "none", ""):
            val_lower = str(val).lower()
            if not any(v in val_lower for v in valid_values):
                wrong_value.append({
                    "field": field,
                    "value": val,
                    "expected": valid_values,
                })

    # ── Document quality ──────────────────────────────────────────────────────
    doc_quality = []
    for doc in docs:
        ds = doc.get("document_structure", {}) or {}
        doc_quality.append({
            "name":    doc.get("document_name", ""),
            "type":    doc.get("document_type", ""),
            "quality": ds.get("structure_quality", "Unknown"),
            "has_summary": bool(doc.get("document_summary", "").strip()),
            "good_practices": len(doc.get("good_practices_observed", [])),
            "weak_items":     len(doc.get("weak_or_missing_items", [])),
        })

    # ── Scoring ───────────────────────────────────────────────────────────────
    completion_rate = len(populated) / len(KEY_FIELDS) if KEY_FIELDS else 0
    has_content     = bool(
        ps.get("scope_of_work") or
        ps.get("package_description") or
        len(docs) > 0
    )

    score = int(completion_rate * 100)
    if wrong_value:  score -= len(wrong_value) * 10
    if not has_content: score = 0
    score = max(0, min(100, score))

    if score >= 80:   quality_grade = "Good"
    elif score >= 50: quality_grade = "Partial"
    else:             quality_grade = "Poor"

    return {
        "indent_id":          indent_id,
        "status":             "ok" if has_content else "empty",
        "quality_grade":      quality_grade,
        "quality_score":      score,
        "procurement_type":   ps.get("procurement_type", "—"),
        "confidence":         ec.get("level", "—"),
        "fields_populated":   len(populated),
        "fields_missing":     len(missing),
        "fields_total":       len(KEY_FIELDS),
        "completion_pct":     _pct(len(populated), len(KEY_FIELDS)),
        "wrong_value_fields": wrong_value,
        "missing_fields":     missing,
        "doc_count":          len(docs),
        "doc_quality":        doc_quality,
        "good_practices":     len(data.get("good_practices", [])),
        "weak_items":         len(data.get("weak_items", [])),
    }


def print_separator(char="─", width=70):
    print(char * width)


def run_evaluation(indent_filter=None, export_csv=False):
    print("\n" + "═" * 70)
    print("  EXTRACTION QUALITY EVALUATION")
    print("═" * 70)

    # ── 1. Parsed file quality ────────────────────────────────────────────────
    print("\n📄 PARSED FILE QUALITY")
    print_separator()

    txt_files    = list(PARSED_DIR.rglob("*.txt"))
    file_results = []
    empty_files  = []
    garbled_files = []
    sidebar_files = []

    type_stats = defaultdict(lambda: {"count": 0, "total_chars": 0,
                                       "empty": 0, "garbled": 0})

    for txt_path in sorted(txt_files):
        if indent_filter and indent_filter not in str(txt_path):
            continue
        result = evaluate_parsed_file(txt_path)
        file_results.append(result)

        ext_type = result.get("extraction_type", "unknown")
        type_stats[ext_type]["count"] += 1
        type_stats[ext_type]["total_chars"] += result.get("chars", 0)

        if result.get("is_empty"):
            empty_files.append(txt_path.name)
            type_stats[ext_type]["empty"] += 1
        if result.get("has_garbled_text"):
            garbled_files.append(txt_path.name)
            type_stats[ext_type]["garbled"] += 1
        if result.get("has_sidebar_noise"):
            sidebar_files.append(txt_path.name)

    total_files = len(file_results)
    print(f"Total parsed files : {total_files}")
    print(f"Empty files        : {len(empty_files)}")
    print(f"Garbled text files : {len(garbled_files)}")
    print(f"Sidebar noise files: {len(sidebar_files)}")
    print()

    print("By file type:")
    for ftype, stats in sorted(type_stats.items()):
        avg_chars = (stats["total_chars"] // stats["count"]
                     if stats["count"] else 0)
        print(f"  {ftype:10s} : {stats['count']:3d} files | "
              f"avg {avg_chars:,} chars | "
              f"{stats['empty']} empty | "
              f"{stats['garbled']} garbled")

    if empty_files:
        print("\n⚠️  Empty files (check parser):")
        for f in empty_files[:10]:
            print(f"   {f}")

    if garbled_files:
        print("\n⚠️  Garbled text (OCR quality issue):")
        for f in garbled_files[:10]:
            print(f"   {f}")

    # ── 2. Extraction quality ─────────────────────────────────────────────────
    print("\n\n🔍 EXTRACTION QUALITY (LLM OUTPUT)")
    print_separator()

    extraction_files = list(EXTRACTIONS_DIR.rglob("*_extraction.json"))
    if indent_filter:
        extraction_files = [
            f for f in extraction_files if indent_filter in f.stem
        ]

    ext_results   = []
    good_count    = 0
    partial_count = 0
    poor_count    = 0
    wrong_fields  = defaultdict(list)

    for ext_path in sorted(extraction_files):
        result = evaluate_extraction(ext_path)
        ext_results.append(result)

        grade = result.get("quality_grade", "Poor")
        if grade == "Good":    good_count    += 1
        elif grade == "Partial": partial_count += 1
        else:                  poor_count    += 1

        for wv in result.get("wrong_value_fields", []):
            wrong_fields[wv["field"]].append({
                "indent": result["indent_id"],
                "value":  wv["value"],
            })

    total_ext = len(ext_results)
    print(f"Total extractions : {total_ext}")
    print(f"  Good    (≥80%) : {good_count} "
          f"({_pct(good_count, total_ext)})")
    print(f"  Partial (50-79%): {partial_count} "
          f"({_pct(partial_count, total_ext)})")
    print(f"  Poor    (<50%) : {poor_count} "
          f"({_pct(poor_count, total_ext)})")

    # ── 3. Field completion rates ─────────────────────────────────────────────
    print("\n\n📊 FIELD COMPLETION RATES")
    print_separator()

    field_counts = defaultdict(int)
    for result in ext_results:
        populated = set(KEY_FIELDS) - set(result.get("missing_fields", []))
        for f in populated:
            field_counts[f] += 1

    print(f"{'Field':<35} {'Populated':>10} {'Rate':>8}")
    print_separator("-")
    for field in KEY_FIELDS:
        count = field_counts[field]
        rate  = _pct(count, total_ext)
        bar   = "█" * int(count / max(total_ext, 1) * 20)
        flag  = " ⚠️" if count / max(total_ext, 1) < 0.5 else ""
        print(f"  {field:<33} {count:>5}/{total_ext:<5} {rate:>6}{flag}")

    # ── 4. Wrong value fields ─────────────────────────────────────────────────
    if wrong_fields:
        print("\n\n❌ WRONG VALUES IN VALIDATED FIELDS")
        print_separator()
        print("These fields had values that don't match expected format:")
        for field, occurrences in wrong_fields.items():
            print(f"\n  Field: {field}")
            for occ in occurrences[:5]:
                print(f"    Indent: {occ['indent']}")
                print(f"    Value:  {occ['value'][:80]}")

    # ── 5. Per-indent detail ──────────────────────────────────────────────────
    print("\n\n📋 PER-INDENT EXTRACTION SUMMARY")
    print_separator()
    print(f"{'Indent ID':<40} {'Grade':<10} {'Score':>6} "
          f"{'Fields':>8} {'Conf':<10} {'Type'}")
    print_separator("-")

    for result in sorted(ext_results,
                         key=lambda x: x.get("quality_score", 0)):
        indent_id = result["indent_id"][:38]
        grade     = result.get("quality_grade", "?")
        score     = result.get("quality_score", 0)
        fields    = (f"{result.get('fields_populated',0)}/"
                     f"{result.get('fields_total',0)}")
        conf      = result.get("confidence", "—")[:8]
        ptype     = result.get("procurement_type", "—")[:30]

        flag = ""
        if grade == "Poor":    flag = " ← needs attention"
        elif result.get("wrong_value_fields"): flag = " ← wrong fields"

        print(f"  {indent_id:<40} {grade:<10} {score:>5}% "
              f"{fields:>8} {conf:<10} {ptype}{flag}")

    # ── 6. Document structure summary ────────────────────────────────────────
    print("\n\n🏗  DOCUMENT STRUCTURE QUALITY")
    print_separator()

    doc_type_quality = defaultdict(lambda: {"well": 0, "partial": 0,
                                             "unstructured": 0, "total": 0})
    for result in ext_results:
        for doc in result.get("doc_quality", []):
            dt      = doc.get("type", "Unknown")
            quality = doc.get("quality", "Unknown")
            doc_type_quality[dt]["total"] += 1
            if quality == "Well structured":
                doc_type_quality[dt]["well"] += 1
            elif quality == "Partially structured":
                doc_type_quality[dt]["partial"] += 1
            elif quality == "Unstructured":
                doc_type_quality[dt]["unstructured"] += 1

    print(f"{'Document Type':<35} {'Well':>6} {'Partial':>8} "
          f"{'Unstruct':>10} {'Total':>7}")
    print_separator("-")
    for dt, counts in sorted(doc_type_quality.items(),
                              key=lambda x: -x[1]["total"]):
        total = counts["total"]
        print(f"  {dt:<33} "
              f"{counts['well']:>5} ({_pct(counts['well'],total):>4}) "
              f"{counts['partial']:>5} ({_pct(counts['partial'],total):>4}) "
              f"{counts['unstructured']:>5} ({_pct(counts['unstructured'],total):>4}) "
              f"{total:>5}")

    # ── 7. CSV export ─────────────────────────────────────────────────────────
    if export_csv:
        import csv
        csv_path = Path("extraction_quality_report.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "indent_id", "quality_grade", "quality_score",
                "procurement_type", "confidence",
                "fields_populated", "fields_missing", "fields_total",
                "completion_pct", "doc_count",
                "good_practices", "weak_items",
                "wrong_value_count",
            ])
            writer.writeheader()
            for result in ext_results:
                writer.writerow({
                    "indent_id":         result["indent_id"],
                    "quality_grade":     result.get("quality_grade", ""),
                    "quality_score":     result.get("quality_score", 0),
                    "procurement_type":  result.get("procurement_type", ""),
                    "confidence":        result.get("confidence", ""),
                    "fields_populated":  result.get("fields_populated", 0),
                    "fields_missing":    result.get("fields_missing", 0),
                    "fields_total":      result.get("fields_total", 0),
                    "completion_pct":    result.get("completion_pct", ""),
                    "doc_count":         result.get("doc_count", 0),
                    "good_practices":    result.get("good_practices", 0),
                    "weak_items":        result.get("weak_items", 0),
                    "wrong_value_count": len(
                        result.get("wrong_value_fields", [])
                    ),
                })
        print(f"\nCSV exported → {csv_path}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n\n" + "═" * 70)
    print("  SUMMARY")
    print("═" * 70)
    avg_score = (
        sum(r.get("quality_score", 0) for r in ext_results) / total_ext
        if total_ext else 0
    )
    print(f"  Parsed files     : {total_files} "
          f"({len(empty_files)} empty, {len(garbled_files)} garbled)")
    print(f"  Extractions      : {total_ext} "
          f"({good_count} good, {partial_count} partial, {poor_count} poor)")
    print(f"  Avg quality score: {avg_score:.0f}%")
    print(f"  Wrong value fields found: "
          f"{sum(len(r.get('wrong_value_fields',[])) for r in ext_results)}")
    print("═" * 70 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Evaluate extraction quality"
    )
    parser.add_argument(
        "--indent", help="Filter to a specific indent ID"
    )
    parser.add_argument(
        "--csv", action="store_true",
        help="Export results to CSV"
    )
    args = parser.parse_args()
    run_evaluation(indent_filter=args.indent, export_csv=args.csv)
