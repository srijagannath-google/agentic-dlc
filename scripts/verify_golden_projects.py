#!/usr/bin/env python3
"""Runs the verify-only pipeline over every golden project under `examples/*/` that has `expected_artifacts/`.

For each example:
  1. copies `inputs/` → `<tmp>/resources/inputs/`, `policies_and_statutes/` and `shared_services/` (if present)
     → `<tmp>/resources/…`, and `expected_artifacts/*` → `<tmp>/` (specs/, backlog/, design/, test/, src/ …);
  2. runs `scripts/run_agentic_dlc_pipeline.py --autonomous --platform none --browser auto --continue-on-failure`;
  3. records the pipeline exit code and the Stage 6 verdict from `<tmp>/test/eval_results.json`.

`scripts/lint_domain_neutrality.py` runs first; the whole run fails if it fails.

Usage: python3 verify_golden_projects.py [--only <example-name>] [--keep] [--browser auto|chrome|none]
Exit 1 if the lint fails or any golden project does not finish with pipeline exit 0 and eval verdict PASS.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = PLUGIN_ROOT / "examples"
PIPELINE = PLUGIN_ROOT / "scripts" / "run_agentic_dlc_pipeline.py"
LINT = PLUGIN_ROOT / "scripts" / "lint_domain_neutrality.py"


def stage_project(example: Path, dest: Path) -> list[str]:
    copied = []
    for sub, target in (("inputs", "resources/inputs"), ("policies_and_statutes", "resources/policies_and_statutes"),
                        ("shared_services", "resources/shared_services"), ("design_references", "resources/design_references")):
        src = example / sub
        if src.exists():
            shutil.copytree(src, dest / target, dirs_exist_ok=True)
            copied.append(target)
    exp = example / "expected_artifacts"
    for child in sorted(exp.iterdir()):
        if child.is_dir():
            shutil.copytree(child, dest / child.name, dirs_exist_ok=True)
            copied.append(child.name + "/")
        elif child.is_file():
            shutil.copy2(child, dest / child.name)
            copied.append(child.name)
    # golden projects start fresh: no prior iterations / results
    for stale in (dest / "test" / ".snapshots", dest / "test" / ".build_logs", dest / "test" / "history", dest / "deploy" / "history"):
        shutil.rmtree(stale, ignore_errors=True)
    for stale_file in (
        dest / "test" / "eval_results.json",
        dest / "test" / "eval_report.md",
        dest / "test" / "remediation_and_guardrail_audit_report.md",
        dest / "deploy" / "deployment_eval_report.json",
        dest / "deploy" / "deployment_eval_report.md",
    ):
        stale_file.unlink(missing_ok=True)
    return copied


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default=None, help="Run a single example by directory name")
    ap.add_argument("--keep", action="store_true", help="Keep the temporary project directories")
    ap.add_argument("--browser", default="auto", choices=["auto", "playwright", "chrome", "none"])
    ap.add_argument("--timeout", type=int, default=900, help="Per-project pipeline timeout (s)")
    args = ap.parse_args()

    print("== domain-neutrality lint ==")
    lint_rc = subprocess.run([sys.executable, str(LINT), "--plugin-root", str(PLUGIN_ROOT)]).returncode
    rows: list[tuple[str, str, str, str, float, str]] = []
    failed = lint_rc != 0

    examples = [p for p in sorted(EXAMPLES.iterdir()) if p.is_dir() and (p / "expected_artifacts").is_dir()] if EXAMPLES.exists() else []
    if args.only:
        examples = [p for p in examples if p.name == args.only]
    if not examples:
        print("No golden projects with expected_artifacts/ found under examples/.")
    for ex in examples:
        if not any((ex / "expected_artifacts").iterdir()):
            rows.append((ex.name, "SKIPPED", "—", "—", 0.0, "expected_artifacts/ is empty"))
            continue
        tmp = Path(tempfile.mkdtemp(prefix=f"dlc-golden-{ex.name}-"))
        copied = stage_project(ex, tmp)
        print(f"\n== golden project: {ex.name} → {tmp}\n   staged: {', '.join(copied)}")
        cmd = [sys.executable, str(PIPELINE), "--project-root", str(tmp), "--autonomous", "--platform", "none",
               "--browser", args.browser, "--continue-on-failure", "--deterministic"]
        t0 = time.time()
        try:
            rc = subprocess.run(cmd, cwd=str(tmp), timeout=args.timeout).returncode
            note = ""
        except subprocess.TimeoutExpired:
            rc, note = 124, f"pipeline timed out after {args.timeout}s"
        dt = time.time() - t0
        verdict, detail = "—", note
        res = tmp / "test" / "eval_results.json"
        if res.exists():
            try:
                d = json.loads(res.read_text(encoding="utf-8"))
                s = d.get("summary", {})
                verdict = s.get("verdict", "?")
                sp = tmp / "backlog" / "sprint_plan.json"
                st_counts = json.loads(sp.read_text(encoding="utf-8")).get("storyStatusCounts", {}) if sp.exists() else {}
                done_n = st_counts.get("Done", 0)
                tot_s = sum(st_counts.values()) if st_counts else 0
                dep_rep = tmp / "deploy" / "deployment_eval_report.json"
                dep_verdict = (json.loads(dep_rep.read_text(encoding="utf-8")).get("summary") or {}).get("verdict", "?") if dep_rep.exists() else "N/A"
                detail = (f"{s.get('pass', 0)}/{s.get('total', 0)} pass, storiesDone={done_n}/{tot_s}, gdcDeploy={dep_verdict}, browser={d.get('runtime', {}).get('browser')}, "
                          f"leakHits={len(d.get('leakage', {}).get('hits', []))}, unwired={len(d.get('interactivity', {}).get('unwired', []))}")
                if tot_s and done_n != tot_s:
                    verdict = "STORIES_NOT_DONE"
                if dep_rep.exists() and dep_verdict != "PASS":
                    verdict = "DEPLOY_NOT_PASS"
            except Exception as e:  # pragma: no cover
                verdict, detail = "?", f"could not parse eval_results.json: {e}"
        ok = rc == 0 and verdict == "PASS"
        if not ok:
            failed = True
        rows.append((ex.name, "PASS" if ok else "FAIL", str(rc), verdict, dt, detail))
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print(f"   kept: {tmp}")

    print("\n" + "=" * 100)
    print(f"{'golden project':<36}{'result':<8}{'pipeline exit':<15}{'eval verdict':<14}{'secs':>7}  detail")
    print("-" * 100)
    for name, result, rc, verdict, dt, detail in rows:
        print(f"{name:<36}{result:<8}{rc:<15}{verdict:<14}{dt:>7.1f}  {detail}")
    print(f"lint: {'PASS' if lint_rc == 0 else 'FAIL'}")
    print("=" * 100)
    print("GOLDEN PROJECTS: " + ("FAIL" if failed else "PASS"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
