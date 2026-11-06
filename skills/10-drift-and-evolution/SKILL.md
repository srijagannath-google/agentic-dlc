---
name: 10-drift-and-evolution
description: "Stage 9 (Day-2 Evolution) of the Agentic DLC v4. Continuously audits spec-to-code, OpenAPI-to-route, DDL-to-persistence, state-machine, and data-testid alignment via 10/scripts/check_spec_code_drift.py -> test/drift_report.{json,md}, and governs bidirectional Architecture Decision Records (design/adrs/ADR-NNN.md) plus downstream artifact hash refresh when production code or requirements evolve after initial delivery."
---

# Stage 9 — Continuous Spec-to-Code Drift & Day-2 Evolution (`10-drift-and-evolution`)

Modernization and greenfield engineering do not end at initial fleet deployment. In Day-2 operations, engineers hotfix `src/`, add endpoints, adjust business thresholds, or ship the next Strangler capability wave (`GRP-02..N`). Without bidirectional governance, `specs/application_spec.md`, `design/solution_design.md`, and `test/test_cases.json` rapidly decay into stale shelfware.

Read first: `docs/ARCHITECTURE.md`, `_shared/workflow_chain_of_custody.md`, `_shared/gate_matrix.md`.

## When to Invoke

- **Post-deployment / Day-2 maintenance:** Whenever a developer or coding agent modifies `src/`, `specs/application_spec.md`, or `design/solution_design.md` after initial Stage 6/8 completion.
- **CI / Pull-Request drift gate:** Run `check_spec_code_drift.py --fail-on-drift` to ensure no undocumented route, schema table, state trigger, or `data-testid` drifts from approved upstream contracts.
- **Next Strangler Capability Wave:** Before advancing `selectedCapabilityGroups` from Wave 1 (`["GRP-01"]`) to Wave 2 (`["GRP-01", "GRP-02"]`).

## Step-by-Step Workflow

### 1. Run Deterministic Spec-to-Code Drift Detection
```bash
python3 <PLUGIN>/skills/10-drift-and-evolution/scripts/check_spec_code_drift.py \
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
  2. Update `specs/application_spec.md` (if business rules, states, or roles changed) and re-validate Gate 2 (`spec-judge` + `validate_spec_scorecard.py`).
  3. Update `design/solution_design.md` (if API paths or 3NF tables changed) and refresh downstream contracts, test skeletons (preserving authored steps), and evaluations in one command:
     ```bash
     python3 <PLUGIN>/scripts/run_agentic_dlc_pipeline.py \
       --project-root "<PROJECT_ROOT>" --refresh-from-stage 4 --to-stage 10
     ```

### 3. Deliverable Hygiene
`test/drift_report.md` and `design/adrs/ADR-*.md` are customer-facing engineering deliverables: never write internal plugin script names, `_shared/` paths, subagent slugs, or raw `SCENARIO_*` enum constants inside them.
