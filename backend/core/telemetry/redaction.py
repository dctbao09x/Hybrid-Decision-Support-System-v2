import logging
import re
from typing import Any

EMAIL_RE = re.compile(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9-.]+")
PHONE_RE = re.compile(r"\b(\+?\d{1,3})?[\s.-]?(0?\d{9,11})\b")
ID_RE = re.compile(r"\b\d{9,12}\b")

SENSITIVE_KEYS = {
    "full_name",
    "fullname",
    "email",
    "phone",
    "phone_number",
    "address",
    "school_name",
    "school",
    "uploaded_documents",
    "free_text_input",
}


def redact_text(text: Any) -> Any:
    if text is None:
        return text
    if not isinstance(text, str):
        return text
    redacted = EMAIL_RE.sub("<REDACTED_EMAIL>", text)
    redacted = PHONE_RE.sub("<REDACTED_PHONE>", redacted)
    redacted = ID_RE.sub("<REDACTED_ID>", redacted)
    return redacted


def _redact_value_for_key(key: str, value: Any) -> Any:
    if key.lower() in SENSITIVE_KEYS:
        return "<REDACTED>"
    return redact_dict(value)


def redact_dict(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {k: _redact_value_for_key(k, v) for k, v in payload.items()}
    if isinstance(payload, list):
        return [redact_dict(item) for item in payload]
    return redact_text(payload)


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)
        if record.args:
            try:
                record.args = tuple(redact_text(arg) for arg in record.args)
            except TypeError:
                pass
        return True
