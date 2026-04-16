from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap biochemistry review chunks from NotebookLM JSON.")
    parser.add_argument(
        "--notebooklm-json",
        default="data/notebooklm/biochemistry_division_answers.json",
        help="Source NotebookLM question JSON.",
    )
    parser.add_argument(
        "--chunks-dir",
        default="data/review/biochem_chunks",
        help="Chunk review directory created by render_biochem_chunks.",
    )
    return parser


def choice_values(item: dict) -> list[str]:
    choices = item.get("choices", {})
    return [str(choices[str(index)]) for index in sorted(int(key) for key in choices.keys())]


def update_chunk_questions(chunk_payload: dict, notebooklm_items: list[dict]) -> dict:
    chunk_payload.setdefault("review_completed", False)
    existing_keys = {
        (int(question["page_number"]), int(question["question_number"]))
        for question in chunk_payload.get("questions", [])
    }
    start = int(chunk_payload["page_range"]["start"])
    end = int(chunk_payload["page_range"]["end"])
    for item in notebooklm_items:
        page_number = int(item["source_pages"]["question_page"])
        if page_number < start or page_number > end:
            continue
        question_number = int(item["question_number"])
        question_key = (page_number, question_number)
        if question_key in existing_keys:
            continue

        answer = str(item["answer"]).strip()
        question = {
            "question_number": question_number,
            "page_number": page_number,
            "question_kind": "multiple_choice",
            "stem": str(item["question_text"]).strip(),
            "choices": choice_values(item),
            "correct_index": int(answer) if answer.isdigit() else None,
            "answer_text": None if answer.isdigit() else answer,
            "manual_reviewed": True,
        }
        if not answer.isdigit():
            question["question_kind"] = "multi_select"
        chunk_payload.setdefault("questions", []).append(question)
        existing_keys.add(question_key)

    chunk_payload["questions"].sort(key=lambda question: (int(question["page_number"]), int(question["question_number"])))
    return chunk_payload


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings.from_env()
    notebooklm_path = Path(args.notebooklm_json)
    if not notebooklm_path.is_absolute():
        notebooklm_path = settings.base_dir / notebooklm_path
    chunks_dir = Path(args.chunks_dir)
    if not chunks_dir.is_absolute():
        chunks_dir = settings.base_dir / chunks_dir

    notebooklm_items = json.loads(notebooklm_path.read_text(encoding="utf-8"))
    updated_paths: list[Path] = []
    for review_path in sorted(chunks_dir.glob("*/review.json")):
        payload = json.loads(review_path.read_text(encoding="utf-8"))
        updated = update_chunk_questions(payload, notebooklm_items)
        review_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
        if updated.get("questions"):
            updated_paths.append(review_path)

    for path in updated_paths:
        print(path)


if __name__ == "__main__":
    main()
