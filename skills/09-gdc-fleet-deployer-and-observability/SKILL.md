---
name: 09-gdc-fleet-deployer-and-observability
description: "Stage 8 of the Agentic DLC v4. platform-ops-agent authors GDC Config Sync GitOps manifests with capability-group wave rollout (deploy/gdc/config-sync/), OpenTelemetry Collector pipelines (deploy/observability/otel-collector.yaml), Spec-derived SLOs and burn-rate alerts (deploy/observability/slo_and_alerts.yaml), a unified multi-cloud & on-prem Fleet Dashboard (deploy/observability/fleet_dashboard.json), and deploy/deployment_and_runbook.md; verified and executed by 09/scripts/run_gdc_fleet_deploy_and_verify.py (Gate 8) with Jira/ADO deployment traceability sync. Use when asked to deploy across GDC/multi-cloud/on-prem or configure fleet monitoring and SLOs."
---

# Stage 8 — GDC Fleet Multi-Cloud / On-Prem Deployment & Unified Observability (Gate 8)

**Read before acting:** `_shared/project_root.md`, `_shared/gdc_multicloud_guardrails.md`,
`docs/ARCHITECTURE.md` §3–§5. Subagent: `platform-ops-agent` ("The Navigator").

> **Unified Multi-Cloud & On-Prem Control Plane:** Using **GDC (Google Distributed Cloud) / GKE Enterprise**, this stage wires GitOps deployment (`Config Sync`) and unified Day-2 observability (`OpenTelemetry` → Google Cloud Managed Service for Prometheus / Cloud Logging / Cloud Trace in `gdc-connected` mode, or local Prometheus/Loki/Grafana in `gdc-air-gapped` mode) across **On-Premises (`on-prem-gdc`)**, **GCP (`gcp`)**, **AWS (`aws`)**, and **Azure (`azure`)**.

## Inputs
`deploy/.gdc_packaging_index.json` (from Stage 7), `specs/application_spec.md` (NFRs, Pillar 2 §2.3 Audit Events, §3.4 Business Rules `BR-*`), `specs/discovery_architecture_and_inventory.md` (§6.1 Capability Groupings & prerequisites), `specs/target_stack.json` (`$.deployment`, `$.selectedCapabilityGroups`), `backlog/user_stories.json`, and `test/test_cases.json`.

## Outputs
| File | Author | Checked by |
| :-- | :-- | :-- |
| `deploy/gdc/config-sync/{rootsync.yaml,cluster-selectors.yaml}` | `platform-ops-agent` | `09/scripts/run_gdc_fleet_deploy_and_verify.py` |
| `deploy/observability/otel-collector.yaml` | `platform-ops-agent` | `09/scripts/run_gdc_fleet_deploy_and_verify.py` |
| `deploy/observability/slo_and_alerts.yaml` | `platform-ops-agent` | `09/scripts/run_gdc_fleet_deploy_and_verify.py` |
| `deploy/observability/fleet_dashboard.json` | `platform-ops-agent` | `09/scripts/run_gdc_fleet_deploy_and_verify.py` |
| `deploy/deployment_and_runbook.md` | `platform-ops-agent` | `09/scripts/run_gdc_fleet_deploy_and_verify.py` |
| `deploy/deployment_eval_report.{md,json}` | script | `schemas/deployment_eval_results.schema.json` (Gate 8) |

## Procedure

### 1. Author GDC Config Sync & Capability-Group Rollout Waves (`deploy/gdc/config-sync/`)
1. **`cluster-selectors.yaml`:** Define one `ClusterSelector` per target environment (`selector-on-prem-gdc`, `selector-gcp`, `selector-aws`, `selector-azure`) matching `gdc.cloud.google.com/provider`.
2. **`rootsync.yaml`:** Define `RootSync` / `RepoSync` resources reconciling `deploy/gdc/overlays/<provider>` in topological wave order of `selectedCapabilityGroups` (`Wave 1`: `GRP-01` Shared Foundation; `Wave 2..N`: dependent capability groups).

### 2. Author Unified Multi-Cloud & On-Prem Observability (`deploy/observability/`)
1. **`otel-collector.yaml`:**
   - Configure `otlp` receiver, `batch` processor, and `resource` processor enriching every metric, trace, and `Spec §2.3` audit log with `gdc.cluster.provider` (`on-prem-gdc | gcp | aws | azure`), `gdc.cluster.name`, and `dlc.capability_group`.
   - Route telemetry to Google Cloud Managed Service for Prometheus / Cloud Trace / Cloud Logging (`gdc-connected`) and/or local Prometheus/Grafana (`gdc-air-gapped`).
2. **`slo_and_alerts.yaml`:**
   - Derive availability (`99.9%`) and latency (`p95`) `ServiceLevelObjective` resources plus `PrometheusRule` burn-rate & business-rule (`BR-*`) alert rules from `specs/application_spec.md`.
3. **`fleet_dashboard.json`:**
   - Single-pane-of-glass JSON dashboard with panels for Multi-Cloud & On-Prem Fleet Health (`on-prem-gdc`, `gcp`, `aws`, `azure`), HTTP RED metrics, SLO Error Budget Burn, Database & Migration Status, and Business Rule (`BR-*`) Counters.

### 3. Author Deployment Runbook (`deploy/deployment_and_runbook.md`)
Use `resources/deployment_runbook_template.md` covering: GDC Fleet Topology, Capability-Group Rollout Waves, Portable Database & Cutover, Cross-Cloud / On-Prem DR Failover (`MultiClusterService`), and Rollback Procedure.

### 4. Execute & Verify GDC Fleet Deployment (Gate 8)
```bash
python3 <PLUGIN>/skills/09-gdc-fleet-deployer-and-observability/scripts/run_gdc_fleet_deploy_and_verify.py --project-root "<PROJECT_ROOT>"
```
By default, validates all Config Sync, OTel, SLO, Dashboard, and Runbook contracts, runs a **local** `/health` smoke probe, and writes `deploy/deployment_eval_report.{md,json}` with `executionMode: "manifest-validation"` and waves marked `MANIFEST_VALIDATED`. Pass `--live` (with `kubectl` configured for each target environment) to execute `kubectl apply -k deploy/gdc/overlays/<env>` and record `DEPLOYED` / `gdc-live-fleet`. Syncs deployment traceability to Jira/ADO via `alm_jira_ado_bridge.py --action sync-deployment-status`.

## Do not
- Configure cloud-specific monitoring agents that only work on a single cloud provider — always route through OpenTelemetry and the GDC Fleet observability pipeline.
- Roll out downstream capability groups (`GRP-02..N`) before `GRP-01` (Shared Foundation) is healthy.
