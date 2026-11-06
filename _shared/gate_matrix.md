# Human Gate Matrix, Adaptive Ceremony Tracks & Strangler Wave Governance

This reference defines the machine-enforced human gate ledger (`specs/gate_approvals.json`), adaptive ceremony tracks (`quick`, `standard`, `regulated`), 1-page Executive Gate Decision Briefs (`specs/gate_briefs/<gate_id>.md`), and iterative Strangler Fig capability waves.

## 1. Adaptive Ceremony Tracks (`ceremonyTrack`)

Configure at Stage 0 (`setup_project_connection.py --ceremony-track <track>`) or anytime via `gate_tracker.py --action set-track --track <track>`:

| Gate ID | Lifecycle Stage | `quick` (Prototypes / Low-Risk Internal Tools) | `standard` (Default Enterprise Delivery) | `regulated` (High-Compliance / Regulated Workloads) |
| :-- | :-- | :-- | :-- | :-- |
| `gate_0_setup` | Stage 0 — Setup & Connections | **Human Pause** | **Human Pause** | **Human Pause** |
| `gate_1_discovery` | Stage 1 — Current-State Discovery & Wave Selection | **Human Pause** | **Human Pause** | **Human Pause** |
| `gate_2_spec` | Stage 2 — 5-Pillar Spec & Spec-Judge (`>= 90/100`) | Auto-advances once `validate_spec_scorecard.py` passes (`AUTO_SKIPPED_BY_CEREMONY_TRACK`) | **Human Pause** | **Human Pause** |
| `gate_3_backlog` | Stage 3 — Stories, Sprints & ALM Board Staging | Auto-advances once `alm_jira_ado_bridge.py --action audit` passes | **Human Pause** | **Human Pause** |
| `gate_4_design_and_tests` | Stage 4A/4B — Target Stack, 7-Perspective Design & Test Plan | **Human Pause** | **Human Pause** | **Human Pause** + **Mandatory** `architecture-critic` Red-Team Scorecard (`>= 90/100`) |
| `gate_5_build` | Stage 5 — Runnable Dual-Mode Build | Auto-advances once `validate_build.py` passes | **Human Pause** | **Human Pause** |
| `gate_6_eval` | Stage 6 — Closed-Loop Browser/HTTP/Static Eval & Gate 4 Diff Audit | **Human Pause** (Gate 4 guardrail hunks **never** auto-approve) | **Human Pause** | **Human Pause** |
| `gate_7_drift` | Stage 7 — Pre-Deployment Spec-to-Code Drift & ADR Alignment | Auto-advances once `check_spec_code_drift.py` reports `ALIGNED` | **Human Pause** | **Human Pause** |
| `gate_8_packaging` | Stage 8 — Rootless OCI & GDC Multi-Cloud KRM Packaging | Auto-advances once `validate_gdc_packaging.py` passes | **Human Pause** | **Human Pause** |
| `gate_9_deployment` | Stage 9 — GDC Fleet GitOps, OpenTelemetry & SLO Verification | **Human Pause** | **Human Pause** | **Human Pause** |

> **Hard Invariant:** Even in `quick` or `--autonomous` mode, deterministic validators (`validate_spec_scorecard.py`, `extract_contracts.py`, `validate_test_cases.py`, `validate_build.py`, `run_closed_loop_eval.py`) are **never** bypassed, and Stage 6 **Gate 4** (`FLAGGED_REQUIRES_HUMAN_APPROVAL` on role, state-guard, formula, masking, or `@dlc-*` hunks) **always** pauses for explicit human review.

## 2. Executive Gate Decision Briefs (`specs/gate_briefs/<gate_id>.md`)

Whenever `mark_gate_awaiting_human()` runs at a gate boundary, it automatically writes a concise 1-page Markdown brief to `specs/gate_briefs/<gate_id>.md` summarizing:
1. Active ceremony track, selected capability wave (`selectedCapabilityGroups`), and coexistence strategy (`clean-cutover` | `boundary-acl-cdc` | `strangler-gateway`).
2. Open `ASSUMPTION-NN` decisions extracted from `specs/application_spec.md`.
3. Documented `REQ-ENH-NN` modernization divergences from legacy behavior.
4. Stage 4A Multi-Persona Architecture Red-Team score and blocking gaps (when `design/architecture_eval_scorecard.json` is present).
5. Pending Stage 6 guardrail-sensitive diff hunks (when `test/.guardrail_state.json` has `pendingHunks`).

Present this brief directly to the human reviewer, **end your turn immediately**, and record their verbatim reply in the next turn via `gate_tracker.py --action approve --gate <gate_id> --user-response "<verbatim reply>"`.

## 3. Iterative Strangler Fig Capability Waves (`GRP-01` → `GRP-02` → `ALL`)

For multi-module legacy estates, avoid risky "Big-Bang" cutovers by iterating Capability Waves:
1. **Stage 1 Topological Grouping:** Ground `§6.1 Business Capability Groupings` (`GRP-01..N`) in `specs/dependency_dag.json` so leaf/foundational capabilities precede dependent capabilities (`dependsOnGroups`).
2. **Wave Selection & Coexistence:** Set `selectedCapabilityGroups: ["GRP-01"]` and `coexistenceStrategy: "boundary-acl-cdc"` (or `"strangler-gateway"`) in `specs/target_stack.json` (or pass `--wave GRP-01` to `run_agentic_dlc_pipeline.py`).
3. **Disposable Boundary ACL Rule:** Keep `src/` 100% pure future-state domain models (zero legacy table/column names). Place any temporary Strangler routing rules, CDC Debezium/DMS connectors, or legacy-to-target outbox translation views strictly inside `deploy/coexistence/`, with explicit retirement milestones in `design/data_migration_and_cutover.md`.
4. **Next Wave Advancement:** Once Wave 1 passes Stage 9 deployment, re-run Stage 7 (`08-drift-and-evolution`) to verify zero drift, expand `selectedCapabilityGroups` to `["GRP-01", "GRP-02"]`, and run `--refresh-from-stage 4` to activate deferred stories and tests while preserving all previously authored test steps.
