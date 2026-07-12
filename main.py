from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
from cross_check_engine import CrossCheckError, run_cross_check


from ai_report_generator import AITaxReportError, generate_ai_tax_report_from_file
from fact_extractor import FactExtractorError, extract_facts_from_pdf_file
from form_detector import FormDetectorError, detect_tax_form_from_file
from questionnaire import (
    QuestionnaireError,
    get_default_questionnaire,
    merge_fact_extraction_result_into_questionnaire,
)
from report_generator import ReportGeneratorError, generate_final_report
from strategy_ai_matcher import StrategyAIMatcherError, match_strategies_with_ai
from strategy_rules import StrategyRulesError, run_strategy_rules


FilingStatus = Literal["single", "married_joint", "head_of_household"]

MAX_UPLOAD_BYTES = 25 * 1024 * 1024

ALLOWED_UPLOAD_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
    ".txt",
    ".csv",
    ".md",
    ".html",
    ".htm",
}

PIPELINE_UPLOAD_EXTENSIONS = {".pdf"}

STANDARD_DEDUCTION_2025: dict[FilingStatus, float] = {
    "single": 15_000.00,
    "married_joint": 30_000.00,
    "head_of_household": 22_500.00,
}

FEDERAL_BRACKETS_2025: dict[FilingStatus, list[tuple[float, float]]] = {
    "single": [
        (11_925.00, 0.10),
        (48_475.00, 0.12),
        (103_350.00, 0.22),
        (197_300.00, 0.24),
        (250_525.00, 0.32),
        (626_350.00, 0.35),
        (float("inf"), 0.37),
    ],
    "married_joint": [
        (23_850.00, 0.10),
        (96_950.00, 0.12),
        (206_700.00, 0.22),
        (394_600.00, 0.24),
        (501_050.00, 0.32),
        (751_600.00, 0.35),
        (float("inf"), 0.37),
    ],
    "head_of_household": [
        (17_000.00, 0.10),
        (64_850.00, 0.12),
        (103_350.00, 0.22),
        (197_300.00, 0.24),
        (250_500.00, 0.32),
        (626_350.00, 0.35),
        (float("inf"), 0.37),
    ],
}


app = FastAPI(
    title="AI Tax Platform",
    version="1.0.0",
    description="AI-assisted tax estimation, tax document detection, extraction, and strategy reporting platform.",
)


class TaxEstimateRequest(BaseModel):
    filing_status: FilingStatus = Field(..., description="Tax filing status")
    annual_income: float = Field(..., ge=0, description="Gross annual income")
    extra_deductions: float = Field(default=0, ge=0, description="Additional deductions")
    tax_credits: float = Field(default=0, ge=0, description="Tax credits")
    federal_withheld: float = Field(default=0, ge=0, description="Federal tax already withheld")


class TaxEstimateResponse(BaseModel):
    filing_status: FilingStatus
    annual_income: float
    standard_deduction: float
    extra_deductions: float
    total_deductions: float
    taxable_income: float
    estimated_federal_tax_before_credits: float
    tax_credits_applied: float
    estimated_federal_tax_after_credits: float
    federal_withheld: float
    estimated_refund: float
    estimated_amount_due: float
    effective_tax_rate: float
    summary: str
    disclaimer: str

class ReviewedFieldsRequest(BaseModel):
    primary_form_type: str = Field(..., description="Primary form type, e.g. 1040, 1120S, 1065, 1120")
    approved_fields: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="User-approved fields keyed by field name.",
    )
    overwrite: bool = Field(default=True, description="Whether approved fields overwrite questionnaire defaults/existing values")

class ReviewedQuestionnaireReportRequest(BaseModel):
    primary_form_type: str = Field(..., description="Primary form type, e.g. 1040, 1120S, 1065, 1120")
    questionnaire: dict[str, Any] = Field(..., description="Reviewed/approved questionnaire data")
    fact_extraction_result: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional original fact extraction result for source cards/context",
    )
    decisions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Strategy decisions: recommend, decline, defer, undecided",
    )
    client_id: str = Field(default="ai_client_name")


def money(value: float) -> float:
    return round(float(value), 2)


def calculate_progressive_tax(
    taxable_income: float,
    brackets: list[tuple[float, float]],
) -> float:
    if taxable_income <= 0:
        return 0.00

    tax = 0.00
    previous_limit = 0.00

    for current_limit, rate in brackets:
        if taxable_income <= previous_limit:
            break

        taxable_at_this_rate = min(taxable_income, current_limit) - previous_limit
        tax += taxable_at_this_rate * rate
        previous_limit = current_limit

    return money(tax)


def build_tax_summary(
    taxable_income: float,
    tax_after_credits: float,
    federal_withheld: float,
    estimated_refund: float,
    estimated_amount_due: float,
) -> str:
    if estimated_refund > 0:
        outcome = f"You may receive an estimated federal refund of ${estimated_refund:,.2f}."
    elif estimated_amount_due > 0:
        outcome = f"You may owe an estimated federal amount of ${estimated_amount_due:,.2f}."
    else:
        outcome = "Your federal withholding appears approximately balanced."

    return (
        f"Estimated taxable income is ${taxable_income:,.2f}. "
        f"Estimated federal tax after credits is ${tax_after_credits:,.2f}. "
        f"Federal withholding entered is ${federal_withheld:,.2f}. "
        f"{outcome}"
    )


def normalize_detection_result(result: Any) -> dict[str, Any]:
    if hasattr(result, "to_dict") and callable(result.to_dict):
        return result.to_dict()

    if isinstance(result, dict):
        return result

    raise TypeError("Form detector returned an unsupported result type.")


async def save_upload_to_temp_file(
    file: UploadFile,
    *,
    allowed_extensions: set[str],
) -> tuple[Path, str, int]:
    original_filename = file.filename or ""
    suffix = Path(original_filename).suffix.lower()

    if suffix not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '{suffix or 'unknown'}'. "
                f"Allowed file types: {', '.join(sorted(allowed_extensions))}."
            ),
        )

    file_bytes = await file.read()

    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Uploaded file is too large. Maximum allowed size is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_file.write(file_bytes)
        temp_path = Path(temp_file.name)

    return temp_path, original_filename, len(file_bytes)


def remove_temp_file(path: Path | None) -> None:
    if path is None:
        return

    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def build_extracted_facts_payload(fact_result: dict[str, Any]) -> dict[str, Any]:
    extracted_facts: dict[str, Any] = {"facts": {}}
    extraction_cards = fact_result.get("extraction_cards", [])

    if not isinstance(extraction_cards, list) or not extraction_cards:
        return extracted_facts

    first_card = extraction_cards[0]

    if not isinstance(first_card, dict):
        return extracted_facts

    fields = first_card.get("fields", {})

    if not isinstance(fields, dict):
        return extracted_facts

    for field_name, payload in fields.items():
        if not isinstance(payload, dict):
            continue

        extracted_facts["facts"][field_name] = {
            "value": payload.get("value"),
            "source": payload.get("source_line"),
            "confidence": payload.get("confidence"),
        }

    return extracted_facts


def build_recommend_all_decisions(
    rule_result: dict[str, Any],
    ai_result: dict[str, Any],
) -> list[dict[str, str]]:
    strategy_names = {
        strategy.get("strategy_name")
        for strategy in rule_result.get("recommended_strategies", [])
        if isinstance(strategy, dict)
    } | {
        strategy.get("strategy_name")
        for strategy in ai_result.get("ai_matches", [])
        if isinstance(strategy, dict)
    }

    return [
        {
            "strategy_name": str(strategy_name),
            "decision": "recommend",
            "notes": "Auto-recommended for API testing only.",
        }
        for strategy_name in sorted(strategy_names)
        if strategy_name
    ]


@app.get("/", response_class=HTMLResponse)
def home() -> FileResponse:
    index_path = Path(__file__).resolve().parent / "index.html"

    if not index_path.exists():
        raise HTTPException(status_code=500, detail="index.html not found.")

    return FileResponse(index_path)



@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "AI Tax Platform"}


@app.post("/estimate-tax", response_model=TaxEstimateResponse)
def estimate_tax(payload: TaxEstimateRequest) -> TaxEstimateResponse:
    standard_deduction = STANDARD_DEDUCTION_2025[payload.filing_status]
    total_deductions = standard_deduction + payload.extra_deductions
    taxable_income = max(payload.annual_income - total_deductions, 0.00)

    tax_before_credits = calculate_progressive_tax(
        taxable_income=taxable_income,
        brackets=FEDERAL_BRACKETS_2025[payload.filing_status],
    )

    credits_applied = min(payload.tax_credits, tax_before_credits)
    tax_after_credits = max(tax_before_credits - credits_applied, 0.00)

    difference = payload.federal_withheld - tax_after_credits
    estimated_refund = max(difference, 0.00)
    estimated_amount_due = max(-difference, 0.00)

    effective_tax_rate = 0.00
    if payload.annual_income > 0:
        effective_tax_rate = money((tax_after_credits / payload.annual_income) * 100)

    summary = build_tax_summary(
        taxable_income=taxable_income,
        tax_after_credits=tax_after_credits,
        federal_withheld=payload.federal_withheld,
        estimated_refund=estimated_refund,
        estimated_amount_due=estimated_amount_due,
    )

    return TaxEstimateResponse(
        filing_status=payload.filing_status,
        annual_income=money(payload.annual_income),
        standard_deduction=money(standard_deduction),
        extra_deductions=money(payload.extra_deductions),
        total_deductions=money(total_deductions),
        taxable_income=money(taxable_income),
        estimated_federal_tax_before_credits=money(tax_before_credits),
        tax_credits_applied=money(credits_applied),
        estimated_federal_tax_after_credits=money(tax_after_credits),
        federal_withheld=money(payload.federal_withheld),
        estimated_refund=money(estimated_refund),
        estimated_amount_due=money(estimated_amount_due),
        effective_tax_rate=money(effective_tax_rate),
        summary=summary,
        disclaimer="This is a simplified estimate for planning only and is not legal, financial, or tax advice.",
    )


@app.post("/detect-form")
async def detect_form(file: UploadFile = File(...)) -> dict[str, Any]:
    temp_path: Path | None = None

    try:
        temp_path, original_filename, uploaded_size = await save_upload_to_temp_file(
            file,
            allowed_extensions=ALLOWED_UPLOAD_EXTENSIONS,
        )

        detection_result = detect_tax_form_from_file(temp_path)
        response = normalize_detection_result(detection_result)
        response["uploaded_filename"] = original_filename
        response["uploaded_size_bytes"] = uploaded_size

        return response

    except FormDetectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(status_code=500, detail="Unable to detect the uploaded tax form.") from exc

    finally:
        remove_temp_file(temp_path)


@app.post("/extract-facts")
async def extract_facts(file: UploadFile = File(...)) -> dict[str, Any]:
    temp_path: Path | None = None

    try:
        temp_path, original_filename, uploaded_size = await save_upload_to_temp_file(
            file,
            allowed_extensions=PIPELINE_UPLOAD_EXTENSIONS,
        )

        fact_result = extract_facts_from_pdf_file(temp_path).to_dict()
        fact_result["uploaded_filename"] = original_filename
        fact_result["uploaded_size_bytes"] = uploaded_size

        return fact_result

    except FactExtractorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except FormDetectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(status_code=500, detail="Unable to extract structured facts from the uploaded PDF.") from exc

    finally:
        remove_temp_file(temp_path)

@app.post("/cross-check-extraction")
async def cross_check_extraction(
    file: UploadFile = File(...),
    page1_number: int = 1,
    page2_number: int = 2,
) -> dict[str, Any]:
    temp_path: Path | None = None

    try:
        temp_path, original_filename, uploaded_size = await save_upload_to_temp_file(
            file,
            allowed_extensions=PIPELINE_UPLOAD_EXTENSIONS,
        )

        cross_check_result = run_cross_check(
            temp_path,
            page1_number=page1_number,
            page2_number=page2_number,
        ).to_dict()

        cross_check_result["uploaded_filename"] = original_filename
        cross_check_result["uploaded_size_bytes"] = uploaded_size

        return cross_check_result

    except CrossCheckError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except FactExtractorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except FormDetectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(status_code=500, detail="Unable to cross-check extraction results.") from exc

    finally:
        remove_temp_file(temp_path)

@app.post("/cross-check-and-merge-questionnaire")
async def cross_check_and_merge_questionnaire(
    file: UploadFile = File(...),
    page1_number: int = 1,
    page2_number: int = 2,
) -> dict[str, Any]:
    temp_path: Path | None = None

    try:
        temp_path, original_filename, uploaded_size = await save_upload_to_temp_file(
            file,
            allowed_extensions=PIPELINE_UPLOAD_EXTENSIONS,
        )

        cross_check_result = run_cross_check(
            temp_path,
            page1_number=page1_number,
            page2_number=page2_number,
        ).to_dict()

        primary_form_type = str(cross_check_result.get("primary_form_type") or "UNKNOWN")
        cross_checked_fields = cross_check_result.get("fields", {})

        if not isinstance(cross_checked_fields, dict):
            raise HTTPException(status_code=500, detail="Cross-check result fields are invalid.")

        trusted_fields: dict[str, Any] = {}
        review_required_fields: dict[str, Any] = {}

        for field_name, field_payload in cross_checked_fields.items():
            if not isinstance(field_payload, dict):
                continue

            if field_payload.get("status") == "MATCHED_TEXT_AND_VISION":
                trusted_fields[field_name] = {
                    "field_name": field_name,
                    "value": field_payload.get("final_value"),
                    "source_form": f"Form {primary_form_type}",
                    "source_line": field_payload.get("text_value", {}).get("source_line")
                    or field_payload.get("vision_value", {}).get("source_line"),
                    "extraction_method": "cross_checked_text_and_vision",
                    "confidence": field_payload.get("confidence", 0),
                    "requires_review": False,
                    "notes": "Auto-merged because text and vision extraction matched.",
                }
            else:
                review_required_fields[field_name] = field_payload

        trusted_extraction_card = {
            "form_type": primary_form_type,
            "display_name": f"Form {primary_form_type}",
            "status": "trusted_cross_checked_fields_only",
            "fields": trusted_fields,
            "schedules_observed": cross_check_result.get("text_extraction", {}).get("forms_found", []),
            "warnings": [
                "Only fields with MATCHED_TEXT_AND_VISION were auto-merged.",
                "All conflicting, text-only, or vision-only fields require human review.",
            ],
        }

        trusted_fact_result = {
            "primary_form_type": primary_form_type,
            "forms_found": cross_check_result.get("text_extraction", {}).get("forms_found", []),
            "extraction_cards": [trusted_extraction_card],
            "document_warnings": cross_check_result.get("warnings", []),
        }

        questionnaire_merge = merge_fact_extraction_result_into_questionnaire(
            get_default_questionnaire(),
            trusted_fact_result,
            overwrite=True,
            minimum_confidence=0.90,
        )

        return {
            "primary_form_type": primary_form_type,
            "questionnaire": questionnaire_merge["questionnaire"],
            "merge_events": questionnaire_merge["merge_events"],
            "trusted_fields_auto_merged": trusted_fields,
            "review_required_fields": review_required_fields,
            "cross_check_warnings": cross_check_result.get("warnings", []),
            "uploaded_filename": original_filename,
            "uploaded_size_bytes": uploaded_size,
        }

    except CrossCheckError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except QuestionnaireError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(status_code=500, detail="Unable to cross-check and merge questionnaire.") from exc

    finally:
        remove_temp_file(temp_path)


@app.post("/generate-ai-report")
async def generate_ai_report(
    file: UploadFile = File(...),
    client_id: str = "ai_client_name",
) -> dict[str, Any]:
    temp_path: Path | None = None

    try:
        temp_path, original_filename, uploaded_size = await save_upload_to_temp_file(
            file,
            allowed_extensions=ALLOWED_UPLOAD_EXTENSIONS,
        )

        report = generate_ai_tax_report_from_file(
            temp_path,
            client_id=client_id,
        )

        report["uploaded_filename"] = original_filename
        report["uploaded_size_bytes"] = uploaded_size

        return report

    except AITaxReportError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    except FormDetectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(status_code=500, detail="Unable to generate AI tax report.") from exc

    finally:
        remove_temp_file(temp_path)

@app.post("/apply-reviewed-fields")
def apply_reviewed_fields(payload: ReviewedFieldsRequest) -> dict[str, Any]:
    try:
        approved_card_fields: dict[str, Any] = {}

        for field_name, field_payload in payload.approved_fields.items():
            if not isinstance(field_payload, dict):
                continue

            approved_card_fields[field_name] = {
                "field_name": field_name,
                "value": field_payload.get("value"),
                "source_form": f"Form {payload.primary_form_type}",
                "source_line": field_payload.get("source_line"),
                "extraction_method": "user_review_approved",
                "confidence": field_payload.get("confidence", 1.0),
                "requires_review": False,
                "notes": field_payload.get("notes", "Approved by user review."),
            }

        reviewed_extraction_card = {
            "form_type": payload.primary_form_type,
            "display_name": f"Form {payload.primary_form_type}",
            "status": "user_review_approved",
            "fields": approved_card_fields,
            "schedules_observed": [],
            "warnings": [],
        }

        reviewed_fact_result = {
            "primary_form_type": payload.primary_form_type,
            "forms_found": [f"Form {payload.primary_form_type}"],
            "extraction_cards": [reviewed_extraction_card],
            "document_warnings": [],
        }

        questionnaire_merge = merge_fact_extraction_result_into_questionnaire(
            get_default_questionnaire(),
            reviewed_fact_result,
            overwrite=payload.overwrite,
            minimum_confidence=0.0,
        )

        return {
            "primary_form_type": payload.primary_form_type,
            "questionnaire": questionnaire_merge["questionnaire"],
            "merge_events": questionnaire_merge["merge_events"],
            "approved_fields_applied": approved_card_fields,
            "guardrails": {
                "user_review_required_for_conflicts": True,
                "only_user_approved_fields_merged": True,
                "no_conflicted_field_auto_merged": True,
            },
        }

    except QuestionnaireError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except Exception as exc:
        raise HTTPException(status_code=500, detail="Unable to apply reviewed fields.") from exc

@app.post("/generate-report-from-reviewed-questionnaire")
def generate_report_from_reviewed_questionnaire(
    payload: ReviewedQuestionnaireReportRequest,
) -> dict[str, Any]:
    try:
        fact_result = dict(payload.fact_extraction_result or {})

        if not fact_result:
            fact_result = {
                "primary_form_type": payload.primary_form_type,
                "forms_found": [f"Form {payload.primary_form_type}"],
                "extraction_cards": [],
                "document_warnings": [
                    "Report generated from reviewed questionnaire without original extraction cards."
                ],
            }

        extracted_facts = build_extracted_facts_payload(fact_result)

        rule_result = run_strategy_rules(
            payload.questionnaire,
            primary_form_type=payload.primary_form_type,
            extracted_facts=extracted_facts,
        ).to_dict()

        ai_result = match_strategies_with_ai(
            primary_form_type=payload.primary_form_type,
            questionnaire=payload.questionnaire,
            fact_extraction_result=fact_result,
            rule_result=rule_result,
        ).to_dict()

        final_report = generate_final_report(
            client_id=payload.client_id,
            fact_extraction_result=fact_result,
            questionnaire=payload.questionnaire,
            rule_result=rule_result,
            ai_match_result=ai_result,
            decisions=payload.decisions,
        ).to_dict()

        final_report["ruleResult"] = rule_result
        final_report["aiMatchResult"] = ai_result
        final_report["reviewedQuestionnaireUsed"] = True

        return final_report

    except (StrategyRulesError, StrategyAIMatcherError, ReportGeneratorError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except Exception as exc:
        raise HTTPException(status_code=500, detail="Unable to generate report from reviewed questionnaire.") from exc


@app.post("/generate-final-report")
async def generate_final_report_endpoint(
    file: UploadFile = File(...),
    client_id: str = "ai_client_name",
    recommend_all: bool = False,
) -> dict[str, Any]:
    temp_path: Path | None = None

    try:
        temp_path, original_filename, uploaded_size = await save_upload_to_temp_file(
            file,
            allowed_extensions=PIPELINE_UPLOAD_EXTENSIONS,
        )

        fact_result = extract_facts_from_pdf_file(temp_path).to_dict()

        questionnaire_merge = merge_fact_extraction_result_into_questionnaire(
            get_default_questionnaire(),
            fact_result,
            overwrite=True,
        )
        questionnaire = questionnaire_merge["questionnaire"]

        extracted_facts = build_extracted_facts_payload(fact_result)

        rule_result = run_strategy_rules(
            questionnaire,
            primary_form_type=str(fact_result.get("primary_form_type") or ""),
            extracted_facts=extracted_facts,
        ).to_dict()

        ai_result = match_strategies_with_ai(
            primary_form_type=str(fact_result.get("primary_form_type") or ""),
            questionnaire=questionnaire,
            fact_extraction_result=fact_result,
            rule_result=rule_result,
        ).to_dict()

        decisions = build_recommend_all_decisions(rule_result, ai_result) if recommend_all else []

        final_report = generate_final_report(
            client_id=client_id,
            fact_extraction_result=fact_result,
            questionnaire=questionnaire,
            rule_result=rule_result,
            ai_match_result=ai_result,
            decisions=decisions,
        ).to_dict()

        final_report["questionnaireMergeEvents"] = questionnaire_merge.get("merge_events", [])
        final_report["ruleResult"] = rule_result
        final_report["aiMatchResult"] = ai_result
        final_report["uploaded_filename"] = original_filename
        final_report["uploaded_size_bytes"] = uploaded_size

        return final_report

    except (FactExtractorError, QuestionnaireError, StrategyRulesError, ReportGeneratorError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except StrategyAIMatcherError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    except FormDetectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(status_code=500, detail="Unable to generate final TaxTruth report.") from exc

    finally:
        remove_temp_file(temp_path)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
