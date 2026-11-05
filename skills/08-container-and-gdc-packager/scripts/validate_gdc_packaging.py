#!/usr/bin/env python3
"""Gate 7 — validate cloud-agnostic OCI containerization and GDC multi-cloud/on-prem KRM packaging (08-container-and-gdc-packager).

Verifies:
  0. Stage 5 did not run in degraded mode (`test/.build_logs/degraded_mode.json` absent) — or, if it did, the real
     target-stack container build was verified (`deploy/.container_build_verified.json` / `--container-build-verified`).
  1. Zero cloud-vendor SDK lock-in in `src/` — per-language import table for Python, JS/TS, Go, Java/Kotlin and .NET
     covering AWS, Azure and GCP control-plane SDKs (GCP allowed only when `deployment.targetEnvironments == ["gcp"]`);
     `node_modules/ dist/ build/ target/ bin/ obj/` are excluded.
  2. Hardened, rootless `deploy/containers/Dockerfile.backend`, `Dockerfile.ui`, and `docker-compose.yaml`
     with non-root `USER` (root / 0 / 0:<gid> rejected), `HEALTHCHECK`, pinned base image tag or digest (no `:latest`;
     `FROM <stage-alias>` and `FROM --platform=… image@sha256:…` are accepted), OCI traceability labels, base images
     matching `specs/target_stack.json` (whole-word tokens), multi-stage builds for compiled/bundled stacks, and
     `backend.kind`/`frontend.kind` not `tbd`.
  3. Canonical KRM base in `deploy/gdc/base/{kustomization.yaml,workloads.yaml}` (Deployment, Service, HPA, PDB,
     NetworkPolicy, schema migration Job; plus legacy ETL cutover Job when `inputScenario == SCENARIO_LEGACY_APP`).
  4. All target GDC provider overlays (`on-prem-gdc`, `gcp`, `aws`, `azure` per `specs/target_stack.json#deployment`)
     exist under `deploy/gdc/overlays/<env>/kustomization.yaml` with GDC Fleet provider & ClusterSelector metadata.
  5. GDC Policy Controller constraints (`deploy/gdc/policy-controller/constraints.yaml`) enforce non-root,
     read-only rootfs, and egress/label guardrails aligned with Spec Pillar 2.
  6. GDC Cloud Service Mesh (`deploy/gdc/service-mesh/`) enforces `STRICT` mTLS (`PeerAuthentication`),
     Spec §3.5 / OpenAPI RBAC (`AuthorizationPolicy`), and cross-cloud/on-prem `MultiClusterService` / `ServiceExport`.
  7. Writes `deploy/.gdc_packaging_index.json` for Stage 8.

This gate is a static manifest-level validation: it does not build images or apply manifests to a cluster.

Usage:
    python3 validate_gdc_packaging.py --project-root <PROJECT_ROOT> [--json] [--container-build-verified]
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

# --------------------------------------------------------------------------------------
# Cloud-vendor SDK lock-in table (per language). Each entry: (vendor, compiled regex).
# The claim behind Gate 7 is "cloud-agnostic behind GDC", so GCP control-plane SDKs are
# flagged too — unless `deployment.targetEnvironments` is exactly ["gcp"], in which case a
# GCP-only dependency is not lock-in relative to the declared targets.
# --------------------------------------------------------------------------------------
_PY_IMPORT = r"^\s*(?:import|from)\s+(?:{mods})(?:[\s.]|$)"
_JS_IMPORT = r"(?:\bfrom\s+|\brequire\s*\(\s*|^\s*import\s+)['\"](?:{mods})(?:/[^'\"]*)?['\"]"
_GO_IMPORT = r"['\"](?:{mods})(?:/[^'\"]*)?['\"]"
_JAVA_IMPORT = r"^\s*import\s+(?:static\s+)?(?:{mods})\."
_CS_USING = r"^\s*using\s+(?:static\s+)?(?:{mods})[\.;]"

CLOUD_SDK_LOCKIN_TABLE: dict[str, list[tuple[str, re.Pattern[str]]]] = {
    # Python
    ".py": [
        ("aws", re.compile(_PY_IMPORT.format(mods=r"boto3|botocore|aws_cdk"), re.MULTILINE)),
        ("azure", re.compile(_PY_IMPORT.format(mods=r"azure"), re.MULTILINE)),
        ("gcp", re.compile(_PY_IMPORT.format(mods=r"google\.cloud"), re.MULTILINE)),
    ],
    # JavaScript / TypeScript
    ".js": [
        ("aws", re.compile(_JS_IMPORT.format(mods=r"@aws-sdk|aws-sdk"), re.MULTILINE)),
        ("azure", re.compile(_JS_IMPORT.format(mods=r"@azure"), re.MULTILINE)),
        ("gcp", re.compile(_JS_IMPORT.format(mods=r"@google-cloud"), re.MULTILINE)),
    ],
    # Go
    ".go": [
        ("aws", re.compile(_GO_IMPORT.format(mods=r"github\.com/aws/aws-sdk-go(?:-v2)?"))),
        ("azure", re.compile(_GO_IMPORT.format(mods=r"github\.com/Azure/azure-sdk-for-go"))),
        ("gcp", re.compile(_GO_IMPORT.format(mods=r"cloud\.google\.com/go"))),
    ],
    # Java / Kotlin
    ".java": [
        ("aws", re.compile(_JAVA_IMPORT.format(mods=r"software\.amazon\.awssdk|com\.amazonaws"), re.MULTILINE)),
        ("azure", re.compile(_JAVA_IMPORT.format(mods=r"com\.azure"), re.MULTILINE)),
        ("gcp", re.compile(_JAVA_IMPORT.format(mods=r"com\.google\.cloud"), re.MULTILINE)),
    ],
    # .NET
    ".cs": [
        ("aws", re.compile(_CS_USING.format(mods=r"AWSSDK|Amazon"), re.MULTILINE)),
        ("azure", re.compile(_CS_USING.format(mods=r"Azure"), re.MULTILINE)),
        ("gcp", re.compile(_CS_USING.format(mods=r"Google\.Cloud"), re.MULTILINE)),
    ],
}
CLOUD_SDK_LOCKIN_TABLE[".ts"] = CLOUD_SDK_LOCKIN_TABLE[".js"]
CLOUD_SDK_LOCKIN_TABLE[".tsx"] = CLOUD_SDK_LOCKIN_TABLE[".js"]
CLOUD_SDK_LOCKIN_TABLE[".jsx"] = CLOUD_SDK_LOCKIN_TABLE[".js"]
CLOUD_SDK_LOCKIN_TABLE[".kt"] = CLOUD_SDK_LOCKIN_TABLE[".java"]
SCAN_SUFFIXES = tuple(CLOUD_SDK_LOCKIN_TABLE.keys())
EXCLUDED_DIR_NAMES = {"node_modules", "dist", "build", "target", "bin", "obj", ".git", "__pycache__", ".venv", "venv"}

# Backend kinds whose images are compiled or bundled and therefore MUST be multi-stage builds.
COMPILED_OR_BUNDLED_BACKENDS = {"java-spring-boot", "node-express", "go", "dotnet"}
COMPILED_OR_BUNDLED_FRONTENDS = {"react", "angular", "vue", "nextjs"}


def scan_cloud_lockin(src_dir: Path, root: Path, allowed_vendors: set[str]) -> list[str]:
    """Return failure strings for every cloud-vendor SDK import found under src/."""
    out: list[str] = []
    for p in sorted(src_dir.rglob("*")):
        if not p.is_file() or p.suffix not in SCAN_SUFFIXES:
            continue
        rel_parts = p.relative_to(src_dir).parts[:-1]
        if any(part in EXCLUDED_DIR_NAMES for part in rel_parts):
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for vendor, rx in CLOUD_SDK_LOCKIN_TABLE[p.suffix]:
            if vendor in allowed_vendors:
                continue
            m = rx.search(content)
            if m:
                out.append(
                    f"Cloud-vendor SDK lock-in ({vendor}) detected in {p.relative_to(root)} "
                    f"({m.group(0).strip()!r}) — application code must remain cloud-agnostic behind GDC."
                )
                break
    return out


def parse_dockerfile(path: Path) -> dict[str, Any]:
    txt = dlc.read_text(path)
    # FROM [--platform=...] <image> [AS <alias>]
    from_matches = re.findall(
        r"^\s*FROM\s+(?:--platform=\S+\s+)?([^\s#]+)(?:\s+AS\s+([A-Za-z0-9_.-]+))?",
        txt, re.IGNORECASE | re.MULTILINE,
    )
    from_lines = [img for img, _alias in from_matches]
    stage_aliases = {alias.lower() for _img, alias in from_matches if alias}
    user_lines = re.findall(r"^\s*USER\s+([^\s#]+)", txt, re.IGNORECASE | re.MULTILINE)
    has_healthcheck = bool(re.search(r"^\s*HEALTHCHECK\b", txt, re.IGNORECASE | re.MULTILINE))
    has_spec_label = "io.agentic.dlc.spec-sha256" in txt
    has_group_label = "io.agentic.dlc.capability-groups" in txt
    has_gdc_label = "io.agentic.dlc.abstraction-plane" in txt

    def _is_unpinned(img: str) -> bool:
        low = img.lower()
        if low == "scratch" or low in stage_aliases:
            return False          # `FROM builder` / `FROM <stage-alias>` are internal stage references
        if "@sha256:" in low:
            return False          # digest-pinned (with or without --platform / tag)
        if low.endswith(":latest"):
            return True
        return ":" not in low     # bare image name == implicit :latest

    unpinned = [img for img in from_lines if _is_unpinned(img)]
    user_val = user_lines[-1] if user_lines else ""
    # `USER root`, `USER 0`, `USER 0:0`, `USER 0:<anything>` and `USER root:<anything>` are all root.
    user_name = user_val.split(":", 1)[0].strip().lower()
    non_root = bool(user_val) and user_name not in ("root", "0")
    return {
        "file": str(path),
        "sha256": dlc.sha256_file(path),
        "baseImages": from_lines,
        "stageCount": len(from_lines),
        "unpinnedImages": unpinned,
        "user": user_val,
        "nonRoot": non_root,
        "hasHealthcheck": has_healthcheck,
        "hasTraceabilityLabels": has_spec_label and has_group_label and has_gdc_label,
    }


def _image_matches(imgs: list[str], tokens: tuple[str, ...]) -> bool:
    """Whole-word token match against base image names (so 'go' never matches 'django' or 'mongo')."""
    blob = " ".join(imgs).lower()
    return any(re.search(rf"(?<![a-z0-9]){re.escape(tok)}(?![a-z0-9])", blob) for tok in tokens)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--container-build-verified", action="store_true",
        help="Assert that every deploy/containers/Dockerfile.* was built successfully with the real toolchain "
             "(lifts the Stage 5 degraded-mode refusal; equivalent to deploy/.container_build_verified.json).",
    )
    args = ap.parse_args()

    root = dlc.resolve_project_root(args.project_root)
    dlc.require_gate_approved(root, "gate_6_eval", "Stage 7 (08-container-and-gdc-packager / validate_gdc_packaging.py)")
    inv = dlc.load_inventory(root)
    legacy = inv.get("inputScenario") == "SCENARIO_LEGACY_APP"
    stack = dlc.load_target_stack(root)
    dep_cfg = stack.get("deployment") or {}
    target_envs: list[str] = dep_cfg.get("targetEnvironments") or DEFAULT_ENVS
    spec_md = dlc.load_spec(root)
    roles = [r["role"] for r in dlc.parse_roles(spec_md)]

    fails: list[str] = []
    warns: list[str] = []

    be_kind = ((stack.get("backend") or {}).get("kind") or "tbd").strip()
    fe_kind = ((stack.get("frontend") or {}).get("kind") or "tbd").strip()

    # 0. Stage 5 degraded-mode refusal (see docs/ARCHITECTURE.md §4.6 "Degraded mode"):
    #    when src/run.sh fell back to the generic local runner because the native toolchain was absent,
    #    Stage 5 records test/.build_logs/degraded_mode.json. Gate 7 refuses to pass while that file exists
    #    unless the real target-stack container build has been verified (deploy/.container_build_verified.json
    #    written by a successful `docker build` of every Dockerfile, or --container-build-verified).
    degraded_p = root / "test" / ".build_logs" / "degraded_mode.json"
    build_verified_p = root / "deploy" / ".container_build_verified.json"
    degraded_mode = False
    if degraded_p.exists():
        degraded_mode = True
        try:
            dm = dlc.read_json(degraded_p)
        except SystemExit:
            dm = {}
        if not (args.container_build_verified or build_verified_p.exists()):
            fails.append(
                "Stage 5 ran in DEGRADED MODE (test/.build_logs/degraded_mode.json present: "
                f"reason={dm.get('reason', '?')!r}, missingTools={dm.get('missingTools', [])}). Gate 7 refuses to pass "
                "until the real target-stack container build is verified (run `docker build` for every "
                "deploy/containers/Dockerfile.* and record deploy/.container_build_verified.json, or pass "
                "--container-build-verified after doing so) — or delete the degraded-mode marker after installing the toolchain."
            )
        else:
            warns.append("Stage 5 degraded-mode marker present but the container build was verified — proceeding.")

    # 1. Cloud-neutral application code check on src/
    src_dir = root / "src"
    if not src_dir.exists():
        fails.append("src/ directory missing — run Stage 5 (06-coding-agent) first.")
    else:
        # GCP SDKs are only acceptable when GCP is the sole declared target environment.
        allowed_vendors: set[str] = {"gcp"} if list(target_envs) == ["gcp"] else set()
        fails += scan_cloud_lockin(src_dir, root, allowed_vendors)

    # 2. OCI Container files
    containers_dir = root / "deploy" / "containers"
    df_backend = containers_dir / "Dockerfile.backend"
    df_ui = containers_dir / "Dockerfile.ui"
    compose_p = containers_dir / "docker-compose.yaml"
    container_infos: list[dict[str, Any]] = []

    # backend.kind must be an explicit, human-confirmed stack (invariant 7) — "tbd"/missing FAILS the gate.
    if be_kind in ("", "tbd"):
        fails.append(
            "specs/target_stack.json#backend.kind is missing or 'tbd' — the Future-State stack must be confirmed "
            "at Gate 4A before packaging; Gate 7 cannot verify the backend image against an undecided stack."
        )
    if fe_kind in ("", "tbd"):
        fails.append("specs/target_stack.json#frontend.kind is missing or 'tbd' — confirm the Future-State stack at Gate 4A first.")

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
            fails.append(f"{df_p.relative_to(root)} must declare a non-root USER (found {info['user'] or 'none'}; 'root', '0' and '0:<gid>' are rejected).")
        if not info["hasHealthcheck"]:
            fails.append(f"{df_p.relative_to(root)} must declare a HEALTHCHECK instruction.")
        if not info["hasTraceabilityLabels"]:
            fails.append(
                f"{df_p.relative_to(root)} missing required OCI traceability labels "
                "('io.agentic.dlc.abstraction-plane', 'io.agentic.dlc.spec-sha256', 'io.agentic.dlc.capability-groups')."
            )
        # Verify Dockerfile base images match specs/target_stack.json
        if comp == "backend":
            expected_be_imgs = {
                "java-spring-boot": ("temurin", "openjdk", "maven", "gradle", "java", "eclipse-temurin", "amazoncorretto"),
                "node-express": ("node",),
                "go": ("golang", "go"),
                "dotnet": ("dotnet", "aspnet", "sdk"),
                "python-fastapi": ("python",),
                "python-flask": ("python",),
                "python-stdlib-http": ("python",),
            }.get(be_kind)
            if expected_be_imgs and not _image_matches(info["baseImages"], expected_be_imgs):
                fails.append(
                    f"{df_p.relative_to(root)} base image(s) {info['baseImages']} do not match "
                    f"specs/target_stack.json#backend.kind={be_kind!r} (expected one of {expected_be_imgs}). "
                    "Never package a Python fallback image when another target backend stack was selected."
                )
            if be_kind in COMPILED_OR_BUNDLED_BACKENDS and info["stageCount"] < 2:
                fails.append(
                    f"{df_p.relative_to(root)} must be a multi-stage build (≥ 2 FROM instructions: build stage + "
                    f"minimal runtime stage) for compiled/bundled backend.kind={be_kind!r}."
                )
        elif comp == "ui":
            if fe_kind in COMPILED_OR_BUNDLED_FRONTENDS:
                if not _image_matches(info["baseImages"], ("node", "nginx", "nginxinc", "caddy", "httpd")):
                    fails.append(
                        f"{df_p.relative_to(root)} base image(s) {info['baseImages']} do not match "
                        f"specs/target_stack.json#frontend.kind={fe_kind!r} (expected multi-stage node build + nginx/static runtime)."
                    )
                if info["stageCount"] < 2:
                    fails.append(
                        f"{df_p.relative_to(root)} must be a multi-stage build (node build stage + static runtime stage) "
                        f"for bundled frontend.kind={fe_kind!r}."
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
        "degradedModeMarkerPresent": degraded_mode,
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
        if not fails:
            dlc.mark_gate_awaiting_human(
                root,
                "gate_7_packaging",
                summary="Stage 7 Cloud-Agnostic OCI Containers & GDC Multi-Cloud KRM Packaging validated. Present deploy/ manifests to user and STOP for Gate 7 approval before Stage 8 Fleet Deployment.",
            )
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
