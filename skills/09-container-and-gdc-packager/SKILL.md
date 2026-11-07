---
name: 09-container-and-gdc-packager
description: "Stage 8 of the Agentic DLC v4 (runs AFTER Stage 7 pre-deployment drift verification). platform-ops-agent packages the verified, zero-drift src/ application into cloud-agnostic, rootless OCI containers (deploy/containers/), authors a single Kubernetes Resource Model (KRM) base (deploy/gdc/base/) with GDC Kustomize overlays for On-Premises (on-prem-gdc), GCP, AWS and Azure (deploy/gdc/overlays/), and derives GDC Policy Controller (OPA) and Cloud Service Mesh (mTLS + RBAC AuthorizationPolicy + MultiClusterService) manifests from Spec Pillar 2 and src/contracts/openapi.yaml; verified by 09/scripts/validate_gdc_packaging.py (Gate 8). Use when asked to containerize the app or package it for GDC multi-cloud / on-prem deployment."
---

# Stage 8 — Cloud-Agnostic Containerization & GDC Multi-Cloud Packaging (Gate 8)

**Read before acting:** `_shared/project_root.md`, `_shared/gdc_multicloud_guardrails.md`,
`docs/ARCHITECTURE.md` §3–§5. Subagent: `platform-ops-agent` ("The Navigator").

> **Core Principle:** Application code (`src/`) stays 100% cloud-provider-agnostic. **Google Distributed Cloud (GDC) / GKE Enterprise** acts as the go-between abstraction plane so the exact same container images and KRM base manifests deploy across **On-Premises (`on-prem-gdc`)**, **Google Cloud (`gcp`)**, **AWS (`aws`)**, and **Azure (`azure`)**.

## Inputs
`src/` (verified at Stage 6 and confirmed `ALIGNED` at Stage 7 in `test/drift_report.json`), `src/contracts/openapi.yaml`, `src/db/schema.sql`,
`specs/application_spec.md` (Pillar 2 Security/RBAC/PII, `§3.5` Roles, Pillar 5 Architecture),
`specs/target_stack.json` (`$.deployment`), `specs/input_inventory.json`,
`design/architecture_design.md`, `design/solution_design.md`, and `design/data_migration_and_cutover.md` (`SCENARIO_LEGACY_APP` only).

## Outputs
| File / Directory | Author | Checked by |
| :-- | :-- | :-- |
| `deploy/containers/Dockerfile.backend`, `Dockerfile.ui`, `docker-compose.yaml` | `platform-ops-agent` | `09/scripts/validate_gdc_packaging.py` |
| `deploy/gdc/base/{kustomization.yaml,workloads.yaml}` | `platform-ops-agent` | `09/scripts/validate_gdc_packaging.py` |
| `deploy/gdc/overlays/{on-prem-gdc,gcp,aws,azure}/kustomization.yaml` | `platform-ops-agent` | `09/scripts/validate_gdc_packaging.py` |
| `deploy/gdc/policy-controller/constraints.yaml` | `platform-ops-agent` | `09/scripts/validate_gdc_packaging.py` |
| `deploy/gdc/service-mesh/{peer-authentication.yaml,authorization-policy.yaml,multicluster-service.yaml}` | `platform-ops-agent` | `09/scripts/validate_gdc_packaging.py` |
| `deploy/.gdc_packaging_index.json` | script | consumed by Stage 9 (`10-gdc-fleet-deployer-and-observability`) |

## Procedure

### 1. Package Cloud-Agnostic OCI Containers Matching `specs/target_stack.json` (`deploy/containers/`)
Follow `resources/gdc_packaging_template.md` and `_shared/gdc_multicloud_guardrails.md`:
1. **`Dockerfile.backend` & `Dockerfile.ui` (Must Match `specs/target_stack.json#{backend.kind, frontend.kind}`):**
   - Select the multi-stage base image and build toolchain matching `specs/target_stack.json` (`maven`/`eclipse-temurin` for `java-spring-boot`, `node` for `node-express` and `react`/`angular`/`vue`/`nextjs`, `golang` for `go`, `mcr.microsoft.com/dotnet` for `dotnet`, `python` + `uvicorn`/`gunicorn` for `python-fastapi`/`python-flask`). **Never** hardcode `FROM python:...` when `backend.kind` is `java-spring-boot`, `node-express`, `go`, or `dotnet` (`09/scripts/validate_gdc_packaging.py` fails Gate 8 if the Dockerfile base image mismatches `target_stack.json`).
   - Set `ENV APP_ENV=production` so the same codebase tested locally in Stage 5/6 (`APP_ENV=local`) runs in production target-environment mode (`DATABASE_URL`, `AUTH_MODE=oidc-iap`, `OTEL_EXPORTER_OTLP_ENDPOINT`).
   - Pin base image tags (never `:latest`), run as non-root (`USER 65532:65532`), expose a **non-privileged port `>= 1024`** (`EXPOSE 8080`, setting `ENV PORT=8080` and `ENV ASPNETCORE_HTTP_PORTS=8080` for `.NET` — never privileged `< 1024` such as `EXPOSE 80`), support `readOnlyRootFilesystem: true`, and declare a `HEALTHCHECK` hitting `/health`.
   - Enforce the **Stateless Container Contract** (`dlc.scan_stateless_container_hazards`: zero `InProc` sticky sessions, zero Windows-only `System.Web`/Registry/WCF/P/Invoke APIs in `src/`) and pass BuildKit static lint (`docker build --check` when Docker CLI is installed; recorded in `deploy/.gdc_packaging_index.json`).
   - Embed OCI traceability labels: `io.agentic.dlc.spec-sha256`, `io.agentic.dlc.capability-groups`, `io.agentic.dlc.abstraction-plane="gdc-fleet"`.
2. **`docker-compose.yaml`:**
   - Local target-stack verification stack wiring `ui`, `backend` (`APP_ENV=production` or `local`, `DATABASE_URL`), portable database (`alloydb-omni` / `postgres` / `sqlite`), and `otel-collector`.

### 2. Author KRM Base & GDC Provider Overlays (`deploy/gdc/base/` & `deploy/gdc/overlays/`)
1. **Base (`deploy/gdc/base/kustomization.yaml` & `workloads.yaml`):**
   - `ServiceAccount`, `Deployment` (with `securityContext.runAsNonRoot: true`, `readOnlyRootFilesystem: true`, liveness/readiness probes on `/health`), `Service`, `HorizontalPodAutoscaler`, `PodDisruptionBudget`, `NetworkPolicy`.
   - Portable database cluster/statefulset (`AlloyDB Omni` / `CloudNativePG` / PVC) + idempotent schema init `Job` applying `src/db/schema.sql`.
   - **Legacy scenario (`SCENARIO_LEGACY_APP`):** include a one-time `legacy-data-migration-job` `Job` referencing `design/data_migration_and_cutover.md` (with pre-cutover reconciliation check).
2. **Multi-Cloud & On-Prem Overlays (`deploy/gdc/overlays/{on-prem-gdc,gcp,aws,azure}/kustomization.yaml`):**
   - Reference `../../base` and set provider-specific GDC Fleet placement labels (`gdc.cloud.google.com/provider: on-prem-gdc | gcp | aws | azure`), storage class bindings, and ingress annotations without altering container images or application logic.

### 3. Derive GDC Policy Controller & Cloud Service Mesh (`deploy/gdc/policy-controller/` & `service-mesh/`)
1. **Policy Controller (`constraints.yaml`):** OPA Gatekeeper constraints derived from Spec Pillar 2 (`K8sPSPAllowedUsers`, `K8sPSPReadOnlyRootFS`, `K8sRequiredLabels`, `K8sRestrictEgress`).
2. **Cloud Service Mesh (`service-mesh/`):**
   - `peer-authentication.yaml`: `PeerAuthentication` with `mtls.mode: STRICT`.
   - `authorization-policy.yaml`: Istio `AuthorizationPolicy` mapping Spec `§3.5 Roles` & `§2.1 RBAC Matrix` to OpenAPI paths/methods from `src/contracts/openapi.yaml`.
   - `multicluster-service.yaml`: GDC `MultiClusterService` / `ServiceExport` for seamless cross-cloud and on-prem failover.

### 4. Validate & Mandatory STOP at Gate 8 (`gate_8_packaging`)
```bash
python3 <PLUGIN>/skills/09-container-and-gdc-packager/scripts/validate_gdc_packaging.py --project-root "<PROJECT_ROOT>"
```
Fix any reported failures until Gate 8 passes. When it passes, `validate_gdc_packaging.py` stamps `gate_8_packaging = AWAITING_HUMAN_REVIEW` in `specs/gate_approvals.json`, blocking Stage 9 (`run_gdc_fleet_deploy_and_verify.py`).
1. Present `deploy/containers/*` and `deploy/gdc/{base,overlays,policy-controller,service-mesh}/*` to the user.
2. **END YOUR TURN IMMEDIATELY (call zero further tools). NEVER start Stage 9 (`10-gdc-fleet-deployer-and-observability`) in the same turn!**
3. Only **in a subsequent turn AFTER the human approves Gate 8**, run:
   ```bash
   python3 <PLUGIN>/scripts/gate_tracker.py --project-root "<PROJECT_ROOT>" --action approve --gate gate_8_packaging --user-response "<verbatim user approval quote>"
   ```
   and then proceed to `10-gdc-fleet-deployer-and-observability`.

## Do not
- Import AWS/Azure/GCP proprietary SDKs in `src/` or hardcode cloud endpoints in container images.
- Run containers as `root` (`UID 0`) or use `:latest` base image tags.
- Duplicate base `Deployment` YAML across overlays — use Kustomize patches/labels only.
