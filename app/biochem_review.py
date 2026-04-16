from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import fitz


CHUNK_SIZE = 10
BIOCHEM_SOURCE_PDF = "pdfs/[답] 생화학 분과회 문제집 답치기 (1).pdf"


@dataclass(frozen=True, slots=True)
class ReviewChunk:
    start_page: int
    end_page: int

    @property
    def slug(self) -> str:
        return f"pages-{self.start_page:03d}-{self.end_page:03d}"

    @property
    def label(self) -> str:
        return f"{self.start_page}-{self.end_page}"


def build_review_chunks(
    *,
    start_page: int,
    end_page: int,
    chunk_size: int = CHUNK_SIZE,
) -> list[ReviewChunk]:
    if start_page < 1:
        raise ValueError("start_page must be >= 1")
    if end_page < start_page:
        raise ValueError("end_page must be >= start_page")
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")

    chunks: list[ReviewChunk] = []
    current = start_page
    while current <= end_page:
        chunk_end = min(end_page, current + chunk_size - 1)
        chunks.append(ReviewChunk(start_page=current, end_page=chunk_end))
        current = chunk_end + 1
    return chunks


def reviewed_question_schema() -> dict:
    return {
        "question_number": 0,
        "page_number": 0,
        "question_kind": "multiple_choice",
        "stem": "",
        "choices": ["", "", "", "", ""],
        "correct_index": 1,
        "answer_text": None,
        "manual_reviewed": True,
    }


def chunk_template_payload(chunk: ReviewChunk, *, source_pdf: str = BIOCHEM_SOURCE_PDF) -> dict:
    return {
        "source_pdf": source_pdf,
        "page_range": {
            "start": chunk.start_page,
            "end": chunk.end_page,
        },
        "review_completed": False,
        "questions": [],
        "question_schema": reviewed_question_schema(),
        "instructions": [
            "형광 표시된 보기만 정답으로 저장한다.",
            "객관식 1개 정답은 correct_index를 사용한다.",
            "복수정답은 answer_text에 '②, ④' 형식으로 저장하고 correct_index는 null로 둔다.",
            "question_number는 PDF 인쇄 번호, page_number는 실제 PDF 페이지 번호를 사용한다.",
        ],
    }


def render_chunk_pages(
    pdf_path: Path,
    chunk: ReviewChunk,
    output_dir: Path,
    *,
    scale: float = 2.5,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered_paths: list[Path] = []
    document = fitz.open(pdf_path)
    try:
        for page_number in range(chunk.start_page, chunk.end_page + 1):
            page = document[page_number - 1]
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            image_path = output_dir / f"page-{page_number:03d}.png"
            pixmap.save(image_path)
            rendered_paths.append(image_path)
    finally:
        document.close()
    return rendered_paths


def question_to_cache_entry(question: dict) -> dict:
    choices = question.get("choices") or []
    normalized_choices = [
        {
            "index": index,
            "label": ["①", "②", "③", "④", "⑤"][index - 1] if index <= 5 else str(index),
            "text": str(choice),
            "bbox": [],
            "label_bbox": [],
        }
        for index, choice in enumerate(choices, start=1)
        if str(choice).strip()
    ]
    answer_text = question.get("answer_text")
    correct_index = question.get("correct_index")
    return {
        "number": int(question["question_number"]),
        "page_number": int(question["page_number"]),
        "stem": str(question["stem"]).strip(),
        "question_kind": str(question["question_kind"]),
        "choices": normalized_choices,
        "answer_text": answer_text.strip() if isinstance(answer_text, str) and answer_text.strip() else None,
        "correct_index": int(correct_index) if correct_index is not None else None,
        "confidence": 1.0,
        "approved": True,
        "issue_reason": None,
        "crop_rel_path": None,
        "source": "vlm_review",
        "manual_reviewed": True,
    }


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
