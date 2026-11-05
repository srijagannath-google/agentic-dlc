# Specification Quality Scorecard (Gate 2)

- **Specification Audited:** `specs/application_spec.md` (sha256 `122f76cd2e98…`)
- **Input Scenario:** Greenfield Requirements Specification
- **Rubric Version:** `4.0`
- **Judged At (UTC):** `2026-10-29T23:40:15Z`
- **TOTAL_SCORE:** `99/100` (pass threshold `90`)
- **OVERALL_VERDICT:** `PASS`

> Synchronized from `specs/application_eval_scorecard.json`.

## Pillar 1 — Functionality & Business Rules (`25/25`)

| Criterion | Title | Awarded | Max | Blocking | Evidence (verbatim) | Gap |
| :-- | :-- | :-: | :-: | :-: | :-- | :-- |
| `P1-C1` | Complete REQ-FUNC coverage of every discovered capability | 6 | 6 | yes | Capability coverage is complete: all 11 capabilities CAP-01…CAP-11 of the discovery inventory map to at least one requirement below … REQ-FUNC-06 \| The Manager queue lists only `SUBMITTED` requests whose requester reports directly to the signed-in Manager |  |
| `P1-C2` | Lifecycle state machine: diagram + transition table complete and evidenced | 6 | 6 | yes | \| SUBMITTED \| MANAGER_APPROVED \| Manager Approve \| Manager \| requester is a direct report; BR-02 applies — requested hours > 40 or type Exception (BRD §4 steps 3–4) \| … Terminal states: `POSTED`, `WITHDRAWN` (ASSUMPTION-03). Initial state: `DRAFT`. |  |
| `P1-C3` | Business rules & formulas with inputs and sources | 5 | 5 | yes | \| BR-03 \| `start_date − submit_date ≥ 3` calendar days unless `leave_type = Exception`; `earliest_date = submit_date + 3 days` \| start date, submit date (today, UTC), leave type \| BRD §3 BR-03; HR policy §4.2 \| |  |
| `P1-C4` | Scenario rule honoured (REQ-ENH present iff legacy; zero scope creep for requirements docs) | 4 | 4 | yes | **Input Scenario:** `Greenfield Requirements Specification` … scope is strictly the input document (BRD v1.0, FR-01…FR-08, NFR-01…NFR-05, BR-01…BR-05); nothing unsolicited is added and no modernization enhancements exist for this scenario. |  |
| `P1-C5` | Open questions and assumptions recorded explicitly | 4 | 4 | no | `ASSUMPTION-04` — Withdrawal is possible from `DRAFT`, `SUBMITTED` and `MANAGER_APPROVED` only; an `APPROVED` request can no longer be withdrawn even if payroll posting has not yet succeeded. |  |

## Pillar 2 — Security, RBAC, PII Protection & Compliance (`19/20`)

| Criterion | Title | Awarded | Max | Blocking | Evidence (verbatim) | Gap |
| :-- | :-- | :-: | :-: | :-: | :-- | :-- |
| `P2-C1` | Authentication model defined | 4 | 4 | no | REQ-SEC-01 \| Authentication: every role signs in through the organisation's OIDC provider (authorization-code flow); the role is taken from the token's group claims (`employees`, `managers`, `hr-certifiers`); sessions expire after 8 hours of inactivity and an expired session redirects to sign-in with the draft preserved locally. No anonymous access exists. |  |
| `P2-C2` | RBAC matrix per role × transition / view | 5 | 5 | yes | \| Manager Approve (`SUBMITTED → MANAGER_APPROVED / APPROVED`) \| ✗ \| ✓ (direct reports) \| ✗ \| ✗ \| … a denied attempt returns 403 (role) or 409 (state) with a user-readable message, changes nothing and is audited (REQ-FUNC-10). External-role views never render internal controls. |  |
| `P2-C3` | PII inventory and masking rules | 4 | 4 | yes | \| Employee identifier (format `EMP-\d{5}`) \| Personal identifier \| Last two digits only: `EMP-•••42`; full value never rendered \| Encrypted at rest; audit on access \| Life of the employment record + 7 years (audit) \| |  |
| `P2-C4` | Encryption in transit and at rest | 3 | 3 | no | REQ-SEC-04 \| Encryption: TLS 1.2+ for all transport including the call to payroll; the database file and backups are encrypted at rest with keys owned by the platform team's key-management service; secrets (payroll credentials, OIDC client secret) are injected from the environment and never stored in source. |  |
| `P2-C5` | Immutable audit trail of workflow actions | 3 | 4 | no | REQ-SEC-05 \| Audit trail: every state transition, denied attempt and payroll posting writes an append-only record `{request, actor, role, previous state, new state, timestamp UTC, reason/comment}`; records cannot be updated or deleted through any API and are retained for 7 years; only internal roles can read them. | Read access to PII (e.g. a manager opening a request's reason text) is not listed as an audited event in §2.3; only transitions, denied attempts and payroll postings are. Add a 'PII access' event row or state explicitly why display-name/reason reads are not audited. |

## Pillar 3 — Accessibility (WCAG 2.1 AA) (`20/20`)

| Criterion | Title | Awarded | Max | Blocking | Evidence (verbatim) | Gap |
| :-- | :-- | :-: | :-: | :-: | :-- | :-- |
| `P3-C1` | Colour contrast and non-colour status cues | 3 | 3 | no | REQ-A11Y-01 \| Text contrast ≥ 4.5:1 and large text / UI component contrast ≥ 3:1 using the three semantic status tokens; every status and validation severity is conveyed by text (label or icon with text), never by colour alone. |  |
| `P3-C2` | Full keyboard operability | 4 | 4 | yes | REQ-A11Y-02 \| Full keyboard operability: every control is reachable with Tab in a logical order and operable with Enter/Space; no keyboard trap; a "Skip to main content" link is the first focusable element |  |
| `P3-C3` | Focus management and visible focus | 3 | 3 | no | REQ-A11Y-03 \| Focus management: a visible focus indicator (≥ 3:1 outline) on every control; after Submit, focus moves to the validation summary (on failure) or to the status heading (on success); after a view/role change focus moves to the view's `h2`. |  |
| `P3-C4` | Programmatic labels, names and roles | 4 | 4 | yes | REQ-A11Y-04 \| Programmatic labels and roles: every `input`/`select`/`textarea` has a visible `<label for>`; icon-only buttons carry `aria-label`; landmarks `header`, `nav`, `main` exist; exactly one `h1`, with `h2` per view; data tables use `<th scope>`. |  |
| `P3-C5` | Live regions for dynamic updates | 3 | 3 | no | REQ-A11Y-05 \| Live regions: the live balance uses `aria-live="polite"`; validation summaries use `role="alert"`; status changes announce through a `role="status"` region. |  |
| `P3-C6` | Error identification, description and suggestion | 3 | 3 | no | REQ-A11Y-06 \| Error identification: each validation message names the field, describes the problem in plain language and states the fix (§1.3); the field gets `aria-invalid="true"` and `aria-describedby` pointing at the message; a summary is shown above the form. |  |

## Pillar 4 — User Experience & Zero Internal Data Leakage (`15/15`)

| Criterion | Title | Awarded | Max | Blocking | Evidence (verbatim) | Gap |
| :-- | :-- | :-: | :-: | :-: | :-- | :-- |
| `P4-C1` | End-to-end user journeys per role | 4 | 4 | no | **Employee (external):** 1. Open the portal → "My requests" view with balance summary. 2. Choose "New request", fill type, dates, hours, reason; live balance updates (REQ-FUNC-02); save → `DRAFT`. |  |
| `P4-C2` | UX guardrails adopted or explicitly overridden | 3 | 3 | no | REQ-UX-01 \| The ten Enterprise UX Simplicity Guardrails are adopted as defaults with no overrides (§4.1) |  |
| `P4-C3` | View & Component Topology table (§4.2) and design reference alignment | 3 | 3 | yes | REQ-UX-02 \| Design reference: `resources/design_references/` is empty, so the default clean Material-Design-3-style theme (system font stack, 8 px spacing grid, tonal surfaces) is applied |  |
| `P4-C4` | Zero internal-data-leakage mandate with label mapping | 5 | 5 | yes | \| MANAGER_APPROVED \| Manager approved \| HR Certifier \| … REQ-UX-03 \| Zero internal-data leakage boundary: visible text never contains database table/column identifiers, raw `UPPER_SNAKE_CASE` state/trigger/error codes, internal keys or UUIDs, API paths, SQL, or engineering notes |  |

## Pillar 5 — Clean Target Architecture & Engineering Guidelines (`20/20`)

| Criterion | Title | Awarded | Max | Blocking | Evidence (verbatim) | Gap |
| :-- | :-- | :-: | :-: | :-: | :-- | :-- |
| `P5-C1` | Target stack alignment | 3 | 3 | no | REQ-ARCH-01 \| Target stack alignment: frontend `static-html` (one page `src/ui/index.html` + `app.js` + `styles.css`, no framework), backend `python-stdlib-http` (Python 3 standard library `http.server`, no third-party packages) serving the UI, `/api/*`, `/health` and the local payroll stub on port 8766, database `sqlite` |  |
| `P5-C2` | Normalised 3NF domain schema | 3 | 3 | no | REQ-ARCH-03 \| Normalised 3NF schema in business `snake_case` (`employee`, `leave_balance`, `leave_type`, `leave_request`, `review_comment`, `request_state_change`, `payroll_posting`) with primary keys, foreign keys, a `status` column constrained to the §3.3 state codes, no derived columns |  |
| `P5-C3` | OpenAPI 3.1 contract requirement | 3 | 3 | yes | REQ-ARCH-04 \| Contract-first API: `design/solution_design.md` contains an OpenAPI 3.1 document with one operation per §3.3 trigger … a common error schema `{code, message}` whose `message` is user-readable; transition endpoints validate `(fromState, trigger, role)`. |  |
| `P5-C4` | ViewModel / DTO presentation boundary | 3 | 3 | no | REQ-ARCH-05 \| ViewModel / DTO boundary: API responses consumed by the UI are display models — codes mapped to labels, employee identifier masked, national identifier and internal keys excluded; templates never bind to raw persistence rows. |  |
| `P5-C5` | Testability contract (stable data-testid hooks) | 3 | 3 | no | REQ-ARCH-06 \| Testability contract: every interactive control, status display and queue row carries a stable kebab-case `data-testid` declared first in `test/test_cases.json` (contract-first), named by entity/role/transition |  |
| `P5-C6` | Traceability matrix completeness | 3 | 3 | yes | See `specs/traceability_matrix.md` — every `REQ-*` above maps to capability → source paragraph → business rules → planned story → test category. |  |
| `P5-C7` | No legacy carry-over (names, bridges, adapters) | 2 | 2 | no | N/A — not applicable to Greenfield Requirements Specification | not applicable: greenfield requirements document, no legacy estate |

## Blocking Gaps

- None

## Validator Findings

- All structural checks passed.
