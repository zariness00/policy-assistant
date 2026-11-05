import json

from conftest import needs_index

from policy_assistant import cli, config, db, server


def test_client_lookup_masks_pii(temp_db):
    out = server.get_client_policies("Sarah Thompson")
    blob = json.dumps(out)
    assert out["found"] and out["client"]["client_id"] == "C001"
    for leaked in ["sarah.thompson@example.com", "07700 900123", "Willow Crescent", "LS6 2AB", "1984-03-12"]:
        assert leaked not in blob
    assert out["policies"][0]["policy_id"] == "POL-1001"  # active policy first
    assert out["disclaimer"] == config.DISCLAIMER and out["requires_human_review"]


def test_ambiguous_client(temp_db):
    out = server.get_client_policies("a")
    assert not out["found"] and len(out["candidates"]) > 1


def test_draft_is_never_sent_without_human(temp_db):
    out = server.draft_client_email(
        "C001", "Burst pipe", "Dear Sarah Thompson, call me on 07700 900123. Covered [RIAS, p.24].", "POL-1001")
    assert out["created"] and out["status"] == "PENDING_APPROVAL" and out["sent"] is False
    assert "07700" not in out["body_preview"] and "Thompson" not in out["body_preview"]
    assert config.DISCLAIMER in out["body_preview"]
    assert not (config.OUTBOX_DIR / "sent").exists()

    cli.main(["approve", out["draft_id"], "--reviewer", "Jane Broker", "--yes"])
    with db.session() as conn:
        assert db.get_draft(conn, out["draft_id"])["status"] == "APPROVED_SENT"
    sent = (config.OUTBOX_DIR / "sent" / f"{out['draft_id']}.eml").read_text()
    assert "sarah.thompson@example.com" in sent and "X-Approved-By: Jane Broker" in sent


def test_no_send_tool_exposed():
    names = {t.name for t in server.mcp._tool_manager.list_tools()}
    assert names == {"search_policy_wording", "get_client_policies", "compare_coverage",
                     "check_claim_eligibility", "draft_client_email"}


@needs_index
def test_burst_pipe_demo(temp_db):
    out = server.check_claim_eligibility("A pipe burst under the kitchen sink and soaked the floor", "POL-1001")
    assert out["likely_peril"].startswith("Escape of water")
    assert out["excess"]["total_excess_gbp"] == 250
    assert out["indicative_view"].startswith("LIKELY COVERED")
    pages = {c["page"] for c in out["relevant_clauses"]}
    assert pages & {23, 24}
    assert all(c["citation"].startswith("[RIAS") for c in out["relevant_clauses"])


@needs_index
def test_lapsed_policy_flagged(temp_db):
    out = server.check_claim_eligibility("burst pipe in the bathroom", "POL-0901")
    assert "lapsed" in out["possible_issues"][0]


@needs_index
def test_search_filters_by_insurer(temp_db):
    out = server.search_policy_wording("escape of water", "esure", 3)
    assert out["results"] and all(r["doc_id"] == "esure_home" for r in out["results"])
