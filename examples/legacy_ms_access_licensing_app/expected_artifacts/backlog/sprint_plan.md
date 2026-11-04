# Sprint Alignment Plan (`backlog/sprint_plan.md`)

- **SPRINT_ALIGNMENT_APPROVAL:** `PRE_APPROVED_BY_USER`
- **ALM platform:** `none` (from `specs/target_stack.json`) — **Board / project:** CSV export only (`backlog/jira_import.csv`)
- **Release 1 goal:** a Commercial Buyer completes and submits a licence application online (buyer details, bond with live regulatory calculation, agent roster with exclusivity rules), Licensing Staff review the same record and issue or reject it with an audited reason, registries and quarterly fee reporting are available — with role-separated views, server-side state guards, masked identifiers, WCAG 2.1 AA and zero internal data in the UI.

## Sprint 1 — Apply & Submit
| Story | Title | Points | Requirement refs | Workflow transitions |
| :-- | :-- | :-: | :-- | :-- |
| US-FUNC-01 | Start a licence application with buyer details | 5 | REQ-FUNC-01, REQ-ENH-01 | — |
| US-FUNC-02 | Surety bond details with live required-bond calculator | 5 | REQ-FUNC-02, REQ-ENH-02 | — |
| US-FUNC-03 | Field-agent roster with exclusivity, owner, suspension and duplicate rules | 8 | REQ-FUNC-03, REQ-FUNC-09, REQ-ENH-03 | — |
| US-FUNC-04 | Submit the application for review | 5 | REQ-FUNC-04, REQ-ENH-01 | DRAFT->SUBMITTED |
| US-TECH-01 | Role-based access and server-side state guards | 5 | REQ-SEC-01, REQ-SEC-02, REQ-ARCH-04, REQ-UX-01 | DRAFT->SUBMITTED, SUBMITTED->ISSUED, SUBMITTED->REJECTED |
| US-TECH-02 | PII masking and zero-leakage presentation boundary | 5 | REQ-SEC-03, REQ-SEC-04, REQ-UX-04, REQ-ARCH-05 | — |
| US-TECH-04 | Accessibility baseline (WCAG 2.1 AA) | 5 | REQ-A11Y-01…06, REQ-UX-03 | — |
| US-TECH-05 | UX guardrails, no dead controls and the test-id contract | 3 | REQ-UX-02, REQ-UX-05, REQ-ARCH-06 | — |
| US-TECH-06 | Runnable zero-dependency stack with layered backend and 3NF schema | 5 | REQ-ARCH-01, REQ-ARCH-02, REQ-ARCH-03 | — |

## Sprint 2 — Review, Decide & Registries
| Story | Title | Points | Requirement refs | Workflow transitions |
| :-- | :-- | :-: | :-- | :-- |
| US-FUNC-05 | Review queue and application review view | 5 | REQ-FUNC-05, REQ-ENH-01 | — |
| US-FUNC-06 | Issue the licence and print certificate and agent cards | 5 | REQ-FUNC-06, REQ-FUNC-08 | SUBMITTED->ISSUED |
| US-FUNC-07 | Reject an application with a reason the buyer can see | 5 | REQ-FUNC-07, REQ-FUNC-12, REQ-ENH-04 | SUBMITTED->REJECTED |
| US-FUNC-08 | Buyer and agent registries with suspension | 5 | REQ-FUNC-10 | — |
| US-FUNC-09 | Supporting documents on an application | 3 | REQ-FUNC-11 | — |
| US-FUNC-10 | Volume fee calculator and quarterly report | 3 | REQ-FUNC-13, REQ-ENH-05 | — |
| US-TECH-03 | Audit trail and input hardening | 3 | REQ-SEC-05, REQ-SEC-06 | — |

## Product Backlog (Release 2 / deferrable)
| Story | Title | Points | Why deferred |
| :-- | :-- | :-: | :-- |
| US-TECH-07 | One-time legacy data migration and retirement | 5 | Runs once at cutover after Release 1 is accepted; the plan (`design/data_migration_and_cutover.md`) is written in Stage 4A, the ETL tooling is built after the target schema is frozen |

## Retired / Not Carried Forward *(SCENARIO_LEGACY_APP)*
| Legacy artefact | Decision | Rationale |
| :-- | :-- | :-- |
| Hard delete of unissued applications (`Command163_Click`) | retired | replaced by the audited `Reject` transition (ASSUMPTION-01) |
| Staff-side licence creation from the applicant-selection form (`cmdLicense_Click`) | retired for Release 1 | applications are filed by the buyer (ASSUMPTION-02); staff entry on behalf of a buyer can return as a Release 2 story if the organization asks |
| Plain-text SSN/FEIN columns and SSN/FEIN search | retired | identifiers are hashed at capture; registry search is by name, city, e-mail or date of birth (REQ-SEC-03) |
| Binary attachments inside the database table | retired | documents live in the vault; only metadata is stored (REQ-FUNC-11) |
| Report-close side effect that marks cards printed | retired | printing is an explicit audited action (REQ-FUNC-08) |
| Licence number parsing (year and applicant id embedded) | retired | `license_year` is a column; the licence number is a generated display value |
| Agent-removal letter table | retired | removal is an audit event; notifications are out of scope for Release 1 |

## Totals
| Tier | Stories | Points |
| :-- | :-: | :-: |
| Sprint 1 | 9 | 46 |
| Sprint 2 | 7 | 29 |
| Product Backlog | 1 | 5 |
| **Total** | **17** | **80** |
