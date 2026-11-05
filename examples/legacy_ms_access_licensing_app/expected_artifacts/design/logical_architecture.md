# Logical Solution Architecture (`design/logical_architecture.md`)

- **Project:** Business Licensing & Renewal Portal — Legacy MS Access Modernization (Legacy Application Modernization)
- **Perspective:** **Logical Business Capability & Functional Domain Architecture** (Standalone Perspective Artifact 3 of 7)
- **Visual Renderer:** `design/diagrams/logical_architecture.svg` (`.png`) — Concentric Multi-Zone Functional Topology
- **Architecture Portfolio Index:** [`design/architecture_design.md`](architecture_design.md)

---

## 1. Logical Solution Architecture (Business Personas, User Experience Channels, Domain Policy Core, Business Capabilities & Domain Data Stores)

*(Depicts the Business Licensing Portal's cloud-agnostic **Business Capability & Functional Domain Architecture**: Business Personas (`Business Applicant`, `Compliance Reviewer`, `Licensing Supervisor`) in the left `#F1F3F4` column, User Experience Channels & Data Privacy Gateway in Column 1, Core Licensing Policy & Fee Calculation Orchestration in Column 2 with red dashed policy-rejection feedback, and the 3×3 grid of Business Capability Services and Logical Domain Data Stores in Column 3.)*

![Logical Solution Architecture](diagrams/logical_architecture.png)

---

## 2. Logical Functional Zone & Capability Responsibilities

| Logical Architecture Zone | Logical Components | Functional Responsibility | Domain Policy Enforced |
| :-- | :-- | :-- | :-- |
| **1. Business Personas & Actors** | `Business Applicant`, `Compliance Reviewer`, `Licensing Supervisor` | Initiates license applications, compliance triage, and certificate issuance/revocation | Role-scoped access and separation of duties |
| **2. User Experience & Channel Capabilities** | `Applicant Portal`, `Reviewer Triage Console`, `Supervisor Console`, `Data Privacy Gateway` | Role-tailored workspaces and outbound Tax ID masking (`***-**-1234`) | Zero legacy MS Access object names (`tbl*`, `frm*`, `qry*`, `rpt*`) in UI |
| **3. Core Licensing Domain Orchestration & Policy Engine** | `Role-Based Access Control`, `License Lifecycle Engine`, `Status & Prerequisite Gate`, `Tiered Fee & Penalty Calculator`, `Tax ID & Good Standing Validator`, `Annual Term & Certificate Gate` | Evaluates lifecycle state transitions, surety bond formulas, quarterly fee rates, and buyer/agent good standing | Rejects illegal transitions (`409`), unauthorized roles (`403`), and bond/standing violations (`422`) |
| **4. Business Capability Services & Logical Stores** | `License Application Intake`, `Fee & Penalty Assessment`, `License Renewal Service`, `Compliance Triage Service`, `Certificate Issuance`, `Certificate Printing`, plus 3 Logical Stores | Executes bounded licensing capabilities and persists state changes with append-only audit trails | Transactional consistency across entities, applications, fees, and certificates |
