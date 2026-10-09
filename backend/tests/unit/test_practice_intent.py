import pytest
from app.domain.practice_intent import PracticeIntent, validate_intent, effective_scope, next_main_index, preference_value


def test_answer_plus_feedback_requires_answer_and_target():
    intent = PracticeIntent.model_validate({"action": "feedback", "answer": "使用缓存降低压力"})
    assert validate_intent(intent, current_turn_id="turn-1", has_answer=False).action == "feedback"
    assert validate_intent(intent, current_turn_id=None, has_answer=False).outcome == "needsClarification"
    assert validate_intent(PracticeIntent(action="feedback"), current_turn_id="turn-1", has_answer=False).outcome == "needsClarification"


def test_explicit_scope_beats_round_and_long_term_defaults():
    intent = PracticeIntent.model_validate({"scope": {"count": 3}, "scopeOverrides": ["count"]})
    scope = effective_scope(intent, {"count": 2, "topic": "缓存"}, {"count": 1, "topic": "SQL"})
    assert (scope.count, scope.topic) == (3, "缓存")
    assert effective_scope(PracticeIntent(), {}, {}).count == 5


def test_navigation_never_creates_another_group():
    assert next_main_index(0, 3) == (1, False)
    assert next_main_index(2, 3) == (2, True)
    assert next_main_index(0, 0) == (0, True)


def test_model_cannot_emit_arbitrary_actions_or_unbounded_preferences():
    with pytest.raises(ValueError):
        PracticeIntent.model_validate({"action": "executeShell"})
    with pytest.raises(ValueError):
        preference_value("count", 100)
    assert preference_value("count", "1") == 1


def test_context_has_a_budget_redacts_contact_and_keeps_current_target():
    from app.domain.practice_intent import build_context
    context = build_context({"currentQuestion": "解释缓存", "facts": [{"content": "联系 a@example.com 13812345678\n" + "x" * 50000}], "recentMessages": [], "summary": "历史摘录"}, budget=5000)
    assert len(context) <= 5000
    assert "解释缓存" in context
    assert "a@example.com" not in context
    assert "13812345678" not in context
