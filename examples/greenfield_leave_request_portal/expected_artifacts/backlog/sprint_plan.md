# Sprint Alignment Plan (`backlog/sprint_plan.md`)

- **SPRINT_ALIGNMENT_APPROVAL:** `PRE_APPROVED_BY_USER`
- **ALM platform:** `none` (from `specs/target_stack.json`) — **Board / project:** `backlog/jira_import.csv` (offline CSV only)
- **Release 1 goal:** the employee journey end to end — create → validate live → submit → manager decision → HR certification → payroll posting → terminal state — with server-side guards, PII masking, accessibility and a zero-leakage UI.

## Sprint 1 — Request intake & guards
| Story | Title | Points | Requirement refs | Workflow transitions |
| :-- | :-- | :-: | :-- | :-- |
| US-FUNC-01 | Create and edit a Draft leave request | 5 | REQ-FUNC-01 | [*]->DRAFT |
| US-FUNC-02 | Live balance and rule indicators while typing | 5 | REQ-FUNC-02, REQ-UX-06 | — |
| US-FUNC-03 | Submit a request with balance, lead-time and overlap validation | 8 | REQ-FUNC-03, REQ-A11Y-06 | DRAFT->SUBMITTED |
| US-FUNC-04 | Withdraw a request before it is approved | 3 | REQ-FUNC-04 | DRAFT->WITHDRAWN, SUBMITTED->WITHDRAWN, MANAGER_APPROVED->WITHDRAWN |
| US-TECH-01 | Server-side workflow and role guards | 5 | REQ-FUNC-10, REQ-SEC-02, REQ-UX-04, REQ-UX-05 | DRAFT->SUBMITTED, SUBMITTED->MANAGER_APPROVED, SUBMITTED->APPROVED, SUBMITTED->DRAFT, MANAGER_APPROVED->APPROVED, MANAGER_APPROVED->DRAFT, APPROVED->POSTED, DRAFT->WITHDRAWN, SUBMITTED->WITHDRAWN, MANAGER_APPROVED->WITHDRAWN |
| US-TECH-02 | Identity adapter, PII masking and input hardening | 5 | REQ-SEC-01, REQ-SEC-03, REQ-SEC-04, REQ-SEC-06, REQ-ARCH-08 | — |
| US-TECH-03 | Accessibility baseline (WCAG 2.1 AA) | 3 | REQ-A11Y-01, REQ-A11Y-02, REQ-A11Y-03, REQ-A11Y-04, REQ-A11Y-05, REQ-A11Y-06 | — |
| US-TECH-05 | Runnable zero-dependency stack and API contract | 3 | REQ-ARCH-01, REQ-ARCH-02, REQ-ARCH-03, REQ-ARCH-04, REQ-ARCH-09 | — |

Sprint goal: an Employee can create, see live balances, submit (with all three validations) and withdraw; the backend enforces the whole §3.3 table; identity, masking, accessibility baseline and the runnable stack are in place.

## Sprint 2 — Approvals, payroll & history
| Story | Title | Points | Requirement refs | Workflow transitions |
| :-- | :-- | :-: | :-- | :-- |
| US-FUNC-05 | Request history with readable statuses and next approver | 3 | REQ-FUNC-05 | — |
| US-FUNC-06 | Manager queue with approve and return | 8 | REQ-FUNC-06 | SUBMITTED->MANAGER_APPROVED, SUBMITTED->APPROVED, SUBMITTED->DRAFT |
| US-FUNC-07 | HR certification queue with certify and return | 5 | REQ-FUNC-07 | MANAGER_APPROVED->APPROVED, MANAGER_APPROVED->DRAFT |
| US-FUNC-08 | Post approved requests to payroll and record the outcome | 5 | REQ-FUNC-08, REQ-ARCH-07 | APPROVED->POSTED |
| US-FUNC-09 | Immutable audit trail of every state change | 3 | REQ-FUNC-09, REQ-SEC-05 | — |
| US-TECH-04 | UX guardrails and zero internal-data leakage | 3 | REQ-UX-01, REQ-UX-02, REQ-UX-03, REQ-UX-07, REQ-ARCH-05, REQ-ARCH-06 | — |

Sprint goal: Manager and HR Certifier queues with approve / return / certify, automatic payroll posting with alerts, the employee history, the audit log and the UX / zero-leakage checks across all four views.

## Product Backlog (Release 2 / deferrable)
| Story | Title | Points | Why deferred |
| :-- | :-- | :-: | :-- |
| — | none | — | The BRD scope (FR-01…FR-08, NFR-01…NFR-05) is fully delivered in Release 1; no deferrable reports or exports were requested. |

## Retired / Not Carried Forward *(Legacy Application Modernization only)*
Not applicable — greenfield requirements document.

## Totals
| Tier | Stories | Points |
| :-- | :-: | :-: |
| Sprint 1 | 8 | 37 |
| Sprint 2 | 6 | 27 |
| Product Backlog | 0 | 0 |
| **Total** | **14** | **64** |
