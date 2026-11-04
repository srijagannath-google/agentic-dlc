#!/usr/bin/env python3
"""Gate 7 — validate cloud-agnostic OCI containerization and GDC multi-cloud/on-prem KRM packaging (08-container-and-gdc-packager).

Verifies:
  1. Zero cloud-vendor SDK lock-in in `src/` (no direct AWS/Azure/GCP control-plane SDK lock-in in app code).
  2. Hardened, rootless `deploy/containers/Dockerfile.backend`, `Dockerfile.ui`, and `docker-compose.yaml`
     with non-root `USER`, `HEALTHCHECK`, pinned base image tag (no `:latest`), and OCI traceability labels.
  3. Canonical KRM base in `deploy/gdc/base/{kustomization.yaml,workloads.yaml}` (Deployment, Service, HPA, PDB,
     NetworkPolicy, schema migration Job; plus legacy ETL cutover Job when `inputScenario == SCENARIO_LEGACY_APP`).
  4. All target GDC provider overlays (`on-prem-gdc`, `gcp`, `aws`, `azure` per `specs/target_stack.json#deployment`)
     exist under `deploy/gdc/overlays/<env>/kustomization.yaml` with GDC Fleet provider & ClusterSelector metadata.
  5. GDC Policy Controller constraints (`deploy/gdc/policy-controller/constraints.yaml`) enforce non-root,
     read-only rootfs, and egress/label guardrails aligned with Spec Pillar 2.
  6. GDC Cloud Service Mesh (`deploy/gdc/service-mesh/`) enforces `STRICT` mTLS (`PeerAuthentication`),
     Spec §3.5 / OpenAPI RBAC (`AuthorizationPolicy`), and cross-cloud/on-prem `MultiClusterService` / `ServiceExport`.
  7. Writes `deploy/.gdc_packaging_index.json` for Stage 8.

Usage:
    python3 validate_gdc_packaging.py --project-root <PROJECT_ROOT> [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import dlc_common as dlc  # noqa: E402

DEFAULT_ENVS = ["on-prem-gdc", "gcp", "aws", "azure"]
CLOUD_SDK_LOCKIN_RE = re.compile(
    r"^\s*(?:import|from)\s+(?:boto3|botocore|azure\.identity|azure\.storage|azure\.mgmt|aws_cdk)\b",
    re.MULTILINE,
)


def parse_dockerfile(path: Path) -> dict[str, Any]:
    txt = dlc.read_text(path)
    from_lines = re.findall(r"^\s*FROM\s+([^\s#]+)", txt, re.IGNORECASE | re.MULTILINE)
    user_lines = re.findall(r"^\s*USER\s+([^\s#]+)", txt, re.IGNORECASE | re.MULTILINE)
    has_healthcheck = bool(re.search(r"^\s*HEALTHCHECK\b", txt, re.IGNORECASE | re.MULTILINE))
    has_spec_label = "io.agentic.dlc.spec-sha256" in txt
    has_group_label = "io.agentic.dlc.capability-groups" in txt
    has_gdc_label = "io.agentic.dlc.abstraction-plane" in txt
    unpinned = [img for img in from_lines if img.endswith(":latest") or (":" not in img and "@" not in img and img.lower() != "scratch")]
    user_val = user_lines[-1] if user_lines else ""
    non_root = bool(user_val) and user_val.lower() not in ("root", "0", "0:0")
    return {
        "file": str(path),
        "sha256": dlc.sha256_file(path),
        "baseImages": from_lines,
        "unpinnedImages": unpinned,
        "user": user_val,
        "nonRoot": non_root,
        "hasHealthcheck": has_healthcheck,
        "hasTraceabilityLabels": has_spec_label and has_group_label and has_gdc_label,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = dlc.resolve_project_root(args.project_root)
    inv = dlc.load_inventory(root)
    legacy = inv.get("inputScenario") == "SCENARIO_LEGACY_APP"
    stack = dlc.load_target_stack(root)
    dep_cfg = stack.get("deployment") or {}
    target_envs: list[str] = dep_cfg.get("targetEnvironments") or DEFAULT_ENVS
    spec_md = dlc.load_spec(root)
    roles = [r["role"] for r in dlc.parse_roles(spec_md)]

    fails: list[str] = []
    warns: list[str] = []

    # 1. Cloud-neutral application code check on src/
    src_dir = root / "src"
    if not src_dir.exists():
        fails.append("src/ directory missing — run Stage 5 (06-coding-agent) first.")
    else:
        for p in sorted(src_dir.rglob("*")):
            if p.is_file() and p.suffix in (".py", ".js", ".ts", ".go", ".java"):
                content = p.read_text(encoding="utf-8", errors="replace")
                m = CLOUD_SDK_LOCKIN_RE.search(content)
                if m:
                    fails.append(
                        f"Cloud-vendor SDK lock-in detected in {p.relative_to(root)} ({m.group(0).strip()!r}) — "
                        "application code must remain cloud-agnostic behind GDC."
                    )

    # 2. OCI Container files
    containers_dir = root / "deploy" / "containers"
    df_backend = containers_dir / "Dockerfile.backend"
    df_ui = containers_dir / "Dockerfile.ui"
    compose_p = containers_dir / "docker-compose.yaml"
    container_infos: list[dict[str, Any]] = []

    for comp, df_p in (("backend", df_backend), ("ui", df_ui)):
        if not df_p.exists():
            fails.append(f"Missing {df_p.relative_to(root)} (Stage 7 08-container-and-gdc-packager).")
            continue
        info = parse_dockerfile(df_p)
        info["file"] = str(df_p.relative_to(root))
        info["component"] = comp
        container_infos.append(info)
        if info["unpinnedImages"]:
            fails.append(f"{df_p.relative_to(root)} uses unpinned or ':latest' base image(s): {info['unpinnedImages']}")
        if not info["nonRoot"]:
            fails.append(f"{df_p.relative_to(root)} must declare a non-root USER (found {info['user'] or 'none'}).")
        if not info["hasHealthcheck"]:
            fails.append(f"{df_p.relative_to(root)} must declare a HEALTHCHECK instruction.")
        if not info["hasTraceabilityLabels"]:
            fails.append(
                f"{df_p.relative_to(root)} missing required OCI traceability labels "
                "('io.agentic.dlc.abstraction-plane', 'io.agentic.dlc.spec-sha256', 'io.agentic.dlc.capability-groups')."
            )
        # Verify Dockerfile base images match specs/target_stack.json
        imgs_blob = " ".join(info["baseImages"]).lower()
        if comp == "backend":
            be_kind = ((stack.get("backend") or {}).get("kind") or "tbd").strip()
            expected_be_imgs = {
                "java-spring-boot": ("temurin", "openjdk", "maven", "gradle", "java"),
                "node-express": ("node",),
                "go": ("golang", "go"),
                "dotnet": ("dotnet",),
                "python-fastapi": ("python",),
                "python-flask": ("python",),
            }.get(be_kind)
            if expected_be_imgs and not any(tok in imgs_blob for tok in expected_be_imgs):
                fails.append(
                    f"{df_p.relative_to(root)} base image(s) {info['baseImages']} do not match "
                    f"specs/target_stack.json#backend.kind={be_kind!r} (expected one of {expected_be_imgs}). "
                    "Never package a Python fallback image when another target backend stack was selected."
                )
        elif comp == "ui":
            fe_kind = ((stack.get("frontend") or {}).get("kind") or "tbd").strip()
            if fe_kind in ("react", "angular", "vue", "nextjs") and "node" not in imgs_blob and "nginx" not in imgs_blob:
                fails.append(
                    f"{df_p.relative_to(root)} base image(s) {info['baseImages']} do not match "
                    f"specs/target_stack.json#frontend.kind={fe_kind!r} (expected multi-stage node/nginx build)."
                )

    if not compose_p.exists():
        fails.append("Missing deploy/containers/docker-compose.yaml (local zero-cloud verification stack).")
    else:
        compose_txt = dlc.read_text(compose_p)
        for req_tok in ("backend", "otel-collector"):
            if req_tok not in compose_txt:
                fails.append(f"deploy/containers/docker-compose.yaml must include service '{req_tok}'.")

    # 3. GDC KRM Base manifests
    base_dir = root / "deploy" / "gdc" / "base"
    base_kust = base_dir / "kustomization.yaml"
    base_workloads = base_dir / "workloads.yaml"
    if not base_kust.exists() or not base_workloads.exists():
        fails.append("Missing deploy/gdc/base/kustomization.yaml or deploy/gdc/base/workloads.yaml.")
    else:
        wk_txt = dlc.read_text(base_workloads)
        for kind in ("Deployment", "Service", "HorizontalPodAutoscaler", "PodDisruptionBudget", "NetworkPolicy", "Job"):
            if not re.search(rf"^\s*kind:\s*{kind}\b", wk_txt, re.MULTILINE):
                fails.append(f"deploy/gdc/base/workloads.yaml missing required KRM resource kind: {kind}.")
        if "runAsNonRoot: true" not in wk_txt or "readOnlyRootFilesystem: true" not in wk_txt:
            fails.append("deploy/gdc/base/workloads.yaml must enforce 'runAsNonRoot: true' and 'readOnlyRootFilesystem: true'.")
        if "schema.sql" not in wk_txt and "db-schema-migration" not in wk_txt:
            fails.append("deploy/gdc/base/workloads.yaml must include a schema migration Job referencing src/db/schema.sql.")
        if legacy and "data_migration_and_cutover" not in wk_txt and "legacy-data-cutover" not in wk_txt:
            fails.append(
                "SCENARIO_LEGACY_APP requires a one-time legacy data migration/cutover Job in "
                "deploy/gdc/base/workloads.yaml referencing design/data_migration_and_cutover.md."
            )

    # 4. Multi-Cloud & On-Prem Kustomize Overlays
    overlay_infos: list[dict[str, Any]] = []
    for env in target_envs:
        ov_p = root / "deploy" / "gdc" / "overlays" / env / "kustomization.yaml"
        if not ov_p.exists():
            fails.append(f"Missing GDC provider Kustomize overlay for '{env}': deploy/gdc/overlays/{env}/kustomization.yaml")
            continue
        ov_txt = dlc.read_text(ov_p)
        has_base_ref = "../../base" in ov_txt
        has_provider = re.search(rf"gdc\.cloud\.google\.com/provider:\s*[\"']?{re.escape(env)}[\"']?", ov_txt) is not None
        cs_match = re.search(r"cluster-selector:\s*[\"']?([\w.-]+)[\"']?", ov_txt)
        if not has_base_ref:
            fails.append(f"deploy/gdc/overlays/{env}/kustomization.yaml must reference '../../base'.")
        if not has_provider:
            fails.append(f"deploy/gdc/overlays/{env}/kustomization.yaml must set label 'gdc.cloud.google.com/provider: {env}'.")
        if not cs_match:
            fails.append(f"deploy/gdc/overlays/{env}/kustomization.yaml must declare 'configmanagement.gke.io/cluster-selector'.")
        overlay_infos.append({
            "environment": env,
            "overlayPath": str(ov_p.relative_to(root)),
            "clusterSelector": cs_match.group(1) if cs_match else "",
            "status": "PASS" if (has_base_ref and has_provider and cs_match) else "FAIL",
        })

    # 5. GDC Policy Controller constraints
    pc_p = root / "deploy" / "gdc" / "policy-controller" / "constraints.yaml"
    pc_info = {
        "constraintsFile": "deploy/gdc/policy-controller/constraints.yaml",
        "constraintCount": 0,
        "nonRootEnforced": False,
        "readOnlyRootFsEnforced": False,
        "status": "FAIL",
    }
    if not pc_p.exists():
        fails.append("Missing deploy/gdc/policy-controller/constraints.yaml (GDC Policy Controller / OPA Gatekeeper constraints).")
    else:
        pc_txt = dlc.read_text(pc_p)
        kinds = re.findall(r"^\s*kind:\s*([A-Za-z0-9_]+)", pc_txt, re.MULTILINE)
        non_root_ok = "MustRunAsNonRoot" in pc_txt or "K8sPSPAllowedUsers" in pc_txt
        ro_fs_ok = "K8sPSPReadOnlyRootFS" in pc_txt or "readOnlyRootFilesystem" in pc_txt
        if not non_root_ok:
            fails.append("deploy/gdc/policy-controller/constraints.yaml must include a non-root execution constraint (K8sPSPAllowedUsers / MustRunAsNonRoot).")
        if not ro_fs_ok:
            fails.append("deploy/gdc/policy-controller/constraints.yaml must include a read-only root filesystem constraint (K8sPSPReadOnlyRootFS).")
        pc_info = {
            "constraintsFile": str(pc_p.relative_to(root)),
            "constraintCount": len(kinds),
            "nonRootEnforced": non_root_ok,
            "readOnlyRootFsEnforced": ro_fs_ok,
            "status": "PASS" if (kinds and non_root_ok and ro_fs_ok) else "FAIL",
        }

    # 6. GDC Cloud Service Mesh manifests
    mesh_dir = root / "deploy" / "gdc" / "service-mesh"
    pa_p = mesh_dir / "peer-authentication.yaml"
    ap_p = mesh_dir / "authorization-policy.yaml"
    mcs_p = mesh_dir / "multicluster-service.yaml"
    strict_mtls = False
    authz_count = 0
    mcs_ok = False
    if not pa_p.exists():
        fails.append("Missing deploy/gdc/service-mesh/peer-authentication.yaml.")
    else:
        pa_txt = dlc.read_text(pa_p)
        strict_mtls = "PeerAuthentication" in pa_txt and bool(re.search(r"mode:\s*STRICT\b", pa_txt))
        if not strict_mtls:
            fails.append("deploy/gdc/service-mesh/peer-authentication.yaml must set PeerAuthentication mtls.mode: STRICT.")
    if not ap_p.exists():
        fails.append("Missing deploy/gdc/service-mesh/authorization-policy.yaml.")
    else:
        ap_txt = dlc.read_text(ap_p)
        authz_count = len(re.findall(r"^\s*kind:\s*AuthorizationPolicy\b", ap_txt, re.MULTILINE))
        if authz_count == 0:
            fails.append("deploy/gdc/service-mesh/authorization-policy.yaml contains no AuthorizationPolicy resource.")
        for r in roles:
            if r not in ap_txt:
                warns.append(f"Spec §3.5 role '{r}' not explicitly referenced in deploy/gdc/service-mesh/authorization-policy.yaml.")
    if not mcs_p.exists():
        fails.append("Missing deploy/gdc/service-mesh/multicluster-service.yaml.")
    else:
        mcs_txt = dlc.read_text(mcs_p)
        mcs_ok = bool(re.search(r"^\s*kind:\s*(?:MultiClusterService|ServiceExport)\b", mcs_txt, re.MULTILINE))
        if not mcs_ok:
            fails.append("deploy/gdc/service-mesh/multicluster-service.yaml must define a GDC MultiClusterService or ServiceExport resource.")

    mesh_info = {
        "strictMtls": strict_mtls,
        "authorizationPolicies": authz_count,
        "multiClusterService": mcs_ok,
        "status": "PASS" if (strict_mtls and authz_count > 0 and mcs_ok) else "FAIL",
    }

    index = {
        "schemaVersion": dlc.SCHEMA_VERSION,
        "abstractionPlane": "gdc-fleet",
        "targetEnvironments": target_envs,
        "containers": container_infos,
        "kustomizeOverlays": overlay_infos,
        "policyController": pc_info,
        "serviceMesh": mesh_info,
        "passed": not fails,
        "failures": fails,
        "warnings": warns,
    }
    if (root / "deploy").exists():
        dlc.write_json(root / "deploy" / ".gdc_packaging_index.json", index)

    if args.json:
        print(json.dumps(index, indent=2))
    else:
        for w in warns:
            dlc.warn(w)
        for f in fails:
            print(f"  ✗ {f}")
        print(
            f"[dlc] Gate 7 GDC packaging: {'PASS' if not fails else 'FAIL'} — "
            f"{len(container_infos)} container(s), {len(overlay_infos)} GDC provider overlay(s) ({', '.join(target_envs)}), "
            f"{pc_info['constraintCount']} Policy Controller constraint(s), {authz_count} Service Mesh policy(ies)"
        )
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
