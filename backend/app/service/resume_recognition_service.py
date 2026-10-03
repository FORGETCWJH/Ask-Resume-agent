import json
import asyncio
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from ..common.errors import AppError, not_found
from ..db import SessionLocal
from ..domain.resume_recognition import transition_status
from ..dto.material import RecognitionOut
from ..infrastructure.resume_parser import build_local_draft, empty_draft
from ..infrastructure.ingestion import ingest_resume
from ..models import EvidenceChunk, Material, ResumeEvidenceLink, ResumeExtractionDraft


SECTIONS = ("personalInfo", "skills", "workExperiences", "projects")
_BACKGROUND_JOBS: set[str] = set()
_KEY_ALIASES = {
    "personal_info": "personalInfo",
    "work_experiences": "workExperiences",
    "evidence_ids": "evidenceIds",
    "target_role": "targetRole",
    "start_date": "startDate",
    "end_date": "endDate",
    "experience_type": "experienceType",
    "time_range": "timeRange",
    "project_archive_id": "projectArchiveId",
}
_DRAFT_FIELDS = {
    "personalInfo": {"name", "phone", "email", "city", "targetRole", "links", "evidenceIds", "confidence", "edited"},
    "skills": {"content", "evidenceIds", "confidence", "edited"},
    "workExperiences": {"company", "role", "startDate", "endDate", "experienceType", "description", "evidenceIds", "confidence", "edited"},
    "projects": {"name", "timeRange", "role", "technologies", "description", "links", "projectArchiveId", "evidenceIds", "confidence", "edited"},
}


def _join_text(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        cleaned = value.strip()
        if cleaned and cleaned not in parts:
            parts.append(cleaned)
    return "\n".join(parts)


def _append_text_once(base: str, extra: str) -> str:
    base = base.strip()
    extra = extra.strip()
    if not extra or extra in base:
        return base
    return _join_text(base, extra)


def _trim_work_description(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    text = re.split(r"\n\s*(?:项目经验|个人项目|项目经历)\s*(?:\n|$)", text, maxsplit=1)[0]
    if "\n项目：" in text and ("项目名称：" in text or "核心技术：" in text):
        text = text.split("\n项目：", 1)[0]
    return text.strip()


def _is_project_skill_category(value: str) -> bool:
    category = value.lstrip("\ufeff").strip()
    exact_markers = {"项目名称", "项目背景", "项目描述", "核心职责与贡献", "核心技术", "登录认证", "缓存优化", "秒杀优化", "下单防重"}
    return category in exact_markers or category.startswith(("工作流", "评估-优化", "复色链路"))


def _evidence_ids(*values: Any) -> list[str]:
    result: list[str] = []
    for value in values:
        if isinstance(value, list):
            for item in value:
                item = str(item)
                if item and item not in result:
                    result.append(item)
    return result


def _compact_skills(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        content = value.get("content")
        if not isinstance(content, str):
            content = _join_text(value.get("description"))
        return {
            "content": content.strip(),
            "evidenceIds": _evidence_ids(value.get("evidenceIds")),
            "confidence": value.get("confidence", 0.0),
            "edited": bool(value.get("edited", False)),
        }
    if not isinstance(value, list):
        return {"content": "", "evidenceIds": [], "confidence": 0.0, "edited": False}
    lines: list[str] = []
    evidence_ids: list[str] = []
    confidence = 0.0
    edited = False
    for item in value:
        if not isinstance(item, dict):
            continue
        description = str(item.get("description") or item.get("content") or "").strip()
        category = str(item.get("category") or "").strip()
        if _is_project_skill_category(category):
            break
        if description:
            lines.append(f"{category}：{description}" if category else description)
        evidence_ids = _evidence_ids(evidence_ids, item.get("evidenceIds"))
        confidence = max(confidence, float(item.get("confidence") or 0.0))
        edited = edited or bool(item.get("edited", False))
    return {"content": "\n".join(lines), "evidenceIds": evidence_ids, "confidence": confidence, "edited": edited}


def _compact_work(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        description = _trim_work_description(item.get("description") or item.get("rawText"))
        has_project_details = bool(re.search(r"项目名称|核心技术|项目背景|实习内容|工作内容|职责", description))
        if not description or not has_project_details:
            for project in item.get("projects", []) if isinstance(item.get("projects"), list) else []:
                if not isinstance(project, dict):
                    continue
                project_parts = []
                if project.get("name"):
                    project_parts.append(f"项目：{project['name']}")
                for label, key in (("背景", "background"), ("职责", "responsibilities"), ("成果描述", "metrics")):
                    if project.get(key):
                        project_parts.append(f"{label}：{project[key]}")
                description = _append_text_once(description, "\n".join(project_parts))
        result.append({
            "company": str(item.get("company") or ""),
            "role": str(item.get("role") or ""),
            "startDate": str(item.get("startDate") or ""),
            "endDate": str(item.get("endDate") or ""),
            "experienceType": str(item.get("experienceType") or "work"),
            "description": description,
            "evidenceIds": _evidence_ids(item.get("evidenceIds"), *(project.get("evidenceIds") for project in item.get("projects", []) if isinstance(project, dict))),
            "confidence": item.get("confidence", 0.0),
            "edited": bool(item.get("edited", False)),
        })
    return result


def _compact_projects(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        description = _append_text_once(str(item.get("description") or ""), str(item.get("contributions") or ""))
        if item.get("metrics"):
            description = _append_text_once(description, f"成果描述：{item['metrics']}")
        result.append({
            "name": str(item.get("name") or ""),
            "timeRange": str(item.get("timeRange") or ""),
            "role": str(item.get("role") or ""),
            "technologies": item.get("technologies") if isinstance(item.get("technologies"), list) else [],
            "description": description,
            "links": item.get("links") if isinstance(item.get("links"), list) else [],
            "projectArchiveId": item.get("projectArchiveId"),
            "evidenceIds": _evidence_ids(item.get("evidenceIds")),
            "confidence": item.get("confidence", 0.0),
            "edited": bool(item.get("edited", False)),
        })
    return result


def _compact_draft(candidate: Any) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        return {}
    normalized = _normalize_keys(candidate)
    return {
        "personalInfo": normalized.get("personalInfo", {}) if isinstance(normalized.get("personalInfo"), dict) else {},
        "skills": _compact_skills(normalized.get("skills")),
        "workExperiences": _compact_work(normalized.get("workExperiences")),
        "projects": _compact_projects(normalized.get("projects")),
    }


def _normalize_keys(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_keys(item) for item in value]
    if isinstance(value, dict):
        return {_KEY_ALIASES.get(key, key): _normalize_keys(item) for key, item in value.items()}
    return value


def _filter_draft_shape(draft: dict[str, Any]) -> dict[str, Any]:
    filtered: dict[str, Any] = {}
    for section, allowed in _DRAFT_FIELDS.items():
        value = draft.get(section)
        if section == "personalInfo":
            filtered[section] = {key: item for key, item in value.items() if key in allowed} if isinstance(value, dict) else {}
            continue
        if section == "skills":
            filtered[section] = {key: item for key, item in value.items() if key in allowed} if isinstance(value, dict) else deepcopy(empty_draft()[section])
            continue
        if not isinstance(value, list):
            filtered[section] = []
            continue
        entries: list[dict[str, Any]] = []
        for entry in value:
            if not isinstance(entry, dict):
                continue
            clean = {key: item for key, item in entry.items() if key in allowed}
            entries.append(clean)
        filtered[section] = entries
    return filtered


def _deep_merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _normalize_draft(candidate: dict[str, Any], fallback: dict[str, Any], valid_evidence_ids: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        return _compact_draft(fallback)
    fallback = _compact_draft(fallback)
    candidate = _compact_draft(candidate)
    if valid_evidence_ids is not None:
        skills = candidate.get("skills")
        fallback_skills = fallback.get("skills", {}) if isinstance(fallback.get("skills"), dict) else {}
        if isinstance(skills, dict):
            ids = {str(value) for value in skills.get("evidenceIds", []) if str(value) in valid_evidence_ids}
            if skills.get("content") and not ids and fallback_skills.get("evidenceIds"):
                candidate["skills"] = deepcopy(fallback_skills)
            else:
                skills["evidenceIds"] = list(ids) or list(fallback_skills.get("evidenceIds", []))
        for section in ("workExperiences", "projects"):
            candidate_items = candidate.get(section)
            fallback_items = fallback.get(section, []) if isinstance(fallback.get(section), list) else []
            if not isinstance(candidate_items, list) or not candidate_items:
                candidate[section] = deepcopy(fallback_items)
                continue
            safe_items: list[dict[str, Any]] = []
            for index, item in enumerate(candidate_items):
                if not isinstance(item, dict):
                    continue
                ids = {str(value) for value in item.get("evidenceIds", []) if str(value) in valid_evidence_ids}
                if not ids:
                    if index < len(fallback_items) and isinstance(fallback_items[index], dict):
                        safe_items.append(deepcopy(fallback_items[index]))
                    continue
                item["evidenceIds"] = list(ids)
                safe_items.append(item)
            candidate[section] = safe_items or deepcopy(fallback_items)
    result = _deep_merge(empty_draft(), fallback)
    result = _deep_merge(result, candidate)
    result = _filter_draft_shape(result)
    for section in SECTIONS:
        if section not in result:
            result[section] = [] if section != "personalInfo" else {}
    local_info = fallback.get("personalInfo", {}) if isinstance(fallback.get("personalInfo"), dict) else {}
    merged_info = result.get("personalInfo") if isinstance(result.get("personalInfo"), dict) else {}
    # Contact fields are extracted locally because they are intentionally redacted from the model context.
    for field in ("name", "phone", "email", "city", "links"):
        if local_info.get(field):
            merged_info[field] = deepcopy(local_info[field])
    result["personalInfo"] = merged_info
    skills = result.get("skills") if isinstance(result.get("skills"), dict) else {}
    if not skills.get("evidenceIds"):
        skills["evidenceIds"] = fallback.get("skills", {}).get("evidenceIds", []) if isinstance(fallback.get("skills"), dict) else []
    result["skills"] = skills
    for section in ("workExperiences", "projects"):
        fallback_items = fallback.get(section, []) if isinstance(fallback.get(section), list) else []
        if not isinstance(result.get(section), list):
            result[section] = fallback_items
        for index, item in enumerate(result[section]):
            if not isinstance(item, dict) or item.get("evidenceIds"):
                continue
            if index < len(fallback_items) and isinstance(fallback_items[index], dict):
                item["evidenceIds"] = fallback_items[index].get("evidenceIds", [])
    return result


class ResumeRecognitionService:
    def __init__(self, db: Session):
        self.db = db

    def material(self, material_id: str) -> Material:
        material = self.db.get(Material, material_id)
        if not material:
            raise not_found("MATERIAL_NOT_FOUND", "材料不存在")
        if material.kind != "resume":
            raise AppError(409, "RESUME_REQUIRED", "Resume material is required", "只有简历材料支持结构化识别")
        return material

    def draft(self, material_id: str) -> ResumeExtractionDraft:
        draft = self.db.query(ResumeExtractionDraft).filter(ResumeExtractionDraft.material_id == material_id).order_by(ResumeExtractionDraft.created_at.desc()).first()
        if not draft:
            raise not_found("RECOGNITION_NOT_FOUND", "简历识别草稿不存在")
        current = json.loads(draft.draft_json or "{}")
        compact = _compact_draft(current)
        if compact != current:
            draft.draft_json = json.dumps(compact, ensure_ascii=False)
            self._replace_links(draft, compact)
            self.db.flush()
        return draft

    def _chunks(self, material_id: str) -> list[dict[str, Any]]:
        chunks = self.db.query(EvidenceChunk).filter(
            EvidenceChunk.material_id == material_id,
            or_(EvidenceChunk.source_path.is_(None), ~EvidenceChunk.source_path.like("resume-recognition:%")),
        ).order_by(EvidenceChunk.chunk_order.asc()).all()
        return [{"id": chunk.id, "content": chunk.content, "source_path": chunk.source_path, "page_number": chunk.page_number} for chunk in chunks]

    def _ensure_draft(self, material: Material) -> ResumeExtractionDraft:
        draft = self.db.query(ResumeExtractionDraft).filter(ResumeExtractionDraft.material_id == material.id).order_by(ResumeExtractionDraft.created_at.desc()).first()
        if draft:
            return draft
        draft = ResumeExtractionDraft(material_id=material.id, revision_id=material.revision_id, status="pending", draft_json=json.dumps(empty_draft(), ensure_ascii=False))
        self.db.add(draft)
        self.db.flush()
        return draft

    def initialize_pending(self, material_id: str, warnings: list[dict[str, Any]] | None = None) -> ResumeExtractionDraft:
        material = self.material(material_id)
        draft = self._ensure_draft(material)
        draft.status = "pending"
        draft.warnings_json = json.dumps(warnings or [], ensure_ascii=False)
        self.db.flush()
        return draft

    def _replace_links(self, draft: ResumeExtractionDraft, structured: dict[str, Any]) -> None:
        self.db.query(ResumeEvidenceLink).filter(ResumeEvidenceLink.draft_id == draft.id).delete(synchronize_session=False)
        chunks = {chunk.id: chunk for chunk in self.db.query(EvidenceChunk).filter(
            EvidenceChunk.material_id == draft.material_id,
            or_(EvidenceChunk.source_path.is_(None), ~EvidenceChunk.source_path.like("resume-recognition:%")),
        ).all()}
        for section in SECTIONS:
            value = structured.get(section)
            if isinstance(value, dict):
                entries = [value]
            elif isinstance(value, list):
                entries = value
            else:
                entries = []
            for index, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    continue
                evidence_ids = entry.get("evidenceIds", [])
                paths = [section if section == "skills" else f"{section}[{index}]"]
                if section == "personalInfo":
                    paths.extend(f"{section}.{field}" for field in ("name", "phone", "email", "city", "targetRole", "links") if entry.get(field))
                elif section == "skills":
                    paths.append("skills.content") if entry.get("content") else None
                else:
                    paths.extend(f"{section}[{index}].{field}" for field in ("company", "role", "startDate", "endDate", "experienceType", "name", "timeRange", "technologies", "description", "links", "projectArchiveId") if entry.get(field))
                for evidence_id in dict.fromkeys(evidence_ids if isinstance(evidence_ids, list) else []):
                    chunk = chunks.get(evidence_id)
                    if not chunk:
                        continue
                    for field_path in paths:
                        self.db.add(ResumeEvidenceLink(
                            draft_id=draft.id,
                            section=section,
                            field_path=field_path,
                            evidence_chunk_id=chunk.id,
                            page_number=chunk.page_number,
                            source_path=chunk.source_path,
                            origin="candidate" if entry.get("edited") else "local",
                        ))

    async def process(self, material_id: str, ingestion_warnings: list[dict[str, Any]] | None = None) -> ResumeExtractionDraft:
        material = self.material(material_id)
        draft = self._ensure_draft(material)
        previously_confirmed = json.loads(draft.confirmed_sections_json or "[]")
        for section in previously_confirmed:
            self._remove_structured_evidence(material.id, section)
        draft.confirmed_sections_json = "[]"
        if draft.status != "processing":
            draft.status = transition_status(draft.status, "processing")
        chunks = self._chunks(material.id)
        warnings: list[dict[str, Any]] = list(ingestion_warnings or [])
        if not chunks:
            draft.status = "failed"
            warnings.append({"code": "NO_RESUME_EVIDENCE", "message": "没有可用的简历文本证据"})
            draft.warnings_json = json.dumps(warnings, ensure_ascii=False)
            self.db.flush()
            return draft
        result = build_local_draft(chunks)
        draft.draft_json = json.dumps(result, ensure_ascii=False)
        draft.warnings_json = json.dumps(warnings, ensure_ascii=False)
        draft.status = "awaitingConfirmation"
        self._replace_links(draft, result)
        self.db.flush()
        return draft

    def serialize(self, material: Material, draft: ResumeExtractionDraft) -> RecognitionOut:
        links: dict[str, list[str]] = {}
        for link in self.db.query(ResumeEvidenceLink).filter(ResumeEvidenceLink.draft_id == draft.id).all():
            links.setdefault(link.field_path, []).append(link.evidence_chunk_id)
        return RecognitionOut(
            material_id=material.id,
            revision_id=material.revision_id,
            material_status=material.status,
            recognition_status=draft.status,
            draft=json.loads(draft.draft_json or "{}"),
            warnings=json.loads(draft.warnings_json or "[]"),
            confirmed_sections=json.loads(draft.confirmed_sections_json or "[]"),
            evidence_links=links,
        )

    def get(self, material_id: str) -> RecognitionOut:
        material = self.material(material_id)
        draft = self.db.query(ResumeExtractionDraft).filter(ResumeExtractionDraft.material_id == material_id).order_by(ResumeExtractionDraft.created_at.desc()).first()
        if not draft:
            draft = self._ensure_draft(material)
            self.db.commit()
            self.db.refresh(draft)
        else:
            draft = self.draft(material_id)
        if draft.status == "pending" and material.status in {"processing", "ready", "partial"}:
            draft.status = transition_status(draft.status, "processing")
            self.db.commit()
            schedule_resume_recognition(material.id)
        return self.serialize(material, draft)

    def update(self, material_id: str, incoming: dict[str, Any]) -> RecognitionOut:
        if not isinstance(incoming, dict):
            raise AppError(422, "INVALID_RECOGNITION_DRAFT", "Invalid recognition draft", "识别草稿必须是 JSON 对象")
        material = self.material(material_id)
        draft = self.draft(material_id)
        current = json.loads(draft.draft_json or "{}")
        updated = _normalize_draft(incoming, current)
        changed_sections: set[str] = set()
        for section in SECTIONS:
            value = updated.get(section)
            if value != current.get(section):
                changed_sections.add(section)
            if isinstance(value, dict):
                value["edited"] = True if value != current.get(section) else value.get("edited", False)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and item != next((old for old in current.get(section, []) if isinstance(old, dict) and old.get("evidenceIds") == item.get("evidenceIds")), None):
                        item["edited"] = True
        confirmed = set(json.loads(draft.confirmed_sections_json or "[]"))
        for section in changed_sections:
            self._remove_structured_evidence(material.id, section)
            confirmed.discard(section)
        if changed_sections:
            draft.confirmed_sections_json = json.dumps([name for name in SECTIONS if name in confirmed], ensure_ascii=False)
            if draft.status == "confirmed":
                draft.status = transition_status(draft.status, "awaitingConfirmation")
        draft.draft_json = json.dumps(updated, ensure_ascii=False)
        self._replace_links(draft, updated)
        self.db.commit()
        self.db.refresh(draft)
        return self.serialize(material, draft)

    async def retry(self, material_id: str, scope: str = "recognition", page_number: int | None = None) -> RecognitionOut:
        material = self.material(material_id)
        draft = self.draft(material_id)
        if draft.status != "processing":
            draft.status = transition_status(draft.status, "processing")
        ingestion_warnings: list[dict[str, Any]] = []
        if scope in {"ocr", "all"}:
            ingestion_warnings = ingest_resume(self.db, material, Path(material.storage_path), page_number)
        self.db.flush()
        draft.warnings_json = json.dumps(ingestion_warnings, ensure_ascii=False) if ingestion_warnings else draft.warnings_json
        self.db.commit()
        schedule_resume_recognition(material.id)
        return self.get(material_id)

    def _remove_structured_evidence(self, material_id: str, section: str) -> None:
        rows = self.db.query(EvidenceChunk).filter(EvidenceChunk.material_id == material_id, EvidenceChunk.source_path == f"resume-recognition:{section}").all()
        for row in rows:
            self.db.execute(text("DELETE FROM evidence_fts WHERE evidence_id = :id"), {"id": row.id})
            self.db.delete(row)

    def confirm(self, material_id: str, section: str) -> RecognitionOut:
        material = self.material(material_id)
        draft = self.draft(material_id)
        if draft.status not in {"pending", "awaitingConfirmation", "confirmed", "failed"}:
            raise AppError(409, "RECOGNITION_NOT_READY", "Recognition is not ready", "简历识别结果尚未准备好")
        selected = list(SECTIONS) if section == "all" else [section]
        current = json.loads(draft.draft_json or "{}")
        confirmed = set(json.loads(draft.confirmed_sections_json or "[]"))
        for name in selected:
            self._remove_structured_evidence(material.id, name)
            value = current.get(name)
            if value not in (None, "", [], {}):
                content = json.dumps(value, ensure_ascii=False)
                source_path = f"resume-recognition:{name}"
                evidence = EvidenceChunk(material_id=material.id, content=content, source_path=source_path, chunk_order=0)
                self.db.add(evidence)
                self.db.flush()
                self.db.execute(text("INSERT INTO evidence_fts(evidence_id, content, source_path) VALUES (:id, :content, :path)"), {"id": evidence.id, "content": content, "path": source_path})
            confirmed.add(name)
        draft.confirmed_sections_json = json.dumps([name for name in SECTIONS if name in confirmed], ensure_ascii=False)
        draft.status = "confirmed" if all(name in confirmed for name in SECTIONS) else "awaitingConfirmation"
        self.db.commit()
        self.db.refresh(draft)
        return self.serialize(material, draft)


async def _run_resume_recognition(material_id: str) -> None:
    db = SessionLocal()
    try:
        material = db.get(Material, material_id)
        if not material:
            return
        service = ResumeRecognitionService(db)
        raw_evidence_exists = db.query(EvidenceChunk).filter(
            EvidenceChunk.material_id == material_id,
            or_(EvidenceChunk.source_path.is_(None), ~EvidenceChunk.source_path.like("resume-recognition:%")),
        ).first() is not None
        ingestion_warnings: list[dict[str, Any]] = []
        if not raw_evidence_exists:
            ingestion_warnings = ingest_resume(db, material, Path(material.storage_path))
            service.initialize_pending(material_id, ingestion_warnings)
        await service.process(material_id, ingestion_warnings)
        db.commit()
    except Exception as exc:
        db.rollback()
        material = db.get(Material, material_id)
        if material:
            service = ResumeRecognitionService(db)
            draft = service._ensure_draft(material)
            draft.status = "failed"
            draft.warnings_json = json.dumps([{"code": "RECOGNITION_BACKGROUND_FAILED", "message": str(exc)[:500]}], ensure_ascii=False)
            db.commit()
    finally:
        db.close()
        _BACKGROUND_JOBS.discard(material_id)


def schedule_resume_recognition(material_id: str) -> None:
    if material_id in _BACKGROUND_JOBS:
        return
    _BACKGROUND_JOBS.add(material_id)
    asyncio.create_task(_run_resume_recognition(material_id))
