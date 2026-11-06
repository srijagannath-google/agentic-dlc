# Agentic DLC Router & Gates (`agentic-dlc` v4.4)

You operate inside the **Agentic Development Lifecycle (DLC) harness v4.4** — "Think Big, Start Small, Move Fast":
the **Elephant** (deep-context discovery/spec author), the **Judge** (adversarial spec/architecture critic and
closed-loop test runner), and the **Goldfish** (clean-context coder). Both **legacy modernisation**
(`SCENARIO_LEGACY_APP`) and **greenfield requirements** (`SCENARIO_REQUIREMENTS_DOC`) are equal first-class paths.

> **Governing Rule:** The LLM (skills + subagents) **authors** every project artefact from user inputs; scripts only
> **scan, derive, lint, execute, and gate**. Never expose plugin internals (`*.py` scripts, `00..10/scripts/*`,
> `_shared/*.md`, `skills/*`, `schemas/*.json`, subagent slugs, `<details>`/`diagram-dsl`, or `SCENARIO_*` enums)
> inside customer deliverables (`specs/`, `backlog/`, `design/`, `test/`, `src/`, `deploy/`).

`<PLUGIN>` = installed plugin directory (`~/.gemini/config/plugins/agentic-dlc`). Read `<PLUGIN>/docs/ARCHITECTURE.md`
and the `_shared/*.md` guides named by the active skill before acting (**progressive disclosure** — load deep stage
references only when executing that stage).

---

## 0. `<PROJECT_ROOT>` (`_shared/project_root.md`)

1. Any folder named `agentic-dlc*` is **never** `<PROJECT_ROOT>`.
2. Resolve in order: `~/.gemini/config/project_root.txt` → `cwd` (if not a plugin/home/tmp dir) → parent of nested plugin → else **ask the user**.
3. Pass `--project-root "<PROJECT_ROOT>"` to every script. Write only inside `<PROJECT_ROOT>/{resources,specs,backlog,design,test,src,deploy}/`.

```text
<PROJECT_ROOT>/
├── resources/{inputs,design_references,policies_and_statutes,shared_services}/   # user-provided only (read-only)
├── specs/     project_setup.json · gate_approvals.json · gate_briefs/*.md · input_inventory.json · dependency_dag.json
│              discovery_architecture_and_inventory.md · target_stack.json · application_spec.md · traceability_matrix.md
│              application_eval_scorecard.{md,json} · drift_report.{md,json} · adr/ADR-*.md
├── backlog/   user_stories.{md,json} · sprint_plan.{md,json} · defects.{md,json} · jira_import.csv
├── design/    architecture_design.md · {business,high_level_solution,logical,application,data,security,infrastructure}_architecture.md
│              diagrams/ · solution_design.md · architecture_eval_scorecard.{md,json} · data_migration_and_cutover.md (legacy)
├── test/      test_plan.md · test_cases.json · legacy_parity_goldens.jsonl (opt) · eval_report.md · eval_results.json
│              remediation_and_guardrail_audit_report.md · history/iter-N/ · .snapshots/iter-N/ · .build_logs/
├── src/       contracts/openapi.yaml · db/schema.sql · ui/ · backend/ · run.sh · README.md
└── deploy/    containers/ · coexistence/ (legacy strangler ACL only) · gdc/{base,overlays/<env>,policy-controller,service-mesh,config-sync}/
               observability/ · deployment_and_runbook.md · deployment_eval_report.{md,json}
```

---

## 1. Lifecycle, Ceremony Tracks & Machine-Enforced Human Gates (`_shared/gate_matrix.md`)

> **HARD-STOP HUMAN GATE RULE (INTERACTIVE MODE):**
> 1. **At most ONE stage per user turn** unless a gate is auto-skipped by `--track quick` (`_shared/gate_matrix.md`) or `--autonomous`.
> 2. **Stage 0 (`00-setup-and-connection`) runs first** when connecting ADO/Jira or initializing a project: list ADO Projects (`list-ado-projects`), ask which ADO Project & repo to use, choose ceremony track (`quick | standard | regulated`), save `specs/project_setup.json`, and **STOP at Gate 0**.
> 3. **Present the Executive Gate Decision Brief & End Turn:** Each gate script writes `specs/gate_briefs/<gate_id>.md` and marks `AWAITING_HUMAN_REVIEW` in `specs/gate_approvals.json` (except gates auto-skipped by `quick` track). Present the brief + open questions and **END YOUR TURN IMMEDIATELY**.
> 4. **Approve Only in the Next Turn:** After the human approves, run `python3 <PLUGIN>/scripts/gate_tracker.py --project-root "<PROJECT_ROOT>" --action approve --gate <gate_id> --user-response "<verbatim quote>"` before starting the next stage.

| Stage | Skill | Subagent(s) | Key Deliverables | Verification Script & Gate |
| :-- | :-- | :-- | :-- | :-- |
| **0 Setup** | `00-setup-and-connection` | coordinator | `specs/project_setup.json` (`ceremonyTrack`, `domainPacks`, `activeWave`) | `00/scripts/setup_project_connection.py` → **`gate_0_setup`** |
| **1 Discovery** | `01-discovery-and-grouping` | `discovery-architect` | `specs/discovery_architecture_and_inventory.md` (**As-Is only**), `specs/target_stack.json`, opt `test/legacy_parity_goldens.jsonl` | `01/scripts/scan_input_sources.py` (`dependency_dag.json`), `validate_discovery_blueprint.py` → **`gate_1_discovery`** |
| **2 Spec** | `02-spec-architect-and-judge` | `discovery-architect`, `spec-judge` | `specs/application_spec.md`, `traceability_matrix.md`, `application_eval_scorecard.{md,json}` | `02/scripts/lint_spec_structure.py`, `validate_spec_scorecard.py` (`≥ 90`) → **`gate_2_spec`** |
| **3 Backlog** | `03-story-and-sprint-planner` | `sprint-planner-agent` | `backlog/user_stories.{md,json}`, `backlog/sprint_plan.{md,json}` | `03/scripts/alm_jira_ado_bridge.py` (`audit`, `sync-stories`, `sync-sprints`) → **`gate_3_backlog`** |
| **4A Design** | `04-solution-architect` | `solution-architect`, `architecture-critic` | 7 `design/*_architecture.md` + `architecture_design.md` + `solution_design.md` + `architecture_eval_scorecard.{md,json}` (+ `data_migration_and_cutover.md` if legacy) | `04/scripts/extract_contracts.py` (`openapi.yaml`, `schema.sql`, 7 SVGs/PNGs), `validate_architecture_scorecard.py` → **`gate_4_design_and_tests`** |
| **4B Tests** | `05-test-plan-designer` | `testing-agent` | `test/test_plan.md`, `test/test_cases.json` (`TC-POS/NEG/EDGE/STATE/UI-LEAK/INTERACT/API/A11Y/PARITY-*`) | `05/scripts/derive_test_cases.py`, `validate_test_cases.py` → **`gate_4_design_and_tests`** |
| **5 Build** | `06-coding-agent`, `google-cloud-ui-design` | `coding-agent` | Runnable dual-mode `src/{ui,backend,run.sh,README.md}` with `@dlc-guard`/`@dlc-rule` pragmas | `06/scripts/validate_build.py` (stories `To Do` → `In Progress`) → **`gate_5_build`** |
| **6 Eval** | `07-test-runner-and-healer` | `testing-agent`, `coding-agent`, `solution-architect` | Self-healing fixes; `test/eval_report.md`, `remediation_and_guardrail_audit_report.md`, `backlog/defects.*` | `07/scripts/run_closed_loop_eval.py` (stories → `Done`; **Gate 4** guardrail pause) → **`gate_6_eval`** |
| **7 GDC Pkg** | `08-container-and-gdc-packager` | `platform-ops-agent` | `deploy/containers/*`, `deploy/coexistence/*` (opt), `deploy/gdc/{base,overlays,policy-controller,service-mesh}/*` | `08/scripts/validate_gdc_packaging.py` → **`gate_7_packaging`** |
| **8 Fleet Obs** | `09-gdc-fleet-deployer-and-observability` | `platform-ops-agent` | `deploy/gdc/config-sync/*`, `deploy/observability/*`, `deploy/deployment_and_runbook.md` | `09/scripts/run_gdc_fleet_deploy_and_verify.py` (`--live` for `kubectl`) → **`gate_8_deployment`** |
| **9 Drift/ADR** | `10-drift-and-evolution` | `discovery-architect`, `solution-architect` | `specs/drift_report.{md,json}`, `specs/adr/ADR-NNNN-*.md`, brownfield spec/contract refresh | `10/scripts/check_spec_code_drift.py` (`ALIGNED` vs `DRIFT_DETECTED`) |

---

## 2. Ten Cross-Stage Invariants

1. **Scenario & As-Is / To-Be Separation (`docs/ARCHITECTURE.md` §1.3):** Stage 1 documents **only Current State ("As-Is")** (and uses Map-Reduce per-module discovery when `largeRepoMapReduceRecommended == true`). Stage 4A owns **all Future State ("To-Be")** (`design/*.md` is 100% target-state — zero local mock flags).
2. **Workflow Chain of Custody (`_shared/workflow_chain_of_custody.md`):** Lifecycle states/transitions are extracted in Stage 1, frozen in `specs/application_spec.md §3.3` (`stateDiagram-v2` + table), and drive stories, tests, UI, and backend guards.
3. **Ask, Don't Assume & Strict Acronym Provenance:** Unresolved workflows/rules/stack go to the next gate (or `ASSUMPTION-NN` in `--autonomous` mode). Never guess expansions for `unverifiedAcronyms` in `specs/input_inventory.json`; tag `[UNVERIFIED_ACRONYM]` and ask at Gate 1.
4. **Pure Target `src/` & Disposable Strangler Boundary ACL:** Never carry legacy table/form names or fixed-width adapters into `src/`. When phased strangler coexistence (`--wave GRP-ID`) is chosen in `target_stack.json#coexistenceStrategy`, isolate disposable CDC/routing adapters strictly under `deploy/coexistence/` with a retirement wave.
5. **Zero UI Leakage, Google Cloud UI Design & `A2UI v0.9`:** Apply `_shared/zero_leak.md`, `_shared/ux_guardrails.md`, and `_shared/google_cloud_ui_design.md` (`Operate | Read | Persuade | Express`, `:root`/`.dark` `--g-*` M3 tokens, ShadCN/Radix, unified surfaces, `tabular-nums`, 4-state coverage, or `references/gemini-enterprise-a2ui.md` when `frontend.kind == "gemini-enterprise-a2ui"`).
6. **Contract-First Test IDs, Differential Parity & Guardrail Pragmas:** Declare `data-testid` selectors in `test/test_cases.json` first, derive `TC-PARITY-*` from `test/legacy_parity_goldens.jsonl` when legacy I/O fixtures exist, use `commands.reset` for hermetic test isolation, and annotate `src/` guards/formulas with `@dlc-guard:<From>-><To>` and `@dlc-rule:BR-NN`.
7. **Human-Confirmed Dual-Mode Target Stack:** Ask for the Future-State stack at Stage 4A if `"tbd"`. Build the real target stack in `src/{ui,backend}` supporting `APP_ENV=local` (`bash src/run.sh`) and `APP_ENV=production` (containers/GDC); never substitute a throwaway Python `http.server` app.
8. **Goldfish Context Isolation:** `coding-agent` reads **only** approved upstream artefacts (`06-coding-agent/SKILL.md`) — never `resources/inputs/`.
9. **End-to-End ALM Story Progression:** Stories progress `To Do` (Stage 3) → `In Progress` (Stage 5) → `Done` (Stage 6 when ≥ 1 directly linked test passes and 0 fail), with automated `Bug` creation/closure.
10. **Environment-Only Credentials & Optional MCP Domain Packs (`_shared/mcp_domain_packs.md`):** Read secrets only from env / `.env` / `~/.gemini/config/agentic-dlc.env` (`chmod 600`); optional MCP packs (`gcp-database-migration`, `spanner`, `cloud-finops`, `apigee-integration`) are additive and never mandatory.

---

## 3. One-Command Pipeline & Plugin Verification

```bash
python3 <PLUGIN>/scripts/run_agentic_dlc_pipeline.py --project-root "<PROJECT_ROOT>" [--autonomous] [--from-stage 1] [--to-stage 10] [--refresh-from-stage N] [--wave GRP-01] [--continue-on-failure]
```

Runs steps `01..10` (`01` discovery → `02` spec judge → `03` backlog audit → `04` contracts + optional `04-arch-judge` → `05` tests → `06` build → `07` closed-loop eval → `08` GDC packaging → `09` GDC fleet → `10` spec-code drift). Use `--refresh-from-stage N` after an intentional upstream edit (`10-drift-and-evolution`) to re-hash/re-derive downstream contracts while preserving authored test steps. After editing any plugin file, run `python3 <PLUGIN>/scripts/lint_domain_neutrality.py` and `python3 <PLUGIN>/evals/run_skill_ablation.py --selftest`.
