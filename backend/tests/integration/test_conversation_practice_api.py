import time
from io import BytesIO
from uuid import uuid4
from docx import Document
from fastapi.testclient import TestClient
from app.main import app


def wait_run(client, run_id):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        result = client.get(f"/api/v1/llm-runs/{run_id}").json()
        if result["status"] in {"succeeded", "failed", "cancelled"}:
            return result
        time.sleep(0.03)
    raise AssertionError("任务超时")


def setup_conversation(client):
    set_id = client.post("/api/v1/material-sets", json={"title": "对话式练习测试"}).json()["id"]
    doc = Document()
    doc.add_paragraph("技能掌握\n熟悉 Python、Redis\n项目经验\n订单服务")
    stream = BytesIO()
    doc.save(stream)
    upload = client.post(f"/api/v1/material-sets/{set_id}/materials?kind=resume", files={"file": ("resume.docx", stream.getvalue())}).json()
    material_id = upload["materials"][0]["id"]
    deadline = time.monotonic() + 5
    while client.get(f"/api/v1/materials/{material_id}/recognition").json()["recognitionStatus"] == "processing":
        assert time.monotonic() < deadline
        time.sleep(0.03)
    client.post(f"/api/v1/materials/{material_id}/recognition/confirm", json={"section": "skills"})
    conversation_id = client.post(f"/api/v1/material-sets/{set_id}/conversations", json={"title": "练习"}).json()["id"]
    return set_id, material_id, conversation_id


def test_resume_snapshot_is_confirmed_and_immutable_after_edit():
    with TestClient(app) as client:
        set_id, material_id, cid = setup_conversation(client)
        try:
            snapshot = client.get(f"/api/v1/conversations/{cid}/resume-snapshots")
            assert snapshot.status_code == 200
            resume = snapshot.json()["resumes"][0]
            assert resume["snapshotStatus"] == "available"
            assert list(resume["sections"]) == ["skills"]
            original = snapshot.json()
            draft = client.get(f"/api/v1/materials/{material_id}/recognition").json()["draft"]
            draft["skills"]["content"] = "改变后的技能内容"
            client.patch(f"/api/v1/materials/{material_id}/recognition", json={"draft": draft})
            assert client.get(f"/api/v1/conversations/{cid}/resume-snapshots").json() == original
        finally:
            client.delete(f"/api/v1/material-sets/{set_id}")


def send(client, cid, content, request_id=None):
    response = client.post(f"/api/v1/conversations/{cid}/input-runs", json={"content": content, "clientRequestId": request_id or str(uuid4())})
    assert response.status_code == 202, response.text
    result = wait_run(client, response.json()["runId"])
    assert result["status"] == "succeeded", result
    return response.json(), result


def test_input_generates_answers_and_next_question_without_new_group():
    with TestClient(app) as client:
        set_id, _, cid = setup_conversation(client)
        try:
            request_id = str(uuid4())
            created, result = send(client, cid, "围绕 Redis 生成 3 个问题", request_id)
            repeated = client.post(f"/api/v1/conversations/{cid}/input-runs", json={"content": "围绕 Redis 生成 3 个问题", "clientRequestId": request_id})
            assert repeated.json()["runId"] == created["runId"]
            conflict = client.post(f"/api/v1/conversations/{cid}/input-runs", json={"content": "其他内容", "clientRequestId": request_id})
            assert conflict.status_code == 409
            state = client.get(f"/api/v1/conversations/{cid}/practice-state").json()
            assert len(state["mainTurnIds"]) == 3
            send(client, cid, "围绕 Redis 生成 3 个问题")
            assert client.get(f"/api/v1/conversations/{cid}/practice-state").json()["questionVersionId"] == state["questionVersionId"]
            send(client, cid, "我先查询缓存，未命中再查数据库")
            turns = client.get(f"/api/v1/conversations/{cid}/practice-turns").json()["items"]
            assert turns[0]["answerVersion"] == 1
            assert turns[0]["feedback"] is None
            send(client, cid, "我还设置了过期时间，请点评")
            turns = client.get(f"/api/v1/conversations/{cid}/practice-turns").json()["items"]
            assert turns[0]["answerVersion"] == 2
            assert turns[0]["feedback"]["summary"]
            send(client, cid, "继续追问")
            follow_state = client.get(f"/api/v1/conversations/{cid}/practice-state").json()
            assert follow_state["currentTurnId"] != state["currentTurnId"]
            send(client, cid, "下一题")
            next_state = client.get(f"/api/v1/conversations/{cid}/practice-state").json()
            assert next_state["currentTurnId"] == state["mainTurnIds"][1]
            assert next_state["questionVersionId"] == state["questionVersionId"]
            messages = client.get(f"/api/v1/conversations/{cid}/practice-messages").json()["items"]
            assert any(m["messageType"] == "feedback" for m in messages)
            assert len({m["sequence"] for m in messages}) == len(messages)
        finally:
            client.delete(f"/api/v1/material-sets/{set_id}")


def test_explicit_preference_clarification_refresh_and_delete_scope():
    with TestClient(app) as client:
        set_id, _, cid = setup_conversation(client)
        try:
            send(client, cid, "以后每次只生成一道题")
            preference = client.get("/api/v1/practice-preferences").json()[0]
            assert preference["key"] == "count" and preference["value"] == 1
            cid2 = client.post(f"/api/v1/material-sets/{set_id}/conversations", json={"title": "第二个对话"}).json()["id"]
            send(client, cid2, "生成问题")
            assert len(client.get(f"/api/v1/conversations/{cid2}/practice-state").json()["mainTurnIds"]) == 1
            send(client, cid, "本轮只生成一道题")
            assert client.get("/api/v1/practice-preferences").json()[0]["revision"] == preference["revision"]
            send(client, cid, "换成消息队列")
            assert client.get(f"/api/v1/conversations/{cid}/practice-state").json()["clarification"]
            patched = client.patch(f"/api/v1/practice-preferences/{preference['id']}", json={"value": 2, "expectedRevision": preference["revision"]})
            assert patched.status_code == 200
            assert client.patch(f"/api/v1/practice-preferences/{preference['id']}", json={"value": 3, "expectedRevision": preference["revision"]}).status_code == 409
            assert client.delete(f"/api/v1/practice-preferences/{preference['id']}").status_code == 204
            assert not client.get("/api/v1/practice-preferences").json()
        finally:
            client.delete(f"/api/v1/material-sets/{set_id}")
        assert client.get(f"/api/v1/conversations/{cid}/practice-state").status_code == 404
        assert not client.get("/api/v1/practice-preferences").json()


def test_feedback_retry_keeps_one_answer_and_cancel_does_not_publish(monkeypatch):
    import asyncio
    import threading
    from app.infrastructure.llm import FakeLLMClient, LLMError
    from app.service import practice_service, agent_follow_up_service

    class ControlledLLM(FakeLLMClient):
        fail = True
        block = False
        entered = threading.Event()
        release = threading.Event()

        async def structured(self, **kwargs):
            if kwargs["mode"] == "feedback":
                if self.fail:
                    self.fail = False
                    raise LLMError("测试：供应商暂时失败")
                if self.block:
                    self.entered.set()
                    await asyncio.to_thread(self.release.wait, 5)
            return await super().structured(**kwargs)

    llm = ControlledLLM()
    monkeypatch.setattr(practice_service, "get_llm_client", lambda: llm)
    monkeypatch.setattr(agent_follow_up_service, "get_llm_client", lambda: llm)
    with TestClient(app) as client:
        set_id, _, cid = setup_conversation(client)
        try:
            send(client, cid, "生成 2 个问题")
            posted = client.post(f"/api/v1/conversations/{cid}/input-runs", json={"content": "我负责缓存，请点评", "clientRequestId": str(uuid4())}).json()
            assert wait_run(client, posted["runId"])["status"] == "failed"
            turns = client.get(f"/api/v1/conversations/{cid}/practice-turns").json()["items"]
            assert turns[0]["answerVersion"] == 1 and turns[0]["feedback"] is None
            retry = client.post(f"/api/v1/llm-runs/{posted['runId']}/retry").json()
            assert wait_run(client, retry["runId"])["status"] == "succeeded"
            assert client.get(f"/api/v1/conversations/{cid}/practice-state").json()["lastRunId"] == retry["runId"]
            assert client.get(f"/api/v1/conversations/{cid}/practice-turns").json()["items"][0]["answerVersion"] == 1
            llm.block = True
            blocked = client.post(f"/api/v1/conversations/{cid}/input-runs", json={"content": "我补充过期策略，请点评", "clientRequestId": str(uuid4())}).json()
            assert llm.entered.wait(3)
            assert client.post(f"/api/v1/conversations/{cid}/input-runs", json={"content": "下一题", "clientRequestId": str(uuid4())}).status_code == 409
            assert client.post(f"/api/v1/practice-turns/{turns[0]['id']}/feedback-runs").status_code == 409
            assert client.post(f"/api/v1/llm-runs/{blocked['runId']}/cancel").json()["status"] == "cancelled"
            llm.release.set()
            assert wait_run(client, blocked["runId"])["status"] == "cancelled"
            turns = client.get(f"/api/v1/conversations/{cid}/practice-turns").json()["items"]
            assert turns[0]["answerVersion"] == 2 and turns[0]["feedback"] is None
        finally:
            llm.release.set()
            client.delete(f"/api/v1/material-sets/{set_id}")
