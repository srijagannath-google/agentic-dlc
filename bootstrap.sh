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

usage() {
  echo "Usage: ./bootstrap.sh [--project-root /path/to/project] [--install-playwright]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root)
      if [[ $# -lt 2 || -z "${2:-}" || "${2:-}" == --* ]]; then
        echo "ERROR: --project-root requires a directory argument." >&2
        usage >&2
        exit 2
      fi
      PROJECT_ROOT="$2"
      shift 2
      ;;
    --project-root=*)
      PROJECT_ROOT="${1#--project-root=}"
      shift
      ;;
    --install-playwright)
      INSTALL_PLAYWRIGHT=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --*)
      echo "ERROR: unknown option '$1'." >&2
      usage >&2
      exit 2
      ;;
    *)
      # A stray positional argument is never silently taken as the project root.
      echo "ERROR: unexpected argument '$1'. Use --project-root /path/to/project." >&2
      usage >&2
      exit 2
      ;;
  esac
done

# Resolve a path to its canonical absolute form (realpath is not available on every macOS).
canon() {
  if command -v realpath >/dev/null 2>&1; then
    realpath "$1" 2>/dev/null || (cd "$1" 2>/dev/null && pwd -P)
  else
    (cd "$1" 2>/dev/null && pwd -P) || python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$1"
  fi
}

# True when a directory name is the plugin/installer directory itself (exact name only — a project called
# `agentic-dlc-demo-app` is a legitimate <PROJECT_ROOT>).
is_plugin_dir_name() {
  local name="$1"
  [[ "${name}" =~ ^[Aa][Gg][Ee][Nn][Tt][Ii][Cc]-[Dd][Ll][Cc](-[Vv][0-9]+)?$ ]]
}

# 1. Resolve <PROJECT_ROOT> safely (never use the installer folder itself, never silently bind the cwd)
CALLER_PWD="$(pwd)"
CALLER_BASE="$(basename "${CALLER_PWD}")"
if [[ -z "${PROJECT_ROOT}" ]]; then
  caller_is_plugin=0
  if [[ "${CALLER_PWD}" == "${SCRIPT_DIR}" ]] || is_plugin_dir_name "${CALLER_BASE}" \
     || { [[ -f "${CALLER_PWD}/plugin.json" ]] && [[ -d "${CALLER_PWD}/skills" ]]; }; then
    caller_is_plugin=1
  fi
  if [[ "${caller_is_plugin}" -eq 0 ]]; then
    case "${CALLER_PWD}" in
      "${HOME}"|"${HOME}/Downloads"|"${HOME}/Desktop"|"${HOME}/Documents"|/|/tmp)
        echo "NOTE: ${CALLER_PWD} is a general-purpose folder and will not be used as a project root."
        ;;
      *)
        if [[ -t 0 && -t 1 ]]; then
          read -r -p "Bind the current directory as <PROJECT_ROOT>? [${CALLER_PWD}] (y/N): " answer
          if [[ "${answer}" =~ ^[Yy]([Ee][Ss])?$ ]]; then
            PROJECT_ROOT="${CALLER_PWD}"
          fi
        else
          echo "NOTE: no --project-root given and not running interactively; the current directory was NOT bound as a project root."
        fi
        ;;
    esac
  fi
fi

GEMINI_CONFIG="${HOME}/.gemini/config"
PLUGIN_DEST="${GEMINI_CONFIG}/plugins/agentic-dlc"

# Reject the plugin/installer directory as a project root before any side effect.
if [[ -n "${PROJECT_ROOT}" ]]; then
  if is_plugin_dir_name "$(basename "${PROJECT_ROOT%/}")" \
     || { [[ -d "${PROJECT_ROOT}" ]] && [[ "$(canon "${PROJECT_ROOT}")" == "$(canon "${SCRIPT_DIR}")" ]]; }; then
    echo "ERROR: ${PROJECT_ROOT} is the plugin/installer directory and can never be a <PROJECT_ROOT>." >&2
    exit 2
  fi
fi

echo "=============================================================================="
echo " Installing Enterprise Agentic DLC (agentic-dlc)"
echo "=============================================================================="

# 2. Clean up any stale global skills that would shadow the plugin (the global rules file is handled below
#    with a backup — it is shared with other plugins and is never silently deleted).
echo "[1/5] Removing any stale global skills..."
rm -rf "${GEMINI_CONFIG}/skills/00-setup-and-connection" \
       "${GEMINI_CONFIG}/skills/01-discovery-and-grouping" \
       "${GEMINI_CONFIG}/skills/02-spec-architect-and-judge" \
       "${GEMINI_CONFIG}/skills/03-story-and-sprint-planner" \
       "${GEMINI_CONFIG}/skills/04-solution-architect" \
       "${GEMINI_CONFIG}/skills/05-test-plan-designer" \
       "${GEMINI_CONFIG}/skills/06-coding-agent" \
       "${GEMINI_CONFIG}/skills/07-test-runner-and-healer" \
       "${GEMINI_CONFIG}/skills/08-drift-and-evolution" \
       "${GEMINI_CONFIG}/skills/09-container-and-gdc-packager" \
       "${GEMINI_CONFIG}/skills/10-gdc-fleet-deployer-and-observability" \
       "${GEMINI_CONFIG}/skills/08-container-and-gdc-packager" \
       "${GEMINI_CONFIG}/skills/09-gdc-fleet-deployer-and-observability" \
       "${GEMINI_CONFIG}/skills/10-drift-and-evolution" \
       "${GEMINI_CONFIG}/skills/clarification-griller" \
       "${GEMINI_CONFIG}/skills/google-cloud-ui-design"

# 3. Install plugin into ~/.gemini/config/plugins/agentic-dlc
echo "[2/5] Installing plugin to ${PLUGIN_DEST}..."
mkdir -p "${GEMINI_CONFIG}/plugins" "${GEMINI_CONFIG}/rules" "${GEMINI_CONFIG}/skills" "${GEMINI_CONFIG}/agents"

# Files that are part of the development checkout but never of an installation.
INSTALL_EXCLUDES=(".git" "__pycache__" "*.pyc" "push-to-github.sh")

SRC_REAL="$(canon "${SCRIPT_DIR}")"
DEST_REAL=""
if [[ -e "${PLUGIN_DEST}" ]]; then
  DEST_REAL="$(canon "${PLUGIN_DEST}")"
fi
if [[ -n "${DEST_REAL}" && "${SRC_REAL}" == "${DEST_REAL}" ]]; then
  # Running from the installed location itself (or a development checkout living there): nothing to copy,
  # and never delete files from the directory we are executing from.
  echo "      Already running from ${PLUGIN_DEST} — skipping self-copy."
elif [[ -n "${DEST_REAL}" && "${SRC_REAL}" == "${DEST_REAL}"/* ]]; then
  echo "ERROR: ${SCRIPT_DIR} is inside the install destination ${PLUGIN_DEST}; refusing to replace the destination from within it." >&2
  exit 2
else
  rm -rf "${PLUGIN_DEST}"
  if command -v rsync >/dev/null 2>&1; then
    rsync_args=(-a)
    for ex in "${INSTALL_EXCLUDES[@]}"; do rsync_args+=(--exclude "${ex}"); done
    rsync "${rsync_args[@]}" "${SCRIPT_DIR}/" "${PLUGIN_DEST}/"
  else
    cp -R "${SCRIPT_DIR}" "${PLUGIN_DEST}"
    for ex in "${INSTALL_EXCLUDES[@]}"; do
      case "${ex}" in
        *"*"*) find "${PLUGIN_DEST}" -name "${ex}" -type f -delete 2>/dev/null || true ;;
        *)     find "${PLUGIN_DEST}" -name "${ex}" -prune -exec rm -rf {} + 2>/dev/null || true ;;
      esac
    done
  fi
fi

# Sync rules, skills, and subagents for global discovery.
# The global rules file is shared with other plugins: back it up instead of discarding user content.
GLOBAL_RULES="${GEMINI_CONFIG}/rules/AGENTS.md"
if [[ -f "${GLOBAL_RULES}" ]] && ! cmp -s "${PLUGIN_DEST}/rules/AGENTS.md" "${GLOBAL_RULES}"; then
  backup="${GLOBAL_RULES}.bak-$(date +%Y%m%d-%H%M%S)"
  cp -p "${GLOBAL_RULES}" "${backup}"
  echo "      WARNING: existing ${GLOBAL_RULES} differs from the agentic-dlc router rules and was backed up to:"
  echo "               ${backup}"
  echo "               Re-apply any custom rules from the backup after installation."
fi
cp -f "${PLUGIN_DEST}/rules/AGENTS.md" "${GLOBAL_RULES}"
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

# Gemini Decisions API (gemini-decision-1 low-cost control plane — $0.10/1M input tokens, $0 output tokens)
GEMINI_API_KEY=

# CodeMender Security CLI ('cm') authentication (or run `gcloud auth application-default login`)
CM_API_KEY=
# CM_BIN=~/.codemender/cm

# Google Distributed Cloud (GDC) Fleet deployment: targets and connectivity come from
# specs/target_stack.json#deployment. Only Stage 8 `--live` (kubectl apply) reads optional per-environment
# kube contexts; uncomment and set as needed:
# GDC_KUBE_CONTEXT_ON_PREM_GDC=
# GDC_KUBE_CONTEXT_GCP=
# GDC_KUBE_CONTEXT_AWS=
# GDC_KUBE_CONTEXT_AZURE=
EOF
  chmod 600 "${ENV_FILE}" || true
else
  echo "[3/5] Preserving existing ALM credentials file at ${ENV_FILE}."
fi

# 5. Scaffold <PROJECT_ROOT> if provided (or confirmed interactively)
#    Only the authoring folders are created; deploy/ is created by Stage 8 (09-container-and-gdc-packager)
#    so an empty deploy/ never makes the pipeline think Stages 8/9 are in scope.
if [[ -n "${PROJECT_ROOT}" ]]; then
  mkdir -p "${PROJECT_ROOT}"
  PROJECT_ROOT="$(cd "${PROJECT_ROOT}" && pwd)"
  if [[ "$(canon "${PROJECT_ROOT}")" == "${SRC_REAL}" ]] || is_plugin_dir_name "$(basename "${PROJECT_ROOT}")"; then
    echo "ERROR: ${PROJECT_ROOT} is the plugin/installer directory and can never be a <PROJECT_ROOT>." >&2
    exit 2
  fi
  echo "[4/5] Initializing project directory structure at ${PROJECT_ROOT}..."
  mkdir -p "${PROJECT_ROOT}/resources/inputs" \
           "${PROJECT_ROOT}/resources/design_references" \
           "${PROJECT_ROOT}/resources/policies_and_statutes" \
           "${PROJECT_ROOT}/resources/shared_services" \
           "${PROJECT_ROOT}/specs" \
           "${PROJECT_ROOT}/backlog" \
           "${PROJECT_ROOT}/design" \
           "${PROJECT_ROOT}/test" \
           "${PROJECT_ROOT}/src"
  printf '%s\n' "${PROJECT_ROOT}" > "${GEMINI_CONFIG}/project_root.txt"
  echo "      Saved active project root -> ${GEMINI_CONFIG}/project_root.txt"
else
  echo "[4/5] No --project-root specified (global plugin installed)."
  echo "      To bind a project folder later, run:"
  echo "        ${PLUGIN_DEST}/bootstrap.sh --project-root /path/to/your-project"
fi

# 6. Optional Playwright Chromium installation for Stage 1 & Stage 6 browser verification
if [[ "${INSTALL_PLAYWRIGHT}" -eq 1 ]]; then
  echo "[5/5] Installing Python Playwright + Chromium browser..."
  if python3 -m pip install --user --upgrade playwright; then
    python3 -m playwright install chromium
  else
    echo "      Playwright pip install failed. On PEP 668 ('externally-managed-environment') systems use either:"
    echo "        pipx install playwright && playwright install chromium"
    echo "        python3 -m venv ~/.venvs/dlc && ~/.venvs/dlc/bin/pip install playwright && ~/.venvs/dlc/bin/playwright install chromium"
    echo "      or install Google Chrome / Chromium and point CHROME_BIN at the binary (the Stage 6 runner falls back to chrome --headless)."
  fi
else
  echo "[5/5] Checking browser runtime..."
  if python3 -c "import playwright" >/dev/null 2>&1; then
    echo "      Playwright Python package detected."
  else
    echo "      (Optional) For full Playwright browser inspection & reference crawling, run:"
    echo "        python3 -m pip install --user playwright && python3 -m playwright install chromium"
  fi
fi

# 7. Check CodeMender ('cm') security CLI availability and alert user if missing
CM_DETECTED=""
if [[ -n "${CM_BIN:-}" && -x "${CM_BIN}" ]]; then
  CM_DETECTED="${CM_BIN}"
elif command -v cm >/dev/null 2>&1; then
  CM_DETECTED="$(command -v cm)"
elif [[ -x "${HOME}/.codemender/cm" ]]; then
  CM_DETECTED="${HOME}/.codemender/cm"
fi

if [[ -n "${CM_DETECTED}" ]]; then
  echo "      CodeMender ('cm') security CLI detected at: ${CM_DETECTED}"
else
  echo "------------------------------------------------------------------------------"
  echo "[SECURITY ALERT] CodeMender ('cm') CLI is NOT installed on this machine."
  echo "  Stage 1 (legacy code scan) and Post-Stage-5 (target code scan & patching)"
  echo "  use CodeMender when installed. Please install 'cm' on this machine:"
  echo "    Guide : https://docs.cloud.google.com/gemini-enterprise-agent-platform/codemender/set-up-environment"
  echo "    Binary: ~/.codemender/cm (chmod +x) or export CM_BIN=/path/to/cm"
  echo "------------------------------------------------------------------------------"
fi

echo "=============================================================================="
echo " Installation Complete!"
echo " - Plugin Path  : ${PLUGIN_DEST}"
echo " - ALM Env File : ${ENV_FILE}"
if [[ -n "${PROJECT_ROOT}" ]]; then
  echo " - Project Root : ${PROJECT_ROOT}"
  echo " Next Step: Place your legacy files or BRD in ${PROJECT_ROOT}/resources/inputs/"
  echo "            then start with Stage 0 (skill 00-setup-and-connection) to connect ALM and initialise the gate ledger."
fi
echo "=============================================================================="
