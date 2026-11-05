"""Command line for setup and for the HUMAN side of the workflow (reviewing and approving
email drafts). Approval is deliberately not exposed as an MCP tool, so the AI cannot
approve or send its own drafts."""

import argparse
import sys
from email.message import EmailMessage

from . import config, db
from .audit import log_event


def _personalise(text: str, client) -> str:
    return text.replace("{client_first_name}", client["full_name"].split()[0]).replace(
        "{client_name}", client["full_name"]
    )


def cmd_setup(args) -> None:
    from .ingest import fetch_policies, ingest

    for line in fetch_policies(force=args.force):
        print(line)
    db.init_db(reset=args.reset_db)
    print(f"SQLite ready: {config.DB_PATH}")
    for doc_id, n in ingest().items():
        print(f"indexed {doc_id}: {n} chunks")


def cmd_drafts(args) -> None:
    with db.session() as conn:
        rows = db.list_drafts(conn, None if args.all else "PENDING_APPROVAL")
    if not rows:
        print("No drafts." if args.all else "No drafts awaiting approval.")
    for r in rows:
        print(f"{r['draft_id']}  {r['status']:<17} {r['client_id']}  {r['created_at']}  {r['subject']}")


def _show(draft, client) -> None:
    print(f"Draft:   {draft['draft_id']} ({draft['status']})")
    print(f"To:      {client['full_name']} <{client['email']}>")
    print(f"Subject: {_personalise(draft['subject'], client)}")
    print("-" * 70)
    print(_personalise(draft["body"], client))
    print("-" * 70)


def _load(draft_id: str):
    with db.session() as conn:
        draft = db.get_draft(conn, draft_id)
        if not draft:
            sys.exit(f"No draft {draft_id}")
        return draft, db.get_client(conn, draft["client_id"])


def cmd_show(args) -> None:
    _show(*_load(args.draft_id))


def cmd_approve(args) -> None:
    draft, client = _load(args.draft_id)
    if draft["status"] != "PENDING_APPROVAL":
        sys.exit(f"{draft['draft_id']} is {draft['status']}, not pending approval.")
    _show(draft, client)
    if not args.yes:
        answer = input(f"Type APPROVE to send as {args.reviewer}: ")
        if answer.strip() != "APPROVE":
            sys.exit("Not approved. Nothing was sent.")

    msg = EmailMessage()
    msg["From"] = "broker@example-brokers.co.uk"
    msg["To"] = client["email"]
    msg["Subject"] = _personalise(draft["subject"], client)
    msg["X-Approved-By"] = args.reviewer
    msg.set_content(_personalise(draft["body"], client))
    sent_dir = config.OUTBOX_DIR / "sent"
    sent_dir.mkdir(parents=True, exist_ok=True)
    path = sent_dir / f"{draft['draft_id']}.eml"
    path.write_bytes(bytes(msg))

    with db.session() as conn:
        db.set_draft_status(conn, draft["draft_id"], "APPROVED_SENT", args.reviewer, None)
    log_event("human_approve_email", {"draft_id": draft["draft_id"], "reviewer": args.reviewer}, "APPROVED_SENT")
    print(f"Approved by {args.reviewer}. Sent (simulated, no SMTP): {path}")


def cmd_reject(args) -> None:
    draft, _ = _load(args.draft_id)
    if draft["status"] != "PENDING_APPROVAL":
        sys.exit(f"{draft['draft_id']} is {draft['status']}, not pending approval.")
    with db.session() as conn:
        db.set_draft_status(conn, draft["draft_id"], "REJECTED", args.reviewer, args.reason)
    log_event("human_reject_email", {"draft_id": draft["draft_id"], "reviewer": args.reviewer}, "REJECTED")
    print(f"{draft['draft_id']} rejected.")


def cmd_serve(args) -> None:
    from .server import main as serve

    serve()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="policy-assistant", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("setup", help="download wordings, seed SQLite, build the ChromaDB index")
    p.add_argument("--force", action="store_true", help="re-download PDFs")
    p.add_argument("--reset-db", action="store_true", help="drop and re-seed the client database")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("serve", help="run the MCP server over stdio")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("drafts", help="list email drafts awaiting approval")
    p.add_argument("--all", action="store_true")
    p.set_defaults(func=cmd_drafts)

    p = sub.add_parser("show", help="show a draft with the client's real details filled in")
    p.add_argument("draft_id")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("approve", help="human sign-off: approve and send a draft")
    p.add_argument("draft_id")
    p.add_argument("--reviewer", required=True, help="name of the approving broker")
    p.add_argument("--yes", action="store_true", help="skip the interactive APPROVE prompt")
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("reject", help="reject a draft")
    p.add_argument("draft_id")
    p.add_argument("--reviewer", required=True)
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_reject)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
