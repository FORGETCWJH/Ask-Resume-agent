from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..common.errors import AppError, not_found
from ..dto.material import EvidenceOut, MaterialSetOut, MaterialSummary
from ..infrastructure.file_storage import LocalFileStorage
from ..models import CandidateSupplement, EvidenceChunk, Material, MaterialRevision, MaterialSet
from ..repository.material_repository import MaterialSetRepository
from ..infrastructure.ingestion import ingest_project, ingest_resume, save_upload
from .resume_recognition_service import ResumeRecognitionService, schedule_resume_recognition


class MaterialService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = MaterialSetRepository(db)
        self.storage = LocalFileStorage()

    def serialize(self, item: MaterialSet) -> MaterialSetOut:
        materials = self.repo.materials_for_revision(item.active_revision_id)
        return MaterialSetOut(
            id=item.id,
            title=item.title,
            active_revision_id=item.active_revision_id,
            materials=[MaterialSummary(id=m.id, kind=m.kind, filename=m.filename, status=m.status, size_bytes=m.size_bytes, error_message=m.error_message) for m in materials],
            created_at=item.created_at,
            updated_at=item.updated_at,
        )

    def create(self, title: str) -> MaterialSetOut:
        item = self.repo.add(MaterialSet(title=title))
        self.db.commit()
        self.db.refresh(item)
        return self.serialize(item)

    def list_sets(self, limit: int, offset: int) -> list[MaterialSetOut]:
        return [self.serialize(item) for item in self.repo.list_sets(limit, offset)]

    def get(self, set_id: str) -> MaterialSet:
        item = self.repo.get(set_id)
        if not item:
            raise not_found("MATERIAL_SET_NOT_FOUND", "材料集合不存在")
        return item

    async def upload(self, set_id: str, upload: UploadFile, kind: str) -> MaterialSetOut:
        item = self.get(set_id)
        suffix = Path(upload.filename or "").suffix.lower()
        allowed = {".pdf", ".docx"} if kind == "resume" else {".zip"}
        if suffix not in allowed:
            raise AppError(400, "UNSUPPORTED_FILE_TYPE", "Unsupported file type", f"不支持的文件类型：{suffix}")
        revision = self.repo.create_revision(item)
        material_dir = self.storage.material_dir(set_id, revision.id)
        original = material_dir / "original" / f"{kind}{suffix}"
        size = await save_upload(upload, original)
        material = Material(revision_id=revision.id, kind=kind, filename=upload.filename or original.name, storage_path=str(original), size_bytes=size)
        self.db.add(material)
        self.db.flush()
        recognition_deferred = False
        if kind == "resume":
            recognition = ResumeRecognitionService(self.db)
            material.status = "processing"
            recognition.initialize_pending(material.id, [])
            recognition_deferred = True
        else:
            ingest_project(self.db, material, original, material_dir / "extracted")
        self.db.commit()
        self.db.refresh(item)
        if recognition_deferred:
            schedule_resume_recognition(material.id)
        return self.serialize(item)

    def evidence(self, set_id: str, query: str | None) -> list[EvidenceOut]:
        item = self.get(set_id)
        if not item.active_revision_id:
            raise AppError(409, "MATERIAL_NOT_READY", "Material is not ready", "材料集合还没有可用版本")
        materials = self.repo.materials_for_revision(item.active_revision_id)
        chunks = self.repo.evidence_for_materials([m.id for m in materials], query)
        result = [EvidenceOut(id=c.id, material_id=c.material_id, content=c.content, source_path=c.source_path, page_number=c.page_number, line_start=c.line_start, line_end=c.line_end) for c in chunks]
        supplements = self.db.query(CandidateSupplement).filter(CandidateSupplement.material_set_id == set_id, CandidateSupplement.confirmed.is_(True)).all()
        result.extend(EvidenceOut(id=f"supplement:{s.id}", content=s.content, source_path="候选人补充内容") for s in supplements)
        return result

    def delete(self, set_id: str) -> None:
        item = self.get(set_id)
        revisions = self.db.query(MaterialRevision).filter(MaterialRevision.material_set_id == set_id).all()
        revision_ids = [revision.id for revision in revisions]
        material_ids = [material.id for material in self.db.query(Material).filter(Material.revision_id.in_(revision_ids)).all()] if revision_ids else []
        evidence_ids = [chunk.id for chunk in self.db.query(EvidenceChunk).filter(EvidenceChunk.material_id.in_(material_ids)).all()] if material_ids else []
        if evidence_ids:
            params = {f"id{i}": value for i, value in enumerate(evidence_ids)}
            placeholders = ",".join(f":id{i}" for i in range(len(evidence_ids)))
            self.db.execute(text(f"DELETE FROM evidence_fts WHERE evidence_id IN ({placeholders})"), params)
        self.db.delete(item)
        self.db.flush()
        from ..repository.practice_repository import PracticeRepository
        PracticeRepository(self.db).delete_orphan_preferences()
        self.db.commit()
        self.storage.delete_material_set(set_id)

    def delete_material(self, material_id: str) -> None:
        material = self.db.get(Material, material_id)
        if not material:
            raise not_found("MATERIAL_NOT_FOUND", "材料不存在")
        revision = self.db.get(MaterialRevision, material.revision_id)
        item = self.get(revision.material_set_id)
        if item.active_revision_id != material.revision_id:
            raise AppError(409, "MATERIAL_NOT_ACTIVE", "Material is not active", "只能删除当前版本中的材料")
        self.repo.create_revision(item, exclude_material_id=material_id)
        self.db.commit()

    def retry_project(self, material_id: str) -> MaterialSetOut:
        material = self.db.get(Material, material_id)
        if not material:
            raise not_found("MATERIAL_NOT_FOUND", "材料不存在")
        revision = self.db.get(MaterialRevision, material.revision_id)
        item = self.get(revision.material_set_id)
        if item.active_revision_id != material.revision_id:
            raise AppError(409, "MATERIAL_NOT_ACTIVE", "Material is not active", "只能重试当前版本中的材料")
        if material.kind != "project_archive":
            raise AppError(409, "PROJECT_ARCHIVE_REQUIRED", "Project archive required", "简历请使用识别重试接口")
        self.repo.clear_evidence_for_material(material.id)
        original = Path(material.storage_path)
        ingest_project(self.db, material, original, original.parent.parent / "extracted")
        self.db.commit()
        return self.serialize(item)
