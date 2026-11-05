"""Policy Assistant MCP server.

Responsible-AI guarantees enforced in code (not just in the prompt):
  * client PII is masked before it reaches the model, and free text is redacted;
  * every coverage answer is returned with page-level citations;
  * every response carries a "not advice" disclaimer and requires_human_review;
  * the model can only create email DRAFTS - there is no send tool. A human approves
    drafts out-of-band with `policy-assistant approve <draft_id>`;
  * every tool call is written to a redacted audit log.
"""

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import claims, config, db
from .audit import log_event
from .redact import mask_email, mask_name, mask_phone, redact_text
from .retrieval import resolve_doc_id, search

INSTRUCTIONS = f"""You are assisting a licensed insurance broker (not a consumer).
Rules:
1. Ground every statement about cover in passages returned by search_policy_wording,
   compare_coverage or check_claim_eligibility, and cite them inline using their `citation` field.
   If no passage supports a point, say you could not find it in the wording.
2. Take excess amounts and optional covers from the client's schedule (get_client_policies /
   check_claim_eligibility), not from generic wording.
3. Never ask for or repeat personal data. Refer to clients by client_id or masked name.
4. You cannot send emails. draft_client_email only creates a draft for a human to approve.
5. End every answer with this disclaimer: "{config.DISCLAIMER}"
"""

mcp = FastMCP("policy-assistant", instructions=INSTRUCTIONS)

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def _policy_summary(row) -> dict:
    p = dict(row)
    return {
        "policy_id": p["policy_id"],
        "status": p["status"],
        "insurer": p["insurer"],
        "product": p["product_name"],
        "wording_doc_id": p["doc_id"],
        "cover_type": p["cover_type"],
        "period": f"{p['start_date']} to {p['end_date']}",
        "sums_insured_gbp": {"buildings": p["buildings_sum_insured"], "contents": p["contents_sum_insured"]},
        "excesses_gbp": {
            "standard": p["standard_excess"],
            "escape_of_water": p["escape_of_water_excess"],
            "subsidence": p["subsidence_excess"],
            "voluntary": p["voluntary_excess"],
        },
        "optional_covers": {
            "accidental_damage_buildings": bool(p["accidental_damage_buildings"]),
            "accidental_damage_contents": bool(p["accidental_damage_contents"]),
            "personal_possessions": bool(p["personal_possessions"]),
            "legal_expenses": bool(p["legal_expenses"]),
        },
        "endorsements": p["endorsements"],
    }


def _client_known_values(client) -> list[str]:
    c = dict(client)
    last = c["full_name"].split()[-1]
    street = c["address"].split(",")[0]
    return [c["full_name"], c["email"], c["phone"], c["address"], street, c["postcode"], c["date_of_birth"], last]


def _envelope(payload: dict) -> dict:
    payload["disclaimer"] = config.DISCLAIMER
    payload["requires_human_review"] = True
    return payload


@mcp.tool(annotations=READ_ONLY)
def search_policy_wording(query: str, insurer_or_doc_id: str | None = None, top_k: int = 5) -> dict:
    """Semantic search over public insurer policy wordings. Returns passages with a citation
    (insurer, document, page) and a link to the exact PDF page. Optionally restrict to one
    insurer/document, e.g. 'RIAS', 'esure', 'Aviva', 'AA' or a doc_id like 'rias_home'."""
    doc_id = resolve_doc_id(insurer_or_doc_id)
    passages = search(query, doc_id, max(1, min(top_k, 10)))
    log_event("search_policy_wording", {"query": query, "doc_id": doc_id}, f"{len(passages)} passages")
    return _envelope({
        "query": query,
        "results": [p.to_dict() for p in passages],
        "available_documents": [f"{s['doc_id']} ({s['insurer']} {s['product']})" for s in config.load_sources()],
    })


@mcp.tool(annotations=READ_ONLY)
def get_client_policies(client: str) -> dict:
    """Look up a client by client_id (e.g. 'C001'), policy_id or name, and return their policy
    schedules: insurer, cover type, sums insured, excesses, optional covers and endorsements.
    Personal data is masked; contact details are never returned to the model."""
    with db.session() as conn:
        matches = db.find_clients(conn, client)
        if not matches:
            log_event("get_client_policies", {"client": client}, "not found")
            return _envelope({"found": False, "message": f"No client matches '{redact_text(client)}'."})
        if len(matches) > 1:
            log_event("get_client_policies", {"client": client}, f"{len(matches)} matches")
            return _envelope({
                "found": False,
                "message": "More than one client matches - ask the broker which client_id they mean.",
                "candidates": [{"client_id": m["client_id"], "name": mask_name(m["full_name"])} for m in matches],
            })
        c = matches[0]
        policies = [_policy_summary(p) for p in db.policies_for_client(conn, c["client_id"])]
    log_event("get_client_policies", {"client": client}, f"{c['client_id']}: {len(policies)} policies")
    return _envelope({
        "found": True,
        "client": {
            "client_id": c["client_id"],
            "name": mask_name(c["full_name"]),
            "email": mask_email(c["email"]),
            "phone": mask_phone(c["phone"]),
            "region": c["address"].split(",")[-1].strip(),
            "broker_notes": redact_text(c["broker_notes"] or "", _client_known_values(c)),
        },
        "policies": policies,
        "pii_notice": "Personal data is masked. The server fills in real contact details only after human approval.",
    })


def _resolve_side(ref: str, conn) -> tuple[str, dict | None]:
    row = db.get_policy(conn, ref)
    if row:
        return row["doc_id"], _policy_summary(row)
    return resolve_doc_id(ref), None


DEFAULT_TOPICS = ["escape of water / burst pipes", "storm and flood", "theft",
                  "subsidence", "accidental damage", "unoccupied home"]


@mcp.tool(annotations=READ_ONLY)
def compare_coverage(policy_a: str, policy_b: str, topics: list[str] | None = None) -> dict:
    """Compare two policies side by side. Each side can be a client policy_id (e.g. 'POL-1001',
    which also compares schedule excesses and optional covers) or an insurer/doc_id
    (e.g. 'esure'). For each topic, returns the most relevant cited clauses from each wording."""
    with db.session() as conn:
        doc_a, sched_a = _resolve_side(policy_a, conn)
        doc_b, sched_b = _resolve_side(policy_b, conn)
    topics = topics or DEFAULT_TOPICS
    comparison = []
    for topic in topics[:8]:
        comparison.append({
            "topic": topic,
            "policy_a_clauses": [p.to_dict() for p in search(topic, doc_a, 2)],
            "policy_b_clauses": [p.to_dict() for p in search(topic, doc_b, 2)],
        })
    log_event("compare_coverage", {"a": policy_a, "b": policy_b, "topics": topics}, f"{len(comparison)} topics")
    return _envelope({
        "policy_a": {"ref": policy_a, "wording_doc_id": doc_a, "schedule": sched_a},
        "policy_b": {"ref": policy_b, "wording_doc_id": doc_b, "schedule": sched_b},
        "comparison": comparison,
        "guidance": "Summarise differences only where the cited clauses support them; flag gaps as 'not found'.",
    })


@mcp.tool(annotations=READ_ONLY)
def check_claim_eligibility(claim_description: str, policy_id: str) -> dict:
    """Triage a described loss against a client's policy: identifies the likely peril, the
    applicable excess from the schedule, red-flag exclusions suggested by the facts, and the
    relevant cover and exclusion clauses (with citations). Gives an indicative view only -
    the insurer makes the claims decision."""
    with db.session() as conn:
        row = db.get_policy(conn, policy_id)
        client = db.get_client(conn, row["client_id"]) if row else None
    if not row:
        log_event("check_claim_eligibility", {"policy_id": policy_id}, "policy not found")
        return _envelope({"found": False, "message": f"No policy '{policy_id}'. Use get_client_policies first."})

    description = redact_text(claim_description, _client_known_values(client))
    policy = dict(row)
    triage = claims.classify(description)
    issues = list(triage.red_flags)
    if policy["status"] != "active":
        issues.insert(0, f"Policy status is '{policy['status']}' - it may not respond to a new loss.")

    if not triage.perils:
        log_event("check_claim_eligibility", {"policy_id": policy_id, "claim": description}, "peril unclear")
        return _envelope({
            "found": True,
            "policy": _policy_summary(row),
            "indicative_view": "UNCLEAR - could not identify the insured peril; ask the broker for more detail.",
            "possible_issues": issues,
            "relevant_clauses": [p.to_dict() for p in search(description, policy["doc_id"], 4)],
        })

    peril = triage.perils[0]
    missing = claims.optional_cover_missing(policy, peril)
    if missing:
        issues.insert(0, missing)

    seen, clauses = set(), []
    for label, query in (("cover", f"{peril.cover_query} {description}"), ("exclusions", peril.exclusion_query)):
        for p in search(query, policy["doc_id"], 3):
            key = (p.page, p.text[:60])
            if key not in seen:
                seen.add(key)
                clauses.append({"purpose": label, **p.to_dict()})

    if missing:
        view = "LIKELY NOT COVERED - required optional cover is not on the schedule."
    elif issues:
        view = "POSSIBLY COVERED - review the flagged issues against the cited exclusions."
    else:
        view = "LIKELY COVERED - subject to the policy terms, exclusions and the insurer's decision."

    log_event("check_claim_eligibility", {"policy_id": policy_id, "claim": description}, f"{peril.key}: {view}")
    return _envelope({
        "found": True,
        "claim_description_redacted": description,
        "policy": _policy_summary(row),
        "likely_peril": peril.label,
        "other_possible_perils": [p.label for p in triage.perils[1:]],
        "excess": claims.applicable_excess(policy, peril),
        "indicative_view": view,
        "possible_issues": issues,
        "relevant_clauses": clauses,
    })


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False,
                                      openWorldHint=False))
def draft_client_email(client_id: str, subject: str, body: str, policy_id: str | None = None) -> dict:
    """Create an email DRAFT to a client. This does NOT send anything: the draft is stored as
    PENDING_APPROVAL and a human broker must review and approve it outside the AI assistant.
    Write 'Dear {client_first_name},' instead of the client's name - the server fills it in
    after approval. Include citations for any statement about cover. Any personal data in the
    text is redacted and the "not advice" disclaimer is appended automatically."""
    with db.session() as conn:
        client = db.get_client(conn, client_id)
        if not client:
            return {"created": False, "message": f"No client '{client_id}'."}
        if policy_id and not db.get_policy(conn, policy_id):
            return {"created": False, "message": f"No policy '{policy_id}'."}
        clean_subject = redact_text(subject, _client_known_values(client))
        clean_body = redact_text(body, _client_known_values(client)).rstrip()
        if config.DISCLAIMER not in clean_body:
            clean_body += f"\n\n---\nImportant: {config.DISCLAIMER}"
        draft_id = db.create_draft(conn, client["client_id"], policy_id, clean_subject, clean_body)

    warnings = []
    if "[" not in body or "p." not in body:
        warnings.append("Draft contains no policy citation - add one before approval if it discusses cover.")
    if clean_body.count("[REDACTED]") or any(t in clean_body for t in ("[EMAIL]", "[PHONE]", "[POSTCODE]")):
        warnings.append("Personal data was found in the draft and redacted.")
    log_event("draft_client_email", {"client_id": client_id, "policy_id": policy_id, "subject": clean_subject},
              f"{draft_id} PENDING_APPROVAL")
    return {
        "created": True,
        "draft_id": draft_id,
        "status": "PENDING_APPROVAL",
        "sent": False,
        "to": mask_email(client["email"]),
        "subject": clean_subject,
        "body_preview": clean_body,
        "warnings": warnings,
        "next_step": f"A human broker must review and approve: `policy-assistant approve {draft_id}`. "
                     "The assistant cannot send emails.",
    }


@mcp.resource("policy://documents")
def list_documents() -> str:
    """The insurer policy wordings indexed by this server."""
    return "\n".join(f"{s['doc_id']}: {s['insurer']} - {s['product']} ({s['url']})" for s in config.load_sources())


@mcp.resource("policy://disclaimer")
def disclaimer() -> str:
    """Disclaimer that must accompany every answer."""
    return config.DISCLAIMER


@mcp.prompt()
def coverage_question(client: str, question: str) -> str:
    """Answer a broker's coverage question about a client's policy, with citations."""
    return (
        f"Broker question about client '{client}': {question}\n\n"
        "Steps: 1) get_client_policies to find the active policy and its excesses; "
        "2) check_claim_eligibility (for a loss) and/or search_policy_wording for the clause; "
        "3) answer in 3-6 sentences, quoting the key clause and citing it like [Insurer Product, p.N]; "
        "state the applicable excess from the schedule and any exclusions to check; "
        "4) end with the disclaimer. Do not draft an email unless the broker asks."
    )


def main() -> None:
    db.init_db()
    mcp.run()


if __name__ == "__main__":
    main()
