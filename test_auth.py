import os
import google.auth.transport.requests
from google.auth import compute_engine
from google.auth.transport.requests import AuthorizedSession


def test_genai_access():
    auth_url = os.getenv("GENAI_AUTH_URL")
    api_url  = os.getenv("GENAI_API_URL")
    api_key  = os.getenv("GENAI_API_KEY")
    adid     = os.getenv("GENAI_ADID")
    model    = os.getenv("GENAI_MODEL", "gpt-4o-mini")

    missing = [
        name for name, val in [
            ("GENAI_AUTH_URL", auth_url),
            ("GENAI_API_URL", api_url),
            ("GENAI_API_KEY", api_key),
            ("GENAI_ADID", adid),
        ] if not val
    ]
    if missing:
        return {"error": f"Missing env vars: {', '.join(missing)}"}

    try:
        request = google.auth.transport.requests.Request()
        creds = compute_engine.IDTokenCredentials(
            request,
            target_audience=auth_url,
            use_metadata_identity_endpoint=True
        )

        authed_session = AuthorizedSession(creds)

        payload = {
            "deployment_name": model,
            "temperature": "0.1",
            "adid": adid,
            "apikey": api_key,
            "messages": '[{"role": "user", "content": "Say hello in one word."}]',
            "max_tokens": "20",
        }

        resp = authed_session.post(api_url, headers={}, data=payload, timeout=60)

        return {
            "status_code": resp.status_code,
            "body": resp.text[:1000],
            "auth_url_used": auth_url,
        }

    except Exception as e:
        return {"error": str(e), "type": type(e).__name__}


if __name__ == "__main__":
    result = test_genai_access()
    print(result)


from fastapi import FastAPI
from test_auth import test_genai_access

app = FastAPI()


@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/test-auth")
def test_auth_endpoint():
    result = test_genai_access()
    return {"result": result}


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

gcloud run deploy test-genai-auth \
  --project=tsl-generative-ai \
  --region=asia-south1 \
  --source=. \
  --service-account=svc-ipms-indent-validation@tsl-generative-ai.iam.gserviceaccount.com \
  --set-env-vars="GENAI_AUTH_URL=https://genai-api-development-one-it-423929642383.asia-south1.run.app,GENAI_API_URL=https://tslgenaiapidev.corp.tatasteel.com/genai,GENAI_API_KEY=SGB7QI6ZVDLCL6W1,GENAI_ADID=ayfph2508h,GENAI_MODEL=gpt-4o-mini" \
  --allow-unauthenticated

gcloud run deploy ipms-indent-validation \
  --project=tsl-generative-ai \
  --region=asia-south1 \
  --source=. \
  --service-account=svc-ipms-indent-validation@tsl-generative-ai.iam.gserviceaccount.com \
  --set-env-vars="GENAI_AUTH_URL=https://genai-api-development-one-it-423929642383.asia-south1.run.app,GENAI_API_URL=https://tslgenaiapidev.corp.tatasteel.com/genai,GENAI_API_KEY=SGB7QI6ZVDLCL6W1,GENAI_ADID=ayfph2508h,GENAI_MODEL=gpt-4o-mini,GENAI_TEMPERATURE=0.1,USE_OCR=True" \
  --allow-unauthenticated


gcloud run jobs executions list --job=test-genai-auth --project=tsl-generative-ai --region=asia-south1



gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=test-genai-auth" --project=tsl-generative-ai --limit=50

    

