# GDC Packaging Reference Skeleton (`08-container-and-gdc-packager`)

> **Target-Stack Alignment Rule (`specs/target_stack.json`):**
> `deploy/containers/Dockerfile.backend` and `deploy/containers/Dockerfile.ui` MUST use multi-stage builds matching the confirmed `specs/target_stack.json#{backend.kind, frontend.kind}` (never hardcoding `FROM python:...` when `backend.kind` is `java-spring-boot`, `node-express`, `go`, or `dotnet`). Both images set `ENV APP_ENV=production` so the same `src/` codebase tested locally in Stage 5/6 (`APP_ENV=local`) runs in production cloud/GDC mode (`APP_ENV=production`, `DATABASE_URL`, `AUTH_MODE=oidc-iap`, `OTEL_EXPORTER_OTLP_ENDPOINT`).

## 1A. `deploy/containers/Dockerfile.backend` — Select the Multi-Stage Pattern Matching `specs/target_stack.json#backend.kind`

### Pattern A: `backend.kind == "java-spring-boot"`
```dockerfile
FROM maven:3.9.8-eclipse-temurin-21 AS build
WORKDIR /workspace
COPY src/backend/ /workspace/
RUN mvn -B -DskipTests package

FROM eclipse-temurin:21.0.4_7-jre-jammy
LABEL io.agentic.dlc.abstraction-plane="gdc-fleet" \
      io.agentic.dlc.spec-sha256="<specSha256>" \
      io.agentic.dlc.capability-groups="<GRP-01,...>"
WORKDIR /app
COPY --from=build /workspace/target/*.jar /app/app.jar
COPY src/db/schema.sql /app/src/db/schema.sql
RUN groupadd -g 65532 nonroot && useradd -u 65532 -g 65532 -s /sbin/nologin nonroot && chown -R 65532:65532 /app
USER 65532:65532
ENV APP_ENV=production PORT=8080 SPRING_PROFILES_ACTIVE=production OTEL_EXPORTER_OTLP_ENDPOINT="http://otel-collector:4318"
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD ["curl", "-fsS", "http://127.0.0.1:8080/health"]
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
```

### Pattern B: `backend.kind == "node-express"` (or `frontend.kind in ("react", "angular", "vue", "nextjs")` for `Dockerfile.ui`)
```dockerfile
FROM node:20.17.0-bookworm-slim AS build
WORKDIR /workspace
COPY src/backend/ /workspace/
RUN npm ci && npm run build --if-present

FROM node:20.17.0-bookworm-slim
LABEL io.agentic.dlc.abstraction-plane="gdc-fleet" \
      io.agentic.dlc.spec-sha256="<specSha256>" \
      io.agentic.dlc.capability-groups="<GRP-01,...>"
WORKDIR /app
COPY --from=build /workspace/ /app/
COPY src/db/schema.sql /app/src/db/schema.sql
RUN groupadd -g 65532 nonroot && useradd -u 65532 -g 65532 -s /sbin/nologin nonroot && chown -R 65532:65532 /app
USER 65532:65532
ENV APP_ENV=production NODE_ENV=production PORT=8080 OTEL_EXPORTER_OTLP_ENDPOINT="http://otel-collector:4318"
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD ["node", "-e", "fetch('http://127.0.0.1:8080/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
CMD ["npm", "start"]
```

### Pattern C: `backend.kind in ("python-fastapi", "python-flask", "python-stdlib-http")`
```dockerfile
FROM python:3.12-slim-bookworm
LABEL io.agentic.dlc.abstraction-plane="gdc-fleet" \
      io.agentic.dlc.spec-sha256="<specSha256>" \
      io.agentic.dlc.capability-groups="<GRP-01,...>"
WORKDIR /app
COPY src/ /app/src/
RUN if [ -f /app/src/backend/requirements.txt ]; then pip install --no-cache-dir -r /app/src/backend/requirements.txt; fi \
    && groupadd -g 65532 nonroot && useradd -u 65532 -g 65532 -s /sbin/nologin nonroot \
    && chown -R 65532:65532 /app
USER 65532:65532
ENV APP_ENV=production PORT=8080 PYTHONUNBUFFERED=1 OTEL_EXPORTER_OTLP_ENDPOINT="http://otel-collector:4318"
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health')"]
CMD ["bash", "src/run.sh"]
```

### Pattern D: `backend.kind == "go"` or `"dotnet"`
- **`go`:** `FROM golang:1.22.7-bookworm AS build` (`go build -o /out/server ./cmd/server`) → `FROM debian:bookworm-slim` with `USER 65532:65532` and `ENV APP_ENV=production`.
- **`dotnet`:** `FROM mcr.microsoft.com/dotnet/sdk:8.0.401 AS build` (`dotnet publish -c Release -o /out`) → `FROM mcr.microsoft.com/dotnet/aspnet:8.0.8` with `USER 65532:65532` and `ENV APP_ENV=production ASPNETCORE_ENVIRONMENT=Production`.

## 2. `deploy/gdc/base/kustomization.yaml` & `workloads.yaml`
- `kustomization.yaml` lists `resources: [workloads.yaml]`.
- `workloads.yaml` defines:
  - `ServiceAccount`
  - `Deployment` (`runAsNonRoot: true`, `runAsUser: 65532`, `readOnlyRootFilesystem: true`, `/health` liveness & readiness probes, OTel env vars)
  - `Service`, `HorizontalPodAutoscaler`, `PodDisruptionBudget`, `NetworkPolicy`
  - `Job` `db-schema-migration` applying `src/db/schema.sql` (and `Job` `legacy-data-cutover-etl` referencing `design/data_migration_and_cutover.md` when `inputScenario == SCENARIO_LEGACY_APP`)

## 3. `deploy/gdc/overlays/<provider>/kustomization.yaml` (`on-prem-gdc`, `gcp`, `aws`, `azure`)
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../base
commonLabels:
  gdc.cloud.google.com/provider: "<on-prem-gdc|gcp|aws|azure>"
  gdc.cloud.google.com/fleet-managed: "true"
commonAnnotations:
  configmanagement.gke.io/cluster-selector: "selector-<on-prem-gdc|gcp|aws|azure>"
  gdc.cloud.google.com/storage-class: "<provider-storage-class>"
```

## 4. `deploy/gdc/policy-controller/constraints.yaml`
- `K8sPSPAllowedUsers` (`MustRunAsNonRoot`)
- `K8sPSPReadOnlyRootFS`
- `K8sRequiredLabels` (`gdc.cloud.google.com/fleet-managed`)
- `K8sRestrictEgress` (enforcing Spec Pillar 2 network/data-exfiltration controls)

## 5. `deploy/gdc/service-mesh/{peer-authentication.yaml,authorization-policy.yaml,multicluster-service.yaml}`
- `PeerAuthentication` (`mtls.mode: STRICT`)
- `AuthorizationPolicy` (maps Spec `§3.5` roles and `src/contracts/openapi.yaml` operations)
- `MultiClusterService` / `ServiceExport` (exposes service across On-Prem, GCP, AWS, and Azure fleet clusters)
