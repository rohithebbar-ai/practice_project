import json
import os
import time

from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession
from dotenv import load_dotenv
load_dotenv()


class LLMClient:
    RETRY_STATUS_CODE = {429, 500, 502, 503, 504}

    def __init__(self):
        self.auth_url             = os.getenv("GENAI_AUTH_URL")
        self.api_url              = os.getenv("GENAI_API_URL")
        self.service_account_file = os.getenv("GENAI_SERVICE_ACCOUNT")
        self.api_key              = os.getenv("GENAI_API_KEY")
        self.adid                 = os.getenv("GENAI_ADID")
        self.model                = os.getenv("GENAI_MODEL", "gpt-4o-mini")
        self.temperature          = os.getenv("GENAI_TEMPERATURE", "0.1")

        if not all([
            self.auth_url,
            self.api_url,
            self.service_account_file,
            self.api_key,
            self.adid,
        ]):
            raise ValueError(
                "Missing required GENAI environment variables"
            )

        creds = service_account.IDTokenCredentials.from_service_account_file(
            self.service_account_file,
            target_audience=self.auth_url
        )
        self.session = AuthorizedSession(creds)

    def _build_payload(
            self,
            messages,
            max_tokens
    ):
        payload = {
            "deployment_name": self.model,
            "temperature":     self.temperature,
            "adid":            self.adid,
            "apikey":          self.api_key,
            "messages":        json.dumps(messages),  # Tata GENAI API requires string
            "max_tokens":      str(max_tokens),
        }
        return payload

    def _post_with_retry(
            self,
            payload,
            max_retries=5,
            timeout=180
    ):
        last_error = None
        for attempt in range(max_retries):
            try:
                response = self.session.post(
                    self.api_url,
                    headers={},
                    data=payload,
                    timeout=timeout
                )

                if response.status_code == 200:
                    # ── Check for plain-text quota/error messages ─────────
                    text = response.text.strip()
                    if "daily token limit exceeded" in text.lower():
                        raise RuntimeError(
                            "Daily token limit exceeded. "
                            "Wait for quota reset before rerunning."
                        )
                    if "invalid messages format" in text.lower():
                        raise RuntimeError(
                            f"Invalid messages format. "
                            f"Check payload structure. "
                            f"Response: {text[:200]}"
                        )
                    return response

                if response.status_code not in self.RETRY_STATUS_CODE:
                    raise RuntimeError(
                        f"LLM API ERROR "
                        f"{response.status_code}: "
                        f"BODY=\n{response.text}"
                    )

            except RuntimeError:
                raise   # don't retry on these, fail immediately
            except Exception as e:
                last_error = e

            sleep_seconds = 2 ** attempt
            time.sleep(sleep_seconds)

        raise RuntimeError(
            f"LLM request failed after "
            f"{max_retries} retries: {last_error}"
        )

    def _extract_text(
            self,
            response_json
    ):
        #
        # GPT/OPENAI style
        #
        try:
            return response_json["choices"][0]["message"]["content"]
        except Exception:
            pass

        #
        # Gemini style
        #
        try:
            return (
                response_json["candidates"][0]
                ["content"]["parts"][0]["text"]
            )
        except Exception:
            pass

        #
        # Generic fallback
        #
        if isinstance(response_json, dict):
            for key in ["response", "content", "text", "message"]:
                if key in response_json:
                    return response_json[key]

        raise RuntimeError(
            f"Unable to extract text from response: \n"
            f"{json.dumps(response_json, indent=2)}"
        )

    def chat(
            self,
            messages,
            max_tokens=4000
    ):
        payload  = self._build_payload(messages, max_tokens)
        response = self._post_with_retry(payload)

        try:
            response_json = response.json()
        except Exception:
            print("=" * 80)
            print("FAILED JSON PARSE")
            print("STATUS:", response.status_code)
            print(response.text[:5000])
            raise RuntimeError(
                f"Failed to parse API response as JSON. "
                f"Status: {response.status_code}"
            )

        return self._extract_text(response_json)

    def chat_json(
            self,
            messages,
            max_tokens=12000
    ):
        text = self.chat(
            messages,
            max_tokens=max_tokens
        )

        text = text.strip()

        # ── Remove markdown fences ────────────────────────────────────
        if text.startswith("```json"):
            text = text[len("```json"):].strip()
        elif text.startswith("```"):
            text = text[len("```"):].strip()

        if text.endswith("```"):
            text = text[:-3].strip()

        # ── Extract JSON object robustly ──────────────────────────────
        # Find first { and last } to handle any extra text before/after.
        # This fixes cases where LLM adds explanation text around the JSON.
        start = text.find("{")
        end   = text.rfind("}")

        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]
        elif not text.strip().endswith("}"):
            raise RuntimeError(
                "LLM response appears truncated or missing JSON.\n\n"
                f"Character length: {len(text)}\n"
                f"Last 1000 characters:\n{text[-1000:]}"
            )

        text = text.strip()

        try:
            return json.loads(text)

        except json.JSONDecodeError as e:
            start_err = max(e.pos - 500, 0)
            end_err   = min(e.pos + 500, len(text))
            raise RuntimeError(
                f"Failed to parse LLM JSON response.\n\n"
                f"JSON error: {e.msg}\n"
                f"Line: {e.lineno}\n"
                f"Column: {e.colno}\n"
                f"Position: {e.pos}\n\n"
                f"Character length: {len(text)}\n"
                f"Starts with:\n{repr(text[:300])}\n\n"
                f"Around error:\n{text[start_err:end_err]}"
            ) from e
