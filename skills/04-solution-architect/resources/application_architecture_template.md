# Application Architecture (`design/application_architecture.md`)

- **Perspective:** **Application & AI Service Architecture (C4 Component Topology, API/BFF Layer, Domain & Agentic Services, and Request Execution Sequence)**
- **Visual Archetype:** 4-Tier Application Component Topology (`diagrams/application_architecture.svg`) + End-to-End `sequenceDiagram`
- **Architecture Portfolio Index:** [`design/architecture_design.md`](architecture_design.md)

---

## 1. Multi-Tier Application & AI Component Architecture

![Application Architecture](diagrams/application_architecture.svg)

```mermaid
flowchart TB
    %% title: <Application Name> — Application & AI Component Architecture
    subgraph SG_Presentation["1. Presentation &amp; Omnichannel Experience Tier (Frontend UI Modules)"]
        UI_MOD1["<b>&lt;Self-Service Workspace&gt;</b><br/>Guided Forms &amp; Live Preview"]
        UI_MOD2["<b>&lt;Operations Review Queue&gt;</b><br/>Master-Detail Review Console"]
        UI_MOD3["<b>&lt;Executive Analytics View&gt;</b><br/>KPI Cards &amp; Audit Explorer"]
        UI_MOD4["<b>&lt;AI Copilot Assistant Panel&gt;</b><br/>Contextual Policy Guidance"]
        UI_MOD5["<b>&lt;Design System &amp; A11y Core&gt;</b><br/>M3 Tokens &amp; WCAG 2.1 AA"]
    end

    subgraph SG_APIGateway["2. API Gateway, BFF &amp; Contract Mediation Tier (OpenAPI 3.1)"]
        API_RTR["<b>OpenAPI 3.1 REST Router</b><br/>Endpoint Dispatch &amp; Versioning"]
        API_VAL["<b>Request Schema Validator</b><br/>Strict Payload &amp; Enum Checks"]
        API_DTO["<b>Zero-Leak DTO Projector</b><br/>PII Masking &amp; Label Mapping"]
        API_ERR["<b>Structured Error Handler</b><br/>Human-Readable 403/409/422"]
    end

    subgraph SG_AppServices["3. Core Domain Application &amp; AI Agent Services Tier"]
        SVC_WF["<b>Lifecycle State Orchestrator</b><br/>Deterministic Transition Table"]
        SVC_RULE["<b>Business Rules &amp; Math Engine</b><br/>Rates, Balances &amp; Thresholds"]
        SVC_DOM1["<b>&lt;Primary Domain Service&gt;</b><br/>Intake, Amendments &amp; Cancellation"]
        SVC_DOM2["<b>&lt;Review &amp; Issuance Service&gt;</b><br/>Triage, Escalation &amp; Approval"]
        SVC_AI["<b>AI Agent &amp; Policy RAG Service</b><br/>Grounded Recommendations"]
    end

    subgraph SG_IntegrationData["4. Data Access, Event Bus &amp; Enterprise Integration Tier"]
        DAL_UOW["<b>Transactional Unit-of-Work</b><br/>ACID Commit &amp; Rollback"]
        DAL_AUD["<b>Immutable Audit Writer</b><br/>Append-Only Lifecycle Log"]
        DAL_EVT["<b>Domain Event Publisher</b><br/>Notifications &amp; Webhooks"]
        DAL_EXT["<b>Enterprise System Adapters</b><br/>SSO, Payment &amp; Document I/O"]
    end

    SG_Presentation ==> SG_APIGateway
    SG_APIGateway ==> SG_AppServices
    SG_AppServices ==> SG_IntegrationData

    style SG_Presentation fill:#E8F0FE,stroke:#1A73E8,stroke-width:2px,color:#174EA6
    style SG_APIGateway fill:#E0F2FE,stroke:#0284C7,stroke-width:2px,color:#0369A1
    style SG_AppServices fill:#F0FDF4,stroke:#16A34A,stroke-width:2px,color:#15803D
    style SG_IntegrationData fill:#FEF3C7,stroke:#D97706,stroke-width:2px,color:#B45309
```

---

## 2. End-to-End Request & Workflow Execution Sequence

```mermaid
sequenceDiagram
    autonumber
    box rgb(241, 243, 244) External Client Zone
        actor User as 👤 Authenticated Business Persona
    end
    box rgb(232, 240, 254) Zero-Trust Edge & Web Tier Zone
        participant UI as 💻 Kubernetes Web Tier & Privacy Gateway
        participant IAP as 🛡️ Global L7 Load Balancer / WAF / OIDC Proxy
    end
    box rgb(232, 240, 254) Kubernetes Application & Domain Policy Zone
        participant WF as ⚙️ Kubernetes Application Tier (Workflow, Rules & AI Service)
    end
    box rgb(230, 244, 234) Managed Database & OpenTelemetry Zone
        participant DB as 🗄️ PgBouncer & Managed Relational Database
        participant OTEL as 📊 OpenTelemetry Collector, Tracing & SLO Alerting
    end

    User->>UI: Trigger business action in role-scoped workspace
    UI->>IAP: HTTPS REST request (OIDC token / role claims)

    rect rgb(232, 240, 254)
        Note over IAP,WF: Phase 1 — Zero-Trust Identity, Access Control & Workflow Policy Gate
        IAP->>WF: Forward verified identity + evaluate role authorization, lifecycle state & business rules
    end

    alt Unauthorized Role, Disallowed Lifecycle Transition, or Business Rule Violation
        rect rgb(255, 235, 238)
            WF-->>IAP: Reject (403 Forbidden / 409 Invalid Transition / 422 Business Rule Violation)
            IAP-.->OTEL: Export structured security event via OpenTelemetry OTLP
            IAP-->>UI: Structured Error Response {message: human-readable guidance}
            UI-->>User: Render accessible alert banner (zero internal system identifiers leaked)
        end
    else Authorized & All Domain Policies Satisfied
        rect rgb(230, 255, 230)
            Note over WF,DB: Phase 2 — Atomic Relational Transaction, Audit Append & Masked Response
            WF->>DB: BEGIN -> UPDATE domain record + INSERT immutable audit record -> COMMIT
            DB-->>WF: Committed domain state
            WF-.->OTEL: Export trace span & latency metric via OpenTelemetry OTLP
            WF-->>UI: Mask sensitive fields & format human-readable labels
            UI-->>User: Render updated status badge, live calculation summary & next eligible actions
        end
    end
```

---

## 3. Application Layering & Component Responsibilities

| Application Layer | Component / Module | Target Runtime (`target_stack.json`) | Interaction Pattern | Key Responsibilities & Guardrails |
| :-- | :-- | :-- | :-- | :-- |
| **1. Presentation & UX Tier** | Self-Service Workspace, Review Queue, Executive Analytics, AI Copilot Panel | `<frontend.kind>` | HTTPS / JSON REST | Renders role-separated views, live calculation previews, and accessible states |
| **2. API Gateway & BFF Tier** | OpenAPI 3.1 Router, Schema Validator, Zero-Leak DTO Projector | `<backend.kind>` | Synchronous REST | Enforces OpenAPI schema contracts and strips `x-internal` / raw PII fields |
| **3. Domain & AI Services Tier** | Lifecycle State Orchestrator, Business Rules Engine, Domain Services, AI RAG Service | `<backend.kind>` | In-Process / Service Mesh mTLS | Enforces state transition guards, deterministic calculations, and grounded AI assistance |
| **4. Data Access & Integration Tier** | Transactional Unit-of-Work, Immutable Audit Writer, Event Publisher | `<backend.kind>` + `<database.kind>` | ACID SQL Transactions & Async Events | Guarantees atomic state + audit commits and publishes domain notifications |
