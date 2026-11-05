---
name: 04-solution-architect
description: "Stage 4A of the Agentic DLC v4 (parallel with 05-test-plan-designer, after Gate 3). solution-architect confirms the Future-State technology stack with the human (specs/target_stack.json), then authors the Multi-Perspective Architecture Suite as SEPARATE artifacts under design/ — (1) design/business_architecture.md, (2) design/high_level_solution_architecture.md (AI-Era System of Engagement / System of Intelligence & AI / Systems of Record), (3) design/logical_architecture.md, (4) design/application_architecture.md (C4 components + sequenceDiagram), (5) design/data_architecture.md (5-stage data/RAG pipeline + 3NF erDiagram), (6) design/security_architecture.md (5-layer defense-in-depth + AI Trust Layer), (7) design/infrastructure_architecture.md (multi-region topology + Well-Architected matrices), and (8) design/architecture_design.md (Executive Portfolio Index) — plus design/solution_design.md (3NF SQL DDL + OpenAPI 3.1 contract + DTO/RBAC mapping) and design/data_migration_and_cutover.md for SCENARIO_LEGACY_APP; verified by 04/scripts/extract_contracts.py."
---

# Stage 4A — Future-State ("To-Be") Multi-Perspective Target Architecture & Solution Design

**Read before acting:** `docs/ARCHITECTURE.md` §3, §4.2, §4.6, `_shared/well_architected_and_diagram_standards.md`, `skills/04-solution-architect/resources/reference_high_level_solution_architecture.png`, `skills/04-solution-architect/resources/reference_business_capability_map.png`, `skills/04-solution-architect/resources/reference_gcp_architecture_diagram.png`, `_shared/zero_leak.md`,
`_shared/workflow_chain_of_custody.md` ("Stage 5"), `_shared/ux_guardrails.md`, `_shared/google_cloud_ui_design.md`, `skills/google-cloud-ui-design/SKILL.md`. Subagent: `solution-architect`.

> **CRITICAL RULE 1 — Separate Artifact per Architectural Perspective & Flexible Multi-Layout Rendering:**
> Never cram all architecture perspectives into a single monolithic file or render every perspective with the same fixed diagram layout. Stage 4A authors **7 Dedicated Architecture Perspective Artifacts** (indexed by **`design/architecture_design.md`**), each rendered with its own purpose-built visual layout in `04/scripts/gcp_diagram_renderer.py`:
> 1. **`design/business_architecture.md`** (`resources/business_architecture_template.md` → `design/diagrams/business_capability_map.{svg,png}`): **Value-Stream Chevrons (`1..4`) + Core Capability Grid + Cross-Cutting Outcome Bar + Foundational Capabilities 2×6 Grid** (`resources/reference_business_capability_map.png`, uniform `#EEEEEE` capability cards, no Phase 1 green color-coding, no vendor watermark).
> 2. **`design/high_level_solution_architecture.md`** (`resources/high_level_solution_architecture_template.md` → `design/diagrams/high_level_solution_architecture.{svg,png}`): **AI-Era 3-Tier Executive Solution Architecture** (`resources/reference_high_level_solution_architecture.png` + Value-Led Enterprise Architecture approach):
>    - **Top Row (`SG_Personas`):** 4 Business Personas with blue user silhouette avatars (`Operational Staff`, `Domain Analysts & AI Users`, `Executives & Supervisors`, `Customers / Applicants`).
>    - **Band 1 (`SG_Engagement` — `Engagement Layer / System of Engagement`):** Self-Service Web Portal, Operational Review Console, Executive BI & KPI Workspace, Embedded AI Copilot UX, Omnichannel Notifications.
>    - **Band 2 (`SG_Intelligence` — `System of Intelligence & AI` inside thick `#19A5E6` cyan container):**
>      - Top wide banner (`SG_AILayer`): **`AI & Agentic Orchestration Layer`** (Domain Copilots, Autonomous Triage & Workflow Agents, Grounded Policy RAG, Prompt Guardrails)
>      - Middle row of 4 capability cards (`SG_CoreCaps`): `Unified 360° Domain View`, `Predictive & Decision Insights`, `Workflow & Rules Engine`, `Cross-Team Collaboration`
>      - Bottom wide banner (`SG_DataLayer`): **`Data Ingestion, Harmonization & Event Transformation Layer`**
>      - Right-hand vertical stack of 4 Governance & Trust boxes (`SG_Governance`): `Built-in Data & AI Security`, `Unified Data Governance`, `API & Event Exchange`, `Anomaly & Compliance Guard`
>      - Bottom platform emblem & title: `Unified Intelligence, Agentic AI & Domain Data Platform`
>    - **Band 3 (`SG_Transactional` — `Transactional Systems / Systems of Record`):** Core 3NF Relational Database, Enterprise Identity & SSO, ERP / HRIS / Financial Ledger, Document & Evidence Store, Immutable Audit Ledger.
> 3. **`design/logical_architecture.md`** (`resources/logical_architecture_template.md` → `design/diagrams/logical_architecture.{svg,png}`): **Concentric Multi-Zone Functional Topology** (`resources/reference_gcp_architecture_diagram.png`) — Personas → User Experience Channels → Core Domain Orchestration & Policy Engine → Business Capability Services & Logical Stores (3×3 grid).
> 4. **`design/application_architecture.md`** (`resources/application_architecture_template.md` → `design/diagrams/application_architecture.{svg,png}`): **4-Tier C4 Application & AI Component Topology** (`Presentation & Omnichannel UI Modules` → `API Gateway, BFF & Zero-Leak DTO Tier` → `Core Domain & AI Agent Services Tier` → `Data Access, Event Bus & Integration Adapters Tier`) + **End-to-End Request & Workflow `sequenceDiagram`**.
> 5. **`design/data_architecture.md`** (`resources/data_architecture_template.md` → `design/diagrams/data_architecture.{svg,png}`): **5-Stage Left-to-Right Information Pipeline** (`Data Sources & Producers` → `Ingestion, Validation & CDC` → `Operational 3NF System of Record & MDM` → `Unified Data & AI Grounding / RAG` → `Consumption, Analytics & Archival`) + **Bottom Unified Data Governance Bar** + **Normalised 3NF `erDiagram`**.
> 6. **`design/security_architecture.md`** (`resources/security_architecture_template.md` → `design/diagrams/security_architecture.{svg,png}`): **5-Layer Defense-in-Depth + AI Trust Layer Stack** (`Identity & Federation Perimeter` → `Network & Edge Perimeter` → `Application RBAC, State-Guard & Separation-of-Duties Perimeter` → `AI Trust Layer & Zero-Leak Data Privacy Perimeter` → `Data Encryption, Secrets & Continuous Compliance Perimeter`).
> 7. **`design/infrastructure_architecture.md`** (`resources/infrastructure_architecture_template.md` → `design/diagrams/infrastructure_architecture.{svg,png}` + `technical_architecture.{svg,png}` alias): **Cloud-Agnostic Multi-Region Deployment & Network Topology** + **Well-Architected 6-Pillar (+ Sustainability) & First-Principles Anti-Pattern Grilling Matrices**.
> 8. **`design/architecture_design.md`** (`resources/architecture_design_template.md`): **Executive Multi-Perspective Architecture Portfolio Index** linking and summarizing all 7 perspective artifacts above.

> **CRITICAL RULE 2 — Cloud-Agnostic Diagrams, Zero Spec/Design Trace Codes & Zero Raw JSON Blocks:**
> - **100% Cloud-Agnostic:** Never render cloud vendor watermarks, never title outer banners `"Google Cloud"`, and never hardcode single-vendor product names or routes (`restricted.googleapis.com / 199.36.153.4/30`). Use portable primitives (`Global L7 Load Balancer`, `Web Application Firewall`, `Edge CDN Cache`, `Zero-Trust Identity Proxy`, `Virtual Router & NAT`, `Kubernetes Web & Application Tiers`, `Service Mesh mTLS`, `Private Service Route: internal.service.mesh 10.240.0.0/16`, `PgBouncer Pooler`, `PostgreSQL HA Primary & Read Replica`, `Object Storage Buckets`, `KMS & Secrets Manager`, `Workload Identity`, `OpenTelemetry & Tracing`, `Metrics & SLO Alerting`, `GitOps & OPA Policy Engine`).
> - **Zero Spec/Design Trace Codes in Architecture Perspective Artifacts:** **NEVER** include `GRP-01`, `CAP-01`, `FRP-04`, `BR-01`, `REQ-FUNC-01`, `US-FUNC-01`, or `Spec §3.3` inside `design/*_architecture.md` or `design/architecture_design.md` (`04/scripts/extract_contracts.py` fails Gate 4A if any trace code appears). Trace IDs belong exclusively in `specs/application_spec.md` and `design/solution_design.md`.
> - **Zero Raw JSON Blocks & Zero Local-Testing Details in Design:** Never embed ```` ```json ```` blocks or local testing mock flags (`APP_ENV=local`, `AUTH_MODE=local-mock`, `STORAGE_BACKEND=local-fs`, SQLite fallback, `127.0.0.1` dev servers) in `design/`.

## Inputs
`specs/application_spec.md` (§3.3 states/transitions, §3.4 rules, §3.5 roles, Pillar 2 PII list, Pillar 5),
`specs/discovery_architecture_and_inventory.md` (§2 current-state data model & §2.1 legacy object inventory),
`backlog/user_stories.json` (approved, with `capabilityGroup` tags), `specs/target_stack.json`, `specs/input_inventory.json`,
`resources/design_references/`, `resources/shared_services/` (if present).

## Outputs
| File | Author | Checked by |
| :-- | :-- | :-- |
| `design/business_architecture.md` | `solution-architect` | `04/scripts/extract_contracts.py` → renders `design/diagrams/business_capability_map.{svg,png}` |
| `design/high_level_solution_architecture.md` | `solution-architect` | `04/scripts/extract_contracts.py` → renders `design/diagrams/high_level_solution_architecture.{svg,png}` (AI-Era 3-Tier Engagement / System of Intelligence & AI / Systems of Record) |
| `design/logical_architecture.md` | `solution-architect` | `04/scripts/extract_contracts.py` → renders `design/diagrams/logical_architecture.{svg,png}` |
| `design/application_architecture.md` | `solution-architect` | `04/scripts/extract_contracts.py` → renders `design/diagrams/application_architecture.{svg,png}` + validates `sequenceDiagram` |
| `design/data_architecture.md` | `solution-architect` | `04/scripts/extract_contracts.py` → renders `design/diagrams/data_architecture.{svg,png}` + validates `erDiagram` |
| `design/security_architecture.md` | `solution-architect` | `04/scripts/extract_contracts.py` → renders `design/diagrams/security_architecture.{svg,png}` |
| `design/infrastructure_architecture.md` | `solution-architect` | `04/scripts/extract_contracts.py` → renders `design/diagrams/infrastructure_architecture.{svg,png}` (`+ technical_architecture.{svg,png}`) + validates Well-Architected & Grilling matrices |
| `design/architecture_design.md` | `solution-architect` | Executive Multi-Perspective Architecture Portfolio Index linking all 7 perspective artifacts |
| `design/solution_design.md` | `solution-architect` | `04/scripts/extract_contracts.py` (`§1` 3NF `erDiagram`, `§1.1` legacy→target mapping, fenced `sql ddl` + `yaml openapi` blocks, ViewModel/DTO & RBAC mapping) |
| `design/data_migration_and_cutover.md` | `solution-architect` — **legacy scenario only** | presence check when `inputScenario == SCENARIO_LEGACY_APP` |
| `src/contracts/openapi.yaml`, `src/db/schema.sql` | script (extracted from `design/solution_design.md`) | YAML/SQL parse; consumed by Stages 4B/5/6 |

## Procedure

### 0. Confirm Future-State ("To-Be") Technology Stack (`specs/target_stack.json`)
- If `decidedBy != "user"` or any of `frontend.kind`, `backend.kind`, or `database.kind` is `"tbd"` in interactive mode, pause and ask the human what Future-State frontend, backend, database, and deployment stack to use. Record `"decidedBy": "user"` in `specs/target_stack.json`. Never downgrade `specs/target_stack.json` to `static-html` + `python-stdlib-http` for local testing.

### 1. Author the 7 Perspective Artifacts + `design/architecture_design.md` Index
Using the templates in `skills/04-solution-architect/resources/*_template.md`:
1. **`design/business_architecture.md`** (`resources/business_architecture_template.md`): Value-Stream Chevrons (`VS1..VS4`), Core Business Capability Grid (`:::capCard`), Cross-Cutting Outcome Bar (`:::capSpan`), Foundational Capabilities (`FOUND`), and Value-Stream Alignment Summary Table.
2. **`design/high_level_solution_architecture.md`** (`resources/high_level_solution_architecture_template.md`): Top Personas (`SG_Personas`), `Engagement Layer` (`SG_Engagement`), `System of Intelligence & AI` (`SG_Intelligence` with `SG_AILayer`, `SG_CoreCaps`, `SG_DataLayer`, `SG_Governance`), and `Transactional Systems` (`SG_Transactional`), plus architectural narrative tables.
3. **`design/logical_architecture.md`** (`resources/logical_architecture_template.md`): Business Personas (`SG_OnPrem`), User Experience Channels (`SG_Edge`), `Core Domain Orchestration & Policy Engine` (`SG_HubProject`), and 3×3 `Business Capability Services & Logical Stores` (`SG_SpokePerimeter`), plus Logical Layering table.
4. **`design/application_architecture.md`** (`resources/application_architecture_template.md`): 4-Tier C4 Component & AI Service Topology (`SG_Tier1`..`SG_Tier4`) + End-to-End Request & Workflow `sequenceDiagram` (using `actor User as ...`, never reserved keyword `actor Actor`).
5. **`design/data_architecture.md`** (`resources/data_architecture_template.md`): 5-Stage Data & AI Grounding Pipeline (`SG_Stage1`..`SG_Stage5` + `SG_GovBar`) + Normalised 3NF `erDiagram` + Data Lifecycle/Retention table.
6. **`design/security_architecture.md`** (`resources/security_architecture_template.md`): 5-Layer Defense-in-Depth & AI Trust Layer (`SG_Layer1`..`SG_Layer5`) + RBAC & Separation-of-Duties Matrix + AI Trust & Guardrail Controls Table.
7. **`design/infrastructure_architecture.md`** (`resources/infrastructure_architecture_template.md`): Multi-Region Cloud-Agnostic Deployment & Network Topology (`SG_OnPrem2`, `SG_Edge2`, `SG_HubProject2`, `SG_SpokePerimeter2`) + Well-Architected 6-Pillar (+ Sustainability) Alignment Matrix + First-Principles Failure Mode & Anti-Pattern Grilling Matrix.
8. **`design/architecture_design.md`** (`resources/architecture_design_template.md`): Executive Multi-Perspective Architecture Portfolio Index linking all 7 artifacts and embedding a visual gallery of all 7 rendered SVGs.

### 2. Author `design/solution_design.md` (and `design/data_migration_and_cutover.md` for Legacy Apps)
Using `resources/solution_design_template.md`, author `§1` 3NF `erDiagram`, `§1.1` Legacy→Target 3NF Entity Mapping (`SCENARIO_LEGACY_APP` only), `§1.2` ```` ```sql ddl ````, `§2` ```` ```yaml openapi ````, `§3` ViewModel/DTO Boundary, `§4` Workflow & Authorization Enforcement, `§5` Frontend Tokens, `§6` Cross-Cutting Concerns, and `§7` Target-State Build & Packaging Specification.

### 3. Validate All Perspectives, Render All 7 Diagrams & Extract Contracts
```bash
python3 <PLUGIN>/skills/04-solution-architect/scripts/extract_contracts.py --project-root "<PROJECT_ROOT>"
```
Validates all 7 perspective artifacts + `architecture_design.md` + `solution_design.md`, renders all 7 SVG/PNG diagram pairs in `design/diagrams/`, and extracts `src/contracts/openapi.yaml` and `src/db/schema.sql`. Fix any reported issues and re-run until PASS.

### 4. Mandatory STOP at Gate 4A/4B (`gate_4_design_and_tests`) — Wait for Human Architecture & Test Plan Approval
`extract_contracts.py` (together with Stage 4B `validate_test_cases.py`) stamps `gate_4_design_and_tests = AWAITING_HUMAN_REVIEW` in `specs/gate_approvals.json`, blocking Stage 5 (`check_testid_contract.py` & `validate_build.py`).
1. Once both Stage 4A (`design/*`) and Stage 4B (`test/test_plan.md` & `test/test_cases.json`) pass validation, present the 7-perspective architecture portfolio (`design/architecture_design.md`), `design/solution_design.md`, and `test/test_plan.md` to the user.
2. **END YOUR TURN IMMEDIATELY (call zero further tools). NEVER start Stage 5 (`06-coding-agent`) in the same turn!**
3. Only **in a subsequent turn AFTER the human explicitly approves Gate 4A/4B**, run:
   ```bash
   python3 <PLUGIN>/scripts/gate_tracker.py --project-root "<PROJECT_ROOT>" --action approve --gate gate_4_design_and_tests --user-response "<verbatim user approval quote>"
   ```
   and then proceed to `06-coding-agent`.
