# Business Architecture & Capability Map (`design/business_architecture.md`)

- **Project:** Employee Leave Request Portal (`SCENARIO_REQUIREMENTS_DOC`)
- **Perspective:** **Business Architecture & Value-Stream Capability Map** (Standalone Perspective Artifact 1 of 7)
- **Visual Renderer:** `design/diagrams/business_capability_map.svg` (`.png`) — Value-Stream Chevrons + Core Capability Grid + Cross-Cutting Outcome Bar + Foundational Capabilities Matrix
- **Architecture Portfolio Index:** [`design/architecture_design.md`](architecture_design.md)

---

## 1. Business Architecture & Capability Map (Value Streams, Core Business Capabilities & Foundational Capabilities)

*(Depicts the Employee Leave Request Portal's cloud-agnostic **Business Architecture & Capability Map**: top horizontal Blue (`#4285F4`) Value-Stream Chevrons (`1. Employee Outreach & Leave Intake`, `2. Entitlement, Calendar & Policy Verification`, `3. Supervisory Review & HR Escalation Routing`, `4. Workforce Availability, Audit & Oversight`), multi-column Level-2 Core Business Capability cards in uniform `#EEEEEE` fill with `#202124` borders, a bottom Cross-Cutting Outcome bar (`:::capSpan`), and a full-width `Foundational Capabilities` banner above a 2×6 Foundational Capabilities grid.)*

![Business Capability Map](diagrams/business_capability_map.png)

<details>
<summary>Architecture Diagram Specification (parsed by 04/scripts/extract_contracts.py into diagrams/business_capability_map.png)</summary>

```diagram-dsl
flowchart TB
    %% title: Employee Leave Request Portal Capability Map
    subgraph VS1["1. Employee Outreach &amp; Leave Intake"]
        C1_1["Guided Leave Type Selection"]:::capCard
        C1_2["Draft Leave Request Entry"]:::capCard
        C1_3["Working-Day Duration Preview"]:::capCard
        C1_4["Request Modification &amp; Resubmission"]:::capCard
        C1_5["Self-Service Leave Cancellation"]:::capCard
    end

    subgraph VS2["2. Entitlement, Calendar &amp; Policy Verification"]
        subgraph VS2_A["Entitlement &amp; Balance"]
            C2_1["Annual Entitlement Tracking"]:::capCard
            C2_2["Real-Time Balance Projection"]:::capCard
            C2_3["Accrual &amp; Carryover Rules"]:::capCard
            C2_4["Balance Re-Credit on Cancellation"]:::capCard
            C2_5["Leave Quota &amp; Policy Directory"]:::capCard
        end
        subgraph VS2_B["Calendar &amp; Date Validation"]
            C2_6["Weekend &amp; Public Holiday Exclusion"]:::capCard
            C2_7["Overlapping Request Detection"]:::capCard
            C2_8["Regional Holiday Schedule Sync"]:::capCard
            C2_9["Team Absence Coverage View"]:::capCard
        end
    end

    subgraph VS3["3. Supervisory Review &amp; HR Escalation Routing"]
        subgraph VS3_A["Line Manager Triage"]
            C3_1["Manager Pending Review Queue"]:::capCard
            C3_2["Separation-of-Duties Guard"]:::capCard
            C3_3["Managerial Approval &amp; Rejection"]:::capCard
            C3_4["Decision Rationale Capture"]:::capCard
        end
        subgraph VS3_B["HR Extended Leave Escalation"]
            C3_5["Extended Leave Threshold Detection"]:::capCard
            C3_6["HR Escalation Queue Routing"]:::capCard
            C3_7["HR Final Adjudication"]:::capCard
            C3_8["Medical &amp; Policy Exception Review"]:::capCard
        end
    end

    subgraph VS4["4. Workforce Availability, Audit &amp; Oversight"]
        subgraph VS4_A["Workforce Analytics"]
            C4_1["Departmental Leave Utilization"]:::capCard
            C4_2["Peak Absence Forecasting"]:::capCard
            C4_3["Employee Leave History Ledger"]:::capCard
            C4_4["SLA &amp; Turnaround Tracking"]:::capCard
        end
        subgraph VS4_B["Compliance &amp; Audit"]
            C4_5["Immutable Lifecycle Audit Trail"]:::capCard
            C4_6["Labor Policy Compliance Checks"]:::capCard
            C4_7["Payroll &amp; HRIS Export Readiness"]:::capCard
            C4_8["Executive Compliance Reporting"]:::capCard
        end
    end

    subgraph SPAN_OUTCOME["Cross-Cutting Leave Lifecycle &amp; Outcome Management"]
        SPAN1["End-to-End Leave Lifecycle, Balance Integrity &amp; Workforce Outcome Management"]:::capSpan
    end

    subgraph FOUND["Foundational Capabilities"]
        F1["Standalone Web Experience"]:::capCard
        F2["Accessibility (WCAG 2.1 AA)"]:::capCard
        F3["Multi-Language &amp; Cultural Access"]:::capCard
        F4["Geo-Spatial &amp; Regional Calendars"]:::capCard
        F5["Leave Policy Taxonomy"]:::capCard
        F6["Federated HR Directory Sync"]:::capCard
        F7["Cloud-Neutral Infrastructure &amp; Security"]:::capCard
        F8["Session &amp; Identity Management"]:::capCard
        F9["Role-Based Access Control"]:::capCard
        F10["Enterprise HRIS Integration"]:::capCard
        F11["Automation &amp; Workflow Engine"]:::capCard
        F12["Privacy &amp; Preference Management"]:::capCard
    end

    VS1 --> VS2 --> VS3 --> VS4
    VS3 --> SPAN_OUTCOME
    VS4 --> SPAN_OUTCOME
    SPAN_OUTCOME --> FOUND

    classDef capCard fill:#EEEEEE,stroke:#202124,stroke-width:1.5px,color:#202124;
    classDef capSpan fill:#EEEEEE,stroke:#202124,stroke-width:1.5px,color:#202124;

    style VS1 fill:#4285F4,stroke:#202124,stroke-width:1.5px,color:#FFFFFF
    style VS2 fill:#4285F4,stroke:#202124,stroke-width:1.5px,color:#FFFFFF
    style VS2_A fill:#FFFFFF,stroke:#DADCE0,stroke-width:1px,color:#202124
    style VS2_B fill:#FFFFFF,stroke:#DADCE0,stroke-width:1px,color:#202124
    style VS3 fill:#4285F4,stroke:#202124,stroke-width:1.5px,color:#FFFFFF
    style VS3_A fill:#FFFFFF,stroke:#DADCE0,stroke-width:1px,color:#202124
    style VS3_B fill:#FFFFFF,stroke:#DADCE0,stroke-width:1px,color:#202124
    style VS4 fill:#4285F4,stroke:#202124,stroke-width:1.5px,color:#FFFFFF
    style VS4_A fill:#FFFFFF,stroke:#DADCE0,stroke-width:1px,color:#202124
    style VS4_B fill:#FFFFFF,stroke:#DADCE0,stroke-width:1px,color:#202124
    style SPAN_OUTCOME fill:#F8F9FA,stroke:#202124,stroke-width:1.5px,color:#202124
    style FOUND fill:#4285F4,stroke:#202124,stroke-width:1.5px,color:#FFFFFF
```

</details>

---

## 2. Business Capability & Value-Stream Alignment Summary

| Value-Stream Pillar / Tier | Business Capabilities Included | Primary Business Personas | Delivery Scope (`Phase 1 MVP` vs. `Full Scope`) | Business Outcome & Value Delivered |
| :-- | :-- | :-- | :-- | :-- |
| **1. Employee Outreach & Leave Intake** | `Guided Leave Type Selection`, `Draft Leave Request Entry`, `Working-Day Duration Preview`, `Request Modification`, `Self-Service Cancellation` | `Employee` | `Phase 1 MVP` | Eliminates manual paper/spreadsheet requests with instant working-day feedback |
| **2. Entitlement, Calendar & Policy Verification** | `Annual Entitlement Tracking`, `Real-Time Balance Projection`, `Balance Re-Credit`, `Weekend & Holiday Exclusion`, `Overlapping Request Detection` | `Employee`, `Line Manager` | `Phase 1 MVP` + `Full Scope` | Guarantees accurate business-day deductions and prevents overlapping or over-balance submissions |
| **3. Supervisory Review & HR Escalation Routing** | `Manager Pending Review Queue`, `Separation-of-Duties Guard`, `Managerial Approval & Rejection`, `Extended Leave Threshold Detection`, `HR Final Adjudication` | `Line Manager`, `HR Administrator` | `Phase 1 MVP` + `Full Scope` | Enforces no-self-approval governance and routes requests `> 10` working days to HR oversight |
| **4. Workforce Availability, Audit & Oversight** | `Departmental Leave Utilization`, `Employee Leave History Ledger`, `Immutable Lifecycle Audit Trail`, `Labor Policy Compliance Checks` | `Line Manager`, `HR Administrator` | `Phase 1 MVP` + `Full Scope` | Provides tamper-evident auditability and real-time departmental capacity visibility |
| **Foundational Capabilities** | `Standalone Web Experience`, `Accessibility (WCAG 2.1 AA)`, `Cloud-Neutral Infrastructure & Security`, `Session & Identity Management`, `Role-Based Access Control`, `Automation & Workflow Engine`, `Privacy & Preference Management` | All Personas | `Phase 1 MVP` Foundation | Delivers zero-trust security, WCAG 2.1 AA accessibility, and multi-cloud portability |
