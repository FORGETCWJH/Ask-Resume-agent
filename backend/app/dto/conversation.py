from datetime import datetime

from pydantic import Field, model_validator

from .base import ApiModel


class ConversationCreate(ApiModel):
    title: str = Field(default="新的练习", max_length=200)


class ConversationPatch(ApiModel):
    title: str | None = Field(default=None, max_length=200)
    is_pinned: bool | None = None
    group_id: str | None = None
    is_archived: bool | None = None

    @model_validator(mode="after")
    def at_least_one_field(self):
        if not self.model_fields_set:
            raise ValueError("至少提供一个对话管理字段")
        return self


class ConversationGroupCreate(ApiModel):
    name: str = Field(min_length=1, max_length=80)


class ConversationGroupOut(ApiModel):
    id: str
    material_set_id: str
    name: str
    created_at: datetime
    updated_at: datetime


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
    group_id: str | None = None
    title: str
    summary: str
    messages: list[MessageOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    is_pinned: bool = False
    pinned_at: datetime | None = None
    is_archived: bool = False
    archived_at: datetime | None = None
    last_activity_at: datetime


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

