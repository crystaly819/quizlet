from __future__ import annotations

import json

from app.database import configure_database, init_db
from app.export_github_pages import export_github_pages_site
from app.ingest_service import ingest_pdf_directory


def test_export_github_pages_site_writes_deck_and_question_data(temp_settings, tmp_path) -> None:
    configure_database(temp_settings.database_url)
    init_db()
    ingest_pdf_directory(temp_settings.pdf_dir, temp_settings, rebuild=True)

    output_path = export_github_pages_site(temp_settings, tmp_path / "docs")

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["site_title"] == "수정 예시 문제집"
    assert payload["decks"]
    assert (tmp_path / "docs" / "assets" / "styles.css").exists()
    assert (tmp_path / "docs" / ".nojekyll").exists()

    first_deck = payload["decks"][0]
    assert first_deck["approved_count"] >= 1
    assert first_deck["questions"]
    first_question = first_deck["questions"][0]
    assert first_question["key"]
    assert first_question["question_kind"]
    assert "correct_text" in first_question
