from __future__ import annotations

import json
import shutil
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import Settings
from .database import Base, session_scope
from .models import Attempt, Deck, ParseIssue, Question
from .parser import parse_pdf


def source_key(pdf_path: Path, settings: Settings) -> str:
    try:
        return str(pdf_path.relative_to(settings.base_dir))
    except ValueError:
        return str(pdf_path)


def clear_runtime_data(settings: Settings) -> None:
    shutil.rmtree(settings.data_dir / "crops", ignore_errors=True)
    shutil.rmtree(settings.cache_dir, ignore_errors=True)
    settings.ensure_dirs()


def reset_all_data(session: Session, settings: Settings) -> None:
    bind = session.get_bind()
    session.rollback()
    Base.metadata.drop_all(bind=bind)
    Base.metadata.create_all(bind=bind)
    clear_runtime_data(settings)


def replace_existing_deck(session: Session, settings: Settings, pdf_path: Path) -> None:
    existing = session.execute(
        select(Deck).where(Deck.source_pdf == source_key(pdf_path, settings))
    ).scalar_one_or_none()
    if existing is not None:
        session.delete(existing)
        session.flush()


def ingest_pdf(session: Session, settings: Settings, pdf_path: Path) -> dict:
    replace_existing_deck(session, settings, pdf_path)
    parse_result = parse_pdf(pdf_path, settings.cache_dir)

    deck = Deck(
        title=parse_result.title,
        slug=parse_result.slug,
        source_pdf=source_key(pdf_path, settings),
        page_count=parse_result.page_count,
        question_count=len(parse_result.questions),
    )
    session.add(deck)
    session.flush()

    approved_count = 0
    issue_count = 0

    for parsed_question in parse_result.questions:
        question = Question(
            deck_id=deck.id,
            number=parsed_question.number,
            page_number=parsed_question.page_number,
            question_kind=parsed_question.question_kind,
            stem=parsed_question.stem,
            answer_text=parsed_question.answer_text,
            explanation_text=parsed_question.explanation_text,
            correct_index=parsed_question.correct_index,
            confidence=parsed_question.confidence,
            source_bbox=json.dumps(parsed_question.bbox),
            crop_path=parsed_question.crop_rel_path,
            is_approved=parsed_question.approved,
        )
        question.set_choices([choice.text for choice in parsed_question.choices])
        session.add(question)
        session.flush()

        if parsed_question.issue_reason:
            issue = ParseIssue(
                question_id=question.id,
                reason=parsed_question.issue_reason,
                payload_json=json.dumps(parsed_question.payload, ensure_ascii=False),
                status="open",
            )
            session.add(issue)
            issue_count += 1

        if parsed_question.approved:
            approved_count += 1

    return {
        "title": deck.title,
        "source_pdf": deck.source_pdf,
        "page_count": deck.page_count,
        "question_count": deck.question_count,
        "approved_count": approved_count,
        "issue_count": issue_count,
    }


def ingest_pdf_directory(
    pdf_dir: Path,
    settings: Settings,
    rebuild: bool = False,
) -> list[dict]:
    settings.ensure_dirs()
    pdf_paths = sorted(path for path in pdf_dir.glob("*.pdf") if path.is_file())
    summaries: list[dict] = []

    with session_scope() as session:
        if rebuild:
            reset_all_data(session, settings)

        for pdf_path in pdf_paths:
            summaries.append(ingest_pdf(session, settings, pdf_path))

    return summaries


def deck_count() -> int:
    with session_scope() as session:
        value = session.execute(select(func.count(Deck.id))).scalar_one()
    return int(value or 0)
