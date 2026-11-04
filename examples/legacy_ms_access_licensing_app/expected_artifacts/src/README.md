# Business Licensing & Renewal Portal — Release 1 (runnable pretotype)

Zero-dependency stack: static HTML/JavaScript UI + Python standard-library HTTP backend + SQLite.
Everything is served by **one process on port 8767**; the backend enforces the lifecycle state table and the
role matrix from `specs/application_spec.md` on every request (the UI is never the only guard).

## Run

| Command (`specs/target_stack.json#commands`) | Value |
| :-- | :-- |
| install / build | none (Python ≥ 3.10 standard library only) |
| start | `python3 src/backend/server.py` (or `sh src/run.sh`) |
| healthcheck | `http://127.0.0.1:8767/health` → `{"status":"ok","database":"ok","version":"1.0.0"}` |
| UI | `http://127.0.0.1:8767/` |
| test | `python3 src/backend/server.py --self-test` (business rules BR-01/BR-03, state table, role guards; compares the state table with `specs/.spec_index.json` when present) |

Environment variables: `PORT` (default `8767`), `APP_DB_PATH` (default `src/backend/data/licensing.db`),
`APP_DB_RESET` (`1` = recreate the database from `src/db/schema.sql` and reload the demo data on every start — the
default for the pretotype so every run is reproducible; set `0` to keep data between starts), `APP_TAX_ID_SALT`.

## Layout
- `src/ui/index.html`, `src/ui/app.js`, `src/ui/styles.css` — single-page UI; `data-testid` attributes implement the contract in `test/test_cases.json`.
- `src/backend/server.py` — rules → workflow → repository → ViewModel → HTTP handlers (sections in that order).
- `src/db/schema.sql` — extracted from `design/solution_design.md` (3NF, snake_case, status `CHECK` constraints).
- `src/contracts/openapi.yaml` — extracted from `design/solution_design.md`; the role is sent as the `X-Role` header
  (`Commercial Buyer` | `Licensing Staff`) and the display name as `X-Actor`. In production both come from the identity service.

## Roles (role switcher in the header)
- **Commercial Buyer** (external, initial view): New application (4 steps), My applications (open by application number, timeline, documents, quarterly fee reports), Fee calculator.
- **Licensing Staff** (internal): Review queue (filter by status), application review (issue / reject / print / roster), Buyers registry, Agents registry (suspend / reinstate).

## Demo data (loaded when the database is created; licence year 2026)
| Application | Buyer | Status | Notes |
| :-- | :-- | :-- | :-- |
| APP-2026-000001 | Acme Commercial Services | Draft | no documents |
| APP-2026-000002 | Apex Retail Group | Submitted | one document attached; masked identifier `**-***4567` |
| APP-2026-000003 | Horizon Logistics | Licence issued `TB-2026-00003` | agent Dale Whitaker (born 1979-03-14) assigned |
| APP-2026-000004 | Oakridge Distribution | Rejected | reason recorded |
| APP-2026-000005 | Northwind Commerce | Submitted | buyer suspended — issue is blocked |
| APP-2026-000006 … 000010 | Cedar Ridge Buyers, Heartland Enterprise Partners, Vanguard Industrial Products, Summit Valley Supply, Metro Trade | Submitted | review fixtures |

Agents: Alex Alvarez (born 1990-11-23) is suspended; Marcus Lee (1988-07-02) and Priya Natarajan (1985-12-01) are unassigned.
Demo tax identifiers (never shown by the application): Apex Retail Group `12-3454567`; all other demo buyers use `NN-NNNNNNN` values listed in `server.py#seed_demo_data`.

## Security notes
Tax identifiers are hashed (salted SHA-256) at capture and only the last four digits are stored; API responses carry the
masked form only. Identifiers are not searchable. TLS termination and at-rest encryption of the database file and
document vault are provided by the deployment platform (see `specs/application_spec.md` Pillar 2).
