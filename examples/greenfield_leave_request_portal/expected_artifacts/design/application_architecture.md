# Application Architecture (`design/application_architecture.md`)

- **Project:** Employee Leave Request Portal (Greenfield Requirements Specification)
- **Perspective:** **Application Component & Service Architecture (C4 Component View & Runtime Sequence)** (Standalone Perspective Artifact 4 of 7)
- **Visual Renderer:** `design/diagrams/application_architecture.svg` (`.png`) — 4-Tier C4 Application & AI Component Topology
- **Architecture Portfolio Index:** [`design/architecture_design.md`](architecture_design.md)

---

## 1. Application Component & Service Topology (4-Tier C4 Component View)

*(Depicts the application's internal modular structure across **Tier 1 (Presentation & Omnichannel UI Modules)**, **Tier 2 (API Gateway, BFF & Zero-Leak DTO Tier)**, **Tier 3 (Core Domain & AI Agent Services Tier)**, and **Tier 4 (Data Access, Event Bus & Integration Adapters Tier)**.)*

![Application Architecture](diagrams/application_architecture.png)

---

## 2. End-to-End Request & Workflow Execution Sequence (`sequenceDiagram`)

```mermaid
sequenceDiagram
    autonumber
    box rgb(241, 243, 244) External Client Zone
        actor User as 👤 Authenticated Persona (Employee / Manager / HR Admin)
    end
    box rgb(232, 240, 254) Zero-Trust Edge & Web Tier Zone
        participant UI as 💻 Kubernetes Web Tier & Privacy Gateway
        participant IAP as 🛡️ Global L7 Load Balancer / WAF / OIDC Proxy
    end
    box rgb(232, 240, 254) Kubernetes Application & Leave Policy Zone
        participant WF as ⚙️ Kubernetes Application Tier (Leave Workflow & Rules Engine)
    end
    box rgb(230, 244, 234) Managed Database & OpenTelemetry Zone
        participant DB as 🗄️ PgBouncer & Managed Relational DB
        participant OTEL as 📊 OpenTelemetry Collector, Tracing & SLO Alerting
    end

    User->>UI: Trigger leave action (Submit / Approve / Escalate)
    UI->>IAP: HTTPS REST request (OIDC token / role claims)

    rect rgb(232, 240, 254)
        Note over IAP,WF: Phase 1 — Zero-Trust Identity, Access Control & Leave Policy Gate
        IAP->>WF: Forward verified identity + evaluate role authorization, lifecycle state & leave balance rules
    end

    alt Unauthorized Role, Disallowed Lifecycle Transition, or Leave Rule Violation
        rect rgb(255, 235, 238)
            WF-->>IAP: Reject (403 Forbidden / 409 Invalid Transition / 422 Leave Rule Violation)
            IAP-.->OTEL: Export structured security event via OpenTelemetry OTLP
            IAP-->>UI: Structured Error Response {message: human-readable guidance}
            UI-->>User: Render accessible alert banner (zero internal system codes leaked)
        end
    else Authorized & All Leave Policies Satisfied
        rect rgb(230, 255, 230)
            Note over WF,DB: Phase 2 — Atomic Relational Transaction, Balance Update & Audit Append
            WF->>DB: BEGIN -> UPDATE leave request & balance + INSERT immutable audit record -> COMMIT
            DB-->>WF: Committed domain state
            WF-.->OTEL: Export trace span & latency metric via OpenTelemetry OTLP
            WF-->>UI: Format human-readable status & balance labels
            UI-->>User: Render updated status badge, live balance preview & next eligible actions
        end
    end
```

---

## 3. Application Component Responsibilities & Guardrails

| Application Tier | Component | Runtime & Pattern | Input / Output Contract | Guardrail Enforced |
| :-- | :-- | :-- | :-- | :-- |
| **Tier 1 — Presentation** | `Employee Leave Workspace`, `Manager Review Console`, `HR Exception Console`, `Leave Policy Copilot Drawer` | Semantic HTML5 + Vanilla ES2022 (`static-html`) | Consumes Zero-Leak DTO JSON; emits user actions | Mutual tab exclusivity; role-gated action visibility; zero dead controls |
| **Tier 2 — API & DTO** | `REST API Router`, `Zero-Leak DTO Serializer`, `RBAC & State Guard Filter`, `Validation & Error Mapper` | Python 3.11 HTTP/REST (`python-stdlib-http`) | OpenAPI 3.1 request/response schemas | Strips internal keys (`x-internal: true`); maps enum codes to human labels |
| **Tier 3 — Domain & AI** | `Leave Lifecycle Service`, `Accrual & Balance Engine`, `Leave Policy AI Agent`, `Supervisory Escalation Service` | Stateless Domain Services | Domain command objects & validated state transitions | Enforces `(fromState, trigger, role)` transition table and no-self-approval guard |
| **Tier 4 — Data & Adapters** | `Leave & Balance Repository`, `Payroll Webhook Adapter`, `Corporate Calendar Adapter`, `Immutable Audit Appender` | Parameterized SQL + REST Outbox | ACID transactions + append-only audit rows | Zero string-interpolated SQL; transactional audit logging on every state change |
