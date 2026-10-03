from app.infrastructure.resume_parser import build_local_draft


def test_local_draft_extracts_personal_information_with_evidence():
    draft = build_local_draft([
        {
            "id": "page-1",
            "content": "张三\n手机号：13812345678\n邮箱：zhangsan@example.com\n所在城市：北京市\n求职方向：Python 后端工程师\nGitHub：https://github.com/zhangsan",
        }
    ])

    assert draft["personalInfo"] == {
        "name": "张三",
        "phone": "13812345678",
        "email": "zhangsan@example.com",
        "city": "北京市",
        "targetRole": "Python 后端工程师",
        "links": ["https://github.com/zhangsan"],
        "evidenceIds": ["page-1"],
        "confidence": 0.8,
    }


def test_local_draft_preserves_full_skill_description_as_one_block():
    draft = build_local_draft([
        {
            "id": "page-2",
            "content": "技能掌握\nJava 基础：熟悉集合、并发、JVM。\n数据库与缓存：MySQL、Redis，了解索引和缓存策略。",
        }
    ])

    assert draft["skills"]["content"] == "Java 基础：熟悉集合、并发、JVM。\n数据库与缓存：MySQL、Redis，了解索引和缓存策略。"
    assert draft["skills"]["evidenceIds"] == ["page-2"]


def test_local_draft_extracts_work_role_and_complete_description():
    draft = build_local_draft([
        {
            "id": "page-3",
            "content": (
                "工作/实习经历\n"
                "2025年06月-2025年08月 上海示例科技有限公司 AI应用开发实习生\n"
                "项目名称：内容生产平台\n"
                "核心技术：Python、MySQL\n"
                "项目背景：支持内容审核和发布。\n"
                "实习内容：负责后端接口开发。\n"
                "指标：接口耗时降低 30%。"
            ),
        }
    ])

    experience = draft["workExperiences"][0]
    assert experience["company"] == "上海示例科技有限公司"
    assert experience["role"] == "AI应用开发实习生"
    assert experience["description"] == "项目名称：内容生产平台\n核心技术：Python、MySQL\n项目背景：支持内容审核和发布。\n实习内容：负责后端接口开发。\n指标：接口耗时降低 30%。"
    assert "projects" not in experience


def test_local_draft_does_not_create_fields_outside_contract():
    draft = build_local_draft([{"id": "page-4", "content": "张三\n出生日期：2000-01\n教育经历：某大学"}])

    assert set(draft["personalInfo"]) <= {"name", "phone", "email", "city", "targetRole", "links", "evidenceIds", "confidence"}
    assert "birthDate" not in draft["personalInfo"]
    assert "education" not in draft["personalInfo"]
