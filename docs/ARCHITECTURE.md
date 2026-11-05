# agentic-dlc v4 — Architecture & Artefact Contracts

This document is the **single source of truth** for how v4 differs from v3 and for the file/JSON
contracts that every skill, agent and script must honour. Anyone (human or agent) editing this
plugin must read it first.

## 0. The one-sentence change from v3

> **v3:** scripts *generated* one fixed demo application and keyword-scored it.
> **v4:** the LLM (skills + subagents) *authors* every project artefact from the user's inputs; scripts only
> **scan, derive, lint, execute and gate** — and they fail loudly instead of falling back to templates.

## 1. Non-negotiable principles

1. **Domain neutrality.** No business-domain literal (the sample domains, fees, regulations, organization names, wizard
   step names, view names, element IDs, dollar amounts) may appear in `rules/`, `agents/`, `skills/`,
   `scripts/`, `_shared/`, `schemas/`. Worked examples live only under `examples/`.
   `scripts/lint_domain_neutrality.py` enforces this and is run in CI / by `verify_golden_projects.py`.
2. **LLM authors, scripts verify.** No script writes a spec, story, design, test plan, UI or backend from a
   built-in template. If an upstream artefact is missing the script exits non-zero with the stage that
   must produce it.
3. **Scenario-aware & Current-State vs. Future-State Separation.** `specs/input_inventory.json#inputScenario` ∈ {`SCENARIO_LEGACY_APP`,
   `SCENARIO_REQUIREMENTS_DOC`}. Stage 1 (`specs/discovery_architecture_and_inventory.md`) documents **only the Current State ("As-Is")** (current-state data model `erDiagram`, `§2.1` current-state legacy object inventory, current-state workflow state machine, pain points, and capability groupings — never future-state 3NF schemas, future-state flow diagrams, or legacy-to-target mappings). Stage 4A (`design/solution_design.md` and `design/data_migration_and_cutover.md`) owns **all Future-State ("To-Be") architecture** (future-state component/process flow diagrams, future-state normalised 3NF `erDiagram`, `§2.1` Legacy-to-Target 3NF entity mapping, target `sql ddl`, and OpenAPI 3.1 contract). Legacy-only artefacts (current-state legacy object inventory in Stage 1, Legacy-to-Target 3NF entity mapping in Stage 4A, `design/data_migration_and_cutover.md`, `REQ-ENH-*`) are required **only** for `SCENARIO_LEGACY_APP`.
   Policy & regulatory sections are required only when `resources/policies_and_statutes/` is non-empty or the
   user declared regulations at Gate 1.
4. **Chain of custody for workflow.** The lifecycle state machine (`stateDiagram-v2`) is extracted at
   Stage 1 from inputs (or asked of the user), frozen in `specs/application_spec.md §3.3`, and every
   downstream artefact (stories, tests, UI gating, backend guards) is **derived** from it. Scripts parse it
   (`dlc_common.parse_state_machine`) — they never hard-code states.
5. **Stack contract.** Gate 1 produces `specs/target_stack.json`. Stage 4A/5/6 consume it. "Working
   application" = the commands in `target_stack.json` build, start, and pass Stage 6.
6. **Real verification.** Spec quality is judged by an LLM against `schemas/spec_rubric.json` with quoted
   evidence; UI behaviour is executed in a real browser runtime; backend contracts are hit over HTTP;
   reports are generated from results and real diffs. Nothing prints a static PASS.
7. **No duplication in plugin rules.** Long shared plugin guidance lives once in `_shared/` for skills and agents to read; **deliverable files inside `<PROJECT_ROOT>/` must never reference `_shared/*.md`, internal script paths, subagent slugs, `<details>` diagram-dsl blocks, or `SCENARIO_*` enum constants**.
   Shared Python lives once in `scripts/dlc_common.py` (skills import it via `sys.path` insertion).
8. **Zero internal harness leakage in deliverables.** Every published deliverable under `<PROJECT_ROOT>/{specs,backlog,design,test,src,deploy}/` is customer-facing and scanned fail-closed by `dlc_common.scan_deliverable_internal_leaks()` across all stage gates and `scripts/lint_domain_neutrality.py`. Machine-readable diagram DSL specifications live exclusively in hidden dot-files `design/diagrams/.specs/<stem>.mmd`.

## 2. Plugin layout

```
agentic-dlc/
├── plugin.json
├── README.md
├── docs/ARCHITECTURE.md                 # this file
├── _shared/                             # referenced by every skill & agent (never pasted)
│   ├── project_root.md                  # PROJECT_ROOT resolution rule (short)
│   ├── ux_guardrails.md                 # the 10 generic UX guardrails (single canonical copy)
│   ├── zero_leak.md                     # zero internal-data-leakage rule + how token lists are derived
│   ├── workflow_chain_of_custody.md     # state machine extraction / ask-don't-assume / derivation rules
│   └── gdc_multicloud_guardrails.md     # GDC Fleet multi-cloud & on-prem portability guardrails
├── schemas/                             # JSON schemas / canonical shapes for every machine artefact
│   ├── project_setup.schema.json        # Stage 0 connection & ADO/Jira project selection
│   ├── gate_approvals.schema.json       # Machine-enforced human gate ledger (gate_0_setup .. gate_7_packaging)
│   ├── input_inventory.schema.json
│   ├── target_stack.schema.json
│   ├── spec_rubric.json                 # the 100-pt rubric the LLM judge scores against
│   ├── spec_scorecard.schema.json
│   ├── user_stories.schema.json
│   ├── test_cases.schema.json
│   ├── eval_results.schema.json
│   └── deployment_eval_results.schema.json
├── rules/AGENTS.md                      # router (generic)
├── agents/*.md                          # 7 subagents (generic)
├── skills/0X-*/SKILL.md (+ resources/, scripts/)
├── scripts/
│   ├── dlc_common.py                    # shared helpers (project root, json io, md parsing, state machine, gate ledger)
│   ├── gate_tracker.py                  # CLI for human gate status & anti-self-approval gate unlocking
│   ├── lint_domain_neutrality.py        # CI check: no domain literals outside examples/
│   ├── run_agentic_dlc_pipeline.py      # VERIFY-ONLY orchestrator: runs gates in order, never generates
│   └── verify_golden_projects.py        # runs the verify pipeline over examples/*/expected_artifacts
└── examples/
    ├── legacy_ms_access_licensing_app/   # SCENARIO_LEGACY_APP golden project (inputs + expected_artifacts)
    └── greenfield_leave_request_portal/  # SCENARIO_REQUIREMENTS_DOC golden project
```

## 3. `<PROJECT_ROOT>` layout (v4)

```
<PROJECT_ROOT>/
├── resources/{inputs,design_references,policies_and_statutes,shared_services}/
├── specs/
│   ├── project_setup.json               # Stage 0 (script)   — schemas/project_setup.schema.json
│   ├── gate_approvals.json              # All gates (script) — schemas/gate_approvals.schema.json
│   ├── input_inventory.json             # Stage 1 (script)   — schemas/input_inventory.schema.json
│   ├── discovery_architecture_and_inventory.md  # Stage 1 (LLM)
│   ├── target_stack.json                # Gate 1 (LLM, from user answers) — schemas/target_stack.schema.json
│   ├── application_spec.md              # Stage 2 (LLM)
│   ├── traceability_matrix.md           # Stage 2 (LLM)
│   ├── application_eval_scorecard.md    # Stage 2 (LLM judge) human-readable
│   └── application_eval_scorecard.json  # Stage 2 (LLM judge) machine — schemas/spec_scorecard.schema.json
├── backlog/
│   ├── user_stories.md / user_stories.json      # Stage 3 (LLM) — schemas/user_stories.schema.json
│   ├── sprint_plan.md / sprint_plan.json        # Stage 3 (LLM + script summary)
│   ├── jira_import.csv, jira_state.json, azure_devops_state.json  # Stage 3 (script)
├── design/
│   ├── architecture_design.md           # Stage 4A (LLM) — Executive Multi-Perspective Architecture Portfolio Index
│   ├── business_architecture.md         # Stage 4A (LLM) — Value-Stream Chevrons + Capability Map + Foundational Matrix
│   ├── high_level_solution_architecture.md # Stage 4A (LLM) — AI-Era System of Engagement / System of Intelligence & AI / Systems of Record
│   ├── logical_architecture.md          # Stage 4A (LLM) — Concentric Multi-Zone Functional Topology
│   ├── application_architecture.md      # Stage 4A (LLM) — 4-Tier C4 Application & AI Components + sequenceDiagram
│   ├── data_architecture.md             # Stage 4A (LLM) — 5-Stage Data & AI Grounding Pipeline + 3NF erDiagram
│   ├── security_architecture.md         # Stage 4A (LLM) — 5-Layer Defense-in-Depth & AI Trust Layer
│   ├── infrastructure_architecture.md   # Stage 4A (LLM) — Multi-Region Deployment Topology + Well-Architected & Grilling Matrices
│   ├── diagrams/.specs/*.mmd            # Stage 4A (LLM, hidden dot-dir) — 7 diagram DSL specifications
│   ├── diagrams/*.{svg,png}             # Stage 4A (script) — 7 rendered perspective diagrams
│   ├── solution_design.md               # Stage 4A (LLM) — must contain fenced ```yaml openapi and ```sql ddl blocks
│   └── data_migration_and_cutover.md    # Stage 4A (LLM) — SCENARIO_LEGACY_APP only
├── test/
│   ├── test_plan.md                     # Stage 4B (LLM)
│   ├── test_cases.json                  # Stage 4B (script derives skeleton from stories+state machine; LLM fills steps) — schemas/test_cases.schema.json
│   ├── eval_report.md, eval_results.json           # Stage 6 (script — latest + cumulative run history)
│   ├── remediation_and_guardrail_audit_report.md   # Stage 6 (script — §0 cumulative history + §1-3 current + §4 prior run failures & remediation diffs)
│   ├── *.iter-NN.{json,md}              # Stage 6 (script) numbered non-overwritten copies per run
│   ├── history/iter-N/                  # Stage 6 (script) immutable per-run archive of eval_results, eval_report, remediation_and_guardrail_audit_report & defects (+ run_index.json)
│   └── .snapshots/iter-N/               # Stage 6 (script) immutable copies of src/ + evaluation/remediation artifacts per iteration (never overwritten)
└── src/
    ├── contracts/openapi.yaml           # Stage 4A (script extracts from solution_design.md)
    ├── db/schema.sql                    # Stage 4A (script extracts from solution_design.md); Stage 5 may add migrations
    ├── ui/…                             # Stage 5 (LLM) per target_stack.frontend
    ├── backend/…                        # Stage 5 (LLM) per target_stack.backend
    ├── run.sh | Makefile | docker-compose.yml   # Stage 5 (LLM) — must match target_stack.commands
    └── README.md                        # Stage 5 (LLM) how to build/run/test
├── deploy/
│   ├── containers/{Dockerfile.backend,Dockerfile.ui,docker-compose.yaml}     # Stage 7 (LLM)
│   ├── gdc/base/{kustomization.yaml,workloads.yaml}                          # Stage 7 (LLM)
│   ├── gdc/overlays/{on-prem-gdc,gcp,aws,azure}/kustomization.yaml           # Stage 7 (LLM)
│   ├── gdc/policy-controller/constraints.yaml                                # Stage 7 (LLM)
│   ├── gdc/service-mesh/{peer-authentication.yaml,authorization-policy.yaml,multicluster-service.yaml} # Stage 7 (LLM)
│   ├── gdc/config-sync/{rootsync.yaml,cluster-selectors.yaml}                # Stage 8 (LLM)
│   ├── observability/{otel-collector.yaml,slo_and_alerts.yaml,fleet_dashboard.json} # Stage 8 (LLM)
│   ├── deployment_and_runbook.md                                             # Stage 8 (LLM)
│   └── deployment_eval_report.{md,json}                                      # Stage 8 (script) — schemas/deployment_eval_results.schema.json
```

## 4. Machine artefact contracts

### 4.0 `specs/project_setup.json` & `specs/gate_approvals.json` (Stage 0 Setup & Machine-Enforced Human Gates)
Stage 0 (`00-setup-and-connection/scripts/setup_project_connection.py`) verifies ADO/Jira connectivity, lists available Azure DevOps Projects (`list-ado-projects`) and Git Repositories (`list-ado-repos`), records the user's chosen ADO Project and repository/input source in `specs/project_setup.json`, and initializes `specs/gate_approvals.json` (`gate_0_setup = AWAITING_HUMAN_REVIEW`). Every downstream stage script calls `dlc_common.require_gate_approved(...)` at startup and `dlc_common.mark_gate_awaiting_human(...)` upon completion, and `scripts/gate_tracker.py --action approve` enforces an anti-self-approval turn-boundary cooldown plus a verbatim `--user-response` quote before unlocking the next stage.

### 4.1 `specs/input_inventory.json` (Stage 1 script — after Gate 0 human approval)
Before running `01/scripts/scan_input_sources.py`, `discovery-architect` confirms the input source location with the user (`<PROJECT_ROOT>/resources/inputs/`, an external local directory via `--input-dir`, an Azure DevOps repository via `--ado-repo`, or a Git repository via `--git-repo`).
```json
{
  "schemaVersion": "4.0",
  "scannedAtUtc": "…",
  "projectRoot": "…",
  "domainSlug": "example-service-portal",       // kebab-case, derived from --domain-slug, source repo name, first H1 of primary input, or dir name
  "domainSlugSource": "flag | source-repository | primary-document-h1 | project-directory-name",
  "sourceRepository": {                         // optional provenance when ingested via --ado-repo or --git-repo
    "provider": "ado | git | local",
    "repositoryUrl": "https://dev.azure.com/<org>/<project>/_git/<repo>",
    "repositoryName": "<repo>",
    "branch": "main",
    "commitSha": "…",
    "localCheckoutPath": "resources/inputs/<repo>"
  },
  "inputScenario": "SCENARIO_LEGACY_APP | SCENARIO_REQUIREMENTS_DOC",
  "scenarioEvidence": {"legacyArtifactCount": 0, "requirementsDocCount": 0, "decisionRule": "majority-by-weight; ties -> ask user"},
  "scenarioConfidence": "HIGH | LOW",           // LOW => Gate 1 must ask the user to confirm
  "includeModernizationEnhancementsInSpec": false,
  "hasPoliciesOrStatutes": false,
  "hasUserProvidedDesignReferences": false,
  "userProvidedDesignReferences": [ {"relativePath": "…", "designType": "figma|stitch|sample_ui|style_guide|tokens"} ],
  "inputFingerprintSha256": "…",
  "files": [ {"relativePath": "…", "name": "…", "extension": "…", "sizeBytes": 0, "sha256": "…", "category": "legacy_schema|legacy_query|legacy_form|legacy_report|legacy_source|requirements_doc|policy|design_reference|shared_service|other"} ]
}
```

### 4.2 `specs/target_stack.json` (Gate 1 & Stage 4A Future-State Tech Stack Confirmation)
```json
{
  "schemaVersion": "4.0",
  "frontend":  {"kind": "tbd | react | angular | vue | nextjs | static-html | other", "notes": ""},
  "backend":   {"kind": "tbd | python-fastapi | python-flask | node-express | java-spring-boot | go | dotnet | python-stdlib-http | none", "notes": ""},
  "database":  {"kind": "tbd | postgres | alloydb-omni | mysql | sqlserver | sqlite | none", "notes": ""},
  "almPlatform": "jira | ado | none",
  "accessibilityStandard": ["WCAG 2.1 AA"],      // add jurisdiction-specific standards only if the user names them
  "regulations": [],                               // free-text names of regulations/policies the user confirmed
  "capabilityGroupingDimension": "functional | business-unit",
  "capabilityGroups": [ {"id": "GRP-01", "name": "…", "dimension": "functional | business-unit", "capabilities": ["CAP-01"]} ],
  "selectedCapabilityGroups": ["ALL | GRP-01"],    // specific group ID(s) or ["ALL"] when all groupings are selected
  "commands": {
    "install": "…",            // optional
    "build":   "…",            // optional
    "start":   "…",            // REQUIRED by Stage 4A when backend.kind != none; must serve UI + API
    "healthcheck": "http://127.0.0.1:8080/health",  // REQUIRED when start is set
    "uiEntry": "src/ui/index.html | http://127.0.0.1:8080/",  // where Stage 6 loads the UI from
    "test":    "…"             // optional project-native unit tests
  },
  "decidedBy": "user | pending-stage-4a | autonomous-default"
}
```
- **Never silently assume `static-html` + Python in Interactive Mode:** During Stage 1 (Current-State Discovery) and Stages 2–3 (Functional Spec & User Stories), if the user has not yet chosen a Future-State technology stack, `specs/target_stack.json` sets `frontend.kind = "tbd"`, `backend.kind = "tbd"`, `database.kind = "tbd"`, and `decidedBy = "pending-stage-4a"`.
- **Mandatory Stage 4A Future-State Tech Stack Intake & Pure Target-State Design (`design/`):** When entering **Stage 4A (`04-solution-architect`)** from the Spec / Sprint Plan, if `decidedBy != "user"` or any stack component is `"tbd"`, `solution-architect` **MUST ask the human what Future-State frontend, backend, database, and deployment technology stack to use**, and update `specs/target_stack.json` with `decidedBy = "user"` before authoring `design/solution_design.md`. Both `design/architecture_design.md` and `design/solution_design.md` must describe **only the Target State ("To-Be")** (target runtime, target managed database e.g. `AlloyDB` / `Cloud SQL` / `PostgreSQL`, `OIDC / IAP` authentication, `Cloud KMS`, `Cloud Logging` / `Monitoring` / `OpenTelemetry`). **Local testing details (`APP_ENV=local`, `AUTH_MODE=local-mock`, `STORAGE_BACKEND=local-fs`, `local_dev_runner`) must never go into `design/architecture_design.md` or `design/solution_design.md`** (`04/scripts/extract_contracts.py` fails Gate 4A if local-testing mock flags appear in the design or if `specs/target_stack.json` is downgraded to `static-html` + `python-stdlib-http` when another stack is designed).
- **Target-Stack Implementation in Stage 5 (`06-coding-agent`) & Stage 7 (`08-container-and-gdc-packager`):** Stage 5 **never** ignores `specs/target_stack.json` to build a throwaway Python `http.server` app just for local testing. Instead, `coding-agent` authors the complete `src/ui/` and `src/backend/` codebase and manifests (`package.json`, `pom.xml`/`build.gradle`, `requirements.txt`, `go.mod`, `.csproj`) in the confirmed Target Stack with 12-Factor environment configuration in `src/` so the **same target-stack codebase** runs locally for testing (`bash src/run.sh`) during Stages 5–6 and deploys to the target cloud/GDC environment (`deploy/containers/Dockerfile.*`, `DATABASE_URL`, `OIDC / IAP`) in Stages 7–8. `06/scripts/validate_build.py` and `08/scripts/validate_gdc_packaging.py` verify the target-stack artifacts and container base images and fail the gate if a Python substitute was used.

### 4.3 `specs/application_spec.md` required structure (LLM) — linted by `02/scripts/lint_spec_structure.py`
- `# <Project Name>` and a header block with `Input Scenario`, `Domain Slug`.
- `## 1 Pillar 1 — Functionality` containing `REQ-FUNC-NN` items; `### 1.4 Modernization Enhancements (REQ-ENH-NN)` **only if legacy**.
- `## 2 Pillar 2 — Security` (`REQ-SEC-NN`), `## 3 Pillar 3 — Accessibility` (`REQ-A11Y-NN`),
  `## 4 Pillar 4 — UX & Zero Leakage` (`REQ-UX-NN`), `## 5 Pillar 5 — Architecture` (`REQ-ARCH-NN`).
- `### 3.3 Lifecycle State Machine` — exactly one ```` ```mermaid stateDiagram-v2 ```` block, **plus** a table
  `| From | To | Trigger | Actor Role | Guard |` that mirrors it (this table is what scripts parse).
- `### 3.4 Business Rules & Formulas` — a table `| Rule ID | Formula / Rule | Inputs | Source |` (Rule IDs `BR-NN`).
- `### 3.5 Roles` — a table `| Role | Kind | Views | Allowed Transitions |`  (Kind values: `external` or `internal`; never put a pipe inside a header cell).
- `### 4.2 View & Component Topology Table` — a table `| View ID | Navigation Tab / Route | UI Pattern | Bound Role(s) | Primary CTA & Lifecycle Trigger |` (parsed by `dlc_common.parse_view_topology`; when `specs/design_reference/reference_ui_manifest.json` exists, every reference view/tab must be mapped).
- Every REQ id unique; every REQ appears in `traceability_matrix.md`.

### 4.4 `specs/application_eval_scorecard.json` (LLM judge, validated by `02/scripts/validate_spec_scorecard.py`)
```json
{"schemaVersion":"4.0","rubricVersion":"4.0","specSha256":"…","inputScenario":"…",
 "criteria":[{"id":"P1-C1","pillar":1,"maxPoints":5,"awarded":4,"evidence":"<verbatim quote from spec>","gap":"what is missing"}],
 "pillarTotals":{"1":22,"2":18,"3":18,"4":14,"5":18},"totalScore":90,"verdict":"PASS|FAIL",
 "blockingGaps":["…"]}
```
Validator checks: every rubric criterion present, awarded ≤ max, totals add up, `specSha256` matches the current
spec (stale scorecards fail), `evidence` is a non-empty substring of the spec for any criterion awarded > 0,
verdict == (total ≥ 90 and no criterion marked `blocking` scored 0). Exit code 1 on FAIL.

### 4.5 `backlog/user_stories.json` (LLM + ALM bridge traceability enrichment)
```json
{"schemaVersion":"4.0","stories":[{
  "id":"US-FUNC-01","type":"Functional|Technical","title":"…","narrative":"As a … I want … so that …",
  "capabilityGroup":"GRP-01|SHARED","capabilityGroupName":"…",
  "requirementRefs":["REQ-FUNC-01"],"businessRuleRefs":["BR-01"],"legacyArtifactsReplaced":[],
  "roles":["<role names from spec §3.5>"],"workflowTransitions":["DRAFT->SUBMITTED"],
  "sprint":"Sprint 1 .. Sprint N | Product Backlog","priority":"Highest|High|Medium|Low","storyPoints":3,
  "traceability":{
    "legacySourceArtifacts":["…"],"requirementRefs":["REQ-FUNC-01"],"businessRuleRefs":["BR-01"],
    "workflowTransitions":["DRAFT->SUBMITTED"],"apiContracts":["POST /api/…"],"databaseTables":["…"],
    "targetSourceFiles":["src/ui/index.html","src/backend/server.py","src/db/schema.sql"],
    "uiTestIds":["…"],"testCases":[{"id":"TC-POS-01","category":"Positive","status":"PASS"}],
    "defectRefs":["BUG-01 (Done)"]
  },
  "acceptanceCriteria":[{"id":"AC-01","tag":"POSITIVE|NEGATIVE|NEGATIVE — ROLE VISIBILITY|NEGATIVE — WORKFLOW PREREQUISITE GATE|POSITIVE — INTERACTIVE COMPLETENESS|EDGE / BOUNDARY","given":"…","when":"…","then":"…"}]
}]}
```
- **Dynamic Story & Sprint Counts:** Never hardcode to 3 sprints or a fixed story count. Story count (`US-FUNC-01..M`, `US-TECH-01..K`) scales from the capability inventory; sprint count (`Sprint 1..N`) scales from capability-group topological order (`isSharedFoundation`, `dependsOnGroups`) and sprint velocity capacity (`specs/target_stack.json#sprintCapacityPoints` or `--sprint-capacity-points`, default `21 SP` per sprint).
- Strings in the old `"[POSITIVE] GIVEN … WHEN … THEN …"` form are still accepted by scripts (parsed), but new output must use the object form.

### 4.6 `test/test_cases.json` (Stage 4B: script derives, LLM completes `steps`)
```json
{"schemaVersion":"4.0","derivedFrom":{"userStoriesSha256":"…","specSha256":"…"},
 "forbiddenUiTokens":{"schemaIdentifiers":["…from src/db/schema.sql + openapi internal fields"],"enumCodes":["…from spec/state table"],"legacyIdentifiers":["…from input_inventory legacy file stems"]},
 "testCases":[{
   "id":"TC-POS-01","category":"Positive|Negative|Edge|UiLeak|State|Interact|A11y|Api",
   "storyRef":"US-FUNC-01","acRef":"AC-01","requirementRefs":["REQ-FUNC-01"],
   "title":"…","expected":"…",
   "runtime":"browser|http|static",
   "role":"<role name or null>",
   "steps":[
     {"action":"goto","target":"ui"},
     {"action":"setRole","value":"Applicant"},
     {"action":"fill","selector":"[data-testid=applicant-name]","value":"…"},
     {"action":"click","selector":"[data-testid=submit-btn]"},
     {"action":"expectText","selector":"[data-testid=status-badge]","contains":"Submitted"},
     {"action":"expectHidden","selector":"[data-testid=approve-btn]"},
     {"action":"expectDisabled","selector":"…"},{"action":"expectEnabled","selector":"…"},
     {"action":"expectCount","selector":"…","equals":3},
     {"action":"expectNoVisibleTextMatching","pattern":"regex"},
     {"action":"httpRequest","method":"POST","path":"/api/…","json":{},"expectStatus":201,"expectJsonPath":"$.status","equals":"SUBMITTED"},
     {"action":"wait","ms":100}
   ]}]}
```
Derivation rules (`05/scripts/derive_test_cases.py`):
- one TC per AC (`TC-POS/NEG/EDGE-*` by tag) with `steps:[]` and `"needsSteps":true` for the LLM to fill;
- `TC-POS-JOURNEY-01` (Default Landing Persona Entry-to-Submit Journey on `runtime: "browser"`, starting from a fresh `goto("ui")` without calling `setRole`);
- one `TC-STATE-*` per **illegal** transition implied by the state table (for each state S and each trigger T
  not allowed from S: attempting T must be blocked) and one per role that lacks a transition;
- `TC-UI-INTERACT-TAB-01..N` (Mutual Tab Exclusivity & Layout Switching on `runtime: "browser"` derived from `§4.2 View & Component Topology Table`, asserting `expectAttribute(..., "aria-selected", "true")`, `expectVisible` on the target `[role="tabpanel"]`, and `expectHidden` on sibling panels);
- `TC-UI-LEAK-01..04` with `forbiddenUiTokens` populated from DDL/openapi/state table/legacy stems;
- `TC-UI-INTERACT-01` (every interactive element has a handler and produces a DOM change — generic);
- `TC-API-*` one per OpenAPI operation (status code smoke) when backend ≠ none;
- `TC-A11Y-01` (labels, roles, contrast tokens) static.
`data-testid` values are **declared by the test plan first**; the coding agent must implement them (contract-first).

### 4.7 `test/eval_results.json` (Stage 6 script)
```json
{"schemaVersion":"4.0","evaluatedAtUtc":"…","iteration":1,"runtime":{"browser":"chrome-headless|playwright|none","backendStarted":true},
 "results":[{"id":"TC-POS-01","status":"PASS|FAIL|NOT_RUN|ERROR","runtime":"browser","durationMs":12,"failedStep":3,"message":"…","actual":"…"}],
 "summary":{"total":0,"pass":0,"fail":0,"notRun":0,"error":0,"score":0.0,"verdict":"PASS|FAIL"},
 "leakage":{"tokensScanned":0,"hits":[{"token":"…","context":"…"}]},
 "interactivity":{"controls":0,"unwired":[{"selector":"…","reason":"…"}]},
 "a11y":{"findings":[]},
 "screenshots":["test/.snapshots/iter-1/screenshots/00-initial-desktop-1440x900.png"]}
```
`NOT_RUN` never counts as pass; verdict PASS requires zero FAIL/ERROR/NOT_RUN among non-optional tests.

### 4.8 Stage 6 runtime
- `07/scripts/run_closed_loop_eval.py` executes `test_cases.json`:
  - **browser** steps via adapter chain: `playwright` (python, executing native `page.locator(selector)` hit-testing, `bounding_box()` visibility checks, automatic `[role="tab"]`/`[role="tabpanel"]` mutual-exclusivity checks, and viewport screenshot capture) → `chrome-headless` (any Chrome/Chromium/Edge binary; zero deps; harness injects `dom_driver.js` with `getBoundingClientRect()` non-zero bounding-box & tab-exclusivity verification plus `--screenshot` capture) → `none` (NOT_RUN).
  - **http** steps via `urllib` after starting `target_stack.commands.start` and polling `healthcheck`.
  - **static** steps (leakage scan of visible text, handler-wiring scan, a11y lint) with stdlib `html.parser`.
- Before each iteration it snapshots `src/` to `test/.snapshots/iter-N/`; the audit report §2 is
  `difflib.unified_diff(iter-(N-1), iter-N)`; §3 classifies each hunk by touching guardrail-sensitive regions
  (role checks, state guards, formulas listed in spec §3.4, aria/labels, masking) and flags
  `GUARDRAIL_REVIEW_STATUS: FLAGGED_REQUIRES_HUMAN_APPROVAL` when any such hunk exists. Nothing is hard-coded PASS.
- On every Stage 6 iteration, `run_closed_loop_eval.py` invokes `alm_jira_ado_bridge.py --action sync-status-from-eval`, which:
  1. Creates/updates `BUG-01..N` (`issueType: "Bug"`) in `backlog/defects.{json,md}` (`schemas/defects.schema.json`) and live Jira (`issuetype: {"name": "Bug"}`) / ADO (`Bug`) for any failing non-optional test case, recording what the bug was and full traceability to the parent story, requirements, and source code.
  2. When a subsequent iteration fixes the failing test (`FAIL -> PASS`), diffs `test/.snapshots/iter-(N-1)` vs `iter-N`, posts a remediation comment on the Jira/ADO `Bug` detailing the exact steps and code changes taken to fix the defect, and transitions the `Bug` to `Done`.
  3. Refreshes `story.traceability` and transitions verified User Stories to `Done`.

## 5. Gates (unchanged in spirit, now enforceable)

| Gate | Enforced by | Pass condition |
| :-- | :-- | :-- |
| 1 Context intake | `01/validate_discovery_blueprint.py` + `target_stack.json` present | Scenario confirmed, strictly Current-State ("As-Is") ERD & legacy object inventory (no future-state 3NF/DDL/Legacy→Target mapping mixed in), state machine present with transition table, stack chosen |
| 2 Spec judge | `02/validate_spec_scorecard.py` | LLM scorecard valid, fresh, total ≥ 90, no blocking gap |
| 3 Sprint approval | `03/alm_jira_ado_bridge.py --action audit` + human | 100% REQ coverage, ≤ 8 SP, human `APPROVED_BY_USER` (or pre-approved) |
| 4a Contracts & Architecture | `04/extract_contracts.py` | Human-confirmed Future-State tech stack (`target_stack.json`), standalone `design/architecture_design.md` (`§1 Logical Solution Architecture` & `§2 Technical & Deployment Solution Architecture` flowcharts with Google Cloud `classDef` palette + `style <SG_ID>`, `§3` `sequenceDiagram`, `§4` Layering table, `§5` Well-Architected 6-Pillar + Sustainability & Failure-Mode Grilling matrices), standalone `design/solution_design.md` (`§1` Future-State 3NF `erDiagram`, `§1.1` Legacy→Target mapping if legacy, OpenAPI + DDL extracted and parse) |
| 4b Tests | `05/derive_test_cases.py` + `05/validate_test_cases.py` | every AC has a TC; every TC has steps; schema valid |
| 5 Build | `06/validate_build.py` | `install/build/start/healthcheck` succeed per `target_stack.json` |
| 6 Closed loop | `07/run_closed_loop_eval.py` | verdict PASS, leakage 0 hits, no unwired controls, guardrail flags approved |
| 7 Container & GDC pkg | `08/validate_gdc_packaging.py` | Zero cloud-provider SDK lock-in in `src/`, hardened rootless OCI images, Kustomize base + 4 GDC overlays (`on-prem-gdc`, `gcp`, `aws`, `azure`), Policy Controller constraints, Cloud Service Mesh mTLS + Spec `§3.5` RBAC |
| 8 GDC Fleet deploy & obs | `09/run_gdc_fleet_deploy_and_verify.py` | Config Sync GitOps RootSync & ClusterSelectors valid, OpenTelemetry Collector + SLOs + multi-cloud dashboard valid, runbook complete, local `/health` smoke probe PASS (`MANIFEST_VALIDATED` by default; `DEPLOYED` / `gdc-live-fleet` only when `--live` `kubectl apply` succeeds across all target environments) |

## 6. Writing rules for skills & agents (v4)

- ≤ 150 lines each. Reference `_shared/*.md` instead of pasting.
- Describe **how to derive** things from upstream artefacts; never give domain examples outside a clearly
  marked `Example (illustrative only, from examples/…)` one-liner, and keep even those domain-neutral where
  possible (e.g. "a fee formula", "a submit button").
- Every "MUST" that a script can check should name the script.
- Greenfield and legacy paths are both first-class; say explicitly what differs.

## 7. Ratified implementation addenda (v4.0.0)

- `test_cases.json` step actions additionally include `select`, `expectVisible`, `expectAttribute`, `pressKey`,
  `check`, `uncheck`, and the static-only `expectAllControlsWired` (TC-UI-INTERACT-01), `expectA11yBaseline`
  (TC-A11Y-01), `expectSourceContains`, `expectSourceMatches`. `httpRequest.expectStatus` may be an int or an
  int array. Test cases carry `needsSteps`, `optional`, `derivationKey`, `derivation`; the file carries
  `retiredTestCases`. Re-derivation preserves authored steps by `derivationKey`.
- `forbiddenUiTokens` classes: `schemaIdentifiers`, `schemaIdentifiersIgnored` (single plain words skipped to
  avoid false positives), `enumCodes` (UPPER_SNAKE of all states and triggers + OpenAPI enums),
  `legacyIdentifiers`, `piiPatterns` (regexes), `engineeringNotePatterns`. Generic heuristics are warnings.
- `schemas/spec_rubric.json` criteria may carry `appliesTo: ["SCENARIO_LEGACY_APP"]`; non-applicable criteria are
  awarded full points with evidence `N/A …`.
- Validators fail on **stale** artefacts: scorecard vs spec SHA, test cases vs stories/spec SHA.
- `run_closed_loop_eval.py` exit codes: 0 PASS & guardrail CLEAR/approved, 1 FAIL, 3 PASS but
  `FLAGGED_REQUIRES_HUMAN_APPROVAL` (Gate 4). `--approve-guardrail-flags` records the human decision.
- Pipeline exit codes: 0 all pass, 1 a gate failed, 2 an artefact is missing (prints the authoring
  skill/agent), 3 Gate 4 needs human approval.
