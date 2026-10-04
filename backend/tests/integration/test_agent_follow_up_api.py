import time
from io import BytesIO
from zipfile import ZipFile

from docx import Document
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings


def _resume_bytes() -> bytes:
    document = Document()
    document.add_paragraph("张三\nPython 后端工程师\n负责订单服务，使用 Redis 缓存。")
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _project_bytes() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("src/cache.py", "def cache():\n    return 'redis'\n")
    return output.getvalue()


def _wait_run(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/llm-runs/{run_id}").json()
        if body["status"] in {"succeeded", "failed", "cancelled"}:
            return body
        time.sleep(0.03)
    raise AssertionError("异步任务未在测试窗口完成")


def test_question_run_is_async_and_answer_save_has_no_llm_side_effect():
    with TestClient(app) as client:
        material_set = client.post("/api/v1/material-sets", json={"title": "Agent 集成测试"}).json()
        set_id = material_set["id"]
        try:
            uploaded = client.post(
                f"/api/v1/material-sets/{set_id}/materials?kind=resume",
                files={"file": ("resume.docx", _resume_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            )
            material_id = uploaded.json()["materials"][0]["id"]
            deadline = time.monotonic() + 3
            while client.get(f"/api/v1/materials/{material_id}/recognition").json()["recognitionStatus"] != "awaitingConfirmation":
                assert time.monotonic() < deadline
                time.sleep(0.03)
            conversation = client.post(f"/api/v1/material-sets/{set_id}/conversations", json={"title": "异步练习"}).json()
            response = client.post(
                f"/api/v1/conversations/{conversation['id']}/question-runs",
                json={"resumeSections": ["skills"], "direction": "实现细节", "count": 2},
            )
            assert response.status_code == 202
            run = response.json()
            assert run["status"] in {"queued", "running", "succeeded"}
            completed = _wait_run(client, run["runId"])
            assert completed["status"] == "succeeded"
            turns = client.get(f"/api/v1/conversations/{conversation['id']}/practice-turns")
            assert turns.status_code == 200
            assert turns.json()["items"]
            turn_id = turns.json()["items"][0]["id"]
            saved = client.post(f"/api/v1/practice-turns/{turn_id}/answers", json={"content": "我负责缓存设计。"})
            assert saved.status_code == 201
            assert saved.json()["answer"] == "我负责缓存设计。"
            assert client.get(f"/api/v1/llm-runs/{run['runId']}").json()["status"] == "succeeded"
            feedback = client.post(f"/api/v1/practice-turns/{turn_id}/feedback-runs")
            assert feedback.status_code == 202
            assert _wait_run(client, feedback.json()["runId"])["status"] == "succeeded"
            follow_up = client.post(f"/api/v1/practice-turns/{turn_id}/follow-up-runs")
            assert follow_up.status_code == 202
            assert _wait_run(client, follow_up.json()["runId"])["status"] == "succeeded"
        finally:
            client.delete(f"/api/v1/material-sets/{set_id}")


def test_reference_answer_run_reuses_same_code_snapshot():
    with TestClient(app) as client:
        material_set = client.post("/api/v1/material-sets", json={"title": "参考答案测试"}).json()
        set_id = material_set["id"]
        try:
            uploaded = client.post(
                f"/api/v1/material-sets/{set_id}/materials?kind=resume",
                files={"file": ("resume.docx", _resume_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            )
            material_id = uploaded.json()["materials"][0]["id"]
            deadline = time.monotonic() + 3
            while client.get(f"/api/v1/materials/{material_id}/recognition").json()["recognitionStatus"] != "awaitingConfirmation":
                assert time.monotonic() < deadline
                time.sleep(0.03)
            conversation = client.post(f"/api/v1/material-sets/{set_id}/conversations", json={}).json()
            generated = client.post(f"/api/v1/conversations/{conversation['id']}/question-runs", json={"count": 1}).json()
            completed = _wait_run(client, generated["runId"])
            turn_id = client.get(f"/api/v1/conversations/{conversation['id']}/practice-turns").json()["items"][0]["id"]
            assert client.post(f"/api/v1/practice-turns/{turn_id}/answers", json={"content": "我负责核心实现。"}).status_code == 201
            first = client.post(f"/api/v1/practice-turns/{turn_id}/reference-answer-runs", json={})
            assert first.status_code == 202
            first_run = _wait_run(client, first.json()["runId"])
            assert first_run["status"] == "succeeded"
            second = client.post(f"/api/v1/practice-turns/{turn_id}/reference-answer-runs", json={})
            assert second.status_code in {200, 202}
            assert second.json()["runId"] == first.json()["runId"]
        finally:
            client.delete(f"/api/v1/material-sets/{set_id}")


def test_delete_material_set_removes_agent_runs_and_conversation():
    with TestClient(app) as client:
        set_id = client.post("/api/v1/material-sets", json={"title": "追问删除级联"}).json()["id"]
        uploaded_project = client.post(f"/api/v1/material-sets/{set_id}/materials?kind=projectArchive", files={"file": ("project.zip", _project_bytes(), "application/zip")}).json()
        project_id = uploaded_project["materials"][0]["id"]
        conversation = client.post(f"/api/v1/material-sets/{set_id}/conversations", json={}).json()
        run = client.post(f"/api/v1/conversations/{conversation['id']}/question-runs", json={"scopeType": "project", "targetIds": [project_id], "count": 1}).json()
        assert _wait_run(client, run["runId"])["status"] == "succeeded"
        deleted = client.delete(f"/api/v1/material-sets/{set_id}")
        assert deleted.status_code == 204
        assert client.get(f"/api/v1/llm-runs/{run['runId']}").status_code == 404
        assert client.get(f"/api/v1/conversations/{conversation['id']}").status_code == 404


def test_redis_unavailable_returns_problem_details_without_losing_run(monkeypatch):
    class BrokenCelery:
        def __init__(self, *args, **kwargs):
            pass

        def send_task(self, *args, **kwargs):
            raise ConnectionError("redis down")

    monkeypatch.setattr(settings, "task_queue_backend", "celery")
    monkeypatch.setattr("app.infrastructure.task_queue.Celery", BrokenCelery)
    with TestClient(app) as client:
        set_id = client.post("/api/v1/material-sets", json={"title": "队列故障测试"}).json()["id"]
        try:
            client.post(f"/api/v1/material-sets/{set_id}/materials?kind=projectArchive", files={"file": ("project.zip", _project_bytes(), "application/zip")})
            conversation = client.post(f"/api/v1/material-sets/{set_id}/conversations", json={}).json()
            response = client.post(f"/api/v1/conversations/{conversation['id']}/question-runs", json={"count": 1})
            assert response.status_code == 503
            assert response.json()["code"] == "TASK_QUEUE_UNAVAILABLE"
        finally:
            client.delete(f"/api/v1/material-sets/{set_id}")


def test_feedback_requires_answer_and_answer_versions_are_persisted():
    with TestClient(app) as client:
        set_id = client.post("/api/v1/material-sets", json={"title": "版本语义测试"}).json()["id"]
        try:
            client.post(f"/api/v1/material-sets/{set_id}/materials?kind=projectArchive", files={"file": ("project.zip", _project_bytes(), "application/zip")})
            conversation = client.post(f"/api/v1/material-sets/{set_id}/conversations", json={}).json()
            generated = client.post(f"/api/v1/conversations/{conversation['id']}/question-runs", json={"count": 1}).json()
            assert _wait_run(client, generated["runId"])["status"] == "succeeded"
            turn_id = client.get(f"/api/v1/conversations/{conversation['id']}/practice-turns").json()["items"][0]["id"]
            assert client.post(f"/api/v1/practice-turns/{turn_id}/feedback-runs").status_code == 409
            first = client.post(f"/api/v1/practice-turns/{turn_id}/answers", json={"content": "我负责缓存设计。"})
            assert first.status_code == 201 and first.json()["answerVersion"] == 1
            feedback = client.post(f"/api/v1/practice-turns/{turn_id}/feedback-runs")
            assert _wait_run(client, feedback.json()["runId"])["status"] == "succeeded"
            second = client.post(f"/api/v1/practice-turns/{turn_id}/answers", json={"content": "我负责缓存和降级策略。"})
            assert second.status_code == 201 and second.json()["answerVersion"] == 2
            turns = client.get(f"/api/v1/conversations/{conversation['id']}/practice-turns").json()["items"]
            assert turns[0]["answerVersion"] == 2
        finally:
            client.delete(f"/api/v1/material-sets/{set_id}")
