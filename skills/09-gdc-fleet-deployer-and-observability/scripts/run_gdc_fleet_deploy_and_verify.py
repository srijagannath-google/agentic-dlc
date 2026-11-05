#!/usr/bin/env python3
"""Gate 8 — validate (and optionally live-apply) GDC Fleet Multi-Cloud / On-Prem Deployment & Unified Observability
(09-gdc-fleet-deployer-and-observability).

Default execution mode is **manifest-validation**: nothing is pushed to any cluster. The script verifies:
  1. Stage 7 packaging index (re-runs `validate_gdc_packaging.py`; its failures are inherited).
  2. GDC Config Sync GitOps manifests (`deploy/gdc/config-sync/{rootsync.yaml,cluster-selectors.yaml}`)
     with `ClusterSelector` definitions for all target environments (`on-prem-gdc`, `gcp`, `aws`, `azure`)
     and topological rollout waves ordered by Business Capability Group dependencies (`GRP-01` Shared Foundation first).
  3. OpenTelemetry Collector pipeline (`deploy/observability/otel-collector.yaml`) tagging `gdc.cluster.provider`,
     `gdc.cluster.name`, and `dlc.capability_group`.
  4. Spec-derived SLOs and burn-rate alerts (`deploy/observability/slo_and_alerts.yaml`).
  5. Single-pane-of-glass Multi-Cloud & On-Prem Fleet Dashboard (`deploy/observability/fleet_dashboard.json`).
  6. Deployment & DR Runbook (`deploy/deployment_and_runbook.md`).
  7. A **local** smoke probe: `specs/target_stack.json#commands.healthcheck` against the application started
     locally from `commands.start` (unless `--skip-smoke`). This is NOT a post-deployment probe of a GDC cluster.
     `--skip-smoke` (or an empty healthcheck) records `httpStatus: null, status: SKIPPED`; a SKIPPED probe counts
     as a FAILED check unless `--allow-skipped-smoke` is passed.
  8. Writes `deploy/deployment_eval_report.{json,md}` (validated against `schemas/deployment_eval_results.schema.json`)
     and calls `alm_jira_ado_bridge.py --action sync-deployment-status` (exit 2 → warning, other non-zero → FAIL).

Rollout waves are labelled `MANIFEST_VALIDATED` in the default mode. Only when `--live` is passed, `kubectl` is
on PATH, and `kubectl apply -k deploy/gdc/overlays/<env>` succeeds for every target environment of a wave is that
wave labelled `DEPLOYED` and the report's `executionMode` set to `gdc-live-fleet`. Per-environment kube contexts may
be supplied via `GDC_KUBE_CONTEXT_<ENV>` (e.g. `GDC_KUBE_CONTEXT_ON_PREM_GDC`); otherwise the current context is used.

Usage:
    python3 run_gdc_fleet_deploy_and_verify.py --project-root <PROJECT_ROOT>
            [--deterministic] [--skip-smoke] [--allow-skipped-smoke] [--skip-alm-sync]
            [--platform jira|ado|both|none] [--live] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
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
WAVE_STATUS_VALIDATED = "MANIFEST_VALIDATED"
WAVE_STATUS_DEPLOYED = "DEPLOYED"
WAVE_STATUS_FAILED = "FAILED"
EXEC_MODE_MANIFEST = "manifest-validation"
EXEC_MODE_LIVE = "gdc-live-fleet"


# --------------------------------------------------------------------------------------
# Process-group helpers (prefer dlc_common implementations when present)
# --------------------------------------------------------------------------------------
def _start_process_group_fallback(cmd: str, cwd: Path) -> subprocess.Popen:
    kwargs: dict[str, Any] = {}
    if os.name == "nt":  # pragma: no cover - Windows
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    elif hasattr(os, "setsid"):
        kwargs["preexec_fn"] = os.setsid
    # TRUST BOUNDARY: `cmd` comes from specs/target_stack.json#commands.start, which is authored by the
    # solution-architect at Gate 4A and approved by the human. It is executed with shell=True exactly as
    # written (so `&&`, env assignments and quoting work for every target stack). Never point this script at a
    # project whose target_stack.json you have not reviewed — see docs/KNOWN_ISSUES.md.
    print(f"[dlc] starting application for local smoke probe (shell): {cmd}")
    return subprocess.Popen(cmd, shell=True, cwd=str(cwd), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)


def _stop_process_group_fallback(proc: subprocess.Popen) -> None:
    try:
        if os.name != "nt" and hasattr(os, "killpg"):
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        else:
            proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            if os.name != "nt" and hasattr(os, "killpg"):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except Exception:
            pass


def start_process_group(cmd: str, cwd: Path) -> subprocess.Popen:
    fn = getattr(dlc, "start_process_group", None)
    if callable(fn):
        print(f"[dlc] starting application for local smoke probe (shell): {cmd}")
        return fn(cmd, cwd)  # type: ignore[misc]
    return _start_process_group_fallback(cmd, cwd)


def stop_process_group(proc: subprocess.Popen) -> None:
    fn = getattr(dlc, "stop_process_group", None)
    if callable(fn):
        fn(proc)  # type: ignore[misc]
        return
    _stop_process_group_fallback(proc)


# --------------------------------------------------------------------------------------
# Rollout waves
# --------------------------------------------------------------------------------------
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
            "status": WAVE_STATUS_VALIDATED,
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
                "status": WAVE_STATUS_VALIDATED,
            })
            placed.add(gid)
            remaining.remove(gid)
        wave_num += 1
    return waves


def live_apply_overlays(root: Path, target_envs: list[str], waves: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """`--live`: kubectl apply -k deploy/gdc/overlays/<env> for every env. Returns (all_ok, failures)."""
    failures: list[str] = []
    kubectl = shutil.which("kubectl")
    if not kubectl:
        return False, ["--live requested but `kubectl` is not on PATH; waves stay MANIFEST_VALIDATED."]
    env_ok: dict[str, bool] = {}
    for env in target_envs:
        overlay = root / "deploy" / "gdc" / "overlays" / env
        cmd = [kubectl, "apply", "-k", str(overlay)]
        ctx = os.environ.get("GDC_KUBE_CONTEXT_" + re.sub(r"[^A-Z0-9]", "_", env.upper()))
        if ctx:
            cmd += ["--context", ctx]
        print(f"[dlc] live apply: {' '.join(cmd)}")
        cp = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)
        env_ok[env] = cp.returncode == 0
        if cp.returncode != 0:
            failures.append(f"Live `kubectl apply -k deploy/gdc/overlays/{env}` failed (rc={cp.returncode}): {(cp.stderr or cp.stdout).strip()[:400]}")
    all_ok = all(env_ok.get(e) for e in target_envs)
    for w in waves:
        w["status"] = WAVE_STATUS_DEPLOYED if all(env_ok.get(e) for e in w["targetEnvironments"]) else WAVE_STATUS_FAILED
    return all_ok, failures


# --------------------------------------------------------------------------------------
# Local smoke probe
# --------------------------------------------------------------------------------------
def _probe_url(url: str) -> tuple[bool, int | None]:
    try:
        with urllib.request.urlopen(url, timeout=3.0) as r:
            return (200 <= r.status < 400), int(r.status)
    except urllib.error.HTTPError as e:
        return False, int(e.code)
    except Exception:
        return False, None


def _port_is_listening(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def run_smoke_probes(root: Path, stack: dict[str, Any], skip_smoke: bool) -> list[dict[str, Any]]:
    cmds = stack.get("commands") or {}
    hc = (cmds.get("healthcheck") or "").strip()
    start_cmd = (cmds.get("start") or "").strip()
    if skip_smoke or not hc:
        return [{
            "probe": "local-healthcheck",
            "target": hc or "none",
            "httpStatus": None,
            "status": "SKIPPED",
            "detail": "--skip-smoke passed" if skip_smoke else "specs/target_stack.json#commands.healthcheck is empty",
        }]

    parsed = urlparse(hc)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    # A process already answering on the healthcheck port before we start anything means the probe cannot
    # attribute the result to this project's build (stale server from an earlier run, or another worker).
    if _port_is_listening(host, port):
        return [{
            "probe": "local-healthcheck",
            "target": hc,
            "httpStatus": None,
            "status": "FAIL",
            "detail": (
                f"Port {host}:{port} was already answering BEFORE the application was started — a stale or foreign "
                "process holds the healthcheck port, so the smoke result cannot be attributed to this build. "
                "Stop the other process (or change commands.healthcheck/start to a free port) and re-run."
            ),
        }]

    if not start_cmd:
        return [{
            "probe": "local-healthcheck",
            "target": hc,
            "httpStatus": None,
            "status": "FAIL",
            "detail": "commands.healthcheck is set but commands.start is empty — nothing to start for the local smoke probe.",
        }]

    proc = start_process_group(start_cmd, root)
    ok, code = False, None
    try:
        deadline = time.time() + 20.0
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            ok, code = _probe_url(hc)
            if ok:
                break
            time.sleep(0.25)
        if not ok and proc.poll() is not None:
            detail = f"start command exited early (rc={proc.returncode}) before the healthcheck answered."
        elif not ok:
            detail = "healthcheck did not return 2xx/3xx within 20s of starting the application."
        else:
            detail = "local application started from commands.start answered the healthcheck."
    finally:
        stop_process_group(proc)
    return [{
        "probe": "local-healthcheck",
        "target": hc,
        "httpStatus": code,
        "status": "PASS" if ok else "FAIL",
        "detail": detail,
    }]


# --------------------------------------------------------------------------------------
# Report rendering
# --------------------------------------------------------------------------------------
def render_markdown_report(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        "# GDC Multi-Cloud & On-Prem Deployment Evaluation Report (`deploy/deployment_eval_report.md`)",
        "",
        f"- **Verdict:** `{s['verdict']}` ({s['passedChecks']}/{s['totalChecks']} checks passed, {s['failedChecks']} failed)",
        f"- **Abstraction Control Plane:** `{report['abstractionPlane']}` (`{report['connectivityMode']}`)",
        f"- **Execution Mode:** `{report['executionMode']}`"
        + (" — manifests validated statically; nothing was applied to a cluster." if report["executionMode"] == EXEC_MODE_MANIFEST else " — `kubectl apply -k` succeeded for every target environment."),
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
        "## 5. Local Smoke Probe (application started from `commands.start`; not a cluster probe)",
        "| Probe | Target | HTTP Status | Status | Detail |",
        "| :-- | :-- | :-: | :-: | :-- |",
    ]
    for p in report["smokeProbes"]:
        hs = p.get("httpStatus")
        lines.append(f"| `{p['probe']}` | `{p['target']}` | `{hs if hs is not None else 'null'}` | `{p['status']}` | {p.get('detail', '')} |")
    if report.get("failures"):
        lines += ["", "## 6. Failed Checks"]
        lines += [f"- ✗ {f}" for f in report["failures"]]
    if report.get("warnings"):
        lines += ["", "## 7. Warnings"]
        lines += [f"- ⚠ {w}" for w in report["warnings"]]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument("--deterministic", action="store_true")
    ap.add_argument("--skip-smoke", action="store_true", help="Record the local smoke probe as SKIPPED (counts as a failed check unless --allow-skipped-smoke).")
    ap.add_argument("--allow-skipped-smoke", action="store_true", help="Do not count a SKIPPED smoke probe as a failed check.")
    ap.add_argument("--skip-alm-sync", action="store_true")
    ap.add_argument("--platform", default=None, choices=["jira", "ado", "both", "none"])
    ap.add_argument("--live", action="store_true", help="Actually `kubectl apply -k` every deploy/gdc/overlays/<env> (requires kubectl on PATH).")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = dlc.resolve_project_root(args.project_root)
    dlc.require_gate_approved(root, "gate_7_packaging", "Stage 8 (09-gdc-fleet-deployer-and-observability / run_gdc_fleet_deploy_and_verify.py)", deterministic=args.deterministic)
    stack = dlc.load_target_stack(root)
    dep_cfg = stack.get("deployment") or {}
    target_envs: list[str] = dep_cfg.get("targetEnvironments") or DEFAULT_ENVS
    conn_mode = dep_cfg.get("connectivityMode", "gdc-connected")

    fails: list[str] = []
    warns: list[str] = []
    total_checks = 0  # every unit that can contribute to failedChecks is counted here

    # 1. Stage 7 packaging index (inherit its checks/failures)
    pkg_script = Path(__file__).resolve().parents[2] / "08-container-and-gdc-packager" / "scripts" / "validate_gdc_packaging.py"
    pkg_cp = subprocess.run([sys.executable, str(pkg_script), "--project-root", str(root), "--json"], capture_output=True, text=True)
    try:
        pkg_idx = json.loads(pkg_cp.stdout)
    except Exception:
        pkg_idx = {"passed": False, "failures": [f"validate_gdc_packaging.py produced no JSON (rc={pkg_cp.returncode}): {(pkg_cp.stderr or pkg_cp.stdout).strip()[:300]}"]}
    pkg_fails = list(pkg_idx.get("failures") or [])
    fails += pkg_fails
    warns += list(pkg_idx.get("warnings") or [])
    container_count = len(pkg_idx.get("containers") or [])
    overlays = pkg_idx.get("kustomizeOverlays") or []
    # Gate 7 units: containers + overlays + policy controller + service mesh + cloud-neutral src scan.
    # If Gate 7 reported more failures than those units (e.g. missing files), count each failure as its own check.
    total_checks += max(container_count + len(overlays) + 3, len(pkg_fails))

    # 2. GDC Config Sync manifests (2 checks: rootsync + cluster-selectors)
    cs_dir = root / "deploy" / "gdc" / "config-sync"
    rootsync_p = cs_dir / "rootsync.yaml"
    selectors_p = cs_dir / "cluster-selectors.yaml"
    total_checks += 2
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
        missing_envs = [env for env in target_envs if env not in sel_txt]
        if missing_envs:
            fails.append(f"deploy/gdc/config-sync/cluster-selectors.yaml missing ClusterSelector for target environment(s): {missing_envs}.")

    # 3. Unified Observability (3 checks: otel, slo/alerts, dashboard)
    obs_dir = root / "deploy" / "observability"
    otel_p = obs_dir / "otel-collector.yaml"
    slo_p = obs_dir / "slo_and_alerts.yaml"
    dash_p = obs_dir / "fleet_dashboard.json"
    total_checks += 3

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
        if slo_count == 0 or alert_count == 0:
            fails.append("deploy/observability/slo_and_alerts.yaml must define ≥ 1 ServiceLevelObjective and ≥ 1 alert rule ('- alert: ...').")

    dash_panels = 0
    if not dash_p.exists():
        fails.append("Missing deploy/observability/fleet_dashboard.json.")
    else:
        try:
            dash_obj = dlc.read_json(dash_p)
            panels = dash_obj.get("panels") or dash_obj.get("widgets") or []
            dash_panels = len(panels)
            dash_str = json.dumps(dash_obj)
            missing_envs = [env for env in target_envs if env not in dash_str]
            problems = []
            if missing_envs:
                problems.append(f"missing fleet filter/panel coverage for {missing_envs}")
            if dash_panels == 0:
                problems.append("contains no panel/widget")
            if problems:
                fails.append("deploy/observability/fleet_dashboard.json " + "; ".join(problems) + ".")
        except SystemExit:
            fails.append("deploy/observability/fleet_dashboard.json is not valid JSON.")

    obs_info = {
        "otelCollectorValid": otel_ok,
        "sloCount": slo_count,
        "alertCount": alert_count,
        "fleetDashboardPanels": dash_panels,
        "status": "PASS" if (otel_ok and slo_count > 0 and alert_count > 0 and dash_panels > 0) else "FAIL",
    }

    # 4. Deployment & DR Runbook (1 check)
    runbook_p = root / "deploy" / "deployment_and_runbook.md"
    total_checks += 1
    if not runbook_p.exists():
        fails.append("Missing deploy/deployment_and_runbook.md.")
    else:
        rb_txt = dlc.read_text(runbook_p).lower()
        missing_kw = [kw for kw in ("topology", "wave", "observability", "failover", "rollback") if kw not in rb_txt]
        if missing_kw:
            fails.append(f"deploy/deployment_and_runbook.md missing required section(s) covering: {missing_kw}.")

    # 5. Capability-group rollout waves (+ optional live apply)
    waves = compute_rollout_waves(root, target_envs)
    execution_mode = EXEC_MODE_MANIFEST
    if args.live:
        total_checks += 1
        live_ok, live_fails = live_apply_overlays(root, target_envs, waves)
        fails += live_fails
        if live_ok:
            execution_mode = EXEC_MODE_LIVE

    # 6. Local smoke probe (1 check per probe)
    probes = run_smoke_probes(root, stack, args.skip_smoke)
    total_checks += len(probes)
    for pr in probes:
        if pr["status"] == "FAIL":
            fails.append(f"Local smoke probe '{pr['probe']}' against {pr['target']} FAILED (HTTP {pr.get('httpStatus')}): {pr.get('detail', '')}")
        elif pr["status"] == "SKIPPED":
            msg = f"Local smoke probe '{pr['probe']}' was SKIPPED ({pr.get('detail', '')})."
            if args.allow_skipped_smoke:
                warns.append(msg + " Accepted because --allow-skipped-smoke was passed.")
            else:
                fails.append(msg + " A skipped probe counts as a failed check; pass --allow-skipped-smoke to accept it explicitly.")

    container_images = [
        {
            "component": c.get("component", "app"),
            "dockerfile": str(Path(c["file"]).relative_to(root)) if str(c.get("file", "")).startswith(str(root)) else str(c.get("file", "")),
            "nonRootUser": c.get("user", ""),
            "sha256Digest": c.get("sha256", ""),
            "status": "PASS" if (c.get("nonRoot") and c.get("hasHealthcheck") and c.get("hasTraceabilityLabels") and not c.get("unpinnedImages")) else "FAIL",
        }
        for c in (pkg_idx.get("containers") or [])
    ]
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

    def _summary() -> dict[str, Any]:
        failed = len(fails)
        total = max(total_checks, failed, 1)
        return {
            "totalChecks": total,
            "passedChecks": max(0, total - failed),
            "failedChecks": failed,
            "verdict": "PASS" if not fails else "FAIL",
        }

    report: dict[str, Any] = {
        "schemaVersion": dlc.SCHEMA_VERSION,
        "evaluatedAtUtc": dlc.utc_now_iso(deterministic=args.deterministic),
        "abstractionPlane": "gdc-fleet",
        "connectivityMode": conn_mode,
        "executionMode": execution_mode,
        "targetEnvironments": target_envs,
        "rolloutWaves": waves,
        "containerImages": container_images,
        "kustomizeOverlays": overlays,
        "policyController": pc_info,
        "serviceMesh": sm_info,
        "observability": obs_info,
        "smokeProbes": probes,
        "failures": fails,
        "warnings": warns,
        "summary": _summary(),
    }

    schema_errs = dlc.validate_against_schema(report, dlc.load_schema("deployment_eval_results.schema.json"))
    if schema_errs:
        total_checks += 1
        for se in schema_errs:
            fails.append(f"deployment_eval_report.json schema violation: {se}")
        report["summary"] = _summary()

    # 7. ALM deployment traceability sync (only when every check passed). Exit 2 == bridge warning
    # (e.g. no credentials / platform 'none'); any other non-zero exit fails the gate.
    # The bridge reads deploy/deployment_eval_report.json, so the report is written BEFORE the call and
    # rewritten afterwards with the bridge outcome folded into failures/warnings/summary.
    report_json = root / "deploy" / "deployment_eval_report.json"
    report_md = root / "deploy" / "deployment_eval_report.md"

    # Preserve any prior deployment evaluation run in deploy/history/iter-N/ so failed runs are never overwritten.
    hist_root = root / "deploy" / "history"
    existing_iters = [
        int(m.group(1))
        for p in (hist_root.glob("iter-*") if hist_root.is_dir() else [])
        if (m := re.match(r"^iter-(\d+)$", p.name))
    ]
    if report_json.is_file() and not existing_iters:
        it1_dir = hist_root / "iter-1"
        it1_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(report_json, it1_dir / "deployment_eval_report.json")
        if report_md.is_file():
            shutil.copy2(report_md, it1_dir / "deployment_eval_report.md")
        existing_iters = [1]
    next_it = (max(existing_iters) + 1) if existing_iters else 1
    it_dir = hist_root / f"iter-{next_it}"
    it_dir.mkdir(parents=True, exist_ok=True)

    def _write_report() -> None:
        report["summary"] = _summary()
        md_report = render_markdown_report(report)
        dlc.write_json(it_dir / "deployment_eval_report.json", report)
        dlc.write_text(it_dir / "deployment_eval_report.md", md_report)
        dlc.write_json(root / "deploy" / f"deployment_eval_report.iter-{next_it:02d}.json", report)
        dlc.write_text(root / "deploy" / f"deployment_eval_report.iter-{next_it:02d}.md", md_report)
        dlc.write_json(report_json, report)
        dlc.write_text(report_md, md_report)

    _write_report()
    if not fails and not args.skip_alm_sync and (root / "backlog" / "user_stories.json").exists():
        bridge_script = Path(__file__).resolve().parents[2] / "03-story-and-sprint-planner" / "scripts" / "alm_jira_ado_bridge.py"
        if bridge_script.exists():
            total_checks += 1
            b_cmd = [sys.executable, str(bridge_script), "--project-root", str(root), "--action", "sync-deployment-status"]
            if args.platform:
                b_cmd += ["--platform", args.platform]
            if args.deterministic:
                b_cmd.append("--deterministic")
            b_cp = subprocess.run(b_cmd, cwd=str(root), capture_output=True, text=True)
            b_out = (b_cp.stderr or b_cp.stdout).strip()[-400:]
            if b_cp.returncode == 2:
                warns.append(f"ALM bridge sync-deployment-status returned 2 (warning): {b_out}")
            elif b_cp.returncode != 0:
                fails.append(f"ALM bridge sync-deployment-status failed (rc={b_cp.returncode}): {b_out}")
            _write_report()

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for w in warns:
            dlc.warn(w)
        for f in fails:
            print(f"  ✗ {f}")
        print(
            f"[dlc] Gate 8 GDC Fleet deployment & observability: {report['summary']['verdict']} "
            f"({report['summary']['passedChecks']}/{report['summary']['totalChecks']} checks) — mode={execution_mode}, "
            f"environments={','.join(target_envs)}, waves={len(waves)}, SLOs={slo_count}, alerts={alert_count}, "
            f"dashboardPanels={dash_panels} -> deploy/deployment_eval_report.{{json,md}}"
        )
        if not fails:
            dlc.mark_gate_awaiting_human(
                root,
                "gate_8_deployment",
                summary="Stage 8 GDC Fleet GitOps Deployment, Observability & SLO Verification passed. Present deploy/deployment_eval_report.md and deploy/deployment_and_runbook.md to user for final Gate 8 sign-off.",
                deterministic=args.deterministic,
            )
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
