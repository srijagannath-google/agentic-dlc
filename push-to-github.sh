#!/usr/bin/env bash
# Pushes the agentic-dlc repository to GitHub
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${REPO_DIR}"

REPO_SLUG="${GITHUB_REPO_SLUG:-agentic-dlc}"

if command -v gh >/dev/null 2>&1; then
  echo "Creating/pushing ${REPO_SLUG} via GitHub CLI (gh)..."
  if gh repo view "${REPO_SLUG}" >/dev/null 2>&1; then
    git push -u origin main
  else
    gh repo create "${REPO_SLUG}" --public --source=. --remote=origin --push || \
      gh repo create "${REPO_SLUG}" --private --source=. --remote=origin --push
  fi
else
  echo "Pushing to origin..."
  git push -u origin main
fi
