# Data Architecture (`design/data_architecture.md`)

- **Project:** Employee Leave Request Portal (`SCENARIO_REQUIREMENTS_DOC`)
- **Perspective:** **Data Architecture — Information Pipeline, Normalised 3NF Domain Model, AI Grounding & Data Governance** (Standalone Perspective Artifact 5 of 7)
- **Visual Renderer:** `design/diagrams/data_architecture.svg` (`.png`) — 5-Stage Left-to-Right Information Pipeline + Bottom Governance Bar
- **Architecture Portfolio Index:** [`design/architecture_design.md`](architecture_design.md)

---

## 1. End-to-End Data & AI Grounding Pipeline Architecture

*(Depicts the end-to-end flow of leave data across **5 Pipeline Stages** — **Data Sources & Producers**, **Ingestion, Validation & CDC**, **Operational 3NF System of Record & MDM**, **Unified Data & AI Grounding / RAG**, and **Consumption, Analytics & Archival** — underpinned by the **Unified Data Governance, Lineage, PII Masking & Retention** bar.)*

![Data Architecture](diagrams/data_architecture.svg)

```mermaid
flowchart LR
    %% title: Employee Leave Request Portal — End-to-End Data & AI Grounding Architecture
    %% subtitle: 5-Stage Data Pipeline from Leave Intake to 3NF System of Record, Policy RAG Grounding, and Payroll Export
    subgraph SG_Stage1["1. Data Sources & Producers"]
        S1["<b>Employee Leave Portal</b><br/>Leave Requests &amp; Edits"]:::dataCard
        S2["<b>Corporate HR Directory</b><br/>Employee &amp; Manager Hierarchy"]:::dataCard
        S3["<b>Regional Holiday Feed</b><br/>Public Holiday Calendars"]:::dataCard
        S4["<b>Medical Cert Uploads</b><br/>Encrypted Attachments"]:::dataCard
    end

    subgraph SG_Stage2["2. Ingestion, Validation & CDC"]
        I1["<b>OpenAPI Schema Gate</b><br/>Type, Date &amp; Enum Checks"]:::dataCard
        I2["<b>Working-Day Validator</b><br/>Holiday &amp; Overlap Filter"]:::dataCard
        I3["<b>Transactional Outbox</b><br/>State Event Capture"]:::dataCard
        I4["<b>PII Tokenization</b><br/>Medical &amp; Reason Redaction"]:::dataCard
    end

    subgraph SG_Stage3["3. Operational 3NF System of Record"]
        D1["<b>3NF Relational Primary</b><br/>ACID Leave &amp; Balance Tables"]:::dataCard
        D2["<b>Cross-Zone HA Standby</b><br/>Synchronous Replication"]:::dataCard
        D3["<b>Employee &amp; Quota Master</b><br/>Accrual &amp; Leave Type Lookup"]:::dataCard
        D4["<b>Append-Only Audit Log</b><br/>Immutable State History"]:::dataCard
    end

    subgraph SG_Stage4["4. Unified Data & AI Grounding"]
        A1["<b>Curated Leave Mart</b><br/>Read-Optimized Views"]:::dataCard
        A2["<b>HR Policy Vector Index</b><br/>Leave Handbook Embeddings"]:::dataCard
        A3["<b>Semantic Balance Layer</b><br/>Accrual &amp; Coverage Metrics"]:::dataCard
        A4["<b>De-Identified Analytics</b><br/>Privacy-Safe Aggregates"]:::dataCard
    end

    subgraph SG_Stage5["5. Consumption, Analytics & Export"]
        C1["<b>Zero-Leak DTO APIs</b><br/>Role-Scoped UI Payloads"]:::dataCard
        C2["<b>Workforce KPI Dashboards</b><br/>Absence &amp; SLA Reporting"]:::dataCard
        C3["<b>Leave Policy AI Copilot</b><br/>Grounded Policy Answers"]:::dataCard
        C4["<b>Payroll Webhook Export</b><br/>Approved Leave Postings"]:::dataCard
    end

    subgraph SG_GovBar["Unified Data Governance, Lineage, PII Masking, KMS Encryption & Retention Policies"]
        G1["<b>Data Catalog &amp; Lineage</b><br/>Schema Registry"]:::govCard
        G2["<b>Zero-Leak PII Masking</b><br/>Role-Based Redaction"]:::govCard
        G3["<b>KMS Encryption (CMEK)</b><br/>TLS 1.3 &amp; AES-256"]:::govCard
        G4["<b>Retention &amp; Archival</b><br/>7-Year Labor Audit Lifecycle"]:::govCard
    end

    SG_Stage1 ==> SG_Stage2 ==> SG_Stage3 ==> SG_Stage4 ==> SG_Stage5
    SG_Stage3 -.-> SG_GovBar

    classDef dataCard fill:#FFFFFF,stroke:#2B5B84,stroke-width:1.5px,color:#202124;
    classDef govCard fill:#E8F0FE,stroke:#1A73E8,stroke-width:1.5px,color:#0D47A1;
```

---

## 2. Normalised 3NF Domain Data Model (`erDiagram`)

```mermaid
erDiagram
    employee ||--o{ leave_request : "submits"
    employee ||--o| employee : "reports to (manager)"
    employee ||--|| leave_balance : "has"
    leave_type ||--o{ leave_request : "classifies"
    leave_request ||--o{ request_state_change : "is audited by"
    leave_request ||--o{ review_comment : "receives on return"
    leave_request ||--o| payroll_posting : "is published as"
    employee ||--o{ request_state_change : "acts as actor"

    employee {
        string employee_ref PK
        string display_name
        string manager_ref FK
        string role_group
    }
    leave_balance {
        string employee_ref PK
        decimal accrued_hours
        decimal taken_hours
    }
    leave_type {
        string leave_type_code PK
        string label
        boolean requires_certification
        boolean exempt_from_lead_time
    }
    leave_request {
        string request_ref PK
        string employee_ref FK
        string leave_type_code FK
        date start_date
        date end_date
        decimal requested_hours
        string reason
        string status
        datetime submitted_at
    }
    review_comment {
        int comment_id PK
        string request_ref FK
        string author_ref FK
        string author_role
        string comment_text
        datetime created_at
    }
    request_state_change {
        int change_id PK
        string request_ref FK
        string actor_ref
        string actor_role
        string trigger_name
        string previous_status
        string new_status
        string outcome
        datetime changed_at
    }
    payroll_posting {
        int posting_id PK
        string request_ref FK
        string outcome
        int http_status
        string payroll_reference
        datetime attempted_at
    }
```

---

## 3. Data Governance, Classification & Retention Matrix

| Domain Entity | Data Classification | PII / Sensitive Fields | Masking & Zero-Leak Rule | Storage Tier & Retention Policy |
| :-- | :-- | :-- | :-- | :-- |
| `employee` | `Internal / Confidential` | `employee_ref`, `display_name` | Expose human-readable `display_name`; mask internal reference IDs where required | Operational 3NF DB; retained for active employment + 7 years |
| `leave_balance` | `Confidential` | `accrued_hours`, `taken_hours` | Visible only to the owning `Employee`, their `Line Manager`, and `HR Administrator` | Operational 3NF DB; recalculated transactionally |
| `leave_request` | `Confidential / Sensitive` | `reason`, medical certification notes | Masked for unauthorized roles; enum status mapped to human-readable labels | Operational 3NF DB + 7-year encrypted archive |
| `request_state_change` | `Compliance Audit` | `actor_ref`, `previous_status`, `new_status` | Append-only (`INSERT` only; `UPDATE`/`DELETE` revoked); exported to WORM storage | Immutable Audit Ledger; 7-year statutory retention |
