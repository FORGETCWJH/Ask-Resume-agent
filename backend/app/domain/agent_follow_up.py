"""追问模块的稳定领域规则，不依赖 HTTP、数据库或模型供应商。"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class QuestionScope(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project_ids: list[str] = Field(default_factory=list, alias="projectIds")
    resume_sections: list[str] = Field(default_factory=list, alias="resumeSections")
    selected_text: str | None = Field(default=None, alias="selectedText")
    scope_type: str | None = Field(default=None, alias="scopeType")
    target_ids: list[str] = Field(default_factory=list, alias="targetIds")
    topic: str | None = None
    question_type: str | None = Field(default=None, alias="questionType")
    difficulty: str | None = None
    direction: str | None = None
    count: int = Field(default=5, ge=1, le=20)


class LlmRunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EvidenceGrade(StrEnum):
    DIRECT = "direct"
    INFERRED = "inferred"
    INSUFFICIENT = "insufficient"


_TERMINAL = {LlmRunState.SUCCEEDED, LlmRunState.FAILED, LlmRunState.CANCELLED}


def transition_run(current: LlmRunState, target: LlmRunState) -> LlmRunState:
    if current in _TERMINAL:
        return current
    if target == LlmRunState.QUEUED:
        return current
    if current == LlmRunState.QUEUED and target in {LlmRunState.RUNNING, LlmRunState.CANCELLED}:
        return target
    if current == LlmRunState.RUNNING and target in _TERMINAL:
        return target
    raise ValueError(f"invalid llm run transition: {current} -> {target}")


def fingerprint_scope(scope: QuestionScope | dict[str, Any]) -> str:
    normalized = scope if isinstance(scope, QuestionScope) else QuestionScope.model_validate(scope)
    payload = normalized.model_dump(mode="json", by_alias=True, exclude_none=True)
    payload["projectIds"] = sorted(set(payload.get("projectIds", [])))
    payload["resumeSections"] = sorted(set(payload.get("resumeSections", [])))
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def fingerprint_answer(content: str) -> str:
    return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()


def validate_evidence_grade(value: str | EvidenceGrade) -> EvidenceGrade:
    try:
        return EvidenceGrade(value)
    except ValueError:
        return EvidenceGrade.INSUFFICIENT
