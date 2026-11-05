# Logical Solution Architecture (`design/logical_architecture.md`)

- **Project:** Employee Leave Request Portal (`SCENARIO_REQUIREMENTS_DOC`)
- **Perspective:** **Logical Business Capability & Functional Domain Architecture** (Standalone Perspective Artifact 3 of 7)
- **Visual Renderer:** `design/diagrams/logical_architecture.svg` (`.png`) — Concentric Multi-Zone Functional Topology
- **Architecture Portfolio Index:** [`design/architecture_design.md`](architecture_design.md)

---

## 1. Logical Solution Architecture (Business Personas, User Experience Channels, Domain Policy Core, Business Capabilities & Domain Data Stores)

*(Depicts the Employee Leave Request Portal's cloud-agnostic **Business Capability & Functional Domain Architecture**: Business Personas (`Employee`, `Line Manager`, `HR Administrator`) in the left `#F1F3F4` column, User Experience Channels & Data Privacy Gateway in Column 1, Core Leave Policy & Calculation Orchestration in Column 2 with red dashed policy-rejection feedback, and the 3×3 grid of Business Capability Services and Logical Domain Data Stores in Column 3.)*

![Logical Solution Architecture](diagrams/logical_architecture.png)

<details>
<summary>Architecture Diagram Specification (parsed by 04/scripts/extract_contracts.py into diagrams/logical_architecture.png)</summary>

```diagram-dsl
flowchart LR
    subgraph SG_OnPrem["Business Personas & Actors"]
        P_EMP["<b>Employee</b><br/>Request &amp; Cancel Leave"]:::gcpCard
        P_MGR["<b>Line Manager</b><br/>Team Review &amp; Approval"]:::gcpCard
        P_HR["<b>HR Administrator</b><br/>Extended Leave &amp; Policy"]:::gcpCard
    end

    subgraph SG_TargetPlatform["Enterprise Target Architecture — Employee Leave Portal Logical Business Capability View"]
        subgraph SG_Edge["User Experience & Channel Capabilities"]
            UI_EMP["<b>Employee Self-Service</b><br/>Leave Request &amp; Balance UI"]:::gcpCard
            UI_MGR["<b>Manager Review Queue</b><br/>Team Calendar &amp; Approvals"]:::gcpCard
            UI_HR["<b>HR Oversight Console</b><br/>Extended Leave &amp; Audits"]:::gcpCard
            UI_DTO["<b>Data Privacy Gateway</b><br/>PII Masking &amp; Formatting"]:::gcpCard
        end

        subgraph SG_HubPerimeter["Core Leave Domain Orchestration Perimeter"]
            subgraph SG_HubProject["Core Leave Domain Orchestration & Business Policy Engine"]
                subgraph SG_SharedVPC["Stateless Workflow, Access Control & Leave Calculation Plane"]
                    subgraph SG_Region1["Identity, Access & Workflow Orchestration"]
                        RBAC["<b>Role-Based Access Control</b><br/>Persona Authorization"]:::gcpCard
                        STATE["<b>Leave Lifecycle Engine</b><br/>Workflow Orchestration"]:::gcpCard
                        subgraph SG_Subnet1["Separation of Duties"]
                            GUARD1["<b>No Self-Approval</b><br/>&amp; Eligibility Policy Gate"]:::focal
                        end
                    end
                    subgraph SG_Region2["Leave Accrual & Business Rules Engine"]
                        CALC["<b>Working-Day Calculator</b><br/>Weekdays &amp; Holidays"]:::gcpCard
                        INVAR["<b>Balance &amp; Overlap Engine</b><br/>Accrual &amp; Date Checks"]:::gcpCard
                        subgraph SG_Subnet2["Escalation Gate"]
                            GUARD2["<b>Extended Leave HR Gate</b><br/>Escalation Policy Gate"]:::focal
                        end
                    end
                end
            end
        end

        subgraph SG_SpokePerimeter["Business Capability Services & Logical Domain Data Stores"]
            subgraph SG_ProdRow["Core Leave Management Capabilities"]
                CAP_IN["<b>Leave Request Intake</b><br/>Drafting &amp; Submission"]:::gcpCard
                CAP_BAL["<b>Balance &amp; Accrual</b><br/>Entitlement Calculation"]:::gcpCard
                CAP_CAN["<b>Leave Cancellation</b><br/>Withdrawal &amp; Re-Credit"]:::gcpCard
            end
            subgraph SG_NonProdRow["Supervisory, HR & Notification Capabilities"]
                CAP_MGR["<b>Managerial Review</b><br/>Approval &amp; Rejection"]:::gcpCard
                CAP_HR["<b>HR Extended Review</b><br/>Escalation &amp; Exceptions"]:::gcpCard
                CAP_HOL["<b>Holiday &amp; Notifications</b><br/>Corporate Calendar &amp; Alerts"]:::gcpCard
            end
            subgraph SG_DevRow["Logical Domain Data Stores"]
                REPO_EMP["<b>Employee &amp; Balance Store</b><br/>Profiles &amp; Entitlements"]:::gcpCard
                REPO_REQ["<b>Leave Request Store</b><br/>Requests &amp; Leave Types"]:::gcpCard
                REPO_AUD["<b>Audit &amp; Calendar Store</b><br/>Immutable History &amp; Holidays"]:::gcpCard
            end
        end
    end

    P_EMP ==>|"Draft / Submit"| UI_EMP
    P_MGR ==>|"Review / Decide"| UI_MGR
    P_HR ==>|"Escalation Review"| UI_HR
    UI_EMP --> UI_DTO
    UI_MGR --> UI_DTO
    UI_HR --> UI_DTO
    UI_DTO ==>|"Business Command"| RBAC
    UI_DTO ==>|"Date Range Request"| CALC
    RBAC --> STATE
    STATE ==>|"Verified State"| GUARD1
    CALC --> INVAR
    INVAR ==>|"Verified Balance"| GUARD2
    RBAC -.->|"Policy Rejection: Unauthorized | Invalid State | Balance Alert"| P_EMP
    GUARD1 ==>|"Capability Dispatch"| CAP_IN
    GUARD1 ==>|"Capability Dispatch"| CAP_MGR
    GUARD2 ==>|"Domain Persistence"| REPO_EMP
    CAP_IN --> CAP_BAL
    CAP_BAL --> CAP_CAN
    CAP_MGR --> CAP_HR
    CAP_HR --> CAP_HOL
    REPO_EMP --> REPO_REQ
    REPO_REQ --> REPO_AUD

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

</details>

---

## 2. Logical Functional Zone & Capability Responsibilities

| Logical Architecture Zone | Logical Components | Functional Responsibility | Domain Policy Enforced |
| :-- | :-- | :-- | :-- |
| **1. Business Personas & Actors** | `Employee`, `Line Manager`, `HR Administrator` | Initiates leave intake, supervisory review, and HR exception workflows | Role-scoped access and separation of duties |
| **2. User Experience & Channel Capabilities** | `Employee Self-Service`, `Manager Review Queue`, `HR Oversight Console`, `Data Privacy Gateway` | Role-tailored workspaces and outbound PII masking / human-readable label mapping | Zero internal column names or enum codes in UI (`_shared/zero_leak.md`) |
| **3. Core Leave Domain Orchestration & Policy Engine** | `Role-Based Access Control`, `Leave Lifecycle Engine`, `No Self-Approval Gate`, `Working-Day Calculator`, `Balance & Overlap Engine`, `Extended Leave HR Gate` | Evaluates lifecycle state transitions, separation of duties, working-day durations, and HR escalation rules | Rejects illegal transitions (`409`), unauthorized roles (`403`), and balance/overlap violations (`422`) |
| **4. Business Capability Services & Logical Stores** | `Leave Request Intake`, `Balance & Accrual`, `Leave Cancellation`, `Managerial Review`, `HR Extended Review`, `Holiday & Notifications`, plus 3 Logical Stores | Executes bounded leave capabilities and persists state changes with append-only audit trails | Transactional consistency across requests, balances, and audit records |
