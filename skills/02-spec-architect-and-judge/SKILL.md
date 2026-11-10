---
name: 02-spec-architect-and-judge
description: "Stage 2 of the Agentic DLC v4. discovery-architect authors the holistic 5-Pillar Specification (specs/application_spec.md with the parsed §3.3 state-transition, §3.4 business-rule and §3.5 role tables; REQ-ENH-* only for legacy projects) and specs/traceability_matrix.md; spec-judge scores it against schemas/spec_rubric.json with verbatim evidence into specs/application_eval_scorecard.{md,json}; loop until 02/scripts/validate_spec_scorecard.py passes (Gate 2). Use when asked to write, score or judge the spec."
---

# Stage 2 — 5-Pillar Specification & LLM Spec Judge (Gate 2)

**Read before acting:** `docs/ARCHITECTURE.md` §4.3–§4.4, `_shared/workflow_chain_of_custody.md` ("Stage 2"),
`_shared/sdd_governance_and_alm.md`, `_shared/zero_leak.md`, `_shared/ux_guardrails.md`, `_shared/google_cloud_ui_design.md`, `schemas/spec_rubric.json`.
Subagents: `discovery-architect` (author), `spec-judge` (judge) — kept separate on purpose.

## Inputs
`specs/discovery_architecture_and_inventory.md`, `specs/input_inventory.json`, `specs/target_stack.json`,
`specs/clarification_decisions.json` (resolved `DECISION-NN` & `capabilityDispositions`, if present), Gate 1 answers / `ASSUMPTION-NN` list, `resources/policies_and_statutes/` (if any), `resources/design_references/` (if any).

## Outputs
| File | Author | Checked by |
| :-- | :-- | :-- |
| `specs/application_spec.md` | `discovery-architect` | `02/scripts/lint_spec_structure.py` (structure), `spec-judge` (quality) |
| `specs/traceability_matrix.md` | `discovery-architect` | `lint_spec_structure.py` (every REQ present) |
| `specs/application_eval_scorecard.md` + `.json` | `spec-judge` | `02/scripts/validate_spec_scorecard.py` |

## Procedure

### 1. Author the spec (`discovery-architect`)
Skeleton: `resources/spec_5pillar_template.md`. Structure is a contract (ARCHITECTURE §4.3):
- Header block: project name, `Input Scenario` (human-readable label: `Legacy Application Modernization` or `Greenfield Requirements Specification` — never internal `SCENARIO_*` enum constants), `Domain Slug`, `Status` (`🟡 IN REVIEW` → `🟡 IN PROGRESS` → `🟢 COMPLETED`, or `🟢 COMPLETED (Retro-Spec)` under `specLifecycleMode == "retro-spec"`), `Author` / optional `Co-Authors`, structured `Approvals` (`* **Approvals:**` with `* **Phases X - Y** - <ticket/PR> - <human_approvers>` sub-bullets; bot/agent identities strictly excluded), accessibility standard(s), regulations, assumptions.
- **Narrative Conciseness Budget (`SD-NARR-01`):** Keep non-table narrative prose under `3,500` words — put enforceable rules, transitions, roles, and view topologies in structured tables, not bloated BRD paragraphs.
- **Living Spec Modes (`standard` | `delta` | `retro-spec`):**
  - **`delta` mode (`--baseline-spec`):** Append Phase `N+1` requirements/enhancements while preserving prior completed (`- [x]`) roadmap records and historic `* **Approvals:**` sub-bullets byte-for-byte (`lint_spec_structure.py --baseline-spec <prior_spec>`).
  - **`retro-spec` mode (`specLifecycleMode == "retro-spec"`):** Reverse-engineer an existing production codebase into a verified `🟢 COMPLETED` 5-Pillar Living Specification + Traceability Matrix and **STOP after Gate 2** (enforcing the **Zero Backlog / Zero Child Ticket Creation Guarantee** — never spawn `To Do` stories for already-shipped code).
- `## 1 Pillar 1 — Functionality` (`REQ-FUNC-NN`); `### 1.4 Modernization Enhancements (REQ-ENH-NN)` **legacy only**.
- `## 2 Pillar 2 — Security` (`REQ-SEC-NN`) incl. RBAC matrix per §3.5 role and the **PII field list** to mask.
- `## 3 Pillar 3 — Accessibility` (`REQ-A11Y-NN`) per `target_stack.json#accessibilityStandard` — **and** the
  three parsed subsections that live under §3 in this template:
  - `### 3.3 Lifecycle State Machine`: one `stateDiagram-v2` block + `| From | To | Trigger | Actor Role | Guard |`
    mirroring it exactly (parsed by `dlc_common.parse_state_machine`);
  - `### 3.4 Business Rules & Formulas`: `| Rule ID | Formula / Rule | Inputs | Source | Examples |` (`BR-NN`; numbers, not adjectives; populate `Examples` with `input -> expected` vectors such as `amount=100 -> fee=105; amount=0 -> REJECT` so Stage 4B `derive_test_cases.py` compiles deterministic `TC-EDGE-BR-*` tests);
  - `### 3.5 Roles`: `| Role | Kind | Views | Allowed Transitions |` (Kind = `external` or `internal`).
- `## 4 Pillar 4 — UX & Zero Leakage` (`REQ-UX-NN`): the UX & Google Cloud UI Design guardrails by reference (`_shared/ux_guardrails.md` and `_shared/google_cloud_ui_design.md`, including Surface Mode declaration `Operate` | `Read` | `Persuade` | `Express`, Reference Layout Archetype from `skills/google-cloud-ui-design/references/*.md`, `--g-*` Light/Dark CSS tokens, Unified Surfaces without card soup, Guardrail #3 View & Tab Mutual Exclusivity, and Guardrail #11 Default Persona & Lifecycle Reachability),
  overrides from design references (`### 4.1`), the **mandatory parsed `### 4.2 View & Component Topology` table**
  (`| View ID | Navigation Tab / Route | UI Pattern | Bound Role(s) | Primary CTA & Lifecycle Trigger |`, aligned
  with `specs/design_reference/reference_ui_manifest.json` when present), and the zero-leakage rule (`### 4.3`).
- `## 5 Pillar 5 — Architecture` (`REQ-ARCH-NN`): clean architectural quality attributes (layered separation of concerns, contract-first OpenAPI 3.1 APIs, normalised 3NF relational domain model, ViewModel/DTO boundary with zero internal data leakage, `data-testid` contract, and OpenTelemetry observability — no legacy carry-over). If `specs/target_stack.json#decidedBy == "pending-stage-4a"`, keep Pillar 5 technology-agnostic so the human can select the concrete Future-State frontend, backend, and database technology when entering Stage 4A (`04-solution-architect`).
- Every REQ id unique; every REQ in `specs/traceability_matrix.md` (REQ → capability → story → test category).

**Derivation, not invention:** states/roles/rules and Legacy `REQ-ENH-*` capabilities come from the discovery blueprint, `specs/clarification_decisions.json` (`DECISION-NN` and `capabilityDispositions`: honor `retire` exclusions strictly per `SD-GRILL-02`, keep `parity` capabilities faithful, and author `REQ-ENH-*` from approved `reimagine-enhance` decisions), and Gate 1 answers. Never start Stage 2 while `clarification_decisions.json` has `openFrontier` items (`SD-GRILL-01`). If a gap remains, ask via `clarification-griller` (interactive) or record `ASSUMPTION-NN` with the most restrictive reading (autonomous).

**Scenario differences**
| | `SCENARIO_LEGACY_APP` | `SCENARIO_REQUIREMENTS_DOC` |
| :-- | :-- | :-- |
| §1.4 `REQ-ENH-*` | required: genuine new capabilities chosen from discovered pain points (self-service, live rule calculation, status notification, duplicate guardrails, search/reporting) | **forbidden** — specify exactly the documented scope |
| Legacy references | "replaces legacy object X" allowed in traceability, never in requirement text or UI labels | none |
| Regulation section | if `hasPoliciesOrStatutes` or `regulations` non-empty | same rule |

```bash
python3 <PLUGIN>/skills/02-spec-architect-and-judge/scripts/lint_spec_structure.py --project-root "<PROJECT_ROOT>"
```

### 2. Judge the spec (`spec-judge`)
The judge reads `schemas/spec_rubric.json`, scores each criterion with a **verbatim quote** from the spec,
writes `specs/application_eval_scorecard.json` (ARCHITECTURE §4.4) and `.md`
(`resources/scorecard_template.md`), then runs:
```bash
python3 <PLUGIN>/skills/02-spec-architect-and-judge/scripts/validate_spec_scorecard.py --project-root "<PROJECT_ROOT>"
```
The validator checks completeness, `awarded ≤ maxPoints`, sums, `specSha256` freshness, that each evidence
string is a substring of the spec, and `verdict == (total ≥ 90 ∧ no blocking criterion at 0)`.

### 3. Loop (Gate 2)
`FAIL` → judge returns numbered gaps → author fixes the spec → lint → judge re-scores (new hash) → validate.
Gate 2 is never pre-approved; autonomous mode just loops without asking.

### 4. Mandatory STOP at Gate 2 (`gate_2_spec`) — Wait for Human Specification Review & Approval
Once `validate_spec_scorecard.py` returns `PASS` (`total ≥ 90`, zero blocking gaps), it automatically stamps `gate_2_spec = AWAITING_HUMAN_REVIEW` in `specs/gate_approvals.json`, blocking Stage 3 (`alm_jira_ado_bridge.py`).
1. Present `specs/application_spec.md`, `specs/traceability_matrix.md`, and `specs/application_eval_scorecard.md` (with pillar scores) to the user for human review.
2. **END YOUR TURN IMMEDIATELY (call zero further tools). NEVER auto-start Stage 3 (`03-story-and-sprint-planner`) in the same turn!**
3. Only **in a subsequent turn AFTER the human explicitly approves Gate 2**, run:
   ```bash
   python3 <PLUGIN>/scripts/gate_tracker.py --project-root "<PROJECT_ROOT>" --action approve --gate gate_2_spec --user-response "<verbatim user approval quote>"
   ```
   and then proceed to `03-story-and-sprint-planner`.

## Do not
- Start Stage 2 before `gate_1_discovery` is `APPROVED_BY_USER`, or auto-start Stage 3 before `gate_2_spec` is `APPROVED_BY_USER`.
- Let the author score or the judge edit the spec.
- Expose internal harness paths (`_shared/*.md`, `*.py` scripts, `schemas/*.json`, subagent slugs, or `SCENARIO_*` enum constants) inside `specs/application_spec.md`, `specs/traceability_matrix.md`, or `specs/application_eval_scorecard.json` — express UX guardrails and zero-leakage presentation standards in clean professional prose and record only overrides.
- Add jurisdiction-specific accessibility/regulatory standards the user did not name.
