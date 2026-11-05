# Employee Leave & Exception Request Portal — source

Zero-dependency stack from `specs/target_stack.json`: static HTML/JS/CSS UI + Python 3 standard-library HTTP
server + SQLite. One process serves everything on port 8766.

## Run

| Command | Value |
| :-- | :-- |
| install | none (Python 3.10+ only) |
| build | none |
| start | `python3 src/backend/server.py` (or `./src/run.sh`) |
| healthcheck | `http://127.0.0.1:8766/health` → `{"status":"ok","database":"ready","today":"2031-03-02"}` |
| UI | `http://127.0.0.1:8766/` |
| test | `python3 -m unittest discover -s src/backend -p 'test_*.py'` |

Run the commands from `<PROJECT_ROOT>` (the directory that contains `src/`).

### Demo mode (default)
`server.py` starts in **demo mode**: the SQLite file (`PORTAL_DB_PATH`, default `<system temp dir>/leave_portal.sqlite`) is recreated from
`src/db/schema.sql`, the clock is fixed at **2031-03-02** (so the 3-day lead-time rule is reproducible) and the
identities / fixtures below are seeded. Use `--no-demo` for the real clock and a persistent, empty database
(`PORTAL_DB_PATH` to relocate it).

Environment: `PORT` (default 8766) · `PAYROLL_BASE_URL` (default: this server's local payroll stub) ·
`PAYROLL_STUB_OUTAGE=1` makes the stub answer 503 so approvals stay *Approved* and raise an alert.

### Demo identities (role switcher in the header)
| Identity | Role | Reference | Notes |
| :-- | :-- | :-- | :-- |
| Alex Rivera | Employee | EMP-10042 | reports to Morgan Lee; 600 h accrued, 40 h taken |
| Sam Chen | Employee | EMP-10077 | reports to Morgan Lee; 40 h accrued, 0 h taken (used for exact balance checks) |
| Jordan Blake | Employee (API only) | EMP-10105 | reports to Casey Ortiz |
| Morgan Lee | Manager | EMP-20001 | |
| Casey Ortiz | Manager (API only) | EMP-20002 | |
| Priya Nair | HR Certifier | EMP-30001 | |
| Payroll Integration | system | SYS-PAYROLL | read-only posting log |

Identity reaches the API through the headers `X-Actor-Role` / `X-Actor-Ref` (pretotype identity adapter in
`server.py: IdentityAdapter`); production replaces the adapter with OIDC token validation.

### Seeded requests
| Reference | Employee | Type | Dates | Hours | Status |
| :-- | :-- | :-- | :-- | :-: | :-- |
| LR-1001 | Alex Rivera | Vacation | 2031-06-09 – 2031-06-13 | 40 | Posted to payroll (PAY-88121) |
| LR-1002 | Alex Rivera | Vacation | 2031-07-07 – 2031-07-08 | 16 | Approved — payroll posting failed (alert) |
| LR-1003 | Jordan Blake | Vacation | 2031-05-19 – 2031-05-20 | 16 | Submitted (other manager) |
| LR-1004 | Jordan Blake | Exception | 2031-04-01 | 8 | Manager approved (in the certification queue) |
| LR-1005 / LR-1007 / LR-1009 | Jordan Blake | Vacation | Dec 2031 / Feb 2032 | 8 | Draft (API fixtures) |
| LR-1006 | Alex Rivera | Vacation | 2031-05-12 | 8 | Submitted (in Morgan Lee's queue) |
| LR-1008 | Jordan Blake | Vacation | 2031-12-15 – 2031-12-16 | 8 | Submitted (API fixture) |

## Layout
```
src/
├── ui/            index.html · app.js · styles.css      (single page, role-separated views, data-testid contract)
├── backend/       server.py (HTTP + identity adapter + payroll client/stub) · workflow.py (TRANSITIONS, BR-01…BR-07)
│                  repositories.py (sqlite3 + demo seed) · viewmodel.py (labels, masking) · test_rules.py
├── db/            schema.sql (authoritative 3NF relational schema); the runtime SQLite file lives outside src/ (PORTAL_DB_PATH)
├── contracts/     openapi.yaml (authoritative OpenAPI 3.1 contract)
└── run.sh         wrapper around the start command
```
