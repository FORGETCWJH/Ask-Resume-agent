"""历史对话管理的纯领域规则，不依赖 FastAPI 或数据库。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


RESERVED_NAMES = {"置顶", "未分组", "已归档"}


def normalize_group_name(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


def validate_group_name(value: str) -> str:
    name = " ".join(value.strip().split())
    if not name or len(name) > 80:
        raise ValueError("分组名称长度必须为 1-80 个字符")
    if name.casefold() in {item.casefold() for item in RESERVED_NAMES}:
        raise ValueError("该名称是系统保留名称")
    return name


def validate_title(value: str) -> str:
    title = value.strip()
    if not title or len(title) > 200:
        raise ValueError("对话标题长度必须为 1-200 个字符")
    return title


@dataclass
class ConversationManagement:
    pinned_at: datetime | None = None
    archived_at: datetime | None = None

    def pin(self, at: datetime) -> "ConversationManagement":
        if self.pinned_at is None:
            self.pinned_at = at
        return self

    def unpin(self) -> "ConversationManagement":
        self.pinned_at = None
        return self

    def archive(self, at: datetime) -> "ConversationManagement":
        if self.archived_at is None:
            self.archived_at = at
        return self

    def restore(self) -> "ConversationManagement":
        self.archived_at = None
        return self


def can_write_conversation(state: ConversationManagement) -> bool:
    return state.archived_at is None


def _time(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _epoch(value: Any) -> float:
    if value is None:
        return 0.0
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.timestamp()


def sort_conversations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            0 if row.get("pinnedAt") else 1,
            -_epoch(row.get("pinnedAt")) if row.get("pinnedAt") else 0,
            -_epoch(row.get("lastActivityAt")),
            str(row.get("id", "")),
        ),
    )
