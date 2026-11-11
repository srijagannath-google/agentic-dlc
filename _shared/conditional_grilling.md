# Conditional Decision-Tree Grilling (`grill-me` BA Clarification, Modernization & Conflict Protocol)

Modernizing a legacy application (MS Access, `.NET`, Java, Mainframe) is **not** a mechanical 1:1 lift-and-shift, and authoring specifications or user stories must **never** silently guess over contradictions or ambiguities. `agentic-dlc` machine-enforces **`grill-me` Frontier-Round Clarification** (`skills/clarification-griller/SKILL.md`) at **two mandatory Business Analyst checkpoints** — **before `specs/application_spec.md` is created (`pre-spec`)** and **when `backlog/user_stories.json` are created (`pre-stories`)** — plus **anytime** an agent encounters unclear, contradictory, conflicting, or ambiguous inputs (`--action flag-conflict`).

---

## 1. Machine-Enforced Activation Matrix vs. Zero-Noise Bypass

| Lifecycle Checkpoint | When `grill-me` Automatically Seeds `openFrontier` & Blocks Downstream Gate | Hard Validator Gate | When Grilling Auto-Bypasses (`CLEAR_AUTO_BYPASSED`) |
| :--- | :--- | :--- | :--- |
| **1. Before `application_spec.md` (`--stage pre-spec`)** | Auto-seeded by `validate_discovery_blueprint.py` whenever: (a) **Legacy Modernization** (`SCENARIO_LEGACY_APP` in `standard`/`delta` mode: MS Access, `.NET`, Java, Mainframe) needs BA `capabilityDispositions` (`retire` vs. `parity` vs. `reimagine-enhance` `REQ-ENH-*`) & modernization mode; (b) `scan_input_sources.py` finds **cross-artifact contradictions** (`detectedAmbiguities`, e.g., conflicting fees/rates/thresholds across forms vs. queries vs. docs); or (c) `§3.1 Open Workflow Questions`, missing transition roles, `[UNVERIFIED_ACRONYM]`, or `LOW` confidence exist. | `gate_tracker.py` (`gate_1_discovery`) + `lint_spec_structure.py` (`SD-GRILL-00` / `SD-GRILL-01` / `SD-GRILL-02`) | Clean greenfield BRD or settled `retro-spec` with `0` contradictions, `0` open workflow questions, and `0` unverified acronyms (`stagesSettled: ["pre-spec"]`). |
| **2. When Creating `user_stories.json` (`--stage pre-stories`)** | Auto-seeded at Gate 2 (`validate_spec_scorecard.py`) / Stage 3 entry whenever: (a) `BR-NN` rules in Spec `§3.4` lack boundary/negative `Examples` vectors needed for `EDGE / BOUNDARY` & `NEGATIVE` ACs; (b) `§3.3` transitions have blank/ambiguous `Guard` conditions; (c) unconfirmed `ASSUMPTION-NN` items remain in `specs/application_spec.md`; (d) `>= 2` capability groups require BA Sprint 1 MVP slicing confirmation; or (e) `sprint-planner-agent` flags a story/AC conflict. | `alm_jira_ado_bridge.py --action audit` + `gate_tracker.py` (`gate_3_backlog`) (`SD-GRILL-03`) | Spec has explicit `BR-NN` `Examples`, explicit transition guards, `0` unconfirmed assumptions, single-group scope, and `0` story conflicts (`stagesSettled: ["pre-stories"]`). |
| **3. Stage 4A Architecture Entry (`--stage stage4a`)** | `specs/target_stack.json` has `decidedBy != "user"` or `"tbd"` stack components. | Stage 4A Step 0 | `decidedBy == "user"` and concrete stack already chosen. |
| **4. Anytime Conflict / Contradiction Interrupt (`--action flag-conflict`)** | **Any stage (`01`–`08`):** Whenever any skill or subagent encounters **unclear, contradictory, conflicting, or ambiguous** files, formulas, state transitions, or instructions, it runs `clarification_interview.py --action flag-conflict` to halt and run `🔥 Grill-Me` with the BA/human. | Blocks active stage validator (`SD-GRILL-01` / `SD-GRILL-03`) | Never bypassed in interactive mode — conflicts must be resolved by the human/BA. |

---

## 2. Five Non-Negotiable Grilling Rules

1. **Subagents Never Silently Guess — Surface Frontier to Coordinator & Human BA:**
   Subagents (`discovery-architect`, `sprint-planner-agent`, `solution-architect`, `coding-agent`) cannot message the user directly; whenever `openFrontier` is non-empty or they call `--action flag-conflict`, they **MUST STOP and return the frontier questions to the coordinator** so the coordinator presents a visible **`🔥 Grill-Me Clarification Round`** to the human / Business Analyst!
2. **Evidence First ("Finding Facts Is Your Job, Decisions Are the User's"):**
   Never ask anything already answered in `resources/inputs/`, `policies_and_statutes/`, or `design_references/`. Every question cites the exact conflicting/ambiguous file, query, form, or section.
3. **Bounded Frontier Rounds (`1–4` Independent Questions per Round) + `➡️ Recommended` + Native UI Selector:**
   Present questions with a visible **`## 🔥 Grill-Me Clarification Round`** header, `❓ **Q1 — ...**` + `➡️ **Recommended:** ...`, and call the host IDE's `ask_question` UI selector (with `(Recommended)` first) when available. Defer dependent child questions to Round 2 *only if* Round 1 answers open new sub-branches.
4. **Fast-Exit Escape Hatch (`"accept recommendations"`):**
   Always remind the BA/human they can reply **`accept recommendations`** to lock in the `➡️` recommendations via `clarification_interview.py --stage <stage> --action accept-recommendations`.
5. **Auditable Chain of Custody (`specs/clarification_decisions.json` → `DECISION-NN`):**
   Every answer is recorded as `DECISION-01..NN` (rendered in `specs/gate_briefs/*.md §3b`), and `stagesSettled` tracks `["pre-spec", "pre-stories", "stage4a"]`.
