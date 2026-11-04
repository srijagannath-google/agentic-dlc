# Data Migration & Cutover Plan — Business Licensing & Renewal Portal (`design/data_migration_and_cutover.md`)

- **Strategy:** one-time extract → cleanse → load from the legacy desktop database (and the previous web application's submission store) into the target schema in `design/solution_design.md §2`; **no dual run, no bridge, no compatibility views**. After reconciliation the legacy database is frozen read-only and archived; the previous web application is retired.
- **Scenario:** `SCENARIO_LEGACY_APP`. Legacy object names below appear **only** in this plan and in the ETL mapping configuration — never in target code, schema or UI (REQ-ARCH-07).
- **Executed by:** story US-TECH-07 (Product Backlog) once Release 1 is accepted and the target schema is frozen.

## 1. Source inventory
| Legacy object (as exported) | Kind | Rows (to be counted at extract) | Target |
| :-- | :-- | :-- | :-- |
| applicant table (row source of the applicant-selection form) | table | n₁ | `commercial_buyers` |
| licence table / licence-application query | table | n₂ | `license_applications` |
| agent information table | table | n₃ | `field_agents` |
| licence–agent bridge table | table | n₄ | `agent_assignments` (active rows) |
| agent assignment history table | table | n₅ | `agent_assignments` (closed rows) + `audit_events` |
| agent removal letter table | table | n₆ | `audit_events` (reason "removal letter requested") |
| uploaded-files table (`tblBusinessLicenseFiles` export) | table with binary column | n₇ | `supporting_documents` + document vault objects |
| volume-fee tables (fee, fee origin) | tables (not exported; described in the overview document) | n₈ | `quarterly_fee_reports` |
| previous web application submission store | external | n₉ | `license_applications` in `SUBMITTED` state |

## 2. Column mapping & cleansing rules
| Legacy column(s) | Target column | Transformation / cleansing |
| :-- | :-- | :-- |
| applicant id | — (not carried) | surrogate `buyer_id` generated; a crosswalk table `migration_buyer_crosswalk(legacy_applicant_id, buyer_id)` is kept **only in the migration workspace** and deleted after reconciliation |
| last name, first name, middle initial / business name | `legal_name`, `business_name` | trim, collapse whitespace, title-case personal names; `legal_name = "First Middle Last"` for individuals, business name for entities |
| applicant type ("other" + free text) | `entity_type` | map to `INDIVIDUAL / LLC / CORPORATION / PARTNERSHIP / OTHER`; unknown → `OTHER` with the free text appended to `business_name` notes |
| SSN / FEIN (plain text) | `tax_id_kind`, `tax_id_hash`, `tax_id_last4` | normalise digits; kind by length (9 digits with 3-2-4 → SSN, 2-7 → FEIN); hash = SHA-256(salt + digits); last4 = final four digits; **raw value discarded**; rows with no identifier → quarantined for staff completion |
| date of birth | `date_of_birth` | ISO-8601; impossible dates (future, < 1900) → quarantined |
| suspended ("Yes"/"No"), under investigation | `is_suspended`, `under_investigation` | `"Yes" → 1`, else `0` |
| e-mail, phone, city, state | `email`, `phone`, `city`, `state_code` | lower-case e-mail; digits-only phone; two-letter state code |
| licence id (`TB` + year + applicant id) | `license_year`, `license_number` | year parsed **once** during migration into `license_year`; issued licences receive `license_number = TB-<year>-<zero-padded buyer_id>`; the legacy composite id is **not** stored |
| licence existence vs. web-submission status | `status` | issued legacy licences → `ISSUED` with `decided_at = created date`; web-submitted, unissued → `SUBMITTED`; everything else → `DRAFT`; no legacy row maps to `REJECTED` (hard deletes left no trace — recorded as a known gap) |
| bond fields (amount, surety, number) | `bond_amount`, `bond_surety_name`, `bond_number`, `required_bond_amount` | amounts to two decimals; `required_bond_amount` recomputed with BR-01 from the prior-year figure where available, else set to 1000.00 and flagged |
| agent id, names, DOB, suspended | `field_agents.*` | de-duplicate on (last name, first name, DOB) — duplicates merged, crosswalk kept in workspace |
| agent `CurrentLicense`, `Relationship`, `CardPrinted`; bridge `DateAssigned` | `agent_assignments.relationship`, `assigned_on`, `card_printed_at` | `Relationship = "Owner" → OWNER` else `AGENT`; `CardPrinted = True → card_printed_at = licence created date` |
| history rows (`Action = Added/Removed`, `ActionDate`) | `agent_assignments.removed_on` + `audit_events` | pair Added/Removed per (licence, agent) to close assignments; every row also becomes an `audit_events` row with `actor_role = 'Licensing Staff'`, `actor_name = 'migration'` |
| uploaded file (binary), name, type, extension, created on | `supporting_documents.file_name`, `content_type`, `size_bytes`, `uploaded_at`, `vault_reference` | binary extracted to the document vault; `content_type` from extension; `size_bytes` from the blob; checksum recorded in the vault manifest |
| volume-fee rows | `quarterly_fee_reports.quarter`, `purchase_total`, `fee_due` | quarter label `Qn YYYY`; `fee_due` recomputed with BR-03 and compared with the legacy value (difference > $0.01 → report) |

## 3. Validation & reconciliation
| Check | Rule | Outcome |
| :-- | :-- | :-- |
| Row counts | target rows = source rows − quarantined − merged duplicates, per table | must match exactly; otherwise cutover is aborted |
| Checksums | per-table hash of ordered business keys (buyer: hash + DOB; application: buyer + year; agent: name + DOB) compared between extract manifest and target | must match |
| Rule conformance | BR-02 (no agent with two active assignments in a year), BR-04 (no buyer with two non-rejected applications in a year), BR-05 (every application has exactly one OWNER assignment) | violations listed for staff decision before load is committed |
| Identifier hygiene | no raw SSN/FEIN pattern (`\d{3}-\d{2}-\d{4}`, `\d{2}-\d{7}`) in any target text column | zero hits required |
| Document integrity | vault checksum = extracted blob checksum; `size_bytes` > 0 | zero mismatches |
| Spot checks | 25 random applications compared field-by-field on screen by Licensing Staff | signed off |

## 4. Cutover & rollback
1. **Freeze:** announce a read-only window; the legacy database and the previous web application stop accepting changes.
2. **Extract** all source tables and the web submission store to the migration workspace with row counts and manifests.
3. **Cleanse & load** into an empty target database created from `src/db/schema.sql`; write the crosswalks in the workspace only.
4. **Reconcile** per §3; produce the reconciliation report; staff sign-off.
5. **Switch:** publish the new application; staff and buyers use it from this point. The legacy database is archived read-only; the previous web application is decommissioned (DNS removed).
6. **Rollback (within the window only):** discard the target database, lift the freeze on the legacy systems. After the window, rollback is not offered — new data exists only in the target.
7. **Post-cutover:** delete the migration workspace (crosswalks, extracts, salts) after 30 days; keep the signed reconciliation report with the audit trail.

## 5. Retirement list
| Legacy artefact | Decision |
| :-- | :-- |
| Desktop database (all tables, forms, queries, reports, code-behind) | archived read-only, then retired |
| Previous buyer web application and its submission store | retired after cutover |
| Report-close "card printed" update query | retired (explicit print action) |
| Hard-delete handler for unissued applications | retired (Reject transition) |
| Plain-text identifier columns and identifier search | retired (hash + last four) |
| Removal-letter table | retired (audit event; notifications are a later release) |
