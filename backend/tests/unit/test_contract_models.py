from app.dto.conversation import MessageCreate
from app.dto.material import MaterialSetCreate


def test_external_contract_uses_camel_case_aliases():
    message = MessageCreate.model_validate({"content": "解释项目", "selection": {"materialId": "m1", "text": "项目", "startOffset": 0, "endOffset": 2}})
    assert message.selection is not None
    assert message.selection.material_id == "m1"
    assert message.model_dump(by_alias=True)["selection"]["startOffset"] == 0


def test_material_title_is_required_and_bounded():
    assert MaterialSetCreate(title="后端面试").title == "后端面试"

