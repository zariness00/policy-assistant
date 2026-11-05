"""PII redaction. Client data is minimised before it ever reaches the LLM, and every
free-text input (claim descriptions, email drafts, audit logs) is scrubbed."""

import re
from typing import Any, Iterable

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("CARD_NUMBER", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("NI_NUMBER", re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b", re.I)),
    ("PHONE", re.compile(r"\(0\d{2,4}\)\s?\d{3,4}[\s-]?\d{3,4}\b")),
    ("PHONE", re.compile(r"(?:\+44\s?\(?0?\)?\s?|\b0)(?:\d[\s-]?){9,10}\b")),
    ("SORT_CODE", re.compile(r"\b\d{2}-\d{2}-\d{2}\b")),
    ("DATE_OF_BIRTH", re.compile(
        r"\b(?:born|dob|d\.o\.b\.?|date of birth)[:\s]*\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}\b", re.I)),
    ("POSTCODE", re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b", re.I)),
    ("ACCOUNT_NUMBER", re.compile(r"\b\d{8}\b")),
]


def redact_text(text: str, known_values: Iterable[str] = ()) -> str:
    """Replace PII with typed placeholders like [EMAIL]. `known_values` are exact strings
    (e.g. a client's name or street address) that should also be removed."""
    if not text:
        return text
    for value in sorted({v for v in known_values if v and len(v) > 2}, key=len, reverse=True):
        text = re.sub(re.escape(value), "[REDACTED]", text, flags=re.I)
    for label, pattern in _PATTERNS:
        text = pattern.sub(f"[{label}]", text)
    return text


def redact_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact_obj(v) for v in obj]
    return obj


def mask_name(full_name: str) -> str:
    parts = full_name.split()
    if len(parts) < 2:
        return parts[0][0] + "." if parts else ""
    return f"{parts[0]} {parts[-1][0]}."


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "[EMAIL]"


def mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    return f"*** *** {digits[-3:]}" if len(digits) >= 3 else "[PHONE]"
