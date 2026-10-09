import json

from sqlalchemy.orm import Session
from sqlalchemy import select

from ..common.errors import AppError, not_found
from ..dto.conversation import ConversationGroupOut, ConversationOut, ConversationPatch, MessageOut, SupplementOut
from ..domain.conversation_history import normalize_group_name, sort_conversations, validate_group_name, validate_title
from ..domain.resume_recognition import redact_personal_context
from ..models import CandidateSupplement, Conversation, ConversationGroup, EvidenceChunk, LlmRun, Material, MaterialRevision, Message, MaterialSet, ResumeExtractionDraft, now
from ..repository.conversation_repository import ConversationRepository
from ..infrastructure.llm import LLMError, request_llm


class ConversationService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ConversationRepository(db)

    def get(self, conversation_id: str) -> Conversation:
        conversation = self.repo.get(conversation_id)
        if not conversation:
            raise not_found("CONVERSATION_NOT_FOUND", "对话不存在")
        return conversation

    def create(self, set_id: str, title: str) -> ConversationOut:
        revision = self.db.query(MaterialRevision).filter(MaterialRevision.material_set_id == set_id).order_by(MaterialRevision.created_at.desc()).first()
        if not revision:
            raise AppError(409, "MATERIAL_NOT_READY", "Material is not ready", "请先上传材料")
        conversation = Conversation(revision_id=revision.id, title=validate_title(title), last_activity_at=now())
        self.db.add(conversation)
        self.db.flush()
        from ..repository.practice_repository import PracticeRepository
        PracticeRepository(self.db).capture(conversation)
        self.db.commit()
        self.db.refresh(conversation)
        return self.serialize(conversation)

    def list_for_set(self, set_id: str, status: str = "all", query: str | None = None, group_id: str | None = None) -> list[ConversationOut]:
        material_set = self.db.get(MaterialSet, set_id)
        if not material_set:
            raise not_found("MATERIAL_SET_NOT_FOUND", "材料集合不存在")
        revisions = select(MaterialRevision.id).where(MaterialRevision.material_set_id == set_id)
        if status not in {"active", "archived", "all"}:
            raise AppError(422, "CONVERSATION_HISTORY_INVALID", "Invalid history filter", "status 必须是 active、archived 或 all")
        if query and len(query.strip()) > 200:
            raise AppError(422, "CONVERSATION_HISTORY_INVALID", "Invalid history filter", "搜索词不能超过 200 个字符")
        rows_query = self.db.query(Conversation).filter(Conversation.revision_id.in_(revisions))
        if status == "active":
            rows_query = rows_query.filter(Conversation.archived_at.is_(None))
        elif status == "archived":
            rows_query = rows_query.filter(Conversation.archived_at.is_not(None))
        if query and query.strip():
            rows_query = rows_query.filter(Conversation.title.ilike(f"%{query.strip()}%", escape="\\"))
        if group_id:
            if group_id == "ungrouped":
                rows_query = rows_query.filter(Conversation.group_id.is_(None))
            else:
                group = self.repo.group(group_id)
                if not group or group.material_set_id != set_id:
                    raise AppError(409, "CONVERSATION_GROUP_SCOPE_MISMATCH", "Conversation group scope mismatch", "分组不属于当前材料集合")
                rows_query = rows_query.filter(Conversation.group_id == group_id)
        rows = rows_query.all()
        serialized = [self.serialize(row) for row in rows]
        return [self.serialize_row(row) for row in sort_conversations([self.row_metadata(item) for item in serialized])]

    @staticmethod
    def row_metadata(item: ConversationOut) -> dict:
        data = item.model_dump(by_alias=True)
        data["_item"] = item
        return data

    @staticmethod
    def serialize_row(row: dict) -> ConversationOut:
        return row["_item"]

    def serialize(self, conversation: Conversation) -> ConversationOut:
        messages = [MessageOut(id=m.id, role=m.role, content=m.text, mode=m.mode, response=json.loads(m.response_json) if m.response_json else None, created_at=m.created_at) for m in self.repo.messages(conversation.id)]
        return ConversationOut(id=conversation.id, revision_id=conversation.revision_id, group_id=conversation.group_id, title=conversation.title, summary=conversation.summary or "", messages=messages, created_at=conversation.created_at, updated_at=conversation.updated_at, is_pinned=conversation.pinned_at is not None, pinned_at=conversation.pinned_at, is_archived=conversation.archived_at is not None, archived_at=conversation.archived_at, last_activity_at=conversation.last_activity_at)

    def groups(self, set_id: str) -> list[ConversationGroupOut]:
        self._set(set_id)
        return [ConversationGroupOut.model_validate(group, from_attributes=True) for group in self.repo.groups_for_set(set_id)]

    def _set(self, set_id: str) -> MaterialSet:
        item = self.db.get(MaterialSet, set_id)
        if not item:
            raise not_found("MATERIAL_SET_NOT_FOUND", "材料集合不存在")
        return item

    def create_group(self, set_id: str, name: str) -> ConversationGroupOut:
        self._set(set_id)
        try:
            clean = validate_group_name(name)
        except ValueError as exc:
            raise AppError(422, "CONVERSATION_HISTORY_INVALID", "Invalid conversation group", str(exc)) from exc
        if self.db.query(ConversationGroup).filter_by(material_set_id=set_id, normalized_name=normalize_group_name(clean)).first():
            raise AppError(409, "CONVERSATION_GROUP_NAME_CONFLICT", "Conversation group name conflict", "当前材料集合已有同名分组")
        group = ConversationGroup(material_set_id=set_id, name=clean, normalized_name=normalize_group_name(clean))
        self.db.add(group)
        self.db.commit()
        self.db.refresh(group)
        return ConversationGroupOut.model_validate(group, from_attributes=True)

    def update_group(self, group_id: str, name: str) -> ConversationGroupOut:
        group = self.repo.group(group_id)
        if not group:
            raise not_found("CONVERSATION_GROUP_NOT_FOUND", "分组不存在")
        try:
            clean = validate_group_name(name)
        except ValueError as exc:
            raise AppError(422, "CONVERSATION_HISTORY_INVALID", "Invalid conversation group", str(exc)) from exc
        conflict = self.db.query(ConversationGroup).filter(ConversationGroup.material_set_id == group.material_set_id, ConversationGroup.normalized_name == normalize_group_name(clean), ConversationGroup.id != group_id).first()
        if conflict:
            raise AppError(409, "CONVERSATION_GROUP_NAME_CONFLICT", "Conversation group name conflict", "当前材料集合已有同名分组")
        group.name = clean
        group.normalized_name = normalize_group_name(clean)
        self.db.commit()
        self.db.refresh(group)
        return ConversationGroupOut.model_validate(group, from_attributes=True)

    def delete_group(self, group_id: str) -> None:
        group = self.repo.group(group_id)
        if not group:
            return
        self.db.query(Conversation).filter(Conversation.group_id == group_id).update({Conversation.group_id: None}, synchronize_session=False)
        self.db.delete(group)
        self.db.commit()

    def update_management(self, conversation_id: str, payload: ConversationPatch) -> ConversationOut:
        conversation = self.get(conversation_id)
        fields = payload.model_fields_set
        if "title" in fields:
            try:
                conversation.title = validate_title(payload.title or "")
            except ValueError as exc:
                raise AppError(422, "CONVERSATION_HISTORY_INVALID", "Invalid conversation title", str(exc)) from exc
        if "group_id" in fields:
            if payload.group_id is None:
                conversation.group_id = None
            else:
                group = self.repo.group(payload.group_id)
                revision = self.db.get(MaterialRevision, conversation.revision_id)
                if not group or not revision or group.material_set_id != revision.material_set_id:
                    raise AppError(409, "CONVERSATION_GROUP_SCOPE_MISMATCH", "Conversation group scope mismatch", "分组不属于对话的材料集合")
                conversation.group_id = group.id
        if "is_archived" in fields and payload.is_archived is not None:
            desired = payload.is_archived
            if desired != (conversation.archived_at is not None):
                self._ensure_not_busy(conversation.id)
                conversation.archived_at = now() if desired else None
        if "is_pinned" in fields and payload.is_pinned is not None:
            desired = payload.is_pinned
            if desired and conversation.pinned_at is None:
                conversation.pinned_at = now()
            elif not desired:
                conversation.pinned_at = None
        self.db.commit()
        self.db.refresh(conversation)
        return self.serialize(conversation)

    def _ensure_not_busy(self, conversation_id: str) -> None:
        if self.db.query(LlmRun).filter(LlmRun.conversation_id == conversation_id, LlmRun.status.in_(["queued", "running"])).first():
            raise AppError(409, "CONVERSATION_BUSY", "Conversation busy", "对话正在处理任务，请等待完成或先取消")

    def delete_conversation(self, conversation_id: str) -> None:
        conversation = self.db.get(Conversation, conversation_id)
        if not conversation:
            return
        self._ensure_not_busy(conversation_id)
        self.db.delete(conversation)
        self.db.commit()
        from ..repository.practice_repository import PracticeRepository
        PracticeRepository(self.db).delete_orphan_preferences()
        self.db.commit()

    def evidence(self, conversation: Conversation, selection_text: str | None) -> list[dict]:
        material_ids = [m.id for m in self.db.query(Material).filter(Material.revision_id == conversation.revision_id).all()]
        query = self.db.query(EvidenceChunk).filter(EvidenceChunk.material_id.in_(material_ids))
        if selection_text:
            query = query.filter(EvidenceChunk.content.contains(selection_text[:80]))
        chunks = query.limit(8).all()
        result = [{"id": c.id, "material_id": c.material_id, "content": c.content, "source_path": c.source_path, "page_number": c.page_number} for c in chunks]
        revision = self.db.get(MaterialRevision, conversation.revision_id)
        if revision:
            supplements = self.db.query(CandidateSupplement).filter(CandidateSupplement.material_set_id == revision.material_set_id, CandidateSupplement.confirmed.is_(True)).all()
            result.extend({"id": f"supplement:{s.id}", "content": s.content, "source_path": "候选人补充内容", "page_number": None} for s in supplements)
        return result

    async def send(self, conversation_id: str, content: str, mode: str, selection_text: str | None) -> MessageOut:
        conversation = self.get(conversation_id)
        if conversation.archived_at is not None:
            raise AppError(409, "CONVERSATION_ARCHIVED", "Conversation archived", "归档对话需要恢复后才能继续练习")
        user_message = Message(conversation_id=conversation_id, role="user", text=content, mode=mode)
        self.db.add(user_message)
        self.db.flush()
        previous = self.db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.created_at.desc()).limit(8).all()
        evidence = self.evidence(conversation, selection_text)
        revision_materials = self.db.query(Material).filter(Material.revision_id == conversation.revision_id, Material.kind == "resume").all()
        personal_info: dict = {}
        if revision_materials:
            draft = self.db.query(ResumeExtractionDraft).filter(ResumeExtractionDraft.material_id == revision_materials[0].id).order_by(ResumeExtractionDraft.created_at.desc()).first()
            if draft:
                try:
                    personal_info = json.loads(draft.draft_json or "{}").get("personalInfo", {})
                except json.JSONDecodeError:
                    personal_info = {}
        llm_evidence = [{**item, "content": redact_personal_context(item["content"], personal_info)} for item in evidence]
        resume_ids = {item.id for item in revision_materials}
        resume_evidence = [item for item in llm_evidence if item.get("material_id") in resume_ids]
        project_evidence = [item for item in llm_evidence if item not in resume_evidence]
        resume_context = "\n".join(f"[{item['id']}] {item['content']}" for item in resume_evidence)[:40_000]
        project_context = "\n".join(f"[{item['id']}] {item['content']}" for item in project_evidence)[:24_000]
        evidence_context = f"简历证据（最多 40000 字符）：\n{resume_context}\n项目证据（最多 24000 字符）：\n{project_context}"
        context = f"对话摘要：{conversation.summary or '暂无'}\n最近对话：\n" + "\n".join(f"{m.role}: {m.text}" for m in reversed(previous)) + f"\n\n{evidence_context}"
        try:
            response = await request_llm(mode, context, llm_evidence, content)
        except LLMError as exc:
            self.db.rollback()
            raise AppError(502, "LLM_REQUEST_FAILED", "LLM request failed", str(exc)) from exc
        assistant = Message(conversation_id=conversation_id, role="assistant", text=response.answer, mode=mode, response_json=response.model_dump_json(by_alias=True))
        self.db.add(assistant)
        revision = self.db.get(MaterialRevision, conversation.revision_id)
        if revision:
            for gap in response.evidence_gaps:
                supplement = CandidateSupplement(conversation_id=conversation_id, material_set_id=revision.material_set_id, content="", evidence_gap=gap.get("question"))
                self.db.add(supplement)
                self.db.flush()
                gap["supplementId"] = supplement.id
            assistant.response_json = response.model_dump_json(by_alias=True)
        self.db.commit()
        self.db.refresh(assistant)
        conversation.last_activity_at = now()
        self.db.commit()
        return MessageOut(id=assistant.id, role=assistant.role, content=assistant.text, mode=assistant.mode, response=response.model_dump(by_alias=True), created_at=assistant.created_at)

    def confirm_supplement(self, conversation_id: str, supplement_id: str, content: str) -> SupplementOut:
        conversation = self.get(conversation_id)
        if conversation.archived_at is not None:
            raise AppError(409, "CONVERSATION_ARCHIVED", "Conversation archived", "归档对话需要恢复后才能确认补充内容")
        supplement = self.db.get(CandidateSupplement, supplement_id)
        if not supplement or supplement.conversation_id != conversation_id:
            raise not_found("SUPPLEMENT_NOT_FOUND", "补充内容不存在")
        supplement.content = content
        supplement.confirmed = True
        supplement.status = "confirmed"
        self.db.commit()
        return SupplementOut(id=supplement.id, content=supplement.content, status=supplement.status, confirmed=supplement.confirmed)
