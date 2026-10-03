from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from .base import ApiModel


class MaterialSetCreate(ApiModel):
    title: str = Field(min_length=1, max_length=200)


class MaterialSummary(ApiModel):
    id: str
    kind: str
    filename: str
    status: str
    size_bytes: int
    error_message: str | None = None


class MaterialSetOut(ApiModel):
    id: str
    title: str
    active_revision_id: str | None
    materials: list[MaterialSummary] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class EvidenceOut(ApiModel):
    id: str
    material_id: str | None = None
    content: str
    source_path: str | None = None
    page_number: int | None = None
    line_start: int | None = None
    line_end: int | None = None


class RecognitionOut(ApiModel):
    material_id: str
    revision_id: str
    material_status: str
    recognition_status: str
    draft: dict[str, Any]
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    confirmed_sections: list[str] = Field(default_factory=list)
    evidence_links: dict[str, list[str]] = Field(default_factory=dict)


class RecognitionPatch(ApiModel):
    draft: dict[str, Any]


class RecognitionRetry(ApiModel):
    scope: Literal["ocr", "recognition", "all"] = "recognition"
    page_number: int | None = Field(default=None, ge=1)


class RecognitionConfirm(ApiModel):
    section: Literal["personalInfo", "skills", "workExperiences", "projects", "all"]
