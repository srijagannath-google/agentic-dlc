# Unified User Story Backlog (`backlog/user_stories.md`)

> All functional (`US-FUNC-NN`) and technical (`US-TECH-NN`) stories for the Employee Leave & Exception Request Portal,
> authored from `specs/application_spec.md` after Gate 2 (99/100). Machine twin: `backlog/user_stories.json`.
> Input Scenario `Greenfield Requirements Specification`: every story traces to a documented requirement; no enhancement stories exist.

## 0. Coverage
| Source | Items | Covered by stories | Uncovered |
| :-- | :-: | :-- | :-- |
| `REQ-FUNC-*` | 10 | 10 | none |
| `REQ-ENH-*` *(legacy only)* | 0 | n/a | n/a |
| `REQ-SEC-*`, `REQ-A11Y-*`, `REQ-UX-*`, `REQ-ARCH-*` | 28 | 28 | none |
| §3.3 transitions | 11 | 11 | none |
| §3.4 business rules | 7 | 7 | none |
| Legacy artefacts *(legacy only)* | 0 | n/a | n/a |

Demo identities used in acceptance criteria (seeded by the backend): Employee **Alex Rivera** (manager Morgan Lee; requests LR-1001 Posted, LR-1002 Approved with failed payroll posting, LR-1006 Submitted), Employee **Sam Chen** (40 h available, no requests), Employee Jordan Blake (reports to another manager; LR-1003 Submitted, LR-1004 Manager approved Exception), Manager **Morgan Lee**, HR Certifier **Priya Nair**, system actor **Payroll Integration**. Demo clock: today = 2031-03-02.

---

## `US-FUNC-01` — Create and edit a Draft leave request
- **Status:** `Done`
- **Traceability:** Reqs: REQ-FUNC-01 | Rules: BR-06 | API: `GET /health`, `GET /api/me`, `GET /api/balance`, `GET /api/requests` | DB: `employee`, `leave_balance`, `leave_type`, `leave_request` | Code: `src/backend/repositories.py`, `src/backend/server.py`, `src/backend/test_rules.py`, `src/backend/viewmodel.py`, `src/backend/workflow.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-01` (PASS), `TC-NEG-01` (PASS), `TC-NEG-02` (PASS), `TC-UI-INTERACT-02` (PASS), `TC-EDGE-01` (PASS), `TC-STATE-01` (PASS) | Defects: None
- **Type:** Functional — **Sprint:** `Sprint 1` — **Priority:** Highest — **Points:** 5
- **Narrative:** As an Employee, I want to create a leave or exception request and edit it while it is a Draft, so that I can prepare an accurate request before submitting it.
- **Requirement refs:** `REQ-FUNC-01` — **Business rule refs:** `BR-06` — **Workflow transitions:** `[*]->DRAFT`
- **Roles:** `Employee`
- **Acceptance Criteria**

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | `POSITIVE` | I am signed in as Employee on My requests | I choose New request, enter type Vacation, start 2031-04-14, end 2031-04-15, 8 hours and save the draft | the request detail shows status "Draft" and the hours I entered |
| AC-02 | `NEGATIVE` | I am editing a Draft | I enter a reason of 501 characters and save | saving is refused with "Reason must be 500 characters or fewer; remove 1 characters." and the status stays "Draft" |
| AC-03 | `NEGATIVE` | I am editing a Draft | I enter an end date earlier than the start date and save | saving is refused with "End date must be on or after the start date." |
| AC-04 | `POSITIVE — INTERACTIVE COMPLETENESS` | I am on My requests | I activate New request, then Save draft, then change the hours to 12 and save again | the form opens on New request, the detail appears after the first save and shows 12 h after the second save |
| AC-05 | `EDGE / BOUNDARY` | I am editing a Draft | I enter a reason of exactly 500 characters and save | the draft is saved with status "Draft" and no reason-length message is shown |
| AC-06 | `NEGATIVE — ROLE VISIBILITY` | I am signed in as Manager | the Manager view renders | no New request control is present and no request form is shown |

## `US-FUNC-02` — Live balance and rule indicators while typing
- **Status:** `Done`
- **Traceability:** Reqs: REQ-FUNC-02, REQ-UX-06 | Rules: BR-01, BR-02, BR-03 | API: `GET /health`, `GET /api/me`, `GET /api/balance`, `GET /api/requests` | DB: `employee`, `leave_balance`, `leave_type`, `leave_request` | Code: `src/backend/repositories.py`, `src/backend/server.py`, `src/backend/test_rules.py`, `src/backend/viewmodel.py`, `src/backend/workflow.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-02` (PASS), `TC-EDGE-02` (PASS), `TC-EDGE-03` (PASS), `TC-EDGE-04` (PASS), `TC-POS-03` (PASS), `TC-POS-04` (PASS) | Defects: None
- **Type:** Functional — **Sprint:** `Sprint 1` — **Priority:** Highest — **Points:** 5
- **Narrative:** As an Employee, I want to see my available balance, the post-request balance, the certification need and the earliest allowed start date update as I type, so that I fix problems before submitting.
- **Requirement refs:** `REQ-FUNC-02`, `REQ-UX-06` — **Business rule refs:** `BR-01`, `BR-02`, `BR-03` — **Workflow transitions:** none
- **Roles:** `Employee`
- **Acceptance Criteria**

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | `POSITIVE` | I am Sam Chen (available balance 40 h) and the request form is open | I type 8 hours without submitting | the available balance reads "40 h" and the post-request balance reads "32 h" immediately |
| AC-02 | `EDGE / BOUNDARY` | the form is open for Sam Chen (40 h available) | I type exactly 40 hours | the post-request balance reads "0 h" and no balance warning is shown |
| AC-03 | `EDGE / BOUNDARY` | the form is open for Sam Chen (40 h available) | I type 40.5 hours | an inline message says the requested hours exceed the available balance by 0.5 h, before any submit |
| AC-04 | `EDGE / BOUNDARY` | the form is open for Sam Chen (40 h available) | I type 39.5 hours | the post-request balance reads "0.5 h" |
| AC-05 | `POSITIVE` | the form is open | I set type Vacation with 41 hours, then 40 hours, then type Exception with 8 hours | the certification indicator reads "HR certification required" for 41 h, "Manager approval is final" for 40 h, and "HR certification required" for Exception |
| AC-06 | `POSITIVE` | the form is open and today is 2031-03-02 | I choose type Vacation, then type Exception | the lead-time hint reads "Earliest start date: 2031-03-05" for Vacation and "No lead time required for Exception" for Exception |

## `US-FUNC-03` — Submit a request with balance, lead-time and overlap validation
- **Status:** `Done`
- **Traceability:** Reqs: REQ-FUNC-03, REQ-A11Y-06 | Rules: BR-01, BR-03, BR-04 | API: `GET /health`, `GET /api/me`, `GET /api/balance`, `GET /api/requests` | DB: `employee`, `leave_balance`, `leave_type`, `leave_request` | Code: `src/backend/repositories.py`, `src/backend/server.py`, `src/backend/test_rules.py`, `src/backend/viewmodel.py`, `src/backend/workflow.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-05` (PASS), `TC-NEG-03` (PASS), `TC-NEG-04` (PASS), `TC-NEG-05` (PASS), `TC-EDGE-05` (PASS), `TC-EDGE-06` (PASS), `TC-POS-06` (PASS), `TC-STATE-02` (PASS), `TC-POS-23` (PASS), `TC-POS-24` (PASS), `TC-POS-25` (PASS), `TC-POS-26` (PASS), `TC-UI-INTERACT-07` (PASS) | Defects: None
- **Type:** Functional — **Sprint:** `Sprint 1` — **Priority:** Highest — **Points:** 8
- **Narrative:** As an Employee, I want to submit my Draft and be told exactly what to fix when a rule blocks it, so that my request reaches my manager without back-and-forth.
- **Requirement refs:** `REQ-FUNC-03`, `REQ-A11Y-06` — **Business rule refs:** `BR-01`, `BR-03`, `BR-04` — **Workflow transitions:** `DRAFT->SUBMITTED`
- **Roles:** `Employee`
- **Acceptance Criteria**

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | `POSITIVE` | I have a valid Draft (Vacation, 2031-04-21 to 2031-04-22, 8 h) | I submit it | the status reads "Submitted" and the next approver reads "Manager" |
| AC-02 | `NEGATIVE` | I am Sam Chen with 40 h available and a Draft of 48 h | I submit it | submission is blocked with "Requested hours exceed your available balance by 8 h. Reduce the request to at most 40 h." and the status stays "Draft" |
| AC-03 | `NEGATIVE` | today is 2031-03-02 and my Draft is Vacation starting 2031-03-04 | I submit it | submission is blocked with a message containing "at least 3 calendar days before the start date" and "2031-03-05", and the status stays "Draft" |
| AC-04 | `NEGATIVE` | my request LR-1001 already covers 2031-06-09 to 2031-06-13 | I submit a Draft for 2031-06-12 to 2031-06-16 | submission is blocked with a message containing "overlap your existing request LR-1001" and the status stays "Draft" |
| AC-05 | `EDGE / BOUNDARY` | today is 2031-03-02 | I submit a Vacation Draft starting exactly 2031-03-05 (3 calendar days ahead) | the request is accepted and reads "Submitted" |
| AC-06 | `EDGE / BOUNDARY` | today is 2031-03-02 | I submit an Exception Draft starting 2031-03-04 (2 days ahead) | the request is accepted and reads "Submitted" because Exceptions are exempt from the lead time |
| AC-07 | `POSITIVE` | a submit was blocked by the balance rule | I inspect the form | the validation summary has role alert, the hours field is marked aria-invalid="true" and is described by the message |
| AC-08 | `NEGATIVE — WORKFLOW PREREQUISITE GATE` | my request has just been submitted | I look at the available actions | no Submit control is shown for a Submitted request and the status remains "Submitted" |

## `US-FUNC-04` — Withdraw a request before it is approved
- **Status:** `Done`
- **Traceability:** Reqs: REQ-FUNC-04 | Rules: BR-05 | API: `GET /health`, `GET /api/me`, `GET /api/balance`, `GET /api/requests` | DB: `employee`, `leave_balance`, `leave_type`, `leave_request` | Code: `src/backend/repositories.py`, `src/backend/server.py`, `src/backend/test_rules.py`, `src/backend/viewmodel.py`, `src/backend/workflow.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-07` (PASS), `TC-POS-08` (PASS), `TC-STATE-03` (PASS), `TC-STATE-04` (PASS), `TC-STATE-05` (PASS), `TC-UI-INTERACT-03` (PASS) | Defects: None
- **Type:** Functional — **Sprint:** `Sprint 1` — **Priority:** High — **Points:** 3
- **Narrative:** As an Employee, I want to withdraw my own request while it is still Draft, Submitted or Manager approved, so that I can cancel plans without involving HR.
- **Requirement refs:** `REQ-FUNC-04` — **Business rule refs:** `BR-05` — **Workflow transitions:** `DRAFT->WITHDRAWN`, `SUBMITTED->WITHDRAWN`, `MANAGER_APPROVED->WITHDRAWN`
- **Roles:** `Employee`
- **Acceptance Criteria**

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | `POSITIVE` | I have a Draft | I withdraw it | the status reads "Withdrawn" |
| AC-02 | `POSITIVE` | I have a Submitted request | I withdraw it | the status reads "Withdrawn" and the next approver reads "—" |
| AC-03 | `NEGATIVE — WORKFLOW PREREQUISITE GATE` | my request LR-1002 is Approved (awaiting payroll) | I open it | no Withdraw control is present and the status stays "Approved" |
| AC-04 | `NEGATIVE — WORKFLOW PREREQUISITE GATE` | my request LR-1001 is Posted to payroll | I open it | no Withdraw control is present and the status stays "Posted to payroll" |
| AC-05 | `NEGATIVE — ROLE VISIBILITY` | I am the Manager viewing an employee's Submitted request | the detail renders | no Withdraw control is present |
| AC-06 | `POSITIVE — INTERACTIVE COMPLETENESS` | I have just withdrawn a request | I look at the detail | no Submit or Withdraw control remains and the status region announces "Withdrawn" |

## `US-FUNC-05` — Request history with readable statuses and next approver
- **Status:** `Done`
- **Traceability:** Reqs: REQ-FUNC-05 | Rules: — | API: `GET /health`, `GET /api/me`, `GET /api/balance`, `GET /api/requests` | DB: `employee`, `leave_balance`, `leave_type`, `leave_request` | Code: `src/backend/repositories.py`, `src/backend/server.py`, `src/backend/test_rules.py`, `src/backend/viewmodel.py`, `src/backend/workflow.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-09` (PASS), `TC-POS-10` (PASS), `TC-STATE-06` (PASS), `TC-UI-INTERACT-04` (PASS), `TC-EDGE-07` (PASS) | Defects: None
- **Type:** Functional — **Sprint:** `Sprint 2` — **Priority:** High — **Points:** 3
- **Narrative:** As an Employee, I want a history of my requests with plain-language statuses, the next approver and any return comment, so that I always know where a request stands.
- **Requirement refs:** `REQ-FUNC-05` — **Business rule refs:** none — **Workflow transitions:** none
- **Roles:** `Employee`
- **Acceptance Criteria**

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | `POSITIVE` | I am Alex Rivera | I open My requests | the history lists LR-1001 as "Posted to payroll", LR-1002 as "Approved" with next approver "Payroll" and LR-1006 as "Submitted" with next approver "Manager" |
| AC-02 | `POSITIVE` | my manager returned my request with the comment "Please shorten to two days" | I open My requests | the request reads "Draft" and the return comment "Please shorten to two days" is shown |
| AC-03 | `NEGATIVE — ROLE VISIBILITY` | I am Alex Rivera | I open My requests | requests of other employees (such as LR-1003) are not listed |
| AC-04 | `POSITIVE — INTERACTIVE COMPLETENESS` | I am on My requests | I open LR-1001 from the history | the detail shows LR-1001 with status "Posted to payroll" |
| AC-05 | `EDGE / BOUNDARY` | I browse My requests, the detail and the form | I read every visible text | no raw status code such as MANAGER_APPROVED or POSTED appears anywhere; only labels are shown |

## `US-FUNC-06` — Manager queue with approve and return
- **Status:** `Done`
- **Traceability:** Reqs: REQ-FUNC-06 | Rules: BR-02, BR-07 | API: `GET /health`, `GET /api/me`, `GET /api/balance`, `GET /api/requests` | DB: `employee`, `leave_balance`, `leave_type`, `leave_request` | Code: `src/backend/repositories.py`, `src/backend/server.py`, `src/backend/test_rules.py`, `src/backend/viewmodel.py`, `src/backend/workflow.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-11` (PASS), `TC-POS-12` (PASS), `TC-NEG-06` (PASS), `TC-POS-13` (PASS), `TC-STATE-07` (PASS), `TC-NEG-07` (PASS), `TC-STATE-08` (PASS), `TC-UI-INTERACT-05` (PASS) | Defects: None
- **Type:** Functional — **Sprint:** `Sprint 2` — **Priority:** Highest — **Points:** 8
- **Narrative:** As a Manager, I want a queue of Submitted requests from my direct reports with Approve and Return actions, so that I can decide quickly and route large requests to HR.
- **Requirement refs:** `REQ-FUNC-06` — **Business rule refs:** `BR-02`, `BR-07` — **Workflow transitions:** `SUBMITTED->MANAGER_APPROVED`, `SUBMITTED->APPROVED`, `SUBMITTED->DRAFT`
- **Roles:** `Manager`
- **Acceptance Criteria**

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | `POSITIVE` | LR-1006 (8 h Vacation from my direct report Alex Rivera) is Submitted | I open it from the Manager queue and approve it | manager approval is final: the history shows "Submitted → Approved" and, after the automatic payroll posting, the status reads "Posted to payroll" |
| AC-02 | `POSITIVE` | my direct report submitted a 48 h Vacation request | I approve it | the status reads "Manager approved" and the next approver reads "HR Certifier" |
| AC-03 | `NEGATIVE` | a Submitted request from my direct report is open | I choose Return without a comment | the return is refused with "A comment is required to return a request. Tell the employee what to change." and the status stays "Submitted" |
| AC-04 | `POSITIVE` | a Submitted request from my direct report is open | I return it with the comment "Please shorten to two days" | the status reads "Draft" and the return comment is shown |
| AC-05 | `NEGATIVE — ROLE VISIBILITY` | I am the Employee viewing my own Submitted request | the detail renders | no Approve and no Return control is present |
| AC-06 | `NEGATIVE` | LR-1003 was submitted by Jordan Blake, who reports to another manager | I open the Manager queue | LR-1003 is not listed |
| AC-07 | `NEGATIVE — WORKFLOW PREREQUISITE GATE` | an employee's request is still a Draft | I view it as Manager | no Approve control is present and the status stays "Draft" |
| AC-08 | `POSITIVE — INTERACTIVE COMPLETENESS` | LR-1006 is listed in my queue | I open it and approve it | the detail loads LR-1006 and the queue no longer lists LR-1006 |

## `US-FUNC-07` — HR certification queue with certify and return
- **Status:** `Done`
- **Traceability:** Reqs: REQ-FUNC-07 | Rules: BR-02, BR-07 | API: `GET /health`, `GET /api/me`, `GET /api/balance`, `GET /api/requests` | DB: `employee`, `leave_balance`, `leave_type`, `leave_request` | Code: `src/backend/repositories.py`, `src/backend/server.py`, `src/backend/test_rules.py`, `src/backend/viewmodel.py`, `src/backend/workflow.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-14` (PASS), `TC-POS-15` (PASS), `TC-NEG-08` (PASS), `TC-POS-16` (PASS), `TC-STATE-09` (PASS), `TC-STATE-10` (PASS) | Defects: None
- **Type:** Functional — **Sprint:** `Sprint 2` — **Priority:** Highest — **Points:** 5
- **Narrative:** As an HR Certifier, I want a queue of Manager-approved requests that need certification (more than 40 h or Exception), so that second-level approval happens in one place.
- **Requirement refs:** `REQ-FUNC-07` — **Business rule refs:** `BR-02`, `BR-07` — **Workflow transitions:** `MANAGER_APPROVED->APPROVED`, `MANAGER_APPROVED->DRAFT`
- **Roles:** `HR Certifier`
- **Acceptance Criteria**

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | `POSITIVE` | LR-1004 (Exception, Manager approved) exists | I open the Certification queue | LR-1004 is listed |
| AC-02 | `POSITIVE` | a 48 h request was approved by the manager | I certify it | the history shows "Manager approved → Approved" and the status reads "Posted to payroll" after the automatic payroll posting |
| AC-03 | `NEGATIVE` | a Manager-approved request is open | I choose Return without a comment | the return is refused with "A comment is required to return a request" and the status stays "Manager approved" |
| AC-04 | `POSITIVE` | a Manager-approved request is open | I return it with the comment "Attach the exception form" | the status reads "Draft" and the comment "Attach the exception form" is shown |
| AC-05 | `NEGATIVE — ROLE VISIBILITY` | I am the Manager viewing a Manager-approved request | the detail renders | no Certify control is present |
| AC-06 | `NEGATIVE — WORKFLOW PREREQUISITE GATE` | a request is only Submitted (not yet manager approved) | I view it as HR Certifier | no Certify control is present and the status stays "Submitted" |

## `US-FUNC-08` — Post approved requests to payroll and record the outcome
- **Status:** `Done`
- **Traceability:** Reqs: REQ-FUNC-08, REQ-ARCH-07 | Rules: — | API: `GET /health`, `GET /api/me`, `GET /api/balance`, `GET /api/requests` | DB: `employee`, `leave_balance`, `leave_type`, `leave_request` | Code: `src/backend/repositories.py`, `src/backend/server.py`, `src/backend/test_rules.py`, `src/backend/viewmodel.py`, `src/backend/workflow.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-17` (PASS), `TC-NEG-09` (PASS), `TC-STATE-11` (PASS), `TC-UI-INTERACT-06` (PASS) | Defects: None
- **Type:** Functional — **Sprint:** `Sprint 2` — **Priority:** High — **Points:** 5
- **Narrative:** As the Payroll Integration, I want every Approved request posted to the payroll REST endpoint with the result recorded, so that HR never re-keys outcomes.
- **Requirement refs:** `REQ-FUNC-08`, `REQ-ARCH-07` — **Business rule refs:** none — **Workflow transitions:** `APPROVED->POSTED`
- **Roles:** `Payroll Integration`
- **Acceptance Criteria**

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | `POSITIVE` | a request has just been approved | I open it in the Payroll postings view | the posting outcome reads "Accepted by payroll" with a payroll reference and the status reads "Posted to payroll" |
| AC-02 | `NEGATIVE` | payroll rejected the posting of LR-1002 | I open the Payroll postings view | an alert "Payroll posting failed" is listed for LR-1002 and its status stays "Approved" |
| AC-03 | `NEGATIVE — ROLE VISIBILITY` | I am signed in as Employee | My requests renders | no payroll posting log is shown |
| AC-04 | `POSITIVE — INTERACTIVE COMPLETENESS` | LR-1001 was posted successfully | I open LR-1001 from the posting log | the detail shows status "Posted to payroll" and the posting outcome "Accepted by payroll" |

## `US-FUNC-09` — Immutable audit trail of every state change
- **Status:** `Done`
- **Traceability:** Reqs: REQ-FUNC-09, REQ-SEC-05 | Rules: — | API: `POST /api/requests/LR-1001/certify`, `GET /api/requests/LR-1001/audit`, `PUT /api/requests/LR-1001/audit`, `DELETE /api/requests/LR-1001/audit` | DB: `employee`, `leave_balance`, `leave_type`, `leave_request` | Code: `src/backend/repositories.py`, `src/backend/server.py`, `src/backend/test_rules.py`, `src/backend/viewmodel.py`, `src/backend/workflow.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-18` (PASS), `TC-POS-19` (PASS), `TC-NEG-10` (PASS), `TC-EDGE-08` (PASS) | Defects: None
- **Type:** Functional — **Sprint:** `Sprint 2` — **Priority:** High — **Points:** 3
- **Narrative:** As a Manager or HR Certifier, I want every state change recorded with actor, time, previous and new state, so that lost approvals can be traced.
- **Requirement refs:** `REQ-FUNC-09`, `REQ-SEC-05` — **Business rule refs:** none — **Workflow transitions:** none
- **Roles:** `Manager`, `HR Certifier`
- **Acceptance Criteria**

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | `POSITIVE` | Alex Rivera submitted a request | I open it as Manager | the audit log lists "Draft → Submitted" by Alex Rivera with a timestamp |
| AC-02 | `POSITIVE` | I approved an 8 h request | I read the audit log | it lists "Submitted → Approved" by Morgan Lee and "Approved → Posted to payroll" by Payroll Integration |
| AC-03 | `NEGATIVE` | LR-1001 is Posted to payroll | the HR Certifier tries to certify it through the API | the attempt is refused and the audit log records a denied attempt for LR-1001 |
| AC-04 | `EDGE / BOUNDARY` | an audit record exists | a client tries to update or delete it through the API | the API answers 405 and the record is unchanged |

## `US-TECH-01` — Server-side workflow and role guards
- **Status:** `Done`
- **Traceability:** Reqs: REQ-FUNC-10, REQ-SEC-02, REQ-UX-04, REQ-UX-05 | Rules: BR-05 | API: `POST /api/requests/LR-1001/submit`, `GET /api/requests/LR-1001`, `POST /api/requests/LR-1006/approve`, `POST /api/requests/LR-1003/approve` | DB: `employee`, `leave_balance`, `leave_type`, `leave_request` | Code: `src/backend/repositories.py`, `src/backend/server.py`, `src/backend/test_rules.py`, `src/backend/viewmodel.py`, `src/backend/workflow.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-STATE-12` (PASS), `TC-STATE-13` (PASS), `TC-NEG-11` (PASS), `TC-STATE-14` (PASS), `TC-POS-20` (PASS) | Defects: None
- **Type:** Technical — **Sprint:** `Sprint 1` — **Priority:** Highest — **Points:** 5
- **Narrative:** As the system, I want every transition validated against the frozen state table and RBAC matrix in the backend, so that the UI is never the only guard.
- **Requirement refs:** `REQ-FUNC-10`, `REQ-SEC-02`, `REQ-UX-04`, `REQ-UX-05` — **Business rule refs:** `BR-05` — **Workflow transitions:** `DRAFT->SUBMITTED`, `SUBMITTED->MANAGER_APPROVED`, `SUBMITTED->APPROVED`, `SUBMITTED->DRAFT`, `MANAGER_APPROVED->APPROVED`, `MANAGER_APPROVED->DRAFT`, `APPROVED->POSTED`, `DRAFT->WITHDRAWN`, `SUBMITTED->WITHDRAWN`, `MANAGER_APPROVED->WITHDRAWN`
- **Roles:** `Employee`, `Manager`, `HR Certifier`, `Payroll Integration`
- **Acceptance Criteria**

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | `NEGATIVE — WORKFLOW PREREQUISITE GATE` | LR-1001 is Posted to payroll | the Employee calls the submit operation | the API answers 409 with a message containing "not available for a request that is Posted to payroll" and the status is unchanged |
| AC-02 | `NEGATIVE — ROLE VISIBILITY` | LR-1006 is Submitted | the Employee calls the approve operation | the API answers 403 with "Only the employee's manager can approve or return this request." |
| AC-03 | `NEGATIVE` | LR-1003 belongs to an employee who does not report to Morgan Lee | Morgan Lee calls the approve operation | the API answers 403 and LR-1003 stays Submitted |
| AC-04 | `NEGATIVE — WORKFLOW PREREQUISITE GATE` | LR-1002 is Approved | the Employee calls the withdraw operation | the API answers 409 and the status stays Approved |
| AC-05 | `POSITIVE` | I am the Employee with a Draft open | I look at the available actions | exactly the Submit and Withdraw controls are present; Approve, Return and Certify are absent |

## `US-TECH-02` — Identity adapter, PII masking and input hardening
- **Status:** `Done`
- **Traceability:** Reqs: REQ-SEC-01, REQ-SEC-03, REQ-SEC-04, REQ-SEC-06, REQ-ARCH-08 | Rules: BR-06 | API: `GET /api/balance`, `POST /api/requests`, `GET /api/requests/LR-1006` | DB: `employee`, `leave_balance`, `leave_type`, `leave_request` | Code: `src/backend/repositories.py`, `src/backend/server.py`, `src/backend/test_rules.py`, `src/backend/viewmodel.py`, `src/backend/workflow.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-21` (PASS), `TC-NEG-12` (PASS), `TC-NEG-13` (PASS), `TC-POS-22` (PASS), `TC-EDGE-09` (PASS) | Defects: None
- **Type:** Technical — **Sprint:** `Sprint 1` — **Priority:** High — **Points:** 5
- **Narrative:** As the platform, I want identity resolved through one adapter, PII masked at the presentation boundary and every payload validated server-side, so that security requirements hold in the pretotype and in production.
- **Requirement refs:** `REQ-SEC-01`, `REQ-SEC-03`, `REQ-SEC-04`, `REQ-SEC-06`, `REQ-ARCH-08` — **Business rule refs:** `BR-06` — **Workflow transitions:** none
- **Roles:** `Employee`, `Manager`
- **Acceptance Criteria**

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | `POSITIVE` | I am the Manager viewing LR-1006 | I read the employee details | the employee identifier is masked as "EMP-•••42" and the full identifier is nowhere on the page |
| AC-02 | `NEGATIVE` | a client sends no identity | it calls the balance operation | the API answers 401 with a readable message |
| AC-03 | `NEGATIVE` | the Employee creates a request | the hours field contains "abc" | the API answers 400 with "Enter the requested hours (more than 0)." |
| AC-04 | `POSITIVE` | the Manager reads LR-1006 through the API | the response arrives | it carries the masked employee reference and no national identifier field |
| AC-05 | `EDGE / BOUNDARY` | the Employee creates a request through the API | the reason has 500 characters, then 501 characters | 500 is accepted (201) and 501 is refused (400) with the 500-character message |

## `US-TECH-03` — Accessibility baseline (WCAG 2.1 AA)
- **Status:** `Done`
- **Traceability:** Reqs: REQ-A11Y-01, REQ-A11Y-02, REQ-A11Y-03, REQ-A11Y-04, REQ-A11Y-05, REQ-A11Y-06 | Rules: — | API: `GET /health`, `GET /api/me`, `GET /api/balance`, `GET /api/requests` | DB: `employee`, `leave_balance`, `leave_type`, `leave_request` | Code: `src/backend/repositories.py`, `src/backend/server.py`, `src/backend/test_rules.py`, `src/backend/viewmodel.py`, `src/backend/workflow.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-23` (PASS), `TC-POS-24` (PASS), `TC-POS-25` (PASS), `TC-POS-26` (PASS), `TC-UI-INTERACT-07` (PASS), `TC-POS-05` (PASS), `TC-NEG-03` (PASS), `TC-NEG-04` (PASS), `TC-NEG-05` (PASS), `TC-EDGE-05` (PASS), `TC-EDGE-06` (PASS), `TC-POS-06` (PASS), `TC-STATE-02` (PASS) | Defects: None
- **Type:** Technical — **Sprint:** `Sprint 1` — **Priority:** High — **Points:** 3
- **Narrative:** As a keyboard or screen-reader user, I want labelled controls, live regions, visible focus and a skip link, so that I can complete every journey.
- **Requirement refs:** `REQ-A11Y-01`, `REQ-A11Y-02`, `REQ-A11Y-03`, `REQ-A11Y-04`, `REQ-A11Y-05`, `REQ-A11Y-06` — **Business rule refs:** none — **Workflow transitions:** none
- **Roles:** `Employee`
- **Acceptance Criteria**

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | `POSITIVE` | the portal loads | I inspect the first focusable element | it is a "Skip to main content" link pointing at the main landmark |
| AC-02 | `POSITIVE` | the request form is open | I inspect the balance panel | it is an aria-live="polite" region |
| AC-03 | `POSITIVE` | a submit was blocked | I inspect the page | the validation summary has role="alert" and the hours field has aria-invalid="true" |
| AC-04 | `POSITIVE` | I submit a valid request | the status changes | the role="status" region announces "Request submitted" |
| AC-05 | `POSITIVE — INTERACTIVE COMPLETENESS` | focus is on New request | I press Enter | the request form opens, proving keyboard operability of the control |

## `US-TECH-04` — UX guardrails and zero internal-data leakage
- **Status:** `Done`
- **Traceability:** Reqs: REQ-UX-01, REQ-UX-02, REQ-UX-03, REQ-UX-07, REQ-ARCH-05, REQ-ARCH-06 | Rules: — | API: `GET /health`, `GET /api/me`, `GET /api/balance`, `GET /api/requests` | DB: `employee`, `leave_balance`, `leave_type`, `leave_request` | Code: `src/backend/repositories.py`, `src/backend/server.py`, `src/backend/test_rules.py`, `src/backend/viewmodel.py`, `src/backend/workflow.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-27` (PASS), `TC-POS-28` (PASS), `TC-POS-29` (PASS), `TC-NEG-14` (PASS), `TC-UI-INTERACT-08` (PASS), `TC-UI-INTERACT-TAB-01` (NOT_RUN), `TC-UI-INTERACT-TAB-02` (NOT_RUN), `TC-POS-JOURNEY-01` (NOT_RUN) | Defects: None
- **Type:** Technical — **Sprint:** `Sprint 2` — **Priority:** High — **Points:** 3
- **Narrative:** As a product owner, I want the ten UX guardrails applied and no internal codes or identifiers in visible text, so that the portal is simple and safe for all roles.
- **Requirement refs:** `REQ-UX-01`, `REQ-UX-02`, `REQ-UX-03`, `REQ-UX-07`, `REQ-ARCH-05`, `REQ-ARCH-06` — **Business rule refs:** none — **Workflow transitions:** none
- **Roles:** `Employee`, `Manager`, `HR Certifier`, `Payroll Integration`
- **Acceptance Criteria**

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | `POSITIVE` | the request form is open | I count high-emphasis buttons | exactly one primary button is visible |
| AC-02 | `POSITIVE` | the request form is open | I count fields outside progressive disclosure | exactly 4 visible fields (type, start, end, hours) are shown; the reason sits inside a details element |
| AC-03 | `POSITIVE` | the portal loads | I inspect the body element | data-design-references equals "default-ux-guardrails" |
| AC-04 | `NEGATIVE` | I visit the Employee, Manager, HR Certifier and Payroll Integration views | I read all visible text | no raw code (DRAFT, SUBMITTED, MANAGER_APPROVED, APPROVED, POSTED, WITHDRAWN) and no API path is visible |
| AC-05 | `POSITIVE — INTERACTIVE COMPLETENESS` | I am on the portal | I switch the role to Manager, then HR Certifier, then Payroll Integration | the view heading changes to "Manager queue", "Certification queue" and "Payroll postings" respectively |

## `US-TECH-05` — Runnable zero-dependency stack and API contract
- **Status:** `Done`
- **Traceability:** Reqs: REQ-ARCH-01, REQ-ARCH-02, REQ-ARCH-03, REQ-ARCH-04, REQ-ARCH-09 | Rules: — | API: `GET /health`, `GET /`, `GET /api/requests/LR-1001`, `GET /api/requests/LR-9999` | DB: `employee`, `leave_balance`, `leave_type`, `leave_request` | Code: `src/backend/repositories.py`, `src/backend/server.py`, `src/backend/test_rules.py`, `src/backend/viewmodel.py`, `src/backend/workflow.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-30` (PASS), `TC-POS-31` (PASS), `TC-POS-32` (PASS), `TC-NEG-15` (PASS), `TC-POS-33` (PASS) | Defects: None
- **Type:** Technical — **Sprint:** `Sprint 1` — **Priority:** High — **Points:** 3
- **Narrative:** As an engineer, I want the application to start with one command, answer a healthcheck and honour the OpenAPI error contract, so that Stage 6 can verify it end to end.
- **Requirement refs:** `REQ-ARCH-01`, `REQ-ARCH-02`, `REQ-ARCH-03`, `REQ-ARCH-04`, `REQ-ARCH-09` — **Business rule refs:** none — **Workflow transitions:** none
- **Roles:** `Employee`, `Manager`
- **Acceptance Criteria**

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | `POSITIVE` | the server was started with the start command | I call the healthcheck | it answers 200 with status "ok" and database "ready" |
| AC-02 | `POSITIVE` | the server is running | I request the root URL | it serves the single-page UI as HTML |
| AC-03 | `POSITIVE` | LR-1001 exists | the Manager reads it through the API | the response carries statusLabel "Posted to payroll" |
| AC-04 | `NEGATIVE` | no request LR-9999 exists | the Manager reads it through the API | the API answers 404 with a readable message |
| AC-05 | `POSITIVE` | LR-1001 is Posted to payroll | the Employee calls submit on it | the error body carries both a code and a user-readable message |
