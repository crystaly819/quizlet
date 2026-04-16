from __future__ import annotations

from pathlib import Path

from app.parser import (
    ChoiceData,
    LineData,
    PageSnapshot,
    ParsedQuestion,
    apply_answer_footer_to_pending_questions,
    build_choice_question,
    derive_document_title,
    filter_page_lines,
    is_answer_highlight,
    is_microbiology_answer_key_page,
    match_highlights,
    parse_microbiology_answer_key_entry,
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


def test_build_choice_question_uses_multi_select_for_multiple_answers() -> None:
    choices = [
        ChoiceData(index=1, label="①", label_bbox=(0, 0, 10, 10), lines=["alpha"], bboxes=[(0, 0, 10, 10)]),
        ChoiceData(index=2, label="②", label_bbox=(0, 10, 10, 20), lines=["beta"], bboxes=[(0, 10, 10, 20)]),
        ChoiceData(index=3, label="③", label_bbox=(0, 20, 10, 30), lines=["gamma"], bboxes=[(0, 20, 10, 30)]),
    ]

    question = build_choice_question(
        number=1,
        page_number=1,
        stem="복수정답 문제",
        choices=choices,
        bbox=(0, 0, 10, 30),
        answer_indices=[1, 3],
        payload={"number": 1, "page_number": 1, "stem": "복수정답 문제"},
    )

    assert question.question_kind == "multi_select"
    assert question.answer_text == "①, ③"
    assert question.correct_index is None
    assert question.approved is True


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


def test_derive_document_title_cleans_known_real_pdf_names() -> None:
    assert derive_document_title(Path("06. 생약학 필수 문제집_워터마크.pdf")) == "생약학"
    assert derive_document_title(Path("15. 약제학 약동학 개념확인 문제집_워터마크.pdf")) == "약제/약동학"
    assert derive_document_title(Path("33. 예방약학 문제집_워터마크.pdf")) == "예방약학"
    assert derive_document_title(Path("[보안][답치기] 대한민국 약전 품질 파트.pdf")) == "약전 품질"
    assert derive_document_title(Path("[절대보안][문제집] 약품미생물학 연습 답치기.pdf")) == "미생물학"
    assert derive_document_title(Path("[보안][과제] 약물구조카드 매일보기.pdf")) == "약물구조"
    assert derive_document_title(Path("[답] 생화학 분과회 문제집 답치기 (1).pdf")) == "생화학"


def test_parse_microbiology_answer_key_entry_handles_ocr_spacing() -> None:
    assert parse_microbiology_answer_key_entry("O1. F") == (1, "F")
    assert parse_microbiology_answer_key_entry("1 0. T") == (10, "T")
    assert parse_microbiology_answer_key_entry("44: ①, ③") == (44, "①, ③")


def test_is_microbiology_answer_key_page_detects_real_answer_section_shape() -> None:
    assert (
        is_microbiology_answer_key_page(
            [
                "해답 123",
                "Chapter 1",
                "O1. F",
                "02. T",
                "03. F",
                "04. T",
                "05. F",
                "06. T",
                "07. T",
                "08. T",
            ]
        )
        is True
    )
    assert (
        is_microbiology_answer_key_page(
            [
                "약품미생물학 요약 및 연습",
                "[1-12] 다음 설명 중 옳은 것에 T, 틀린 것에 F를 표시하시오.",
                "1 Robe㏏ Koch가 탄저균을 발견하고 백신을 개발하였다.",
                "2 히포크라테스는 질병의 원인으로 사기설을 주장하였다.",
                "3 Walter Reed는 황열이 모기에 의해 매개됨을 규명하였다.",
            ]
        )
        is False
    )


def test_apply_answer_footer_to_pending_questions_uses_most_recent_matching_number() -> None:
    older_question = ParsedQuestion(
        number=1,
        page_number=2,
        question_kind="multiple_choice",
        stem="older",
        answer_text=None,
        explanation_text=None,
        choices=[],
        bbox=(0, 0, 10, 10),
        correct_index=None,
        confidence=0.1,
        approved=False,
        issue_reason="missing_answer",
        payload={},
    )
    newer_question = ParsedQuestion(
        number=1,
        page_number=5,
        question_kind="multiple_choice",
        stem="newer",
        answer_text=None,
        explanation_text=None,
        choices=[],
        bbox=(0, 0, 10, 10),
        correct_index=None,
        confidence=0.1,
        approved=False,
        issue_reason="missing_answer",
        payload={},
    )
    sibling_question = ParsedQuestion(
        number=2,
        page_number=5,
        question_kind="multiple_choice",
        stem="sibling",
        answer_text=None,
        explanation_text=None,
        choices=[],
        bbox=(0, 0, 10, 10),
        correct_index=None,
        confidence=0.1,
        approved=False,
        issue_reason="missing_answer",
        payload={},
    )

    remaining = apply_answer_footer_to_pending_questions(
        [older_question, newer_question, sibling_question],
        {
            1: ("③", None),
            2: ("①", None),
        },
    )

    assert older_question.answer_text is None
    assert newer_question.answer_text == "③"
    assert sibling_question.answer_text == "①"
    assert remaining == [older_question]
