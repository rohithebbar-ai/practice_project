# test_auth.py
import os
import google.auth.transport.requests
from google.auth import compute_engine
from google.auth.transport.requests import AuthorizedSession

def test_genai_access():
    auth_url = os.getenv("GENAI_AUTH_URL")
    api_url  = os.getenv("GENAI_API_URL")
    api_key  = os.getenv("GENAI_API_KEY")
    adid     = os.getenv("GENAI_ADID")

    print(f"Testing with auth_url={auth_url}")
    print(f"Testing with api_url={api_url}")

    request = google.auth.transport.requests.Request()
    creds = compute_engine.IDTokenCredentials(
        request,
        target_audience=auth_url,
        use_metadata_identity_endpoint=True
    )

    authed_session = AuthorizedSession(creds)

    payload = {
        "deployment_name": "gpt-4o-mini",
        "temperature": "0.1",
        "adid": adid,
        "apikey": api_key,
        "messages": '[{"role": "user", "content": "Say hello in one word."}]',
        "max_tokens": "20",
    }

    resp = authed_session.post(api_url, headers={}, data=payload, timeout=60)
    print("STATUS:", resp.status_code)
    print("BODY:", resp.text[:1000])

if __name__ == "__main__":
    test_genai_access()



FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir google-auth requests
COPY test_auth.py .
CMD ["python", "test_auth.py"]

gcloud run jobs create test-genai-auth \
  --project=tsl-generative-ai \
  --region=asia-south1 \
  --source=. \
  --service-account=svc-ipms-indent-validation@tsl-generative-ai.iam.gserviceaccount.com \
  --set-env-vars="GENAI_AUTH_URL=<gateway_url>,GENAI_API_URL=<api_url>,GENAI_API_KEY=<key>,GENAI_ADID=<adid>"


gcloud run jobs executions list --job=test-genai-auth --project=tsl-generative-ai --region=asia-south1



gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=test-genai-auth" --project=tsl-generative-ai --limit=50

    

