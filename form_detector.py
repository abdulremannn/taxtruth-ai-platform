from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


MAX_DEFAULT_FILE_BYTES = 25 * 1024 * 1024

SUPPORTED_TEXT_EXTENSIONS = {".txt", ".text", ".csv", ".md", ".html", ".htm"}
SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
SUPPORTED_PDF_EXTENSIONS = {".pdf"}
SUPPORTED_EXTENSIONS = SUPPORTED_TEXT_EXTENSIONS | SUPPORTED_IMAGE_EXTENSIONS | SUPPORTED_PDF_EXTENSIONS


class FormDetectorError(Exception):
    """Base exception for tax form detection errors."""


class UnsupportedFileTypeError(FormDetectorError):
    """Raised when the uploaded file type is not supported."""


class FileTooLargeError(FormDetectorError):
    """Raised when the uploaded file exceeds the configured maximum size."""


class TextExtractionError(FormDetectorError):
    """Raised when text cannot be extracted from the uploaded file."""


@dataclass(frozen=True)
class RegexRule:
    label: str
    pattern: str
    weight: float


@dataclass(frozen=True)
class FormSignature:
    form_type: str
    display_name: str
    category: str
    strong_score: float
    rules: tuple[RegexRule, ...]


@dataclass(frozen=True)
class DetectionCandidate:
    form_type: str
    display_name: str
    category: str
    confidence: float
    score: float
    matched_rules: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "form_type": self.form_type,
            "display_name": self.display_name,
            "category": self.category,
            "confidence": round(self.confidence, 4),
            "score": round(self.score, 2),
            "matched_rules": list(self.matched_rules),
        }


@dataclass(frozen=True)
class FormDetectionResult:
    form_type: str
    display_name: str
    category: str
    confidence: float
    tax_year: int | None
    requires_review: bool
    extracted_text_length: int
    extraction_method: str
    candidates: tuple[DetectionCandidate, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "form_type": self.form_type,
            "display_name": self.display_name,
            "category": self.category,
            "confidence": round(self.confidence, 4),
            "tax_year": self.tax_year,
            "requires_review": self.requires_review,
            "extracted_text_length": self.extracted_text_length,
            "extraction_method": self.extraction_method,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }

    FormSignature(
        form_type="1065",
        display_name="Form 1065",
        category="partnership_tax_return",
        strong_score=100,
        rules=(
            RegexRule("form_1065", r"\bFORM\s+1065\b", 50),
            RegexRule("return_of_partnership_income", r"\bU\.?S\.?\s+RETURN\s+OF\s+PARTNERSHIP\s+INCOME\b", 55),
            RegexRule("partnership_income", r"\bPARTNERSHIP\s+INCOME\b", 20),
            RegexRule("ordinary_business_income_1065", r"\bORDINARY\s+BUSINESS\s+INCOME\s+\(LOSS\)\b", 14),
            RegexRule("guaranteed_payments", r"\bGUARANTEED\s+PAYMENTS\b", 18),
            RegexRule("partners_distributive_share", r"\bPARTNERS(?:'|’)?\s+DISTRIBUTIVE\s+SHARE\b", 18),
            RegexRule("schedule_k_1065", r"\bSCHEDULE\s+K\b.{0,160}\bPARTNERS\b", 20),
            RegexRule("analysis_of_net_income", r"\bANALYSIS\s+OF\s+NET\s+INCOME\b", 12),
        ),
    ),

    FormSignature(
        form_type="1065",
        display_name="Form 1065",
        category="partnership_tax_return",
        strong_score=100,
        rules=(
            RegexRule("form_1065", r"\bFORM\s+1065\b", 50),
            RegexRule("standalone_1065", r"\b1065\b", 35),
            RegexRule("return_of_partnership_income", r"\bU\.?S\.?\s+RETURN\s+OF\s+PARTNERSHIP\s+INCOME\b", 60),
            RegexRule("irs_form_1065_url", r"\bIRS\.GOV/FOrm1065\b|\bIRS\.GOV/FORM1065\b", 20),
            RegexRule("partner_llc_member_signature", r"\bSIGNATURE\s+OF\s+PARTNER\s+OR\s+LIMITED\s+LIABILITY\s+COMPANY\s+MEMBER\b", 25),
            RegexRule("number_of_schedules_k1", r"\bNUMBER\s+OF\s+SCHEDULES\s+K[-\s]?1\b", 20),
            RegexRule("partnership_income", r"\bPARTNERSHIP\s+INCOME\b", 18),
            RegexRule("ordinary_business_income_1065", r"\bORDINARY\s+BUSINESS\s+INCOME\s+\(LOSS\)\b", 14),
            RegexRule("guaranteed_payments", r"\bGUARANTEED\s+PAYMENTS\b", 18),
            RegexRule("partners_distributive_share", r"\bPARTNERS(?:'|’)?\s+DISTRIBUTIVE\s+SHARE\b", 18),
            RegexRule("analysis_of_net_income", r"\bANALYSIS\s+OF\s+NET\s+INCOME\b", 12),
        ),
    ),


FORM_SIGNATURES: tuple[FormSignature, ...] = (
    FormSignature(
        form_type="1120S",
        display_name="Form 1120-S",
        category="business_tax_return",
        strong_score=100,
        rules=(
            RegexRule("form_1120s", r"\bFORM\s+1120[-\s]?S\b", 50),
            RegexRule("standalone_1120s", r"\b1120[-\s]?S\b", 35),
            RegexRule(
                "s_corporation_return",
                r"\bU\.?S\.?\s+INCOME\s+TAX\s+RETURN\s+FOR\s+AN\s+S\s+CORPORATION\b",
                55,
            ),
            RegexRule("s_corporation", r"\bS\s+CORPORATION\b", 20),
            RegexRule("form_2553", r"\bFORM\s+2553\b", 18),
            RegexRule("s_election", r"\bS\s+ELECTION\b", 15),
            RegexRule("number_of_shareholders", r"\bNUMBER\s+OF\s+SHAREHOLDERS\b", 12),
            RegexRule("ordinary_business_income_1120s", r"\bORDINARY\s+BUSINESS\s+INCOME\s+\(LOSS\)", 14),
            RegexRule("schedule_k_1120s", r"\bSCHEDULE\s+K\b.{0,160}\bSHAREHOLDERS\b", 20),
            RegexRule("shareholders_pro_rata", r"\bSHAREHOLDERS(?:'|’)?\s+PRO\s+RATA\s+SHARE\s+ITEMS\b", 25),
        ),
    ),
    FormSignature(
        form_type="W2",
        display_name="Form W-2",
        category="income",
        strong_score=95,
        rules=(
            RegexRule("form_w2", r"\bFORM\s+W[-\s]?2\b", 45),
            RegexRule("wage_tax_statement", r"\bWAGE\s+AND\s+TAX\s+STATEMENT\b", 35),
            RegexRule("wages_tips_compensation", r"\bWAGES[,]?\s+TIPS[,]?\s+OTHER\s+COMPENSATION\b", 20),
            RegexRule("employer_ein", r"\bEMPLOYER(?:'S)?\s+IDENTIFICATION\s+NUMBER\b", 12),
            RegexRule("federal_income_tax_withheld", r"\bFEDERAL\s+INCOME\s+TAX\s+WITHHELD\b", 12),
            RegexRule("social_security_wages", r"\bSOCIAL\s+SECURITY\s+WAGES\b", 10),
            RegexRule("medicare_wages", r"\bMEDICARE\s+WAGES(?:\s+AND\s+TIPS)?\b", 10),
        ),
    ),
    FormSignature(
        form_type="1099_NEC",
        display_name="Form 1099-NEC",
        category="income",
        strong_score=90,
        rules=(
            RegexRule("form_1099_nec", r"\bFORM\s+1099[-\s]?NEC\b", 50),
            RegexRule("nonemployee_compensation", r"\bNONEMPLOYEE\s+COMPENSATION\b", 35),
            RegexRule("payer_tin", r"\bPAYER(?:'S)?\s+TIN\b", 10),
            RegexRule("recipient_tin", r"\bRECIPIENT(?:'S)?\s+TIN\b", 10),
            RegexRule("account_number", r"\bACCOUNT\s+NUMBER\b", 6),
        ),
    ),
    FormSignature(
        form_type="1099_MISC",
        display_name="Form 1099-MISC",
        category="income",
        strong_score=90,
        rules=(
            RegexRule("form_1099_misc", r"\bFORM\s+1099[-\s]?MISC\b", 50),
            RegexRule("miscellaneous_information", r"\bMISCELLANEOUS\s+(?:INCOME|INFORMATION)\b", 28),
            RegexRule("rents", r"\bRENTS\b", 9),
            RegexRule("royalties", r"\bROYALTIES\b", 9),
            RegexRule("other_income", r"\bOTHER\s+INCOME\b", 9),
            RegexRule("medical_health_payments", r"\bMEDICAL\s+AND\s+HEALTH\s+CARE\s+PAYMENTS\b", 12),
        ),
    ),
    FormSignature(
        form_type="1099_INT",
        display_name="Form 1099-INT",
        category="income",
        strong_score=90,
        rules=(
            RegexRule("form_1099_int", r"\bFORM\s+1099[-\s]?INT\b", 50),
            RegexRule("interest_income", r"\bINTEREST\s+INCOME\b", 35),
            RegexRule("early_withdrawal_penalty", r"\bEARLY\s+WITHDRAWAL\s+PENALTY\b", 12),
            RegexRule("federal_tax_withheld", r"\bFEDERAL\s+INCOME\s+TAX\s+WITHHELD\b", 8),
            RegexRule("savings_bond", r"\bSAVINGS\s+BOND\b", 8),
        ),
    ),
    FormSignature(
        form_type="1099_DIV",
        display_name="Form 1099-DIV",
        category="income",
        strong_score=90,
        rules=(
            RegexRule("form_1099_div", r"\bFORM\s+1099[-\s]?DIV\b", 50),
            RegexRule("dividends_distributions", r"\bDIVIDENDS\s+AND\s+DISTRIBUTIONS\b", 35),
            RegexRule("ordinary_dividends", r"\bTOTAL\s+ORDINARY\s+DIVIDENDS\b", 14),
            RegexRule("qualified_dividends", r"\bQUALIFIED\s+DIVIDENDS\b", 14),
            RegexRule("capital_gain_distributions", r"\bCAPITAL\s+GAIN\s+DISTRIBUTIONS\b", 12),
        ),
    ),
    FormSignature(
        form_type="1099_B",
        display_name="Form 1099-B",
        category="income",
        strong_score=95,
        rules=(
            RegexRule("form_1099_b", r"\bFORM\s+1099[-\s]?B\b", 50),
            RegexRule("broker_barter", r"\bPROCEEDS\s+FROM\s+BROKER\s+AND\s+BARTER\s+EXCHANGE\s+TRANSACTIONS\b", 35),
            RegexRule("date_acquired", r"\bDATE\s+ACQUIRED\b", 12),
            RegexRule("date_sold", r"\bDATE\s+SOLD\s+OR\s+DISPOSED\b", 12),
            RegexRule("cost_basis", r"\bCOST\s+OR\s+OTHER\s+BASIS\b", 12),
        ),
    ),
    FormSignature(
        form_type="1099_R",
        display_name="Form 1099-R",
        category="income",
        strong_score=95,
        rules=(
            RegexRule("form_1099_r", r"\bFORM\s+1099[-\s]?R\b", 50),
            RegexRule("pensions_annuities", r"\bDISTRIBUTIONS\s+FROM\s+PENSIONS[,]?\s+ANNUITIES[,]?\s+RETIREMENT\b", 34),
            RegexRule("gross_distribution", r"\bGROSS\s+DISTRIBUTION\b", 16),
            RegexRule("taxable_amount", r"\bTAXABLE\s+AMOUNT\b", 14),
            RegexRule("distribution_code", r"\bDISTRIBUTION\s+CODE\b", 12),
        ),
    ),
    FormSignature(
        form_type="1099_K",
        display_name="Form 1099-K",
        category="income",
        strong_score=90,
        rules=(
            RegexRule("form_1099_k", r"\bFORM\s+1099[-\s]?K\b", 50),
            RegexRule("payment_card", r"\bPAYMENT\s+CARD\s+AND\s+THIRD\s+PARTY\s+NETWORK\s+TRANSACTIONS\b", 35),
            RegexRule("gross_amount", r"\bGROSS\s+AMOUNT\s+OF\s+PAYMENT\b", 16),
            RegexRule("merchant_category", r"\bMERCHANT\s+CATEGORY\s+CODE\b", 10),
            RegexRule("third_party_network", r"\bTHIRD\s+PARTY\s+NETWORK\b", 10),
        ),
    ),
    FormSignature(
        form_type="SSA_1099",
        display_name="Form SSA-1099",
        category="income",
        strong_score=90,
        rules=(
            RegexRule("form_ssa_1099", r"\bFORM\s+SSA[-\s]?1099\b", 50),
            RegexRule("social_security_benefit_statement", r"\bSOCIAL\s+SECURITY\s+BENEFIT\s+STATEMENT\b", 40),
            RegexRule("benefits_paid", r"\bBENEFITS\s+PAID\b", 14),
            RegexRule("net_benefits", r"\bNET\s+BENEFITS\b", 14),
            RegexRule("ssa", r"\bSOCIAL\s+SECURITY\s+ADMINISTRATION\b", 10),
        ),
    ),
    FormSignature(
        form_type="1098",
        display_name="Form 1098 Mortgage Interest Statement",
        category="deduction",
        strong_score=90,
        rules=(
            RegexRule("form_1098", r"\bFORM\s+1098\b(?![-\s]?(T|E)\b)", 45),
            RegexRule("mortgage_interest_statement", r"\bMORTGAGE\s+INTEREST\s+STATEMENT\b", 40),
            RegexRule("mortgage_interest_received", r"\bMORTGAGE\s+INTEREST\s+RECEIVED\b", 18),
            RegexRule("outstanding_mortgage_principal", r"\bOUTSTANDING\s+MORTGAGE\s+PRINCIPAL\b", 14),
            RegexRule("property_tax", r"\bPROPERTY\s+TAX(?:ES)?\b", 8),
        ),
    ),
    FormSignature(
        form_type="1098_T",
        display_name="Form 1098-T",
        category="education",
        strong_score=90,
        rules=(
            RegexRule("form_1098_t", r"\bFORM\s+1098[-\s]?T\b", 50),
            RegexRule("tuition_statement", r"\bTUITION\s+STATEMENT\b", 38),
            RegexRule("qualified_tuition", r"\bQUALIFIED\s+TUITION\s+AND\s+RELATED\s+EXPENSES\b", 18),
            RegexRule("scholarships_grants", r"\bSCHOLARSHIPS\s+OR\s+GRANTS\b", 14),
            RegexRule("student_tin", r"\bSTUDENT(?:'S)?\s+TIN\b", 10),
        ),
    ),
    FormSignature(
        form_type="1098_E",
        display_name="Form 1098-E",
        category="education",
        strong_score=90,
        rules=(
            RegexRule("form_1098_e", r"\bFORM\s+1098[-\s]?E\b", 50),
            RegexRule("student_loan_interest_statement", r"\bSTUDENT\s+LOAN\s+INTEREST\s+STATEMENT\b", 38),
            RegexRule("student_loan_interest_received", r"\bSTUDENT\s+LOAN\s+INTEREST\s+RECEIVED\b", 20),
            RegexRule("borrower_tin", r"\bBORROWER(?:'S)?\s+TIN\b", 10),
        ),
    ),
    FormSignature(
        form_type="1040",
        display_name="Form 1040",
        category="tax_return",
        strong_score=100,
        rules=(
            RegexRule("form_1040", r"\bFORM\s+1040\b", 45),
            RegexRule("individual_income_tax_return", r"\bU\.?S\.?\s+INDIVIDUAL\s+INCOME\s+TAX\s+RETURN\b", 45),
            RegexRule("filing_status", r"\bFILING\s+STATUS\b", 14),
            RegexRule("standard_deduction", r"\bSTANDARD\s+DEDUCTION\b", 12),
            RegexRule("adjusted_gross_income", r"\bADJUSTED\s+GROSS\s+INCOME\b", 14),
            RegexRule("taxable_income", r"\bTAXABLE\s+INCOME\b", 10),
        ),
    ),
    FormSignature(
        form_type="SCHEDULE_C",
        display_name="Schedule C",
        category="tax_return_schedule",
        strong_score=95,
        rules=(
            RegexRule("schedule_c", r"\bSCHEDULE\s+C\b", 45),
            RegexRule("profit_loss_business", r"\bPROFIT\s+OR\s+LOSS\s+FROM\s+BUSINESS\b", 40),
            RegexRule("sole_proprietorship", r"\bSOLE\s+PROPRIETORSHIP\b", 18),
            RegexRule("gross_receipts", r"\bGROSS\s+RECEIPTS\s+OR\s+SALES\b", 14),
            RegexRule("business_expenses", r"\bEXPENSES\b.{0,80}\bBUSINESS\b", 8),
        ),
    ),
    FormSignature(
        form_type="SCHEDULE_D",
        display_name="Schedule D",
        category="tax_return_schedule",
        strong_score=95,
        rules=(
            RegexRule("schedule_d", r"\bSCHEDULE\s+D\b", 45),
            RegexRule("capital_gains_losses", r"\bCAPITAL\s+GAINS\s+AND\s+LOSSES\b", 40),
            RegexRule("short_term", r"\bSHORT[-\s]?TERM\s+CAPITAL\s+GAINS?\b", 14),
            RegexRule("long_term", r"\bLONG[-\s]?TERM\s+CAPITAL\s+GAINS?\b", 14),
            RegexRule("form_8949", r"\bFORM\s+8949\b", 12),
        ),
    ),
    FormSignature(
        form_type="SCHEDULE_E",
        display_name="Schedule E",
        category="tax_return_schedule",
        strong_score=95,
        rules=(
            RegexRule("schedule_e", r"\bSCHEDULE\s+E\b", 45),
            RegexRule("supplemental_income_loss", r"\bSUPPLEMENTAL\s+INCOME\s+AND\s+LOSS\b", 40),
            RegexRule("rental_real_estate", r"\bRENTAL\s+REAL\s+ESTATE\b", 16),
            RegexRule("royalties", r"\bROYALTIES\b", 10),
            RegexRule("partnerships", r"\bPARTNERSHIPS\b", 10),
        ),
    ),
    FormSignature(
        form_type="K1_1120S",
        display_name="Schedule K-1 Form 1120-S",
        category="income",
        strong_score=95,
        rules=(
            RegexRule("schedule_k1", r"\bSCHEDULE\s+K[-\s]?1\b", 35),
            RegexRule("form_1120s_k1", r"\bFORM\s+1120[-\s]?S\b", 30),
            RegexRule("shareholder_share", r"\bSHAREHOLDER(?:'S|S')?\s+SHARE\s+OF\s+INCOME\b", 28),
            RegexRule("ordinary_business_income", r"\bORDINARY\s+BUSINESS\s+INCOME\s+\(LOSS\)", 18),
            RegexRule("s_corporation", r"\bS\s+CORPORATION\b", 12),
            RegexRule("shareholder_basis", r"\bSHAREHOLDER\s+BASIS\b", 10),
        ),
    ),
    FormSignature(
        form_type="K1_1065",
        display_name="Schedule K-1 Form 1065",
        category="income",
        strong_score=95,
        rules=(
            RegexRule("schedule_k1", r"\bSCHEDULE\s+K[-\s]?1\b", 40),
            RegexRule("form_1065", r"\bFORM\s+1065\b", 30),
            RegexRule("partner_share", r"\bPARTNER(?:'S)?\s+SHARE\s+OF\s+INCOME\b", 28),
            RegexRule("ordinary_business_income", r"\bORDINARY\s+BUSINESS\s+INCOME\b", 14),
            RegexRule("partnership", r"\bPARTNERSHIP\b", 10),
        ),
    ),
)


PRIMARY_RETURN_PRIORITY: dict[str, int] = {
    "1120S": 100,
    "1065": 98,
    "1120": 97,
    "1040": 95,
    "K1_1120S": 80,
    "K1_1065": 75,
    "W2": 70,
    "1099_NEC": 70,
    "1099_MISC": 70,
    "1099_INT": 70,
    "1099_DIV": 70,
    "1099_B": 70,
    "1099_R": 70,
    "1099_K": 70,
    "SSA_1099": 70,
    "1098": 65,
    "1098_T": 65,
    "1098_E": 65,
    "SCHEDULE_C": 40,
    "SCHEDULE_D": 40,
    "SCHEDULE_E": 40,
}


def normalize_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[^\S\r\n]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_text_from_text_file(path: Path) -> str:
    encodings = ("utf-8", "utf-8-sig", "cp1252", "latin-1")

    for encoding in encodings:
        try:
            return path.read_text(encoding=encoding, errors="replace")
        except UnicodeDecodeError:
            continue
        except OSError as exc:
            raise TextExtractionError(f"Unable to read text file: {exc}") from exc

    raise TextExtractionError("Unable to decode text file.")


def extract_text_from_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise TextExtractionError("PDF support requires pypdf. Install it with: pip install pypdf") from exc

    try:
        reader = PdfReader(str(path))
        pages_text: list[str] = []

        for page in reader.pages:
            page_text = page.extract_text() or ""
            if page_text.strip():
                pages_text.append(page_text)

        return "\n\n".join(pages_text)

    except Exception as exc:
        raise TextExtractionError(f"Unable to extract text from PDF: {exc}") from exc


def extract_text_from_image(path: Path) -> str:
    try:
        from PIL import Image
        import pytesseract
    except ImportError as exc:
        raise TextExtractionError(
            "Image OCR requires Pillow and pytesseract. Install them with: pip install Pillow pytesseract"
        ) from exc

    try:
        with Image.open(path) as image:
            return pytesseract.image_to_string(image)

    except pytesseract.TesseractNotFoundError as exc:
        raise TextExtractionError(
            "Tesseract OCR is not installed or not on PATH. "
            "Install it from: https://github.com/UB-Mannheim/tesseract/wiki"
        ) from exc

    except Exception as exc:
        raise TextExtractionError(f"Unable to extract text from image: {exc}") from exc


def extract_text_from_file(path: str | Path) -> tuple[str, str]:
    file_path = Path(path)

    if not file_path.exists():
        raise FormDetectorError(f"File does not exist: {file_path}")

    if not file_path.is_file():
        raise FormDetectorError(f"Path is not a file: {file_path}")

    suffix = file_path.suffix.lower()

    if suffix not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{suffix or 'unknown'}'. "
            f"Supported extensions: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    file_size = file_path.stat().st_size
    if file_size > MAX_DEFAULT_FILE_BYTES:
        max_mb = MAX_DEFAULT_FILE_BYTES // (1024 * 1024)
        raise FileTooLargeError(f"File is too large. Maximum size is {max_mb} MB.")

    if suffix in SUPPORTED_TEXT_EXTENSIONS:
        return normalize_text(extract_text_from_text_file(file_path)), "text"

    if suffix in SUPPORTED_PDF_EXTENSIONS:
        return normalize_text(extract_text_from_pdf(file_path)), "pdf"

    if suffix in SUPPORTED_IMAGE_EXTENSIONS:
        return normalize_text(extract_text_from_image(file_path)), "image_ocr"

    raise UnsupportedFileTypeError(f"Unsupported file type: {suffix}")


def detect_tax_year(text: str) -> int | None:
    reasonable_years = range(2015, 2031)
    year_scores: dict[int, int] = {}

    patterns = (
        r"\bTAX\s+YEAR\s+(20\d{2})\b",
        r"\bFOR\s+CALENDAR\s+YEAR\s+(20\d{2})\b",
        r"\bFOR\s+CALENDAR\s+YEAR\s+(20\d{2})\s+OR\s+TAX\s+YEAR\b",
        r"\bYEAR\s+(20\d{2})\b",
        r"\b(20\d{2})\s+FORM\b",
        r"\bFORM\s+\w+[-\s]?\w*\s+(20\d{2})\b",
        r"\b(20\d{2})\b",
    )

    upper_text = text.upper()

    for pattern_index, pattern in enumerate(patterns):
        weight = len(patterns) - pattern_index

        for match in re.finditer(pattern, upper_text, flags=re.IGNORECASE):
            try:
                year = int(match.group(1))
            except (IndexError, ValueError):
                continue

            if year in reasonable_years:
                year_scores[year] = year_scores.get(year, 0) + weight

    if not year_scores:
        return None

    return max(year_scores.items(), key=lambda item: item[1])[0]


def score_signature(text: str, signature: FormSignature) -> DetectionCandidate | None:
    matched_labels: list[str] = []
    score = 0.0

    for rule in signature.rules:
        if re.search(rule.pattern, text, flags=re.IGNORECASE | re.DOTALL):
            score += rule.weight
            matched_labels.append(rule.label)

    if score <= 0:
        return None

    confidence = min(score / signature.strong_score, 1.0)

    return DetectionCandidate(
        form_type=signature.form_type,
        display_name=signature.display_name,
        category=signature.category,
        confidence=confidence,
        score=score,
        matched_rules=tuple(matched_labels),
    )

def detect_primary_form_from_header(text: str) -> str | None:
    """
    Detect primary tax return from the first-page/header area.

    This must override embedded K-1, 1120-S, 1065, Schedule D, 1099, or Form 4562 references.
    """
    header = text[:12_000].upper()
    compact_header = re.sub(r"[^A-Z0-9]+", "", header)

    # Form 1065 primary return
    if (
        "1065" in compact_header
        and "USRETURNOFPARTNERSHIPINCOME" in compact_header
    ):
        return "1065"

    if (
        "1065" in compact_header
        and "PARTNERSHIPINCOME" in compact_header
        and "SIGNATUREOFPARTNER" in compact_header
    ):
        return "1065"

    # Form 1120-S primary return
    if (
        ("1120S" in compact_header or "1120S2024" in compact_header)
        and "USINCOMETAXRETURNFORANSCORPORATION" in compact_header
    ):
        return "1120S"

    # Form 1040 primary return
    if (
        "1040" in compact_header
        and "USINDIVIDUALINCOMETAXRETURN" in compact_header
    ):
        return "1040"

    # Form 1120 primary return, but not 1120-S
    if (
        "1120" in compact_header
        and "1120S" not in compact_header
        and "USCORPORATIONINCOMETAXRETURN" in compact_header
    ):
        return "1120"

    return None

def build_forced_primary_candidate(form_type: str) -> DetectionCandidate:
    if form_type == "1065":
        return DetectionCandidate(
            form_type="1065",
            display_name="Form 1065",
            category="partnership_tax_return",
            confidence=1.0,
            score=999.0,
            matched_rules=("primary_header_1065",),
        )

    if form_type == "1120S":
        return DetectionCandidate(
            form_type="1120S",
            display_name="Form 1120-S",
            category="business_tax_return",
            confidence=1.0,
            score=999.0,
            matched_rules=("primary_header_1120s",),
        )

    if form_type == "1040":
        return DetectionCandidate(
            form_type="1040",
            display_name="Form 1040",
            category="tax_return",
            confidence=1.0,
            score=999.0,
            matched_rules=("primary_header_1040",),
        )

    if form_type == "1120":
        return DetectionCandidate(
            form_type="1120",
            display_name="Form 1120",
            category="business_tax_return",
            confidence=1.0,
            score=999.0,
            matched_rules=("primary_header_1120",),
        )

    return DetectionCandidate(
        form_type="UNKNOWN",
        display_name="Unknown Tax Document",
        category="unknown",
        confidence=0.0,
        score=0.0,
        matched_rules=("primary_header_unknown",),
    )



def choose_best_candidate(
    candidates: list[DetectionCandidate],
    *,
    primary_header_form: str | None = None,
) -> DetectionCandidate:
    """
    Choose the primary tax return, not an embedded schedule/K-1.

    Example:
    A 1065 return package can contain Schedule K-1, 1120-S references, Schedule D,
    and Form 4562. If the first page says Form 1065 / U.S. Return of Partnership
    Income, the primary form must be 1065.
    """
    if not candidates:
        raise FormDetectorError("No detection candidates available.")

    by_type = {candidate.form_type: candidate for candidate in candidates}

    if primary_header_form and primary_header_form in by_type:
        return by_type[primary_header_form]

    form_1040 = by_type.get("1040")
    form_1065 = by_type.get("1065")
    form_1120s = by_type.get("1120S")
    form_1120 = by_type.get("1120")

    # Strong individual return should beat embedded K-1/entity references.
    if form_1040 and form_1040.confidence >= 0.90 and form_1040.score >= 100:
        return form_1040

    # Strong partnership return should beat embedded 1120-S/K-1 references.
    if form_1065 and form_1065.confidence >= 0.85 and form_1065.score >= 100:
        return form_1065

    # True standalone 1120-S should win when strong.
    if form_1120s and form_1120s.confidence >= 0.90 and form_1120s.score >= 140:
        return form_1120s

    # True standalone 1120 should win when strong.
    if form_1120 and form_1120.confidence >= 0.90 and form_1120.score >= 120:
        return form_1120

    high_confidence_candidates = [candidate for candidate in candidates if candidate.confidence >= 0.70]

    if high_confidence_candidates:
        return max(
            high_confidence_candidates,
            key=lambda candidate: (
                candidate.confidence,
                candidate.score,
                PRIMARY_RETURN_PRIORITY.get(candidate.form_type, 0),
            ),
        )

    return max(
        candidates,
        key=lambda candidate: (
            candidate.confidence,
            candidate.score,
            PRIMARY_RETURN_PRIORITY.get(candidate.form_type, 0),
        ),
    )




def detect_tax_form_from_text(text: str, extraction_method: str = "text") -> FormDetectionResult:
    normalized = normalize_text(text)
    upper_text = normalized.upper()

    primary_header_form = detect_primary_form_from_header(upper_text)

    candidates = [
        candidate
        for signature in FORM_SIGNATURES
        if (candidate := score_signature(upper_text, signature)) is not None
    ]

    tax_year = detect_tax_year(upper_text)

    # Critical override:
    # If the first-page header clearly identifies the primary return, force it to the top.
    if primary_header_form:
        forced_primary = build_forced_primary_candidate(primary_header_form)

        remaining_candidates = [
            candidate for candidate in candidates if candidate.form_type != forced_primary.form_type
        ]

        remaining_candidates.sort(
            key=lambda candidate: (
                candidate.confidence,
                candidate.score,
                PRIMARY_RETURN_PRIORITY.get(candidate.form_type, 0),
            ),
            reverse=True,
        )

        return FormDetectionResult(
            form_type=forced_primary.form_type,
            display_name=forced_primary.display_name,
            category=forced_primary.category,
            confidence=forced_primary.confidence,
            tax_year=tax_year,
            requires_review=False,
            extracted_text_length=len(normalized),
            extraction_method=extraction_method,
            candidates=tuple([forced_primary] + remaining_candidates[:4]),
        )

    if not candidates:
        return FormDetectionResult(
            form_type="UNKNOWN",
            display_name="Unknown Tax Document",
            category="unknown",
            confidence=0.0,
            tax_year=tax_year,
            requires_review=True,
            extracted_text_length=len(normalized),
            extraction_method=extraction_method,
            candidates=tuple(),
        )

    candidates.sort(
        key=lambda candidate: (
            candidate.confidence,
            candidate.score,
            PRIMARY_RETURN_PRIORITY.get(candidate.form_type, 0),
        ),
        reverse=True,
    )

    best = choose_best_candidate(candidates)

    reordered_candidates = [best] + [
        candidate for candidate in candidates if candidate.form_type != best.form_type
    ]

    requires_review = best.confidence < 0.70

    return FormDetectionResult(
        form_type=best.form_type,
        display_name=best.display_name,
        category=best.category,
        confidence=best.confidence,
        tax_year=tax_year,
        requires_review=requires_review,
        extracted_text_length=len(normalized),
        extraction_method=extraction_method,
        candidates=tuple(reordered_candidates[:5]),
    )





def detect_tax_form_from_file(path: str | Path) -> FormDetectionResult:
    text, extraction_method = extract_text_from_file(path)

    if not text.strip():
        raise TextExtractionError(
            "No readable text was found in this file. "
            "If this is a scanned PDF, OCR is required."
        )

    return detect_tax_form_from_text(text, extraction_method=extraction_method)


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect U.S. tax form type from a file.")
    parser.add_argument("file", help="Path to a PDF, image, TXT, CSV, MD, or HTML file.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    args = parser.parse_args()

    try:
        result = detect_tax_form_from_file(args.file)
        print(json.dumps(result.to_dict(), indent=2 if args.pretty else None))
    except FormDetectorError as exc:
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
