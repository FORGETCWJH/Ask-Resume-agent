from app.domain.agent_follow_up import (
    EvidenceGrade,
    LlmRunState,
    QuestionScope,
    fingerprint_answer,
    fingerprint_scope,
    transition_run,
    validate_evidence_grade,
)
from app.infrastructure.code_search import ReadOnlyCodeSearch


def test_question_scope_fingerprint_is_stable_for_mapping_order():
    left = QuestionScope.model_validate({"projectIds": ["p2", "p1"], "resumeSections": ["skills"], "direction": "实现细节"})
    right = QuestionScope.model_validate({"resumeSections": ["skills"], "direction": "实现细节", "projectIds": ["p1", "p2"]})
    assert fingerprint_scope(left) == fingerprint_scope(right)


def test_llm_run_state_allows_only_forward_transitions():
    assert transition_run(LlmRunState.QUEUED, LlmRunState.RUNNING) == LlmRunState.RUNNING
    assert transition_run(LlmRunState.RUNNING, LlmRunState.SUCCEEDED) == LlmRunState.SUCCEEDED
    assert transition_run(LlmRunState.SUCCEEDED, LlmRunState.RUNNING) == LlmRunState.SUCCEEDED


def test_evidence_grade_rejects_unknown_values():
    assert validate_evidence_grade("direct") == EvidenceGrade.DIRECT
    assert validate_evidence_grade("insufficient") == EvidenceGrade.INSUFFICIENT
    assert validate_evidence_grade("fabricated") == EvidenceGrade.INSUFFICIENT


def test_answer_fingerprint_changes_only_when_submitted_content_changes():
    assert fingerprint_answer("  我负责缓存。 ") == fingerprint_answer("我负责缓存。")
    assert fingerprint_answer("我负责缓存。") != fingerprint_answer("我负责消息队列。")


def test_code_search_never_reads_outside_project(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("def answer():\n    return 'redis cache'\n", encoding="utf-8")
    search = ReadOnlyCodeSearch(tmp_path)
    result = search.search("redis", paths=["src"])
    assert result[0].path == "src/service.py"
    assert result[0].line_start == 2
    assert search.search("redis", paths=["../"] ) == []
