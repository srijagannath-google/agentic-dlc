# Zero Internal Data Leakage in UI (`REQ-UX-ZERO-LEAK`) — canonical copy (shared)

## The rule
Visible UI text (labels, headings, badges, table cells, tooltips, modal bodies, validation banners, `alt`,
`title`, `aria-label`) must contain **none** of:

1. database table/column identifiers (anything that appears as a table or column name in `src/db/schema.sql`
   or as an internal field in `src/contracts/openapi.yaml` schemas marked `x-internal: true`);
2. raw machine enum / status / error codes (`UPPER_SNAKE_CASE` tokens that appear in the spec state table or
   OpenAPI enums) — the UI shows the human label from spec §3.3 instead;
3. internal UUIDs / primary keys / hashes;
4. legacy identifiers from the input estate (file stems and object names in `specs/input_inventory.json`
   `files[].name` for legacy categories, e.g. form/report/query/table object names) and engineering notes
   such as "parity", "TODO", "FIXME", stack traces, SQL fragments, API paths;
5. unmasked PII patterns the spec marks as sensitive (national IDs, tax IDs, full card numbers).

`data-testid` and other **attributes** are allowed to carry stable technical identifiers; visible text is not.

## How the token list is built (no hand-written lists)
`05/scripts/derive_test_cases.py` writes `test/test_cases.json#forbiddenUiTokens` from:
- `src/db/schema.sql` → table and column names (`schemaIdentifiers`);
- `specs/application_spec.md` §3.3 state table (states + triggers) and underscore-containing OpenAPI enum members → `enumCodes` (fail); other all-caps enum members → `enumCodesWarnOnly` (warn);
- `specs/input_inventory.json` legacy file stems/object names → `legacyIdentifiers`;
- spec §2 PII list → `piiPatterns` (regexes).

`07/scripts/run_closed_loop_eval.py` scans the **rendered** visible text (after JS runs, every role/view) and
reports each hit with its surrounding context. Generic heuristics (`[A-Z]{2,}_[A-Z0-9_]{3,}`, UUID regex)
are reported as **warnings**, not failures, to avoid false positives like `ISO_8601`.

## What the coding agent must do
- Map every state/enum/error code to a label dictionary at the presentation boundary (ViewModel/DTO layer in
  `design/solution_design.md §4`).
- Never put engineering commentary in rendered text. Comments go in code comments.
- Mask PII in ViewModels, not in the template.
