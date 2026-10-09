"""对话式练习用例。HTTP 只读取状态或提交短任务。"""
import json
import time
from ..common.errors import AppError, not_found
from ..domain.practice_intent import (PracticeIntent, validate_intent, effective_scope, next_main_index, preference_value, build_context, redact_context, INTENT_PROMPT)
from ..models import PracticeInput, LlmRun, now
from ..repository.practice_repository import PracticeRepository, encode
from ..infrastructure.llm import get_llm_client
from ..infrastructure.agent_graph import run_short_graph


class PracticeService:
    def __init__(self, db):
        self.db = db
        self.repo = PracticeRepository(db)

    def conversation(self, cid):
        conversation = self.repo.conversation(cid)
        if not conversation:
            raise not_found("CONVERSATION_NOT_FOUND", "对话不存在")
        return conversation

    def ensure_writable(self, cid):
        conversation = self.conversation(cid)
        if conversation.archived_at is not None:
            raise AppError(409, "CONVERSATION_ARCHIVED", "Conversation archived", "归档对话需要恢复后才能继续练习")
        return conversation

    def snapshots(self, cid):
        self.conversation(cid)
        state = self.repo.state(cid)
        snapshot = json.loads(state.snapshot_json)
        self.db.commit()
        return {key: value for key, value in snapshot.items() if key not in {"facts", "personalValues"}}

    def state(self, cid):
        self.conversation(cid)
        row = self.repo.state(cid)
        state = json.loads(row.state_json)
        if not state.get("mainTurnIds"):
            turns = self.repo.main_turns(cid)
            if turns:
                state.update(mainTurnIds=[t.id for t in turns], currentTurnId=turns[0].id, currentIndex=0, questionVersionId=turns[0].question_version_id)
                row.state_json = encode(state)
        busy = self.repo.input(row.busy_input_id) if row.busy_input_id else None
        run = self.repo.run(busy.run_id) if busy else self.repo.run(row.busy_input_id) if row.busy_input_id else None
        if row.busy_input_id and (not run or run.status in {"failed", "cancelled", "succeeded"}):
            self.repo.release(cid, row.busy_input_id)
            run = None
        self.db.commit()
        return {"mainTurnIds": [], "currentIndex": 0, "currentTurnId": None, "completed": False, "clarification": None, **state, "activeRunId": run.id if run else None}

    def messages(self, cid, after, limit):
        self.conversation(cid)
        rows = self.repo.events(cid, after, limit)
        items = [{"id": r.id, "sequence": r.sequence, "role": r.role, "messageType": r.message_type, "content": r.content, "createdAt": r.created_at.isoformat(), "runId": None, "practiceTurnId": None, "answerVersionId": None, **json.loads(r.data_json)} for r in rows]
        return {"items": items, "nextAfterSequence": rows[-1].sequence if len(rows) == limit else None}

    def preferences(self):
        return [{"id": p.id, "key": p.key, "value": json.loads(p.value_json), "revision": p.revision, "sourceConversationIds": [s.conversation_id for s in self.repo.sources(p.id)], "createdAt": p.created_at.isoformat(), "updatedAt": p.updated_at.isoformat()} for p in self.repo.preferences()]

    def patch_preference(self, pid, value, revision):
        pref = self.repo.preference(pid)
        if not pref or pref.deleted:
            raise not_found("PREFERENCE_NOT_FOUND", "偏好不存在")
        if pref.revision != revision:
            raise AppError(409, "PREFERENCE_VERSION_CONFLICT", "Preference version conflict", "偏好已被修改，请刷新")
        try:
            pref.value_json = encode(preference_value(pref.key, value))
        except ValueError as exc:
            raise AppError(422, "INVALID_PREFERENCE", "Invalid preference", str(exc)) from exc
        pref.revision += 1
        self.db.commit()
        return next(p for p in self.preferences() if p["id"] == pid)

    def delete_preference(self, pid):
        pref = self.repo.preference(pid)
        if pref and not pref.deleted:
            # 保留版本墓碑，冻结输入或旧摘要不能恢复已撤销的偏好。
            pref.deleted = True
            pref.value_json = "null"
            pref.revision += 1
            self.db.commit()

    def freeze_context(self, cid, state):
        snapshot = json.loads(self.repo.state(cid).snapshot_json)
        turn = self.repo.turn(state.get("currentTurnId"))
        answer = self.repo.answer(turn.id) if turn else None
        chain, parent = [], turn
        while parent and len(chain) < 4:
            chain.insert(0, {"id": parent.id, "question": parent.question_text})
            parent = self.repo.turn(parent.parent_turn_id)
        recent = self.repo.recent_events(cid)
        values = list(snapshot.get("personalValues", []))
        for resume in snapshot.get("resumes", []):
            personal = resume.get("sections", {}).get("personalInfo", {}) or {}
            values.extend(str(personal.get(k, "")) for k in ("name", "phone", "email", "city"))
            values.extend(personal.get("links", []))
        preferences = self.preferences()
        return {**snapshot, "personalValues": values, "currentTurnId": turn.id if turn else None, "currentQuestion": turn.question_text if turn else "", "currentAnswer": answer.content if answer else "", "answerVersionId": answer.id if answer else None,
            "followUpChain": chain, "roundPreferences": state.get("roundPreferences", {}), "clarification": state.get("clarification"),
            "activeScope": state.get("activeScope", {}),
            "longPreferences": {p["key"]: p["value"] for p in preferences}, "preferenceVersions": {p.key: p.revision for p in self.repo.preferences(include_deleted=True)},
            "recentMessages": [{"sequence": e.sequence, "type": e.message_type, "content": e.content[:1200]} for e in recent],
            "summary": state.get("summary", ""), "summaryThroughSequence": state.get("summaryThroughSequence", 0),
            "availableMaterials": [{"id": r["materialId"], "kind": "resume", "filename": r["filename"], "confirmedSections": r["confirmedSections"]} for r in snapshot.get("resumes", [])] + [{"id": f["materialId"], "kind": "project_archive"} for f in snapshot.get("facts", []) if "section" not in f and "materialId" in f]}

    def submit(self, cid, content, request_id):
        content = content.strip()
        if not content:
            raise AppError(422, "INPUT_REQUIRED", "Input required", "输入不能为空")
        self.ensure_writable(cid)
        previous = self.repo.input_for_request(cid, request_id)
        if previous:
            if previous.content != content:
                raise AppError(409, "INPUT_IDEMPOTENCY_CONFLICT", "Input conflict", "重复请求的内容不一致")
            run = self.repo.run(previous.run_id)
            return {"runId": run.id, "status": run.status, "messageId": previous.id}
        state = self.state(cid)
        item = PracticeInput(conversation_id=cid, client_request_id=request_id, content=content, snapshot_json=encode(self.freeze_context(cid, state)))
        self.db.add(item)
        self.db.flush()
        if not self.repo.claim(cid, item.id):
            self.db.rollback()
            raise AppError(409, "CONVERSATION_BUSY", "Conversation busy", "当前对话正在处理输入，请稍后发送")
        run = LlmRun(conversation_id=cid, kind="input", request_json=encode({"inputId": item.id}))
        self.db.add(run)
        self.db.flush()
        item.run_id = run.id
        state["lastRunId"] = run.id
        self.repo.state(cid).state_json = encode(state)
        self.repo.add_event(cid, "input", content, role="user", data={"runId": run.id, "inputId": item.id})
        self.db.commit()
        from .agent_follow_up_service import AgentFollowUpService
        AgentFollowUpService(self.db)._schedule(run.id)
        return {"runId": run.id, "status": "queued", "messageId": item.id}

    def next_question(self, cid, request_id, *, from_input=False):
        if not from_input:
            self.ensure_writable(cid)
        state = self.state(cid) if not from_input else json.loads(self.repo.state(cid).state_json)
        previous = self.repo.input_for_request(cid, request_id)
        if previous and not from_input:
            if previous.content != "@nextQuestion":
                raise AppError(409, "INPUT_IDEMPOTENCY_CONFLICT", "Input conflict", "请求标识已用于其他输入")
            return json.loads(previous.steps_json)
        if state.get("activeRunId") and not from_input:
            raise AppError(409, "CONVERSATION_BUSY", "Conversation busy", "请等待当前输入完成")
        ids = state.get("mainTurnIds", [])
        index, completed = next_main_index(state.get("currentIndex", 0), len(ids))
        state.update(currentIndex=index, currentTurnId=ids[index] if ids else None, completed=completed, clarification=None)
        self.repo.state(cid).state_json = encode(state)
        text = "本组问题已完成。需要新一组时，请明确告诉我。" if completed else self.repo.turn(ids[index]).question_text
        self.repo.add_event(cid, "status" if completed else "question", text, data={"practiceTurnId": state.get("currentTurnId")})
        if not from_input:
            self.db.add(PracticeInput(conversation_id=cid, client_request_id=request_id, content="@nextQuestion", steps_json=encode(state)))
            conversation = self.conversation(cid)
            conversation.last_activity_at = now()
            conversation.updated_at = conversation.last_activity_at
            self.db.commit()
        return state

    async def process(self, run, worker):
        started = time.monotonic()
        item = self.repo.input(json.loads(run.request_json)["inputId"])
        snapshot = json.loads(item.snapshot_json)
        steps = json.loads(item.steps_json)
        if "intent" not in steps:
            async def identify():
                return await get_llm_client().structured(mode="practiceIntent", context=build_context(snapshot), user_text=redact_context(item.content, snapshot.get("personalValues")), schema=PracticeIntent, system_prompt=INTENT_PROMPT)
            intent = await run_short_graph(identify, node_name="intentNode")
            intent = PracticeIntent.model_validate(intent)
            steps["intent"] = intent.model_dump(by_alias=True, mode="json")
            self.repo.guard_running(run.id)
            item.steps_json = encode(steps)
            self.db.commit()
        intent = PracticeIntent.model_validate(steps["intent"])
        target = intent.target_turn_id or snapshot.get("currentTurnId")
        turn = self.repo.turn(target)
        if target and (not turn or turn.conversation_id != run.conversation_id or turn.revision_id != snapshot["revisionId"] or target != snapshot.get("currentTurnId")):
            intent = intent.model_copy(update={"outcome": "needsClarification", "clarification": "目标问题不属于当前对话，请说明要练习哪一题。"})
        intent = validate_intent(intent, current_turn_id=turn.id if turn else None, has_answer=bool(snapshot.get("answerVersionId")))
        result = {"outcome": intent.outcome, "action": intent.action, "practiceTurnId": turn.id if turn else None, "createdMessageIds": [], "preferenceChanges": [], "clarification": intent.clarification}
        self.repo.guard_running(run.id)
        state_row = self.repo.state(run.conversation_id)
        state = json.loads(state_row.state_json)
        if intent.outcome != "recognized":
            text = intent.clarification or "当前支持生成问题、提交回答、点评、参考答案、追问和下一题。"
            state["clarification"] = text if intent.outcome == "needsClarification" else None
            event = self.repo.add_event(run.conversation_id, "clarification" if intent.outcome == "needsClarification" else "status", text, data={"runId": run.id})
            result["createdMessageIds"].append(event.id)
        else:
            state["clarification"] = None
            if "preferences" not in steps:
                changes = []
                for change in intent.preferences:
                    if not change.explicit or not change.instruction_quote.strip() or change.instruction_quote not in redact_context(item.content, snapshot.get("personalValues")):
                        continue
                    value = preference_value(change.key, change.value)
                    if change.scope == "round":
                        state.setdefault("roundPreferences", {})[change.key] = value
                    else:
                        pref = self.repo.write_preference(run.conversation_id, change.key, value, item.content, snapshot.get("preferenceVersions", {}).get(change.key, 0))
                        if pref:
                            changes.append({"id": pref.id, "key": pref.key, "value": value, "revision": pref.revision})
                steps["preferences"] = changes
                state_row.state_json = encode(state)
                item.steps_json = encode(steps)
                self.db.commit()
                self.repo.guard_running(run.id)
            result["preferenceChanges"] = steps["preferences"]
            if intent.answer and turn and "answerId" not in steps:
                answer = self.repo.save_answer(turn, intent.answer)
                steps["answerId"] = answer.id
                self.repo.add_event(run.conversation_id, "answer", answer.content, role="user", data={"practiceTurnId": turn.id, "answerVersionId": answer.id, "answerVersion": answer.version, "runId": run.id})
                item.steps_json = encode(steps)
                self.db.commit()
                self.repo.guard_running(run.id)
            result["answerVersionId"] = steps.get("answerId") or snapshot.get("answerVersionId")
            state = json.loads(state_row.state_json)
            if "actionResult" not in steps:
                self.db.commit()  # 模型等待期间不持有数据库写锁。
                action_result = {}
                if intent.action in {"generate", "regenerate"}:
                    scope = effective_scope(intent, state.get("roundPreferences", {}), snapshot.get("longPreferences", {}))
                    if scope.scope_type == "project" and not scope.project_ids:
                        scope.project_ids = list(scope.target_ids)
                    facts = snapshot.get("facts", [])
                    if scope.resume_sections:
                        available_sections = {s for r in snapshot.get("resumes", []) for s in r.get("confirmedSections", [])}
                        if not set(scope.resume_sections).issubset(available_sections):
                            state["clarification"] = "请求的简历章节在创建此对话时尚未确认，请先确认材料后新建对话，或指定其他范围。"
                            result.update(outcome="needsClarification", clarification=state["clarification"])
                            self.repo.add_event(run.conversation_id, "clarification", state["clarification"], data={"runId": run.id})
                            steps["actionResult"] = {}
                            state_row.state_json = encode(state)
                            item.steps_json = encode(steps)
                            self.repo.release(run.conversation_id, item.id)
                            return result
                        facts = [f for f in facts if "section" not in f or f["section"] in scope.resume_sections]
                    if scope.project_ids:
                        facts = [f for f in facts if f.get("materialId") in scope.project_ids]
                    available_projects = {f.get("materialId") for f in facts if "section" not in f}
                    if not set(scope.project_ids).issubset(available_projects):
                        raise AppError(409, "PROJECT_NOT_BOUND", "Project not bound", "项目不属于当前对话绑定版本")
                    from ..domain.agent_follow_up import fingerprint_scope
                    from .agent_follow_up_service import QUESTION_PROMPT_VERSION
                    current_version = self.repo.question_version(state.get("questionVersionId"))
                    if intent.action == "generate" and current_version and current_version.scope_fingerprint == fingerprint_scope(scope) and current_version.prompt_version == QUESTION_PROMPT_VERSION:
                        action_result = {"questionVersionId": current_version.id, "turnIds": state["mainTurnIds"], "questions": json.loads(current_version.questions_json), "reused": True}
                        self.repo.guard_running(run.id)
                        self.repo.add_event(run.conversation_id, "status", "问题范围没有变化，继续本组当前问题即可。需要新问题时请明确要求换一组。", data={"runId": run.id})
                    else:
                        scoped_context = build_context({**snapshot, "facts": facts, "activeScope": scope.model_dump(by_alias=True), "currentQuestion": scope.topic or snapshot.get("currentQuestion", "")})
                        fake_run = LlmRun(id=run.id, conversation_id=run.conversation_id, request_json=encode({"scope": scope.model_dump(by_alias=True), "facts": facts, "context": scoped_context}))
                        action_result = await run_short_graph(lambda: worker._generate_questions(fake_run), node_name="questionNode")
                        state.update(mainTurnIds=action_result["turnIds"], currentIndex=0, currentTurnId=action_result["turnIds"][0], questionVersionId=action_result["questionVersionId"], completed=False, activeScope=scope.model_dump(by_alias=True))
                        self.repo.add_event(run.conversation_id, "question", action_result["questions"][0]["text"], data={"practiceTurnId": state["currentTurnId"], "runId": run.id})
                elif intent.action == "nextQuestion":
                    state = self.next_question(run.conversation_id, item.client_request_id, from_input=True)
                elif intent.action in {"feedback", "referenceAnswer", "followUp"}:
                    answer_id = steps.get("answerId") or snapshot.get("answerVersionId")
                    fake_run = LlmRun(id=run.id, conversation_id=run.conversation_id, turn_id=turn.id, request_json=encode({"answerId": answer_id, "context": build_context(snapshot)}))
                    handlers = {"feedback": worker._generate_feedback, "referenceAnswer": worker._generate_reference_answer, "followUp": worker._generate_follow_up}
                    # 相同问题版本的参考答案保持不可变；优先复用已持久化结果。
                    from .agent_follow_up_service import AgentFollowUpService
                    cached = AgentFollowUpService(self.db).serialize_turn(turn).reference_answer if intent.action == "referenceAnswer" else None
                    action_result = cached or await run_short_graph(lambda: handlers[intent.action](fake_run), node_name=intent.action + "Node")
                    if intent.action == "followUp":
                        state["currentTurnId"] = action_result["turnId"]
                    text = action_result.get("summary") or action_result.get("answer") or action_result.get("question") or "操作已完成"
                    self.repo.add_event(run.conversation_id, intent.action, text, data={"practiceTurnId": state.get("currentTurnId"), "answerVersionId": answer_id, "result": action_result, "runId": run.id})
                elif intent.action in {"answer", "preference"}:
                    self.repo.add_event(run.conversation_id, "status", "回答已提交。需要点评时请告诉我。" if intent.action == "answer" else "练习偏好已更新，可在偏好面板撤销。", data={"runId": run.id})
                steps["actionResult"] = action_result
                result["actionResult"] = action_result
            state_row.state_json = encode(state)
            item.steps_json = encode(steps)
        self.repo.guard_running(run.id)
        state_row.state_json = encode(state)
        self.repo.release(run.conversation_id, item.id)
        conversation = self.conversation(run.conversation_id)
        conversation.updated_at = now()
        conversation.last_activity_at = conversation.updated_at
        result.update(elapsedMs=round((time.monotonic() - started) * 1000), promptVersion="intent-v1", completedSteps=list(steps))
        # 用带来源边界的截取摘要压缩较早消息；不再调用模型，也不把摘要当事实。
        recent = self.repo.recent_events(run.conversation_id, 24)
        result["createdMessageIds"] = [e.id for e in recent if json.loads(e.data_json).get("runId") == run.id]
        if len(recent) > 12:
            older = recent[:-12]
            state["summary"] = "\n".join(f"[{e.sequence}:{e.message_type}] {e.content[:160]}" for e in older if e.message_type not in {"input", "preference"})[:2000]
            state["summaryThroughSequence"] = older[-1].sequence
            state_row.state_json = encode(state)
        return result

    def publish_shortcut(self, run, result):
        row = self.repo.state(run.conversation_id)
        state = json.loads(row.state_json)
        kind = {"question_generation": "question", "reference_answer": "referenceAnswer", "follow_up": "followUp"}.get(run.kind, run.kind)
        if run.kind == "question_generation":
            state.update(mainTurnIds=result["turnIds"], currentIndex=0, currentTurnId=result["turnIds"][0], questionVersionId=result["questionVersionId"], completed=False, clarification=None)
            text = result["questions"][0]["text"]
        else:
            text = result.get("summary") or result.get("answer") or result.get("question") or "操作已完成"
            if run.kind == "follow_up":
                state["currentTurnId"] = result["turnId"]
        self.repo.add_event(run.conversation_id, kind, text, data={"runId": run.id, "practiceTurnId": state.get("currentTurnId"), "result": result})
        row.state_json = encode(state)
        conversation = self.conversation(run.conversation_id)
        conversation.last_activity_at = now()
        conversation.updated_at = conversation.last_activity_at
