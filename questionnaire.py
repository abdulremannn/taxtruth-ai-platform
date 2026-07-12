from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any


class QuestionnaireError(Exception):
    """Raised when questionnaire operations fail."""


DEFAULT_QUESTIONNAIRE: dict[str, Any] = {
    "personalQuestionnaire": {
        "clientName": "",
        "dateOfBirth": None,
        "cellPhone": "",
        "homeAddress": "",
        "clientEmail": "",
        "spouseName": "",
        "spouseDateOfBirth": None,
        "spouseAnnualCompensation": 0,
        "spouseWorksInPractice": False,
        "filingStatus": "",
        "noOfChildren": 0,
        "children": [],
        "primaryBusinessName": "",
        "businessAddress": "",
        "businessPhoneNumber": "",
        "businessWebsite": "",
        "businessStructure": "Sole proprietorship",
        "whyThisStructure": "",
        "employeesCount": 0,
        "businessOwnershipPercentage": 0,
        "secondaryBusinessOwnership": 0,
        "thirdBusinessOwnership": 0,
        "has1120S": False,
        "has1120": False,
        "has1065": False,
        "sCorpOfficerComp": 0,
        "sCorpDistributions": 0,
        "cCorpRetainedEarningsActual": 0,
        "partnershipGuaranteedPayments": 0,
        "managementCompanyRevenue": 0,
        "ownsPracticeBuilding": False,
        "buildingPurchasePrice": 0,
        "buildingPlacedInServiceYear": 0,
        "plannedEquipmentPurchase": 0,
        "annualEquipmentLeasePayments": 0,
        "monthlyLifestyleExpenses": 0,
        "monthlyMedicalInsurance": 0,
        "premiumPayer": "",
        "ownsHome": False,
        "ownsPrimaryHome": False,
        "ownsSecondaryHome": False,
        "secondaryHomeCount": 0,
        "ownsBoatOrYacht": False,
        "hasRentalProperties": False,
        "rentalPropertyCount": 0,
        "hasShortTermRental": False,
        "shortTermRental": False,
        "realEstateProfessionalHours": 0,
        "otherWorkHours": 0,
        "planningRetirement": False,
        "retirementAge": 0,
        "longTermFinancialGoals": "",
        "practiceSalePlanned": False,
        "hasForm4797": False,
        "hasForm6252": False,
        "installmentSaleProceeds": 0,
        "section1231Gain": 0,
        "nolCarryoverAmount": 0,
        "isoSpreadAmount": 0,
        "hasDSOEquity": False,
        "advisor1Description": "",
        "relationshipLength": "",
        "advisorAnnualCost": "",
        "advisorRating": 1,
        "advisorRatingExplanation": "",
        "clientAnnualCompensation": 0,
        "householdIncome": 0,
        "futureIncomeYear": "",
        "mainResidenceDetails": "",
        "secondaryHomeDetails": "",
        "PNL": "",
        "taxReturnFile1": "",
        "taxReturnFile2": "",
    },
    "financialQuestionnaire": {
        "clientName": "",
        "clientEmail": "",
        "clientPhone": "",
        "dob": None,
        "federalTaxReturns": "",
        "extraordinaryItems": "",
        "newIncomeSources": "",
        "retirementAge": None,
        "desiredRetirementIncome": 0,
        "retirementPlan": "",
        "cashOnHand": 0,
        "realEstateValues": 0,
        "automobileValues": 0,
        "mortgages": "",
        "commercialProperty": False,
        "propertyTaxes": False,
        "newEmployeesPerYear": 0,
        "takeCreditCards": False,
        "creditCardType": "",
        "workersCompPremiumOver40k": False,
        "selfInsured": False,
        "anySavings": "0",
        "hasLifeInsurance": False,
        "insuredName": "",
        "deathBenefitAmount": 0,
        "insuranceType": "",
        "insurancePolicyType": "",
        "annualPremium": 0,
        "annualPremium1": "",
        "totalCashValue": 0,
        "estimatedNetWorthRange": "",
        "currentSecuritiesInvestments": 0,
        "cCorpRetainedEarnings": 0,
    },
}


FIELD_TO_QUESTIONNAIRE_MAPPING: dict[str, tuple[str, str]] = {
    # 1120-S mappings
    "officer_compensation": ("personalQuestionnaire", "sCorpOfficerComp"),
    "shareholder_distributions": ("personalQuestionnaire", "sCorpDistributions"),
    "ending_retained_earnings": ("personalQuestionnaire", "cCorpRetainedEarningsActual"),
    "partnership_guaranteed_payments": ("personalQuestionnaire", "partnershipGuaranteedPayments"),
    "gross_receipts": ("personalQuestionnaire", "managementCompanyRevenue"),
    "ordinary_business_income": ("personalQuestionnaire", "householdIncome"),

    # 1065 mappings
    "gross_receipts_balance": ("personalQuestionnaire", "managementCompanyRevenue"),
    "guaranteed_payments": ("personalQuestionnaire", "partnershipGuaranteedPayments"),

    # 1040 mappings
    "filing_status": ("personalQuestionnaire", "filingStatus"),
    "taxpayer_name": ("personalQuestionnaire", "clientName"),
    "spouse_name": ("personalQuestionnaire", "spouseName"),
    "wages": ("personalQuestionnaire", "clientAnnualCompensation"),
    "total_income": ("personalQuestionnaire", "householdIncome"),
}



FORM_TYPE_TO_FLAGS: dict[str, tuple[tuple[str, str, Any], ...]] = {
    "1120S": (
        ("personalQuestionnaire", "has1120S", True),
        ("personalQuestionnaire", "businessStructure", "S Corporation"),
    ),
    "1120-S": (
        ("personalQuestionnaire", "has1120S", True),
        ("personalQuestionnaire", "businessStructure", "S Corporation"),
    ),
    "1120": (
        ("personalQuestionnaire", "has1120", True),
        ("personalQuestionnaire", "businessStructure", "C Corporation"),
    ),
    "1065": (
        ("personalQuestionnaire", "has1065", True),
        ("personalQuestionnaire", "businessStructure", "Partnership"),
    ),
    "1040": (
        ("personalQuestionnaire", "businessStructure", "Individual"),
    ),
}


@dataclass(frozen=True)
class QuestionnaireMergeEvent:
    section: str
    field_name: str
    old_value: Any
    new_value: Any
    source_field: str
    source_form: str
    confidence: float
    applied: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "field_name": self.field_name,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "source_field": self.source_field,
            "source_form": self.source_form,
            "confidence": round(self.confidence, 4),
            "applied": self.applied,
            "reason": self.reason,
        }


def get_default_questionnaire() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_QUESTIONNAIRE)


def is_empty_default(value: Any) -> bool:
    return value in ("", 0, 0.0, None, False, [], {})


def normalize_form_type(form_type: str | None) -> str:
    return (form_type or "").upper().replace("-", "").replace("FORM", "").strip()


def set_questionnaire_value(
    questionnaire: dict[str, Any],
    section: str,
    field_name: str,
    value: Any,
) -> None:
    if section not in questionnaire:
        raise QuestionnaireError(f"Unknown questionnaire section: {section}")

    if field_name not in questionnaire[section]:
        raise QuestionnaireError(f"Unknown questionnaire field: {section}.{field_name}")

    questionnaire[section][field_name] = value


def get_questionnaire_value(
    questionnaire: dict[str, Any],
    section: str,
    field_name: str,
) -> Any:
    if section not in questionnaire:
        raise QuestionnaireError(f"Unknown questionnaire section: {section}")

    if field_name not in questionnaire[section]:
        raise QuestionnaireError(f"Unknown questionnaire field: {section}.{field_name}")

    return questionnaire[section][field_name]


def apply_form_flags(
    questionnaire: dict[str, Any],
    form_type: str,
    *,
    overwrite: bool,
) -> list[QuestionnaireMergeEvent]:
    normalized = normalize_form_type(form_type)
    events: list[QuestionnaireMergeEvent] = []

    flag_rules = FORM_TYPE_TO_FLAGS.get(normalized, ())

    for section, field_name, new_value in flag_rules:
        old_value = get_questionnaire_value(questionnaire, section, field_name)

        should_apply = overwrite or is_empty_default(old_value) or isinstance(new_value, bool)

        if should_apply:
            set_questionnaire_value(questionnaire, section, field_name, new_value)

        events.append(
            QuestionnaireMergeEvent(
                section=section,
                field_name=field_name,
                old_value=old_value,
                new_value=new_value,
                source_field="form_type",
                source_form=form_type,
                confidence=1.0,
                applied=should_apply,
                reason="Applied form type flag." if should_apply else "Skipped because questionnaire already had a user value.",
            )
        )

    return events


def extract_fields_from_card(card: dict[str, Any]) -> dict[str, dict[str, Any]]:
    fields = card.get("fields", {})

    if not isinstance(fields, dict):
        return {}

    return {key: value for key, value in fields.items() if isinstance(value, dict)}


def merge_extraction_card_into_questionnaire(
    questionnaire: dict[str, Any],
    extraction_card: dict[str, Any],
    *,
    overwrite: bool = False,
    minimum_confidence: float = 0.80,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    merged = copy.deepcopy(questionnaire)
    events: list[QuestionnaireMergeEvent] = []

    form_type = str(extraction_card.get("form_type") or "")
    events.extend(apply_form_flags(merged, form_type, overwrite=overwrite))

    fields = extract_fields_from_card(extraction_card)

    for source_field, field_payload in fields.items():
        mapping = FIELD_TO_QUESTIONNAIRE_MAPPING.get(source_field)

        if mapping is None:
            continue

        section, target_field = mapping
        confidence = float(field_payload.get("confidence") or 0)
        source_form = str(field_payload.get("source_form") or form_type)
        new_value = field_payload.get("value")

        old_value = get_questionnaire_value(merged, section, target_field)

        if confidence < minimum_confidence:
            applied = False
            reason = f"Skipped because confidence {confidence:.2f} is below threshold {minimum_confidence:.2f}."

        elif new_value is None:
            applied = False
            reason = "Skipped because extracted value is null."

        elif not overwrite and not is_empty_default(old_value):
            applied = False
            reason = "Skipped because questionnaire already has a user-entered value."

        else:
            set_questionnaire_value(merged, section, target_field, new_value)
            applied = True
            reason = "Applied extracted value."

        events.append(
            QuestionnaireMergeEvent(
                section=section,
                field_name=target_field,
                old_value=old_value,
                new_value=new_value,
                source_field=source_field,
                source_form=source_form,
                confidence=confidence,
                applied=applied,
                reason=reason,
            )
        )

    return merged, [event.to_dict() for event in events]


def merge_fact_extraction_result_into_questionnaire(
    questionnaire: dict[str, Any],
    fact_extraction_result: dict[str, Any],
    *,
    applied_form_types: list[str] | None = None,
    overwrite: bool = False,
    minimum_confidence: float = 0.80,
) -> dict[str, Any]:
    merged = copy.deepcopy(questionnaire)
    all_events: list[dict[str, Any]] = []

    cards = fact_extraction_result.get("extraction_cards", [])

    if not isinstance(cards, list):
        raise QuestionnaireError("fact_extraction_result.extraction_cards must be a list.")

    allowed_form_types = {normalize_form_type(form_type) for form_type in applied_form_types or []}

    for card in cards:
        if not isinstance(card, dict):
            continue

        card_form_type = normalize_form_type(str(card.get("form_type") or ""))

        if allowed_form_types and card_form_type not in allowed_form_types:
            continue

        merged, events = merge_extraction_card_into_questionnaire(
            merged,
            card,
            overwrite=overwrite,
            minimum_confidence=minimum_confidence,
        )
        all_events.extend(events)

    return {
        "questionnaire": merged,
        "merge_events": all_events,
    }


def main() -> None:
    import argparse
    from fact_extractor import extract_facts_from_pdf_file

    parser = argparse.ArgumentParser(description="Merge extracted tax facts into the TaxTruth questionnaire schema.")
    parser.add_argument("pdf", help="Path to PDF file")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite non-empty questionnaire values")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args()

    questionnaire = get_default_questionnaire()
    facts = extract_facts_from_pdf_file(args.pdf).to_dict()

    result = merge_fact_extraction_result_into_questionnaire(
        questionnaire,
        facts,
        overwrite=args.overwrite,
    )

    print(json.dumps(result, indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
