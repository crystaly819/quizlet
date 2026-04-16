from __future__ import annotations

import json
from pathlib import Path

import fitz
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select

from .config import Settings
from .database import configure_database, init_db, session_scope
from .ingest_service import ingest_pdf_directory
from .models import Attempt, Deck, ParseIssue, Question
from .parser import choice_label_for_index, compact_text, extract_choice_indices_from_text


class AttemptPayload(BaseModel):
    question_id: int
    selected_index: int | None = Field(default=None, ge=1)
    selected_indices: list[int] | None = None
    was_correct: bool | None = None
    answer_input: str | None = None


def normalize_answer_text(value: str | None) -> str:
    return compact_text((value or "").lower())


def resolve_source_pdf_path(settings: Settings, source_pdf: str) -> Path:
    if "::" in source_pdf:
        source_pdf = source_pdf.split("::", 1)[0]
    if "#" in source_pdf:
        source_pdf = source_pdf.split("#", 1)[0]
    path = Path(source_pdf)
    if path.is_absolute():
        return path
    return settings.base_dir / source_pdf


def preview_url_for_question(question: Question) -> str | None:
    if not question.source_bbox:
        return None
    try:
        bbox = json.loads(question.source_bbox)
    except json.JSONDecodeError:
        return None
    return f"/api/questions/{question.id}/preview.png" if isinstance(bbox, list) and len(bbox) == 4 else None


def review_url_for_question(question: Question) -> str:
    return f"/review/questions/{question.id}"


def deck_questions_url(deck_id: int, *, saved_question_id: int | None = None) -> str:
    url = f"/decks/{deck_id}/questions"
    if saved_question_id is not None:
        return f"{url}?saved={saved_question_id}#question-{saved_question_id}"
    return url


def question_to_payload(question: Question) -> dict:
    if question.question_kind == "true_false":
        choices = ["O", "X"]
    else:
        choices = question.get_choices()
    return {
        "id": question.id,
        "number": question.number,
        "page_number": question.page_number,
        "question_kind": question.question_kind,
        "stem": question.stem,
        "answer_text": question.answer_text,
        "explanation_text": question.explanation_text,
        "choices": [{"index": index, "text": text} for index, text in enumerate(choices, start=1)],
        "crop_url": preview_url_for_question(question),
        "manual_reviewed": question.manual_reviewed,
        "review_url": review_url_for_question(question),
    }


def build_multi_select_correct_text(choices: list[str], answer_indices: list[int]) -> str:
    parts: list[str] = []
    for index in answer_indices:
        if 1 <= index <= len(choices):
            parts.append(f"{choice_label_for_index(index)} {choices[index - 1]}")
        else:
            parts.append(choice_label_for_index(index))
    return ", ".join(parts)


def build_review_entry(question: Question, deck: Deck, issue: ParseIssue | None = None) -> dict:
    payload_pretty = None
    if issue is not None:
        payload_pretty = json.dumps(json.loads(issue.payload_json), ensure_ascii=False, indent=2)
    return {
        "issue": issue,
        "deck": deck,
        "question": question,
        "preview_url": preview_url_for_question(question),
        "choices": list(enumerate(question.get_choices(), start=1)),
        "payload_pretty": payload_pretty,
        "review_url": review_url_for_question(question),
    }


def collect_choices_from_form(form) -> list[str]:
    choice_pairs: list[tuple[int, str]] = []
    for key, value in form.items():
        if not key.startswith("choice_"):
            continue
        try:
            index = int(key.split("_", 1)[1])
        except ValueError:
            continue
        choice_pairs.append((index, str(value).strip()))
    return [choice for _, choice in sorted(choice_pairs) if choice]


def next_question_number(session, deck_id: int) -> int:
    current_max = session.execute(
        select(func.max(Question.number)).where(Question.deck_id == deck_id)
    ).scalar_one()
    return (current_max or 0) + 1


def next_page_number(session, deck_id: int) -> int:
    current_max = session.execute(
        select(func.max(Question.page_number)).where(Question.deck_id == deck_id)
    ).scalar_one()
    return current_max or 1


def apply_question_review(
    question: Question,
    *,
    stem: str,
    answer_text: str,
    explanation_text: str,
    question_kind: str,
    correct_index: int,
    choices: list[str],
) -> None:
    filtered_choices = [choice.strip() for choice in choices if choice.strip()]
    cleaned_stem = stem.strip()
    if not cleaned_stem:
        raise HTTPException(status_code=400, detail="Stem is required.")

    question.stem = cleaned_stem
    question.question_kind = question_kind
    if question_kind in {"flashcard", "short_answer", "true_false"}:
        if not answer_text.strip():
            raise HTTPException(status_code=400, detail="Answer text is required.")
        question.answer_text = answer_text.strip()
        question.explanation_text = explanation_text.strip() or None
        question.set_choices([])
        question.correct_index = None
    elif question_kind == "multi_select":
        if not filtered_choices:
            raise HTTPException(status_code=400, detail="At least one choice is required.")
        if not answer_text.strip():
            raise HTTPException(status_code=400, detail="Answer text is required.")
        question.answer_text = answer_text.strip()
        question.explanation_text = explanation_text.strip() or None
        question.set_choices(filtered_choices)
        question.correct_index = None
    else:
        if not filtered_choices:
            raise HTTPException(status_code=400, detail="At least one choice is required.")
        if correct_index < 1 or correct_index > len(filtered_choices):
            raise HTTPException(status_code=400, detail="Correct index is out of range.")
        question.answer_text = None
        question.explanation_text = explanation_text.strip() or None
        question.set_choices(filtered_choices)
        question.correct_index = correct_index

    question.confidence = max(question.confidence, 0.8)
    question.is_approved = True
    question.manual_reviewed = True


def next_question_for_mode(deck_id: int, mode: str) -> Question | None:
    with session_scope() as session:
        statement = select(Question).where(Question.deck_id == deck_id, Question.is_approved.is_(True))
        if mode == "unseen":
            attempted = select(Attempt.question_id)
            statement = statement.where(~Question.id.in_(attempted))
        elif mode == "wrong":
            wrong_attempts = select(Attempt.question_id).where(Attempt.is_correct.is_(False))
            statement = statement.where(Question.id.in_(wrong_attempts))

        question = session.execute(statement.order_by(func.random()).limit(1)).scalar_one_or_none()
        return question


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.ensure_dirs()
    configure_database(settings.database_url)
    init_db()

    app = FastAPI(title="수정 예시 문제집")
    app.state.settings = settings
    app.state.templates = Jinja2Templates(directory=str(settings.template_dir))
    app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
    app.mount("/data", StaticFiles(directory=str(settings.data_dir)), name="data")

    @app.on_event("startup")
    def startup() -> None:
        if not settings.auto_ingest or not settings.pdf_dir.exists():
            return
        with session_scope() as session:
            deck_total = session.execute(select(func.count(Deck.id))).scalar_one()
        if deck_total == 0:
            ingest_pdf_directory(settings.pdf_dir, settings, rebuild=False)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        with session_scope() as session:
            rows = session.execute(
                select(Deck, func.count(ParseIssue.id))
                .outerjoin(Question, Question.deck_id == Deck.id)
                .outerjoin(
                    ParseIssue,
                    and_(ParseIssue.question_id == Question.id, ParseIssue.status == "open"),
                )
                .group_by(Deck.id)
                .order_by(Deck.title)
            ).all()
            open_issue_total = session.execute(
                select(func.count(ParseIssue.id)).where(ParseIssue.status == "open")
            ).scalar_one()

        deck_rows = [{"deck": deck, "open_issues": open_issues} for deck, open_issues in rows]
        return app.state.templates.TemplateResponse(
            request,
            "index.html",
            {
                "decks": deck_rows,
                "open_issue_total": open_issue_total,
            },
        )

    @app.get("/timer", response_class=HTMLResponse)
    def timer_page(request: Request) -> HTMLResponse:
        return app.state.templates.TemplateResponse(
            request,
            "timer.html",
            {
                "focus_minutes": 90,
                "break_minutes": 15,
            },
        )

    @app.get("/decks/{deck_id}/study", response_class=HTMLResponse)
    def study_page(request: Request, deck_id: int, mode: str = "all") -> HTMLResponse:
        if mode not in {"all", "unseen", "wrong"}:
            raise HTTPException(status_code=400, detail="Unsupported study mode.")
        with session_scope() as session:
            deck = session.get(Deck, deck_id)
            if deck is None:
                raise HTTPException(status_code=404, detail="Deck not found.")

            approved_count = session.execute(
                select(func.count(Question.id)).where(
                    Question.deck_id == deck_id,
                    Question.is_approved.is_(True),
                )
            ).scalar_one()
            wrong_count = session.execute(
                select(func.count(func.distinct(Attempt.question_id)))
                .join(Question, Question.id == Attempt.question_id)
                .where(Question.deck_id == deck_id, Attempt.is_correct.is_(False))
            ).scalar_one()
            seen_count = session.execute(
                select(func.count(func.distinct(Attempt.question_id)))
                .join(Question, Question.id == Attempt.question_id)
                .where(Question.deck_id == deck_id)
            ).scalar_one()

        return app.state.templates.TemplateResponse(
            request,
            "study.html",
            {
                "deck": deck,
                "mode": mode,
                "approved_count": approved_count,
                "seen_count": seen_count,
                "wrong_count": wrong_count,
            },
        )

    @app.get("/decks/{deck_id}/questions", response_class=HTMLResponse)
    def deck_questions_page(request: Request, deck_id: int, saved: int = 0) -> HTMLResponse:
        with session_scope() as session:
            deck = session.get(Deck, deck_id)
            if deck is None:
                raise HTTPException(status_code=404, detail="Deck not found.")

            questions = session.execute(
                select(Question)
                .where(Question.deck_id == deck_id)
                .order_by(Question.page_number, Question.number, Question.id)
            ).scalars().all()

            entries = [build_review_entry(question, deck, question.parse_issue) for question in questions]
            suggested_number = next_question_number(session, deck_id)
            suggested_page_number = next_page_number(session, deck_id)

        return app.state.templates.TemplateResponse(
            request,
            "deck_questions.html",
            {
                "deck": deck,
                "entries": entries,
                "saved_question_id": saved if saved else None,
                "suggested_number": suggested_number,
                "suggested_page_number": suggested_page_number,
            },
        )

    @app.get("/api/decks/{deck_id}/next")
    def next_question(deck_id: int, mode: str = "all") -> dict:
        if mode not in {"all", "unseen", "wrong"}:
            raise HTTPException(status_code=400, detail="Unsupported study mode.")

        question = next_question_for_mode(deck_id, mode)
        if question is None:
            return {"question": None}
        return {"question": question_to_payload(question)}

    @app.post("/api/decks/{deck_id}/questions")
    async def create_question(
        request: Request,
        deck_id: int,
        stem: str = Form(...),
        answer_text: str = Form(""),
        explanation_text: str = Form(""),
        question_kind: str = Form("multiple_choice"),
        correct_index: int = Form(1),
        page_number: int = Form(...),
        number: str = Form(""),
    ) -> RedirectResponse:
        form = await request.form()
        choices = collect_choices_from_form(form)

        with session_scope() as session:
            deck = session.get(Deck, deck_id)
            if deck is None:
                raise HTTPException(status_code=404, detail="Deck not found.")

            question_number = int(number) if str(number).strip() else next_question_number(session, deck_id)
            question = Question(
                deck_id=deck_id,
                number=question_number,
                page_number=page_number,
                question_kind=question_kind,
                stem=stem.strip(),
                confidence=1.0,
                source_bbox="",
                crop_path=None,
                is_approved=True,
                manual_reviewed=True,
            )
            session.add(question)
            session.flush()

            apply_question_review(
                question,
                stem=stem,
                answer_text=answer_text,
                explanation_text=explanation_text,
                question_kind=question_kind,
                correct_index=correct_index,
                choices=choices,
            )

            deck.question_count = session.execute(
                select(func.count(Question.id)).where(Question.deck_id == deck_id)
            ).scalar_one()

        return RedirectResponse(
            url=deck_questions_url(deck_id, saved_question_id=question.id),
            status_code=303,
        )

    @app.get("/api/questions/{question_id}/preview.png")
    def question_preview(question_id: int) -> Response:
        with session_scope() as session:
            question = session.get(Question, question_id)
            if question is None:
                raise HTTPException(status_code=404, detail="Question not found.")
            deck = question.deck
            if deck is None:
                raise HTTPException(status_code=404, detail="Deck not found.")
            try:
                bbox = json.loads(question.source_bbox)
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail="Invalid source bbox.") from exc
            if not isinstance(bbox, list) or len(bbox) != 4:
                raise HTTPException(status_code=404, detail="Preview crop not available.")
            source_pdf = deck.source_pdf
            page_number = question.page_number

        pdf_path = resolve_source_pdf_path(settings, source_pdf)
        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail="Source PDF not found.")

        document = fitz.open(pdf_path)
        try:
            if page_number < 1 or page_number > document.page_count:
                raise HTTPException(status_code=404, detail="Source page not found.")
            page = document[page_number - 1]
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=fitz.Rect(*bbox), alpha=False)
            return Response(content=pixmap.tobytes("png"), media_type="image/png")
        finally:
            document.close()

    @app.post("/api/attempts")
    def create_attempt(payload: AttemptPayload) -> dict:
        with session_scope() as session:
            question = session.get(Question, payload.question_id)
            if question is None or not question.is_approved:
                raise HTTPException(status_code=404, detail="Question not found.")

            if question.question_kind == "flashcard":
                if payload.was_correct is None:
                    raise HTTPException(status_code=400, detail="Flashcard attempts require self-evaluation.")
                attempt = Attempt(
                    question_id=question.id,
                    selected_index=1 if payload.was_correct else 0,
                    is_correct=payload.was_correct,
                )
                session.add(attempt)
                return {
                    "is_correct": attempt.is_correct,
                    "correct_index": None,
                    "correct_text": question.answer_text,
                    "question_kind": "flashcard",
                    "explanation_text": question.explanation_text,
                }

            if question.question_kind == "short_answer":
                submitted = (payload.answer_input or "").strip()
                if not submitted:
                    raise HTTPException(status_code=400, detail="Answer input is required.")
                is_correct = normalize_answer_text(submitted) == normalize_answer_text(question.answer_text)
                attempt = Attempt(
                    question_id=question.id,
                    selected_index=1 if is_correct else 0,
                    is_correct=is_correct,
                )
                session.add(attempt)
                return {
                    "is_correct": attempt.is_correct,
                    "correct_index": None,
                    "correct_text": question.answer_text,
                    "question_kind": "short_answer",
                    "explanation_text": question.explanation_text,
                }

            if question.question_kind == "true_false":
                if payload.selected_index is None:
                    raise HTTPException(status_code=400, detail="O/X choice is required.")
                if payload.selected_index not in {1, 2}:
                    raise HTTPException(status_code=400, detail="O/X choice must be 1 or 2.")
                selected_value = "O" if payload.selected_index == 1 else "X"
                attempt = Attempt(
                    question_id=question.id,
                    selected_index=payload.selected_index,
                    is_correct=normalize_answer_text(selected_value) == normalize_answer_text(question.answer_text),
                )
                session.add(attempt)
                return {
                    "is_correct": attempt.is_correct,
                    "correct_index": 1 if normalize_answer_text(question.answer_text) == "o" else 2,
                    "correct_text": question.answer_text,
                    "question_kind": "true_false",
                    "explanation_text": question.explanation_text,
                }

            if question.question_kind == "multi_select":
                choices = question.get_choices()
                selected_indices = sorted(set(payload.selected_indices or []))
                if not selected_indices:
                    raise HTTPException(status_code=400, detail="At least one choice is required.")
                if any(index < 1 or index > len(choices) for index in selected_indices):
                    raise HTTPException(status_code=400, detail="Choice index is out of range.")

                correct_indices = extract_choice_indices_from_text(question.answer_text)
                attempt = Attempt(
                    question_id=question.id,
                    selected_index=0,
                    is_correct=selected_indices == correct_indices,
                )
                session.add(attempt)
                return {
                    "is_correct": attempt.is_correct,
                    "correct_indices": correct_indices,
                    "correct_text": build_multi_select_correct_text(choices, correct_indices),
                    "question_kind": "multi_select",
                    "explanation_text": question.explanation_text,
                }

            if payload.selected_index is None:
                raise HTTPException(status_code=400, detail="Choice index is required.")

            choices = question.get_choices()
            if payload.selected_index > len(choices):
                raise HTTPException(status_code=400, detail="Choice index is out of range.")

            attempt = Attempt(
                question_id=question.id,
                selected_index=payload.selected_index,
                is_correct=payload.selected_index == question.correct_index,
            )
            session.add(attempt)

            correct_index = question.correct_index
            correct_text = choices[correct_index - 1] if correct_index else None

            return {
                "is_correct": attempt.is_correct,
                "correct_index": correct_index,
                "correct_text": correct_text,
                "question_kind": "multiple_choice",
                "explanation_text": question.explanation_text,
            }

    @app.get("/review", response_class=HTMLResponse)
    def review_page(request: Request) -> HTMLResponse:
        with session_scope() as session:
            rows = session.execute(
                select(ParseIssue, Question, Deck)
                .join(Question, ParseIssue.question_id == Question.id)
                .join(Deck, Question.deck_id == Deck.id)
                .where(ParseIssue.status == "open")
                .order_by(Deck.title, Question.page_number, Question.number)
            ).all()

        issues = [build_review_entry(question, deck, issue) for issue, question, deck in rows]

        return app.state.templates.TemplateResponse(
            request,
            "review.html",
            {"issues": issues},
        )

    @app.get("/review/questions/{question_id}", response_class=HTMLResponse)
    def review_question_page(request: Request, question_id: int, saved: int = 0) -> HTMLResponse:
        with session_scope() as session:
            question = session.get(Question, question_id)
            if question is None:
                raise HTTPException(status_code=404, detail="Question not found.")
            deck = question.deck
            if deck is None:
                raise HTTPException(status_code=404, detail="Deck not found.")
            issue = question.parse_issue

        return app.state.templates.TemplateResponse(
            request,
            "review_question.html",
            {
                "entry": build_review_entry(question, deck, issue),
                "saved": bool(saved),
            },
        )

    @app.post("/api/review/{issue_id}")
    async def resolve_issue(
        request: Request,
        issue_id: int,
        stem: str = Form(...),
        answer_text: str = Form(""),
        explanation_text: str = Form(""),
        question_kind: str = Form("multiple_choice"),
        correct_index: int = Form(1),
    ) -> RedirectResponse:
        form = await request.form()
        filtered_choices = collect_choices_from_form(form)
        redirect_to = str(form.get("redirect_to") or "/review")

        with session_scope() as session:
            issue = session.get(ParseIssue, issue_id)
            if issue is None:
                raise HTTPException(status_code=404, detail="Issue not found.")
            question = issue.question
            apply_question_review(
                question,
                stem=stem,
                answer_text=answer_text,
                explanation_text=explanation_text,
                question_kind=question_kind,
                correct_index=correct_index,
                choices=filtered_choices,
            )
            issue.status = "resolved"

        return RedirectResponse(url=redirect_to, status_code=303)

    @app.post("/api/review/{issue_id}/discard")
    async def discard_issue(request: Request, issue_id: int) -> RedirectResponse:
        form = await request.form()
        redirect_to = str(form.get("redirect_to") or "/review")
        with session_scope() as session:
            issue = session.get(ParseIssue, issue_id)
            if issue is None:
                raise HTTPException(status_code=404, detail="Issue not found.")
            question = issue.question
            question.is_approved = False
            question.manual_reviewed = False
            issue.status = "discarded"

        return RedirectResponse(url=redirect_to, status_code=303)

    @app.post("/api/questions/{question_id}/review")
    async def review_question(
        request: Request,
        question_id: int,
        stem: str = Form(...),
        answer_text: str = Form(""),
        explanation_text: str = Form(""),
        question_kind: str = Form("multiple_choice"),
        correct_index: int = Form(1),
    ) -> RedirectResponse:
        form = await request.form()
        choices = collect_choices_from_form(form)
        redirect_to = str(form.get("redirect_to") or "")

        with session_scope() as session:
            question = session.get(Question, question_id)
            if question is None:
                raise HTTPException(status_code=404, detail="Question not found.")
            apply_question_review(
                question,
                stem=stem,
                answer_text=answer_text,
                explanation_text=explanation_text,
                question_kind=question_kind,
                correct_index=correct_index,
                choices=choices,
            )
            if question.parse_issue is not None:
                question.parse_issue.status = "resolved"
            if not redirect_to:
                redirect_to = f"/review/questions/{question_id}?saved=1"
            elif redirect_to == "__deck_questions__":
                redirect_to = deck_questions_url(question.deck_id, saved_question_id=question.id)

        return RedirectResponse(url=redirect_to, status_code=303)

    return app


app = create_app()
