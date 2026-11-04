# Requirements Traceability Matrix — Business Licensing & Renewal Portal

Maps every requirement in `specs/application_spec.md` to its discovered capability (discovery §6), business rules (§3.4), the user story that implements it (`backlog/user_stories.json`) and the test categories that verify it (`test/test_cases.json`). Legacy artefacts replaced are listed per capability in the discovery blueprint and per story in `backlog/user_stories.md` §0.

## 1. Capability coverage (discovery §6 → REQ-FUNC)
| Capability | Covered by |
| :-- | :-- |
| CAP-01 Buyer registry | REQ-FUNC-10 |
| CAP-02 Licence application capture | REQ-FUNC-01, REQ-FUNC-02, REQ-FUNC-04, REQ-FUNC-11 |
| CAP-03 Review queue & decision | REQ-FUNC-04, REQ-FUNC-05, REQ-FUNC-06, REQ-FUNC-07 |
| CAP-04 Field-agent roster | REQ-FUNC-03, REQ-FUNC-09 |
| CAP-05 Issue licence, certificate & cards | REQ-FUNC-06, REQ-FUNC-08 |
| CAP-06 Agent registry | REQ-FUNC-10 |
| CAP-07 Quarterly volume-fee reporting | REQ-FUNC-13 |
| CAP-08 Status tracking & audit history | REQ-FUNC-09, REQ-FUNC-12 |

Coverage: 8 of 8 capabilities (100 %). No capability was dropped or merged.

## 2. Requirement → rules → story → tests
| Requirement | Capability / source | Business rules | Story | Test categories |
| :-- | :-- | :-- | :-- | :-- |
| REQ-FUNC-01 | CAP-02 | BR-07 | US-FUNC-01 | Positive, Negative, A11y, UiLeak |
| REQ-FUNC-02 | CAP-02 | BR-01 | US-FUNC-02 | Positive, Edge, Negative |
| REQ-FUNC-03 | CAP-04 | BR-02, BR-05, BR-06, BR-07 | US-FUNC-03 | Positive, Negative, Edge |
| REQ-FUNC-04 | CAP-02, CAP-03 | BR-01, BR-04 | US-FUNC-04 | Positive, Negative, State |
| REQ-FUNC-05 | CAP-03 | — | US-FUNC-05 | Positive, State, UiLeak |
| REQ-FUNC-06 | CAP-03, CAP-05 | BR-01, BR-02, BR-06 | US-FUNC-06 | Positive, Negative, State, Api |
| REQ-FUNC-07 | CAP-03 | — | US-FUNC-07 | Positive, Negative, State, Api |
| REQ-FUNC-08 | CAP-05 | — | US-FUNC-06 | Positive, State |
| REQ-FUNC-09 | CAP-04, CAP-08 | BR-02, BR-05, BR-06 | US-FUNC-03 | Positive, Negative, State |
| REQ-FUNC-10 | CAP-01, CAP-06 | BR-06, BR-08 | US-FUNC-08 | Positive, Negative, UiLeak |
| REQ-FUNC-11 | CAP-02 | — | US-FUNC-09 | Positive, Negative |
| REQ-FUNC-12 | CAP-08 | — | US-FUNC-07 | Positive, State |
| REQ-FUNC-13 | CAP-07 | BR-03 | US-FUNC-10 | Positive, Edge, Negative |
| REQ-ENH-01 | discovery §5 #1 | — | US-FUNC-01, US-FUNC-04, US-FUNC-05 | Positive |
| REQ-ENH-02 | discovery §5 #2 | BR-01 | US-FUNC-02 | Positive, Edge |
| REQ-ENH-03 | discovery §5 #3, #5 | BR-02, BR-07 | US-FUNC-03 | Negative, Edge |
| REQ-ENH-04 | discovery §5 #4 | — | US-FUNC-07 | Positive |
| REQ-ENH-05 | discovery §5 #6 | BR-03 | US-FUNC-10 | Positive, Edge |
| REQ-SEC-01 | shared identity service | — | US-TECH-01 | Api, State |
| REQ-SEC-02 | RBAC matrix §2.1 | — | US-TECH-01 | State, Api |
| REQ-SEC-03 | PII inventory §2.2 | — | US-TECH-02 | UiLeak, Positive |
| REQ-SEC-04 | platform | — | US-TECH-02 | Api |
| REQ-SEC-05 | audit events §2.3 | — | US-TECH-03 | Positive, Api |
| REQ-SEC-06 | platform | — | US-TECH-03 | Negative, Api |
| REQ-A11Y-01 | WCAG 1.4.x | — | US-TECH-04 | A11y |
| REQ-A11Y-02 | WCAG 2.1.x, 2.4.x | — | US-TECH-04 | A11y, Interact |
| REQ-A11Y-03 | WCAG 2.4.7 | — | US-TECH-04 | A11y |
| REQ-A11Y-04 | WCAG 1.3.1, 4.1.2 | — | US-TECH-04 | A11y |
| REQ-A11Y-05 | WCAG 4.1.3 | — | US-TECH-04 | A11y |
| REQ-A11Y-06 | WCAG 3.3.x | — | US-TECH-04 | A11y, Negative |
| REQ-UX-01 | §3.3, §3.5 | — | US-TECH-01 | State |
| REQ-UX-02 | `_shared/ux_guardrails.md` | BR-01, BR-03 | US-TECH-05 | Interact, Edge |
| REQ-UX-03 | Gate 1 default design system | — | US-TECH-04 | A11y |
| REQ-UX-04 | `_shared/zero_leak.md` | — | US-TECH-02 | UiLeak |
| REQ-UX-05 | `_shared/ux_guardrails.md` #1, #8, #10 | — | US-TECH-05 | Interact |
| REQ-ARCH-01 | target_stack.json | — | US-TECH-06 | Api |
| REQ-ARCH-02 | layering | BR-01, BR-02, BR-03, BR-04, BR-05, BR-06, BR-07, BR-08 | US-TECH-06 | Api |
| REQ-ARCH-03 | 3NF schema | BR-04, BR-05 | US-TECH-06 | Api |
| REQ-ARCH-04 | OpenAPI 3.1 | — | US-TECH-01 | Api, State |
| REQ-ARCH-05 | ViewModel boundary | — | US-TECH-02 | UiLeak |
| REQ-ARCH-06 | data-testid contract | — | US-TECH-05 | Interact |
| REQ-ARCH-07 | clean migration | — | US-TECH-07 | UiLeak, Api |

## 3. Business rule coverage
| Rule | Requirements | Stories |
| :-- | :-- | :-- |
| BR-01 | REQ-FUNC-02, REQ-FUNC-04, REQ-FUNC-06, REQ-ENH-02 | US-FUNC-02, US-FUNC-04, US-FUNC-06, US-TECH-05, US-TECH-06 |
| BR-02 | REQ-FUNC-03, REQ-FUNC-06, REQ-FUNC-09, REQ-ENH-03 | US-FUNC-03, US-FUNC-06, US-TECH-06 |
| BR-03 | REQ-FUNC-13, REQ-ENH-05 | US-FUNC-10, US-TECH-05, US-TECH-06 |
| BR-04 | REQ-FUNC-04 | US-FUNC-04, US-TECH-06 |
| BR-05 | REQ-FUNC-03, REQ-FUNC-09 | US-FUNC-03, US-TECH-06 |
| BR-06 | REQ-FUNC-03, REQ-FUNC-06, REQ-FUNC-10 | US-FUNC-03, US-FUNC-06, US-FUNC-08, US-TECH-06 |
| BR-07 | REQ-FUNC-01, REQ-FUNC-03, REQ-ENH-03 | US-FUNC-01, US-FUNC-03, US-TECH-06 |
| BR-08 | REQ-FUNC-10 | US-FUNC-08, US-TECH-06 |
