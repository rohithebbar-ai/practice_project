"""
check_available_models.py
────────────────────────────
Quick diagnostic — tries a minimal real call against the GENAI gateway
for each candidate model name, and reports whether it succeeded or was
rejected. This is the fastest way to answer "is gpt-5.2 available?"
since most internal gateways (this one included, based on llm_client.py
using a `deployment_name` field) will return an explicit error for an
unconfigured deployment name rather than silently falling back.

Usage:
    python check_available_models.py

Requires the same env vars llm_client.py needs (GENAI_AUTH_URL,
GENAI_API_URL, GENAI_SERVICE_ACCOUNT, GENAI_API_KEY, GENAI_ADID) —
run this locally where your .env / GENAI_SERVICE_ACCOUNT file already
works, not from inside the deployed Cloud Run service.
"""

import os
import sys

# Reuse the exact same client the production code uses — if this
# script works, main.py's GENAI calls will work the same way.
sys.path.insert(0, os.path.dirname(__file__))
from llm_client import LLMClient  # noqa: E402


# Candidate model / deployment names to check. Add/remove as needed —
# "gpt-5.2" is included because the reference project (Alekh2D) uses
# that exact deployment_name value successfully, which is a strong
# signal it's already configured on this same gateway.
CANDIDATE_MODELS = [
    "gpt-5.2",
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4.1",
]

TEST_MESSAGES = [
    {"role": "user", "content": "Reply with exactly the word: ok"}
]


def check_model(model_name: str) -> None:
    print(f"\n--- Testing deployment_name = '{model_name}' ---")
    original_model_env = os.environ.get("GENAI_MODEL")
    os.environ["GENAI_MODEL"] = model_name
    try:
        client = LLMClient()
        result = client.chat(TEST_MESSAGES, max_tokens=20)
        print(f"  AVAILABLE — response: {result!r}")
    except Exception as e:
        msg = str(e)
        # Try to distinguish "model not found/configured" from other
        # failures (auth, network, quota) so the report is useful.
        lower = msg.lower()
        if any(kw in lower for kw in [
            "not found", "invalid deployment", "does not exist",
            "unknown model", "not configured", "404",
        ]):
            print(f"  NOT AVAILABLE — gateway rejected this deployment name")
            print(f"  Detail: {msg[:300]}")
        else:
            print(f"  ERROR (may not be about model availability):")
            print(f"  {msg[:300]}")
    finally:
        if original_model_env is not None:
            os.environ["GENAI_MODEL"] = original_model_env
        else:
            os.environ.pop("GENAI_MODEL", None)


if __name__ == "__main__":
    print("Checking GENAI gateway model/deployment availability...")
    print(f"Auth URL: {os.getenv('GENAI_AUTH_URL')}")
    print(f"API URL:  {os.getenv('GENAI_API_URL')}")

    for model in CANDIDATE_MODELS:
        check_model(model)

    print("\nDone. 'AVAILABLE' entries are confirmed working deployment "
          "names on this gateway right now.")
