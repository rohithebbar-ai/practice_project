"""
document_analyzer.py  (v3.2)
──────────────────────────────
Changes from v3.1:
  - classify_rule_based() improved:
    * Excel files always content-checked first (BOQ signal detection)
    * Stronger PDF content fallbacks
    * Better coverage for project-named files
"""

import os
from typing import List, Dict, Any, Tuple

from src.llm_client import LLMClient
from src.prompts import (
    DOCUMENT_CLASSIFICATION_PROMPT_V1,
    INDENT_EXTRACTION_PROMPT_V3,
)
from src.schemas import (
    DocumentClassification,
    DocumentAnalysis,
    DocumentStructure,
    IndentExtraction,
    ProcurementSummary,
    ExtractionConfidence,
    CategoryDocumentPattern,
    RiskControl,
    ApprovalStep,
    DocumentType,
    ConfidenceLevel,
    GoodPractice,
    WeakPractice,
    Evidence,
)
from src.procurement_tracker_extractor import (
    extract_tracker_fields,
    is_procurement_tracker_doc,
)
from src.text_selector import select_relevant_text

# ── Token limits ──────────────────────────────────────────────────────────────
MAX_INPUT_TOKENS  = 28_000
MAX_OUTPUT_TOKENS = 3_500

# ── Per-document char budgets ─────────────────────────────────────────────────
DOC_TYPE_CHAR_BUDGET = {
    DocumentType.RFQ_INDENT:               6_000,
    DocumentType.BOQ:                      8_000,
    DocumentType.TECHNICAL_SPECIFICATION: 12_000,
    DocumentType.SAFETY_DOCUMENT:          6_000,
    DocumentType.APPROVAL_NOTE:            4_000,
    DocumentType.TERMSHEET:                5_000,
    DocumentType.DRAWING:                  2_000,
    DocumentType.VENDOR_DOCUMENT:          6_000,
    DocumentType.OTHER:                    5_000,
}
DEFAULT_CHAR_BUDGET = 8_000

SKIP_EXTRACTION_TYPES = {DocumentType.DRAWING}


def _count_tokens(text: str) -> int:
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        return len(text) // 4


def _compress_docs_block(
    prepared: List[Dict],
    target_tokens: int,
) -> Tuple[str, int]:
    # Step 1: tighter keyword selection (60% of current budget)
    tighter_prepared = []
    for doc in prepared:
        current_len    = len(doc["prepared_text"])
        tighter_budget = max(int(current_len * 0.6), 500)
        doc_type       = doc["classification"].document_type

        if doc.get("extraction_method") == "tracker_field_extractor":
            tighter_prepared.append(doc)
        else:
            new_text, _ = select_relevant_text(
                doc["document_text"], doc_type, tighter_budget
            )
            tighter_prepared.append({**doc, "prepared_text": new_text})

    block  = _build_docs_block(tighter_prepared)
    tokens = _count_tokens(block)
    if tokens <= target_tokens:
        return block, tokens

    # Step 2: drop lowest-value docs
    priority_order = [
        DocumentType.OTHER,
        DocumentType.DRAWING,
        DocumentType.VENDOR_DOCUMENT,
        DocumentType.APPROVAL_NOTE,
        DocumentType.TERMSHEET,
        DocumentType.SAFETY_DOCUMENT,
        DocumentType.BOQ,
        DocumentType.RFQ_INDENT,
        DocumentType.TECHNICAL_SPECIFICATION,
    ]
    surviving = list(tighter_prepared)
    for drop_type in priority_order:
        if tokens <= target_tokens:
            break
        candidates = [d for d in surviving
                      if d["classification"].document_type == drop_type]
        if candidates and len(surviving) > 1:
            surviving.remove(candidates[-1])
            block  = _build_docs_block(surviving)
            tokens = _count_tokens(block)

    if tokens <= target_tokens:
        return block, tokens

    # Step 3: equal truncation
    chars_per_doc = (target_tokens * 4) // max(len(surviving), 1)
    for doc in surviving:
        doc["prepared_text"] = doc["prepared_text"][:chars_per_doc]

    block  = _build_docs_block(surviving)
    tokens = _count_tokens(block)
    return block, tokens


def _build_docs_block(prepared: List[Dict]) -> str:
    parts = []
    for i, doc in enumerate(prepared, 1):
        parts.append(
            f"{'='*60}\n"
            f"DOCUMENT {i} OF {len(prepared)}\n"
            f"Name: {doc['document_name']}\n"
            f"Type: {doc['classification'].document_type.value}\n"
            f"Reason: {doc['classification'].short_reason}\n"
            f"{'='*60}\n"
            f"{doc['prepared_text']}\n"
        )
    return "\n".join(parts)


class DocumentAnalyzer:
    def __init__(self):
        self.llm = LLMClient()

    # ─────────────────────────────────────────────────────────────────────────
    # Classification
    # ─────────────────────────────────────────────────────────────────────────

    def classify_rule_based(
        self,
        document_name: str,
        document_text: str,
    ) -> DocumentClassification:
        """
        Rule-based classification — zero LLM calls.

        Priority order:
        1. Procurement Tracker content detection (always first)
        2. Excel files → content-based BOQ detection (always before filename)
        3. Filename keyword matching
        4. Content keyword matching (first 2000 chars)
        5. Fallback to OTHER
        """
        name = document_name.lower()
        text = document_text[:3000].lower()   # slightly more for content checks
        ext  = name.split(".")[-1] if "." in name else ""

        # ── 1. Procurement Tracker (content-based, filename-independent) ──────
        if is_procurement_tracker_doc(document_name, document_text):
            return DocumentClassification(
                document_name=document_name,
                document_type=DocumentType.RFQ_INDENT,
                short_reason="Procurement Tracker portal export detected",
                confidence=ConfidenceLevel.HIGH,
            )

        # ── 2. Excel files — content check FIRST ─────────────────────────────
        # Excel files in procurement are almost always BOQ or cost estimates
        # regardless of what they're named (project-specific names are common)
        if ext in ("xlsx", "xls", "xlsm", "xlsb"):
            boq_signals = [
                "quantity", "qty", "rate", "amount", "uom",
                "unit of measure", "item description", "item no",
                "boq", "bill of quantit", "cost estimate",
                "service type", "slno", "s.no", "sno",
                "description", "total", "supply", "erection",
                "fabrication", "labour", "material",
            ]
            hits = sum(1 for s in boq_signals if s in text)
            if hits >= 2:
                return DocumentClassification(
                    document_name=document_name,
                    document_type=DocumentType.BOQ,
                    short_reason=f"Excel file with {hits} BOQ/cost content signals",
                    confidence=ConfidenceLevel.MEDIUM,
                )

        # ── 3. Filename keyword matching ──────────────────────────────────────
        filename_rules = [
            (["boq", "bill of quantity", "bill of quantities"],
             DocumentType.BOQ, "Filename: BOQ"),

            (["rfq", "indent_rfq"],
             DocumentType.RFQ_INDENT, "Filename: RFQ"),

            (["safety", "hse", "health and safety"],
             DocumentType.SAFETY_DOCUMENT, "Filename: Safety/HSE"),

            (["term sheet", "termsheet", "term-sheet"],
             DocumentType.TERMSHEET, "Filename: Term Sheet"),

            (["drawing", "drg", "dwg"],
             DocumentType.DRAWING, "Filename: Drawing"),

            (["technical spec", "tech spec", "specification"],
             DocumentType.TECHNICAL_SPECIFICATION, "Filename: Tech Spec"),

            (["approval", "single party", "single_party"],
             DocumentType.APPROVAL_NOTE, "Filename: Approval"),

            (["cost estimate", "cost_estimate", "costing"],
             DocumentType.BOQ, "Filename: Cost Estimate"),

            (["vendor", "supplier"],
             DocumentType.VENDOR_DOCUMENT, "Filename: Vendor"),
        ]

        for keywords, doc_type, reason in filename_rules:
            if any(kw in name for kw in keywords):
                return DocumentClassification(
                    document_name=document_name,
                    document_type=doc_type,
                    short_reason=reason,
                    confidence=ConfidenceLevel.HIGH,
                )

        # TS / TSP prefix (common naming for technical specs at Tata Steel)
        fname_no_ext = name.rsplit(".", 1)[0] if "." in name else name
        if (fname_no_ext.startswith("ts") or
                fname_no_ext.startswith("tsp") or
                fname_no_ext.startswith("tsl-tsp")):
            return DocumentClassification(
                document_name=document_name,
                document_type=DocumentType.TECHNICAL_SPECIFICATION,
                short_reason="Filename starts with TS/TSP/TSL-TSP",
                confidence=ConfidenceLevel.HIGH,
            )

        # ── 4. Content keyword matching ───────────────────────────────────────
        content_rules = [
            # BOQ / cost estimate content
            (["bill of quantity", "bill of quantities",
              "item description", "unit rate", "unit of measure"],
             DocumentType.BOQ, "Content: BOQ keywords"),

            # RFQ / indent
            (["request for quotation", "request of quotation",
              "indent submission", "rfq no"],
             DocumentType.RFQ_INDENT, "Content: RFQ keywords"),

            # Technical specification
            (["technical specification", "scope of services",
              "scope of work", "shall be", "technical requirement",
              "inspection criteria"],
             DocumentType.TECHNICAL_SPECIFICATION, "Content: Tech Spec keywords"),

            # Safety / HSE
            (["health, safety", "hse requirement", "safety requirement",
              "ppe", "personal protective equipment", "hazard identification",
              "permit to work"],
             DocumentType.SAFETY_DOCUMENT, "Content: Safety keywords"),

            # Term sheet / commercial
            (["payment term", "commercial term", "liquidated damage",
              "penalty clause", "warranty period", "delivery obligation"],
             DocumentType.TERMSHEET, "Content: Term Sheet keywords"),

            # Approval note
            (["single party approval", "single source", "proprietary",
              "justification for", "approval authority"],
             DocumentType.APPROVAL_NOTE, "Content: Approval keywords"),

            # Vendor document
            (["vendor qualification", "past experience",
              "similar work", "turnover", "certification"],
             DocumentType.VENDOR_DOCUMENT, "Content: Vendor keywords"),
        ]

        for keywords, doc_type, reason in content_rules:
            hits = sum(1 for kw in keywords if kw in text)
            # Require 2+ hits for content matching to avoid false positives
            # (except for very specific phrases like "single party approval")
            threshold = 1 if any(len(kw) > 20 for kw in keywords) else 2
            if hits >= threshold:
                return DocumentClassification(
                    document_name=document_name,
                    document_type=doc_type,
                    short_reason=f"{reason} ({hits} hits)",
                    confidence=ConfidenceLevel.MEDIUM,
                )

        # ── 5. Fallback ───────────────────────────────────────────────────────
        return DocumentClassification(
            document_name=document_name,
            document_type=DocumentType.OTHER,
            short_reason="Rule-based classifier uncertain",
            confidence=ConfidenceLevel.LOW,
        )

    def classify(
        self,
        document_name: str,
        document_text: str,
    ) -> DocumentClassification:
        """LLM-based classification — edge cases only."""
        text = document_text[:12000]
        messages = [
            {"role": "system", "content": DOCUMENT_CLASSIFICATION_PROMPT_V1},
            {"role": "user",
             "content": f"Document Name:\n{document_name}\n\nDocument Content:\n{text}"},
        ]
        try:
            result = self.llm.chat_json(messages=messages, max_tokens=500)
        except Exception:
            result = {"document_type": "Other",
                      "short_reason": "LLM failed", "confidence": "Low"}
        return DocumentClassification(
            document_name=document_name,
            document_type=self._safe_document_type(result.get("document_type")),
            likely_indent_category=result.get("likely_indent_category"),
            short_reason=result.get("short_reason", ""),
            confidence=self._safe_confidence(result.get("confidence", "")),
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Per-indent extraction
    # ─────────────────────────────────────────────────────────────────────────

    def extract_indent(
        self,
        indent_id: str,
        indent_title: str,
        documents: List[Dict[str, Any]],
    ) -> IndentExtraction:
        prepared     = []
        skipped_docs = []

        # ── Prepare each document ─────────────────────────────────────────────
        for doc in documents:
            name     = doc["document_name"]
            raw_text = doc["document_text"]
            cls      = doc["classification"]
            doc_type = cls.document_type

            if doc_type in SKIP_EXTRACTION_TYPES:
                skipped_docs.append({
                    "document_name": name,
                    "document_type": doc_type,
                    "reason": "drawing_skipped",
                })
                print(f"  [SKIP]    {name} — drawing")
                continue

            if is_procurement_tracker_doc(name, raw_text):
                text   = extract_tracker_fields(raw_text)
                method = "tracker_field_extractor"
                print(
                    f"  [TRACKER] {name}: "
                    f"{len(raw_text):,} → {len(text):,} chars"
                )
            else:
                budget = DOC_TYPE_CHAR_BUDGET.get(doc_type, DEFAULT_CHAR_BUDGET)
                text, stats = select_relevant_text(raw_text, doc_type, budget)
                method = stats.get("method", "keyword_selection")
                print(
                    f"  [SELECT]  {name} ({doc_type.value}): "
                    f"{stats.get('chars_before', len(raw_text)):,} → "
                    f"{stats.get('chars_after', len(text)):,} chars | "
                    f"{stats.get('selected_paragraphs', '?')}/"
                    f"{stats.get('total_paragraphs', '?')} paragraphs"
                )

            prepared.append({
                **doc,
                "prepared_text":     text,
                "extraction_method": method,
            })

        if not prepared:
            print(f"  [WARN] No processable documents for {indent_id}")
            return self._empty_indent_extraction(
                indent_id, indent_title, skipped_docs
            )

        # ── Build docs block ──────────────────────────────────────────────────
        docs_block    = _build_docs_block(prepared)
        system_prompt = INDENT_EXTRACTION_PROMPT_V3
        user_prefix   = (
            f"Indent ID: {indent_id}\n"
            f"Indent Title: {indent_title}\n"
            f"Total documents: {len(prepared)}\n\n"
        )
        input_tokens = _count_tokens(system_prompt + user_prefix + docs_block)

        print(
            f"\n  [TOKENS] {indent_id}: "
            f"~{input_tokens:,} input tokens "
            f"(limit {MAX_INPUT_TOKENS:,})"
        )

        # ── Adaptive compression if over limit ────────────────────────────────
        if input_tokens > MAX_INPUT_TOKENS:
            print(
                f"  [COMPRESS] Over limit — compressing "
                f"({input_tokens:,} → target {MAX_INPUT_TOKENS:,})"
            )
            target     = MAX_INPUT_TOKENS - _count_tokens(
                system_prompt + user_prefix
            )
            docs_block, input_tokens = _compress_docs_block(prepared, target)
            print(f"  [COMPRESS] After: ~{input_tokens:,} tokens")

        # ── LLM call ──────────────────────────────────────────────────────────
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prefix + docs_block},
        ]

        try:
            result = self.llm.chat_json(
                messages=messages,
                max_tokens=MAX_OUTPUT_TOKENS,
            )
        except Exception as e:
            print(f"  [ERROR] LLM call failed for {indent_id}: {e}")
            result = {}

        # ── Parse result ──────────────────────────────────────────────────────
        return self._parse_indent_result(
            indent_id=indent_id,
            indent_title=indent_title,
            result=result,
            prepared=prepared,
            skipped_docs=skipped_docs,
            input_tokens=input_tokens,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_indent_result(
        self,
        indent_id: str,
        indent_title: str,
        result: dict,
        prepared: List[Dict],
        skipped_docs: List[Dict],
        input_tokens: int,
    ) -> IndentExtraction:

        ps_raw = result.get("procurement_summary", {}) or {}
        procurement_summary = ProcurementSummary(
            procurement_type        = ps_raw.get("procurement_type"),
            package_description     = ps_raw.get("package_description"),
            scope_of_work           = ps_raw.get("scope_of_work"),
            location                = ps_raw.get("location"),
            discipline              = ps_raw.get("discipline"),
            estimated_cost_crores   = ps_raw.get("estimated_cost_crores"),
            contract_period_months  = ps_raw.get("contract_period_months"),
            order_required_date     = ps_raw.get("order_required_date"),
            job_risk_category       = ps_raw.get("job_risk_category"),
            is_single_party         = ps_raw.get("is_single_party"),
            vendor_panel            = ps_raw.get("vendor_panel"),
            vendor_count            = str(ps_raw.get("vendor_count"))
                                      if ps_raw.get("vendor_count") is not None
                                      else None,
            term_sheet_type         = ps_raw.get("term_sheet_type"),
            technical_spec_attached = ps_raw.get("technical_spec_attached"),
            hse_plan_available      = ps_raw.get("hse_plan_available"),
            boq_surplus_checked     = ps_raw.get("boq_surplus_checked"),
            approval_authority      = ps_raw.get("approval_authority"),
            indent_approval_date    = ps_raw.get("indent_approval_date"),
            procurement_head        = ps_raw.get("procurement_head"),
            document_types_present  = ps_raw.get("document_types_present", []),
            missing_documents       = ps_raw.get("missing_documents", []),
        )

        doc_results = result.get("documents", [])
        documents   = []

        for i, doc in enumerate(prepared):
            raw    = doc_results[i] if i < len(doc_results) else {}
            ds_raw = raw.get("document_structure")

            document_structure = None
            if ds_raw and isinstance(ds_raw, dict):
                try:
                    document_structure = DocumentStructure(
                        sections_found            = ds_raw.get("sections_found", []),
                        follows_standard_template = ds_raw.get("follows_standard_template"),
                        structure_quality         = ds_raw.get("structure_quality"),
                        logical_sequence          = ds_raw.get("logical_sequence"),
                        missing_sections          = ds_raw.get("missing_sections", []),
                        notable_pattern           = ds_raw.get("notable_pattern"),
                    )
                except Exception:
                    document_structure = None

            documents.append(DocumentAnalysis(
                document_name           = doc["document_name"],
                document_type           = doc["classification"].document_type,
                document_summary        = raw.get("document_summary", ""),
                key_information         = raw.get("key_information", {}),
                good_practices_observed = [
                    GoodPractice.model_validate(p)
                    for p in raw.get("good_practices_observed", [])
                    if isinstance(p, dict)
                ],
                weak_or_missing_items   = [
                    WeakPractice.model_validate(w)
                    for w in raw.get("weak_or_missing_items", [])
                    if isinstance(w, dict)
                ],
                document_structure = document_structure,
                extraction_method  = doc.get("extraction_method", ""),
                char_budget_used   = len(doc.get("prepared_text", "")),
            ))

        for skipped in skipped_docs:
            documents.append(DocumentAnalysis(
                document_name     = skipped["document_name"],
                document_type     = skipped["document_type"],
                document_summary  = "Drawing — skipped LLM extraction",
                extraction_method = skipped["reason"],
            ))

        good_practices = [
            GoodPractice.model_validate(p)
            for p in result.get("good_practices", [])
            if isinstance(p, dict)
        ]
        weak_items = [
            WeakPractice.model_validate(w)
            for w in result.get("weak_items", [])
            if isinstance(w, dict)
        ]

        risk_controls = []
        for rc in result.get("risk_controls", []):
            if not isinstance(rc, dict):
                continue
            ev_raw = rc.get("evidence", {}) or {}
            try:
                risk_controls.append(RiskControl(
                    risk_area = rc.get("risk_area", ""),
                    risk      = rc.get("risk", ""),
                    control   = rc.get("control", ""),
                    evidence  = Evidence(
                        source_document  = ev_raw.get("source_document", ""),
                        source_location  = ev_raw.get("source_location"),
                        evidence_snippet = ev_raw.get("evidence_snippet"),
                        confidence       = self._safe_confidence(
                            ev_raw.get("confidence", "")
                        ),
                    ),
                ))
            except Exception:
                continue

        approval_flow = []
        for step in result.get("approval_flow", []):
            if not isinstance(step, dict):
                continue
            try:
                approval_flow.append(ApprovalStep(
                    role    = step.get("role", ""),
                    name    = step.get("name"),
                    date    = step.get("date"),
                    remarks = step.get("remarks"),
                ))
            except Exception:
                continue

        recommendations = [
            r for r in result.get("recommendations", [])
            if isinstance(r, str)
        ]

        category_document_patterns = []
        for cdp in result.get("category_document_patterns", []):
            if not isinstance(cdp, dict):
                continue
            try:
                category_document_patterns.append(CategoryDocumentPattern(
                    procurement_type   = cdp.get("procurement_type", ""),
                    document_type      = cdp.get("document_type", ""),
                    pattern_observed   = cdp.get("pattern_observed", ""),
                    quality_assessment = cdp.get("quality_assessment"),
                    recommendation     = cdp.get("recommendation"),
                ))
            except Exception:
                continue

        ec_raw = result.get("extraction_confidence", {}) or {}
        extraction_confidence = ExtractionConfidence(
            level  = self._safe_confidence(ec_raw.get("level", "Medium")),
            reason = ec_raw.get("reason", ""),
        )

        return IndentExtraction(
            indent_id                  = indent_id,
            indent_title               = indent_title,
            procurement_summary        = procurement_summary,
            documents                  = documents,
            good_practices             = good_practices,
            weak_items                 = weak_items,
            risk_controls              = risk_controls,
            approval_flow              = approval_flow,
            recommendations            = recommendations,
            category_document_patterns = category_document_patterns,
            extraction_confidence      = extraction_confidence,
            analyzer_metadata          = {
                "prompt_version":  "v3.2",
                "llm_model":       os.getenv("GENAI_MODEL", "gpt-4o-mini"),
                "input_tokens":    input_tokens,
                "docs_processed":  len(prepared),
                "docs_skipped":    len(skipped_docs),
            },
        )

    def _empty_indent_extraction(
        self,
        indent_id: str,
        indent_title: str,
        skipped_docs: List[Dict],
    ) -> IndentExtraction:
        documents = [
            DocumentAnalysis(
                document_name     = d["document_name"],
                document_type     = d["document_type"],
                document_summary  = f"Skipped: {d['reason']}",
                extraction_method = d["reason"],
            )
            for d in skipped_docs
        ]
        return IndentExtraction(
            indent_id         = indent_id,
            indent_title      = indent_title,
            documents         = documents,
            analyzer_metadata = {
                "prompt_version": "v3.2",
                "docs_processed": 0,
            },
        )

    def _safe_document_type(self, value):
        if not value:
            return DocumentType.OTHER
        for item in DocumentType:
            if item.value.lower() == str(value).lower():
                return item
        return DocumentType.OTHER

    def _safe_confidence(self, value):
        if not value:
            return ConfidenceLevel.NOT_FOUND
        for item in ConfidenceLevel:
            if item.value.lower() == str(value).lower():
                return item
        return ConfidenceLevel.NOT_FOUND
