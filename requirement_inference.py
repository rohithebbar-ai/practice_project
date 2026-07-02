"""
requirement_inference.py
──────────────────────────

Purpose
-------
Two distinct kinds of "gap" are detected, per the confirmed production
flow (step 6):

  1. Direct gaps — a field is marked `required=true` by IPMS but its
     value is blank. This alone covers most of what you'd otherwise
     write a bespoke rule for (e.g. "Technical Specification is
     missing" or "Class A Vendor is unanswered") — IPMS already tells
     us these are mandatory, so no extra logic is needed.

  2. Inferred gaps — a field VALUE implies that some OTHER field or
     document should be present, even though IPMS itself doesn't mark
     that other field required. This is the genuinely new logic, and
     it's expressed as DATA (INFERENCE_RULES below), not as one Python
     function per rule. Examples:
       - job_risk_category = High  → HSE plan expected
       - discipline = Civil        → Soil Report expected
       - discipline = Electromech  → Electrical safety cert expected

Why a rule TABLE instead of rule FUNCTIONS
-------------------------------------------
Every one of these rules has the same shape: "IF <trigger field> has
<one of these values> THEN <expected field> should not be blank."
Writing a new `_rule_xxx()` function for every domain/document
combination doesn't scale — a dozen domains with a few document types
each would mean a few dozen near-identical functions. Instead,
INFERENCE_RULES is a list of RuleSpec entries; adding a new domain
requirement is adding one entry to that list, not writing new code.
If this list grows large enough to be awkward to edit inline, it can
be moved to a JSON/YAML file and loaded at startup — the engine
(`_evaluate_rule`) doesn't care where the specs come from.

This module consumes the output of field_mapper.py (a MappingResult),
so it only ever sees canonical field names — it has no knowledge of
IPMS's raw question wording.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


def _val(result, name: str) -> Optional[str]:
    mf = result.mapped.get(name)
    if mf is None:
        return None
    v = mf.value
    return str(v).strip() if v is not None else None


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
# Rule table — DATA, not code. Add a dict here to add a rule.
# ─────────────────────────────────────────────────────────────────────────
#
# Fields:
#   trigger_field    canonical field name whose value gates this rule
#   trigger_values   list of acceptable values (case-insensitive match)
#   expected_field   canonical field that must NOT be blank once the
#                     trigger fires; use None for rules that should
#                     always flag for review when triggered (no
#                     specific field to check, e.g. "needs a written
#                     justification somewhere, not a dedicated field")
#   domains          list of domain strings this rule applies to;
#                     None = universal (applies to every domain)
#   reason           human-readable explanation shown in the gap;
#                     {trigger_field}/{trigger_value}/{expected_field}
#                     are available as format placeholders
#   severity         "low" | "medium" | "high"
#
INFERENCE_RULES: list[dict] = [
    {
        "trigger_field": "job_risk_category",
        "trigger_values": ["high"],
        "expected_field": "hse_plan_available",
        "domains": None,
        "reason": (
            "{trigger_field} is High but {expected_field} is blank/NA "
            "— a High-risk job normally expects an HSE plan document."
        ),
        "severity": "high",
    },
    {
        "trigger_field": "is_single_party",
        "trigger_values": ["yes", "y", "true"],
        "expected_field": None,
        "domains": None,
        "reason": (
            "{trigger_field} is Yes — a single-party procurement "
            "normally requires an explicit justification, which is "
            "not a dedicated IPMS field. Check remarks/background text "
            "before flagging as missing."
        ),
        "severity": "medium",
    },
    {
        "trigger_field": "discipline",
        "trigger_values": ["civil"],
        "expected_field": "soil_report_file",
        "domains": ["civil"],
        "reason": (
            "discipline is Civil — IPMS's own Documents Upload section "
            "labels this slot 'Soil Report (for Civil Only)', implying "
            "it is expected for civil work, but no file was found."
        ),
        "severity": "medium",
    },
    {
        # Placeholder — confirm the real electromech document slot name
        # from an actual electromech screenshot (the same way
        # soil_report_file was confirmed from civil screenshots) before
        # relying on this in production.
        "trigger_field": "discipline",
        "trigger_values": [
            "electromech", "electromechanical", "e&i", "electrical",
        ],
        "expected_field": "electrical_safety_cert_file",
        "domains": ["electromech"],
        "reason": (
            "discipline is Electromechanical — an electrical safety "
            "certificate is expected for this class of work, but no "
            "file was found. UNVERIFIED: confirm the real IPMS field "
            "name for this slot."
        ),
        "severity": "medium",
    },
]


def _evaluate_rule(rule: dict, mapping_result) -> Optional[Gap]:
    trigger_value = _val(mapping_result, rule["trigger_field"])
    if trigger_value is None:
        return None

    trigger_values = rule.get("trigger_values")
    if trigger_values is not None and \
            trigger_value.strip().lower() not in trigger_values:
        return None

    expected_field = rule.get("expected_field")
    if expected_field is not None:
        expected_value = _val(mapping_result, expected_field)
        if not _is_blank(expected_value):
            return None  # expected field is present — no gap

    reason = rule["reason"].format(
        trigger_field=rule["trigger_field"],
        trigger_value=trigger_value,
        expected_field=expected_field or "",
    )

    return Gap(
        kind="inferred",
        field_or_doc=expected_field or f"{rule['trigger_field']}_followup",
        reason=reason,
        severity=rule.get("severity", "medium"),
    )


def _rules_for_domain(domain: Optional[str]) -> list[dict]:
    domain_norm = domain.strip().lower() if domain else None
    return [
        r for r in INFERENCE_RULES
        if r["domains"] is None
        or (domain_norm is not None and domain_norm in r["domains"])
    ]


def infer_requirements(
    mapping_result,
    domain: Optional[str] = None,
    rules: Optional[list[dict]] = None,
) -> InferenceResult:
    """
    Runs direct required-flag gap detection plus the declarative
    value-triggered rules in INFERENCE_RULES over a FieldMapper output.

    domain: "civil" | "electromech" | ... — selects which domain-scoped
            rules (in addition to universal ones) get evaluated. Pass
            the same domain string used to pick the matching standard
            in main.py, so gap detection and scoring stay consistent
            for the same indent.
    rules:  override the rule set entirely (mainly for testing); if
            omitted, rules are resolved from `domain` via
            `_rules_for_domain`.
    """
    active_rules = rules if rules is not None else _rules_for_domain(domain)
    out = InferenceResult()

    # 1. Direct gaps — required=true fields with blank values. This
    #    alone covers "Technical Specification missing", "Class A
    #    Vendor unanswered", "Cost Estimate missing", etc. — anything
    #    IPMS itself marks mandatory needs no separate rule.
    for name, mf in mapping_result.mapped.items():
        if mf.required and _is_blank(
            str(mf.value) if mf.value is not None else None
        ):
            out.gaps.append(Gap(
                kind="direct",
                field_or_doc=name,
                reason=(
                    f"'{mf.raw_question}' is marked required by IPMS "
                    f"but the answer is blank/NA."
                ),
                severity="high",
            ))

    # 2. Inferred gaps — declarative rule table
    for rule in active_rules:
        gap = _evaluate_rule(rule, mapping_result)
        if gap is not None:
            out.gaps.append(gap)

    # De-duplicate on (kind, field_or_doc) — an inferred gap can name
    # the same field a direct gap already caught (e.g. hse_plan_available
    # marked required AND blank, plus the high-risk rule also firing on
    # it). Keep the first occurrence; direct gaps are added first.
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

    print("=== domain=civil ===")
    inference = infer_requirements(mapping, domain="civil")
    import json
    print(json.dumps(inference.summary(), indent=2))

    print("\n=== domain=electromech ===")
    inference2 = infer_requirements(mapping, domain="electromech")
    print(json.dumps(inference2.summary(), indent=2))
