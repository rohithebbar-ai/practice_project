"""
test_llm.py
───────────
Quick test to verify LLM connection works from terminal.
Run: python test_llm.py
"""
from src.llm_client import LLMClient

print("Testing LLM connection...")

llm = LLMClient()

# Test 1: Simple JSON response
try:
    result = llm.chat_json(
        messages=[
            {
                "role": "system",
                "content": 'Return only this exact JSON: {"status": "ok", "message": "LLM working"}'
            },
            {
                "role": "user",
                "content": "Return the JSON now."
            }
        ],
        max_tokens=50
    )
    print(f"SUCCESS: {result}")
except Exception as e:
    print(f"FAILED: {e}")
