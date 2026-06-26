"""
standard_practice_generator.py  (v5)
──────────────────────────────────────
Reads from:  pipeline_outputs/04_frequency/
Writes to:   pipeline_outputs/05_standard/

Changes from v4:
  - Increased MAX_INPUT_TOKENS to 35,000
  - Increased MAX_OUTPUT_TOKENS to 8,000
  - Representative examples now included in main output (not just metadata)
  - Better trimming logic to stay within token budget
"""

import json
from pathlib import Path

from src.llm_client import LLMClient
from src.storage import load_json, save_json
from src.prompts import STANDARD_PRACTICE_PROMPT_V2
from src.pipeline_paths import PATHS

PROMPT_VERSION    = "v4.0"
MAX_INPUT_TOKENS  = 35_000
MAX_OUTPUT_TOKENS = 8_000


def _count_tokens(text: str) -> int:
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        return len(text) // 4


def _trim_to_budget(payload: dict, budget_chars: int) -> dict:
    """
    Trim payload to fit within token budget.
    Priority: keep frequency data, trim examples last.
    """
    # First try with all examples
    if len(json.dumps(payload)) <= budget_chars:
        return payload

    # Trim worst examples first
    while (payload.get("representative_worst_examples") and
           len(json.dumps(payload)) > budget_chars):
        payload["representative_worst_examples"].pop()

    # Then trim best examples (keep at least 1)
    while (len(payload.get("representative_best_examples", [])) > 1 and
           len(json.dumps(payload)) > budget_chars):
        payload["representative_best_examples"].pop()

    # Then trim category patterns
    while (payload.get("category_document_patterns") and
           len(json.dumps(payload)) > budget_chars):
        payload["category_document_patterns"].pop()

    # Then trim good/weak practice frequency (keep top 30)
    if len(json.dumps(payload)) > budget_chars:
        payload["good_practice_frequency"] = \
            payload.get("good_practice_frequency", [])[:30]
        payload["weak_item_frequency"] = \
            payload.get("weak_item_frequency", [])[:30]

    return payload


def generate_standard() -> None:
    PATHS.ensure_all()

    if not PATHS.frequency_report.exists():
        raise FileNotFoundError(
            f"Frequency report not found: {PATHS.frequency_report}\n"
            "Run frequency_analyzer.py first."
        )

    frequency_report = load_json(PATHS.frequency_report)
    total_indents    = frequency_report.get("total_indents", 0)

    print(f"Frequency report loaded: {total_indents} indents")
    print(f"  Procurement types : "
          f"{len(frequency_report.get('procurement_type_breakdown', []))}")
    print(f"  Good practices    : "
          f"{len(frequency_report.get('good_practice_frequency', []))}")
    print(f"  Weak items        : "
          f"{len(frequency_report.get('weak_item_frequency', []))}")
    print(f"  Risk controls     : "
          f"{len(frequency_report.get('risk_control_frequency', []))}")
    print(f"  Category patterns : "
          f"{len(frequency_report.get('category_document_patterns', []))}")

    best_examples  = []
    worst_examples = []

    if PATHS.representative_examples.exists():
        representative = load_json(PATHS.representative_examples)
        best_examples  = representative.get("representative_best_examples",  [])
        worst_examples = representative.get("representative_worst_examples", [])
        print(f"  Best examples     : {len(best_examples)}")
        print(f"  Worst examples    : {len(worst_examples)}")
    else:
        print("  [WARN] representative_examples.json not found")

    # ── Build payload ─────────────────────────────────────────────────────────
    system_tokens = _count_tokens(STANDARD_PRACTICE_PROMPT_V2)
    available     = MAX_INPUT_TOKENS - system_tokens - 500
    budget_chars  = available * 4

    user_payload = {
        "total_indents":                  total_indents,
        "procurement_type_breakdown":     frequency_report.get("procurement_type_breakdown", []),
        "document_type_frequency":        frequency_report.get("document_type_frequency", []),
        "good_practice_frequency":        frequency_report.get("good_practice_frequency", []),
        "weak_item_frequency":            frequency_report.get("weak_item_frequency", []),
        "risk_control_frequency":         frequency_report.get("risk_control_frequency", []),
        "structure_quality_frequency":    frequency_report.get("structure_quality_frequency", []),
        "category_document_patterns":     frequency_report.get("category_document_patterns", []),
        "representative_best_examples":   best_examples,
        "representative_worst_examples":  worst_examples,
    }

    user_payload  = _trim_to_budget(user_payload, budget_chars)
    user_content  = json.dumps(user_payload, indent=2)
    input_tokens  = system_tokens + _count_tokens(user_content)

    print(f"\nInput: ~{input_tokens:,} tokens (limit {MAX_INPUT_TOKENS:,})")

    if input_tokens > MAX_INPUT_TOKENS:
        print(f"  [WARN] Still over limit — trimming further...")
        # Hard trim good/weak practices
        user_payload["good_practice_frequency"] = \
            user_payload.get("good_practice_frequency", [])[:20]
        user_payload["weak_item_frequency"] = \
            user_payload.get("weak_item_frequency", [])[:20]
        user_payload["risk_control_frequency"] = \
            user_payload.get("risk_control_frequency", [])[:20]
        user_content = json.dumps(user_payload, indent=2)
        input_tokens = system_tokens + _count_tokens(user_content)
        print(f"  After trim: ~{input_tokens:,} tokens")

    # ── LLM call ──────────────────────────────────────────────────────────────
    llm      = LLMClient()
    messages = [
        {"role": "system", "content": STANDARD_PRACTICE_PROMPT_V2},
        {"role": "user",   "content": user_content},
    ]

    print("Calling LLM...")
    standard = llm.chat_json(messages=messages, max_tokens=MAX_OUTPUT_TOKENS)

    # ── Add metadata and examples to output ───────────────────────────────────
    standard["_metadata"] = {
        "prompt_version":  PROMPT_VERSION,
        "source_indents":  total_indents,
        "input_tokens":    input_tokens,
        "best_examples":   len(best_examples),
        "worst_examples":  len(worst_examples),
    }

    # Include representative examples in standard for app.py to use
    standard["representative_best_examples"]  = best_examples
    standard["representative_worst_examples"] = worst_examples

    save_json(standard, PATHS.best_practice_standard)
    print(f"\nSaved → {PATHS.best_practice_standard}")

    # ── Print summary ─────────────────────────────────────────────────────────
    sections = [
        "mandatory_practices",
        "recommended_practices",
        "optional_practices",
        "common_good_practices",
        "common_weak_practices",
        "risk_controls",
        "documentation_requirements",
        "document_structure_standards",
        "vendor_requirements",
        "approval_requirements",
        "category_specific_patterns",
    ]
    for section in sections:
        count = len(standard.get(section, []))
        print(f"  {section}: {count} items")


if __name__ == "__main__":
    generate_standard()
