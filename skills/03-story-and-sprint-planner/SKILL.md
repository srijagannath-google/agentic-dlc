---
name: 03-story-and-sprint-planner
description: "Stage 3 of the Agentic DLC v4. sprint-planner-agent authors ALL functional (US-FUNC-*) and technical (US-TECH-*) user stories in backlog/user_stories.{md,json} with variable 4–10+ Given/When/Then ACs (positive, negative, role-visibility, workflow-prerequisite-gate, interactive-completeness, edge) derived from spec §3.3/§3.4/§3.5, tiers them into Sprint 1..N + Product Backlog in backlog/sprint_plan.md, audits coverage and stages the Jira/Azure DevOps board with 03/scripts/alm_jira_ado_bridge.py before Gate 3, then syncs sprints after human approval. Use when asked for user stories, a sprint plan, or a Jira/ADO push."
---

# Stage 3 — Unified User Stories, Sprint Alignment & Gate 3

**Read before acting:** `docs/ARCHITECTURE.md` §4.5, `schemas/user_stories.schema.json`, `_shared/sdd_governance_and_alm.md`, `_shared/conditional_grilling.md`,
`_shared/workflow_chain_of_custody.md` ("Stage 3"), `_shared/project_root.md`. Subagent: `sprint-planner-agent`. Companion skill: `clarification-griller`.

## Inputs
`specs/application_spec.md` (Gate 2 PASS), `specs/traceability_matrix.md`, `specs/clarification_decisions.json`,
`specs/discovery_architecture_and_inventory.md`, `specs/input_inventory.json`, `specs/target_stack.json#almPlatform`.

## Outputs
| File | Author | Checked by |
| :-- | :-- | :-- |
| `specs/clarification_decisions.json` (`stagesSettled` incl. `"pre-stories"`) | `clarification-griller` (`clarification_interview.py --stage pre-stories`) | `alm_jira_ado_bridge.py --action audit` (`SD-GRILL-03`) |
| `backlog/user_stories.md`, `backlog/user_stories.json` | `sprint-planner-agent` | `alm_jira_ado_bridge.py --action audit` (100 % REQ coverage, ≤ 8 SP, tiers), schema |
| `backlog/sprint_plan.md` (+ `sprint_plan.json` summary) | `sprint-planner-agent` (+ script summary) | approval marker |
| `backlog/jira_import.csv`, `backlog/jira_state.json`, `backlog/azure_devops_state.json` | script | `liveSyncErrors` empty |

## Procedure

### 0. Mandatory User-Story & Acceptance-Criteria `grill-me` Check (`--stage pre-stories` / `SD-GRILL-03`)
Before finalizing `backlog/user_stories.{md,json}` (and whenever decomposing requirements into `GIVEN/WHEN/THEN` acceptance criteria), run:
```bash
python3 <PLUGIN>/skills/clarification-griller/scripts/clarification_interview.py \
  --project-root "<PROJECT_ROOT>" --stage pre-stories --action detect --auto-bypass-if-clear --seed-if-needed
```
- **Engage the Business Analyst / Human When Needed:** If `needsClarification == true` (unconfirmed `ASSUMPTION-NN`, `BR-NN` rules missing boundary/rejection `Examples` for `EDGE / BOUNDARY` & `NEGATIVE` ACs, unguarded `§3.3` workflow transitions, multi-group Sprint 1 MVP slicing order) — OR if `sprint-planner-agent` encounters **any unclear, contradictory, conflicting, or ambiguous requirement/rule** while authoring stories (in which case it MUST run `clarification_interview.py --stage pre-stories --action flag-conflict ...`) — **STOP**, present a visible **`## 🔥 Grill-Me Clarification Round (User Stories & Acceptance Criteria)`** (`❓ Q1..Qn` + `➡️ Recommended` + native `ask_question` widget) to the Business Analyst / human, and record their answers via `--action record-round` (or `--action accept-recommendations`)! `alm_jira_ado_bridge.py --action audit` enforces `SD-GRILL-03` and refuses to pass Gate 3 while `"pre-stories"` is unsettled.

### 1. Author the backlog (before any script)
Templates: `resources/user_stories_template.md`, `resources/sprint_plan_template.md`. Rules:
- **Coverage set** = every `REQ-*` in the spec (incl. `REQ-ENH-*` for legacy projects), every §3.3 transition
  row, every `BR-NN`, every §3.5 role, and — legacy only — every legacy artefact in the capability inventory
  (`legacyArtifactsReplaced`). Keep a coverage table in `user_stories.md` §0.
- **Granularity & Dynamic Story / Sprint Count (NEVER Hardcode to 3 Sprints or a Fixed Story Count):**
  - Each story is sized at 3–8 SP (`US-FUNC-01..M` for functional capabilities, `US-TECH-01..K` for security/a11y/UX/architecture enablers). **Never cap or default the backlog to a fixed number of stories or 3 sprints.**
  - Story count (`M + K`) scales strictly from the discovered capability inventory, `REQ-*` count, `§3.3` state transitions, and `§3.4` business rules.
  - Sprint count (`Sprint 1 .. Sprint N`) scales dynamically from total story points, capability-group topological dependencies (`isSharedFoundation`, `dependsOnGroups`), and velocity capacity (`specs/target_stack.json#sprintCapacityPoints` or `--sprint-capacity-points`, default `21` SP per sprint). Large capability groups automatically span multiple consecutive sprints (`Sprint k .. Sprint m`).
- **Acceptance criteria** in the object form (`id`, `tag`, `given`, `when`, `then`); count varies with the
  story (4 → 10+). Tags and their derivation source:

| Tag | Derived from | Must state |
| :-- | :-- | :-- |
| `POSITIVE` | REQ + each role/variant served | observable result per role |
| `NEGATIVE` | validation rules, RBAC matrix, `BR-NN` violations | the user-readable reason shown |
| `NEGATIVE — ROLE VISIBILITY` | §3.5 `Kind` + §3.3 actor roles | internal-transition controls absent for external roles |
| `NEGATIVE — WORKFLOW PREREQUISITE GATE` | (state, trigger) pairs **not** in §3.3 | attempt is blocked with a reason; state unchanged |
| `POSITIVE — INTERACTIVE COMPLETENESS` | controls the story introduces | each control's effect on DOM/data |
| `NEGATIVE — SECURITY / ABUSE CASE` | Pillar 2 `REQ-SEC-*`, Stage 1 `securityPostureSignals`, mutating/ID routes | BOLA/IDOR cross-tenant rejection, unauthorized role `401`/`403`, injection/payload rejection (`TC-SEC-*`) |
| `EDGE / BOUNDARY` | §3.4 thresholds (value, −1 unit, +1 unit), empty/max payloads, duplicates, concurrency | exact expected values |

- Each story carries `capabilityGroup` (`GRP-01..N` from `discovery_architecture_and_inventory.md` §6.1, or `SHARED` for cross-cutting `US-TECH-*` enablers), `capabilityGroupName`, `requirementRefs`, `businessRuleRefs`, `roles`, `workflowTransitions` (`FROM->TO` copied
  from §3.3), `sprint`, `priority`, optional PMO `storyPoints` (`1..8`), plus **SDD Execution Slice Contracts** (`_shared/sdd_governance_and_alm.md`):
  - **`dependsOnStories` (Contract-First Blocker Chaining):** Isolate schema/OpenAPI/testid contracts in foundational `US-TECH-*` slices first, then chain backend service slices and UI slices via `dependsOnStories` (synced as Jira `Blocks` / ADO `Predecessor` links; zero cycles allowed).
  - **`specPointer` (Thin-Pointer Single Source of Truth):** Point every ALM ticket back to `specs/application_spec.md` (`specSha256` + `REQ-*`/`BR-*` anchors) instead of inventing diverging prose rules inside tickets.
  - **`scopeBounds` (3D Small-Slice Bounds & Unit-Test Co-Location):** Target `<= 3` production files, `<= 400` implementation LOC, and non-empty `unitTestTargets` co-located in the **same slice** (never create a separate "write unit tests later" story, and avoid compound `"and"` titles bundling multiple views).
  - **`verificationPlan` (4-Part Runnable Check):** Specify `surface` (`ui | cli | api | sql | non-runnable-contract`), `executionCommand`, `targetUrlOrSurface`, and `stepsAndExpectedOutcome` — or `nonRunnableRationale: "N/A — <specific contract rationale>"` (bare `"N/A"` is rejected).
  - **Dual-Plane Human Review (`almPlatform != "none"` vs. `almPlatform == "none"`):** When Jira/ADO is configured (`alm-and-git`), stage stories + sprints on the live board before Gate 3; when `almPlatform == "none"` (`git-pr-docs-as-code`), present `backlog/user_stories.md` + `specs/gate_briefs/gate_3_backlog.md` for Git PR `CODEOWNERS` review and use `--action compact-completed` after Stage 6 to compact `Done` slices to single-line `- **Compacted Context:**` summaries.
- **Capability-Group Tiering, Shared Prerequisites & Selection (`specs/target_stack.json#selectedCapabilityGroups`):**
  - **Shared Foundation & Prerequisite Resolution (`resolve_group_closure`):** Any capability group marked `isSharedFoundation: true` in `specs/target_stack.json#capabilityGroups` (or `Prerequisite for all` in discovery §6.1), any prerequisite group listed in `dependsOnGroups` of a selected group, and all cross-cutting `SHARED` technical foundation stories (`US-TECH-*`) are **automatically included** and scheduled into **`Sprint 1`** ahead of dependent groups (`Sprint 2..N`).
  - **Specific Group(s) Selected (`["GRP-01"]`, `["GRP-02"]`, etc.):** Stories belonging to the human-selected Capability Group(s) plus their prerequisite/shared foundation groups (`dependsOnGroups`, `isSharedFoundation`, `SHARED`) are scheduled into `Sprint 1..N` in topological prerequisite order; stories belonging to unselected Capability Groups are placed into `Product Backlog` (grouped by their `capabilityGroup`).
  - **ALL Groupings Selected (`["ALL"]`):** When the user selects **ALL** groupings (or by default in autonomous mode), stories across **all** Capability Groups (`GRP-01..N`) are scheduled into `Sprint 1..N` (with prerequisite/shared foundation groups in `Sprint 1`).
  - Sprint names ≤ 30 characters. Mark `SPRINT_ALIGNMENT_APPROVAL: PENDING_HUMAN_APPROVAL`
    (or `PRE_APPROVED_BY_USER` in autonomous mode).
  - You can also switch between specific group(s) or `ALL` groupings via CLI at any time:
    ```bash
    python3 $B --project-root "<PROJECT_ROOT>" --action select-groups --select-groups "GRP-01"   # or --select-groups "ALL"
    ```

**Scenario differences:** legacy projects must show every legacy artefact replaced or consciously retired
(retirements listed in `sprint_plan.md`); requirements-document projects trace every documented requirement
and nothing more — no "enhancement" stories.

### 2. Audit, then stage the board (Gate 3 preparation)
```bash
B=<PLUGIN>/skills/03-story-and-sprint-planner/scripts/alm_jira_ado_bridge.py
python3 $B --project-root "<PROJECT_ROOT>" --action audit              # coverage, sizing, tiers — exit 0 required
python3 <PLUGIN>/scripts/dlc_decisions_client.py --project-root "<PROJECT_ROOT>" --action route-stories  # assigns Flash vs Pro tier + security criticality
python3 $B --project-root "<PROJECT_ROOT>" --action test-connection    # when almPlatform != none
python3 $B --project-root "<PROJECT_ROOT>" --action sync-stories       # --platform defaults from target_stack.json#almPlatform
```
Actions (`--platform jira|ado|both|none`, default from `specs/target_stack.json#almPlatform`; all local artefacts are written to `backlog/`):

| `--action` | Purpose | Exit codes |
| :-- | :-- | :-- |
| `audit` | Gate 3 coverage / sizing / tiering audit; refreshes `sprint_plan.json` + story traceability; stamps `gate_3_backlog = AWAITING_HUMAN_REVIEW` when it passes and the plan is still pending | `0` pass · `1` audit failed |
| `select-groups --select-groups GRP-01,GRP-02\|ALL [--sprint-capacity-points N]` | Record `selectedCapabilityGroups`, re-pack stories into `Sprint 1..N` / `Product Backlog`, update `user_stories.{json,md}` (incl. `**Sprint:**` lines) | `0` ok · `1` backlog missing/invalid |
| `test-connection` | Verify Jira / ADO credentials, project and board | `0` connected with no errors · `1` not connected, offline, or errors |
| `sync-stories` | Idempotent upsert of stories (+ sprints, defects) to stage the board before Gate 3; offline/no-creds → local export only; stamps `gate_3_backlog = AWAITING_HUMAN_REVIEW` | `0` ok · `1` audit failed · `2` live sync had errors |
| `set-approval --set-approval <STATUS>` | Write `SPRINT_ALIGNMENT_APPROVAL` (`PENDING_HUMAN_APPROVAL` \| `APPROVED_BY_USER` \| `PRE_APPROVED_BY_USER`) and mirror it into `specs/gate_approvals.json#gate_3_backlog` (refuses `APPROVED_BY_USER` < 8 s after staging) | `0` ok · `1` audit failed (non-pending statuses) / self-approval refused |
| `sync-sprints --approved` | After Gate 3 (requires `gate_3_backlog` approved in the ledger): same as `sync-stories` and marks the plan approved (`--approved` is honoured only here) | `0` ok · `1` audit failed / `--approved` missing / gate not approved · `2` live sync had errors |
| `transition-stories --target-status <S> [--scope all\|active-sprints] [--story-ids …] [--only-from-todo]` | Explicit story status transition locally and on the board | `0` ok · `1` bad arguments · `2` live transition errors |
| `sync-status-from-eval` | Stage 6: derive story statuses from `test/eval_results.json` (Done only on directly linked passing tests), create/resolve `BUG-*` defects, post fix comments | `0` ok · `1` eval results missing · `2` live sync errors |
| `sync-deployment-status` | Stage 8: record `traceability.gdcDeployment` from `deploy/deployment_eval_report.json` and post/refresh one deployment comment per story | `0` ok · `1` deployment report missing · `2` live comment errors |
| `export-csv` | Write `backlog/jira_import.csv` (stories + defects) | `0` ok · `1` audit failed |

`audit`, `select-groups`, `sync-stories`, `sync-sprints`, `set-approval` and `export-csv` all require `gate_2_spec` to be approved in
`specs/gate_approvals.json` (autonomous mode excepted). Exit `1` means a gate/audit failure (fix the backlog — `--allow-partial-coverage`
only downgrades REQ gaps to warnings and must be justified to the user); exit `2` means the live sync had errors (read the state file,
report verbatim, do not proceed).
`sync-stories` upserts stories idempotently (match on the story id in the summary), creates future sprint
containers for `Sprint 1..N`, places Product Backlog items in the backlog drawer and removes empty orphan
sprints — so the user can inspect the alignment on the board **before** approving. Confirm in
`backlog/jira_state.json` / `backlog/azure_devops_state.json` that `liveSyncErrors` is empty and every story sits
in its intended container. Credentials come from the environment (`JIRA_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`,
optional `JIRA_PROJECT_KEY`/`JIRA_BOARD_ID`; `ADO_ORG_URL`, `ADO_PROJECT`, `ADO_PAT`). With `almPlatform = none`,
`export-csv` produces `backlog/jira_import.csv` only.

### 3. Mandatory STOP at Gate 3 (`gate_3_backlog`) — Wait for Human Backlog & Sprint Approval
`alm_jira_ado_bridge.py --action audit` / `sync-stories` automatically stamps `gate_3_backlog = AWAITING_HUMAN_REVIEW` in `specs/gate_approvals.json`, blocking Stage 4A/4B (`extract_contracts.py`, `derive_test_cases.py`, `validate_test_cases.py`).
1. Present `backlog/user_stories.md`, `backlog/sprint_plan.md`, capability-group allocation, and the live Jira/ADO board link to the user.
2. **END YOUR TURN IMMEDIATELY (call zero further tools). NEVER call `set-approval --set-approval APPROVED_BY_USER` or start Stage 4 in the same turn!**
3. Only **in a subsequent turn AFTER the human replies explicitly approving Gate 3**, run:
   ```bash
   python3 <PLUGIN>/scripts/gate_tracker.py --project-root "<PROJECT_ROOT>" --action approve --gate gate_3_backlog --user-response "<verbatim user approval quote>"
   python3 $B --project-root "<PROJECT_ROOT>" --action set-approval --set-approval APPROVED_BY_USER
   python3 $B --project-root "<PROJECT_ROOT>" --action sync-sprints --approved
   ```
**Autonomous mode only (`--autonomous`):** `--action set-approval --set-approval PRE_APPROVED_BY_USER`, then `sync-sprints --approved`, continue to Stage 4.

### 4. End-to-End Traceability, Automated Stage 6 `Bug` Creation & Lifecycle Status Transitions
Every Jira Story and Azure DevOps Work Item automatically includes an **End-to-End Traceability Matrix** (`story.traceability`) linking:
1. **Legacy / Input Source Artifacts** (`legacyArtifactsReplaced` & `specs/input_inventory.json`)
2. **Requirements & Business Rules** (`REQ-*`, `BR-*`, and `§3.3` `workflowTransitions`)
3. **Architecture & Design Contracts** (OpenAPI operations `METHOD /api/...` and 3NF database tables from `design/.contracts_index.json` / `src/db/schema.sql`)
4. **Implemented Target Source Code** (`src/ui/*`, `src/backend/*`, `src/db/*` and UI `data-testid` hooks)
5. **Shift-Left Test Cases & Stage 6 Status** (`TC-*` IDs and their latest `PASS` / `FAIL` / `NOT_RUN` result)
6. **Linked Stage 6 Defects (`BUG-*`)**

Stories start in `status: "To Do"` during Stage 3. As implementation and verification progress, `alm_jira_ado_bridge.py` transitions story statuses and manages Stage 6 defects (`Bug` issues) both locally (`backlog/user_stories.{json,md}`, `backlog/defects.{json,md}`, `backlog/sprint_plan.json`, `backlog/jira_import.csv`, `backlog/jira_state.json`, `backlog/azure_devops_state.json`) and on the live Jira / Azure DevOps board:
- **Stage 5 (Build Gate pass):** `validate_build.py` automatically runs `--action transition-stories --target-status "In Progress" --scope active-sprints --only-from-todo`.
- **Stage 6 (Closed-loop evaluation & self-healing):** `run_closed_loop_eval.py` automatically runs `--action sync-status-from-eval`, which:
  1. **Creates a Jira `Bug` (and ADO `Bug` + `backlog/defects.{json,md}`)** for any failing non-optional test case (`BUG-01..N`), with a detailed description of **what the bug was** (failing test ID, step, expected vs. actual behavior, diagnostic message) and full traceability to the parent `US-*` story, `REQ-*`, and source files.
  2. **When a defect is fixed in a subsequent Stage 6 iteration (`FAIL -> PASS`)**, automatically diffs `test/.snapshots/iter-(N-1)` vs `iter-N`, **posts a comment on the Jira `Bug` (`POST /rest/api/3/issue/{key}/comment`) and ADO `Bug` (`/fields/System.History`) detailing the exact steps and code changes taken to fix the defect**, and transitions the `Bug` to `Done`.
  3. **Transitions verified User Stories to `Done`** and refreshes their Jira/ADO descriptions and verification comments with the complete end-to-end traceability matrix.
- You can also invoke status transitions or capacity-aware group selection directly at any time:
  ```bash
  python3 $B --project-root "<PROJECT_ROOT>" --action sync-status-from-eval
  python3 $B --project-root "<PROJECT_ROOT>" --action select-groups --select-groups "ALL" --sprint-capacity-points 21
  python3 $B --project-root "<PROJECT_ROOT>" --action transition-stories --target-status "Done" --scope all
  ```

### 5. Hand over (Only After Human Gate 3 Approval in Subsequent Turn)
Once `gate_3_backlog` is `APPROVED_BY_USER` and `sync-sprints --approved` succeeds, start `04-solution-architect` and `05-test-plan-designer` in parallel.

## Do not
- Start Stage 3 before `gate_2_spec` is `APPROVED_BY_USER`, or self-approve Gate 3 in the same turn stories are staged.
- Run the bridge before the backlog is authored, or rely on any default/template stories.
- Invent screens, steps, fees or roles absent from the spec; cap ACs at a fixed count; omit role/state tags
  on workflow stories.
