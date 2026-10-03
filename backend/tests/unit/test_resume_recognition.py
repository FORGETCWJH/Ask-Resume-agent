from app.domain.resume_recognition import redact_personal_context, transition_status
from app.infrastructure.resume_parser import build_local_draft, llm_context
from app.service.resume_recognition_service import _normalize_draft


def test_resume_llm_context_redacts_personal_contact_information():
    text = "张三\n电话：13812345678\n邮箱：zhangsan@example.com\n技能掌握\nPython：熟悉 FastAPI"

    redacted = redact_personal_context(text)

    assert "13812345678" not in redacted
    assert "zhangsan@example.com" not in redacted
    assert "熟悉 FastAPI" in redacted


def test_resume_llm_context_redacts_locally_extracted_name_city_and_links():
    chunks = [{"id": "e1", "content": "张三\n所在城市：北京市\n技能掌握\nPython：熟悉 FastAPI"}]

    context = llm_context(chunks, {"name": "张三", "city": "北京市", "links": ["https://github.com/zhangsan"]})

    assert "张三" not in context
    assert "北京市" not in context
    assert "github.com/zhangsan" not in context
    assert "熟悉 FastAPI" in context


def test_model_cannot_erase_locally_extracted_personal_information():
    fallback = {
        "personalInfo": {"name": "张三", "phone": "13812345678", "email": "a@example.com", "city": "北京市", "targetRole": "", "links": []},
        "skills": [],
        "workExperiences": [],
        "projects": [],
    }

    normalized = _normalize_draft({"personalInfo": {"name": "", "phone": "", "email": "", "city": "", "links": []}}, fallback)

    assert normalized["personalInfo"]["name"] == "张三"
    assert normalized["personalInfo"]["email"] == "a@example.com"


def test_model_entries_without_evidence_fall_back_to_local_facts():
    fallback = {
        "personalInfo": {"name": "", "phone": "", "email": "", "city": "", "targetRole": "", "links": []},
        "skills": [{"category": "后端开发", "description": "Python", "items": ["Python"], "evidenceIds": ["e1"]}],
        "workExperiences": [],
        "projects": [],
    }

    normalized = _normalize_draft({"skills": [{"category": "虚构技能", "description": "不存在的事实"}]}, fallback, {"e1"})

    assert normalized["skills"]["content"] == "后端开发：Python"


def test_model_cannot_persist_fields_outside_the_recognition_contract():
    normalized = _normalize_draft(
        {"personalInfo": {"name": "张三", "birthDate": "2000-01", "education": [{"school": "不应保存"}]}},
        {"personalInfo": {"name": "", "phone": "", "email": "", "city": "", "targetRole": "", "links": []}, "skills": [], "workExperiences": [], "projects": []},
    )

    assert normalized["personalInfo"] == {"name": "张三", "phone": "", "email": "", "city": "", "targetRole": "", "links": []}


def test_recognition_status_transition_rejects_confirmation_before_draft():
    assert transition_status("pending", "processing") == "processing"
    assert transition_status("processing", "awaitingConfirmation") == "awaitingConfirmation"
    assert transition_status("awaitingConfirmation", "confirmed") == "confirmed"

    try:
        transition_status("pending", "confirmed")
    except ValueError:
        pass
    else:
        raise AssertionError("pending recognition must not be confirmable")


def test_local_resume_parser_keeps_skills_and_experience_as_complete_descriptions():
    draft = build_local_draft([
        {"id": "e1", "content": "技能掌握\n后端开发：熟悉 Python、FastAPI、SQLAlchemy。\n数据库与缓存：熟悉 MySQL、Redis。"},
        {"id": "e2", "content": "工作/实习经历\n2025年06月-2025年08月 上海示例科技有限公司 AI应用开发实习生\n项目名称：内容生产平台；核心技术：Python、MySQL。"},
        {"id": "e3", "content": "项目经验\n项目名称：本地生活服务平台；角色：后端开发；核心技术：Redis、RabbitMQ。\n负责订单和缓存模块设计。"},
    ])

    assert draft["skills"]["content"] == "后端开发：熟悉 Python、FastAPI、SQLAlchemy。\n数据库与缓存：熟悉 MySQL、Redis。"
    assert draft["skills"]["evidenceIds"] == ["e1"]
    assert draft["workExperiences"][0]["description"] == "项目名称：内容生产平台；核心技术：Python、MySQL。"
    assert "projects" not in draft["workExperiences"][0]
    assert draft["projects"][0]["name"] == "本地生活服务平台"
    assert draft["projects"][0]["description"] == "负责订单和缓存模块设计。"
    assert "metrics" not in draft["projects"][0]


def test_legacy_draft_is_migrated_to_compact_shape():
    fallback = {
        "personalInfo": {"name": "", "phone": "", "email": "", "city": "", "targetRole": "", "links": []},
        "skills": [{"category": "后端开发", "description": "Python、FastAPI", "items": ["Python", "FastAPI"], "evidenceIds": ["e1"]}],
        "workExperiences": [{"company": "示例公司", "role": "实习生", "startDate": "2025年06月", "endDate": "2025年08月", "experienceType": "internship", "rawText": "原始经历", "projects": [{"name": "内容平台", "background": "背景", "responsibilities": "职责", "metrics": "提升30%", "evidenceIds": ["e2"]}], "evidenceIds": ["e2"]}],
        "projects": [{"name": "平台", "timeRange": "2025", "role": "后端", "technologies": ["Python"], "description": "描述", "contributions": "贡献", "metrics": "提升30%", "links": [], "projectArchiveId": None, "evidenceIds": ["e3"]}],
    }

    normalized = _normalize_draft(fallback, fallback)

    assert normalized["skills"]["content"] == "后端开发：Python、FastAPI"
    assert normalized["workExperiences"][0]["description"] == "原始经历\n项目：内容平台\n背景：背景\n职责：职责\n成果描述：提升30%"
    assert "projects" not in normalized["workExperiences"][0]
    assert normalized["projects"][0]["description"] == "描述\n贡献\n成果描述：提升30%"
    assert "metrics" not in normalized["projects"][0]


def test_legacy_skill_migration_does_not_absorb_project_entries():
    legacy = {
        "personalInfo": {},
        "skills": [
            {"category": "Java 基础", "description": "熟悉 Java", "evidenceIds": ["e1"]},
            {"category": "后端开发", "description": "熟悉 Spring Boot", "evidenceIds": ["e1"]},
            {"category": "项目名称", "description": "AIGC 内容生产提效平台", "evidenceIds": ["e1"]},
            {"category": "核心技术", "description": "Python、FastAPI", "evidenceIds": ["e1"]},
            {"category": "工作流平台工程化", "description": "参与建设工作台", "evidenceIds": ["e1"]},
        ],
        "workExperiences": [],
        "projects": [],
    }

    normalized = _normalize_draft(legacy, legacy)

    assert normalized["skills"]["content"] == "Java 基础：熟悉 Java\n后端开发：熟悉 Spring Boot"
    assert "AIGC" not in normalized["skills"]["content"]
    assert "工作流平台工程化" not in normalized["skills"]["content"]


def test_legacy_work_migration_does_not_duplicate_raw_text_and_nested_project():
    legacy = {
        "personalInfo": {},
        "skills": [],
        "workExperiences": [{
            "company": "示例公司",
            "role": "实习生",
            "rawText": "项目名称：内容平台\n实习内容：负责后端接口开发。\n项目经验",
            "projects": [{
                "name": "内容平台",
                "background": "项目背景：支持内容审核。",
                "responsibilities": "实习内容：负责后端接口开发。",
                "evidenceIds": ["e1"],
            }],
            "evidenceIds": ["e1"],
        }],
        "projects": [],
    }

    normalized = _normalize_draft(legacy, legacy)
    description = normalized["workExperiences"][0]["description"]

    assert description == "项目名称：内容平台\n实习内容：负责后端接口开发。"
    assert description.count("负责后端接口开发") == 1
    assert "项目经验" not in description
