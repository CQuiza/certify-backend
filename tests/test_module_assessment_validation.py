"""Validaciones del esquema de evaluaciones por módulo."""

import pytest
from pydantic import ValidationError

from app.schemas.module_assessment import (
    AssessmentQuestionCreate,
    ModuleAssessmentCreate,
)


def _options(*correct_indices: int) -> list[dict]:
    return [
        {"option_text": f"opción {i}", "is_correct": i in correct_indices}
        for i in range(3)
    ]


def test_multiple_choice_requires_correct_option():
    with pytest.raises(ValidationError):
        AssessmentQuestionCreate(
            question_text="¿Cuál es la correcta?",
            question_type="multiple_choice",
            options=_options(),
        )


def test_multiple_choice_rejects_multiple_correct_options():
    with pytest.raises(ValidationError):
        AssessmentQuestionCreate(
            question_text="¿Cuál es la correcta?",
            question_type="multiple_choice",
            options=_options(0, 1),
        )


def test_multiple_choice_accepts_single_correct_option():
    question = AssessmentQuestionCreate(
        question_text="¿Cuál es la correcta?",
        question_type="multiple_choice",
        options=_options(1),
    )
    assert sum(o.is_correct for o in question.options) == 1


def test_passing_score_must_be_within_bounds():
    with pytest.raises(ValidationError):
        ModuleAssessmentCreate(passing_score=101, questions=[])
    with pytest.raises(ValidationError):
        ModuleAssessmentCreate(passing_score=0, questions=[])
