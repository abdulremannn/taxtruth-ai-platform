from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


class StrategyRulesError(Exception):
    """Raised when deterministic strategy rules fail."""


@dataclass(frozen=True)
class RuleBasedStrategy:
    strategy_id: str
    strategy_name: str
    confidence: str
    reason: str
    evidence: list[str] = field(default_factory=list)
    source_rule: str = ""
    readiness: str = "REVIEW_REQUIRED"
    estimated_savings_low: float = 0.0
    estimated_savings_high: float = 0.0
    audit_risk: str = "Medium"

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "confidence": self.confidence,
            "reason": self.reason,
            "evidence": list(self.evidence),
            "source_rule": self.source_rule,
            "readiness": self.readiness,
            "estimated_savings_low": round(self.estimated_savings_low, 2),
            "estimated_savings_high": round(self.estimated_savings_high, 2),
            "audit_risk": self.audit_risk,
        }


@dataclass(frozen=True)
class StrategyRuleResult:
    recommended_strategies: list[RuleBasedStrategy]
    risk_drivers: list[str]
    facts_used: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommended_strategies": [strategy.to_dict() for strategy in self.recommended_strategies],
            "risk_drivers": list(self.risk_drivers),
            "facts_used": dict(self.facts_used),
        }


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default

    if isinstance(value, int | float):
        return float(value)

    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("$", "").strip()
        if not cleaned:
            return default

        is_negative = cleaned.startswith("(") and cleaned.endswith(")")
        cleaned = cleaned.strip("()")

        try:
            parsed = float(cleaned)
        except ValueError:
            return default

        return -parsed if is_negative else parsed

    return default


def safe_bool(value: Any) -> bool:
    return bool(value)


def get_nested(data: dict[str, Any], section: str, field_name: str, default: Any = None) -> Any:
    section_value = data.get(section, {})

    if not isinstance(section_value, dict):
        return default

    return section_value.get(field_name, default)


def dedupe_strategies(strategies: list[RuleBasedStrategy]) -> list[RuleBasedStrategy]:
    seen: set[str] = set()
    output: list[RuleBasedStrategy] = []

    for strategy in strategies:
        if strategy.strategy_name in seen:
            continue

        seen.add(strategy.strategy_name)
        output.append(strategy)

    return output


def estimate_payroll_tax_savings_from_distribution_review(distributions: float) -> tuple[float, float]:
    """
    Conservative estimate for planning only.

    This is not saying distributions become wages or vice versa.
    It estimates the value range of compensation/distribution planning review.
    """
    if distributions <= 0:
        return 0.0, 0.0

    low = min(distributions * 0.05, 5_000)
    high = min(distributions * 0.15, 20_000)

    return low, max(high, low)


def estimate_retirement_savings(income: float) -> tuple[float, float]:
    if income <= 0:
        return 0.0, 0.0

    low = min(income * 0.03, 10_000)
    high = min(income * 0.10, 50_000)

    return low, max(high, low)


def estimate_depreciation_review_savings(section_179: float) -> tuple[float, float]:
    if section_179 <= 0:
        return 0.0, 0.0

    low = min(section_179 * 0.03, 3_000)
    high = min(section_179 * 0.12, 15_000)

    return low, max(high, low)


def run_1120s_rules(questionnaire: dict[str, Any], extracted_facts: dict[str, Any] | None = None) -> StrategyRuleResult:
    personal = questionnaire.get("personalQuestionnaire", {})
    financial = questionnaire.get("financialQuestionnaire", {})

    if not isinstance(personal, dict) or not isinstance(financial, dict):
        raise StrategyRulesError("Questionnaire must contain personalQuestionnaire and financialQuestionnaire objects.")

    has_1120s = safe_bool(personal.get("has1120S"))
    officer_comp = safe_float(personal.get("sCorpOfficerComp"))
    distributions = safe_float(personal.get("sCorpDistributions"))
    ordinary_income = safe_float(personal.get("householdIncome"))
    gross_receipts = safe_float(personal.get("managementCompanyRevenue"))
    retirement_age = safe_float(personal.get("retirementAge"))
    owns_practice_building = safe_bool(personal.get("ownsPracticeBuilding"))
    planned_equipment_purchase = safe_float(personal.get("plannedEquipmentPurchase"))
    employees_count = safe_float(personal.get("employeesCount"))
    has_rental_properties = safe_bool(personal.get("hasRentalProperties"))
    ccorp_retained_earnings_actual = safe_float(personal.get("cCorpRetainedEarningsActual"))

    facts = extracted_facts if isinstance(extracted_facts, dict) else {}
    fact_fields = facts.get("facts", {}) if isinstance(facts.get("facts"), dict) else {}

    def fact_value(key: str, default: Any = None) -> Any:
        item = fact_fields.get(key)
        return item.get("value", default) if isinstance(item, dict) else default

    section_179 = safe_float(fact_value("section_179_deduction"))
    ending_retained_earnings = safe_float(fact_value("ending_retained_earnings", ccorp_retained_earnings_actual))
    form_4562_attached = fact_value("form_4562_attached", None)

    strategies: list[RuleBasedStrategy] = []
    risk_drivers: list[str] = []

    facts_used = {
        "has1120S": has_1120s,
        "officer_compensation": officer_comp,
        "shareholder_distributions": distributions,
        "ordinary_business_income": ordinary_income,
        "gross_receipts": gross_receipts,
        "section_179_deduction": section_179,
        "ending_retained_earnings": ending_retained_earnings,
        "form_4562_attached": form_4562_attached,
        "employees_count": employees_count,
        "owns_practice_building": owns_practice_building,
        "planned_equipment_purchase": planned_equipment_purchase,
        "has_rental_properties": has_rental_properties,
        "retirement_age": retirement_age,
    }

    if not has_1120s:
        return StrategyRuleResult(
            recommended_strategies=[],
            risk_drivers=["No 1120-S flag found in questionnaire; 1120-S rules skipped."],
            facts_used=facts_used,
        )

    if officer_comp > 0 and (distributions > 0 or ordinary_income > 0):
        low, high = estimate_payroll_tax_savings_from_distribution_review(distributions)

        ratio_text = ""
        if distributions > 0 and officer_comp > 0:
            total_owner_cash_flow = officer_comp + distributions
            ratio = distributions / total_owner_cash_flow if total_owner_cash_flow else 0
            ratio_text = f"Distributions are approximately {ratio:.1%} of officer compensation plus distributions."

        strategies.append(
            RuleBasedStrategy(
                strategy_id="DTTS-001-s-corp-reasonable-compensation-planning",
                strategy_name="S-Corp Reasonable Compensation Planning",
                confidence="High",
                reason="S corporation return shows officer compensation and shareholder distributions/business income requiring reasonable compensation review.",
                evidence=[
                    f"Officer compensation: ${officer_comp:,.0f}",
                    f"Shareholder distributions: ${distributions:,.0f}" if distributions else "Shareholder distributions require confirmation.",
                    f"Ordinary business income: ${ordinary_income:,.0f}" if ordinary_income else "Ordinary business income requires confirmation.",
                    ratio_text,
                ],
                source_rule="1120S_REASONABLE_COMP_WITH_DISTRIBUTIONS",
                readiness="IMPLEMENT_NOW",
                estimated_savings_low=low,
                estimated_savings_high=high,
                audit_risk="Medium",
            )
        )

        risk_drivers.append("Officer compensation and shareholder distributions should be reviewed for reasonable compensation support.")

    if ordinary_income >= 150_000:
        low, high = estimate_retirement_savings(ordinary_income)

        strategies.append(
            RuleBasedStrategy(
                strategy_id="DTTS-004-retirement-plan-design",
                strategy_name="Retirement Plan Design",
                confidence="High",
                reason="High ordinary business income indicates potential capacity for qualified retirement plan contributions.",
                evidence=[
                    f"Ordinary business income: ${ordinary_income:,.0f}",
                    "No retirement plan deduction should be confirmed against the full return and general ledger.",
                    "Employee census and payroll data are required before implementation.",
                ],
                source_rule="1120S_HIGH_INCOME_RETIREMENT_PLAN_REVIEW",
                readiness="REVIEW_REQUIRED",
                estimated_savings_low=low,
                estimated_savings_high=high,
                audit_risk="Low",
            )
        )

        risk_drivers.append("High ordinary business income may create retirement plan design opportunity.")

    if ordinary_income >= 300_000:
        low, high = estimate_retirement_savings(ordinary_income)

        strategies.append(
            RuleBasedStrategy(
                strategy_id="DTTS-005-defined-benefit-cash-balance-plan",
                strategy_name="Defined Benefit / Cash Balance Plan",
                confidence="Medium",
                reason="High-income professional practice may benefit from advanced retirement plan modeling.",
                evidence=[
                    f"Ordinary business income: ${ordinary_income:,.0f}",
                    f"Officer compensation: ${officer_comp:,.0f}" if officer_comp else "Owner compensation requires confirmation.",
                    "Owner age, employee census, and actuarial feasibility are required.",
                ],
                source_rule="1120S_HIGH_INCOME_CASH_BALANCE_REVIEW",
                readiness="REVIEW_REQUIRED",
                estimated_savings_low=low,
                estimated_savings_high=high,
                audit_risk="Low",
            )
        )

        risk_drivers.append("High income supports reviewing cash balance or defined benefit plan feasibility.")

    if section_179 > 0 or planned_equipment_purchase > 0:
        low, high = estimate_depreciation_review_savings(section_179 or planned_equipment_purchase)

        evidence = [
            f"Section 179 deduction already claimed: ${section_179:,.0f}" if section_179 else "",
            f"Planned equipment purchase: ${planned_equipment_purchase:,.0f}" if planned_equipment_purchase else "",
            "Fixed asset schedule and Form 4562/depreciation schedules should be reviewed.",
        ]

        if form_4562_attached is False:
            evidence.append("Form 4562 is referenced but an attached Form 4562 schedule was not confirmed.")

        strategies.append(
            RuleBasedStrategy(
                strategy_id="DTTS-010-dental-equipment-depreciation",
                strategy_name="Dental Equipment Depreciation Planning",
                confidence="High" if section_179 else "Medium",
                reason="Equipment/depreciation activity exists and should be reconciled for current and future depreciation planning.",
                evidence=[item for item in evidence if item],
                source_rule="1120S_SECTION_179_OR_EQUIPMENT_REVIEW",
                readiness="REVIEW_REQUIRED",
                estimated_savings_low=low,
                estimated_savings_high=high,
                audit_risk="Medium",
            )
        )

        risk_drivers.append("Section 179/depreciation activity should be reconciled with fixed asset schedules.")

    if ending_retained_earnings < 0:
        risk_drivers.append("Negative retained earnings should be reviewed against AAA, shareholder basis, and distributions.")

    if has_1120s:
        strategies.append(
            RuleBasedStrategy(
                strategy_id="DTTS-003-accountable-plan",
                strategy_name="Accountable Plan",
                confidence="Medium",
                reason="S corporation shareholder/employees commonly need accountable plan review; the return alone does not prove a compliant plan exists.",
                evidence=[
                    "S corporation structure supports reviewing shareholder/employee reimbursement practices.",
                    "No accountable plan policy or reimbursement substantiation is proven by the return alone.",
                ],
                source_rule="1120S_ACCOUNTABLE_PLAN_REVIEW",
                readiness="REVIEW_REQUIRED",
                estimated_savings_low=1_000,
                estimated_savings_high=5_000,
                audit_risk="Low",
            )
        )

    if owns_practice_building or has_rental_properties:
        strategies.append(
            RuleBasedStrategy(
                strategy_id="DTTS-016-cost-segregation",
                strategy_name="Cost Segregation",
                confidence="Medium",
                reason="Real estate ownership/rental property facts indicate possible depreciation acceleration review.",
                evidence=[
                    "Practice building or rental property ownership indicated in questionnaire.",
                    "Building basis, improvement detail, and prior depreciation must be confirmed.",
                ],
                source_rule="REAL_ESTATE_COST_SEG_REVIEW",
                readiness="REVIEW_REQUIRED",
                estimated_savings_low=5_000,
                estimated_savings_high=50_000,
                audit_risk="Medium",
            )
        )

    strategies.append(
        RuleBasedStrategy(
            strategy_id="DTTS-050-tax-planning-fee-deduction",
            strategy_name="Tax Planning Fee Deduction",
            confidence="Low",
            reason="Professional tax/advisory fee classification should be reviewed, but invoices and general ledger are required.",
            evidence=[
                "Tax planning/advisory fees are not proven by the return alone.",
                "General ledger and invoices are required before claiming incremental deductions.",
            ],
            source_rule="PROFESSIONAL_FEE_CLASSIFICATION_REVIEW",
            readiness="REVIEW_REQUIRED",
            estimated_savings_low=500,
            estimated_savings_high=2_000,
            audit_risk="Low",
        )
    )

    return StrategyRuleResult(
        recommended_strategies=dedupe_strategies(strategies),
        risk_drivers=list(dict.fromkeys(risk_drivers)),
        facts_used=facts_used,
    )

def run_1040_rules(questionnaire: dict[str, Any], extracted_facts: dict[str, Any] | None = None) -> StrategyRuleResult:
    personal = questionnaire.get("personalQuestionnaire", {})
    financial = questionnaire.get("financialQuestionnaire", {})

    if not isinstance(personal, dict) or not isinstance(financial, dict):
        raise StrategyRulesError("Questionnaire must contain personalQuestionnaire and financialQuestionnaire objects.")

    household_income = safe_float(personal.get("householdIncome"))
    wages = safe_float(personal.get("clientAnnualCompensation"))

    facts = extracted_facts if isinstance(extracted_facts, dict) else {}
    fact_fields = facts.get("facts", {}) if isinstance(facts.get("facts"), dict) else {}

    def fact_value(key: str, default: Any = None) -> Any:
        item = fact_fields.get(key)
        return item.get("value", default) if isinstance(item, dict) else default

    qbi_deduction = safe_float(fact_value("qbi_deduction"))
    taxable_income = safe_float(fact_value("taxable_income"))
    total_tax = safe_float(fact_value("total_tax"))
    amount_owed = safe_float(fact_value("amount_owed"))
    capital_gain_or_loss = safe_float(fact_value("capital_gain_or_loss"))

    strategies: list[RuleBasedStrategy] = []
    risk_drivers: list[str] = []

    facts_used = {
        "primary_form_type": "1040",
        "household_income": household_income,
        "wages": wages,
        "qbi_deduction": qbi_deduction,
        "taxable_income": taxable_income,
        "total_tax": total_tax,
        "amount_owed": amount_owed,
        "capital_gain_or_loss": capital_gain_or_loss,
    }

    if qbi_deduction > 0:
        strategies.append(
            RuleBasedStrategy(
                strategy_id="DTTS-002-qbi-deduction-optimization",
                strategy_name="QBI Deduction Optimization",
                confidence="High",
                reason="Form 1040 shows a QBI deduction, so QBI eligibility and limitation optimization should be reviewed.",
                evidence=[
                    f"QBI deduction reported: ${qbi_deduction:,.0f}",
                    f"Taxable income reported: ${taxable_income:,.0f}" if taxable_income else "Taxable income requires confirmation.",
                    "Shareholder/business-level QBI details are required before final planning.",
                ],
                source_rule="1040_QBI_DEDUCTION_PRESENT",
                readiness="REVIEW_REQUIRED",
                estimated_savings_low=0,
                estimated_savings_high=0,
                audit_risk="Medium",
            )
        )

        risk_drivers.append("QBI deduction is present and should be reviewed against business income, SSTB status, and income thresholds.")

    if household_income >= 200_000 or wages >= 200_000:
        low, high = estimate_retirement_savings(max(household_income, wages))

        strategies.append(
            RuleBasedStrategy(
                strategy_id="DTTS-004-retirement-plan-design",
                strategy_name="Retirement Plan Design",
                confidence="Medium",
                reason="High household income may create retirement planning and tax deferral opportunities.",
                evidence=[
                    f"Household income: ${household_income:,.0f}" if household_income else "",
                    f"Wages: ${wages:,.0f}" if wages else "",
                    "Current retirement plan participation and employer plan details are required.",
                ],
                source_rule="1040_HIGH_INCOME_RETIREMENT_REVIEW",
                readiness="REVIEW_REQUIRED",
                estimated_savings_low=low,
                estimated_savings_high=high,
                audit_risk="Low",
            )
        )

        risk_drivers.append("High income supports reviewing retirement contribution and deferral opportunities.")

    if household_income >= 200_000 or taxable_income >= 150_000:
        strategies.append(
            RuleBasedStrategy(
                strategy_id="DTTS-009-state-and-local-tax-planning",
                strategy_name="State and Local Tax Planning",
                confidence="Medium",
                reason="Income level supports reviewing state residency, withholding, estimated payments, and SALT exposure.",
                evidence=[
                    f"Household income: ${household_income:,.0f}" if household_income else "",
                    f"Taxable income: ${taxable_income:,.0f}" if taxable_income else "",
                    "State return, residency facts, and state tax payments are required before recommendations.",
                ],
                source_rule="1040_HIGH_INCOME_SALT_REVIEW",
                readiness="REVIEW_REQUIRED",
                estimated_savings_low=0,
                estimated_savings_high=0,
                audit_risk="Medium",
            )
        )

        risk_drivers.append("Income level supports state and local tax planning review.")

    if amount_owed > 0:
        risk_drivers.append(f"Amount owed of ${amount_owed:,.0f} suggests withholding or estimated payment planning should be reviewed.")

    if capital_gain_or_loss > 0:
        risk_drivers.append(f"Capital gain of ${capital_gain_or_loss:,.0f} indicates investment tax planning should be reviewed.")

    return StrategyRuleResult(
        recommended_strategies=dedupe_strategies(strategies),
        risk_drivers=list(dict.fromkeys(risk_drivers)),
        facts_used=facts_used,
    )

def run_1065_rules(questionnaire: dict[str, Any], extracted_facts: dict[str, Any] | None = None) -> StrategyRuleResult:
    personal = questionnaire.get("personalQuestionnaire", {})
    financial = questionnaire.get("financialQuestionnaire", {})

    if not isinstance(personal, dict) or not isinstance(financial, dict):
        raise StrategyRulesError("Questionnaire must contain personalQuestionnaire and financialQuestionnaire objects.")

    has_1065 = safe_bool(personal.get("has1065"))
    partnership_income = safe_float(personal.get("householdIncome"))
    gross_receipts = safe_float(personal.get("managementCompanyRevenue"))
    guaranteed_payments = safe_float(personal.get("partnershipGuaranteedPayments"))
    owns_practice_building = safe_bool(personal.get("ownsPracticeBuilding"))
    has_rental_properties = safe_bool(personal.get("hasRentalProperties"))

    facts = extracted_facts if isinstance(extracted_facts, dict) else {}
    fact_fields = facts.get("facts", {}) if isinstance(facts.get("facts"), dict) else {}

    def fact_value(key: str, default: Any = None) -> Any:
        item = fact_fields.get(key)
        return item.get("value", default) if isinstance(item, dict) else default

    total_assets = safe_float(fact_value("total_assets"))
    number_of_schedules_k1 = safe_float(fact_value("number_of_schedules_k1"))
    ordinary_business_income = safe_float(fact_value("ordinary_business_income", partnership_income))
    total_deductions = safe_float(fact_value("total_deductions"))
    cost_of_goods_sold = safe_float(fact_value("cost_of_goods_sold"))

    strategies: list[RuleBasedStrategy] = []
    risk_drivers: list[str] = []

    facts_used = {
        "has1065": has_1065,
        "gross_receipts": gross_receipts,
        "ordinary_business_income": ordinary_business_income,
        "partnership_income": partnership_income,
        "guaranteed_payments": guaranteed_payments,
        "total_assets": total_assets,
        "number_of_schedules_k1": number_of_schedules_k1,
        "total_deductions": total_deductions,
        "cost_of_goods_sold": cost_of_goods_sold,
        "owns_practice_building": owns_practice_building,
        "has_rental_properties": has_rental_properties,
    }

    if not has_1065:
        return StrategyRuleResult(
            recommended_strategies=[],
            risk_drivers=["No 1065 flag found in questionnaire; 1065 rules skipped."],
            facts_used=facts_used,
        )

    if ordinary_business_income > 0:
        strategies.append(
            RuleBasedStrategy(
                strategy_id="DTTS-002-qbi-deduction-optimization",
                strategy_name="QBI Deduction Optimization",
                confidence="High",
                reason="Partnership has ordinary business income that may flow through to partners for QBI analysis.",
                evidence=[
                    f"Ordinary business income: ${ordinary_business_income:,.0f}",
                    "Partner-level taxable income, SSTB status, W-2 wages, and UBIA details are required.",
                ],
                source_rule="1065_QBI_REVIEW_WITH_ORDINARY_INCOME",
                readiness="REVIEW_REQUIRED",
                estimated_savings_low=0,
                estimated_savings_high=0,
                audit_risk="Medium",
            )
        )
        risk_drivers.append("Partnership ordinary income should be reviewed for partner-level QBI treatment.")

    if gross_receipts > 500_000 or total_assets > 500_000:
        strategies.append(
            RuleBasedStrategy(
                strategy_id="DTTS-008-entity-structure-review",
                strategy_name="Entity Structure Review",
                confidence="Medium",
                reason="Partnership has material receipts/assets, supporting review of ownership, allocation, and entity structure.",
                evidence=[
                    f"Gross receipts: ${gross_receipts:,.0f}" if gross_receipts else "",
                    f"Total assets: ${total_assets:,.0f}" if total_assets else "",
                    f"Number of Schedules K-1: {number_of_schedules_k1:,.0f}" if number_of_schedules_k1 else "",
                    "Partnership agreement and ownership percentages are required.",
                ],
                source_rule="1065_MATERIAL_ENTITY_STRUCTURE_REVIEW",
                readiness="REVIEW_REQUIRED",
                estimated_savings_low=0,
                estimated_savings_high=0,
                audit_risk="Medium",
            )
        )
        risk_drivers.append("Material partnership receipts/assets support entity structure and allocation review.")

    if ordinary_business_income >= 250_000:
        low, high = estimate_retirement_savings(ordinary_business_income)

        strategies.append(
            RuleBasedStrategy(
                strategy_id="DTTS-004-retirement-plan-design",
                strategy_name="Retirement Plan Design",
                confidence="Medium",
                reason="Partnership income may support qualified retirement plan design, subject to partner and employee census details.",
                evidence=[
                    f"Ordinary business income: ${ordinary_business_income:,.0f}",
                    "Employee census, partner compensation/SE income, and current plan details are required.",
                ],
                source_rule="1065_INCOME_RETIREMENT_PLAN_REVIEW",
                readiness="REVIEW_REQUIRED",
                estimated_savings_low=low,
                estimated_savings_high=high,
                audit_risk="Low",
            )
        )
        risk_drivers.append("Partnership income supports reviewing retirement plan design.")

    if guaranteed_payments > 0:
        strategies.append(
            RuleBasedStrategy(
                strategy_id="DTTS-008-entity-structure-review",
                strategy_name="Entity Structure Review",
                confidence="High",
                reason="Guaranteed payments require review against partnership agreement and partner compensation economics.",
                evidence=[
                    f"Guaranteed payments: ${guaranteed_payments:,.0f}",
                    "Partnership agreement and partner allocation provisions are required.",
                ],
                source_rule="1065_GUARANTEED_PAYMENT_REVIEW",
                readiness="REVIEW_REQUIRED",
                estimated_savings_low=0,
                estimated_savings_high=0,
                audit_risk="Medium",
            )
        )
        risk_drivers.append("Guaranteed payments should be reviewed against partnership agreement and allocation terms.")

    if owns_practice_building or has_rental_properties:
        strategies.append(
            RuleBasedStrategy(
                strategy_id="DTTS-016-cost-segregation",
                strategy_name="Cost Segregation",
                confidence="Medium",
                reason="Real estate ownership/rental property facts may support depreciation acceleration review.",
                evidence=[
                    "Practice building or rental property ownership indicated in questionnaire.",
                    "Building basis, improvement detail, and prior depreciation schedules are required.",
                ],
                source_rule="1065_REAL_ESTATE_COST_SEG_REVIEW",
                readiness="REVIEW_REQUIRED",
                estimated_savings_low=5_000,
                estimated_savings_high=50_000,
                audit_risk="Medium",
            )
        )
        risk_drivers.append("Real estate ownership may support cost segregation review.")

    strategies.append(
        RuleBasedStrategy(
            strategy_id="DTTS-050-tax-planning-fee-deduction",
            strategy_name="Tax Planning Fee Deduction",
            confidence="Low",
            reason="Professional tax/advisory fee classification should be reviewed, but invoices and general ledger are required.",
            evidence=[
                "Partnership return complexity supports reviewing professional fee classification.",
                "General ledger and invoices are required before claiming incremental deductions.",
            ],
            source_rule="1065_PROFESSIONAL_FEE_CLASSIFICATION_REVIEW",
            readiness="REVIEW_REQUIRED",
            estimated_savings_low=500,
            estimated_savings_high=2_000,
            audit_risk="Low",
        )
    )

    return StrategyRuleResult(
        recommended_strategies=dedupe_strategies(strategies),
        risk_drivers=list(dict.fromkeys(risk_drivers)),
        facts_used=facts_used,
    )


def run_strategy_rules(
    questionnaire: dict[str, Any],
    *,
    primary_form_type: str,
    extracted_facts: dict[str, Any] | None = None,
) -> StrategyRuleResult:
    normalized_form_type = (primary_form_type or "").upper().replace("-", "").replace("FORM", "").strip()

    if normalized_form_type == "1120S":
        return run_1120s_rules(questionnaire, extracted_facts=extracted_facts)
    if normalized_form_type == "1040":
        return run_1040_rules(questionnaire, extracted_facts=extracted_facts)

    if normalized_form_type == "1065":
        return run_1065_rules(questionnaire, extracted_facts=extracted_facts)


    return StrategyRuleResult(
        recommended_strategies=[],
        risk_drivers=[f"No deterministic strategy rules implemented yet for form type: {primary_form_type}"],
        facts_used={"primary_form_type": primary_form_type},
    )


def main() -> None:
    import argparse

    from fact_extractor import extract_facts_from_pdf_file
    from questionnaire import get_default_questionnaire, merge_fact_extraction_result_into_questionnaire

    parser = argparse.ArgumentParser(description="Run deterministic strategy rules from a tax PDF.")
    parser.add_argument("pdf", help="Path to PDF file")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args()

    facts_result = extract_facts_from_pdf_file(args.pdf).to_dict()
    questionnaire_result = merge_fact_extraction_result_into_questionnaire(
        get_default_questionnaire(),
        facts_result,
        overwrite=True,
    )

    questionnaire = questionnaire_result["questionnaire"]

    extraction_cards = facts_result.get("extraction_cards", [])
    extracted_facts: dict[str, Any] = {"facts": {}}

    if extraction_cards:
        first_card = extraction_cards[0]
        fields = first_card.get("fields", {})

        if isinstance(fields, dict):
            for field_name, payload in fields.items():
                if isinstance(payload, dict):
                    extracted_facts["facts"][field_name] = {
                        "value": payload.get("value"),
                        "source": payload.get("source_line"),
                        "confidence": payload.get("confidence"),
                    }

    result = run_strategy_rules(
        questionnaire,
        primary_form_type=str(facts_result.get("primary_form_type") or ""),
        extracted_facts=extracted_facts,
    )

    print(json.dumps(result.to_dict(), indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
