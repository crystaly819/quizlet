from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from app.config import Settings


def build_sample_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((360, 60), "반복 헤더", fontsize=9)
    page.insert_text((285, 800), "- 1 -", fontsize=10)

    page.insert_text((56, 120), "1. 첫 번째 문제는 무엇인가?", fontsize=12)
    page.insert_text((72, 148), "① 정답 보기", fontsize=12)
    page.insert_text((283, 148), "② 오답 보기", fontsize=12)
    page.insert_text((72, 172), "③ 다른 오답", fontsize=12)
    page.insert_text((283, 172), "④ 또 다른 오답", fontsize=12)
    page.insert_text((72, 196), "⑤ 마지막 오답", fontsize=12)
    page.draw_rect(fitz.Rect(72, 136, 83, 149), fill=(1, 1, 0), color=None)

    page.insert_text((56, 260), "2. 보기 조합 문제로 가장 알맞은 것은?", fontsize=12)
    page.insert_text((72, 286), "㉠ 알파", fontsize=12)
    page.insert_text((283, 286), "㉡ 베타", fontsize=12)
    page.insert_text((72, 318), "① ㉠", fontsize=12)
    page.insert_text((283, 318), "② ㉡", fontsize=12)
    page.insert_text((72, 342), "③ ㉠, ㉡", fontsize=12)
    page.insert_text((283, 342), "④ 없음", fontsize=12)
    page.insert_text((72, 366), "⑤ 기타", fontsize=12)

    true_false_page = document.new_page(width=595, height=842)
    true_false_page.insert_text((360, 60), "반복 헤더", fontsize=9)
    true_false_page.insert_text((50, 50), "O/X", fontsize=12)
    true_false_page.insert_text((430, 50), "정답및해설", fontsize=12)
    true_false_page.insert_text((50, 90), "1.", fontsize=12)
    true_false_page.insert_text((73, 90), "물은 상온에서 액체이다.", fontsize=12)
    true_false_page.insert_text((430, 90), "(O)", fontsize=12)
    true_false_page.insert_text((455, 90), "[상온에서 물은 액체 상태다.]", fontsize=12)

    short_answer_page = document.new_page(width=595, height=842)
    short_answer_page.insert_text((360, 60), "반복 헤더", fontsize=9)
    short_answer_page.insert_text((50, 50), "단답형", fontsize=12)
    short_answer_page.insert_text((430, 50), "정답및해설", fontsize=12)
    short_answer_page.insert_text((50, 90), "1.", fontsize=12)
    short_answer_page.insert_text((73, 90), "Capital of Korea?", fontsize=12)
    short_answer_page.insert_text((430, 90), "Seoul", fontsize=12)
    short_answer_page.insert_text((430, 114), "[Seoul is the capital of Korea.]", fontsize=12)

    r_type_page = document.new_page(width=595, height=842)
    r_type_page.insert_text((50, 80), "419. Choose the matching tests below.", fontsize=12)
    r_type_page.insert_text((60, 120), "① Sterility test", fontsize=12)
    r_type_page.insert_text((280, 120), "④ Dissolution test", fontsize=12)
    r_type_page.insert_text((60, 146), "② Endotoxin test", fontsize=12)
    r_type_page.insert_text((280, 146), "⑤ Assay", fontsize=12)
    r_type_page.insert_text((60, 172), "③ Content uniformity", fontsize=12)
    r_type_page.insert_text((60, 220), "(1) Pick two release-related tests.", fontsize=12)
    r_type_page.insert_text((60, 246), "<A ④⑤>", fontsize=12)
    r_type_page.insert_text((60, 286), "(2) Pick two injection-related tests.", fontsize=12)
    r_type_page.insert_text((60, 312), "<A ①②>", fontsize=12)

    document.save(path)


@pytest.fixture()
def temp_settings(tmp_path: Path) -> Settings:
    repo_root = Path(__file__).resolve().parent.parent
    pdf_dir = tmp_path / "pdfs"
    data_dir = tmp_path / "data"
    pdf_dir.mkdir()
    data_dir.mkdir()

    build_sample_pdf(pdf_dir / "sample.pdf")

    return Settings(
        base_dir=repo_root,
        data_dir=data_dir,
        pdf_dir=pdf_dir,
        database_url=f"sqlite:///{(data_dir / 'test.db').as_posix()}",
        auto_ingest=False,
        testing=True,
    )
