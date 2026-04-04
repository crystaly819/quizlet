from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.database import configure_database, init_db, session_scope
from app.ingest_service import ingest_pdf_directory
from app.models import Deck, Question

PDF06_TITLE = "06. 생약학 필수 문제집_워터마크"
PDF15_TITLE = "15. 약제학 약동학 개념확인 문제집_워터마크"
QUALITY_TITLE = "[보안][답치기] 대한민국 약전 품질 파트"


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
    summary_by_title = {summary["title"]: summary for summary in summaries}
    assert summary_by_title[PDF06_TITLE]["question_count"] > 0
    assert summary_by_title[PDF15_TITLE]["question_count"] > 0
    assert summary_by_title[QUALITY_TITLE]["question_count"] > 0

    with session_scope() as session:
        decks = session.execute(select(Deck).order_by(Deck.id)).scalars().all()
        approved_questions = session.execute(
            select(Question).where(Question.is_approved.is_(True))
        ).scalars().all()
        pdf15_deck = session.execute(
            select(Deck).where(Deck.title == PDF15_TITLE)
        ).scalar_one()
        pdf15_kind_rows = session.execute(
            select(Question.question_kind, func.count(Question.id))
            .where(Question.deck_id == pdf15_deck.id, Question.is_approved.is_(True))
            .group_by(Question.question_kind)
        ).all()
        quality_deck = session.execute(
            select(Deck).where(Deck.title == QUALITY_TITLE)
        ).scalar_one()
        quality_kind_rows = session.execute(
            select(Question.question_kind, func.count(Question.id))
            .where(Question.deck_id == quality_deck.id, Question.is_approved.is_(True))
            .group_by(Question.question_kind)
        ).all()
        pdf15_min_page = session.execute(
            select(func.min(Question.page_number)).where(Question.deck_id == pdf15_deck.id)
        ).scalar_one()

    assert len(decks) >= 3
    assert approved_questions
    assert all(question.source_bbox for question in approved_questions)
    assert all(question.crop_path is None for question in approved_questions)
    assert pdf15_min_page == 5
    assert any(deck.title == PDF06_TITLE for deck in decks)
    assert any(deck.title == PDF15_TITLE for deck in decks)
    assert any(deck.title == QUALITY_TITLE for deck in decks)
    pdf15_kinds = {kind for kind, _ in pdf15_kind_rows}
    assert "true_false" in pdf15_kinds
    assert "short_answer" in pdf15_kinds
    quality_kinds = {kind for kind, _ in quality_kind_rows}
    assert "multi_select" in quality_kinds
