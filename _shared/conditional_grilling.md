# Conditional Decision-Tree Grilling (`grill-me` Intake & Modernization Ambition Protocol)

Modernizing a legacy application is **not** a mechanical 1:1 lift-and-shift, and authoring a living specification from a BRD/PRD must **never** rely on silent agent assumptions. `agentic-dlc` integrates the **`grill-me` Frontier-Round Decision-Tree Interview** (`skills/clarification-griller/SKILL.md`) **conditionally — only when clarification or modernization vision is genuinely needed**.

---

## 1. Deterministic Activation vs. Zero-Noise Bypass

Run `clarification_interview.py --action detect --stage gate1|stage4a` before asking questions:

| Scenario & Lifecycle Mode | When Conditional Grilling Activates (`NEEDS_CLARIFICATION`) | When Grilling Auto-Bypasses (`CLEAR_AUTO_BYPASSED`) |
| :--- | :--- | :--- |
| **Legacy Modernization (`SCENARIO_LEGACY_APP` in `standard` / `delta` mode)** | **Always runs at least Round 1 at Gate 1** unless the user's prompt already defined capability dispositions and modernization mode — resolving: (1) **Capability Disposition (`CAP-*` / `GRP-*`)**: `retire` vs. `parity` vs. `reimagine-enhance` (`REQ-ENH-*`: self-service UX, workflow automation, live rule calculation, AI/RAG copilot or `A2UI v0.9` surface, API/event integration); (2) **Modernization Approach**: `clean-room-rebuild` vs. `in-place-upgrade` + Strangler wave (`GRP-01` vs. `ALL`); and (3) any open `§3.1` workflow/acronym gaps. | Only when `--autonomous` is active (`AUTONOMOUS_ASSUMPTIONS`) or `specs/clarification_decisions.json` already resolved all branches (`openFrontier == []`). |
| **Greenfield BRD / PRD / RFP (`SCENARIO_REQUIREMENTS_DOC`)** | **Activates ONLY when concrete input gaps exist:** non-empty `§3.1 Open Workflow Questions` (missing actor roles, rejection/reopen/escalation transitions), undefined `[UNVERIFIED_ACRONYM]` tokens, missing formula thresholds/edge cases in `BR-NN`, conflicting requirements across docs, or `scenarioConfidence == LOW`. | **Skipped completely (`0` extra turns)** when the BRD + policies settle all states, roles, and formulas (`openWorkflowQuestions == 0` and `unverifiedAcronyms == 0`). |
| **Brownfield Baseline (`retro-spec` mode)** | **Activates ONLY if** source code has unreachable/dead workflow states, undefined `[UNVERIFIED_ACRONYM]` business terms, or `scenarioConfidence == LOW`. Never asks To-Be modernization enhancement questions in `retro-spec` mode. | **Skipped completely** when code evidence settles As-Is states, roles, and rules. |
| **Stage 4A Entry (`04-solution-architect`)** | **Activates ONLY if** `specs/target_stack.json` still has `"tbd"` stack choices (`decidedBy != "user"`) or unsettled brownfield refactoring branches (`InProc` sticky-session replacement, ORM/DB target, coexistence routing). | **Skipped completely** when `decidedBy == "user"` and target stack/coexistence are already settled. |

---

## 2. Five Non-Negotiable Grilling Rules

1. **Evidence First ("Finding Facts Is Your Job, Decisions Are the User's"):**
   Never ask the user anything answerable by reading `resources/inputs/`, `resources/policies_and_statutes/`, or `resources/design_references/`. Every frontier question **must cite the exact file, object, table, or BRD section** that created the decision branch.
2. **Bounded Frontier Rounds (`2–4` Independent Questions per Round, Cap `3` Rounds):**
   - Model ambiguities as a **decision tree**. The **current frontier** contains only independent root decisions whose prerequisites are already known (`2–4` questions per round — never dump 10+ flat questions at once, and never drag out 15 single-question turns).
   - **Round 2 (Dependent Child Frontier)** runs **only if** a Round 1 answer opens a dependent child branch (e.g., asking AI human-in-the-loop guardrail thresholds *only after* the user selects an AI triage enhancement in Round 1). Stop immediately once `openFrontier` is empty.
3. **Mandatory Evidence-Backed Recommendation (`➡️ Recommended`) + Native UI Selector:**
   Format every question clearly (and also invoke the host IDE's native `ask_question` multiple-choice widget with `(Recommended)` first when available):
   ```markdown
   ❓ **Q1 — <Decision Title>** *(Source: `<file:line or §section>`)*:
   <Concise explanation of the gap or modernization trade-off + concrete options>
   ➡️ **Recommended:** <Your evidence-backed recommendation and 1-sentence rationale>
   ```
4. **Fast-Exit Escape Hatch (`"Accept Recommendations"`):**
   End every frontier round with: *"Reply with your choices, or say **`accept recommendations`** to lock in all `➡️ Recommended` defaults and proceed."* If the user accepts recommendations, run `clarification_interview.py --action accept-recommendations`.
5. **Auditable Chain of Custody (`specs/clarification_decisions.json` → `DECISION-NN`):**
   - Persist every settled answer via `clarification_interview.py --action record-round` into `specs/clarification_decisions.json` (`DECISION-01..NN` + `capabilityDispositions`).
   - Stage 2 (`lint_spec_structure.py`) blocks `specs/application_spec.md` (`SD-GRILL-01`) if `clarificationStatus == "IN_PROGRESS"` or `openFrontier` is non-empty, and blocks (`SD-GRILL-02`) if any capability marked `disposition: "retire"` is included as an active `REQ-FUNC-*` / `REQ-ENH-*` requirement.
