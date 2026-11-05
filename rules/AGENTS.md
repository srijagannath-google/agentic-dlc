# Agentic DLC Router & Gates (`agentic-dlc`)

You are operating inside the **Agentic Development Lifecycle (DLC) harness v4** — "Think Big, Start Small,
Move Fast": the **Elephant** (deep-context discovery/spec author), the **Judge** (adversarial spec judge and
test runner) and the **Goldfish** (clean-context coder). The harness is **domain-neutral** and
**scenario-aware**: it modernises **legacy applications** (`SCENARIO_LEGACY_APP`) and builds **greenfield
systems from requirements documents** (`SCENARIO_REQUIREMENTS_DOC`) as equal, first-class paths.

> **The one rule that governs everything:** the LLM (skills + subagents) **authors** every project artefact
> from the user's inputs; scripts only **scan, derive, lint, execute and gate**. No script ever writes a spec,
> story, design, test plan, UI or backend from a template, and no script prints a static PASS.

`<PLUGIN>` below means the installed plugin directory (normally `~/.gemini/config/plugins/agentic-dlc`).
Before any stage, read `<PLUGIN>/docs/ARCHITECTURE.md` (binding artefact contracts) and the `_shared/*.md`
files a skill names. Never paste their text into project files; reference them.

---

## 0. `<PROJECT_ROOT>` (read `<PLUGIN>/_shared/project_root.md` — summary only)

1. The plugin directory (any folder named `agentic-dlc*`) is **never** `<PROJECT_ROOT>`; never create
   `resources/ specs/ backlog/ design/ test/ src/` inside it.
2. Resolve in order: `~/.gemini/config/project_root.txt` → cwd (if not a plugin dir) → parent of a plugin dir
   nested in a project → otherwise **ask the user** before writing anything.
3. Pass `--project-root "<PROJECT_ROOT>"` to every script; scripts refuse plugin directories.
4. Write only inside `<PROJECT_ROOT>/{resources,specs,backlog,design,test,src,deploy}/`; never write scratch files
   there and never attach artifact metadata to project files.

```text
<PROJECT_ROOT>/
├── resources/{inputs,design_references,policies_and_statutes,shared_services}/   # user-provided only
├── specs/     project_setup.json · gate_approvals.json · input_inventory.json · discovery_architecture_and_inventory.md
│              target_stack.json · application_spec.md · traceability_matrix.md · application_eval_scorecard.{md,json}
├── backlog/   user_stories.{md,json} · sprint_plan.{md,json} · jira_import.csv · jira_state.json · azure_devops_state.json
├── design/    architecture_design.md (portfolio index) · business_architecture.md · high_level_solution_architecture.md
│              logical_architecture.md · application_architecture.md · data_architecture.md · security_architecture.md
│              infrastructure_architecture.md · solution_design.md · data_migration_and_cutover.md (legacy scenario only)
├── test/      test_plan.md · test_cases.json · eval_report.md · eval_results.json
│              remediation_and_guardrail_audit_report.md · history/iter-N/ · .snapshots/iter-N/ · *.iter-NN.*
├── src/       contracts/openapi.yaml · db/schema.sql · ui/ · backend/ · run script · README.md
└── deploy/    containers/ · gdc/{base,overlays/{on-prem-gdc,gcp,aws,azure},policy-controller,service-mesh,config-sync}/
               observability/ · deployment_and_runbook.md · deployment_eval_report.{md,json}
```

---

## 1. Lifecycle, skills, subagents and gates

> **HARD-STOP HUMAN GATE RULE (MANDATORY AT EVERY STAGE IN INTERACTIVE MODE):**
> 1. **Execute AT MOST ONE STAGE per user turn.** Never chain Stage 0 → Stage 1, Stage 1 → Stage 2, Stage 2 → Stage 3, etc., without returning to the human first.
> 2. **Stage 0 (`00-setup-and-connection`) comes first** whenever the user asks to configure/connect Azure DevOps (ADO) or Jira, initialize a project, or start the DLC. If connecting to ADO, you **MUST** list the available ADO Projects (`setup_project_connection.py --action list-ado-projects`), **ask the user which ADO Project (and repository) they want to work on**, save `specs/project_setup.json`, and **STOP at Gate 0** — never start Stage 1 during connection setup!
> 3. **End Your Turn at Every Gate (`gate_0_setup` .. `gate_7_packaging`):** When a stage completes validation, `dlc_common.mark_gate_awaiting_human` stamps `AWAITING_HUMAN_REVIEW` in `specs/gate_approvals.json`, blocking all downstream stage scripts. Present the stage's deliverables and open questions to the user, and **END YOUR TURN IMMEDIATELY (call zero more tools)**.
> 4. **Record Approval Only in the Next Turn:** Only **after** the human replies in a subsequent turn explicitly approving the gate, run `python3 <PLUGIN>/scripts/gate_tracker.py --project-root "<PROJECT_ROOT>" --action approve --gate <gate_id> --user-response "<verbatim user quote>"` before starting the next stage. Never self-approve a gate in the same turn!

| Stage | Skill (`<PLUGIN>/skills/…/SKILL.md`) | Subagent(s) | Authors (LLM) | Verifies / Enforces (script) | Mandatory Human Gate |
| :-- | :-- | :-- | :-- | :-- | :-- |
| **0 Setup & connection** | `00-setup-and-connection` | coordinator | Connects to ADO / Jira, **lists ADO Projects & Repos, asks user which ADO Project & repository/input source to work on**, writes `specs/project_setup.json` | `00/scripts/setup_project_connection.py --action check-env \| list-ado-projects \| list-ado-repos \| list-jira-projects \| save-setup` | **Gate 0 (`gate_0_setup`)** — **STOP & wait** for human confirmation of project/repo before Stage 1 |
| 1 Discovery & intake | `01-discovery-and-grouping` | `discovery-architect` | Authors `specs/discovery_architecture_and_inventory.md` (**Current-State "As-Is" only**), `specs/target_stack.json` | `01/scripts/scan_input_sources.py` → `specs/input_inventory.json`; `01/scripts/validate_discovery_blueprint.py` | **Gate 1 (`gate_1_discovery`)** — **STOP & wait** for human review + capability group selection |
| 2 Spec & judge | `02-spec-architect-and-judge` | `discovery-architect`, `spec-judge` | `specs/application_spec.md`, `specs/traceability_matrix.md`, `specs/application_eval_scorecard.{md,json}` | `02/scripts/lint_spec_structure.py`, `02/scripts/validate_spec_scorecard.py` | **Gate 2 (`gate_2_spec`)** — total ≥ 90, no blocking gap, then **STOP & wait** for human spec approval |
| 3 Stories & sprints | `03-story-and-sprint-planner` | `sprint-planner-agent` | `backlog/user_stories.{md,json}`, `backlog/sprint_plan.md` | `03/scripts/alm_jira_ado_bridge.py --action audit \| sync-stories \| set-approval \| sync-sprints \| transition-stories \| sync-status-from-eval \| sync-deployment-status \| export-csv` | **Gate 3 (`gate_3_backlog`)** — **STOP & wait** for human sprint alignment approval |
| 4A Design | `04-solution-architect` | `solution-architect` | Confirms **Future-State Tech Stack** with human (`specs/target_stack.json`), then authors the **Multi-Perspective Architecture Suite as separate artifacts under `design/`**: (1) `design/business_architecture.md`, (2) `design/high_level_solution_architecture.md` (AI-Era System of Engagement / System of Intelligence & AI / Systems of Record), (3) `design/logical_architecture.md`, (4) `design/application_architecture.md` (C4 components + `sequenceDiagram`), (5) `design/data_architecture.md` (5-stage data/RAG pipeline + 3NF `erDiagram`), (6) `design/security_architecture.md` (5-layer defense-in-depth + AI Trust Layer), (7) `design/infrastructure_architecture.md` (multi-region topology + Well-Architected & Grilling matrices), (8) `design/architecture_design.md` (Executive Portfolio Index), and (9) `design/solution_design.md` (`§1` 3NF `erDiagram`, `§1.1` Legacy→Target mapping, `§1.2` DDL, `§2` OpenAPI, ViewModel/DTO mapping; + `data_migration_and_cutover.md` if legacy) | `04/scripts/extract_contracts.py` → `src/contracts/openapi.yaml`, `src/db/schema.sql`, `design/diagrams/*.{svg,png}` | **Gate 4A/4B (`gate_4_design_and_tests`)** — human tech-stack choice + **STOP & wait** for human design & test-plan approval |
| 4B Test plan | `05-test-plan-designer` | `testing-agent` | `test/test_plan.md`; completes `steps` in `test/test_cases.json` | `05/scripts/derive_test_cases.py` (skeleton), `05/scripts/validate_test_cases.py` | **Gate 4A/4B (`gate_4_design_and_tests`)** — every AC has a TC with steps; **STOP & wait** before Stage 5 |
| 5 Build | `06-coding-agent` + `google-cloud-ui-design` | `coding-agent` | `src/**` runnable per `target_stack.json` (+ `src/README.md`, run script) with Google Cloud UI Design (`_shared/google_cloud_ui_design.md`) | `06/scripts/validate_build.py` (automatically transitions active sprint stories from `To Do` → `In Progress`) | **Gate 5 (`gate_5_build`)** — install/build/start/healthcheck pass; **STOP & wait** for human build review |
| 6 Closed loop | `07-test-runner-and-healer` | `testing-agent`, `coding-agent`, `solution-architect` | fixes only | `07/scripts/run_closed_loop_eval.py` → `test/eval_*`, audit report (+ automatically transitions verified stories to `Done` via `sync-status-from-eval`) | **Gate 6 (`gate_6_eval`)** (+ guardrail flags) — **STOP & wait** for human evaluation & audit approval |
| 7 Container & GDC pkg | `08-container-and-gdc-packager` | `platform-ops-agent` | `deploy/containers/*`, `deploy/gdc/{base,overlays/{on-prem-gdc,gcp,aws,azure},policy-controller,service-mesh}/*` | `08/scripts/validate_gdc_packaging.py` | **Gate 7 (`gate_7_packaging`)** — **STOP & wait** for human container & KRM packaging approval |
| 8 GDC Fleet deploy & obs | `09-gdc-fleet-deployer-and-observability` | `platform-ops-agent` | `deploy/gdc/config-sync/*`, `deploy/observability/*`, `deploy/deployment_and_runbook.md` | `09/scripts/run_gdc_fleet_deploy_and_verify.py` → `deploy/deployment_eval_report.{md,json}` (+ `sync-deployment-status`) | **Gate 8** — GDC Fleet GitOps, SLOs & observability verified |

Stages 4A and 4B run in parallel **only after** human approval of Gate 3 (`gate_3_backlog`). Every other stage runs strictly one stage at a time with an explicit human review & approval stop between stages. Stages 7 and 8 package and deploy the verified application across Google Distributed Cloud (GDC) Fleet targets (`on-prem-gdc`, `gcp`, `aws`, `azure`).

### Routing by intent
| User says (intent) | Load skill | Invoke |
| :-- | :-- | :-- |
| "connect to ADO / Jira", "configure connection", "set up project", "which ADO project", "start a new project" | `00-setup-and-connection` | coordinator (**STOP after setup & ADO project selection — NEVER start Stage 1 in the same turn**) |
| "analyse this legacy app / database export / BRD", "extract ERD, state machine, capabilities" | `01-discovery-and-grouping` | `discovery-architect` (requires `gate_0_setup` approved; **STOP at Gate 1**) |
| "write the spec", "run the spec judge", "score the spec" | `02-spec-architect-and-judge` | `discovery-architect` then `spec-judge` (requires `gate_1_discovery` approved; **STOP at Gate 2**) |
| "create user stories / sprint plan", "push to Jira / Azure DevOps" | `03-story-and-sprint-planner` | `sprint-planner-agent` (requires `gate_2_spec` approved; **STOP at Gate 3**) |
| "design the architecture / schema / API", "data migration plan" | `04-solution-architect` | `solution-architect` (requires `gate_3_backlog` approved; **STOP at Gate 4A/4B**) |
| "write the test plan / test cases" | `05-test-plan-designer` | `testing-agent` (requires `gate_3_backlog` approved; **STOP at Gate 4A/4B**) |
| "build the app / UI / backend", "design a high-quality Google Cloud UI" | `06-coding-agent`, `google-cloud-ui-design` | `coding-agent` (requires `gate_4_design_and_tests` approved; **STOP at Gate 5**) |
| "run the tests", "what failed, what changed, any guardrail issues" | `07-test-runner-and-healer` | `testing-agent` (+ `coding-agent`, `solution-architect` for fixes; requires `gate_5_build` approved; **STOP at Gate 6**) |
| "containerize the app", "package for GDC / multi-cloud / on-prem" | `08-container-and-gdc-packager` | `platform-ops-agent` (requires `gate_6_eval` approved; **STOP at Gate 7**) |
| "deploy to GDC fleet", "configure multi-cloud GitOps / monitoring / SLOs" | `09-gdc-fleet-deployer-and-observability` | `platform-ops-agent` (requires `gate_7_packaging` approved) |

---

## 2. Cross-stage invariants (apply at every stage)

1. **Scenario awareness & Current-State vs. Future-State Separation.** Read `specs/input_inventory.json#inputScenario` first. Stage 1 (`specs/discovery_architecture_and_inventory.md`) documents **only the Current State ("As-Is")** (current-state data model `erDiagram`, `§2.1` current-state legacy object inventory, current-state workflow state machine, pain points, capability groupings — never future-state 3NF schemas, future-state flow diagrams, or legacy-to-target mappings). Stage 4A (`design/solution_design.md` and `design/data_migration_and_cutover.md`) owns **all Future-State ("To-Be") design** (future-state flow diagrams, future-state normalised 3NF `erDiagram`, `§2.1` Legacy-to-Target 3NF entity mapping, target DDL, and OpenAPI). Legacy-only artefacts —
   current-state legacy object inventory in Stage 1, legacy→target entity mapping in Stage 4A, `design/data_migration_and_cutover.md`, `REQ-ENH-*` modernization
   enhancements — exist **only** for `SCENARIO_LEGACY_APP`. For `SCENARIO_REQUIREMENTS_DOC` specify the
   documented scope exactly; never inject unsolicited features. If `scenarioConfidence` is `LOW`, ask.
2. **Workflow chain of custody** (`_shared/workflow_chain_of_custody.md`). The lifecycle state machine is
   extracted from inputs at Stage 1 (or asked of the user — never invented), frozen in spec §3.3 as a
   `stateDiagram-v2` **plus** a `| From | To | Trigger | Actor Role | Guard |` table, and every downstream
   artefact derives from that table. Roles come from spec §3.5; business rules/formulas from spec §3.4.
3. **Ask, don't assume.** Unclear workflow, roles, rules, stack or regulations → ask at the next gate. In
   autonomous mode choose the most restrictive reading and record it as `ASSUMPTION-NN` in the spec.
4. **Clean target.** Never carry legacy internals (table/form/report/query names, dead columns, fixed-width
   record adapters, dual-run bridges) into target design or code. This does **not** forbid integrations a
   requirements document legitimately demands; those are requirements and are specified as such.
5. **Zero internal data leakage in UI** (`_shared/zero_leak.md`), the **UX guardrails**
   (`_shared/ux_guardrails.md`), and the **Google Cloud UI Design System** (`_shared/google_cloud_ui_design.md`
   & `skills/google-cloud-ui-design/SKILL.md`: Surface Mode `Operate`/`Read`/`Persuade`/`Express` + 6 layout
   blueprints, `:root`/`.dark` `--g-*` Material 3 CSS tokens with `defaultTheme="system"`, ShadCN UI + Radix
   primitives, Unified Surfaces with `divide-x`/`divide-y` + `<dl>` grids, `tabular-nums`, 4-state coverage, and
   the 8 Anti-Slop bans) are defaults for every generated UI; user design references in
   `resources/design_references/` or explicit Gate 1 instructions override them (record overrides in spec §4).
6. **Contract-first test IDs.** `data-testid` values are declared in `test/test_cases.json` first; the coder
   implements them. Accessibility baseline is WCAG 2.1 AA; add jurisdiction-specific standards only when the
   user names them (`specs/target_stack.json#accessibilityStandard`).
7. **Future-State technology stack is chosen by the human, `design/` documents are 100% Target-State (zero local-testing details in design), and Stage 5 builds the Target Stack so it can be both tested locally and deployed to the target environment.**
   - When entering Stage 4A (`04-solution-architect`) from the Spec/Sprint Plan, if `specs/target_stack.json` does not yet have an explicit human-confirmed stack (`decidedBy != "user"` or `"tbd"`), `solution-architect` **must ask the human what Future-State frontend, backend, database, and deployment stack to use** (never silently assuming `static-html` + Python, and never setting `specs/target_stack.json` to `static-html` + `python-stdlib-http` while recommending another stack in `design/architecture_design.md`).
   - **Stage 4A (`design/architecture_design.md` and `design/solution_design.md`) is 100% Target-State ("To-Be"):** Design documents must describe **only the Target State** (target frontend/backend runtimes, target managed database e.g. `AlloyDB` / `Cloud SQL` / `PostgreSQL`, `OIDC / IAP` authentication, `Cloud KMS`, `Cloud Logging` / `Monitoring` / `OpenTelemetry`). **Local testing concerns (`APP_ENV=local`, `AUTH_MODE=local-mock`, embedded SQLite fallback, `local_dev_runner`) must never go into `design/architecture_design.md` or `design/solution_design.md`** (`04/scripts/extract_contracts.py` fails Gate 4A if local-testing mock flags appear in the design).
   - In Stage 5 (`06-coding-agent`), `coding-agent` **must build `src/ui/` and `src/backend/` in the confirmed Target Stack (`specs/target_stack.json`)** with 12-Factor environment configuration in `src/` so the **same target-stack codebase** is:
     1. **Testable locally (`bash src/run.sh`)** in Stages 5 & 6 (`validate_build.py` and `run_closed_loop_eval.py`); and
     2. **Deployable to the target cloud / GDC environment (`deploy/containers/Dockerfile.*` & `deploy/gdc/`)** using multi-stage target-stack container builds, managed `DATABASE_URL` (`AlloyDB` / `Cloud SQL` / `PostgreSQL` with `PgBouncer` pooling), `OIDC / IAP`, and OpenTelemetry / Cloud Operations.
   - `04/scripts/extract_contracts.py`, `06/scripts/validate_build.py`, and `08/scripts/validate_gdc_packaging.py` fail the gate if the agent ignores `specs/target_stack.json` and substitutes a standalone Python `http.server` + `static-html` implementation.
8. **Context isolation.** `coding-agent` (Goldfish) reads only the approved upstream artefacts listed in
   `06-coding-agent/SKILL.md` — never raw legacy sources.
9. **End-to-end ALM story status progression (`To Do` → `In Progress` → `Done`).** Stories start in `To Do` at
   Stage 3 (`alm_jira_ado_bridge.py --action sync-stories`), automatically transition to `In Progress` when
   Stage 5 build validation passes (`validate_build.py` → `--action transition-stories --target-status "In Progress"`),
   and automatically transition to `Done` in local backlog files and on live Atlassian Jira / Azure DevOps
   boards once Stage 6 evaluation passes all linked test cases (`run_closed_loop_eval.py` → `--action sync-status-from-eval`).

---

## 3. Human gates (Machine-Enforced via `specs/gate_approvals.json` & `scripts/gate_tracker.py`)

Every stage boundary is enforced in code (`dlc_common.require_gate_approved` / `dlc_common.mark_gate_awaiting_human`). Downstream scripts exit with `GateFailure` if the upstream gate is not `APPROVED_BY_USER`, and `gate_tracker.py --action approve` enforces a turn-boundary cooldown + verbatim `--user-response` so an agent can **never** self-approve a gate in the same turn.

| Gate ID (`specs/gate_approvals.json`) | When | Default Interactive Behaviour (Mandatory STOP) | Pre-approved / `--autonomous` Behaviour |
| :-- | :-- | :-- | :-- |
| `gate_0_setup` (**Gate 0**) | Stage 0 (`00-setup-and-connection`) before Stage 1 | Connect to ADO/Jira, **list available ADO Projects (`list-ado-projects`) and ask which ADO Project (and repository) the user wants to work on** (or confirm local/Git input source), write `specs/project_setup.json`, **END TURN**, and wait for explicit user approval | Use the input source named in prompt or populated `<PROJECT_ROOT>/resources/inputs/` |
| `gate_1_discovery` (**Gate 1**) | After Stage 1 (`validate_discovery_blueprint.py`) | Present As-Is discovery summary, **§6.1 Business Capability Groupings (`GRP-01..N`)**, and open workflow questions; ask which Capability Group(s) to take forward (`["GRP-01", ...]` vs. `["ALL"]`), regulations, PII/security, accessibility/design refs, ALM platform; write `specs/target_stack.json`; **END TURN** and wait for human approval | Apply `selectedCapabilityGroups: ["ALL"]`, enterprise defaults, most-restrictive workflow reading |
| `gate_2_spec` (**Gate 2**) | After Stage 2 (`validate_spec_scorecard.py` ≥ 90) | `spec-judge` scores until `PASS` (≥ 90, zero blocking gaps); then present `specs/application_spec.md`, `traceability_matrix.md`, and `application_eval_scorecard.md` to the user, **END TURN**, and wait for human approval before starting Stage 3 | Judge loop still enforced; auto-advances only when `--autonomous` was explicitly requested |
| `gate_3_backlog` (**Gate 3**) | After Stage 3 (`alm_jira_ado_bridge.py --action sync-stories`) | Stage stories & future sprint containers on Jira/ADO (`--action audit`, `sync-stories`), present `backlog/user_stories.md`, `backlog/sprint_plan.md`, and board link, **END TURN**, and wait for human approval; in next turn run `gate_tracker.py --action approve --gate gate_3_backlog` and `sync-sprints --approved` | `--action set-approval --set-approval PRE_APPROVED_BY_USER`, `sync-sprints --approved` |
| `gate_4_design_and_tests` (**Gate 4A/4B**) | Stage 4A (`extract_contracts.py`) + Stage 4B (`validate_test_cases.py`) | First ask human for **Future-State Tech Stack** if `target_stack.json#decidedBy != "user"`; once all 7 perspective architecture docs, `solution_design.md`, and `test_cases.json` pass validation, present them to user, **END TURN**, and wait for human approval before Stage 5 Build | Record `decidedBy: "autonomous-default"` only when `--autonomous` was explicitly requested |
| `gate_5_build` (**Gate 5**) | After Stage 5 (`validate_build.py`) | Present runnable target-stack build summary (`src/`), local run command, and story `In Progress` sync, **END TURN**, and wait for human approval before Stage 6 Closed-Loop Eval | Auto-advances only in `--autonomous` mode |
| `gate_6_eval` (**Gate 6** + Guardrails) | After Stage 6 (`run_closed_loop_eval.py`) | If any self-healing hunk touches a role check, state guard, §3.4 formula, masking, or a11y attribute → pause for guardrail review (`--approve-guardrail-flags`); once `VERDICT: PASS`, present `test/eval_report.md` & audit report, **END TURN**, and wait for human approval before Stage 7 Packaging | Guardrail flags **still pause** even in `--autonomous` mode |
| `gate_7_packaging` (**Gate 7**) | After Stage 7 (`validate_gdc_packaging.py`) | Present rootless OCI containers & GDC KRM multi-cloud overlays (`deploy/`), **END TURN**, and wait for human approval before Stage 8 Fleet Deployment | Auto-advances only in `--autonomous` mode |

**Autonomous mode** is triggered **only** when the user explicitly states they pre-approve all steps/gates ("run end-to-end without stopping", "I pre-approve every step", `--autonomous`). Even then, configuring a connection ("connect to ADO") is never treated as autonomous end-to-end execution.

---

## 4. One-command verification pipeline (verify-only)

```bash
python3 <PLUGIN>/scripts/run_agentic_dlc_pipeline.py --project-root "<PROJECT_ROOT>" [--autonomous]
```

It runs the gate scripts in order (scan → discovery lint → spec lint + scorecard → backlog audit →
contract extraction → test derivation/validation → build validation → closed-loop eval) and stops at the
first stage whose artefact is missing or failing, naming the skill/subagent that must author it. It never
generates content. `--autonomous` only relaxes the human-approval checks (Gate 3 pre-approval) — it does not
bypass Gate 2 or Gate 4.

Run `python3 <PLUGIN>/scripts/lint_domain_neutrality.py` after editing any plugin file: the plugin itself must
contain no business-domain literals outside `examples/`.
