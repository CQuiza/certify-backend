"""Esquemas de evaluaciones por módulo."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AssessmentOptionCreate(BaseModel):
    option_text: str = Field(..., max_length=255)
    is_correct: bool = False


class AssessmentOptionRead(BaseModel):
    id: int
    option_text: str
    model_config = ConfigDict(from_attributes=True)


class AssessmentOptionReadWithCorrect(AssessmentOptionRead):
    is_correct: bool


class AssessmentQuestionCreate(BaseModel):
    question_text: str
    question_type: Literal["multiple_choice", "true_false"]
    points: int = 1
    order_index: int = 0
    options: list[AssessmentOptionCreate]


class AssessmentQuestionRead(BaseModel):
    id: int
    question_text: str
    question_type: str
    points: int
    order_index: int
    options: list[AssessmentOptionRead]
    model_config = ConfigDict(from_attributes=True)


class AssessmentQuestionReadWithCorrect(AssessmentQuestionRead):
    options: list[AssessmentOptionReadWithCorrect]


class ModuleAssessmentCreate(BaseModel):
    passing_score: int = 70
    questions: list[AssessmentQuestionCreate]


class ModuleAssessmentRead(BaseModel):
    id: int
    module_id: int
    passing_score: int
    questions: list[AssessmentQuestionRead]
    model_config = ConfigDict(from_attributes=True)


class ModuleAssessmentReadTeacher(ModuleAssessmentRead):
    questions: list[AssessmentQuestionReadWithCorrect]


class AnswerSubmission(BaseModel):
    question_id: int
    selected_option_id: int


class AssessmentSubmit(BaseModel):
    answers: list[AnswerSubmission]


class AnswerResult(BaseModel):
    question_id: int
    question_text: str
    selected_option_id: int
    is_correct: bool
    correct_option_id: int | None = None


class AttemptResult(BaseModel):
    attempt_id: int
    score: float
    passed: bool
    total_points: int
    earned_points: int
    answers: list[AnswerResult]


class ModuleProgressItem(BaseModel):
    module_id: int
    module_title: str
    module_order: int
    total_assessment_questions: int
    attempts_count: int
    last_score: float | None = None
    passed: bool


class CourseProgressSummary(BaseModel):
    course_id: int
    course_title: str
    total_modules: int
    completed_modules: int
    progress_percent: float
    modules: list[ModuleProgressItem]


class AllProgressSummary(BaseModel):
    courses: list[CourseProgressSummary]
    overall_percent: float


class AttemptRead(BaseModel):
    id: int
    assessment_id: int
    user_id: int
    score: Decimal
    passed: bool
    started_at: datetime
    finished_at: datetime | None
    model_config = ConfigDict(from_attributes=True)
