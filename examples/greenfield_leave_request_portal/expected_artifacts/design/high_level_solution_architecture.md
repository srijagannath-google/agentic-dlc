# High-Level Solution Architecture — AI-Era Enterprise View (`design/high_level_solution_architecture.md`)

- **Project:** Employee Leave Request Portal (Greenfield Requirements Specification)
- **Perspective:** **High-Level Solution Architecture — System of Engagement, System of Intelligence & AI, and Systems of Record** (Standalone Perspective Artifact 2 of 7)
- **Visual Renderer:** `design/diagrams/high_level_solution_architecture.svg` (`.png`) — 3-Tier Enterprise Architecture with Top Personas, Engagement Layer, Cyan System of Intelligence & Agentic AI Layer, and Transactional Systems of Record
- **Architecture Portfolio Index:** [`design/architecture_design.md`](architecture_design.md)

---

## 1. Future-State High-Level Solution Architecture (Engagement, Agentic Intelligence & Systems of Record)

*(Synthesizes the executive 3-tier enterprise architecture across **Business Personas**, the **Engagement Layer (`System of Engagement`)**, the **System of Intelligence & AI (`Agentic AI, Leave Policy RAG, Balance Forecasting & Governance Core`)**, and **Transactional Systems (`Systems of Record`)**.)*

![High-Level Solution Architecture](diagrams/high_level_solution_architecture.png)

---

## 2. High-Level Architectural Tiers & System-of-Intelligence Responsibilities

| Architectural Tier | Core Role in Target State | Key Capabilities & Components | Governance & Trust Boundary |
| :-- | :-- | :-- | :-- |
| **Personas & Actors** | Role-authenticated human actors interacting with the leave platform | `Employees`, `Line Managers`, `HR Administrators`, `Workforce Analysts` | OIDC / SAML 2.0 identity federation with role-scoped session claims |
| **Engagement Layer (`System of Engagement`)** | Responsive, accessible multi-channel user experience and embedded AI assistance | `Employee Self-Service Portal`, `Manager Review Console`, `HR Oversight Workspace`, `Leave Policy AI Copilot`, `Omnichannel Alerts` | Zero-Leak ViewModel/DTO boundary; WCAG 2.1 AA compliance |
| **System of Intelligence & AI (`Agentic & Domain Core`)** | Combines deterministic leave policy/accrual rules with grounded AI copilots and team coverage forecasting | • **AI & Agentic Layer:** Leave Policy RAG Copilot, Team Coverage Advisor Agent, Medical Certification Verifier, Prompt Guardrails<br>• **Core Domain Capabilities:** `Unified Employee Leave View`, `Absence & Coverage Insights`, `Leave Lifecycle & Rules Engine`, `Cross-Team Coverage Sync`<br>• **Data Ingestion & Transformation:** Holiday Calendar Sync, Accrual Ledger Normalization, Payroll Event Outbox | • `Built-in Data & AI Security` (PII redaction before prompt grounding)<br>• `Unified Leave Governance`<br>• `Payroll & HRIS Exchange`<br>• `Overlap & Policy Guard` (deterministic state/role check before any write) |
| **Transactional Systems (`Systems of Record`)** | Authoritative ACID persistence, identity federation, payroll integration, and immutable audit storage | `Leave Relational DB` (3NF), `Corporate Identity (OIDC/SAML)`, `Enterprise Payroll API`, `Certification Store`, `Immutable Audit Ledger` | Encryption at rest (`KMS CMEK`), mTLS in transit, append-only audit constraints |
