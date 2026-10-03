from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models import EvidenceChunk, Material, MaterialRevision, MaterialSet, ResumeEvidenceLink, ResumeExtractionDraft


class MaterialSetRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, set_id: str) -> MaterialSet | None:
        return self.db.get(MaterialSet, set_id)

    def list_sets(self, limit: int, offset: int) -> list[MaterialSet]:
        return self.db.query(MaterialSet).order_by(MaterialSet.updated_at.desc()).offset(offset).limit(limit).all()

    def add(self, item: MaterialSet) -> MaterialSet:
        self.db.add(item)
        self.db.flush()
        return item

    def materials_for_revision(self, revision_id: str | None) -> list[Material]:
        if not revision_id:
            return []
        return self.db.query(Material).filter(Material.revision_id == revision_id).all()

    def evidence_for_materials(self, material_ids: list[str], query: str | None = None) -> list[EvidenceChunk]:
        if not material_ids:
            return []
        if query and query.strip():
            rows = self.db.execute(text("SELECT evidence_id FROM evidence_fts WHERE evidence_fts MATCH :query LIMIT 50"), {"query": query.strip()}).all()
            ids = [row[0] for row in rows]
            if not ids:
                return []
            return self.db.query(EvidenceChunk).filter(EvidenceChunk.id.in_(ids), EvidenceChunk.material_id.in_(material_ids)).all()
        return self.db.query(EvidenceChunk).filter(EvidenceChunk.material_id.in_(material_ids)).limit(100).all()

    def clear_evidence_for_material(self, material_id: str) -> None:
        for chunk in self.db.query(EvidenceChunk).filter(EvidenceChunk.material_id == material_id).all():
            self.db.execute(text("DELETE FROM evidence_fts WHERE evidence_id = :id"), {"id": chunk.id})
            self.db.delete(chunk)
        self.db.flush()

    def create_revision(self, item: MaterialSet, exclude_material_id: str | None = None) -> MaterialRevision:
        previous = [material for material in self.materials_for_revision(item.active_revision_id) if material.id != exclude_material_id]
        revision = MaterialRevision(material_set_id=item.id)
        self.db.add(revision)
        self.db.flush()
        material_map: dict[str, str] = {}
        evidence_map: dict[str, str] = {}
        for old_material in previous:
            copied = Material(revision_id=revision.id, kind=old_material.kind, filename=old_material.filename, storage_path=old_material.storage_path, size_bytes=old_material.size_bytes, status=old_material.status, error_message=old_material.error_message)
            self.db.add(copied)
            self.db.flush()
            material_map[old_material.id] = copied.id
            for old_chunk in self.db.query(EvidenceChunk).filter(EvidenceChunk.material_id == old_material.id).all():
                copied_chunk = EvidenceChunk(material_id=copied.id, content=old_chunk.content, source_path=old_chunk.source_path, page_number=old_chunk.page_number, line_start=old_chunk.line_start, line_end=old_chunk.line_end, chunk_order=old_chunk.chunk_order)
                self.db.add(copied_chunk)
                self.db.flush()
                evidence_map[old_chunk.id] = copied_chunk.id
                self.db.execute(text("INSERT INTO evidence_fts(evidence_id, content, source_path) VALUES (:id, :content, :path)"), {"id": copied_chunk.id, "content": copied_chunk.content, "path": copied_chunk.source_path or ""})
        for old_material_id, new_material_id in material_map.items():
            old_draft = self.db.query(ResumeExtractionDraft).filter(ResumeExtractionDraft.material_id == old_material_id).order_by(ResumeExtractionDraft.created_at.desc()).first()
            if not old_draft:
                continue
            copied_draft = ResumeExtractionDraft(
                material_id=new_material_id,
                revision_id=revision.id,
                status=old_draft.status,
                draft_json=old_draft.draft_json,
                warnings_json=old_draft.warnings_json,
                confirmed_sections_json=old_draft.confirmed_sections_json,
                extractor_version=old_draft.extractor_version,
            )
            self.db.add(copied_draft)
            self.db.flush()
            links = self.db.query(ResumeEvidenceLink).filter(ResumeEvidenceLink.draft_id == old_draft.id).all()
            for link in links:
                mapped_evidence_id = evidence_map.get(link.evidence_chunk_id)
                if mapped_evidence_id:
                    self.db.add(ResumeEvidenceLink(
                        draft_id=copied_draft.id,
                        section=link.section,
                        field_path=link.field_path,
                        evidence_chunk_id=mapped_evidence_id,
                        page_number=link.page_number,
                        source_path=link.source_path,
                        origin=link.origin,
                    ))
        item.active_revision_id = revision.id
        return revision
