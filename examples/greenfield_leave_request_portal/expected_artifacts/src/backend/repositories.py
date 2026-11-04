"""Repositories (sqlite3) — the only module that speaks SQL. Creates the database from src/db/schema.sql and
seeds the demo identities / fixtures documented in src/README.md."""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SCHEMA = HERE.parent / "db" / "schema.sql"

STATUS_LABEL = {"DRAFT": "Draft", "SUBMITTED": "Submitted", "MANAGER_APPROVED": "Manager approved",
                "APPROVED": "Approved", "POSTED": "Posted to payroll", "WITHDRAWN": "Withdrawn"}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Repository:
    def __init__(self, path: str, reset: bool):
        if reset and path != ":memory:" and os.path.exists(path):
            os.remove(path)
        fresh = path == ":memory:" or not os.path.exists(path)
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if fresh:
            self.conn.executescript(SCHEMA.read_text(encoding="utf-8"))
            self.conn.executemany("INSERT INTO leave_type(leave_type_code, label, requires_certification, exempt_from_lead_time) VALUES (?,?,?,?)",
                                  [("vacation", "Vacation", 0, 0), ("sick", "Sick", 0, 0), ("exception", "Exception", 1, 1)])

    # ---- generic
    def label(self, status: str) -> str:
        return STATUS_LABEL.get(status, status.title())

    def ready(self) -> bool:
        try:
            self.conn.execute("SELECT 1 FROM leave_type LIMIT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    def _tx(self):
        return self.conn

    # ---- employees
    def get_employee(self, ref: str) -> dict[str, Any] | None:
        r = self.conn.execute("SELECT * FROM employee WHERE employee_ref = ?", (ref,)).fetchone()
        return dict(r) if r else None

    def get_balance(self, ref: str) -> dict[str, Any]:
        r = self.conn.execute("SELECT * FROM leave_balance WHERE employee_ref = ?", (ref,)).fetchone()
        return dict(r) if r else {"employee_ref": ref, "accrued_hours": 0.0, "taken_hours": 0.0}

    def pending_hours(self, ref: str, states: tuple[str, ...]) -> float:
        q = f"SELECT COALESCE(SUM(requested_hours), 0) AS h FROM leave_request WHERE employee_ref = ? AND status IN ({','.join('?' * len(states))})"
        return float(self.conn.execute(q, (ref, *states)).fetchone()["h"])

    # ---- requests
    _SELECT = """SELECT r.*, t.label AS leave_type, e.display_name AS employee_name, e.manager_ref AS manager_ref,
                        (SELECT c.comment_text FROM review_comment c WHERE c.request_ref = r.request_ref ORDER BY c.comment_id DESC LIMIT 1) AS last_comment,
                        (SELECT c.author_role FROM review_comment c WHERE c.request_ref = r.request_ref ORDER BY c.comment_id DESC LIMIT 1) AS last_comment_role
                 FROM leave_request r JOIN leave_type t ON t.leave_type_code = r.leave_type_code JOIN employee e ON e.employee_ref = r.employee_ref"""

    def get_request(self, reference: str) -> dict[str, Any] | None:
        r = self.conn.execute(self._SELECT + " WHERE r.request_ref = ?", (reference,)).fetchone()
        return dict(r) if r else None

    def list_requests(self, employee_ref: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(self._SELECT + " WHERE r.employee_ref = ? ORDER BY r.request_ref DESC", (employee_ref,))]

    def other_requests(self, employee_ref: str, exclude_ref: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM leave_request WHERE employee_ref = ? AND request_ref <> ?", (employee_ref, exclude_ref))]

    def manager_queue(self, manager_ref: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(self._SELECT + " WHERE r.status = 'SUBMITTED' AND e.manager_ref = ? ORDER BY r.submitted_at, r.request_ref", (manager_ref,))]

    def certification_queue(self, threshold: float) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            self._SELECT + " WHERE r.status = 'MANAGER_APPROVED' AND (r.requested_hours > ? OR t.requires_certification = 1) ORDER BY r.submitted_at, r.request_ref", (threshold,))]

    def next_reference(self) -> str:
        r = self.conn.execute("SELECT MAX(CAST(substr(request_ref, 4) AS INTEGER)) AS n FROM leave_request").fetchone()
        return f"LR-{(r['n'] or 1000) + 1:04d}"

    def create_request(self, employee_ref: str, f: dict[str, Any], today: dt.date) -> str:
        ref = self.next_reference()
        ts = now_iso()
        self.conn.execute("INSERT INTO leave_request(request_ref, employee_ref, leave_type_code, start_date, end_date, requested_hours, reason, status, created_at, updated_at) "
                          "VALUES (?,?,?,?,?,?,?,'DRAFT',?,?)",
                          (ref, employee_ref, f["leave_type_code"], f["start_date"], f["end_date"], f["requested_hours"], f["reason"], ts, ts))
        return ref

    def update_request(self, ref: str, f: dict[str, Any]) -> None:
        self.conn.execute("UPDATE leave_request SET leave_type_code=?, start_date=?, end_date=?, requested_hours=?, reason=?, updated_at=? WHERE request_ref=?",
                          (f["leave_type_code"], f["start_date"], f["end_date"], f["requested_hours"], f["reason"], now_iso(), ref))

    def set_status(self, ref: str, status: str, submitted: bool = False) -> None:
        ts = now_iso()
        if submitted:
            self.conn.execute("UPDATE leave_request SET status=?, updated_at=?, submitted_at=? WHERE request_ref=?", (status, ts, ts, ref))
        else:
            self.conn.execute("UPDATE leave_request SET status=?, updated_at=? WHERE request_ref=?", (status, ts, ref))

    def add_comment(self, ref: str, actor, comment: str) -> None:
        self.conn.execute("INSERT INTO review_comment(request_ref, author_ref, author_role, comment_text, created_at) VALUES (?,?,?,?,?)",
                          (ref, actor.ref, actor.role, comment, now_iso()))

    # ---- audit (append-only: no update/delete methods exist)
    def audit(self, ref: str, actor, trigger: str, prev: str, new: str, outcome: str, detail: str | None) -> None:
        self.conn.execute("INSERT INTO request_state_change(request_ref, actor_ref, actor_role, trigger_name, previous_status, new_status, outcome, detail, changed_at) "
                          "VALUES (?,?,?,?,?,?,?,?,?)", (ref, actor.ref, actor.role, trigger, prev, new, outcome, detail, now_iso()))

    def audit_entries(self, ref: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            "SELECT s.*, COALESCE(e.display_name, s.actor_ref) AS actor_name FROM request_state_change s LEFT JOIN employee e ON e.employee_ref = s.actor_ref "
            "WHERE s.request_ref = ? ORDER BY s.change_id", (ref,))]

    # ---- payroll postings
    def record_posting(self, ref: str, outcome: str, http_status: int | None, payroll_reference: str | None) -> None:
        self.conn.execute("INSERT INTO payroll_posting(request_ref, outcome, http_status, payroll_reference, attempted_at) VALUES (?,?,?,?,?)",
                          (ref, outcome, http_status, payroll_reference, now_iso()))

    def last_posting(self, ref: str) -> dict[str, Any] | None:
        r = self.conn.execute("SELECT * FROM payroll_posting WHERE request_ref = ? ORDER BY posting_id DESC LIMIT 1", (ref,)).fetchone()
        return dict(r) if r else None

    def list_postings(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            "SELECT p.*, r.status FROM payroll_posting p JOIN leave_request r ON r.request_ref = p.request_ref ORDER BY p.posting_id DESC")]


# ------------------------------------------------------------------------------------------------ demo seed
def seed_demo(repo: Repository) -> None:
    c = repo.conn
    if c.execute("SELECT COUNT(*) AS n FROM employee").fetchone()["n"]:
        return
    emps = [("EMP-20001", "Morgan Lee", "managers", None), ("EMP-20002", "Casey Ortiz", "managers", None),
            ("EMP-30001", "Priya Nair", "hr-certifiers", None), ("SYS-PAYROLL", "Payroll Integration", "system", None),
            ("EMP-10042", "Alex Rivera", "employees", "EMP-20001"), ("EMP-10077", "Sam Chen", "employees", "EMP-20001"),
            ("EMP-10105", "Jordan Blake", "employees", "EMP-20002")]
    c.executemany("INSERT INTO employee(employee_ref, display_name, role_group, manager_ref) VALUES (?,?,?,?)", emps)
    c.executemany("INSERT INTO leave_balance(employee_ref, accrued_hours, taken_hours) VALUES (?,?,?)",
                  [("EMP-10042", 600, 40), ("EMP-10077", 40, 0), ("EMP-10105", 200, 0)])
    ts = "2031-02-20T09:00:00Z"
    reqs = [  # ref, employee, type, start, end, hours, status
        ("LR-1001", "EMP-10042", "vacation", "2031-06-09", "2031-06-13", 40, "POSTED"),
        ("LR-1002", "EMP-10042", "vacation", "2031-07-07", "2031-07-08", 16, "APPROVED"),
        ("LR-1003", "EMP-10105", "vacation", "2031-05-19", "2031-05-20", 16, "SUBMITTED"),
        ("LR-1004", "EMP-10105", "exception", "2031-04-01", "2031-04-01", 8, "MANAGER_APPROVED"),
        ("LR-1005", "EMP-10105", "vacation", "2031-12-01", "2031-12-02", 8, "DRAFT"),
        ("LR-1006", "EMP-10042", "vacation", "2031-05-12", "2031-05-12", 8, "SUBMITTED"),
        ("LR-1007", "EMP-10105", "vacation", "2031-12-08", "2031-12-09", 8, "DRAFT"),
        ("LR-1008", "EMP-10105", "vacation", "2031-12-15", "2031-12-16", 8, "SUBMITTED"),
        ("LR-1009", "EMP-10105", "vacation", "2032-02-02", "2032-02-03", 8, "DRAFT"),
    ]
    for ref, emp, lt, s, e, h, st in reqs:
        c.execute("INSERT INTO leave_request(request_ref, employee_ref, leave_type_code, start_date, end_date, requested_hours, reason, status, created_at, updated_at, submitted_at) "
                  "VALUES (?,?,?,?,?,?,NULL,?,?,?,?)", (ref, emp, lt, s, e, h, st, ts, ts, None if st == "DRAFT" else ts))
    chain = {"DRAFT": [], "SUBMITTED": [("Submit", "DRAFT", "SUBMITTED")],
             "MANAGER_APPROVED": [("Submit", "DRAFT", "SUBMITTED"), ("Manager Approve", "SUBMITTED", "MANAGER_APPROVED")],
             "APPROVED": [("Submit", "DRAFT", "SUBMITTED"), ("Manager Approve", "SUBMITTED", "APPROVED")],
             "POSTED": [("Submit", "DRAFT", "SUBMITTED"), ("Manager Approve", "SUBMITTED", "APPROVED"), ("Post", "APPROVED", "POSTED")]}
    actor_for = {"Submit": None, "Manager Approve": "manager", "Post": ("SYS-PAYROLL", "Payroll Integration")}
    for ref, emp, lt, s, e, h, st in reqs:
        mgr = dict(repo.get_employee(emp) or {}).get("manager_ref")
        c.execute("INSERT INTO request_state_change(request_ref, actor_ref, actor_role, trigger_name, previous_status, new_status, outcome, detail, changed_at) VALUES (?,?,?,?,?,?,?,?,?)",
                  (ref, emp, "Employee", "Create", "—", "DRAFT", "applied", None, ts))
        for trig, p, n in chain[st]:
            if trig == "Submit":
                a_ref, a_role = emp, "Employee"
            elif trig == "Manager Approve":
                a_ref, a_role = mgr, "Manager"
            else:
                a_ref, a_role = "SYS-PAYROLL", "Payroll Integration"
            detail = "PAY-88121" if trig == "Post" else None
            c.execute("INSERT INTO request_state_change(request_ref, actor_ref, actor_role, trigger_name, previous_status, new_status, outcome, detail, changed_at) VALUES (?,?,?,?,?,?,?,?,?)",
                      (ref, a_ref, a_role, trig, p, n, "applied", detail, ts))
    c.execute("INSERT INTO payroll_posting(request_ref, outcome, http_status, payroll_reference, attempted_at) VALUES ('LR-1001','accepted',201,'PAY-88121',?)", (ts,))
    c.execute("INSERT INTO payroll_posting(request_ref, outcome, http_status, payroll_reference, attempted_at) VALUES ('LR-1002','failed',503,NULL,?)", (ts,))
    c.execute("INSERT INTO request_state_change(request_ref, actor_ref, actor_role, trigger_name, previous_status, new_status, outcome, detail, changed_at) VALUES "
              "('LR-1002','SYS-PAYROLL','Payroll Integration','Post','APPROVED','APPROVED','denied','Payroll posting failed (HTTP 503); alert raised',?)", (ts,))
