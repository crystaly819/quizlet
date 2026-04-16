from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import func, select

from .config import Settings
from .database import configure_database, init_db, session_scope
from .models import Deck, ParseIssue, Question


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import a reviewed cache JSON deck into the app database.")
    parser.add_argument("cache_json", help="Path to cache JSON.")
    parser.add_argument("--source-pdf", required=True, help="Source PDF path to store on the deck, usually under pdfs/.")
    parser.add_argument("--overrides-json", help="Optional review override JSON keyed by question number.")
    return parser


def apply_override(question_payload: dict, override: dict) -> dict:
    updated = dict(question_payload)
    if "stem" in override:
        updated["stem"] = override["stem"]
    if "choices" in override:
        updated["choices"] = [
            {
                "index": index,
                "label": ["①", "②", "③", "④", "⑤"][index - 1] if 1 <= index <= 5 else str(index),
                "text": choice,
                "bbox": question_payload.get("bbox"),
                "label_bbox": question_payload.get("bbox"),
            }
            for index, choice in enumerate(override["choices"], start=1)
        ]
    if "question_kind" in override:
        updated["question_kind"] = override["question_kind"]
    if "correct_index" in override:
        updated["correct_index"] = override["correct_index"]
        updated["answer_text"] = None
    if "answer_text" in override:
        updated["answer_text"] = override["answer_text"]
        updated["correct_index"] = None
    updated["approved"] = True
    updated["issue_reason"] = None
    updated["confidence"] = max(float(updated.get("confidence", 0.0) or 0.0), 0.95)
    updated["manual_reviewed"] = True
    return updated


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings.from_env()
    settings.ensure_dirs()
    configure_database(settings.database_url)
    init_db()

    cache_path = Path(args.cache_json)
    cache_payload = load_json(cache_path)
    overrides = load_json(Path(args.overrides_json)) if args.overrides_json else {}
    source_pdf = args.source_pdf

    with session_scope() as session:
        existing = session.execute(select(Deck).where(Deck.source_pdf == source_pdf)).scalar_one_or_none()
        if existing is not None:
            session.delete(existing)
            session.flush()

        deck = Deck(
            title=cache_payload["title"],
            slug=cache_payload["slug"],
            source_pdf=source_pdf,
            page_count=int(cache_payload["page_count"]),
            question_count=0,
        )
        session.add(deck)
        session.flush()

        for item in cache_payload.get("questions", []):
            override = overrides.get(str(item.get("number")))
            payload = apply_override(item, override) if override else dict(item)
            question = Question(
                deck_id=deck.id,
                number=int(payload["number"]),
                page_number=int(payload["page_number"]),
                question_kind=str(payload.get("question_kind") or "multiple_choice"),
                stem=str(payload.get("stem") or "").strip(),
                answer_text=payload.get("answer_text"),
                explanation_text=payload.get("explanation_text"),
                correct_index=payload.get("correct_index"),
                confidence=float(payload.get("confidence", 0.0) or 0.0),
                source_bbox=json.dumps(payload.get("bbox") or []),
                crop_path=payload.get("crop_rel_path"),
                is_approved=bool(payload.get("approved", True)),
                manual_reviewed=bool(payload.get("manual_reviewed", False) or override),
            )
            question.set_choices([choice.get("text", "") for choice in payload.get("choices", [])])
            session.add(question)
            session.flush()

            issue_reason = payload.get("issue_reason")
            if issue_reason:
                session.add(
                    ParseIssue(
                        question_id=question.id,
                        reason=str(issue_reason),
                        payload_json=json.dumps(payload, ensure_ascii=False),
                        status="open",
                    )
                )

        deck.question_count = session.execute(
            select(func.count(Question.id)).where(Question.deck_id == deck.id)
        ).scalar_one()

    print(f"Imported '{cache_payload['title']}' with source_pdf='{source_pdf}'")


if __name__ == "__main__":
    main()
