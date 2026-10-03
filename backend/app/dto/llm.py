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
        return None if value in ([], "") else value

