from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fact_extractor import extract_facts_from_pdf_file
from vision_extractor import vision_extract_1040_from_pdf


class CrossCheckError(Exception):
    """Raised when text/vision cross-checking fails."""


@dataclass(frozen=True)
class SourceValue:
    value: Any
    confidence: float
    source: str
    source_line: str | None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "confidence": round(self.confidence, 4),
            "source": self.source,
            "source_line": self.source_line,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class CrossCheckedField:
    field_name: str
    final_value: Any
    confidence: float
    status: str
    requires_review: bool
    text_value: SourceValue | None = None
    vision_value: SourceValue | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "final_value": self.final_value,
            "confidence": round(self.confidence, 4),
            "status": self.status,
            "requires_review": self.requires_review,
            "text_value": self.text_value.to_dict() if self.text_value else None,
            "vision_value": self.vision_value.to_dict() if self.vision_value else None,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class CrossCheckResult:
    primary_form_type: str
    fields: dict[str, CrossCheckedField]
    warnings: list[str]
    text_extraction: dict[str, Any]
    vision_extraction: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_form_type": self.primary_form_type,
            "fields": {key: value.to_dict() for key, value in self.fields.items()},
            "warnings": list(self.warnings),
            "text_extraction": self.text_extraction,
            "vision_extraction": self.vision_extraction,
        }


def safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, int | float):
        return float(value)

    if isinstance(value, str):
        cleaned = value.replace("$", "").replace(",", "").strip()

        if not cleaned:
            return None

        is_negative = cleaned.startswith("(") and cleaned.endswith(")")
        cleaned = cleaned.strip("()")

        try:
            parsed = float(cleaned)
        except ValueError:
            return None

        return -parsed if is_negative else parsed

    return None


def normalize_string(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip().upper()

    if not text:
        return None

    text = text.replace("_", " ")
    text = text.replace("-", " ")
    text = " ".join(text.split())

    # Normalize common filing status variants.
    filing_status_aliases = {
        "MARRIED FILING JOINTLY": "MARRIED FILING JOINTLY",
        "MARRIED FILING SEPARATELY": "MARRIED FILING SEPARATELY",
        "HEAD OF HOUSEHOLD": "HEAD OF HOUSEHOLD",
        "SINGLE": "SINGLE",
        "QUALIFYING SURVIVING SPOUSE": "QUALIFYING SURVIVING SPOUSE",
    }

    if text in filing_status_aliases:
        return filing_status_aliases[text]

    # Remove common OCR title noise from names.
    for noise in (" MR ", " MRS ", " MS ", " DR "):
        text = f" {text} ".replace(noise, " ").strip()

    return " ".join(text.split())




def values_match(left: Any, right: Any) -> bool:
    left_number = safe_float(left)
    right_number = safe_float(right)

    if left_number is not None and right_number is not None:
        return abs(left_number - right_number) <= 1

    left_string = normalize_string(left)
    right_string = normalize_string(right)

    if left_string is not None and right_string is not None:
        if left_string == right_string:
            return True

        # Allow very small OCR typo differences for names only.
        left_tokens = set(left_string.split())
        right_tokens = set(right_string.split())

        if left_tokens and right_tokens:
            common_tokens = left_tokens & right_tokens
            shorter_len = min(len(left_tokens), len(right_tokens))

            if shorter_len > 0 and len(common_tokens) / shorter_len >= 0.75:
                return True

    return False




def extract_text_fields(fact_result: dict[str, Any]) -> dict[str, SourceValue]:
    cards = fact_result.get("extraction_cards", [])

    if not isinstance(cards, list) or not cards:
        return {}

    first_card = cards[0]

    if not isinstance(first_card, dict):
        return {}

    raw_fields = first_card.get("fields", {})

    if not isinstance(raw_fields, dict):
        return {}

    fields: dict[str, SourceValue] = {}

    for field_name, payload in raw_fields.items():
        if not isinstance(payload, dict):
            continue

        fields[field_name] = SourceValue(
            value=payload.get("value"),
            confidence=float(payload.get("confidence") or 0),
            source="TEXT_EXTRACTION",
            source_line=payload.get("source_line"),
            notes=str(payload.get("notes") or ""),
        )

    return fields


def extract_vision_fields(vision_result: dict[str, Any] | None) -> dict[str, SourceValue]:
    if not isinstance(vision_result, dict):
        return {}

    raw_fields = vision_result.get("fields", {})

    if not isinstance(raw_fields, dict):
        return {}

    fields: dict[str, SourceValue] = {}

    for field_name, payload in raw_fields.items():
        if not isinstance(payload, dict):
            continue

        fields[field_name] = SourceValue(
            value=payload.get("value"),
            confidence=float(payload.get("confidence") or 0),
            source="VISION_EXTRACTION",
            source_line=payload.get("source_line"),
            notes=str(payload.get("notes") or ""),
        )

    return fields


def choose_cross_checked_value(
    field_name: str,
    text_value: SourceValue | None,
    vision_value: SourceValue | None,
) -> CrossCheckedField:
    notes: list[str] = []

    if text_value and vision_value:
        if values_match(text_value.value, vision_value.value):
            final_confidence = min(max(text_value.confidence, vision_value.confidence), 0.98)

            return CrossCheckedField(
                field_name=field_name,
                final_value=text_value.value,
                confidence=final_confidence,
                status="MATCHED_TEXT_AND_VISION",
                requires_review=final_confidence < 0.90,
                text_value=text_value,
                vision_value=vision_value,
                notes=["Text and vision extraction agree."],
            )

        notes.append("Text and vision extraction disagree; human review required.")

        return CrossCheckedField(
            field_name=field_name,
            final_value=None,
            confidence=0.0,
            status="CONFLICT_REVIEW_REQUIRED",
            requires_review=True,
            text_value=text_value,
            vision_value=vision_value,
            notes=notes,
        )

    if text_value and not vision_value:
        notes.append("Only text extraction found this value.")

        return CrossCheckedField(
            field_name=field_name,
            final_value=text_value.value,
            confidence=min(text_value.confidence, 0.85),
            status="TEXT_ONLY_REVIEW_REQUIRED",
            requires_review=True,
            text_value=text_value,
            vision_value=None,
            notes=notes,
        )

    if vision_value and not text_value:
        notes.append("Only vision extraction found this value.")

        return CrossCheckedField(
            field_name=field_name,
            final_value=vision_value.value,
            confidence=min(vision_value.confidence, 0.85),
            status="VISION_ONLY_REVIEW_REQUIRED",
            requires_review=True,
            text_value=None,
            vision_value=vision_value,
            notes=notes,
        )

    return CrossCheckedField(
        field_name=field_name,
        final_value=None,
        confidence=0.0,
        status="MISSING",
        requires_review=True,
        text_value=None,
        vision_value=None,
        notes=["Field missing from both text and vision extraction."],
    )


def run_cross_check(
    pdf_path: str | Path,
    *,
    page1_number: int = 1,
    page2_number: int = 2,
) -> CrossCheckResult:
    path = Path(pdf_path)

    fact_result = extract_facts_from_pdf_file(path).to_dict()
    primary_form_type = str(fact_result.get("primary_form_type") or "UNKNOWN")

    vision_result: dict[str, Any] | None = None
    warnings: list[str] = []

    if primary_form_type == "1040":
        try:
            vision_result = vision_extract_1040_from_pdf(
                path,
                page1_number=page1_number,
                page2_number=page2_number,
            )
        except Exception as exc:
            warnings.append(f"Vision extraction failed: {exc}")
            vision_result = None
    else:
        warnings.append(f"Vision extraction not implemented yet for form type: {primary_form_type}")

    text_fields = extract_text_fields(fact_result)
    vision_fields = extract_vision_fields(vision_result)

    all_field_names = sorted(set(text_fields) | set(vision_fields))

    cross_checked_fields = {
        field_name: choose_cross_checked_value(
            field_name,
            text_fields.get(field_name),
            vision_fields.get(field_name),
        )
        for field_name in all_field_names
    }

    conflicts = [
        field_name
        for field_name, field in cross_checked_fields.items()
        if field.status == "CONFLICT_REVIEW_REQUIRED"
    ]

    if conflicts:
        warnings.append(
            "Conflicting text/vision fields require human review: "
            + ", ".join(conflicts)
        )

    return CrossCheckResult(
        primary_form_type=primary_form_type,
        fields=cross_checked_fields,
        warnings=warnings,
        text_extraction=fact_result,
        vision_extraction=vision_result,
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Cross-check text extraction against vision extraction.")
    parser.add_argument("pdf", help="Path to PDF file")
    parser.add_argument("--page1", type=int, default=1, help="Form 1040 page 1 number")
    parser.add_argument("--page2", type=int, default=2, help="Form 1040 page 2 number")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args()

    try:
        result = run_cross_check(
            args.pdf,
            page1_number=args.page1,
            page2_number=args.page2,
        )
        print(json.dumps(result.to_dict(), indent=2 if args.pretty else None))

    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "error_type": exc.__class__.__name__,
                },
                indent=2,
            )
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
