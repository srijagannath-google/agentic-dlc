#!/usr/bin/env python3
"""Business Licensing & Renewal Portal — backend (Python standard library only).

Serves the static UI (src/ui) and the JSON API (src/contracts/openapi.yaml) on one port, creates the SQLite
database from src/db/schema.sql on start and enforces the lifecycle state table (specs/application_spec.md §3.3)
and the RBAC matrix (§2.1) server-side.  Layers inside this single file, top to bottom:

    rules       — BR-01 … BR-08 (pure functions)
    workflow    — STATE_TABLE, PERMISSIONS, transition guards
    repository  — SQL (sqlite3, parameterised)
    viewmodel   — codes → labels, masking, formatting (the only shapes the API returns)
    handlers    — HTTP routing, validation, error envelopes

Run:  python3 src/backend/server.py            (PORT, APP_DB_PATH, APP_DB_RESET, APP_TAX_ID_SALT)
Test: python3 src/backend/server.py --self-test
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
import time
import traceback
import urllib.parse
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
UI_DIR = SRC / "ui"
SCHEMA_PATH = SRC / "db" / "schema.sql"
DB_PATH = Path(os.environ.get("APP_DB_PATH") or (HERE / "data" / "licensing.db"))
RESET_ON_START = os.environ.get("APP_DB_RESET", "1") != "0"
TAX_ID_SALT = os.environ.get("APP_TAX_ID_SALT", "release-1-pretotype-salt")
PORT = int(os.environ.get("PORT", "8767"))
VERSION = "1.0.0"
LICENSE_YEAR_DEFAULT = 2026

ROLE_BUYER = "Commercial Buyer"
ROLE_STAFF = "Licensing Staff"
ROLES = (ROLE_BUYER, ROLE_STAFF)


# ======================================================================================================
# rules — spec §3.4
# ======================================================================================================
CENT = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def required_bond(prior_year_purchases) -> Decimal:
    """BR-01: max(1000.00, round_half_up(0.10 × prior_year_purchases, 2))."""
    tenth = (Decimal(str(prior_year_purchases)) * Decimal("0.10")).quantize(CENT, rounding=ROUND_HALF_UP)
    return max(Decimal("1000.00"), tenth)


def bond_shortfall(prior_year_purchases, bond_amount) -> Decimal:
    short = required_bond(prior_year_purchases) - money(bond_amount)
    return short if short > 0 else Decimal("0.00")


def harvest_fee(purchase_total) -> Decimal:
    """BR-03: round_half_up(0.04 × purchase_total, 2)."""
    return (Decimal(str(purchase_total)) * Decimal("0.04")).quantize(CENT, rounding=ROUND_HALF_UP)


def fmt_money(value) -> str:
    return "${:,.2f}".format(money(value))


def shortfall_message(prior_year_purchases, bond_amount) -> str:
    """VAL-04 sentence."""
    req = required_bond(prior_year_purchases)
    short = bond_shortfall(prior_year_purchases, bond_amount)
    return f"Bond amount is below the required bond of {fmt_money(req)}. Increase the bond by {fmt_money(short)} before submitting."


# ======================================================================================================
# workflow — spec §3.3 state table and §2.1 RBAC matrix
# ======================================================================================================
STATE_LABELS = {
    "DRAFT": "Draft — not yet submitted",
    "SUBMITTED": "Submitted — awaiting review",
    "ISSUED": "Licence issued",
    "REJECTED": "Rejected",
}
TRIGGER_LABELS = {"SUBMIT": "Submit application", "ISSUE": "Issue licence", "REJECT": "Reject application"}
# (from, trigger, to, roles) — one row per spec §3.3 row; the UI holds the identical table.
STATE_TABLE = [
    ("DRAFT", "SUBMIT", "SUBMITTED", (ROLE_BUYER,)),
    ("SUBMITTED", "ISSUE", "ISSUED", (ROLE_STAFF,)),
    ("SUBMITTED", "REJECT", "REJECTED", (ROLE_STAFF,)),
]
TERMINAL_STATES = {"ISSUED", "REJECTED"}

PERMISSIONS = {
    ROLE_BUYER: {"application:create", "application:read-own", "application:update-draft", "SUBMIT",
                 "agent:manage-draft", "document:add", "fee-report:add", "calc"},
    ROLE_STAFF: {"application:read-all", "ISSUE", "REJECT", "agent:manage-review", "print", "registry:read",
                 "registry:suspend", "calc"},
}
ACTION_LABELS = {
    "CREATED": "Application created", "SUBMITTED": "Submitted", "ISSUED": "Licence issued", "REJECTED": "Rejected",
    "AGENT_ASSIGNED": "Agent assigned", "AGENT_REMOVED": "Agent removed", "CERTIFICATE_PRINTED": "Certificate printed",
    "AGENT_CARDS_PRINTED": "Agent cards printed", "SUSPENDED": "Suspended", "REINSTATED": "Reinstated",
    "PERMISSION_DENIED": "Permission denied", "DOCUMENT_ADDED": "Document attached", "FEE_REPORT_ADDED": "Fee report recorded",
}
DENY_PHRASES = {"SUBMIT": "submit applications", "ISSUE": "issue licences", "REJECT": "reject applications",
                "print": "print credentials", "registry:read": "view the registries", "registry:suspend": "change suspensions",
                "application:read-all": "view the review queue", "application:create": "create applications",
                "application:update-draft": "edit applications", "agent:manage-draft": "change the agent roster",
                "agent:manage-review": "change the agent roster", "document:add": "attach documents", "fee-report:add": "record fee reports"}


class ApiError(Exception):
    def __init__(self, status: int, message: str, code: str):
        super().__init__(message)
        self.status, self.message, self.code = status, message, code


def allowed_triggers(status: str, role: str | None) -> list[str]:
    return [trig for (src, trig, _dst, roles) in STATE_TABLE if src == status and (role in roles)]


def trigger_target(status: str, trigger: str) -> str | None:
    for src, trig, dst, _roles in STATE_TABLE:
        if src == status and trig == trigger:
            return dst
    return None


def check_transition(status: str, trigger: str, role: str | None) -> str:
    """Order matters (design §5): role first (403), then state (409). Returns the target state."""
    owners = {r for (_s, t, _d, roles) in STATE_TABLE if t == trigger for r in roles}
    if role not in owners:
        raise ApiError(403, f"You do not have permission to {DENY_PHRASES[trigger]}.", "PERMISSION_DENIED")
    target = trigger_target(status, trigger)
    if target is None:
        raise ApiError(409, f"This application is {STATE_LABELS[status]}; {TRIGGER_LABELS[trigger].split(' ')[0]} is not possible from this status.", "ILLEGAL_TRANSITION")
    return target


def authorize(action: str, role: str | None) -> None:
    if role not in PERMISSIONS or action not in PERMISSIONS[role]:
        raise ApiError(403, f"You do not have permission to {DENY_PHRASES.get(action, action)}.", "PERMISSION_DENIED")


# ======================================================================================================
# repository — SQL lives here only
# ======================================================================================================
def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def tax_id_digits(raw: str) -> str:
    return re.sub(r"\D", "", raw or "")


def tax_id_hash(raw: str) -> str:
    return hashlib.sha256((TAX_ID_SALT + tax_id_digits(raw)).encode("utf-8")).hexdigest()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    fresh = RESET_ON_START or not DB_PATH.exists()
    if RESET_ON_START and DB_PATH.exists():
        DB_PATH.unlink()
    conn = connect()
    try:
        if fresh:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            seed_demo_data(conn)
            conn.commit()
    finally:
        conn.close()


def insert(conn, table: str, row: dict) -> int:
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(row.values()))
    return int(cur.lastrowid)


def audit(conn, action: str, role: str, actor: str | None, *, application_id=None, buyer_id=None, agent_id=None,
          from_status=None, to_status=None, reason=None, occurred_at=None) -> None:
    insert(conn, "audit_events", {"application_id": application_id, "buyer_id": buyer_id, "agent_id": agent_id,
                                  "actor_role": role, "actor_name": actor, "action": action, "from_status": from_status,
                                  "to_status": to_status, "reason": reason, "occurred_at": occurred_at or now_iso()})


def seed_demo_data(conn) -> None:
    """Deterministic pretotype data for licence year 2026 (documented in src/README.md)."""
    ts = "2026-01-10T09:00:00Z"
    buyers = [
        # legal_name, business_name, entity, kind, raw tax id, dob, email, city, suspended
        ("Acme Commercial Services", "Acme Commercial Services", "CORPORATION", "FEIN", "36-1122334", "1970-01-15", "office@acmecommercial.example", "Metropolis", 0),
        ("Apex Retail Group", "Apex Retail Group", "CORPORATION", "FEIN", "12-3454567", "1968-05-20", "licensing@apexretail.example", "Centerville", 0),
        ("Horizon Logistics", "Horizon Logistics", "PARTNERSHIP", "FEIN", "45-6784321", "1975-09-09", "ops@horizonlogistics.example", "Oakdale", 0),
        ("Oakridge Distribution", "Oakridge Distribution", "CORPORATION", "FEIN", "55-5551212", "1980-02-02", "mill@oakridgedist.example", "Fairview", 0),
        ("Northwind Commerce", "Northwind Commerce", "LLC", "FEIN", "66-6660001", "1972-11-30", "admin@northwindcommerce.example", "Riverside", 1),
        ("Cedar Ridge Buyers", "Cedar Ridge Buyers", "CORPORATION", "FEIN", "77-7770002", "1983-04-18", "buyers@cedarridge.example", "Georgetown", 0),
        ("Heartland Enterprise Partners", "Heartland Enterprise Partners", "PARTNERSHIP", "FEIN", "88-8880003", "1979-08-08", "team@heartlandent.example", "Franklin", 0),
        ("Vanguard Industrial Products", "Vanguard Industrial Products", "CORPORATION", "FEIN", "91-0010004", "1981-03-03", "info@vanguardindustrial.example", "Clinton", 0),
        ("Summit Valley Supply", "Summit Valley Supply", "PARTNERSHIP", "FEIN", "92-0010005", "1977-06-06", "desk@summitsupply.example", "Madison", 0),
        ("Metro Trade", "Metro Trade", "CORPORATION", "FEIN", "93-0010006", "1984-10-10", "hello@metrotrade.example", "Waverly", 0),
    ]
    buyer_ids = []
    for legal, biz, ent, kind, raw, dob, email, city, susp in buyers:
        buyer_ids.append(insert(conn, "commercial_buyers", {
            "legal_name": legal, "business_name": biz, "entity_type": ent, "tax_id_kind": kind,
            "tax_id_hash": tax_id_hash(raw), "tax_id_last4": tax_id_digits(raw)[-4:], "date_of_birth": dob,
            "email": email, "phone": "555-010-0100", "city": city, "state_code": "IL", "is_suspended": susp,
            "under_investigation": 0, "created_at": ts, "updated_at": ts}))
    apps = [
        # buyer index, status, prior, bond, surety, submitted, decided, reason, license_number
        (0, "DRAFT", 15000, 1500, "Granite State Surety", None, None, None, None),
        (1, "SUBMITTED", 25000, 2500, "Midwest Bonding Company", "2026-01-12T10:00:00Z", None, None, None),
        (2, "ISSUED", 80000, 8000, "Heartland Casualty", "2026-01-05T08:30:00Z", "2026-01-08T14:00:00Z", None, "TB-2026-00003"),
        (3, "REJECTED", 40000, 4000, "Unlisted Surety Group", "2026-01-06T11:00:00Z", "2026-01-09T09:15:00Z", "Bond certificate is missing the surety company signature", None),
        (4, "SUBMITTED", 30000, 3000, "Midwest Bonding Company", "2026-01-13T10:00:00Z", None, None, None),
        (5, "SUBMITTED", 12000, 1200, "Granite State Surety", "2026-01-14T10:00:00Z", None, None, None),
        (6, "SUBMITTED", 50000, 5000, "Heartland Casualty", "2026-01-15T10:00:00Z", None, None, None),
        (7, "SUBMITTED", 20000, 2000, "Midwest Bonding Company", "2026-01-16T10:00:00Z", None, None, None),
        (8, "SUBMITTED", 35000, 3500, "Granite State Surety", "2026-01-17T10:00:00Z", None, None, None),
        (9, "SUBMITTED", 45000, 4500, "Heartland Casualty", "2026-01-18T10:00:00Z", None, None, None),
    ]
    app_ids = []
    for bi, status, prior, bond, surety, sub, dec, reason, lic in apps:
        app_ids.append(insert(conn, "license_applications", {
            "buyer_id": buyer_ids[bi], "license_year": LICENSE_YEAR_DEFAULT, "status": status, "license_number": lic,
            "prior_year_purchases": prior, "required_bond_amount": str(required_bond(prior)), "bond_amount": bond,
            "bond_surety_name": surety, "bond_number": f"SB-{1000 + bi}", "bond_expiry": "2026-12-31",
            "decision_reason": reason, "submitted_at": sub, "decided_at": dec, "created_at": ts, "updated_at": ts}))
    # owner agents (BR-05)
    for i, (legal, _b, _e, _k, _r, dob, *_rest) in enumerate(buyers):
        first, last = split_name(legal)
        aid = insert(conn, "field_agents", {"first_name": first, "last_name": last, "date_of_birth": dob,
                                                 "is_suspended": 0, "created_at": ts, "updated_at": ts})
        insert(conn, "agent_assignments", {"application_id": app_ids[i], "agent_id": aid, "relationship": "OWNER",
                                           "assigned_on": "2026-01-10", "removed_on": None, "card_printed_at": None})
    extra = [("Dale", "Whitaker", "1979-03-14", 0), ("Alex", "Alvarez", "1990-11-23", 1), ("Marcus", "Lee", "1988-07-02", 0),
             ("Priya", "Natarajan", "1985-12-01", 0)]
    extra_ids = [insert(conn, "field_agents", {"first_name": f, "last_name": l, "date_of_birth": d, "is_suspended": s,
                                                    "created_at": ts, "updated_at": ts}) for f, l, d, s in extra]
    insert(conn, "agent_assignments", {"application_id": app_ids[2], "agent_id": extra_ids[0], "relationship": "AGENT",
                                       "assigned_on": "2026-01-06", "removed_on": None, "card_printed_at": None})
    insert(conn, "supporting_documents", {"application_id": app_ids[1], "file_name": "surety-bond-apex.pdf", "content_type": "application/pdf",
                                          "size_bytes": 184320, "vault_reference": None, "uploaded_at": ts})
    for i, (_bi, status, _p, _b, _s, submitted, decided, reason, _lic) in enumerate(apps):
        audit(conn, "CREATED", ROLE_BUYER, buyers[i][0], application_id=app_ids[i], to_status="DRAFT", occurred_at=ts)
        if status != "DRAFT":
            audit(conn, "SUBMITTED", ROLE_BUYER, buyers[i][0], application_id=app_ids[i], from_status="DRAFT", to_status="SUBMITTED", occurred_at=submitted)
        if status == "ISSUED":
            audit(conn, "ISSUED", ROLE_STAFF, "Commercial Licensing Desk", application_id=app_ids[i], from_status="SUBMITTED", to_status="ISSUED", occurred_at=decided)
        if status == "REJECTED":
            audit(conn, "REJECTED", ROLE_STAFF, "Commercial Licensing Desk", application_id=app_ids[i], from_status="SUBMITTED", to_status="REJECTED", reason=reason, occurred_at=decided)
    audit(conn, "SUSPENDED", ROLE_STAFF, "Commercial Licensing Desk", buyer_id=buyer_ids[4], reason="Outstanding volume-fee remittance", occurred_at=ts)
    audit(conn, "SUSPENDED", ROLE_STAFF, "Commercial Licensing Desk", agent_id=extra_ids[1], reason="Enforcement referral", occurred_at=ts)


def split_name(full: str) -> tuple[str, str]:
    parts = (full or "").strip().split()
    if len(parts) <= 1:
        return (parts[0] if parts else "", parts[0] if parts else "")
    return (" ".join(parts[:-1]), parts[-1])


def fetch_application_row(conn, application_id: int):
    row = conn.execute("SELECT * FROM license_applications WHERE application_id = ?", (application_id,)).fetchone()
    if not row:
        raise ApiError(404, "No application exists with that number.", "NOT_FOUND")
    return row


def fetch_buyer_row(conn, buyer_id: int):
    row = conn.execute("SELECT * FROM commercial_buyers WHERE buyer_id = ?", (buyer_id,)).fetchone()
    if not row:
        raise ApiError(404, "No buyer exists with that number.", "NOT_FOUND")
    return row


def fetch_agent_row(conn, agent_id: int):
    row = conn.execute("SELECT * FROM field_agents WHERE agent_id = ?", (agent_id,)).fetchone()
    if not row:
        raise ApiError(404, "No agent exists with that number.", "NOT_FOUND")
    return row


def active_roster(conn, application_id: int):
    return conn.execute(
        "SELECT a.assignment_id, a.relationship, a.card_printed_at, g.agent_id, g.first_name, g.last_name, g.date_of_birth, g.is_suspended "
        "FROM agent_assignments a JOIN field_agents g ON g.agent_id = a.agent_id "
        "WHERE a.application_id = ? AND a.removed_on IS NULL ORDER BY a.relationship = 'OWNER' DESC, a.assignment_id",
        (application_id,)).fetchall()


def conflicting_assignment(conn, agent_id: int, license_year: int, exclude_application_id: int | None = None):
    """BR-02: active assignment on a SUBMITTED or ISSUED application of the same year."""
    return conn.execute(
        "SELECT la.application_id, la.license_number FROM agent_assignments a JOIN license_applications la ON la.application_id = a.application_id "
        "WHERE a.agent_id = ? AND a.removed_on IS NULL AND la.license_year = ? AND la.status IN ('SUBMITTED', 'ISSUED') "
        "AND (? IS NULL OR la.application_id <> ?) LIMIT 1",
        (agent_id, license_year, exclude_application_id, exclude_application_id)).fetchone()


def other_open_application(conn, buyer_id: int, license_year: int, exclude_application_id: int | None = None):
    """BR-04: another non-rejected application for buyer + year."""
    return conn.execute(
        "SELECT application_id, status FROM license_applications WHERE buyer_id = ? AND license_year = ? AND status <> 'REJECTED' "
        "AND (? IS NULL OR application_id <> ?) ORDER BY application_id LIMIT 1",
        (buyer_id, license_year, exclude_application_id, exclude_application_id)).fetchone()


# ======================================================================================================
# viewmodel — the only shapes the API returns (design §4)
# ======================================================================================================
def mask_tax_id(kind: str, last4: str) -> str:
    return f"***-**-{last4}" if kind == "SSN" else f"**-***{last4}"


def status_vm(code: str) -> dict:
    return {"code": code, "label": STATE_LABELS[code]}


def app_number(application_id: int, license_year: int) -> str:
    return f"APP-{license_year}-{application_id:06d}"


def bond_check_text(prior, bond) -> str:
    short = bond_shortfall(prior, bond)
    return "Sufficient" if short == 0 else shortfall_message(prior, bond)


def buyer_vm(conn, row, role: str | None) -> dict:
    count = conn.execute("SELECT COUNT(*) FROM license_applications WHERE buyer_id = ?", (row["buyer_id"],)).fetchone()[0]
    vm = {"buyerId": row["buyer_id"], "legalName": row["legal_name"], "businessName": row["business_name"],
          "entityType": row["entity_type"], "entityTypeLabel": ENTITY_LABELS.get(row["entity_type"], "Other"),
          "maskedTaxId": mask_tax_id(row["tax_id_kind"], row["tax_id_last4"]),
          "suspended": bool(row["is_suspended"]), "suspensionLabel": "Suspended" if row["is_suspended"] else "Active",
          "underInvestigation": bool(row["under_investigation"]), "applicationCount": count,
          "dateOfBirth": row["date_of_birth"], "email": row["email"], "phone": row["phone"], "city": row["city"], "stateCode": row["state_code"]}
    return vm


ENTITY_LABELS = {"INDIVIDUAL": "Individual / sole proprietor", "LLC": "Limited liability company", "CORPORATION": "Corporation",
                 "PARTNERSHIP": "Partnership", "OTHER": "Other"}
TAX_KIND_LABELS = {"SSN": "Social-security number", "FEIN": "Employer identification number"}


def roster_vm(conn, application_id: int, notice: str = "") -> dict:
    entries = []
    for r in active_roster(conn, application_id):
        entries.append({"agentId": r["agent_id"], "fullName": f"{r['first_name']} {r['last_name']}",
                        "relationshipLabel": "Owner" if r["relationship"] == "OWNER" else "Agent", "isOwner": r["relationship"] == "OWNER",
                        "cardPrinted": bool(r["card_printed_at"]), "cardPrintedLabel": "Card printed" if r["card_printed_at"] else "Card not printed",
                        "suspended": bool(r["is_suspended"])})
    return {"notice": notice, "entries": entries}


def size_label(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} bytes"


TYPE_LABELS = {"application/pdf": "PDF", "image/jpeg": "JPEG image", "image/png": "PNG image", "text/plain": "Text"}


def documents_vm(conn, application_id: int) -> list:
    rows = conn.execute("SELECT * FROM supporting_documents WHERE application_id = ? ORDER BY document_id", (application_id,)).fetchall()
    return [{"documentId": r["document_id"], "fileName": r["file_name"], "typeLabel": TYPE_LABELS.get(r["content_type"], r["content_type"]),
             "sizeLabel": size_label(r["size_bytes"]), "uploadedAt": r["uploaded_at"]} for r in rows]


def fee_reports_vm(conn, application_id: int) -> list:
    rows = conn.execute("SELECT * FROM quarterly_fee_reports WHERE application_id = ? ORDER BY report_id", (application_id,)).fetchall()
    return [{"reportId": r["report_id"], "quarter": r["quarter"], "purchaseTotal": float(money(r["purchase_total"])), "feeDue": float(money(r["fee_due"])),
             "summary": f"{r['quarter']} — purchases {fmt_money(r['purchase_total'])} — fee due {fmt_money(r['fee_due'])}"} for r in rows]


def history_vm(conn, application_id: int) -> list:
    rows = conn.execute("SELECT * FROM audit_events WHERE application_id = ? ORDER BY event_id", (application_id,)).fetchall()
    return [{"actionLabel": ACTION_LABELS.get(r["action"], r["action"].title()), "actorRole": r["actor_role"],
             "fromStatusLabel": STATE_LABELS.get(r["from_status"]) if r["from_status"] else None,
             "toStatusLabel": STATE_LABELS.get(r["to_status"]) if r["to_status"] else None,
             "reason": r["reason"], "occurredAt": r["occurred_at"]} for r in rows]


def summary_vm(conn, row) -> dict:
    buyer = fetch_buyer_row(conn, row["buyer_id"])
    return {"applicationId": row["application_id"], "applicationNumber": app_number(row["application_id"], row["license_year"]),
            "licenseYear": row["license_year"], "buyerName": buyer["legal_name"], "status": status_vm(row["status"]),
            "licenseNumber": row["license_number"], "bondCheck": bond_check_text(row["prior_year_purchases"], row["bond_amount"]),
            "submittedAt": row["submitted_at"]}


def application_vm(conn, row, role: str | None, notice: str = "") -> dict:
    vm = summary_vm(conn, row)
    buyer = fetch_buyer_row(conn, row["buyer_id"])
    vm.update({"buyer": buyer_vm(conn, buyer, role), "priorYearPurchases": float(money(row["prior_year_purchases"])),
               "requiredBondAmount": float(required_bond(row["prior_year_purchases"])), "bondAmount": float(money(row["bond_amount"])),
               "bondShortfall": float(bond_shortfall(row["prior_year_purchases"], row["bond_amount"])),
               "bondSuretyName": row["bond_surety_name"], "bondNumber": row["bond_number"], "bondExpiry": row["bond_expiry"],
               "decisionReason": row["decision_reason"], "decidedAt": row["decided_at"],
               "allowedTriggers": allowed_triggers(row["status"], role), "agents": roster_vm(conn, row["application_id"], notice),
               "documents": documents_vm(conn, row["application_id"]), "feeReports": fee_reports_vm(conn, row["application_id"]),
               "history": history_vm(conn, row["application_id"])})
    return vm


def agent_vm(conn, row) -> dict:
    cur = conn.execute("SELECT la.license_number, la.status FROM agent_assignments a JOIN license_applications la ON la.application_id = a.application_id "
                       "WHERE a.agent_id = ? AND a.removed_on IS NULL AND la.status IN ('SUBMITTED', 'ISSUED') ORDER BY la.application_id DESC LIMIT 1",
                       (row["agent_id"],)).fetchone()
    count = conn.execute("SELECT COUNT(*) FROM agent_assignments WHERE agent_id = ?", (row["agent_id"],)).fetchone()[0]
    return {"agentId": row["agent_id"], "fullName": f"{row['first_name']} {row['last_name']}", "dateOfBirth": row["date_of_birth"],
            "suspended": bool(row["is_suspended"]), "suspensionLabel": "Suspended" if row["is_suspended"] else "Active",
            "currentLicenseNumber": (cur["license_number"] if cur and cur["license_number"] else ("Application under review" if cur else None)),
            "assignmentCount": count}


# ======================================================================================================
# services — validation + use cases
# ======================================================================================================
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SSN_RE = re.compile(r"^\d{3}-\d{2}-\d{4}$")
FEIN_RE = re.compile(r"^\d{2}-\d{7}$")
AMOUNT_MSG = "Enter amounts in dollars, for example 25000.00."


def req_str(body: dict, key: str, max_len: int, required: bool = True) -> str | None:
    val = body.get(key)
    if val is None or str(val).strip() == "":
        if required:
            raise ApiError(400, f"{key} is required.", "VALIDATION")
        return None
    val = str(val).strip()
    if len(val) > max_len:
        raise ApiError(400, f"{key} must be {max_len} characters or fewer.", "VALIDATION")
    return val


def req_amount(body: dict, key: str, required: bool = True, default=None):
    val = body.get(key, default)
    if val is None or str(val).strip() == "":
        if required:
            raise ApiError(400, AMOUNT_MSG, "VALIDATION")
        return None
    try:
        dec = Decimal(str(val).replace(",", "").replace("$", ""))
    except Exception:
        raise ApiError(400, AMOUNT_MSG, "VALIDATION")
    if dec < 0 or dec > Decimal("1000000000"):
        raise ApiError(400, AMOUNT_MSG, "VALIDATION")
    return money(dec)


def req_date(body: dict, key: str, required: bool = True) -> str | None:
    val = req_str(body, key, 10, required)
    if val is None:
        return None
    if not DATE_RE.match(val):
        raise ApiError(400, f"Enter {key} as a date in the form 2026-01-31.", "VALIDATION")
    return val


def svc_create_application(conn, body: dict, role: str, actor: str | None) -> dict:
    authorize("application:create", role)
    legal = req_str(body, "legalName", 200)
    business = req_str(body, "businessName", 200, required=False)
    entity = req_str(body, "entityType", 20)
    if entity not in ENTITY_LABELS:
        raise ApiError(400, "Choose the entity type from the list.", "VALIDATION")
    kind = req_str(body, "taxIdKind", 4)
    raw = req_str(body, "taxId", 20)
    if kind not in ("SSN", "FEIN") or not ((kind == "SSN" and SSN_RE.match(raw)) or (kind == "FEIN" and FEIN_RE.match(raw))):
        raise ApiError(400, "Enter the tax identifier as NNN-NN-NNNN (Social-security number) or NN-NNNNNNN (employer identification number).", "VALIDATION")
    dob = req_date(body, "dateOfBirth")
    year = body.get("licenseYear", LICENSE_YEAR_DEFAULT)
    try:
        year = int(year)
    except Exception:
        raise ApiError(400, "Choose the licence year.", "VALIDATION")
    if not 2000 <= year <= 2100:
        raise ApiError(400, "Choose the licence year.", "VALIDATION")
    prior = req_amount(body, "priorYearPurchases", required=False, default="0")
    bond = req_amount(body, "bondAmount", required=False, default="0")
    surety = req_str(body, "bondSuretyName", 200, required=False)
    bond_no = req_str(body, "bondNumber", 100, required=False)
    expiry = req_date(body, "bondExpiry", required=False)
    ts = now_iso()
    h = tax_id_hash(raw)
    buyer = conn.execute("SELECT * FROM commercial_buyers WHERE tax_id_hash = ?", (h,)).fetchone()
    if buyer:
        buyer_id = buyer["buyer_id"]
        other = other_open_application(conn, buyer_id, year)
        if other:
            raise ApiError(409, f"An application for {year} already exists for this buyer ({STATE_LABELS[other['status']]}). Open it instead of starting a new one.", "DUPLICATE_APPLICATION")
    else:
        buyer_id = insert(conn, "commercial_buyers", {
            "legal_name": legal, "business_name": business, "entity_type": entity, "tax_id_kind": kind, "tax_id_hash": h,
            "tax_id_last4": tax_id_digits(raw)[-4:], "date_of_birth": dob, "email": req_str(body, "email", 200, False),
            "phone": req_str(body, "phone", 40, False), "city": req_str(body, "city", 100, False),
            "state_code": req_str(body, "stateCode", 2, False), "is_suspended": 0, "under_investigation": 0,
            "created_at": ts, "updated_at": ts})
    app_id = insert(conn, "license_applications", {
        "buyer_id": buyer_id, "license_year": year, "status": "DRAFT", "license_number": None, "prior_year_purchases": str(prior),
        "required_bond_amount": str(required_bond(prior)), "bond_amount": str(bond), "bond_surety_name": surety, "bond_number": bond_no,
        "bond_expiry": expiry, "decision_reason": None, "submitted_at": None, "decided_at": None, "created_at": ts, "updated_at": ts})
    # BR-05 owner agent (re-use an agent record with the same name + date of birth, BR-07)
    first, last = split_name(legal)
    agent = conn.execute("SELECT agent_id FROM field_agents WHERE lower(last_name) = lower(?) AND lower(first_name) = lower(?) AND date_of_birth = ?",
                         (last, first, dob)).fetchone()
    agent_id = agent["agent_id"] if agent else insert(conn, "field_agents", {
        "first_name": first, "last_name": last, "date_of_birth": dob, "is_suspended": 0, "created_at": ts, "updated_at": ts})
    insert(conn, "agent_assignments", {"application_id": app_id, "agent_id": agent_id, "relationship": "OWNER",
                                       "assigned_on": today_iso(), "removed_on": None, "card_printed_at": None})
    audit(conn, "CREATED", role, actor or legal, application_id=app_id, to_status="DRAFT")
    return application_vm(conn, fetch_application_row(conn, app_id), role)


def svc_update_draft(conn, app_id: int, body: dict, role: str, actor: str | None) -> dict:
    authorize("application:update-draft", role)
    row = fetch_application_row(conn, app_id)
    if row["status"] != "DRAFT":
        raise ApiError(409, f"This application is {STATE_LABELS[row['status']]}; it can no longer be edited.", "ILLEGAL_TRANSITION")
    prior = req_amount(body, "priorYearPurchases", required=False, default=str(row["prior_year_purchases"]))
    bond = req_amount(body, "bondAmount", required=False, default=str(row["bond_amount"]))
    conn.execute("UPDATE license_applications SET prior_year_purchases = ?, required_bond_amount = ?, bond_amount = ?, bond_surety_name = ?, "
                 "bond_number = ?, bond_expiry = ?, updated_at = ? WHERE application_id = ?",
                 (str(prior), str(required_bond(prior)), str(bond), req_str(body, "bondSuretyName", 200, False) or row["bond_surety_name"],
                  req_str(body, "bondNumber", 100, False) or row["bond_number"], req_date(body, "bondExpiry", False) or row["bond_expiry"],
                  now_iso(), app_id))
    return application_vm(conn, fetch_application_row(conn, app_id), role)


def svc_transition(conn, app_id: int, trigger: str, body: dict, role: str | None, actor: str | None) -> dict:
    row = fetch_application_row(conn, app_id)
    try:
        target = check_transition(row["status"], trigger, role)
    except ApiError as e:
        if e.code == "PERMISSION_DENIED":
            audit(conn, "PERMISSION_DENIED", role or "anonymous", actor, application_id=app_id, reason=f"{TRIGGER_LABELS[trigger]} is not permitted for this role")
            conn.commit()
        raise
    buyer = fetch_buyer_row(conn, row["buyer_id"])
    reason = None
    lic = row["license_number"]
    if trigger == "SUBMIT":
        if not row["bond_surety_name"] or not row["bond_number"]:
            raise ApiError(409, "Enter the surety company and bond number before submitting.", "GUARD_FAILED")
        if bond_shortfall(row["prior_year_purchases"], row["bond_amount"]) > 0:
            raise ApiError(409, shortfall_message(row["prior_year_purchases"], row["bond_amount"]), "GUARD_FAILED")
        for r in active_roster(conn, app_id):
            if r["relationship"] != "OWNER" and conflicting_assignment(conn, r["agent_id"], row["license_year"], app_id):
                raise ApiError(409, f"{r['first_name']} {r['last_name']} is already an agent for another licensed buyer in {row['license_year']}. One licensed buyer per calendar year is allowed.", "GUARD_FAILED")
        other = other_open_application(conn, row["buyer_id"], row["license_year"], app_id)
        if other:
            raise ApiError(409, f"An application for {row['license_year']} already exists for this buyer ({STATE_LABELS[other['status']]}). Open it instead of starting a new one.", "GUARD_FAILED")
    elif trigger == "ISSUE":
        failing = None
        if buyer["is_suspended"]:
            failing = "the buyer is suspended"
        elif bond_shortfall(row["prior_year_purchases"], row["bond_amount"]) > 0:
            failing = f"the bond is {fmt_money(bond_shortfall(row['prior_year_purchases'], row['bond_amount']))} below the required bond"
        else:
            for r in active_roster(conn, app_id):
                if r["is_suspended"]:
                    failing = f"agent {r['first_name']} {r['last_name']} is suspended"
                    break
                if r["relationship"] != "OWNER" and conflicting_assignment(conn, r["agent_id"], row["license_year"], app_id):
                    failing = f"agent {r['first_name']} {r['last_name']} is already an agent for another licensed buyer in {row['license_year']}"
                    break
        if failing:
            raise ApiError(409, f"The licence cannot be issued: {failing}. Resolve it and try again.", "GUARD_FAILED")
        lic = f"TB-{row['license_year']}-{row['buyer_id']:05d}"
    elif trigger == "REJECT":
        reason = (body.get("reason") or "").strip()
        if len(reason) < 10:
            raise ApiError(400, "Enter a rejection reason of at least 10 characters so the buyer knows what to correct.", "VALIDATION")
        if len(reason) > 500:
            raise ApiError(400, "Keep the rejection reason to 500 characters or fewer.", "VALIDATION")
    ts = now_iso()
    conn.execute("UPDATE license_applications SET status = ?, license_number = ?, decision_reason = COALESCE(?, decision_reason), "
                 "submitted_at = CASE WHEN ? = 'SUBMITTED' THEN ? ELSE submitted_at END, "
                 "decided_at = CASE WHEN ? IN ('ISSUED', 'REJECTED') THEN ? ELSE decided_at END, updated_at = ? WHERE application_id = ?",
                 (target, lic, reason, target, ts, target, ts, ts, app_id))
    audit(conn, target, role, actor, application_id=app_id, from_status=row["status"], to_status=target, reason=reason)
    return application_vm(conn, fetch_application_row(conn, app_id), role)


def roster_permission(row, role: str | None) -> None:
    if role == ROLE_BUYER:
        authorize("agent:manage-draft", role)
        if row["status"] != "DRAFT":
            raise ApiError(409, f"This application is {STATE_LABELS[row['status']]}; the roster can only be changed while it is a draft.", "ILLEGAL_TRANSITION")
    else:
        authorize("agent:manage-review", role)
        if row["status"] not in ("SUBMITTED", "ISSUED"):
            raise ApiError(409, f"This application is {STATE_LABELS[row['status']]}; staff change the roster on submitted or issued applications only.", "ILLEGAL_TRANSITION")


def svc_add_agent(conn, app_id: int, body: dict, role: str | None, actor: str | None) -> tuple[int, dict]:
    row = fetch_application_row(conn, app_id)
    roster_permission(row, role)
    missing = [k for k in ("firstName", "lastName", "dateOfBirth") if not str(body.get(k) or "").strip()]
    if missing:
        raise ApiError(400, "Enter the agent's first name, last name and date of birth.", "VALIDATION")
    first = req_str(body, "firstName", 100)
    last = req_str(body, "lastName", 100)
    dob = req_date(body, "dateOfBirth")
    ts = now_iso()
    agent = conn.execute("SELECT * FROM field_agents WHERE lower(last_name) = lower(?) AND date_of_birth = ?", (last, dob)).fetchone()
    if agent is None:
        first_t, last_t = first.title() if first.islower() or first.isupper() else first, last.title() if last.islower() or last.isupper() else last
        agent_id = insert(conn, "field_agents", {"first_name": first_t, "last_name": last_t, "date_of_birth": dob, "is_suspended": 0,
                                                      "created_at": ts, "updated_at": ts})
        agent = fetch_agent_row(conn, agent_id)
    full = f"{agent['first_name']} {agent['last_name']}"
    already = conn.execute("SELECT 1 FROM agent_assignments WHERE application_id = ? AND agent_id = ? AND removed_on IS NULL", (app_id, agent["agent_id"])).fetchone()
    if already:
        return 200, application_vm(conn, row, role, notice=f"{full} is already on this roster")
    if agent["is_suspended"]:
        raise ApiError(409, "This agent is suspended and cannot be assigned. Contact licensing staff to review the suspension.", "AGENT_SUSPENDED")
    if conflicting_assignment(conn, agent["agent_id"], row["license_year"], app_id):
        raise ApiError(409, f"This person is already an agent for another licensed buyer in {row['license_year']}. One licensed buyer per calendar year is allowed.", "AGENT_CONFLICT")
    insert(conn, "agent_assignments", {"application_id": app_id, "agent_id": agent["agent_id"], "relationship": "AGENT",
                                       "assigned_on": today_iso(), "removed_on": None, "card_printed_at": None})
    audit(conn, "AGENT_ASSIGNED", role, actor, application_id=app_id, agent_id=agent["agent_id"], reason=full)
    return 201, application_vm(conn, row, role, notice=f"{full} added to the roster")


def svc_remove_agent(conn, app_id: int, agent_id: int, role: str | None, actor: str | None) -> dict:
    row = fetch_application_row(conn, app_id)
    roster_permission(row, role)
    a = conn.execute("SELECT * FROM agent_assignments WHERE application_id = ? AND agent_id = ? AND removed_on IS NULL", (app_id, agent_id)).fetchone()
    if not a:
        raise ApiError(404, "That agent is not on this roster.", "NOT_FOUND")
    if a["relationship"] == "OWNER":
        raise ApiError(409, "The licence holder is the owner agent and cannot be removed.", "OWNER_LOCKED")
    conn.execute("UPDATE agent_assignments SET removed_on = ? WHERE assignment_id = ?", (today_iso(), a["assignment_id"]))
    g = fetch_agent_row(conn, agent_id)
    full = f"{g['first_name']} {g['last_name']}"
    audit(conn, "AGENT_REMOVED", role, actor, application_id=app_id, agent_id=agent_id, reason=full)
    return application_vm(conn, row, role, notice=f"{full} removed from the roster")


def svc_add_document(conn, app_id: int, body: dict, role: str | None, actor: str | None) -> list:
    authorize("document:add", role)
    row = fetch_application_row(conn, app_id)
    if row["status"] != "DRAFT":
        raise ApiError(409, f"This application is {STATE_LABELS[row['status']]}; documents can be attached while it is a draft.", "ILLEGAL_TRANSITION")
    if not str(body.get("fileName") or "").strip():
        raise ApiError(400, "Enter the document name to attach it.", "VALIDATION")
    name = req_str(body, "fileName", 200)
    ctype = req_str(body, "contentType", 100)
    try:
        size = int(body.get("sizeBytes"))
        assert size >= 0
    except Exception:
        raise ApiError(400, "Enter the document size in bytes.", "VALIDATION")
    insert(conn, "supporting_documents", {"application_id": app_id, "file_name": name, "content_type": ctype, "size_bytes": size,
                                          "vault_reference": None, "uploaded_at": now_iso()})
    audit(conn, "DOCUMENT_ADDED", role, actor, application_id=app_id, reason=name)
    return documents_vm(conn, app_id)


def svc_add_fee_report(conn, app_id: int, body: dict, role: str | None, actor: str | None) -> list:
    authorize("fee-report:add", role)
    row = fetch_application_row(conn, app_id)
    if row["status"] != "ISSUED":
        raise ApiError(409, f"This application is {STATE_LABELS[row['status']]}; volume-fee reports are recorded on issued licences only.", "ILLEGAL_TRANSITION")
    quarter = req_str(body, "quarter", 10)
    if body.get("purchaseTotal") in (None, ""):
        raise ApiError(400, "Enter the quarter's total purchase price in dollars.", "VALIDATION")
    total = req_amount(body, "purchaseTotal")
    if conn.execute("SELECT 1 FROM quarterly_fee_reports WHERE application_id = ? AND quarter = ?", (app_id, quarter)).fetchone():
        raise ApiError(409, f"A report for {quarter} already exists on this licence.", "DUPLICATE_REPORT")
    insert(conn, "quarterly_fee_reports", {"application_id": app_id, "quarter": quarter, "purchase_total": str(total),
                                         "fee_due": str(harvest_fee(total)), "reported_at": now_iso()})
    audit(conn, "FEE_REPORT_ADDED", role, actor, application_id=app_id, reason=quarter)
    return fee_reports_vm(conn, app_id)


def svc_print(conn, app_id: int, body: dict, role: str | None, actor: str | None) -> dict:
    authorize("print", role)
    row = fetch_application_row(conn, app_id)
    if row["status"] != "ISSUED":
        raise ApiError(409, f"This application is {STATE_LABELS[row['status']]}; printing is available for issued licences only.", "ILLEGAL_TRANSITION")
    kind = body.get("kind")
    if kind == "certificate":
        audit(conn, "CERTIFICATE_PRINTED", role, actor, application_id=app_id)
        notice = "Certificate printed"
    elif kind == "agent-cards":
        conn.execute("UPDATE agent_assignments SET card_printed_at = ? WHERE application_id = ? AND removed_on IS NULL", (now_iso(), app_id))
        audit(conn, "AGENT_CARDS_PRINTED", role, actor, application_id=app_id)
        notice = "Agent cards printed"
    else:
        raise ApiError(400, "Choose what to print: the certificate or the agent cards.", "VALIDATION")
    return application_vm(conn, row, role, notice=notice)


def svc_set_suspension(conn, kind: str, record_id: int, body: dict, role: str | None, actor: str | None) -> dict:
    authorize("registry:suspend", role)
    if "suspended" not in body or not isinstance(body["suspended"], bool):
        raise ApiError(400, "State whether the record is suspended (true) or active (false).", "VALIDATION")
    flag = 1 if body["suspended"] else 0
    reason = req_str(body, "reason", 300, required=False)
    ts = now_iso()
    if kind == "buyer":
        fetch_buyer_row(conn, record_id)
        conn.execute("UPDATE commercial_buyers SET is_suspended = ?, updated_at = ? WHERE buyer_id = ?", (flag, ts, record_id))
        audit(conn, "SUSPENDED" if flag else "REINSTATED", role, actor, buyer_id=record_id, reason=reason)
        return buyer_vm(conn, fetch_buyer_row(conn, record_id), role)
    fetch_agent_row(conn, record_id)
    conn.execute("UPDATE field_agents SET is_suspended = ?, updated_at = ? WHERE agent_id = ?", (flag, ts, record_id))
    audit(conn, "SUSPENDED" if flag else "REINSTATED", role, actor, agent_id=record_id, reason=reason)
    return agent_vm(conn, fetch_agent_row(conn, record_id))


# ======================================================================================================
# handlers — HTTP
# ======================================================================================================
MIME = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".txt": "text/plain; charset=utf-8"}
ROUTES = [
    ("GET", re.compile(r"^/health$"), "health"),
    ("GET", re.compile(r"^/api/applications$"), "list_applications"),
    ("POST", re.compile(r"^/api/applications$"), "create_application"),
    ("GET", re.compile(r"^/api/applications/(\d+)$"), "get_application"),
    ("PUT", re.compile(r"^/api/applications/(\d+)$"), "update_draft"),
    ("POST", re.compile(r"^/api/applications/(\d+)/submit$"), "submit"),
    ("POST", re.compile(r"^/api/applications/(\d+)/issue$"), "issue"),
    ("POST", re.compile(r"^/api/applications/(\d+)/reject$"), "reject"),
    ("POST", re.compile(r"^/api/applications/(\d+)/agents$"), "add_agent"),
    ("DELETE", re.compile(r"^/api/applications/(\d+)/agents/(\d+)$"), "remove_agent"),
    ("POST", re.compile(r"^/api/applications/(\d+)/documents$"), "add_document"),
    ("POST", re.compile(r"^/api/applications/(\d+)/fee-reports$"), "add_fee_report"),
    ("POST", re.compile(r"^/api/applications/(\d+)/prints$"), "record_print"),
    ("GET", re.compile(r"^/api/buyers$"), "search_buyers"),
    ("GET", re.compile(r"^/api/buyers/duplicate-check$"), "duplicate_check"),
    ("POST", re.compile(r"^/api/buyers/(\d+)/suspension$"), "buyer_suspension"),
    ("GET", re.compile(r"^/api/agents$"), "search_agents"),
    ("POST", re.compile(r"^/api/agents/(\d+)/suspension$"), "agent_suspension"),
    ("POST", re.compile(r"^/api/calculations/bond$"), "calc_bond"),
    ("POST", re.compile(r"^/api/calculations/volume-fee$"), "calc_fee"),
]


class Handler(BaseHTTPRequestHandler):
    server_version = "BusinessLicensing/" + VERSION
    protocol_version = "HTTP/1.1"

    # ---- plumbing
    def log_message(self, fmt, *args):  # structured one-liner instead of the default access log
        pass

    def _send_json(self, status: int, payload) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Role, X-Actor")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            raise ApiError(400, "The request body is not valid JSON.", "BAD_JSON")
        if not isinstance(body, dict):
            raise ApiError(400, "The request body must be a JSON object.", "BAD_JSON")
        return body

    def _role(self) -> str | None:
        role = self.headers.get("X-Role")
        return role if role in ROLES else None

    def _actor(self) -> str | None:
        actor = (self.headers.get("X-Actor") or "").strip()
        return actor[:100] or None

    def do_OPTIONS(self):
        self._send_json(204, {})

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        t0 = time.time()
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        status = 500
        try:
            if method == "GET" and not path.startswith("/api/") and path != "/health":
                status = self._serve_static(path)
            else:
                status = self._api(method, path, urllib.parse.parse_qs(parsed.query))
        except ApiError as e:
            status = e.status
            self._send_json(e.status, {"message": e.message, "code": e.code})
        except Exception:  # never leak a stack trace
            sys.stderr.write(traceback.format_exc())
            status = 500
            self._send_json(500, {"message": "Something went wrong on our side. Please try again.", "code": "INTERNAL"})
        finally:
            print(f"{method} {path} {status} {int((time.time() - t0) * 1000)}ms role={self._role() or '-'}", flush=True)

    def _serve_static(self, path: str) -> int:
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (UI_DIR / rel).resolve()
        if UI_DIR.resolve() not in target.parents or not target.is_file():
            raise ApiError(404, "That page does not exist.", "NOT_FOUND")
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(target.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)
        return 200

    def _api(self, method: str, path: str, query: dict) -> int:
        for m, rx, name in ROUTES:
            match = rx.match(path)
            if match and m == method:
                body = self._read_json() if method in ("POST", "PUT") else {}
                conn = connect()
                try:
                    code, payload = getattr(self, "h_" + name)(conn, body, query, self._role(), self._actor(), *[int(g) for g in match.groups()])
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    conn.close()
                self._send_json(code, payload)
                return code
        if any(rx.match(path) for _m, rx, _n in ROUTES):
            raise ApiError(405, "That operation is not available for this address.", "METHOD_NOT_ALLOWED")
        raise ApiError(404, "That address does not exist.", "NOT_FOUND")

    # ---- operations (operationId order of the OpenAPI contract)
    def h_health(self, conn, body, query, role, actor):
        conn.execute("SELECT 1").fetchone()
        tables = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0]
        return 200, {"status": "ok", "database": "ok" if tables >= 7 else "incomplete", "version": VERSION}

    def h_list_applications(self, conn, body, query, role, actor):
        if role == ROLE_STAFF:
            status = (query.get("status") or [None])[0]
            if status and status not in STATE_LABELS:
                raise ApiError(400, "Choose a status from the list.", "VALIDATION")
            rows = conn.execute("SELECT * FROM license_applications" + (" WHERE status = ?" if status else "") + " ORDER BY submitted_at IS NULL, submitted_at, application_id",
                                (status,) if status else ()).fetchall()
            return 200, [summary_vm(conn, r) for r in rows]
        authorize("application:read-own", role)
        ids = [int(x) for x in re.findall(r"\d+", (query.get("ids") or [""])[0])][:50]
        if not ids:
            return 200, []
        rows = conn.execute(f"SELECT * FROM license_applications WHERE application_id IN ({','.join('?' * len(ids))}) ORDER BY application_id", ids).fetchall()
        return 200, [summary_vm(conn, r) for r in rows]

    def h_create_application(self, conn, body, query, role, actor):
        return 201, svc_create_application(conn, body, role, actor)

    def h_get_application(self, conn, body, query, role, actor, app_id):
        if role == ROLE_STAFF:
            authorize("application:read-all", role)
        else:
            authorize("application:read-own", role)
        return 200, application_vm(conn, fetch_application_row(conn, app_id), role)

    def h_update_draft(self, conn, body, query, role, actor, app_id):
        return 200, svc_update_draft(conn, app_id, body, role, actor)

    def h_submit(self, conn, body, query, role, actor, app_id):
        return 200, svc_transition(conn, app_id, "SUBMIT", body, role, actor)

    def h_issue(self, conn, body, query, role, actor, app_id):
        return 200, svc_transition(conn, app_id, "ISSUE", body, role, actor)

    def h_reject(self, conn, body, query, role, actor, app_id):
        return 200, svc_transition(conn, app_id, "REJECT", body, role, actor)

    def h_add_agent(self, conn, body, query, role, actor, app_id):
        return svc_add_agent(conn, app_id, body, role, actor)

    def h_remove_agent(self, conn, body, query, role, actor, app_id, agent_id):
        return 200, svc_remove_agent(conn, app_id, agent_id, role, actor)

    def h_add_document(self, conn, body, query, role, actor, app_id):
        return 201, svc_add_document(conn, app_id, body, role, actor)

    def h_add_fee_report(self, conn, body, query, role, actor, app_id):
        return 201, svc_add_fee_report(conn, app_id, body, role, actor)

    def h_record_print(self, conn, body, query, role, actor, app_id):
        return 200, svc_print(conn, app_id, body, role, actor)

    def h_search_buyers(self, conn, body, query, role, actor):
        authorize("registry:read", role)
        q = (query.get("q") or [""])[0].strip()
        if re.fullmatch(r"[\d\- ]{9,}", q):  # identifiers are never searchable (REQ-SEC-03)
            return 200, []
        like = f"%{q.lower()}%"
        rows = conn.execute("SELECT * FROM commercial_buyers WHERE lower(legal_name) LIKE ? OR lower(business_name) LIKE ? OR lower(city) LIKE ? OR lower(email) LIKE ? "
                            "ORDER BY is_suspended DESC, under_investigation DESC, legal_name LIMIT 100", (like, like, like, like)).fetchall()
        return 200, [buyer_vm(conn, r, role) for r in rows]

    def h_duplicate_check(self, conn, body, query, role, actor):
        legal = (query.get("legalName") or [""])[0].strip()
        dob = (query.get("dateOfBirth") or [""])[0].strip()
        if not legal or not DATE_RE.match(dob):
            raise ApiError(400, "Provide the legal name and the date of birth to check for duplicates.", "VALIDATION")
        _first, last = split_name(legal)
        row = conn.execute("SELECT 1 FROM commercial_buyers WHERE date_of_birth = ? AND (lower(legal_name) = lower(?) OR lower(legal_name) LIKE lower(?)) LIMIT 1",
                           (dob, legal, f"% {last}")).fetchone()
        if not row:
            row = conn.execute("SELECT 1 FROM field_agents WHERE date_of_birth = ? AND lower(last_name) = lower(?) LIMIT 1", (dob, last)).fetchone()
        dup = bool(row)
        return 200, {"possibleDuplicate": dup, "notice": "A record with the same last name and date of birth already exists" if dup else ""}

    def h_buyer_suspension(self, conn, body, query, role, actor, buyer_id):
        return 200, svc_set_suspension(conn, "buyer", buyer_id, body, role, actor)

    def h_search_agents(self, conn, body, query, role, actor):
        authorize("registry:read", role)
        q = (query.get("q") or [""])[0].strip()
        like = f"%{q.lower()}%"
        rows = conn.execute("SELECT * FROM field_agents WHERE lower(last_name) LIKE ? OR lower(first_name) LIKE ? OR date_of_birth = ? "
                            "ORDER BY is_suspended DESC, last_name, first_name LIMIT 100", (like, like, q)).fetchall()
        return 200, [agent_vm(conn, r) for r in rows]

    def h_agent_suspension(self, conn, body, query, role, actor, agent_id):
        return 200, svc_set_suspension(conn, "agent", agent_id, body, role, actor)

    def h_calc_bond(self, conn, body, query, role, actor):
        prior = req_amount(body, "priorYearPurchases")
        bond = req_amount(body, "bondAmount", required=False)
        req = required_bond(prior)
        short = bond_shortfall(prior, bond) if bond is not None else None
        msg = ("Bond is sufficient" if short == 0 else shortfall_message(prior, bond)) if bond is not None else f"Required bond: {fmt_money(req)}"
        return 200, {"requiredBondAmount": float(req), "shortfall": float(short) if short is not None else None, "message": msg}

    def h_calc_fee(self, conn, body, query, role, actor):
        total = req_amount(body, "purchaseTotal")
        return 200, {"feeDue": float(harvest_fee(total))}


# ======================================================================================================
# self-test (commands.test)
# ======================================================================================================
def self_test() -> int:
    assert required_bond(0) == Decimal("1000.00")
    assert required_bond("9999.99") == Decimal("1000.00")
    assert required_bond("10000.00") == Decimal("1000.00")
    assert required_bond("10000.10") == Decimal("1000.01")
    assert required_bond(25000) == Decimal("2500.00")
    assert required_bond(250000) == Decimal("25000.00")
    assert bond_shortfall(25000, "2499.99") == Decimal("0.01")
    assert harvest_fee(12500) == Decimal("500.00")
    assert harvest_fee("0.13") == Decimal("0.01")
    assert harvest_fee("0.10") == Decimal("0.00")
    assert allowed_triggers("DRAFT", ROLE_BUYER) == ["SUBMIT"]
    assert allowed_triggers("SUBMITTED", ROLE_STAFF) == ["ISSUE", "REJECT"]
    assert allowed_triggers("SUBMITTED", ROLE_BUYER) == []
    for st in STATE_LABELS:
        for trig in TRIGGER_LABELS:
            legal = trigger_target(st, trig) is not None
            try:
                check_transition(st, trig, ROLE_STAFF if trig != "SUBMIT" else ROLE_BUYER)
                assert legal
            except ApiError as e:
                assert not legal and e.status == 409
    try:
        check_transition("SUBMITTED", "ISSUE", ROLE_BUYER)
        raise AssertionError("buyer must not issue")
    except ApiError as e:
        assert e.status == 403
    # the backend table must mirror the spec index when it is available
    idx = SRC.parent / "specs" / ".spec_index.json"
    if idx.exists():
        spec = json.loads(idx.read_text(encoding="utf-8"))
        spec_rows = {(t["from"], t["trigger"].upper(), t["to"]) for t in spec.get("transitions", [])}
        assert spec_rows == {(s, t, d) for s, t, d, _r in STATE_TABLE}, "STATE_TABLE differs from spec §3.3"
    print("self-test: rules BR-01/BR-03, state table and role guards OK")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    init_db()
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    httpd.daemon_threads = True
    print(f"Commercial Buyer Licensing backend listening on http://127.0.0.1:{PORT}/ (database {DB_PATH}, reset={RESET_ON_START})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
