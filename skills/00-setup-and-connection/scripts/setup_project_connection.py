#!/usr/bin/env python3
"""Stage 0 — Project Setup, ALM/SCM Connection Verifier & ADO/Jira Project Selector (`00-setup-and-connection`).

Connects to Azure DevOps (ADO) or Atlassian Jira, lists available Projects and Git Repositories so the agent
can **ask the user which ADO/Jira project and input repository they want to start working on**, writes
`specs/project_setup.json`, and initializes `specs/gate_approvals.json` (`gate_0_setup = AWAITING_HUMAN_REVIEW`)
so Stage 1 (`01-discovery-and-grouping`) CANNOT auto-start without explicit human confirmation.

Actions:
  check-env         Inspect configured env / .env files (secrets masked) and initialize Gate 0 lock
  list-ado-projects Verify ADO connection and list all Projects in `ADO_ORG_URL`
  list-ado-repos    List all Git Repositories inside `--ado-project` (or `ADO_PROJECT`)
  list-jira-projects Verify Jira connection and list accessible Jira Projects
  save-setup        Save the user-selected input source & ALM project to `specs/project_setup.json` and pause at Gate 0

Usage:
  python3 setup_project_connection.py --project-root <PROJECT_ROOT> --action list-ado-projects [--ado-org-url https://dev.azure.com/<org>]
  python3 setup_project_connection.py --project-root <PROJECT_ROOT> --action list-ado-repos --ado-project "<PROJECT>"
  python3 setup_project_connection.py --project-root <PROJECT_ROOT> --action save-setup \
      --input-kind ado --ado-project "<PROJECT>" --repo-name "<REPO>" [--branch main] --alm-platform ado
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import dlc_common as dlc  # noqa: E402


def load_env_files(project_root: Path | None = None) -> list[str]:
    """Populate os.environ from `<PROJECT_ROOT>/.env` and `~/.gemini/config/agentic-dlc.env` only (never the current
    working directory — a stray `.env` in an unrelated folder must not inject credentials). Real environment
    variables are never overridden."""
    loaded: list[str] = []
    candidates = [Path.home() / ".gemini" / "config" / "agentic-dlc.env"]
    if project_root:
        candidates.insert(0, project_root / ".env")
    for env_path in candidates:
        if not env_path.is_file():
            continue
        loaded.append(str(env_path))
        for raw_line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    return loaded


def _ado_get_json(url: str, pat: str) -> dict[str, Any]:
    token_b64 = base64.b64encode(f":{pat}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Basic {token_b64}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        raise dlc.GateFailure(
            f"Azure DevOps API HTTP {exc.code} on {url}. Verify ADO_ORG_URL and ADO_PAT scopes (Project Read, Code Read, Work Items Read & Write). Details: {body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise dlc.GateFailure(f"Could not reach Azure DevOps ({url}): {exc}") from exc


def _jira_get_json(url: str, email: str, token: str) -> Any:
    token_b64 = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Basic {token_b64}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        raise dlc.GateFailure(
            f"Jira API HTTP {exc.code} on {url}. Verify JIRA_URL, JIRA_EMAIL, and JIRA_API_TOKEN. Details: {body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise dlc.GateFailure(f"Could not reach Jira ({url}): {exc}") from exc


def verify_alm_connection(alm: str, ado_org: str, ado_pat: str, jira_url: str, jira_email: str, jira_token: str) -> bool:
    """`connectionVerified` is true ONLY after a successful authenticated REST call to the ALM platform —
    never because a token happens to be present in the environment."""
    try:
        if alm == "ado":
            if not (ado_org and ado_pat):
                return False
            _ado_get_json(f"{ado_org}/_apis/projects?api-version=7.1&$top=1", ado_pat)
            return True
        if alm == "jira":
            if not (jira_url and jira_email and jira_token):
                return False
            me = _jira_get_json(f"{jira_url}/rest/api/3/myself", jira_email, jira_token)
            return isinstance(me, dict) and bool(me.get("accountId") or me.get("emailAddress") or me.get("displayName"))
    except SystemExit as exc:  # dlc.GateFailure — connection problems are reported, not fatal, at save time
        dlc.warn(f"ALM connection could not be verified: {str(exc)[:300]}")
    return False


def _write_setup(root: Path, payload: dict[str, Any]) -> Path:
    out = root / "specs" / "project_setup.json"
    errs = dlc.validate_against_schema(payload, dlc.load_schema("project_setup.schema.json"))
    if errs:
        raise dlc.GateFailure("project_setup.json violated schemas/project_setup.schema.json:\n  " + "\n  ".join(errs))
    dlc.write_json(out, payload)
    return out


def upsert_env_vars(env_file: Path, updates: dict[str, str]) -> None:
    """Update non-empty key=value entries in `env_file` while preserving comments and existing keys."""
    env_file.parent.mkdir(parents=True, exist_ok=True)
    lines = env_file.read_text(encoding="utf-8", errors="replace").splitlines() if env_file.exists() else []
    remaining = {k: v for k, v in updates.items() if v is not None and str(v).strip() != ""}
    out_lines: list[str] = []
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k = s.split("=", 1)[0].strip()
            if k in remaining:
                val = remaining.pop(k)
                out_lines.append(f'{k}="{val}"' if " " in val else f"{k}={val}")
                continue
        out_lines.append(line)
    for k, val in remaining.items():
        out_lines.append(f'{k}="{val}"' if " " in val else f"{k}={val}")
    env_file.write_text("\n".join(out_lines).rstrip() + "\n", encoding="utf-8")
    try:
        os.chmod(env_file, 0o600)  # the file may later hold ADO_PAT / JIRA_API_TOKEN — owner-only from the start
    except OSError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument("--bind-project-root", action="store_true", help="Persist --project-root to ~/.gemini/config/project_root.txt")
    ap.add_argument(
        "--action",
        required=True,
        choices=["check-env", "list-ado-projects", "list-ado-repos", "list-jira-projects", "save-setup"],
    )
    ap.add_argument("--ado-org-url", default=None, help="Azure DevOps Organization URL (https://dev.azure.com/<org>)")
    ap.add_argument("--ado-project", default=None, help="Azure DevOps Project name")
    ap.add_argument("--jira-url", default=None, help="Jira Cloud base URL")
    ap.add_argument("--jira-project-key", default=None, help="Jira Project Key")
    ap.add_argument("--input-kind", default="tbd", choices=["ado", "git", "local-dir", "resources-inputs", "tbd"])
    ap.add_argument("--repo-name", default=None, help="Repository name (for ADO or Git)")
    ap.add_argument("--repo-url", default=None, help="Repository clone URL (for ADO or Git)")
    ap.add_argument("--branch", default=None, help="Optional Git branch")
    ap.add_argument("--local-path", default=None, help="Local input folder path (for local-dir or resources-inputs)")
    ap.add_argument("--alm-platform", default="tbd", choices=["ado", "jira", "none", "tbd"])
    ap.add_argument("--ceremony-track", default="standard", choices=["quick", "standard", "regulated"],
                    help="Adaptive ceremony track: quick (prototype/internal tool), standard (default), or regulated (full compliance + mandatory Red-Team scorecard)")
    ap.add_argument("--domain-packs", nargs="*", default=[],
                    help=f"Optional pluggable MCP modernization domain packs to activate (comma or space separated from: {', '.join(dlc.VALID_DOMAIN_PACKS)})")
    ap.add_argument("--active-wave", default=None, help="Optional Strangler capability wave ID (e.g. GRP-01)")
    ap.add_argument("--persist-env", action="store_true", help="Persist non-secret org/project settings into <PROJECT_ROOT>/.env")
    ap.add_argument("--notes", default="")
    args = ap.parse_args()

    if args.project_root:
        root_candidate = Path(args.project_root).expanduser()
        if not dlc.is_installer_dir(root_candidate):
            root_candidate.mkdir(parents=True, exist_ok=True)
    root = dlc.resolve_project_root(args.project_root)
    if args.bind_project_root:
        pr_cfg = Path.home() / ".gemini" / "config" / "project_root.txt"
        pr_cfg.parent.mkdir(parents=True, exist_ok=True)
        pr_cfg.write_text(str(root) + "\n", encoding="utf-8")
        dlc.info(f"bound ~/.gemini/config/project_root.txt -> {root}")

    for folder in ["resources/inputs", "resources/design_references", "resources/policies_and_statutes",
                   "resources/shared_services", "specs"]:
        (root / folder).mkdir(parents=True, exist_ok=True)

    loaded_envs = load_env_files(root)
    ado_org = (args.ado_org_url or os.environ.get("ADO_ORG_URL") or "").strip().rstrip("/")
    ado_proj = (args.ado_project or os.environ.get("ADO_PROJECT") or "").strip()
    ado_pat = (os.environ.get("ADO_PAT") or "").strip()  # env / .env only — never a CLI flag (argv is visible in `ps`)
    jira_url = (args.jira_url or os.environ.get("JIRA_URL") or "").strip().rstrip("/")
    jira_email = (os.environ.get("JIRA_EMAIL") or "").strip()
    jira_token = (os.environ.get("JIRA_API_TOKEN") or "").strip()
    jira_key = (args.jira_project_key or os.environ.get("JIRA_PROJECT_KEY") or "").strip()

    if args.action == "check-env":
        dlc.mark_gate_awaiting_human(
            root,
            "gate_0_setup",
            summary="Stage 0 connection check executed; awaiting user selection of project / input source and Gate 0 approval.",
        )
        status = {
            "projectRoot": str(root),
            "loadedEnvFiles": loaded_envs,
            "ado": {
                "ADO_ORG_URL": ado_org or None,
                "ADO_PROJECT": ado_proj or None,
                "ADO_PAT_present": bool(ado_pat),
            },
            "jira": {
                "JIRA_URL": jira_url or None,
                "JIRA_EMAIL_present": bool(jira_email),
                "JIRA_API_TOKEN_present": bool(jira_token),
                "JIRA_PROJECT_KEY": jira_key or None,
            },
            "git": {
                "GIT_TOKEN_present": bool(os.environ.get("GIT_TOKEN") or os.environ.get("GITHUB_TOKEN")),
            },
            "modernizationTools": {
                "codmod_cli_present": bool(shutil.which("codmod")),
                "supportedDomainPacks": list(dlc.VALID_DOMAIN_PACKS),
            },
        }
        print(json.dumps(status, indent=2))
        return 0

    if args.action == "list-ado-projects":
        if not ado_org or not ado_pat:
            raise dlc.GateFailure(
                "ADO_ORG_URL and ADO_PAT are required to list Azure DevOps projects.\n"
                "  Ask the user for their Azure DevOps Organization URL (https://dev.azure.com/<org>) and configure ADO_PAT in <PROJECT_ROOT>/.env or ~/.gemini/config/agentic-dlc.env."
            )
        if args.persist_env:
            upsert_env_vars(root / ".env", {"ADO_ORG_URL": ado_org})
        data = _ado_get_json(f"{ado_org}/_apis/projects?api-version=7.1", ado_pat)
        projects = [
            {
                "name": p.get("name"),
                "id": p.get("id"),
                "state": p.get("state"),
                "description": (p.get("description") or "")[:120],
            }
            for p in (data.get("value") or [])
        ]
        setup_payload = {
            "schemaVersion": dlc.SCHEMA_VERSION,
            "updatedAtUtc": dlc.utc_now_iso(False),
            "setupStatus": "AWAITING_PROJECT_SELECTION",
            "inputSource": {
                "kind": "ado",
                "adoOrgUrl": ado_org,
                "adoProject": None,
                "repositoryName": None,
                "repositoryUrl": None,
                "branch": None,
                "localPath": None,
            },
            "almPlatform": "ado",
            "almConfig": {
                "adoOrgUrl": ado_org,
                "adoProject": None,
                "jiraUrl": None,
                "jiraProjectKey": None,
                "connectionVerified": True,
            },
            "notes": f"Connected to {ado_org}; found {len(projects)} project(s). Waiting for user to select which ADO Project to work on.",
        }
        _write_setup(root, setup_payload)
        dlc.mark_gate_awaiting_human(
            root,
            "gate_0_setup",
            summary=f"Connected to {ado_org} ({len(projects)} ADO projects found). Ask the user which ADO Project they want to start working on and STOP.",
            force_reset=True,
        )
        print(json.dumps({"adoOrgUrl": ado_org, "projectCount": len(projects), "projects": projects}, indent=2))
        return 0

    if args.action == "list-ado-repos":
        if not ado_org or not ado_pat or not ado_proj:
            raise dlc.GateFailure(
                "ADO_ORG_URL, ADO_PROJECT (--ado-project), and ADO_PAT are required to list repositories in an Azure DevOps project."
            )
        if args.persist_env:
            upsert_env_vars(root / ".env", {"ADO_ORG_URL": ado_org, "ADO_PROJECT": ado_proj})
        data = _ado_get_json(
            f"{ado_org}/{urllib.parse.quote(ado_proj)}/_apis/git/repositories?api-version=7.1",
            ado_pat,
        )
        repos = [
            {
                "name": r.get("name"),
                "defaultBranch": str(r.get("defaultBranch") or "").replace("refs/heads/", "") or None,
                "remoteUrl": r.get("remoteUrl"),
                "size": r.get("size"),
            }
            for r in (data.get("value") or [])
        ]
        dlc.mark_gate_awaiting_human(
            root,
            "gate_0_setup",
            summary=f"Listed {len(repos)} repository(ies) in ADO project '{ado_proj}'. Confirm repository selection and Gate 0 approval with the user before starting Stage 1.",
            force_reset=True,
        )
        print(json.dumps({"adoOrgUrl": ado_org, "adoProject": ado_proj, "repositoryCount": len(repos), "repositories": repos}, indent=2))
        return 0

    if args.action == "list-jira-projects":
        if not jira_url or not jira_email or not jira_token:
            raise dlc.GateFailure("JIRA_URL, JIRA_EMAIL, and JIRA_API_TOKEN are required to list Jira projects.")
        data = _jira_get_json(f"{jira_url}/rest/api/3/project/search?maxResults=100", jira_email, jira_token)
        values = data.get("values") if isinstance(data, dict) else []
        projects = [{"key": p.get("key"), "name": p.get("name")} for p in (values or [])]
        dlc.mark_gate_awaiting_human(
            root,
            "gate_0_setup",
            summary=f"Connected to {jira_url} ({len(projects)} Jira projects found). Ask the user which Jira project & input source to use and STOP.",
            force_reset=True,
        )
        print(json.dumps({"jiraUrl": jira_url, "projectCount": len(projects), "projects": projects}, indent=2))
        return 0

    if args.action == "save-setup":
        if args.input_kind == "ado" and not ado_proj:
            raise dlc.GateFailure(
                "Cannot save ADO setup without --ado-project (or ADO_PROJECT). Ask the user which Azure DevOps Project they want to work on first!"
            )
        repo_url = args.repo_url
        if args.input_kind == "ado" and not repo_url and ado_org and ado_proj and args.repo_name:
            repo_url = f"{ado_org}/{urllib.parse.quote(ado_proj)}/_git/{urllib.parse.quote(args.repo_name)}"
        alm = args.alm_platform
        if alm == "tbd":
            alm = "ado" if (args.input_kind == "ado" or ado_org) else ("jira" if jira_url else "none")
        if args.persist_env:
            env_updates: dict[str, str] = {}
            if ado_org:
                env_updates["ADO_ORG_URL"] = ado_org
            if ado_proj:
                env_updates["ADO_PROJECT"] = ado_proj
            if jira_url:
                env_updates["JIRA_URL"] = jira_url
            if jira_key:
                env_updates["JIRA_PROJECT_KEY"] = jira_key
            if env_updates:
                upsert_env_vars(root / ".env", env_updates)

        raw_packs: list[str] = []
        for tok in (args.domain_packs or []):
            for sub in str(tok).split(","):
                s = sub.strip()
                if s:
                    raw_packs.append(s)
        invalid_packs = [p for p in raw_packs if p not in dlc.VALID_DOMAIN_PACKS]
        if invalid_packs:
            raise dlc.GateFailure(
                f"Unsupported --domain-packs value(s): {invalid_packs}. Allowed: {list(dlc.VALID_DOMAIN_PACKS)}"
            )

        setup_payload = {
            "schemaVersion": dlc.SCHEMA_VERSION,
            "updatedAtUtc": dlc.utc_now_iso(False),
            "setupStatus": "AWAITING_HUMAN_REVIEW",
            "ceremonyTrack": args.ceremony_track,
            "domainPacks": list(dict.fromkeys(raw_packs)),
            "activeWave": args.active_wave,
            "inputSource": {
                "kind": args.input_kind,
                "adoOrgUrl": ado_org or None,
                "adoProject": ado_proj or None,
                "repositoryName": args.repo_name,
                "repositoryUrl": repo_url,
                "branch": args.branch,
                "localPath": args.local_path or ("resources/inputs" if args.input_kind == "resources-inputs" else None),
            },
            "almPlatform": alm,
            "almConfig": {
                "adoOrgUrl": ado_org or None,
                "adoProject": ado_proj or None,
                "jiraUrl": jira_url or None,
                "jiraProjectKey": jira_key or None,
                "connectionVerified": verify_alm_connection(alm, ado_org, ado_pat, jira_url, jira_email, jira_token),
            },
            "notes": args.notes,
        }
        out = _write_setup(root, setup_payload)
        dlc.info(f"wrote {out}")
        if args.ceremony_track != "standard" or dlc.gate_approvals_path(root).is_file():
            ga_data = dlc.load_gate_approvals(root)
            if not ga_data.get("gates"):
                ga_data = dlc.new_gate_ledger(autonomous=False, ceremony_track=args.ceremony_track)
            else:
                ga_data["ceremonyTrack"] = args.ceremony_track
            dlc.write_json(dlc.gate_approvals_path(root), ga_data)
        dlc.mark_gate_awaiting_human(
            root,
            "gate_0_setup",
            summary=(
                f"Stage 0 setup saved (inputSource={args.input_kind}, adoProject={ado_proj or 'N/A'}, "
                f"repo={args.repo_name or repo_url or args.local_path or 'resources/inputs'}, alm={alm}). "
                f"Ask the user for Gate 0 confirmation before running Stage 1!"
            ),
            force_reset=True,
        )
        print(json.dumps(setup_payload, indent=2))
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
