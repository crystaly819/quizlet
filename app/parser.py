from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import csv
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import fitz

try:
    from kiwipiepy import Kiwi
except ImportError:  # pragma: no cover - optional dependency for spacing recovery
    Kiwi = None


QUESTION_RE = re.compile(r"^(\d+)\.\s*(.*)$")
OPTION_RE = re.compile(r"^([①②③④⑤])\s*(.*)$")
PAGE_NUMBER_RE = re.compile(r"^-\s*\d+\s*-$")
TRUE_FALSE_RE = re.compile(r"^\((O|X)\)\s*(.*)$", re.IGNORECASE)
DRUG_CARD_LABEL_RE = re.compile(r"^Drug\s+(\d+)$", re.IGNORECASE)
CHAPTER_HEADING_RE = re.compile(r"^Chapter\s+(\d+)$", re.IGNORECASE)
OPTION_INDEX = {"①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5}
CIRCLED_LABELS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
CIRCLED_LABEL_TO_INDEX = {label: index for index, label in enumerate(CIRCLED_LABELS, start=1)}
INDEX_TO_CIRCLED_LABEL = {index: label for label, index in CIRCLED_LABEL_TO_INDEX.items()}
SUBQUESTION_RE = re.compile(r"^\((\d+)\)\s*(.*)$")
HANGUL_RE = re.compile(r"[가-힣]")
ANSWER_ITEM_RE = re.compile(r"(\d+)\.\s*")
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
ProgressCallback = Callable[[str], None]


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


@dataclass(slots=True)
class OcrWord:
    text: str
    bbox: tuple[float, float, float, float]
    confidence: float
    yellow_ratio: float


@dataclass(slots=True)
class OcrSegment:
    text: str
    bbox: tuple[float, float, float, float]
    words: list[OcrWord]
    yellow_ratio: float


@dataclass(slots=True)
class OcrRow:
    text: str
    bbox: tuple[float, float, float, float]
    words: list[OcrWord]
    segments: list[OcrSegment]


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


def derive_document_title(pdf_path: Path) -> str:
    normalized_stem = unicodedata.normalize("NFC", pdf_path.stem)

    if normalized_stem.startswith("06.") and "생약학" in normalized_stem:
        return "생약학"
    if normalized_stem.startswith("15.") and "약제학" in normalized_stem and "약동학" in normalized_stem:
        return "약제/약동학"
    if "대한민국 약전 품질 파트" in normalized_stem:
        return "약전 품질"
    if "약품미생물학" in normalized_stem and "답치기" in normalized_stem:
        return "미생물학"
    if normalized_stem.startswith("33.") and "예방약학" in normalized_stem:
        return "예방약학"
    if "약물구조카드" in normalized_stem:
        return "약물구조"
    if "생화학 분과회" in normalized_stem and "답치기" in normalized_stem:
        return "생화학"

    return pdf_path.stem


def is_microbiology_answer_key_deck(pdf_path: Path) -> bool:
    normalized_stem = unicodedata.normalize("NFC", pdf_path.stem)
    return "약품미생물학" in normalized_stem and "답치기" in normalized_stem


def parse_microbiology_answer_key_entry(text: str) -> tuple[int, str] | None:
    normalized = normalize_text(text)
    if not normalized:
        return None

    normalized = re.sub(
        r"^(?P<prefix>[Oo0]?\s*\d(?:\s+\d){0,2})",
        lambda match: compact_text(match.group("prefix")),
        normalized,
    )
    match = re.match(r"^[Oo0]?\s*(\d{1,3})\s*[\.\:˛]?\s*(.+)$", normalized)
    if match is None:
        return None

    answer_text = match.group(2).strip()
    if not answer_text:
        return None
    return int(match.group(1)), answer_text


def is_likely_microbiology_answer_value(text: str) -> bool:
    compact = compact_text(text)
    if not compact:
        return False
    if len(compact) <= 24:
        return True
    if extract_choice_indices_from_text(text):
        return True
    if re.fullmatch(r"[TFOX0ㄱ-ㅎㅏ-ㅣ①-⑳,\s/().+-]+", text):
        return True
    return False


def is_microbiology_answer_key_page(lines: list[str]) -> bool:
    normalized_lines = [normalize_text(line) for line in lines if normalize_text(line)]
    if not normalized_lines:
        return False

    entry_count = 0
    answer_like_entry_count = 0
    for line in normalized_lines:
        entry = parse_microbiology_answer_key_entry(line)
        if entry is None:
            continue
        entry_count += 1
        if is_likely_microbiology_answer_value(entry[1]):
            answer_like_entry_count += 1
    has_solution_heading = any("해답" in line for line in normalized_lines)
    has_chapter_heading = any(CHAPTER_HEADING_RE.match(line) is not None for line in normalized_lines)

    if has_solution_heading and answer_like_entry_count >= 3:
        return True
    if has_chapter_heading and answer_like_entry_count >= 8:
        return True
    return answer_like_entry_count >= 20 and answer_like_entry_count >= max(8, entry_count // 2)


def parse_microbiology_answer_key(document: fitz.Document, pdf_path: Path) -> list[ParsedQuestion]:
    if not is_microbiology_answer_key_deck(pdf_path):
        return []

    parsed_questions: list[ParsedQuestion] = []
    global_number = 1
    current_chapter = "1"
    in_answer_key_section = False

    for page_number, page in enumerate(document, start=1):
        raw_lines = [normalize_text(line) for line in page.get_text("text").splitlines()]
        if not raw_lines:
            continue

        if not in_answer_key_section and page_number > document.page_count * 0.5:
            in_answer_key_section = is_microbiology_answer_key_page(raw_lines)
        if not in_answer_key_section:
            continue

        line_index = 0
        while line_index < len(raw_lines):
            current_line = raw_lines[line_index]
            if not current_line:
                line_index += 1
                continue

            chapter_match = CHAPTER_HEADING_RE.match(current_line)
            if chapter_match is not None:
                current_chapter = chapter_match.group(1)
                line_index += 1
                continue

            entry = parse_microbiology_answer_key_entry(current_line)
            if entry is None:
                line_index += 1
                continue

            item_number, answer_text = entry
            next_index = line_index + 1
            while next_index < len(raw_lines):
                next_line = raw_lines[next_index]
                if not next_line:
                    next_index += 1
                    continue
                if CHAPTER_HEADING_RE.match(next_line) or parse_microbiology_answer_key_entry(next_line) is not None:
                    break
                if len(compact_text(answer_text)) > 1:
                    break
                answer_text = normalize_text(f"{answer_text} {next_line}")
                next_index += 1

            cleaned_answer = normalize_short_answer_text(answer_text) or normalize_text(answer_text)
            if not cleaned_answer:
                line_index = next_index
                continue

            parsed_questions.append(
                ParsedQuestion(
                    number=global_number,
                    page_number=page_number,
                    question_kind="flashcard",
                    stem=f"Chapter {current_chapter} {item_number}번 정답",
                    answer_text=cleaned_answer,
                    explanation_text=None,
                    choices=[],
                    bbox=(0.0, 0.0, page.rect.width, page.rect.height),
                    correct_index=None,
                    confidence=1.0,
                    approved=True,
                    issue_reason=None,
                    payload={
                        "number": global_number,
                        "page_number": page_number,
                        "question_kind": "flashcard",
                        "stem": f"Chapter {current_chapter} {item_number}번 정답",
                        "answer_text": cleaned_answer,
                        "chapter": current_chapter,
                        "source_number": item_number,
                    },
                )
            )
            global_number += 1
            line_index = next_index

    return parsed_questions


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


def tesseract_binary() -> str | None:
    binary = shutil.which("tesseract")
    if binary:
        return binary
    candidate = Path(sys.prefix) / "bin" / "tesseract"
    if candidate.exists():
        return str(candidate)
    return None


def page_text_lines(page: fitz.Page) -> list[str]:
    return [line.strip() for line in page.get_text("text").splitlines() if line.strip()]


def extract_drug_card_number(page: fitz.Page) -> int | None:
    for line in page_text_lines(page):
        match = DRUG_CARD_LABEL_RE.match(line)
        if match is not None:
            return int(match.group(1))
    return None


def extract_page_image_rects(page: fitz.Page) -> list[fitz.Rect]:
    rects: list[fitz.Rect] = []
    seen: set[tuple[float, float, float, float]] = set()
    for image in page.get_images(full=True):
        for rect in page.get_image_rects(image[0]):
            key = tuple(round(value, 3) for value in rect)
            if key in seen:
                continue
            seen.add(key)
            rects.append(rect)
    rects.sort(key=lambda item: (item.y0, item.x0))
    return rects


def ocr_page_clip(page: fitz.Page, clip: fitz.Rect, *, dpi: int = 300, lang: str = "eng", psm: int = 6) -> str:
    binary = tesseract_binary()
    if binary is None:
        return ""

    scale = dpi / 72.0
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
    with tempfile.TemporaryDirectory() as tmp_dir:
        image_path = Path(tmp_dir) / "clip.png"
        image_path.write_bytes(pixmap.tobytes("png"))
        result = subprocess.run(
            [
                binary,
                str(image_path),
                "stdout",
                "--psm",
                str(psm),
                "-l",
                lang,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    return result.stdout


def normalize_ocr_line(text: str) -> str:
    normalized = normalize_text(text)
    normalized = re.sub(r"(?<=\d)\s*-\s*(?=[A-Za-z])", "-", normalized)
    return normalized.strip(" _-=:;,.|/\\'\"`~")


def yellow_pixel_ratio(
    pixmap: fitz.Pixmap,
    bbox: tuple[float, float, float, float],
) -> float:
    margin = 8
    x0 = max(0, min(int(bbox[0]) - margin, pixmap.width - 1))
    y0 = max(0, min(int(bbox[1]) - margin, pixmap.height - 1))
    x1 = max(0, min(int(bbox[2]) + margin, pixmap.width))
    y1 = max(0, min(int(bbox[3]) + margin, pixmap.height))
    if x1 <= x0 or y1 <= y0:
        return 0.0

    samples = memoryview(pixmap.samples)
    total = 0
    yellow = 0
    for y in range(y0, y1):
        row_offset = y * pixmap.stride
        for x in range(x0, x1):
            pixel_offset = row_offset + x * pixmap.n
            red = samples[pixel_offset]
            green = samples[pixel_offset + 1]
            blue = samples[pixel_offset + 2]
            total += 1
            if red >= 220 and green >= 210 and blue <= 170:
                yellow += 1
    return yellow / total if total else 0.0


def join_ocr_words(words: list[OcrWord]) -> str:
    if not words:
        return ""
    parts: list[str] = []
    previous_right: float | None = None
    average_width = sum(word.bbox[2] - word.bbox[0] for word in words) / len(words)
    gap_threshold = max(12.0, average_width * 0.7)

    for word in sorted(words, key=lambda item: item.bbox[0]):
        if previous_right is not None and word.bbox[0] - previous_right > gap_threshold:
            parts.append(" ")
        elif parts:
            parts.append(" ")
        parts.append(word.text)
        previous_right = word.bbox[2]
    return normalize_text("".join(parts))


def split_ocr_segments(words: list[OcrWord], gap_threshold: float) -> list[OcrSegment]:
    if not words:
        return []
    ordered = sorted(words, key=lambda item: item.bbox[0])
    groups: list[list[OcrWord]] = [[ordered[0]]]
    for word in ordered[1:]:
        previous = groups[-1][-1]
        if word.bbox[0] - previous.bbox[2] > gap_threshold:
            groups.append([word])
        else:
            groups[-1].append(word)

    segments: list[OcrSegment] = []
    for group in groups:
        bbox = union_bboxes(word.bbox for word in group)
        segments.append(
            OcrSegment(
                text=join_ocr_words(group),
                bbox=bbox,
                words=group,
                yellow_ratio=max((word.yellow_ratio for word in group), default=0.0),
            )
        )
    return segments


def ocr_page_rows(
    page: fitz.Page,
    *,
    dpi: int = 180,
    lang: str = "kor+eng",
    psm: int = 6,
) -> list[OcrRow]:
    binary = tesseract_binary()
    if binary is None:
        return []

    scale = dpi / 72.0
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    with tempfile.TemporaryDirectory() as tmp_dir:
        image_path = Path(tmp_dir) / "page.png"
        output_base = Path(tmp_dir) / "ocr"
        image_path.write_bytes(pixmap.tobytes("png"))
        subprocess.run(
            [binary, str(image_path), str(output_base), "--psm", str(psm), "-l", lang, "tsv"],
            capture_output=True,
            text=True,
            check=True,
        )
        tsv_rows = csv.DictReader((output_base.with_suffix(".tsv")).read_text(encoding="utf-8").splitlines(), delimiter="\t")
        grouped_words: dict[tuple[int, int, int], list[OcrWord]] = {}
        for row in tsv_rows:
            if row.get("level") != "5":
                continue
            text = (row.get("text") or "").strip()
            if not text:
                continue
            confidence = float(row.get("conf") or -1)
            left = int(row["left"])
            top = int(row["top"])
            width = int(row["width"])
            height = int(row["height"])
            bbox = (left, top, left + width, top + height)
            yellow_ratio = yellow_pixel_ratio(pixmap, bbox)
            if confidence < 20 and yellow_ratio < 0.08:
                continue
            word = OcrWord(
                text=text,
                bbox=bbox,
                confidence=confidence,
                yellow_ratio=yellow_ratio,
            )
            key = (int(row["block_num"]), int(row["par_num"]), int(row["line_num"]))
            grouped_words.setdefault(key, []).append(word)

    page_width = pixmap.width
    rows: list[OcrRow] = []
    for words in grouped_words.values():
        ordered = sorted(words, key=lambda item: item.bbox[0])
        bbox = union_bboxes(word.bbox for word in ordered)
        segments = split_ocr_segments(ordered, gap_threshold=max(90.0, page_width * 0.1))
        rows.append(
            OcrRow(
                text=join_ocr_words(ordered),
                bbox=bbox,
                words=ordered,
                segments=segments,
            )
        )

    rows.sort(key=lambda item: (item.bbox[1], item.bbox[0]))
    return rows


def clean_biochem_ocr_text(text: str) -> str:
    cleaned = normalize_text(text)
    cleaned = re.sub(r"^[\[\(\{]?\d+[\)\].:\-]?\s*", "", cleaned)
    cleaned = cleaned.strip("[]|")
    return normalize_text(cleaned)


def clean_biochem_choice_text(text: str) -> str:
    cleaned = clean_biochem_ocr_text(text)
    cleaned = re.sub(r"^[^A-Za-z가-힣0-9+\-]+", "", cleaned)
    cleaned = cleaned.replace("charge7t", "charge가")
    return normalize_text(cleaned)


def looks_like_drug_name(text: str) -> bool:
    if not text:
        return False
    alpha_count = sum(character.isalpha() for character in text)
    if alpha_count < 4:
        return False
    allowed_extra = set(" -+/(),.")
    disallowed = sum(1 for character in text if not character.isalnum() and character not in allowed_extra)
    if disallowed > 0:
        return False
    return True


def extract_underlined_drug_name(page: fitz.Page) -> str | None:
    rects = extract_page_image_rects(page)
    clips: list[fitz.Rect] = []
    if rects:
        clips.append(rects[0])
    page_rect = page.rect
    clips.insert(
        0,
        fitz.Rect(
            page_rect.width * 0.2,
            page_rect.height * 0.16,
            page_rect.width * 0.8,
            page_rect.height * 0.48,
        ),
    )

    for clip in clips:
        ocr_text = ocr_page_clip(page, clip, lang="eng", psm=6)
        for raw_line in ocr_text.splitlines():
            line = normalize_ocr_line(raw_line)
            if not line:
                continue
            if DRUG_CARD_LABEL_RE.match(line):
                continue
            if looks_like_drug_name(line):
                return line
    return None


def build_choice_bbox() -> tuple[float, float, float, float]:
    return (0.0, 0.0, 0.0, 0.0)


def build_drug_name_choices(names: list[str], current_index: int) -> tuple[list[ChoiceData], int]:
    unique_pool: list[str] = []
    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        unique_pool.append(name)

    correct_name = names[current_index]
    distractors: list[str] = []
    for offset in range(1, len(unique_pool) + 1):
        candidate = unique_pool[(current_index + offset) % len(unique_pool)]
        if candidate == correct_name or candidate in distractors:
            continue
        distractors.append(candidate)
        if len(distractors) == 3:
            break

    correct_index = (current_index % 4) + 1
    ordered_names = list(distractors)
    ordered_names.insert(correct_index - 1, correct_name)
    choices = [
        ChoiceData(
            index=index,
            label=choice_label_for_index(index),
            label_bbox=build_choice_bbox(),
            lines=[name],
            bboxes=[build_choice_bbox()],
        )
        for index, name in enumerate(ordered_names, start=1)
    ]
    return choices, correct_index


def parse_drug_structure_cards(document: fitz.Document, pdf_path: Path) -> list[ParsedQuestion]:
    normalized_stem = unicodedata.normalize("NFC", pdf_path.stem)
    if "약물구조카드" not in normalized_stem:
        return []

    answers_by_card: dict[int, tuple[int, str]] = {}
    for page_number in range(1, document.page_count + 1):
        page = document[page_number - 1]
        card_number = extract_drug_card_number(page)
        if card_number is None:
            continue
        drug_name = extract_underlined_drug_name(page)
        if drug_name:
            answers_by_card[card_number] = (page_number, drug_name)

    if not answers_by_card:
        return []

    ordered_cards = sorted(answers_by_card)
    all_names = [answers_by_card[number][1] for number in ordered_cards]
    parsed: list[ParsedQuestion] = []

    for index, card_number in enumerate(ordered_cards):
        answer_page_number, answer_name = answers_by_card[card_number]
        structure_page_number = next(
            (
                candidate_page
                for candidate_page in range(answer_page_number - 1, max(answer_page_number - 3, 0), -1)
                if extract_drug_card_number(document[candidate_page - 1]) == card_number
            ),
            None,
        )
        if structure_page_number is None:
            continue

        structure_page = document[structure_page_number - 1]
        structure_rects = extract_page_image_rects(structure_page)
        if structure_rects:
            bbox_rect = fitz.Rect(structure_rects[0])
            for rect in structure_rects[1:]:
                bbox_rect.include_rect(rect)
            bbox = clamp_bbox(expand_bbox(tuple(bbox_rect), 8.0), structure_page.rect.width, structure_page.rect.height)
        else:
            bbox = (0.0, 0.0, structure_page.rect.width, structure_page.rect.height)

        choices, correct_index = build_drug_name_choices(all_names, index)
        parsed.append(
            ParsedQuestion(
                number=card_number,
                page_number=structure_page_number,
                question_kind="multiple_choice",
                stem="이 약물 구조의 이름은?",
                answer_text=answer_name,
                explanation_text=None,
                choices=choices,
                bbox=bbox,
                correct_index=correct_index,
                confidence=1.0,
                approved=True,
                issue_reason=None,
                payload={
                    "number": card_number,
                    "page_number": structure_page_number,
                    "question_kind": "multiple_choice",
                    "stem": "이 약물 구조의 이름은?",
                    "answer_text": answer_name,
                    "drug_card_page": answer_page_number,
                },
            )
        )

    return parsed


def row_looks_like_biochem_option(row: OcrRow, page_width: float) -> bool:
    if not row.segments:
        return False
    first_token = row.words[0].text.strip() if row.words else ""
    first_char = first_token[0] if first_token else ""
    if first_char in {"@", "©", "®", "~", "+", "-"}:
        return True
    if len(row.segments) >= 3:
        return True
    if len(row.segments) >= 2 and any(
        segment.words and segment.words[0].text[:1] in {"@", "©", "®", "~", "+", "-"}
        for segment in row.segments
    ):
        return True
    return False


def ocr_clip_text(
    page: fitz.Page,
    bbox: tuple[float, float, float, float],
    *,
    dpi: int = 220,
    lang: str = "kor+eng",
    psm: int = 7,
) -> str:
    clip = fitz.Rect(*bbox)
    text = ocr_page_clip(page, clip, dpi=dpi, lang=lang, psm=psm)
    return clean_biochem_ocr_text(normalize_ocr_line(text))


def build_biochem_choice_data(
    page: fitz.Page,
    segments: list[OcrSegment],
    scale: float,
) -> tuple[list[ChoiceData], list[int]]:
    choices: list[ChoiceData] = []
    answer_indices: list[int] = []
    for index, segment in enumerate(segments, start=1):
        page_bbox = (
            segment.bbox[0] / scale,
            segment.bbox[1] / scale,
            segment.bbox[2] / scale,
            segment.bbox[3] / scale,
        )
        choice_text = ocr_clip_text(page, page_bbox) or clean_biochem_choice_text(segment.text)
        choice = ChoiceData(
            index=index,
            label=choice_label_for_index(index),
            label_bbox=page_bbox,
            lines=[clean_biochem_choice_text(choice_text) or clean_biochem_choice_text(segment.text)],
            bboxes=[page_bbox],
        )
        choices.append(choice)
        if segment.yellow_ratio >= 0.1:
            answer_indices.append(index)
    return choices, answer_indices


def parse_biochem_highlight_deck(document: fitz.Document, pdf_path: Path) -> list[ParsedQuestion]:
    normalized_stem = unicodedata.normalize("NFC", pdf_path.stem)
    if "생화학 분과회" not in normalized_stem:
        return []

    first_question_page = next(
        (
            page.number + 1
            for page in document
            if page.get_images(full=True) and len(page.get_text("text").strip()) <= 5
        ),
        None,
    )
    if first_question_page is None:
        return []

    parsed: list[ParsedQuestion] = []
    next_number = 1

    for page_number in range(first_question_page, document.page_count + 1):
        page = document[page_number - 1]
        if not page.get_images(full=True):
            continue

        dpi = 180
        scale = dpi / 72.0
        rows = ocr_page_rows(page, dpi=dpi, lang="kor+eng", psm=6)
        if not rows:
            continue

        filtered_rows = [
            row
            for row in rows
            if row.bbox[1] > page.rect.height * scale * 0.12
            and row.bbox[3] < page.rect.height * scale * 0.97
            and compact_text(row.text) not in {"기본편", "3", "4", "5", "6", "7", "8", "9"}
        ]
        if not filtered_rows:
            continue

        current_stem_rows: list[OcrRow] = []
        current_option_rows: list[OcrRow] = []

        def finalize_block() -> None:
            nonlocal next_number, current_stem_rows, current_option_rows
            if not current_stem_rows or not current_option_rows:
                current_stem_rows = []
                current_option_rows = []
                return

            all_segments: list[OcrSegment] = []
            for row in current_option_rows:
                all_segments.extend(segment for segment in row.segments if clean_biochem_choice_text(segment.text))

            if len(all_segments) < 2:
                current_stem_rows = []
                current_option_rows = []
                return

            choices, answer_indices = build_biochem_choice_data(page, all_segments[:5], scale)
            if not answer_indices:
                current_stem_rows = []
                current_option_rows = []
                return

            stem_bbox_pixels = union_bboxes(row.bbox for row in current_stem_rows)
            stem_bbox = (
                stem_bbox_pixels[0] / scale,
                stem_bbox_pixels[1] / scale,
                stem_bbox_pixels[2] / scale,
                stem_bbox_pixels[3] / scale,
            )
            stem = ocr_clip_text(page, stem_bbox) or assemble_text_fragments(
                [clean_biochem_ocr_text(row.text) for row in current_stem_rows]
            )
            if not stem:
                current_stem_rows = []
                current_option_rows = []
                return

            question_bbox_pixels = union_bboxes(
                [row.bbox for row in current_stem_rows] + [row.bbox for row in current_option_rows]
            )
            question_bbox = (
                question_bbox_pixels[0] / scale,
                question_bbox_pixels[1] / scale,
                question_bbox_pixels[2] / scale,
                question_bbox_pixels[3] / scale,
            )
            parsed.append(
                build_choice_question(
                    number=next_number,
                    page_number=page_number,
                    stem=stem,
                    choices=choices,
                    bbox=question_bbox,
                    answer_indices=answer_indices,
                    payload={
                        "number": next_number,
                        "page_number": page_number,
                        "stem": stem,
                        "source": "biochem_ocr",
                    },
                )
            )
            next_number += 1
            current_stem_rows = []
            current_option_rows = []

        for row in filtered_rows:
            is_option_row = row_looks_like_biochem_option(row, page.rect.width * scale)
            if is_option_row:
                if current_stem_rows:
                    current_option_rows.append(row)
                continue

            if current_option_rows:
                finalize_block()

            current_stem_rows.append(row)

        finalize_block()

    return parsed


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


def answer_text_for_indices(answer_indices: list[int]) -> str | None:
    labels = [choice_label_for_index(index) for index in answer_indices]
    return ", ".join(labels) or None


def build_choice_question(
    *,
    number: int,
    page_number: int,
    stem: str,
    choices: list[ChoiceData],
    bbox: tuple[float, float, float, float],
    answer_indices: list[int],
    payload: dict,
    confidence: float | None = None,
    issue_reasons: list[str] | None = None,
) -> ParsedQuestion:
    normalized_indices = sorted(index for index in dict.fromkeys(answer_indices) if index > 0)
    issues = list(issue_reasons or [])
    if not stem:
        issues.append("missing_stem")
    if len(choices) < 2:
        issues.append("missing_choices")
    if not normalized_indices:
        issues.append("missing_answer")
    if any(index > len(choices) for index in normalized_indices):
        issues.append("invalid_answer_choice")

    question_kind = "multi_select" if len(normalized_indices) > 1 else "multiple_choice"
    approved = not issues and bool(normalized_indices)
    if confidence is None:
        confidence = 1.0 if approved else 0.35 if normalized_indices else 0.0

    merged_payload = payload | {
        "question_kind": question_kind,
        "answer_indices": normalized_indices,
        "answer_text": answer_text_for_indices(normalized_indices),
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
    }

    return ParsedQuestion(
        number=number,
        page_number=page_number,
        question_kind=question_kind,
        stem=stem,
        answer_text=answer_text_for_indices(normalized_indices) if question_kind == "multi_select" else None,
        explanation_text=None,
        choices=choices,
        bbox=bbox,
        correct_index=normalized_indices[0] if question_kind == "multiple_choice" and normalized_indices else None,
        confidence=confidence,
        approved=approved,
        issue_reason=", ".join(issues) if issues else None,
        payload=merged_payload,
    )


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

    _, unique_matches, debug_rows = match_highlights(snapshot.yellow_rects, choices)
    if not unique_matches:
        issue_reasons.append("ambiguous_highlight")

    payload = {
        "number": current.number,
        "page_number": current.page_number,
        "stem": stem,
        "highlight_matches": debug_rows,
        "unique_matches": unique_matches,
    }
    return build_choice_question(
        number=current.number,
        page_number=current.page_number,
        stem=stem,
        choices=choices,
        bbox=bbox,
        answer_indices=unique_matches,
        payload=payload,
        issue_reasons=issue_reasons,
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


def slice_snapshot(
    snapshot: PageSnapshot,
    *,
    x0: float,
    x1: float,
) -> PageSnapshot:
    sliced_lines: list[LineData] = []
    for line in snapshot.lines:
        center_x = (line.bbox[0] + line.bbox[2]) / 2
        if center_x < x0 or center_x >= x1:
            continue
        sliced_lines.append(
            LineData(
                text=line.text,
                bbox=(line.bbox[0] - x0, line.bbox[1], line.bbox[2] - x0, line.bbox[3]),
                page_number=line.page_number,
                direction=line.direction,
                color=line.color,
                chars=[
                    CharData(
                        value=char.value,
                        bbox=(char.bbox[0] - x0, char.bbox[1], char.bbox[2] - x0, char.bbox[3]),
                    )
                    for char in line.chars
                ],
            )
        )

    sliced_rects = []
    for rect in snapshot.yellow_rects:
        center_x = (rect[0] + rect[2]) / 2
        if center_x < x0 or center_x >= x1:
            continue
        sliced_rects.append((rect[0] - x0, rect[1], rect[2] - x0, rect[3]))

    return PageSnapshot(
        page_number=snapshot.page_number,
        width=x1 - x0,
        height=snapshot.height,
        lines=sliced_lines,
        yellow_rects=sliced_rects,
    )


def split_booklet_spread(snapshot: PageSnapshot) -> list[PageSnapshot]:
    page_markers = [line for line in snapshot.lines if PAGE_NUMBER_RE.match(line.text)]
    if len(page_markers) != 2:
        return [snapshot]

    marker_centers = sorted((line.bbox[0] + line.bbox[2]) / 2 for line in page_markers)
    if marker_centers[1] - marker_centers[0] < snapshot.width * 0.3:
        return [snapshot]

    split_x = (marker_centers[0] + marker_centers[1]) / 2
    return [
        slice_snapshot(snapshot, x0=0.0, x1=split_x),
        slice_snapshot(snapshot, x0=split_x, x1=snapshot.width),
    ]


def split_content_and_footer(snapshot: PageSnapshot) -> tuple[list[LineData], list[RowData]]:
    rows = merge_lines_into_rows(snapshot.lines)
    footer_start = next((row.bbox[1] for row in rows if "정답" in row.text), None)
    content_lines = [
        line
        for line in snapshot.lines
        if not PAGE_NUMBER_RE.match(line.text) and (footer_start is None or line.bbox[1] < footer_start - 2.0)
    ]
    footer_rows = []
    if footer_start is not None:
        footer_rows = [
            row
            for row in rows
            if row.bbox[1] >= footer_start - 2.0 and not PAGE_NUMBER_RE.match(row.text)
        ]
    return content_lines, footer_rows


def extract_answer_from_segment(segment: str) -> tuple[str, str | None]:
    text = normalize_text(segment).rstrip(",")
    if not text:
        return "", None

    if re.match(rf"^(?:[{re.escape(CIRCLED_LABELS)}]\s*[OX0X])+?", text):
        matches = re.findall(rf"([{re.escape(CIRCLED_LABELS)}])\s*([OX0])", text)
        if matches:
            answer_text = "".join(f"{label}{value}" for label, value in matches)
            explanation = text
            for label, value in matches:
                explanation = explanation.replace(f"{label}{value}", "", 1)
            explanation = clean_explanation([explanation])
            return answer_text, explanation

    simple_patterns = [
        rf"^[{re.escape(CIRCLED_LABELS)}]+",
        r"^(?:[OX0]\s*)+$",
        r"^(?:[①-⑤][OX0])+$",
    ]
    for pattern in simple_patterns:
        match = re.match(pattern, text)
        if match is None:
            continue
        answer_text = normalize_text(match.group(0))
        remainder = text[match.end() :].strip()
        if remainder.startswith("("):
            return answer_text, clean_explanation([remainder])
        return answer_text, None

    return text, None


def parse_answer_footer(footer_rows: list[RowData]) -> dict[int, tuple[str, str | None]]:
    if not footer_rows:
        return {}

    joined = normalize_text(" ".join(row.text for row in footer_rows))
    joined = joined.replace("정답:", "").replace("정답", "").strip()
    while True:
        matches = list(ANSWER_ITEM_RE.finditer(joined))
        repaired = False
        previous_number: int | None = None
        for match in matches:
            number = int(match.group(1))
            if previous_number is None:
                previous_number = number
                continue
            if number <= 50:
                previous_number = number
                continue
            number_text = match.group(1)
            for suffix_length in (1, 2):
                candidate_text = number_text[-suffix_length:]
                if not candidate_text:
                    continue
                candidate = int(candidate_text)
                if candidate != previous_number + 1:
                    continue
                prefix = number_text[:-suffix_length]
                if not prefix:
                    continue
                insert_at = match.start(1) + len(prefix)
                joined = joined[:insert_at] + " " + joined[insert_at:]
                repaired = True
                break
            if repaired:
                break
            previous_number = number
        if not repaired:
            break

    matches = list(ANSWER_ITEM_RE.finditer(joined))
    parsed: dict[int, tuple[str, str | None]] = {}
    for index, match in enumerate(matches):
        number = int(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(joined)
        segment = joined[start:end].strip()
        if not segment:
            continue
        parsed[number] = extract_answer_from_segment(segment)
    return parsed


def dedupe_heading_like_questions(questions: list[ParsedQuestion]) -> list[ParsedQuestion]:
    deduped: list[ParsedQuestion] = []
    for question in questions:
        previous = next((item for item in reversed(deduped) if item.number == question.number), None)
        if previous is None:
            deduped.append(question)
            continue
        previous_is_heading = not previous.choices and len(compact_text(previous.stem)) <= 12
        current_is_heading = not question.choices and len(compact_text(question.stem)) <= 12
        if previous_is_heading and not current_is_heading:
            deduped = [item for item in deduped if item is not previous]
            deduped.append(question)
            continue
        if current_is_heading and not previous_is_heading:
            continue
        deduped.append(question)
    return deduped


def apply_answer_footer(
    questions: list[ParsedQuestion],
    footer_answers: dict[int, tuple[str, str | None]],
) -> list[ParsedQuestion]:
    for question in questions:
        answer = footer_answers.get(question.number)
        if answer is None:
            continue
        answer_text, explanation_text = answer
        if answer_text:
            question.answer_text = answer_text
            indices = extract_choice_indices_from_text(answer_text)
            if len(indices) == 1 and question.choices:
                question.correct_index = indices[0]
        if explanation_text:
            question.explanation_text = explanation_text
        if question.answer_text:
            question.approved = True
            question.confidence = max(question.confidence, 0.8)
            if question.issue_reason == "ambiguous_highlight":
                question.issue_reason = None
    return questions


def apply_answer_footer_to_pending_questions(
    pending_questions: list[ParsedQuestion],
    footer_answers: dict[int, tuple[str, str | None]],
) -> list[ParsedQuestion]:
    if not pending_questions or not footer_answers:
        return pending_questions

    matched_indices: set[int] = set()
    for number, answer in footer_answers.items():
        for index in range(len(pending_questions) - 1, -1, -1):
            if index in matched_indices:
                continue
            question = pending_questions[index]
            if question.number != number or question.answer_text:
                continue
            apply_answer_footer([question], {number: answer})
            matched_indices.add(index)
            break

    return [question for question in pending_questions if not question.answer_text]


def parse_snapshot_questions(
    snapshot: PageSnapshot,
    repeats: set[str],
) -> tuple[list[ParsedQuestion], dict[int, tuple[str, str | None]]]:
    filtered_lines = filter_page_lines(snapshot, repeats)
    content_lines, footer_rows = split_content_and_footer(
        PageSnapshot(
            page_number=snapshot.page_number,
            width=snapshot.width,
            height=snapshot.height,
            lines=filtered_lines,
            yellow_rects=snapshot.yellow_rects,
        )
    )

    page_questions: list[ParsedQuestion] = []
    working_snapshot = PageSnapshot(
        page_number=snapshot.page_number,
        width=snapshot.width,
        height=snapshot.height,
        lines=content_lines,
        yellow_rects=snapshot.yellow_rects,
    )
    regions = split_into_regions(content_lines, working_snapshot)
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

    handled_numbers, r_questions = parse_r_questions_from_regions(regions, working_snapshot)
    if handled_numbers:
        page_questions = [question for question in page_questions if question.number not in handled_numbers]
        page_questions.extend(r_questions)

    page_questions = dedupe_heading_like_questions(page_questions)
    page_questions.sort(
        key=lambda question: (
            question.number,
            int(question.payload.get("sub_number", 0)),
            question.bbox[1],
            question.bbox[0],
        )
    )
    return page_questions, parse_answer_footer(footer_rows)


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
    progress_callback: ProgressCallback | None = None,
) -> DocumentParseResult:
    def progress(message: str) -> None:
        if progress_callback is not None:
            progress_callback(message)

    document = fitz.open(pdf_path)
    try:
        slug = safe_slug(pdf_path.stem)
        title = derive_document_title(pdf_path)
        progress(f"[parse] Opened PDF '{pdf_path.name}' ({document.page_count} pages)")

        special_questions = parse_biochem_highlight_deck(document, pdf_path)
        if special_questions:
            progress(f"[parse] Detected OCR highlight layout in '{pdf_path.name}'")
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_rel_path = Path("cache") / f"{slug}.json"
            cache_payload = {
                "title": title,
                "slug": slug,
                "source_pdf": pdf_path.name,
                "page_count": document.page_count,
                "questions": [serialize_question(question) for question in special_questions],
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
                questions=special_questions,
                cache_rel_path=cache_rel_path.as_posix(),
            )

        special_questions = parse_drug_structure_cards(document, pdf_path)
        if special_questions:
            progress(f"[parse] Detected special card layout in '{pdf_path.name}'")
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_rel_path = Path("cache") / f"{slug}.json"
            cache_payload = {
                "title": title,
                "slug": slug,
                "source_pdf": pdf_path.name,
                "page_count": document.page_count,
                "questions": [serialize_question(question) for question in special_questions],
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
                questions=special_questions,
                cache_rel_path=cache_rel_path.as_posix(),
            )

        special_questions = parse_microbiology_answer_key(document, pdf_path)
        if special_questions:
            progress(f"[parse] Detected microbiology answer-key layout in '{pdf_path.name}'")
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_rel_path = Path("cache") / f"{slug}.json"
            cache_payload = {
                "title": title,
                "slug": slug,
                "source_pdf": pdf_path.name,
                "page_count": document.page_count,
                "questions": [serialize_question(question) for question in special_questions],
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
                questions=special_questions,
                cache_rel_path=cache_rel_path.as_posix(),
            )

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
            if (page.number + 1) % 25 == 0 or page.number + 1 == document.page_count:
                progress(
                    f"[parse] Extracted page layout {page.number + 1}/{document.page_count} for '{pdf_path.name}'"
                )

        repeats = repeated_texts(snapshots)
        parsed_questions: list[ParsedQuestion] = []
        pending_questions: list[ParsedQuestion] = []
        for snapshot in snapshots:
            logical_pages = split_booklet_spread(snapshot)
            for logical_snapshot in logical_pages:
                page_questions, footer_answers = parse_snapshot_questions(logical_snapshot, repeats)
                if footer_answers:
                    apply_answer_footer(page_questions, footer_answers)
                    if pending_questions:
                        current_numbers = {question.number for question in page_questions}
                        pending_footer_answers = {
                            number: answer
                            for number, answer in footer_answers.items()
                            if number not in current_numbers
                        }
                        pending_questions = apply_answer_footer_to_pending_questions(
                            pending_questions,
                            pending_footer_answers,
                        )
                else:
                    pending_questions.extend(page_questions)
                for order, question in enumerate(page_questions, start=1):
                    question.crop_rel_path = None
                    parsed_questions.append(question)
            if snapshot.page_number % 25 == 0 or snapshot.page_number == len(snapshots):
                progress(
                    f"[parse] Parsed questions through page {snapshot.page_number}/{len(snapshots)} in '{pdf_path.name}'"
                )

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
        progress(f"[parse] Wrote cache for '{pdf_path.name}' with {len(parsed_questions)} questions")

        return DocumentParseResult(
            title=title,
            slug=slug,
            source_pdf=pdf_path.name,
            page_count=document.page_count,
            questions=parsed_questions,
            cache_rel_path=cache_rel_path.as_posix(),
        )
    finally:
        document.close()
