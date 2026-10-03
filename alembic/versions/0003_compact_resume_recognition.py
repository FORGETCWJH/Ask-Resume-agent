"""compact resume recognition drafts without splitting descriptions"""

import json

from alembic import op
import sqlalchemy as sa


revision = "0003_compact_resume_recognition"
down_revision = "0002_resume_recognition"
branch_labels = None
depends_on = None


def _join_text(*values: object) -> str:
    parts: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        value = value.strip()
        if value and value not in parts:
            parts.append(value)
    return "\n".join(parts)


def _ids(*values: object) -> list[str]:
    result: list[str] = []
    for value in values:
        if not isinstance(value, list):
            continue
        for item in value:
            item = str(item)
            if item and item not in result:
                result.append(item)
    return result


def _compact_legacy_draft(value: object) -> dict:
    if not isinstance(value, dict):
        return {"personalInfo": {}, "skills": {"content": "", "evidenceIds": [], "confidence": 0.0, "edited": False}, "workExperiences": [], "projects": []}

    personal_info = value.get("personalInfo") if isinstance(value.get("personalInfo"), dict) else {}
    raw_skills = value.get("skills")
    skill_lines: list[str] = []
    skill_ids: list[str] = []
    skill_confidence = 0.0
    skill_edited = False
    if isinstance(raw_skills, dict):
        skill_lines = [_join_text(raw_skills.get("content"), raw_skills.get("description"))]
        skill_ids = _ids(raw_skills.get("evidenceIds"))
        skill_confidence = float(raw_skills.get("confidence") or 0.0)
        skill_edited = bool(raw_skills.get("edited", False))
    elif isinstance(raw_skills, list):
        for item in raw_skills:
            if not isinstance(item, dict):
                continue
            description = str(item.get("description") or item.get("content") or "").strip()
            category = str(item.get("category") or "").strip()
            if description:
                skill_lines.append(f"{category}：{description}" if category else description)
            skill_ids = _ids(skill_ids, item.get("evidenceIds"))
            skill_confidence = max(skill_confidence, float(item.get("confidence") or 0.0))
            skill_edited = skill_edited or bool(item.get("edited", False))

    work_experiences: list[dict] = []
    for item in value.get("workExperiences", []) if isinstance(value.get("workExperiences"), list) else []:
        if not isinstance(item, dict):
            continue
        description = _join_text(item.get("description"), item.get("rawText"))
        evidence_ids = _ids(item.get("evidenceIds"))
        for project in item.get("projects", []) if isinstance(item.get("projects"), list) else []:
            if not isinstance(project, dict):
                continue
            parts: list[str] = []
            if project.get("name"):
                parts.append(f"项目：{project['name']}")
            for label, field in (("背景", "background"), ("职责", "responsibilities"), ("成果描述", "metrics")):
                if project.get(field):
                    parts.append(f"{label}：{project[field]}")
            description = _join_text(description, "\n".join(parts))
            evidence_ids = _ids(evidence_ids, project.get("evidenceIds"))
        work_experiences.append({
            "company": str(item.get("company") or ""),
            "role": str(item.get("role") or ""),
            "startDate": str(item.get("startDate") or ""),
            "endDate": str(item.get("endDate") or ""),
            "experienceType": str(item.get("experienceType") or "work"),
            "description": description,
            "evidenceIds": evidence_ids,
            "confidence": item.get("confidence", 0.0),
            "edited": bool(item.get("edited", False)),
        })

    projects: list[dict] = []
    for item in value.get("projects", []) if isinstance(value.get("projects"), list) else []:
        if not isinstance(item, dict):
            continue
        description = _join_text(item.get("description"), item.get("contributions"))
        if item.get("metrics"):
            description = _join_text(description, f"成果描述：{item['metrics']}")
        projects.append({
            "name": str(item.get("name") or ""),
            "timeRange": str(item.get("timeRange") or ""),
            "role": str(item.get("role") or ""),
            "technologies": item.get("technologies") if isinstance(item.get("technologies"), list) else [],
            "description": description,
            "links": item.get("links") if isinstance(item.get("links"), list) else [],
            "projectArchiveId": item.get("projectArchiveId"),
            "evidenceIds": _ids(item.get("evidenceIds")),
            "confidence": item.get("confidence", 0.0),
            "edited": bool(item.get("edited", False)),
        })

    return {
        "personalInfo": personal_info,
        "skills": {"content": "\n".join(item for item in skill_lines if item), "evidenceIds": skill_ids, "confidence": skill_confidence, "edited": skill_edited},
        "workExperiences": work_experiences,
        "projects": projects,
    }


def _field_path(path: str) -> str:
    if path.startswith("skills["):
        return "skills.content"
    if ".metrics" in path or ".contributions" in path or ".rawText" in path or ".projects[" in path:
        prefix = path.split(".", 1)[0]
        return f"{prefix}.description"
    return path


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, draft_json FROM resume_extraction_drafts")).mappings().all()
    for row in rows:
        try:
            current = json.loads(row["draft_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            current = {}
        bind.execute(
            sa.text("UPDATE resume_extraction_drafts SET draft_json = :draft_json, extractor_version = :version WHERE id = :id"),
            {"id": row["id"], "draft_json": json.dumps(_compact_legacy_draft(current), ensure_ascii=False), "version": "resume-v2"},
        )
    links = bind.execute(sa.text("SELECT id, field_path FROM resume_evidence_links")).mappings().all()
    for row in links:
        bind.execute(sa.text("UPDATE resume_evidence_links SET field_path = :field_path WHERE id = :id"), {"id": row["id"], "field_path": _field_path(row["field_path"])})


def downgrade() -> None:
    # The compact shape is a data migration. Original OCR evidence remains intact,
    # but the previous split draft shape cannot be reconstructed without ambiguity.
    pass
