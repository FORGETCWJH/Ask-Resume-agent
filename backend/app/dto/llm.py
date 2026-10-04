from typing import Any

from pydantic import Field, field_validator

from .base import ApiModel


class StructuredResponse(ApiModel):
    answer: str = ""
    questions: list[dict] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    inference_drafts: list[dict] = Field(default_factory=list)
    evidence_gaps: list[dict] = Field(default_factory=list)
    feedback: dict | None = None

    @field_validator("feedback", mode="before")
    @classmethod
    def normalize_empty_feedback(cls, value):
        if value in ([], "", None):
            return None
        if isinstance(value, str):
            return {"text": value}
        return value

    @field_validator("questions", "evidence", "inference_drafts", "evidence_gaps", mode="before")
    @classmethod
    def normalize_object_lists(cls, value: Any):
        if value in (None, ""):
            return []
        if isinstance(value, str):
            return [{"text": value}]
        if isinstance(value, list):
            return [{"text": item} if isinstance(item, str) else item for item in value]
        return value


class QuestionItem(ApiModel):
    text: str
    type: str = "implementation"
    evidence_ids: list[str] = Field(default_factory=list)


class QuestionGenerationResponse(ApiModel):
    questions: list[QuestionItem] = Field(default_factory=list)


class FeedbackResponse(ApiModel):
    summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    missing_points: list[str] = Field(default_factory=list)
    evidence_gaps: list[dict] = Field(default_factory=list)
    next_practice_step: str = ""


class ReferenceAnswerResponse(ApiModel):
    answer: str = ""
    evidence_grade: str = "insufficient"
    evidence: list[dict] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    generic_explanation: str | None = None


class FollowUpQuestionResponse(ApiModel):
    question: str
    reason: str = ""
    evidence_gap: str | None = None

