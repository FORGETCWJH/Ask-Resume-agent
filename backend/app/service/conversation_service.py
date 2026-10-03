import json

from sqlalchemy.orm import Session

from ..common.errors import AppError, not_found
from ..dto.conversation import ConversationOut, MessageOut, SupplementOut
from ..domain.resume_recognition import redact_personal_context
from ..models import CandidateSupplement, Conversation, EvidenceChunk, Material, MaterialRevision, Message, ResumeExtractionDraft
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
        conversation = Conversation(revision_id=revision.id, title=title)
        self.db.add(conversation)
        self.db.commit()
        self.db.refresh(conversation)
        return self.serialize(conversation)

    def serialize(self, conversation: Conversation) -> ConversationOut:
        messages = [MessageOut(id=m.id, role=m.role, content=m.text, mode=m.mode, response=json.loads(m.response_json) if m.response_json else None, created_at=m.created_at) for m in self.repo.messages(conversation.id)]
        return ConversationOut(id=conversation.id, revision_id=conversation.revision_id, title=conversation.title, summary=conversation.summary or "", messages=messages, created_at=conversation.created_at, updated_at=conversation.updated_at)

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
        return MessageOut(id=assistant.id, role=assistant.role, content=assistant.text, mode=assistant.mode, response=response.model_dump(by_alias=True), created_at=assistant.created_at)

    def confirm_supplement(self, conversation_id: str, supplement_id: str, content: str) -> SupplementOut:
        supplement = self.db.get(CandidateSupplement, supplement_id)
        if not supplement or supplement.conversation_id != conversation_id:
            raise not_found("SUPPLEMENT_NOT_FOUND", "补充内容不存在")
        supplement.content = content
        supplement.confirmed = True
        supplement.status = "confirmed"
        self.db.commit()
        return SupplementOut(id=supplement.id, content=supplement.content, status=supplement.status, confirmed=supplement.confirmed)
