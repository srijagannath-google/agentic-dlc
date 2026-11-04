---
name: 01-discovery-and-grouping
description: "Stage 1 of the Agentic DLC v4. Confirms the input source location with the user first (local resources/inputs/, local folder path, Azure DevOps Git repository via --ado-repo, or Git repository via --git-repo), scans inputs into specs/input_inventory.json, classifies the scenario (SCENARIO_LEGACY_APP vs SCENARIO_REQUIREMENTS_DOC), has discovery-architect author specs/discovery_architecture_and_inventory.md strictly documenting the Current State ('As-Is' data model ERD, legacy object inventory, evidenced current-state workflow/state machine, roles, business rules, pain points, capability inventory, and §6.1 business capability groupings — never mixing in future-state 3NF schemas or future-state flow diagrams), runs Gate 1 context intake and records specs/target_stack.json. Use when asked to analyse a legacy app, Azure DevOps / Git repository, database export, BRD/PRD/RFP or existing spec."
---

# Stage 1 — Current-State ("As-Is") Discovery, Capability Grouping & Gate 1 Intake

**Read before acting:** `_shared/project_root.md`, `_shared/workflow_chain_of_custody.md`,
`docs/ARCHITECTURE.md` §4.1–§4.2. Subagent: `discovery-architect`. `<PLUGIN>` = installed plugin dir.

> **Strict Current-State ("As-Is") Boundary:** `specs/discovery_architecture_and_inventory.md` documents **only the Current State ("As-Is")** of the legacy application or input problem domain. **Never** combine Future-State ("To-Be") 3NF ERDs, target SQL DDL, future-state component/flow diagrams, or Legacy-to-Target entity mappings into Stage 1 — all future-state architecture, target 3NF schemas, and legacy-to-target mappings belong exclusively in Stage 4A (`design/solution_design.md` and `design/data_migration_and_cutover.md`).

## Inputs
`<PROJECT_ROOT>/resources/inputs/` (legacy exports, cloned Azure DevOps / Git repositories, **or** requirements documents),
`resources/policies_and_statutes/`, `resources/design_references/`, `resources/shared_services/` (all optional
except the primary input source). Never seed synthetic sample inputs.

## Outputs
| File | Author | Checked by |
| :-- | :-- | :-- |
| `specs/input_inventory.json` | script | schema `schemas/input_inventory.schema.json` |
| `specs/discovery_architecture_and_inventory.md` | `discovery-architect` (strictly Current-State "As-Is") | `01/scripts/validate_discovery_blueprint.py` |
| `specs/target_stack.json` | `discovery-architect` (from Gate 1 answers / defaults) | schema `schemas/target_stack.schema.json`; required by Stages 4A/5/6 |

## Procedure

### 0. Confirm the Input Source Location with the User (Mandatory Before Scanning)
Before running `scan_input_sources.py` (unless the user's prompt already explicitly specified the input source URL/path or `--autonomous` mode was requested with an already-populated `<PROJECT_ROOT>/resources/inputs/`), **ask the user where their input source is located**:

1. **Azure DevOps (ADO) Repository (`--ado-repo`):**
   - Ask for the **ADO Repository URL** (`https://dev.azure.com/<org>/<project>/_git/<repo>`) or **repository name** (if `ADO_ORG_URL` and `ADO_PROJECT` are set in `.env`), optional branch (`--ado-branch`), and verify `ADO_PAT` is configured in `<PROJECT_ROOT>/.env` or `~/.gemini/config/agentic-dlc.env`.
2. **Git Repository (`--git-repo` — GitHub, GitLab, Bitbucket, etc.):**
   - Ask for the **Git Repository URL**, optional branch (`--git-branch`), and `GIT_TOKEN` / `GITHUB_TOKEN` if private.
3. **Existing Local Directory / Checkout (`--input-dir`):**
   - Ask for the local filesystem path to the existing source code folder, database export, or requirements document directory.
4. **Project `<PROJECT_ROOT>/resources/inputs/` Folder:**
   - Confirm the user has placed their legacy exports (`.sql`, `.cs`, `.vb`, `.frm`, `.xsd`, etc.) or requirements documents (BRD/PRD/RFP `.md`, `.docx`, `.pdf`, `.txt`) inside `<PROJECT_ROOT>/resources/inputs/`.

Do **not** proceed with Stage 1 scanning until the user confirms where the input source is located.

### 1. Ingest (if remote), scan, classify, and capture any live design reference URL
```bash
# If the user provided a reference portal URL (in prompt or resources/design_references/*.url/.txt/.html), crawl it first:
python3 <PLUGIN>/skills/01-discovery-and-grouping/scripts/capture_design_reference.py --project-root "<PROJECT_ROOT>" [--url "<REFERENCE_URL>"]

# Option A — Input is in <PROJECT_ROOT>/resources/inputs/:
python3 <PLUGIN>/skills/01-discovery-and-grouping/scripts/scan_input_sources.py --project-root "<PROJECT_ROOT>"

# Option B — Input is in an Azure DevOps (ADO) Git repository:
python3 <PLUGIN>/skills/01-discovery-and-grouping/scripts/scan_input_sources.py --project-root "<PROJECT_ROOT>" \
  --ado-repo "<ADO_REPO_URL_OR_NAME>" [--ado-branch "<BRANCH>"] [--ado-org-url "<ORG_URL>"] [--ado-project "<PROJECT>"]

# Option C — Input is in a GitHub / GitLab / generic Git repository:
python3 <PLUGIN>/skills/01-discovery-and-grouping/scripts/scan_input_sources.py --project-root "<PROJECT_ROOT>" \
  --git-repo "<GIT_REPO_URL>" [--git-branch "<BRANCH>"]

# Option D — Input is in another local directory on disk:
python3 <PLUGIN>/skills/01-discovery-and-grouping/scripts/scan_input_sources.py --project-root "<PROJECT_ROOT>" \
  --input-dir "<LOCAL_SOURCE_PATH>"
```
When `--ado-repo` or `--git-repo` is passed, `scan_input_sources.py` authenticates via `ADO_PAT` / `GIT_TOKEN` (using transient HTTP headers so tokens are never persisted in `.git/config`, with an automatic fallback to the Azure DevOps Git Items REST API v7.1 if `git` CLI is unavailable), shallow-clones/updates the repository under `<PROJECT_ROOT>/resources/inputs/<repo-slug>/`, automatically filters out build/VCS noise (`.git/`, `node_modules/`, `bin/`, `obj/`, `packages/`, `dist/`, `build/`, `target/`), and records `sourceRepository` provenance (`provider`, `repositoryUrl`, `branch`, `commitSha`, `localCheckoutPath`) in `specs/input_inventory.json`.

When a reference URL or prototype is present, `capture_design_reference.py` launches a headless browser at desktop (`1440×900`) and mobile (`390×844`) viewports, clicks every top-level `[role="tab"]` / navigation route and wizard step, saves per-tab screenshots under `resources/design_references/screenshots/`, and writes `resources/design_references/reference_ui_manifest.json` (CSS custom properties, colours, typography, border radii, and view/tab topology).
Read the scan result: `inputScenario`, `scenarioConfidence`, `scenarioEvidence`, `sourceRepository`, `hasPoliciesOrStatutes`,
`hasUserProvidedDesignReferences`, `domainSlug`, `files[].category`.
- `scenarioConfidence == LOW` (mixed or thin inputs) → ask the user which scenario applies before step 2.
- Classification drives every later stage (`includeModernizationEnhancementsInSpec`, legacy mapping, migration
  doc). Do not override it silently; if the user corrects it, re-run the scan with their answer recorded.

### 2. Author the Current-State ("As-Is") discovery blueprint
Use `resources/discovery_template.md` as the section skeleton. Content rules:
1. **Executive summary is narrative** (business context, current-state assessment or current-state problem statement,
   governing rules) — never a list of input filenames; files are itemised in the inventory sections.
2. **Current-State ("As-Is") Data Model (`erDiagram`)**: document the existing tables/entities and relationships as they exist today in the legacy application (or the current-state conceptual entities in the requirements document). Do **not** include the future-state 3NF target schema or Legacy-to-Target entity mapping here; those belong in Stage 4A (`design/solution_design.md`).
3. **Current-State ("As-Is") Workflow & Lifecycle State Machine**: `stateDiagram-v2` **plus** the transition table
   `| From | To | Trigger | Actor Role | Guard | Evidence |`. Every row cites where it came from.
4. **Current-State Roles** `| Role | Kind | Responsibilities | Evidence |` (Kind = `external` or `internal`; never a pipe inside a header cell), **business rules**
   `| Rule ID | Rule / Formula | Inputs | Source |`, the **capability inventory** (`CAP-*`), and **§6.1 Business Capability Groupings**
   `| Group ID | Group Name | Grouping Dimension | Capabilities | Prerequisite Groups / Shared | Legacy Artefacts / Source Scope | Notes |` — grouping all discovered capabilities (`CAP-*`) into logical groups (`GRP-01..N`) either by **Business Functionality (`functional`)** or by the **Business Unit / Department (`business-unit`)** the application supports, and explicitly identifying **Shared Foundation / Prerequisite Groups (`isSharedFoundation: true` / `dependsOnGroups: ["GRP-01"]`)** (such as shared entity registries, core intake records, common document vaults, or shared identity/audit services) that must be built first in Group 1 / Sprint 1 when any dependent group is selected.
5. **Open workflow questions (§3.1)** — every item from `_shared/workflow_chain_of_custody.md` "Ask-don't-assume"
   the inputs do not settle.
6. **Project name is domain-pure**: no stack names in the title, entity names or capability headers.

**Scenario differences**
| | `SCENARIO_LEGACY_APP` | `SCENARIO_REQUIREMENTS_DOC` |
| :-- | :-- | :-- |
| State machine source | status columns/enums, form event handlers, status-filtered queries, report criteria | documented process steps, approval paths, SLAs, actor descriptions |
| §2.1 current-state legacy object inventory | **required** (`Legacy object → object type → current-state role & key fields → observed limitations → evidence`; future-state Legacy→Target mapping is deferred to Stage 4A `design/solution_design.md`) | **omit** |
| §5 current-state pain points & technical debt | **required** (observed current-state gaps and risks with evidence) | **omit** — scope is the document |
| Future-state 3NF ERD, flow diagrams & DDL | **forbidden in Stage 1** — placed in Stage 4A (`design/solution_design.md` & `design/data_migration_and_cutover.md`) | **forbidden in Stage 1** — placed in Stage 4A (`design/solution_design.md`) |
| Capability inventory & §6.1 groupings | one row per legacy form/report/query/module cluster, grouped in §6.1 by **Business Functionality** or **Business Unit/Department** | one row per actor journey / documented capability / NFR, grouped in §6.1 by functional area or organizational unit |

### 3. Validate
```bash
python3 <PLUGIN>/skills/01-discovery-and-grouping/scripts/validate_discovery_blueprint.py --project-root "<PROJECT_ROOT>"
```
Fix the blueprint until it passes (required sections, current-state ERD & legacy inventory, both state representations, tables parse, no future-state 3NF/DDL/Legacy-to-Target mapping mixed into Stage 1, no stack names in the title, no filename dumps in §1).

### 4. Gate 1 — context intake & capability group selection (interactive) / defaults (autonomous)
Present the current-state discovery summary, the **§6.1 Business Capability Groupings (`GRP-01..N`)**, and the open workflow questions first; then confirm:
1. **Business Capability Grouping & Selected Group(s) to take forward:**
   - Confirm whether capabilities should be grouped by **Business Functionality (`functional`)** or by **Business Unit / Department (`business-unit`)**.
   - Ask which **Capability Group(s)** the user wants to take forward for implementation:
     - **Specific Group(s)** (e.g., `["GRP-01"]` or `["GRP-01", "GRP-02"]`) — all user stories will still be authored during Spec/Backlog (Stages 2–3), grouped by Capability Group, with the selected group(s) (plus any shared prerequisite group such as `GRP-01`) scheduled into `Sprint 1..N` and implemented in Stages 4–6 while unselected groups stay in `Product Backlog`.
     - **ALL Groupings (`["ALL"]`)** — takes **all** capability groups forward across `Sprint 1..N` and implements all groups end-to-end.
2. **Regulations / policies** governing the domain (beyond what is already in `resources/policies_and_statutes/`).
3. **Security, privacy & PII** — authentication model, roles beyond those discovered, fields to mask, audit needs.
4. **Accessibility & design references** — baseline WCAG 2.1 AA; add jurisdiction-specific standards only if
   the user names them. If `hasUserProvidedDesignReferences == false`, ask whether they want to add a design
   file/export/sample to `resources/design_references/` or proceed with `_shared/ux_guardrails.md` defaults.
5. **ALM platform** — Jira, Azure DevOps or none (if ingested via `--ado-repo` or `ADO_ORG_URL` is configured, default recommendation is `ado`).
6. **Future-State Target Stack (optional at Gate 1 — otherwise asked when entering Stage 4A):** If the user already knows their target stack, record it (`decidedBy: "user"`). If they have not specified a target stack yet, **do NOT silently assume `static-html` or Python** — set `frontend.kind: "tbd"`, `backend.kind: "tbd"`, `database.kind: "tbd"`, and `decidedBy: "pending-stage-4a"` in `specs/target_stack.json` so that Stage 4A (`04-solution-architect`) asks the human what Future-State technology stack to use when transitioning from the Spec/Sprint Plan into Solution Design.

Write `specs/target_stack.json` from the answers (recording `capabilityGroupingDimension`, `capabilityGroups`, and `selectedCapabilityGroups`: e.g. `["GRP-01"]` or `["ALL"]`). **Autonomous mode only (when the user explicitly requested non-interactive end-to-end execution):** do not pause; default `selectedCapabilityGroups` to `["ALL"]` (unless the user's prompt named specific group(s)), apply the statutes in
`resources/policies_and_statutes/`, enterprise defaults (OIDC/RBAC, masking of declared PII, audit log,
WCAG 2.1 AA), `almPlatform` from env (`JIRA_URL` → `jira`, `ADO_ORG_URL` → `ado`, else `none`), `decidedBy: "autonomous-default"` (using the stack named in the prompt or the zero-dependency fallback `static-html` + `python-stdlib-http` + `sqlite` only in autonomous mode), and the most restrictive workflow reading for every
open question, each recorded for the spec as `ASSUMPTION-NN`.

### 5. Hand over
Proceed to `02-spec-architect-and-judge`; Stage 3 starts as soon as Gate 2 passes.

## Do not
- Start Stage 1 scanning without first confirming with the user where the input source is located (unless already explicitly specified in the user's prompt or running in `--autonomous` mode with populated `resources/inputs/`).
- Mix future-state 3NF ERDs, target SQL DDL, future-state architecture flow diagrams, or Legacy-to-Target entity mappings into `specs/discovery_architecture_and_inventory.md` — keep Stage 1 strictly to the Current State ("As-Is") and place all Future-State ("To-Be") design in Stage 4A (`design/solution_design.md`).
- Guess states, roles or rules; unresolved items go to §3.1 and Gate 1.
- Copy anything from `examples/` or write outside `<PROJECT_ROOT>/specs/`.
