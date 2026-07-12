from __future__ import annotations

import base64
import hashlib
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class PdfExtractorError(Exception):
    """Raised when PDF extraction fails."""


@dataclass(frozen=True)
class ExtractedPdfPage:
    page_number: int
    text: str
    image_path: str | None
    image_base64: str | None
    text_length: int
    extraction_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "text": self.text,
            "image_path": self.image_path,
            "image_base64": self.image_base64,
            "text_length": self.text_length,
            "extraction_notes": list(self.extraction_notes),
        }


@dataclass(frozen=True)
class ExtractedPdfDocument:
    file_name: str
    file_sha256: str
    file_size_bytes: int
    page_count: int
    full_text: str
    pages: list[ExtractedPdfPage]
    text_extraction_engine: str
    image_extraction_engine: str | None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self, *, include_page_text: bool = True, include_images: bool = False) -> dict[str, Any]:
        pages_payload: list[dict[str, Any]] = []

        for page in self.pages:
            page_dict = page.to_dict()

            if not include_page_text:
                page_dict["text"] = ""

            if not include_images:
                page_dict["image_base64"] = None

            pages_payload.append(page_dict)

        return {
            "file_name": self.file_name,
            "file_sha256": self.file_sha256,
            "file_size_bytes": self.file_size_bytes,
            "page_count": self.page_count,
            "full_text": self.full_text if include_page_text else "",
            "text_extraction_engine": self.text_extraction_engine,
            "image_extraction_engine": self.image_extraction_engine,
            "warnings": list(self.warnings),
            "pages": pages_payload,
        }


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def read_image_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def extract_text_with_pypdf(path: Path) -> tuple[list[str], list[str]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise PdfExtractorError("pypdf is required. Install it with: pip install pypdf") from exc

    warnings: list[str] = []

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        raise PdfExtractorError(f"Unable to open PDF: {exc}") from exc

    page_texts: list[str] = []

    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            text = ""
            warnings.append(f"Page {index}: text extraction failed: {exc}")

        if not text.strip():
            warnings.append(f"Page {index}: no readable text extracted with pypdf.")

        page_texts.append(text)

    return page_texts, warnings


def render_pdf_pages_with_pymupdf(
    path: Path,
    *,
    output_dir: Path,
    dpi: int = 180,
    include_base64: bool = False,
) -> tuple[list[tuple[str, str | None]], list[str]]:
    warnings: list[str] = []

    try:
        import fitz
    except ImportError:
        return [], [
            "PyMuPDF is not installed, so page images were not rendered. "
            "Install it with: pip install PyMuPDF"
        ]

    rendered_pages: list[tuple[str, str | None]] = []

    try:
        document = fitz.open(str(path))
    except Exception as exc:
        raise PdfExtractorError(f"Unable to render PDF pages with PyMuPDF: {exc}") from exc

    zoom = dpi / 72

    try:
        matrix = fitz.Matrix(zoom, zoom)

        for page_index in range(document.page_count):
            page_number = page_index + 1
            page = document.load_page(page_index)

            try:
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                image_path = output_dir / f"page_{page_number:04d}.png"
                pixmap.save(str(image_path))

                image_base64 = read_image_base64(image_path) if include_base64 else None
                rendered_pages.append((str(image_path), image_base64))

            except Exception as exc:
                warnings.append(f"Page {page_number}: image rendering failed: {exc}")
                rendered_pages.append(("", None))

    finally:
        document.close()

    return rendered_pages, warnings


def extract_pdf(
    path: str | Path,
    *,
    render_images: bool = True,
    include_image_base64: bool = False,
    output_dir: str | Path | None = None,
    dpi: int = 180,
) -> ExtractedPdfDocument:
    pdf_path = Path(path)

    if not pdf_path.exists():
        raise PdfExtractorError(f"PDF file does not exist: {pdf_path}")

    if not pdf_path.is_file():
        raise PdfExtractorError(f"Path is not a file: {pdf_path}")

    if pdf_path.suffix.lower() != ".pdf":
        raise PdfExtractorError(f"Expected a PDF file, got: {pdf_path.suffix}")

    file_size = pdf_path.stat().st_size
    file_hash = calculate_sha256(pdf_path)

    text_pages, text_warnings = extract_text_with_pypdf(pdf_path)

    warnings = list(text_warnings)
    image_engine: str | None = None

    if output_dir is None:
        image_output_dir = Path(tempfile.mkdtemp(prefix="taxtruth_pdf_pages_"))
    else:
        image_output_dir = Path(output_dir)
        image_output_dir.mkdir(parents=True, exist_ok=True)

    rendered_pages: list[tuple[str, str | None]] = []

    if render_images:
        rendered_pages, image_warnings = render_pdf_pages_with_pymupdf(
            pdf_path,
            output_dir=image_output_dir,
            dpi=dpi,
            include_base64=include_image_base64,
        )
        warnings.extend(image_warnings)

        if rendered_pages:
            image_engine = "PyMuPDF"

    pages: list[ExtractedPdfPage] = []

    page_count = max(len(text_pages), len(rendered_pages))

    for index in range(page_count):
        text = text_pages[index] if index < len(text_pages) else ""

        image_path: str | None = None
        image_base64: str | None = None

        if index < len(rendered_pages):
            rendered_path, rendered_base64 = rendered_pages[index]
            image_path = rendered_path or None
            image_base64 = rendered_base64

        page_notes: list[str] = []

        if not text.strip():
            page_notes.append("No text extracted from this page; vision extraction should be used.")

        if render_images and not image_path:
            page_notes.append("No page image rendered.")

        pages.append(
            ExtractedPdfPage(
                page_number=index + 1,
                text=text,
                image_path=image_path,
                image_base64=image_base64,
                text_length=len(text),
                extraction_notes=page_notes,
            )
        )

    full_text = "\n\n".join(page.text for page in pages if page.text.strip())

    return ExtractedPdfDocument(
        file_name=pdf_path.name,
        file_sha256=file_hash,
        file_size_bytes=file_size,
        page_count=page_count,
        full_text=full_text,
        pages=pages,
        text_extraction_engine="pypdf",
        image_extraction_engine=image_engine,
        warnings=warnings,
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Extract text and optional page images from a tax return PDF.")
    parser.add_argument("pdf", help="Path to PDF file")
    parser.add_argument("--no-images", action="store_true", help="Skip rendering page images")
    parser.add_argument("--include-base64", action="store_true", help="Include page image base64 in JSON output")
    parser.add_argument("--output-dir", default=None, help="Directory for rendered page images")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args()

    try:
        document = extract_pdf(
            args.pdf,
            render_images=not args.no_images,
            include_image_base64=args.include_base64,
            output_dir=args.output_dir,
        )

        print(
            json.dumps(
                document.to_dict(include_page_text=True, include_images=args.include_base64),
                indent=2 if args.pretty else None,
            )
        )

    except PdfExtractorError as exc:
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
