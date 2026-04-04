from __future__ import annotations

from pathlib import Path

import pytest

from app.ocr_probe import ocr_pdf_pages, tesseract_binary


def test_ocr_probe_reads_sample_pdf_text(temp_settings) -> None:
    try:
        tesseract_binary()
    except RuntimeError:
        pytest.skip("tesseract is not available in this environment")

    pdf_path = Path(temp_settings.pdf_dir) / "sample.pdf"
    results = ocr_pdf_pages(pdf_path, [3], lang="eng", psm=6, dpi=200)

    assert 3 in results
    assert "Capital of Korea" in results[3] or "Seoul" in results[3]
