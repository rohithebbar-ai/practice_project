"""
requirement_inference.py
──────────────────────────
NEW component for Iteration 1 (Indent Validation Service).

Purpose
-------
Two distinct kinds of "gap" need to be detected, per the confirmed
production flow (step 6):

  1. Direct gaps — a field is marked `required=true` by IPMS but its
     value is blank. This is a simple pass-through check on the mapped
     fields.

  2. Inferred gaps — a field VALUE implies that some OTHER field or
     document should be present, even if IPMS didn't mark that other
     field required=true. E.g.:
       - job_risk_category = High  → HSE plan / safety document expected
       - is_single_party   = Yes   → single-party justification expected
       - estimated_cost_crores > threshold → CR (cost reasonability)
         stage expected to be exercised, not silently skipped
       - discipline = Civil        → Soil Report expected (civil-only
         doc slot observed directly in the IPMS Documents Upload
         section: "Soil Report (for Civil Only)")

Per Dhiraj's direction (confirmed earlier): this is intentionally basic
for Iteration 1 — required-flag gaps plus a handful of hand-written
field→doc rules, NOT an exhaustive rule engine. Deeper inference is
deferred to Iteration 2.

This module consumes the output of field_mapper.py (a MappingResult),
so it only ever sees canonical field names — it has no knowledge of
IPMS's raw question wording.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from field_mapper import MappingResult, MappedField


def _val(result: MappingResult, name: str) -> Optional[str]:
    mf = result.mapped.get(name)
    if mf is None:
        return None
    v = mf.value
    return str(v).strip() if v is not None else None


def _is_yes(value: Optional[str]) -> bool:
    return bool(value) and value.strip().lower() in ("yes", "y", "true")


def _is_blank(value: Optional[str]) -> bool:
    return value is None or value.strip() == "" or value.strip().lower() in (
        "na", "n/a", "none", "null",
    )


@dataclass
class Gap:
    kind: str            # "direct" | "inferred"
    field_or_doc: str    # canonical field name or a human doc label
    reason: str
    severity: str = "medium"   # "low" | "medium" | "high"


@dataclass
class InferenceResult:
    gaps: list[Gap] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "gap_count": len(self.gaps),
            "high_severity_count": sum(
                1 for g in self.gaps if g.severity == "high"
            ),
            "gaps": [
                {
                    "kind": g.kind,
                    "field_or_doc": g.field_or_doc,
                    "reason": g.reason,
                    "severity": g.severity,
                }
                for g in self.gaps
            ],
        }


# ─────────────────────────────────────────────────────────────────────────
# Rule definitions
# ─────────────────────────────────────────────────────────────────────────
# Each rule is a plain function(result) -> Optional[Gap] so new rules can
# be added independently without touching a giant if/elif block. Keep
# this list short and hand-written per Dhiraj's Iteration-1 scope.

def _rule_hse_plan_for_high_risk(result: MappingResult) -> Optional[Gap]:
    risk = _val(result, "job_risk_category")
    hse  = _val(result, "hse_plan_available")
    if risk and risk.strip().lower() == "high" and _is_blank(hse):
        return Gap(
            kind="inferred",
            field_or_doc="hse_plan_available",
            reason=(
                "job_risk_category is High but hse_plan_available is "
                "blank/NA — a High-risk job normally expects an HSE "
                "plan document."
            ),
            severity="high",
        )
    if risk and risk.strip().lower() == "high" and hse and \
            hse.strip().lower() == "na":
        return Gap(
            kind="inferred",
            field_or_doc="hse_plan_available",
            reason=(
                "job_risk_category is High but hse_plan_available is "
                "explicitly marked NA — worth flagging for user "
                "confirmation rather than auto-accepting."
            ),
            severity="medium",
        )
    return None


def _rule_single_party_justification(result: MappingResult) -> Optional[Gap]:
    single_party = _val(result, "is_single_party")
    remarks      = _val(result, "package_description")  # closest proxy
    if _is_yes(single_party):
        return Gap(
            kind="inferred",
            field_or_doc="single_party_justification",
            reason=(
                "is_single_party is Yes — a single-party procurement "
                "normally requires an explicit justification, which "
                "is not a dedicated IPMS field. Check remarks/background "
                "text for a justification before flagging as missing."
            ),
            severity="medium",
        )
    return None


def _rule_soil_report_for_civil(result: MappingResult) -> Optional[Gap]:
    discipline = _val(result, "discipline")
    soil       = _val(result, "soil_report_file")
    if discipline and discipline.strip().lower() == "civil" and \
            _is_blank(soil):
        return Gap(
            kind="inferred",
            field_or_doc="soil_report_file",
            reason=(
                "discipline is Civil — IPMS's own Documents Upload "
                "section labels this slot 'Soil Report (for Civil "
                "Only)', implying it is expected for civil work, but "
                "no file was found in the mapped fields."
            ),
            severity="medium",
        )
    return None


def _rule_technical_spec_present(result: MappingResult) -> Optional[Gap]:
    tech_spec = _val(result, "technical_spec_attached")
    if _is_blank(tech_spec):
        return Gap(
            kind="direct",
            field_or_doc="technical_spec_attached",
            reason="Technical Specification field/file is blank.",
            severity="high",
        )
    return None


def _rule_cost_estimate_present(result: MappingResult) -> Optional[Gap]:
    cost_file = _val(result, "cost_estimate_file")
    if _is_blank(cost_file):
        return Gap(
            kind="direct",
            field_or_doc="cost_estimate_file",
            reason="Cost Estimate file is blank.",
            severity="high",
        )
    return None


def _rule_class_a_vendor_unanswered(result: MappingResult) -> Optional[Gap]:
    # Observed directly in a real screenshot: "Class A Vendor?" left
    # with both Yes/No boxes unchecked despite being marked mandatory (*).
    mf = result.mapped.get("class_a_vendor")
    if mf is not None and mf.required and _is_blank(str(mf.value)):
        return Gap(
            kind="direct",
            field_or_doc="class_a_vendor",
            reason=(
                "Class A Vendor is marked required by IPMS but neither "
                "Yes nor No is answered."
            ),
            severity="medium",
        )
    return None


DEFAULT_RULES = [
    _rule_hse_plan_for_high_risk,
    _rule_single_party_justification,
    _rule_soil_report_for_civil,
    _rule_technical_spec_present,
    _rule_cost_estimate_present,
    _rule_class_a_vendor_unanswered,
]


def infer_requirements(
    mapping_result: MappingResult,
    rules: Optional[list] = None,
) -> InferenceResult:
    """
    Runs direct required-flag gap detection plus the hand-written
    field-value-based inference rules over a FieldMapper output.
    """
    rules = rules if rules is not None else DEFAULT_RULES
    out = InferenceResult()

    # 1. Direct gaps — required=true fields with blank values, across
    #    ALL mapped fields, not just the ones covered by hand-written
    #    rules above.
    for name, mf in mapping_result.mapped.items():
        if mf.required and _is_blank(str(mf.value) if mf.value is not None
                                      else None):
            out.gaps.append(Gap(
                kind="direct",
                field_or_doc=name,
                reason=(
                    f"'{mf.raw_question}' is marked required by IPMS "
                    f"but the answer is blank/NA."
                ),
                severity="high",
            ))

    # 2. Inferred gaps — hand-written rules
    for rule in rules:
        gap = rule(mapping_result)
        if gap is not None:
            out.gaps.append(gap)

    # De-duplicate: a field can legitimately be caught by both the
    # generic required-flag loop and a specific hand-written rule
    # (e.g. class_a_vendor, technical_spec_attached). Keep the first
    # occurrence per (kind, field_or_doc) — direct gaps are added
    # before inferred ones, so a generic direct-gap duplicate of a
    # specific direct-rule gap collapses to one entry.
    seen = set()
    deduped = []
    for g in out.gaps:
        key = (g.kind, g.field_or_doc)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(g)
    out.gaps = deduped

    return out


if __name__ == "__main__":
    from field_mapper import FieldMapper

    sample_fields = [
        {"question": "*Job Risk Category :", "answer": "High",
         "required": True},
        {"question": "*HSE plan document specific to this package for "
                      "Service order available ?", "answer": "NA",
         "required": True},
        {"question": "*Is it a single party?", "answer": "No",
         "required": True},
        {"question": "*Discipline :", "answer": "Civil", "required": True},
        {"question": "Technical Specification", "answer": "",
         "required": True},
        {"question": "*Class A Vendor?", "answer": "", "required": True},
    ]

    mapper = FieldMapper()
    mapping = mapper.map_fields(sample_fields)
    inference = infer_requirements(mapping)

    import json
    print(json.dumps(inference.summary(), indent=2))
