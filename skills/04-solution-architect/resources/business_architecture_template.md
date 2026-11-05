# Business Architecture & Capability Map (`design/business_architecture.md`)

- **Perspective:** **Business Architecture ("Why & What" — Value Streams, Core Business Capabilities & Foundational Capabilities)**
- **Input Scenario:** `<Legacy Application Modernization | Greenfield Requirements Specification>`
- **Visual Archetype:** Executive Value-Stream Chevron Ribbon (`1..4`) + Multi-Column Level-2 Capability Grid + Cross-Cutting Outcome Bar + Foundational Capabilities Grid (`diagrams/business_capability_map.png`)
- **Architecture Portfolio Index:** [`design/architecture_design.md`](architecture_design.md)

---

## 1. Executive Business Capability Map

![Business Capability Map](diagrams/business_capability_map.png)

---

## 2. Value-Stream & Business Capability Alignment Matrix

| Value-Stream Pillar / Tier | Level-2 Business Capabilities | Primary Personas | Delivery Scope | Strategic Business Outcome & KPIs |
| :-- | :-- | :-- | :-- | :-- |
| **1. `<Value Stream 1>`** | `<Core Capabilities 1.1 – 1.5>` | `<Persona 1>` | `Phase 1 MVP` + `Full Scope` | Streamlines guided intake, onboarding, and self-service submission |
| **2. `<Value Stream 2>`** | `<Core Capabilities 2A.1 – 2B.4>` | `<Persona 1, Persona 2>` | `Phase 1 MVP` + `Full Scope` | Centralizes eligibility verification, directory lookup, and validation |
| **3. `<Value Stream 3>`** | `<Core Capabilities 3A.1 – 3B.4>` | `<Persona 2>` | `Phase 1 MVP` + `Full Scope` | Automates deterministic policy calculation, review routing, and adjudication |
| **4. `<Value Stream 4>`** | `<Core Capabilities 4A.1 – 4B.4>` | `<Persona 2, Persona 3>` | `Phase 1 MVP` + `Full Scope` | Enforces issuance, compliance monitoring, and executive oversight |
| **Foundational Capabilities** | `Standalone Web Experience`, `Accessibility (WCAG 2.1 AA)`, `Cloud-Neutral Infrastructure & Security`, `Session & Identity Management`, `Role-Based Access Control`, `Automation & Workflow Engine`, `Privacy & Preference Management` | All Personas | `Phase 1 MVP` Foundation | Provides zero-trust security, accessibility, auditability, and cloud-neutral operations |
