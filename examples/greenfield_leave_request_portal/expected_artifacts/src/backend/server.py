#!/usr/bin/env python3
"""Employee Leave & Exception Request Portal — single-process server (Python standard library only).

Serves the single-page UI (src/ui), the JSON API (/api/*), GET /health and a local stand-in for the external
payroll REST interface (POST /payroll/leave-postings) on one port.

    python3 src/backend/server.py            # demo mode (default): fixed clock 2031-03-02, seeded data, DB recreated
    python3 src/backend/server.py --no-demo  # real clock, persistent empty database (PORTAL_DB_PATH)

Environment: PORT (8766) · PORTAL_DB_PATH · PAYROLL_BASE_URL (default: this server) · PAYROLL_STUB_OUTAGE=1
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import repositories as repos  # noqa: E402
import viewmodel as vm  # noqa: E402
import workflow as wf  # noqa: E402

HERE = Path(__file__).resolve().parent
UI_DIR = HERE.parent / "ui"
DEMO_TODAY = dt.date(2031, 3, 2)
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon"}


# ------------------------------------------------------------------------------------------ identity adapter
class IdentityAdapter:
    """Resolves the signed-in Actor. Pretotype: X-Actor-Role / X-Actor-Ref headers. Production: OIDC token
    validation implementing the same `resolve(headers) -> Actor | None` contract."""

    def __init__(self, repo: repos.Repository):
        self.repo = repo

    def resolve(self, headers) -> wf.Actor | None:
        role = (headers.get("X-Actor-Role") or "").strip()
        ref = (headers.get("X-Actor-Ref") or "").strip()
        if role not in wf.ROLES or not ref:
            return None
        emp = self.repo.get_employee(ref)
        if not emp:
            return None
        expected_group = {wf.EMPLOYEE: "employees", wf.MANAGER: "managers", wf.HR_CERTIFIER: "hr-certifiers", wf.PAYROLL: "system"}[role]
        if emp["role_group"] != expected_group:
            return None
        return wf.Actor(role, ref, emp["display_name"])


# ------------------------------------------------------------------------------------------ payroll client
class PayrollClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def post(self, row: dict[str, Any]) -> tuple[bool, int | None, str | None]:
        body = json.dumps({"requestReference": row["request_ref"], "employeeReference": row["employee_ref"], "leaveType": row["leave_type"],
                           "startDate": row["start_date"], "endDate": row["end_date"], "hours": row["requested_hours"]}).encode()
        req = urllib.request.Request(self.base_url + "/payroll/leave-postings", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = resp.status
                data = json.loads(resp.read().decode() or "{}")
                return 200 <= status < 300, status, data.get("payrollReference")
        except urllib.error.HTTPError as e:
            return False, e.code, None
        except Exception:
            return False, None, None


# ------------------------------------------------------------------------------------------ HTTP layer
class App:
    def __init__(self, repo: repos.Repository, clock, payroll_base: str, stub_outage: bool):
        self.repo = repo
        self.clock = clock
        self.identity = IdentityAdapter(repo)
        self.payroll = PayrollClient(payroll_base)
        self.wf = wf.WorkflowService(repo, self.payroll, clock)
        self.stub_outage = stub_outage
        # One SQLite connection is shared by the request threads: serialise every API request that touches it.
        # The payroll stub path never takes the lock, so the synchronous self-call from the approval flow cannot deadlock.
        self.db_lock = threading.Lock()

    # ---- helpers
    def _view(self, actor: wf.Actor, row: dict[str, Any]) -> dict[str, Any]:
        return vm.request_view(row, self.wf.allowed_actions(actor, row), self.repo.last_posting(row["request_ref"]))

    def _require(self, actor: wf.Actor | None) -> wf.Actor:
        if actor is None:
            raise wf.WorkflowError(401, "UNAUTHENTICATED", "Sign in to use the leave portal.")
        return actor

    def _readable(self, actor: wf.Actor, reference: str) -> dict[str, Any]:
        row = self.repo.get_request(reference)
        if not row:
            raise wf.WorkflowError(404, "NOT_FOUND", f"We could not find request {reference}.")
        if not self.wf.can_read(actor, row):
            raise wf.WorkflowError(403, "ROLE_NOT_ALLOWED", "You can only view your own requests.")
        return row

    # ---- routing
    def handle(self, method: str, path: str, headers, body: Any) -> tuple[int, Any]:
        if path == "/payroll/leave-postings":
            return self.payroll_stub(method, body)
        with self.db_lock:
            return self._handle_api(method, path, headers, body)

    def _handle_api(self, method: str, path: str, headers, body: Any) -> tuple[int, Any]:
        if path == "/health" and method == "GET":
            return 200, {"status": "ok", "database": "ready" if self.repo.ready() else "down", "today": self.clock().isoformat()}
        if not path.startswith("/api/"):
            raise wf.WorkflowError(404, "NOT_FOUND", "There is nothing at this address.")
        actor = self.identity.resolve(headers)
        parts = [p for p in path.split("/") if p][1:]  # after 'api'
        if parts == ["me"] and method == "GET":
            a = self._require(actor)
            return 200, vm.actor_view(self.repo.get_employee(a.ref), a.role)
        if parts == ["balance"] and method == "GET":
            a = self._require(actor)
            if a.role != wf.EMPLOYEE:
                raise wf.WorkflowError(403, "ROLE_NOT_ALLOWED", "Balances are shown to employees only.")
            return 200, vm.balance_view(self.wf.balance(a.ref), self.clock())
        if parts == ["requests"]:
            a = self._require(actor)
            if method == "GET":
                if a.role != wf.EMPLOYEE:
                    raise wf.WorkflowError(403, "ROLE_NOT_ALLOWED", "Only employees have a request history; use your queue instead.")
                return 200, [self._view(a, r) for r in self.repo.list_requests(a.ref)]
            if method == "POST":
                ref = self.wf.create(a, body)
                return 201, self._view(a, self.repo.get_request(ref))
        if len(parts) >= 2 and parts[0] == "requests":
            a = self._require(actor)
            ref = parts[1]
            if len(parts) == 2:
                if method == "GET":
                    return 200, self._view(a, self._readable(a, ref))
                if method == "PUT":
                    self.wf.update(a, ref, body)
                    return 200, self._view(a, self.repo.get_request(ref))
            elif len(parts) == 3:
                sub = parts[2]
                if sub == "audit":
                    if method != "GET":
                        raise wf.WorkflowError(405, "VALIDATION", "Audit records are append-only and cannot be changed.")
                    row = self._readable(a, ref)
                    return 200, vm.audit_view(self.repo.audit_entries(ref), show_actor=(a.role != wf.EMPLOYEE))
                triggers = {"submit": "Submit", "withdraw": "Withdraw", "approve": "Manager Approve", "return": "Return", "certify": "Certify"}
                if sub in triggers and method == "POST":
                    self.wf.apply(a, ref, triggers[sub], body if isinstance(body, dict) else {})
                    return 200, self._view(a, self.repo.get_request(ref))
        if parts == ["queues", "manager"] and method == "GET":
            a = self._require(actor)
            if a.role != wf.MANAGER:
                raise wf.WorkflowError(403, "ROLE_NOT_ALLOWED", "The manager queue is available to managers only.")
            return 200, [self._view(a, r) for r in self.repo.manager_queue(a.ref)]
        if parts == ["queues", "certification"] and method == "GET":
            a = self._require(actor)
            if a.role != wf.HR_CERTIFIER:
                raise wf.WorkflowError(403, "ROLE_NOT_ALLOWED", "The certification queue is available to HR Certifiers only.")
            return 200, [self._view(a, r) for r in self.repo.certification_queue(wf.CERTIFICATION_THRESHOLD_HOURS)]
        if parts == ["payroll-postings"] and method == "GET":
            a = self._require(actor)
            if a.role != wf.PAYROLL:
                raise wf.WorkflowError(403, "ROLE_NOT_ALLOWED", "Payroll postings are visible to the Payroll Integration only.")
            return 200, [vm.posting_view(p, p["status"]) for p in self.repo.list_postings()]
        raise wf.WorkflowError(404, "NOT_FOUND", "There is nothing at this address.")

    # ---- local stand-in for the external payroll REST interface (BRD §8)
    def payroll_stub(self, method: str, body: Any) -> tuple[int, Any]:
        if method != "POST":
            raise wf.WorkflowError(405, "VALIDATION", "Use POST to send a leave posting.")
        if self.stub_outage or os.environ.get("PAYROLL_STUB_OUTAGE") == "1":
            return 503, {"code": "UNAVAILABLE", "message": "Payroll is temporarily unavailable."}
        required = ("requestReference", "employeeReference", "leaveType", "startDate", "endDate", "hours")
        if not isinstance(body, dict) or any(k not in body for k in required):
            raise wf.WorkflowError(400, "VALIDATION", "A leave posting needs requestReference, employeeReference, leaveType, startDate, endDate and hours.")
        return 201, {"payrollReference": "PAY-" + uuid.uuid4().hex[:6].upper()}


class Handler(BaseHTTPRequestHandler):
    app: App = None  # type: ignore[assignment]
    server_version = "LeavePortal/1.0"

    def log_message(self, fmt, *args):  # structured one-line log
        sys.stdout.write(json.dumps({"ts": repos.now_iso(), "method": self.command, "path": self.path, "msg": fmt % args}) + "\n")
        sys.stdout.flush()

    # ---- static UI
    def _serve_static(self) -> None:
        rel = self.path.split("?", 1)[0]
        rel = "index.html" if rel in ("/", "") else rel.lstrip("/")
        p = (UI_DIR / rel).resolve()
        if not str(p).startswith(str(UI_DIR.resolve())) or not p.is_file():
            self._json(404, {"code": "NOT_FOUND", "message": "There is nothing at this address."})
            return
        data = p.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(p.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Actor-Role, X-Actor-Ref")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")

    def _json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, method: str) -> None:
        path = self.path.split("?", 1)[0]
        if method == "GET" and not path.startswith("/api/") and path not in ("/health", "/payroll/leave-postings"):
            self._serve_static()
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        body: Any = None
        if raw:
            try:
                body = json.loads(raw.decode("utf-8"))
            except ValueError:
                self._json(400, {"code": "VALIDATION", "message": "The request body must be valid JSON."})
                return
        try:
            status, payload = self.app.handle(method, path, self.headers, body)
            self._json(status, payload)
        except wf.WorkflowError as e:
            err = {"code": e.code, "message": e.message}
            if e.field:
                err["field"] = e.field
            self._json(e.status, err)
        except Exception as e:  # pragma: no cover
            cid = uuid.uuid4().hex[:8]
            sys.stdout.write(json.dumps({"ts": repos.now_iso(), "level": "error", "correlationId": cid, "error": repr(e)}) + "\n")
            self._json(500, {"code": "INTERNAL", "message": f"Something went wrong on our side (reference {cid}). Please try again."})

    def do_GET(self):  # noqa: N802
        self._dispatch("GET")

    def do_POST(self):  # noqa: N802
        self._dispatch("POST")

    def do_PUT(self):  # noqa: N802
        self._dispatch("PUT")

    def do_DELETE(self):  # noqa: N802
        self._dispatch("DELETE")

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8766")))
    ap.add_argument("--no-demo", action="store_true", help="Real clock, no seed data, keep the existing database file")
    ap.add_argument("--db", default=os.environ.get("PORTAL_DB_PATH") or os.path.join(tempfile.gettempdir(), "leave_portal.sqlite"),
                    help="SQLite file (default: PORTAL_DB_PATH or <tmp>/leave_portal.sqlite; demo mode recreates it on start)")
    args = ap.parse_args()
    demo = not args.no_demo
    repo = repos.Repository(args.db, reset=demo)
    if demo:
        repos.seed_demo(repo)
    clock = (lambda: DEMO_TODAY) if demo else (lambda: dt.date.today())
    payroll_base = os.environ.get("PAYROLL_BASE_URL") or f"http://127.0.0.1:{args.port}"
    Handler.app = App(repo, clock, payroll_base, os.environ.get("PAYROLL_STUB_OUTAGE") == "1")
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    httpd.daemon_threads = True
    sys.stdout.write(json.dumps({"ts": repos.now_iso(), "msg": f"leave portal listening on http://127.0.0.1:{args.port}/ (demo={demo}, today={clock().isoformat()})"}) + "\n")
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
