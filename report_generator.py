from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ReportGeneratorError(Exception):
    """Raised when final report generation fails."""


VALID_DECISIONS = {"recommend", "decline", "defer", "undecided"}


@dataclass(frozen=True)
class StrategyDecision:
    strategy_name: str
    decision: str = "undecided"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_name": self.strategy_name,
            "decision": self.decision,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class FinalStrategy:
    strategy_id: str
    strategy_name: str
    decision: str
    confidence: str
    confidence_score: float
    reason: str
    evidence_basis: list[str]
    missing_information: list[str]
    readiness: str
    sources: list[str]
    estimated_savings_low: float
    estimated_savings_high: float
    audit_risk: str
    user_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "decision": self.decision,
            "confidence": self.confidence,
            "confidence_score": round(self.confidence_score, 4),
            "reason": self.reason,
            "evidence_basis": list(self.evidence_basis),
            "missing_information": list(self.missing_information),
            "readiness": self.readiness,
            "sources": list(self.sources),
            "estimated_savings_low": round(self.estimated_savings_low, 2),
            "estimated_savings_high": round(self.estimated_savings_high, 2),
            "audit_risk": self.audit_risk,
            "user_notes": self.user_notes,
        }


@dataclass(frozen=True)
class FinalTaxTruthReport:
    client_id: str
    generated_at: str
    form_type: str
    extracted_forms: list[str]
    questionnaire: dict[str, Any]
    extraction_cards: list[dict[str, Any]]
    recommended_strategies: list[FinalStrategy]
    declined_strategies: list[FinalStrategy]
    deferred_strategies: list[FinalStrategy]
    undecided_strategies: list[FinalStrategy]
    total_estimated_savings_low: float
    total_estimated_savings_high: float
    guardrails: dict[str, Any]
    source_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "generated_at": self.generated_at,
            "formType": self.form_type,
            "extractedForms": list(self.extracted_forms),
            "questionnaire": self.questionnaire,
            "extractionCards": list(self.extraction_cards),
            "recommendedStrategies": [strategy.to_dict() for strategy in self.recommended_strategies],
            "declinedStrategies": [strategy.to_dict() for strategy in self.declined_strategies],
            "deferredStrategies": [strategy.to_dict() for strategy in self.deferred_strategies],
            "undecidedStrategies": [strategy.to_dict() for strategy in self.undecided_strategies],
            "totalEstimatedSavingsLow": round(self.total_estimated_savings_low, 2),
            "totalEstimatedSavingsHigh": round(self.total_estimated_savings_high, 2),
            "guardrails": dict(self.guardrails),
            "sourceSummary": dict(self.source_summary),
        }


def utc_now_string() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default

    if isinstance(value, int | float):
        return float(value)

    if isinstance(value, str):
        cleaned = value.replace("$", "").replace(",", "").strip()

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


def normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []

    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]

    return []


def dedupe_strings(items: list[str]) -> list[str]:
    output: list[str] = []

    for item in items:
        cleaned = str(item).strip()

        if cleaned and cleaned not in output:
            output.append(cleaned)

    return output


def confidence_to_score(confidence: Any) -> float:
    if isinstance(confidence, int | float):
        value = float(confidence)

        if 0 <= value <= 1:
            return value

        if 1 < value <= 100:
            return value / 100

    text = str(confidence or "").strip().lower()

    if text == "high":
        return 0.90

    if text == "medium":
        return 0.65

    if text == "low":
        return 0.35

    return 0.50


def confidence_to_label(score: float) -> str:
    if score >= 0.80:
        return "High"

    if score >= 0.50:
        return "Medium"

    return "Low"


def normalize_decision(value: Any) -> str:
    decision = str(value or "undecided").strip().lower()

    if decision not in VALID_DECISIONS:
        return "undecided"

    return decision


def build_decision_map(decisions: list[dict[str, Any]] | None) -> dict[str, StrategyDecision]:
    if not decisions:
        return {}

    decision_map: dict[str, StrategyDecision] = {}

    for item in decisions:
        if not isinstance(item, dict):
            continue

        strategy_name = str(item.get("strategy_name") or item.get("strategy") or "").strip()

        if not strategy_name:
            continue

        decision_map[strategy_name] = StrategyDecision(
            strategy_name=strategy_name,
            decision=normalize_decision(item.get("decision")),
            notes=str(item.get("notes") or "").strip(),
        )

    return decision_map


def extract_rule_strategy_payloads(rule_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}

    strategies = rule_result.get("recommended_strategies", [])

    if not isinstance(strategies, list):
        return payloads

    for strategy in strategies:
        if not isinstance(strategy, dict):
            continue

        strategy_name = str(strategy.get("strategy_name") or "").strip()

        if not strategy_name:
            continue

        payloads[strategy_name] = strategy

    return payloads


def extract_ai_strategy_payloads(ai_match_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}

    strategies = ai_match_result.get("ai_matches", [])

    if not isinstance(strategies, list):
        return payloads

    for strategy in strategies:
        if not isinstance(strategy, dict):
            continue

        strategy_name = str(strategy.get("strategy_name") or "").strip()

        if not strategy_name:
            continue

        payloads[strategy_name] = strategy

    return payloads


def merge_strategy_payloads(
    rule_payloads: dict[str, dict[str, Any]],
    ai_payloads: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    names = sorted(set(rule_payloads) | set(ai_payloads))
    merged: list[dict[str, Any]] = []

    for name in names:
        rule = rule_payloads.get(name, {})
        ai = ai_payloads.get(name, {})

        strategy_id = (
            ai.get("strategy_id")
            or rule.get("strategy_id")
            or ""
        )

        confidence_score = max(
            confidence_to_score(ai.get("confidence_score", ai.get("confidence"))),
            confidence_to_score(rule.get("confidence")),
        )

        evidence = dedupe_strings(
            [
                *normalize_string_list(rule.get("evidence")),
                *normalize_string_list(ai.get("evidence_basis")),
            ]
        )

        missing_information = normalize_string_list(ai.get("missing_information"))

        reason_parts = [
            str(rule.get("reason") or "").strip(),
            str(ai.get("reason") or "").strip(),
        ]
        reason = " ".join(part for part in reason_parts if part).strip()

        readiness = str(ai.get("readiness") or rule.get("readiness") or "REVIEW_REQUIRED").strip().upper()

        sources: list[str] = []

        if rule:
            sources.append("RULE_ENGINE")

        if ai:
            sources.append("AI_MATCHER")

        merged.append(
            {
                "strategy_id": strategy_id,
                "strategy_name": name,
                "confidence": confidence_to_label(confidence_score),
                "confidence_score": confidence_score,
                "reason": reason,
                "evidence_basis": evidence,
                "missing_information": missing_information,
                "readiness": readiness,
                "sources": sources,
                "estimated_savings_low": safe_float(rule.get("estimated_savings_low")),
                "estimated_savings_high": safe_float(rule.get("estimated_savings_high")),
                "audit_risk": str(rule.get("audit_risk") or "Medium"),
            }
        )

    merged.sort(
        key=lambda item: (
            item["confidence_score"],
            item["estimated_savings_high"],
        ),
        reverse=True,
    )

    return merged


def build_final_strategy(payload: dict[str, Any], decision: StrategyDecision) -> FinalStrategy:
    return FinalStrategy(
        strategy_id=str(payload.get("strategy_id") or ""),
        strategy_name=str(payload.get("strategy_name") or ""),
        decision=decision.decision,
        confidence=str(payload.get("confidence") or "Medium"),
        confidence_score=safe_float(payload.get("confidence_score"), 0.50),
        reason=str(payload.get("reason") or ""),
        evidence_basis=normalize_string_list(payload.get("evidence_basis")),
        missing_information=normalize_string_list(payload.get("missing_information")),
        readiness=str(payload.get("readiness") or "REVIEW_REQUIRED"),
        sources=normalize_string_list(payload.get("sources")),
        estimated_savings_low=safe_float(payload.get("estimated_savings_low")),
        estimated_savings_high=safe_float(payload.get("estimated_savings_high")),
        audit_risk=str(payload.get("audit_risk") or "Medium"),
        user_notes=decision.notes,
    )


def generate_final_report(
    *,
    client_id: str,
    fact_extraction_result: dict[str, Any],
    questionnaire: dict[str, Any],
    rule_result: dict[str, Any],
    ai_match_result: dict[str, Any],
    decisions: list[dict[str, Any]] | None = None,
) -> FinalTaxTruthReport:
    form_type = str(fact_extraction_result.get("primary_form_type") or "UNKNOWN")
    extracted_forms = normalize_string_list(fact_extraction_result.get("forms_found"))
    extraction_cards = fact_extraction_result.get("extraction_cards", [])

    if not isinstance(extraction_cards, list):
        extraction_cards = []

    decision_map = build_decision_map(decisions)

    rule_payloads = extract_rule_strategy_payloads(rule_result)
    ai_payloads = extract_ai_strategy_payloads(ai_match_result)

    merged_payloads = merge_strategy_payloads(rule_payloads, ai_payloads)

    recommended: list[FinalStrategy] = []
    declined: list[FinalStrategy] = []
    deferred: list[FinalStrategy] = []
    undecided: list[FinalStrategy] = []

    for payload in merged_payloads:
        strategy_name = str(payload.get("strategy_name") or "")
        decision = decision_map.get(strategy_name, StrategyDecision(strategy_name=strategy_name))

        final_strategy = build_final_strategy(payload, decision)

        if final_strategy.decision == "recommend":
            recommended.append(final_strategy)
        elif final_strategy.decision == "decline":
            declined.append(final_strategy)
        elif final_strategy.decision == "defer":
            deferred.append(final_strategy)
        else:
            undecided.append(final_strategy)

    total_low = sum(strategy.estimated_savings_low for strategy in recommended)
    total_high = sum(strategy.estimated_savings_high for strategy in recommended)

    source_summary = {
        "primary_form_type": form_type,
        "forms_found": extracted_forms,
        "rule_strategy_count": len(rule_payloads),
        "ai_match_count": len(ai_payloads),
        "recommended_count": len(recommended),
        "declined_count": len(declined),
        "deferred_count": len(deferred),
        "undecided_count": len(undecided),
    }

    return FinalTaxTruthReport(
        client_id=client_id,
        generated_at=utc_now_string(),
        form_type=form_type,
        extracted_forms=extracted_forms,
        questionnaire=questionnaire,
        extraction_cards=extraction_cards,
        recommended_strategies=recommended,
        declined_strategies=declined,
        deferred_strategies=deferred,
        undecided_strategies=undecided,
        total_estimated_savings_low=total_low,
        total_estimated_savings_high=total_high,
        guardrails={
            "not_tax_advice": True,
            "requires_cpa_review": True,
            "savings_are_directional_estimates": True,
            "strategies_count_only_after_recommend_decision": True,
            "declined_and_deferred_excluded_from_totals": True,
            "no_silent_field_merging": True,
        },
        source_summary=source_summary,
    )


def main() -> None:
    import argparse

    from fact_extractor import extract_facts_from_pdf_file
    from questionnaire import get_default_questionnaire, merge_fact_extraction_result_into_questionnaire
    from strategy_ai_matcher import match_strategies_with_ai
    from strategy_rules import run_strategy_rules

    parser = argparse.ArgumentParser(description="Generate final TaxTruth report from a tax PDF.")
    parser.add_argument("pdf", help="Path to PDF file")
    parser.add_argument("--client-id", default="ai_client_name", help="Client ID")
    parser.add_argument("--recommend-all", action="store_true", help="For testing only: mark all strategies as recommend")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args()

    fact_result = extract_facts_from_pdf_file(args.pdf).to_dict()

    questionnaire_merge = merge_fact_extraction_result_into_questionnaire(
        get_default_questionnaire(),
        fact_result,
        overwrite=True,
    )
    questionnaire = questionnaire_merge["questionnaire"]

    extracted_facts: dict[str, Any] = {"facts": {}}
    extraction_cards = fact_result.get("extraction_cards", [])

    if extraction_cards:
        fields = extraction_cards[0].get("fields", {})

        if isinstance(fields, dict):
            for field_name, payload in fields.items():
                if isinstance(payload, dict):
                    extracted_facts["facts"][field_name] = {
                        "value": payload.get("value"),
                        "source": payload.get("source_line"),
                        "confidence": payload.get("confidence"),
                    }

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

    decisions: list[dict[str, Any]] = []

    if args.recommend_all:
        strategy_names = {
            strategy.get("strategy_name")
            for strategy in rule_result.get("recommended_strategies", [])
            if isinstance(strategy, dict)
        } | {
            strategy.get("strategy_name")
            for strategy in ai_result.get("ai_matches", [])
            if isinstance(strategy, dict)
        }

        decisions = [
            {
                "strategy_name": str(strategy_name),
                "decision": "recommend",
                "notes": "Auto-recommended for CLI testing only.",
            }
            for strategy_name in sorted(strategy_names)
            if strategy_name
        ]

    report = generate_final_report(
        client_id=args.client_id,
        fact_extraction_result=fact_result,
        questionnaire=questionnaire,
        rule_result=rule_result,
        ai_match_result=ai_result,
        decisions=decisions,
    )

    print(json.dumps(report.to_dict(), indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
