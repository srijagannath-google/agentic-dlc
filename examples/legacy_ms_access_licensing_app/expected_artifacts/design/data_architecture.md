# Data Architecture (`design/data_architecture.md`)

- **Project:** Business Licensing & Renewal Portal — Legacy MS Access Modernization (Legacy Application Modernization)
- **Perspective:** **Data Architecture — Information Pipeline, Normalised 3NF Domain Model, AI Grounding & Data Governance** (Standalone Perspective Artifact 5 of 7)
- **Visual Renderer:** `design/diagrams/data_architecture.svg` (`.png`) — 5-Stage Left-to-Right Information Pipeline + Bottom Governance Bar
- **Architecture Portfolio Index:** [`design/architecture_design.md`](architecture_design.md)

---

## 1. End-to-End Data & AI Grounding Pipeline Architecture

*(Depicts the end-to-end flow of licensing data across **5 Pipeline Stages** — **Data Sources & Producers**, **Ingestion, Validation & CDC**, **Operational 3NF System of Record & MDM**, **Unified Data & AI Grounding / RAG**, and **Consumption, Analytics & Archival** — underpinned by the **Unified Data Governance, Lineage, Tax ID Masking & Retention** bar.)*

![Data Architecture](diagrams/data_architecture.png)

---

## 2. Normalised 3NF Domain Data Model (`erDiagram`)

```mermaid
erDiagram
    commercial_buyers ||--o{ license_applications : "files one per calendar year"
    license_applications ||--o{ agent_assignments : "designates"
    field_agents ||--o{ agent_assignments : "serves under"
    license_applications ||--o{ supporting_documents : "attaches"
    license_applications ||--o{ quarterly_fee_reports : "reports quarterly"
    license_applications ||--o{ audit_events : "records"

    commercial_buyers {
        int buyer_id PK
        text legal_name
        text business_name
        text entity_type
        text tax_id_kind
        text tax_id_hash
        text tax_id_last4
        date date_of_birth
        text email
        text phone
        text city
        text state_code
        int is_suspended
        int under_investigation
    }
    license_applications {
        int application_id PK
        int buyer_id FK
        int license_year
        text status
        text license_number
        numeric prior_year_purchases
        numeric required_bond_amount
        numeric bond_amount
        text bond_surety_name
        text bond_number
        text decision_reason
        datetime submitted_at
        datetime decided_at
    }
    field_agents {
        int agent_id PK
        text first_name
        text last_name
        date date_of_birth
        int is_suspended
    }
    agent_assignments {
        int assignment_id PK
        int application_id FK
        int agent_id FK
        text relationship
        date assigned_on
        date removed_on
        datetime card_printed_at
    }
    supporting_documents {
        int document_id PK
        int application_id FK
        text file_name
        text content_type
        int size_bytes
        datetime uploaded_at
    }
    quarterly_fee_reports {
        int report_id PK
        int application_id FK
        text quarter
        numeric purchase_total
        numeric fee_due
        datetime reported_at
    }
    audit_events {
        int event_id PK
        int application_id FK
        text actor_role
        text action
        text from_status
        text to_status
        text note
        datetime occurred_at
    }
```

---

## 3. Data Governance, Classification & Retention Matrix

| Domain Entity | Data Classification | PII / Sensitive Fields | Masking & Zero-Leak Rule | Storage Tier & Retention Policy |
| :-- | :-- | :-- | :-- | :-- |
| `commercial_buyers` | `Restricted / PII` | `tax_id_hash`, `tax_id_last4`, `date_of_birth` | Full Tax ID hashed (`SHA-256`) at rest; UI/API expose only `***-**-<last4>` (`tax_id_hash` marked `x-internal: true`) | Operational 3NF DB; KMS AES-256 encrypted |
| `license_applications` | `Confidential / Regulatory` | `bond_number`, `prior_year_purchases`, `decision_reason` | Status enum codes mapped to human-readable labels; zero legacy `tbl*` column names | Operational 3NF DB + 7-year statutory archive |
| `field_agents` | `Confidential / PII` | `date_of_birth` | Used to verify statutory age `>= 18`; masked in public lookups | Operational 3NF DB |
| `audit_events` | `Compliance Audit` | `actor_role`, `from_status`, `to_status`, `note` | Append-only (`INSERT` only; `UPDATE`/`DELETE` revoked); exported to WORM storage | Immutable Audit Ledger; 7-year statutory retention |
