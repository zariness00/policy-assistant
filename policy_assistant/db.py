"""SQLite store for fictional clients, their policy schedules and email drafts."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    client_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL,
    date_of_birth TEXT NOT NULL,
    address TEXT NOT NULL,
    postcode TEXT NOT NULL,
    broker_notes TEXT
);
CREATE TABLE IF NOT EXISTS policies (
    policy_id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL REFERENCES clients(client_id),
    doc_id TEXT NOT NULL,
    insurer TEXT NOT NULL,
    product_name TEXT NOT NULL,
    cover_type TEXT NOT NULL CHECK (cover_type IN ('buildings_and_contents', 'buildings', 'contents')),
    status TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    buildings_sum_insured INTEGER,
    contents_sum_insured INTEGER,
    standard_excess INTEGER NOT NULL,
    escape_of_water_excess INTEGER,
    subsidence_excess INTEGER,
    voluntary_excess INTEGER NOT NULL DEFAULT 0,
    accidental_damage_buildings INTEGER NOT NULL DEFAULT 0,
    accidental_damage_contents INTEGER NOT NULL DEFAULT 0,
    personal_possessions INTEGER NOT NULL DEFAULT 0,
    legal_expenses INTEGER NOT NULL DEFAULT 0,
    annual_premium REAL,
    endorsements TEXT
);
CREATE TABLE IF NOT EXISTS email_drafts (
    draft_id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL REFERENCES clients(client_id),
    policy_id TEXT,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PENDING_APPROVAL', 'APPROVED_SENT', 'REJECTED')),
    created_at TEXT NOT NULL,
    reviewed_by TEXT,
    reviewed_at TEXT,
    review_note TEXT
);
"""

# All people, addresses and contact details below are fictional.
CLIENTS = [
    ("C001", "Sarah Thompson", "sarah.thompson@example.com", "07700 900123", "1984-03-12",
     "14 Willow Crescent, Leeds", "LS6 2AB",
     "Prefers email. Called 02/10 about a damp patch; tel 07700 900123."),
    ("C002", "James Okafor", "j.okafor@example.org", "07700 900456", "1977-11-30",
     "3 Harbour View, Bristol", "BS1 5TT", "Landlord of two flats. Wants annual review in March."),
    ("C003", "Priya Patel", "priya.patel@example.net", "07700 900789", "1991-06-05",
     "Flat 9, 22 Canal Street, Manchester", "M1 3HE", "Renter, contents only."),
    ("C004", "Tom Gallagher", "tom.g@example.com", "07700 900321", "1965-01-20",
     "The Old Barn, Mill Lane, Harrogate", "HG3 1QP", "Listed building. Away Jan-Mar most years."),
    ("C005", "Aisha Rahman", "aisha.rahman@example.co.uk", "07700 900654", "1988-09-14",
     "57 Beech Road, Glasgow", "G12 8QQ", "First-time buyer."),
]

POLICIES = [
    # policy_id, client_id, doc_id, insurer, product, cover_type, status, start, end,
    # buildings SI, contents SI, std excess, EoW excess, subsidence excess, voluntary excess,
    # AD buildings, AD contents, personal possessions, legal expenses, premium, endorsements
    ("POL-1001", "C001", "rias_home", "RIAS", "Home Insurance", "buildings_and_contents", "active",
     "2026-04-01", "2027-03-31", 350000, 60000, 50, 250, 1000, 0, 0, 1, 0, 1, 412.50, None),
    ("POL-1002", "C002", "esure_home", "esure", "Home Core", "buildings", "active",
     "2026-01-15", "2027-01-14", 420000, None, 100, 350, 1000, 150, 0, 0, 0, 0, 389.00,
     "Property let to tenants - unoccupancy limit 30 days"),
    ("POL-1003", "C003", "aviva_home", "Aviva", "Home Insurance", "contents", "active",
     "2026-07-01", "2027-06-30", None, 25000, 100, 100, None, 0, 0, 0, 1, 0, 168.20, None),
    ("POL-1004", "C004", "aa_home", "AA", "Home Insurance (Gold)", "buildings_and_contents", "active",
     "2025-12-01", "2026-11-30", 650000, 90000, 125, 400, 1000, 250, 1, 1, 1, 1, 1240.00,
     "Listed building - specialist repair clause"),
    ("POL-1005", "C005", "esure_home", "esure", "Home Core", "buildings_and_contents", "active",
     "2026-05-20", "2027-05-19", 210000, 35000, 100, 350, 1000, 0, 0, 0, 0, 0, 301.75, None),
    ("POL-0901", "C001", "aviva_home", "Aviva", "Home Insurance", "buildings_and_contents", "lapsed",
     "2025-04-01", "2026-03-31", 340000, 55000, 100, 100, 1000, 0, 0, 0, 0, 0, 455.00,
     "Previous year's policy - replaced by POL-1001"),
]


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def session(db_path: Path | None = None):
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path | None = None, reset: bool = False) -> None:
    with session(db_path) as conn:
        if reset:
            conn.executescript(
                "DROP TABLE IF EXISTS email_drafts; DROP TABLE IF EXISTS policies; DROP TABLE IF EXISTS clients;"
            )
        conn.executescript(SCHEMA)
        conn.executemany("INSERT OR IGNORE INTO clients VALUES (?,?,?,?,?,?,?,?)", CLIENTS)
        conn.executemany(
            "INSERT OR IGNORE INTO policies VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", POLICIES
        )


def find_clients(conn: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
    q = query.strip()
    rows = conn.execute("SELECT * FROM clients WHERE upper(client_id) = upper(?)", (q,)).fetchall()
    if rows:
        return rows
    row = conn.execute(
        "SELECT c.* FROM clients c JOIN policies p ON p.client_id = c.client_id WHERE upper(p.policy_id) = upper(?)",
        (q,),
    ).fetchall()
    if row:
        return row
    return conn.execute("SELECT * FROM clients WHERE full_name LIKE ?", (f"%{q}%",)).fetchall()


def get_client(conn: sqlite3.Connection, client_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM clients WHERE upper(client_id) = upper(?)", (client_id,)).fetchone()


def get_policy(conn: sqlite3.Connection, policy_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM policies WHERE upper(policy_id) = upper(?)", (policy_id.strip(),)).fetchone()


def policies_for_client(conn: sqlite3.Connection, client_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM policies WHERE client_id = ? ORDER BY status = 'active' DESC, start_date DESC", (client_id,)
    ).fetchall()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_draft(conn: sqlite3.Connection, client_id: str, policy_id: str | None, subject: str, body: str) -> str:
    n = conn.execute("SELECT COUNT(*) FROM email_drafts").fetchone()[0] + 1
    draft_id = f"DRAFT-{n:04d}"
    conn.execute(
        "INSERT INTO email_drafts (draft_id, client_id, policy_id, subject, body, status, created_at) "
        "VALUES (?,?,?,?,?, 'PENDING_APPROVAL', ?)",
        (draft_id, client_id, policy_id, subject, body, now_iso()),
    )
    return draft_id


def get_draft(conn: sqlite3.Connection, draft_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM email_drafts WHERE upper(draft_id) = upper(?)", (draft_id,)).fetchone()


def list_drafts(conn: sqlite3.Connection, status: str | None = None) -> list[sqlite3.Row]:
    if status:
        return conn.execute("SELECT * FROM email_drafts WHERE status = ? ORDER BY created_at", (status,)).fetchall()
    return conn.execute("SELECT * FROM email_drafts ORDER BY created_at").fetchall()


def set_draft_status(conn: sqlite3.Connection, draft_id: str, status: str, reviewer: str, note: str | None) -> None:
    conn.execute(
        "UPDATE email_drafts SET status = ?, reviewed_by = ?, reviewed_at = ?, review_note = ? WHERE draft_id = ?",
        (status, reviewer, now_iso(), note, draft_id),
    )
