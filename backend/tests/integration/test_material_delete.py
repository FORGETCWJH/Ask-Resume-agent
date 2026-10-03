from io import BytesIO
from zipfile import ZipFile

from docx import Document
from fastapi.testclient import TestClient

from app.main import app


def _resume_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _project_bytes() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("README.md", "项目原始证据")
    return output.getvalue()


def test_delete_one_material_creates_revision_and_preserves_history():
    with TestClient(app) as client:
        created = client.post("/api/v1/material-sets", json={"title": "单份删除测试"}).json()
        set_id = created["id"]
        try:
            first = client.post(
                f"/api/v1/material-sets/{set_id}/materials?kind=resume",
                files={"file": ("first.docx", _resume_bytes("第一份简历 独有内容"))},
            ).json()
            old_id = first["materials"][0]["id"]
            conversation = client.post(f"/api/v1/material-sets/{set_id}/conversations", json={"title": "历史练习"}).json()
            second = client.post(
                f"/api/v1/material-sets/{set_id}/materials?kind=resume",
                files={"file": ("second.docx", _resume_bytes("第二份简历 独有内容"))},
            ).json()
            current_first = next(item for item in second["materials"] if item["filename"] == "first.docx")
            current_second = next(item for item in second["materials"] if item["filename"] == "second.docx")

            deleted = client.delete(f"/api/v1/materials/{current_first['id']}")
            assert deleted.status_code == 204
            current = client.get(f"/api/v1/material-sets/{set_id}").json()
            assert current["activeRevisionId"] != second["activeRevisionId"]
            assert [item["filename"] for item in current["materials"]] == ["second.docx"]
            assert client.get(f"/api/v1/conversations/{conversation['id']}").status_code == 200
            assert client.get(f"/api/v1/materials/{old_id}/recognition").status_code == 200
            assert client.delete(f"/api/v1/materials/{current_first['id']}").status_code == 409
            assert client.delete(f"/api/v1/materials/{current_second['id']}").status_code == 409
            assert client.delete("/api/v1/materials/missing").status_code == 404
        finally:
            assert client.delete(f"/api/v1/material-sets/{set_id}").status_code == 204


def test_project_material_can_be_retried_without_duplicate_evidence():
    with TestClient(app) as client:
        set_id = client.post("/api/v1/material-sets", json={"title": "项目重试测试"}).json()["id"]
        try:
            uploaded = client.post(
                f"/api/v1/material-sets/{set_id}/materials?kind=projectArchive",
                files={"file": ("project.zip", _project_bytes(), "application/zip")},
            )
            material_id = uploaded.json()["materials"][0]["id"]
            before = client.get(f"/api/v1/material-sets/{set_id}/evidence").json()
            assert len(before) == 1
            retried = client.post(f"/api/v1/materials/{material_id}/retry")
            assert retried.status_code == 200
            after = client.get(f"/api/v1/material-sets/{set_id}/evidence").json()
            assert len(after) == 1
            assert after[0]["content"] == before[0]["content"]
        finally:
            assert client.delete(f"/api/v1/material-sets/{set_id}").status_code == 204
