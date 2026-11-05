# Requirements Traceability Matrix — Employee Leave & Exception Request Portal

Input Scenario: `Greenfield Requirements Specification` — every requirement traces to a paragraph of the input BRD (v1.0) and to a
discovery capability; nothing outside the document is specified.

## 1 Capability coverage (discovery §6 → REQ)
| Capability | Covered by | Complete |
| :-- | :-- | :-: |
| CAP-01 Create / edit Draft | REQ-FUNC-01 | ✓ |
| CAP-02 Live balance | REQ-FUNC-02, REQ-UX-06 | ✓ |
| CAP-03 Submit with validation | REQ-FUNC-03, REQ-A11Y-06 | ✓ |
| CAP-04 Withdraw | REQ-FUNC-04 | ✓ |
| CAP-05 History with statuses and next approver | REQ-FUNC-05 | ✓ |
| CAP-06 Manager queue, approve / return | REQ-FUNC-06, REQ-FUNC-10 | ✓ |
| CAP-07 HR Certifier queue, certify / return | REQ-FUNC-07, REQ-FUNC-10 | ✓ |
| CAP-08 Payroll posting | REQ-FUNC-08, REQ-ARCH-07 | ✓ |
| CAP-09 Audit log | REQ-FUNC-09, REQ-SEC-05 | ✓ |
| CAP-10 OIDC, PII, encryption | REQ-SEC-01, REQ-SEC-03, REQ-SEC-04, REQ-ARCH-08 | ✓ |
| CAP-11 Accessible, responsive UI | REQ-A11Y-01 … REQ-A11Y-06, REQ-UX-01 | ✓ |

Coverage: 11 / 11 capabilities (100 %).

## 2 Requirement → source → rules → story → test category
| REQ ID | Source (BRD paragraph) | Capability | Business rules | Planned story | Test categories |
| :-- | :-- | :-- | :-- | :-- | :-- |
| REQ-FUNC-01 | FR-01; §4 step 1 | CAP-01 | BR-06 | US-FUNC-01 | Positive, Negative, Edge, Interact |
| REQ-FUNC-02 | FR-02 | CAP-02 | BR-01 | US-FUNC-02 | Positive, Edge |
| REQ-FUNC-03 | FR-03; §4 step 2 | CAP-03 | BR-01, BR-03, BR-04 | US-FUNC-03 | Positive, Negative, Edge, Api |
| REQ-FUNC-04 | §4 step 6; BR-05 | CAP-04 | BR-05 | US-FUNC-04 | Positive, State, Api |
| REQ-FUNC-05 | FR-06 | CAP-05 | — | US-FUNC-05 | Positive, UiLeak |
| REQ-FUNC-06 | FR-04; §4 steps 3–4 | CAP-06 | BR-02, BR-07 | US-FUNC-06 | Positive, Negative, State, Api |
| REQ-FUNC-07 | FR-05; §4 step 4 | CAP-07 | BR-02, BR-07 | US-FUNC-07 | Positive, Negative, State, Api |
| REQ-FUNC-08 | FR-07; §4 step 5; §8 | CAP-08 | — | US-FUNC-08 | Positive, Negative, Api |
| REQ-FUNC-09 | FR-08; NFR-05 | CAP-09 | — | US-FUNC-09 | Positive, Api |
| REQ-FUNC-10 | §4 (all steps) | CAP-04, CAP-06, CAP-07 | BR-05 | US-TECH-01 | State, Api |
| REQ-SEC-01 | NFR-01 | CAP-10 | — | US-TECH-02 | Positive |
| REQ-SEC-02 | NFR-01; §2 roles | CAP-06, CAP-07 | — | US-TECH-01 | State, Api |
| REQ-SEC-03 | NFR-02 | CAP-10 | — | US-TECH-02 | UiLeak |
| REQ-SEC-04 | NFR-02 | CAP-10 | — | US-TECH-02 | Static review |
| REQ-SEC-05 | FR-08; NFR-05 | CAP-09 | — | US-FUNC-09 | Positive, Api |
| REQ-SEC-06 | NFR-02 | CAP-03 | BR-06 | US-TECH-02 | Negative, Api |
| REQ-A11Y-01 | NFR-03 | CAP-11 | — | US-TECH-03 | A11y |
| REQ-A11Y-02 | NFR-03 | CAP-11 | — | US-TECH-03 | A11y, Interact |
| REQ-A11Y-03 | NFR-03 | CAP-11 | — | US-TECH-03 | A11y |
| REQ-A11Y-04 | NFR-03 | CAP-11 | — | US-TECH-03 | A11y |
| REQ-A11Y-05 | NFR-03 | CAP-11, CAP-02 | — | US-TECH-03 | A11y |
| REQ-A11Y-06 | NFR-03; FR-03 | CAP-03 | — | US-TECH-03 | A11y, Negative |
| REQ-UX-01 | NFR-03; HR complaints §1 | CAP-11 | — | US-TECH-04 | Interact, A11y |
| REQ-UX-02 | Gate 1 (autonomous) | CAP-11 | — | US-TECH-04 | Static review |
| REQ-UX-03 | NFR-02; Zero-Leak Boundary | CAP-05, CAP-11 | — | US-TECH-04 | UiLeak |
| REQ-UX-04 | §2 roles | CAP-06, CAP-07 | — | US-TECH-01 | State |
| REQ-UX-05 | §4 workflow | CAP-04, CAP-06, CAP-07 | BR-05 | US-TECH-01 | State |
| REQ-UX-06 | FR-02; FR-03 | CAP-02, CAP-03 | BR-01, BR-02, BR-03 | US-FUNC-02 | Edge |
| REQ-UX-07 | §1 goals | CAP-11 | — | US-TECH-04 | Interact |
| REQ-ARCH-01 | Gate 1 stack | CAP-11 | — | US-TECH-05 | Api (health) |
| REQ-ARCH-02 | §4 workflow | CAP-06, CAP-07 | BR-01 … BR-07 | US-TECH-05 | State, Api |
| REQ-ARCH-03 | §1 (entitlement arithmetic errors) | CAP-09 | — | US-TECH-05 | Static review |
| REQ-ARCH-04 | FR-07; §4 | CAP-06, CAP-07, CAP-08 | — | US-TECH-05 | Api |
| REQ-ARCH-05 | NFR-02 | CAP-05 | — | US-TECH-04 | UiLeak |
| REQ-ARCH-06 | NFR-03 (testable UI) | CAP-11 | — | US-TECH-04 | Interact |
| REQ-ARCH-07 | FR-07; §8 | CAP-08 | — | US-FUNC-08 | Api |
| REQ-ARCH-08 | NFR-01 | CAP-10 | — | US-TECH-02 | Api |
| REQ-ARCH-09 | NFR-04; Gate 1 | CAP-11 | — | US-TECH-05 | Api (health) |

## 3 Business rule → requirement
| Rule | Requirements |
| :-- | :-- |
| BR-01 | REQ-FUNC-02, REQ-FUNC-03, REQ-UX-06 |
| BR-02 | REQ-FUNC-06, REQ-FUNC-07, REQ-UX-06 |
| BR-03 | REQ-FUNC-03, REQ-UX-06 |
| BR-04 | REQ-FUNC-03 |
| BR-05 | REQ-FUNC-04, REQ-FUNC-10 |
| BR-06 | REQ-FUNC-01, REQ-SEC-06 |
| BR-07 | REQ-FUNC-06, REQ-FUNC-07 |
