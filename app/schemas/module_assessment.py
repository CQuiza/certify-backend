"""Esquemas de evaluaciones por módulo."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaskProgressItem(BaseModel):
    task_id: int
    task_title: str
    submitted: bool
    submission_id: int | None = None
    file_url: str | None = None
    original_filename: str | None = None
    submitted_at: datetime | None = None
    score: float | None = None
    feedback: str | None = None
    passed: bool = False
    graded_at: datetime | None = None


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

    @model_validator(mode="after")
    def _validate_correct_option(self) -> "AssessmentQuestionCreate":
        correct = sum(1 for o in self.options if o.is_correct)
        if self.question_type == "multiple_choice":
            if len(self.options) < 2:
                raise ValueError("Una pregunta de opción múltiple debe tener al menos 2 opciones")
            if correct != 1:
                raise ValueError("Debes marcar exactamente una respuesta correcta")
        else:
            if len(self.options) != 2:
                raise ValueError("Una pregunta de verdadero/falso debe tener 2 opciones")
            if correct != 1:
                raise ValueError("Debes marcar exactamente una respuesta correcta")
        return self


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
    passing_score: int = Field(default=70, ge=1, le=100)
    questions: list[AssessmentQuestionCreate] = Field(..., min_length=1)


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
    total_tasks: int = 0
    submitted_tasks: int = 0
    tasks: list[TaskProgressItem] = []


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
