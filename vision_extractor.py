from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pdf_extractor import ExtractedPdfDocument, extract_pdf


class VisionExtractorError(Exception):
    """Raised when vision extraction fails."""


OPENAI_VISION_URL = os.getenv("OPENROUTER_API_URL", "https://api.openai.com/v1/chat/completions")
DEFAULT_VISION_MODEL = os.getenv("OPENROUTER_VISION_MODEL") or os.getenv("OPENAI_VISION_MODEL") or "gpt-4o-mini"


@dataclass(frozen=True)
class VisionField:
    field_name: str
    value: Any
    source_line: str | None
    confidence: float
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "value": self.value,
            "source_line": self.source_line,
            "confidence": round(self.confidence, 4),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class VisionExtractionResult:
    form_type: str
    page_number: int
    fields: dict[str, VisionField] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "form_type": self.form_type,
            "page_number": self.page_number,
            "fields": {key: field.to_dict() for key, field in self.fields.items()},
            "warnings": list(self.warnings),
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


def get_api_key() -> str:
    load_local_env_file()

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip() or os.getenv("OPENAI_API_KEY", "").strip()

    if not api_key:
        raise VisionExtractorError("Missing OPENAI_API_KEY or OPENROUTER_API_KEY in .env.")

    return api_key


def image_to_data_url(image_path: str | Path) -> str:
    path = Path(image_path)

    if not path.exists():
        raise VisionExtractorError(f"Image file not found: {path}")

    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def clean_json_text(text: str) -> str:
    cleaned = text.strip()

    if cleaned.startswith("```json"):
        cleaned = cleaned.removeprefix("```json").strip()

    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```").strip()

    if cleaned.endswith("```"):
        cleaned = cleaned.removesuffix("```").strip()

    return cleaned


def call_vision_json(
    *,
    image_path: str | Path,
    prompt: str,
) -> dict[str, Any]:
    api_key = get_api_key()

    payload = {
        "model": DEFAULT_VISION_MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a CPA-grade tax form vision extraction engine. "
                    "Read the form image visually. Extract only visible values. "
                    "Never guess. Return only valid JSON."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt,
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_to_data_url(image_path),
                        },
                    },
                ],
            },
        ],
    }

    request = urllib.request.Request(
        OPENAI_VISION_URL,
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
        raise VisionExtractorError(f"Vision API error {exc.code}: {error_body}") from exc

    except urllib.error.URLError as exc:
        raise VisionExtractorError(f"Unable to connect to vision API: {exc}") from exc

    try:
        data = json.loads(response_body)
        content = data["choices"][0]["message"]["content"]
        return json.loads(clean_json_text(content))

    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise VisionExtractorError("Vision model returned invalid JSON.") from exc


def normalize_number(value: Any) -> float | None:
    if value is None or value == "":
        return None

    if isinstance(value, bool):
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

    text = str(value).strip()
    return text or None


def build_1040_page1_prompt() -> str:
    return """
Extract visible values from Form 1040 page 1.

Return ONLY this JSON shape:
{
  "form": "1040",
  "page": 1,
  "fields": {
    "filing_status": {"value": null, "sourceLine": "Filing Status", "confidence": 0.0, "notes": ""},
    "taxpayer_name": {"value": null, "sourceLine": "Taxpayer name", "confidence": 0.0, "notes": ""},
    "spouse_name": {"value": null, "sourceLine": "Spouse name", "confidence": 0.0, "notes": ""},
    "wages": {"value": null, "sourceLine": "Line 1a", "confidence": 0.0, "notes": ""},
    "taxable_interest": {"value": null, "sourceLine": "Line 2b", "confidence": 0.0, "notes": ""},
    "ordinary_dividends": {"value": null, "sourceLine": "Line 3b", "confidence": 0.0, "notes": ""},
    "capital_gain_or_loss": {"value": null, "sourceLine": "Line 7", "confidence": 0.0, "notes": ""},
    "additional_income_schedule_1": {"value": null, "sourceLine": "Line 8", "confidence": 0.0, "notes": ""},
    "total_income": {"value": null, "sourceLine": "Line 9", "confidence": 0.0, "notes": ""},
    "adjusted_gross_income": {"value": null, "sourceLine": "Line 11", "confidence": 0.0, "notes": ""},
    "standard_or_itemized_deduction": {"value": null, "sourceLine": "Line 12", "confidence": 0.0, "notes": ""},
    "qbi_deduction": {"value": null, "sourceLine": "Line 13", "confidence": 0.0, "notes": ""},
    "total_deductions_line_14": {"value": null, "sourceLine": "Line 14", "confidence": 0.0, "notes": ""},
    "taxable_income": {"value": null, "sourceLine": "Line 15", "confidence": 0.0, "notes": ""}
  }
}

Rules:
- Read values visually from the image.
- Do not calculate.
- If blank or unclear, return null.
- Filing status should be the checked box only.
""".strip()


def build_1040_page2_prompt() -> str:
    return """
Extract visible values from Form 1040 page 2.

Return ONLY this JSON shape:
{
  "form": "1040",
  "page": 2,
  "fields": {
    "tax": {"value": null, "sourceLine": "Line 16", "confidence": 0.0, "notes": ""},
    "child_tax_credit_or_other_dependents": {"value": null, "sourceLine": "Line 19", "confidence": 0.0, "notes": ""},
    "total_tax": {"value": null, "sourceLine": "Line 24", "confidence": 0.0, "notes": ""},
    "federal_income_tax_withheld": {"value": null, "sourceLine": "Line 25d", "confidence": 0.0, "notes": ""},
    "estimated_tax_payments": {"value": null, "sourceLine": "Line 26", "confidence": 0.0, "notes": ""},
    "total_payments": {"value": null, "sourceLine": "Line 33", "confidence": 0.0, "notes": ""},
    "refund": {"value": null, "sourceLine": "Line 34", "confidence": 0.0, "notes": ""},
    "amount_owed": {"value": null, "sourceLine": "Line 37", "confidence": 0.0, "notes": ""},
    "estimated_tax_penalty": {"value": null, "sourceLine": "Line 38", "confidence": 0.0, "notes": ""}
  }
}

Rules:
- Read values visually from the image.
- Do not calculate.
- If blank or unclear, return null.
""".strip()


def normalize_vision_fields(raw_response: dict[str, Any], *, page_number: int) -> VisionExtractionResult:
    raw_fields = raw_response.get("fields", {})

    if not isinstance(raw_fields, dict):
        return VisionExtractionResult(
            form_type="1040",
            page_number=page_number,
            fields={},
            warnings=["Vision response did not contain a valid fields object."],
        )

    fields: dict[str, VisionField] = {}

    string_fields = {"filing_status", "taxpayer_name", "spouse_name"}

    for field_name, payload in raw_fields.items():
        if not isinstance(payload, dict):
            continue

        raw_value = payload.get("value")

        value = normalize_string(raw_value) if field_name in string_fields else normalize_number(raw_value)

        if value is None:
            continue

        confidence = float(payload.get("confidence") or 0)

        fields[field_name] = VisionField(
            field_name=field_name,
            value=value,
            source_line=normalize_string(payload.get("sourceLine")),
            confidence=max(0.0, min(confidence, 1.0)),
            notes=normalize_string(payload.get("notes")) or "",
        )

    return VisionExtractionResult(
        form_type="1040",
        page_number=page_number,
        fields=fields,
        warnings=[],
    )


def vision_extract_1040_from_pdf(
    pdf_path: str | Path,
    *,
    page1_number: int = 1,
    page2_number: int = 2,
) -> dict[str, Any]:
    document = extract_pdf(
        pdf_path,
        render_images=True,
        include_image_base64=False,
    )

    if document.page_count < max(page1_number, page2_number):
        raise VisionExtractorError(
            f"PDF has {document.page_count} pages, cannot extract requested pages {page1_number} and {page2_number}."
        )

    page1 = document.pages[page1_number - 1]
    page2 = document.pages[page2_number - 1]

    if not page1.image_path or not page2.image_path:
        raise VisionExtractorError("PDF page images were not rendered.")

    page1_raw = call_vision_json(
        image_path=page1.image_path,
        prompt=build_1040_page1_prompt(),
    )
    page2_raw = call_vision_json(
        image_path=page2.image_path,
        prompt=build_1040_page2_prompt(),
    )

    page1_result = normalize_vision_fields(page1_raw, page_number=page1_number)
    page2_result = normalize_vision_fields(page2_raw, page_number=page2_number)

    merged_fields: dict[str, Any] = {}

    for result in (page1_result, page2_result):
        for field_name, field_value in result.fields.items():
            merged_fields[field_name] = field_value.to_dict()

    return {
        "form_type": "1040",
        "page1_number": page1_number,
        "page2_number": page2_number,
        "fields": merged_fields,
        "page_results": [page1_result.to_dict(), page2_result.to_dict()],
        "warnings": [
            *page1_result.warnings,
            *page2_result.warnings,
        ],
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Vision extract Form 1040 fields from a PDF.")
    parser.add_argument("pdf", help="Path to PDF file")
    parser.add_argument("--page1", type=int, default=1, help="Form 1040 page 1 number")
    parser.add_argument("--page2", type=int, default=2, help="Form 1040 page 2 number")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args()

    try:
        result = vision_extract_1040_from_pdf(
            args.pdf,
            page1_number=args.page1,
            page2_number=args.page2,
        )
        print(json.dumps(result, indent=2 if args.pretty else None))

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
