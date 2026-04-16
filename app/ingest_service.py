from __future__ import annotations

import json
import shutil
from pathlib import Path
from time import perf_counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import Settings
from .database import Base, session_scope
from .models import Attempt, Deck, ParseIssue, Question
from .parser import parse_pdf
from .pdf_selector import select_pdfs_interactively


def emit_progress(message: str) -> None:
    print(message, flush=True)


def choose_pdf_paths(
    pdf_dir: Path,
    *,
    selected_pdfs: list[Path] | None = None,
    interactive_select: bool = False,
) -> list[Path]:
    pdf_paths = sorted(path for path in pdf_dir.glob("*.pdf") if path.is_file())
    if selected_pdfs is not None:
        selected_set = {path.resolve() for path in selected_pdfs}
        return [path for path in pdf_paths if path.resolve() in selected_set]
    if interactive_select and len(pdf_paths) > 1:
        return select_pdfs_interactively(pdf_paths)
    return pdf_paths


def source_key(pdf_path: Path, settings: Settings) -> str:
    try:
        return str(pdf_path.relative_to(settings.base_dir))
    except ValueError:
        return str(pdf_path)


def clear_runtime_data(settings: Settings) -> None:
    emit_progress("[ingest] Clearing runtime cache directories")
    shutil.rmtree(settings.data_dir / "crops", ignore_errors=True)
    shutil.rmtree(settings.cache_dir, ignore_errors=True)
    settings.ensure_dirs()


def reset_all_data(session: Session, settings: Settings) -> None:
    emit_progress("[ingest] Rebuilding database schema from scratch")
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
        emit_progress(f"[ingest] Replacing existing deck for '{pdf_path.name}'")
        session.delete(existing)
        session.flush()


def ingest_pdf(session: Session, settings: Settings, pdf_path: Path) -> dict:
    started_at = perf_counter()
    emit_progress(f"[ingest] Starting '{pdf_path.name}'")
    replace_existing_deck(session, settings, pdf_path)
    parse_result = parse_pdf(
        pdf_path,
        settings.cache_dir,
        progress_callback=emit_progress,
    )
    emit_progress(f"[ingest] Saving parsed questions for '{pdf_path.name}' to the database")

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

    for index, parsed_question in enumerate(parse_result.questions, start=1):
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

        if len(parse_result.questions) >= 200 and index % 250 == 0:
            emit_progress(
                f"[ingest] Stored {index}/{len(parse_result.questions)} questions for '{pdf_path.name}'"
            )

    elapsed = perf_counter() - started_at
    emit_progress(
        f"[ingest] Finished '{pdf_path.name}' in {elapsed:.1f}s: "
        f"{deck.question_count} questions, {approved_count} approved, {issue_count} issues"
    )
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
    selected_pdfs: list[Path] | None = None,
    interactive_select: bool = False,
) -> list[dict]:
    settings.ensure_dirs()
    pdf_paths = choose_pdf_paths(
        pdf_dir,
        selected_pdfs=selected_pdfs,
        interactive_select=interactive_select,
    )
    emit_progress(f"[ingest] Found {len(pdf_paths)} PDF file(s) in '{pdf_dir}'")
    summaries: list[dict] = []

    with session_scope() as session:
        if rebuild:
            reset_all_data(session, settings)

        for index, pdf_path in enumerate(pdf_paths, start=1):
            emit_progress(f"[ingest] Processing file {index}/{len(pdf_paths)}: '{pdf_path.name}'")
            summaries.append(ingest_pdf(session, settings, pdf_path))

    return summaries


def sync_selected_decks(
    pdf_dir: Path,
    settings: Settings,
    *,
    interactive_select: bool = False,
) -> list[dict]:
    settings.ensure_dirs()
    pdf_paths = choose_pdf_paths(pdf_dir, interactive_select=interactive_select)
    emit_progress(f"[startup] Selected {len(pdf_paths)} PDF file(s) from '{pdf_dir}'")

    selected_sources = {source_key(path, settings): path for path in pdf_paths}
    summaries: list[dict] = []

    with session_scope() as session:
        existing_decks = session.execute(select(Deck)).scalars().all()
        existing_sources = {deck.source_pdf for deck in existing_decks}

        for deck in existing_decks:
            if deck.source_pdf in selected_sources:
                continue
            emit_progress(f"[startup] Removing unselected deck '{deck.title}'")
            session.delete(deck)
        session.flush()

        for index, pdf_path in enumerate(pdf_paths, start=1):
            deck_source = source_key(pdf_path, settings)
            if deck_source in existing_sources:
                emit_progress(f"[startup] Keeping already loaded deck '{pdf_path.name}'")
                continue
            emit_progress(f"[startup] Loading selected file {index}/{len(pdf_paths)}: '{pdf_path.name}'")
            summaries.append(ingest_pdf(session, settings, pdf_path))

    return summaries


def deck_count() -> int:
    with session_scope() as session:
        value = session.execute(select(func.count(Deck.id))).scalar_one()
    return int(value or 0)
