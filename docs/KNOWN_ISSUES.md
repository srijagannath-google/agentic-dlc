# Known Issues & Friction Log (v4.4.0)

Collected while dogfooding both golden projects (`examples/*`). Items marked ✅ were fixed before release;
the rest are open and prioritised.

## Fixed in v4.4.0 ✅
- **TC-STATE explosion (#1):** `05/scripts/derive_test_cases.py --group-state-tests` groups illegal `(state, trigger)` and `(role, trigger)` pairs into compact parametrised `matrixCases` test definitions per trigger (`schemas/test_cases.schema.json`).
- **Per-test state reset & inline browser `httpRequest` (#2):** `target_stack.json#commands.reset` is invoked automatically before each `browser`/`http` test in `run_closed_loop_eval.py`, and both `PlaywrightAdapter` and `dom_driver.js` (`chrome-headless`) now execute `httpRequest` steps inline inside `browser` tests.
- **Guardrail classifier false positives (#3):** `04/scripts/extract_contracts.py` indexes explicit `@dlc-guard`/`@dlc-rule`/`@dlc-mask`/`@dlc-a11y` pragmas into `design/.contracts_index.json#guardrailBindings`, and `run_closed_loop_eval.py` strips ISO-8601 timestamp literals and generic column words before numeric formula proximity matching.
- **Downstream hash refresh (#4):** `run_agentic_dlc_pipeline.py --refresh-from-stage <N>` re-hashes and re-derives downstream contracts/tests after an intentional brownfield spec/design edit (`10-drift-and-evolution`) while preserving authored test steps by `derivationKey`.
- **Negative HTTP assertions (#5):** `validate_test_cases.py` and `run_closed_loop_eval.py` now support `expectBodyNotContains` and `expectJsonPathAbsent` on `httpRequest` steps (plus anti-tautology checks).
- **Generic XSD/XML stopwords (#8):** `01/scripts/scan_input_sources.py` filters generic XSD/XML wrapper identifiers (`dataroot`, `CreatedOn`, `UpdatedAt`, `rowguid`, etc.) from `legacyObjectNames` and extracts `unverifiedAcronyms` + `specs/dependency_dag.json`.

## Fixed during v4.3 dogfooding ✅
- `dlc_common.strip_md` removed `_` inside identifiers (`MANAGER_APPROVED` → `MANAGERAPPROVED`).
- `scan_input_sources.py`: domain slug included document-type prefixes; `--domain-slug` override was lost on
  re-scan.
- `validate_discovery_blueprint.py` rejected a heading its own template emitted; template lacked the
  `Project Name` line.
- `derive_test_cases.py`: re-derivation dropped authored `runtime`; creation-only triggers (`[*] → X`) spawned
  meaningless illegal-pair tests; every all-caps OpenAPI enum member was a FAIL-level leak token (now only
  states/triggers and underscore codes fail; short all-caps members warn — `enumCodesWarnOnly`).
- `validate_test_cases.py`: rejected `check/uncheck/expectAttribute` and `expectCount` with `min/max`.
- `check_testid_contract.py`: dynamic ids (`'row-' + id`, template literals) and absence-only ids.
- `dom_driver.js`: unhandled promise rejections were invisible; now recorded as script errors.
- `run_closed_loop_eval.py`: snapshots ignored databases/logs; binary files skipped in diffs; markdown hunks not
  guardrail-classified; stale server on the healthcheck port detected.
- Docs: `set-approval` syntax, roles table header without a pipe.

## Open — medium
6. `dom_driver.isVisible` treats fields inside a closed `<details>` as visible; UX metric compensates, and `skills/05-test-plan-designer/SKILL.md` documents `:not(details *)`.
7. `setRole` text matching is "contains"; multi-identity switchers use exact option labels (documented in `skills/05-test-plan-designer/SKILL.md`).
9. Static a11y/leak lint runs on the raw `index.html`; `skills/06-coding-agent/SKILL.md` documents the "render all views in DOM, toggle visibility" pattern for `static-html`.
10. Playwright adapter falls back cleanly to the verified `chrome-headless` adapter when Python `playwright` is not installed on the host.

## Non-goals (by design)
- Scripts never author content; a missing artefact is always an LLM task.
- `NOT_RUN` never counts as a pass; without a browser the pipeline cannot go green.

## Remaining by design (v4.4.0) — read before relying on a gate

11. **`shell=True` on `target_stack.json#commands.*` is a trust boundary.** `validate_build.py`,
    `run_closed_loop_eval.py` and `run_gdc_fleet_deploy_and_verify.py` execute `commands.install/build/start/test`
    verbatim through the shell so that `&&`, env assignments and quoting work across target stacks. The commands are
    authored by `solution-architect` at Gate 4A and approved by the human; never point the harness at an untrusted
    `specs/target_stack.json` or run it as root against untrusted inputs.
12. **Headless Chrome under root needs `--no-sandbox`.** Chrome refuses to start as UID 0 without `--no-sandbox`; the
    adapters add it only when UID 0 is detected or `DLC_CHROME_NO_SANDBOX=1` is set. Prefer running as a non-root user.
13. **Gate 7 and Gate 8 are manifest-level unless `--live`.** `validate_gdc_packaging.py` parses Dockerfiles and KRM
    YAML; `run_gdc_fleet_deploy_and_verify.py` validates Config Sync/observability manifests and runs a **local**
    smoke probe (`executionMode: manifest-validation`, wave status `MANIFEST_VALIDATED`). Only `--live` runs
    `kubectl apply -k deploy/gdc/overlays/<env>` and records `DEPLOYED` / `gdc-live-fleet`.
14. **Degraded-mode marker is advisory at Gate 5, blocking at Gate 7.** If `src/run.sh` falls back to a local dev
    runner because the native toolchain is absent (`test/.build_logs/degraded_mode.json`), Gate 7 refuses until a real
    container build is recorded in `deploy/.container_build_verified.json` (or `--container-build-verified`).
15. **Machine-enforced human gate ledger (`specs/gate_approvals.json`).** Every stage script calls
    `require_gate_approved()` and rejects missing or unapproved upstream gates unless `DLC_AUTONOMOUS=1` (explicit
    `--autonomous`) or `DLC_GOLDEN_RUN=1` (`verify_golden_projects.py`) is set. `gate_tracker.py --action approve`
    enforces `readyAtEpoch` presence and an 8-second turn-boundary cooldown in interactive mode.
16. **Pipeline is "verify + derive", not read-only.** `run_agentic_dlc_pipeline.py` refreshes `test/test_cases.json`
    (preserving authored steps by `derivationKey`), `src/contracts/`, `src/db/`, `design/diagrams/` and, with
    `--autonomous`, `specs/gate_approvals.json` and Gate 3 backlog pre-approval.
