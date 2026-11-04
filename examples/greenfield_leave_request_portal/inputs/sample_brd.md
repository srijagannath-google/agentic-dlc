# Business Requirements Document — Employee Leave & Exception Request Portal

- **Document type:** BRD (greenfield — no existing system)
- **Version:** 1.0
- **Sponsor:** Human Resources Operations
- **Input scenario expected:** `SCENARIO_REQUIREMENTS_DOC`

## 1. Business Context & Goals
Employees currently request leave by e-mail; managers approve by reply, and HR re-keys outcomes into the
payroll ledger. Errors in entitlement arithmetic and lost approvals are the top two HR complaints. The portal
must let employees submit leave/exception requests, validate entitlements in real time, route approvals by
threshold, and publish approved outcomes to payroll through its existing REST interface.

## 2. Actors / Roles
| Role | Kind | Responsibilities |
| :-- | :-- | :-- |
| Employee | external (self-service) | Create, edit (while Draft), submit, withdraw own requests; view own balance and history |
| Manager | internal | Approve or return requests from direct reports up to the manager threshold |
| HR Certifier | internal | Second-level certification for requests above the manager threshold or of type Exception |
| Payroll Integration (system) | system | Receives approved outcomes |

## 3. Business Rules
| Rule ID | Rule | Inputs | Source |
| :-- | :-- | :-- | :-- |
| BR-01 | Requested hours must not exceed available balance: `available = accrued − taken − pending` | accrued, taken, pending, requested | HR policy §4.1 |
| BR-02 | Requests of **more than 40 hours** or of type **Exception** require HR Certifier approval after Manager approval | requested hours, type | HR policy §4.3 |
| BR-03 | Requests must be submitted **at least 3 calendar days** before the start date, except type Exception | start date, submit date, type | HR policy §4.2 |
| BR-04 | A request whose date range overlaps an existing non-withdrawn, non-rejected request of the same employee is rejected as a duplicate | existing requests | Data-quality standard |
| BR-05 | Withdrawal is allowed only while the request is not yet Approved | state | HR policy §4.5 |

## 4. Workflow (approval path)
1. Employee creates a request → **Draft**.
2. Employee submits → **Submitted** (validation BR-01, BR-03, BR-04 must pass; otherwise stays Draft with a message).
3. Manager reviews → **Manager Approved** or **Returned** (Returned goes back to Draft with a comment).
4. If BR-02 applies, HR Certifier reviews → **Approved** or **Returned**; otherwise Manager approval is final → **Approved**.
5. Approved requests are posted to payroll → **Posted** (system transition; failure keeps the request Approved and raises an alert).
6. Employee may withdraw at any point before Approved → **Withdrawn** (terminal).
7. Rejection is **not** used; "Returned" is the only negative outcome and it is not terminal.

## 5. Functional Requirements
- FR-01 Employee can create/edit a Draft request with: leave type (Vacation, Sick, Exception), start date, end date, hours, reason (optional ≤ 500 chars).
- FR-02 The form shows live `available` balance and the post-request balance as the user types (BR-01).
- FR-03 Submit is blocked with a plain-language, actionable message when BR-01, BR-03 or BR-04 fails (state the amount/days needed).
- FR-04 Manager queue lists Submitted requests from direct reports only, with approve/return actions and a mandatory comment on return.
- FR-05 HR Certifier queue lists Manager-Approved requests that meet BR-02.
- FR-06 Employees see history with human-readable statuses and the next approver.
- FR-07 Approved requests are POSTed to the payroll REST endpoint (`POST /payroll/leave-postings`, JSON) and the result recorded.
- FR-08 Every state change is audit-logged with actor, timestamp, previous and new state.

## 6. Non-Functional Requirements
- NFR-01 Authentication via the organisation's OIDC provider; roles from its group claims.
- NFR-02 Personal data (employee id, national identifier if ever displayed) masked in UI; TLS in transit; encryption at rest.
- NFR-03 WCAG 2.1 AA.
- NFR-04 p95 page interaction < 300 ms with 500 concurrent users.
- NFR-05 Audit log immutable for 7 years.

## 7. Out of Scope
- Payroll calculation itself; accrual engine (balances are read from the HR system of record).
- Mobile native apps.

## 8. Integration Notes
Payroll's REST interface is an **external contract** the portal must call; it is not legacy carry-over. No
other integrations are required.
