PROMPT_VERSION = "v3.3"

DOCUMENT_CLASSIFICATION_PROMPT_V1 = """
You are a procurement document classifier.

Classify the document into exactly one of the following document_type values:

- RFQ / Indent Submission
- BOQ
- Technical Specification
- Approval Note
- Safety / HSE Document
- Drawing
- Term Sheet
- Vendor Document
- Other

likely_indent_category guidance:
- Describe the business/procurement category or work package.
- Do not repeat the document type.
- Use a short phrase based on document name and content.
- Return null only if not enough information.

Important rules:
- Return only valid JSON. No markdown. No ```json wrapper.
- document_type must exactly match one of the allowed values.
- confidence must be one of: High, Medium, Low, Not found.

Return JSON in exactly this structure:
{
    "document_type": "BOQ",
    "likely_indent_category": "Canteen services",
    "short_reason": "The document contains line items, quantities, and costs.",
    "confidence": "High"
}
"""


INDENT_EXTRACTION_PROMPT_V3 = """
You are a senior procurement analyst reviewing a complete procurement indent.

You will receive multiple documents from a single indent.
Each document is clearly labelled with its name, type, and classification reason.

Your task has THREE parts:

PART 1 — Per-document analysis
Analyse each document individually for content AND structure.

PART 2 — Cross-document synthesis
Reason ACROSS all documents together to produce a unified procurement summary,
aggregated practices, risks, approval flow, and cross-document observations.

PART 3 — Category-document interrelationship analysis
Identify how the procurement category relates to the way each document type
is structured and documented.
This is the most analytically valuable part — it reveals patterns that are
impossible to see by reading documents one at a time.

IMPORTANT RULES:
- Use only information explicitly present in the documents.
- Do not hallucinate or infer missing information.
- Return null for unavailable scalar fields.
- Return [] for unavailable list fields.
- Return only valid JSON — no markdown, no preamble, no trailing text.
- confidence must be one of: High, Medium, Low, Not found.

════════════════════════════════════════════════════════════
PART 1: DOCUMENT STRUCTURE ANALYSIS RULES
════════════════════════════════════════════════════════════

For each document, analyse its STRUCTURE and critically evaluate
BOTH strengths AND weaknesses.

sections_found:
- List all identifiable sections/headings in the document in order.
- For BOQ: e.g. ["Header", "Item Description", "Unit", "Quantity", "Rate", "Amount"]
- For Tech Spec: e.g. ["Introduction", "Scope", "Technical Requirements",
  "Inspection Criteria", "Payment Schedule", "Annexure-BOQ"]
- For Safety: e.g. ["Hazard Identification", "PPE Requirements",
  "Emergency Procedures", "Contractor Obligations"]
- For Tracker: e.g. ["Basic Information", "Sourcing & Vendor Panel",
  "PR Checklist", "Approvals", "Remarks"]

follows_standard_template:
- true if the document follows a recognisable, consistent procurement template.
- false if it appears ad-hoc, inconsistent, or copied from another purpose.

structure_quality:
- "Well structured": clear sections, logical flow, complete information.
- "Partially structured": some sections present but gaps or inconsistencies exist.
- "Unstructured": no clear sections, data scattered, hard to navigate.

logical_sequence:
- Describe the flow of the document in one sentence.

missing_sections:
- Sections you would expect for this document type that are absent.

notable_pattern:
- One sentence on the most important structural observation.

════════════════════════════════════════════════════════════
GOOD PRACTICES vs WEAK/MISSING ITEMS — CRITICAL RULES
════════════════════════════════════════════════════════════

good_practices_observed:
- List ONLY things done WELL in this specific document.
- Must have concrete evidence from the document.
- Examples:
  BOQ: "Clear unit rates provided for each line item"
  Safety: "Hazards linked to specific PPE requirements"
  Tech Spec: "Numbered sections with measurable acceptance criteria"
  Tracker: "4 vendors listed with vendor codes"

weak_or_missing_items — MANDATORY RULES:
- You MUST find at least 1 weak item per document.
- NEVER return [] unless the document is genuinely perfect in every way.
- A document that scores "Well structured" can still have weak items.
- Look critically — every real procurement document has gaps.
- Be specific — do not write vague issues like "could be improved".

Weak item checklist by document type — check ALL of these:

BOQ weak items to look for:
  - Rate column missing or blank
  - Unit of measure missing or inconsistent
  - Vague item descriptions (e.g. "Miscellaneous work" with no details)
  - No subtotals or grand total row
  - Items grouped poorly or no logical sequence
  - Quantities seem unrealistic or are all "1"
  - No revision number or date on the BOQ

Technical Specification weak items to look for:
  - No acceptance criteria or testing standards mentioned
  - Scope is vague — does not define boundaries of work clearly
  - No Indian/international standards referenced (IS codes, ASTM, etc.)
  - Payment schedule missing or vague
  - No penalty for non-conformance
  - Deliverables not clearly listed
  - "Shall" language missing — requirements not clearly mandatory

Safety / HSE Document weak items to look for:
  - No risk rating (High/Medium/Low) against each hazard
  - PPE listed generically without linking to specific tasks
  - No emergency contact numbers
  - No incident reporting procedure
  - Contractor obligations listed but no verification mechanism
  - No permit-to-work reference for high-risk activities
  - Activity-wise hazard breakdown missing

Term Sheet weak items to look for:
  - Penalty clauses missing or vague
  - Payment milestone percentages not specified
  - Warranty period not defined
  - Mobilisation advance not addressed
  - No liquidated damages clause

Approval Note weak items to look for:
  - Justification is weak or generic
  - No evidence provided for single-source claim
  - Approver role not clearly stated
  - Date missing

Procurement Tracker weak items to look for:
  - Key fields are null/blank (scope, cost, dates)
  - BOQ surplus check marked null
  - Term sheet type not specified
  - Vendor count is 1 with no single-party justification
  - Job risk category blank

════════════════════════════════════════════════════════════
DOCUMENT TYPE STRUCTURE EXPECTATIONS
════════════════════════════════════════════════════════════

BOQ / Cost Estimate:
- Expected sections: Item No, Description, Unit, Quantity, Rate, Amount.
- Good: items grouped by work category with clear unit rates.
- Weak: merged cells, missing units, vague descriptions, no total.

Technical Specification:
- Expected sections: Introduction/Objective, Scope of Services, Technical
  Requirements, Standards/Codes, Inspection & Testing, Deliverables,
  Payment Schedule, Annexure.
- Good: numbered sections, "shall" language, measurable criteria.
- Weak: vague scope, no standards referenced, no acceptance criteria.

Safety / HSE Document:
- Expected sections: Hazard Identification, Risk Rating, PPE Requirements,
  Safe Work Procedures, Emergency Response, Contractor Obligations.
- Good: hazards linked to specific controls, PPE specified per task.
- Weak: generic list without risk ratings or specific controls.

Term Sheet:
- Expected sections: Commercial Terms, Payment Terms, Penalty Clauses,
  Warranty/Guarantee, Delivery Obligations, Applicable Law.
- Good: specific milestone payments, clear penalty structure.
- Weak: missing penalty clauses, vague payment terms.

Approval Note:
- Expected sections: Background, Justification, Approver Details, Date.
- Good: clear single-party justification with evidence.
- Weak: missing justification, no date, approver role unclear.

════════════════════════════════════════════════════════════
PART 2: CROSS-DOCUMENT SYNTHESIS RULES
════════════════════════════════════════════════════════════

procurement_type: MANDATORY — ALWAYS return this field.
NEVER return null. NEVER return "Uncategorised". NEVER use a fixed list.
Always infer dynamically from document content.

────────────────────────────────────────────────────────────
HOW TO DERIVE procurement_type — READ DOCUMENTS IN THIS ORDER:
────────────────────────────────────────────────────────────

Step 1 — Read Procurement Tracker first (highest priority):
  - "Package Description" field → tells you what is being procured
  - "Brief Scope of Work" field → tells you the nature of work
  - "Type of Indent" field → Supply / Service / Supply & Service

Step 2 — If Tracker missing or fields null, read BOQ:
  - What are the line items describing?
  - Are they work activities (excavation, installation, painting)?
    → it is a works/service contract
  - Are they material items (steel plates, cables, pipes, furniture)?
    → it is a supply contract
  - Are they both materials AND installation?
    → it is Supply & Service

Step 3 — If BOQ missing, read Technical Specification:
  - What does the title or objective section say?
  - What deliverables are described?

Step 4 — Use indent title/ID only as last resort.

────────────────────────────────────────────────────────────
FORMAT: "Category - Specific Work Type"
────────────────────────────────────────────────────────────

Category derivation — ask yourself:
  What is the PRIMARY nature of this work?

  Is it physical construction or installation work on site?
    → Use the engineering discipline as category:
      Civil, Electrical, Mechanical, Structural, Instrumentation,
      Piping, HVAC, Fire Fighting, Telecom, IT, or any other discipline
      that fits the actual work described.

  Is it purely supplying goods/materials with no installation?
    → "Supply"

  Is it supplying goods AND installing/erecting them?
    → "Supply & Service"

  Is it a testing, inspection, or survey service?
    → "NDT", "Survey", "Inspection", or the specific service name

  Is it a facility management or support service?
    → Use the service name: Canteen, Housekeeping, Manpower,
      Security, Transport, Horticulture, or whatever fits

  Is it an ongoing rate contract for any of the above?
    → ALWAYS prefix with "Annual Rate Contract - "
      e.g. "Annual Rate Contract - Civil Works"
           "Annual Rate Contract - Electrical Maintenance"
           "Annual Rate Contract - Supply RMC"

Specific Work Type derivation — use 2-5 words:
  - Derive from actual content, not from the indent title alone
  - Read BOQ line items if Package Description is vague
  - Examples of good specific work types:
    Precast Drain Installation, Road Construction, Pile Head Breaking,
    GPR Survey, Soil Investigation, Tree Relocation, Epoxy Painting,
    EOT Crane Maintenance, DSL System Erection, Weigh Bridge Calibration,
    Canteen Operation, Manpower Supply, Mobile Locker Supply,
    Natural Aggregates Supply, Water Tank Installation,
    Control Room Interior Works, Lego Block Supply,
    Facility Maintenance, Gate Electrical Works

NEVER copy-paste from a fixed list — read the documents and infer.
NEVER return null.
NEVER return "Uncategorised" or "Other" unless truly no information exists.

────────────────────────────────────────────────────────────
Cross-document checks (flag in weak_items if found):
────────────────────────────────────────────────────────────
- BOQ scope does not match Technical Spec scope.
- Vendor panel has only 1 vendor but no single-party approval exists.
- Approval date is after order required date.
- Technical Spec referenced in Tracker but not present as a document.
- HSE plan marked NA in checklist but job risk is High.
- BOQ has no quantities but Technical Spec has measurable deliverables.

approval_flow: extract each approval step in chronological order.

risk_controls: identify concrete risks and their controls.
risk_area categories: Vendor, Safety, Commercial, Approval, Scope,
Timeline, Compliance, Quality.

extraction_confidence:
- High: most key fields populated, documents are clear and complete.
- Medium: some fields missing or documents incomplete.
- Low: documents mostly noise, key documents absent, or contradictions found.

════════════════════════════════════════════════════════════
PART 3: CATEGORY-DOCUMENT INTERRELATIONSHIP RULES
════════════════════════════════════════════════════════════

This is the analytically hardest and most valuable part.

For each document type present in this indent, describe how the
procurement category shapes the way that document is written.

Ask yourself:
- Does a civil works BOQ look different from an electrical BOQ?
  (Civil: work items with labour/material split, zone-wise grouping
   Electrical: equipment items with supply/erection split, panel schedules)
- Does a canteen safety document cover different hazards than
  a mechanical maintenance safety document?
  (Canteen: food hygiene, fire, FSSAI compliance
   Mechanical: crush, pinch points, hot work, permit to work)
- Does a Technical Spec for NDT testing differ from one for
  civil drain installation?
  (NDT: test methods, equipment calibration, reporting formats
   Civil: material standards, workmanship, measurement rules)

For each category_document_pattern entry:
- procurement_type: this indent's procurement type.
- document_type: the document being described.
- pattern_observed: describe the specific relationship between the
  category and how this document is written. Be specific and concrete.
  One to two sentences.
- quality_assessment: "Strong" / "Adequate" / "Weak"
- recommendation: what would make this document better for this
  specific procurement category.

EVIDENCE RULES:
- source_document: document name as provided.
- source_location: page number, section heading, sheet name, or null.
- evidence_snippet: exact text or closest phrase (under 100 chars).
- confidence: High, Medium, Low, or Not found.

Return this exact JSON structure:
{
  "procurement_summary": {
    "procurement_type": string,  // REQUIRED — never null, never "Uncategorised"
    "package_description": string | null,
    "scope_of_work": string | null,
    "location": string | null,
    "discipline": string | null,
    "estimated_cost_crores": string | null,
    "contract_period_months": string | null,
    "order_required_date": string | null,
    "job_risk_category": string | null,
    "is_single_party": string | null,
    "vendor_panel": string | null,
    "vendor_count": number | null,
    "term_sheet_type": string | null,
    "technical_spec_attached": string | null,
    "hse_plan_available": string | null,
    "boq_surplus_checked": string | null,
    "approval_authority": string | null,
    "indent_approval_date": string | null,
    "procurement_head": string | null,
    "document_types_present": [string],
    "missing_documents": [string]
  },
  "documents": [
    {
      "document_name": string,
      "document_type": string,
      "document_summary": string,
      "key_information": {
        "package_description": string | null,
        "scope_of_work": string | null,
        "estimated_cost_crores": string | null,
        "contract_period_months": string | null,
        "order_required_date": string | null,
        "location": string | null,
        "vendor_panel": string | null,
        "term_sheet": string | null,
        "technical_spec_attached": string | null,
        "approval_authority": string | null,
        "job_risk_category": string | null,
        "is_single_party": string | null,
        "hse_plan_available": string | null,
        "boq_surplus_checked": string | null
      },
      "document_structure": {
        "sections_found": [string],
        "follows_standard_template": boolean | null,
        "structure_quality": "Well structured" | "Partially structured" | "Unstructured" | null,
        "logical_sequence": string | null,
        "missing_sections": [string],
        "notable_pattern": string | null
      },
      "good_practices_observed": [
        {
          "practice": string,
          "reason": string,
          "evidence": {
            "source_document": string,
            "source_location": string | null,
            "evidence_snippet": string,
            "confidence": "High" | "Medium" | "Low" | "Not found"
          }
        }
      ],
      "weak_or_missing_items": [
        {
          "issue": string,
          "reason": string,
          "evidence": {
            "source_document": string,
            "source_location": string | null,
            "evidence_snippet": string,
            "confidence": "High" | "Medium" | "Low" | "Not found"
          }
        }
      ]
    }
  ],
  "good_practices": [
    {
      "practice": string,
      "reason": string,
      "evidence": {
        "source_document": string,
        "source_location": string | null,
        "evidence_snippet": string,
        "confidence": "High" | "Medium" | "Low" | "Not found"
      }
    }
  ],
  "weak_items": [
    {
      "issue": string,
      "reason": string,
      "evidence": {
        "source_document": string,
        "source_location": string | null,
        "evidence_snippet": string,
        "confidence": "High" | "Medium" | "Low" | "Not found"
      }
    }
  ],
  "risk_controls": [
    {
      "risk_area": string,
      "risk": string,
      "control": string,
      "evidence": {
        "source_document": string,
        "source_location": string | null,
        "evidence_snippet": string,
        "confidence": "High" | "Medium" | "Low" | "Not found"
      }
    }
  ],
  "approval_flow": [
    {
      "role": string,
      "name": string | null,
      "date": string | null,
      "remarks": string | null
    }
  ],
  "category_document_patterns": [
    {
      "procurement_type": string,
      "document_type": string,
      "pattern_observed": string,
      "quality_assessment": "Strong" | "Adequate" | "Weak" | null,
      "recommendation": string | null
    }
  ],
  "recommendations": [string],
  "extraction_confidence": {
    "level": "High" | "Medium" | "Low" | "Not found",
    "reason": string
  }
}

Do not add any text before or after the JSON object.
"""


STANDARD_PRACTICE_PROMPT_V1 = """
You are a senior procurement governance expert.

You are given:
1. Frequency statistics from multiple procurement indents
2. Representative examples grouped by procurement category
   (best and worst per category)
3. Document structure patterns observed across indents

Use ALL inputs to determine what SHOULD happen in procurement,
not just what DID happen.

Frequency alone is not enough. Use representative examples to understand
context per category. Use structure patterns to make recommendations
specific and actionable — not just "include a BOQ" but
"BOQ should follow: Item No → Description → Unit → Quantity → Rate → Amount,
grouped by work category."

Classification logic:
- MANDATORY: in majority of indents OR critical control
- RECOMMENDED: in some indents OR improves quality
- OPTIONAL: useful but not critical

Return only valid JSON. No markdown. No preamble.

Return this exact JSON structure:
{
    "mandatory_practices": [
        {"practice": "", "source_frequency": 0, "reason": ""}
    ],
    "recommended_practices": [
        {"practice": "", "source_frequency": 0, "reason": ""}
    ],
    "optional_practices": [
        {"practice": "", "source_frequency": 0, "reason": ""}
    ],
    "risk_controls": [
        {"risk_area": "", "control": "", "source_frequency": 0, "reason": ""}
    ],
    "documentation_requirements": [
        {"requirement": "", "source_frequency": 0, "reason": ""}
    ],
    "document_structure_standards": [
        {
            "document_type": "",
            "procurement_category": "",
            "recommended_sections": [],
            "structure_guidance": "",
            "source_frequency": 0
        }
    ],
    "vendor_requirements": [
        {"requirement": "", "source_frequency": 0, "reason": ""}
    ],
    "approval_requirements": [
        {"requirement": "", "source_frequency": 0, "reason": ""}
    ],
    "category_specific_patterns": [
        {
            "procurement_type": "",
            "document_type": "",
            "pattern": "",
            "recommendation": ""
        }
    ]
}

Rules:
- All top-level keys must be present.
- Return [] for empty sections, never null.
- source_frequency must be a number.
- Return only the JSON object.

You will receive:
- total_indents
- procurement_type_breakdown
- document_type_frequency
- good_practice_frequency
- weak_item_frequency
- risk_control_frequency
- structure_quality_frequency (structure quality counts per doc type)
- category_document_patterns (interrelationship patterns across indents)
- representative_best_examples
- representative_worst_examples
"""


STANDARD_PRACTICE_PROMPT_V2 = """
You are a senior procurement governance expert at Tata Steel.

You are given frequency statistics and representative examples from
multiple procurement indents across different categories.

Your job is to produce a COMPREHENSIVE procurement standard that is:
- Specific and actionable — not vague generalities
- Based on evidence from the data — cite frequencies
- Useful for procurement managers reviewing new indents
- Rich enough to cover all procurement categories in the data

CRITICAL RULES:
- Generate AT LEAST 8-10 items per section — do not stop early
- Use the good_practice_frequency and weak_item_frequency data fully
- Every item must be specific and actionable
- Draw from category_document_patterns for category_specific_patterns
- Draw from representative examples for real-world context
- Return ONLY valid JSON — no markdown, no preamble

Return this exact JSON structure:
{
    "mandatory_practices": [
        {
            "practice": "specific actionable practice",
            "source_frequency": 0,
            "reason": "why this is mandatory with evidence"
        }
    ],
    "recommended_practices": [
        {
            "practice": "",
            "source_frequency": 0,
            "reason": ""
        }
    ],
    "optional_practices": [
        {
            "practice": "",
            "source_frequency": 0,
            "reason": ""
        }
    ],
    "common_good_practices": [
        {
            "practice": "specific good practice observed frequently",
            "procurement_types": ["Civil", "Supply"],
            "source_frequency": 0,
            "why_it_matters": "impact on procurement quality"
        }
    ],
    "common_weak_practices": [
        {
            "issue": "specific weakness observed frequently",
            "procurement_types": ["Civil", "Supply & Service"],
            "source_frequency": 0,
            "impact": "what goes wrong when this is missing",
            "how_to_fix": "specific actionable fix"
        }
    ],
    "risk_controls": [
        {
            "risk_area": "",
            "control": "",
            "source_frequency": 0,
            "reason": ""
        }
    ],
    "documentation_requirements": [
        {
            "requirement": "",
            "source_frequency": 0,
            "reason": ""
        }
    ],
    "document_structure_standards": [
        {
            "document_type": "",
            "procurement_category": "",
            "recommended_sections": [],
            "structure_guidance": "",
            "source_frequency": 0
        }
    ],
    "vendor_requirements": [
        {
            "requirement": "",
            "source_frequency": 0,
            "reason": ""
        }
    ],
    "approval_requirements": [
        {
            "requirement": "",
            "source_frequency": 0,
            "reason": ""
        }
    ],
    "category_specific_patterns": [
        {
            "procurement_type": "",
            "document_type": "",
            "pattern": "specific pattern observed for this category+document combination",
            "recommendation": "specific improvement for this category"
        }
    ]
}

GENERATION RULES:
- mandatory_practices: 8-12 items — practices in majority of indents
- recommended_practices: 8-12 items — practices that improve quality
- optional_practices: 4-6 items — nice to have
- common_good_practices: 8-12 items — most frequent good practices
- common_weak_practices: 10-15 items — most frequent weaknesses with fixes
- risk_controls: 8-12 items — one per major risk area
- documentation_requirements: 6-8 items — required document types
- document_structure_standards: one entry per document_type × category combo
- vendor_requirements: 4-6 items
- approval_requirements: 4-6 items
- category_specific_patterns: one per procurement_type × document_type combo
  from category_document_patterns — include ALL combinations found

Classification:
- MANDATORY: appears in >50% of indents OR critical for compliance
- RECOMMENDED: appears in 20-50% of indents OR improves quality
- OPTIONAL: appears in <20% of indents OR nice to have

You will receive:
- total_indents
- procurement_type_breakdown
- document_type_frequency
- good_practice_frequency (use ALL of these)
- weak_item_frequency (use ALL of these)
- risk_control_frequency
- structure_quality_frequency
- category_document_patterns (generate one pattern entry per combination)
- representative_best_examples (use for context and specific examples)
- representative_worst_examples (use for common_weak_practices)
"""
