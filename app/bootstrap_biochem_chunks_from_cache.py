from __future__ import annotations

import argparse
import json
from pathlib import Path

from .biochem_review import load_json
from .config import Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap biochemistry review chunks from the base OCR cache JSON.")
    parser.add_argument(
        "--base-cache",
        default="data/cache/1-325c78c1.json",
        help="Source OCR cache JSON.",
    )
    parser.add_argument(
        "--chunks-dir",
        default="data/review/biochem_chunks",
        help="Directory containing chunk review JSON files.",
    )
    parser.add_argument(
        "--include-completed",
        action="store_true",
        help="Also seed chunks already marked review_completed=true.",
    )
    return parser

def cache_choices_to_review_choices(item: dict) -> list[str]:
    choices = item.get("choices") or []
    return [str(choice.get("text") or "").strip() for choice in choices if str(choice.get("text") or "").strip()]


def cache_entry_to_review_question(item: dict) -> dict:
    question_kind = str(item.get("question_kind") or "multiple_choice")
    answer_text = item.get("answer_text")
    correct_index = item.get("correct_index")
    return {
        "question_number": int(item["number"]),
        "page_number": int(item["page_number"]),
        "question_kind": question_kind,
        "stem": str(item.get("stem") or "").strip(),
        "choices": cache_choices_to_review_choices(item),
        "correct_index": int(correct_index) if correct_index is not None else None,
        "answer_text": str(answer_text).strip() if isinstance(answer_text, str) and answer_text.strip() else None,
        "manual_reviewed": False,
    }


def update_chunk_questions(chunk_payload: dict, cache_questions: list[dict]) -> dict:
    chunk_payload.setdefault("review_completed", False)
    existing_keys = {
        (int(question["page_number"]), int(question["question_number"]))
        for question in chunk_payload.get("questions", [])
    }
    start = int(chunk_payload["page_range"]["start"])
    end = int(chunk_payload["page_range"]["end"])
    for item in cache_questions:
        page_number = int(item["page_number"])
        if page_number < start or page_number > end:
            continue
        question_key = (page_number, int(item["number"]))
        if question_key in existing_keys:
            continue
        chunk_payload.setdefault("questions", []).append(cache_entry_to_review_question(item))
        existing_keys.add(question_key)

    chunk_payload["questions"].sort(key=lambda question: (int(question["page_number"]), int(question["question_number"])))
    return chunk_payload


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings.from_env()
    base_cache = Path(args.base_cache)
    if not base_cache.is_absolute():
        base_cache = settings.base_dir / base_cache
    chunks_dir = Path(args.chunks_dir)
    if not chunks_dir.is_absolute():
        chunks_dir = settings.base_dir / chunks_dir

    cache_payload = load_json(base_cache)
    cache_questions = cache_payload.get("questions", [])
    updated_paths: list[Path] = []
    for review_path in sorted(chunks_dir.glob("*/review.json")):
        payload = load_json(review_path)
        if payload.get("review_completed") and not args.include_completed:
            continue
        updated = update_chunk_questions(payload, cache_questions)
        review_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
        if updated.get("questions"):
            updated_paths.append(review_path)

    for path in updated_paths:
        print(path)


if __name__ == "__main__":
    main()
