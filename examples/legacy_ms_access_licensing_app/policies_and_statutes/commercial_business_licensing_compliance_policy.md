# Commercial Business Licensing Policy (CBL-101) — Excerpt for Application Design

> **Purpose:** Authoritative business rules for the Business Licensing & Renewal Portal.

## Section 4 — Surety Bond Requirement (`BR-01`)
Every Commercial Buyer applying for an annual license must file and maintain a performance surety bond:
- **Principal calculation:** `10%` of the total dollar value of prior-year licensed purchases, rounded to the nearest cent (`round_half_up`).
- **Minimum bond:** `$1,000.00` USD (applies to new applicants or when `10%` of prior-year purchases is less than `$1,000.00`).
- **Formula:** `required_bond_amount = max(1000.00, round_half_up(0.10 * prior_year_purchases, 2))`.

## Section 6 — Field Agent Exclusivity (`BR-02`)
- No person may be registered as an active Field Agent for more than **one (1)** licensed Commercial Buyer in the same calendar license year.
- The license holder is automatically recorded as the primary `OWNER` agent on their own license (`BR-05`) and cannot be removed while the application is active.

## Section 9a — Quarterly Volume Fee (`BR-03`)
- Every licensed Commercial Buyer must file a quarterly purchase report and remit a **`4%` volume fee** on total quarterly purchases (`fee_due = round_half_up(0.04 * purchase_total, 2)`).
