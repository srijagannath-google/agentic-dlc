#!/usr/bin/env python3
"""Empirical A/B Skill Ablation, Counterfactual Trap & Routing Abstention Evaluator (`evals/`).

Pure Python 3.10+ stdlib harness supporting:
  1. `--validate-only`: Structural & regex lint of `evals/evalset.json` (used in CI).
  2. `--selftest`: Executes deterministic graders against `syntheticBaselineOutput` vs `syntheticTreatmentOutput`
     and verifies positive Net Skill Lift + 95% Bootstrap Confidence Interval + 100% negative abstention.
  3. `--baseline <file.jsonl> --treatment <file.jsonl> [--k 3]`: Scores real multi-trial agent transcripts,
     computes `pass^k`, Trigger Rate, Negative Abstention Rate, Net Lift, and 1,000-sample Bootstrap 95% CI.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import dlc_common as dlc  # noqa: E402


def load_evalset(path: Path) -> dict[str, Any]:
    doc = dlc.read_json(path)
    if not isinstance(doc, dict) or not isinstance(doc.get("cases"), list):
        raise dlc.GateFailure(f"{path} must be a JSON object containing a 'cases' list.")
    return doc


def validate_evalset(doc: dict[str, Any], repo_root: Path) -> list[str]:
    errs: list[str] = []
    cases = doc.get("cases") or []
    if len(cases) < 8:
        errs.append(f"evalset must contain at least 8 cases (found {len(cases)}).")

    seen_ids: set[str] = set()
    by_id: dict[str, dict[str, Any]] = {}
    skill_dirs = {p.name for p in (repo_root / "skills").iterdir() if p.is_dir()} if (repo_root / "skills").is_dir() else set()
    trap_count = 0
    neg_count = 0

    for idx, c in enumerate(cases):
        if not isinstance(c, dict):
            errs.append(f"cases[{idx}] is not an object.")
            continue
        cid = str(c.get("id") or "").strip()
        if not cid:
            errs.append(f"cases[{idx}] missing 'id'.")
            continue
        if cid in seen_ids:
            errs.append(f"duplicate case id '{cid}'.")
        seen_ids.add(cid)
        by_id[cid] = c

        kind = c.get("kind")
        if kind == "skill_trap":
            trap_count += 1
            tskill = c.get("targetSkill")
            if not tskill or tskill not in skill_dirs:
                errs.append(f"{cid}: targetSkill '{tskill}' does not exist under skills/ ({sorted(skill_dirs)}).")
        elif kind == "negative_abstention":
            neg_count += 1
            if c.get("targetSkill") is not None:
                errs.append(f"{cid}: negative_abstention case must have targetSkill=null.")
        else:
            errs.append(f"{cid}: unknown kind {kind!r} (expected 'skill_trap' or 'negative_abstention').")

        if not str(c.get("prompt") or "").strip():
            errs.append(f"{cid}: empty prompt.")
        for field in ("mustMatchRegex", "mustNotMatchRegex"):
            arr = c.get(field)
            if not isinstance(arr, list):
                errs.append(f"{cid}: '{field}' must be a list of regex strings.")
                continue
            for pat in arr:
                try:
                    re.compile(str(pat), re.IGNORECASE | re.DOTALL)
                except re.error as exc:
                    errs.append(f"{cid}: invalid regex in {field} ({pat!r}): {exc}")

    if trap_count < 6:
        errs.append(f"evalset needs >= 6 'skill_trap' cases (found {trap_count}).")
    if neg_count < 3:
        errs.append(f"evalset needs >= 3 'negative_abstention' cases (found {neg_count}).")

    for cid, c in by_id.items():
        pair_id = c.get("counterfactualPairId")
        if pair_id is not None:
            partner = by_id.get(str(pair_id))
            if not partner:
                errs.append(f"{cid}: counterfactualPairId '{pair_id}' not found in evalset.")
            elif partner.get("counterfactualPairId") != cid:
                errs.append(f"{cid}: counterfactualPairId '{pair_id}' is not symmetric (partner points to {partner.get('counterfactualPairId')!r}).")
    return errs


def grade_output(case: dict[str, Any], output: str, triggered_skills: list[str] | None = None) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    for pat in case.get("mustMatchRegex") or []:
        if not re.search(str(pat), output, re.IGNORECASE | re.DOTALL):
            reasons.append(f"missing required pattern /{pat}/")
    for pat in case.get("mustNotMatchRegex") or []:
        m = re.search(str(pat), output, re.IGNORECASE | re.DOTALL)
        if m:
            reasons.append(f"matched forbidden trap pattern /{pat}/ ('{m.group(0)[:60]}')")

    if triggered_skills is not None:
        if case["kind"] == "skill_trap" and case.get("targetSkill") not in triggered_skills:
            reasons.append(f"did not trigger targetSkill '{case.get('targetSkill')}' (triggered={triggered_skills})")
        elif case["kind"] == "negative_abstention" and triggered_skills:
            reasons.append(f"failed abstention: triggered DLC skill(s) {triggered_skills} on unrelated prompt")
    return (len(reasons) == 0), reasons


def bootstrap_lift_ci(deltas: list[float], resamples: int = 1000, seed: int = 42) -> tuple[float, float, float]:
    """Return (mean_lift, ci95_low, ci95_high) via deterministic bootstrap resampling."""
    if not deltas:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)
    n = len(deltas)
    mean_val = sum(deltas) / n
    means: list[float] = []
    for _ in range(resamples):
        sample = [deltas[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[max(0, int(0.025 * resamples))]
    hi = means[min(resamples - 1, int(0.975 * resamples))]
    return mean_val, lo, hi


def load_jsonl_runs(path: Path) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for lineno, raw in enumerate(dlc.read_text(path).splitlines(), 1):
        s = raw.strip()
        if not s:
            continue
        rec = json.loads(s)
        cid = str(rec.get("caseId") or "")
        if not cid:
            raise dlc.GateFailure(f"{path}:{lineno} missing 'caseId'.")
        grouped.setdefault(cid, []).append(rec)
    return grouped


def evaluate_arms(
    cases: list[dict[str, Any]],
    base_runs: dict[str, list[dict[str, Any]]],
    treat_runs: dict[str, list[dict[str, Any]]],
    k: int,
    resamples: int,
    seed: int,
) -> dict[str, Any]:
    per_case: list[dict[str, Any]] = []
    trap_deltas: list[float] = []
    abstention_passes = 0
    abstention_total = 0

    for c in cases:
        cid = c["id"]
        b_list = base_runs.get(cid, [])
        t_list = treat_runs.get(cid, [])

        b_scores = [1.0 if grade_output(c, str(r.get("output", "")))[0] else 0.0 for r in b_list]
        t_graded = [
            grade_output(c, str(r.get("output", "")), r.get("triggeredSkills"))
            for r in t_list
        ]
        t_scores = [1.0 if ok else 0.0 for ok, _ in t_graded]
        b_rate = (sum(b_scores) / len(b_scores)) if b_scores else 0.0
        t_rate = (sum(t_scores) / len(t_scores)) if t_scores else 0.0
        pass_hat_k = (t_rate ** k) if t_scores else 0.0

        if c["kind"] == "skill_trap":
            trap_deltas.append(t_rate - b_rate)
        else:
            abstention_total += 1
            if t_rate == 1.0:
                abstention_passes += 1

        per_case.append({
            "id": cid,
            "kind": c["kind"],
            "targetSkill": c.get("targetSkill"),
            "baselinePassRate": round(b_rate, 3),
            "treatmentPassRate": round(t_rate, 3),
            "netLift": round(t_rate - b_rate, 3),
            f"passHat{k}": round(pass_hat_k, 3),
            "treatmentFailures": [rsn for ok, rsn in t_graded if not ok][:3],
        })

    mean_lift, ci_lo, ci_hi = bootstrap_lift_ci(trap_deltas, resamples=resamples, seed=seed)
    return {
        "totalCases": len(cases),
        "skillTrapCases": len(trap_deltas),
        "negativeAbstentionCases": abstention_total,
        "negativeAbstentionRate": round(abstention_passes / abstention_total, 3) if abstention_total else 1.0,
        "meanSkillTrapLift": round(mean_lift, 3),
        "bootstrap95Ci": [round(ci_lo, 3), round(ci_hi, 3)],
        "k": k,
        "cases": per_case,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--evalset", default=str(REPO_ROOT / "evals" / "evalset.json"))
    ap.add_argument("--validate-only", action="store_true", help="Validate evalset schema, skill links, counterfactual pairs, and regexes")
    ap.add_argument("--selftest", action="store_true", help="Run synthetic Baseline vs Treatment transcripts through the graders and bootstrap CI")
    ap.add_argument("--baseline", default=None, help="Path to Baseline (without_skill) JSONL run outputs")
    ap.add_argument("--treatment", default=None, help="Path to Treatment (with_skill) JSONL run outputs")
    ap.add_argument("--k", type=int, default=3, help="Exponent k for pass^k multi-trial consistency")
    ap.add_argument("--bootstrap-samples", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    evalset_path = Path(args.evalset).resolve()
    doc = load_evalset(evalset_path)
    errs = validate_evalset(doc, REPO_ROOT)
    if errs:
        for e in errs:
            print(f"  ✗ {e}")
        print(f"EVALSET VALIDATION: FAIL ({len(errs)} error(s))")
        return 1

    if args.validate_only:
        print(f"EVALSET VALIDATION: PASS ({len(doc['cases'])} cases verified in {evalset_path.relative_to(REPO_ROOT)})")
        return 0

    if args.selftest or (not args.baseline and not args.treatment):
        base_runs = {
            c["id"]: [{"caseId": c["id"], "trial": 1, "triggeredSkills": [], "output": c.get("syntheticBaselineOutput", "")}]
            for c in doc["cases"]
        }
        treat_runs = {
            c["id"]: [{
                "caseId": c["id"],
                "trial": 1,
                "triggeredSkills": [c["targetSkill"]] if c.get("targetSkill") else [],
                "output": c.get("syntheticTreatmentOutput", ""),
            }]
            for c in doc["cases"]
        }
    else:
        if not args.baseline or not args.treatment:
            raise dlc.GateFailure("Provide both --baseline and --treatment JSONL files (or run --validate-only / --selftest).")
        base_runs = load_jsonl_runs(Path(args.baseline))
        treat_runs = load_jsonl_runs(Path(args.treatment))

    summary = evaluate_arms(doc["cases"], base_runs, treat_runs, k=args.k, resamples=args.bootstrap_samples, seed=args.seed)
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(
            f"[evals] A/B Skill Ablation Summary — Trap Net Lift: +{summary['meanSkillTrapLift'] * 100:.1f}% "
            f"(95% Bootstrap CI: [{summary['bootstrap95Ci'][0] * 100:.1f}%, {summary['bootstrap95Ci'][1] * 100:.1f}%]) | "
            f"Abstention Rate: {summary['negativeAbstentionRate'] * 100:.1f}%"
        )
        for row in summary["cases"]:
            print(
                f"  - {row['id']:<36} kind={row['kind']:<20} base={row['baselinePassRate']:.2f} "
                f"treat={row['treatmentPassRate']:.2f} lift={row['netLift']:+.2f}"
            )
    if args.selftest and (summary["meanSkillTrapLift"] <= 0.5 or summary["negativeAbstentionRate"] < 1.0):
        print("SELFTEST: FAIL — expected strong positive trap lift and 100% negative abstention.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
