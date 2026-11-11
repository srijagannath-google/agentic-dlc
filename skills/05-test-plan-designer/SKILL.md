---
name: 05-test-plan-designer
description: "Stage 4B of the Agentic DLC v4 (parallel with 04-solution-architect, after Gate 3). 05/scripts/derive_test_cases.py derives test/test_cases.json from stories, the spec state/role tables, the extracted DDL/OpenAPI and the input inventory (Positive, Negative, Edge, UiLeak, State, Interact, A11y, Api); testing-agent completes executable steps and declares data-testid selectors contract-first, authors test/test_plan.md, and validates with 05/scripts/validate_test_cases.py. Use when asked for a test plan or test cases."
---

# Stage 4B — Shift-Left Test Plan & Executable Test Cases

**Read before acting:** `docs/ARCHITECTURE.md` §4.6, `schemas/test_cases.schema.json`,
`_shared/workflow_chain_of_custody.md` ("Stage 4B"), `_shared/zero_leak.md`, `_shared/ux_guardrails.md`
(the "How Stage 6 checks it" column). Subagent: `testing-agent`.

## Inputs
`backlog/user_stories.json` (approved), `specs/application_spec.md` (§3.3, §3.4, §3.5, Pillar 2 PII list),
`src/db/schema.sql` + `src/contracts/openapi.yaml` (from 4A — wait for them if 4A is still running),
`specs/input_inventory.json`, `specs/target_stack.json`.

## Outputs
| File | Author | Checked by |
| :-- | :-- | :-- |
| `test/test_cases.json` | script skeleton + `testing-agent` steps | `05/scripts/validate_test_cases.py` |
| `test/test_plan.md` | `testing-agent` (template `resources/test_plan_template.md`) | reviewed at Stage 6 |

## Procedure

### 1. Derive the skeleton (never hand-write ids or token lists)
```bash
python3 <PLUGIN>/skills/05-test-plan-designer/scripts/derive_test_cases.py --project-root "<PROJECT_ROOT>" [--group-state-tests]
```
| Category | Derived from | What the script emits |
| :-- | :-- | :-- |
| `Positive` / `Negative` / `Edge` | each AC by tag (`TC-POS/NEG/EDGE-*`) + `TC-POS-JOURNEY-01` (Default Landing Persona Entry-to-Submit Journey without `setRole` override) | `storyRef`, `acRef`, `capabilityGroup`, `expected` = AC `then`, `steps: []`, `needsSteps: true` for stories in `selectedCapabilityGroups` (or all stories when `selectedCapabilityGroups == ["ALL"]`); unselected-group stories in `Product Backlog` are emitted with `optional: true, deferredByGroupSelection: true, needsSteps: false` |
| `State` (`TC-STATE-*`) | §3.3 table: every (state, trigger) **not** allowed; every (role, trigger) the role does not own; plus external-role visibility of internal controls | one TC per pair (or one parametrised `matrixCases` test per trigger when `--group-state-tests` is passed), `role` set |
| `Security` (`TC-SEC-*`, `TC-SEC-AUTHZ-*`, `TC-SEC-LEGACY-*`) | `[NEGATIVE — SECURITY / ABUSE CASE]` story ACs, mutating OpenAPI routes (`POST/PUT/PATCH/DELETE`), and Stage 1 `securityPostureSignals` | unauthorized role/token `401/403` probes without stack trace leak + anti-regression tests proving legacy vulnerability classes (`CWE-*`) were eliminated |
| `Parity` (`TC-PARITY-*`) | `test/legacy_parity_goldens.jsonl` (when present in `SCENARIO_LEGACY_APP`) | differential input/output parity tests with `httpRequest` steps (or `optional: true` + `intentionalDivergenceRef: "REQ-ENH-NN"` when a modernization enhancement intentionally alters legacy behaviour) |
| `UiLeak` (`TC-UI-LEAK-01..04`) | `forbiddenUiTokens`: DDL identifiers, state/enum codes, legacy file stems (legacy scenario), PII regexes from Pillar 2 | static scan tests |
| `Interact` (`TC-UI-INTERACT-01` + `TC-UI-INTERACT-TAB-01..N`) | generic + §4.2 View & Component Topology table | every interactive element has a handler; every navigation tab `T_i` clicked on `runtime: "browser"` asserts `expectAttribute(T_i, "aria-selected", "true")`, `expectVisible(P_i)`, and `expectHidden(P_j)` for every sibling panel `P_j != P_i` |
| `Api` (`TC-API-*`) | each OpenAPI operation, when `backend.kind != none` | status-code & payload checks with `httpRequest` (`expectStatus`, `expectJsonPath`, `expectBodyContains`, `expectBodyNotContains`, `expectJsonPathAbsent`) |
| `A11y` (`TC-A11Y-01`) | generic WCAG 2.1 AA static checks (+ named standards) | labels, roles, contrast tokens |

### 2. Complete every `needsSteps` test (`testing-agent`)
Use only the step vocabulary of ARCHITECTURE §4.6. Rules of good steps:
- **Behavioural:** `goto` → `setRole` → `fill`/`click` → `expectText`/`expectHidden`/`expectDisabled`/
  `expectCount`/`httpRequest`. Asserting that text exists on first load is not a test.
- **Default Landing Persona Journey (`TC-POS-JOURNEY-01`):** starting from a fresh `goto("ui")` **without** calling
  `setRole`, verify the default initial state badge is rendered, step through any multi-step wizard (`Next Step` /
  step indicators), verify the entry-state primary transition trigger (e.g., `Submit`) is visible and enabled in the
  viewport, click it, and assert the state transitions to the next state in §3.3.
- **Mutual Tab Exclusivity (`TC-UI-INTERACT-TAB-01..N`):** for each top-level navigation tab `T_i` and controlled
  panel `P_i` from §4.2, execute `click` on `T_i`, assert `expectAttribute(T_i, "aria-selected", "true")`,
  `expectVisible(P_i)`, and `expectHidden(P_j)` for every other tab panel `P_j != P_i`. `validate_test_cases.py`
  rejects any tab-navigation test case that clicks a `[role="tab"]` without asserting `expectHidden` on at least one
  previously active sibling panel.
- **Contract-first ids:** choose `data-testid` values now (`<entity>-<field>`, `<action>-btn`,
  `<entity>-status`, `<role>-view`, `tab-<view>`, `panel-<view>`); the coder implements exactly these. Keep one glossary in `test_plan.md`.
- **State tests:** reach state S (through the UI or by seeding via `httpRequest` inside a `browser` test when a backend exists), act as
  the role, attempt the trigger, assert the control is hidden/disabled **or** the attempt shows the blocking
  reason and the status text is unchanged.
- **Negative & API Zero-Leak tests** assert the human-readable reason from the AC (never a raw code) and use `expectBodyNotContains` / `expectJsonPathAbsent` on `httpRequest` steps to prove internal fields and unmasked PII are excluded from API payloads.
- **Edge tests** from `BR-NN`: `fill` the threshold, threshold−1 unit, threshold+1 unit and assert the
  recomputed value/status **without** clicking submit (live calculation guardrail).
- **UX guardrail checks** where the AC calls for them: `expectCount` of primary buttons per view ≤ 1, visible
  inputs outside `<details>` (`:not(details *)`) per step ≤ 5, tabs per role ≤ 3 — unless §4 of the spec records an override. When using `setRole`, pass the exact option label rendered in `[data-testid=role-switcher]`.
- Set `runtime` (`browser` | `http` | `static`) and `role` (from §3.5) on every test.

**Scenario differences:** legacy projects get `legacyIdentifiers` in `forbiddenUiTokens` (legacy object names
must never appear in visible text); requirements-document projects have an empty list there. Everything else
is identical — both derive from the same spec tables.

### 3. Author `test/test_plan.md`
From the template: objectives, environment per `target_stack.json`, the eight categories with counts and
derivation sources, the `data-testid` glossary, AC → TC traceability, entry/exit criteria (Stage 6 PASS =
zero FAIL/ERROR/NOT_RUN, zero leakage hits, zero unwired controls, no pending Gate 4 flags).

### 4. Validate
```bash
python3 <PLUGIN>/skills/05-test-plan-designer/scripts/validate_test_cases.py --project-root "<PROJECT_ROOT>"
```
Every AC has a TC, every TC has non-empty steps, selectors are `[data-testid=…]`, schema valid.

### 5. Mandatory STOP at Gate 4A/4B (`gate_4_design_and_tests`) — Wait for Human Architecture & Test Plan Approval
`validate_test_cases.py` stamps `gate_4_design_and_tests = AWAITING_HUMAN_REVIEW` in `specs/gate_approvals.json`, blocking Stage 5 (`06-coding-agent`).
1. Present `test/test_plan.md` and `test/test_cases.json` (alongside the Stage 4A architecture suite) to the user for review.
2. **END YOUR TURN IMMEDIATELY (call zero further tools). NEVER start Stage 5 (`06-coding-agent`) in the same turn!**
3. Only **in a subsequent turn AFTER the human explicitly approves Gate 4A/4B**, run `gate_tracker.py --action approve --gate gate_4_design_and_tests --user-response "<verbatim user approval quote>"` before invoking `06-coding-agent`.

## Do not
- Start Stage 4B before `gate_3_backlog` is `APPROVED_BY_USER`, or auto-start Stage 5 before `gate_4_design_and_tests` is `APPROVED_BY_USER`.
- Write tests from a canned list of screens; every TC traces to an AC, a table row or a contract operation.
- Weaken a derived `TC-STATE-*` or leak test because the UI "doesn't have that yet" — that is the point.
- Put domain literals in the plugin; project-specific values live only in the project's `test/`.
