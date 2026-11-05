# Business Architecture & Capability Map (`design/business_architecture.md`)

- **Project:** Business Licensing & Renewal Portal — Legacy MS Access Modernization (Legacy Application Modernization)
- **Perspective:** **Business Architecture & Value-Stream Capability Map** (Standalone Perspective Artifact 1 of 7)
- **Visual Renderer:** `design/diagrams/business_capability_map.svg` (`.png`) — Value-Stream Chevrons + Core Capability Grid + Cross-Cutting Outcome Bar + Foundational Capabilities Matrix
- **Architecture Portfolio Index:** [`design/architecture_design.md`](architecture_design.md)

---

## 1. Business Architecture & Capability Map (Value Streams, Core Business Capabilities & Foundational Capabilities)

*(Depicts the Business Licensing & Renewal Portal's cloud-agnostic **Business Architecture & Capability Map**: top horizontal Blue (`#4285F4`) Value-Stream Chevrons (`1. Business Onboarding & License Intake`, `2. Category Classification, Fee & Tax Verification`, `3. Compliance Review & Adjudication Routing`, `4. Certificate Issuance, Renewal & Regulatory Oversight`), multi-column Level-2 Core Business Capability cards in uniform `#EEEEEE` fill with `#202124` borders, a bottom Cross-Cutting Outcome bar, and a full-width `Foundational Capabilities` banner above a 2×6 Foundational Capabilities grid.)*

![Business Capability Map](diagrams/business_capability_map.png)

---

## 2. Business Capability & Value-Stream Alignment Summary

| Value-Stream Pillar / Tier | Business Capabilities Included | Primary Business Personas | Delivery Scope (`Phase 1 MVP` vs. `Full Scope`) | Business Outcome & Value Delivered |
| :-- | :-- | :-- | :-- | :-- |
| **1. Business Onboarding & License Intake** | `Business Entity Registration`, `Guided License Category Selection`, `Draft Application & Amendment Entry`, `Self-Service Status Portal`, `Deficiency Resubmission` | `Business Applicant` | `Phase 1 MVP` | Replaces single-user MS Access forms (`frmLicenseApp`) with concurrent web self-service |
| **2. Category Classification, Fee & Tax Verification** | `Tiered Category Fee Assessment`, `Employee Headcount Surcharge`, `Late Renewal Penalty`, `Tax ID Verification & Masking`, `Duplicate Active License Prevention` | `Business Applicant`, `Compliance Reviewer` | `Phase 1 MVP` + `Full Scope` | Automates deterministic fee/penalty calculation and protects sensitive Tax IDs (`***-**-1234`) |
| **3. Compliance Review & Adjudication Routing** | `Submitted Application Triage Queue`, `Category & Headcount Verification`, `Compliance Approval & Rejection`, `Supervisory Issuance Queue`, `License Revocation` | `Compliance Reviewer`, `Licensing Supervisor` | `Phase 1 MVP` + `Full Scope` | Enforces regulatory workflow and role separation between triage and issuance |
| **4. Certificate Issuance, Renewal & Regulatory Oversight** | `Annual 365-Day Certificate Issuance`, `Printable License Certificate View`, `Expiration & Renewal Tracking`, `Immutable Licensing Audit Trail`, `Revenue Analytics` | `Licensing Supervisor`, `Business Applicant` | `Phase 1 MVP` + `Full Scope` | Replaces legacy Access reports (`rptCertificate`) with verifiable certificates and audit history |
| **Foundational Capabilities** | `Standalone Web Experience`, `Accessibility (WCAG 2.1 AA)`, `Legacy MS Access Data Migration`, `Cloud-Neutral Infrastructure & Security`, `Role-Based Access Control`, `Tax ID Encryption & Privacy` | All Personas | `Phase 1 MVP` Foundation | Eliminates SMB `.mdb` lock corruption and delivers zero-trust security across multi-cloud targets |
