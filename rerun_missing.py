"""
rerun_missing.py
─────────────────
Finds indents with no extraction JSON and re-runs ONLY those.
Also diagnoses WHY each one failed before retrying.

Run:
  python rerun_missing.py           # diagnose + rerun all missing
  python rerun_missing.py --dry-run # diagnose only, no LLM calls
"""

import json
import sys
import io
import argparse
from pathlib import Path
from collections import defaultdict

# ── Path setup ────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.pipeline_paths import PATHS
from src.storage import load_json, save_model, save_error, safe_name


def _count_tokens(text: str) -> int:
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        return len(text) // 4


def find_missing_indents() -> list:
    """Find all parsed indent folders that have no extraction JSON."""
    parsed_folders = [
        f for f in PATHS.parsed.iterdir() if f.is_dir()
    ]

    missing = []
    for folder in sorted(parsed_folders):
        indent_id   = folder.name
        output_path = PATHS.extractions / f"{indent_id}_extraction.json"

        if not output_path.exists():
            missing.append(indent_id)

    return missing


def diagnose_indent(indent_id: str) -> dict:
    """
    Diagnose why an indent failed to extract.
    Returns diagnosis dict with likely_cause and recommendation.
    """
    indent_dir = PATHS.parsed / indent_id
    txt_files  = list(indent_dir.glob("*.txt"))

    if not txt_files:
        return {
            "indent_id":    indent_id,
            "likely_cause": "NO_PARSED_FILES",
            "detail":       "No .txt files in parsed folder",
            "fix":          "Re-run pipeline_parse.py",
            "can_retry":    False,
            "files":        [],
        }

    file_details = []
    total_chars  = 0

    for txt in sorted(txt_files):
        try:
            text     = txt.read_text(encoding="utf-8", errors="ignore")
            chars    = len(text.strip())
            tokens   = _count_tokens(text)
            total_chars += chars
            file_details.append({
                "name":   txt.name,
                "chars":  chars,
                "tokens": tokens,
                "empty":  chars < 50,
                "sample": text[:100].replace("\n", " "),
            })
        except Exception as e:
            file_details.append({
                "name":  txt.name,
                "error": str(e),
            })

    total_tokens = sum(f.get("tokens", 0) for f in file_details)
    empty_count  = sum(1 for f in file_details if f.get("empty", False))
    large_files  = [
        f for f in file_details
        if f.get("chars", 0) > 50_000
    ]

    # ── Determine likely cause ────────────────────────────────────────────────
    if empty_count == len(txt_files):
        likely_cause = "ALL_DOCUMENTS_EMPTY"
        detail       = "All parsed files are < 50 chars"
        fix          = "Source documents may be image-only PDFs"
        can_retry    = False

    elif total_tokens > 25_000:
        likely_cause = "TOKEN_LIMIT_EXCEEDED"
        detail       = (
            f"Total ~{total_tokens:,} tokens across {len(txt_files)} files. "
            f"Large files: "
            f"{[f['name'] + ' (' + str(f['chars']) + ' chars)' for f in large_files]}"
        )
        fix          = (
            "Compression should handle this but may have truncated the response. "
            "Retry — the adaptive compression in extract_indent() will kick in."
        )
        can_retry    = True

    elif total_tokens > 15_000:
        likely_cause = "LARGE_DOCUMENT_SET"
        detail       = (
            f"Total ~{total_tokens:,} tokens — above average. "
            f"LLM response may have been truncated."
        )
        fix          = "Retry — response truncation is non-deterministic"
        can_retry    = True

    else:
        likely_cause = "UNKNOWN_LLM_FAILURE"
        detail       = (
            f"Total ~{total_tokens:,} tokens — within normal range. "
            f"LLM call likely failed silently (quota/network)."
        )
        fix          = "Retry — should work on second attempt"
        can_retry    = True

    return {
        "indent_id":    indent_id,
        "likely_cause": likely_cause,
        "detail":       detail,
        "fix":          fix,
        "can_retry":    can_retry,
        "total_chars":  total_chars,
        "total_tokens": total_tokens,
        "file_count":   len(txt_files),
        "empty_count":  empty_count,
        "large_files":  [f["name"] for f in large_files],
        "files":        file_details,
    }


def rerun_single_indent(indent_id: str, verbose: bool = True) -> bool:
    """
    Re-run extraction for a single indent.
    Returns True if successful.
    """
    from src.text_cleaner      import clean_document_text
    from src.document_analyzer import DocumentAnalyzer
    from src.procurement_tracker_extractor import is_procurement_tracker_doc

    analyzer   = DocumentAnalyzer()
    indent_dir = PATHS.parsed / indent_id
    txt_files  = list(indent_dir.glob("*.txt"))

    if verbose:
        print(f"\n  Re-extracting: {indent_id}")
        print(f"  Files: {len(txt_files)}")

    documents = []

    for txt_path in sorted(txt_files):
        doc_name = txt_path.name.replace(".txt", "")
        try:
            raw_text      = txt_path.read_text(encoding="utf-8", errors="ignore")
            document_text = clean_document_text(raw_text)

            if len(document_text.strip()) < 50:
                if verbose:
                    print(f"    [SKIP] {doc_name} — empty after cleaning")
                continue

            classification = analyzer.classify_rule_based(
                document_name=doc_name,
                document_text=document_text,
            )

            if verbose:
                print(
                    f"    [CLASS] {doc_name}: "
                    f"{classification.document_type.value}"
                )

            # Load parser metadata if available
            meta_path = (
                PATHS.parsed_metadata / indent_id /
                f"{safe_name(txt_path.name)}.metadata.json"
            )
            parser_metadata = {}
            if meta_path.exists():
                try:
                    parser_metadata = load_json(meta_path)
                except Exception:
                    pass

            documents.append({
                "document_name":   doc_name,
                "document_text":   document_text,
                "classification":  classification,
                "parser_metadata": parser_metadata,
            })

        except Exception as e:
            if verbose:
                print(f"    [ERROR] {doc_name}: {e}")

    if not documents:
        if verbose:
            print(f"  [SKIP] No valid documents for {indent_id}")
        return False

    # ── LLM extraction — stdout redirected ───────────────────────────────────
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()

    try:
        indent_extraction = analyzer.extract_indent(
            indent_id=indent_id,
            indent_title=indent_id.replace("_", " "),
            documents=documents,
        )
        result = indent_extraction

    except Exception as e:
        sys.stdout = old_stdout
        if verbose:
            print(f"  [ERROR] extract_indent failed: {e}")
        save_error(
            error=e,
            output_dir=PATHS.logs,
            file_stem=f"rerun_{indent_id}",
            extra={"indent_id": indent_id},
        )
        return False
    finally:
        sys.stdout = old_stdout

    # ── Check if extraction has content ──────────────────────────────────────
    result_dict = result.model_dump()
    ps          = result_dict.get("procurement_summary", {}) or {}
    docs        = result_dict.get("documents", [])

    has_content = any([
        ps.get("scope_of_work"),
        ps.get("package_description"),
        ps.get("procurement_type"),
        any(d.get("document_summary") for d in docs),
        len(result_dict.get("good_practices", [])) > 0,
    ])

    if not has_content:
        if verbose:
            print(f"  [WARN] Extraction returned empty content")
            print(f"         procurement_type: {ps.get('procurement_type')}")
            print(f"         package_description: {ps.get('package_description')}")
        return False

    # ── Save ──────────────────────────────────────────────────────────────────
    try:
        saved_path = save_model(
            model=result,
            output_dir=PATHS.extractions,
            file_stem=f"{indent_id}_extraction",
        )
        if verbose:
            print(f"  [SAVED] {saved_path}")
            print(f"  procurement_type: {ps.get('procurement_type', '—')}")
            print(f"  package_description: {ps.get('package_description', '—')}")
        return True
    except Exception as e:
        if verbose:
            print(f"  [ERROR] Save failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Diagnose and re-run missing indent extractions"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Diagnose only — do not make LLM calls",
    )
    parser.add_argument(
        "--indent",
        help="Re-run a specific indent ID only",
    )
    args = parser.parse_args()

    PATHS.ensure_all()

    print("\n" + "=" * 70)
    print("  MISSING INDENT DIAGNOSIS & RERUN")
    print("=" * 70)

    # ── Find missing ──────────────────────────────────────────────────────────
    if args.indent:
        missing = [args.indent]
    else:
        missing = find_missing_indents()

    print(f"\nMissing extractions: {len(missing)}")
    for m in missing:
        print(f"  - {m}")

    if not missing:
        print("\nAll indents have extractions. Nothing to do.")
        return

    # ── Diagnose each ─────────────────────────────────────────────────────────
    print(f"\n{'─' * 70}")
    print("DIAGNOSIS")
    print(f"{'─' * 70}")

    diagnoses  = []
    can_retry  = []
    cant_retry = []

    for indent_id in missing:
        diagnosis = diagnose_indent(indent_id)
        diagnoses.append(diagnosis)

        print(f"\n{indent_id}")
        print(f"  Cause   : {diagnosis['likely_cause']}")
        print(f"  Detail  : {diagnosis['detail']}")
        print(f"  Fix     : {diagnosis['fix']}")
        print(f"  Files   : {diagnosis['file_count']} "
              f"({diagnosis['total_chars']:,} chars, "
              f"~{diagnosis['total_tokens']:,} tokens)")
        if diagnosis.get("large_files"):
            print(f"  Large   : {diagnosis['large_files']}")

        if diagnosis["can_retry"]:
            can_retry.append(indent_id)
        else:
            cant_retry.append(indent_id)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'─' * 70}")
    print(f"Can retry  : {len(can_retry)}")
    print(f"Cannot retry: {len(cant_retry)}")
    if cant_retry:
        print(f"  {cant_retry} — check source documents")

    if args.dry_run:
        print("\nDry run — no LLM calls made.")
        print(f"To retry, run: python rerun_missing.py")
        return

    if not can_retry:
        print("\nNo indents to retry.")
        return

    # ── Rerun ─────────────────────────────────────────────────────────────────
    print(f"\n{'─' * 70}")
    print(f"RERUNNING {len(can_retry)} INDENT(S)")
    print(f"{'─' * 70}")

    success = 0
    failed  = []

    for i, indent_id in enumerate(can_retry, 1):
        print(f"\n[{i}/{len(can_retry)}] {indent_id}")
        ok = rerun_single_indent(indent_id, verbose=True)
        if ok:
            success += 1
        else:
            failed.append(indent_id)

        # Small pause between calls to avoid rate limiting
        if i < len(can_retry):
            import time
            time.sleep(2)

    # ── Final report ──────────────────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("  RERUN COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Attempted : {len(can_retry)}")
    print(f"  Succeeded : {success}")
    print(f"  Failed    : {len(failed)}")
    if failed:
        print(f"  Still missing: {failed}")
        print()
        print("  For failed indents, try:")
        print("  1. Run again (LLM failures are sometimes transient)")
        print("  2. Check if source documents are complete")
        print("  3. The large file compression may need MAX_OUTPUT_TOKENS")
        print("     increased in document_analyzer.py")

    # ── If any succeeded, re-run Steps 3 & 4 ─────────────────────────────────
    if success > 0:
        print(f"\n  {success} new extraction(s) added.")
        print("  Run Steps 3 & 4 to update the standard:")
        print("  python run_steps34.py")
    print()


if __name__ == "__main__":
    main()
