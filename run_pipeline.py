"""
run_pipeline.py  (v3)
──────────────────────
Steps:
  1. Parse      — document_parser.py    — 0 LLM calls
  2. Analyze    — pipeline_analyze.py   — 55 LLM calls (1 per indent)
  3. Frequency  — frequency_analyzer.py — 0 LLM calls
  4. Standard   — standard_practice_generator.py — 1 LLM call

Total: ~56 LLM calls, ~400–500k tokens
Note: pipeline_consolidate.py removed — no longer needed.
"""

from src.pipeline_parse import parse_raw_documents
from src.pipeline_analyze import analyze_parsed_documents
from src.frequency_analyzer import analyze_frequencies
from src.standard_practice_generator import generate_standard


def main() -> None:
    print("\n" + "="*60)
    print("Civil Indent Practice Pipeline  (v3)")
    print("="*60 + "\n")

    print("="*60)
    print("Step 1: Parsing raw documents")
    print("="*60)
    parse_raw_documents()

    print("\n" + "="*60)
    print("Step 2: Analyzing documents (1 LLM call per indent)")
    print("="*60)
    analyze_parsed_documents()

    print("\n" + "="*60)
    print("Step 3: Analyzing frequencies + selecting examples")
    print("="*60)
    analyze_frequencies()

    print("\n" + "="*60)
    print("Step 4: Generating standard practice")
    print("="*60)
    generate_standard()

    print("\n" + "="*60)
    print("Pipeline complete.")
    print("="*60)


if __name__ == "__main__":
    main()