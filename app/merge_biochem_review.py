from __future__ import annotations

import argparse
import json
from pathlib import Path

from .biochem_review import BIOCHEM_SOURCE_PDF, load_json, question_to_cache_entry
from .config import Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Merge reviewed biochemistry chunks into a final cache JSON.")
    parser.add_argument("--base-cache", required=True, help="Existing cache JSON that provides 1-27p baseline.")
    parser.add_argument("--chunks-dir", default="data/review/biochem_chunks", help="Directory with chunk review JSON files.")
    parser.add_argument("--output", default="data/review/biochem_reviewed_cache.json", help="Merged cache output path.")
    parser.add_argument("--keep-through-page", type=int, default=27, help="Keep original parsed questions through this page.")
    parser.add_argument("--source-pdf", default=BIOCHEM_SOURCE_PDF, help="Canonical source PDF path for the merged deck.")
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Allow merging even if some chunk review.json files are not marked review_completed.",
    )
    parser.add_argument(
        "--retain-unreviewed",
        action="store_true",
        help="Retain base-cache questions beyond the reviewed set and overlay reviewed questions on top.",
    )
    parser.add_argument(
        "--manual-only",
        action="store_true",
        help="Only overlay questions where manual_reviewed=true.",
    )
    parser.add_argument(
        "--completed-only",
        action="store_true",
        help="Use only chunks marked review_completed=true and replace their page ranges in the base cache.",
    )
    parser.add_argument(
        "--preserve-base-metadata",
        action="store_true",
        help="Keep the base cache title and slug instead of appending [reviewed]/-reviewed.",
    )
    return parser


def validate_review_payload(payload: dict) -> None:
    if "page_range" not in payload or "questions" not in payload or "review_completed" not in payload:
        raise ValueError("review chunk must include page_range, review_completed, and questions")
    seen_question_keys: set[tuple[int, int]] = set()
    for question in payload["questions"]:
        required = {"question_number", "page_number", "question_kind", "stem", "choices", "manual_reviewed"}
        missing = required - set(question)
        if missing:
            raise ValueError(f"reviewed question is missing keys: {sorted(missing)}")
        number = int(question["question_number"])
        page_number = int(question["page_number"])
        question_key = (page_number, number)
        if question_key in seen_question_keys:
            raise ValueError(f"duplicate question key inside chunk: page={page_number} number={number}")
        seen_question_keys.add(question_key)

        kind = str(question["question_kind"])
        choices = [str(choice).strip() for choice in question.get("choices", []) if str(choice).strip()]
        if not str(question["stem"]).strip():
            raise ValueError(f"question {number} has empty stem")
        if kind == "multiple_choice":
            correct_index = question.get("correct_index")
            if correct_index is None:
                raise ValueError(f"question {number} is missing correct_index")
            if int(correct_index) < 1 or int(correct_index) > len(choices):
                raise ValueError(f"question {number} correct_index is out of range")
        elif kind == "multi_select":
            if not str(question.get("answer_text") or "").strip():
                raise ValueError(f"question {number} is missing answer_text")
        elif kind == "short_answer":
            if not str(question.get("answer_text") or "").strip():
                raise ValueError(f"question {number} is missing answer_text")
        else:
            raise ValueError(f"unsupported question_kind: {kind}")


def review_json_paths(chunks_dir: Path) -> list[Path]:
    return sorted(path for path in chunks_dir.glob("*/review.json") if path.is_file())


def ensure_chunk_completion(review_payloads: list[dict]) -> None:
    incomplete = [
        f"{payload['page_range']['start']}-{payload['page_range']['end']}"
        for payload in review_payloads
        if not bool(payload.get("review_completed"))
    ]
    if incomplete:
        raise ValueError(f"cannot merge incomplete review chunks: {', '.join(incomplete)}")


def merge_payloads(
    base_payload: dict,
    review_payloads: list[dict],
    *,
    keep_through_page: int,
    source_pdf: str,
    retain_unreviewed: bool = False,
    manual_only: bool = False,
    completed_only: bool = False,
    preserve_base_metadata: bool = False,
) -> dict:
    selected_payloads = [payload for payload in review_payloads if bool(payload.get("review_completed"))] if completed_only else review_payloads
    replaced_pages: set[int] = set()
    if retain_unreviewed and completed_only:
        for payload in selected_payloads:
            start = int(payload["page_range"]["start"])
            end = int(payload["page_range"]["end"])
            replaced_pages.update(range(start, end + 1))

    if retain_unreviewed and completed_only:
        retained = [
            question for question in base_payload.get("questions", []) if int(question["page_number"]) not in replaced_pages
        ]
    elif retain_unreviewed:
        retained = list(base_payload.get("questions", []))
    else:
        retained = [question for question in base_payload.get("questions", []) if int(question["page_number"]) <= keep_through_page]
    merged_questions = list(retained)
    seen_question_keys = {(int(question["page_number"]), int(question["number"])) for question in retained}
    merged_index_by_key = {
        (int(question["page_number"]), int(question["number"])): index for index, question in enumerate(merged_questions)
    }

    for payload in selected_payloads:
        validate_review_payload(payload)
        for question in payload["questions"]:
            if manual_only and not bool(question.get("manual_reviewed")):
                continue
            cache_entry = question_to_cache_entry(question)
            question_key = (int(cache_entry["page_number"]), int(cache_entry["number"]))
            if retain_unreviewed and not completed_only and question_key in merged_index_by_key:
                merged_questions[merged_index_by_key[question_key]] = cache_entry
                continue
            if question_key in seen_question_keys:
                raise ValueError(
                    f"duplicate question key across merged output: page={cache_entry['page_number']} number={cache_entry['number']}"
                )
            seen_question_keys.add(question_key)
            merged_index_by_key[question_key] = len(merged_questions)
            merged_questions.append(cache_entry)

    merged_questions.sort(key=lambda item: (int(item["number"]), int(item["page_number"])))
    return {
        "title": base_payload["title"] if preserve_base_metadata else f"{base_payload['title']} [reviewed]",
        "slug": base_payload["slug"] if preserve_base_metadata else f"{base_payload['slug']}-reviewed",
        "source_pdf": source_pdf,
        "page_count": int(base_payload["page_count"]),
        "questions": merged_questions,
    }


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings.from_env()
    base_cache = Path(args.base_cache)
    if not base_cache.is_absolute():
        base_cache = settings.base_dir / base_cache
    chunks_dir = Path(args.chunks_dir)
    if not chunks_dir.is_absolute():
        chunks_dir = settings.base_dir / chunks_dir
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = settings.base_dir / output_path

    base_payload = load_json(base_cache)
    chunk_payloads: list[dict] = []
    for path in review_json_paths(chunks_dir):
        payload = load_json(path)
        chunk_payloads.append(payload)
    if not args.allow_incomplete:
        ensure_chunk_completion(chunk_payloads)
    chunk_payloads = [payload for payload in chunk_payloads if payload.get("questions")]
    merged = merge_payloads(
        base_payload,
        chunk_payloads,
        keep_through_page=args.keep_through_page,
        source_pdf=args.source_pdf,
        retain_unreviewed=args.retain_unreviewed,
        manual_only=args.manual_only,
        completed_only=args.completed_only,
        preserve_base_metadata=args.preserve_base_metadata,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
