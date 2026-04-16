from __future__ import annotations

import argparse
import json
from pathlib import Path

import fitz

from .config import Settings
from .parser import PAGE_NUMBER_RE, clamp_bbox, expand_bbox, ocr_page_rows, union_bboxes

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Enrich reviewed cache entries with source bbox values for preview crops.")
    parser.add_argument("--input-cache", required=True, help="Merged reviewed cache JSON to enrich.")
    parser.add_argument("--output-cache", help="Optional output path. Defaults to overwriting input cache.")
    parser.add_argument("--pdf", required=True, help="Source PDF path for OCR row detection.")
    parser.add_argument("--dpi", type=int, default=120, help="OCR dpi for row detection. Lower is faster.")
    parser.add_argument(
        "--mode",
        choices=("even", "ocr"),
        default="even",
        help="BBox strategy: even is fast and approximate, ocr is slower and uses page OCR rows.",
    )
    return parser


def filter_content_rows(rows, page: fitz.Page, *, scale: float):
    page_h = page.rect.height * scale
    footer_start = next((row.bbox[1] for row in rows if "정답" in row.text), None)
    filtered = []
    for row in rows:
        text = (row.text or "").strip()
        if not text:
            continue
        if PAGE_NUMBER_RE.match(text):
            continue
        if footer_start is not None and row.bbox[1] >= footer_start - 4.0:
            continue
        if row.bbox[1] < page_h * 0.12 or row.bbox[3] > page_h * 0.97:
            continue
        filtered.append(row)
    return filtered


def split_rows_into_question_groups(rows, question_count: int):
    if question_count <= 0:
        return []
    if not rows:
        return [[] for _ in range(question_count)]
    if question_count == 1:
        return [rows]

    if len(rows) < question_count:
        groups = [[row] for row in rows]
        groups.extend([[] for _ in range(question_count - len(rows))])
        return groups

    gaps = []
    for index in range(len(rows) - 1):
        gap = rows[index + 1].bbox[1] - rows[index].bbox[3]
        gaps.append((gap, index))

    split_after = {index for _, index in sorted(gaps, reverse=True)[: question_count - 1]}
    groups = []
    start = 0
    for index in range(len(rows) - 1):
        if index in split_after:
            groups.append(rows[start : index + 1])
            start = index + 1
    groups.append(rows[start:])

    if len(groups) != question_count or any(not group for group in groups):
        groups = []
        for group_index in range(question_count):
            start = round(group_index * len(rows) / question_count)
            end = round((group_index + 1) * len(rows) / question_count)
            groups.append(rows[start:end])
    return groups


def page_group_bbox(rows, page: fitz.Page, *, scale: float) -> list[float]:
    if not rows:
        return [0.0, 0.0, float(page.rect.width), float(page.rect.height)]
    pixel_bbox = union_bboxes(row.bbox for row in rows)
    page_bbox = tuple(value / scale for value in pixel_bbox)
    expanded = expand_bbox(page_bbox, 6.0)
    clamped = clamp_bbox(expanded, float(page.rect.width), float(page.rect.height))
    return [round(value, 2) for value in clamped]


def even_split_bboxes(page: fitz.Page, question_count: int) -> list[list[float]]:
    if question_count <= 0:
        return []
    width = float(page.rect.width)
    height = float(page.rect.height)
    top = height * 0.14
    bottom = height * 0.95
    left = width * 0.08
    right = width * 0.95
    segment = (bottom - top) / question_count
    boxes: list[list[float]] = []
    for index in range(question_count):
        y0 = top + segment * index
        y1 = top + segment * (index + 1)
        box = clamp_bbox((left, y0 - 4.0, right, y1 + 4.0), width, height)
        boxes.append([round(value, 2) for value in box])
    return boxes


def enrich_payload_with_bboxes(payload: dict, pdf_path: Path, *, dpi: int = 120, mode: str = "even") -> dict:
    enriched = dict(payload)
    questions = [dict(question) for question in payload.get("questions", [])]
    page_to_indices: dict[int, list[int]] = {}
    scale = dpi / 72.0
    for index, question in enumerate(questions):
        page_to_indices.setdefault(int(question["page_number"]), []).append(index)

    document = fitz.open(pdf_path)
    try:
        for order, (page_number, indices) in enumerate(sorted(page_to_indices.items()), start=1):
            page = document[page_number - 1]
            if mode == "ocr":
                rows = filter_content_rows(ocr_page_rows(page, dpi=dpi), page, scale=scale)
                groups = split_rows_into_question_groups(rows, len(indices))
                for question_index, group in zip(indices, groups):
                    questions[question_index]["bbox"] = page_group_bbox(group, page, scale=scale)
            else:
                for question_index, bbox in zip(indices, even_split_bboxes(page, len(indices))):
                    questions[question_index]["bbox"] = bbox
            if order % 10 == 0:
                print(f"processed {order}/{len(page_to_indices)} pages")
    finally:
        document.close()

    enriched["questions"] = questions
    return enriched


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings.from_env()

    input_cache = Path(args.input_cache)
    if not input_cache.is_absolute():
        input_cache = settings.base_dir / input_cache
    output_cache = Path(args.output_cache) if args.output_cache else input_cache
    if not output_cache.is_absolute():
        output_cache = settings.base_dir / output_cache
    pdf_path = Path(args.pdf)
    if not pdf_path.is_absolute():
        pdf_path = settings.base_dir / pdf_path

    payload = json.loads(input_cache.read_text(encoding="utf-8"))
    enriched = enrich_payload_with_bboxes(payload, pdf_path, dpi=args.dpi, mode=args.mode)
    output_cache.write_text(json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output_cache)


if __name__ == "__main__":
    main()
