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

from ins_field_mapper import map_ins_fields, get_document_fetch_list
from requirement_inference import infer_requirements
# These now live under service/src/ — see folder-structure correction:
# document_analyzer.py, document_parser.py, text_cleaner.py must move
# from offline/src/ to service/src/, since they run on every live
# "Check Adequacy" click (step 6 of the flow), not just during offline
# standard rebuilding.
from src.document_analyzer import DocumentAnalyzer
from src.document_parser import parse_file
from src.text_cleaner import clean_document_text
from src.indent_comparator import compare_indent_to_standard

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("indent-validation-service")

app = FastAPI(title="Indent Validation Service", version="1.0")

# ── Standards are loaded into memory at startup, keyed by domain ───────────
# Loaded from GCS (not bundled in the container image) — per Dhiraj:
# "keep it modular, so we can change when we update without need to
# update the cloud run." This means updating a standard is just
# re-uploading a JSON to the bucket; no redeploy needed. The service
# only re-reads the bucket at container startup, so a new Cloud Run
# revision (or restart) is still needed to pick up a changed file —
# but no rebuild/redeploy of the image itself.
#
# The bucket is created and access-granted by Dhiraj (project owner);
# this service's own identity (its Cloud Run service account) needs
# roles/storage.objectViewer on that bucket.
#
# GCS layout expected:
#   gs://YOUR_BUCKET/standards/civil_standard.json
#   gs://YOUR_BUCKET/standards/electromech_standard.json

STANDARDS_BUCKET = os.environ.get("STANDARDS_BUCKET", "your-bucket-name")
STANDARDS_PREFIX = os.environ.get("STANDARDS_PREFIX", "")  # files sit at
                                                              # bucket root
                                                              # per Dhiraj's
                                                              # upload — no
                                                              # "standards/"
                                                              # subfolder

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
    path = f"{STANDARDS_PREFIX}/{blob_name}" if STANDARDS_PREFIX else blob_name
    blob = bucket.blob(path)
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
            "and that the GCS blobs exist, and that this service's "
            "identity has roles/storage.objectViewer on the bucket."
        )


class CheckAdequacyRequest(BaseModel):
    """
    Matches Pranay's CONFIRMED real payload shape (per his Excel
    example): a NESTED object, not flat INS_* keys at the top level.

        {
          "Header": { "INS_NO": "12", "INS_FY_YR": "25-26", ... },
          "BOQ": [ {"PBOQ_...": ...}, ... ],
          "Vendors": [ {"INV_...": ...}, ... ]
        }

    All the INS_* fields live under "Header", not at the top level —
    this corrects an earlier version of this model that assumed a
    flat structure. BOQ and Vendors are kept as separate top-level
    objects (arrays of line-item / vendor-row dicts, matching the
    "Indent BOQ Data" / "Indent Vendor Panel" tables from the PDF).

    `extra = "allow"` inside Header-handling code (not here — Header
    itself is just a dict) means any INS_* field not yet in
    ins_field_mapper.py's INS_FIELD_MAP is still preserved rather than
    dropped, same principle as before.
    """
    Header: dict
    BOQ: list[dict] = []
    Vendors: list[dict] = []


class AnalysisResult(BaseModel):
    """
    Matches section 2.2 of the architecture PDF — the full analysis
    payload, returned directly and synchronously in the /check-adequacy
    response body. Per Pranay's confirmation: no separate ack + later
    callback — the response IS the result, same as the diagram Dhiraj
    approved. This supersedes the earlier async assumption.
    """
    analysis_id: str
    indent_id: str
    domain: str
    analysis_timestamp: str
    standard_version: str | None = None
    score: float
    grade: str
    score_breakdown: dict = {}
    findings: list = []
    recommendations: list[str] = []
    missing_documents: list[str] = []
    interrelationship_issues: list[str] = []
    document_inventory: list = []


DOMAIN_ALIASES = {
    "civil": "civil",
    "electromechanical": "electromech",
    "electromech": "electromech",
    "e&i": "electromech",
    "electrical": "electromech",
}


def _derive_domain(ins_discipline: str) -> str:
    return DOMAIN_ALIASES.get(ins_discipline.strip().lower(), ins_discipline.strip().lower())


@app.get("/healthz")
def healthz():
    """Cloud Run / load balancer health check."""
    return {"status": "ok", "standards_loaded": list(STANDARDS.keys())}


@app.post("/check-adequacy", response_model=AnalysisResult)
def check_adequacy(req: CheckAdequacyRequest):
    ins_discipline = req.Header.get("INS_DISCIPLINE", "")
    ins_no = req.Header.get("INS_NO", "")

    if not ins_discipline:
        raise HTTPException(
            status_code=400,
            detail="Header.INS_DISCIPLINE is required to select a standard.",
        )

    domain = _derive_domain(ins_discipline)
    if domain not in STANDARDS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No standard loaded for domain='{domain}' "
                f"(from Header.INS_DISCIPLINE='{ins_discipline}'). "
                f"Currently supported: {list(STANDARDS.keys())}"
            ),
        )

    import uuid
    analysis_id = f"analysis_{uuid.uuid4().hex[:12]}"
    indent_id = str(ins_no)

    # Field mapping / document-GUID extraction operate on Header only
    # — that's where the INS_* keys live. BOQ and Vendors are passed
    # through separately; they're not yet consumed by
    # requirement_inference.py or the comparator beyond what
    # DocumentAnalyzer.extract_indent() does with document content —
    # worth revisiting once real BOQ/Vendors data is available to see
    # if line-item-level checks are wanted (e.g. "BOQ has no rate
    # column" was one of the weak-item checks in the extraction
    # prompt, but that currently only fires on parsed BOQ documents,
    # not structured BOQ line items sent directly like this).
    raw_fields = req.Header

    return _run_analysis(analysis_id, indent_id, domain, raw_fields)


def _run_analysis(
    analysis_id: str, indent_id: str, domain: str, raw_fields: dict
) -> AnalysisResult:
    """
    The actual work: map fields, fetch+classify documents, infer
    requirements, run GENAI extraction, compare & score. Called
    directly (synchronously) from check_adequacy() — the caller gets
    this function's return value back as the HTTP response body,
    per Pranay's confirmation that the response IS the result.
    """
    try:
        standard = STANDARDS[domain]

        # 1. Map INS_* fields directly (no fuzzy matching needed —
        #    see ins_field_mapper.py's module docstring for why)
        mapping = map_ins_fields(raw_fields)

        # 2. Documents to fetch come from GUIDs already present in
        #    the request body itself — no separate document-store
        #    listing call, per the confirmed contract.
        doc_fetch_list = get_document_fetch_list(raw_fields)

        # 3. Download + parse + classify each attachment by content —
        #    NOT by filename or upload slot.
        analyzer = DocumentAnalyzer()
        documents = []
        for doc_ref in doc_fetch_list:
            try:
                local_path, filename = _download_attachment_by_guid(
                    doc_ref["guid"], doc_ref["path"]
                )
                text, parser_metadata = parse_file(local_path)
                cleaned = clean_document_text(text)
                if len(cleaned.strip()) < 50:
                    continue
                classification = analyzer.classify_rule_based(
                    document_name=filename, document_text=cleaned,
                )
                documents.append({
                    "document_name": filename,
                    "document_text": cleaned,
                    "classification": classification,
                    "parser_metadata": parser_metadata,
                })
            except Exception as e:
                logger.warning(
                    f"Failed to fetch/parse/classify "
                    f"{doc_ref.get('label')}: {e}"
                )

        # 4. Infer requirements from mapped fields (domain-aware)
        inference = infer_requirements(mapping, domain=domain)

        # 5. Analyse via GENAI API — one LLM call for the whole indent
        if documents:
            extraction = analyzer.extract_indent(
                indent_id=indent_id, indent_title=indent_id, documents=documents,
            )
            extraction_dict = extraction.model_dump()
        else:
            logger.warning(
                f"No parseable documents for {indent_id} — comparison "
                f"will run against field data only."
            )
            extraction_dict = {
                "indent_id": indent_id, "indent_title": indent_id,
                "documents": [], "procurement_summary": {},
            }

        # 6. Compare & score against the domain-matched standard
        report = compare_indent_to_standard(extraction_dict, standard)

        import datetime
        missing_documents = list(dict.fromkeys(
            report.gaps + [g.field_or_doc for g in inference.gaps]
        ))

        result = AnalysisResult(
            analysis_id=analysis_id,
            indent_id=indent_id,
            domain=domain,
            analysis_timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            standard_version=standard.get("version") if isinstance(standard, dict) else None,
            score=report.overall_score,
            grade=report.overall_grade,
            score_breakdown=report.score_breakdown,
            findings=[
                {"category": f.category, "status": f.status,
                 "title": f.title, "detail": f.detail}
                for f in (
                    report.mandatory_findings + report.documentation_findings
                    + report.risk_findings + report.vendor_findings
                    + report.approval_findings
                )
            ],
            recommendations=report.recommendations,
            missing_documents=missing_documents,
            interrelationship_issues=report.cross_doc_issues,
            document_inventory=[
                {"file": d.get("document_name"),
                 "classified_as": d.get("document_type")}
                for d in extraction_dict.get("documents", [])
            ],
        )

        return result

    except Exception as e:
        logger.exception(f"Analysis failed for {analysis_id} "
                          f"(indent {indent_id})")
        raise HTTPException(status_code=500, detail=str(e))


def _download_attachment_by_guid(guid: str, path_hint: str | None) -> tuple[str, str]:
    """
    Downloads one attachment given its GUID (from the request body's
    INS_*_GUID fields). Returns (local_file_path, filename).

    TODO once confirmed by Pranay/IT:
      - real SharePoint/Document Store download URL pattern for a GUID
      - real auth (Azure AD app registration, client-credentials flow
        — store client ID/secret in Secret Manager, not here)
    """
    import requests
    import tempfile
    import os as _os

    base_url = os.environ.get("DOCUMENT_STORE_BASE_URL")
    token = os.environ.get("DOCUMENT_STORE_ACCESS_TOKEN")  # TODO: replace
    # with real OAuth client-credentials token acquisition.

    if not base_url or not token:
        raise RuntimeError(
            "DOCUMENT_STORE_BASE_URL / DOCUMENT_STORE_ACCESS_TOKEN not "
            "configured — cannot download attachment."
        )

    response = requests.get(
        f"{base_url}/{guid}/content",
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    response.raise_for_status()

    filename = path_hint or f"{guid}.bin"
    filename = _os.path.basename(filename)  # strip any path components
    tmp_dir = tempfile.mkdtemp(prefix="attachment_")
    local_path = _os.path.join(tmp_dir, filename)
    with open(local_path, "wb") as f:
        f.write(response.content)

    return local_path, filename
