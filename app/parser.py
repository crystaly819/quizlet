from __future__ import annotations

import hashlib
import io
import json
import re
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

import fitz

try:
    from kiwipiepy import Kiwi
except ImportError:  # pragma: no cover - optional dependency for spacing recovery
    Kiwi = None


QUESTION_RE = re.compile(r"^(\d+)\.\s*(.*)$")
OPTION_RE = re.compile(r"^([①②③④⑤])\s*(.*)$")
PAGE_NUMBER_RE = re.compile(r"^-\s*\d+\s*-$")
TRUE_FALSE_RE = re.compile(r"^\((O|X)\)\s*(.*)$", re.IGNORECASE)
OPTION_INDEX = {"①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5}
CIRCLED_LABELS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
CIRCLED_LABEL_TO_INDEX = {label: index for index, label in enumerate(CIRCLED_LABELS, start=1)}
INDEX_TO_CIRCLED_LABEL = {index: label for label, index in CIRCLED_LABEL_TO_INDEX.items()}
SUBQUESTION_RE = re.compile(r"^\((\d+)\)\s*(.*)$")
HANGUL_RE = re.compile(r"[가-힣]")
PHARMA_SPACING_TERMS = (
    "수용성좌제기제",
    "글리세로젤라틴제",
    "세틸에스터왁스",
    "폴리에틸렌글리콜",
    "글리세로젤라틴",
    "카타플라스마제",
    "소염진통습포",
    "반고형제제",
    "하이드로겔",
    "오르가노겔",
    "카카오지",
    "좌제기제",
    "유기용매",
    "경화제",
    "페이스트제",
    "글리세린",
    "삼출물",
    "단일상",
    "젤라틴",
    "겔화제",
    "겔제",
    "융점",
    "국소",
    "밀납",
)
_KIWI: Kiwi | bool | None = None


@dataclass(slots=True)
class CharData:
    value: str
    bbox: tuple[float, float, float, float]


@dataclass(slots=True)
class LineData:
    text: str
    bbox: tuple[float, float, float, float]
    page_number: int
    direction: tuple[float, float]
    color: tuple[float, float, float]
    chars: list[CharData] = field(default_factory=list)


@dataclass(slots=True)
class ChoiceData:
    index: int
    label: str
    label_bbox: tuple[float, float, float, float]
    lines: list[str] = field(default_factory=list)
    bboxes: list[tuple[float, float, float, float]] = field(default_factory=list)

    @property
    def text(self) -> str:
        return assemble_text_fragments(self.lines)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return union_bboxes(self.bboxes or [self.label_bbox])


@dataclass(slots=True)
class RowData:
    text: str
    bbox: tuple[float, float, float, float]


@dataclass(slots=True)
class ParsedQuestion:
    number: int
    page_number: int
    question_kind: str
    stem: str
    answer_text: str | None
    explanation_text: str | None
    choices: list[ChoiceData]
    bbox: tuple[float, float, float, float]
    correct_index: int | None
    confidence: float
    approved: bool
    issue_reason: str | None
    payload: dict
    crop_rel_path: str | None = None


@dataclass(slots=True)
class PageSnapshot:
    page_number: int
    width: float
    height: float
    lines: list[LineData]
    yellow_rects: list[tuple[float, float, float, float]]


@dataclass(slots=True)
class DocumentParseResult:
    title: str
    slug: str
    source_pdf: str
    page_count: int
    questions: list[ParsedQuestion]
    cache_rel_path: str


@dataclass(slots=True)
class WorkingQuestion:
    number: int
    page_number: int
    stem_lines: list[str] = field(default_factory=list)
    stem_bboxes: list[tuple[float, float, float, float]] = field(default_factory=list)
    choices: dict[int, ChoiceData] = field(default_factory=dict)

    def append_stem(self, line: LineData, text: str | None = None) -> None:
        value = line.text if text is None else text
        if value:
            self.stem_lines.append(value)
        self.stem_bboxes.append(line.bbox)

    def append_choice(self, line: LineData) -> None:
        if not self.choices:
            self.append_stem(line)
            return

        last_index = sorted(self.choices)[-1]
        choice = self.choices[last_index]
        choice.lines.append(line.text)
        choice.bboxes.append(line.bbox)


def rgb_from_int(color_value: int | None) -> tuple[float, float, float]:
    if color_value is None:
        return (0.0, 0.0, 0.0)
    red = ((color_value >> 16) & 0xFF) / 255.0
    green = ((color_value >> 8) & 0xFF) / 255.0
    blue = (color_value & 0xFF) / 255.0
    return (red, green, blue)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def compact_text(value: str) -> str:
    return re.sub(r"\s+", "", value).strip()


def get_kiwi() -> Kiwi | None:
    global _KIWI
    if _KIWI is False:
        return None
    if _KIWI is not None:
        return _KIWI
    if Kiwi is None:
        _KIWI = False
        return None

    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        kiwi = Kiwi()
        for term in PHARMA_SPACING_TERMS:
            kiwi.add_user_word(term, "NNP", 0.0)
    _KIWI = kiwi
    return kiwi


def should_restore_spacing(text: str) -> bool:
    stripped = text.strip()
    if not stripped or not HANGUL_RE.search(stripped):
        return False
    hangul_count = len(HANGUL_RE.findall(stripped))
    if hangul_count < 4:
        return False
    return stripped.count(" ") == 0 or stripped.count(" ") / hangul_count < 0.04


def restore_korean_spacing(text: str) -> str:
    if not should_restore_spacing(text):
        return text.strip()

    kiwi = get_kiwi()
    if kiwi is None:
        return text.strip()

    restored_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            restored_lines.append(kiwi.space(line, reset_whitespace=False))
    return "\n".join(restored_lines)


def normalize_flashcard_parts(parts: list[str]) -> list[str]:
    normalized: list[str] = []
    for part in parts:
        cleaned = normalize_text(part)
        if not cleaned:
            continue
        if is_trivial_fragment(cleaned):
            normalized.append(cleaned)
            continue
        normalized.append(restore_korean_spacing(cleaned))
    return normalized


def split_compound_terms(text: str) -> list[str] | None:
    source = compact_text(text)
    if not source:
        return None

    ordered_terms = sorted(PHARMA_SPACING_TERMS, key=len, reverse=True)
    tokens: list[str] = []
    cursor = 0
    while cursor < len(source):
        matched = next((term for term in ordered_terms if source.startswith(term, cursor)), None)
        if matched is None:
            return None
        tokens.append(matched)
        cursor += len(matched)
    return tokens if len(tokens) >= 2 else None


def normalize_short_answer_text(text: str | None) -> str | None:
    if text is None:
        return None

    stripped = text.strip()
    if not stripped:
        return None

    trailing_comma = stripped.endswith(",")
    base = stripped.rstrip(",").strip()
    tokens = split_compound_terms(base)
    if tokens:
        return ", ".join(tokens)

    restored = restore_korean_spacing(stripped).rstrip(",").strip()
    return restored or None


def is_fragment_punctuation(text: str) -> bool:
    return bool(re.fullmatch(r"[\)\]\}\>\.,\?!:;]+", text))


def is_list_marker_start(text: str) -> bool:
    compact = compact_text(text)
    if compact in {"가", "나", "다", "라", "마", "바", "사", "아", "자"}:
        return True
    if compact.startswith(("가)", "나)", "다)", "라)", "마)", "바)", "사)", "아)", "자)")):
        return True
    if compact.startswith(("㉠", "㉡", "㉢", "㉣", "㉤", "㉥", "㉦", "㉧")):
        return True
    return False


def join_separator(previous: str, current: str) -> str:
    if not previous:
        return ""
    if current and current[0] in ",.?!:;%)]}>":
        return ""
    if previous[-1] in "([{<":
        return ""
    if previous.endswith(")") and len(compact_text(previous)) <= 3:
        return " "
    if previous[-1] not in ",.?!:;" and current.startswith(
        ("은", "는", "이", "가", "을", "를", "와", "과", "의", "에", "도", "만", "까지", "부터", "보다", "으로", "로", "이라", "이며", "인데")
    ):
        return ""
    if " " in previous or " " in current:
        return " "
    prev_last = previous[-1]
    current_first = current[0]
    if prev_last.isascii() and current_first.isascii():
        return " "
    if not prev_last.isascii() and current_first.isascii():
        return " "
    if prev_last.isascii() and not current_first.isascii():
        if current.startswith(("에", "의", "은", "는", "이", "가", "을", "를", "와", "과", "로", "으로", "도", "만", "까지", "부터", "보다")):
            return ""
        return " "
    return ""


def assemble_text_fragments(parts: list[str]) -> str:
    logical_lines: list[str] = []

    for raw_part in parts:
        text = normalize_text(raw_part)
        if not text:
            continue

        if logical_lines and text == ")":
            logical_lines[-1] += text
            continue

        if logical_lines and is_fragment_punctuation(text):
            logical_lines[-1] += text
            continue

        if is_list_marker_start(text):
            logical_lines.append(text)
            continue

        if not logical_lines:
            logical_lines.append(text)
            continue

        separator = join_separator(logical_lines[-1], text)
        logical_lines[-1] += f"{separator}{text}"

    return "\n".join(line.strip() for line in logical_lines if line.strip())


def transform_point(matrix: fitz.Matrix, x: float, y: float) -> tuple[float, float]:
    return (
        matrix.a * x + matrix.c * y + matrix.e,
        matrix.b * x + matrix.d * y + matrix.f,
    )


def transform_bbox(
    bbox: tuple[float, float, float, float],
    matrix: fitz.Matrix,
) -> tuple[float, float, float, float]:
    points = [
        transform_point(matrix, bbox[0], bbox[1]),
        transform_point(matrix, bbox[2], bbox[1]),
        transform_point(matrix, bbox[0], bbox[3]),
        transform_point(matrix, bbox[2], bbox[3]),
    ]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs), min(ys), max(xs), max(ys))


def transform_direction(direction: tuple[float, float], rotation: int) -> tuple[float, float]:
    dx, dy = direction
    normalized_rotation = rotation % 360
    if normalized_rotation == 90:
        return (-dy, dx)
    if normalized_rotation == 180:
        return (-dx, -dy)
    if normalized_rotation == 270:
        return (dy, -dx)
    return (dx, dy)


def union_bboxes(bboxes: Iterable[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    bbox_list = list(bboxes)
    x0 = min(bbox[0] for bbox in bbox_list)
    y0 = min(bbox[1] for bbox in bbox_list)
    x1 = max(bbox[2] for bbox in bbox_list)
    y1 = max(bbox[3] for bbox in bbox_list)
    return (x0, y0, x1, y1)


def expand_bbox(bbox: tuple[float, float, float, float], margin: float) -> tuple[float, float, float, float]:
    return (bbox[0] - margin, bbox[1] - margin, bbox[2] + margin, bbox[3] + margin)


def clamp_bbox(
    bbox: tuple[float, float, float, float],
    width: float,
    height: float,
) -> tuple[float, float, float, float]:
    return (
        max(0.0, bbox[0]),
        max(0.0, bbox[1]),
        min(width, bbox[2]),
        min(height, bbox[3]),
    )


def bbox_intersection_area(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    x0 = max(left[0], right[0])
    y0 = max(left[1], right[1])
    x1 = min(left[2], right[2])
    y1 = min(left[3], right[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return (x1 - x0) * (y1 - y0)


def bbox_distance(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    dx = max(left[0] - right[2], right[0] - left[2], 0.0)
    dy = max(left[1] - right[3], right[1] - left[3], 0.0)
    return (dx * dx + dy * dy) ** 0.5


def is_gray(color: tuple[float, float, float]) -> bool:
    spread = max(color) - min(color)
    average = sum(color) / 3
    return spread < 0.08 and 0.2 < average < 0.9


def is_answer_highlight(fill: tuple[float, float, float] | None) -> bool:
    if fill is None:
        return False
    red, green, blue = fill
    yellow_like = red >= 0.9 and green >= 0.85 and blue <= 0.35
    pink_like = red >= 0.88 and blue >= 0.72 and green >= 0.5 and green <= 0.88 and red >= green
    return yellow_like or pink_like


def safe_slug(name: str) -> str:
    prefix = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    prefix = prefix[:40] or "deck"
    suffix = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}-{suffix}"


def extract_lines(page: fitz.Page) -> list[LineData]:
    raw = page.get_text("rawdict")
    extracted: list[LineData] = []
    matrix = page.rotation_matrix
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text_parts: list[str] = []
            chars: list[CharData] = []
            first_color: tuple[float, float, float] | None = None
            for span in line.get("spans", []):
                if first_color is None:
                    first_color = rgb_from_int(span.get("color"))
                for char in span.get("chars", []):
                    value = char.get("c", "")
                    text_parts.append(value)
                    chars.append(CharData(value=value, bbox=transform_bbox(tuple(char["bbox"]), matrix)))
            text = normalize_text("".join(text_parts))
            if not text:
                continue
            extracted.append(
                LineData(
                    text=text,
                    bbox=transform_bbox(tuple(line["bbox"]), matrix),
                    page_number=page.number + 1,
                    direction=transform_direction(tuple(line.get("dir", (1.0, 0.0))), page.rotation),
                    color=first_color or (0.0, 0.0, 0.0),
                    chars=chars,
                )
            )
    return extracted


def clean_explanation(parts: list[str]) -> str | None:
    if not parts:
        return None
    joined = assemble_text_fragments(parts)
    if not joined:
        return None
    joined = re.sub(r"^\[+", "", joined)
    joined = re.sub(r"\]+$", "", joined)
    return joined.strip() or None


def is_question_label(text: str) -> bool:
    return bool(QUESTION_RE.match(text))


def is_trivial_fragment(text: str) -> bool:
    compact = compact_text(text)
    return not compact or compact in {".", ",", "(", ")", "[", "]", "?", ":", ";", "-", "'", '"', "‘", "’", "“", "”"}


def choice_label_for_index(index: int) -> str:
    return INDEX_TO_CIRCLED_LABEL.get(index, str(index))


def extract_choice_indices_from_text(text: str | None) -> list[int]:
    if not text:
        return []
    seen: list[int] = []
    for character in text:
        index = CIRCLED_LABEL_TO_INDEX.get(character)
        if index is None or index in seen:
            continue
        seen.append(index)
    return seen


def merge_lines_into_rows(lines: list[LineData], y_tolerance: float = 4.0) -> list[RowData]:
    if not lines:
        return []

    ordered = sorted(lines, key=lambda item: (round(item.bbox[1], 1), item.bbox[0]))
    grouped: list[list[LineData]] = []

    for line in ordered:
        if not grouped:
            grouped.append([line])
            continue
        last_group = grouped[-1]
        last_y = sum((item.bbox[1] + item.bbox[3]) / 2 for item in last_group) / len(last_group)
        current_y = (line.bbox[1] + line.bbox[3]) / 2
        if abs(current_y - last_y) <= y_tolerance:
            last_group.append(line)
        else:
            grouped.append([line])

    rows: list[RowData] = []
    for group in grouped:
        group.sort(key=lambda item: item.bbox[0])
        text = "".join(item.text for item in group).strip()
        if not text:
            continue
        rows.append(RowData(text=text, bbox=union_bboxes([item.bbox for item in group])))
    return rows


def row_starts_subquestion(text: str) -> bool:
    return bool(SUBQUESTION_RE.match(compact_text(text)))


def row_is_answer_marker(text: str) -> bool:
    compact = compact_text(text)
    return compact.startswith("<") and ">" in compact and bool(extract_choice_indices_from_text(compact))


def row_is_choice_only_answer(text: str) -> bool:
    if not extract_choice_indices_from_text(text):
        return False
    stripped = text
    for label in CIRCLED_LABELS:
        stripped = stripped.replace(label, "")
    stripped = re.sub(r"[\s,<>.\-:;'\"]+", "", stripped)
    stripped = stripped.replace("‘", "").replace("’", "").replace("“", "").replace("”", "")
    return not stripped


def parse_choice_segments(text: str) -> list[tuple[int, str]]:
    matches = list(re.finditer(f"[{re.escape(CIRCLED_LABELS)}]", text))
    parsed: list[tuple[int, str]] = []
    for offset, match in enumerate(matches):
        label = match.group(0)
        next_start = matches[offset + 1].start() if offset + 1 < len(matches) else len(text)
        content = text[match.end() : next_start].strip(" ,·")
        index = CIRCLED_LABEL_TO_INDEX.get(label)
        if index is None:
            continue
        parsed.append((index, content))
    return parsed


def extract_yellow_rects(page: fitz.Page) -> list[tuple[float, float, float, float]]:
    rects: list[tuple[float, float, float, float]] = []
    matrix = page.rotation_matrix
    for drawing in page.get_drawings():
        fill = drawing.get("fill")
        rect = drawing.get("rect")
        if rect is None or not is_answer_highlight(fill):
            continue
        bbox = transform_bbox((rect.x0, rect.y0, rect.x1, rect.y1), matrix)
        if bbox_intersection_area(bbox, bbox) < 20:
            continue
        rects.append(bbox)
    return rects


def repeated_texts(pages: list[PageSnapshot]) -> set[str]:
    counter: Counter[str] = Counter()
    for snapshot in pages:
        for line in snapshot.lines:
            counter[line.text] += 1
    return {text for text, count in counter.items() if count >= 3}


def filter_page_lines(snapshot: PageSnapshot, repeats: set[str]) -> list[LineData]:
    filtered: list[LineData] = []
    for line in snapshot.lines:
        x0, y0, x1, y1 = line.bbox
        x_center = (x0 + x1) / 2

        horizontal = abs(line.direction[0]) > 0.9 and abs(line.direction[1]) < 0.15
        vertical = abs(line.direction[1]) > 0.9 and abs(line.direction[0]) < 0.15
        if not horizontal and not vertical:
            continue
        if is_question_label(line.text):
            filtered.append(line)
            continue
        if PAGE_NUMBER_RE.match(line.text):
            continue
        if line.text in repeats and (y0 < snapshot.height * 0.12 or y1 > snapshot.height * 0.88):
            continue
        if line.text in repeats and is_gray(line.color) and snapshot.width * 0.25 < x_center < snapshot.width * 0.75:
            continue
        filtered.append(line)

    filtered.sort(key=lambda item: (round(item.bbox[1], 1), item.bbox[0]))
    return filtered


def find_label_bbox(line: LineData, label: str) -> tuple[float, float, float, float]:
    matches = [char.bbox for char in line.chars if char.value == label]
    if matches:
        return union_bboxes(matches)
    return line.bbox


def match_highlights(
    yellow_rects: list[tuple[float, float, float, float]],
    choices: list[ChoiceData],
) -> tuple[int | None, list[int], list[dict]]:
    matches: list[int] = []
    debug_rows: list[dict] = []

    for rect in yellow_rects:
        best_index: int | None = None
        best_score: float | None = None

        for choice in choices:
            probe = expand_bbox(choice.label_bbox, 3.0)
            overlap = bbox_intersection_area(rect, probe)
            distance = bbox_distance(rect, probe)
            if overlap <= 0 and distance > 8.0:
                continue
            score = (overlap * 10.0) - distance
            if best_score is None or score > best_score:
                best_score = score
                best_index = choice.index

        debug_rows.append({"rect": rect, "matched_choice": best_index})
        if best_index is not None:
            matches.append(best_index)

    unique_matches = sorted(set(matches))
    if len(unique_matches) == 1:
        return unique_matches[0], unique_matches, debug_rows
    return None, unique_matches, debug_rows


def finalize_question(
    current: WorkingQuestion,
    snapshot: PageSnapshot,
) -> ParsedQuestion:
    choices = [current.choices[index] for index in sorted(current.choices)]
    all_bboxes = list(current.stem_bboxes) + [choice.bbox for choice in choices]
    bbox = clamp_bbox(expand_bbox(union_bboxes(all_bboxes), 8.0), snapshot.width, snapshot.height)
    stem = assemble_text_fragments(current.stem_lines)

    issue_reasons: list[str] = []
    if len(choices) < 2:
        issue_reasons.append("missing_choices")

    correct_index, unique_matches, debug_rows = match_highlights(snapshot.yellow_rects, choices)
    if correct_index is None:
        issue_reasons.append("ambiguous_highlight")

    approved = not issue_reasons and correct_index is not None
    confidence = 1.0 if approved else 0.35 if correct_index is not None else 0.0

    payload = {
        "number": current.number,
        "page_number": current.page_number,
        "stem": stem,
        "choices": [
            {
                "index": choice.index,
                "label": choice.label,
                "text": choice.text,
                "bbox": choice.bbox,
                "label_bbox": choice.label_bbox,
            }
            for choice in choices
        ],
        "highlight_matches": debug_rows,
        "unique_matches": unique_matches,
    }

    return ParsedQuestion(
        number=current.number,
        page_number=current.page_number,
        question_kind="multiple_choice",
        stem=stem,
        answer_text=None,
        explanation_text=None,
        choices=choices,
        bbox=bbox,
        correct_index=correct_index,
        confidence=confidence,
        approved=approved,
        issue_reason=", ".join(issue_reasons) if issue_reasons else None,
        payload=payload,
    )


def parse_questions_from_lines(
    lines: list[LineData],
    snapshot: PageSnapshot,
) -> list[ParsedQuestion]:
    questions: list[ParsedQuestion] = []
    current: WorkingQuestion | None = None

    for line in lines:
        question_match = QUESTION_RE.match(line.text)
        if question_match:
            if current is not None:
                questions.append(finalize_question(current, snapshot))
            current = WorkingQuestion(number=int(question_match.group(1)), page_number=snapshot.page_number)
            current.append_stem(line, question_match.group(2).strip())
            continue

        if current is None:
            continue

        option_match = OPTION_RE.match(line.text)
        if option_match:
            label = option_match.group(1)
            index = OPTION_INDEX[label]
            choice = current.choices.get(index)
            if choice is None:
                choice = ChoiceData(
                    index=index,
                    label=label,
                    label_bbox=find_label_bbox(line, label),
                )
                current.choices[index] = choice
            content = option_match.group(2).strip()
            if content:
                choice.lines.append(content)
            choice.bboxes.append(line.bbox)
            continue

        if current.choices:
            current.append_choice(line)
        else:
            current.append_stem(line)

    if current is not None:
        questions.append(finalize_question(current, snapshot))

    return questions


def split_into_regions(
    lines: list[LineData],
    snapshot: PageSnapshot,
) -> list[tuple[list[LineData], list[tuple[float, float, float, float]]]]:
    question_lines = [line for line in lines if QUESTION_RE.match(line.text)]
    if len(question_lines) < 2:
        return [(lines, snapshot.yellow_rects)]

    left_starts = [line.bbox[0] for line in question_lines if line.bbox[0] < snapshot.width * 0.45]
    right_starts = [line.bbox[0] for line in question_lines if line.bbox[0] > snapshot.width * 0.55]
    if not left_starts or not right_starts:
        return [(lines, snapshot.yellow_rects)]

    split_x = (max(left_starts) + min(right_starts)) / 2
    left_lines = [line for line in lines if (line.bbox[0] + line.bbox[2]) / 2 < split_x]
    right_lines = [line for line in lines if (line.bbox[0] + line.bbox[2]) / 2 >= split_x]
    left_rects = [rect for rect in snapshot.yellow_rects if (rect[0] + rect[2]) / 2 < split_x]
    right_rects = [rect for rect in snapshot.yellow_rects if (rect[0] + rect[2]) / 2 >= split_x]
    return [(left_lines, left_rects), (right_lines, right_rects)]


def block_has_r_structure(rows: list[RowData]) -> bool:
    return any(row_starts_subquestion(row.text) for row in rows) and any(
        row_is_answer_marker(row.text) for row in rows
    )


def parse_r_question_block(rows: list[RowData], snapshot: PageSnapshot) -> list[ParsedQuestion]:
    if not rows:
        return []

    header_match = QUESTION_RE.match(rows[0].text)
    if header_match is None:
        return []

    parent_number = int(header_match.group(1))
    intro_parts = [header_match.group(2).strip()] if header_match.group(2).strip() else []
    intro_bboxes = [rows[0].bbox]

    option_rows: list[RowData] = []
    option_map: dict[int, ChoiceData] = {}
    parsed: list[ParsedQuestion] = []
    current_subquestion: dict | None = None

    def finalize_subquestion() -> None:
        nonlocal current_subquestion
        if current_subquestion is None:
            return

        prompt = assemble_text_fragments(
            [part for part in current_subquestion["prompt_parts"] if part and not is_trivial_fragment(part)]
        ).strip().strip("'\"“”‘’")
        answer_indices: list[int] = current_subquestion["answer_indices"]
        choices = [option_map[index] for index in sorted(option_map)]
        visible_bboxes = intro_bboxes + [row.bbox for row in option_rows] + current_subquestion["prompt_bboxes"]

        issues: list[str] = []
        if not prompt:
            issues.append("missing_stem")
        if not choices:
            issues.append("missing_choices")
        if not answer_indices:
            issues.append("missing_answer")
        if answer_indices and any(index not in option_map for index in answer_indices):
            issues.append("invalid_answer_choice")

        intro_text = assemble_text_fragments([part for part in intro_parts if part]).strip()
        stem = "\n\n".join(
            part
            for part in [
                intro_text,
                f"({current_subquestion['sub_number']}) {prompt}" if prompt else None,
            ]
            if part
        )

        parsed.append(
            ParsedQuestion(
                number=parent_number,
                page_number=snapshot.page_number,
                question_kind="multi_select",
                stem=stem,
                answer_text=", ".join(choice_label_for_index(index) for index in answer_indices) or None,
                explanation_text=None,
                choices=choices,
                bbox=clamp_bbox(expand_bbox(union_bboxes(visible_bboxes), 8.0), snapshot.width, snapshot.height),
                correct_index=None,
                confidence=1.0 if not issues else 0.0,
                approved=not issues,
                issue_reason=", ".join(issues) if issues else None,
                payload={
                    "number": parent_number,
                    "page_number": snapshot.page_number,
                    "question_kind": "multi_select",
                    "sub_number": current_subquestion["sub_number"],
                    "stem": stem,
                    "answer_text": ", ".join(choice_label_for_index(index) for index in answer_indices) or None,
                    "answer_indices": answer_indices,
                    "choices": [
                        {
                            "index": choice.index,
                            "label": choice.label,
                            "text": choice.text,
                        }
                        for choice in choices
                    ],
                },
            )
        )
        current_subquestion = None

    for row in rows[1:]:
        text = row.text.strip()
        if not text or text in {"[R형문제]", "[R", "형문제]"}:
            continue

        if row_starts_subquestion(text):
            finalize_subquestion()
            sub_match = SUBQUESTION_RE.match(compact_text(text))
            assert sub_match is not None
            current_subquestion = {
                "sub_number": int(sub_match.group(1)),
                "prompt_parts": [sub_match.group(2).strip()] if sub_match.group(2).strip() else [],
                "prompt_bboxes": [row.bbox],
                "answer_indices": [],
            }
            continue

        if row_is_answer_marker(text) or (current_subquestion is not None and row_is_choice_only_answer(text)):
            if current_subquestion is not None:
                current_subquestion["answer_indices"] = extract_choice_indices_from_text(text)
            continue

        segments = parse_choice_segments(text)
        if current_subquestion is None and segments:
            option_rows.append(row)
            for index, content in segments:
                if index not in option_map:
                    option_map[index] = ChoiceData(
                        index=index,
                        label=choice_label_for_index(index),
                        label_bbox=row.bbox,
                    )
                if content:
                    option_map[index].lines.append(content)
                option_map[index].bboxes.append(row.bbox)
            continue

        if current_subquestion is None:
            if not is_trivial_fragment(text):
                intro_parts.append(text)
                intro_bboxes.append(row.bbox)
            continue

        if not is_trivial_fragment(text):
            current_subquestion["prompt_parts"].append(text)
            current_subquestion["prompt_bboxes"].append(row.bbox)

    finalize_subquestion()
    return parsed


def parse_r_questions_from_regions(
    regions: list[tuple[list[LineData], list[tuple[float, float, float, float]]]],
    snapshot: PageSnapshot,
) -> tuple[set[int], list[ParsedQuestion]]:
    rows: list[RowData] = []
    for region_lines, _ in regions:
        rows.extend(merge_lines_into_rows(region_lines))

    if not block_has_r_structure(rows):
        return set(), []

    blocks: list[list[RowData]] = []
    current_block: list[RowData] = []
    for row in rows:
        if QUESTION_RE.match(row.text):
            if current_block:
                blocks.append(current_block)
            current_block = [row]
            continue
        if current_block:
            current_block.append(row)
    if current_block:
        blocks.append(current_block)

    handled_numbers: set[int] = set()
    parsed_questions: list[ParsedQuestion] = []
    for block in blocks:
        if not block_has_r_structure(block):
            continue
        block_questions = parse_r_question_block(block, snapshot)
        if not block_questions:
            continue
        handled_numbers.add(block_questions[0].number)
        parsed_questions.extend(block_questions)

    return handled_numbers, parsed_questions


def parse_flashcards_from_lines(
    lines: list[LineData],
    snapshot: PageSnapshot,
) -> list[ParsedQuestion]:
    start_positions = [(index, QUESTION_RE.match(line.text)) for index, line in enumerate(lines) if QUESTION_RE.match(line.text)]
    if not start_positions:
        return []

    split_x = snapshot.width * 0.5
    parsed: list[ParsedQuestion] = []

    for offset, match in start_positions:
        assert match is not None
        next_offset = next((index for index, _ in start_positions if index > offset), len(lines))
        block = lines[offset:next_offset]
        bboxes = [line.bbox for line in block]
        stem_parts: list[str] = []
        answer_parts: list[str] = []

        remainder = match.group(2).strip()
        if remainder:
            stem_parts.append(remainder)

        for line in block[1:]:
            center_x = (line.bbox[0] + line.bbox[2]) / 2
            if center_x >= split_x:
                answer_parts.append(line.text)
            else:
                stem_parts.append(line.text)

        stem = assemble_text_fragments(normalize_flashcard_parts(stem_parts))
        answer_parts = [part for part in answer_parts if part]
        answer_text: str | None = None
        explanation_text: str | None = None
        question_kind = "short_answer"

        if answer_parts:
            marker_index = next(
                (index for index, part in enumerate(answer_parts) if TRUE_FALSE_RE.match(part)),
                None,
            )
            if marker_index is not None:
                marker_match = TRUE_FALSE_RE.match(answer_parts[marker_index])
                assert marker_match is not None
                question_kind = "true_false"
                answer_text = marker_match.group(1).upper()
                explanation_parts: list[str] = []
                explanation_parts.extend(
                    part for part in answer_parts[:marker_index] if not is_trivial_fragment(part)
                )
                first_explanation = marker_match.group(2).strip()
                if first_explanation:
                    explanation_parts.append(first_explanation)
                explanation_parts.extend(answer_parts[marker_index + 1 :])
                explanation_text = clean_explanation(normalize_flashcard_parts(explanation_parts))
            else:
                answer_lines: list[str] = []
                explanation_parts = []
                explanation_started = False
                for part in answer_parts:
                    clean_part = part.strip()
                    if not clean_part:
                        continue
                    if explanation_started:
                        explanation_parts.append(clean_part)
                        continue
                    if "[" in clean_part:
                        before_bracket, _, after_bracket = clean_part.partition("[")
                        if before_bracket.strip():
                            answer_lines.append(before_bracket.strip())
                        explanation_started = True
                        explanation_parts.append("[" + after_bracket if after_bracket else "[")
                        continue
                    if is_trivial_fragment(clean_part):
                        if answer_lines and clean_part in {",", ".", ")", "]", "?", "!", ":", ";"}:
                            answer_lines.append(clean_part)
                        continue
                    answer_lines.append(clean_part)
                answer_text = normalize_short_answer_text(assemble_text_fragments(normalize_flashcard_parts(answer_lines)))
                explanation_text = clean_explanation(normalize_flashcard_parts(explanation_parts))

        issues: list[str] = []
        if not stem:
            issues.append("missing_stem")
        if not answer_text:
            issues.append("missing_answer")

        parsed.append(
            ParsedQuestion(
                number=int(match.group(1)),
                page_number=snapshot.page_number,
                question_kind=question_kind,
                stem=stem,
                answer_text=answer_text or None,
                explanation_text=explanation_text,
                choices=[],
                bbox=clamp_bbox(expand_bbox(union_bboxes(bboxes), 8.0), snapshot.width, snapshot.height),
                correct_index=None,
                confidence=1.0 if not issues else 0.0,
                approved=not issues,
                issue_reason=", ".join(issues) if issues else None,
                payload={
                    "number": int(match.group(1)),
                    "page_number": snapshot.page_number,
                    "question_kind": question_kind,
                    "stem": stem,
                    "answer_text": answer_text,
                    "explanation_text": explanation_text,
                },
            )
        )

    return parsed


def serialize_question(question: ParsedQuestion) -> dict:
    payload = question.payload | {
        "question_kind": question.question_kind,
        "answer_text": question.answer_text,
        "explanation_text": question.explanation_text,
        "bbox": question.bbox,
        "correct_index": question.correct_index,
        "confidence": question.confidence,
        "approved": question.approved,
        "issue_reason": question.issue_reason,
        "crop_rel_path": question.crop_rel_path,
    }
    return payload


def parse_pdf(
    pdf_path: Path,
    cache_dir: Path,
) -> DocumentParseResult:
    document = fitz.open(pdf_path)
    slug = safe_slug(pdf_path.stem)

    snapshots: list[PageSnapshot] = []
    for page in document:
        snapshots.append(
            PageSnapshot(
                page_number=page.number + 1,
                width=page.rect.width,
                height=page.rect.height,
                lines=extract_lines(page),
                yellow_rects=extract_yellow_rects(page),
            )
        )

    repeats = repeated_texts(snapshots)
    parsed_questions: list[ParsedQuestion] = []
    for snapshot in snapshots:
        filtered_lines = filter_page_lines(snapshot, repeats)
        page_questions: list[ParsedQuestion] = []
        regions = split_into_regions(filtered_lines, snapshot)
        for region_lines, region_rects in regions:
            region = PageSnapshot(
                page_number=snapshot.page_number,
                width=snapshot.width,
                height=snapshot.height,
                lines=region_lines,
                yellow_rects=region_rects,
            )
            if any(OPTION_RE.match(line.text) for line in region_lines):
                page_questions.extend(parse_questions_from_lines(region_lines, region))
            else:
                page_questions.extend(parse_flashcards_from_lines(region_lines, region))

        handled_numbers, r_questions = parse_r_questions_from_regions(regions, snapshot)
        if handled_numbers:
            page_questions = [question for question in page_questions if question.number not in handled_numbers]
            page_questions.extend(r_questions)

        page_questions.sort(
            key=lambda question: (
                question.number,
                int(question.payload.get("sub_number", 0)),
                question.bbox[1],
                question.bbox[0],
            )
        )

        for order, question in enumerate(page_questions, start=1):
            question.crop_rel_path = None
            parsed_questions.append(question)

    title = pdf_path.stem
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_rel_path = Path("cache") / f"{slug}.json"
    cache_payload = {
        "title": title,
        "slug": slug,
        "source_pdf": pdf_path.name,
        "page_count": document.page_count,
        "questions": [serialize_question(question) for question in parsed_questions],
    }
    (cache_dir / f"{slug}.json").write_text(
        json.dumps(cache_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return DocumentParseResult(
        title=title,
        slug=slug,
        source_pdf=pdf_path.name,
        page_count=document.page_count,
        questions=parsed_questions,
        cache_rel_path=cache_rel_path.as_posix(),
    )
