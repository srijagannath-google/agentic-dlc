# Unified User Stories — Business Licensing & Renewal Portal

All functional (`US-FUNC-*`) and technical (`US-TECH-*`) stories in one backlog, derived from `specs/application_spec.md` (§3.3 transitions, §3.4 rules, §3.5 roles) and `specs/discovery_architecture_and_inventory.md`. Machine twin: `backlog/user_stories.json`.

## 0. Coverage

- Requirements covered: 42 (`REQ-FUNC-01…13`, `REQ-ENH-01…05`, `REQ-SEC-01…06`, `REQ-A11Y-01…06`, `REQ-UX-01…05`, `REQ-ARCH-01…07`) — 100 % of the spec.
- §3.3 transitions covered: `DRAFT->SUBMITTED` (US-FUNC-04, US-TECH-01), `SUBMITTED->ISSUED` (US-FUNC-06, US-TECH-01), `SUBMITTED->REJECTED` (US-FUNC-07, US-TECH-01).
- Business rules covered: BR-01…BR-08 (see `businessRuleRefs`).
- Roles covered: Commercial Buyer (external), Licensing Staff (internal).

| Legacy artefact | Replaced by story |
| :-- | :-- |
| Form_frmBusinessLicenseApplicantSelection.txt (applicant capture) | US-FUNC-01 |
| applicant-information form (referenced) | US-FUNC-01 |
| Form_frmBusinessLicenseApplication.txt (bond fields) | US-FUNC-02 |
| Form_frmBusinessLicenseApplication.txt (cmdAddAgent/cmdAssignAgent/cmdRemoveAgent/cmdDeleteAgent handlers) | US-FUNC-03 |
| Form_frmBusinessLicenseNewApplicationDetail.txt (same handlers + removal letter) | US-FUNC-03 |
| licence-agent bridge and assignment-history tables | US-FUNC-03 |
| Form_frmBusinessLicenseApplicantSelection.txt (cmdLicense_Click year check) | US-FUNC-04 |
| legacy web-application submission | US-FUNC-04 |
| Form_frmBusinessLicenseNewApplications.txt | US-FUNC-05 |
| Form_frmBusinessLicenseNewApplicationDetail.txt | US-FUNC-05 |
| Form_frmBusinessLicenseApplicantSelection.txt (search/list) | US-FUNC-05 |
| Form_frmBusinessLicenseApplication.txt (cmdPreviewReport, cmdAgentCardsSingle) | US-FUNC-06 |
| Report_rptBusinessLicenseAgentCardLabels.txt | US-FUNC-06 |
| card-printed update query | US-FUNC-06 |
| Form_frmBusinessLicenseNewApplications.txt (Command163_Click hard delete) | US-FUNC-07 |
| agent assignment history table | US-FUNC-07 |
| Form_frmBusinessLicenseApplicantSelection.txt (search handlers, cmdDeleteApplicant_Click) | US-FUNC-08 |
| Form_frmBusinessLicenseApplication.txt (cmdSearch/cmdReset/cmdDeleteAgent) | US-FUNC-08 |
| agent-information form (referenced) | US-FUNC-08 |
| tblBusinessLicenseFiles.xsd | US-FUNC-09 |
| qryBusinessLicenseFiles.sql | US-FUNC-09 |
| uploaded-files sub-form (referenced) | US-FUNC-09 |
| volume-fee form family (overview document) | US-FUNC-10 |
| plain-text SSN/FEIN columns and search keys | US-TECH-02 |
| assignment-history and agent-removal tables | US-TECH-03 |
| entire legacy desktop database (all tables, forms, queries, reports) | US-TECH-07 |
| legacy web application | US-TECH-07 |

## US-FUNC-01 — Start a licence application with buyer details
- **Status:** `Done`
- **Traceability:** Reqs: REQ-FUNC-01, REQ-ENH-01 | Rules: BR-07 | API: `GET /health`, `GET /api/applications`, `POST /api/applications`, `GET /api/applications/{applicationId}` | DB: `commercial_buyers`, `license_applications`, `field_agents`, `agent_assignments` | Code: `src/backend/server.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-01` (PASS), `TC-NEG-01` (PASS), `TC-NEG-02` (PASS), `TC-POS-02` (PASS), `TC-UI-INTERACT-02` (PASS), `TC-POS-03` (PASS), `TC-POS-09` (PASS), `TC-NEG-08` (PASS), `TC-NEG-09` (PASS), `TC-STATE-01` (PASS), `TC-UI-INTERACT-03` (PASS), `TC-POS-10` (PASS), `TC-POS-11` (PASS), `TC-POS-12` (PASS), `TC-STATE-02` (PASS), `TC-UI-INTERACT-04` (PASS), `TC-POS-13` (PASS) | Defects: None

- **Type:** Functional · **Sprint:** Sprint 1 · **Priority:** Highest · **Points:** 5
- **Narrative:** As a Commercial Buyer I want to enter my buyer details and open a draft application for the licence year so that my application exists as the single record staff will review.
- **Requirements:** REQ-FUNC-01, REQ-ENH-01 · **Rules:** BR-07 · **Roles:** Commercial Buyer · **Transitions:** —

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | POSITIVE | a Commercial Buyer on the New application tab with legal name, entity type, tax identifier kind, tax identifier and date of birth entered | they continue to step 2 and save the draft | an application number is shown and the status reads "Draft — not yet submitted" |
| AC-02 | NEGATIVE | a Commercial Buyer on step 1 with the legal name left empty | they press Continue | the step does not advance and the banner reads "Enter the legal name, entity type, tax identifier and date of birth to continue." |
| AC-03 | NEGATIVE | a Commercial Buyer who chose the Social-security number kind and typed 12345 | they press Continue | the banner reads "Enter the tax identifier as NNN-NN-NNNN (Social-security number) or NN-NNNNNNN (employer identification number)." and the step does not advance |
| AC-04 | POSITIVE | a Commercial Buyer whose legal name and date of birth equal an existing buyer record | they press Continue | a duplicate notice "A record with the same last name and date of birth already exists" is shown and the buyer may still continue |
| AC-05 | POSITIVE — INTERACTIVE COMPLETENESS | a Commercial Buyer on step 1 | they expand "More contact details" | business name, e-mail, phone, city and state fields become visible and remain optional |
| AC-06 | POSITIVE | a Commercial Buyer who typed a Social-security number into the tax identifier field | the field loses focus | the field shows only the masked form ending in the last four digits (for example ***-**-6789) and the raw number is never displayed again |

## US-FUNC-02 — Surety bond details with live required-bond calculator
- **Status:** `Done`
- **Traceability:** Reqs: REQ-FUNC-02, REQ-ENH-02 | Rules: BR-01 | API: `GET /health`, `GET /api/applications`, `POST /api/applications`, `GET /api/applications/{applicationId}` | DB: `commercial_buyers`, `license_applications`, `field_agents`, `agent_assignments` | Code: `src/backend/server.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-04` (PASS), `TC-EDGE-01` (PASS), `TC-EDGE-02` (PASS), `TC-EDGE-03` (PASS), `TC-POS-05` (PASS), `TC-NEG-03` (PASS) | Defects: None

- **Type:** Functional · **Sprint:** Sprint 1 · **Priority:** Highest · **Points:** 5
- **Narrative:** As a Commercial Buyer I want the required surety bond to be calculated while I type my prior-year purchases so that I know the exact shortfall before I submit.
- **Requirements:** REQ-FUNC-02, REQ-ENH-02 · **Rules:** BR-01 · **Roles:** Commercial Buyer · **Transitions:** —

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | POSITIVE | a Commercial Buyer on step 2 of a new application | they type 25000 as prior-year purchases without clicking anything | the required bond reads $2,500.00 |
| AC-02 | EDGE / BOUNDARY | a Commercial Buyer on step 2 | they type 9999.99 as prior-year purchases | the required bond reads $1,000.00 (regulatory minimum) |
| AC-03 | EDGE / BOUNDARY | a Commercial Buyer on step 2 | they type 10000.10 as prior-year purchases | the required bond reads $1,000.01 |
| AC-04 | EDGE / BOUNDARY | a Commercial Buyer on step 2 with prior-year purchases 25000 | they type 2499.99 as the bond amount | the shortfall text reads "Bond amount is below the required bond of $2,500.00. Increase the bond by $0.01 before submitting." |
| AC-05 | POSITIVE | a Commercial Buyer on step 2 with prior-year purchases 25000 | they type 2500 as the bond amount | the bond check reads "Bond is sufficient" and no shortfall is shown |
| AC-06 | NEGATIVE | a Commercial Buyer on step 2 | they type -5 as the bond amount and save the draft | the banner reads "Enter amounts in dollars, for example 25000.00." and no application is created |

## US-FUNC-03 — Field-agent roster with exclusivity, owner, suspension and duplicate rules
- **Status:** `Done`
- **Traceability:** Reqs: REQ-FUNC-03, REQ-FUNC-09, REQ-ENH-03 | Rules: BR-02, BR-05, BR-06, BR-07 | API: `GET /health`, `GET /api/applications`, `POST /api/applications`, `GET /api/applications/{applicationId}` | DB: `commercial_buyers`, `license_applications`, `field_agents`, `agent_assignments` | Code: `src/backend/server.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-06` (PASS), `TC-POS-07` (PASS), `TC-NEG-04` (PASS), `TC-NEG-05` (PASS), `TC-NEG-06` (PASS), `TC-POS-08` (PASS), `TC-NEG-07` (PASS), `TC-EDGE-04` (PASS) | Defects: None

- **Type:** Functional · **Sprint:** Sprint 1 · **Priority:** Highest · **Points:** 8
- **Narrative:** As a Commercial Buyer (on my draft) or Licensing Staff (on a submitted or issued licence) I want to add and remove field agents with the regulatory rules enforced as I type so that conflicts are resolved before issuance.
- **Requirements:** REQ-FUNC-03, REQ-FUNC-09, REQ-ENH-03 · **Rules:** BR-02, BR-05, BR-06, BR-07 · **Roles:** Commercial Buyer, Licensing Staff · **Transitions:** —

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | POSITIVE | a Commercial Buyer on step 3 of a draft application | they look at the roster before adding anyone | the buyer is listed as the owner agent with the label "Owner" and no remove control |
| AC-02 | POSITIVE | a Commercial Buyer on step 3 | they add agent Marcus Lee born 1988-07-02 | the roster shows Marcus Lee with a remove control and the notice reads "Marcus Lee added to the roster" |
| AC-03 | NEGATIVE | a Commercial Buyer on step 3 of a 2026 application | they add Dale Whitaker born 1979-03-14, who is already an agent on another issued 2026 licence | the roster is unchanged and the notice reads "This person is already an agent for another licensed buyer in 2026. One licensed buyer per calendar year is allowed." |
| AC-04 | NEGATIVE | a Commercial Buyer on step 3 | they add Alex Alvarez born 1990-11-23, who is suspended | the roster is unchanged and the notice reads "This agent is suspended and cannot be assigned. Contact licensing staff to review the suspension." |
| AC-05 | NEGATIVE | a Commercial Buyer on step 3 | they press Add agent with the last name empty | the notice reads "Enter the agent's first name, last name and date of birth." and the roster is unchanged |
| AC-06 | POSITIVE | Licensing Staff reviewing a submitted application | they add agent Marcus Lee born 1988-07-02 and then remove him | the roster first shows and then no longer shows Marcus Lee and the history lists "Agent assigned" and "Agent removed" |
| AC-07 | NEGATIVE | Licensing Staff reviewing an issued licence | they attempt to remove the owner agent | no remove control exists for the owner row and the roster is unchanged |
| AC-08 | EDGE / BOUNDARY | a Commercial Buyer on step 3 who already added Marcus Lee born 1988-07-02 | they add "marcus" "LEE" born 1988-07-02 again | the existing record is re-used and the notice reads "Marcus Lee is already on this roster" with exactly one Marcus Lee row |

## US-FUNC-04 — Submit the application for review
- **Status:** `Done`
- **Traceability:** Reqs: REQ-FUNC-04, REQ-ENH-01 | Rules: BR-01, BR-04 | API: `GET /health`, `GET /api/applications`, `POST /api/applications`, `GET /api/applications/{applicationId}` | DB: `commercial_buyers`, `license_applications`, `field_agents`, `agent_assignments` | Code: `src/backend/server.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-09` (PASS), `TC-NEG-08` (PASS), `TC-NEG-09` (PASS), `TC-STATE-01` (PASS), `TC-UI-INTERACT-03` (PASS), `TC-POS-01` (PASS), `TC-NEG-01` (PASS), `TC-NEG-02` (PASS), `TC-POS-02` (PASS), `TC-UI-INTERACT-02` (PASS), `TC-POS-03` (PASS), `TC-POS-10` (PASS), `TC-POS-11` (PASS), `TC-POS-12` (PASS), `TC-STATE-02` (PASS), `TC-UI-INTERACT-04` (PASS), `TC-POS-13` (PASS) | Defects: None

- **Type:** Functional · **Sprint:** Sprint 1 · **Priority:** Highest · **Points:** 5
- **Narrative:** As a Commercial Buyer I want to submit my completed draft so that licensing staff can review it, with every regulatory block explained before it leaves my hands.
- **Requirements:** REQ-FUNC-04, REQ-ENH-01 · **Rules:** BR-01, BR-04 · **Roles:** Commercial Buyer · **Transitions:** DRAFT->SUBMITTED

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | POSITIVE | a Commercial Buyer on step 4 of a draft whose bond amount meets the required bond | they press Submit application | the status badge reads "Submitted — awaiting review" and the banner confirms the submission |
| AC-02 | NEGATIVE | a Commercial Buyer whose bond amount is below the required bond | they press Submit application | the status stays "Draft — not yet submitted" and the banner reads "Bond amount is below the required bond of $2,500.00. Increase the bond by $500.00 before submitting." |
| AC-03 | NEGATIVE | a Commercial Buyer whose tax identifier belongs to a buyer that already has a submitted 2026 application | they save the draft | no second application is created and the banner reads "An application for 2026 already exists for this buyer (Submitted — awaiting review). Open it instead of starting a new one." |
| AC-04 | NEGATIVE — WORKFLOW PREREQUISITE GATE | a Commercial Buyer viewing an application that is already submitted | they look for the Submit application control | no Submit control is rendered and the status is unchanged |
| AC-05 | POSITIVE — INTERACTIVE COMPLETENESS | a Commercial Buyer on step 4 | they press Back | step 3 is shown again with the roster intact |

## US-FUNC-05 — Review queue and application review view
- **Status:** `Done`
- **Traceability:** Reqs: REQ-FUNC-05, REQ-ENH-01 | Rules: — | API: `GET /health`, `GET /api/applications`, `POST /api/applications`, `GET /api/applications/{applicationId}` | DB: `commercial_buyers`, `license_applications`, `field_agents`, `agent_assignments` | Code: `src/backend/server.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-10` (PASS), `TC-POS-11` (PASS), `TC-POS-12` (PASS), `TC-STATE-02` (PASS), `TC-UI-INTERACT-04` (PASS), `TC-POS-13` (PASS), `TC-POS-01` (PASS), `TC-NEG-01` (PASS), `TC-NEG-02` (PASS), `TC-POS-02` (PASS), `TC-UI-INTERACT-02` (PASS), `TC-POS-03` (PASS), `TC-POS-09` (PASS), `TC-NEG-08` (PASS), `TC-NEG-09` (PASS), `TC-STATE-01` (PASS), `TC-UI-INTERACT-03` (PASS) | Defects: None

- **Type:** Functional · **Sprint:** Sprint 2 · **Priority:** Highest · **Points:** 5
- **Narrative:** As Licensing Staff I want a queue of submitted applications and a complete review view so that I can decide from the same record the buyer completed.
- **Requirements:** REQ-FUNC-05, REQ-ENH-01 · **Rules:** — · **Roles:** Licensing Staff · **Transitions:** —

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | POSITIVE | Licensing Staff on the Review queue tab | the queue loads with the default filter | only applications with status "Submitted — awaiting review" are listed, each with application number, buyer, licence year, bond check and submitted date |
| AC-02 | POSITIVE | Licensing Staff on the Review queue | they change the status filter to Issued | the list shows only issued licences and each row shows the licence number |
| AC-03 | POSITIVE | Licensing Staff on the Review queue | they open the submitted application of Apex Retail Group | the review view shows the buyer name, the masked tax identifier ending in 4 digits, required bond, bond amount, the bond check "Sufficient", the agent roster and the history |
| AC-04 | NEGATIVE — ROLE VISIBILITY | a Commercial Buyer in the portal | they look for the Review queue, Issue licence or Reject application controls | none of them is rendered in the buyer view |
| AC-05 | POSITIVE — INTERACTIVE COMPLETENESS | Licensing Staff in the review view | they press Back to queue | the queue is shown again with the same filter applied |
| AC-06 | POSITIVE | Licensing Staff on the Review queue with the filter set to Draft | they open the draft application of Acme Commercial Services | the review view shows status "Draft — not yet submitted" and no decision controls |

## US-FUNC-06 — Issue the licence and print certificate and agent cards
- **Status:** `Done`
- **Traceability:** Reqs: REQ-FUNC-06, REQ-FUNC-08 | Rules: BR-01, BR-02, BR-06 | API: `GET /health`, `GET /api/applications`, `POST /api/applications`, `GET /api/applications/{applicationId}` | DB: `commercial_buyers`, `license_applications`, `field_agents`, `agent_assignments` | Code: `src/backend/server.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-14` (PASS), `TC-NEG-10` (PASS), `TC-STATE-03` (PASS), `TC-POS-15` (PASS), `TC-UI-INTERACT-05` (PASS), `TC-STATE-04` (PASS) | Defects: None

- **Type:** Functional · **Sprint:** Sprint 2 · **Priority:** Highest · **Points:** 5
- **Narrative:** As Licensing Staff I want to issue a submitted application that passes every guard and print the certificate and agent cards so that the buyer and agents are credentialed.
- **Requirements:** REQ-FUNC-06, REQ-FUNC-08 · **Rules:** BR-01, BR-02, BR-06 · **Roles:** Licensing Staff · **Transitions:** SUBMITTED->ISSUED

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | POSITIVE | Licensing Staff reviewing the submitted application of Apex Retail Group | they press Issue licence | the status reads "Licence issued", a licence number starting with TB-2026- is shown and the history lists "Licence issued" |
| AC-02 | NEGATIVE | Licensing Staff reviewing the submitted application of Northwind Commerce, whose buyer is suspended | they press Issue licence | the status stays "Submitted — awaiting review" and the banner reads "The licence cannot be issued: the buyer is suspended. Resolve it and try again." |
| AC-03 | NEGATIVE — WORKFLOW PREREQUISITE GATE | Licensing Staff reviewing an application that is already issued | they look for the Issue licence and Reject application controls | neither control is rendered and the status stays "Licence issued" |
| AC-04 | POSITIVE | Licensing Staff reviewing the issued licence of Horizon Logistics | they press Print agent cards | every agent row shows "Card printed" and the history lists "Agent cards printed" |
| AC-05 | POSITIVE — INTERACTIVE COMPLETENESS | Licensing Staff reviewing the issued licence of Horizon Logistics | they press Print certificate | the banner confirms "Certificate printed" and the history lists "Certificate printed" |
| AC-06 | NEGATIVE — WORKFLOW PREREQUISITE GATE | Licensing Staff reviewing a draft application | they look for the Print certificate control | no print control is rendered |

## US-FUNC-07 — Reject an application with a reason the buyer can see
- **Status:** `Done`
- **Traceability:** Reqs: REQ-FUNC-07, REQ-FUNC-12, REQ-ENH-04 | Rules: — | API: `GET /health`, `GET /api/applications`, `POST /api/applications`, `GET /api/applications/{applicationId}` | DB: `commercial_buyers`, `license_applications`, `field_agents`, `agent_assignments` | Code: `src/backend/server.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-16` (PASS), `TC-NEG-11` (PASS), `TC-POS-17` (PASS), `TC-STATE-05` (PASS), `TC-POS-18` (PASS) | Defects: None

- **Type:** Functional · **Sprint:** Sprint 2 · **Priority:** High · **Points:** 5
- **Narrative:** As Licensing Staff I want to reject a submitted application with a reason, and as a Commercial Buyer I want to see that decision on my application timeline, so that nothing is silently deleted.
- **Requirements:** REQ-FUNC-07, REQ-FUNC-12, REQ-ENH-04 · **Rules:** — · **Roles:** Licensing Staff, Commercial Buyer · **Transitions:** SUBMITTED->REJECTED

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | POSITIVE | Licensing Staff reviewing the submitted application of Cedar Ridge Buyers | they enter the reason "Surety company is not authorised in this state" and press Reject application | the status reads "Rejected" and the history lists "Rejected" with that reason |
| AC-02 | NEGATIVE | Licensing Staff reviewing a submitted application | they press Reject application with a reason of fewer than 10 characters | the status stays "Submitted — awaiting review" and the banner reads "Enter a rejection reason of at least 10 characters so the buyer knows what to correct." |
| AC-03 | POSITIVE | a Commercial Buyer who opens the rejected application of Oakridge Distribution by its application number | the application detail loads | the status reads "Rejected" and the timeline shows the rejection with its reason |
| AC-04 | NEGATIVE — WORKFLOW PREREQUISITE GATE | Licensing Staff reviewing an application that is already rejected | they look for the Reject application control | no Reject control is rendered and the status stays "Rejected" |
| AC-05 | POSITIVE | a Commercial Buyer who opens the issued licence of Horizon Logistics | the timeline loads | it lists the submission and the issuance with their dates and the licence number is shown |

## US-FUNC-08 — Buyer and agent registries with suspension
- **Status:** `Done`
- **Traceability:** Reqs: REQ-FUNC-10 | Rules: BR-06, BR-08 | API: `GET /health`, `GET /api/applications`, `POST /api/applications`, `GET /api/applications/{applicationId}` | DB: `commercial_buyers`, `license_applications`, `field_agents`, `agent_assignments` | Code: `src/backend/server.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-19` (PASS), `TC-POS-20` (PASS), `TC-POS-21` (PASS), `TC-POS-22` (PASS), `TC-NEG-12` (PASS), `TC-STATE-06` (PASS) | Defects: None

- **Type:** Functional · **Sprint:** Sprint 2 · **Priority:** High · **Points:** 5
- **Narrative:** As Licensing Staff I want to search buyers and agents, see their flags and current licence, and suspend or reinstate them so that suspended parties cannot be licensed or assigned.
- **Requirements:** REQ-FUNC-10 · **Rules:** BR-06, BR-08 · **Roles:** Licensing Staff · **Transitions:** —

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | POSITIVE | Licensing Staff on the Buyers tab | they search for "Retail" | Apex Retail Group is listed with its masked tax identifier and a suspension flag of "Active" |
| AC-02 | POSITIVE | Licensing Staff on the Buyers tab | they search for "Northwind" | Northwind Commerce is listed with the flag "Suspended" and a Reinstate control |
| AC-03 | POSITIVE | Licensing Staff on the Agents tab | they search for "Whitaker" | Dale Whitaker is listed with the current licence TB-2026-00003 |
| AC-04 | POSITIVE | Licensing Staff on the Agents tab | they suspend Priya Natarajan and search again | Priya Natarajan shows "Suspended" and the control now reads Reinstate |
| AC-05 | NEGATIVE | Licensing Staff on the Buyers tab | they look for a Delete control on a buyer with applications | no Delete control is rendered |
| AC-06 | NEGATIVE — ROLE VISIBILITY | a Commercial Buyer in the portal | they look for the Buyers or Agents registry tabs | neither tab is rendered |

## US-FUNC-09 — Supporting documents on an application
- **Status:** `Done`
- **Traceability:** Reqs: REQ-FUNC-11 | Rules: — | API: `GET /health`, `GET /api/applications`, `POST /api/applications`, `GET /api/applications/{applicationId}` | DB: `commercial_buyers`, `license_applications`, `field_agents`, `agent_assignments` | Code: `src/backend/server.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-23` (PASS), `TC-NEG-13` (PASS), `TC-POS-24` (PASS), `TC-UI-INTERACT-06` (PASS) | Defects: None

- **Type:** Functional · **Sprint:** Sprint 2 · **Priority:** Medium · **Points:** 3
- **Narrative:** As a Commercial Buyer I want to attach supporting documents to my draft, and as Licensing Staff I want to see them during review, so that bond certificates travel with the application.
- **Requirements:** REQ-FUNC-11 · **Rules:** — · **Roles:** Commercial Buyer, Licensing Staff · **Transitions:** —

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | POSITIVE | a Commercial Buyer viewing their draft application | they add the document "surety-bond.pdf" of type PDF and size 240000 bytes | the document list shows "surety-bond.pdf (PDF, 234.4 KB)" |
| AC-02 | NEGATIVE | a Commercial Buyer viewing their draft application | they press Add document with the file name empty | the banner reads "Enter the document name to attach it." and the list is unchanged |
| AC-03 | POSITIVE | Licensing Staff reviewing an application with documents | the review view loads | the documents section lists every document with its type and size and never shows binary content |
| AC-04 | POSITIVE — INTERACTIVE COMPLETENESS | a Commercial Buyer viewing an application with no documents | the documents section renders | it shows the sentence "No documents attached yet." instead of an empty table |

## US-FUNC-10 — Volume fee calculator and quarterly report
- **Status:** `Done`
- **Traceability:** Reqs: REQ-FUNC-13, REQ-ENH-05 | Rules: BR-03 | API: `GET /health`, `GET /api/applications`, `POST /api/applications`, `GET /api/applications/{applicationId}` | DB: `commercial_buyers`, `license_applications`, `field_agents`, `agent_assignments` | Code: `src/backend/server.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-25` (PASS), `TC-EDGE-05` (PASS), `TC-EDGE-06` (PASS), `TC-POS-26` (PASS), `TC-NEG-14` (PASS), `TC-STATE-07` (PASS) | Defects: None

- **Type:** Functional · **Sprint:** Sprint 2 · **Priority:** Medium · **Points:** 3
- **Narrative:** As a Commercial Buyer I want the 4 % volume fee calculated while I type and recorded per quarter on my issued licence so that remittances are correct.
- **Requirements:** REQ-FUNC-13, REQ-ENH-05 · **Rules:** BR-03 · **Roles:** Commercial Buyer, Licensing Staff · **Transitions:** —

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | POSITIVE | a Commercial Buyer on the Fee calculator tab | they type 12500 as the quarter's purchase total | the fee due reads $500.00 without pressing any button |
| AC-02 | EDGE / BOUNDARY | a Commercial Buyer on the Fee calculator tab | they type 0.13 as the purchase total | the fee due reads $0.01 |
| AC-03 | EDGE / BOUNDARY | a Commercial Buyer on the Fee calculator tab | they type 0.10 as the purchase total | the fee due reads $0.00 |
| AC-04 | POSITIVE | a Commercial Buyer viewing the issued licence of Horizon Logistics | they choose quarter Q1 2026, type 12500 and press Record report | the report list shows "Q1 2026 — purchases $12,500.00 — fee due $500.00" |
| AC-05 | NEGATIVE | a Commercial Buyer viewing the issued licence of Horizon Logistics | they press Record report with the purchase total empty | the banner reads "Enter the quarter's total purchase price in dollars." and no report is added |
| AC-06 | NEGATIVE — ROLE VISIBILITY | a Commercial Buyer viewing the draft application of Acme Commercial Services | they look for the Record report control | no fee-report controls are rendered because the licence is not issued |

## US-TECH-01 — Role-based access and server-side state guards
- **Status:** `Done`
- **Traceability:** Reqs: REQ-SEC-01, REQ-SEC-02, REQ-ARCH-04, REQ-UX-01 | Rules: — | API: `POST /api/applications/5/issue`, `GET /api/applications/5`, `POST /api/applications/1/issue`, `GET /api/applications/1` | DB: `commercial_buyers`, `license_applications`, `field_agents`, `agent_assignments` | Code: `src/backend/server.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-NEG-15` (PASS), `TC-STATE-08` (PASS), `TC-NEG-16` (PASS), `TC-POS-27` (PASS), `TC-NEG-17` (PASS), `TC-STATE-09` (PASS), `TC-UI-INTERACT-TAB-01` (NOT_RUN), `TC-UI-INTERACT-TAB-02` (NOT_RUN), `TC-UI-INTERACT-TAB-03` (NOT_RUN), `TC-UI-INTERACT-TAB-04` (NOT_RUN), `TC-UI-INTERACT-TAB-05` (NOT_RUN), `TC-UI-INTERACT-TAB-06` (NOT_RUN), `TC-POS-JOURNEY-01` (NOT_RUN) | Defects: None

- **Type:** Technical · **Sprint:** Sprint 1 · **Priority:** Highest · **Points:** 5
- **Narrative:** As the platform I want every transition validated against the state table and the RBAC matrix on the server so that the UI is never the only guard.
- **Requirements:** REQ-SEC-01, REQ-SEC-02, REQ-ARCH-04, REQ-UX-01 · **Rules:** — · **Roles:** Commercial Buyer, Licensing Staff · **Transitions:** DRAFT->SUBMITTED, SUBMITTED->ISSUED, SUBMITTED->REJECTED

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | NEGATIVE | an API client acting as Commercial Buyer | it calls the issue operation on a submitted application | the response is 403 with the message "You do not have permission to issue licences." and the status is unchanged |
| AC-02 | NEGATIVE — WORKFLOW PREREQUISITE GATE | an API client acting as Licensing Staff | it calls the issue operation on a draft application | the response is 409 with a message stating the application is "Draft — not yet submitted" and Issue is not possible from this status |
| AC-03 | NEGATIVE | an API client acting as Licensing Staff | it calls the submit operation on a draft application | the response is 403 with the message "You do not have permission to submit applications." |
| AC-04 | POSITIVE | an API client acting as Licensing Staff | it calls the reject operation on a submitted application with a valid reason | the response is 200 and the returned status label is "Rejected" |
| AC-05 | NEGATIVE | an API client with no role header | it lists the review queue | the response is 403 with a permission message |
| AC-06 | NEGATIVE — ROLE VISIBILITY | the Commercial Buyer view | it is rendered for any application | no element bound to Issue or Reject exists in the buyer view |

## US-TECH-02 — PII masking and zero-leakage presentation boundary
- **Status:** `Done`
- **Traceability:** Reqs: REQ-SEC-03, REQ-SEC-04, REQ-UX-04, REQ-ARCH-05 | Rules: — | API: `GET /api/applications/2`, `GET /api/applications/3`, `GET /api/buyers` | DB: `commercial_buyers`, `license_applications`, `field_agents`, `agent_assignments` | Code: `src/backend/server.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-28` (PASS), `TC-POS-29` (PASS), `TC-NEG-18` (PASS), `TC-POS-30` (PASS) | Defects: None

- **Type:** Technical · **Sprint:** Sprint 1 · **Priority:** Highest · **Points:** 5
- **Narrative:** As the platform I want tax identifiers hashed at capture and every API response to expose display models only so that no raw identifier, internal key or code reaches the UI.
- **Requirements:** REQ-SEC-03, REQ-SEC-04, REQ-UX-04, REQ-ARCH-05 · **Rules:** — · **Roles:** Commercial Buyer, Licensing Staff · **Transitions:** —

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | POSITIVE | an API client acting as Licensing Staff | it reads the application of Apex Retail Group | the tax identifier field contains only the masked form **-***4567 and no field contains a hash |
| AC-02 | POSITIVE | an API client | it reads any application | the status is returned as a code and a label pair and the label is human-readable |
| AC-03 | NEGATIVE | an API client acting as Licensing Staff | it searches buyers by a full raw tax identifier | the search returns no match by identifier (identifiers are not searchable) and the response contains no raw identifier |
| AC-04 | POSITIVE | the rendered UI in every role and view | all states reached by the test suite are scanned | no database identifier, state or trigger code, legacy object name or unmasked identifier appears in visible text |

## US-TECH-03 — Audit trail and input hardening
- **Status:** `Done`
- **Traceability:** Reqs: REQ-SEC-05, REQ-SEC-06 | Rules: — | API: `GET /api/applications/3`, `POST /api/applications`, `POST /api/calculations/bond`, `GET /api/nothing-here` | DB: `commercial_buyers`, `license_applications`, `field_agents`, `agent_assignments` | Code: `src/backend/server.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-31` (PASS), `TC-NEG-19` (PASS), `TC-NEG-20` (PASS), `TC-NEG-21` (PASS) | Defects: None

- **Type:** Technical · **Sprint:** Sprint 2 · **Priority:** High · **Points:** 3
- **Narrative:** As the platform I want every transition, roster change, suspension and print recorded in an append-only history and every input validated server-side so that decisions are traceable and errors are safe.
- **Requirements:** REQ-SEC-05, REQ-SEC-06 · **Rules:** — · **Roles:** Licensing Staff, Commercial Buyer · **Transitions:** —

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | POSITIVE | an API client acting as Licensing Staff | it reads the history of the issued licence of Horizon Logistics | the history contains the submission and issuance events with actor role, from and to status labels and a timestamp |
| AC-02 | NEGATIVE | an API client acting as Commercial Buyer | it creates an application with a legal name longer than 200 characters | the response is 400 with a message naming the field and the limit |
| AC-03 | NEGATIVE | an API client | it sends a malformed JSON body | the response is 400 with a plain message and no stack trace |
| AC-04 | NEGATIVE | an API client acting as Licensing Staff | it calls an unknown API path | the response is 404 with a plain JSON message |

## US-TECH-04 — Accessibility baseline (WCAG 2.1 AA)
- **Status:** `Done`
- **Traceability:** Reqs: REQ-A11Y-01, REQ-A11Y-02, REQ-A11Y-03, REQ-A11Y-04, REQ-A11Y-05, REQ-A11Y-06, REQ-UX-03 | Rules: — | API: `GET /health`, `GET /api/applications`, `POST /api/applications`, `GET /api/applications/{applicationId}` | DB: `commercial_buyers`, `license_applications`, `field_agents`, `agent_assignments` | Code: `src/backend/server.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-32` (PASS), `TC-POS-33` (PASS), `TC-POS-34` (PASS), `TC-POS-35` (PASS), `TC-POS-36` (PASS) | Defects: None

- **Type:** Technical · **Sprint:** Sprint 1 · **Priority:** High · **Points:** 5
- **Narrative:** As any user I want the portal operable by keyboard and screen reader with labelled fields, live regions and visible focus so that it meets WCAG 2.1 AA.
- **Requirements:** REQ-A11Y-01, REQ-A11Y-02, REQ-A11Y-03, REQ-A11Y-04, REQ-A11Y-05, REQ-A11Y-06, REQ-UX-03 · **Rules:** — · **Roles:** Commercial Buyer, Licensing Staff · **Transitions:** —

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | POSITIVE | the portal in any view | the page is inspected | every input has a bound label, there is exactly one h1, the document declares lang="en" and no control has a positive tabindex |
| AC-02 | POSITIVE | the portal on first load | the first Tab press is simulated | a "Skip to main content" link is the first focusable element |
| AC-03 | POSITIVE | a Commercial Buyer who triggers a validation error | the banner appears | the banner has role="alert" and the invalid field carries aria-invalid="true" |
| AC-04 | POSITIVE | a Commercial Buyer on step 2 | the required bond recalculates | the required-bond element is a live region (role="status") |
| AC-05 | POSITIVE | the role tabs of either view | they are inspected | each tab has role="tab" inside a role="tablist" and the active one has aria-selected="true" |

## US-TECH-05 — UX guardrails, no dead controls and the test-id contract
- **Status:** `Done`
- **Traceability:** Reqs: REQ-UX-02, REQ-UX-05, REQ-ARCH-06 | Rules: BR-01, BR-03 | API: `GET /health`, `GET /api/applications`, `POST /api/applications`, `GET /api/applications/{applicationId}` | DB: `commercial_buyers`, `license_applications`, `field_agents`, `agent_assignments` | Code: `src/backend/server.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-UI-INTERACT-07` (PASS), `TC-POS-37` (PASS), `TC-POS-38` (PASS), `TC-POS-39` (PASS), `TC-POS-40` (PASS) | Defects: None

- **Type:** Technical · **Sprint:** Sprint 1 · **Priority:** High · **Points:** 3
- **Narrative:** As the product team I want the ten UX guardrails applied, every control wired, and every declared data-testid implemented so that the pretotype is simple and testable.
- **Requirements:** REQ-UX-02, REQ-UX-05, REQ-ARCH-06 · **Rules:** BR-01, BR-03 · **Roles:** Commercial Buyer, Licensing Staff · **Transitions:** —

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | POSITIVE — INTERACTIVE COMPLETENESS | the portal in every view reached by the suite | the control audit runs | every button, tab and select has a bound handler and activating it changes the DOM |
| AC-02 | POSITIVE | a Commercial Buyer on any step | the visible primary buttons are counted | exactly one primary button is visible |
| AC-03 | POSITIVE | a Commercial Buyer on step 1 | visible inputs outside progressive disclosure are counted | at most 5 inputs are visible |
| AC-04 | POSITIVE | either role | top-level tabs are counted | at most 3 tabs are visible |
| AC-05 | POSITIVE | the main container | its computed max-width is read | it is between 720 px and 840 px |

## US-TECH-06 — Runnable zero-dependency stack with layered backend and 3NF schema
- **Status:** `Done`
- **Traceability:** Reqs: REQ-ARCH-01, REQ-ARCH-02, REQ-ARCH-03 | Rules: BR-01, BR-02, BR-03, BR-04, BR-05, BR-06, BR-07, BR-08 | API: `GET /health`, `POST /api/calculations/bond`, `POST /api/calculations/volume-fee`, `GET /` | DB: `commercial_buyers`, `license_applications`, `field_agents`, `agent_assignments` | Code: `src/backend/server.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-41` (PASS), `TC-POS-42` (PASS), `TC-POS-43` (PASS), `TC-NEG-22` (PASS), `TC-POS-44` (PASS) | Defects: None

- **Type:** Technical · **Sprint:** Sprint 1 · **Priority:** Highest · **Points:** 5
- **Narrative:** As the delivery team I want the application to start with one command, answer a health check and persist to a normalised SQLite schema so that it runs anywhere Python exists.
- **Requirements:** REQ-ARCH-01, REQ-ARCH-02, REQ-ARCH-03 · **Rules:** BR-01, BR-02, BR-03, BR-04, BR-05, BR-06, BR-07, BR-08 · **Roles:** Licensing Staff, Commercial Buyer · **Transitions:** —

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | POSITIVE | the start command has been run | the health endpoint is requested | it returns 200 with status "ok" and database "ok" |
| AC-02 | POSITIVE | the backend is running | the bond calculation endpoint is called with prior-year purchases 25000 | it returns 200 with required bond 2500.00 |
| AC-03 | POSITIVE | the backend is running | the volume-fee calculation endpoint is called with purchase total 12500 | it returns 200 with fee due 500.00 |
| AC-04 | NEGATIVE | the backend is running | the bond calculation endpoint is called with a negative amount | it returns 400 with the amounts message |
| AC-05 | POSITIVE | the backend is running | the UI entry is requested | it returns 200 with the HTML document |

## US-TECH-07 — One-time legacy data migration and retirement
- **Status:** `Done`
- **Traceability:** Reqs: REQ-ARCH-07 | Rules: — | API: `GET /api/applications/3`, `GET /api/files/legacy-attachments`, `GET /legacy-portal/` | DB: `commercial_buyers`, `license_applications`, `field_agents`, `agent_assignments` | Code: `src/backend/server.py`, `src/contracts/openapi.yaml`, `src/db/schema.sql`, `src/ui/app.js`, `src/ui/index.html`, `src/ui/styles.css` | Tests: `TC-POS-45` (PASS), `TC-POS-46` (PASS), `TC-NEG-23` (PASS), `TC-NEG-24` (PASS) | Defects: None

- **Type:** Technical · **Sprint:** Product Backlog · **Priority:** Medium · **Points:** 5
- **Narrative:** As the programme I want a one-time ETL from the legacy desktop database into the new schema with reconciliation counts so that the legacy database and the old web application can be retired without bridges.
- **Requirements:** REQ-ARCH-07 · **Rules:** — · **Roles:** Licensing Staff · **Transitions:** —

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | POSITIVE | the rendered UI in every view | visible text is scanned | no legacy table, form, report, query or control name appears |
| AC-02 | POSITIVE | the backend is running | the application of Horizon Logistics is read | its licence number follows the new format TB-2026-00003 and no legacy identifier field is present |
| AC-03 | NEGATIVE | an API client | it requests a legacy-style attachment path under the API | the response is 404 with the message "That address does not exist." — no compatibility route exists |
| AC-04 | NEGATIVE | a browser or client | it requests the previous web application's portal path | the response is 404 with the message "That page does not exist." — the old application is not proxied or bridged |
