from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


NOISE_CHARS = ("|", "¥", "—", "：", "@", "{", "}", "®")


def score_question(question: dict) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    stem = str(question.get("stem") or "")
    choices = [str(choice.get("text") or "") for choice in question.get("choices", [])]
    all_text = " ".join([stem] + choices)

    if any(char in stem for char in ("|", "¥", "—", "：")) or " @" in stem or "= " in stem or "}" in stem:
        score += 3
        reasons.append("stem_noise")

    if len(stem.strip()) < 12:
        score += 2
        reasons.append("short_stem")

    if sum(char in all_text for char in NOISE_CHARS) >= 2:
        score += 2
        reasons.append("symbol_noise")

    merged_choices = 0
    for choice in choices:
        if re.search(r"[①-⑤]\s", choice) or re.search(r"\([1-5]\)", choice) or re.search(r"\b[1-5]\)", choice):
            merged_choices += 1
    if merged_choices:
        score += 2 + merged_choices
        reasons.append(f"merged_choices:{merged_choices}")

    if choices and len(choices) < 4:
        score += 2
        reasons.append("few_choices")

    if any(len(choice.strip()) < 2 for choice in choices):
        score += 1
        reasons.append("tiny_choice")

    if re.search(r"[가-힣][A-Za-z]|[A-Za-z][가-힣]", stem):
        score += 1
        reasons.append("mixed_script_join")

    return score, reasons


def build_suspects(cache_path: Path, *, min_score: int = 4) -> dict:
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    suspects: list[dict] = []

    for question in payload.get("questions", []):
        score, reasons = score_question(question)
        if score < min_score:
            continue

        suspects.append(
            {
                "number": question.get("number"),
                "page_number": question.get("page_number"),
                "correct_index": question.get("correct_index"),
                "score": score,
                "reasons": reasons,
                "stem": question.get("stem"),
                "choices": [choice.get("text") for choice in question.get("choices", [])],
            }
        )

    suspects.sort(key=lambda item: (-item["score"], item["page_number"], item["number"]))
    return {
        "title": payload.get("title"),
        "source_pdf": payload.get("source_pdf"),
        "page_count": payload.get("page_count"),
        "question_count": len(payload.get("questions", [])),
        "suspect_count": len(suspects),
        "min_score": min_score,
        "suspects": suspects,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Find OCR review candidates from a cache JSON file.")
    parser.add_argument("cache_json", help="Path to a generated cache JSON file.")
    parser.add_argument("--min-score", type=int, default=4, help="Minimum suspicion score to include.")
    parser.add_argument("--output", help="Optional path to write the suspect JSON file.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cache_path = Path(args.cache_json)
    report = build_suspects(cache_path, min_score=args.min_score)

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = cache_path.with_suffix(".suspects.json")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output_path)
    print(f"suspects={report['suspect_count']}")


if __name__ == "__main__":
    main()
