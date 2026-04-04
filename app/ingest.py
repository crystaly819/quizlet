from __future__ import annotations

import argparse
from pathlib import Path

from .config import Settings
from .database import configure_database, init_db
from .ingest_service import ingest_pdf_directory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest PDF decks into the Quizlet app.")
    parser.add_argument("pdf_dir", nargs="?", default="pdfs", help="Directory that contains PDF files.")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild decks and runtime cache from scratch.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings.from_env()
    settings.ensure_dirs()
    configure_database(settings.database_url)
    init_db()

    pdf_dir = Path(args.pdf_dir)
    if not pdf_dir.is_absolute():
        pdf_dir = settings.base_dir / pdf_dir

    summaries = ingest_pdf_directory(pdf_dir=pdf_dir, settings=settings, rebuild=args.rebuild)
    for summary in summaries:
        print(
            f"{summary['title']}: {summary['question_count']} questions "
            f"({summary['approved_count']} approved, {summary['issue_count']} issues)"
        )


if __name__ == "__main__":
    main()
