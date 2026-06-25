"""
pipeline_analyze.py  (v3)
─────────────────────────
One LLM call per indent.
Saves one IndentExtraction JSON per indent (not per document).
pipeline_consolidate.py is no longer needed.
"""

from pathlib import Path
from collections import defaultdict

from src.document_analyzer import DocumentAnalyzer
from src.storage import ensure_dir, save_model, save_error, load_json, safe_name
from src.text_cleaner import clean_document_text


PARSED_DIR      = Path("data/parsed_text")
PARSER_META_DIR = Path("data/parsed_text_metadata")
INDENT_OUTPUT_DIR = Path("data/extracted_json/indent_level")   # one JSON per indent
CLEANED_DIR     = Path("data/cleaned_text")
ERROR_DIR       = Path("logs/error_logs")


def _load_parser_metadata(indent_id: str, parsed_file_name: str) -> dict:
    original_name = parsed_file_name.replace(".txt", "")
    meta_path = (
        PARSER_META_DIR / indent_id / f"{original_name}.metadata.json"
    )
    if meta_path.exists():
        return load_json(meta_path)
    return {}


def analyze_parsed_documents() -> None:
    analyzer = DocumentAnalyzer()
    ensure_dir(INDENT_OUTPUT_DIR)

    # ── Group all txt files by indent ────────────────────────────────────────
    txt_files = list(PARSED_DIR.rglob("*.txt"))
    print(f"Found {len(txt_files)} parsed text files\n")

    indent_to_files = defaultdict(list)
    for txt_path in txt_files:
        indent_id = txt_path.parent.name
        indent_to_files[indent_id].append(txt_path)

    print(f"Found {len(indent_to_files)} indents\n")

    total_llm_calls  = 0
    total_docs       = 0
    total_chars_sent = 0

    # ── Process one indent at a time ─────────────────────────────────────────
    for indent_id, txt_paths in sorted(indent_to_files.items()):
        safe_id = safe_name(indent_id)
        print(f"\n{'='*60}")
        print(f"INDENT: {indent_id}")
        print(f"Documents: {len(txt_paths)}")
        print(f"{'='*60}")

        # Skip if already processed
        output_path = INDENT_OUTPUT_DIR / f"{safe_id}_extraction.json"
        if output_path.exists():
            print(f"  [CACHED] Already processed — skipping")
            continue

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

                # Save cleaned text for inspection
                cleaned_dir = CLEANED_DIR / safe_id
                ensure_dir(cleaned_dir)
                (cleaned_dir / txt_path.name).write_text(
                    document_text, encoding="utf-8"
                )

                # Rule-based classification (0 LLM calls)
                classification = analyzer.classify_rule_based(
                    document_name=document_name,
                    document_text=document_text,
                )
                print(
                    f"  [CLASS] {document_name}: "
                    f"{classification.document_type.value} "
                    f"({classification.confidence.value})"
                )

                parser_metadata = _load_parser_metadata(
                    indent_id, txt_path.name
                )

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
                    output_dir=ERROR_DIR,
                    file_stem=f"clean_{safe_id}_{document_name}",
                    extra={"txt_path": str(txt_path)},
                )

        if not documents:
            print(f"  [SKIP] No valid documents for {indent_id}")
            continue

        # ── ONE LLM call for entire indent ───────────────────────────────────
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

        except Exception as exc:
            print(f"  [ERROR] extract_indent failed: {exc}")
            save_error(
                error=exc,
                output_dir=ERROR_DIR,
                file_stem=f"extract_{safe_id}",
                extra={"indent_id": indent_id},
            )
            continue

        # ── Save ONE JSON per indent ─────────────────────────────────────────
        try:
            saved_path = save_model(
                model=indent_extraction,
                output_dir=INDENT_OUTPUT_DIR,
                file_stem=f"{safe_id}_extraction",
            )
            print(f"  [SAVED] {saved_path}")
        except Exception as exc:
            print(f"  [ERROR] Failed saving: {exc}")
            save_error(
                error=exc,
                output_dir=ERROR_DIR,
                file_stem=f"save_{safe_id}",
            )

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"pipeline_analyze complete")
    print(f"  LLM calls made : {total_llm_calls}")
    print(f"  Documents      : {total_docs}")
    print(f"  Chars sent     : {total_chars_sent:,}")
    print(f"  Approx tokens  : ~{total_chars_sent // 4:,}")
    print(f"{'='*60}")


if __name__ == "__main__":
    analyze_parsed_documents()