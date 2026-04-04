from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

import fitz


def tesseract_binary() -> str:
    binary = shutil.which("tesseract")
    if binary is None:
        raise RuntimeError("tesseract is not installed or not available on PATH.")
    return binary


def available_languages() -> list[str]:
    binary = tesseract_binary()
    result = subprocess.run(
        [binary, "--list-langs"],
        capture_output=True,
        text=True,
        check=True,
    )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return [line for line in lines if not line.startswith("List of available languages")]


def render_page_to_png_bytes(pdf_path: Path, page_number: int, dpi: int = 300) -> bytes:
    document = fitz.open(pdf_path)
    try:
        if page_number < 1 or page_number > document.page_count:
            raise ValueError(f"Page {page_number} is out of range for {pdf_path.name}.")
        page = document[page_number - 1]
        scale = dpi / 72.0
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        return pixmap.tobytes("png")
    finally:
        document.close()


def ocr_png_bytes(image_bytes: bytes, *, lang: str = "eng+snum", psm: int = 6) -> str:
    binary = tesseract_binary()
    with tempfile.TemporaryDirectory() as tmp_dir:
        image_path = Path(tmp_dir) / "page.png"
        image_path.write_bytes(image_bytes)
        result = subprocess.run(
            [
                binary,
                str(image_path),
                "stdout",
                "--psm",
                str(psm),
                "-l",
                lang,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    return result.stdout.strip()


def ocr_pdf_pages(
    pdf_path: Path,
    page_numbers: list[int],
    *,
    lang: str = "eng+snum",
    psm: int = 6,
    dpi: int = 300,
) -> dict[int, str]:
    results: dict[int, str] = {}
    for page_number in page_numbers:
        image_bytes = render_page_to_png_bytes(pdf_path, page_number, dpi=dpi)
        results[page_number] = ocr_png_bytes(image_bytes, lang=lang, psm=psm)
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a minimal Tesseract OCR probe against selected PDF pages.")
    parser.add_argument("pdf_path", help="Path to the source PDF.")
    parser.add_argument("--pages", nargs="+", type=int, required=True, help="1-based page numbers to OCR.")
    parser.add_argument("--lang", default="eng+snum", help="Tesseract language pack hint, for example eng or kor+eng.")
    parser.add_argument("--psm", type=int, default=6, help="Tesseract page segmentation mode.")
    parser.add_argument("--dpi", type=int, default=300, help="Rendering DPI before OCR.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")

    langs = available_languages()
    print(f"Available languages: {', '.join(langs)}")
    results = ocr_pdf_pages(
        pdf_path,
        page_numbers=args.pages,
        lang=args.lang,
        psm=args.psm,
        dpi=args.dpi,
    )
    for page_number in args.pages:
        print(f"\n=== Page {page_number} ===")
        print(results[page_number])


if __name__ == "__main__":
    main()
