import time
from io import BytesIO

from docx import Document
from fastapi.testclient import TestClient

from app.main import app


def create_resume(client: TestClient):
    set_id = client.post("/api/v1/material-sets", json={"title": "历史管理测试"}).json()["id"]
    document = Document()
    document.add_paragraph("技能掌握\nPython、Redis")
    stream = BytesIO()
    document.save(stream)
    uploaded = client.post(f"/api/v1/material-sets/{set_id}/materials?kind=resume", files={"file": ("resume.docx", stream.getvalue())}).json()
    material_id = uploaded["materials"][0]["id"]
    deadline = time.monotonic() + 5
    while True:
        recognition = client.get(f"/api/v1/materials/{material_id}/recognition").json()
        if recognition["recognitionStatus"] != "processing":
            break
        assert time.monotonic() < deadline
        time.sleep(0.03)
    return set_id


def test_history_management_persists_and_filters_archive_and_group():
    with TestClient(app) as client:
        set_id = create_resume(client)
        try:
            first = client.post(f"/api/v1/material-sets/{set_id}/conversations", json={"title": "Redis 练习"}).json()
            second = client.post(f"/api/v1/material-sets/{set_id}/conversations", json={"title": "消息队列练习"}).json()
            group = client.post(f"/api/v1/material-sets/{set_id}/conversation-groups", json={"name": "后端专项"})
            assert group.status_code == 201, group.text
            group_id = group.json()["id"]
            changed = client.patch(f"/api/v1/conversations/{first['id']}", json={"isPinned": True, "groupId": group_id})
            assert changed.status_code == 200, changed.text
            assert changed.json()["isPinned"] is True
            archived = client.patch(f"/api/v1/conversations/{second['id']}", json={"isArchived": True})
            assert archived.status_code == 200
            active = client.get(f"/api/v1/material-sets/{set_id}/conversations?status=active").json()
            assert [item["id"] for item in active] == [first["id"]]
            all_rows = client.get(f"/api/v1/material-sets/{set_id}/conversations?status=all&q=队列").json()
            assert [item["id"] for item in all_rows] == [second["id"]]
            assert all_rows[0]["isArchived"] is True
            restored = client.patch(f"/api/v1/conversations/{second['id']}", json={"isArchived": False})
            assert restored.json()["isArchived"] is False
            renamed = client.patch(f"/api/v1/conversations/{first['id']}", json={"title": "Redis 深入练习"})
            assert renamed.json()["title"] == "Redis 深入练习"
        finally:
            client.delete(f"/api/v1/material-sets/{set_id}")


def test_archived_conversation_rejects_new_input_and_group_delete_unassigns():
    with TestClient(app) as client:
        set_id = create_resume(client)
        try:
            conversation = client.post(f"/api/v1/material-sets/{set_id}/conversations", json={"title": "归档只读"}).json()
            group = client.post(f"/api/v1/material-sets/{set_id}/conversation-groups", json={"name": "临时组"}).json()
            client.patch(f"/api/v1/conversations/{conversation['id']}", json={"groupId": group["id"], "isArchived": True})
            rejected = client.post(f"/api/v1/conversations/{conversation['id']}/input-runs", json={"content": "回答", "clientRequestId": "archive-input"})
            assert rejected.status_code == 409
            assert rejected.json()["code"] == "CONVERSATION_ARCHIVED"
            assert client.get(f"/api/v1/conversations/{conversation['id']}/practice-state").status_code == 200
            deleted = client.delete(f"/api/v1/conversation-groups/{group['id']}")
            assert deleted.status_code == 204
            row = client.get(f"/api/v1/conversations/{conversation['id']}").json()
            assert row["groupId"] is None
        finally:
            client.delete(f"/api/v1/material-sets/{set_id}")


def test_single_conversation_delete_is_idempotent_and_keeps_material_set():
    with TestClient(app) as client:
        set_id = create_resume(client)
        try:
            first = client.post(f"/api/v1/material-sets/{set_id}/conversations", json={"title": "保留材料"}).json()
            second = client.post(f"/api/v1/material-sets/{set_id}/conversations", json={"title": "待删除"}).json()
            assert client.delete(f"/api/v1/conversations/{second['id']}").status_code == 204
            assert client.delete(f"/api/v1/conversations/{second['id']}").status_code == 204
            assert client.get(f"/api/v1/conversations/{second['id']}").status_code == 404
            assert client.get(f"/api/v1/conversations/{first['id']}").status_code == 200
            assert client.get(f"/api/v1/material-sets/{set_id}").status_code == 200
        finally:
            client.delete(f"/api/v1/material-sets/{set_id}")
