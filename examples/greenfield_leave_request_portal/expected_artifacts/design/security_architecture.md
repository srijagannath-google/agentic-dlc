# Security Architecture (`design/security_architecture.md`)

- **Project:** Employee Leave Request Portal (`SCENARIO_REQUIREMENTS_DOC`)
- **Perspective:** **Security, Zero-Trust & AI Trust Layer Architecture** (Standalone Perspective Artifact 6 of 7)
- **Visual Renderer:** `design/diagrams/security_architecture.svg` (`.png`) — 5-Layer Defense-in-Depth & AI Trust Layer Stack
- **Architecture Portfolio Index:** [`design/architecture_design.md`](architecture_design.md)

---

## 1. Defense-in-Depth & AI Trust Layer Architecture (5 Security Perimeters)

*(Depicts the concentric 5-layer defense-in-depth security model across **Perimeter 1 (Identity & Federation)**, **Perimeter 2 (Network & Edge)**, **Perimeter 3 (Application RBAC, State-Guard & Separation of Duties)**, **Perimeter 4 (AI Trust Layer & Zero-Leak Data Privacy)**, and **Perimeter 5 (Data Encryption, Secrets & Continuous Compliance)**.)*

![Security Architecture](diagrams/security_architecture.png)

<details>
<summary>Architecture Diagram Specification (parsed by 04/scripts/extract_contracts.py into diagrams/security_architecture.png)</summary>

```diagram-dsl
flowchart TB
    %% title: Employee Leave Request Portal — Zero-Trust & AI Security Architecture
    %% subtitle: 5-Layer Defense-in-Depth across Identity, Edge, Application RBAC, AI Trust Layer, and Data Encryption
    subgraph SG_Layer1["Perimeter 1 — Identity, Authentication & Access Federation"]
        L1_1["<b>Corporate OIDC / SAML 2.0</b><br/>Single Sign-On Federation"]:::secCard
        L1_2["<b>Multi-Factor Auth (MFA)</b><br/>Step-Up Auth for Approvers"]:::secCard
        L1_3["<b>Short-Lived JWT Claims</b><br/>Signed Persona &amp; Dept Scopes"]:::secCard
        L1_4["<b>Workload Identity (OIDC)</b><br/>Keyless Service-to-Service IAM"]:::secCard
    end

    subgraph SG_Layer2["Perimeter 2 — Network & Zero-Trust Edge Security"]
        L2_1["<b>Global WAF &amp; DDoS Shield</b><br/>OWASP Top-10 &amp; Rate Limiting"]:::secCard
        L2_2["<b>TLS 1.3 &amp; HSTS Edge</b><br/>Strict Transport Encryption"]:::secCard
        L2_3["<b>Service Mesh STRICT mTLS</b><br/>Mutual TLS Pod-to-Pod"]:::secCard
        L2_4["<b>Private Subnets &amp; No Public IPs</b><br/>Isolated Compute &amp; DB Tiers"]:::secCard
    end

    subgraph SG_Layer3["Perimeter 3 — Application RBAC, State-Guard & Separation of Duties"]
        L3_1["<b>Persona RBAC Matrix</b><br/>Employee · Manager · HR Scopes"]:::secCard
        L3_2["<b>Lifecycle State Guard</b><br/>Blocks Illegal Transitions (409)"]:::secCard
        L3_3["<b>No Self-Approval Guard</b><br/>Requester != Approver Check"]:::secCard
        L3_4["<b>Parameterized SQL Queries</b><br/>SQLi &amp; CSRF Prevention"]:::secCard
    end

    subgraph SG_Layer4["Perimeter 4 — AI Trust Layer & Zero-Leak Data Privacy"]
        L4_1["<b>Zero-Leak DTO Serializer</b><br/>No Raw Columns or Enum Codes"]:::secCard
        L4_2["<b>PII &amp; Medical Redaction</b><br/>Role-Based Field Masking"]:::secCard
        L4_3["<b>AI Prompt &amp; RAG Guardrails</b><br/>PII Stripping &amp; Citation Lock"]:::secCard
        L4_4["<b>Human-in-the-Loop Gate</b><br/>AI Never Mutates Leave State"]:::secCard
    end

    subgraph SG_Layer5["Perimeter 5 — Data Encryption, Secrets Management & Continuous Compliance"]
        L5_1["<b>KMS Envelope Encryption</b><br/>AES-256 CMEK at Rest"]:::secCard
        L5_2["<b>Secrets Manager Vault</b><br/>Zero Hardcoded Credentials"]:::secCard
        L5_3["<b>OPA Policy Controller</b><br/>Rootless &amp; Read-Only FS Admission"]:::secCard
        L5_4["<b>Immutable SIEM Audit</b><br/>Tamper-Evident Security Logs"]:::secCard
    end

    SG_Layer1 ==> SG_Layer2 ==> SG_Layer3 ==> SG_Layer4 ==> SG_Layer5

    classDef secCard fill:#FFFFFF,stroke:#3C4043,stroke-width:1.5px,color:#202124;
```

</details>

---

## 2. Role-Based Access Control (RBAC) & Separation-of-Duties Matrix

| Business Persona | Authentication & Scope | Permitted Views | Permitted Workflow Actions | Prohibited Actions & Separation-of-Duties Guards |
| :-- | :-- | :-- | :-- | :-- |
| **Employee** | Corporate OIDC + Employee ID claim | Employee Leave Workspace, Personal Balance & History | Create Draft, Submit Request, Withdraw/Cancel Own Request, Resubmit Returned Request | Cannot view other employees' requests; cannot approve, reject, or return any request (`403 Forbidden`) |
| **Line Manager** | Corporate OIDC + Manager Role + MFA | Manager Review Queue, Team Calendar, Own Leave Workspace | Approve, Return for Correction, or Reject direct-report requests (`<= 10` working days); Escalate extended leave | **No Self-Approval Guard:** Cannot approve, return, or reject their own leave request (`403 Forbidden`) |
| **HR Administrator** | Corporate OIDC + HR Role + MFA | HR Oversight Console, Extended Leave Queue, Payroll Retry, Audit Trail | Adjudicate extended/exception leave (`> 10` working days), retry failed payroll postings, inspect audit trail | Cannot bypass immutable audit logging or mutate historical `request_state_change` rows |

---

## 3. AI Trust Layer & Zero-Leak Privacy Controls

| Control Domain | Threat / Risk Mitigated | Enforcement Mechanism | Verification Gate |
| :-- | :-- | :-- | :-- |
| **Zero-Leak DTO Boundary** | Leaking internal SQL column names (`employee_ref`, `leave_type_code`) or raw enum codes (`PENDING_HR`) in UI | Dedicated ViewModel/DTO mapper converts all status codes and errors into human-readable labels | `TC-UI-LEAK-01..04` in Stage 6 (`07/scripts/run_closed_loop_eval.py`) |
| **AI Prompt & RAG Privacy** | Sensitive medical reasons or employee PII sent to external LLM endpoints | Pre-prompt PII redaction strips personal identifiers; RAG retrieves only public HR leave handbook policies | Static & runtime security checks |
| **Human-in-the-Loop Governance** | Autonomous AI agent approving or rejecting leave without human accountability | AI Copilot is strictly advisory (`read-only`); all state transitions require authenticated human actor JWT | Backend state-transition guard (`403`/`409`) |
