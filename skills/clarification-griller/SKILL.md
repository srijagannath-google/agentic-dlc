---
name: clarification-griller
description: "Conditional Decision-Tree Clarification & Modernization Ambition Interview skill ('grill-me' for Agentic DLC). Triggered automatically during Stage 1 (Gate 1) or Stage 4A ONLY when clarification is needed — either to define Legacy-to-Modernized target capabilities beyond lift-and-shift (retire vs. 1:1 parity vs. reimagined REQ-ENH-* / AI / self-service capabilities, rebuild vs. in-place-upgrade, Strangler waves) OR to resolve concrete ambiguities in a BRD/requirements document or codebase (open workflow transitions, edge-case formulas, unverified acronyms, or unsettled target stack). Auto-bypasses with zero questions when inputs are already complete."
---

# Conditional Decision-Tree Clarification & Modernization Griller (`clarification-griller`)

**Read before acting:** `_shared/conditional_grilling.md`, `_shared/workflow_chain_of_custody.md`, `schemas/clarification_decisions.schema.json`. `<PLUGIN>` = installed plugin dir.

> **Core Rule ("Grill Only When Needed, Never Ask What the Repo/BRD Already Answers"):**
> 1. Run `clarification_interview.py --action detect` first to inspect `specs/input_inventory.json`, `specs/discovery_architecture_and_inventory.md`, `specs/project_setup.json`, and `specs/target_stack.json`.
> 2. If `needsClarification == false`, record `CLEAR_AUTO_BYPASSED` and **return immediately without asking extra questions**.
> 3. If `needsClarification == true`, interview the human in **bounded Frontier Rounds** (`2–4` independent root decisions per round, each with an evidence citation and `➡️ Recommended` answer; dependent child questions deferred to Round 2 *only if* opened by Round 1 answers), and persist resolved `DECISION-NN` items into `specs/clarification_decisions.json`.

## Outputs
| File | Author | Checked by |
| :-- | :-- | :-- |
| `specs/clarification_decisions.json` | `clarification-griller` (`clarification_interview.py`) | `schemas/clarification_decisions.schema.json`, `02/scripts/lint_spec_structure.py` (`SD-GRILL-01/02`) |

## Procedure

### 1. Detect Whether Clarification or Modernization Ambition Grilling Is Needed
```bash
python3 <PLUGIN>/skills/clarification-griller/scripts/clarification_interview.py \
  --project-root "<PROJECT_ROOT>" --action detect --stage gate1 [--auto-bypass-if-clear]
```
Inspect the JSON output (`needsClarification`, `triggerReasons`, `suggestedRootFrontier`):
- **`needsClarification == false`:** `--auto-bypass-if-clear` writes `clarificationStatus: "CLEAR_AUTO_BYPASSED"` to `specs/clarification_decisions.json`. Do **not** grill the user; proceed directly with the normal gate brief.
- **`needsClarification == true`:** Proceed to Step 2.

### 2. Present Frontier Round 1 (`2–4` Independent Root Decisions + `➡️ Recommended`)
Refine the detected `suggestedRootFrontier` using actual domain specifics from `specs/discovery_architecture_and_inventory.md` (`§2.1` legacy objects, `§3.1` open workflow questions, `§5` pain points, `§6.1` `GRP-01..N` capability groups) — **never ask generic boilerplate or facts already answered in the inputs**:
1. **For Legacy Modernization (`SCENARIO_LEGACY_APP` in `standard` / `delta` mode):**
   - **Capability Disposition (`CAP-*` / `GRP-*`):** Ask which discovered legacy capabilities/modules should be **`retire`** (drop dead forms/reports), **`parity`** (1:1 behavior verified via `TC-PARITY-*`), or **`reimagine-enhance`** (`REQ-ENH-*`: e.g., external self-service portal, automated workflow/notifications, live `BR-NN` calculation engine, grounded AI triage copilot / `A2UI v0.9` surface, API/event integration).
   - **Modernization Execution Approach:** `clean-room-rebuild` vs. `in-place-upgrade` (citing `runtimeReadinessSignals`), Strangler wave (`GRP-01` foundation first vs. `ALL`), and regulatory/PII constraints.
2. **For BRD / Requirements Gaps (`SCENARIO_REQUIREMENTS_DOC` or Legacy Workflow Gaps):**
   - Ask only the **root** unsettled workflow/rule/acronym branches (`§3.1 Open Workflow Questions`, `[UNVERIFIED_ACRONYM]`, missing boundary thresholds or failure/rejection paths). Keep dependent sub-questions out of Round 1 until the root branch is answered.

Persist the active frontier before ending your turn:
```bash
python3 <PLUGIN>/skills/clarification-griller/scripts/clarification_interview.py \
  --project-root "<PROJECT_ROOT>" --action save-frontier --frontier-json '<JSON_ARRAY>'
```
Present the `2–4` frontier questions formatted with `❓ **Q1 — ...**` and `➡️ **Recommended:** ...` (and call the native `ask_question` UI tool with `(Recommended)` first when available in the host IDE), remind the user they can reply **`accept recommendations`** to fast-exit, and **END YOUR TURN**.

### 3. Record Answers & Recompute Dependent Child Frontier (Round 2 Only If Needed)
When the user replies:
- If the user replies **"accept recommendations"** (or approves defaults):
  ```bash
  python3 <PLUGIN>/skills/clarification-griller/scripts/clarification_interview.py \
    --project-root "<PROJECT_ROOT>" --action accept-recommendations
  ```
- Otherwise, record their answers (`DECISION-01..NN` and `capabilityDispositions`), check whether any answer opens a **dependent child decision** (Round 2, e.g., human-in-the-loop approval thresholds for a newly chosen AI copilot or rejection-reopen guards for a multi-tier workflow):
  - **If dependent child questions exist (and `< 3` rounds completed):** pass them in `--next-frontier-json` and run Round 2.
  - **If the frontier is empty (`next-frontier == []`):** `clarificationStatus` becomes `"RESOLVED_BY_HUMAN"` and the interview is complete!
  ```bash
  python3 <PLUGIN>/skills/clarification-griller/scripts/clarification_interview.py \
    --project-root "<PROJECT_ROOT>" --action record-round \
    --decisions-json '<DECISIONS_JSON_ARRAY>' \
    [--dispositions-json '<CAPABILITY_DISPOSITIONS_JSON_ARRAY>'] \
    [--next-frontier-json '[]']
  ```

### 4. Stage 4A Technical Frontier Check (`--stage stage4a`)
Before authoring `design/*` in Stage 4A, run `--action detect --stage stage4a`. Only if `target_stack.json` still has `"tbd"` stack components or unsettled stateless/ORM refactoring branches, run a single concise technical frontier round and update `specs/target_stack.json` (`decidedBy: "user"`) + `specs/clarification_decisions.json`.

## Do not
- Grill the user when `needsClarification == false` or in `--autonomous` mode.
- Ask questions whose answers already exist in `resources/inputs/` or `resources/policies_and_statutes/`.
- Dump more than `4` questions in a single round or omit `➡️ Recommended` answers.
- Advance to Stage 2 (`lint_spec_structure.py`) while `specs/clarification_decisions.json` has `openFrontier` items remaining.
