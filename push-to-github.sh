#!/usr/bin/env bash
# Developer-only helper: pushes this repository to GitHub.
# Not part of the installed plugin (bootstrap.sh / bootstrap.ps1 exclude it from the install copy).
#
# Usage:
#   GITHUB_OWNER=<owner> GITHUB_REPO=<repo> ./push-to-github.sh [branch]
# Both environment variables are REQUIRED (no default owner or repository is built in); branch defaults to main.
# New repositories are always created PRIVATE; make them public deliberately afterwards with
#   gh repo edit <owner>/<repo> --visibility public
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${REPO_DIR}"

if [[ -z "${GITHUB_OWNER:-}" || -z "${GITHUB_REPO:-}" ]]; then
  echo "ERROR: GITHUB_OWNER and GITHUB_REPO must be set, e.g." >&2
  echo "  GITHUB_OWNER=<owner> GITHUB_REPO=<repo> ./push-to-github.sh [branch]" >&2
  exit 2
fi
if [[ ! "${GITHUB_OWNER}" =~ ^[A-Za-z0-9][A-Za-z0-9-]*$ || ! "${GITHUB_REPO}" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "ERROR: GITHUB_OWNER / GITHUB_REPO contain unexpected characters." >&2
  exit 2
fi

BRANCH="${1:-main}"
SLUG="${GITHUB_OWNER}/${GITHUB_REPO}"
REMOTE_URL="https://github.com/${SLUG}.git"

if command -v gh >/dev/null 2>&1; then
  if gh repo view "${SLUG}" >/dev/null 2>&1; then
    echo "Pushing ${BRANCH} to existing repository ${SLUG} via GitHub CLI..."
    if ! git remote get-url origin >/dev/null 2>&1; then
      git remote add origin "${REMOTE_URL}"
    fi
    git push -u origin "${BRANCH}"
  else
    echo "Creating PRIVATE repository ${SLUG} and pushing ${BRANCH}..."
    gh repo create "${SLUG}" --private --source=. --remote=origin --push
  fi
else
  echo "GitHub CLI not found — pushing ${BRANCH} to origin (${REMOTE_URL})..."
  if ! git remote get-url origin >/dev/null 2>&1; then
    git remote add origin "${REMOTE_URL}"
  fi
  git push -u origin "${BRANCH}"
fi
