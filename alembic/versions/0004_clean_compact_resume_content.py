"""remove project leakage and duplicate text from compact resume drafts"""

import json
import re

from alembic import op
import sqlalchemy as sa


revision = "0004_clean_compact_resume_content"
down_revision = "0003_compact_resume_recognition"
branch_labels = None
depends_on = None


def _trim_work_description(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    text = re.split(r"\n\s*(?:项目经验|个人项目|项目经历)\s*(?:\n|$)", text, maxsplit=1)[0]
    if "\n项目：" in text and ("项目名称：" in text or "核心技术：" in text):
        text = text.split("\n项目：", 1)[0]
    return text.strip()


def _dedupe_lines(value: object) -> str:
    if not isinstance(value, str):
        return ""
    seen: set[str] = set()
    result: list[str] = []
    for line in value.splitlines():
        line = line.strip()
        if not line or line in seen:
            continue
        seen.add(line)
        result.append(line)
    return "\n".join(result)


def _clean_draft(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    skills = value.get("skills") if isinstance(value.get("skills"), dict) else {}
    skill_lines: list[str] = []
    for line in str(skills.get("content") or "").splitlines():
        category = line.split("：", 1)[0].lstrip("\ufeff").strip()
        if category in {"项目名称", "项目背景", "项目描述", "核心职责与贡献", "核心技术", "登录认证", "缓存优化", "秒杀优化", "下单防重"} or category.startswith(("工作流", "评估-优化", "复色链路")):
            break
        if line.strip():
            skill_lines.append(line.strip())
    skills["content"] = "\n".join(skill_lines)
    for work in value.get("workExperiences", []) if isinstance(value.get("workExperiences"), list) else []:
        if isinstance(work, dict):
            work["description"] = _trim_work_description(work.get("description"))
    for project in value.get("projects", []) if isinstance(value.get("projects"), list) else []:
        if isinstance(project, dict):
            project["description"] = _dedupe_lines(project.get("description"))
    value["skills"] = skills
    return value


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
            {"id": row["id"], "draft_json": json.dumps(_clean_draft(current), ensure_ascii=False), "version": "resume-v3"},
        )


def downgrade() -> None:
    # This cleanup removes duplicate derived text and cannot be reversed safely.
    pass
