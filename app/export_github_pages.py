from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, UTC
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .config import Settings
from .database import configure_database, init_db, session_scope
from .main import build_multi_select_correct_text
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


def build_question_payload(deck: Deck, question: Question) -> dict:
    correct_indices = (
        extract_choice_indices_from_text(question.answer_text)
        if question.question_kind == "multi_select"
        else None
    )
    return {
        "id": question.id,
        "key": question_storage_key(deck, question),
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
        # Server-generated preview crops are not available on GitHub Pages.
        "preview_src": None,
    }


def export_github_pages_site(settings: Settings, output_dir: Path) -> Path:
    assets_dir = output_dir / "assets"
    data_dir = output_dir / "data"
    assets_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

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
                    build_question_payload(deck, question)
                    for question in approved_questions
                ],
            }
        )

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
