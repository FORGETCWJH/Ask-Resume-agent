from datetime import datetime

from pydantic import Field

from .base import ApiModel


class QuestionScope(ApiModel):
    project_ids: list[str] = Field(default_factory=list)
    resume_sections: list[str] = Field(default_factory=list)
    selected_text: str | None = None
    scope_type: str | None = None
    target_ids: list[str] = Field(default_factory=list)
    topic: str | None = None
    question_type: str | None = None
    difficulty: str | None = None
    direction: str | None = Field(default=None, max_length=500)
    count: int = Field(default=5, ge=1, le=20)
    new_version: bool = False


class LlmRunCreateOut(ApiModel):
    run_id: str
    status: str
    run_type: str | None = None
    conversation_id: str | None = None
    practice_turn_id: str | None = None


class LlmRunOut(ApiModel):
    id: str
    status: str
    kind: str
    conversation_id: str | None = None
    practice_turn_id: str | None = None
    result: dict | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class PracticeAnswerCreate(ApiModel):
    content: str = Field(min_length=1, max_length=30_000)


class PracticeTurnOut(ApiModel):
    id: str
    question: str
    question_data: dict = Field(default_factory=dict)
    answer: str | None = None
    answer_id: str | None = None
    answer_version: int | None = None
    parent_turn_id: str | None = None
    feedback: dict | None = None
    reference_answer: dict | None = None
    created_at: datetime
    updated_at: datetime


class PracticeTurnListOut(ApiModel):
    items: list[PracticeTurnOut] = Field(default_factory=list)


class PracticeAnswerOut(ApiModel):
    turn_id: str
    answer: str
    answer_id: str | None = None
    answer_version: int = 1
    saved_at: datetime
