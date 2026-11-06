---
name: 06-coding-agent
description: "Stage 5 of the Agentic DLC v4. coding-agent (The Goldfish, clean context) builds a RUNNABLE application for the stack in specs/target_stack.json strictly from the approved upstream artefacts — spec, approved stories/sprint plan, solution design + extracted contracts, test/test_cases.json (contract-first data-testids), design references — with state-table-driven guards in UI and backend, role-separated views, live business rules, zero dead controls and zero internal identifiers in visible text; verified by 06/scripts/validate_build.py. Use when asked to build the app, UI or backend."
---

# Stage 5 — Clean-Context Build of a Runnable Application

**Read before acting:** `_shared/project_root.md`, `_shared/ux_guardrails.md`, `_shared/google_cloud_ui_design.md`,
`skills/google-cloud-ui-design/SKILL.md` (plus `skills/google-cloud-ui-design/references/tokens-and-accessibility.md`
and the matching layout blueprint in `skills/google-cloud-ui-design/references/*.md`), `_shared/zero_leak.md`,
`_shared/workflow_chain_of_custody.md` ("Stage 5"), `docs/ARCHITECTURE.md` §3, §4.2. Subagent: `coding-agent`,
invoked **in a fresh context** with only the inputs below.

## Inputs (the only files the coder may read)
1. `specs/application_spec.md` — §3.3 state table, §3.4 rules, §3.5 roles, Pillar 2 PII list, §4 UX overrides
2. `backlog/user_stories.json` + `backlog/sprint_plan.md` — build the `Sprint 1..N` scope (which reflects the human-selected `selectedCapabilityGroups`: either the selected `GRP-*` group(s) + `SHARED` technical stories, or **all** capability groups when `selectedCapabilityGroups` is `["ALL"]`)
3. `design/architecture_design.md`, `design/solution_design.md`, `src/contracts/openapi.yaml`, `src/db/schema.sql`
4. `test/test_cases.json` (+ `test/test_plan.md`) — the `data-testid` selectors and behaviours to satisfy
5. `specs/target_stack.json` (including `selectedCapabilityGroups`); `resources/design_references/`, `resources/shared_services/` if present

`resources/inputs/` is off-limits: legacy sources and requirements documents never enter the coder's context.
Gaps are reported upstream, not reconstructed.

## Outputs
| Path | Content |
| :-- | :-- |
| `src/ui/…` | frontend per `target_stack.frontend` |
| `src/backend/…` | backend per `target_stack.backend` (serves UI + `/api/*` + healthcheck) |
| `src/db/schema.sql` (+ migrations) | from 4A; add migrations only, never rewrite the extracted file silently |
| `src/run.sh` \| `Makefile` \| `docker-compose.yml` | the commands in `target_stack.json#commands`, verbatim |
| `src/README.md` | how to install, run, test; which role/test accounts exist; where the DB lives |

## Procedure

### 1. Design-reference & Google Cloud UI Design System ingestion (`google-cloud-ui-design`)
- Inspect `specs/design_reference/reference_ui_manifest.json` and `specs/design_reference/screenshots/`
  when present: apply the extracted CSS custom properties (`designTokens`), header/banner and accent colours, font
  families, border radii, and view/tab topology (`views` + `wizardSteps`).
- When user design references do not override the palette/layout, apply the **Google Cloud UI Design System**
  (`<PLUGIN>/_shared/google_cloud_ui_design.md` and `<PLUGIN>/skills/google-cloud-ui-design/SKILL.md`):
  1. **Surface Mode & Layout Archetype:** Match each view to its declared Surface Mode (`Operate` | `Read` | `Persuade` | `Express`) and corresponding blueprint in `<PLUGIN>/skills/google-cloud-ui-design/references/` (`admin-dashboard.md`, `master-detail-workspace.md`, `gis-map-telemetry.md`, `document-auditor.md`, `marketing-landing.md`, or `ai-agent-workspace.md`). Never mix modes on the same viewport (no marketing hero banners inside an `Operate` workspace).
  2. **Google Material 3 / Cloud Console Token System (`--g-*`) & Theme Provider:** Define the `:root` (Light) and `.dark` (Dark) `--g-*` CSS custom properties (`--g-bg`, `--g-surface`, `--g-surface-dim`, `--g-surface-high`, `--g-ink`, `--g-ink-secondary`, `--g-ink-muted`, `--g-border`, `--g-border-subtle`, `--g-blue`, `--g-green`, `--g-amber`, `--g-amber-text`, `--g-red`, `--g-purple`) in `globals.css` / `styles.css`. Default to `defaultTheme="system"` via `window.matchMedia("(prefers-color-scheme: dark)")` with a 3-way `System | Light | Dark` theme switcher.
  3. **ShadCN UI + Radix Primitives (for React/Next.js stacks):** Use ShadCN UI (`@radix-ui/*`) + Tailwind CSS + `lucide-react` (`size={16}`/`{18}`, `strokeWidth={1.75}`) + `sonner` (`<Toaster />`) + `@tanstack/react-table` + `react-resizable-panels` (`50/50` split with `ResizableHandle withHandle`, `col-resize` cursor, double-click reset to `50/50`).
  4. **Unified Surfaces & Anti-Slop Craft Floor:** Render KPI strips and detail panels as a **single unified surface** (`rounded-xl border border-[var(--g-border)] bg-[var(--g-surface)]`) divided by `1px solid var(--g-border-subtle)` hairlines (`divide-x`, `divide-y`, `<Separator />`) and semantic `<dl>` (`<dt>`/`<dd>`) grids — never wrap individual metadata fields or KPIs in separate mini-cards ("card soup") or nest scrollbars. Enforce all 8 Anti-Slop bans (no purple-to-blue gradients, no neon dark-mode halos, no glassmorphism on tables/forms, no rainbow KPI numbers/icons, `<Badge>` only on Status column or finding Severity, no raw JSON or model SKU strings in UI chrome).
- Stamp whatever design reference or Google Cloud UI Design archetype was applied in `<body data-design-references="…" data-surface-mode="…">`.

### 2. Build to the Target Stack Contract — Dual-Mode Architecture (Testable Locally AND Deployable to Target Cloud/GDC Environment)
> **CRITICAL MANDATE — NEVER Ignore `specs/target_stack.json` or Substitute a Throwaway Python App:**
> You MUST build `src/ui/` and `src/backend/` in the **confirmed Future-State Target Stack** declared in `specs/target_stack.json#{frontend,backend,database}` and `design/architecture_design.md`. **Never** discard the recommended target stack (`react`, `angular`, `vue`, `nextjs`, `java-spring-boot`, `node-express`, `python-fastapi`, `python-flask`, `go`, `dotnet`, `postgres`, `alloydb-omni`) and build a standalone `python-stdlib-http` (`server.py`) + `static-html` substitute just for local testing (`06/scripts/validate_build.py` inspects `src/ui/` and `src/backend/` for the target-stack project manifests and source files and **fails Gate 5** if they are missing).

1. **Author the Full Target-Stack Codebase in `src/ui/` and `src/backend/`:**
   - **`frontend.kind == "react" | "nextjs"`:** `src/ui/package.json`, `tsconfig.json`, `vite.config.ts` / `next.config.js`, modular `.tsx`/`.jsx` components, state-driven role views, and build output (`dist/` or `build/`).
   - **`frontend.kind == "angular"`:** `src/ui/package.json`, `angular.json`, `tsconfig.json`, modular `.component.ts`/`.component.html` components and services.
   - **`frontend.kind == "vue"`:** `src/ui/package.json`, `vite.config.ts`, modular `.vue` single-file components and services.
   - **`frontend.kind == "gemini-enterprise-a2ui"`:** declarative `A2UI v0.9` agent surface (`skills/google-cloud-ui-design/references/gemini-enterprise-a2ui.md`) emitting `createSurface` / `updateComponents` / `updateDataModel` envelopes bound to registered `--g-*` ShadCN catalog widgets alongside a dual-mode local web host.
   - **`frontend.kind == "static-html"` (only when explicitly chosen in `target_stack.json`):** `src/ui/index.html`, `src/ui/app.js`, `src/ui/styles.css` (render all views in DOM and toggle `[role="tabpanel"]` `hidden` state so static a11y/leak lint inspects every view).
   - **`backend.kind == "java-spring-boot"`:** `src/backend/pom.xml` (or `build.gradle`), `src/backend/src/main/java/...` (`@SpringBootApplication`, `@RestController` controllers implementing `src/contracts/openapi.yaml`, `@Service` workflow state machine & `BR-*` rule engine, `@Repository`/JPA/JDBC persistence), and `src/backend/src/main/resources/application.yml` supporting `spring.profiles.active=${APP_ENV:local}` and `DATABASE_URL`.
   - **`backend.kind == "node-express"`:** `src/backend/package.json`, `src/backend/src/` (`.ts`/`.js` Express/Fastify routes, workflow & `BR-*` rule services, `pg`/SQLite dual-mode repository adapter reading `DATABASE_URL` and `APP_ENV`).
   - **`backend.kind == "python-fastapi"` or `"python-flask"`:** `src/backend/requirements.txt` (or `pyproject.toml`), `src/backend/app/` (`FastAPI`/`Flask` routers, Pydantic/DTO ViewModels, SQLAlchemy/`psycopg` connection pool reading `DATABASE_URL` in `APP_ENV=production` with local embedded DB fallback in `APP_ENV=local`, ASGI/WSGI entrypoint).
   - **`backend.kind == "go"`:** `src/backend/go.mod`, `cmd/server/main.go`, `internal/{api,workflow,rules,store}/` (`database/sql` reading `DATABASE_URL` with local fallback).
   - **`backend.kind == "dotnet"`:** `src/backend/*.csproj`, `Program.cs`, `Controllers/`, `Services/`, `Data/`, `appsettings.json` + `appsettings.Development.json` reading `ConnectionStrings__DefaultConnection` / `DATABASE_URL`.
   - **`backend.kind == "python-stdlib-http"` (only when `target_stack.json` explicitly sets `python-stdlib-http`):** Python 3.10+ `http.server` + `sqlite3` created from `src/db/schema.sql`.

2. **12-Factor Dual-Mode Configuration (`APP_ENV=local` vs `APP_ENV=production`):**
   Wire `src/backend/`, `src/ui/`, `src/run.sh`, and `src/docker-compose.yml` so the **same codebase** runs seamlessly in both modes:
   - **Local Test & Evaluation Mode (`APP_ENV=local`, default via `bash src/run.sh`):**
     - Uses `DATABASE_URL` if set on the host, or auto-initializes a local embedded database from `src/db/schema.sql` + deterministic demo seed data so `validate_build.py` and `run_closed_loop_eval.py` run locally with zero external cloud dependencies.
     - Enables `AUTH_MODE=local-mock` (`<select data-testid="role-switcher">` and `X-Actor-Role` header) while enforcing the exact `Spec §3.3` state table and `Spec §3.5` RBAC rules.
     - **Offline Sandbox Resilience in `src/run.sh`:** `src/run.sh` MUST first detect and execute the native target-stack toolchain on `PATH` (`mvn`/`java`, `npm`/`node`, `uvicorn`/`gunicorn`, `go`, `dotnet`). If executed inside an air-gapped evaluation container where the external package manager (`mvn`, `npm`, `go`, `dotnet`, `uvicorn`) is not installed on `PATH`, `src/run.sh` may fall back to a local contract-faithful dev runner (`src/backend/local_dev_runner.py` or pre-bundled asset server) that executes against the **exact same `src/db/schema.sql`, `src/contracts/openapi.yaml`, and `src/ui/`** — while keeping the complete target-stack source code and manifests (`pom.xml`, `package.json`, `.java`/`.tsx`/`.ts`/`.go`/`.cs`) in `src/backend/` and `src/ui/` for target environment container builds.
   - **Target Cloud / GDC Deployment Mode (`APP_ENV=production`, via `deploy/containers/Dockerfile.*` & `deploy/gdc/`):**
     - Connects to the target managed database (`AlloyDB for PostgreSQL` / `Cloud SQL` / `PostgreSQL` / `MySQL` / `SQL Server`) via `DATABASE_URL` with connection pooling (`PgBouncer` / HikariCP / SQLAlchemy pool).
     - Enforces `AUTH_MODE=oidc-iap` (validating Google Cloud IAP / OIDC JWT bearer tokens and disabling the demo role-switcher override).
     - Emits structured JSON logs (`severity`, `httpRequest`, `trace`, `actorRole`, `capabilityGroup`) to stdout and exports telemetry to `OTEL_EXPORTER_OTLP_ENDPOINT`.
   - `src/README.md` + `src/run.sh` + `src/docker-compose.yml` must document both **Local Testing (`APP_ENV=local`, `bash src/run.sh`)** and **Target Cloud Deployment (`APP_ENV=production`, `docker compose up --build` / GDC Fleet)**.

### 3. Implement the workflow once, enforce it twice (with mutual tab exclusivity & default-persona reachability)
Encode the §3.3 table as one data structure shared (or duplicated verbatim) by UI and backend:
- **UI:** controls render/enable from `(currentState, currentRole)`; external-role views contain no
  internal-transition control; role switcher only if §3.5 has more than one role; initial role = the primary
  `external` role when one exists, landing in the initial lifecycle state (`Draft` / entry state) with the primary
  forward transition CTA (e.g., `Submit`) immediately reachable (`Guardrail #11`).
- **View & tab mutual exclusivity (`Guardrail #3`):** every top-level `[role="tab"]` in `[role="tablist"]` must wire
  `aria-controls="<panel-id>"` and `aria-selected="true|false"` to a corresponding `[role="tabpanel"]` container, and
  clicking a tab must set `hidden = false` (non-zero bounding box) on its target `[role="tabpanel"]` while setting
  `hidden = true` (`display: none`, zero bounding box) on all sibling `[role="tabpanel"]` containers. Multi-step
  wizards must support interactive step switching (`Next Step` / `Previous Step` / step indicators), and changing a
  lifecycle state selector must reactively update available transition controls or display which role owns the next
  transition.
- **Backend:** every transition endpoint validates `(fromState, trigger, role)` and returns 4xx + readable
  `message` otherwise. The UI is never the only guard. When `target_stack.json#commands.reset` is configured (e.g., `POST /__test/reset` enabled strictly under `APP_ENV=local`), re-seed deterministic fixture state between Stage 6 tests and disable the endpoint (`404`) under `APP_ENV=production`.
- **Guardrail Contract Pragmas (`@dlc-*`):** Annotate transition guards with `@dlc-guard:<From>-><To>`, business-rule calculations with `@dlc-rule:BR-NN`, PII masking helpers with `@dlc-mask:<field>`, and custom accessibility widgets with `@dlc-a11y:<rule>` so Stage 4A/Stage 6 diff auditing (`design/.contracts_index.json#guardrailBindings`) binds hunks with deterministic precision.

### 4. Business rules, labels, leakage
- Every `BR-NN` depending on input recomputes on `input`; one semantic status element per view; validation
  messages say what failed and the fix.
- All states/enums/errors go through the ViewModel label dictionary from the design; PII masked in the
  ViewModel; no engineering commentary in rendered text; technical ids only in attributes.

### 5. Contract-first ids, 4-state coverage, numeric discipline & accessibility
- Implement every `data-testid` in `test/test_cases.json`; missing ids are Stage 6 failures, not test bugs.
- Every button/link/tab/row action/dropzone/filter/modal trigger has a handler with a visible effect; lists
  and detail views bind to live state; implement complete **4-state coverage** (**Loading** `Skeleton`, **Empty** icon + explanation + recovery action, **Error** plain explanation + inline `Retry` + `<details>`, **Populated/Extreme** with `tabular-nums` and sticky headers).
- Apply `font-variant-numeric: tabular-nums` (`tabular-nums`) to all KPI numbers, currency amounts, percentages, counts, timestamps, and right-aligned numeric table columns (`text-right font-mono tabular-nums`).
- Action-oriented `[Verb] + [Object]` button labels; at least `8px` (`gap-2`) separation between primary and destructive actions; `cursor: pointer` on all enabled interactive elements and symmetrical `12px` `<select>` caret padding in `@layer base`.
- WCAG 2.1 AA (+ named standards): `<a href="#main-content">Skip to main content</a>` first in `<body>`, semantic HTML5 landmarks (`<header>`, `<nav aria-label>`, `<main id="main-content">`, `<section>`, `<aside>`, `<dl>`, `<footer>`, `<table>`), labelled inputs, keyboard operability, modal focus management, `aria-live` for validation/status, contrast tokens (`--g-amber-text: #B06000` in light mode), status never by colour alone.
- UX & Google Cloud UI Design guardrails (`_shared/ux_guardrails.md` and `_shared/google_cloud_ui_design.md`) are defaults; design references / §4 overrides win.

### 6. Verify
```bash
python3 <PLUGIN>/skills/06-coding-agent/scripts/validate_build.py --project-root "<PROJECT_ROOT>"
```
Runs `install` → `build` → `start` → polls `healthcheck` → optional `test` → stops the process, and automatically transitions active sprint stories from `To Do` to `In Progress` in `backlog/` and on Jira / Azure DevOps via `alm_jira_ado_bridge.py --action transition-stories --target-status "In Progress" --scope active-sprints --only-from-todo`. Fix until green.

### 7. Mandatory STOP at Gate 5 (`gate_5_build`) — Wait for Human Build Review & Approval
`validate_build.py` stamps `gate_5_build = AWAITING_HUMAN_REVIEW` in `specs/gate_approvals.json`, blocking Stage 6 (`run_closed_loop_eval.py`).
1. Report what was built in `src/`, the local run command (`bash src/run.sh`), applied design references, and any upstream gap found.
2. **END YOUR TURN IMMEDIATELY (call zero further tools). NEVER start Stage 6 (`07-test-runner-and-healer`) in the same turn!**
3. Only **in a subsequent turn AFTER the human reviews and approves Gate 5**, run:
   ```bash
   python3 <PLUGIN>/scripts/gate_tracker.py --project-root "<PROJECT_ROOT>" --action approve --gate gate_5_build --user-response "<verbatim user approval quote>"
   ```
   and then proceed to `07-test-runner-and-healer`.

**Scenario differences:** none in this stage by design — the coder sees only derived artefacts. (Legacy
projects simply have no legacy names anywhere in `src/`; `TC-UI-LEAK-*` checks that.)

## Do not
- Start Stage 5 before `gate_4_design_and_tests` is `APPROVED_BY_USER`, or auto-start Stage 6 before `gate_5_build` is `APPROVED_BY_USER`.
- Read raw inputs; reproduce legacy screens, naming or fixed-width/dual-run adapters.
- Invent screens, steps, roles or formulas; hard-code values a test expects; add dependencies the stack
  does not name.
- Write outside `<PROJECT_ROOT>/src/`.
