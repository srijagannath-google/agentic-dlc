#!/usr/bin/env python3
"""Runs the verify + derive pipeline over every golden project under `examples/*/` that has `expected_artifacts/`.

For each example:
  1. copies `inputs/` → `<tmp>/resources/inputs/`, `policies_and_statutes/` and `shared_services/` (if present)
     → `<tmp>/resources/…`, and `expected_artifacts/*` → `<tmp>/` (specs/, backlog/, design/, test/, src/ …),
     then strips every prior *output* (eval results/reports, deployment report, snapshots, build logs) and
     resets story statuses to `To Do` so the summary can only reflect this run;
  2. runs `scripts/run_agentic_dlc_pipeline.py --autonomous --platform none --browser auto --continue-on-failure`
     with `DLC_GOLDEN_RUN=1` in its environment;
  3. records the pipeline exit code and the Stage 6 verdict from `<tmp>/test/eval_results.json`.

`scripts/lint_domain_neutrality.py` runs first; the whole run fails if it fails.

Usage: python3 verify_golden_projects.py [--only <example-name>] [--keep] [--browser auto|chrome|none]
Exit 1 if the lint fails or any golden project does not finish with pipeline exit 0 and eval verdict PASS.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
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
    # Golden projects start fresh: the staged copy must not carry any prior run's *outputs*, otherwise the
    # summary columns (eval verdict, storiesDone, gdcDeploy) could show stale PASS values that this run never
    # produced. Remove iteration snapshots/logs/history and every Stage 6/8 result file, and reset ALM status.
    for stale in (
        dest / "test" / ".snapshots",
        dest / "test" / ".build_logs",
        dest / "test" / "history",
        dest / "deploy" / "history",
        dest / ".chrome-smoke-profile",
    ):
        shutil.rmtree(stale, ignore_errors=True)
    for stale_file in (
        dest / "test" / "eval_results.json",
        dest / "test" / "eval_report.md",
        dest / "test" / "remediation_and_guardrail_audit_report.md",
        dest / "test" / ".guardrail_state.json",
        *sorted((dest / "test").glob("*.iter-*")),
        *sorted((dest / "deploy").glob("deployment_eval_report*")),
        dest / "specs" / "gate_approvals.json",
    ):
        try:
            stale_file.unlink()
        except FileNotFoundError:
            pass
    reset_alm_runtime_status(dest)
    return copied


def _write_json(p: Path, data: object) -> None:
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def reset_alm_runtime_status(dest: Path) -> None:
    """Reset every story to `To Do` (dropping runtime status fields) and the sprint plan's approval / status
    counters, so `storiesDone` in the summary only reflects transitions made by *this* pipeline run."""
    stories_p = dest / "backlog" / "user_stories.json"
    if stories_p.is_file():
        try:
            data = json.loads(stories_p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = None
        stories = data.get("stories") if isinstance(data, dict) else data
        if isinstance(stories, list):
            for s in stories:
                if isinstance(s, dict):
                    s["status"] = "To Do"
                    for k in ("statusReason", "statusUpdatedAtUtc", "jiraKey", "adoWorkItemId", "lastSyncedAtUtc", "traceability"):
                        s.pop(k, None)
            _write_json(stories_p, data)
    plan_p = dest / "backlog" / "sprint_plan.json"
    if plan_p.is_file():
        try:
            plan = json.loads(plan_p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            plan = None
        if isinstance(plan, dict):
            if "approvalStatus" in plan:
                plan["approvalStatus"] = "PENDING_HUMAN_APPROVAL"  # --autonomous re-applies PRE_APPROVED_BY_USER
            n_stories = 0
            for sprint in plan.get("sprints") or []:
                if isinstance(sprint, dict) and isinstance(sprint.get("storyStatuses"), dict):
                    sprint["storyStatuses"] = {k: "To Do" for k in sprint["storyStatuses"]}
                    n_stories += len(sprint["storyStatuses"])
            backlog = plan.get("productBacklog")
            if isinstance(backlog, list):
                n_stories += len(backlog)
            if isinstance(plan.get("storyStatusCounts"), dict):
                plan["storyStatusCounts"] = {"To Do": int(plan.get("totalStories") or n_stories), "In Progress": 0, "Done": 0}
            _write_json(plan_p, plan)
    for state in (dest / "backlog" / "jira_state.json", dest / "backlog" / "azure_devops_state.json"):
        try:
            state.unlink()
        except FileNotFoundError:
            pass


def run_pipeline(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str]:
    """Run the pipeline in its own process group with DLC_GOLDEN_RUN=1 so a timeout kills the whole tree."""
    env = dict(os.environ)
    env["DLC_GOLDEN_RUN"] = "1"
    popen_kwargs: dict = {"cwd": str(cwd), "env": env}
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **popen_kwargs)
    try:
        return proc.wait(timeout=timeout), ""
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        return 124, f"pipeline timed out after {timeout}s (process group killed)"


def _kill_group(proc: subprocess.Popen) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            if os.name == "nt":
                proc.kill()
            else:
                os.killpg(os.getpgid(proc.pid), sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            continue
    try:
        proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass


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
        rc, note = run_pipeline(cmd, tmp, args.timeout)
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
