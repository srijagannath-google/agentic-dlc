"""Workflow service — the spec §3.3 transition table encoded once as data, plus the business rules BR-01…BR-07.

Nothing in here knows about HTTP. The HTTP layer (server.py) maps WorkflowError → status code + {code, message}.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

# --------------------------------------------------------------------------- roles & states (spec §3.3 / §3.5)
EMPLOYEE, MANAGER, HR_CERTIFIER, PAYROLL = "Employee", "Manager", "HR Certifier", "Payroll Integration"
ROLES = (EMPLOYEE, MANAGER, HR_CERTIFIER, PAYROLL)
EXTERNAL_ROLES = {EMPLOYEE}

DRAFT, SUBMITTED, MANAGER_APPROVED, APPROVED, POSTED, WITHDRAWN = (
    "DRAFT", "SUBMITTED", "MANAGER_APPROVED", "APPROVED", "POSTED", "WITHDRAWN")
STATES = (DRAFT, SUBMITTED, MANAGER_APPROVED, APPROVED, POSTED, WITHDRAWN)

# Trigger names exactly as in spec §3.3; API action names used by the UI / OpenAPI `allowedActions`.
TRIGGER_ACTION = {"Submit": "submit", "Withdraw": "withdraw", "Manager Approve": "approve", "Return": "return",
                  "Certify": "certify", "Post": "post"}

# (from, to, trigger, role, guard-name). The guard names are resolved in WorkflowService.
TRANSITIONS: list[tuple[str, str, str, str, str]] = [
    (DRAFT, SUBMITTED, "Submit", EMPLOYEE, "own+BR-01+BR-03+BR-04"),
    (SUBMITTED, MANAGER_APPROVED, "Manager Approve", MANAGER, "direct-report+BR-02"),
    (SUBMITTED, APPROVED, "Manager Approve", MANAGER, "direct-report+not-BR-02"),
    (SUBMITTED, DRAFT, "Return", MANAGER, "direct-report+BR-07"),
    (MANAGER_APPROVED, APPROVED, "Certify", HR_CERTIFIER, "BR-02"),
    (MANAGER_APPROVED, DRAFT, "Return", HR_CERTIFIER, "BR-07"),
    (APPROVED, POSTED, "Post", PAYROLL, "payroll-accepted"),
    (DRAFT, WITHDRAWN, "Withdraw", EMPLOYEE, "own+BR-05"),
    (SUBMITTED, WITHDRAWN, "Withdraw", EMPLOYEE, "own+BR-05"),
    (MANAGER_APPROVED, WITHDRAWN, "Withdraw", EMPLOYEE, "own+BR-05"),
]
ROLE_TRIGGERS = {r: sorted({t[2] for t in TRANSITIONS if t[3] == r}) for r in ROLES}
ROLE_TRIGGERS[EMPLOYEE] = ["Create"] + ROLE_TRIGGERS[EMPLOYEE]

LEAD_TIME_DAYS = 3                 # BR-03
CERTIFICATION_THRESHOLD_HOURS = 40  # BR-02
REASON_MAX = 500                   # BR-06
PENDING_STATES = (SUBMITTED, MANAGER_APPROVED, APPROVED, POSTED)  # BR-01 pending (ASSUMPTION-09)
WITHDRAWABLE = (DRAFT, SUBMITTED, MANAGER_APPROVED)  # BR-05
LEAVE_TYPES = {"Vacation": "vacation", "Sick": "sick", "Exception": "exception"}


class WorkflowError(Exception):
    def __init__(self, status: int, code: str, message: str, field: str | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.field = status, code, message, field


@dataclass
class Actor:
    role: str
    ref: str
    display_name: str


# --------------------------------------------------------------------------- pure rules (unit-tested)
def fmt_hours(h: float) -> str:
    return f"{h:g}"


def requires_certification(hours: float, leave_type: str) -> bool:  # BR-02
    return hours > CERTIFICATION_THRESHOLD_HOURS or leave_type == "Exception"


def earliest_start(today: dt.date) -> dt.date:  # BR-03
    return today + dt.timedelta(days=LEAD_TIME_DAYS)


def lead_time_ok(start: dt.date, today: dt.date, leave_type: str) -> bool:  # BR-03
    return leave_type == "Exception" or (start - today).days >= LEAD_TIME_DAYS


def overlaps(a_start: dt.date, a_end: dt.date, b_start: dt.date, b_end: dt.date) -> bool:  # BR-04
    return a_start <= b_end and a_end >= b_start


def available_hours(accrued: float, taken: float, pending: float) -> float:  # BR-01
    return accrued - taken - pending


def parse_date(value: Any, field: str, label: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise WorkflowError(400, "VALIDATION", f"Enter the {label} as a calendar date.", field)


def validate_input(payload: dict[str, Any]) -> dict[str, Any]:
    """Field validation for create / update (VAL-04, VAL-05). Returns the normalised fields."""
    if not isinstance(payload, dict):
        raise WorkflowError(400, "VALIDATION", "Send the request fields as a JSON object.")
    leave_type = str(payload.get("leaveType") or "").strip()
    if leave_type not in LEAVE_TYPES:
        raise WorkflowError(400, "VALIDATION", "Choose a leave type and both dates.", "leaveType")
    if not payload.get("startDate") or not payload.get("endDate"):
        raise WorkflowError(400, "VALIDATION", "Choose a leave type and both dates.", "startDate")
    start = parse_date(payload.get("startDate"), "startDate", "start date")
    end = parse_date(payload.get("endDate"), "endDate", "end date")
    if end < start:
        raise WorkflowError(400, "VALIDATION", "End date must be on or after the start date.", "endDate")
    raw_hours = payload.get("hours")
    try:
        hours = float(raw_hours)
    except (TypeError, ValueError):
        raise WorkflowError(400, "VALIDATION", "Enter the requested hours (more than 0).", "hours")
    if not hours > 0 or hours != hours:
        raise WorkflowError(400, "VALIDATION", "Enter the requested hours (more than 0).", "hours")
    if abs(hours * 2 - round(hours * 2)) > 1e-9:
        raise WorkflowError(400, "VALIDATION", "Enter the hours in steps of 0.5 (for example 7.5).", "hours")
    reason = payload.get("reason")
    reason = None if reason in (None, "") else str(reason)
    if reason is not None and len(reason) > REASON_MAX:
        raise WorkflowError(400, "VALIDATION", f"Reason must be {REASON_MAX} characters or fewer; remove {len(reason) - REASON_MAX} characters.", "reason")
    return {"leave_type_code": LEAVE_TYPES[leave_type], "leave_type": leave_type, "start_date": start.isoformat(),
            "end_date": end.isoformat(), "requested_hours": hours, "reason": reason}


# --------------------------------------------------------------------------- service
class WorkflowService:
    def __init__(self, repo, payroll_client, clock):
        self.repo = repo
        self.payroll = payroll_client
        self.clock = clock  # callable -> dt.date (today)

    # ---- helpers
    def _load(self, reference: str) -> dict[str, Any]:
        row = self.repo.get_request(reference)
        if not row:
            raise WorkflowError(404, "NOT_FOUND", f"We could not find request {reference}.")
        return row

    def can_read(self, actor: Actor, row: dict[str, Any]) -> bool:
        if actor.role == EMPLOYEE:
            return row["employee_ref"] == actor.ref
        return actor.role in ROLES

    def allowed_actions(self, actor: Actor, row: dict[str, Any]) -> list[str]:
        """Actions the actor may trigger now, derived from TRANSITIONS + ownership (the UI renders only these)."""
        out: list[str] = []
        for src, _dst, trig, role, guard in TRANSITIONS:
            if src != row["status"] or role != actor.role or trig == "Post":
                continue
            if actor.role == EMPLOYEE and row["employee_ref"] != actor.ref:
                continue
            if actor.role == MANAGER and row["manager_ref"] != actor.ref:
                continue
            if trig == "Manager Approve" and "BR-02" in guard:
                # both routing rows share the trigger; expose once
                pass
            action = TRIGGER_ACTION[trig]
            if action not in out:
                out.append(action)
        if actor.role == EMPLOYEE and row["status"] == DRAFT and row["employee_ref"] == actor.ref:
            out.insert(0, "edit")
        return out

    def balance(self, employee_ref: str) -> dict[str, float]:
        bal = self.repo.get_balance(employee_ref)
        pending = self.repo.pending_hours(employee_ref, PENDING_STATES)
        return {"accrued": bal["accrued_hours"], "taken": bal["taken_hours"], "pending": pending,
                "available": available_hours(bal["accrued_hours"], bal["taken_hours"], pending)}

    # ---- Create / edit
    def create(self, actor: Actor, payload: dict[str, Any]) -> str:
        if actor.role != EMPLOYEE:
            raise WorkflowError(403, "ROLE_NOT_ALLOWED", "Only an employee can create a leave request.")
        fields = validate_input(payload)
        ref = self.repo.create_request(actor.ref, fields, self.clock())
        self.repo.audit(ref, actor, "Create", "—", DRAFT, "applied", None)
        return ref

    def update(self, actor: Actor, reference: str, payload: dict[str, Any]) -> None:
        row = self._load(reference)
        if actor.role != EMPLOYEE or row["employee_ref"] != actor.ref:
            raise WorkflowError(403, "ROLE_NOT_ALLOWED", "Only the employee who owns this request can edit it.")
        if row["status"] != DRAFT:
            raise WorkflowError(409, "STATE_NOT_ALLOWED", f"This action is not available for a request that is {self.repo.label(row['status'])}.")
        fields = validate_input(payload)
        self.repo.update_request(reference, fields)

    # ---- transitions
    def apply(self, actor: Actor, reference: str, trigger: str, payload: dict[str, Any] | None = None) -> None:
        payload = payload or {}
        row = self._load(reference)
        status = row["status"]
        label = self.repo.label(status)
        # 1. role ownership of the trigger (403) + ownership / direct-report constraints
        owners = {t[3] for t in TRANSITIONS if t[2] == trigger}
        if actor.role not in owners or trigger == "Post":
            msg = {"Manager Approve": "Only the employee's manager can approve or return this request.",
                   "Return": "Only the employee's manager or an HR Certifier can return this request.",
                   "Certify": "Only an HR Certifier can certify this request.",
                   "Submit": "Only the employee who owns this request can submit it.",
                   "Withdraw": "Only the employee who owns this request can withdraw it.",
                   "Post": "Payroll posting is performed by the system, not by a person."}.get(trigger, "You are not allowed to perform this action.")
            self.repo.audit(reference, actor, trigger, status, status, "denied", msg)
            raise WorkflowError(403, "ROLE_NOT_ALLOWED", msg)
        if actor.role == EMPLOYEE and row["employee_ref"] != actor.ref:
            msg = "Only the employee who owns this request can do that."
            self.repo.audit(reference, actor, trigger, status, status, "denied", msg)
            raise WorkflowError(403, "ROLE_NOT_ALLOWED", msg)
        if actor.role == MANAGER and row["manager_ref"] != actor.ref:
            msg = "Only the employee's manager can approve or return this request."
            self.repo.audit(reference, actor, trigger, status, status, "denied", msg)
            raise WorkflowError(403, "ROLE_NOT_ALLOWED", msg)
        # 2. (fromState, trigger) present in the table (409)
        candidates = [t for t in TRANSITIONS if t[0] == status and t[2] == trigger and t[3] == actor.role]
        if not candidates:
            msg = f"This action is not available for a request that is {label}."
            self.repo.audit(reference, actor, trigger, status, status, "denied", msg)
            raise WorkflowError(409, "STATE_NOT_ALLOWED", msg)
        # 3. rule guards
        if trigger == "Submit":
            self._check_submit_rules(row)
            new_status = SUBMITTED
        elif trigger == "Manager Approve":
            new_status = MANAGER_APPROVED if requires_certification(row["requested_hours"], row["leave_type"]) else APPROVED
        elif trigger == "Certify":
            new_status = APPROVED
        elif trigger == "Return":
            comment = str(payload.get("comment") or "").strip()
            if not comment:  # BR-07
                raise WorkflowError(400, "COMMENT_REQUIRED", "A comment is required to return a request. Tell the employee what to change.", "comment")
            new_status = DRAFT
        elif trigger == "Withdraw":
            if status not in WITHDRAWABLE:  # BR-05 (also covered by the table)
                raise WorkflowError(409, "STATE_NOT_ALLOWED", f"This action is not available for a request that is {label}.")
            new_status = WITHDRAWN
        else:  # pragma: no cover
            raise WorkflowError(409, "STATE_NOT_ALLOWED", f"This action is not available for a request that is {label}.")
        # 4. persist + audit (one transaction)
        detail = None
        if trigger == "Return":
            detail = comment
            self.repo.add_comment(reference, actor, comment)
        self.repo.set_status(reference, new_status, submitted=(trigger == "Submit"))
        self.repo.audit(reference, actor, trigger, status, new_status, "applied", detail)
        # 5. system transition Post when the request became APPROVED
        if new_status == APPROVED:
            self._post_to_payroll(reference)

    def _check_submit_rules(self, row: dict[str, Any]) -> None:
        bal = self.balance(row["employee_ref"])
        requested = row["requested_hours"]
        if requested > bal["available"]:  # BR-01
            excess = requested - bal["available"]
            raise WorkflowError(400, "BALANCE_EXCEEDED",
                                f"Requested hours exceed your available balance by {fmt_hours(excess)} h. Reduce the request to at most {fmt_hours(max(bal['available'], 0))} h.", "hours")
        today = self.clock()
        start = dt.date.fromisoformat(row["start_date"])
        if not lead_time_ok(start, today, row["leave_type"]):  # BR-03
            raise WorkflowError(400, "LEAD_TIME",
                                f"Vacation and Sick requests must be submitted at least {LEAD_TIME_DAYS} calendar days before the start date. "
                                f"Choose a start date on or after {earliest_start(today).isoformat()}, or request an Exception.", "startDate")
        end = dt.date.fromisoformat(row["end_date"])
        for other in self.repo.other_requests(row["employee_ref"], row["request_ref"]):  # BR-04
            if other["status"] == WITHDRAWN:
                continue
            if overlaps(start, end, dt.date.fromisoformat(other["start_date"]), dt.date.fromisoformat(other["end_date"])):
                raise WorkflowError(400, "OVERLAP",
                                    f"These dates overlap your existing request {other['request_ref']} ({other['start_date']} – {other['end_date']}). "
                                    f"Change the dates or withdraw the other request first.", "startDate")

    def _post_to_payroll(self, reference: str) -> None:
        row = self._load(reference)
        system = Actor(PAYROLL, "SYS-PAYROLL", "Payroll Integration")
        ok, http_status, payroll_ref = self.payroll.post(row)
        self.repo.record_posting(reference, "accepted" if ok else "failed", http_status, payroll_ref)
        if ok:
            self.repo.set_status(reference, POSTED)
            self.repo.audit(reference, system, "Post", APPROVED, POSTED, "applied", payroll_ref)
        else:
            self.repo.audit(reference, system, "Post", APPROVED, APPROVED, "denied", f"Payroll posting failed (HTTP {http_status}); alert raised")
