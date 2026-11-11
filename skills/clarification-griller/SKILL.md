---
name: clarification-griller
description: "Machine-enforced Decision-Tree Business Analyst Clarification, Modernization Ambition & Conflict-Resolution skill ('grill-me' for Agentic DLC). Runs automatically BEFORE specs/application_spec.md is created (--stage pre-spec), WHEN backlog/user_stories.json are created (--stage pre-stories), at Stage 4A (--stage stage4a), and ANYTIME an agent encounters unclear, contradictory, conflicting, or ambiguous inputs (--action flag-conflict). Presents visible 🔥 Grill-Me Frontier Rounds (1–4 questions with evidence citations, ➡️ Recommended answers, and native ask_question UI cards) and persists DECISION-NN into specs/clarification_decisions.json."
---

# Conditional Decision-Tree BA Clarification & Conflict Griller (`clarification-griller`)

**Read before acting:** `_shared/conditional_grilling.md`, `_shared/workflow_chain_of_custody.md`, `schemas/clarification_decisions.schema.json`. `<PLUGIN>` = installed plugin dir.

> **Machine-Enforced Checkpoints (`SD-GRILL-00` / `SD-GRILL-01` / `SD-GRILL-02` / `SD-GRILL-03`):**
> 1. **Before `specs/application_spec.md` (`--stage pre-spec`):** Auto-seeded by `validate_discovery_blueprint.py`. Blocks `gate_1_discovery` approval and `lint_spec_structure.py` until settled!
> 2. **When Creating `backlog/user_stories.json` (`--stage pre-stories`):** Auto-seeded by `validate_spec_scorecard.py` and checked at Stage 3 entry. Blocks `alm_jira_ado_bridge.py --action audit` and `gate_3_backlog` until settled!
> 3. **Anytime Unclear / Contradictory / Conflicting / Ambiguous (`--action flag-conflict`):** Run immediately by any skill or subagent whenever two artifacts disagree or a business rule / AC boundary is ambiguous!

## Procedure

### 1. Detect or Inspect Active Frontier (`pre-spec` | `pre-stories` | `stage4a`)
```bash
python3 <PLUGIN>/skills/clarification-griller/scripts/clarification_interview.py \
  --project-root "<PROJECT_ROOT>" --stage pre-spec --action detect --auto-bypass-if-clear --seed-if-needed
```
(Use `--stage pre-stories` before/during Stage 3 User Story creation, or `--stage stage4a` at Stage 4A entry.)
- **`needsClarification == false`:** Stage is automatically added to `stagesSettled` in `specs/clarification_decisions.json` — ask **zero** extra questions and proceed.
- **`needsClarification == true`:** Refine `openFrontier` with concrete domain details (`--action save-frontier` if customizing wording) and proceed to Step 2.

### 2. Anytime Conflict / Contradiction Interrupt (`--action flag-conflict`)
Whenever **any** agent or subagent spots conflicting formulas across files (e.g., Form VBA vs. SQL Query vs. Policy PDF), contradictory requirements, or ambiguous acceptance criteria:
```bash
python3 <PLUGIN>/skills/clarification-griller/scripts/clarification_interview.py \
  --project-root "<PROJECT_ROOT>" --stage <pre-spec|pre-stories|stage4a|anytime> --action flag-conflict \
  --category contradiction-conflict \
  --evidence "<File A:line vs File B:line>" \
  --question "<Concise BA question stating both conflicting rules and options>" \
  --recommended "<Evidence-backed recommended resolution>"
```
Subagents must **STOP immediately** and return the flagged frontier question to the coordinator so the coordinator engages the human / Business Analyst!

### 3. Present a Visible `🔥 Grill-Me Clarification Round` to the Business Analyst / Human
Always format the chat presentation with an unmistakable **`## 🔥 Grill-Me Clarification Round (<Pre-Spec | User Stories | Conflict>)`** heading, `1–4` numbered `❓ **Q<N> — <Title>** *(Source: ...)*` items + `➡️ **Recommended:** ...` (and invoke the host IDE's native `ask_question` tool with `(Recommended)` first when available), remind the user they can reply **`accept recommendations`** to fast-exit, and **END YOUR TURN**.

### 4. Record BA Answers (`record-round` or `accept-recommendations`)
```bash
# Option A — Record explicit Business Analyst / human answers:
python3 <PLUGIN>/skills/clarification-griller/scripts/clarification_interview.py \
  --project-root "<PROJECT_ROOT>" --stage <pre-spec|pre-stories|stage4a> --action record-round \
  --decisions-json '<DECISIONS_JSON_ARRAY>' \
  [--dispositions-json '<CAPABILITY_DISPOSITIONS_JSON_ARRAY>'] \
  [--next-frontier-json '[]']

# Option B — User replied "accept recommendations":
python3 <PLUGIN>/skills/clarification-griller/scripts/clarification_interview.py \
  --project-root "<PROJECT_ROOT>" --stage <pre-spec|pre-stories|stage4a> --action accept-recommendations
```
Once `openFrontierCount == 0`, the stage is recorded in `stagesSettled` and `lint_spec_structure.py` (`pre-spec`) or `alm_jira_ado_bridge.py` (`pre-stories`) unlocks!
