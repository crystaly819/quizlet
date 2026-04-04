from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import configure_database, init_db, session_scope
from app.ingest_service import ingest_pdf_directory
from app.main import create_app, question_to_payload
from app.models import ParseIssue, Question


def test_web_flow_supports_study_and_review(temp_settings) -> None:
    configure_database(temp_settings.database_url)
    init_db()
    ingest_pdf_directory(temp_settings.pdf_dir, temp_settings, rebuild=True)
    with session_scope() as session:
        multi_select_question = Question(
            deck_id=1,
            number=900,
            page_number=4,
            question_kind="multi_select",
            stem="Pick the matching items.",
            answer_text="②, ④",
            confidence=1.0,
            source_bbox=json.dumps([0, 0, 100, 100]),
            crop_path=None,
            is_approved=True,
        )
        multi_select_question.set_choices(
            [
                "Alpha",
                "Beta",
                "Gamma",
                "Delta",
                "Epsilon",
                "Zeta",
            ]
        )
        session.add(multi_select_question)
        session.flush()

        discard_question = Question(
            deck_id=1,
            number=901,
            page_number=4,
            question_kind="multiple_choice",
            stem="이건 실제 문항이 아닌 잘못 잡힌 조각입니다.",
            confidence=0.0,
            source_bbox=json.dumps([0, 0, 80, 80]),
            crop_path=None,
            is_approved=False,
        )
        discard_question.set_choices(["조각 1", "조각 2"])
        session.add(discard_question)
        session.flush()
        discard_issue = ParseIssue(
            question_id=discard_question.id,
            reason="discard_me",
            payload_json=json.dumps({"stem": discard_question.stem}, ensure_ascii=False),
            status="open",
        )
        session.add(discard_issue)
    client = TestClient(create_app(temp_settings))

    index_response = client.get("/")
    assert index_response.status_code == 200
    assert "sample" in index_response.text

    study_response = client.get("/decks/1/study?mode=all")
    assert study_response.status_code == 200
    assert "원문은 기본으로 숨겨져 있습니다." in study_response.text

    next_response = client.get("/api/decks/1/next?mode=all")
    payload = next_response.json()["question"]
    assert payload is not None

    with session_scope() as session:
        true_false_question = session.execute(
            select(Question).where(Question.question_kind == "true_false").order_by(Question.id)
        ).scalars().first()
        short_answer_question = session.execute(
            select(Question).where(Question.question_kind == "short_answer").order_by(Question.id)
        ).scalars().first()
        multi_select_question = session.execute(
            select(Question).where(Question.question_kind == "multi_select").order_by(Question.id)
        ).scalars().first()
        issue = session.execute(
            select(ParseIssue).where(ParseIssue.reason != "discard_me").order_by(ParseIssue.id)
        ).scalars().first()
        discard_issue = session.execute(
            select(ParseIssue).where(ParseIssue.reason == "discard_me")
        ).scalar_one()
        issue_question = issue.question
        discard_issue_question = discard_issue.question

    assert true_false_question is not None
    assert short_answer_question is not None
    assert multi_select_question is not None
    assert issue is not None

    preview_response = client.get(f"/api/questions/{true_false_question.id}/preview.png")
    assert preview_response.status_code == 200
    assert preview_response.headers["content-type"] == "image/png"
    assert preview_response.content

    true_false_attempt = client.post(
        "/api/attempts",
        json={"question_id": true_false_question.id, "selected_index": 1},
    )
    true_false_payload = true_false_attempt.json()
    assert true_false_payload["is_correct"] is True
    assert true_false_payload["correct_text"] == "O"

    short_answer_attempt = client.post(
        "/api/attempts",
        json={"question_id": short_answer_question.id, "answer_input": "definitely-wrong"},
    )
    short_answer_payload = short_answer_attempt.json()
    assert short_answer_payload["is_correct"] is False
    assert short_answer_payload["correct_text"] == short_answer_question.answer_text

    multi_select_attempt = client.post(
        "/api/attempts",
        json={"question_id": multi_select_question.id, "selected_indices": [1, 2]},
    )
    multi_select_payload = multi_select_attempt.json()
    assert multi_select_payload["is_correct"] is False
    assert "④" in multi_select_payload["correct_text"]

    wrong_response = client.get("/api/decks/1/next?mode=wrong")
    assert wrong_response.json()["question"]["id"] in {short_answer_question.id, multi_select_question.id}

    review_response = client.get("/review")
    assert review_response.status_code == 200
    assert "해설" in review_response.text
    assert "단독 편집" in review_response.text
    assert "문항 버리기" in review_response.text

    manual_review_page = client.get(f"/review/questions/{true_false_question.id}")
    assert manual_review_page.status_code == 200
    assert "문항 수동 검수" in manual_review_page.text

    manual_update_response = client.post(
        f"/api/questions/{true_false_question.id}/review",
        data={
            "stem": true_false_question.stem,
            "question_kind": "true_false",
            "answer_text": "X",
            "explanation_text": "수동으로 정답을 바로잡았습니다.",
        },
        follow_redirects=False,
    )
    assert manual_update_response.status_code == 303

    discard_response = client.post(
        f"/api/review/{discard_issue.id}/discard",
        follow_redirects=False,
    )
    assert discard_response.status_code == 303

    resolve_response = client.post(
        f"/api/review/{issue.id}",
        data={
            "stem": issue_question.stem,
            "question_kind": "multiple_choice",
            "choice_1": issue_question.choice_1 or "㉠",
            "choice_2": issue_question.choice_2 or "㉡",
            "choice_3": issue_question.choice_3 or "㉠, ㉡",
            "choice_4": issue_question.choice_4 or "없음",
            "choice_5": issue_question.choice_5 or "기타",
            "correct_index": 3,
            "explanation_text": "검수로 정답을 보완했습니다.",
        },
        follow_redirects=False,
    )
    assert resolve_response.status_code == 303

    with session_scope() as session:
        updated_question = session.get(Question, issue_question.id)
        updated_issue = session.get(ParseIssue, issue.id)
        discarded_issue = session.get(ParseIssue, discard_issue.id)
        discarded_question = session.get(Question, discard_issue_question.id)
        manually_reviewed_question = session.get(Question, true_false_question.id)
        assert updated_question is not None
        assert updated_question.is_approved is True
        assert updated_question.correct_index == 3
        assert updated_question.explanation_text == "검수로 정답을 보완했습니다."
        assert updated_question.manual_reviewed is True
        assert updated_issue is not None
        assert updated_issue.status == "resolved"
        assert discarded_issue is not None
        assert discarded_issue.status == "discarded"
        assert discarded_question is not None
        assert discarded_question.is_approved is False
        assert discarded_question.manual_reviewed is False
        assert manually_reviewed_question is not None
        assert manually_reviewed_question.answer_text == "X"
        assert manually_reviewed_question.manual_reviewed is True

        reviewed_payload = question_to_payload(manually_reviewed_question)
        assert reviewed_payload["manual_reviewed"] is True
        assert reviewed_payload["review_url"] == f"/review/questions/{manually_reviewed_question.id}"

    review_after_discard = client.get("/review")
    assert review_after_discard.status_code == 200
    assert "이건 실제 문항이 아닌 잘못 잡힌 조각입니다." not in review_after_discard.text
