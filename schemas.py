from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator
import re


class DocumentType(str, Enum):
    RFQ_INDENT              = "RFQ / Indent Submission"
    BOQ                     = "BOQ"
    TECHNICAL_SPECIFICATION = "Technical Specification"
    APPROVAL_NOTE           = "Approval Note"
    SAFETY_DOCUMENT         = "Safety / HSE Document"
    DRAWING                 = "Drawing"
    TERMSHEET               = "Term Sheet"
    VENDOR_DOCUMENT         = "Vendor Document"
    OTHER                   = "Other"


class ConfidenceLevel(str, Enum):
    HIGH      = "High"
    MEDIUM    = "Medium"
    LOW       = "Low"
    NOT_FOUND = "Not found"


# ── Validation helpers ────────────────────────────────────────────────────────

def _has_digits(value: str) -> bool:
    return any(c.isdigit() for c in value)


def _is_date_pattern(value: str) -> bool:
    """Return True if value looks like a date."""
    return bool(re.search(
        r"\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}"  # 12-06-2026
        r"|\d{4}[\/\-]\d{2}[\/\-]\d{2}",            # 2026-06-12
        value
    ))


def _is_term_sheet_value(value: str) -> bool:
    """
    Return True if value looks like a term sheet name or class reference.
    These appear in hse_plan_available, boq_surplus_checked etc. due to
    PDF field bleeding in the Procurement Tracker.
    """
    lower = value.lower()
    return any(s in lower for s in [
        "term sheet",
        "class civil",
        "class a",
        "class b",
        "class c",
        "b class",
        "a class",
        "c class",
    ])


def _clean_yesno(value: str) -> Optional[str]:
    """
    Validate and clean a yes/no field.
    Returns cleaned value or None if invalid.

    Valid values: Yes, No, NA, N/A, Attached, Not Attached,
                  Available, Not Available, Applicable,
                  Not Applicable, Uploaded, Checked
    """
    if not value or not value.strip():
        return None

    value = value.strip()
    lower = value.lower()

    # Reject term sheet names
    if _is_term_sheet_value(value):
        return None

    # Reject dates
    if _is_date_pattern(value):
        return None

    # Reject long text (yes/no fields should be short)
    if len(value) > 60:
        # Try to extract just the yes/no part
        match = re.search(
            r"\b(yes|no|na|n/a|not\s+applicable|attached|"
            r"available|not\s+available|not\s+attached|"
            r"applicable|uploaded|checked)\b",
            lower,
        )
        if match:
            return match.group(0).title()
        return None

    # Accept known yes/no indicators
    yesno_words = [
        "yes", "no", "na", "n/a", "not applicable",
        "attached", "available", "not available",
        "not attached", "applicable", "uploaded", "checked",
    ]
    if any(word in lower for word in yesno_words):
        return value

    # Short value (≤ 30 chars) with no known word — keep it
    if len(value) <= 30:
        return value

    return None


def _clean_numeric(value: str) -> Optional[str]:
    """
    Validate a numeric/cost field.
    Must contain at least one digit.
    Returns None if no digits found.
    """
    if not value or not value.strip():
        return None
    value = value.strip()
    if not _has_digits(value):
        return None
    if _is_term_sheet_value(value):
        return None
    return value


def _clean_date(value: str) -> Optional[str]:
    """
    Validate a date field.
    Must contain at least one digit.
    Returns None if no digits found.
    """
    if not value or not value.strip():
        return None
    value = value.strip()
    if not _has_digits(value):
        return None
    return value


def _clean_technical_spec(value: str) -> Optional[str]:
    """
    Validate technical_spec_attached field.
    Valid: Yes, No, NA, Attached, a filename
    Invalid: a bare date with no filename context
    """
    if not value or not value.strip():
        return None
    value = value.strip()
    lower = value.lower()

    # Reject term sheet names
    if _is_term_sheet_value(value):
        return None

    # Reject bare dates (no filename context)
    # A date alone like "12-06-2026" is not a valid tech spec value
    if _is_date_pattern(value) and len(value) <= 12:
        return None

    # Accept known yes/no indicators
    if any(w in lower for w in [
        "yes", "no", "na", "n/a", "attached",
        "not attached", "available",
    ]):
        return value

    # Accept if it looks like a filename (has extension or slash)
    if any(ext in lower for ext in [
        ".pdf", ".docx", ".xlsx", ".doc", ".xls", "/"
    ]):
        return value

    # Accept short values
    if len(value) <= 40:
        return value

    return None


# ── Core models (unchanged) ───────────────────────────────────────────────────

class Evidence(BaseModel):
    source_document:  str
    source_location:  Optional[str] = None
    evidence_snippet: Optional[str] = None
    confidence:       ConfidenceLevel = ConfidenceLevel.NOT_FOUND


class ExtractedField(BaseModel):
    field_name: str
    value:      Optional[str] = None
    evidence:   Evidence


class GoodPractice(BaseModel):
    practice: str
    reason:   Optional[str] = None
    evidence: Evidence


class WeakPractice(BaseModel):
    issue:    str
    reason:   Optional[str] = None
    evidence: Evidence


class RiskControl(BaseModel):
    risk_area: str
    risk:      str
    control:   str
    evidence:  Evidence


class ApprovalStep(BaseModel):
    role:    str
    name:    Optional[str] = None
    date:    Optional[str] = None
    remarks: Optional[str] = None


class DocumentStructure(BaseModel):
    sections_found:            List[str] = []
    follows_standard_template: Optional[bool] = None
    structure_quality:         Optional[str] = None
    logical_sequence:          Optional[str] = None
    missing_sections:          List[str] = []
    notable_pattern:           Optional[str] = None


class DocumentClassification(BaseModel):
    document_name:          str
    document_type:          DocumentType
    likely_indent_category: Optional[str] = None
    short_reason:           str = ""
    confidence:             ConfidenceLevel


class DocumentAnalysis(BaseModel):
    document_name:           str
    document_type:           DocumentType
    document_summary:        str = ""
    key_information:         Dict[str, Any] = {}
    good_practices_observed: List[GoodPractice] = []
    weak_or_missing_items:   List[WeakPractice] = []
    document_structure:      Optional[DocumentStructure] = None
    extraction_method:       str = ""
    char_budget_used:        int = 0


# ── ProcurementSummary with field validators ──────────────────────────────────

class ProcurementSummary(BaseModel):
    procurement_type:        Optional[str] = None
    package_description:     Optional[str] = None
    scope_of_work:           Optional[str] = None
    location:                Optional[str] = None
    discipline:              Optional[str] = None
    estimated_cost_crores:   Optional[str] = None
    contract_period_months:  Optional[str] = None
    order_required_date:     Optional[str] = None
    job_risk_category:       Optional[str] = None
    is_single_party:         Optional[str] = None
    vendor_panel:            Optional[str] = None
    vendor_count:            Optional[str] = None
    term_sheet_type:         Optional[str] = None
    technical_spec_attached: Optional[str] = None
    hse_plan_available:      Optional[str] = None
    boq_surplus_checked:     Optional[str] = None
    approval_authority:      Optional[str] = None
    indent_approval_date:    Optional[str] = None
    procurement_head:        Optional[str] = None
    document_types_present:  List[str] = []
    missing_documents:       List[str] = []

    # ── Yes/No fields ─────────────────────────────────────────────────────────
    # Must be Yes/No/NA/Attached etc.
    # Rejects: term sheet names, dates, long text

    @field_validator("hse_plan_available", mode="before")
    @classmethod
    def validate_hse_plan(cls, v):
        if v is None: return None
        return _clean_yesno(str(v))

    @field_validator("boq_surplus_checked", mode="before")
    @classmethod
    def validate_boq_surplus(cls, v):
        if v is None: return None
        return _clean_yesno(str(v))

    @field_validator("is_single_party", mode="before")
    @classmethod
    def validate_single_party(cls, v):
        if v is None: return None
        return _clean_yesno(str(v))

    # ── Technical spec — special handling ────────────────────────────────────
    # Rejects bare dates and term sheet names
    # Accepts: Yes/No/NA/Attached/filenames

    @field_validator("technical_spec_attached", mode="before")
    @classmethod
    def validate_tech_spec(cls, v):
        if v is None: return None
        return _clean_technical_spec(str(v))

    # ── Numeric fields ────────────────────────────────────────────────────────
    # Must contain digits

    @field_validator("estimated_cost_crores", mode="before")
    @classmethod
    def validate_cost(cls, v):
        if v is None: return None
        return _clean_numeric(str(v))

    @field_validator("vendor_count", mode="before")
    @classmethod
    def validate_vendor_count(cls, v):
        if v is None: return None
        return _clean_numeric(str(v))

    # ── Date fields ───────────────────────────────────────────────────────────
    # Must contain digits

    @field_validator("indent_approval_date", mode="before")
    @classmethod
    def validate_approval_date(cls, v):
        if v is None: return None
        return _clean_date(str(v))

    @field_validator("order_required_date", mode="before")
    @classmethod
    def validate_order_date(cls, v):
        if v is None: return None
        return _clean_date(str(v))

    # ── vendor_panel — must not be a term sheet name ──────────────────────────

    @field_validator("vendor_panel", mode="before")
    @classmethod
    def validate_vendor_panel(cls, v):
        if v is None: return None
        v = str(v).strip()
        if _is_term_sheet_value(v):
            return None
        return v

    # ── term_sheet_type — accept term sheet names, reject dates ──────────────

    @field_validator("term_sheet_type", mode="before")
    @classmethod
    def validate_term_sheet_type(cls, v):
        if v is None: return None
        v = str(v).strip()
        # Dates are not valid term sheet types
        if _is_date_pattern(v) and len(v) <= 12:
            return None
        return v


# ── Remaining models (unchanged) ─────────────────────────────────────────────

class ExtractionConfidence(BaseModel):
    level:  ConfidenceLevel = ConfidenceLevel.MEDIUM
    reason: str = ""


class CategoryDocumentPattern(BaseModel):
    procurement_type:   str
    document_type:      str
    pattern_observed:   str
    quality_assessment: Optional[str] = None
    recommendation:     Optional[str] = None


class IndentExtraction(BaseModel):
    indent_id:                  str
    indent_title:               Optional[str] = None
    procurement_summary:        ProcurementSummary = Field(
        default_factory=ProcurementSummary
    )
    documents:                  List[DocumentAnalysis] = []
    good_practices:             List[GoodPractice] = []
    weak_items:                 List[WeakPractice] = []
    risk_controls:              List[RiskControl] = []
    approval_flow:              List[ApprovalStep] = []
    recommendations:            List[str] = []
    category_document_patterns: List[CategoryDocumentPattern] = []
    extraction_confidence:      ExtractionConfidence = Field(
        default_factory=ExtractionConfidence
    )
    analyzer_metadata:          Dict[str, Any] = {}


class IndentSummary(BaseModel):
    indent_id:               str
    documents_processed:     List[str]
    document_types_found:    List[str]
    fields_found:            List[str]
    good_practices_observed: List[str]
    weak_or_missing_items:   List[str]
    document_level_files:    List[str]
