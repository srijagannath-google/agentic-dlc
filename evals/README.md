# Empirical Skill Ablation & Counterfactual Trap Suite (`evals/`)

Validating golden project outputs (`scripts/verify_golden_projects.py`) proves that our **deterministic gate scripts** work, but measuring whether **skill instructions (`SKILL.md`) and subagents (`agents/*.md`)** genuinely lift agent reasoning over a frontier model's pretraining baseline requires **empirical A/B skill ablation**:

$$\text{Net Skill Lift} = \text{Score}(\text{Model} + \text{Skill}) - \text{Score}(\text{Model Baseline without Skill})$$

This suite evaluates `agentic-dlc` skills across four rigorous dimensions:
1. **A/B Skill Ablation with 95% Bootstrap Confidence Intervals:** Compares Treatment (`with_skill`) vs. Control (`without_skill`) across deterministic structural & trap graders.
2. **Counterfactual Trap Pairs:** Paired prompts where subtle non-standard constraints in the input (e.g., an inverted business threshold, an undefined domain acronym, or a Strangler coexistence boundary) punish pretraining memorization and reward strict input provenance.
3. **`pass^k` Multi-Trial Consistency:** Measures the probability that **all** $k$ independent trials of a case succeed ($\hat{p}^k$), exposing brittle or nondeterministic instructions.
4. **Routing Precision & Abstention:** Verifies both positive skill triggering on modernization/greenfield tasks and clean **abstention** on unrelated developer tasks (e.g., fixing a CSS typo in a standalone script or answering a generic Linux CLI question).

## Quick Start

```bash
# 1. Validate evalset structure, skill references, counterfactual pairs, and regex graders (runs in CI)
python3 evals/run_skill_ablation.py --validate-only

# 2. Run built-in synthetic A/B grader & bootstrap CI self-test
python3 evals/run_skill_ablation.py --selftest

# 3. Compare recorded Baseline vs. Treatment agent transcripts (.jsonl)
python3 evals/run_skill_ablation.py \
  --baseline /tmp/baseline_runs.jsonl \
  --treatment /tmp/treatment_runs.jsonl \
  --k 3
```

## Transcript JSONL Format

Each line in `--baseline` / `--treatment` JSONL files has the shape:
```json
{"caseId": "EVAL-01-ACRONYM-PROVENANCE", "trial": 1, "triggeredSkills": ["01-discovery-and-grouping"], "output": "..."}
```
