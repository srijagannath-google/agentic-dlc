#!/usr/bin/env python3
"""VERIFY-ONLY orchestrator for agentic-dlc v4.

Runs every deterministic gate script in stage order against an existing `<PROJECT_ROOT>`. It **never**
authors, copies or templates any artefact: when an upstream artefact is missing it prints exactly which
skill / subagent must author it and exits 2 (docs/ARCHITECTURE.md §1.2, §5).

Order (each step is a subprocess of the sibling skill script, resolved relative to this plugin root):
  01 scan_input_sources → 01 validate_discovery_blueprint → 02 lint_spec_structure → 02 validate_spec_scorecard
  → 03 alm_jira_ado_bridge --action audit → 04 extract_contracts → 05 derive_test_cases (only if test_cases.json
  is missing or --rederive) → 05 validate_test_cases → 06 check_testid_contract → 06 validate_build
  → 07 run_closed_loop_eval → 08 validate_gdc_packaging (if deploy/ or deployment config present)
  → 09 run_gdc_fleet_deploy_and_verify (if deploy/ or deployment config present)

Usage:
  python3 run_agentic_dlc_pipeline.py --project-root <PROJECT_ROOT> [--from-stage 1] [--to-stage 9]
      [--autonomous] [--platform jira|ado|both|none] [--browser auto|playwright|chrome|none]
      [--continue-on-failure] [--rederive] [--deterministic] [--skip-backend]

Exit codes: 0 all gates passed · 1 a gate failed · 2 an artefact is missing (LLM stage must author it)
            · 3 Stage 6 passed but guardrail-sensitive hunks need human approval (Gate 4).
A script that does not exist yet is reported as SKIPPED-MISSING (never a crash).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dlc_common as dlc  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILLS = PLUGIN_ROOT / "skills"
S01 = SKILLS / "01-discovery-and-grouping" / "scripts"
S02 = SKILLS / "02-spec-architect-and-judge" / "scripts"
S03 = SKILLS / "03-story-and-sprint-planner" / "scripts"
S04 = SKILLS / "04-solution-architect" / "scripts"
S05 = SKILLS / "05-test-plan-designer" / "scripts"
S06 = SKILLS / "06-coding-agent" / "scripts"
S07 = SKILLS / "07-test-runner-and-healer" / "scripts"
S08 = SKILLS / "08-container-and-gdc-packager" / "scripts"
S09 = SKILLS / "09-gdc-fleet-deployer-and-observability" / "scripts"


class Step:
    def __init__(self, stage: int, key: str, label: str, script: Path, args: Callable[[argparse.Namespace], list[str]],
                 requires: list[tuple[str, str]] | None = None, condition: Callable[[Path, argparse.Namespace], bool] | None = None,
                 pre: Callable[[Path, argparse.Namespace], list[list[str]]] | None = None, ok_codes: tuple[int, ...] = (0,)):
        self.stage, self.key, self.label, self.script, self.args = stage, key, label, script, args
        self.requires = requires or []       # (relative artefact path, who must author it)
        self.condition = condition            # return False to skip the step
        self.pre = pre                        # extra argv lists to run before the main command (e.g. set-approval)
        self.ok_codes = ok_codes


def has_inputs(root: Path) -> bool:
    d = root / "resources" / "inputs"
    return d.exists() and any(p.is_file() for p in d.rglob("*"))


def scenario_is_legacy(root: Path) -> bool:
    p = root / "specs" / "input_inventory.json"
    try:
        return p.exists() and dlc.read_json(p).get("inputScenario") == "SCENARIO_LEGACY_APP"
    except SystemExit:
        return False


def backend_present(root: Path) -> bool:
    try:
        return (dlc.load_target_stack(root).get("backend") or {}).get("kind", "none") != "none"
    except SystemExit:
        return False


def deployment_present(root: Path) -> bool:
    if (root / "deploy").exists():
        return True
    try:
        return bool(dlc.load_target_stack(root).get("deployment"))
    except SystemExit:
        return False


def build_steps(a: argparse.Namespace) -> list[Step]:
    det = ["--deterministic"] if a.deterministic else []
    platform = ["--platform", a.platform] if a.platform else []
    return [
        Step(1, "01-scan", "Stage 1 · scan inputs → specs/input_inventory.json", S01 / "scan_input_sources.py", lambda a: det,
             requires=[("resources/inputs", "the USER (place legacy exports or requirement documents in resources/inputs/)")]),
        Step(1, "01-blueprint", "Gate 1 · discovery blueprint + target stack", S01 / "validate_discovery_blueprint.py", lambda a: [],
             requires=[("specs/discovery_architecture_and_inventory.md", "Stage 1 discovery-architect (skill 01-discovery-and-grouping)"),
                       ("specs/target_stack.json", "Gate 1 discovery-architect, from the user's stack answers (docs/ARCHITECTURE.md §4.2)")]),
        Step(2, "02-lint", "Stage 2 · spec structure lint", S02 / "lint_spec_structure.py", lambda a: [],
             requires=[("specs/application_spec.md", "Stage 2 discovery-architect (skill 02-spec-architect-and-judge)"),
                       ("specs/traceability_matrix.md", "Stage 2 discovery-architect (skill 02-spec-architect-and-judge)")]),
        Step(2, "02-judge", "Gate 2 · LLM spec scorecard validation", S02 / "validate_spec_scorecard.py", lambda a: [],
             requires=[("specs/application_eval_scorecard.json", "Stage 2 spec-judge (scores specs/application_spec.md against schemas/spec_rubric.json)")]),
        Step(3, "03-audit", "Gate 3 · backlog coverage audit (+ approval)", S03 / "alm_jira_ado_bridge.py",
             lambda a: ["--action", "audit", *platform, *det] + (["--approved"] if a.autonomous else []),
             requires=[("backlog/user_stories.json", "Stage 3 sprint-planner-agent (skill 03-story-and-sprint-planner)"),
                       ("backlog/sprint_plan.md", "Stage 3 sprint-planner-agent (skill 03-story-and-sprint-planner)")],
             pre=lambda root, a: ([["--action", "set-approval", "--set-approval", "PRE_APPROVED_BY_USER", *platform, *det]] if a.autonomous else [])),
        Step(4, "04-contracts", "Gate 4a · validate Well-Architected architecture + extract OpenAPI & DDL from solution design", S04 / "extract_contracts.py", lambda a: [],
             requires=[("design/architecture_design.md", "Stage 4A solution-architect (skill 04-solution-architect)"),
                       ("design/solution_design.md", "Stage 4A solution-architect (skill 04-solution-architect)")]),
        Step(4, "04-migration", "Stage 4A · legacy data migration plan present", None, lambda a: [],  # type: ignore[arg-type]
             requires=[("design/data_migration_and_cutover.md", "Stage 4A solution-architect — required only for SCENARIO_LEGACY_APP")],
             condition=lambda root, a: scenario_is_legacy(root)),
        Step(5, "05-derive", "Stage 4B · derive test-case skeleton", S05 / "derive_test_cases.py", lambda a: det,
             requires=[("backlog/user_stories.json", "Stage 3 sprint-planner-agent")],
             condition=lambda root, a: a.rederive or not (root / "test" / "test_cases.json").exists()),
        Step(5, "05-validate", "Gate 4b · test cases complete (every AC → TC, every TC has steps)", S05 / "validate_test_cases.py", lambda a: [],
             requires=[("test/test_cases.json", "Stage 4B testing-agent fills `steps` in the skeleton from 05/scripts/derive_test_cases.py"),
                       ("test/test_plan.md", "Stage 4B testing-agent (skill 05-test-plan-designer)")]),
        Step(6, "06-testids", "Stage 5 · data-testid contract implemented", S06 / "check_testid_contract.py", lambda a: [],
             requires=[("src/ui", "Stage 5 coding-agent (skill 06-coding-agent)")]),
        Step(6, "06-build", "Gate 5 · install/build/start/healthcheck (+ mark stories In Progress)", S06 / "validate_build.py", lambda a: [*det],
             requires=[("src/README.md", "Stage 5 coding-agent (skill 06-coding-agent)")]),
        Step(7, "07-eval", "Gate 6 · closed-loop browser/http/static evaluation", S07 / "run_closed_loop_eval.py",
             lambda a: ["--browser", a.browser, "--skip-alm-sync", *det] + (["--skip-backend"] if a.skip_backend else []) + (["--approve-guardrail-flags"] if a.approve_guardrail_flags else []),
             requires=[("test/test_cases.json", "Stage 4B testing-agent")], ok_codes=(0, 3)),
        Step(7, "07-alm-status", "Stage 6 · transition verified user stories to Done in backlog & Jira/ADO", S03 / "alm_jira_ado_bridge.py",
             lambda a: ["--action", "sync-status-from-eval", *platform, *det],
             requires=[("backlog/user_stories.json", "Stage 3 sprint-planner-agent"),
                       ("test/eval_results.json", "Stage 6 run_closed_loop_eval.py")], ok_codes=(0, 2)),
        Step(8, "08-gdc-pkg", "Gate 7 · cloud-agnostic OCI containers & GDC multi-cloud KRM packaging", S08 / "validate_gdc_packaging.py",
             lambda a: [],
             requires=[("deploy/containers/Dockerfile.backend", "Stage 7 platform-ops-agent (skill 08-container-and-gdc-packager)"),
                       ("deploy/gdc/base/workloads.yaml", "Stage 7 platform-ops-agent (skill 08-container-and-gdc-packager)")],
             condition=lambda root, a: deployment_present(root)),
        Step(9, "09-gdc-deploy", "Gate 8 · GDC Fleet GitOps deployment, observability & SLO verification", S09 / "run_gdc_fleet_deploy_and_verify.py",
             lambda a: [*det, *platform] + (["--skip-smoke"] if a.skip_backend else []),
             requires=[("deploy/gdc/config-sync/rootsync.yaml", "Stage 8 platform-ops-agent (skill 09-gdc-fleet-deployer-and-observability)"),
                       ("deploy/observability/otel-collector.yaml", "Stage 8 platform-ops-agent (skill 09-gdc-fleet-deployer-and-observability)"),
                       ("deploy/deployment_and_runbook.md", "Stage 8 platform-ops-agent (skill 09-gdc-fleet-deployer-and-observability)")],
             condition=lambda root, a: deployment_present(root)),
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument("--from-stage", type=int, default=1, choices=range(1, 10))
    ap.add_argument("--to-stage", type=int, default=9, choices=range(1, 10))
    ap.add_argument("--autonomous", action="store_true", help="Pre-approve Gate 3 (sets PRE_APPROVED_BY_USER via the bridge) and never prompt")
    ap.add_argument("--platform", default=None, choices=["jira", "ado", "both", "none"], help="ALM platform for the Stage 3 bridge (default: target_stack.json#almPlatform)")
    ap.add_argument("--browser", default="auto", choices=["auto", "playwright", "chrome", "none"])
    ap.add_argument("--continue-on-failure", action="store_true", help="Run all remaining gates even after a failure / missing artefact")
    ap.add_argument("--rederive", action="store_true", help="Re-run derive_test_cases even if test/test_cases.json exists")
    ap.add_argument("--deterministic", action="store_true")
    ap.add_argument("--skip-backend", action="store_true", help="Pass through to Stage 6 (backend already running)")
    ap.add_argument("--approve-guardrail-flags", action="store_true", help="Pass through to Stage 6 after a human reviewed the audit report")
    args = ap.parse_args()

    root = dlc.resolve_project_root(args.project_root)
    if dlc.is_installer_dir(root) or root == PLUGIN_ROOT:
        raise dlc.GateFailure(f"{root} is the plugin directory, not a project root (see _shared/project_root.md).")
    print(f"agentic-dlc v4 — verify-only pipeline\n  project root : {root}\n  plugin root  : {PLUGIN_ROOT}\n  stages       : {args.from_stage}..{args.to_stage}"
          f"{'  (autonomous: Gate 3 pre-approved)' if args.autonomous else ''}")

    rows: list[tuple[str, str, str, float, str]] = []
    worst = 0
    stop = False
    for step in build_steps(args):
        if not (args.from_stage <= step.stage <= args.to_stage):
            continue
        if stop:
            rows.append((step.key, step.label, "SKIPPED", 0.0, "earlier gate failed"))
            continue
        if step.condition and not step.condition(root, args):
            rows.append((step.key, step.label, "SKIPPED", 0.0, "not applicable (condition false)"))
            continue
        # artefact presence — the only thing this orchestrator checks itself
        missing = []
        for rel, who in step.requires:
            p = root / rel
            if p.is_dir():
                present = any(f.is_file() for f in p.rglob("*"))
            else:
                present = p.is_file() and p.stat().st_size > 0
            if not present:
                missing.append((rel, who))
        if missing:
            for rel, who in missing:
                print(f"\n[MISSING ARTEFACT] {rel}\n  → must be authored by: {who}\n  v4 scripts never substitute templates.")
            rows.append((step.key, step.label, "MISSING", 0.0, "; ".join(f"{rel} ← {who}" for rel, who in missing)))
            worst = max(worst, 2)
            if not args.continue_on_failure:
                stop = True
            continue
        if step.script is None:  # presence-only step
            rows.append((step.key, step.label, "PASS", 0.0, "artefact present"))
            continue
        if not step.script.exists():
            rows.append((step.key, step.label, "SKIPPED-MISSING", 0.0, f"script not found: {step.script.relative_to(PLUGIN_ROOT)}"))
            continue
        base = [sys.executable, str(step.script), "--project-root", str(root)]
        t0 = time.time()
        rc = 0
        for extra in (step.pre(root, args) if step.pre else []):
            print(f"\n$ {' '.join([step.script.name, *extra])}")
            rc = subprocess.run(base + extra, cwd=str(root)).returncode
            if rc != 0:
                break
        if rc == 0:
            argv = base + step.args(args)
            print(f"\n{'=' * 78}\n {step.label}\n$ {step.script.name} {' '.join(argv[3:])}\n{'=' * 78}")
            rc = subprocess.run(argv, cwd=str(root)).returncode
        dt = time.time() - t0
        if rc in step.ok_codes and rc == 0:
            rows.append((step.key, step.label, "PASS", dt, ""))
        elif rc in step.ok_codes:
            rows.append((step.key, step.label, "NEEDS-HUMAN-APPROVAL", dt, "Gate 4: review test/remediation_and_guardrail_audit_report.md, then re-run with --approve-guardrail-flags"))
            worst = max(worst, 3)
        else:
            rows.append((step.key, step.label, "FAIL", dt, f"exit {rc}"))
            worst = max(worst, 1) if worst != 2 else 2
            if not args.continue_on_failure:
                stop = True

    print("\n" + "=" * 78 + "\n STAGE TABLE\n" + "=" * 78)
    print(f"{'step':<14}{'status':<22}{'secs':>7}  label / detail")
    for key, label, status, dt, detail in rows:
        print(f"{key:<14}{status:<22}{dt:>7.1f}  {label}" + (f"\n{'':<43}↳ {detail}" if detail else ""))
    final = {0: "ALL GATES PASSED", 1: "GATE FAILED", 2: "ARTEFACT(S) MISSING — an LLM stage must author them", 3: "PASSED — GATE 4 NEEDS HUMAN APPROVAL"}[worst]
    print(f"\nRESULT: {final} (exit {worst})")
    return worst


if __name__ == "__main__":
    sys.exit(main())
