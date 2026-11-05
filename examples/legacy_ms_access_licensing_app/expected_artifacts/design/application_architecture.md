# Application Architecture (`design/application_architecture.md`)

- **Project:** Business Licensing & Renewal Portal — Legacy MS Access Modernization (`SCENARIO_LEGACY_APP`)
- **Perspective:** **Application Component & Service Architecture (C4 Component View & Runtime Sequence)** (Standalone Perspective Artifact 4 of 7)
- **Visual Renderer:** `design/diagrams/application_architecture.svg` (`.png`) — 4-Tier C4 Application & AI Component Topology
- **Architecture Portfolio Index:** [`design/architecture_design.md`](architecture_design.md)

---

## 1. Application Component & Service Topology (4-Tier C4 Component View)

*(Depicts the application's internal modular structure across **Tier 1 (Presentation & Omnichannel UI Modules)**, **Tier 2 (API Gateway, BFF & Zero-Leak DTO Tier)**, **Tier 3 (Core Domain & AI Agent Services Tier)**, and **Tier 4 (Data Access, Event Bus & Integration Adapters Tier)**.)*

![Application Architecture](diagrams/application_architecture.png)

<details>
<summary>Architecture Diagram Specification (parsed by 04/scripts/extract_contracts.py into diagrams/application_architecture.png)</summary>

```diagram-dsl
flowchart TB
    %% title: Business Licensing & Renewal Portal — Application Component Architecture
    %% subtitle: 4-Tier Modular Application, BFF/DTO Boundary, Domain & AI Services, and Repository Adapters
    subgraph SG_Tier1["Tier 1 — Presentation & Omnichannel UI Modules (WCAG 2.1 AA · Material 3 Tokens)"]
        UI1["<b>Applicant Filing Portal</b><br/>Application, Bond &amp; Fee UI"]:::appCard
        UI2["<b>Staff Compliance Console</b><br/>Review Queue &amp; Decision Modal"]:::appCard
        UI3["<b>Certificate &amp; Agent Card UI</b><br/>Printable License &amp; ID Cards"]:::appCard
        UI4["<b>Statute AI Copilot Drawer</b><br/>Cited Licensing Q&amp;A Assistant"]:::appCard
    end

    subgraph SG_Tier2["Tier 2 — API Gateway, BFF & Zero-Leak ViewModel/DTO Tier (OpenAPI 3.1)"]
        API1["<b>REST API Router</b><br/>OpenAPI 3.1 Request Dispatch"]:::appCard
        API2["<b>Zero-Leak DTO Serializer</b><br/>Tax ID Masking &amp; Enum Labels"]:::appCard
        API3["<b>RBAC &amp; State Guard Filter</b><br/>Buyer vs Staff Scope Check"]:::appCard
        API4["<b>Validation &amp; Error Mapper</b><br/>Structured 403/409/422 Alerts"]:::appCard
    end

    subgraph SG_Tier3["Tier 3 — Core Licensing Domain & AI Agent Services Tier (Stateless Business Logic)"]
        SVC1["<b>License Lifecycle Service</b><br/>State Machine Orchestrator"]:::appCard
        SVC2["<b>Bond &amp; Fee Calculation Engine</b><br/>Surety Bond &amp; Quarterly Fees"]:::appCard
        SVC3["<b>Licensing Statute AI Agent</b><br/>Grounded Regulatory RAG"]:::appCard
        SVC4["<b>Good-Standing &amp; Agent Service</b><br/>Suspension &amp; Age Validation"]:::appCard
    end

    subgraph SG_Tier4["Tier 4 — Data Access, Document Store & Integration Adapters Tier"]
        DAO1["<b>Licensing 3NF Repository</b><br/>ACID SQL Unit-of-Work"]:::appCard
        DAO2["<b>Supporting Document Adapter</b><br/>MIME &amp; Size Validated Store"]:::appCard
        DAO3["<b>Tax ID Crypto Adapter</b><br/>SHA-256 Hash &amp; Last-4 Mask"]:::appCard
        DAO4["<b>Immutable Audit Appender</b><br/>Append-Only Event Ledger"]:::appCard
    end

    SG_Tier1 ==>|"HTTPS JSON / Action Triggers"| SG_Tier2
    SG_Tier2 ==>|"Validated Domain Commands"| SG_Tier3
    SG_Tier3 ==>|"Transactional Repository Calls"| SG_Tier4

    classDef appCard fill:#FFFFFF,stroke:#1A73E8,stroke-width:1.5px,color:#202124;
```

</details>

---

## 2. End-to-End Request & Workflow Execution Sequence (`sequenceDiagram`)

```mermaid
sequenceDiagram
    autonumber
    box rgb(241, 243, 244) External Client Zone
        actor User as 👤 Authenticated Persona (Applicant / Reviewer / Supervisor)
    end
    box rgb(232, 240, 254) Zero-Trust Edge & Web Tier Zone
        participant UI as 💻 Kubernetes Web Tier & Privacy Gateway
        participant IAP as 🛡️ Global L7 Load Balancer / WAF / OIDC Proxy
    end
    box rgb(232, 240, 254) Kubernetes Application & Licensing Policy Zone
        participant WF as ⚙️ Kubernetes Application Tier (Licensing Workflow & Fee Engine)
    end
    box rgb(230, 244, 234) Managed Database & OpenTelemetry Zone
        participant DB as 🗄️ PgBouncer & Managed Relational DB
        participant OTEL as 📊 OpenTelemetry Collector, Tracing & SLO Alerting
    end

    User->>UI: Trigger licensing action (Submit / Approve / Issue Certificate)
    UI->>IAP: HTTPS REST request (OIDC token / role claims)

    rect rgb(232, 240, 254)
        Note over IAP,WF: Phase 1 — Zero-Trust Identity, Access Control & Licensing Policy Gate
        IAP->>WF: Forward verified identity + evaluate role authorization, lifecycle state & fee/compliance rules
    end

    alt Unauthorized Role, Disallowed Lifecycle Transition, or Compliance Rule Violation
        rect rgb(255, 235, 238)
            WF-->>IAP: Reject (403 Forbidden / 409 Invalid Transition / 422 Compliance Rule Violation)
            IAP-.->OTEL: Export structured security event via OpenTelemetry OTLP
            IAP-->>UI: Structured Error Response {message: human-readable guidance}
            UI-->>User: Render accessible alert banner (zero legacy system codes leaked)
        end
    else Authorized & All Licensing Policies Satisfied
        rect rgb(230, 255, 230)
            Note over WF,DB: Phase 2 — Atomic Relational Transaction, Certificate Issuance & Masked Response
            WF->>DB: BEGIN -> UPDATE application & payment records + INSERT immutable audit record -> COMMIT
            DB-->>WF: Committed domain state
            WF-.->OTEL: Export trace span & latency metric via OpenTelemetry OTLP
            WF-->>UI: Mask Tax ID (***-**-1234) & format human-readable status labels
            UI-->>User: Render updated status badge, live fee breakdown & printable certificate view
        end
    end
```

---

## 3. Application Component Responsibilities & Guardrails

| Application Tier | Component | Runtime & Pattern | Input / Output Contract | Guardrail Enforced |
| :-- | :-- | :-- | :-- | :-- |
| **Tier 1 — Presentation** | `Applicant Filing Portal`, `Staff Compliance Console`, `Certificate & Agent Card UI`, `Statute AI Copilot Drawer` | Semantic HTML5 + Vanilla ES2022 (`static-html`) | Consumes Zero-Leak DTO JSON; emits user actions | Mutual tab exclusivity; role-gated action visibility; zero legacy MS Access form/table names |
| **Tier 2 — API & DTO** | `REST API Router`, `Zero-Leak DTO Serializer`, `RBAC & State Guard Filter`, `Validation & Error Mapper` | Python 3.11 HTTP/REST (`python-stdlib-http`) | OpenAPI 3.1 request/response schemas | Strips `tax_id_hash` (`x-internal: true`); exposes only masked `***-**-1234` |
| **Tier 3 — Domain & AI** | `License Lifecycle Service`, `Bond & Fee Calculation Engine`, `Licensing Statute AI Agent`, `Good-Standing & Agent Service` | Stateless Domain Services | Domain command objects & validated state transitions | Enforces surety bond formula (`max(10000, min(100000, round(0.10 * purchases)))`), 1.5% quarterly fee, and age `>= 18` |
| **Tier 4 — Data & Adapters** | `Licensing 3NF Repository`, `Supporting Document Adapter`, `Tax ID Crypto Adapter`, `Immutable Audit Appender` | Parameterized SQL + Document Store | ACID transactions + append-only audit rows | Zero string-interpolated SQL; transactional audit logging on every state change |
