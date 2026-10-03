import re
from collections.abc import Iterable
from typing import Any

from ..domain.resume_recognition import redact_personal_context


SECTIONS = ("personalInfo", "skills", "workExperiences", "projects")
_PHONE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"https?://[^\s)]+")
_DATE_RANGE = re.compile(r"\d{4}\s*年?\s*\d{1,2}\s*月?\s*(?:[-~到至])\s*(?:至今|\d{4}\s*年?\s*\d{1,2}\s*月?)")
_DATE_RANGE_PARTS = re.compile(r"(?P<start>\d{4}\s*年?\s*\d{1,2}\s*月?)\s*(?:[-~到至])\s*(?P<end>至今|\d{4}\s*年?\s*\d{1,2}\s*月?)")


def empty_draft() -> dict[str, Any]:
    return {
        "personalInfo": {"name": "", "phone": "", "email": "", "city": "", "targetRole": "", "links": []},
        "skills": {"content": "", "evidenceIds": [], "confidence": 0.0, "edited": False},
        "workExperiences": [],
        "projects": [],
    }


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" \t:：")


def _lines(chunks: Iterable[dict[str, Any]]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for chunk in chunks:
        chunk_id = str(chunk.get("id", ""))
        for line in str(chunk.get("content", "")).splitlines():
            if line.strip():
                result.append((line.strip(), chunk_id))
    return result


def _split_items(description: str) -> list[str]:
    return [item for item in (_clean(part) for part in re.split(r"[、,，/；;|]", description)) if item]


_SECTION_HEADINGS = (
    "技能掌握", "专业技能", "技能特长", "技术栈",
    "工作/实习经历", "工作经历", "实习经历",
    "项目经验", "个人项目", "项目经历",
    "教育经历", "荣誉奖励", "证书", "自我评价",
)


def _section_lines(lines: list[tuple[str, str]], heading_patterns: tuple[str, ...]) -> list[tuple[str, str]]:
    active = False
    result: list[tuple[str, str]] = []
    for line, chunk_id in lines:
        if any(pattern in line for pattern in heading_patterns):
            active = True
            continue
        if active and any(pattern in line for pattern in _SECTION_HEADINGS if pattern not in heading_patterns):
            break
        if active:
            result.append((line, chunk_id))
    return result


def _date_parts(value: str) -> tuple[str, str]:
    matched = _DATE_RANGE_PARTS.search(value)
    if not matched:
        return "", ""
    return _clean(matched.group("start")), _clean(matched.group("end"))


def _split_company_role(value: str) -> tuple[str, str]:
    value = _clean(value)
    company = re.match(r"(.+?(?:有限公司|有限责任公司|集团|研究院|实验室|大学|学院))\s+(.+)$", value)
    if company:
        return _clean(company.group(1)), _clean(company.group(2))
    role = re.search(r"(.+?)\s+([^\s]{2,12}(?:实习生|工程师|开发|经理|专员|助理|研究员|顾问))$", value)
    if role:
        return _clean(role.group(1)), _clean(role.group(2))
    return value, ""


def _parse_personal_info(text: str, lines: list[tuple[str, str]]) -> dict[str, Any]:
    phone = _PHONE.search(text)
    email = _EMAIL.search(text)
    links = _URL.findall(text)
    name = ""
    for line, _ in lines[:5]:
        candidate = _clean(line)
        if candidate and len(candidate) <= 30 and not any(token in candidate for token in ("技能", "经历", "项目", "电话", "邮箱", "简历")) and not _EMAIL.search(candidate):
            name = candidate
            break
    city_match = re.search(r"(?:所在城市|城市|所在地)\s*[:：]\s*([^\s,，;；]+)", text)
    role_match = re.search(r"(?:求职方向|目标岗位|应聘岗位)\s*[:：]\s*([^\n]+)", text)
    evidence_ids = list(dict.fromkeys(chunk_id for _, chunk_id in lines[:3] if chunk_id))
    return {
        "name": name,
        "phone": phone.group(0) if phone else "",
        "email": email.group(0) if email else "",
        "city": _clean(city_match.group(1)) if city_match else "",
        "targetRole": _clean(role_match.group(1)) if role_match else "",
        "links": links,
        "evidenceIds": evidence_ids,
        "confidence": 0.8 if evidence_ids else 0.0,
    }


def _parse_skills(lines: list[tuple[str, str]]) -> dict[str, Any]:
    skill_lines = _section_lines(lines, ("技能掌握", "专业技能", "技能特长", "技术栈"))
    content = "\n".join(line for line, _ in skill_lines).strip()
    evidence_ids = list(dict.fromkeys(chunk_id for _, chunk_id in skill_lines if chunk_id))
    return {"content": content, "evidenceIds": evidence_ids, "confidence": 0.75 if content else 0.0, "edited": False}


def _parse_work(lines: list[tuple[str, str]]) -> list[dict[str, Any]]:
    work_lines = _section_lines(lines, ("工作/实习经历", "工作经历", "实习经历"))
    result: list[dict[str, Any]] = []
    starts = [index for index, (line, _) in enumerate(work_lines) if _DATE_RANGE.search(line)]
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(work_lines)
        block = work_lines[start:end]
        line, chunk_id = block[0]
        date = _DATE_RANGE.search(line)
        if not date:
            continue
        start_date, end_date = _date_parts(date.group(0))
        company, role = _split_company_role(line.replace(date.group(0), ""))
        result.append({
            "company": company,
            "role": role,
            "startDate": start_date,
            "endDate": end_date,
            "experienceType": "internship" if "实习" in line else "work",
            "description": "\n".join(item[0] for item in block[1:]).strip(),
            "evidenceIds": list(dict.fromkeys(item[1] for item in block if item[1])),
            "confidence": 0.65,
            "edited": False,
        })
    return result


def _parse_projects(lines: list[tuple[str, str]]) -> list[dict[str, Any]]:
    project_lines = _section_lines(lines, ("项目经验", "个人项目", "项目经历"))
    if not project_lines:
        return []
    text = "\n".join(line for line, _ in project_lines)
    ids = list(dict.fromkeys(chunk_id for _, chunk_id in project_lines if chunk_id))
    name_match = re.search(r"项目名称\s*[:：]\s*([^\n；;]+)", text)
    role_match = re.search(r"(?:项目角色|角色)\s*[:：]\s*([^\n；;]+)", text)
    tech_match = re.search(r"核心技术\s*[:：]\s*([^\n]+)", text)
    description_lines: list[str] = []
    for line, _ in project_lines:
        remainder = re.sub(r"(?:项目名称|项目角色|角色|核心技术|项目时间|时间范围)\s*[:：]\s*[^\n；;]+[；;]?", "", line)
        remainder = _clean(remainder)
        if remainder:
            description_lines.append(remainder)
    return [{
        "name": _clean(name_match.group(1)) if name_match else _clean(project_lines[0][0]),
        "timeRange": "",
        "role": _clean(role_match.group(1)) if role_match else "",
        "technologies": _split_items(_clean(tech_match.group(1))) if tech_match else [],
        "description": "\n".join(description_lines).strip(),
        "links": [],
        "projectArchiveId": None,
        "evidenceIds": ids,
        "confidence": 0.65,
        "edited": False,
    }]


def build_local_draft(chunks: Iterable[dict[str, Any]]) -> dict[str, Any]:
    chunk_list = list(chunks)
    lines = _lines(chunk_list)
    text = "\n".join(str(chunk.get("content", "")) for chunk in chunk_list)
    draft = empty_draft()
    draft["personalInfo"] = _parse_personal_info(text, lines)
    draft["skills"] = _parse_skills(lines)
    draft["workExperiences"] = _parse_work(lines)
    draft["projects"] = _parse_projects(lines)
    return draft


def llm_context(chunks: Iterable[dict[str, Any]], personal_info: dict[str, Any] | None = None) -> str:
    return "\n\n".join(
        f"证据 {chunk.get('id')}: {redact_personal_context(str(chunk.get('content', '')), personal_info)}"
        for chunk in chunks
    )
