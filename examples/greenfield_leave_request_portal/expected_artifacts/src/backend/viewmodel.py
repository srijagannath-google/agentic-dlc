"""ViewModel mapper — the single presentation boundary (spec §4.2, design §4).

Everything the UI receives passes through here: status codes become labels, the employee identifier is masked,
internal keys / audit columns are dropped. `statusCode` is carried for client-side gating only (x-internal)."""
from __future__ import annotations

from typing import Any

import workflow as wf

NEXT_APPROVER = {"DRAFT": "—", "SUBMITTED": "Manager", "MANAGER_APPROVED": "HR Certifier", "APPROVED": "Payroll", "POSTED": "—", "WITHDRAWN": "—"}
POSTING_LABEL = {"accepted": "Accepted by payroll", "failed": "Payroll posting failed"}


def mask_reference(ref: str) -> str:
    if not ref or "-" not in ref:
        return "•••"
    prefix, digits = ref.split("-", 1)
    return f"{prefix}-•••{digits[-2:]}"


def actor_view(employee: dict[str, Any] | None, role: str) -> dict[str, Any]:
    if not employee:
        return {"role": role, "displayName": role, "maskedReference": "—"}
    return {"role": role, "displayName": employee["display_name"], "maskedReference": mask_reference(employee["employee_ref"])}


def balance_view(b: dict[str, float], today) -> dict[str, Any]:
    return {"accruedHours": b["accrued"], "takenHours": b["taken"], "pendingHours": b["pending"], "availableHours": b["available"],
            "today": today.isoformat(), "leadTimeDays": wf.LEAD_TIME_DAYS, "certificationThresholdHours": wf.CERTIFICATION_THRESHOLD_HOURS}


def posting_view(p: dict[str, Any] | None, status: str | None = None) -> dict[str, Any] | None:
    if not p:
        return None
    return {"reference": p["request_ref"], "outcomeLabel": POSTING_LABEL.get(p["outcome"], p["outcome"]), "payrollReference": p.get("payroll_reference"),
            "attemptedAt": p["attempted_at"], "alert": "Payroll posting failed" if p["outcome"] == "failed" else None,
            "statusLabel": None if status is None else STATUS_LABEL[status]}


STATUS_LABEL = {"DRAFT": "Draft", "SUBMITTED": "Submitted", "MANAGER_APPROVED": "Manager approved",
                "APPROVED": "Approved", "POSTED": "Posted to payroll", "WITHDRAWN": "Withdrawn"}


def request_view(row: dict[str, Any], allowed: list[str], posting: dict[str, Any] | None) -> dict[str, Any]:
    status = row["status"]
    needs_cert = wf.requires_certification(row["requested_hours"], row["leave_type"])
    return {
        "reference": row["request_ref"],
        "employee": {"role": "Employee", "displayName": row["employee_name"], "maskedReference": mask_reference(row["employee_ref"])},
        "leaveType": row["leave_type"],
        "startDate": row["start_date"],
        "endDate": row["end_date"],
        "hours": row["requested_hours"],
        "reason": row.get("reason") or "",
        "statusCode": status,
        "statusLabel": STATUS_LABEL[status],
        "nextApprover": NEXT_APPROVER[status],
        "requiresCertification": needs_cert,
        "certificationLabel": "HR certification required" if needs_cert else "Manager approval is final",
        "returnComment": row.get("last_comment") or "",
        "returnedByRole": row.get("last_comment_role") or "",
        "allowedActions": allowed,
        "posting": posting_view(posting, status),
        "updatedAt": row["updated_at"],
    }


def audit_view(entries: list[dict[str, Any]], show_actor: bool) -> list[dict[str, Any]]:
    out = []
    for e in entries:
        out.append({
            "at": e["changed_at"],
            "actor": e["actor_name"] if show_actor else "",
            "role": e["actor_role"] if show_actor else "",
            "fromLabel": STATUS_LABEL.get(e["previous_status"], "—"),
            "toLabel": STATUS_LABEL.get(e["new_status"], "—"),
            "outcome": "applied" if e["outcome"] == "applied" else "denied",
            "detail": (e.get("detail") or "") if show_actor else "",
        })
    return out
