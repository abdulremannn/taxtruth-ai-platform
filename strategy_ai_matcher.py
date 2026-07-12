from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ai_report_generator import APPROVED_STRATEGIES, DEFAULT_OPENAI_MODEL, OPENAI_API_URL, get_form_policy


class StrategyAIMatcherError(Exception):
    """Raised when AI strategy matching fails."""


@dataclass(frozen=True)
class AIStrategyMatch:
    strategy_id: str
    strategy_name: str
    confidence: str
    confidence_score: float
    reason: str
    evidence_basis: list[str] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    readiness: str = "REVIEW_REQUIRED"
    source: str = "AI_MATCHER"
    overlaps_with_rule: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "confidence": self.confidence,
            "confidence_score": round(self.confidence_score, 4),
            "reason": self.reason,
            "evidence_basis": list(self.evidence_basis),
            "missing_information": list(self.missing_information),
            "readiness": self.readiness,
            "source": self.source,
            "overlaps_with_rule": self.overlaps_with_rule,
        }


@dataclass(frozen=True)
class StrategyAIMatchResult:
    primary_form_type: str
    ai_matches: list[AIStrategyMatch]
    rejected_matches: list[dict[str, Any]]
    approved_strategy_names_used: list[str]
    guardrails: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_form_type": self.primary_form_type,
            "ai_matches": [match.to_dict() for match in self.ai_matches],
            "rejected_matches": list(self.rejected_matches),
            "approved_strategy_names_used": list(self.approved_strategy_names_used),
            "guardrails": dict(self.guardrails),
        }


def load_local_env_file() -> None:
    env_path = Path(__file__).resolve().parent / ".env"

    if not env_path.exists():
        return

    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for line in lines:
        stripped = line.strip()

        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and value and key not in os.environ:
            os.environ[key] = value


def clean_json_text(text: str) -> str:
    cleaned = text.strip()

    if cleaned.startswith("```json"):
        cleaned = cleaned.removeprefix("```json").strip()

    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```").strip()

    if cleaned.endswith("```"):
        cleaned = cleaned.removesuffix("```").strip()

    return cleaned


def normalize_form_type(form_type: str | None) -> str:
    return (form_type or "").upper().replace("-", "").replace("FORM", "").strip()


def approved_strategy_by_name(strategy_name: str) -> dict[str, Any] | None:
    return next(
        (strategy for strategy in APPROVED_STRATEGIES if strategy["strategy_name"] == strategy_name),
        None,
    )


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


def confidence_to_label(confidence_score: float) -> str:
    if confidence_score >= 0.80:
        return "High"

    if confidence_score >= 0.50:
        return "Medium"

    return "Low"


def normalize_readiness(value: Any) -> str:
    readiness = str(value or "REVIEW_REQUIRED").strip().upper()

    if readiness not in {"IMPLEMENT_NOW", "REVIEW_REQUIRED", "PREREQUISITE_BUILD", "DEFER"}:
        return "REVIEW_REQUIRED"

    return readiness


def extract_rule_strategy_names(rule_result: dict[str, Any]) -> set[str]:
    strategies = rule_result.get("recommended_strategies", [])

    if not isinstance(strategies, list):
        return set()

    output: set[str] = set()

    for strategy in strategies:
        if not isinstance(strategy, dict):
            continue

        strategy_name = str(strategy.get("strategy_name") or "").strip()

        if strategy_name:
            output.add(strategy_name)

    return output


def build_matcher_system_prompt() -> str:
    approved_names = [strategy["strategy_name"] for strategy in APPROVED_STRATEGIES]

    return f"""
You are TaxTruth's AI strategy matcher.

You behave like a highly conservative CPA strategy analyst.
You do NOT prepare final tax advice.
You identify planning candidates for CPA review only.

Rules:
1. Return ONLY valid JSON.
2. Never invent strategy names.
3. Select strategies ONLY from the allowed strategy list provided by the user message.
4. Use extracted facts and questionnaire data as evidence.
5. Do not infer facts that are not present.
6. If data is missing, add it to missing_information and use REVIEW_REQUIRED or PREREQUISITE_BUILD.
7. If a deterministic rule already recommended a strategy, you may still include it only if you add useful CPA reasoning.
8. Do not include savings estimates here. This matcher only selects and explains strategies.

Full approved strategy database:
{json.dumps(approved_names, indent=2)}

Required JSON shape:
{{
  "matches": [
    {{
      "strategy_name": "exact approved strategy name",
      "confidence": "High | Medium | Low",
      "confidence_score": 0.0,
      "reason": "short reason",
      "evidence_basis": ["source-based evidence"],
      "missing_information": ["missing data needed before implementation"],
      "readiness": "IMPLEMENT_NOW | REVIEW_REQUIRED | PREREQUISITE_BUILD | DEFER"
    }}
  ]
}}
""".strip()


def build_matcher_user_prompt(
    *,
    primary_form_type: str,
    questionnaire: dict[str, Any],
    fact_extraction_result: dict[str, Any],
    rule_result: dict[str, Any],
    max_matches: int,
) -> str:
    policy = get_form_policy(primary_form_type)
    allowed_strategy_names = sorted(policy["allowed_strategy_names"])

    return f"""
Match tax planning strategies for this client.

Primary form type:
{primary_form_type}

Form policy:
{json.dumps(policy, indent=2, default=list)}

Allowed strategy names for this form:
{json.dumps(allowed_strategy_names, indent=2)}

Questionnaire:
{json.dumps(questionnaire, indent=2)}

Fact extraction result:
{json.dumps(fact_extraction_result, indent=2)}

Deterministic rule result:
{json.dumps(rule_result, indent=2)}

Instructions:
- Return at most {max_matches} strategy matches.
- Every strategy_name must exactly match one item in the allowed strategy names list.
- Do not recommend S-corp-only strategies for 1040, 1065, or 1120 unless the allowed list includes them.
- If a strategy is already included in deterministic rule result, you may include it only with additional CPA-level reasoning.
- If facts are missing, do not guess. Put missing facts in missing_information.
- Use REVIEW_REQUIRED when implementation depends on payroll, basis, GL, invoices, census, ownership, or shareholder-level data.
- Use IMPLEMENT_NOW only to mean begin professional review/workflow, not final tax filing position.
- Return valid JSON only.
""".strip()


def call_openai_json(messages: list[dict[str, str]]) -> dict[str, Any]:
    load_local_env_file()

    api_key = os.getenv("OPENAI_API_KEY", "").strip()

    if not api_key:
        raise StrategyAIMatcherError(
            "OPENAI_API_KEY is missing. Create a .env file and add OPENAI_API_KEY=your_actual_key."
        )

    if not api_key.startswith("sk-"):
        raise StrategyAIMatcherError("OPENAI_API_KEY appears invalid. It should usually start with 'sk-' or 'sk-proj-'.")

    model = os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip() or DEFAULT_OPENAI_MODEL

    payload = {
        "model": model,
        "temperature": 0.1,
        "max_tokens": 6000,
        "response_format": {"type": "json_object"},
        "messages": messages,
    }

    request = urllib.request.Request(
        OPENAI_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            response_body = response.read().decode("utf-8")

    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise StrategyAIMatcherError(f"OpenAI API error {exc.code}: {error_body}") from exc

    except urllib.error.URLError as exc:
        raise StrategyAIMatcherError(f"Unable to connect to OpenAI API: {exc}") from exc

    try:
        api_response = json.loads(response_body)
        content = api_response["choices"][0]["message"]["content"]
        return json.loads(clean_json_text(content))

    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise StrategyAIMatcherError("OpenAI returned an invalid JSON response.") from exc


def normalize_ai_matches(
    raw_response: dict[str, Any],
    *,
    primary_form_type: str,
    allowed_strategy_names: set[str],
    rule_strategy_names: set[str],
) -> tuple[list[AIStrategyMatch], list[dict[str, Any]]]:
    raw_matches = raw_response.get("matches", [])

    if not isinstance(raw_matches, list):
        raise StrategyAIMatcherError("AI matcher response must contain a 'matches' list.")

    matches: list[AIStrategyMatch] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in raw_matches:
        if not isinstance(item, dict):
            rejected.append(
                {
                    "reason": "Match item was not an object.",
                    "item": item,
                }
            )
            continue

        strategy_name = str(item.get("strategy_name") or item.get("strategy") or "").strip()

        if not strategy_name:
            rejected.append(
                {
                    "reason": "Missing strategy_name.",
                    "item": item,
                }
            )
            continue

        if strategy_name in seen:
            rejected.append(
                {
                    "strategy_name": strategy_name,
                    "reason": "Duplicate strategy returned by AI.",
                }
            )
            continue

        if strategy_name not in allowed_strategy_names:
            rejected.append(
                {
                    "strategy_name": strategy_name,
                    "reason": f"Strategy is not allowed for form type {primary_form_type}.",
                }
            )
            continue

        approved = approved_strategy_by_name(strategy_name)

        if approved is None:
            rejected.append(
                {
                    "strategy_name": strategy_name,
                    "reason": "Strategy is not in approved strategy database.",
                }
            )
            continue

        confidence_score = confidence_to_score(item.get("confidence_score", item.get("confidence")))
        confidence_label = confidence_to_label(confidence_score)
        readiness = normalize_readiness(item.get("readiness"))

        evidence_basis = normalize_string_list(item.get("evidence_basis"))
        missing_information = normalize_string_list(item.get("missing_information"))
        reason = str(item.get("reason") or "").strip()

        if not reason:
            rejected.append(
                {
                    "strategy_name": strategy_name,
                    "reason": "Missing reason.",
                }
            )
            continue

        if not evidence_basis:
            evidence_basis = ["AI selected this strategy from questionnaire and extracted facts; CPA must confirm evidence."]

        match = AIStrategyMatch(
            strategy_id=approved["strategy_id"],
            strategy_name=approved["strategy_name"],
            confidence=confidence_label,
            confidence_score=confidence_score,
            reason=reason,
            evidence_basis=dedupe_strings(evidence_basis),
            missing_information=dedupe_strings(missing_information),
            readiness=readiness,
            source="AI_MATCHER",
            overlaps_with_rule=strategy_name in rule_strategy_names,
        )

        seen.add(strategy_name)
        matches.append(match)

    matches.sort(key=lambda match: match.confidence_score, reverse=True)

    return matches, rejected


def match_strategies_with_ai(
    *,
    primary_form_type: str,
    questionnaire: dict[str, Any],
    fact_extraction_result: dict[str, Any],
    rule_result: dict[str, Any],
    max_matches: int = 8,
) -> StrategyAIMatchResult:
    normalized_form_type = normalize_form_type(primary_form_type)
    policy = get_form_policy(normalized_form_type)
    allowed_strategy_names = set(policy["allowed_strategy_names"])

    if not allowed_strategy_names:
        return StrategyAIMatchResult(
            primary_form_type=normalized_form_type or "UNKNOWN",
            ai_matches=[],
            rejected_matches=[],
            approved_strategy_names_used=[],
            guardrails={
                "ai_strategy_matching_enabled": False,
                "reason": f"No allowed strategies configured for form type {primary_form_type}.",
            },
        )

    messages = [
        {
            "role": "system",
            "content": build_matcher_system_prompt(),
        },
        {
            "role": "user",
            "content": build_matcher_user_prompt(
                primary_form_type=normalized_form_type,
                questionnaire=questionnaire,
                fact_extraction_result=fact_extraction_result,
                rule_result=rule_result,
                max_matches=max_matches,
            ),
        },
    ]

    raw_response = call_openai_json(messages)
    rule_strategy_names = extract_rule_strategy_names(rule_result)

    matches, rejected = normalize_ai_matches(
        raw_response,
        primary_form_type=normalized_form_type,
        allowed_strategy_names=allowed_strategy_names,
        rule_strategy_names=rule_strategy_names,
    )

    return StrategyAIMatchResult(
        primary_form_type=normalized_form_type,
        ai_matches=matches[:max_matches],
        rejected_matches=rejected,
        approved_strategy_names_used=sorted(allowed_strategy_names),
        guardrails={
            "ai_strategy_matching_enabled": True,
            "approved_strategy_list_enforced": True,
            "form_policy_enforced": True,
            "no_invented_strategy_names": True,
            "max_matches": max_matches,
        },
    )


def main() -> None:
    import argparse

    from fact_extractor import extract_facts_from_pdf_file
    from questionnaire import get_default_questionnaire, merge_fact_extraction_result_into_questionnaire
    from strategy_rules import run_strategy_rules

    parser = argparse.ArgumentParser(description="Run AI strategy matcher from a tax PDF.")
    parser.add_argument("pdf", help="Path to PDF file")
    parser.add_argument("--max-matches", type=int, default=8, help="Maximum AI strategy matches")
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
        max_matches=args.max_matches,
    )

    print(json.dumps(ai_result.to_dict(), indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
