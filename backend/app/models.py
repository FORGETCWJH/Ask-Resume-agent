from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


def uid() -> str:
    return str(uuid4())


class MaterialSet(Base):
    __tablename__ = "material_sets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(200))
    active_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class MaterialRevision(Base):
    __tablename__ = "material_revisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    material_set_id: Mapped[str] = mapped_column(ForeignKey("material_sets.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Material(Base):
    __tablename__ = "materials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    revision_id: Mapped[str] = mapped_column(ForeignKey("material_revisions.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="processing")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class EvidenceChunk(Base):
    __tablename__ = "evidence_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    material_id: Mapped[str] = mapped_column(ForeignKey("materials.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text)
    source_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_order: Mapped[int] = mapped_column(Integer, default=0)


class ResumeExtractionDraft(Base):
    __tablename__ = "resume_extraction_drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    material_id: Mapped[str] = mapped_column(ForeignKey("materials.id", ondelete="CASCADE"), index=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("material_revisions.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    draft_json: Mapped[str] = mapped_column(Text, default="{}")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    confirmed_sections_json: Mapped[str] = mapped_column(Text, default="[]")
    extractor_version: Mapped[str] = mapped_column(String(80), default="resume-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class ResumeEvidenceLink(Base):
    __tablename__ = "resume_evidence_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    draft_id: Mapped[str] = mapped_column(ForeignKey("resume_extraction_drafts.id", ondelete="CASCADE"), index=True)
    section: Mapped[str] = mapped_column(String(40), index=True)
    field_path: Mapped[str] = mapped_column(String(240))
    evidence_chunk_id: Mapped[str] = mapped_column(ForeignKey("evidence_chunks.id", ondelete="CASCADE"), index=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    origin: Mapped[str] = mapped_column(String(24), default="model")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    revision_id: Mapped[str] = mapped_column(ForeignKey("material_revisions.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="新的练习")
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    mode: Mapped[str | None] = mapped_column(String(40), nullable=True)
    response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CandidateSupplement(Base):
    __tablename__ = "candidate_supplements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    material_set_id: Mapped[str] = mapped_column(ForeignKey("material_sets.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text)
    evidence_gap: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="unconfirmed")
    source_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class QuestionVersion(Base):
    __tablename__ = "question_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("material_revisions.id", ondelete="CASCADE"), index=True)
    scope_json: Mapped[str] = mapped_column(Text, default="{}")
    scope_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    questions_json: Mapped[str] = mapped_column(Text, default="[]")
    prompt_version: Mapped[str] = mapped_column(String(40), default="question-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PracticeTurn(Base):
    __tablename__ = "practice_turns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("material_revisions.id", ondelete="CASCADE"), index=True)
    question_version_id: Mapped[str] = mapped_column(ForeignKey("question_versions.id", ondelete="CASCADE"), index=True)
    parent_turn_id: Mapped[str | None] = mapped_column(ForeignKey("practice_turns.id", ondelete="CASCADE"), nullable=True, index=True)
    question_index: Mapped[int] = mapped_column(Integer, default=0)
    question_text: Mapped[str] = mapped_column(Text)
    question_json: Mapped[str] = mapped_column(Text, default="{}")
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class PracticeAnswer(Base):
    __tablename__ = "practice_answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    turn_id: Mapped[str] = mapped_column(ForeignKey("practice_turns.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PracticeFeedback(Base):
    __tablename__ = "practice_feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    turn_id: Mapped[str] = mapped_column(ForeignKey("practice_turns.id", ondelete="CASCADE"), index=True)
    answer_id: Mapped[str] = mapped_column(ForeignKey("practice_answers.id", ondelete="CASCADE"), index=True)
    prompt_version: Mapped[str] = mapped_column(String(40), default="feedback-v1")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CodeEvidenceSnapshot(Base):
    __tablename__ = "code_evidence_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    revision_id: Mapped[str] = mapped_column(ForeignKey("material_revisions.id", ondelete="CASCADE"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ReferenceAnswer(Base):
    __tablename__ = "reference_answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    turn_id: Mapped[str] = mapped_column(ForeignKey("practice_turns.id", ondelete="CASCADE"), index=True)
    question_version_id: Mapped[str] = mapped_column(ForeignKey("question_versions.id", ondelete="CASCADE"), index=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("material_revisions.id", ondelete="CASCADE"), index=True)
    question_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    code_snapshot_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    answer_json: Mapped[str] = mapped_column(Text, default="{}")
    prompt_version: Mapped[str] = mapped_column(String(40), default="reference-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LlmRun(Base):
    __tablename__ = "llm_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    turn_id: Mapped[str | None] = mapped_column(ForeignKey("practice_turns.id", ondelete="CASCADE"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    request_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
