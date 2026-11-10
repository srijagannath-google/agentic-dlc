---
name: 08-drift-and-evolution
description: "Stage 7 (Gate 7 Pre-Deployment Release Alignment & Day-2 Evolution) of the Agentic DLC v4. Verifies zero spec-to-code, OpenAPI-to-route, DDL-to-persistence, state-machine, and data-testid drift via 08/scripts/check_spec_code_drift.py -> test/drift_report.{json,md} AFTER Stage 6 self-healing and BEFORE Stage 8 containerization/GDC deployment, and governs bidirectional Architecture Decision Records (design/adrs/ADR-NNN.md) plus downstream artifact hash refresh on Day-2 evolution."
---

# Stage 7 — Pre-Deployment Spec-to-Code Drift Gate & Day-2 Evolution (`08-drift-and-evolution`)

During Stage 5 (Build) and Stage 6 (Closed-Loop Evaluation & Self-Healing), `src/` undergoes iterative fixes. **Before a single container image or GDC manifest is packaged (Stage 8) or deployed (Stage 9)**, Stage 7 verifies that `src/` remains 100% aligned with `specs/application_spec.md`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, and `test/test_cases.json`. In Day-2 operations, this same stage governs brownfield hotfixes, requirement changes, and subsequent Strangler capability waves (`GRP-02..N`).

Read first: `docs/ARCHITECTURE.md`, `_shared/sdd_governance_and_alm.md`, `_shared/workflow_chain_of_custody.md`, `_shared/gate_matrix.md`.

## When to Invoke

- **Mandatory Pre-Deployment Gate (Stage 7, after Gate 6 and BEFORE Stage 8 Packaging):** Verify `ALIGNED` (`0` blocking drift errors) after closed-loop evaluation & self-healing, stamping `gate_7_drift` before `09-container-and-gdc-packager` can run.
- **Post-deployment / Day-2 maintenance:** Re-run with `--skip-gate-check` (or via `--refresh-from-stage N`) whenever a developer or coding agent modifies `src/`, `specs/application_spec.md`, or `design/solution_design.md` after initial deployment.
- **CI / Pull-Request drift gate:** Run `check_spec_code_drift.py --skip-gate-check --fail-on-drift` to block undocumented routes, schema tables, state triggers, or missing `data-testid` selectors.
- **Next Strangler Capability Wave:** Before advancing `selectedCapabilityGroups` from Wave 1 (`["GRP-01"]`) to Wave 2 (`["GRP-01", "GRP-02"]`).

## Step-by-Step Workflow

### 1. Run Deterministic Spec-to-Code Drift Detection
```bash
python3 <PLUGIN>/skills/08-drift-and-evolution/scripts/check_spec_code_drift.py \
  --project-root "<PROJECT_ROOT>"
```
This inspects six alignment planes without mutating source files:
1. **Artifact Cryptographic Lineage:** Verifies SHA-256 freshness across `specs/application_spec.md` → `specs/application_eval_scorecard.json` & `test/test_cases.json`, and `design/solution_design.md` → `design/.contracts_index.json`.
2. **OpenAPI 3.1 ↔ Backend Route Parity:** Compares declared `src/contracts/openapi.yaml` path prefixes against implemented backend handlers in `src/backend/`.
3. **3NF SQL DDL ↔ Persistence Alignment:** Verifies every `CREATE TABLE` in `src/db/schema.sql` is backed by schema initialization or persistence queries in `src/backend/`.
4. **Lifecycle State Machine Chain-of-Custody:** Verifies Spec `§3.3` triggers and `§3.5` roles remain represented in `src/` and tracks `@dlc-guard` / `@dlc-rule` / `@dlc-mask` / `@dlc-a11y` contract pragmas.
5. **Contract-First `data-testid` Parity:** Verifies every selector in `test/.testid_contract.json` remains present in `src/ui/`.
6. **Architecture Decision Record (`design/adrs/ADR-NNN.md`) Governance:** Audits recorded ADRs for structural completeness (`Status`, `Context`, `Decision`, `Consequences`).

### 2. Reconcile Detected Drift (Bidirectional Sync)
When `test/drift_report.json` reports `DRIFT_DETECTED`:
- **Unintended Code Regression:** Have `coding-agent` restore conformance to `specs/application_spec.md`, `src/contracts/openapi.yaml`, and `src/db/schema.sql`.
- **Intentional Day-2 Evolution / Requirement Change:**
  1. Author an **Architecture Decision Record** in `design/adrs/ADR-NNN-<slug>.md` using `resources/adr_template.md` (zero internal harness script/skill names in deliverables).
  2. Update `specs/application_spec.md` in **Living Spec Phase `N+1` Delta Mode** (if business rules, states, or roles changed), preserving prior completed items and historic `* **Approvals:**` sub-bullets (`lint_spec_structure.py --baseline-spec <prior_spec>`), and re-validate Gate 2 (`spec-judge` + `validate_spec_scorecard.py`). Compact completed stories via `alm_jira_ado_bridge.py --action compact-completed` to prevent context bloat across waves.
  3. Update `design/solution_design.md` (if API paths or 3NF tables changed) and refresh downstream contracts, test skeletons (preserving authored steps), and evaluations in one command:
     ```bash
     python3 <PLUGIN>/scripts/run_agentic_dlc_pipeline.py \
       --project-root "<PROJECT_ROOT>" --refresh-from-stage 4 --to-stage 10
     ```

### 3. Pre-Deployment Gate 7 (`gate_7_drift`) & Deliverable Hygiene
When `check_spec_code_drift.py` reports `ALIGNED` (`errors == 0`) during interactive delivery, it stamps `gate_7_drift` in `specs/gate_approvals.json` (auto-advancing under `--track quick`, or pausing on `standard` / `regulated` for human review before Stage 8 `09-container-and-gdc-packager` can run). `test/drift_report.md` and `design/adrs/ADR-*.md` are customer-facing engineering deliverables: never write internal plugin script names, `_shared/` paths, subagent slugs, or raw `SCENARIO_*` enum constants inside them.
