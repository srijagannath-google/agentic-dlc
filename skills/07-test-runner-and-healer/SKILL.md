---
name: 07-test-runner-and-healer
description: "Stage 6 of the Agentic DLC v4. Executes test/test_cases.json against the running application with 07/scripts/run_closed_loop_eval.py (browser runtime chain playwright → chrome-headless → NOT_RUN; http via urllib; static scans), snapshots src/ per iteration into test/.snapshots, writes test/eval_results.json, test/eval_report.md and a diff-based test/remediation_and_guardrail_audit_report.md, drives self-healing through coding-agent/solution-architect, and enforces Gate 4 (human approval) on any guardrail-sensitive change. Use when asked to run tests, evaluate the build, or report what failed and what changed."
---

# Stage 6 — Closed-Loop Evaluation, Self-Healing & Gate 4

**Read before acting:** `docs/ARCHITECTURE.md` §4.7–§4.8, §5, `schemas/eval_results.schema.json`,
`_shared/workflow_chain_of_custody.md` ("Stage 6"), `_shared/zero_leak.md`.
Subagents: `testing-agent` (runs, triages, reports), `coding-agent` (fixes code), `solution-architect` (contract changes).

## Inputs
`test/test_cases.json` (validated), `specs/target_stack.json#commands`, `src/**` (build-validated),
`specs/application_spec.md` §3.3/§3.4/§3.5 (for guardrail classification).

## Outputs (all written by the script from real results — nothing is pre-canned, and prior runs are NEVER overwritten)
| File | Content |
| :-- | :-- |
| `test/eval_results.json` & `test/eval_results.iter-NN.json` | per-test `PASS/FAIL/NOT_RUN/ERROR`, runtime used, failed step, actual; leakage hits; unwired controls; a11y findings; summary + verdict |
| `test/eval_report.md` & `test/eval_report.iter-NN.md` | human-readable rendering of the above, by category, with evidence + cumulative run history table (`iter-1..N`) |
| `test/remediation_and_guardrail_audit_report.md` & `test/remediation_and_guardrail_audit_report.iter-NN.md` | §0 Cumulative Run & Remediation History across all iterations · §1 what failed · §2 what changed (`difflib.unified_diff` between `test/.snapshots/iter-(N-1)` and `iter-N`) · §3 guardrail classification per hunk · §4 Preserved Failure & Remediation Log from prior iterations · `GUARDRAIL_REVIEW_STATUS` |
| `backlog/defects.json`, `backlog/defects.md` (& `test/defects.iter-NN.{json,md}`) | Automated Stage 6 defect log (`BUG-01..N`, `issueType: "Bug"`), root-cause description of what the bug was, full traceability to story/reqs/code/tests, and remediation fix-steps comments |
| `test/history/iter-N/` & `test/history/run_index.json` (`README.md`) | **Immutable, non-overwritten per-run archive** containing `eval_results.json`, `eval_report.md`, `remediation_and_guardrail_audit_report.md`, and `defects.{json,md}` for every iteration `N` |
| `test/.snapshots/iter-N/` | immutable copy of `src/` + that run's evaluation and remediation artifacts (auto-increments if `iter-N` already exists — never deletes or overwrites a prior iteration) |

## Procedure

### 1. Execute
```bash
python3 <PLUGIN>/skills/07-test-runner-and-healer/scripts/run_closed_loop_eval.py --project-root "<PROJECT_ROOT>"
```
What it does — and what it refuses to fake:
- Snapshots `src/` → `test/.snapshots/iter-N/`.
- Starts `commands.start` (if a backend exists), polls `commands.healthcheck`, loads `commands.uiEntry`, and runs `commands.reset` (when configured in `specs/target_stack.json#commands.reset`) before each `browser`/`http` test for hermetic per-test isolation.
- **browser** tests: adapter chain `playwright` (native Playwright `page.locator(selector)` hit-testing,
  `locator.bounding_box()` layout visibility checks, inline `httpRequest` seeding/assertions, automatic `[role="tab"]` / `[role="tabpanel"]` mutual-exclusivity
  verification, real tab-click interactivity probes, and viewport PNG screenshots in
  `test/.snapshots/iter-N/screenshots/`) → `chrome-headless` (headless Chrome with bounding-box, inline `httpRequest`, & tab-exclusivity
  verification + `--screenshot` capture) → `none` ⇒ every browser test is `NOT_RUN`. `NOT_RUN` never counts as PASS.
- **http** & **parity (`TC-PARITY-*`)** tests: `urllib` against the started backend supporting `expectStatus`, `expectJsonPath`, `expectBodyContains`, `expectBodyNotContains`, and `expectJsonPathAbsent`.
- **static** tests: visible-text leakage scan over every role/view (tokens from `forbiddenUiTokens`; generic
  `UPPER_SNAKE` / UUID heuristics are warnings), handler-wiring scan for every interactive element, a11y lint.
- Verdict `PASS` only when zero `FAIL/ERROR/NOT_RUN` among non-optional tests, zero leakage hits, zero
  unwired controls.

If `runtime.browser == none`, report it first and tell the user how to supply a browser
(`pip install playwright && playwright install chromium`, or any Chrome/Chromium on `PATH`). Do not rewrite
browser tests as static ones.

### 2. Triage and heal (one iteration = one targeted set of fixes)
| Failure kind | Fixer | Rule |
| :-- | :-- | :-- |
| UI/backend behaviour, missing `data-testid`, dead control, leaked label | `coding-agent` | smallest change that makes the behaviour correct |
| endpoint/schema/enum mismatch | `solution-architect` → edit design → `extract_contracts.py` → `coding-agent` | contracts stay the source of truth |
| test steps contradict the AC | `testing-agent` edits the test and records why in the audit report | the AC, not the code, is the reference |
| AC or spec itself wrong | stop; raise to the user — upstream artefacts change only with human consent | |

Never: weaken an assertion, mark a test optional to pass, hard-code expected values, widen a guard, or
relax masking. Re-run step 1 after each iteration.

### 3. Gate 4 — guardrail review
The audit report §3 classifies every diff hunk (matching explicit `@dlc-guard` / `@dlc-rule` / `@dlc-mask` / `@dlc-a11y` contract pragmas plus structural AST/regex heuristics while ignoring ISO-8601 fixture timestamps). Hunks touching a **role check, state guard (§3.3), business
formula (§3.4), PII masking, or accessibility attribute/role/label** set
`GUARDRAIL_REVIEW_STATUS: FLAGGED_REQUIRES_HUMAN_APPROVAL`. When flagged:
1. present the hunk table (file, lines, guardrail touched, why the change was needed, before/after);
2. **pause** for explicit approval or rejection of each flagged hunk — autonomous mode does not skip this;
3. rejected hunks are reverted from the snapshot and an alternative fix is attempted.
`GUARDRAIL_REVIEW_STATUS: CLEAR` when no hunk is guardrail-sensitive.

### 4. Finish, Automated Defect (`Bug`) Resolution & ALM Status Closure (`Done`)
Done when `summary.verdict == PASS`, `leakage.hits == []`, `interactivity.unwired == []`, `notRun == 0` and no
flag is pending. On every evaluation iteration, `run_closed_loop_eval.py` automatically runs
`alm_jira_ado_bridge.py --action sync-status-from-eval`, which:
1. **Creates a Jira `Bug` (and ADO `Bug` + `backlog/defects.{json,md}`)** for any failing non-optional test case (`BUG-01..N`), recording a detailed description of **what the bug was** (failing test ID, step, expected vs. actual behavior, diagnostic message) and linking it to the parent User Story (`US-*`), requirements (`REQ-*`), and source code (`src/`).
2. **When a defect is fixed in a subsequent iteration (`FAIL -> PASS`)**, automatically diffs `test/.snapshots/iter-(N-1)` vs `iter-N`, **posts a comment on the Jira `Bug` (`POST /rest/api/3/issue/{key}/comment`) and ADO `Bug` (`/fields/System.History`) detailing the exact steps and code changes taken to fix the defect**, and transitions the `Bug` to `Done`.
3. **Transitions all verified User Stories to `Done`** in `backlog/user_stories.{json,md}`, `backlog/sprint_plan.json`, and on the live Jira / Azure DevOps board (including multi-hop `To Do → In Progress → Done` workflows), while refreshing each story's **End-to-End Traceability Matrix** (linking Legacy/Input Sources ↔ Requirements ↔ Design Contracts ↔ Target Source Code ↔ Test Cases ↔ Defects).
Report iterations, final counts per category, story status counts (`storyStatusCounts`), defect counts (`totalDefects`, `resolvedDefects`), report paths, and any approved guardrail
changes with their rationale.

### 5. Mandatory STOP at Gate 6 (`gate_6_eval`) — Wait for Human Evaluation & Audit Approval
When `run_closed_loop_eval.py` exits `0` (`VERDICT: PASS`), it stamps `gate_6_eval = AWAITING_HUMAN_REVIEW` in `specs/gate_approvals.json`, blocking Stage 7 (`check_spec_code_drift.py`).
1. Present `test/eval_report.md`, `test/remediation_and_guardrail_audit_report.md`, and Jira/ADO story closure summary to the user.
2. **END YOUR TURN IMMEDIATELY (call zero further tools). NEVER start Stage 7 (`08-drift-and-evolution`) in the same turn!**
3. Only **in a subsequent turn AFTER the human approves Gate 6**, run:
   ```bash
   python3 <PLUGIN>/scripts/gate_tracker.py --project-root "<PROJECT_ROOT>" --action approve --gate gate_6_eval --user-response "<verbatim user approval quote>"
   ```
   and then proceed to Stage 7 (`08-drift-and-evolution`) to verify zero spec-to-code drift before containerization and GDC packaging.

**Scenario differences:** none at execution time; legacy projects additionally fail `TC-UI-LEAK-*` on any legacy
object name in visible text (tokens derived at Stage 4B).

## Do not
- Accept a static PASS from any tool, count `NOT_RUN` as pass, or approve your own Gate 4 flags.
- Edit `test/test_cases.json` to match the code; edit the code to match the tests (or raise the AC upstream).
- Generate the audit report by hand — it is produced from `eval_results.json` and real diffs.
