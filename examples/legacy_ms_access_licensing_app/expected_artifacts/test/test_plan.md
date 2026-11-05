# Test Plan — Business Licensing & Renewal Portal (`test/test_plan.md`)

- **Executable twin:** `test/test_cases.json` (contract-first executable test suite with deterministic browser, HTTP, and static steps)
- **Derived from:** `backlog/user_stories.json` (sha `5081e696a894…`), `specs/application_spec.md` (sha `595174a5493f…`), `src/db/schema.sql`, `src/contracts/openapi.yaml`, `specs/input_inventory.json`
- **Environment:** `specs/target_stack.json#commands` — start `python3 src/backend/server.py`, healthcheck `http://127.0.0.1:8767/health`, uiEntry `http://127.0.0.1:8767/`; browser runtime chain `playwright → chrome-headless → NOT_RUN`; http runtime via `urllib`; static scans over every rendered state reached by the browser tests.
- **Fixtures:** the backend recreates the database and loads the demo data on every start (`APP_DB_RESET=1`), so the suite starts from the same seven-plus-three applications each run (see `src/README.md`). Tests that mutate a seeded record own that record (e.g. APP-2026-000002 is issued by US-FUNC-06/AC-01, 000006 is rejected by US-FUNC-07/AC-01, 000008/000009/000010 are consumed by API and permission tests); tests that need a fresh draft create one through the wizard with a unique tax identifier.

## 1. Objectives & Exit Criteria
Stage 6 PASS = zero `FAIL/ERROR/NOT_RUN` among non-optional tests, zero leakage hits (`forbiddenUiTokens`: 55 schema identifiers, 14 enum codes, 62 legacy identifiers, 2 PII patterns), zero unwired controls, no pending Gate 4 flag. No test is marked optional.

## 2. Categories
| Category | ID prefix | Derivation source | Runtime | Count |
| :-- | :-- | :-- | :-- | :-: |
| Positive | `TC-POS-*` | ACs tagged `POSITIVE` — observable result per role | browser/http/static | 46 |
| Negative | `TC-NEG-*` | ACs tagged `NEGATIVE` (validation VAL-01…12, RBAC §2.1, BR-NN) — assert the user-readable reason | browser/http | 24 |
| Edge | `TC-EDGE-*` | ACs tagged `EDGE / BOUNDARY`; BR-01 / BR-03 thresholds (9,999.99 · 10,000.10 · 2,499.99 · 0.10 · 0.13) asserted live, without submit | browser | 6 |
| UiLeak | `TC-UI-LEAK-01..04` | `forbiddenUiTokens`: DDL identifiers · state/trigger/enum codes · legacy object names + engineering notes · PII regexes from spec §2.2 | static | 4 |
| State | `TC-STATE-*` | ACs tagged role-visibility / prerequisite-gate + every illegal (state, trigger) pair (9) and every (role, trigger) the role does not own (3) from §3.3/§3.5 | browser/http | 21 |
| Interact | `TC-UI-INTERACT-*` | control-wiring audit (every button/tab/select has a handler) + ACs tagged `POSITIVE — INTERACTIVE COMPLETENESS` | browser/static | 7 |
| A11y | `TC-A11Y-*` | labels, single h1, lang, accessible names, tabindex (static + in-browser) | static | 1 |
| Api | `TC-API-*` | one per OpenAPI operation (20) — status code + ViewModel field assertions | http | 20 |
| **Total** | | | | **129** |

## 3. `data-testid` Glossary *(contract-first — the coder implements exactly these; attribute selectors such as `[data-id="2"]` address seeded records)*
| Selector(s) | Element | Used by |
| :-- | :-- | :-- |
| `role-switcher` | header select | simulated sign-in: Commercial Buyer | Licensing Staff |
| `skip-link` | first focusable link | a11y |
| `view-buyer / view-staff` | role views | role visibility |
| `banner` | role=alert region (one per view) | every validation / outcome message |
| `tab-new-application / tab-my-applications / tab-fee-calculator` | buyer tabs (role=tab) | navigation |
| `tab-review-queue / tab-buyers / tab-agents` | staff tabs | navigation |
| `step-1 … step-4, step1-continue-btn, save-draft-btn, step3-continue-btn, submit-application-btn, stepN-back-btn` | wizard steps and their single primary action | US-FUNC-01/02/03/04 |
| `buyer-legal-name, buyer-entity-type, buyer-tax-id-kind, buyer-tax-id, buyer-date-of-birth (+ more-contact-details: buyer-business-name, buyer-email, buyer-phone, buyer-city, buyer-state)` | step 1 inputs | US-FUNC-01 |
| `duplicate-notice` | role=status notice | BR-07 |
| `license-year, prior-year-purchases, bond-amount, bond-surety-name, bond-number, bond-expiry` | step 2 inputs | US-FUNC-02 |
| `required-bond-region / required-bond, bond-check` | live BR-01 output (role=status) | US-FUNC-02 edges |
| `current-application-card, application-number, application-status` | current draft header + status badge | US-FUNC-01/04 |
| `agent-roster, agent-row[data-agent-id], remove-agent-btn[data-agent-id], agent-first-name, agent-last-name, agent-date-of-birth, add-agent-btn, agent-notice` | roster component (buyer step 3 and staff review) | US-FUNC-03 |
| `review-summary` | step 4 summary | US-FUNC-04 |
| `lookup-application-number, lookup-btn, my-applications-list, my-app-row, open-my-app-btn, my-applications-empty` | buyer: find / list applications | US-FUNC-07/09/10 |
| `my-app-detail, my-app-number, my-app-status, my-app-license-number, my-app-decision-reason, my-app-summary, my-app-actions, status-timeline, timeline-item` | buyer application detail + timeline | US-FUNC-07/12 |
| `document-form, document-name, document-type, document-size, add-document-btn, document-list, document-item, documents-empty` | documents | US-FUNC-09 |
| `fee-report-form, fee-quarter, fee-purchase-total, fee-due, record-fee-report-btn, fee-report-list, fee-report-item, fee-reports-empty` | quarterly fee reports (issued licences) | US-FUNC-10 |
| `calc-purchase-total, calc-fee-due` | fee calculator (BR-03 live) | US-FUNC-10 |
| `queue-section, queue-status-filter, queue-table, queue-row[data-id], open-application-btn[data-id], queue-empty` | staff review queue | US-FUNC-05 |
| `review-panel, back-to-queue-btn, review-application-number, review-status, review-license-number, review-decision-reason, review-buyer-name, review-entity-type, review-tax-id, review-date-of-birth, review-buyer-standing, review-prior-purchases, review-required-bond, review-bond-amount, review-bond-check, review-surety, audit-history` | staff review view | US-FUNC-05/06/07 |
| `decision-section, reject-reason, issue-licence-btn, reject-application-btn, print-section, print-certificate-btn, print-agent-cards-btn, no-decision-note` | transition / print controls rendered from (status, role) | US-FUNC-06/07, TC-STATE-* |
| `buyer-search, buyer-search-btn, buyer-results, buyer-result-row[data-id], buyer-standing, toggle-buyer-suspension-btn[data-id], buyer-results-empty` | buyer registry | US-FUNC-08 |
| `agent-search, agent-search-btn, agent-results, agent-result-row[data-id], agent-standing, agent-current-license, toggle-agent-suspension-btn[data-id], agent-results-empty` | agent registry | US-FUNC-08 |

Selector rules: all selectors are `[data-testid=…]` (plus attribute filters and the generic `.btn-primary`, `[role=tab]` for UX-guardrail counts); `setRole` uses `[data-testid=role-switcher]`.

## 4. Traceability (AC → test case)
| Story | AC | Tag | Test case | Runtime |
| :-- | :-- | :-- | :-- | :-- |
| US-FUNC-01 | AC-01 | POSITIVE | TC-POS-01 | browser |
| US-FUNC-01 | AC-02 | NEGATIVE | TC-NEG-01 | browser |
| US-FUNC-01 | AC-03 | NEGATIVE | TC-NEG-02 | browser |
| US-FUNC-01 | AC-04 | POSITIVE | TC-POS-02 | browser |
| US-FUNC-01 | AC-05 | POSITIVE — INTERACTIVE COMPLETENESS | TC-UI-INTERACT-02 | browser |
| US-FUNC-01 | AC-06 | POSITIVE | TC-POS-03 | browser |
| US-FUNC-02 | AC-01 | POSITIVE | TC-POS-04 | browser |
| US-FUNC-02 | AC-02 | EDGE / BOUNDARY | TC-EDGE-01 | browser |
| US-FUNC-02 | AC-03 | EDGE / BOUNDARY | TC-EDGE-02 | browser |
| US-FUNC-02 | AC-04 | EDGE / BOUNDARY | TC-EDGE-03 | browser |
| US-FUNC-02 | AC-05 | POSITIVE | TC-POS-05 | browser |
| US-FUNC-02 | AC-06 | NEGATIVE | TC-NEG-03 | browser |
| US-FUNC-03 | AC-01 | POSITIVE | TC-POS-06 | browser |
| US-FUNC-03 | AC-02 | POSITIVE | TC-POS-07 | browser |
| US-FUNC-03 | AC-03 | NEGATIVE | TC-NEG-04 | browser |
| US-FUNC-03 | AC-04 | NEGATIVE | TC-NEG-05 | browser |
| US-FUNC-03 | AC-05 | NEGATIVE | TC-NEG-06 | browser |
| US-FUNC-03 | AC-06 | POSITIVE | TC-POS-08 | browser |
| US-FUNC-03 | AC-07 | NEGATIVE | TC-NEG-07 | browser |
| US-FUNC-03 | AC-08 | EDGE / BOUNDARY | TC-EDGE-04 | browser |
| US-FUNC-04 | AC-01 | POSITIVE | TC-POS-09 | browser |
| US-FUNC-04 | AC-02 | NEGATIVE | TC-NEG-08 | browser |
| US-FUNC-04 | AC-03 | NEGATIVE | TC-NEG-09 | browser |
| US-FUNC-04 | AC-04 | NEGATIVE — WORKFLOW PREREQUISITE GATE | TC-STATE-01 | browser |
| US-FUNC-04 | AC-05 | POSITIVE — INTERACTIVE COMPLETENESS | TC-UI-INTERACT-03 | browser |
| US-FUNC-05 | AC-01 | POSITIVE | TC-POS-10 | browser |
| US-FUNC-05 | AC-02 | POSITIVE | TC-POS-11 | browser |
| US-FUNC-05 | AC-03 | POSITIVE | TC-POS-12 | browser |
| US-FUNC-05 | AC-04 | NEGATIVE — ROLE VISIBILITY | TC-STATE-02 | browser |
| US-FUNC-05 | AC-05 | POSITIVE — INTERACTIVE COMPLETENESS | TC-UI-INTERACT-04 | browser |
| US-FUNC-05 | AC-06 | POSITIVE | TC-POS-13 | browser |
| US-FUNC-06 | AC-01 | POSITIVE | TC-POS-14 | browser |
| US-FUNC-06 | AC-02 | NEGATIVE | TC-NEG-10 | browser |
| US-FUNC-06 | AC-03 | NEGATIVE — WORKFLOW PREREQUISITE GATE | TC-STATE-03 | browser |
| US-FUNC-06 | AC-04 | POSITIVE | TC-POS-15 | browser |
| US-FUNC-06 | AC-05 | POSITIVE — INTERACTIVE COMPLETENESS | TC-UI-INTERACT-05 | browser |
| US-FUNC-06 | AC-06 | NEGATIVE — WORKFLOW PREREQUISITE GATE | TC-STATE-04 | browser |
| US-FUNC-07 | AC-01 | POSITIVE | TC-POS-16 | browser |
| US-FUNC-07 | AC-02 | NEGATIVE | TC-NEG-11 | browser |
| US-FUNC-07 | AC-03 | POSITIVE | TC-POS-17 | browser |
| US-FUNC-07 | AC-04 | NEGATIVE — WORKFLOW PREREQUISITE GATE | TC-STATE-05 | browser |
| US-FUNC-07 | AC-05 | POSITIVE | TC-POS-18 | browser |
| US-FUNC-08 | AC-01 | POSITIVE | TC-POS-19 | browser |
| US-FUNC-08 | AC-02 | POSITIVE | TC-POS-20 | browser |
| US-FUNC-08 | AC-03 | POSITIVE | TC-POS-21 | browser |
| US-FUNC-08 | AC-04 | POSITIVE | TC-POS-22 | browser |
| US-FUNC-08 | AC-05 | NEGATIVE | TC-NEG-12 | browser |
| US-FUNC-08 | AC-06 | NEGATIVE — ROLE VISIBILITY | TC-STATE-06 | browser |
| US-FUNC-09 | AC-01 | POSITIVE | TC-POS-23 | browser |
| US-FUNC-09 | AC-02 | NEGATIVE | TC-NEG-13 | browser |
| US-FUNC-09 | AC-03 | POSITIVE | TC-POS-24 | browser |
| US-FUNC-09 | AC-04 | POSITIVE — INTERACTIVE COMPLETENESS | TC-UI-INTERACT-06 | browser |
| US-FUNC-10 | AC-01 | POSITIVE | TC-POS-25 | browser |
| US-FUNC-10 | AC-02 | EDGE / BOUNDARY | TC-EDGE-05 | browser |
| US-FUNC-10 | AC-03 | EDGE / BOUNDARY | TC-EDGE-06 | browser |
| US-FUNC-10 | AC-04 | POSITIVE | TC-POS-26 | browser |
| US-FUNC-10 | AC-05 | NEGATIVE | TC-NEG-14 | browser |
| US-FUNC-10 | AC-06 | NEGATIVE — ROLE VISIBILITY | TC-STATE-07 | browser |
| US-TECH-01 | AC-01 | NEGATIVE | TC-NEG-15 | http |
| US-TECH-01 | AC-02 | NEGATIVE — WORKFLOW PREREQUISITE GATE | TC-STATE-08 | http |
| US-TECH-01 | AC-03 | NEGATIVE | TC-NEG-16 | http |
| US-TECH-01 | AC-04 | POSITIVE | TC-POS-27 | http |
| US-TECH-01 | AC-05 | NEGATIVE | TC-NEG-17 | http |
| US-TECH-01 | AC-06 | NEGATIVE — ROLE VISIBILITY | TC-STATE-09 | browser |
| US-TECH-02 | AC-01 | POSITIVE | TC-POS-28 | http |
| US-TECH-02 | AC-02 | POSITIVE | TC-POS-29 | http |
| US-TECH-02 | AC-03 | NEGATIVE | TC-NEG-18 | http |
| US-TECH-02 | AC-04 | POSITIVE | TC-POS-30 | static |
| US-TECH-03 | AC-01 | POSITIVE | TC-POS-31 | http |
| US-TECH-03 | AC-02 | NEGATIVE | TC-NEG-19 | http |
| US-TECH-03 | AC-03 | NEGATIVE | TC-NEG-20 | http |
| US-TECH-03 | AC-04 | NEGATIVE | TC-NEG-21 | http |
| US-TECH-04 | AC-01 | POSITIVE | TC-POS-32 | static |
| US-TECH-04 | AC-02 | POSITIVE | TC-POS-33 | browser |
| US-TECH-04 | AC-03 | POSITIVE | TC-POS-34 | browser |
| US-TECH-04 | AC-04 | POSITIVE | TC-POS-35 | browser |
| US-TECH-04 | AC-05 | POSITIVE | TC-POS-36 | browser |
| US-TECH-05 | AC-01 | POSITIVE — INTERACTIVE COMPLETENESS | TC-UI-INTERACT-07 | static |
| US-TECH-05 | AC-02 | POSITIVE | TC-POS-37 | browser |
| US-TECH-05 | AC-03 | POSITIVE | TC-POS-38 | browser |
| US-TECH-05 | AC-04 | POSITIVE | TC-POS-39 | browser |
| US-TECH-05 | AC-05 | POSITIVE | TC-POS-40 | static |
| US-TECH-06 | AC-01 | POSITIVE | TC-POS-41 | http |
| US-TECH-06 | AC-02 | POSITIVE | TC-POS-42 | http |
| US-TECH-06 | AC-03 | POSITIVE | TC-POS-43 | http |
| US-TECH-06 | AC-04 | NEGATIVE | TC-NEG-22 | http |
| US-TECH-06 | AC-05 | POSITIVE | TC-POS-44 | http |
| US-TECH-07 | AC-01 | POSITIVE | TC-POS-45 | static |
| US-TECH-07 | AC-02 | POSITIVE | TC-POS-46 | http |
| US-TECH-07 | AC-03 | NEGATIVE | TC-NEG-23 | http |
| US-TECH-07 | AC-04 | NEGATIVE | TC-NEG-24 | http |

## 5. Role & State Coverage (synthesised from spec §3.3 / §3.5)
| State | Trigger | Role | Expected | Test |
| :-- | :-- | :-- | :-- | :-- |
| DRAFT | Issue | Licensing Staff | control hidden; status unchanged | TC-STATE-10 |
| DRAFT | Reject | Licensing Staff | control hidden; status unchanged | TC-STATE-11 |
| SUBMITTED | Submit | Commercial Buyer | control hidden; status unchanged | TC-STATE-12 |
| ISSUED | Submit | Commercial Buyer | control hidden; status unchanged | TC-STATE-13 |
| ISSUED | Issue | Licensing Staff | control hidden; status unchanged | TC-STATE-14 |
| ISSUED | Reject | Licensing Staff | control hidden; status unchanged | TC-STATE-15 |
| REJECTED | Submit | Commercial Buyer | control hidden; status unchanged | TC-STATE-16 |
| REJECTED | Issue | Licensing Staff | control hidden; status unchanged | TC-STATE-17 |
| REJECTED | Reject | Licensing Staff | control hidden; status unchanged | TC-STATE-18 |
| SUBMITTED | Issue | Commercial Buyer | control not rendered for this role | TC-STATE-19 |
| SUBMITTED | Reject | Commercial Buyer | control not rendered for this role | TC-STATE-20 |
| DRAFT | Submit | Licensing Staff | control not rendered for this role | TC-STATE-21 |
| DRAFT | Submit | Commercial Buyer | allowed (guards BR-01, BR-02, BR-04) | TC-POS-09, TC-NEG-08, TC-NEG-09 |
| SUBMITTED | Issue | Licensing Staff | allowed (guards: suspension, BR-01, BR-02, BR-06) | TC-POS-14, TC-NEG-10, TC-API-07 |
| SUBMITTED | Reject | Licensing Staff | allowed (reason ≥ 10 chars) | TC-POS-16, TC-NEG-11, TC-POS-27, TC-API-08 |
| any | Issue / Reject over HTTP as Commercial Buyer | Commercial Buyer | 403 + permission message | TC-NEG-15 |
| DRAFT | Issue over HTTP | Licensing Staff | 409 + status label | TC-STATE-08 |

## 6. Risks, Assumptions & Out of Scope
- Browser tests run against the live backend started by the runner; the seeded ids used in selectors (`[data-id="2"]`, `[data-agent-id="13"]`) depend on the deterministic seed order documented in `src/README.md`.
- The http runtime has no negative body assertion, so "no hash field in the response" (US-TECH-02/AC-01) is covered by the positive masked-field assertion plus the static leakage scan; the `x-internal` fields are excluded by the ViewModel layer by construction.
- ASSUMPTION-01…05 (spec header) are tested as written: no return-for-correction, no renewal, suspension as an attribute, only the amount of the bond validated.
- Out of scope for Release 1 tests: notifications, document binary upload (metadata only), the one-time migration ETL (US-TECH-07 is Product Backlog; its ACs verify the absence of legacy routes/names in the running application).
