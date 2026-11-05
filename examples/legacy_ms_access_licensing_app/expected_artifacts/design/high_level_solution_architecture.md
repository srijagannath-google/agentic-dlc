# High-Level Solution Architecture — AI-Era Enterprise View (`design/high_level_solution_architecture.md`)

- **Project:** Business Licensing & Renewal Portal — Legacy MS Access Modernization (Legacy Application Modernization)
- **Perspective:** **High-Level Solution Architecture — System of Engagement, System of Intelligence & AI, and Systems of Record** (Standalone Perspective Artifact 2 of 7)
- **Visual Renderer:** `design/diagrams/high_level_solution_architecture.svg` (`.png`) — 3-Tier Enterprise Architecture with Top Personas, Engagement Layer, Cyan System of Intelligence & Agentic AI Layer, and Transactional Systems of Record
- **Architecture Portfolio Index:** [`design/architecture_design.md`](architecture_design.md)

---

## 1. Future-State High-Level Solution Architecture (Engagement, Agentic Intelligence & Systems of Record)

*(Synthesizes the executive 3-tier enterprise architecture across **Business Personas**, the **Engagement Layer (`System of Engagement`)**, the **System of Intelligence & AI (`Agentic AI, Regulatory RAG, Fee/Bond Intelligence & Governance Core`)**, and **Transactional Systems (`Systems of Record`)**.)*

![High-Level Solution Architecture](diagrams/high_level_solution_architecture.png)

---

## 2. High-Level Architectural Tiers & System-of-Intelligence Responsibilities

| Architectural Tier | Core Role in Target State | Key Capabilities & Components | Governance & Trust Boundary |
| :-- | :-- | :-- | :-- |
| **Personas & Actors** | Role-authenticated external and internal licensing actors | `Business Applicants`, `Compliance Reviewers`, `Licensing Supervisors`, `Regulatory Analysts` | OIDC / SAML 2.0 identity federation with role-scoped session claims |
| **Engagement Layer (`System of Engagement`)** | Replaces single-user MS Access forms (`frmLicenseApp`) and reports (`rptCertificate`) with web self-service and triage consoles | `Applicant Self-Service Portal`, `Reviewer Triage Console`, `Supervisor Console`, `Licensing AI Copilot`, `Public License Lookup` | Zero-Leak ViewModel/DTO boundary (`***-**-1234` Tax ID masking, zero `tbl*`/`frm*` legacy leaks); WCAG 2.1 AA compliance |
| **System of Intelligence & AI (`Agentic & Domain Core`)** | Combines deterministic licensing/bond/fee rules with grounded statute RAG copilots and compliance risk analytics | • **AI & Agentic Layer:** Licensing Statute RAG Copilot, Bond Document Verifier Agent, Risk Triage, Prompt Guardrails<br>• **Core Domain Capabilities:** `Unified Business Profile`, `Revenue & Risk Insights`, `Licensing & Fee Engine`, `Cross-Agency Collaboration`<br>• **Data Ingestion & Transformation:** Legacy MS Access Migration, Surety Bond Validation, Quarterly Fee Normalization | • `Built-in Data & AI Security` (Tax ID redaction before prompt grounding)<br>• `Unified Data Governance`<br>• `Payment & Registry API`<br>• `Anomaly & Fraud Guard` (blocks suspended buyers/agents and duplicate active filings) |
| **Transactional Systems (`Systems of Record`)** | Authoritative ACID persistence replacing shared SMB `.mdb` files | `Licensing Relational DB` (3NF), `Enterprise Identity (OIDC/SAML)`, `Treasury Payment Gateway`, `Certificate & Doc Store`, `Immutable Audit Ledger` | Encryption at rest (`KMS CMEK`), mTLS in transit, append-only audit constraints |
