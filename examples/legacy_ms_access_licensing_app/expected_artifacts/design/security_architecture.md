# Security Architecture (`design/security_architecture.md`)

- **Project:** Business Licensing & Renewal Portal — Legacy MS Access Modernization (Legacy Application Modernization)
- **Perspective:** **Security, Zero-Trust & AI Trust Layer Architecture** (Standalone Perspective Artifact 6 of 7)
- **Visual Renderer:** `design/diagrams/security_architecture.svg` (`.png`) — 5-Layer Defense-in-Depth & AI Trust Layer Stack
- **Architecture Portfolio Index:** [`design/architecture_design.md`](architecture_design.md)

---

## 1. Defense-in-Depth & AI Trust Layer Architecture (5 Security Perimeters)

*(Depicts the concentric 5-layer defense-in-depth security model across **Perimeter 1 (Identity & Federation)**, **Perimeter 2 (Network & Edge)**, **Perimeter 3 (Application RBAC, State-Guard & Separation of Duties)**, **Perimeter 4 (AI Trust Layer & Zero-Leak Tax ID Privacy)**, and **Perimeter 5 (Data Encryption, Secrets & Continuous Compliance)**.)*

![Security Architecture](diagrams/security_architecture.png)

---

## 2. Role-Based Access Control (RBAC) & Separation-of-Duties Matrix

| Business Persona | Authentication & Scope | Permitted Views | Permitted Workflow Actions | Prohibited Actions & Separation-of-Duties Guards |
| :-- | :-- | :-- | :-- | :-- |
| **Commercial Buyer (`Business Applicant`)** | OIDC SSO + Buyer Entity Scope | Applicant Filing Portal, Bond Calculator, Agent Roster, Quarterly Fee Report, Certificate View | Create/Update Draft Application, Designate Field Agents, Upload Supporting Docs, Submit Application, File Quarterly Fees | Cannot access Staff Compliance Console; cannot Issue or Reject any application (`403 Forbidden`); cannot print agent ID cards before license is `ISSUED` (`409 Conflict`) |
| **Licensing Staff (`Compliance Reviewer` / `Supervisor`)** | Enterprise OIDC + Staff Role + MFA | Staff Compliance Console, Submitted Queue, Audit Trail, Certificate & Agent Card View | Review Submitted Applications, Issue License (generates `LIC-YYYY-NNNN`), Reject Application (mandatory reason), Print Agent ID Cards | Cannot mutate historical `audit_events` rows; cannot issue a license when buyer is suspended, under investigation, or bond is insufficient (`422 Unprocessable Entity`) |

---

## 3. AI Trust Layer & Zero-Leak Privacy Controls

| Control Domain | Threat / Risk Mitigated | Enforcement Mechanism | Verification Gate |
| :-- | :-- | :-- | :-- |
| **Tax ID Cryptographic Protection** | Plaintext SSN/FEIN exposure in database, logs, or UI (legacy MS Access stored raw Tax IDs) | Full Tax ID is hashed (`SHA-256`) on intake; only `tax_id_last4` is stored for display as `***-**-1234` (`tax_id_hash` marked `x-internal: true`) | `TC-UI-LEAK-01..04` & `TC-NEG-*` Zero-Leakage & Security Verification |
| **Zero Legacy Identifier Leakage** | Leaking legacy MS Access table/form/query/report names (`tblBuyers`, `frmLicenseApp`, `qryActiveLicenses`) | Clean 3NF domain model and ViewModel/DTO serializer strip all internal and legacy identifiers | `forbiddenUiTokens` static + runtime browser scan |
| **AI Prompt & Statute RAG Guardrails** | Tax IDs or confidential investigation notes leaking into LLM prompts or hallucinated statutory rules | Pre-prompt PII redaction strips SSN/FEIN patterns; RAG grounds responses strictly in public licensing statutes; AI is read-only | Runtime RBAC & state-transition guard (`403`/`409`) |
