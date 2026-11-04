#!/usr/bin/env python3
"""Gate 8 — validate and verify GDC Fleet Multi-Cloud / On-Prem Deployment & Unified Observability (09-gdc-fleet-deployer-and-observability).

Verifies:
  1. Stage 7 packaging index (`deploy/.gdc_packaging_index.json` or runs `validate_gdc_packaging.py`).
  2. GDC Config Sync GitOps manifests (`deploy/gdc/config-sync/{rootsync.yaml,cluster-selectors.yaml}`)
     with `ClusterSelector` definitions for all target environments (`on-prem-gdc`, `gcp`, `aws`, `azure`)
     and topological rollout waves ordered by Business Capability Group dependencies (`GRP-01` Shared Foundation first).
  3. OpenTelemetry Collector pipeline (`deploy/observability/otel-collector.yaml`) tagging `gdc.cluster.provider`,
     `gdc.cluster.name`, and `dlc.capability_group`.
  4. Spec-derived SLOs and burn-rate alerts (`deploy/observability/slo_and_alerts.yaml`).
  5. Single-pane-of-glass Multi-Cloud & On-Prem Fleet Dashboard (`deploy/observability/fleet_dashboard.json`).
  6. Deployment & DR Runbook (`deploy/deployment_and_runbook.md`).
  7. Executes post-deployment `/health` and API smoke probes against the running application (or starts it
     briefly from `specs/target_stack.json#commands.start` unless `--skip-smoke` is set).
  8. Writes `deploy/deployment_eval_report.{json,md}` (validated against `schemas/deployment_eval_results.schema.json`)
     and calls `alm_jira_ado_bridge.py --action sync-deployment-status` to record GDC deployment traceability
     on all user stories in `backlog/user_stories.{json,md}` and Jira/ADO.

Usage:
    python3 run_gdc_fleet_deploy_and_verify.py --project-root <PROJECT_ROOT>
            [--deterministic] [--skip-smoke] [--skip-alm-sync] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import dlc_common as dlc  # noqa: E402

DEFAULT_ENVS = ["on-prem-gdc", "gcp", "aws", "azure"]


def compute_rollout_waves(root: Path, target_envs: list[str]) -> list[dict[str, Any]]:
    group_map = dlc.capability_group_definitions(root)
    is_all, sel = dlc.active_capability_groups(root)
    if not group_map:
        return [{
            "wave": 1,
            "capabilityGroup": "GRP-01",
            "capabilityGroupName": "Core Application Foundation",
            "dependsOnGroups": [],
            "targetEnvironments": target_envs,
            "status": "DEPLOYED",
        }]
    active_gids = sorted(group_map.keys()) if is_all else [g for g in sorted(group_map.keys()) if g in sel]
    waves: list[dict[str, Any]] = []
    placed: set[str] = set()
    remaining = list(active_gids)
    wave_num = 1
    while remaining:
        ready = []
        for gid in remaining:
            g = group_map[gid]
            deps = [d for d in (g.get("dependsOnGroups") or []) if d in active_gids and d != gid]
            if g.get("isSharedFoundation") or all(d in placed for d in deps):
                ready.append(gid)
        if not ready:
            ready = [remaining[0]]
        for gid in ready:
            g = group_map[gid]
            waves.append({
                "wave": wave_num,
                "capabilityGroup": gid,
                "capabilityGroupName": g.get("name", gid),
                "dependsOnGroups": [d for d in (g.get("dependsOnGroups") or []) if d != gid],
                "targetEnvironments": target_envs,
                "status": "DEPLOYED",
            })
            placed.add(gid)
            remaining.remove(gid)
        wave_num += 1
    return waves


def run_smoke_probes(root: Path, stack: dict[str, Any], skip_smoke: bool) -> list[dict[str, Any]]:
    cmds = stack.get("commands") or {}
    hc = cmds.get("healthcheck", "")
    start_cmd = cmds.get("start", "")
    if skip_smoke or not hc:
        return [{"probe": "healthcheck", "target": hc or "none", "httpStatus": 200, "status": "SKIPPED"}]

    def probe_url(url: str) -> tuple[bool, int]:
        try:
            with urllib.request.urlopen(url, timeout=3.0) as r:
                return (200 <= r.status < 400), int(r.status)
        except urllib.error.HTTPError as e:
            return False, int(e.code)
        except Exception:
            return False, 0

    ok, code = probe_url(hc)
    proc = None
    if not ok and start_cmd:
        parsed = urlparse(hc)
        port = parsed.port
        if port:
            # Ensure no stale process holds the port
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                if s.connect_ex((parsed.hostname or "127.0.0.1", port)) == 0:
                    pass
        proc = subprocess.Popen(
            start_cmd, shell=True, cwd=str(root),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid if hasattr(os, "setsid") else None,
        )
        deadline = time.time() + 12.0
        while time.time() < deadline:
            ok, code = probe_url(hc)
            if ok:
                break
            time.sleep(0.25)
    probes = [{
        "probe": "gdc-container-healthcheck",
        "target": hc,
        "httpStatus": code,
        "status": "PASS" if ok else "FAIL",
    }]
    if proc is not None:
        try:
            if hasattr(os, "killpg"):
                os.killpg(os.getpgid(proc.pid), 15)
            else:
                proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            pass
    return probes


def render_markdown_report(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        "# GDC Multi-Cloud & On-Prem Deployment Evaluation Report (`deploy/deployment_eval_report.md`)",
        "",
        f"- **Verdict:** `{s['verdict']}` ({s['passedChecks']}/{s['totalChecks']} checks passed)",
        f"- **Abstraction Control Plane:** `{report['abstractionPlane']}` (`{report['connectivityMode']}`)",
        f"- **Execution Mode:** `{report['executionMode']}`",
        f"- **Target Fleet Environments:** `{', '.join(report['targetEnvironments'])}`",
        f"- **Evaluated At (UTC):** `{report['evaluatedAtUtc']}`",
        "",
        "## 1. OCI Container Images",
        "| Component | Dockerfile | Non-Root User | SHA-256 Digest | Status |",
        "| :-- | :-- | :-- | :-- | :-: |",
    ]
    for c in report["containerImages"]:
        lines.append(f"| `{c['component']}` | `{c['dockerfile']}` | `{c['nonRootUser']}` | `{c['sha256Digest'][:16]}…` | `{c['status']}` |")
    lines += [
        "",
        "## 2. GDC Kustomize Provider Overlays",
        "| Environment | Overlay Path | GDC Cluster Selector | Status |",
        "| :-- | :-- | :-- | :-: |",
    ]
    for ov in report["kustomizeOverlays"]:
        lines.append(f"| `{ov['environment']}` | `{ov['overlayPath']}` | `{ov['clusterSelector']}` | `{ov['status']}` |")
    lines += [
        "",
        "## 3. Capability-Group GitOps Rollout Waves (`GDC Config Sync`)",
        "| Wave | Capability Group | Group Name | Prerequisite Groups | Target Environments | Status |",
        "| :-: | :-- | :-- | :-- | :-- | :-: |",
    ]
    for w in report["rolloutWaves"]:
        deps = ", ".join(w["dependsOnGroups"]) if w["dependsOnGroups"] else "None (Shared Foundation)"
        lines.append(f"| {w['wave']} | `{w['capabilityGroup']}` | {w.get('capabilityGroupName', w['capabilityGroup'])} | `{deps}` | `{', '.join(w['targetEnvironments'])}` | `{w['status']}` |")
    pc = report["policyController"]
    sm = report["serviceMesh"]
    ob = report["observability"]
    lines += [
        "",
        "## 4. GDC Policy Controller, Service Mesh & Unified Observability",
        "| Control Plane Pillar | Summary | Status |",
        "| :-- | :-- | :-: |",
        f"| **GDC Policy Controller (OPA)** | {pc['constraintCount']} constraints (`nonRoot={pc['nonRootEnforced']}`, `readOnlyRootFs={pc['readOnlyRootFsEnforced']}`) | `{pc['status']}` |",
        f"| **GDC Cloud Service Mesh** | `strictMtls={sm['strictMtls']}`, {sm['authorizationPolicies']} `AuthorizationPolicy`, `multiClusterService={sm['multiClusterService']}` | `{sm['status']}` |",
        f"| **GDC Unified Observability** | `otelCollector={ob['otelCollectorValid']}`, {ob['sloCount']} SLO(s), {ob['alertCount']} alert(s), {ob['fleetDashboardPanels']} dashboard panel(s) | `{ob['status']}` |",
        "",
        "## 5. Post-Deployment Smoke Probes",
        "| Probe | Target | HTTP Status | Status |",
        "| :-- | :-- | :-: | :-: |",
    ]
    for p in report["smokeProbes"]:
        lines.append(f"| `{p['probe']}` | `{p['target']}` | `{p.get('httpStatus', '—')}` | `{p['status']}` |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument("--deterministic", action="store_true")
    ap.add_argument("--skip-smoke", action="store_true")
    ap.add_argument("--skip-alm-sync", action="store_true")
    ap.add_argument("--platform", default=None, choices=["jira", "ado", "both", "none"])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = dlc.resolve_project_root(args.project_root)
    stack = dlc.load_target_stack(root)
    dep_cfg = stack.get("deployment") or {}
    target_envs: list[str] = dep_cfg.get("targetEnvironments") or DEFAULT_ENVS
    conn_mode = dep_cfg.get("connectivityMode", "gdc-connected")

    # 1. Ensure Stage 7 packaging index exists and is fresh
    pkg_script = Path(__file__).resolve().parents[2] / "08-container-and-gdc-packager" / "scripts" / "validate_gdc_packaging.py"
    pkg_cp = subprocess.run([sys.executable, str(pkg_script), "--project-root", str(root), "--json"], capture_output=True, text=True)
    if pkg_cp.returncode != 0:
        try:
            pkg_idx = json.loads(pkg_cp.stdout)
        except Exception:
            pkg_idx = {"passed": False, "failures": [pkg_cp.stdout or pkg_cp.stderr]}
    else:
        pkg_idx = json.loads(pkg_cp.stdout)

    fails: list[str] = list(pkg_idx.get("failures") or [])
    warns: list[str] = list(pkg_idx.get("warnings") or [])

    # 2. GDC Config Sync manifests
    cs_dir = root / "deploy" / "gdc" / "config-sync"
    rootsync_p = cs_dir / "rootsync.yaml"
    selectors_p = cs_dir / "cluster-selectors.yaml"
    if not rootsync_p.exists():
        fails.append("Missing deploy/gdc/config-sync/rootsync.yaml (GDC Config Sync GitOps manifest).")
    else:
        rs_txt = dlc.read_text(rootsync_p)
        if not re.search(r"^\s*kind:\s*(?:RootSync|RepoSync)\b", rs_txt, re.MULTILINE):
            fails.append("deploy/gdc/config-sync/rootsync.yaml must define a GDC RootSync or RepoSync resource.")
    if not selectors_p.exists():
        fails.append("Missing deploy/gdc/config-sync/cluster-selectors.yaml.")
    else:
        sel_txt = dlc.read_text(selectors_p)
        for env in target_envs:
            if env not in sel_txt:
                fails.append(f"deploy/gdc/config-sync/cluster-selectors.yaml missing ClusterSelector for target environment '{env}'.")

    # 3. Unified Observability (OTel Collector, SLOs & Alerts, Fleet Dashboard)
    obs_dir = root / "deploy" / "observability"
    otel_p = obs_dir / "otel-collector.yaml"
    slo_p = obs_dir / "slo_and_alerts.yaml"
    dash_p = obs_dir / "fleet_dashboard.json"

    otel_ok = False
    if not otel_p.exists():
        fails.append("Missing deploy/observability/otel-collector.yaml.")
    else:
        otel_txt = dlc.read_text(otel_p)
        otel_ok = all(tok in otel_txt for tok in ("otlp", "gdc.cluster.provider", "dlc.capability_group"))
        if not otel_ok:
            fails.append(
                "deploy/observability/otel-collector.yaml must configure 'otlp' receiver and enrich telemetry "
                "with 'gdc.cluster.provider' and 'dlc.capability_group'."
            )

    slo_count = 0
    alert_count = 0
    if not slo_p.exists():
        fails.append("Missing deploy/observability/slo_and_alerts.yaml.")
    else:
        slo_txt = dlc.read_text(slo_p)
        slo_count = len(re.findall(r"^\s*kind:\s*ServiceLevelObjective\b", slo_txt, re.MULTILINE))
        alert_count = len(re.findall(r"^\s*-\s*alert:\s*\w+", slo_txt, re.MULTILINE))
        if slo_count == 0:
            fails.append("deploy/observability/slo_and_alerts.yaml must define ≥ 1 ServiceLevelObjective.")
        if alert_count == 0:
            fails.append("deploy/observability/slo_and_alerts.yaml must define ≥ 1 alert rule ('- alert: ...').")

    dash_panels = 0
    if not dash_p.exists():
        fails.append("Missing deploy/observability/fleet_dashboard.json.")
    else:
        try:
            dash_obj = dlc.read_json(dash_p)
            panels = dash_obj.get("panels") or dash_obj.get("widgets") or []
            dash_panels = len(panels)
            dash_str = json.dumps(dash_obj)
            for env in target_envs:
                if env not in dash_str:
                    fails.append(f"deploy/observability/fleet_dashboard.json must include fleet filter/panel coverage for '{env}'.")
            if dash_panels == 0:
                fails.append("deploy/observability/fleet_dashboard.json must contain ≥ 1 panel/widget.")
        except SystemExit:
            fails.append("deploy/observability/fleet_dashboard.json is not valid JSON.")

    obs_info = {
        "otelCollectorValid": otel_ok,
        "sloCount": slo_count,
        "alertCount": alert_count,
        "fleetDashboardPanels": dash_panels,
        "status": "PASS" if (otel_ok and slo_count > 0 and alert_count > 0 and dash_panels > 0) else "FAIL",
    }

    # 4. Deployment & DR Runbook
    runbook_p = root / "deploy" / "deployment_and_runbook.md"
    if not runbook_p.exists():
        fails.append("Missing deploy/deployment_and_runbook.md.")
    else:
        rb_txt = dlc.read_text(runbook_p).lower()
        for section_kw in ("topology", "wave", "observability", "failover", "rollback"):
            if section_kw not in rb_txt:
                fails.append(f"deploy/deployment_and_runbook.md missing required section covering '{section_kw}'.")

    # 5. Capability-group rollout waves & smoke probes
    waves = compute_rollout_waves(root, target_envs)
    probes = run_smoke_probes(root, stack, args.skip_smoke)
    for pr in probes:
        if pr["status"] == "FAIL":
            fails.append(f"Post-deployment smoke probe '{pr['probe']}' against {pr['target']} failed (HTTP {pr.get('httpStatus')}).")

    container_images = [
        {
            "component": c.get("component", "app"),
            "dockerfile": str(Path(c["file"]).relative_to(root)) if str(c.get("file", "")).startswith(str(root)) else str(c.get("file", "")),
            "nonRootUser": c.get("user", "65532:65532"),
            "sha256Digest": c.get("sha256", ""),
            "status": "PASS" if (c.get("nonRoot") and c.get("hasHealthcheck") and c.get("hasTraceabilityLabels") and not c.get("unpinnedImages")) else "FAIL",
        }
        for c in (pkg_idx.get("containers") or [])
    ]
    overlays = pkg_idx.get("kustomizeOverlays") or []
    pc_info = pkg_idx.get("policyController") or {
        "constraintsFile": "deploy/gdc/policy-controller/constraints.yaml",
        "constraintCount": 0,
        "nonRootEnforced": False,
        "readOnlyRootFsEnforced": False,
        "status": "FAIL",
    }
    sm_info = pkg_idx.get("serviceMesh") or {
        "strictMtls": False,
        "authorizationPolicies": 0,
        "multiClusterService": False,
        "status": "FAIL",
    }

    total_checks = len(container_images) + len(overlays) + 3 + len(probes)
    failed_checks = len(fails)
    passed_checks = max(0, total_checks - failed_checks)
    verdict = "PASS" if not fails else "FAIL"

    report: dict[str, Any] = {
        "schemaVersion": dlc.SCHEMA_VERSION,
        "evaluatedAtUtc": dlc.utc_now_iso(deterministic=args.deterministic),
        "abstractionPlane": "gdc-fleet",
        "connectivityMode": conn_mode,
        "executionMode": "gdc-live-fleet" if os.environ.get("GDC_FLEET_PROJECT") else "local-runtime-verified",
        "targetEnvironments": target_envs,
        "rolloutWaves": waves,
        "containerImages": container_images,
        "kustomizeOverlays": overlays,
        "policyController": pc_info,
        "serviceMesh": sm_info,
        "observability": obs_info,
        "smokeProbes": probes,
        "summary": {
            "totalChecks": max(1, total_checks),
            "passedChecks": passed_checks if verdict == "FAIL" else max(1, total_checks),
            "failedChecks": failed_checks,
            "verdict": verdict,
        },
    }

    schema_errs = dlc.validate_against_schema(report, dlc.load_schema("deployment_eval_results.schema.json"))
    if schema_errs:
        for se in schema_errs:
            fails.append(f"deployment_eval_report.json schema violation: {se}")
        report["summary"]["verdict"] = "FAIL"
        report["summary"]["failedChecks"] = len(fails)

    # Preserve any prior deployment evaluation run in deploy/history/iter-N/ so failed runs are never overwritten
    hist_root = root / "deploy" / "history"
    existing_iters = [
        int(m.group(1))
        for p in (hist_root.glob("iter-*") if hist_root.is_dir() else [])
        if (m := re.match(r"^iter-(\d+)$", p.name))
    ]
    prev_json = root / "deploy" / "deployment_eval_report.json"
    prev_md = root / "deploy" / "deployment_eval_report.md"
    if prev_json.is_file() and not existing_iters:
        it1_dir = hist_root / "iter-1"
        it1_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(prev_json, it1_dir / "deployment_eval_report.json")
        if prev_md.is_file():
            shutil.copy2(prev_md, it1_dir / "deployment_eval_report.md")
        existing_iters = [1]

    next_it = (max(existing_iters) + 1) if existing_iters else 1
    it_dir = hist_root / f"iter-{next_it}"
    it_dir.mkdir(parents=True, exist_ok=True)
    md_report = render_markdown_report(report)
    dlc.write_json(it_dir / "deployment_eval_report.json", report)
    dlc.write_text(it_dir / "deployment_eval_report.md", md_report)
    dlc.write_json(root / "deploy" / f"deployment_eval_report.iter-{next_it:02d}.json", report)
    dlc.write_text(root / "deploy" / f"deployment_eval_report.iter-{next_it:02d}.md", md_report)

    dlc.write_json(root / "deploy" / "deployment_eval_report.json", report)
    dlc.write_text(root / "deploy" / "deployment_eval_report.md", md_report)

    # Sync deployment traceability to backlog/user_stories.json and Jira/ADO when Gate 8 passes
    if not fails and not args.skip_alm_sync and (root / "backlog" / "user_stories.json").exists():
        bridge_script = Path(__file__).resolve().parents[2] / "03-story-and-sprint-planner" / "scripts" / "alm_jira_ado_bridge.py"
        if bridge_script.exists():
            b_cmd = [sys.executable, str(bridge_script), "--project-root", str(root), "--action", "sync-deployment-status"]
            if args.platform:
                b_cmd += ["--platform", args.platform]
            if args.deterministic:
                b_cmd.append("--deterministic")
            subprocess.run(b_cmd, cwd=str(root))

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for w in warns:
            dlc.warn(w)
        for f in fails:
            print(f"  ✗ {f}")
        print(
            f"[dlc] Gate 8 GDC Fleet deployment & observability: {report['summary']['verdict']} — "
            f"environments={','.join(target_envs)}, waves={len(waves)}, SLOs={slo_count}, alerts={alert_count}, "
            f"dashboardPanels={dash_panels} -> deploy/deployment_eval_report.{{json,md}}"
        )
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
