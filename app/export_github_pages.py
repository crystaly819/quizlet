from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, UTC
from pathlib import Path

import fitz
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .config import Settings
from .database import configure_database, init_db, session_scope
from .main import build_multi_select_correct_text, resolve_source_pdf_path
from .models import Deck, Question
from .parser import compact_text, extract_choice_indices_from_text


def question_storage_key(deck: Deck, question: Question) -> str:
    raw = "|".join(
        [
            deck.slug,
            str(question.number),
            str(question.page_number),
            question.question_kind,
            compact_text(question.stem),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def build_correct_text(question: Question) -> str | None:
    if question.question_kind == "flashcard":
        return question.answer_text
    if question.question_kind == "short_answer":
        return question.answer_text
    if question.question_kind == "true_false":
        return question.answer_text
    if question.question_kind == "multi_select":
        return build_multi_select_correct_text(
            question.get_choices(),
            extract_choice_indices_from_text(question.answer_text),
        )
    choices = question.get_choices()
    if question.correct_index is None:
        return None
    if 1 <= question.correct_index <= len(choices):
        return choices[question.correct_index - 1]
    return None


def render_preview_image(
    settings: Settings,
    previews_dir: Path,
    deck: Deck,
    question: Question,
    *,
    question_key: str,
    documents: dict[str, fitz.Document],
) -> str | None:
    if not question.source_bbox:
        return None

    try:
        bbox = json.loads(question.source_bbox)
    except json.JSONDecodeError:
        return None

    if not isinstance(bbox, list) or len(bbox) != 4:
        return None

    pdf_path = resolve_source_pdf_path(settings, deck.source_pdf)
    if not pdf_path.exists():
        return None

    path_key = str(pdf_path.resolve())
    document = documents.get(path_key)
    if document is None:
        document = fitz.open(pdf_path)
        documents[path_key] = document

    if question.page_number < 1 or question.page_number > document.page_count:
        return None

    page = document[question.page_number - 1]
    pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=fitz.Rect(*bbox), alpha=False)
    preview_name = f"{question_key}.png"
    preview_path = previews_dir / preview_name
    preview_path.write_bytes(pixmap.tobytes("png"))
    return f"./previews/{preview_name}"


def build_question_payload(
    settings: Settings,
    previews_dir: Path,
    deck: Deck,
    question: Question,
    *,
    documents: dict[str, fitz.Document],
) -> dict:
    question_key = question_storage_key(deck, question)
    correct_indices = (
        extract_choice_indices_from_text(question.answer_text)
        if question.question_kind == "multi_select"
        else None
    )
    preview_src = render_preview_image(
        settings,
        previews_dir,
        deck,
        question,
        question_key=question_key,
        documents=documents,
    )
    return {
        "id": question.id,
        "key": question_key,
        "number": question.number,
        "page_number": question.page_number,
        "question_kind": question.question_kind,
        "stem": question.stem,
        "answer_text": question.answer_text,
        "explanation_text": question.explanation_text,
        "choices": [
            {"index": index, "text": text}
            for index, text in enumerate(question.get_choices(), start=1)
        ],
        "correct_index": question.correct_index,
        "correct_indices": correct_indices,
        "correct_text": build_correct_text(question),
        "manual_reviewed": question.manual_reviewed,
        "preview_src": preview_src,
    }


def export_github_pages_site(settings: Settings, output_dir: Path) -> Path:
    assets_dir = output_dir / "assets"
    data_dir = output_dir / "data"
    previews_dir = output_dir / "previews"
    assets_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(previews_dir, ignore_errors=True)
    previews_dir.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(settings.static_dir / "styles.css", assets_dir / "styles.css")
    shutil.copyfile(settings.static_dir / "timer.js", assets_dir / "timer.js")
    (output_dir / ".nojekyll").write_text("", encoding="utf-8")

    with session_scope() as session:
        decks = session.execute(
            select(Deck)
            .options(selectinload(Deck.questions))
            .order_by(Deck.title)
        ).scalars().all()

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "site_title": "수정 예시 문제집",
        "decks": [],
    }
    documents: dict[str, fitz.Document] = {}
    try:
        for deck in decks:
            approved_questions = [question for question in deck.questions if question.is_approved]
            payload["decks"].append(
                {
                    "id": deck.id,
                    "slug": deck.slug,
                    "title": deck.title,
                    "page_count": deck.page_count,
                    "question_count": len(approved_questions),
                    "approved_count": len(approved_questions),
                    "questions": [
                        build_question_payload(
                            settings,
                            previews_dir,
                            deck,
                            question,
                            documents=documents,
                        )
                        for question in approved_questions
                    ],
                }
            )
    finally:
        for document in documents.values():
            document.close()

    output_path = data_dir / "app-data.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export a GitHub Pages-friendly static study site.")
    parser.add_argument(
        "--output-dir",
        default="docs",
        help="Directory that will receive the GitHub Pages export (default: docs).",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings.from_env()
    configure_database(settings.database_url)
    init_db()

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = settings.base_dir / output_dir

    output_path = export_github_pages_site(settings, output_dir)
    print(f"Exported GitHub Pages data to {output_path}")


if __name__ == "__main__":
    main()
