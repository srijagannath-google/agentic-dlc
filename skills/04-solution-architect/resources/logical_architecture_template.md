# Logical Architecture (`design/logical_architecture.md`)

- **Perspective:** **Logical Architecture (Technology-Agnostic Domain Capabilities, Policy Orchestration & Logical Information Stores)**
- **Visual Archetype:** Concentric Multi-Zone Functional Topology (`diagrams/logical_architecture.svg`)
- **Architecture Portfolio Index:** [`design/architecture_design.md`](architecture_design.md)

---

## 1. Logical Solution Architecture Diagram

![Logical Solution Architecture](diagrams/logical_architecture.svg)

```mermaid
flowchart LR
    subgraph SG_OnPrem["Business Personas & Actors"]
        P1["<b>&lt;Business Persona 1&gt;</b><br/>&lt;Business Role&gt;"]:::gcpCard
        P2["<b>&lt;Business Persona 2&gt;</b><br/>&lt;Business Role&gt;"]:::gcpCard
        P3["<b>&lt;Business Persona 3&gt;</b><br/>&lt;Business Role&gt;"]:::gcpCard
    end

    subgraph SG_TargetPlatform["Enterprise Target Architecture — Logical Business Capability View"]
        subgraph SG_Edge["User Experience & Channel Capabilities"]
            UI1["<b>&lt;User Self-Service Portal&gt;</b><br/>Intake &amp; Status Tracking"]:::gcpCard
            UI2["<b>&lt;Reviewer Triage Console&gt;</b><br/>Queue &amp; Decision Workflow"]:::gcpCard
            UI3["<b>&lt;Admin Oversight Portal&gt;</b><br/>Policy &amp; Reporting"]:::gcpCard
            UI4["<b>Data Privacy Gateway</b><br/>PII Masking &amp; Formatting"]:::gcpCard
        end

        subgraph SG_HubPerimeter["Core Domain Orchestration Perimeter"]
            subgraph SG_HubProject["Core Domain Orchestration & Business Policy Engine"]
                subgraph SG_SharedVPC["Stateless Workflow, Access Control & Calculation Plane"]
                    subgraph SG_Region1["Identity, Access & Workflow Orchestration"]
                        RBAC["<b>Role-Based Access Control</b><br/>Persona Authorization"]:::gcpCard
                        STATE["<b>Lifecycle Workflow Engine</b><br/>State Orchestration"]:::gcpCard
                        subgraph SG_Subnet1["Eligibility Gate"]
                            GUARD1["<b>Status &amp; Prerequisite</b><br/>Transition Policy Gate"]:::focal
                        end
                    end
                    subgraph SG_Region2["Business Rules & Financial Calculation Engine"]
                        CALC["<b>Fee &amp; Financial Engine</b><br/>Rates, Balances &amp; Totals"]:::gcpCard
                        INVAR["<b>Domain Compliance Engine</b><br/>Eligibility &amp; Thresholds"]:::gcpCard
                        subgraph SG_Subnet2["Compliance Gate"]
                            GUARD2["<b>Regulatory &amp; Audit</b><br/>Compliance Policy Gate"]:::focal
                        end
                    end
                end
            end
        end

        subgraph SG_SpokePerimeter["Business Capability Services & Logical Domain Data Stores"]
            subgraph SG_ProdRow["Core Business Capability Services"]
                CAP1["<b>&lt;Business Capability 1&gt;</b><br/>&lt;Functional Scope&gt;"]:::gcpCard
                CAP2["<b>&lt;Business Capability 2&gt;</b><br/>&lt;Functional Scope&gt;"]:::gcpCard
                CAP3["<b>&lt;Business Capability 3&gt;</b><br/>&lt;Functional Scope&gt;"]:::gcpCard
            end
            subgraph SG_NonProdRow["Supporting & Shared Business Capabilities"]
                CAP4["<b>&lt;Business Capability 4&gt;</b><br/>&lt;Functional Scope&gt;"]:::gcpCard
                CAP5["<b>&lt;Business Capability 5&gt;</b><br/>&lt;Functional Scope&gt;"]:::gcpCard
                SHARED_SVC["<b>Notifications &amp; Documents</b><br/>Alerts &amp; Certificates"]:::gcpCard
            end
            subgraph SG_DevRow["Logical Domain Data Stores"]
                REPO1["<b>&lt;Primary Domain Store&gt;</b><br/>Core Business Entities"]:::gcpCard
                REPO2["<b>&lt;Financial Ledger Store&gt;</b><br/>Transactions &amp; Balances"]:::gcpCard
                REPO3["<b>Audit &amp; Document Archive</b><br/>Immutable History &amp; Files"]:::gcpCard
            end
        end
    end

    P1 ==>|"Self-Service"| UI1
    P2 ==>|"Case Review"| UI2
    P3 ==>|"Administration"| UI3
    UI1 --> UI4
    UI2 --> UI4
    UI3 --> UI4
    UI4 ==>|"Business Command"| RBAC
    UI4 ==>|"Calculation Request"| CALC
    RBAC --> STATE
    STATE ==>|"Verified State"| GUARD1
    CALC --> INVAR
    INVAR ==>|"Verified Rule"| GUARD2
    RBAC -.->|"Policy Rejection: Unauthorized | Invalid State | Rule Alert"| P1
    GUARD1 ==>|"Capability Dispatch"| CAP1
    GUARD1 ==>|"Capability Dispatch"| CAP4
    GUARD2 ==>|"Domain Persistence"| REPO1
    CAP1 --> CAP2
    CAP2 --> CAP3
    CAP4 --> CAP5
    CAP5 --> SHARED_SVC
    REPO1 --> REPO2
    REPO2 --> REPO3

    classDef gcpCard fill:#FFFFFF,stroke:#3C4043,stroke-width:1.5px,color:#202124;
    classDef focal fill:#FFFFFF,stroke:#1A73E8,stroke-width:2.5px,color:#202124,font-weight:bold;
    classDef gcpBlue fill:#E8F0FE,stroke:#1967D2,stroke-width:1.5px,color:#202124;
    classDef gcpGreen fill:#E6F4EA,stroke:#1E8E3E,stroke-width:1.5px,color:#202124;
    classDef gcpYellow fill:#FEF7E0,stroke:#B06000,stroke-width:1.5px,color:#202124;
    classDef gcpRed fill:#FCE8E6,stroke:#D93025,stroke-width:1.5px,color:#202124;

    style SG_OnPrem fill:#F1F3F4,stroke:#9AA0A6,stroke-width:1.5px,color:#202124
    style SG_TargetPlatform fill:#FFFFFF,stroke:#1A73E8,stroke-width:3px,color:#1A73E8
    style SG_Edge fill:#FFFFFF,stroke:#DADCE0,stroke-width:1px,color:#3C4043
    style SG_HubPerimeter fill:#FFFFFF,stroke:#5F6368,stroke-dasharray: 4 4,stroke-width:1.5px,color:#3C4043
    style SG_HubProject fill:#F1F3F4,stroke:#5F6368,stroke-width:1.5px,color:#202124
    style SG_SharedVPC fill:#AECBFA,stroke:#4285F4,stroke-width:1.5px,color:#202124
    style SG_Region1 fill:#F1F3F4,stroke:#7F868D,stroke-width:1.5px,color:#202124
    style SG_Region2 fill:#F1F3F4,stroke:#7F868D,stroke-width:1.5px,color:#202124
    style SG_Subnet1 fill:#AECBFA,stroke:#4285F4,stroke-width:1.5px,color:#202124
    style SG_Subnet2 fill:#AECBFA,stroke:#4285F4,stroke-width:1.5px,color:#202124
    style SG_SpokePerimeter fill:#FFFFFF,stroke:#5F6368,stroke-dasharray: 4 4,stroke-width:1.5px,color:#3C4043
    style SG_ProdRow fill:#F1F3F4,stroke:#9AA0A6,stroke-width:1.5px,color:#202124
    style SG_NonProdRow fill:#F1F3F4,stroke:#9AA0A6,stroke-width:1.5px,color:#202124
    style SG_DevRow fill:#F1F3F4,stroke:#9AA0A6,stroke-width:1.5px,color:#202124
```

---

## 2. Logical Domain Boundary & Functional Decomposition

| Logical Zone | Bounded Functional Components | Domain Responsibility |
| :-- | :-- | :-- |
| **User Experience & Channel Zone** | Self-Service Portal, Reviewer Triage Console, Admin Oversight Portal, Data Privacy Gateway | Presents role-scoped views and masks sensitive internal identifiers |
| **Core Domain Orchestration & Policy Zone** | Role-Based Access Control, Lifecycle Workflow Engine, Financial/Business Rules Engine, Eligibility & Compliance Gates | Enforces state-machine transitions and deterministic business calculations before persistence |
| **Business Capability Services Zone** | Core & Supporting Domain Capability Services | Implements bounded functional operations for each business value stream |
| **Logical Domain Data Stores Zone** | Primary Domain Store, Financial Ledger Store, Audit & Document Archive | Maintains domain entities, financial records, and immutable history |
