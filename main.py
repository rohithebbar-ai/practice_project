"""
main.py
────────
FastAPI entrypoint for the Indent Validation Service.

Exposes a single endpoint, POST /check-adequacy, which IPMS calls
synchronously when a user selects "Check Adequacy" on an indent. The
request body contains the indent's field data and document references
directly (see CheckAdequacyRequest below); the response contains the
full adequacy analysis (see AnalysisResult below) — there is no
separate acknowledgement step or callback.

Processing pipeline per request:
  1. Map the indent's fields to canonical concept names
     (ins_field_mapper.py)
  2. Resolve and download referenced attachments by GUID
     (_download_attachment_by_guid)
  3. Parse and classify each attachment by content, not by filename
     (document_analyzer.py)
  4. Infer additional requirements implied by field values
     (requirement_inference.py)
  5. Run GENAI extraction across all documents for the indent
     (document_analyzer.py)
  6. Compare the extraction against the domain-matched standard and
     produce a score (indent_comparator.py)

The service is stateless aside from the standards held in memory
(loaded once at startup from Cloud Storage); it does not write to any
database — the caller is responsible for persisting the result.

Known open items:
  - Attachment download (_download_attachment_by_guid) still requires
    real Document Store / SharePoint authentication details.
  - Structured BOQ and vendor-panel data arriving in the request body
    are not yet consumed by requirement_inference.py or the
    comparator beyond what document-level extraction covers.

Run locally:
    pip install fastapi uvicorn
    uvicorn main:app --reload --port 8080

Cloud Run sets the PORT env var itself — see Dockerfile.
"""

from __future__ import annotations

import os
import json
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from ins_field_mapper import map_ins_fields, get_document_fetch_list
from requirement_inference import infer_requirements
# document_analyzer.py, document_parser.py, and text_cleaner.py live
# under service/src/ rather than the offline pipeline's src/ tree,
# since they run on every live "Check Adequacy" request (document
# classification and GENAI extraction), not just during offline
# standard rebuilding.
from src.document_analyzer import DocumentAnalyzer
from src.document_parser import parse_file
from src.text_cleaner import clean_document_text
from src.indent_comparator import compare_indent_to_standard

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("indent-validation-service")

# ── Standards are loaded into memory at startup, keyed by domain ───────────
# Loaded from GCS rather than bundled into the container image, so
# that publishing an updated standard is a matter of uploading a new
# JSON file to the bucket rather than rebuilding and redeploying the
# service. The bucket is re-read at container startup, so a new
# revision or restart is needed to pick up a changed file, but not a
# rebuild of the image itself.
#
# This service's own identity (its Cloud Run service account) needs
# roles/storage.objectViewer on the standards bucket.
#
# GCS layout expected:
#   gs://YOUR_BUCKET/standards/civil_standard.json
#   gs://YOUR_BUCKET/standards/electromech_standard.json

STANDARDS_BUCKET = os.environ.get("STANDARDS_BUCKET", "your-bucket-name")
STANDARDS_PREFIX = os.environ.get("STANDARDS_PREFIX", "")  # files currently
                                                              # sit at the
                                                              # bucket root,
                                                              # not under a
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


def _load_standards() -> None:
    """
    Loads all configured domain standards into memory once, at
    container startup. Only civil and electromech are currently
    active for "Check Adequacy" — additional domains follow the same
    pattern once they're added to DOMAIN_TO_STANDARD_FILE.
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler (replaces the deprecated
    @app.on_event("startup") pattern). Code before `yield` runs once
    at container startup; code after `yield` would run at shutdown
    (none needed here).
    """
    _load_standards()
    yield


app = FastAPI(title="Indent Validation Service", version="1.0", lifespan=lifespan)


class CheckAdequacyRequest(BaseModel):
    """
    Matches the confirmed payload shape: a nested object, not flat
    INS_* keys at the top level.

        {
          "Header": { "INS_NO": "12", "INS_FY_YR": "25-26", ... },
          "BOQ": [ {"PBOQ_...": ...}, ... ],
          "Vendors": [ {"INV_...": ...}, ... ]
        }

    All INS_* fields live under "Header", not at the top level. BOQ
    and Vendors are kept as separate top-level objects (arrays of
    line-item / vendor-row dicts, matching the "Indent BOQ Data" /
    "Indent Vendor Panel" tables in the architecture specification).

    Any INS_* field under Header not yet present in
    ins_field_mapper.py's INS_FIELD_MAP is still preserved rather than
    dropped (see ins_field_mapper.py for details).
    """
    Header: dict
    BOQ: list[dict] = []
    Vendors: list[dict] = []


class AnalysisResult(BaseModel):
    """
    Matches section 2.2 of the architecture specification — the full
    analysis payload, returned directly and synchronously in the
    /check-adequacy response body. There is no separate acknowledgement
    step or later callback; the response is the result.
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
    The actual work: map fields, fetch and classify documents, infer
    requirements, run GENAI extraction, compare and score. Called
    directly (synchronously) from check_adequacy() — the caller
    receives this function's return value as the HTTP response body.
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

    TODO once real credentials and endpoint details are available:
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
