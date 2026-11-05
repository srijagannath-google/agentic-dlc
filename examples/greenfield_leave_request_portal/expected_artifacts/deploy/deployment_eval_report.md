# GDC Multi-Cloud & On-Prem Deployment Evaluation Report (`deploy/deployment_eval_report.md`)

- **Verdict:** `PASS` (17/17 checks passed, 0 failed)
- **Abstraction Control Plane:** `gdc-fleet` (`gdc-connected`)
- **Execution Mode:** `manifest-validation` — manifests validated statically; nothing was applied to a cluster.
- **Target Fleet Environments:** `on-prem-gdc, gcp, aws, azure`
- **Evaluated At (UTC):** `1970-01-01T00:00:00Z`

## 1. OCI Container Images
| Component | Dockerfile | Non-Root User | SHA-256 Digest | Status |
| :-- | :-- | :-- | :-- | :-: |
| `backend` | `deploy/containers/Dockerfile.backend` | `65532:65532` | `b648f5e5122dc3a3…` | `PASS` |
| `ui` | `deploy/containers/Dockerfile.ui` | `65532:65532` | `8ff479c60ec6ef41…` | `PASS` |

## 2. GDC Kustomize Provider Overlays
| Environment | Overlay Path | GDC Cluster Selector | Status |
| :-- | :-- | :-- | :-: |
| `on-prem-gdc` | `deploy/gdc/overlays/on-prem-gdc/kustomization.yaml` | `selector-on-prem-gdc` | `PASS` |
| `gcp` | `deploy/gdc/overlays/gcp/kustomization.yaml` | `selector-gcp` | `PASS` |
| `aws` | `deploy/gdc/overlays/aws/kustomization.yaml` | `selector-aws` | `PASS` |
| `azure` | `deploy/gdc/overlays/azure/kustomization.yaml` | `selector-azure` | `PASS` |

## 3. Capability-Group GitOps Rollout Waves (`GDC Config Sync`)
| Wave | Capability Group | Group Name | Prerequisite Groups | Target Environments | Status |
| :-: | :-- | :-- | :-- | :-- | :-: |
| 1 | `GRP-01` | Employee Leave Self-Service & Balance Calculation | `None (Shared Foundation)` | `on-prem-gdc, gcp, aws, azure` | `MANIFEST_VALIDATED` |
| 2 | `GRP-02` | Manager & HR Certification Adjudication | `GRP-01` | `on-prem-gdc, gcp, aws, azure` | `MANIFEST_VALIDATED` |
| 2 | `GRP-03` | Payroll Posting Integration & Audit Compliance | `GRP-01` | `on-prem-gdc, gcp, aws, azure` | `MANIFEST_VALIDATED` |

## 4. GDC Policy Controller, Service Mesh & Unified Observability
| Control Plane Pillar | Summary | Status |
| :-- | :-- | :-: |
| **GDC Policy Controller (OPA)** | 2 constraints (`nonRoot=True`, `readOnlyRootFs=True`) | `PASS` |
| **GDC Cloud Service Mesh** | `strictMtls=True`, 1 `AuthorizationPolicy`, `multiClusterService=True` | `PASS` |
| **GDC Unified Observability** | `otelCollector=True`, 1 SLO(s), 2 alert(s), 5 dashboard panel(s) | `PASS` |

## 5. Local Smoke Probe (application started from `commands.start`; not a cluster probe)
| Probe | Target | HTTP Status | Status | Detail |
| :-- | :-- | :-: | :-: | :-- |
| `local-healthcheck` | `http://127.0.0.1:8766/health` | `200` | `PASS` | local application started from commands.start answered the healthcheck. |
