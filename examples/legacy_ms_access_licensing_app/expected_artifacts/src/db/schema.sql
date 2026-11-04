-- ---- block 1 (extracted from design/solution_design.md) ----
-- Business Licensing & Renewal Portal — normalised schema (SQLite dialect, 3NF)
-- Status values are the spec §3.3 state codes; relationship values are the owner / agent kinds of BR-05.

CREATE TABLE commercial_buyers (
    buyer_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    legal_name          TEXT    NOT NULL CHECK (length(legal_name) BETWEEN 1 AND 200),
    business_name       TEXT,
    entity_type         TEXT    NOT NULL CHECK (entity_type IN ('INDIVIDUAL', 'LLC', 'CORPORATION', 'PARTNERSHIP', 'OTHER')),
    tax_id_kind         TEXT    NOT NULL CHECK (tax_id_kind IN ('SSN', 'FEIN')),
    tax_id_hash         TEXT    NOT NULL UNIQUE,
    tax_id_last4        TEXT    NOT NULL CHECK (length(tax_id_last4) = 4),
    date_of_birth       TEXT    NOT NULL,
    email               TEXT,
    phone               TEXT,
    city                TEXT,
    state_code          TEXT,
    is_suspended        INTEGER NOT NULL DEFAULT 0 CHECK (is_suspended IN (0, 1)),
    under_investigation INTEGER NOT NULL DEFAULT 0 CHECK (under_investigation IN (0, 1)),
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);

CREATE TABLE license_applications (
    application_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    buyer_id             INTEGER NOT NULL REFERENCES commercial_buyers(buyer_id),
    license_year         INTEGER NOT NULL CHECK (license_year BETWEEN 2000 AND 2100),
    status               TEXT    NOT NULL CHECK (status IN ('DRAFT', 'SUBMITTED', 'ISSUED', 'REJECTED')),
    license_number       TEXT    UNIQUE,
    prior_year_purchases NUMERIC NOT NULL DEFAULT 0 CHECK (prior_year_purchases >= 0),
    required_bond_amount NUMERIC NOT NULL DEFAULT 1000.00,
    bond_amount          NUMERIC NOT NULL DEFAULT 0 CHECK (bond_amount >= 0),
    bond_surety_name     TEXT,
    bond_number          TEXT,
    bond_expiry          TEXT,
    decision_reason      TEXT,
    submitted_at         TEXT,
    decided_at           TEXT,
    created_at           TEXT    NOT NULL,
    updated_at           TEXT    NOT NULL
);
CREATE INDEX idx_license_applications_status ON license_applications(status, submitted_at);
CREATE INDEX idx_license_applications_buyer_year ON license_applications(buyer_id, license_year);

CREATE TABLE field_agents (
    agent_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name    TEXT    NOT NULL CHECK (length(first_name) BETWEEN 1 AND 100),
    last_name     TEXT    NOT NULL CHECK (length(last_name) BETWEEN 1 AND 100),
    date_of_birth TEXT    NOT NULL,
    is_suspended  INTEGER NOT NULL DEFAULT 0 CHECK (is_suspended IN (0, 1)),
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL,
    UNIQUE (last_name, first_name, date_of_birth)
);
CREATE INDEX idx_field_agents_name ON field_agents(last_name, first_name);

CREATE TABLE agent_assignments (
    assignment_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id  INTEGER NOT NULL REFERENCES license_applications(application_id),
    agent_id        INTEGER NOT NULL REFERENCES field_agents(agent_id),
    relationship    TEXT    NOT NULL CHECK (relationship IN ('OWNER', 'AGENT')),
    assigned_on     TEXT    NOT NULL,
    removed_on      TEXT,
    card_printed_at TEXT
);
CREATE INDEX idx_agent_assignments_agent_active ON agent_assignments(agent_id, removed_on);
CREATE INDEX idx_agent_assignments_application ON agent_assignments(application_id, removed_on);

CREATE TABLE supporting_documents (
    document_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES license_applications(application_id),
    file_name      TEXT    NOT NULL CHECK (length(file_name) BETWEEN 1 AND 200),
    content_type   TEXT    NOT NULL,
    size_bytes     INTEGER NOT NULL CHECK (size_bytes >= 0),
    vault_reference TEXT,
    uploaded_at    TEXT    NOT NULL
);

CREATE TABLE quarterly_fee_reports (
    report_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES license_applications(application_id),
    quarter        TEXT    NOT NULL,
    purchase_total NUMERIC NOT NULL CHECK (purchase_total >= 0),
    fee_due        NUMERIC NOT NULL,
    reported_at    TEXT    NOT NULL,
    UNIQUE (application_id, quarter)
);

CREATE TABLE audit_events (
    event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER REFERENCES license_applications(application_id),
    buyer_id       INTEGER REFERENCES commercial_buyers(buyer_id),
    agent_id       INTEGER REFERENCES field_agents(agent_id),
    actor_role     TEXT    NOT NULL,
    actor_name     TEXT,
    action         TEXT    NOT NULL,
    from_status    TEXT,
    to_status      TEXT,
    reason         TEXT,
    occurred_at    TEXT    NOT NULL
);
CREATE INDEX idx_audit_events_application ON audit_events(application_id, occurred_at);
