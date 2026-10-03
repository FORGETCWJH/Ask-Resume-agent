from datetime import datetime

from pydantic import Field

from .base import ApiModel


class ConversationCreate(ApiModel):
    title: str = Field(default="新的练习", max_length=200)


class Selection(ApiModel):
    material_id: str
    text: str
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)


class MessageCreate(ApiModel):
    content: str = Field(min_length=1, max_length=20_000)
    mode: str = "selectedPassageQuestion"
    selection: Selection | None = None


class SupplementUpdate(ApiModel):
    content: str = Field(min_length=1, max_length=20_000)


class MessageOut(ApiModel):
    id: str
    role: str
    content: str
    mode: str | None = None
    response: dict | None = None
    created_at: datetime


class ConversationOut(ApiModel):
    id: str
    revision_id: str
    title: str
    summary: str
    messages: list[MessageOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class SupplementOut(ApiModel):
    id: str
    content: str
    status: str
    confirmed: bool


class QuestionBatchOut(ApiModel):
    id: str
    conversation_id: str
    status: str
    questions: list[dict] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)

