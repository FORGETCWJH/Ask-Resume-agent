import re


RECOGNITION_STATUSES = {
    "pending",
    "processing",
    "awaitingConfirmation",
    "confirmed",
    "failed",
}

_ALLOWED_TRANSITIONS = {
    "pending": {"processing", "failed"},
    "processing": {"awaitingConfirmation", "failed"},
    "awaitingConfirmation": {"processing", "confirmed", "failed"},
    "failed": {"processing", "awaitingConfirmation"},
    "confirmed": {"processing", "awaitingConfirmation"},
}


def transition_status(current: str, target: str) -> str:
    if current not in RECOGNITION_STATUSES or target not in RECOGNITION_STATUSES:
        raise ValueError("unknown recognition status")
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"invalid recognition transition: {current} -> {target}")
    return target


def redact_personal_context(text: str, personal_info: dict | None = None) -> str:
    """Remove locally known personal details before evidence leaves the server."""
    redacted = re.sub(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)", "[手机号]", text)
    redacted = re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "[邮箱]", redacted)
    redacted = re.sub(r"https?://[^\s)]+", "[个人链接]", redacted)
    redacted = re.sub(r"((?:姓名|名字)\s*[:：]\s*)[^\s,，;；\n]+", r"\1[姓名]", redacted)
    redacted = re.sub(r"((?:所在城市|城市|所在地)\s*[:：]\s*)[^\s,，;；\n]+", r"\1[城市]", redacted)
    if personal_info:
        for value, replacement in ((personal_info.get("name"), "[姓名]"), (personal_info.get("city"), "[城市]")):
            if isinstance(value, str) and len(value.strip()) >= 2:
                redacted = re.sub(re.escape(value.strip()), replacement, redacted, flags=re.IGNORECASE)
        for link in personal_info.get("links", []) or []:
            if isinstance(link, str) and link.strip():
                redacted = redacted.replace(link.strip(), "[个人链接]")
    return redacted
