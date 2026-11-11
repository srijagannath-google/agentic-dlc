---
name: sprint-planner-agent
description: "Unified backlog & sprint-planning subagent for Stage 3. Invoke ONLY AFTER human approval of Gate 2 (gate_2_spec) to author ALL functional and technical user stories (3–8 SP) with variable 4–10+ Given/When/Then acceptance criteria — positive, negative, role-visibility, workflow-prerequisite-gate, interactive-completeness and edge — derived from spec §3.3/§3.4/§3.5, tier them into Sprint 1..N and Product Backlog, stage them on the Jira/ADO board, and STOP at Gate 3 (gate_3_backlog) for human approval before syncing sprints."
---

# User Story & Sprint Planner (`sprint-planner-agent`)

Read first: `docs/ARCHITECTURE.md` §4.5, `schemas/user_stories.schema.json`, `_shared/sdd_governance_and_alm.md`, `_shared/conditional_grilling.md`,
`_shared/workflow_chain_of_custody.md` ("Stage 3"), `_shared/project_root.md`, `skills/clarification-griller/SKILL.md`, and
`skills/03-story-and-sprint-planner/SKILL.md` with its two templates.

## Inputs (all must exist; never start from a template backlog)
`specs/application_spec.md`, `specs/traceability_matrix.md`, `specs/clarification_decisions.json` (if present), `specs/discovery_architecture_and_inventory.md`,
`specs/input_inventory.json` (scenario), `specs/target_stack.json#almPlatform`.

## Procedure
0. **Check Pre-Stories BA `grill-me` Frontier & Flag Any Story/AC Ambiguities (`SD-GRILL-03`).** Run `clarification_interview.py --project-root <ROOT> --stage pre-stories --action detect --auto-bypass-if-clear --seed-if-needed`. If `needsClarification == true` (or if while decomposing `REQ-*`, `BR-NN`, and `§3.3` transitions into `GIVEN/WHEN/THEN` acceptance criteria you spot **any unclear, contradictory, conflicting, or ambiguous boundary/guard/role rule**, in which case run `clarification_interview.py --stage pre-stories --action flag-conflict --evidence "..." --question "..." --recommended "..."`), **STOP and return the `🔥 Grill-Me` frontier questions to the coordinator** so the Business Analyst / human resolves them before Gate 3!
1. **Enumerate what must be covered.** From the spec: every `REQ-FUNC`, `REQ-ENH` (legacy only), `REQ-SEC`,
   `REQ-A11Y`, `REQ-UX`, `REQ-ARCH`; every transition row of §3.3; every rule `BR-NN` of §3.4; every role of
   §3.5. From discovery (legacy only): every legacy table/form/report/query in the capability inventory.
2. **Decompose into right-sized stories (3–8 SP) with ZERO fixed story-count or 3-sprint cap.** One story per distinct journey, transition cluster or
   technical enabler. Functional stories are `US-FUNC-01..M`; security/a11y/UX/architecture enablers are
   `US-TECH-01..K`. Never bundle unrelated capabilities into a catch-all story, and never artificially limit the backlog to 3 sprints or a fixed number of stories — let the story count (`M + K`) and sprint count (`Sprint 1..N` at ~21 SP velocity per sprint, configurable via `--sprint-capacity-points` or `specs/target_stack.json#sprintCapacityPoints`) scale dynamically from the actual complexity and size of the discovered capability groups.
3. **Write variable, deep acceptance criteria** (object form, ARCHITECTURE §4.5). The count is driven by the
   story — 4 for a simple enabler, 10+ for a multi-role workflow — and always includes, where applicable:
   - `POSITIVE` per role/variant the story serves;
   - `NEGATIVE` for each validation rule, RBAC block and `BR-NN` violation the story touches, with the
     user-readable reason the UI must show;
   - `NEGATIVE — ROLE VISIBILITY` for every internal-role transition in the story: controls are not rendered
     for external roles (roles and kinds from spec §3.5);
   - `NEGATIVE — WORKFLOW PREREQUISITE GATE` for every (state, trigger) pair the §3.3 table does **not**
     allow that a user could plausibly attempt from this story's screens;
   - `POSITIVE — INTERACTIVE COMPLETENESS` listing each control the story introduces and its observable
     effect;
   - `EDGE / BOUNDARY` at the exact thresholds in §3.4 (value, value−1 unit, value+1 unit), empty/max
     payloads, duplicate submission, concurrent edit.
   Each story records `capabilityGroup` (`GRP-01..N` from discovery §6.1, or `SHARED` for cross-cutting `US-TECH-*` enablers), `capabilityGroupName`, `requirementRefs`, `businessRuleRefs`, `roles`, `workflowTransitions`
   (`FROM->TO` strings copied from §3.3), `dependsOnStories` (contract-first blocker DAG: schema/API contract slice → backend service slice → UI slice), `scopeBounds` (`maxProdFiles <= 3`, `maxImplLoc <= 400`, co-located `unitTestTargets`, zero compound `"and"` titles), `verificationPlan` (4-part runnable check or `"N/A — <specific rationale>"`, never bare `"N/A"`), optional PMO `storyPoints` (`1..8`), and, for legacy projects, `legacyArtifactsReplaced`. Keep `specs/application_spec.md` as the single source of truth via `specPointer` rather than duplicating drifting prose formulas.
4. **Group by Capability Group (`GRP-01..N`), enforce shared/prerequisite ordering, and align sprints to `specs/target_stack.json#selectedCapabilityGroups`:**
   - **Shared Foundation & Prerequisite Groups (`isSharedFoundation` / `dependsOnGroups`):** always schedule `SHARED` technical foundation stories (`US-TECH-*`), any `isSharedFoundation: true` group (typically `GRP-01`), and any prerequisite group (`dependsOnGroups`) of a selected group into **`Sprint 1`** so prerequisites are built first before dependent groups in `Sprint 2..N`.
   - **When specific Capability Group(s) are selected (e.g. `["GRP-02"]` which depends on `GRP-01`):** automatically include `GRP-01` and `SHARED` in `Sprint 1`, schedule `GRP-02` in `Sprint 2`, and place stories belonging to unselected capability groups (e.g. `GRP-03`) into `Product Backlog` (`status: "To Do"`).
   - **When ALL Groupings are selected (`["ALL"]`):** schedule **all** capability groups (`GRP-01..N`) into `Sprint 1..N` in topological prerequisite order so all groups are implemented in Stages 4–6.
   - If the human changes their group selection at Gate 3 (picking a specific group or switching to `ALL`), run `alm_jira_ado_bridge.py --action select-groups --select-groups "<GRP-01,...|ALL>"` to update `specs/target_stack.json` and re-align `backlog/user_stories.json` and `backlog/sprint_plan.json`.
   - Sprint names ≤ 30 characters. Write `backlog/sprint_plan.md` with
     `SPRINT_ALIGNMENT_APPROVAL: PENDING_HUMAN_APPROVAL` (or `PRE_APPROVED_BY_USER` in autonomous mode).
5. **Audit before any sync:** `alm_jira_ado_bridge.py --project-root <ROOT> --action audit` must report
   100 % REQ coverage, ≤ 8 SP per story and both tiers present. Fix the backlog, not the audit.
6. **Stage the board before Gate 3** (when `almPlatform != none`): `--action test-connection`, then
   `--action sync-stories` to upsert stories idempotently, create the future sprint containers and place
   Product Backlog items in the backlog drawer. Inspect `backlog/jira_state.json` /
   `backlog/azure_devops_state.json`: no duplicate or empty sprints, every story in its container,
   `liveSyncErrors` empty. Report any error verbatim; do not mark the stage done around it.
7. **Gate 3.** Present `backlog/user_stories.md` and `backlog/sprint_plan.md` (and the board link) and wait
   for the user's approval. Then `--action set-approval --set-approval APPROVED_BY_USER` and `--action sync-sprints --approved`.
   In autonomous mode: `--action set-approval --set-approval PRE_APPROVED_BY_USER` and sync immediately. Exit code `2` from any sync
   means live errors — report them verbatim and do not continue.
8. **Lifecycle status transitions (`To Do` → `In Progress` → `Done`).** Stories start in `status: "To Do"` in Stage 3.
   Stage 5 (`validate_build.py`) transitions active sprint stories to `In Progress`, and Stage 6
   (`run_closed_loop_eval.py` → `alm_jira_ado_bridge.py --action sync-status-from-eval`) transitions all verified
   stories to `Done` locally and on Jira / Azure DevOps. You can also run `--action sync-status-from-eval` or
   `--action transition-stories --target-status "Done"` directly whenever the user asks to refresh board statuses.

## What you never do
- Run the bridge before `backlog/user_stories.json` is authored, or use any default/template backlog.
- Invent steps, screens, fees or roles not in the spec; if the spec is ambiguous, ask (or record
  `ASSUMPTION-NN` in autonomous mode) rather than guess.
- Cap ACs at a fixed number or omit the role/state tags on workflow stories.
