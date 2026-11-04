# Test Plan (`test/test_plan.md`)

- **Executable twin:** `test/test_cases.json` (derived by `derive_test_cases.py`, steps completed by `testing-agent`, validated by `validate_test_cases.py`)
- **Derived from:** `backlog/user_stories.json` (sha `<…>`), `specs/application_spec.md` (sha `<…>`), `src/db/schema.sql`, `src/contracts/openapi.yaml`, `specs/input_inventory.json`
- **Environment:** `specs/target_stack.json#commands` (start / healthcheck / uiEntry); browser runtime chain `playwright → chrome-headless → NOT_RUN`

## 1. Objectives & Exit Criteria
Stage 6 PASS = zero `FAIL/ERROR/NOT_RUN` among non-optional tests, zero leakage hits, zero unwired controls, no pending Gate 4 flag.

## 2. Categories
| Category | ID prefix | Derivation source | Runtime | Count |
| :-- | :-- | :-- | :-- | :-: |
| Positive | `TC-POS-*` | ACs tagged `POSITIVE` | browser/http | |
| Negative | `TC-NEG-*` | ACs tagged `NEGATIVE` (validation, RBAC, `BR-NN`) — assert the user-readable reason | browser/http | |
| Edge / Boundary | `TC-EDGE-*` | ACs tagged `EDGE / BOUNDARY`; §3.4 thresholds at value, −1, +1 without submit | browser | |
| UI Leakage | `TC-UI-LEAK-01..04` | `forbiddenUiTokens`: DDL identifiers · state/enum codes · legacy identifiers (legacy only) · PII patterns (spec §2.2) | static | 4 |
| State / Role | `TC-STATE-*` | every illegal (state, trigger) pair and (role, trigger) pair from §3.3/§3.5; external-role visibility | browser (+http) | |
| Interactivity | `TC-UI-INTERACT-*` | every interactive element has a handler and a DOM effect | static + browser | |
| Accessibility | `TC-A11Y-*` | WCAG 2.1 AA (+ standards named in `target_stack.json`) | static | |
| API | `TC-API-*` | one per OpenAPI operation (when a backend exists) | http | |

## 3. `data-testid` Glossary *(contract-first — the coder implements exactly these)*
| Selector | Element | Used by tests |
| :-- | :-- | :-- |

## 4. Traceability
| Story | AC | Test case(s) | Category |
| :-- | :-- | :-- | :-- |

## 5. Role & State Coverage
| State | Trigger | Role | Expected | Test |
| :-- | :-- | :-- | :-- | :-- |

## 6. Risks, Assumptions & Out of Scope
