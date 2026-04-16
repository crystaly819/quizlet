from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _default_base_dir() -> Path:
    return Path(__file__).resolve().parent.parent


@dataclass(slots=True)
class Settings:
    base_dir: Path
    data_dir: Path
    pdf_dir: Path
    database_url: str
    auto_ingest: bool = True
    interactive_pdf_select: bool = False
    testing: bool = False

    @property
    def template_dir(self) -> Path:
        return self.base_dir / "app" / "templates"

    @property
    def static_dir(self) -> Path:
        return self.base_dir / "app" / "static"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> "Settings":
        base_dir = _default_base_dir()
        data_dir = Path(os.getenv("QUIZLET_DATA_DIR", str(base_dir / "data")))
        pdf_dir = Path(os.getenv("QUIZLET_PDF_DIR", str(base_dir / "pdfs")))
        database_url = os.getenv(
            "QUIZLET_DATABASE_URL",
            f"sqlite:///{(data_dir / 'app.db').as_posix()}",
        )
        auto_ingest = os.getenv("QUIZLET_AUTO_INGEST", "1") != "0"
        interactive_pdf_select = os.getenv("QUIZLET_SELECT_PDFS", "0") == "1"
        testing = os.getenv("QUIZLET_TESTING", "0") == "1"
        return cls(
            base_dir=base_dir,
            data_dir=data_dir,
            pdf_dir=pdf_dir,
            database_url=database_url,
            auto_ingest=auto_ingest,
            interactive_pdf_select=interactive_pdf_select,
            testing=testing,
        )
