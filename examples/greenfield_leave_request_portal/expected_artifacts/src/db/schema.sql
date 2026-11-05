-- Employee Leave & Exception Request Portal — SQLite 3 DDL (3NF). Status values = spec §3.3 state codes.
PRAGMA foreign_keys = ON;

CREATE TABLE employee (
    employee_ref      TEXT PRIMARY KEY,                 -- format EMP-NNNNN (masked at the ViewModel boundary)
    display_name      TEXT NOT NULL,
    role_group        TEXT NOT NULL CHECK (role_group IN ('employees', 'managers', 'hr-certifiers', 'system')),
    manager_ref       TEXT REFERENCES employee(employee_ref)
);

CREATE TABLE leave_balance (
    employee_ref      TEXT PRIMARY KEY REFERENCES employee(employee_ref),
    accrued_hours     REAL NOT NULL CHECK (accrued_hours >= 0),
    taken_hours       REAL NOT NULL CHECK (taken_hours >= 0)
);

CREATE TABLE leave_type (
    leave_type_code        TEXT PRIMARY KEY,            -- vacation | sick | exception
    label                  TEXT NOT NULL UNIQUE,        -- Vacation | Sick | Exception
    requires_certification INTEGER NOT NULL DEFAULT 0 CHECK (requires_certification IN (0, 1)),
    exempt_from_lead_time  INTEGER NOT NULL DEFAULT 0 CHECK (exempt_from_lead_time IN (0, 1))
);

CREATE TABLE leave_request (
    request_ref       TEXT PRIMARY KEY,                 -- LR-NNNN, shown to users as the request reference
    employee_ref      TEXT NOT NULL REFERENCES employee(employee_ref),
    leave_type_code   TEXT NOT NULL REFERENCES leave_type(leave_type_code),
    start_date        TEXT NOT NULL,                    -- ISO-8601 date
    end_date          TEXT NOT NULL CHECK (end_date >= start_date),
    requested_hours   REAL NOT NULL CHECK (requested_hours > 0),
    reason            TEXT CHECK (reason IS NULL OR length(reason) <= 500),
    status            TEXT NOT NULL CHECK (status IN ('DRAFT', 'SUBMITTED', 'MANAGER_APPROVED', 'APPROVED', 'POSTED', 'WITHDRAWN')),
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    submitted_at      TEXT
);
CREATE INDEX idx_leave_request_employee_status ON leave_request(employee_ref, status);
CREATE INDEX idx_leave_request_status ON leave_request(status);

CREATE TABLE review_comment (
    comment_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    request_ref       TEXT NOT NULL REFERENCES leave_request(request_ref),
    author_ref        TEXT NOT NULL REFERENCES employee(employee_ref),
    author_role       TEXT NOT NULL,
    comment_text      TEXT NOT NULL CHECK (length(trim(comment_text)) >= 1),
    created_at        TEXT NOT NULL
);
CREATE INDEX idx_review_comment_request ON review_comment(request_ref, created_at);

CREATE TABLE request_state_change (                    -- append-only audit (FR-08)
    change_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    request_ref       TEXT NOT NULL REFERENCES leave_request(request_ref),
    actor_ref         TEXT NOT NULL,
    actor_role        TEXT NOT NULL,
    trigger_name      TEXT NOT NULL,
    previous_status   TEXT NOT NULL,
    new_status        TEXT NOT NULL,
    outcome           TEXT NOT NULL CHECK (outcome IN ('applied', 'denied')),
    detail            TEXT,
    changed_at        TEXT NOT NULL
);
CREATE INDEX idx_state_change_request ON request_state_change(request_ref, changed_at);

CREATE TABLE payroll_posting (                         -- one row per posting attempt (FR-07)
    posting_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    request_ref       TEXT NOT NULL REFERENCES leave_request(request_ref),
    outcome           TEXT NOT NULL CHECK (outcome IN ('accepted', 'failed')),
    http_status       INTEGER,
    payroll_reference TEXT,
    attempted_at      TEXT NOT NULL
);
CREATE INDEX idx_payroll_posting_request ON payroll_posting(request_ref, attempted_at);
