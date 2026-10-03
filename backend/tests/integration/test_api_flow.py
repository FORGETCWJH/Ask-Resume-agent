from io import BytesIO
import time

from docx import Document
from fastapi.testclient import TestClient

from app.main import app


def _docx_bytes() -> bytes:
    document = Document()
    document.add_paragraph("负责订单服务，使用 Redis 缓存降低接口延迟。")
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def test_material_conversation_and_delete_flow():
    with TestClient(app) as client:
        created = client.post("/api/v1/material-sets", json={"title": "集成测试临时集合"})
        assert created.status_code == 201
        set_id = created.json()["id"]
        try:
            uploaded = client.post(f"/api/v1/material-sets/{set_id}/materials?kind=resume", files={"file": ("resume.docx", _docx_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
            assert uploaded.status_code == 202
            assert uploaded.json()["materials"][0]["status"] == "processing"

            deadline = time.monotonic() + 3
            while True:
                recognition = client.get(f"/api/v1/materials/{uploaded.json()['materials'][0]['id']}/recognition")
                assert recognition.status_code == 200
                recognition_body = recognition.json()
                if recognition_body["recognitionStatus"] == "awaitingConfirmation":
                    break
                assert recognition_body["recognitionStatus"] != "failed"
                assert time.monotonic() < deadline, recognition_body
                time.sleep(0.05)

            evidence = client.get(f"/api/v1/material-sets/{set_id}/evidence")
            assert evidence.status_code == 200
            assert evidence.json()

            batch = client.post(f"/api/v1/material-sets/{set_id}/question-batches")
            assert batch.status_code == 201
            assert batch.json()["status"] == "ready"
            assert batch.json()["questions"]

            conversation = client.post(f"/api/v1/material-sets/{set_id}/conversations", json={"title": "练习"})
            assert conversation.status_code == 201
            conversation_id = conversation.json()["id"]

            message = client.post(f"/api/v1/conversations/{conversation_id}/messages", json={"content": "这段经历怎么解释？", "mode": "selectedPassageQuestion", "selection": None})
            assert message.status_code == 201
            assert message.json()["message"]["response"]["evidence"]
            supplement_id = message.json()["message"]["response"]["evidenceGaps"][0]["supplementId"]

            confirmed = client.patch(f"/api/v1/conversations/{conversation_id}/supplements/{supplement_id}", json={"content": "接口延迟从 200ms 降到 80ms。"})
            assert confirmed.status_code == 200
            assert confirmed.json()["confirmed"] is True
        finally:
            deleted = client.delete(f"/api/v1/material-sets/{set_id}")
            assert deleted.status_code == 204

