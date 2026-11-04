# GDC Multi-Cloud & On-Prem Portability Guardrails (`REQ-DEPLOY-GDC`) — canonical copy (shared)

**Google Distributed Cloud (GDC) / GKE Enterprise** is the universal abstraction and control plane between containerized applications (`src/`) and any underlying infrastructure (`on-prem-gdc`, `gcp`, `aws`, `azure`). Every Stage 7 (`08-container-and-gdc-packager`) and Stage 8 (`09-gdc-fleet-deployer-and-observability`) artefact must honour these 8 guardrails:

1. **Zero Cloud-Vendor SDK Lock-In in Application Code (`src/`):**
   - Application source code (`src/ui/`, `src/backend/`, `src/db/`) must never import provider-proprietary cloud SDKs (`boto3`, `botocore`, `azure.identity`, `azure.storage`, or direct cloud-specific control-plane SDKs). All backing services (database, object storage, identity, telemetry) are consumed via open protocols (SQL, HTTP/REST, OIDC JWT headers, OpenTelemetry OTLP) and 12-Factor environment variables.
2. **Rootless, Hardened, Traceable OCI Containers (`deploy/containers/`):**
   - Every `Dockerfile.*` runs as a non-root user (`USER 65532:65532` or non-zero UID), supports read-only root filesystems (`readOnlyRootFilesystem: true`), defines a `/health` `HEALTHCHECK`, pins base image versions (never `:latest`), and embeds OCI labels (`io.agentic.dlc.spec-sha256`, `io.agentic.dlc.capability-groups`).
3. **Single KRM Base + Provider Overlays (`deploy/gdc/base/` & `deploy/gdc/overlays/`):**
   - Workload manifests (`Deployment`, `Service`, `HorizontalPodAutoscaler`, `PodDisruptionBudget`, `NetworkPolicy`, `ServiceAccount`, schema migration `Job`) are authored **once** in `deploy/gdc/base/`.
   - Cloud and on-prem specifics (`StorageClass`, ingress/Gateway class, node topology spread, and GDC `ClusterSelector` labels) live exclusively in Kustomize overlays under `deploy/gdc/overlays/{on-prem-gdc,gcp,aws,azure}/`.
4. **Database & Migration Portability Across Clouds & On-Prem:**
   - Stateful persistence uses portable SQL (`src/db/schema.sql`) running on **AlloyDB Omni** or **CloudNativePG** (which run identically inside containers on GDC Bare Metal/VMware on-prem, AWS, Azure, and GCP) or an attached PVC in air-gapped/edge mode.
   - For `SCENARIO_LEGACY_APP`, one-time ETL and reconciliation from `design/data_migration_and_cutover.md` are packaged as an idempotent KRM `Job` that runs before traffic cutover.
5. **Spec-Driven GDC Policy Controller (`deploy/gdc/policy-controller/`):**
   - Every security and PII mandate in **Spec Pillar 2 (`REQ-SEC-*`)** maps to an enforceable OPA Gatekeeper / GDC Policy Controller constraint (`K8sPSPAllowedUsers`, `K8sPSPReadOnlyRootFS`, `K8sRequiredLabels`, `K8sRestrictEgress`) applied uniformly across all fleet clusters.
6. **Spec-Driven GDC Cloud Service Mesh (`deploy/gdc/service-mesh/`):**
   - Enforce fleet-wide zero-trust mTLS (`PeerAuthentication` with `mtls.mode: STRICT`), L7 `AuthorizationPolicy` rules derived directly from **Spec `§2.1 RBAC Matrix`, `§3.5 Roles`, and `src/contracts/openapi.yaml`**, and cross-cloud/on-prem routing via `MultiClusterService` / `ServiceExport`.
7. **Capability-Group GitOps Wave Rollout via GDC Config Sync (`deploy/gdc/config-sync/`):**
   - GDC Config Sync (`RootSync` / `RepoSync` + `ClusterSelector`) reconciles workloads across fleet memberships (`on-prem-gdc`, `gcp`, `aws`, `azure`) in topological order of `selectedCapabilityGroups` (`GRP-01` Shared Foundation first, followed by dependent groups `GRP-02..N`).
8. **Unified Multi-Cloud & On-Prem Observability (`deploy/observability/`):**
   - OpenTelemetry Collector (`otel-collector.yaml`) enriches all metrics, traces, and `Spec §2.3` immutable audit logs with `gdc.cluster.provider` (`on-prem-gdc | gcp | aws | azure`), `gdc.cluster.name`, and `dlc.capability_group` (`GRP-*`), exporting to Google Cloud Managed Service for Prometheus / Cloud Logging / Cloud Trace in `gdc-connected` mode or local Prometheus/Loki/Grafana in `gdc-air-gapped` mode, paired with Spec-derived SLOs (`slo_and_alerts.yaml`) and a single-pane-of-glass `fleet_dashboard.json`.
