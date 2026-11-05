import pytest

from policy_assistant import config, db


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    path = tmp_path / "clients.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(config, "AUDIT_LOG", tmp_path / "audit.jsonl")
    monkeypatch.setattr(config, "OUTBOX_DIR", tmp_path / "outbox")
    db.init_db(path)
    return path


def index_ready() -> bool:
    try:
        from policy_assistant.retrieval import get_collection

        return get_collection().count() > 0
    except Exception:
        return False


needs_index = pytest.mark.skipif(not index_ready(), reason="run `policy-assistant setup` first")
