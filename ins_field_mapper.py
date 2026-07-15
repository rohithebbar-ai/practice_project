"""
ins_field_mapper.py
──────────────────────
Replaces field_mapper.py's fuzzy-matching approach for the REAL
IPMS contract confirmed directly from Pranay's document (the one with
actual DB column names: INS_NO, INS_LOC_CD, INS_HSE, etc.).

Why this replaces fuzzy matching, not extends it:
--------------------------------------------------
field_mapper.py existed to handle an assumed IPMS Field API shape —
a list of {question, answer, required} pairs with free-text UI
labels ("Job Risk Category", "HSE plan document specific to this
package...") that could vary in wording between indents. That's a
real problem worth fuzzy-matching.

Pranay's confirmed contract is different: the POST /check-adequacy
body contains the full set of INS_* fields directly, as fixed,
stable JSON keys HE controls. There's no free-text label to fuzzy
match against — "INS_HSE" is always spelled "INS_HSE". A direct
dictionary lookup is the correct tool here, not a similarity engine.

field_mapper.py's fuzzy engine is NOT deleted — it may still be
useful if IPMS's Field API is ever exposed as a separate, more
dynamic endpoint later — but it is NOT what runs for this real
integration. This module is what runs instead.

This module maps INS_* keys directly onto the same canonical concept
names field_mapper.py used to produce, so requirement_inference.py
needs ZERO changes — it already reads canonical names like
"job_risk_category", "hse_plan_available", "discipline", etc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# INS_* key -> canonical concept name (direct, exact mapping — no
# fuzzy matching needed since these keys are fixed by Pranay's DB
# schema, not free-text UI labels).
INS_FIELD_MAP: dict[str, str] = {
    "INS_NO":                  "indent_no",
    "INS_FY_YR":                "indent_fy_yr",
    "INS_LOC_CD":                "location",
    "INS_PARAMETER":              "parameter",
    "INS_ORD_REQ_DT":              "order_required_date",
    "INS_MAT_REQ_DT":              "material_service_required_date",
    "INS_EXP_VALUE":              "estimated_cost_crores",
    "INS_PROJ_ID":                "project_id",
    "INS_ACTIVITY_ID":             "activity_id",
    "INS_PROJ_NAME":               "project_name",
    "INS_TYPE":                  "type_of_indent",
    "INS_DISCIPLINE":              "discipline",
    "INS_CATEGORY":               "category_per_indent_value",
    "INS_ACNT_ASSIGN":             "account_assignment",
    "INS_DESC":                  "package_description",
    "INS_REMARKS":                "remarks",
    "INS_TS_PATH":                "technical_spec_attached",
    "INS_TS_GUID":                "technical_spec_guid",
    "INS_COST_EST_PATH":           "cost_estimate_file",
    "INS_COST_EST_GUID":           "cost_estimate_guid",
    "INS_PRIORITY":               "priority",
    "INS_IND_SUB_DT":              "indent_submission_date",
    "INS_IND_SUB_ID":              "indentor",
    "INS_STATUS":                "indent_status",
    "INS_RFQ_NO":                "rfq_no",
    "INS_RFQ_FINYR":              "rfq_fy_yr",
    "INS_HEAD":                  "commercial_head",
    "INS_PROC_MGR":               "procurement_manager",
    "INS_ADD_REMARKS":             "additional_remarks",
    "INS_RETURN_REMARKS":           "return_remarks",
    "INS_PROJ_HEAD":              "procurement_head",
    "INS_RISK_CAT":               "job_risk_category",
    "INS_PREBID":                "prebid_tagging",
    "INS_SCOPE_OF_WORK":            "scope_of_work",
    "INS_HSE":                  "hse_plan_available",
    "INS_SURPLUS":                "boq_surplus_checked",
    "INS_SINGLE_PARTY":            "is_single_party",
    "INS_SINGLE_PARTY_PATH":        "single_party_justification_file",
    "INS_SINGLE_PARTY_GUID":        "single_party_justification_guid",
    "INS_HSE_PATH":               "hse_plan_file",
    "INS_HSE_GUID":               "hse_plan_guid",
    "INS_CHIEF":                 "project_head",
    "INS_ITEM_CAT":               "item_category",
    "INS_ENGG_MGR":               "engineering_manager",
    "INS_ENS_LOC_CD":              "ensafe_location",
    "INS_SPOT_TENDER":             "spot_tender",
    "INS_SPOT_FILENAME":           "spot_tender_file",
    "INS_SPOT_GUID":              "spot_tender_guid",
    "INS_WRENCH_PROJ_ID":          "wrench_project_id",
    "INS_WRENCH_TASK_ID":          "wrench_task_id",
    "INS_ORD_TYPE":               "order_type",
    "INS_ARC_PERIOD":             "contract_period_months",
    "INS_CEILING_VALUE":           "contract_ceiling_value",
    "INS_IS_FEL":                "fel_based_ordering",
    "INS_TERMSHEET_SNO":           "term_sheet_type",
    "INS_CONTRACT_TYPE":           "type_of_contract",
    "INS_ARC_TYPE":               "arc_type",
    "INS_ARC_MULTI_LOC":           "arc_multi_location",
    "INS_IMPORT_PCKG_TYPE":         "import_package_type",
    "INS_COM_DISC":               "commercial_discipline",
    "INS_VL_CAT":                "vendor_loading_category",
    "INS_VL_SUBCAT":              "vendor_loading_subcategory",
    "INS_VL_CAT_TEXT":             "vendor_loading_category_text",
    "INS_VL_SUBCAT_TEXT":           "vendor_loading_subcategory_text",
    "INS_JOB_RISK_TYPE":           "job_risk_type",
    "INS_PG_APP":                "performance_guarantee_applicable",
    "INS_BRIEF_SCOPE":             "brief_scope",
    "INS_SURPLUS_PATH":            "surplus_stock_verification_file",
    "INS_SURPLUS_GUID":            "surplus_stock_verification_guid",
    "INS_DRWNG_PATH":             "drawings_file",
    "INS_DRWNG_GUID":             "drawings_guid",
    "INS_SOIL_PATH":              "soil_report_file",
    "INS_SOIL_GUID":              "soil_report_guid",
    "INS_REASON_SINGLE_PARTY":       "single_party_reason",
    "INS_IS_CLASSC_VENDOR":         "class_a_vendor",
}

# Fields that carry a document GUID + path pair — used to build the
# attachment-fetch list. Each tuple is (guid_field, path_field,
# human-readable document label for logging/classification hints).
DOCUMENT_GUID_FIELDS: list[tuple[str, str, str]] = [
    ("INS_TS_GUID", "INS_TS_PATH", "Technical Specification"),
    ("INS_COST_EST_GUID", "INS_COST_EST_PATH", "Cost Estimate"),
    ("INS_SINGLE_PARTY_GUID", "INS_SINGLE_PARTY_PATH", "Single Party Justification"),
    ("INS_HSE_GUID", "INS_HSE_PATH", "HSE Document"),
    ("INS_SPOT_GUID", "INS_SPOT_FILENAME", "Spot Tender Document"),
    ("INS_SURPLUS_GUID", "INS_SURPLUS_PATH", "Surplus Stock Verification"),
    ("INS_DRWNG_GUID", "INS_DRWNG_PATH", "Drawing"),
    ("INS_SOIL_GUID", "INS_SOIL_PATH", "Soil Report"),
]


# Canonical fields treated as mandatory for the direct-gap check in
# requirement_inference.py. Pranay's INS_* schema doesn't carry a
# per-field "required" flag the way the old {question,answer,required}
# shape did, so this list is a best-effort approximation based on
# which fields showed a `*` in the IPMS UI screenshots reviewed
# earlier (Package Description, Discipline, Estimated Cost, Technical
# Spec, etc.). CONFIRM WITH PRANAY which INS_* columns are actually
# NOT NULL / mandatory in the real DB schema — this list may need
# correcting once he confirms.
REQUIRED_CANONICAL_FIELDS: set[str] = {
    "package_description",
    "discipline",
    "estimated_cost_crores",
    "order_required_date",
    "job_risk_category",
    "is_single_party",
    "technical_spec_attached",
    "cost_estimate_file",
    "type_of_indent",
    "procurement_head",
}


@dataclass
class MappedField:
    canonical_name: str
    raw_key: str
    value: Any
    required: bool = False

    @property
    def raw_question(self) -> str:
        """
        Alias for raw_key — requirement_inference.py's direct-gap
        check was written against field_mapper.py's MappedField,
        which used `raw_question` (from the old {question, answer,
        required} shape). This keeps requirement_inference.py
        unchanged rather than editing it just for a naming difference.
        """
        return self.raw_key


@dataclass
class MappingResult:
    mapped: dict[str, MappedField] = field(default_factory=dict)
    unmapped: list[dict] = field(default_factory=list)

    def to_llm_context(self) -> dict:
        return {
            "mapped_fields": {k: v.value for k, v in self.mapped.items()},
            "unmapped_fields": self.unmapped,
        }


def map_ins_fields(raw: dict) -> MappingResult:
    """
    Direct dictionary mapping — no fuzzy matching. raw is the INS_*
    header object straight out of the POST /check-adequacy body.

    Any key present in `raw` but NOT in INS_FIELD_MAP is preserved as
    "unmapped" rather than dropped, same principle as before: new or
    renamed fields Pranay adds later shouldn't silently disappear,
    they should surface so the map can be updated.
    """
    result = MappingResult()

    for raw_key, value in raw.items():
        canonical = INS_FIELD_MAP.get(raw_key)
        if canonical:
            result.mapped[canonical] = MappedField(
                canonical_name=canonical,
                raw_key=raw_key,
                value=value,
                required=canonical in REQUIRED_CANONICAL_FIELDS,
            )
        else:
            result.unmapped.append({"key": raw_key, "value": value})

    return result


def get_document_fetch_list(raw: dict) -> list[dict]:
    """
    Returns [{"guid": str, "path": str, "label": str}, ...] for every
    document slot that has a non-empty GUID in the request body.
    Empty/missing GUIDs are skipped — that slot's document wasn't
    provided for this indent, which requirement_inference.py's rules
    will independently catch as a gap where relevant (e.g. Civil with
    no soil report GUID).
    """
    fetch_list = []
    for guid_field, path_field, label in DOCUMENT_GUID_FIELDS:
        guid = raw.get(guid_field)
        path = raw.get(path_field)
        if guid:  # skip empty/null GUIDs — document not provided
            fetch_list.append({"guid": guid, "path": path, "label": label})
    return fetch_list


if __name__ == "__main__":
    sample = {
        "INS_NO": 39001,
        "INS_LOC_CD": "NINL",
        "INS_DISCIPLINE": "Civil",
        "INS_RISK_CAT": "High",
        "INS_HSE": "NA",
        "INS_HSE_GUID": "",
        "INS_SOIL_GUID": "abc-123-guid",
        "INS_SOIL_PATH": "SoilReport.pdf",
        "INS_SOME_NEW_FIELD_NOT_YET_MAPPED": "surprise value",
    }

    result = map_ins_fields(sample)
    print("Mapped:")
    for k, v in result.mapped.items():
        print(f"  {k:35s} <- {v.raw_key:25s} = {v.value!r}")

    print("\nUnmapped (kept, not dropped):")
    for u in result.unmapped:
        print(f"  {u}")

    print("\nDocuments to fetch:")
    for d in get_document_fetch_list(sample):
        print(f"  {d}")
