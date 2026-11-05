#!/usr/bin/env bash
# ==============================================================================
# Enterprise Agentic DLC (agentic-dlc) — Developer Laptop Installer
# Supports macOS, Linux, and Windows WSL2
# Usage:
#   ./bootstrap.sh [--project-root /path/to/my-project] [--install-playwright]
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT=""
INSTALL_PLAYWRIGHT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root)
      PROJECT_ROOT="$2"
      shift 2
      ;;
    --install-playwright)
      INSTALL_PLAYWRIGHT=1
      shift
      ;;
    -h|--help)
      echo "Usage: ./bootstrap.sh [--project-root /path/to/project] [--install-playwright]"
      exit 0
      ;;
    *)
      if [[ -z "${PROJECT_ROOT}" ]]; then
        PROJECT_ROOT="$1"
      fi
      shift
      ;;
  esac
done

# 1. Resolve <PROJECT_ROOT> safely (never use the installer folder itself)
CALLER_PWD="$(pwd)"
CALLER_BASE="$(basename "${CALLER_PWD}")"
if [[ -z "${PROJECT_ROOT}" ]]; then
  if [[ "${CALLER_PWD}" != "${SCRIPT_DIR}" && "${CALLER_BASE}" != *agentic-dlc* ]]; then
    PROJECT_ROOT="${CALLER_PWD}"
  fi
fi

GEMINI_CONFIG="${HOME}/.gemini/config"
PLUGIN_DEST="${GEMINI_CONFIG}/plugins/agentic-dlc"

echo "=============================================================================="
echo " Installing Enterprise Agentic DLC (agentic-dlc)"
echo "=============================================================================="

# 2. Clean up any legacy global rules/skills that would shadow the plugin
echo "[1/5] Removing any stale global rules/skills..."
rm -rf "${GEMINI_CONFIG}/plugins/agentic-dlc" \
       "${GEMINI_CONFIG}/rules/AGENTS.md" \
       "${GEMINI_CONFIG}/skills/00-setup-and-connection" \
       "${GEMINI_CONFIG}/skills/01-discovery-and-grouping" \
       "${GEMINI_CONFIG}/skills/02-spec-architect-and-judge" \
       "${GEMINI_CONFIG}/skills/03-story-and-sprint-planner" \
       "${GEMINI_CONFIG}/skills/04-solution-architect" \
       "${GEMINI_CONFIG}/skills/05-test-plan-designer" \
       "${GEMINI_CONFIG}/skills/06-coding-agent" \
       "${GEMINI_CONFIG}/skills/07-test-runner-and-healer" \
       "${GEMINI_CONFIG}/skills/08-container-and-gdc-packager" \
       "${GEMINI_CONFIG}/skills/09-gdc-fleet-deployer-and-observability" \
       "${GEMINI_CONFIG}/skills/google-cloud-ui-design"

# 3. Install plugin into ~/.gemini/config/plugins/agentic-dlc
echo "[2/5] Installing plugin to ${PLUGIN_DEST}..."
mkdir -p "${GEMINI_CONFIG}/plugins" "${GEMINI_CONFIG}/rules" "${GEMINI_CONFIG}/skills" "${GEMINI_CONFIG}/agents"
rm -rf "${PLUGIN_DEST}"
cp -R "${SCRIPT_DIR}" "${PLUGIN_DEST}"
rm -rf "${PLUGIN_DEST}/.git"

# Sync rules, skills, and subagents for global discovery
cp -f "${PLUGIN_DEST}/rules/AGENTS.md" "${GEMINI_CONFIG}/rules/AGENTS.md"
for skill_dir in "${PLUGIN_DEST}/skills/"*; do
  if [[ -d "${skill_dir}" ]]; then
    skill_name="$(basename "${skill_dir}")"
    rm -rf "${GEMINI_CONFIG}/skills/${skill_name}"
    cp -R "${skill_dir}" "${GEMINI_CONFIG}/skills/${skill_name}"
  fi
done
for agent_file in "${PLUGIN_DEST}/agents/"*.md; do
  if [[ -f "${agent_file}" ]]; then
    cp -f "${agent_file}" "${GEMINI_CONFIG}/agents/$(basename "${agent_file}")"
  fi
done

# 4. Create default ALM credentials template if not present
ENV_FILE="${GEMINI_CONFIG}/agentic-dlc.env"
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "[3/5] Creating ALM credentials template at ${ENV_FILE}..."
  cat > "${ENV_FILE}" <<'EOF'
# Atlassian Jira Cloud (optional — leave blank for offline CSV/JSON mode)
JIRA_URL=
JIRA_EMAIL=
JIRA_API_TOKEN=
JIRA_PROJECT_KEY=
JIRA_BOARD_ID=

# Microsoft Azure DevOps Boards (optional)
ADO_ORG_URL=
ADO_PROJECT=
ADO_PAT=

# Default Sprint Velocity Capacity (story points per sprint, default 21)
DLC_SPRINT_CAPACITY_POINTS=21

# Google Distributed Cloud (GDC) Fleet & Multi-Cloud / On-Prem Deployment (optional)
GDC_FLEET_PROJECT=
GDC_CONNECTIVITY_MODE=gdc-connected
GDC_CONTAINER_REGISTRY=registry.gdc.local
GDC_TARGET_ENVIRONMENTS=on-prem-gdc,gcp,aws,azure
EOF
  chmod 600 "${ENV_FILE}" || true
else
  echo "[3/5] Preserving existing ALM credentials file at ${ENV_FILE}."
fi

# 5. Scaffold <PROJECT_ROOT> if provided or invoked from a project directory
if [[ -n "${PROJECT_ROOT}" ]]; then
  mkdir -p "${PROJECT_ROOT}"
  PROJECT_ROOT="$(cd "${PROJECT_ROOT}" && pwd)"
  echo "[4/5] Initializing project directory structure at ${PROJECT_ROOT}..."
  mkdir -p "${PROJECT_ROOT}/resources/inputs" \
           "${PROJECT_ROOT}/resources/design_references" \
           "${PROJECT_ROOT}/resources/policies_and_statutes" \
           "${PROJECT_ROOT}/resources/shared_services" \
           "${PROJECT_ROOT}/specs" \
           "${PROJECT_ROOT}/backlog" \
           "${PROJECT_ROOT}/design" \
           "${PROJECT_ROOT}/test" \
           "${PROJECT_ROOT}/src" \
           "${PROJECT_ROOT}/deploy/containers" \
           "${PROJECT_ROOT}/deploy/gdc/base" \
           "${PROJECT_ROOT}/deploy/gdc/overlays/on-prem-gdc" \
           "${PROJECT_ROOT}/deploy/gdc/overlays/gcp" \
           "${PROJECT_ROOT}/deploy/gdc/overlays/aws" \
           "${PROJECT_ROOT}/deploy/gdc/overlays/azure" \
           "${PROJECT_ROOT}/deploy/gdc/policy-controller" \
           "${PROJECT_ROOT}/deploy/gdc/service-mesh" \
           "${PROJECT_ROOT}/deploy/gdc/config-sync" \
           "${PROJECT_ROOT}/deploy/observability"
  echo "${PROJECT_ROOT}" > "${GEMINI_CONFIG}/project_root.txt"
  echo "      Saved active project root -> ${GEMINI_CONFIG}/project_root.txt"
else
  echo "[4/5] No --project-root specified (global plugin installed)."
  echo "      To bind a project folder later, run:"
  echo "        ${PLUGIN_DEST}/bootstrap.sh --project-root /path/to/your-project"
fi

# 6. Optional Playwright Chromium installation for Stage 1 & Stage 6 browser verification
if [[ "${INSTALL_PLAYWRIGHT}" -eq 1 ]]; then
  echo "[5/5] Installing Python Playwright + Chromium browser..."
  python3 -m pip install --upgrade playwright && python3 -m playwright install chromium
else
  echo "[5/5] Checking browser runtime..."
  if python3 -c "import playwright" >/dev/null 2>&1; then
    echo "      Playwright Python package detected."
  else
    echo "      (Optional) For full Playwright browser inspection & reference crawling, run:"
    echo "        python3 -m pip install playwright && python3 -m playwright install chromium"
  fi
fi

echo "=============================================================================="
echo " Installation Complete!"
echo " - Plugin Path  : ${PLUGIN_DEST}"
echo " - ALM Env File : ${ENV_FILE}"
if [[ -n "${PROJECT_ROOT}" ]]; then
  echo " - Project Root : ${PROJECT_ROOT}"
  echo " Next Step: Place your legacy files or BRD in ${PROJECT_ROOT}/resources/inputs/"
fi
echo "=============================================================================="
