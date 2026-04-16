from __future__ import annotations

from pathlib import Path
import unicodedata

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.database import configure_database, init_db, session_scope
from app.ingest_service import ingest_pdf_directory
from app.models import Deck, Question

PDF06_TITLE = "생약학"
PDF15_TITLE = "약제/약동학"
QUALITY_TITLE = "약전 품질"
DRUG_CARD_TITLE = "약물구조"


def normalize_title(value: str) -> str:
    return unicodedata.normalize("NFC", value)


@pytest.mark.integration
def test_real_pdf_corpus_ingests_known_decks(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    settings = Settings(
        base_dir=repo_root,
        data_dir=tmp_path / "data",
        pdf_dir=repo_root / "pdfs",
        database_url=f"sqlite:///{((tmp_path / 'data') / 'integration.db').as_posix()}",
        auto_ingest=False,
        testing=True,
    )
    settings.ensure_dirs()

    configure_database(settings.database_url)
    init_db()
    summaries = ingest_pdf_directory(settings.pdf_dir, settings, rebuild=True)

    assert len(summaries) >= 3
    summary_by_title = {normalize_title(summary["title"]): summary for summary in summaries}
    assert summary_by_title[normalize_title(PDF06_TITLE)]["question_count"] > 0
    assert summary_by_title[normalize_title(PDF15_TITLE)]["question_count"] > 0
    assert summary_by_title[normalize_title(QUALITY_TITLE)]["question_count"] > 0
    assert summary_by_title[normalize_title(DRUG_CARD_TITLE)]["question_count"] >= 100

    with session_scope() as session:
        decks = session.execute(select(Deck).order_by(Deck.id)).scalars().all()
        deck_by_title = {normalize_title(deck.title): deck for deck in decks}
        approved_questions = session.execute(
            select(Question).where(Question.is_approved.is_(True))
        ).scalars().all()
        pdf15_deck = deck_by_title[normalize_title(PDF15_TITLE)]
        pdf15_kind_rows = session.execute(
            select(Question.question_kind, func.count(Question.id))
            .where(Question.deck_id == pdf15_deck.id, Question.is_approved.is_(True))
            .group_by(Question.question_kind)
        ).all()
        quality_deck = deck_by_title[normalize_title(QUALITY_TITLE)]
        quality_kind_rows = session.execute(
            select(Question.question_kind, func.count(Question.id))
            .where(Question.deck_id == quality_deck.id, Question.is_approved.is_(True))
            .group_by(Question.question_kind)
        ).all()
        drug_card_deck = deck_by_title[normalize_title(DRUG_CARD_TITLE)]
        drug_card_kind_rows = session.execute(
            select(Question.question_kind, func.count(Question.id))
            .where(Question.deck_id == drug_card_deck.id, Question.is_approved.is_(True))
            .group_by(Question.question_kind)
        ).all()
        drug_card_first_question = session.execute(
            select(Question)
            .where(Question.deck_id == drug_card_deck.id)
            .order_by(Question.number, Question.page_number)
        ).scalars().first()
        pdf15_min_page = session.execute(
            select(func.min(Question.page_number)).where(Question.deck_id == pdf15_deck.id)
        ).scalar_one()

    assert len(decks) >= 3
    assert approved_questions
    assert all(question.source_bbox for question in approved_questions)
    assert all(question.crop_path is None for question in approved_questions)
    assert pdf15_min_page == 5
    assert normalize_title(PDF06_TITLE) in deck_by_title
    assert normalize_title(PDF15_TITLE) in deck_by_title
    assert normalize_title(QUALITY_TITLE) in deck_by_title
    assert normalize_title(DRUG_CARD_TITLE) in deck_by_title
    pdf15_kinds = {kind for kind, _ in pdf15_kind_rows}
    assert "true_false" in pdf15_kinds
    assert "short_answer" in pdf15_kinds
    quality_kinds = {kind for kind, _ in quality_kind_rows}
    assert "multi_select" in quality_kinds
    drug_card_kinds = {kind for kind, _ in drug_card_kind_rows}
    assert drug_card_kinds == {"multiple_choice"}
    assert drug_card_first_question is not None
    assert drug_card_first_question.correct_index is not None
    assert len(drug_card_first_question.get_choices()) == 4
