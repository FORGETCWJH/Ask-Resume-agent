"""对话练习的持久化边界，事实快照只在创建对话时捕获。"""
import json
from sqlalchemy import func, update
from sqlalchemy.orm import Session
from ..models import (Conversation, Material, EvidenceChunk, ResumeExtractionDraft,
    CandidateSupplement, MaterialRevision, PracticeState, PracticeEvent, PracticeInput,
    PracticePreference, PracticePreferenceSource, PracticeTurn, PracticeAnswer, QuestionVersion, LlmRun)


def encode(value):
    return json.dumps(value, ensure_ascii=False)


class PracticeRepository:
    def __init__(self, db: Session):
        self.db = db

    def conversation(self, cid):
        return self.db.get(Conversation, cid)

    def state(self, cid):
        state = self.db.get(PracticeState, cid)
        if not state:
            # 旧对话不从当前草稿伪造历史确认内容。
            conversation = self.conversation(cid)
            state = PracticeState(conversation_id=cid, snapshot_json=encode({"conversationId": cid, "revisionId": conversation.revision_id, "resumes": [], "facts": [], "snapshotStatus": "missing"}), state_json="{}")
            self.db.add(state)
            self.db.flush()
        return state

    def capture(self, conversation):
        materials = self.db.query(Material).filter(Material.revision_id == conversation.revision_id).all()
        resumes, facts, personal_values = [], [], []
        for material in materials:
            chunks = self.db.query(EvidenceChunk).filter(EvidenceChunk.material_id == material.id).order_by(EvidenceChunk.chunk_order).all()
            if material.kind != "resume":
                facts.extend({"id": c.id, "content": c.content, "materialId": material.id, "sourcePath": c.source_path} for c in chunks)
                continue
            draft = self.db.query(ResumeExtractionDraft).filter(ResumeExtractionDraft.material_id == material.id).order_by(ResumeExtractionDraft.created_at.desc()).first()
            confirmed = json.loads(draft.confirmed_sections_json) if draft else []
            values = json.loads(draft.draft_json) if draft else {}
            personal = values.get("personalInfo", {})
            personal_values.extend(str(personal.get(k, "")) for k in ("name", "phone", "email", "city"))
            personal_values.extend(personal.get("links", []))
            confirmed_chunks = [c for c in chunks if c.source_path in [f"resume-recognition:{s}" for s in confirmed]]
            originals = [c for c in chunks if not (c.source_path or "").startswith("resume-recognition:")]
            resumes.append({"materialId": material.id, "filename": material.filename, "snapshotStatus": "available", "confirmedSections": confirmed,
                "sections": {s: values.get(s) for s in confirmed},
                "evidence": [{"id": c.id, "content": c.content, "pageNumber": c.page_number, "sourcePath": c.source_path} for c in originals]})
            facts.extend({"id": c.id, "content": c.content, "materialId": material.id, "section": c.source_path.split(":", 1)[-1], "sourcePath": c.source_path} for c in confirmed_chunks if c.source_path != "resume-recognition:personalInfo")
        revision = self.db.get(MaterialRevision, conversation.revision_id)
        supplements = self.db.query(CandidateSupplement).filter(CandidateSupplement.material_set_id == revision.material_set_id, CandidateSupplement.confirmed.is_(True)).all()
        facts.extend({"id": f"supplement:{s.id}", "content": s.content, "sourcePath": "已确认补充"} for s in supplements)
        from ..domain.practice_intent import redact_context
        facts = [{**f, "content": redact_context(f["content"], personal_values)} for f in facts]
        snapshot = {"conversationId": conversation.id, "revisionId": conversation.revision_id, "resumes": resumes, "facts": facts, "personalValues": personal_values}
        self.db.add(PracticeState(conversation_id=conversation.id, snapshot_json=encode(snapshot), state_json="{}"))

    def events(self, cid, after=0, limit=100):
        return self.db.query(PracticeEvent).filter(PracticeEvent.conversation_id == cid, PracticeEvent.sequence > after).order_by(PracticeEvent.sequence).limit(limit).all()

    def add_event(self, cid, kind, text, *, role="assistant", data=None):
        sequence = (self.db.query(func.max(PracticeEvent.sequence)).filter(PracticeEvent.conversation_id == cid).scalar() or 0) + 1
        event = PracticeEvent(conversation_id=cid, sequence=sequence, message_type=kind, content=text, role=role, data_json=encode(data or {}))
        self.db.add(event)
        self.db.flush()
        return event

    def input_for_request(self, cid, request_id):
        return self.db.query(PracticeInput).filter_by(conversation_id=cid, client_request_id=request_id).first()

    def input(self, iid):
        return self.db.get(PracticeInput, iid)

    def turn(self, tid):
        return self.db.get(PracticeTurn, tid) if tid else None

    def question_version(self, vid):
        return self.db.get(QuestionVersion, vid) if vid else None

    def answer(self, tid):
        return self.db.query(PracticeAnswer).filter_by(turn_id=tid).order_by(PracticeAnswer.version.desc()).first() if tid else None

    def run(self, rid):
        return self.db.get(LlmRun, rid)

    def preferences(self, include_deleted=False):
        query = self.db.query(PracticePreference)
        return query.all() if include_deleted else query.filter_by(deleted=False).all()

    def preference(self, pid):
        return self.db.get(PracticePreference, pid)

    def sources(self, pid):
        return self.db.query(PracticePreferenceSource).filter_by(preference_id=pid).all()

    def delete_orphan_preferences(self):
        for pref in self.preferences(include_deleted=True):
            if not self.sources(pref.id):
                self.db.delete(pref)

    def recent_events(self, cid, limit=12):
        return list(reversed(self.db.query(PracticeEvent).filter_by(conversation_id=cid).order_by(PracticeEvent.sequence.desc()).limit(limit).all()))

    def main_turns(self, cid):
        turns = self.db.query(PracticeTurn).filter_by(conversation_id=cid, parent_turn_id=None).order_by(PracticeTurn.created_at.desc()).all()
        if not turns:
            return []
        return sorted([t for t in turns if t.question_version_id == turns[0].question_version_id], key=lambda t: t.question_index)

    def claim(self, cid, iid):
        return self.db.execute(update(PracticeState).where(PracticeState.conversation_id == cid, PracticeState.busy_input_id.is_(None)).values(busy_input_id=iid), execution_options={"synchronize_session": False}).rowcount == 1

    def release(self, cid, iid):
        self.db.execute(update(PracticeState).where(PracticeState.conversation_id == cid, PracticeState.busy_input_id == iid).values(busy_input_id=None), execution_options={"synchronize_session": False})

    def guard_running(self, rid):
        # 条件写获得数据库写锁；取消/删除不会与结果发布穿插。
        changed = self.db.execute(update(LlmRun).where(LlmRun.id == rid, LlmRun.status == "running").values(status="running"), execution_options={"synchronize_session": False}).rowcount
        if not changed:
            raise RuntimeError("任务已取消或删除")

    def save_answer(self, turn, content):
        from ..domain.agent_follow_up import fingerprint_answer
        latest = self.answer(turn.id)
        answer = PracticeAnswer(turn_id=turn.id, version=(latest.version if latest else 0) + 1, content=content.strip(), fingerprint=fingerprint_answer(content))
        self.db.add(answer)
        turn.answer_text = answer.content
        self.db.flush()
        return answer

    def write_preference(self, cid, key, value, instruction, expected_revision=None):
        pref = self.db.query(PracticePreference).filter_by(key=key).first()
        if pref and expected_revision is not None and pref.revision != expected_revision:
            return None
        if not pref:
            pref = PracticePreference(key=key, value_json=encode(value))
            self.db.add(pref)
            self.db.flush()
        else:
            pref.value_json = encode(value)
            pref.deleted = False
            pref.revision += 1
        source = self.db.query(PracticePreferenceSource).filter_by(preference_id=pref.id, conversation_id=cid).first()
        if not source:
            self.db.add(PracticePreferenceSource(preference_id=pref.id, conversation_id=cid, original_instruction=instruction))
        else:
            source.original_instruction = instruction
        self.db.flush()
        return pref
