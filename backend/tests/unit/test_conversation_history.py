from datetime import datetime, timezone

import pytest

from app.domain.conversation_history import (
    ConversationManagement,
    can_write_conversation,
    normalize_group_name,
    sort_conversations,
    validate_group_name,
    validate_title,
)


def test_group_names_are_trimmed_case_insensitive_and_reject_reserved_words():
    assert normalize_group_name("  Redis 专项  ") == "redis 专项"
    assert validate_group_name(" 项目专项 ") == "项目专项"
    with pytest.raises(ValueError):
        validate_group_name("已归档")
    with pytest.raises(ValueError):
        validate_group_name(" ")


def test_title_is_trimmed_and_has_a_bounded_length():
    assert validate_title("  Redis 练习 ") == "Redis 练习"
    with pytest.raises(ValueError):
        validate_title("x" * 201)


def test_repeated_management_operations_are_idempotent_and_archive_is_read_only():
    now = datetime(2026, 10, 9, tzinfo=timezone.utc)
    state = ConversationManagement()
    assert state.pin(now).pinned_at == now
    assert state.pin(datetime(2026, 10, 10, tzinfo=timezone.utc)).pinned_at == now
    assert state.archive(now).archived_at == now
    assert state.archive(datetime(2026, 10, 10, tzinfo=timezone.utc)).archived_at == now
    assert can_write_conversation(state) is False
    assert state.restore().archived_at is None
    assert can_write_conversation(state) is True


def test_sorting_puts_pinned_first_then_recent_activity_and_id():
    rows = [
        {"id": "b", "pinnedAt": None, "lastActivityAt": "2026-10-09T12:00:00+00:00"},
        {"id": "a", "pinnedAt": "2026-10-09T10:00:00+00:00", "lastActivityAt": "2026-10-01T12:00:00+00:00"},
        {"id": "c", "pinnedAt": "2026-10-09T11:00:00+00:00", "lastActivityAt": "2026-10-01T12:00:00+00:00"},
        {"id": "d", "pinnedAt": None, "lastActivityAt": "2026-10-09T12:00:00+00:00"},
    ]
    assert [row["id"] for row in sort_conversations(rows)] == ["c", "a", "b", "d"]
