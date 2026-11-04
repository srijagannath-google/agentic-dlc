# Unified User Story Backlog (`backlog/user_stories.md`)

> All functional (`US-FUNC-NN`) and technical (`US-TECH-NN`) stories for the whole application, authored from
> `specs/application_spec.md` after Gate 2. Machine twin: `backlog/user_stories.json` (ARCHITECTURE §4.5).
> AC counts vary by story (4 → 10+); workflow stories always carry role-visibility and prerequisite-gate ACs.

## 0. Coverage
| Source | Items | Covered by stories | Uncovered |
| :-- | :-: | :-- | :-- |
| `REQ-FUNC-*` | | | |
| `REQ-ENH-*` *(legacy only)* | | | |
| `REQ-SEC-*`, `REQ-A11Y-*`, `REQ-UX-*`, `REQ-ARCH-*` | | | |
| §3.3 transitions | | | |
| §3.4 business rules | | | |
| Legacy artefacts *(legacy only)* | | | |

---

## `US-FUNC-NN` — <Story title>
- **Type:** Functional | Technical — **Capability Group:** `GRP-NN (<group name>)` | `SHARED` — **Sprint:** `Sprint N` | `Product Backlog` — **Priority:** Highest|High|Medium|Low — **Points:** 3|5|8
- **Narrative:** As a `<role from spec §3.5>`, I want `<capability>`, so that `<value>`.
- **Requirement refs:** `REQ-…` — **Business rule refs:** `BR-…` — **Workflow transitions:** `FROM->TO, …`
- **Roles:** `<roles>` — **Legacy artefacts replaced** *(legacy only)*: `<objects | none>`
- **Acceptance Criteria**

| AC | Tag | Given | When | Then |
| :-- | :-- | :-- | :-- | :-- |
| AC-01 | `POSITIVE` | | | |
| AC-02 | `NEGATIVE` | | | *(user-readable reason)* |
| AC-03 | `NEGATIVE — ROLE VISIBILITY` | an `external` role is active | the view renders | no control for `<internal transition>` is present |
| AC-04 | `NEGATIVE — WORKFLOW PREREQUISITE GATE` | the record is in `<state>` | `<trigger not allowed from that state>` is attempted | the action is blocked with `<reason>`; state unchanged |
| AC-05 | `POSITIVE — INTERACTIVE COMPLETENESS` | | each control introduced is used | its observable DOM/data effect |
| AC-06 | `EDGE / BOUNDARY` | input at `<threshold>` / `<threshold ± 1 unit>` | | exact expected value/status |
