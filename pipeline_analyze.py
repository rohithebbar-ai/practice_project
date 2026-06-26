"""
pipeline_analyze.py  (v5)
──────────────────────────
Reads from:  pipeline_outputs/01_parsed/
Writes to:   pipeline_outputs/02_cleaned/
             pipeline_outputs/03_extractions/

Batch control:
  Default: processes ALL indents (no limit)
  Override via environment variable: set PIPELINE_BATCH=5
  Override via command line: python pipeline_analyze.py --batch 5

Examples:
  python pipeline_analyze.py              → runs all indents
  python pipeline_analyze.py --batch 5   → runs 5 at a time
  set PIPELINE_BATCH=5 (Windows)         → runs 5 at a time
  export PIPELINE_BATCH=5 (Linux/Mac)    → runs 5 at a time
"""

import argparse
import os
from pathlib import Path
from collections import defaultdict

from src.document_analyzer import DocumentAnalyzer
from src.storage import ensure_dir, save_model, save_error, load_json, safe_name
from src.text_cleaner import clean_document_text
from src.pipeline_paths import PATHS

# ── Current prompt version — update when prompts.py changes ──────────────────
# This forces reprocessing of cached extractions when prompt changes.
CURRENT_PROMPT_VERSION = "v3.3"


def _get_max_batch() -> int:
    """
    Determine batch size from:
    1. Command line argument --batch (highest priority)
    2. Environment variable PIPELINE_BATCH
    3. Default: 999999 (effectively unlimited — runs all indents)
    """
    # Check command line argument
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--batch", type=int, default=None)
    args, _ = parser.parse_known_args()

    if args.batch is not None:
        print(f"  [BATCH] Using command line batch size: {args.batch}")
        return args.batch

    # Check environment variable
    env_batch = os.getenv("PIPELINE_BATCH")
    if env_batch is not None:
        try:
            batch = int(env_batch)
            print(f"  [BATCH] Using environment variable batch size: {batch}")
            return batch
        except ValueError:
            print(f"  [WARN] Invalid PIPELINE_BATCH value: {env_batch}, using unlimited")

    # Default: run all
    print(f"  [BATCH] No batch limit set — running all indents")
    return 999_999


def _load_parser_metadata(safe_indent_id: str, parsed_file_name: str) -> dict:
    meta_path = (
        PATHS.parsed_metadata
        / safe_indent_id
        / f"{safe_name(parsed_file_name)}.metadata.json"
    )
    if meta_path.exists():
        return load_json(meta_path)
    return {}


def _has_content(existing: dict) -> bool:
    """
    Broader content check — avoids skipping valid extractions
    that have documents but no scope_of_work/package_description.
    Also checks prompt version to force reprocess when prompt changes.
    """
    # Check prompt version — reprocess if prompt has changed
    cached_version = existing.get(
        "analyzer_metadata", {}
    ).get("prompt_version", "")

    if cached_version != CURRENT_PROMPT_VERSION:
        print(
            f"  [RERUN] Prompt version changed "
            f"({cached_version} → {CURRENT_PROMPT_VERSION})"
        )
        return False

    ps   = existing.get("procurement_summary", {}) or {}
    docs = existing.get("documents", []) or []

    return any([
        ps.get("scope_of_work"),
        ps.get("package_description"),
        ps.get("procurement_type"),
        ps.get("document_types_present"),
        any(d.get("document_summary") for d in docs),
        any(d.get("document_type") for d in docs),
        len(existing.get("good_practices", [])) > 0,
        len(docs) > 0,
    ])


def analyze_parsed_documents() -> None:
    analyzer  = DocumentAnalyzer()
    max_batch = _get_max_batch()
    PATHS.ensure_all()

    # Group all txt files by indent
    txt_files = list(PATHS.parsed.rglob("*.txt"))
    print(f"Found {len(txt_files)} parsed text files\n")

    indent_to_files: dict = defaultdict(list)
    for txt_path in txt_files:
        indent_id = txt_path.parent.name
        indent_to_files[indent_id].append(txt_path)

    total_available = len(indent_to_files)
    print(f"Found {total_available} indents\n")

    total_llm_calls  = 0
    total_docs       = 0
    total_chars_sent = 0
    indents_run      = 0

    for indent_id, txt_paths in sorted(indent_to_files.items()):

        # ── Batch limit check ─────────────────────────────────────────────────
        if indents_run >= max_batch:
            remaining = total_available - indents_run
            cached    = sum(
                1 for iid in indent_to_files
                if (PATHS.extractions / f"{safe_name(iid)}_extraction.json").exists()
            ) - indents_run
            print(f"\n[BATCH LIMIT] Processed {indents_run} new indent(s) this run.")
            print(f"  Rerun to continue with remaining indents.")
            print(f"  Tip: run without --batch to process all at once.\n")
            break

        safe_id = safe_name(indent_id)

        print(f"\n{'=' * 60}")
        print(f"INDENT: {indent_id}")
        print(f"Documents: {len(txt_paths)}")
        print(f"{'=' * 60}")

        # ── Skip if already processed successfully ────────────────────────────
        output_path = PATHS.extractions / f"{safe_id}_extraction.json"
        if output_path.exists():
            try:
                existing = load_json(output_path)
                if _has_content(existing):
                    print(f"  [CACHED] Already processed — skipping")
                    continue
                else:
                    print(f"  [RERUN] Cached file empty or outdated — reprocessing")
                    output_path.unlink()
            except Exception:
                pass

        documents = []

        for txt_path in txt_paths:
            document_name = txt_path.name.replace(".txt", "")
            try:
                raw_text      = txt_path.read_text(encoding="utf-8", errors="ignore")
                document_text = clean_document_text(raw_text)

                if len(document_text.strip()) < 50:
                    print(f"  [SKIP] {document_name} — empty after cleaning")
                    continue

                print(
                    f"  [CLEAN] {document_name}: "
                    f"{len(raw_text):,} → {len(document_text):,} chars"
                )

                # Save cleaned text
                cleaned_dir = PATHS.cleaned / safe_id
                ensure_dir(cleaned_dir)
                (cleaned_dir / txt_path.name).write_text(
                    document_text, encoding="utf-8"
                )

                # Rule-based classification
                classification = analyzer.classify_rule_based(
                    document_name=document_name,
                    document_text=document_text,
                )
                print(
                    f"  [CLASS] {document_name}: "
                    f"{classification.document_type.value} "
                    f"({classification.confidence.value})"
                )

                parser_metadata = _load_parser_metadata(safe_id, txt_path.name)

                documents.append({
                    "document_name":   document_name,
                    "document_text":   document_text,
                    "classification":  classification,
                    "parser_metadata": parser_metadata,
                })
                total_docs += 1

            except Exception as exc:
                print(f"  [ERROR] Failed processing {txt_path.name}: {exc}")
                save_error(
                    error=exc,
                    output_dir=PATHS.logs,
                    file_stem=f"clean_{safe_id}_{document_name}",
                    extra={"txt_path": str(txt_path)},
                )

        if not documents:
            print(f"  [SKIP] No valid documents for {indent_id}")
            continue

        # ONE LLM call for entire indent
        try:
            indent_extraction = analyzer.extract_indent(
                indent_id=safe_id,
                indent_title=indent_id,
                documents=documents,
            )
            total_llm_calls  += 1
            total_chars_sent += indent_extraction.analyzer_metadata.get(
                "total_input_chars", 0
            )
            indents_run += 1   # only increment on successful LLM call

        except Exception as exc:
            print(f"  [ERROR] extract_indent failed: {exc}")
            save_error(
                error=exc,
                output_dir=PATHS.logs,
                file_stem=f"extract_{safe_id}",
                extra={"indent_id": indent_id},
            )
            continue

        # Save ONE JSON per indent
        try:
            saved_path = save_model(
                model=indent_extraction,
                output_dir=PATHS.extractions,
                file_stem=f"{safe_id}_extraction",
            )
            print(f"  [SAVED] {saved_path}")
        except Exception as exc:
            print(f"  [ERROR] Failed saving: {exc}")
            save_error(
                error=exc,
                output_dir=PATHS.logs,
                file_stem=f"save_{safe_id}",
            )

    print(f"\n{'=' * 60}")
    print(f"pipeline_analyze complete")
    print(f"  New indents processed  : {indents_run}")
    print(f"  LLM calls made         : {total_llm_calls}")
    print(f"  Documents processed    : {total_docs}")
    print(f"  Chars sent             : {total_chars_sent:,}")
    print(f"  Approx tokens          : ~{total_chars_sent // 4:,}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    analyze_parsed_documents()
