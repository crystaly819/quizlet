from __future__ import annotations

from app.database import configure_database
from app.ingest_service import deck_count, ingest_pdf_directory
from app.render_boot import bootstrap_render_data


def test_bootstrap_render_data_ingests_when_database_is_empty(temp_settings) -> None:
    result = bootstrap_render_data(temp_settings)

    assert result.action == "ingested"
    assert result.deck_total == 1


def test_bootstrap_render_data_skips_when_decks_already_exist(temp_settings) -> None:
    configure_database(temp_settings.database_url)
    ingest_pdf_directory(temp_settings.pdf_dir, temp_settings, rebuild=True)

    result = bootstrap_render_data(temp_settings)

    assert result.action == "skipped_existing_data"
    assert result.deck_total == deck_count() == 1
