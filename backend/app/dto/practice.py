from typing import Literal
from pydantic import Field
from .base import ApiModel


class PracticeInputCreate(ApiModel):
    content: str = Field(min_length=1, max_length=30000)
    client_request_id: str = Field(min_length=1, max_length=80)


class NavigationCreate(ApiModel):
    action: Literal["nextQuestion"]
    client_request_id: str = Field(min_length=1, max_length=80)


class PreferencePatch(ApiModel):
    value: str | int
    expected_revision: int = Field(ge=1)
