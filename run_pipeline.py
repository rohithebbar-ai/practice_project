"""
run_pipeline.py  (v4)
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
"""

from src.pipeline_parse import parse_raw_documents
from src.pipeline_analyze import analyze_parsed_documents
from src.frequency_analyzer import analyze_frequencies
from src.standard_practice_generator import generate_standard
from src.pipeline_paths import PATHS


def main() -> None:
    print("\n" + "="*60)
    print("Civil Indent Practice Pipeline  (v4)")
    print(f"All outputs → {PATHS.parsed.parent.resolve()}")
    print("="*60 + "\n")

    print("="*60)
    print("Step 1: Parsing raw documents")
    print("="*60)
    parse_raw_documents()

    print("\n" + "="*60)
    print("Step 2: Analysing documents (1 LLM call per indent)")
    print("="*60)
    analyze_parsed_documents()

    print("\n" + "="*60)
    print("Step 3: Analysing frequencies + selecting examples")
    print("="*60)
    analyze_frequencies()

    print("\n" + "="*60)
    print("Step 4: Generating standard practice")
    print("="*60)
    generate_standard()

    print("\n" + "="*60)
    print("Pipeline complete.")
    print(f"Outputs in: {PATHS.parsed.parent.resolve()}")
    print("="*60)


if __name__ == "__main__":
    main()