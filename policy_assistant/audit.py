import json
from datetime import datetime, timezone

from . import config
from .redact import redact_obj


def log_event(tool: str, arguments: dict, outcome: str) -> None:
    """Append a PII-redacted record of every tool call to a JSONL audit trail."""
    config.AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": tool,
        "arguments": redact_obj(arguments),
        "outcome": outcome,
    }
    with config.AUDIT_LOG.open("a") as f:
        f.write(json.dumps(record) + "\n")
