"""
pipeline_analyze.py  (v4)
──────────────────────────
Reads from:  pipeline_outputs/01_parsed/
Writes to:   pipeline_outputs/02_cleaned/
             pipeline_outputs/03_extractions/
"""

from pathlib import Path
from collections import defaultdict

from src.document_analyzer import DocumentAnalyzer
from src.storage import ensure_dir, save_model, save_error, load_json, safe_name
from src.text_cleaner import clean_document_text
from src.pipeline_paths import PATHS


def _load_parser_metadata(safe_indent_id: str, parsed_file_name: str) -> dict:
    meta_path = (
        PATHS.parsed_metadata
        / safe_indent_id
        / f"{safe_name(parsed_file_name)}.metadata.json"
    )
    if meta_path.exists():
        return load_json(meta_path)
    return {}


def analyze_parsed_documents() -> None:
    analyzer = DocumentAnalyzer()
    PATHS.ensure_all()

    # Group all txt files by indent
    txt_files = list(PATHS.parsed.rglob("*.txt"))
    print(f"Found {len(txt_files)} parsed text files\n")

    indent_to_files: dict = defaultdict(list)
    for txt_path in txt_files:
        indent_id = txt_path.parent.name
        indent_to_files[indent_id].append(txt_path)

    print(f"Found {len(indent_to_files)} indents\n")

    total_llm_calls  = 0
    total_docs       = 0
    total_chars_sent = 0

    for indent_id, txt_paths in sorted(indent_to_files.items()):
        safe_id = safe_name(indent_id)

        print(f"\n{'='*60}")
        print(f"INDENT: {indent_id}")
        print(f"Documents: {len(txt_paths)}")
        print(f"{'='*60}")

        # Skip if already processed successfully
        output_path = PATHS.extractions / f"{safe_id}_extraction.json"
        if output_path.exists():
            # Check it's not empty
            try:
                existing = load_json(output_path)
                ps = existing.get("procurement_summary", {}) or {}
                has_content = any([
                    ps.get("scope_of_work"),
                    ps.get("package_description"),
                    any(d.get("document_summary")
                        for d in existing.get("documents", [])),
                    len(existing.get("good_practices", [])) > 0,
                ])
                if has_content:
                    print(f"  [CACHED] Already processed — skipping")
                    continue
                else:
                    print(f"  [RERUN] Cached file is empty — reprocessing")
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

    print(f"\n{'='*60}")
    print(f"pipeline_analyze complete")
    print(f"  LLM calls made : {total_llm_calls}")
    print(f"  Documents      : {total_docs}")
    print(f"  Chars sent     : {total_chars_sent:,}")
    print(f"  Approx tokens  : ~{total_chars_sent // 4:,}")
    print(f"{'='*60}")


if __name__ == "__main__":
    analyze_parsed_documents()