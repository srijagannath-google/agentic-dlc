# Test Plan (`test/test_plan.md`) — Employee Leave & Exception Request Portal

- **Executable twin:** `test/test_cases.json` (contract-first executable test suite with deterministic browser, HTTP, and static steps)
- **Derived from:** `backlog/user_stories.json` (sha `275986796af8…`), `specs/application_spec.md` (sha `553172354ef6…`), `src/db/schema.sql`, `src/contracts/openapi.yaml`, `specs/input_inventory.json`
- **Environment:** `python3 src/backend/server.py` (demo mode: fixed clock 2031-03-02, seeded identities and fixtures) · healthcheck `http://127.0.0.1:8766/health` · uiEntry `http://127.0.0.1:8766/` · browser chain `playwright → chrome-headless → NOT_RUN`

## 1. Objectives & Exit Criteria
Stage 6 PASS = zero `FAIL/ERROR/NOT_RUN` among non-optional tests, zero leakage hits, zero unwired controls, no pending Gate 4 flag. Every acceptance criterion of the 14 approved stories has one executable test; every illegal (state, trigger) pair and every (role, trigger) pair the role does not own has a synthesised `TC-STATE-*`; every OpenAPI operation has a `TC-API-*` smoke test.

### Test data strategy
Browser tests share one running backend, so each test creates the record it needs (Alex Rivera, unique week per test from 2031-08-04 on) and, where it leaves pending hours behind, withdraws it at the end. Exact-number assertions use **Sam Chen** (40 h available, never submits more than 8 h). Fixtures used read-only by browser tests: LR-1001 (Posted), LR-1002 (Approved, payroll failed), LR-1006 (Submitted, consumed only by US-FUNC-06/AC-08), LR-1003 (other manager — visibility only), LR-1004 (Certification queue). API smoke tests run last and consume Jordan Blake's fixtures LR-1003/1004/1005/1007/1008/1009 through the identity headers `X-Actor-Role` / `X-Actor-Ref`.

## 2. Categories
| Category | ID prefix | Derivation source | Runtime | Count |
| :-- | :-- | :-- | :-- | :-: |
| Positive | `TC-POS-*` | ACs tagged `POSITIVE` | browser/http | 33 |
| Negative | `TC-NEG-*` | ACs tagged `NEGATIVE` — assert the §1.3 user-readable reason | browser/http | 15 |
| Edge | `TC-EDGE-*` | ACs tagged `EDGE / BOUNDARY`; BR-01 at 40 / 39.5 / 40.5 h, BR-03 at 2 / 3 days, BR-06 at 500 / 501 chars | browser/http | 9 |
| UiLeak | `TC-UI-LEAK-01..04` | `forbiddenUiTokens`: 37 DDL identifiers · 22 state/trigger/error codes · 0 legacy identifiers · 2 PII patterns (spec §2.2) | static | 4 |
| State | `TC-STATE-*` | ACs tagged role-visibility / prerequisite-gate + every illegal (state, trigger) pair and (role, trigger) pair from §3.3/§3.5 | browser/http | 61 |
| Interact | `TC-UI-INTERACT-*` | generic dead-control scan + ACs tagged `POSITIVE — INTERACTIVE COMPLETENESS` | browser/static | 8 |
| A11y | `TC-A11Y-01` | WCAG 2.1 AA static baseline (labels, names, single h1, lang, tabindex) | static | 1 |
| Api | `TC-API-*` | one per OpenAPI operation (17) | http | 17 |
| **Total** | | | | **148** |

## 3. `data-testid` Glossary *(contract-first — the coder implements exactly these)*
| Selector | Element | Used by tests |
| :-- | :-- | :-- |
| `role-switcher` | `select` in the header — demo identity (Employee (Alex Rivera) / Employee (Sam Chen) / Manager (Morgan Lee) / HR Certifier (Priya Nair) / Payroll Integration (system)) | every `setRole` step |
| `skip-link` | first focusable `a[href=#main]` | TC-A11Y, US-TECH-03 |
| `view-title` | `h2` of the active role view (My requests · Manager queue · Certification queue · Payroll postings) | role tests |
| `employee-view / manager-view / hr-view / payroll-view` | one `section` per role; only the active role's section is rendered | role visibility |
| `status-region` | `role=status` live region announcing the last outcome ("Request submitted", "Request withdrawn" …) | US-FUNC-04, US-TECH-03 |
| `balance-panel` | `aria-live=polite` panel | US-FUNC-02, US-TECH-03 |
| `available-balance / post-request-balance` | BR-01 figures, formatted `N h` | US-FUNC-02 |
| `balance-warning` | inline live BR-01 message (shown only when requested > available) | US-FUNC-02 |
| `certification-indicator` | BR-02 live text: "HR certification required" / "Manager approval is final" | US-FUNC-02 |
| `lead-time-hint` | BR-03 live text: "Earliest start date: YYYY-MM-DD" / "No lead time required for Exception" | US-FUNC-02 |
| `new-request-btn` | Employee-only secondary button opening the form | US-FUNC-01, role tests |
| `request-form` | `form`; 4 wrappers `visible-field` (leave-type, start-date, end-date, hours) + `<details>` containing `reason` | US-FUNC-01..03, US-TECH-04 |
| `leave-type / start-date / end-date / hours / reason` | inputs bound to visible labels | all form tests |
| `save-draft-btn / submit-btn` | secondary save · primary submit (Create/Submit triggers) | US-FUNC-01, US-FUNC-03, state tests |
| `validation-summary` | `role=alert` summary with the §1.3 messages; fields get `aria-invalid` + `aria-describedby` | negative tests |
| `request-detail` | card for the selected request (persists across role switches) | all |
| `request-reference / request-status / request-next-approver / request-hours / request-employee` | display fields of the ViewModel (status label, next approver, `N h`, `Name · EMP-•••NN`) | all |
| `return-comment` | latest return comment with the returning role | US-FUNC-05..07 |
| `posting-outcome` | payroll posting outcome of the selected request ("Accepted by payroll — PAY-…" / "Payroll posting failed") | US-FUNC-08 |
| `audit-log` | list of `From → To · actor · time` entries (actor shown to internal roles only) | US-FUNC-09 |
| `withdraw-btn / approve-btn / return-btn / certify-btn` | transition buttons rendered only when the backend lists the action in `allowedActions` | state / role tests |
| `post-btn` | declared absent: `Post` is a system transition and must never render for any role | TC-STATE (absence only) |
| `return-comment-input` | textarea for the mandatory return comment (BR-07) | US-FUNC-06/07 |
| `history-table / history-row-<ref> / open-<ref>` | Employee history rows with an Open button | US-FUNC-05 |
| `manager-queue / hr-queue / queue-row-<ref>` | queue tables; rows carry the request reference | US-FUNC-06/07 |
| `posting-log / posting-row-<ref>` | Payroll Integration log of posting attempts with alerts | US-FUNC-08 |

## 4. Traceability (story / AC → test case)
| Story | AC | Test case | Category | Runtime |
| :-- | :-- | :-- | :-- | :-- |
| US-FUNC-01 | AC-01 | TC-POS-01 | Positive | browser |
| US-FUNC-01 | AC-02 | TC-NEG-01 | Negative | browser |
| US-FUNC-01 | AC-03 | TC-NEG-02 | Negative | browser |
| US-FUNC-01 | AC-04 | TC-UI-INTERACT-02 | Interact | browser |
| US-FUNC-01 | AC-05 | TC-EDGE-01 | Edge | browser |
| US-FUNC-01 | AC-06 | TC-STATE-01 | State | browser |
| US-FUNC-02 | AC-01 | TC-POS-02 | Positive | browser |
| US-FUNC-02 | AC-02 | TC-EDGE-02 | Edge | browser |
| US-FUNC-02 | AC-03 | TC-EDGE-03 | Edge | browser |
| US-FUNC-02 | AC-04 | TC-EDGE-04 | Edge | browser |
| US-FUNC-02 | AC-05 | TC-POS-03 | Positive | browser |
| US-FUNC-02 | AC-06 | TC-POS-04 | Positive | browser |
| US-FUNC-03 | AC-01 | TC-POS-05 | Positive | browser |
| US-FUNC-03 | AC-02 | TC-NEG-03 | Negative | browser |
| US-FUNC-03 | AC-03 | TC-NEG-04 | Negative | browser |
| US-FUNC-03 | AC-04 | TC-NEG-05 | Negative | browser |
| US-FUNC-03 | AC-05 | TC-EDGE-05 | Edge | browser |
| US-FUNC-03 | AC-06 | TC-EDGE-06 | Edge | browser |
| US-FUNC-03 | AC-07 | TC-POS-06 | Positive | browser |
| US-FUNC-03 | AC-08 | TC-STATE-02 | State | browser |
| US-FUNC-04 | AC-01 | TC-POS-07 | Positive | browser |
| US-FUNC-04 | AC-02 | TC-POS-08 | Positive | browser |
| US-FUNC-04 | AC-03 | TC-STATE-03 | State | browser |
| US-FUNC-04 | AC-04 | TC-STATE-04 | State | browser |
| US-FUNC-04 | AC-05 | TC-STATE-05 | State | browser |
| US-FUNC-04 | AC-06 | TC-UI-INTERACT-03 | Interact | browser |
| US-FUNC-05 | AC-01 | TC-POS-09 | Positive | browser |
| US-FUNC-05 | AC-02 | TC-POS-10 | Positive | browser |
| US-FUNC-05 | AC-03 | TC-STATE-06 | State | browser |
| US-FUNC-05 | AC-04 | TC-UI-INTERACT-04 | Interact | browser |
| US-FUNC-05 | AC-05 | TC-EDGE-07 | Edge | browser |
| US-FUNC-06 | AC-01 | TC-POS-11 | Positive | browser |
| US-FUNC-06 | AC-02 | TC-POS-12 | Positive | browser |
| US-FUNC-06 | AC-03 | TC-NEG-06 | Negative | browser |
| US-FUNC-06 | AC-04 | TC-POS-13 | Positive | browser |
| US-FUNC-06 | AC-05 | TC-STATE-07 | State | browser |
| US-FUNC-06 | AC-06 | TC-NEG-07 | Negative | browser |
| US-FUNC-06 | AC-07 | TC-STATE-08 | State | browser |
| US-FUNC-06 | AC-08 | TC-UI-INTERACT-05 | Interact | browser |
| US-FUNC-07 | AC-01 | TC-POS-14 | Positive | browser |
| US-FUNC-07 | AC-02 | TC-POS-15 | Positive | browser |
| US-FUNC-07 | AC-03 | TC-NEG-08 | Negative | browser |
| US-FUNC-07 | AC-04 | TC-POS-16 | Positive | browser |
| US-FUNC-07 | AC-05 | TC-STATE-09 | State | browser |
| US-FUNC-07 | AC-06 | TC-STATE-10 | State | browser |
| US-FUNC-08 | AC-01 | TC-POS-17 | Positive | browser |
| US-FUNC-08 | AC-02 | TC-NEG-09 | Negative | browser |
| US-FUNC-08 | AC-03 | TC-STATE-11 | State | browser |
| US-FUNC-08 | AC-04 | TC-UI-INTERACT-06 | Interact | browser |
| US-FUNC-09 | AC-01 | TC-POS-18 | Positive | browser |
| US-FUNC-09 | AC-02 | TC-POS-19 | Positive | browser |
| US-FUNC-09 | AC-03 | TC-NEG-10 | Negative | http |
| US-FUNC-09 | AC-04 | TC-EDGE-08 | Edge | http |
| US-TECH-01 | AC-01 | TC-STATE-12 | State | http |
| US-TECH-01 | AC-02 | TC-STATE-13 | State | http |
| US-TECH-01 | AC-03 | TC-NEG-11 | Negative | http |
| US-TECH-01 | AC-04 | TC-STATE-14 | State | http |
| US-TECH-01 | AC-05 | TC-POS-20 | Positive | browser |
| US-TECH-02 | AC-01 | TC-POS-21 | Positive | browser |
| US-TECH-02 | AC-02 | TC-NEG-12 | Negative | http |
| US-TECH-02 | AC-03 | TC-NEG-13 | Negative | http |
| US-TECH-02 | AC-04 | TC-POS-22 | Positive | http |
| US-TECH-02 | AC-05 | TC-EDGE-09 | Edge | http |
| US-TECH-03 | AC-01 | TC-POS-23 | Positive | browser |
| US-TECH-03 | AC-02 | TC-POS-24 | Positive | browser |
| US-TECH-03 | AC-03 | TC-POS-25 | Positive | browser |
| US-TECH-03 | AC-04 | TC-POS-26 | Positive | browser |
| US-TECH-03 | AC-05 | TC-UI-INTERACT-07 | Interact | browser |
| US-TECH-04 | AC-01 | TC-POS-27 | Positive | browser |
| US-TECH-04 | AC-02 | TC-POS-28 | Positive | browser |
| US-TECH-04 | AC-03 | TC-POS-29 | Positive | browser |
| US-TECH-04 | AC-04 | TC-NEG-14 | Negative | browser |
| US-TECH-04 | AC-05 | TC-UI-INTERACT-08 | Interact | browser |
| US-TECH-05 | AC-01 | TC-POS-30 | Positive | http |
| US-TECH-05 | AC-02 | TC-POS-31 | Positive | http |
| US-TECH-05 | AC-03 | TC-POS-32 | Positive | http |
| US-TECH-05 | AC-04 | TC-NEG-15 | Negative | http |
| US-TECH-05 | AC-05 | TC-POS-33 | Positive | http |

## 5. Role & State Coverage (synthesised)
| Test | Derivation | Expected |
| :-- | :-- | :-- |
| TC-STATE-15 | `illegal:DRAFT/Manager Approve` | With a record in state 'DRAFT', the control for 'Manager Approve' is hidden or disabled for every role (Manager); any attempt leaves the sta |
| TC-STATE-16 | `illegal:DRAFT/Return` | With a record in state 'DRAFT', the control for 'Return' is hidden or disabled for every role (HR Certifier, Manager); any attempt leaves th |
| TC-STATE-17 | `illegal:DRAFT/Certify` | With a record in state 'DRAFT', the control for 'Certify' is hidden or disabled for every role (HR Certifier); any attempt leaves the state  |
| TC-STATE-18 | `illegal:DRAFT/Post` | With a record in state 'DRAFT', the control for 'Post' is hidden or disabled for every role (Payroll Integration); any attempt leaves the st |
| TC-STATE-19 | `illegal:SUBMITTED/Submit` | With a record in state 'SUBMITTED', the control for 'Submit' is hidden or disabled for every role (Employee); any attempt leaves the state ' |
| TC-STATE-20 | `illegal:SUBMITTED/Certify` | With a record in state 'SUBMITTED', the control for 'Certify' is hidden or disabled for every role (HR Certifier); any attempt leaves the st |
| TC-STATE-21 | `illegal:SUBMITTED/Post` | With a record in state 'SUBMITTED', the control for 'Post' is hidden or disabled for every role (Payroll Integration); any attempt leaves th |
| TC-STATE-22 | `illegal:MANAGER_APPROVED/Submit` | With a record in state 'MANAGER_APPROVED', the control for 'Submit' is hidden or disabled for every role (Employee); any attempt leaves the  |
| TC-STATE-23 | `illegal:MANAGER_APPROVED/Manager Approve` | With a record in state 'MANAGER_APPROVED', the control for 'Manager Approve' is hidden or disabled for every role (Manager); any attempt lea |
| TC-STATE-24 | `illegal:MANAGER_APPROVED/Post` | With a record in state 'MANAGER_APPROVED', the control for 'Post' is hidden or disabled for every role (Payroll Integration); any attempt le |
| TC-STATE-25 | `illegal:APPROVED/Submit` | With a record in state 'APPROVED', the control for 'Submit' is hidden or disabled for every role (Employee); any attempt leaves the state 'A |
| TC-STATE-26 | `illegal:APPROVED/Manager Approve` | With a record in state 'APPROVED', the control for 'Manager Approve' is hidden or disabled for every role (Manager); any attempt leaves the  |
| TC-STATE-27 | `illegal:APPROVED/Return` | With a record in state 'APPROVED', the control for 'Return' is hidden or disabled for every role (HR Certifier, Manager); any attempt leaves |
| TC-STATE-28 | `illegal:APPROVED/Certify` | With a record in state 'APPROVED', the control for 'Certify' is hidden or disabled for every role (HR Certifier); any attempt leaves the sta |
| TC-STATE-29 | `illegal:APPROVED/Withdraw` | With a record in state 'APPROVED', the control for 'Withdraw' is hidden or disabled for every role (Employee); any attempt leaves the state  |
| TC-STATE-30 | `illegal:POSTED/Submit` | With a record in state 'POSTED', the control for 'Submit' is hidden or disabled for every role (Employee); any attempt leaves the state 'POS |
| TC-STATE-31 | `illegal:POSTED/Manager Approve` | With a record in state 'POSTED', the control for 'Manager Approve' is hidden or disabled for every role (Manager); any attempt leaves the st |
| TC-STATE-32 | `illegal:POSTED/Return` | With a record in state 'POSTED', the control for 'Return' is hidden or disabled for every role (HR Certifier, Manager); any attempt leaves t |
| TC-STATE-33 | `illegal:POSTED/Certify` | With a record in state 'POSTED', the control for 'Certify' is hidden or disabled for every role (HR Certifier); any attempt leaves the state |
| TC-STATE-34 | `illegal:POSTED/Post` | With a record in state 'POSTED', the control for 'Post' is hidden or disabled for every role (Payroll Integration); any attempt leaves the s |
| TC-STATE-35 | `illegal:POSTED/Withdraw` | With a record in state 'POSTED', the control for 'Withdraw' is hidden or disabled for every role (Employee); any attempt leaves the state 'P |
| TC-STATE-36 | `illegal:WITHDRAWN/Submit` | With a record in state 'WITHDRAWN', the control for 'Submit' is hidden or disabled for every role (Employee); any attempt leaves the state ' |
| TC-STATE-37 | `illegal:WITHDRAWN/Manager Approve` | With a record in state 'WITHDRAWN', the control for 'Manager Approve' is hidden or disabled for every role (Manager); any attempt leaves the |
| TC-STATE-38 | `illegal:WITHDRAWN/Return` | With a record in state 'WITHDRAWN', the control for 'Return' is hidden or disabled for every role (HR Certifier, Manager); any attempt leave |
| TC-STATE-39 | `illegal:WITHDRAWN/Certify` | With a record in state 'WITHDRAWN', the control for 'Certify' is hidden or disabled for every role (HR Certifier); any attempt leaves the st |
| TC-STATE-40 | `illegal:WITHDRAWN/Post` | With a record in state 'WITHDRAWN', the control for 'Post' is hidden or disabled for every role (Payroll Integration); any attempt leaves th |
| TC-STATE-41 | `illegal:WITHDRAWN/Withdraw` | With a record in state 'WITHDRAWN', the control for 'Withdraw' is hidden or disabled for every role (Employee); any attempt leaves the state |
| TC-STATE-42 | `role:Employee/Manager Approve` | Signed in as 'Employee' viewing a record in SUBMITTED, no 'Manager Approve' control is rendered (external role — internal controls never app |
| TC-STATE-43 | `role:Employee/Return` | Signed in as 'Employee' viewing a record in MANAGER_APPROVED, SUBMITTED, no 'Return' control is rendered (external role — internal controls  |
| TC-STATE-44 | `role:Employee/Certify` | Signed in as 'Employee' viewing a record in MANAGER_APPROVED, no 'Certify' control is rendered (external role — internal controls never appe |
| TC-STATE-45 | `role:Employee/Post` | Signed in as 'Employee' viewing a record in APPROVED, no 'Post' control is rendered (external role — internal controls never appear on exter |
| TC-STATE-46 | `role:Manager/Create` | Signed in as 'Manager' viewing a record in [*], no 'Create' control is rendered; a direct attempt is rejected with a user-readable message a |
| TC-STATE-47 | `role:Manager/Submit` | Signed in as 'Manager' viewing a record in DRAFT, no 'Submit' control is rendered; a direct attempt is rejected with a user-readable message |
| TC-STATE-48 | `role:Manager/Certify` | Signed in as 'Manager' viewing a record in MANAGER_APPROVED, no 'Certify' control is rendered; a direct attempt is rejected with a user-read |
| TC-STATE-49 | `role:Manager/Post` | Signed in as 'Manager' viewing a record in APPROVED, no 'Post' control is rendered; a direct attempt is rejected with a user-readable messag |
| TC-STATE-50 | `role:Manager/Withdraw` | Signed in as 'Manager' viewing a record in DRAFT, MANAGER_APPROVED, SUBMITTED, no 'Withdraw' control is rendered; a direct attempt is reject |
| TC-STATE-51 | `role:HR Certifier/Create` | Signed in as 'HR Certifier' viewing a record in [*], no 'Create' control is rendered; a direct attempt is rejected with a user-readable mess |
| TC-STATE-52 | `role:HR Certifier/Submit` | Signed in as 'HR Certifier' viewing a record in DRAFT, no 'Submit' control is rendered; a direct attempt is rejected with a user-readable me |
| TC-STATE-53 | `role:HR Certifier/Manager Approve` | Signed in as 'HR Certifier' viewing a record in SUBMITTED, no 'Manager Approve' control is rendered; a direct attempt is rejected with a use |
| TC-STATE-54 | `role:HR Certifier/Post` | Signed in as 'HR Certifier' viewing a record in APPROVED, no 'Post' control is rendered; a direct attempt is rejected with a user-readable m |
| TC-STATE-55 | `role:HR Certifier/Withdraw` | Signed in as 'HR Certifier' viewing a record in DRAFT, MANAGER_APPROVED, SUBMITTED, no 'Withdraw' control is rendered; a direct attempt is r |
| TC-STATE-56 | `role:Payroll Integration/Create` | Signed in as 'Payroll Integration' viewing a record in [*], no 'Create' control is rendered; a direct attempt is rejected with a user-readab |
| TC-STATE-57 | `role:Payroll Integration/Submit` | Signed in as 'Payroll Integration' viewing a record in DRAFT, no 'Submit' control is rendered; a direct attempt is rejected with a user-read |
| TC-STATE-58 | `role:Payroll Integration/Manager Approve` | Signed in as 'Payroll Integration' viewing a record in SUBMITTED, no 'Manager Approve' control is rendered; a direct attempt is rejected wit |
| TC-STATE-59 | `role:Payroll Integration/Return` | Signed in as 'Payroll Integration' viewing a record in MANAGER_APPROVED, SUBMITTED, no 'Return' control is rendered; a direct attempt is rej |
| TC-STATE-60 | `role:Payroll Integration/Certify` | Signed in as 'Payroll Integration' viewing a record in MANAGER_APPROVED, no 'Certify' control is rendered; a direct attempt is rejected with |
| TC-STATE-61 | `role:Payroll Integration/Withdraw` | Signed in as 'Payroll Integration' viewing a record in DRAFT, MANAGER_APPROVED, SUBMITTED, no 'Withdraw' control is rendered; a direct attem |

## 6. Risks, Assumptions & Out of Scope
- `Post` (APPROVED → POSTED) is executed by the system inside approve/certify; tests observe it through the status label, the audit log and the Payroll postings view. `post-btn` is declared only to assert its absence.
- The demo clock is fixed at 2031-03-02 so lead-time boundaries (2031-03-04 vs 2031-03-05) are deterministic; the application uses the real clock without `--demo`.
- NFR-04 (p95 < 300 ms at 500 users) and NFR-05 retention are design obligations verified by review, not by this suite.
- Identity is simulated by the role switcher (pretotype adapter); OIDC token validation is out of scope for Stage 6.
