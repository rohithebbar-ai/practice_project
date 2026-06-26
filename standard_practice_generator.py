"""
standard_practice_generator.py  (v4)
──────────────────────────────────────
Reads from:  pipeline_outputs/04_frequency/
Writes to:   pipeline_outputs/05_standard/
"""

import json
from pathlib import Path

from src.llm_client import LLMClient
from src.storage import load_json, save_json
from src.prompts import STANDARD_PRACTICE_PROMPT_V1
from src.pipeline_paths import PATHS

PROMPT_VERSION    = "v3.1"
MAX_INPUT_TOKENS  = 20_000
MAX_OUTPUT_TOKENS = 3_500


def _count_tokens(text: str) -> int:
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        return len(text) // 4


def _trim_examples_to_budget(best: list, worst: list, budget_chars: int):
    while worst and len(json.dumps(best + worst)) > budget_chars:
        worst = worst[:-1]
    while len(best) > 1 and len(json.dumps(best + worst)) > budget_chars:
        best = best[:-1]
    return best, worst


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

    system_tokens = _count_tokens(STANDARD_PRACTICE_PROMPT_V1)
    available     = MAX_INPUT_TOKENS - system_tokens - 500
    budget_chars  = available * 4

    best_examples, worst_examples = _trim_examples_to_budget(
        best_examples, worst_examples, budget_chars
    )

    user_payload = {
        "frequency_report":              frequency_report,
        "representative_best_examples":  best_examples,
        "representative_worst_examples": worst_examples,
    }
    user_content = json.dumps(user_payload, indent=2)
    input_tokens = system_tokens + _count_tokens(user_content)

    print(f"\nInput: ~{input_tokens:,} tokens (limit {MAX_INPUT_TOKENS:,})")

    llm      = LLMClient()
    messages = [
        {"role": "system", "content": STANDARD_PRACTICE_PROMPT_V1},
        {"role": "user",   "content": user_content},
    ]

    print("Calling LLM...")
    standard = llm.chat_json(messages=messages, max_tokens=MAX_OUTPUT_TOKENS)

    standard["_metadata"] = {
        "prompt_version":  PROMPT_VERSION,
        "source_indents":  total_indents,
        "input_tokens":    input_tokens,
        "best_examples":   len(best_examples),
        "worst_examples":  len(worst_examples),
    }

    save_json(standard, PATHS.best_practice_standard)
    print(f"\nSaved → {PATHS.best_practice_standard}")

    for section in [
        "mandatory_practices", "recommended_practices", "optional_practices",
        "risk_controls", "documentation_requirements",
        "vendor_requirements", "approval_requirements",
    ]:
        count = len(standard.get(section, []))
        print(f"  {section}: {count} items")


if __name__ == "__main__":
    generate_standard()