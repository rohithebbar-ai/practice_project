"""
main.py
────────
Minimal FastAPI entrypoint for the Indent Validation Service, wrapping
your existing pipeline modules (document_analyzer, indent_comparator,
field_mapper, requirement_inference) behind the API contract confirmed
in the architecture doc:

    POST /check-adequacy { indent_id, domain }
    -> { analysis_id, status: "processing" }   (returned immediately)

This is a STARTING skeleton, not a finished service — it shows the
shape Cloud Run expects and where your existing modules plug in. You
will need to fill in:
  - _fetch_fields_from_ipms()      (real IPMS Field API client, once
                                     Pranay exposes it — for now this
                                     can call simulate_ipms_fields.py)
  - _fetch_attachments()           (SharePoint OAuth client)
  - the actual async job dispatch (Cloud Run request-response is
    synchronous per request by default; for a real "processing" status
    you'd typically push to Cloud Tasks/Pub-Sub and have a worker call
    back into IPMS, or just make this endpoint block and return the
    full result directly if response times stay under Cloud Run's
    request timeout — simplest option for Iteration 1)

Run locally:
    pip install fastapi uvicorn
    uvicorn main:app --reload --port 8080

Cloud Run will set the PORT env var itself — see Dockerfile.
"""

from __future__ import annotations

import os
import json
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from field_mapper import FieldMapper
from requirement_inference import infer_requirements
# from src.document_analyzer import DocumentAnalyzer          # existing
# from src.indent_comparator import compare_indent_to_standard # existing

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("indent-validation-service")

app = FastAPI(title="Indent Validation Service", version="1.0")

# ── Standards are loaded into memory at startup, keyed by domain ───────────
# The JSON files themselves are NOT exposed as an API — they are internal
# data this service reads once at boot. IPMS never fetches them directly;
# it only ever calls /check-adequacy and gets back an analysis result.
#
# Storage: GCS, not baked into the container image, because:
#   - Cloud Run images should stay small/fast to cold-start
#   - the standard is rebuilt periodically (15 new indents / 30 days) —
#     you don't want to rebuild+redeploy the container just to pick up
#     a refreshed standard; re-uploading to GCS and restarting revisions
#     (or a periodic in-process refresh) is much cheaper.
#
# GCS bucket layout expected:
#   gs://YOUR_BUCKET/standards/civil_standard.json
#   gs://YOUR_BUCKET/standards/electromech_standard.json

STANDARDS_BUCKET = os.environ.get("STANDARDS_BUCKET", "your-bucket-name")
STANDARDS_PREFIX = os.environ.get("STANDARDS_PREFIX", "standards")

# domain (as sent by IPMS in the payload) -> GCS blob filename
DOMAIN_TO_STANDARD_FILE = {
    "civil": "civil_standard.json",
    "electromech": "electromech_standard.json",
}

STANDARDS: dict[str, dict] = {}  # domain -> loaded standard dict


def _load_standard_from_gcs(blob_name: str) -> dict:
    from google.cloud import storage
    client = storage.Client()
    bucket = client.bucket(STANDARDS_BUCKET)
    blob = bucket.blob(f"{STANDARDS_PREFIX}/{blob_name}")
    data = blob.download_as_text()
    return json.loads(data)


@app.on_event("startup")
def load_standards():
    """
    Loads BOTH domain standards into memory once, at container startup.
    Per Dhiraj's confirmed scope: only civil and electromech are opened
    for "Check Adequacy" right now — other domains follow the same
    route once IPMS sends them.
    """
    for domain, filename in DOMAIN_TO_STANDARD_FILE.items():
        try:
            STANDARDS[domain] = _load_standard_from_gcs(filename)
            logger.info(f"Loaded standard for domain='{domain}' "
                        f"from {filename}")
        except Exception as e:
            logger.error(f"Failed to load standard for domain='{domain}': "
                         f"{e}")
    if not STANDARDS:
        logger.warning(
            "No standards loaded at startup — check STANDARDS_BUCKET "
            "and that the GCS blobs exist."
        )


class CheckAdequacyRequest(BaseModel):
    indent_id: str
    domain: str   # "civil" | "electromech" — required, no default;
                  # this is what Pranay's payload must send so we pick
                  # the matching inferred standard


class CheckAdequacyResponse(BaseModel):
    analysis_id: str
    status: str


@app.get("/healthz")
def healthz():
    """Cloud Run / load balancer health check."""
    return {"status": "ok", "standards_loaded": list(STANDARDS.keys())}


@app.post("/check-adequacy", response_model=CheckAdequacyResponse)
def check_adequacy(req: CheckAdequacyRequest):
    if not req.indent_id:
        raise HTTPException(status_code=400, detail="indent_id is required")

    domain = req.domain.lower().strip()
    if domain not in STANDARDS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No standard loaded for domain='{domain}'. "
                f"Currently supported: {list(STANDARDS.keys())}"
            ),
        )
    standard = STANDARDS[domain]

    try:
        # 1. Fetch fields + attachments (parallel in production; sequential
        #    here for clarity)
        raw_fields = _fetch_fields_from_ipms(req.indent_id)

        # 2. Field mapping (NEW component you already have)
        mapper = FieldMapper()
        mapping = mapper.map_fields(raw_fields)

        # 3. Classify documents (existing — plug in DocumentAnalyzer here)
        # classified_docs = DocumentAnalyzer().classify_rule_based(...)

        # 4. Infer requirements (NEW component you already have)
        #    domain-aware: civil vs electromech get different
        #    domain-specific rules on top of the shared universal ones
        inference = infer_requirements(mapping, domain=domain)

        # 5. Analyse via GENAI API (existing)
        # extraction = DocumentAnalyzer().extract_indent(...)

        # 6. Compare & score against the DOMAIN-MATCHED standard
        #    (existing indent_comparator.py, unchanged this iteration)
        # report = compare_indent_to_standard(extraction, standard)

        analysis_id = f"analysis_{req.indent_id}"

        # The service does NOT write to the DB — IPMS persists.
        # Full result would be returned to IPMS here (or pushed to a
        # callback URL if you go the async-job route).

        return CheckAdequacyResponse(analysis_id=analysis_id, status="complete")

    except Exception as e:
        logger.exception(f"check_adequacy failed for {req.indent_id}")
        raise HTTPException(status_code=500, detail=str(e))


def _fetch_fields_from_ipms(indent_id: str) -> list[dict]:
    """
    Placeholder — swap for a real IPMS Field API call once Pranay
    exposes it. For local testing you can point this at
    simulate_ipms_fields.py against your existing extraction JSONs.
    """
    return []
