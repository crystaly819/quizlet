from __future__ import annotations

import json
from pathlib import Path

from app.biochem_review import build_review_chunks, question_to_cache_entry
from app.enrich_review_bboxes import split_rows_into_question_groups
from app.bootstrap_biochem_chunks_from_cache import cache_entry_to_review_question, update_chunk_questions
from app.merge_biochem_review import ensure_chunk_completion, merge_payloads, validate_review_payload
from app.parser import RowData


def test_build_review_chunks_splits_pages_into_tens() -> None:
    chunks = build_review_chunks(start_page=28, end_page=53, chunk_size=10)

    assert [(chunk.start_page, chunk.end_page) for chunk in chunks] == [
        (28, 37),
        (38, 47),
        (48, 53),
    ]


def test_question_to_cache_entry_converts_reviewed_question() -> None:
    entry = question_to_cache_entry(
        {
            "question_number": 99,
            "page_number": 120,
            "question_kind": "multiple_choice",
            "stem": "검수된 문제",
            "choices": ["A", "B", "C"],
            "correct_index": 2,
            "answer_text": None,
            "manual_reviewed": True,
        }
    )

    assert entry["number"] == 99
    assert entry["question_kind"] == "multiple_choice"
    assert entry["correct_index"] == 2
    assert [choice["text"] for choice in entry["choices"]] == ["A", "B", "C"]
    assert entry["source"] == "vlm_review"


def test_validate_review_payload_requires_answer_shape() -> None:
    payload = {
        "page_range": {"start": 28, "end": 37},
        "review_completed": False,
        "questions": [
            {
                "question_number": 1,
                "page_number": 29,
                "question_kind": "multiple_choice",
                "stem": "문제",
                "choices": ["A", "B"],
                "manual_reviewed": True,
            }
        ],
    }

    try:
        validate_review_payload(payload)
    except ValueError as exc:
        assert "correct_index" in str(exc)
    else:
        raise AssertionError("expected payload validation to fail")


def test_validate_review_payload_allows_short_answer() -> None:
    payload = {
        "page_range": {"start": 98, "end": 107},
        "review_completed": False,
        "questions": [
            {
                "question_number": 5,
                "page_number": 103,
                "question_kind": "short_answer",
                "stem": "주관식 문제",
                "choices": [],
                "correct_index": None,
                "answer_text": "Glutamate",
                "manual_reviewed": True,
            }
        ],
    }

    validate_review_payload(payload)


def test_merge_payloads_keeps_early_pages_and_appends_reviewed_questions() -> None:
    base_payload = {
        "title": "sample",
        "slug": "sample",
        "page_count": 100,
        "questions": [
            {
                "number": 1,
                "page_number": 10,
                "stem": "early",
                "question_kind": "multiple_choice",
                "choices": [],
                "correct_index": 1,
            },
            {
                "number": 2,
                "page_number": 30,
                "stem": "late",
                "question_kind": "multiple_choice",
                "choices": [],
                "correct_index": 1,
            },
        ],
    }
    review_payload = {
        "page_range": {"start": 28, "end": 37},
        "review_completed": True,
        "questions": [
            {
                "question_number": 3,
                "page_number": 29,
                "question_kind": "multiple_choice",
                "stem": "reviewed",
                "choices": ["A", "B"],
                "correct_index": 2,
                "answer_text": None,
                "manual_reviewed": True,
            }
        ],
    }

    merged = merge_payloads(
        base_payload,
        [review_payload],
        keep_through_page=27,
        source_pdf="pdfs/sample.pdf",
    )

    assert merged["title"].endswith("[reviewed]")
    assert [question["number"] for question in merged["questions"]] == [1, 3]
    assert merged["questions"][1]["manual_reviewed"] is True


def test_merge_payloads_can_overlay_reviewed_questions_while_retaining_base() -> None:
    base_payload = {
        "title": "sample",
        "slug": "sample",
        "page_count": 100,
        "questions": [
            {
                "number": 1,
                "page_number": 10,
                "stem": "early",
                "question_kind": "multiple_choice",
                "choices": [],
                "correct_index": 1,
            },
            {
                "number": 2,
                "page_number": 30,
                "stem": "ocr",
                "question_kind": "multiple_choice",
                "choices": [{"text": "A"}],
                "correct_index": 1,
            },
        ],
    }
    review_payload = {
        "page_range": {"start": 28, "end": 37},
        "review_completed": False,
        "questions": [
            {
                "question_number": 2,
                "page_number": 30,
                "question_kind": "multiple_choice",
                "stem": "reviewed",
                "choices": ["X", "Y"],
                "correct_index": 2,
                "answer_text": None,
                "manual_reviewed": True,
            }
        ],
    }

    merged = merge_payloads(
        base_payload,
        [review_payload],
        keep_through_page=27,
        source_pdf="pdfs/sample.pdf",
        retain_unreviewed=True,
        manual_only=True,
    )

    assert [question["number"] for question in merged["questions"]] == [1, 2]
    assert merged["questions"][1]["stem"] == "reviewed"
    assert merged["questions"][1]["correct_index"] == 2


def test_merge_payloads_manual_only_skips_unreviewed_drafts() -> None:
    base_payload = {
        "title": "sample",
        "slug": "sample",
        "page_count": 100,
        "questions": [
            {
                "number": 5,
                "page_number": 50,
                "stem": "ocr",
                "question_kind": "multiple_choice",
                "choices": [{"text": "A"}],
                "correct_index": 1,
            }
        ],
    }
    review_payload = {
        "page_range": {"start": 48, "end": 57},
        "review_completed": False,
        "questions": [
            {
                "question_number": 5,
                "page_number": 50,
                "question_kind": "multiple_choice",
                "stem": "draft",
                "choices": ["X", "Y"],
                "correct_index": 2,
                "answer_text": None,
                "manual_reviewed": False,
            }
        ],
    }

    merged = merge_payloads(
        base_payload,
        [review_payload],
        keep_through_page=27,
        source_pdf="pdfs/sample.pdf",
        retain_unreviewed=True,
        manual_only=True,
    )

    assert merged["questions"][0]["stem"] == "ocr"


def test_merge_payloads_completed_only_replaces_entire_completed_page_ranges() -> None:
    base_payload = {
        "title": "sample",
        "slug": "sample",
        "page_count": 100,
        "questions": [
            {
                "number": 10,
                "page_number": 48,
                "stem": "base-48",
                "question_kind": "multiple_choice",
                "choices": [{"text": "A"}],
                "correct_index": 1,
            },
            {
                "number": 11,
                "page_number": 49,
                "stem": "base-49",
                "question_kind": "multiple_choice",
                "choices": [{"text": "A"}],
                "correct_index": 1,
            },
            {
                "number": 12,
                "page_number": 60,
                "stem": "base-60",
                "question_kind": "multiple_choice",
                "choices": [{"text": "A"}],
                "correct_index": 1,
            },
        ],
    }
    review_payload = {
        "page_range": {"start": 48, "end": 57},
        "review_completed": True,
        "questions": [
            {
                "question_number": 1,
                "page_number": 48,
                "question_kind": "multiple_choice",
                "stem": "review-48",
                "choices": ["X", "Y"],
                "correct_index": 2,
                "answer_text": None,
                "manual_reviewed": True,
            }
        ],
    }

    merged = merge_payloads(
        base_payload,
        [review_payload],
        keep_through_page=27,
        source_pdf="pdfs/sample.pdf",
        retain_unreviewed=True,
        manual_only=True,
        completed_only=True,
    )

    assert [(question["page_number"], question["stem"]) for question in merged["questions"]] == [
        (48, "review-48"),
        (60, "base-60"),
    ]


def test_merge_payloads_can_preserve_base_metadata() -> None:
    base_payload = {
        "title": "sample",
        "slug": "sample",
        "page_count": 100,
        "questions": [],
    }

    merged = merge_payloads(
        base_payload,
        [],
        keep_through_page=27,
        source_pdf="pdfs/sample.pdf",
        preserve_base_metadata=True,
    )

    assert merged["title"] == "sample"
    assert merged["slug"] == "sample"


def test_ensure_chunk_completion_rejects_incomplete_chunks() -> None:
    try:
        ensure_chunk_completion(
            [
                {"page_range": {"start": 28, "end": 37}, "review_completed": True, "questions": []},
                {"page_range": {"start": 38, "end": 47}, "review_completed": False, "questions": []},
            ]
        )
    except ValueError as exc:
        assert "38-47" in str(exc)
    else:
        raise AssertionError("expected incomplete chunk validation to fail")


def test_cache_entry_to_review_question_preserves_mcq_shape() -> None:
    review_question = cache_entry_to_review_question(
        {
            "number": 12,
            "page_number": 120,
            "question_kind": "multiple_choice",
            "stem": "문제",
            "choices": [
                {"index": 1, "text": "A"},
                {"index": 2, "text": "B"},
            ],
            "correct_index": 2,
            "answer_text": None,
        }
    )

    assert review_question["question_number"] == 12
    assert review_question["choices"] == ["A", "B"]
    assert review_question["correct_index"] == 2
    assert review_question["manual_reviewed"] is False


def test_update_chunk_questions_only_adds_questions_in_range() -> None:
    chunk_payload = {
        "page_range": {"start": 118, "end": 127},
        "review_completed": False,
        "questions": [
            {
                "question_number": 1,
                "page_number": 118,
                "question_kind": "multiple_choice",
                "stem": "existing",
                "choices": ["A", "B"],
                "correct_index": 1,
                "answer_text": None,
                "manual_reviewed": True,
            }
        ],
    }
    cache_questions = [
        {
            "number": 1,
            "page_number": 118,
            "question_kind": "multiple_choice",
            "stem": "duplicate",
            "choices": [{"index": 1, "text": "A"}],
            "correct_index": 1,
            "answer_text": None,
        },
        {
            "number": 2,
            "page_number": 119,
            "question_kind": "multiple_choice",
            "stem": "added",
            "choices": [{"index": 1, "text": "A"}],
            "correct_index": 1,
            "answer_text": None,
        },
        {
            "number": 99,
            "page_number": 140,
            "question_kind": "multiple_choice",
            "stem": "out-of-range",
            "choices": [{"index": 1, "text": "A"}],
            "correct_index": 1,
            "answer_text": None,
        },
    ]

    updated = update_chunk_questions(chunk_payload, cache_questions)

    assert [(item["page_number"], item["question_number"]) for item in updated["questions"]] == [(118, 1), (119, 2)]


def test_update_chunk_questions_keeps_existing_review_flag() -> None:
    chunk_payload = {
        "page_range": {"start": 48, "end": 57},
        "review_completed": True,
        "questions": [],
    }
    cache_questions = [
        {
            "number": 10,
            "page_number": 49,
            "question_kind": "multiple_choice",
            "stem": "draft",
            "choices": [{"index": 1, "text": "A"}],
            "correct_index": 1,
            "answer_text": None,
        }
    ]

    updated = update_chunk_questions(chunk_payload, cache_questions)

    assert updated["review_completed"] is True
    assert updated["questions"][0]["manual_reviewed"] is False


def test_split_rows_into_question_groups_uses_largest_vertical_gaps() -> None:
    rows = [
        RowData(text="q1 stem", bbox=(0, 0, 100, 20)),
        RowData(text="q1 choice", bbox=(0, 30, 100, 50)),
        RowData(text="q2 stem", bbox=(0, 100, 100, 120)),
        RowData(text="q2 choice", bbox=(0, 130, 100, 150)),
        RowData(text="q3 stem", bbox=(0, 220, 100, 240)),
    ]

    groups = split_rows_into_question_groups(rows, 3)

    assert [[row.text for row in group] for group in groups] == [
        ["q1 stem", "q1 choice"],
        ["q2 stem", "q2 choice"],
        ["q3 stem"],
    ]
