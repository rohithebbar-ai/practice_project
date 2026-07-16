cd ~/ipms-indent-validation


gcloud auth print-identity-token \
  --impersonate-service-account=svc-ipms-indent-validation@tsl-generative-ai.iam.gserviceaccount.com \
  --audiences=https://genai-api-development-one-it-423929642383.asia-south1.run.app


gcloud secrets create genai-key \
  --project=tsl-generative-ai \
  --replication-policy="automatic" \
  --data-file="secrets/svc-genai-api-dev-oneit.json"


gcloud secrets add-iam-policy-binding genai-key \
  --project=tsl-generative-ai \
  --member="serviceAccount:svc-ipms-indent-validation@tsl-generative-ai.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"


gcloud run deploy ipms-indent-validation \
  --project=tsl-generative-ai \
  --region=asia-south1 \
  --source=. \
  --service-account=svc-ipms-indent-validation@tsl-generative-ai.iam.gserviceaccount.com \
  --set-secrets="/secrets/genai-key.json=genai-key:latest" \
  --set-env-vars="GENAI_SERVICE_ACCOUNT=/secrets/genai-key.json,GENAI_AUTH_URL=<your_auth_url>,GENAI_API_URL=<your_api_url>,GENAI_API_KEY=<your_api_key>,GENAI_ADID=<your_adid>,GENAI_MODEL=gpt-4o-mini" \
  --allow-unauthenticated \
  --memory=1Gi \
  --timeout=300





"""
diagnose_missing.py
────────────────────
Finds the 7 indents that were parsed but never extracted.

Compares:
  pipeline_outputs/01_parsed/     ← what was parsed (source of truth)
  pipeline_outputs/03_extractions/ ← what was extracted

For each missing indent, shows:
  - What documents were parsed
  - How much text was extracted per document
  - Whether there are error logs
  - Likely reason for failure

Run:
  python diagnose_missing.py
"""

import json
from pathlib import Path
from collections import defaultdict

PIPELINE_ROOT   = Path("pipeline_outputs")
PARSED_DIR      = PIPELINE_ROOT / "01_parsed"
EXTRACTIONS_DIR = PIPELINE_ROOT / "03_extractions"
LOGS_DIR        = PIPELINE_ROOT / "logs"


def main():
    print("\n" + "=" * 70)
    print("  MISSING INDENT DIAGNOSIS")
    print("=" * 70)

    # ── Get all parsed indent folders ─────────────────────────────────────────
    parsed_indents = set()
    for folder in PARSED_DIR.iterdir():
        if folder.is_dir():
            parsed_indents.add(folder.name)

    # ── Get all extracted indent IDs ──────────────────────────────────────────
    extracted_indents = set()
    for f in EXTRACTIONS_DIR.rglob("*_extraction.json"):
        # stem is like "indent_id_extraction" → strip "_extraction"
        indent_id = f.stem.replace("_extraction", "")
        extracted_indents.add(indent_id)

    # ── Find missing ──────────────────────────────────────────────────────────
    missing = parsed_indents - extracted_indents

    print(f"\nParsed indent folders : {len(parsed_indents)}")
    print(f"Extracted JSONs       : {len(extracted_indents)}")
    print(f"Missing               : {len(missing)}")

    if not missing:
        print("\nAll parsed indents have extractions.")
        return

    print(f"\nMissing indents: {sorted(missing)}")

    # ── Diagnose each missing indent ──────────────────────────────────────────
    for indent_id in sorted(missing):
        print(f"\n{'─' * 70}")
        print(f"MISSING: {indent_id}")
        print(f"{'─' * 70}")

        indent_dir = PARSED_DIR / indent_id
        txt_files  = list(indent_dir.glob("*.txt"))

        if not txt_files:
            print("  ❌ No parsed .txt files found — parse step may have failed")
            continue

        print(f"  Parsed files ({len(txt_files)}):")
        total_chars = 0
        empty_count = 0

        for txt in sorted(txt_files):
            try:
                text  = txt.read_text(encoding="utf-8", errors="ignore")
                chars = len(text.strip())
                total_chars += chars
                status = "OK" if chars >= 50 else "EMPTY"
                if chars < 50:
                    empty_count += 1
                print(f"    {status:5s}  {chars:>7,} chars  {txt.name}")
            except Exception as e:
                print(f"    ERROR  {txt.name}: {e}")

        print(f"\n  Total chars: {total_chars:,}")

        # ── Diagnose likely reason ────────────────────────────────────────────
        print("\n  Likely reason:")

        if total_chars < 100:
            print("  → All documents are empty after parsing")
            print("    Check source files in data/raw/")

        elif empty_count == len(txt_files):
            print("  → All documents too short (< 50 chars)")
            print("    Documents may be images/drawings with no text layer")

        else:
            # Check if it was cached and skipped
            cached_check = EXTRACTIONS_DIR / f"{indent_id}_extraction.json"
            if not cached_check.exists():
                print("  → Extraction was attempted but no output file found")
                print("    Possible causes:")
                print("    1. LLM call failed (quota/timeout)")
                print("    2. JSON parsing failed (truncated response)")
                print("    3. Extraction returned empty content")
                print("    4. Pipeline was interrupted mid-run")

        # ── Check error logs ──────────────────────────────────────────────────
        if LOGS_DIR.exists():
            error_logs = list(LOGS_DIR.glob(f"*{indent_id}*"))
            if error_logs:
                print(f"\n  Error logs found ({len(error_logs)}):")
                for log in error_logs[:5]:
                    print(f"    {log.name}")
                    try:
                        log_data = json.loads(
                            log.read_text(encoding="utf-8")
                        )
                        error_msg = log_data.get("error", "")
                        if error_msg:
                            print(f"    Error: {error_msg[:200]}")
                    except Exception:
                        pass
            else:
                print("\n  No error logs found for this indent")
                print("  → Pipeline may have skipped it silently")

        # ── Check if content would pass has_content check ─────────────────────
        print("\n  Content quality check:")
        for txt in sorted(txt_files)[:3]:
            try:
                text = txt.read_text(encoding="utf-8", errors="ignore")
                sample = text[:200].replace("\n", " ")
                print(f"    {txt.name}: '{sample[:150]}...'")
            except Exception:
                pass

    # ── Summary and recommended actions ──────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("  RECOMMENDED ACTIONS")
    print(f"{'=' * 70}")
    print()
    print("Option 1 — Force re-extract missing indents:")
    print("  The pipeline skips indents with existing extractions.")
    print("  Since these have NO extraction, they should run automatically.")
    print("  Just run:")
    print("    python pipeline_analyze.py")
    print()
    print("Option 2 — If they keep failing, check source documents:")
    for indent_id in sorted(missing):
        raw_path = Path("data") / "raw" / indent_id
        if raw_path.exists():
            raw_files = list(raw_path.iterdir())
            print(f"  data/raw/{indent_id}/: {len(raw_files)} files")
        else:
            # Try to find the folder with similar name
            print(f"  data/raw/{indent_id}/: folder not found")
            print(f"    → folder name mismatch between raw/ and parsed/")

    print()
    print("Option 3 — Check if has_content filter is too strict:")
    print("  pipeline_analyze.py skips extractions where has_content=False")
    print("  These indents may have been extracted but returned empty JSON")
    print("  Check: pipeline_outputs/03_extractions/ for partial files")
    print()


if __name__ == "__main__":
    main()
