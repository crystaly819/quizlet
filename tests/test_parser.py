from __future__ import annotations

from app.parser import (
    ChoiceData,
    LineData,
    PageSnapshot,
    filter_page_lines,
    is_answer_highlight,
    match_highlights,
    parse_flashcards_from_lines,
    parse_questions_from_lines,
)


def line(text: str, bbox: tuple[float, float, float, float], *, direction=(1.0, 0.0), color=(0.0, 0.0, 0.0)) -> LineData:
    return LineData(text=text, bbox=bbox, page_number=1, direction=direction, color=color, chars=[])


def test_filter_page_lines_removes_repeated_header_and_rotated_watermark() -> None:
    snapshot = PageSnapshot(
        page_number=1,
        width=595,
        height=842,
        lines=[
            line("반복 헤더", (350, 50, 420, 62)),
            line("국시넷_윤수정", (220, 320, 360, 470), direction=(0.7, -0.7), color=(0.5, 0.5, 0.5)),
            line("1. 실제 문항", (56, 100, 180, 120)),
        ],
        yellow_rects=[],
    )

    filtered = filter_page_lines(snapshot, {"반복 헤더", "국시넷_윤수정"})

    assert [item.text for item in filtered] == ["1. 실제 문항"]


def test_filter_page_lines_keeps_question_number_at_top_even_if_repeated() -> None:
    snapshot = PageSnapshot(
        page_number=1,
        width=595,
        height=842,
        lines=[
            line("반복 헤더", (350, 50, 420, 62)),
            line("1.", (50, 72, 61, 86)),
            line("문제 본문", (73, 72, 180, 86)),
        ],
        yellow_rects=[],
    )

    filtered = filter_page_lines(snapshot, {"반복 헤더", "1."})

    assert [item.text for item in filtered] == ["1.", "문제 본문"]


def test_parse_questions_keeps_inner_markers_in_stem() -> None:
    snapshot = PageSnapshot(page_number=1, width=595, height=842, lines=[], yellow_rects=[(72, 306, 83, 320)])
    lines = [
        line("1. 보기 조합 문제는?", (56, 120, 180, 140)),
        line("㉠ 알파", (72, 150, 140, 168)),
        line("㉡ 베타", (283, 150, 340, 168)),
        line("① ㉠", (72, 306, 110, 320)),
        line("② ㉡", (283, 306, 320, 320)),
    ]

    questions = parse_questions_from_lines(lines, snapshot)

    assert len(questions) == 1
    assert "㉠ 알파" in questions[0].stem
    assert "㉡ 베타" in questions[0].stem
    assert questions[0].correct_index == 1


def test_parse_questions_assembles_fragmented_stem_and_choices() -> None:
    snapshot = PageSnapshot(page_number=18, width=595, height=842, lines=[], yellow_rects=[(72, 416, 83, 430)])
    lines = [
        line("243.", (56, 120, 80, 136)),
        line("용출시험에대한설명으로옳은것은", (84, 120, 260, 136)),
        line("?", (262, 120, 270, 136)),
        line("가", (84, 150, 92, 166)),
        line(")", (94, 150, 98, 166)),
        line("용출시험은현저한생물학적비동등성을방지하는것을목적으로한다", (102, 150, 360, 166)),
        line(".", (362, 150, 366, 166)),
        line("나", (84, 178, 92, 194)),
        line(")", (94, 178, 98, 194)),
        line("서방성제제는이시험을적용하지않는다", (102, 178, 260, 194)),
        line(".", (262, 178, 266, 194)),
        line("①", (72, 306, 83, 320)),
        line("가나", (87, 306, 112, 320)),
        line(",", (114, 306, 118, 320)),
        line("②", (72, 334, 83, 348)),
        line("나다", (87, 334, 112, 348)),
        line(",", (114, 334, 118, 348)),
        line("③", (72, 362, 83, 376)),
        line("다라", (87, 362, 112, 376)),
        line(",", (114, 362, 118, 376)),
        line("④", (72, 390, 83, 404)),
        line("라마", (87, 390, 112, 404)),
        line(",", (114, 390, 118, 404)),
        line("⑤", (72, 416, 83, 430)),
        line("가라", (87, 416, 112, 430)),
        line(",", (114, 416, 118, 430)),
    ]

    questions = parse_questions_from_lines(lines, snapshot)

    assert len(questions) == 1
    assert questions[0].stem.startswith("용출시험에대한설명으로옳은것은?")
    assert "\n가) 용출시험은현저한생물학적비동등성을방지하는것을목적으로한다." in questions[0].stem
    assert "\n나) 서방성제제는이시험을적용하지않는다." in questions[0].stem
    assert [choice.text for choice in questions[0].choices] == ["가나,", "나다,", "다라,", "라마,", "가라,"]
    assert questions[0].correct_index == 5


def test_match_highlights_returns_none_for_multiple_choices() -> None:
    choices = [
        ChoiceData(index=1, label="①", label_bbox=(72, 136, 83, 149)),
        ChoiceData(index=2, label="②", label_bbox=(283, 136, 294, 149)),
    ]

    matched, unique_matches, _ = match_highlights(
        [(72, 136, 83, 149), (283, 136, 294, 149)],
        choices,
    )

    assert matched is None
    assert unique_matches == [1, 2]


def test_answer_highlight_supports_yellow_and_pink_tones() -> None:
    assert is_answer_highlight((1.0, 1.0, 0.0)) is True
    assert is_answer_highlight((0.949, 0.604, 0.776)) is True
    assert is_answer_highlight((0.973, 0.796, 0.886)) is True
    assert is_answer_highlight((1.0, 1.0, 1.0)) is False


def test_parse_flashcards_detects_true_false_and_explanation() -> None:
    snapshot = PageSnapshot(page_number=2, width=595, height=842, lines=[], yellow_rects=[])
    lines = [
        line("1.", (50, 90, 61, 104)),
        line("물은 상온에서 액체이다.", (73, 90, 220, 104)),
        line("(O)", (430, 90, 452, 104)),
        line("[상온에서 물은 액체 상태다.]", (455, 90, 590, 120)),
    ]

    questions = parse_flashcards_from_lines(lines, snapshot)

    assert len(questions) == 1
    assert questions[0].question_kind == "true_false"
    assert questions[0].answer_text == "O"
    assert questions[0].explanation_text == "상온에서 물은 액체 상태다."


def test_parse_flashcards_detects_short_answer_and_explanation() -> None:
    snapshot = PageSnapshot(page_number=3, width=595, height=842, lines=[], yellow_rects=[])
    lines = [
        line("1.", (50, 90, 61, 104)),
        line("대한민국의 수도는?", (73, 90, 220, 104)),
        line("서울", (430, 90, 470, 104)),
        line("[대한민국의 수도는 서울이다.]", (430, 114, 590, 138)),
    ]

    questions = parse_flashcards_from_lines(lines, snapshot)

    assert len(questions) == 1
    assert questions[0].question_kind == "short_answer"
    assert questions[0].answer_text == "서울"
    assert questions[0].explanation_text == "대한민국의 수도는 서울이다."


def test_parse_flashcards_restores_spacing_for_unspaced_korean_prompt_and_answer() -> None:
    snapshot = PageSnapshot(page_number=45, width=595, height=842, lines=[], yellow_rects=[])
    lines = [
        line("12.", (50, 90, 61, 104)),
        line("카카오지의융점이저하되었을때경화제로사용되는것은?", (73, 90, 320, 104)),
        line("세틸에스터왁스밀납", (430, 90, 520, 104)),
        line(",", (522, 90, 526, 104)),
    ]

    questions = parse_flashcards_from_lines(lines, snapshot)

    assert len(questions) == 1
    assert questions[0].stem == "카카오지의 융점이 저하되었을 때 경화제로 사용되는 것은?"
    assert questions[0].answer_text == "세틸에스터왁스, 밀납"
