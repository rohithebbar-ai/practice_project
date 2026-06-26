"""
run_pipeline.py  (v5)
──────────────────────
All outputs go to pipeline_outputs/ — one folder, clear structure.

pipeline_outputs/
├── 01_parsed/           ← Step 1 output
├── 01_parsed_metadata/  ← Step 1 metadata
├── 02_cleaned/          ← Step 2 cleaned text (for inspection)
├── 03_extractions/      ← Step 2 LLM output — one JSON per indent
├── 04_frequency/        ← Step 3 frequency report + examples
├── 05_standard/         ← Step 4 best_practice_standard.json
└── logs/                ← error logs

Changes from v4:
  - Steps 3 & 4 only run when ALL indents are processed
  - Dynamically counts expected indents from data/raw/
  - No hardcoded numbers — works for any dataset size
"""

from pathlib import Path

from src.pipeline_parse import parse_raw_documents
from src.pipeline_analyze import analyze_parsed_documents
from src.frequency_analyzer import analyze_frequencies
from src.standard_practice_generator import generate_standard
from src.pipeline_paths import PATHS
from src.storage import load_json

# ── Raw data directory ────────────────────────────────────────────────────────
RAW_DIR = Path("data/raw")

# ── Supported file extensions (must match pipeline_parse.py) ─────────────────
SUPPORTED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".xlsm", ".docx", ".txt"}


def count_total_indent_folders() -> int:
    """
    Count how many indent folders exist in data/raw/
    that contain at least one supported file.
    Works for any dataset — civil, electromechanical, or any other.
    """
    if not RAW_DIR.exists():
        print(f"  [WARN] data/raw/ not found at {RAW_DIR.resolve()}")
        return 0

    count = 0
    for folder in RAW_DIR.iterdir():
        if not folder.is_dir():
            continue
        has_supported_files = any(
            f.suffix.lower() in SUPPORTED_EXTENSIONS
            for f in folder.rglob("*")
            if f.is_file()
        )
        if has_supported_files:
            count += 1
    return count


def count_valid_extractions() -> int:
    """
    Count how many valid (non-empty) extraction JSONs exist
    in pipeline_outputs/03_extractions/.
    An extraction is valid if it has at least one meaningful field.
    """
    if not PATHS.extractions.exists():
        return 0

    extraction_files = list(PATHS.extractions.rglob("*_extraction.json"))
    valid = 0

    for f in extraction_files:
        try:
            data = load_json(f)
            ps   = data.get("procurement_summary", {}) or {}
            docs = data.get("documents", []) or []

            has_content = any([
                ps.get("procurement_type"),
                ps.get("scope_of_work"),
                ps.get("package_description"),
                ps.get("document_types_present"),
                len(docs) > 0,
                len(data.get("good_practices", [])) > 0,
            ])
            if has_content:
                valid += 1
        except Exception:
            pass

    return valid


def main() -> None:
    print("\n" + "=" * 60)
    print("Civil Indent Practice Pipeline  (v5)")
    print(f"All outputs → {PATHS.parsed.parent.resolve()}")
    print("=" * 60 + "\n")

    # ── Step 1: Parse raw documents ───────────────────────────────────────────
    print("=" * 60)
    print("Step 1: Parsing raw documents")
    print("=" * 60)
    parse_raw_documents()

    # ── Step 2: Analyse documents (MAX_BATCH controls how many run) ───────────
    print("\n" + "=" * 60)
    print("Step 2: Analysing documents (1 LLM call per indent)")
    print("=" * 60)
    analyze_parsed_documents()

    # ── Check progress ────────────────────────────────────────────────────────
    total_indents  = count_total_indent_folders()
    valid_extractions = count_valid_extractions()

    print(f"\n{'=' * 60}")
    print(f"Progress Check")
    print(f"{'=' * 60}")
    print(f"  Total indent folders in data/raw/ : {total_indents}")
    print(f"  Valid extractions so far          : {valid_extractions}")
    print(f"  Remaining                         : {total_indents - valid_extractions}")

    # ── Only run Steps 3 & 4 when ALL indents are processed ──────────────────
    if valid_extractions < total_indents:
        remaining = total_indents - valid_extractions
        print(f"\n  [SKIP] Steps 3 & 4 — only {valid_extractions}/{total_indents} indents done.")
        print(f"  {remaining} indent(s) still need processing.")
        print(f"  Rerun the pipeline to process the next batch.")
        print(f"  Steps 3 & 4 will run automatically once all {total_indents} are ready.")
        print(f"\n{'=' * 60}")
        print(f"Pipeline paused — batch complete.")
        print(f"{'=' * 60}")
        return

    # ── All indents processed — run Steps 3 & 4 ──────────────────────────────
    print(f"\n All {total_indents} indents processed!")
    print(f"  Running Steps 3 & 4 to generate final standard practice...")

    print("\n" + "=" * 60)
    print("Step 3: Analysing frequencies + selecting examples")
    print("=" * 60)
    analyze_frequencies()

    print("\n" + "=" * 60)
    print("Step 4: Generating standard practice")
    print("=" * 60)
    generate_standard()

    print("\n" + "=" * 60)
    print("Pipeline complete!")
    print(f"Standard practice: {PATHS.best_practice_standard.resolve()}")
    print(f"All outputs: {PATHS.parsed.parent.resolve()}")
    print("=" * 60)


if __name__ == "__main__":
    main()
