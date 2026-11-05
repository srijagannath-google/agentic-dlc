---
name: 00-setup-and-connection
description: "Stage 0 (Gate 0) of the Agentic DLC v4. Project Setup, ALM/SCM Connection Configuration, and Azure DevOps / Jira Project & Repository Selection. Use whenever the user asks to connect to Azure DevOps (ADO) or Jira, configure credentials, initialize a new project root, or start the Agentic DLC process. Connects to ADO/Jira, lists available ADO Projects and Git Repositories, asks the user WHICH ADO Project and repository/input source they want to work on, writes specs/project_setup.json, and STOPS at Gate 0 for explicit human approval before Stage 1 (Discovery) can run."
---

# Stage 0 — Project Setup, Connection Verification & Project/Repository Selection (Gate 0)

**Read before acting:** `_shared/project_root.md`, `docs/ARCHITECTURE.md` §4.0–§4.1. `<PLUGIN>` = installed plugin dir.

> **CRITICAL HARD-STOP RULE (GATE 0):**
> Stage 0 is **strictly setup, connection verification, and project/input-source selection**.
> - If the user asks to *"connect to ADO"*, *"configure Azure DevOps / Jira"*, or *"set up the project"*, **DO NOT start Stage 1 (`01-discovery-and-grouping`), DO NOT clone repositories, and DO NOT author `specs/discovery_architecture_and_inventory.md`!**
> - You **MUST** first verify the connection, **list the available Azure DevOps Projects (`list-ado-projects`), ask the user which ADO Project (and which repository / branch) they want to start working on**, save `specs/project_setup.json`, and **END YOUR TURN (STOP)** waiting for the user's explicit confirmation to begin Stage 1!

## Outputs
| File | Author | Checked by |
| :-- | :-- | :-- |
| `specs/project_setup.json` | `00/scripts/setup_project_connection.py` | `schemas/project_setup.schema.json` |
| `specs/gate_approvals.json` (`gate_0_setup`) | `00/scripts/setup_project_connection.py` + `scripts/gate_tracker.py` | Blocks Stage 1 (`scan_input_sources.py`) until `APPROVED_BY_USER` |

## Procedure

### 1. Resolve `<PROJECT_ROOT>` and Check Existing Connection Settings
Resolve `<PROJECT_ROOT>` per `_shared/project_root.md` (never the `agentic-dlc` plugin folder; ask the user where to create the project directory if none is bound yet). Then check current environment / `.env` configuration:
```bash
python3 <PLUGIN>/skills/00-setup-and-connection/scripts/setup_project_connection.py \
  --project-root "<PROJECT_ROOT>" --bind-project-root --action check-env
```

### 2. Ask Where the Input Source Is & Configure / Test the Connection

#### Path A — Azure DevOps (ADO) Connection & Project Selection
1. Ensure `ADO_ORG_URL` (`https://dev.azure.com/<org>`) and `ADO_PAT` (Personal Access Token with **Project Read**, **Code Read**, and **Work Items Read & Write** scopes) are configured in `<PROJECT_ROOT>/.env` or `~/.gemini/config/agentic-dlc.env` (ask the user if missing).
2. **List all ADO Projects in the organization and ask the user which ADO Project they want to work on:**
   ```bash
   python3 <PLUGIN>/skills/00-setup-and-connection/scripts/setup_project_connection.py \
     --project-root "<PROJECT_ROOT>" --action list-ado-projects [--ado-org-url "https://dev.azure.com/<org>"] --persist-env
   ```
   - **STOP HERE AND END YOUR TURN** if the user has not yet named which ADO Project from that list they want to work on! Present the numbered list of ADO Projects and ask which one to select.
3. **Once the user selects an ADO Project, list the Git Repositories inside that ADO Project:**
   ```bash
   python3 <PLUGIN>/skills/00-setup-and-connection/scripts/setup_project_connection.py \
     --project-root "<PROJECT_ROOT>" --action list-ado-repos --ado-project "<SELECTED_ADO_PROJECT>" --persist-env
   ```
   - If there are multiple repositories (or the user hasn't confirmed whether the input is an ADO Git repository vs. a local BRD/export while using ADO Boards for work items), **present the repositories and ask the user which repository (and branch) to use** — then **END YOUR TURN**.

#### Path B — Jira / GitHub / GitLab / Local Folder
- **Jira Boards:** Run `--action list-jira-projects` to verify `JIRA_URL`, `JIRA_EMAIL`, and `JIRA_API_TOKEN` and ask the user which Jira project key to bind.
- **Git Repository / Local Directory / `resources/inputs/`:** Ask the user to confirm the Git repository URL (`--input-kind git`), external local directory (`--input-kind local-dir`), or files in `<PROJECT_ROOT>/resources/inputs/` (`--input-kind resources-inputs`).

### 3. Save `specs/project_setup.json` & Pause at Gate 0 for Human Approval
Once the user has identified their project and input source, save the Stage 0 setup:
```bash
python3 <PLUGIN>/skills/00-setup-and-connection/scripts/setup_project_connection.py \
  --project-root "<PROJECT_ROOT>" --action save-setup \
  --input-kind ado --ado-project "<SELECTED_ADO_PROJECT>" --repo-name "<SELECTED_REPO>" [--branch main] \
  --alm-platform ado --persist-env
```
Then present the confirmed Stage 0 configuration summary (`<PROJECT_ROOT>`, ADO Organization, selected ADO Project, selected Repository & Branch, ALM Board target) and ask:
> *"Stage 0 (Setup & Connection) is complete. Please confirm if you approve Gate 0 and want me to proceed to Stage 1 (Current-State Discovery)."*

**END YOUR TURN IMMEDIATELY (call zero further tools).**

### 4. Advancing Beyond Gate 0 (Only in a Subsequent Turn After Explicit User Approval)
Only **after** the human replies in chat explicitly approving Gate 0 and asking to proceed to Stage 1:
```bash
python3 <PLUGIN>/scripts/gate_tracker.py \
  --project-root "<PROJECT_ROOT>" --action approve --gate gate_0_setup \
  --user-response "<verbatim quote from the user's approval message>"
```
Then — and only then — invoke Stage 1 (`01-discovery-and-grouping`).

## Do not
- Start Stage 1 (`scan_input_sources.py` or `discovery-architect` authoring) during the same turn you configure/test an ADO or Jira connection.
- Guess which ADO Project or Git Repository the user wants to work on when `ADO_ORG_URL` has projects — always list them and ask!
- Call `gate_tracker.py --action approve --gate gate_0_setup` in the same turn `save-setup` ran.
