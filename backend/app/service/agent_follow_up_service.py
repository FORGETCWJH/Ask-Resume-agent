"""面试练习用例：HTTP 只创建任务，Worker 负责一次短 LangGraph 执行。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..common.errors import AppError, not_found
from ..db import SessionLocal
from ..domain.agent_follow_up import (
    LlmRunState,
    QuestionScope as DomainQuestionScope,
    fingerprint_answer,
    fingerprint_scope,
    transition_run,
)
from ..dto.agent_follow_up import (
    LlmRunCreateOut,
    LlmRunOut,
    PracticeAnswerOut,
    PracticeTurnListOut,
    PracticeTurnOut,
    QuestionScope,
)
from ..dto.llm import FeedbackResponse, FollowUpQuestionResponse, QuestionGenerationResponse, ReferenceAnswerResponse
from ..infrastructure.agent_graph import run_short_graph
from ..infrastructure.llm import LLMError, get_llm_client, request_llm
from ..infrastructure.task_queue import TaskQueueUnavailable, enqueue
from ..models import (
    CodeEvidenceSnapshot,
    Conversation,
    EvidenceChunk,
    LlmRun,
    Material,
    PracticeAnswer,
    PracticeFeedback,
    PracticeTurn,
    QuestionVersion,
    ReferenceAnswer,
)


QUESTION_PROMPT_VERSION = "question-v2"
FEEDBACK_PROMPT_VERSION = "feedback-v2"
REFERENCE_PROMPT_VERSION = "reference-v2"
FOLLOW_UP_PROMPT_VERSION = "follow-up-v2"


class AgentFollowUpService:
    def __init__(self, db: Session):
        self.db = db

    def _conversation(self, conversation_id: str) -> Conversation:
        item = self.db.get(Conversation, conversation_id)
        if not item:
            raise not_found("CONVERSATION_NOT_FOUND", "对话不存在")
        return item

    def create_question_run(self, conversation_id: str, scope: QuestionScope) -> LlmRunOut:
        conversation = self._conversation(conversation_id)
        normalized = DomainQuestionScope.model_validate(scope.model_dump())
        if not normalized.project_ids and normalized.scope_type == "project":
            normalized.project_ids = list(normalized.target_ids)
        scope_fp = fingerprint_scope(normalized)
        force_new = bool(scope.new_version)
        if not force_new:
            current = self._existing_run(conversation.id, "question_generation", scope_fp)
            if current:
                return self.serialize_run(current)
        request = {
            "scope": normalized.model_dump(mode="json", by_alias=True),
            "scopeFingerprint": scope_fp,
            "promptVersion": QUESTION_PROMPT_VERSION,
            "forceNew": force_new,
        }
        run = LlmRun(conversation_id=conversation.id, kind="question_generation", request_json=json.dumps(request, ensure_ascii=False))
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        self._schedule(run.id)
        return self.serialize_run(run)

    def list_turns(self, conversation_id: str) -> PracticeTurnListOut:
        self._conversation(conversation_id)
        turns = self.db.query(PracticeTurn).filter(PracticeTurn.conversation_id == conversation_id).order_by(PracticeTurn.created_at.asc()).all()
        return PracticeTurnListOut(items=[self.serialize_turn(turn) for turn in turns])

    def save_answer(self, turn_id: str, content: str) -> PracticeAnswerOut:
        turn = self._turn(turn_id)
        normalized = content.strip()
        if not normalized:
            raise AppError(422, "ANSWER_REQUIRED", "Answer required", "回答不能为空")
        latest = self.db.query(func.max(PracticeAnswer.version)).filter(PracticeAnswer.turn_id == turn.id).scalar() or 0
        answer = PracticeAnswer(turn_id=turn.id, version=latest + 1, content=normalized, fingerprint=fingerprint_answer(normalized))
        self.db.add(answer)
        turn.answer_text = normalized
        self.db.commit()
        self.db.refresh(answer)
        return PracticeAnswerOut(turn_id=turn.id, answer=answer.content, answer_version=answer.version, answer_id=answer.id, saved_at=answer.created_at)

    def create_reference_run(self, turn_id: str) -> LlmRunOut:
        turn = self._turn(turn_id)
        self._require_answer(turn.id)
        question_version = self.db.get(QuestionVersion, turn.question_version_id)
        snapshot_fp = self._empty_code_snapshot(turn.revision_id)
        previous = self.db.query(ReferenceAnswer).filter(
            ReferenceAnswer.turn_id == turn.id,
            ReferenceAnswer.question_version_id == turn.question_version_id,
            ReferenceAnswer.question_fingerprint == _question_fingerprint(turn.question_text),
            ReferenceAnswer.code_snapshot_fingerprint == snapshot_fp,
        ).order_by(ReferenceAnswer.created_at.desc()).first()
        if previous:
            cached = self._succeeded_run(turn.id, "reference_answer", previous.id)
            if cached:
                return self.serialize_run(cached)
        request = {"question": turn.question_text, "questionVersionId": turn.question_version_id, "snapshotFingerprint": snapshot_fp, "promptVersion": REFERENCE_PROMPT_VERSION}
        run = LlmRun(conversation_id=turn.conversation_id, turn_id=turn.id, kind="reference_answer", request_json=json.dumps(request, ensure_ascii=False))
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        self._schedule(run.id)
        return self.serialize_run(run)

    def create_feedback_run(self, turn_id: str) -> LlmRunOut:
        return self._create_turn_run(turn_id, "feedback")

    def create_follow_up_run(self, turn_id: str) -> LlmRunOut:
        return self._create_turn_run(turn_id, "follow_up")

    def _create_turn_run(self, turn_id: str, kind: str) -> LlmRunOut:
        turn = self._turn(turn_id)
        answer = self._require_answer(turn.id)
        input_fp = answer.fingerprint if answer else ""
        existing = self._active_or_succeeded_turn_run(turn.id, kind, input_fp)
        if existing:
            return self.serialize_run(existing)
        request = {
            "question": turn.question_text,
            "answer": answer.content,
            "answerId": answer.id,
            "answerFingerprint": input_fp,
            "promptVersion": FEEDBACK_PROMPT_VERSION if kind == "feedback" else FOLLOW_UP_PROMPT_VERSION,
        }
        run = LlmRun(conversation_id=turn.conversation_id, turn_id=turn.id, kind=kind, request_json=json.dumps(request, ensure_ascii=False))
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        self._schedule(run.id)
        return self.serialize_run(run)

    def get_run(self, run_id: str) -> LlmRunOut:
        run = self.db.get(LlmRun, run_id)
        if not run:
            raise not_found("LLM_RUN_NOT_FOUND", "模型任务不存在")
        return self.serialize_run(run)

    def retry_run(self, run_id: str) -> LlmRunOut:
        old = self.db.get(LlmRun, run_id)
        if not old:
            raise not_found("LLM_RUN_NOT_FOUND", "模型任务不存在")
        if old.status not in {"failed", "cancelled"}:
            raise AppError(409, "LLM_RUN_NOT_RETRYABLE", "Run is not retryable", "只有失败或取消的任务可以重试")
        retry = LlmRun(conversation_id=old.conversation_id, turn_id=old.turn_id, kind=old.kind, request_json=old.request_json)
        self.db.add(retry)
        self.db.commit()
        self.db.refresh(retry)
        self._schedule(retry.id)
        return self.serialize_run(retry)

    def cancel_run(self, run_id: str) -> LlmRunOut:
        run = self.db.get(LlmRun, run_id)
        if not run:
            raise not_found("LLM_RUN_NOT_FOUND", "模型任务不存在")
        if run.status in {"queued", "running"}:
            run.status = "cancelled"
            self.db.commit()
        return self.serialize_run(run)

    def serialize_run(self, run: LlmRun) -> LlmRunOut:
        return LlmRunOut(id=run.id, status=run.status, kind=run.kind, conversation_id=run.conversation_id, practice_turn_id=run.turn_id, result=json.loads(run.result_json) if run.result_json else None, error=run.error_message, created_at=run.created_at, updated_at=run.updated_at)

    def serialize_turn(self, turn: PracticeTurn) -> PracticeTurnOut:
        answer = self._latest_answer(turn.id)
        feedback = self.db.query(PracticeFeedback).filter(PracticeFeedback.turn_id == turn.id, PracticeFeedback.answer_id == (answer.id if answer else "")).order_by(PracticeFeedback.created_at.desc()).first() if answer else None
        reference = self.db.query(ReferenceAnswer).filter(ReferenceAnswer.turn_id == turn.id, ReferenceAnswer.question_version_id == turn.question_version_id).order_by(ReferenceAnswer.created_at.desc()).first()
        return PracticeTurnOut(
            id=turn.id,
            question=turn.question_text,
            question_data=json.loads(turn.question_json or "{}"),
            answer=answer.content if answer else None,
            answer_version=answer.version if answer else None,
            answer_id=answer.id if answer else None,
            parent_turn_id=turn.parent_turn_id,
            feedback=json.loads(feedback.result_json) if feedback else None,
            reference_answer=json.loads(reference.answer_json) if reference else None,
            created_at=turn.created_at,
            updated_at=turn.updated_at,
        )

    def _turn(self, turn_id: str) -> PracticeTurn:
        turn = self.db.get(PracticeTurn, turn_id)
        if not turn:
            raise not_found("PRACTICE_TURN_NOT_FOUND", "练习问题不存在")
        return turn

    def _latest_answer(self, turn_id: str) -> PracticeAnswer | None:
        answer = self.db.query(PracticeAnswer).filter(PracticeAnswer.turn_id == turn_id).order_by(PracticeAnswer.version.desc()).first()
        if answer:
            return answer
        turn = self.db.get(PracticeTurn, turn_id)
        if turn and turn.answer_text:
            legacy = PracticeAnswer(turn_id=turn.id, version=1, content=turn.answer_text, fingerprint=fingerprint_answer(turn.answer_text))
            self.db.add(legacy)
            self.db.commit()
            self.db.refresh(legacy)
            return legacy
        return None

    def _require_answer(self, turn_id: str) -> PracticeAnswer:
        answer = self._latest_answer(turn_id)
        if not answer:
            raise AppError(409, "ANSWER_REQUIRED", "Answer required", "请先提交回答，再查看反馈、参考答案或继续追问")
        return answer

    def _existing_run(self, conversation_id: str, kind: str, scope_fp: str) -> LlmRun | None:
        runs = self.db.query(LlmRun).filter(LlmRun.conversation_id == conversation_id, LlmRun.kind == kind).order_by(LlmRun.created_at.desc()).all()
        for run in runs:
            request = json.loads(run.request_json or "{}")
            if request.get("scopeFingerprint") == scope_fp and run.status in {"queued", "running", "succeeded"}:
                return run
        return None

    def _active_or_succeeded_turn_run(self, turn_id: str, kind: str, answer_fp: str) -> LlmRun | None:
        for run in self.db.query(LlmRun).filter(LlmRun.turn_id == turn_id, LlmRun.kind == kind).order_by(LlmRun.created_at.desc()).all():
            request = json.loads(run.request_json or "{}")
            if request.get("answerFingerprint") == answer_fp and run.status in {"queued", "running", "succeeded"}:
                return run
        return None

    def _succeeded_run(self, turn_id: str, kind: str, reference_id: str) -> LlmRun | None:
        for run in self.db.query(LlmRun).filter(LlmRun.turn_id == turn_id, LlmRun.kind == kind, LlmRun.status == "succeeded").order_by(LlmRun.created_at.desc()).all():
            result = json.loads(run.result_json or "{}")
            if result.get("referenceAnswerId") == reference_id:
                return run
        return None

    def _empty_code_snapshot(self, revision_id: str) -> str:
        payload = json.dumps({"status": "disabled", "evidence": []}, ensure_ascii=False, sort_keys=True)
        fingerprint = hashlib.sha256(payload.encode()).hexdigest()
        if not self.db.query(CodeEvidenceSnapshot).filter(CodeEvidenceSnapshot.revision_id == revision_id, CodeEvidenceSnapshot.fingerprint == fingerprint).first():
            self.db.add(CodeEvidenceSnapshot(revision_id=revision_id, fingerprint=fingerprint, evidence_json=payload))
            self.db.commit()
        return fingerprint

    def _schedule(self, run_id: str) -> None:
        try:
            enqueue(run_id, _run_in_background)
        except TaskQueueUnavailable as exc:
            run = self.db.get(LlmRun, run_id)
            if run:
                run.status = "failed"
                run.error_message = str(exc)[:1000]
                self.db.commit()
            raise AppError(503, "TASK_QUEUE_UNAVAILABLE", "Task queue unavailable", "后台任务队列暂时不可用，请稍后重试") from exc


def _run_in_background(run_id: str) -> None:
    db = SessionLocal()
    try:
        AgentWorker(db).run(run_id)
    finally:
        db.close()


class AgentWorker:
    def __init__(self, db: Session):
        self.db = db

    def run(self, run_id: str) -> None:
        run = self.db.get(LlmRun, run_id)
        if not run or run.status in {"succeeded", "failed", "cancelled"}:
            return
        try:
            run.status = transition_run(LlmRunState(run.status), LlmRunState.RUNNING).value
            self.db.commit()
            if run.kind == "question_generation":
                result = asyncio.run(run_short_graph(lambda: self._generate_questions(run), node_name="questionNode"))
            elif run.kind == "reference_answer":
                result = asyncio.run(run_short_graph(lambda: self._generate_reference_answer(run), node_name="referenceAnswerNode"))
            elif run.kind == "feedback":
                result = asyncio.run(run_short_graph(lambda: self._generate_feedback(run), node_name="feedbackNode"))
            elif run.kind == "follow_up":
                result = asyncio.run(run_short_graph(lambda: self._generate_follow_up(run), node_name="followUpNode"))
            else:
                raise LLMError(f"未知模型任务：{run.kind}")
            self.db.refresh(run)
            if run.status == "cancelled":
                return
            run.result_json = json.dumps(result, ensure_ascii=False)
            run.status = "succeeded"
            run.error_message = None
        except Exception as exc:
            self.db.rollback()
            run = self.db.get(LlmRun, run_id)
            if run and run.status != "cancelled":
                run.status = "failed"
                run.error_message = str(exc)[:1000]
        self.db.commit()

    def _revision_evidence(self, conversation: Conversation, scope: dict[str, Any] | None = None) -> list[dict]:
        query = self.db.query(EvidenceChunk).join(Material).filter(Material.revision_id == conversation.revision_id).order_by(EvidenceChunk.chunk_order.asc())
        scope = scope or {}
        project_ids = set(scope.get("projectIds", scope.get("project_ids", [])))
        if project_ids:
            query = query.filter(Material.id.in_(project_ids))
        rows = query.limit(120).all()
        return [{"id": row.id, "content": row.content, "material_id": row.material_id, "source_path": row.source_path, "page_number": row.page_number} for row in rows]

    async def _generate_questions(self, run: LlmRun) -> dict:
        conversation = self.db.get(Conversation, run.conversation_id)
        request = json.loads(run.request_json or "{}")
        scope = DomainQuestionScope.model_validate(request.get("scope", {}))
        evidence = self._revision_evidence(conversation, request.get("scope", {}))
        context = "问题范围：" + json.dumps(request.get("scope", {}), ensure_ascii=False) + "\n材料证据：\n" + "\n".join(f"[{item['id']}] {item['content']}" for item in evidence)[:55_000]
        response = await get_llm_client().structured(mode="questionGeneration", context=context, user_text="生成练习问题", schema=QuestionGenerationResponse)
        questions = [item.model_dump(mode="json", by_alias=True) for item in response.questions[: scope.count]]
        if not questions:
            questions = [{"text": "请介绍一个你最熟悉的项目，并说明你亲自负责的核心部分。", "type": "project", "evidenceIds": []}]
        version = QuestionVersion(conversation_id=conversation.id, revision_id=conversation.revision_id, scope_json=json.dumps(request.get("scope", {}), ensure_ascii=False), scope_fingerprint=request.get("scopeFingerprint") or fingerprint_scope(scope), questions_json=json.dumps(questions, ensure_ascii=False), prompt_version=QUESTION_PROMPT_VERSION)
        self.db.add(version)
        self.db.flush()
        turn_ids = []
        for index, question in enumerate(questions):
            turn = PracticeTurn(conversation_id=conversation.id, revision_id=conversation.revision_id, question_version_id=version.id, question_index=index, question_text=question.get("text", "请解释你的项目。"), question_json=json.dumps(question, ensure_ascii=False))
            self.db.add(turn)
            self.db.flush()
            turn_ids.append(turn.id)
        return {"questionVersionId": version.id, "turnIds": turn_ids, "questions": questions}

    async def _generate_reference_answer(self, run: LlmRun) -> dict:
        turn = self.db.get(PracticeTurn, run.turn_id)
        request = json.loads(run.request_json or "{}")
        snapshot_fp = request.get("snapshotFingerprint") or "disabled"
        response = await get_llm_client().structured(
            mode="referenceAnswer",
            context="当前代码证据功能尚未启用，不能验证候选人的项目实现。",
            user_text=turn.question_text,
            schema=ReferenceAnswerResponse,
        )
        answer = response.model_dump(mode="json", by_alias=True)
        answer.update({"evidenceGrade": "insufficient", "codeEvidence": [], "limitations": ["当前阶段尚未启用代码证据"]})
        reference = ReferenceAnswer(
            turn_id=turn.id,
            question_version_id=turn.question_version_id,
            revision_id=turn.revision_id,
            question_fingerprint=_question_fingerprint(turn.question_text),
            code_snapshot_fingerprint=snapshot_fp,
            answer_json=json.dumps(answer, ensure_ascii=False),
            prompt_version=REFERENCE_PROMPT_VERSION,
        )
        self.db.add(reference)
        self.db.flush()
        return {"referenceAnswerId": reference.id, **answer}

    async def _generate_feedback(self, run: LlmRun) -> dict:
        turn = self.db.get(PracticeTurn, run.turn_id)
        request = json.loads(run.request_json or "{}")
        answer = self.db.get(PracticeAnswer, request.get("answerId"))
        response = await get_llm_client().structured(
            mode="feedback",
            context=f"问题：{turn.question_text}\n候选人回答：{answer.content if answer else request.get('answer', '')}",
            user_text=answer.content if answer else "",
            schema=FeedbackResponse,
        )
        result = response.model_dump(mode="json", by_alias=True)
        feedback = PracticeFeedback(turn_id=turn.id, answer_id=answer.id, prompt_version=FEEDBACK_PROMPT_VERSION, result_json=json.dumps(result, ensure_ascii=False))
        self.db.add(feedback)
        self.db.flush()
        return result

    async def _generate_follow_up(self, run: LlmRun) -> dict:
        turn = self.db.get(PracticeTurn, run.turn_id)
        request = json.loads(run.request_json or "{}")
        answer = self.db.get(PracticeAnswer, request.get("answerId"))
        feedback = self.db.query(PracticeFeedback).filter(PracticeFeedback.turn_id == turn.id, PracticeFeedback.answer_id == answer.id).order_by(PracticeFeedback.created_at.desc()).first()
        depth = self._follow_up_depth(turn)
        if depth >= 3:
            raise AppError(409, "FOLLOW_UP_DEPTH_REACHED", "Follow-up depth reached", "当前追问已达到 3 层上限")
        response = await get_llm_client().structured(
            mode="followUp",
            context=f"问题：{turn.question_text}\n回答：{answer.content}\n反馈：{feedback.result_json if feedback else '尚未查看反馈'}",
            user_text="请针对回答缺口生成一个继续追问",
            schema=FollowUpQuestionResponse,
        )
        child = PracticeTurn(
            conversation_id=turn.conversation_id,
            revision_id=turn.revision_id,
            question_version_id=turn.question_version_id,
            question_index=turn.question_index,
            question_text=response.question,
            question_json=json.dumps(response.model_dump(mode="json", by_alias=True), ensure_ascii=False),
            parent_turn_id=turn.id,
        )
        self.db.add(child)
        self.db.flush()
        return {"turnId": child.id, "parentTurnId": turn.id, **response.model_dump(mode="json", by_alias=True)}

    def _follow_up_depth(self, turn: PracticeTurn) -> int:
        depth = 0
        while turn.parent_turn_id:
            depth += 1
            turn = self.db.get(PracticeTurn, turn.parent_turn_id)
            if not turn:
                break
        return depth


def _question_fingerprint(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
