from __future__ import annotations

import os
from dataclasses import dataclass

import uvicorn

from .config import Settings
from .database import configure_database, init_db
from .ingest_service import deck_count, emit_progress, ingest_pdf_directory


@dataclass(frozen=True)
class BootstrapResult:
    action: str
    deck_total: int


def bootstrap_render_data(settings: Settings, *, force_rebuild: bool = False) -> BootstrapResult:
    settings.ensure_dirs()
    configure_database(settings.database_url)
    init_db()

    if not settings.pdf_dir.exists():
        emit_progress(f"[render] PDF directory '{settings.pdf_dir}' was not found; skipping ingest")
        return BootstrapResult(action="missing_pdf_dir", deck_total=deck_count())

    current_decks = deck_count()
    if current_decks > 0 and not force_rebuild:
        emit_progress(f"[render] Found {current_decks} existing deck(s); skipping ingest")
        return BootstrapResult(action="skipped_existing_data", deck_total=current_decks)

    emit_progress(
        "[render] Starting ingest before web server boot"
        + (" with rebuild" if force_rebuild else "")
    )
    ingest_pdf_directory(settings.pdf_dir, settings, rebuild=force_rebuild)
    final_decks = deck_count()
    emit_progress(f"[render] Ingest finished with {final_decks} deck(s)")
    return BootstrapResult(
        action="rebuilt" if force_rebuild and current_decks > 0 else "ingested",
        deck_total=final_decks,
    )


def main() -> None:
    settings = Settings.from_env()
    force_rebuild = os.getenv("QUIZLET_RENDER_FORCE_REBUILD", "0") == "1"
    port = int(os.getenv("PORT", "10000"))

    bootstrap_render_data(settings, force_rebuild=force_rebuild)
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
