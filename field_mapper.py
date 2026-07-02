"""
field_mapper.py
────────────────
NEW component for Iteration 1 (Indent Validation Service).

Purpose
-------
IPMS's Field API returns a raw list of `{question, answer, required}` for a
given indent. The exact set of questions, their wording, and even whether a
field appears at all VARIES between indents — confirmed across 3 real
indents (Civil/Geotechnical, Canteen/Admin, Civil/HRPGL, Civil/R&D Burma
mines). Column counts on the RFQ-stage and Vendor-Panel tables alone ranged
from 8 to 13 and 5 to 10 respectively.

Because of this, the mapper CANNOT rely on fixed field names, positions, or
counts. Instead it:
  1. Walks whatever list of {question, answer, required} it is given.
  2. Fuzzy-matches each `question` string against a registry of canonical
     concepts (each concept holds a set of known label variants/aliases
     seen so far, plus keyword fragments for partial matches).
  3. Keeps the best match above a similarity threshold; anything that
     doesn't clear the threshold is NOT dropped — it is preserved as
     "unmapped" so it can still be passed to the LLM as extra context
     (per the confirmed design: "Unmapped fields kept as extra LLM
     context, not dropped").
  4. Table-shaped fields (Vendor Panel, RFQ Stage date-plan table) are
     treated separately — as an array of {label, value} pairs per column,
     not as a single scalar field.

This module has NO dependency on exact IPMS output — it will be re-pointed
at the real Field API response shape once Pranay exposes it. For now it is
built to be driven by simulated data derived from procurement_tracker_
extractor.py's existing field vocabulary (see simulate_ipms_fields.py).
"""

from __future__ import annotations

import re
import difflib
from dataclasses import dataclass, field
from typing import Any, Optional


# ─────────────────────────────────────────────────────────────────────────
# Canonical concept registry
# ─────────────────────────────────────────────────────────────────────────
# Each canonical concept maps to a set of known label variants observed
# across real IPMS screenshots (Civil/Geotechnical, Canteen, HRPGL, Burma
# mines indents) plus generic keyword fragments for partial/fuzzy matches.
# Extend this dict as new indents reveal new phrasing — it is the single
# place field-label drift gets absorbed.

CANONICAL_FIELDS: dict[str, dict] = {
    "indent_no": {
        "aliases": ["indent no", "indent number"],
        "keywords": ["indent no"],
    },
    "rfq_no": {
        "aliases": ["rfq no", "rfq number"],
        "keywords": ["rfq no"],
    },
    "indent_submission_date": {
        "aliases": ["indent submission date"],
        "keywords": ["submission date"],
    },
    "indentor": {
        "aliases": ["indentor"],
        "keywords": ["indentor"],
    },
    "location": {
        "aliases": ["location", "ensafe location"],
        "keywords": ["location"],
    },
    "project_name": {
        "aliases": ["project name"],
        "keywords": ["project name"],
    },
    "package_description": {
        "aliases": ["package description"],
        "keywords": ["package description"],
    },
    "scope_of_work": {
        "aliases": ["brief scope of work", "scope of work"],
        "keywords": ["scope of work"],
    },
    "background_context": {
        "aliases": ["background & essentially", "background and essentially",
                    "background"],
        "keywords": ["background"],
    },
    "type_of_indent": {
        "aliases": ["type of indent"],
        "keywords": ["type of indent"],
    },
    "discipline": {
        "aliases": ["discipline", "commercial discipline"],
        "keywords": ["discipline"],
    },
    "order_or_arc": {
        "aliases": ["order/arc", "order arc"],
        "keywords": ["order/arc"],
    },
    "arc_type": {
        "aliases": ["arc type"],
        "keywords": ["arc type"],
    },
    "contract_period_months": {
        "aliases": ["period of contract (in months)", "period of contract"],
        "keywords": ["period of contract"],
    },
    "estimated_cost_crores": {
        "aliases": ["estimated cost (rs in crores)", "estimated cost"],
        "keywords": ["estimated cost"],
    },
    "contract_ceiling_value": {
        "aliases": ["contract ceiling value (rs in crores)",
                    "contract ceiling value (in inr)",
                    "contract ceiling value"],
        "keywords": ["ceiling value"],
    },
    "package_type": {
        "aliases": ["package type"],
        "keywords": ["package type"],
    },
    "fel_based_ordering": {
        "aliases": ["fel based ordering"],
        "keywords": ["fel based"],
    },
    "performance_guarantee_applicable": {
        "aliases": ["applicability of performance guarantee parameter(s)",
                    "applicability of performance guarantee"],
        "keywords": ["performance guarantee"],
    },
    "order_required_date": {
        "aliases": ["order reqd date", "order required date"],
        "keywords": ["order reqd date"],
    },
    "material_service_required_date": {
        "aliases": ["material/service reqd at site",
                    "material service reqd at site"],
        "keywords": ["reqd at site"],
    },
    "account_assignment": {
        "aliases": ["account assignment"],
        "keywords": ["account assignment"],
    },
    "job_risk_type": {
        "aliases": ["job risk type"],
        "keywords": ["job risk type"],
    },
    "job_risk_category": {
        "aliases": ["job risk category"],
        "keywords": ["job risk category"],
    },
    "sourcing": {
        "aliases": ["sourcing"],
        "keywords": ["sourcing"],
    },
    "item_category": {
        "aliases": ["item category"],
        "keywords": ["item category"],
    },
    "item_sub_category": {
        "aliases": ["item sub-category", "item sub category"],
        "keywords": ["sub-category"],
    },
    "vendor_panel": {
        "aliases": ["proposed vendor panel", "vendor panel"],
        "keywords": ["vendor panel"],
        "is_table": True,
    },
    "estimated_cost_boq": {
        "aliases": ["estimated cost (rs in crores)"],
        "keywords": ["estimated cost"],
    },
    "category_per_indent_value": {
        "aliases": ["category (as per indent value)"],
        "keywords": ["category"],
    },
    "spot_tender": {
        "aliases": ["spot tender (emergency proc)", "spot tender"],
        "keywords": ["spot tender"],
    },
    "hse_plan_available": {
        "aliases": [
            "hse plan document specific to this package for service "
            "order available",
            "hse plan available",
        ],
        "keywords": ["hse plan"],
    },
    "boq_surplus_checked": {
        "aliases": [
            "boq prepared/modified after checking surplus stock at im "
            "section",
        ],
        "keywords": ["surplus stock"],
    },
    "is_single_party": {
        "aliases": ["is it a single party"],
        "keywords": ["single party"],
    },
    "class_a_vendor": {
        "aliases": ["class a vendor"],
        "keywords": ["class a vendor"],
    },
    "term_sheet_type": {
        "aliases": ["term sheet"],
        "keywords": ["term sheet"],
    },
    "priority": {
        "aliases": ["priority"],
        "keywords": ["priority"],
    },
    "engineering_manager": {
        "aliases": ["engineering manager"],
        "keywords": ["engineering manager"],
    },
    "project_manager": {
        "aliases": ["project manager"],
        "keywords": ["project manager"],
    },
    "dept_chief_head": {
        "aliases": ["dept chief/head", "dept chief head"],
        "keywords": ["dept chief"],
    },
    "technical_spec_attached": {
        "aliases": ["technical specification"],
        "keywords": ["technical specification"],
    },
    "cost_estimate_file": {
        "aliases": ["cost estimate"],
        "keywords": ["cost estimate"],
    },
    "surplus_stock_verification_file": {
        "aliases": ["surplus stock verification"],
        "keywords": ["surplus stock verification"],
    },
    "drawings_file": {
        "aliases": ["drawings"],
        "keywords": ["drawings"],
    },
    "soil_report_file": {
        "aliases": ["soil report (for civil only)", "soil report"],
        "keywords": ["soil report"],
    },
    "indent_approval_date": {
        "aliases": ["indent approval date"],
        "keywords": ["approval date"],
    },
    "procurement_head": {
        "aliases": ["procurement head"],
        "keywords": ["procurement head"],
    },
    "procurement_manager": {
        "aliases": ["procurement manager"],
        "keywords": ["procurement manager"],
    },
    "type_of_contract": {
        "aliases": ["type of contract"],
        "keywords": ["type of contract"],
    },
    "reverse_auction": {
        "aliases": ["reverse auction(ra)", "reverse auction"],
        "keywords": ["reverse auction"],
    },
    "vendor_panel_change_requested": {
        "aliases": ["request to vendor panel change"],
        "keywords": ["vendor panel change"],
    },
    "whether_sent_for_tr": {
        "aliases": ["whether to be sent for tr"],
        "keywords": ["sent for tr"],
    },
    "requirement_of_cr": {
        "aliases": ["requirement of cr"],
        "keywords": ["requirement of cr"],
    },
    "expected_order_date": {
        "aliases": ["expected order dt", "expected order date"],
        "keywords": ["expected order"],
    },
    "negotiate_price": {
        "aliases": ["do you want to negotiate the price"],
        "keywords": ["negotiate the price"],
    },
    "negotiation_status": {
        "aliases": ["negotiation status"],
        "keywords": ["negotiation status"],
    },
}

# Tables that need row/column-based handling instead of scalar mapping.
KNOWN_TABLE_FIELDS = {"vendor_panel", "rfq_stage_dates", "technical_bid_receipt"}

FUZZY_MATCH_THRESHOLD = 0.72  # below this, field is left unmapped


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[*:]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


@dataclass
class MappedField:
    canonical_name: str
    raw_question: str
    value: Any
    required: bool
    match_score: float
    is_table: bool = False


@dataclass
class MappingResult:
    mapped: dict[str, MappedField] = field(default_factory=dict)
    unmapped: list[dict] = field(default_factory=list)
    tables: dict[str, Any] = field(default_factory=dict)

    def to_llm_context(self) -> dict:
        """
        Shape the mapping result the way it should be handed to the
        GENAI analysis step (step 7 of the production flow): mapped
        fields as clean key:value, unmapped fields preserved as raw
        question/answer pairs (NOT dropped), tables kept structured.
        """
        return {
            "mapped_fields": {
                k: v.value for k, v in self.mapped.items()
            },
            "unmapped_fields": [
                {"question": u["question"], "answer": u["answer"]}
                for u in self.unmapped
            ],
            "tables": self.tables,
        }


class FieldMapper:
    """
    Maps a raw IPMS Field API response — a list of
    {question, answer, required} dicts — to internal canonical concepts.

    Usage:
        mapper = FieldMapper()
        result = mapper.map_fields(raw_fields)
    """

    def __init__(self, extra_aliases: Optional[dict[str, list[str]]] = None):
        self.registry = {
            name: {
                "aliases": [_normalize(a) for a in cfg["aliases"]],
                "keywords": [_normalize(k) for k in cfg["keywords"]],
                "is_table": cfg.get("is_table", False),
            }
            for name, cfg in CANONICAL_FIELDS.items()
        }
        if extra_aliases:
            for canonical, aliases in extra_aliases.items():
                if canonical not in self.registry:
                    continue
                self.registry[canonical]["aliases"].extend(
                    _normalize(a) for a in aliases
                )

    def _best_match(self, question: str) -> tuple[Optional[str], float]:
        norm_q = _normalize(question)
        best_name, best_score = None, 0.0

        for name, cfg in self.registry.items():
            # Exact/near-exact alias match short-circuits with score 1.0
            for alias in cfg["aliases"]:
                if norm_q == alias:
                    return name, 1.0
                score = _similarity(norm_q, alias)
                if score > best_score:
                    best_name, best_score = name, score

            # Keyword containment — strong signal even if full string
            # similarity is low (e.g. long question text with a short
            # distinguishing keyword embedded in it)
            for kw in cfg["keywords"]:
                if kw and kw in norm_q:
                    kw_score = 0.85 + min(0.1, len(kw) / 100)
                    if kw_score > best_score:
                        best_name, best_score = name, kw_score

        return best_name, best_score

    def map_fields(self, raw_fields: list[dict]) -> MappingResult:
        """
        raw_fields: list of {"question": str, "answer": Any,
                              "required": bool}
        """
        result = MappingResult()

        for raw in raw_fields:
            question = raw.get("question", "")
            answer   = raw.get("answer")
            required = bool(raw.get("required", False))

            if not question:
                continue

            name, score = self._best_match(question)

            if name is not None and score >= FUZZY_MATCH_THRESHOLD:
                # Prefer the highest-confidence match if a concept is
                # somehow matched twice (shouldn't happen often, but
                # IPMS forms do repeat similar labels across stages,
                # e.g. "Term Sheet" appears in both PR Checklist and
                # Technical Bid stage).
                existing = result.mapped.get(name)
                if existing is None or score > existing.match_score:
                    result.mapped[name] = MappedField(
                        canonical_name=name,
                        raw_question=question,
                        value=answer,
                        required=required,
                        match_score=round(score, 3),
                        is_table=self.registry[name]["is_table"],
                    )
            else:
                result.unmapped.append({
                    "question": question,
                    "answer": answer,
                    "required": required,
                })

        return result

    def map_table(self, table_name: str, rows: list[dict]) -> dict:
        """
        Handles table-shaped sections (Vendor Panel, RFQ Stage dates,
        Technical Bid Receipt) which vary in column count/presence
        between indents (observed: 8-13 RFQ-stage columns, 5-10 vendor
        panel columns across 3 real indents). Rows are kept as-is —
        label-keyed dicts — rather than forced into fixed positions.
        """
        return {
            "table_name": table_name,
            "row_count": len(rows),
            "columns_seen": sorted({
                k for row in rows for k in row.keys()
            }),
            "rows": rows,
        }


if __name__ == "__main__":
    # Minimal smoke test using field labels taken directly from the
    # screenshots (Civil/Geotechnical NINL indent).
    sample_fields = [
        {"question": "Indent No", "answer": "25-26/39001", "required": True},
        {"question": "*Package Description :",
         "answer": "ARC for Soil investigation for the expansion project "
                    "of NINL, Kalinganagar.", "required": True},
        {"question": "*Job Risk Category :", "answer": "High",
         "required": True},
        {"question": "*Is it a single party?", "answer": "No",
         "required": True},
        {"question": "*HSE plan document specific to this package for "
                      "Service order available ?", "answer": "NA",
         "required": True},
        {"question": "Some brand-new field IPMS added last week",
         "answer": "unexpected value", "required": False},
    ]

    mapper = FieldMapper()
    out = mapper.map_fields(sample_fields)

    print("Mapped:")
    for k, v in out.mapped.items():
        print(f"  {k:30s} <- \"{v.raw_question}\" (score={v.match_score})"
              f" = {v.value!r}")

    print("\nUnmapped (kept as LLM context, not dropped):")
    for u in out.unmapped:
        print(f"  {u}")
