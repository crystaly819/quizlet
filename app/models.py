from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .database import Base


class Deck(Base):
    __tablename__ = "decks"

    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    slug = Column(String(80), nullable=False, unique=True)
    source_pdf = Column(String(500), nullable=False, unique=True)
    page_count = Column(Integer, nullable=False, default=0)
    question_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    questions = relationship(
        "Question",
        back_populates="deck",
        cascade="all, delete-orphan",
        order_by="Question.page_number, Question.number",
    )


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True)
    deck_id = Column(Integer, ForeignKey("decks.id", ondelete="CASCADE"), index=True)
    number = Column(Integer, nullable=False)
    page_number = Column(Integer, nullable=False)
    question_kind = Column(String(20), nullable=False, default="multiple_choice")
    stem = Column(Text, nullable=False)
    answer_text = Column(Text)
    explanation_text = Column(Text)
    choices_json = Column(Text)
    choice_1 = Column(Text)
    choice_2 = Column(Text)
    choice_3 = Column(Text)
    choice_4 = Column(Text)
    choice_5 = Column(Text)
    correct_index = Column(Integer)
    confidence = Column(Float, nullable=False, default=0.0)
    source_bbox = Column(Text, nullable=False)
    crop_path = Column(String(500))
    is_approved = Column(Boolean, nullable=False, default=False, index=True)
    manual_reviewed = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    deck = relationship("Deck", back_populates="questions")
    parse_issue = relationship(
        "ParseIssue",
        back_populates="question",
        cascade="all, delete-orphan",
        uselist=False,
    )
    attempts = relationship(
        "Attempt",
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="Attempt.answered_at",
    )

    def get_choices(self) -> list[str]:
        if self.choices_json:
            try:
                values = json.loads(self.choices_json)
            except json.JSONDecodeError:
                values = None
            if isinstance(values, list):
                return [str(choice) for choice in values if str(choice).strip()]
        return [
            choice
            for choice in [self.choice_1, self.choice_2, self.choice_3, self.choice_4, self.choice_5]
            if choice
        ]

    def set_choices(self, choices: list[str]) -> None:
        normalized_choices = [choice for choice in choices if choice]
        self.choices_json = json.dumps(normalized_choices, ensure_ascii=False) if normalized_choices else None
        padded = (choices + [None] * 5)[:5]
        self.choice_1, self.choice_2, self.choice_3, self.choice_4, self.choice_5 = padded


class ParseIssue(Base):
    __tablename__ = "parse_issues"

    id = Column(Integer, primary_key=True)
    question_id = Column(
        Integer,
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    reason = Column(String(255), nullable=False)
    payload_json = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="open", index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    question = relationship("Question", back_populates="parse_issue")


class Attempt(Base):
    __tablename__ = "attempts"

    id = Column(Integer, primary_key=True)
    question_id = Column(Integer, ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    selected_index = Column(Integer, nullable=False)
    is_correct = Column(Boolean, nullable=False)
    answered_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    question = relationship("Question", back_populates="attempts")
