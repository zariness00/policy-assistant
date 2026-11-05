import json
import os
from pathlib import Path

ROOT = Path(os.environ.get("POLICY_ASSISTANT_HOME", Path(__file__).resolve().parent.parent))
DATA_DIR = ROOT / "data"
PDF_DIR = DATA_DIR / "policies"
CHROMA_DIR = DATA_DIR / "chroma"
DB_PATH = Path(os.environ.get("POLICY_ASSISTANT_DB", DATA_DIR / "clients.db"))
OUTBOX_DIR = DATA_DIR / "outbox"
AUDIT_LOG = DATA_DIR / "audit.log.jsonl"
SOURCES_FILE = DATA_DIR / "sources.json"

COLLECTION = "policy_wordings"

DISCLAIMER = (
    "This is general information taken from the policy wording and is not advice. "
    "Cover depends on the full policy wording, the client's schedule and endorsements, "
    "and the insurer's claims decision. A qualified broker must review this before it is "
    "relied on or shared with a client."
)


def load_sources() -> list[dict]:
    return json.loads(SOURCES_FILE.read_text())


def source_by_doc_id() -> dict[str, dict]:
    return {s["doc_id"]: s for s in load_sources()}
