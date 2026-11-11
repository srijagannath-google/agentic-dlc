#!/usr/bin/env python3
"""Stage 1 — deterministic input scanner & repository ingestor (01-discovery-and-grouping).

Optionally ingests legacy source code or requirements documents from an **Azure DevOps (ADO) Git repository**
(`--ado-repo <repo-url-or-name> [--ado-branch <branch>]`) or any **Git repository** (`--git-repo <git-url>
[--git-branch <branch>]`) into `<PROJECT_ROOT>/resources/inputs/<repo-slug>/`, then scans the project's
`resources/` estate (plus any `--input-dir` paths), categorises every file with generic heuristics, decides the
input scenario by **majority-by-weight** (never by a single file), fingerprints everything with SHA-256 and
writes `specs/input_inventory.json` (contract: docs/ARCHITECTURE.md §4.1, schemas/input_inventory.schema.json).

It only ingests, scans and classifies — it never writes a discovery document, spec or template.

Usage:
    python3 scan_input_sources.py --project-root <PROJECT_ROOT>
                                  [--input-dir resources/inputs ...]
                                  [--ado-repo <repo-url-or-name>] [--ado-branch <branch>]
                                  [--ado-org-url https://dev.azure.com/<org>] [--ado-project <project>]
                                  [--git-repo <git-url>] [--git-branch <branch>]
                                  [--domain-slug my-app] [--output specs/input_inventory.json] [--deterministic]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import dlc_common as dlc  # noqa: E402
import dlc_security_runner  # noqa: E402

# --------------------------------------------------------------------------------------------------
# Heuristics (generic — no domain literals)
# --------------------------------------------------------------------------------------------------
SCHEMA_EXT = {".xsd", ".ddl", ".dbml", ".prisma", ".dbschema", ".dacpac", ".edmx", ".dcl", ".dclgen"}
# Binary database containers / backups / data exports are strong legacy-estate evidence even though their
# content cannot be read as text (weight comes from the legacy_schema category).
DB_CONTAINER_EXT = {".accdb", ".mdb", ".dbf", ".bak", ".sqlite", ".sqlite3", ".db"}
DATA_EXPORT_EXT = {".csv", ".xlsx", ".xls"}
SOURCE_EXT = {
    ".vb", ".bas", ".cls", ".frm", ".cs", ".cshtml", ".vbhtml", ".razor", ".java", ".cbl", ".cob", ".cpy",
    ".jcl", ".prc", ".proc", ".bms", ".pli", ".pl1", ".asm", ".hlasm", ".mac", ".rexx", ".rex", ".rpg",
    ".rpgle", ".dspf", ".py", ".js", ".jsx", ".ts", ".tsx", ".php", ".rb", ".go", ".pl", ".asp", ".aspx",
    ".ascx", ".master", ".asax", ".ashx", ".asmx", ".svc", ".sln", ".slnx", ".csproj", ".vbproj", ".fsproj",
    ".props", ".targets", ".xaml", ".gradle", ".kts", ".jsp", ".vbs", ".c", ".cpp", ".h", ".kt", ".swift",
    ".rs", ".scala",
}
PROJECT_CONFIG_NAMES = {
    "web.config", "app.config", "packages.config", "nuget.config", "global.json", "bundleconfig.json",
    "applicationhost.config", "pom.xml", "web.xml", "struts.xml", "jboss-web.xml", "application.properties",
    "application.yml", "application.yaml",
}
APPSETTINGS_RE = re.compile(r"^appsettings(?:\.[a-z0-9_.-]+)?\.json$", re.IGNORECASE)
GENERIC_SOURCE_STEM_STOPWORDS = frozenset({
    "program", "startup", "appsettings", "packages", "web", "app", "global", "pom", "build", "index",
    "main", "server", "config", "nuget", "bundleconfig", "directory.build", "directory.packages", "application",
})
DOC_EXT = {".md", ".docx", ".pdf", ".txt", ".rtf", ".html", ".htm"}
NARRATIVE_DOC_EXT = {".md", ".docx", ".pdf"}  # may be promoted to requirements_doc when the only/largest document
GENERATED_REFERENCE_NAMES = {"reference_ui_manifest.json"}  # written by capture_design_reference.py, never user input
FORM_PREFIXES = ("form_", "frm", "screen_", "screen-", "dialog_", "dlg", "ui_", "page_")
REPORT_PREFIXES = ("report_", "rpt", "rep_", "print_")
QUERY_PREFIXES = ("qry", "query_", "view_", "vw_", "sp_", "proc_")
TABLE_PREFIXES = ("tbl", "table_", "tb_", "dbo_")
REQ_KEYWORDS = re.compile(
    r"\b(brd|prd|rfp|rfi|srs|requirements?|specification|spec|user guide|functional design|business rules?|use cases?|scope)\b",
    re.IGNORECASE,
)
POLICY_KEYWORDS = re.compile(
    r"\b(policy|policies|regulation|regulations|ordinance|legislation|compliance|act of|code of|rule(?:s)? of)\b",
    re.IGNORECASE,
)
DESIGN_KEYWORDS = re.compile(
    r"(figma|stitch|wireframe|mockup|mock-up|style[ _-]?guide|design[ _-]?system|design[ _-]?tokens?|theme|ui[ _-]?sample|prototype)",
    re.IGNORECASE,
)
LEGACY_TEXT_MARKERS = re.compile(
    r"^\s*(Begin Form|Begin Report|Version =\d|Option Compare Database|Attribute VB_Name|IDENTIFICATION DIVISION|//[A-Z0-9]+\s+JOB\s)",
    re.IGNORECASE | re.MULTILINE,
)
DDL_RE = re.compile(
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMP(?:ORARY)?\s+)?(?:TABLE|VIEW|INDEX|PROCEDURE|FUNCTION|TRIGGER)\b",
    re.IGNORECASE,
)
DML_RE = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|PARAMETERS|TRANSFORM)\b", re.IGNORECASE)

IGNORED_DIRS = {
    ".git", ".hg", ".svn", ".vs", ".vscode", ".idea", "node_modules", "bin", "obj", "packages", "dist", "build",
    "target", "out", "__pycache__", ".pytest_cache", ".mypy_cache", ".venv", "venv", "env", "vendor", "coverage",
    "testresults", ".next", ".nuxt", ".gradle",
}
IGNORED_FILES = {"readme.md", ".gitkeep", ".ds_store", ".gitignore", ".gitattributes", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"}
IGNORED_EXT = {".dll", ".exe", ".pdb", ".cache", ".suo", ".user", ".class", ".jar", ".war", ".nupkg", ".pyc", ".pyo", ".so", ".dylib", ".o", ".a"}

WEIGHTS = {
    "legacy_schema": 3, "legacy_source": 3, "legacy_query": 2, "legacy_form": 2, "legacy_report": 2,
    "requirements_doc": 3, "policy": 0, "design_reference": 0, "shared_service": 0, "other": 0,
}
LEGACY_CATEGORIES = {"legacy_schema", "legacy_query", "legacy_form", "legacy_report", "legacy_source"}
DECISION_RULE = (
    "majority-by-weight over categorised files under resources/inputs "
    "(schema/source/db-container/data-export=3, query/form/report=2, requirements_doc=3); "
    "narrative .md/.docx/.pdf files count as requirements_doc only when they carry requirement keywords "
    "or are the only/largest document; LOW confidence when zero files, "
    "margin < 3 or margin/total < 0.2 -> Gate 1 must ask the user to confirm the scenario"
)

ADO_URL_RE = re.compile(
    r"^https?://(?:[^@/]+@)?(?:"
    r"dev\.azure\.com/(?P<org1>[^/]+)/(?P<proj1>[^/]+)/_git/(?P<repo1>[^/?#]+)"
    r"|(?P<org2>[^.]+)\.visualstudio\.com/(?:DefaultCollection/)?(?P<proj2>[^/]+)/_git/(?P<repo2>[^/?#]+)"
    r")/?$",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------------------------------
# Environment & Repository Ingestion (Azure DevOps / Git)
# --------------------------------------------------------------------------------------------------
def load_env_files(project_root: Path | None = None) -> None:
    """Populate os.environ from dotenv-style files without overriding real environment variables.

    Only `<PROJECT_ROOT>/.env` and `~/.gemini/config/agentic-dlc.env` are read — never the current working
    directory (a stray `.env` in an unrelated folder must not inject credentials)."""
    candidates = [Path.home() / ".gemini" / "config" / "agentic-dlc.env"]
    if project_root:
        candidates.insert(0, project_root / ".env")
    for env_path in candidates:
        if not env_path.is_file():
            continue
        for raw_line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


def resolve_ado_repo_coordinates(
    ado_repo_arg: str,
    org_url_arg: str | None,
    project_arg: str | None,
) -> tuple[str, str, str, str]:
    """Resolve (org_url, project, repo_name, clone_url) from --ado-repo + env/flags."""
    raw = ado_repo_arg.strip()
    m = ADO_URL_RE.match(raw)
    if m:
        if m.group("org1"):
            org = urllib.parse.unquote(m.group("org1"))
            proj = urllib.parse.unquote(m.group("proj1"))
            repo = urllib.parse.unquote(m.group("repo1"))
            if repo.endswith(".git"):
                repo = repo[:-4]
            org_url = f"https://dev.azure.com/{org}"
        else:
            org = urllib.parse.unquote(m.group("org2"))
            proj = urllib.parse.unquote(m.group("proj2"))
            repo = urllib.parse.unquote(m.group("repo2"))
            if repo.endswith(".git"):
                repo = repo[:-4]
            org_url = f"https://{org}.visualstudio.com"
        clone_url = (
            f"{org_url}/{urllib.parse.quote(proj)}/_git/{urllib.parse.quote(repo)}"
        )
        return org_url, proj, repo, clone_url

    if raw.startswith(("http://", "https://", "git@", "ssh://")):
        repo_name = Path(urllib.parse.urlparse(raw).path).stem or "ado-repo"
        org_url = (org_url_arg or os.environ.get("ADO_ORG_URL") or "").rstrip("/")
        proj = (project_arg or os.environ.get("ADO_PROJECT") or "").strip()
        return org_url, proj, repo_name, raw

    # Bare repository name: build from ADO_ORG_URL and ADO_PROJECT
    org_url = (org_url_arg or os.environ.get("ADO_ORG_URL") or "").strip().rstrip("/")
    proj = (project_arg or os.environ.get("ADO_PROJECT") or "").strip()
    if not org_url or not proj:
        raise dlc.GateFailure(
            f"--ado-repo '{raw}' is a repository name rather than a full URL, so ADO_ORG_URL and ADO_PROJECT "
            "must be set (via --ado-org-url / --ado-project, <PROJECT_ROOT>/.env, or ~/.gemini/config/agentic-dlc.env)."
        )
    repo = raw[:-4] if raw.endswith(".git") else raw
    clone_url = f"{org_url}/{urllib.parse.quote(proj)}/_git/{urllib.parse.quote(repo)}"
    return org_url, proj, repo, clone_url


def _fetch_ado_items_via_rest(
    org_url: str,
    project: str,
    repo_name: str,
    pat: str,
    branch: str | None,
    dest_dir: Path,
) -> str | None:
    """Fallback when `git` is unavailable: download files via Azure DevOps Git Items REST API v7.1."""
    if not org_url or not project:
        raise dlc.GateFailure("Cannot use Azure DevOps REST fallback without ADO_ORG_URL and ADO_PROJECT.")
    token_b64 = base64.b64encode(f":{pat}".encode("utf-8")).decode("ascii")
    headers = {"Authorization": f"Basic {token_b64}", "Accept": "application/json"}
    q: dict[str, str] = {
        "recursionLevel": "Full",
        "includeContentMetadata": "true",
        "api-version": "7.1",
    }
    if branch:
        q["versionDescriptor.version"] = branch
        q["versionDescriptor.versionType"] = "branch"
    items_url = (
        f"{org_url.rstrip('/')}/{urllib.parse.quote(project)}/_apis/git/repositories/"
        f"{urllib.parse.quote(repo_name)}/items?{urllib.parse.urlencode(q)}"
    )
    req = urllib.request.Request(items_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        raise dlc.GateFailure(
            f"Azure DevOps Git Items REST API failed (HTTP {exc.code}) for {items_url}. "
            "Check ADO_ORG_URL, ADO_PROJECT, repository name, and ADO_PAT (Code Read scope)."
        ) from exc

    items = payload.get("value") or []
    commit_sha: str | None = None
    downloaded = 0
    for item in items:
        if item.get("isFolder") or item.get("gitObjectType") == "tree":
            continue
        rel_path = str(item.get("path") or "").lstrip("/")
        if not rel_path:
            continue
        parts_lower = [p.lower() for p in Path(rel_path).parts]
        if any(p in IGNORED_DIRS for p in parts_lower):
            continue
        if Path(rel_path).suffix.lower() in IGNORED_EXT:
            continue
        if not commit_sha and item.get("commitId"):
            commit_sha = str(item["commitId"])
        file_q: dict[str, str] = {"path": f"/{rel_path}", "api-version": "7.1"}
        if branch:
            file_q["versionDescriptor.version"] = branch
            file_q["versionDescriptor.versionType"] = "branch"
        raw_url = (
            f"{org_url.rstrip('/')}/{urllib.parse.quote(project)}/_apis/git/repositories/"
            f"{urllib.parse.quote(repo_name)}/items?{urllib.parse.urlencode(file_q)}"
        )
        raw_req = urllib.request.Request(raw_url, headers={"Authorization": f"Basic {token_b64}"})
        with urllib.request.urlopen(raw_req, timeout=60) as f_resp:
            content = f_resp.read()
        target_file = dest_dir / rel_path
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_bytes(content)
        downloaded += 1

    dlc.info(f"downloaded {downloaded} files from Azure DevOps REST API into {dest_dir}")
    return commit_sha


def _redact_secrets(text: str, *secrets: str | None) -> str:
    """Mask Authorization headers, Basic/Bearer tokens and any literal secret value in diagnostic text."""
    out = str(text or "")
    out = re.sub(r"Authorization:\s*(Basic|Bearer)\s+[A-Za-z0-9+/=._-]+", r"Authorization: \1 ***", out, flags=re.IGNORECASE)
    out = re.sub(r"(https?://)[^/\s@]+@", r"\1***@", out)  # user:token@host in clone URLs
    for sec in secrets:
        if sec and len(sec) >= 4:
            out = out.replace(sec, "***")
            out = out.replace(base64.b64encode(f":{sec}".encode("utf-8")).decode("ascii"), "***")
    return out


def ingest_remote_repository(
    root: Path,
    provider: str,
    repo_url: str,
    repo_name: str,
    branch: str | None,
    pat_or_token: str | None,
    ado_org_url: str = "",
    ado_project: str = "",
) -> dict[str, Any]:
    """Clone or update an Azure DevOps (`provider='ado'`) or generic Git (`provider='git'`) repository
    into `<PROJECT_ROOT>/resources/inputs/<repo-slug>/` and return `sourceRepository` provenance metadata."""
    repo_slug = dlc.slugify(repo_name) or "source-repo"
    dest_dir = root / "resources" / "inputs" / repo_slug
    dest_dir.parent.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    if pat_or_token:
        # Basic auth `:<PAT>` works for Azure DevOps PATs as well as GitHub/GitLab personal access tokens.
        # The header is passed through git's environment config (GIT_CONFIG_COUNT/KEY/VALUE, git >= 2.31) so the
        # secret never appears in a process argv (visible in `ps`, shell history, CalledProcessError messages).
        b64 = base64.b64encode(f":{pat_or_token}".encode("utf-8")).decode("ascii")
        n = int(env.get("GIT_CONFIG_COUNT") or 0)
        env[f"GIT_CONFIG_KEY_{n}"] = "http.extraHeader"
        env[f"GIT_CONFIG_VALUE_{n}"] = f"Authorization: Basic {b64}"
        env["GIT_CONFIG_COUNT"] = str(n + 1)

    commit_sha: str | None = None
    resolved_branch = branch
    git_succeeded = False

    safe_url = _redact_secrets(repo_url, pat_or_token)
    try:
        if (dest_dir / ".git").is_dir():
            dlc.info(f"updating existing {provider.upper()} checkout at {dest_dir} from {safe_url}")
            fetch_cmd = ["git", "-C", str(dest_dir), "fetch", "--depth", "1", "origin"]
            if branch:
                fetch_cmd.append(branch)
            subprocess.run(fetch_cmd, check=True, capture_output=True, text=True, env=env, timeout=120)
            subprocess.run(
                ["git", "-C", str(dest_dir), "reset", "--hard", "FETCH_HEAD"],
                check=True, capture_output=True, text=True, env=env, timeout=60,
            )
            git_succeeded = True
        else:
            dlc.info(f"cloning {provider.upper()} repository {safe_url} -> {dest_dir}")
            clone_cmd = ["git", "clone", "--depth", "1"]
            if branch:
                clone_cmd += ["--branch", branch]
            clone_cmd += [repo_url, str(dest_dir)]
            subprocess.run(clone_cmd, check=True, capture_output=True, text=True, env=env, timeout=180)
            git_succeeded = True

        if git_succeeded:
            sha_proc = subprocess.run(
                ["git", "-C", str(dest_dir), "rev-parse", "HEAD"],
                check=False, capture_output=True, text=True, env=env, timeout=15,
            )
            if sha_proc.returncode == 0:
                commit_sha = sha_proc.stdout.strip() or None
            if not resolved_branch:
                br_proc = subprocess.run(
                    ["git", "-C", str(dest_dir), "rev-parse", "--abbrev-ref", "HEAD"],
                    check=False, capture_output=True, text=True, env=env, timeout=15,
                )
                if br_proc.returncode == 0 and br_proc.stdout.strip() not in ("", "HEAD"):
                    resolved_branch = br_proc.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        # Never echo credentials: redact on EVERY branch (the message may contain argv, env dumps or server echoes).
        err_text = _redact_secrets(getattr(exc, "stderr", "") or str(exc), pat_or_token)
        if provider == "ado" and pat_or_token and ado_org_url and ado_project:
            dlc.warn(f"git clone failed ({err_text.strip()[:300]}); falling back to Azure DevOps Git Items REST API v7.1...")
            dest_dir.mkdir(parents=True, exist_ok=True)
            commit_sha = _fetch_ado_items_via_rest(
                ado_org_url, ado_project, repo_name, pat_or_token, branch, dest_dir
            )
        else:
            raise dlc.GateFailure(
                f"Failed to ingest {provider.upper()} repository '{safe_url}': {err_text.strip()}\n"
                "Verify the repository URL, network connectivity, and authentication token "
                "(ADO_PAT for Azure DevOps or GIT_TOKEN / GITHUB_TOKEN for Git)."
            ) from exc

    rel_checkout = str(dest_dir.resolve().relative_to(root.resolve()))
    return {
        "provider": provider,
        "repositoryUrl": _redact_secrets(repo_url, pat_or_token),  # never persist embedded credentials
        "repositoryName": repo_name,
        "branch": resolved_branch,
        "commitSha": commit_sha,
        "localCheckoutPath": rel_checkout,
    }


def _pdf_head_text(path: Path, max_bytes: int) -> str:
    """First pages of a PDF via `pdftotext` when it is on PATH; otherwise no text (never binary garbage)."""
    exe = shutil.which("pdftotext")
    if not exe:
        return ""
    try:
        cp = subprocess.run([exe, "-l", "5", "-layout", str(path), "-"], capture_output=True, text=True, timeout=20, check=False)
        return (cp.stdout or "")[:max_bytes]
    except (subprocess.TimeoutExpired, OSError):
        return ""


def head_text(path: Path, max_bytes: int = 64_000) -> str:
    """Best-effort text from the start of a file (handles .docx via zipfile, .pdf via pdftotext; binary
    containers yield no text; other files decode utf-8 then latin-1)."""
    ext = path.suffix.lower()
    try:
        if ext == ".docx":
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml").decode("utf-8", errors="replace")
            xml = re.sub(r"</w:p>", "\n", xml)
            return re.sub(r"<[^>]+>", "", xml)[:max_bytes]
        if ext == ".pdf":
            return _pdf_head_text(path, max_bytes)
        if ext in DB_CONTAINER_EXT or ext in {".xlsx", ".xls"}:
            return ""
        raw = path.read_bytes()[:max_bytes]
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1", errors="replace")
    except Exception:  # unreadable / corrupt zip
        return ""


def printable_title(s: str) -> bool:
    """A usable document title: printable, mostly alphanumeric, no replacement/control characters."""
    s = s.strip()
    if len(s) < 3 or len(s) > 120:
        return False
    if any((not ch.isprintable()) or ch == "\ufffd" for ch in s):
        return False
    alnum = sum(1 for ch in s if ch.isalnum() or ch.isspace())
    return alnum / len(s) >= 0.7 and any(ch.isalpha() for ch in s)


def title_from_filename(path: Path) -> str:
    return re.sub(r"[_\-]+", " ", path.stem).strip()


def first_heading(text: str, ext: str) -> str:
    if ext == ".pdf":
        return ""  # callers fall back to the file name (pdftotext output has no reliable heading structure)
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if ext in (".md", ".markdown"):
            m = re.match(r"^#\s+(.+)$", s)
            if m:
                return dlc.strip_md(m.group(1))
            continue
        # docx / txt: first short non-empty line acts as the title
        if len(s) <= 80 and not s.startswith(("|", "-", "*", "<")):
            return dlc.strip_md(s)
        if ext not in (".txt",):
            return ""
    return ""


def categorise(path: Path, bucket: str, text: str) -> tuple[str, str]:
    """Return (category, reason). `bucket` is the resources/ sub-folder the file came from."""
    name = path.name.lower()
    stem = path.stem.lower()
    ext = path.suffix.lower()
    if bucket == "policies_and_statutes":
        return "policy", "located in resources/policies_and_statutes"
    if bucket == "design_references":
        return "design_reference", "located in resources/design_references"
    if bucket == "shared_services":
        return "shared_service", "located in resources/shared_services"
    if DESIGN_KEYWORDS.search(name) or ext in (".fig", ".sketch", ".xd"):
        return "design_reference", "design keyword in file name"
    if stem.startswith(FORM_PREFIXES) or ext in (".frm", ".bms", ".dspf"):
        return "legacy_form", "form/screen name prefix or screen-map file"
    if stem.startswith(REPORT_PREFIXES):
        return "legacy_report", "report name prefix"
    if ext in SCHEMA_EXT or stem.startswith(TABLE_PREFIXES):
        return "legacy_schema", "schema file extension or table name prefix"
    if ext in DB_CONTAINER_EXT:
        return "legacy_schema", f"legacy database container / backup file ({ext})"
    if ext in DATA_EXPORT_EXT:
        return "legacy_schema", f"tabular data export of a legacy store ({ext})"
    if ext == ".sql":
        if DDL_RE.search(text):
            return "legacy_schema", "SQL file containing DDL (CREATE …)"
        if DML_RE.search(text) or stem.startswith(QUERY_PREFIXES):
            return "legacy_query", "SQL file containing a query"
        return "legacy_query", "SQL file (no DDL detected)"
    if stem.startswith(QUERY_PREFIXES):
        return "legacy_query", "query name prefix"
    if name in PROJECT_CONFIG_NAMES or APPSETTINGS_RE.match(name):
        return "legacy_source", f"project/runtime configuration manifest ({path.name})"
    if ext in SOURCE_EXT:
        return "legacy_source", f"source-code or project manifest extension {ext}"
    if POLICY_KEYWORDS.search(name):
        return "policy", "policy/compliance keyword in file name"
    if ext in DOC_EXT or ext == "":
        if LEGACY_TEXT_MARKERS.search(text[:4000]):
            return "legacy_form", "text export of a legacy form/module (legacy markers in content)"
        head = "\n".join(text.splitlines()[:40])
        if REQ_KEYWORDS.search(name) or REQ_KEYWORDS.search(head):
            return "requirements_doc", "requirements keyword in name or first lines"
        if ext == ".pdf":
            # A PDF in resources/inputs is a narrative document by construction (title from the file name;
            # body text only when `pdftotext` is available) — never a legacy export.
            return "requirements_doc", "PDF document (title from file name)"
        if ext in NARRATIVE_DOC_EXT:
            # Not a requirements document by evidence; scan() promotes the only/largest narrative document.
            return "other", f"{ext} narrative document without requirements keywords"
        return "other", "plain document without requirements keywords"
    return "other", f"unrecognised extension {ext or '(none)'}"


def design_type(path: Path) -> str:
    n = path.name.lower()
    if "figma" in n or path.suffix.lower() == ".fig":
        return "figma"
    if "stitch" in n:
        return "stitch"
    if "token" in n:
        return "tokens"
    if re.search(r"style[ _-]?guide|design[ _-]?system|theme", n):
        return "style_guide"
    return "sample_ui"


GENERIC_XSD_XML_STOPWORDS = frozenset({
    "dataroot", "createdon", "updatedon", "modifiedon", "deletedon", "timestamp",
    "root", "row", "rows", "record", "records", "item", "items", "schema", "element",
    "complextype", "simpletype", "sequence", "attribute", "value", "id", "name",
    "type", "status", "version", "description", "notes", "comments",
})

COMMON_TECH_ACRONYMS = frozenset({
    "API", "SQL", "DDL", "DML", "XML", "XSD", "CSV", "JSON", "HTML", "CSS", "HTTP", "HTTPS",
    "REST", "GRPC", "SOAP", "UUID", "UTF", "ASCII", "PDF", "DOCX", "XLSX", "URL", "URI", "UTC",
    "GMT", "ISO", "RFC", "JWT", "OIDC", "SAML", "OAUTH", "RBAC", "ABAC", "MFA", "SSO", "TLS",
    "MTLS", "CORS", "CSRF", "XSS", "CRUD", "ORM", "CLI", "GUI", "DOM", "SPA", "SSR", "PWA",
    "WCAG", "ARIA", "SLA", "SLO", "SLI", "KPI", "OKR", "TCO", "ROI", "CAPEX", "OPEX", "PII",
    "PHI", "PCI", "HIPAA", "GDPR", "SOC", "FEDRAMP", "NIST", "OWASP", "GDC", "GCP", "AWS",
    "OCI", "KRM", "OPA", "CDC", "ACL", "ADR", "BRD", "PRD", "SRS", "RFP", "RFI", "SOW", "MVP",
    "UAT", "SIT", "E2E", "TDD", "BDD", "CI", "CD", "CICD", "SCM", "VCS", "ALM", "ADO", "IDE",
    "SDK", "CPU", "RAM", "SSD", "DNS", "TCP", "UDP", "VPC", "NAT", "WAF", "CDN", "IAM", "KMS",
    "HSM", "ETL", "ELT", "OLTP", "OLAP", "RDBMS", "NOSQL", "DBMS", "VBA", "VB6", "COBOL", "JCL",
    "CICS", "VSAM", "DB2", "IMS", "RPG", "ABAP", "PLSQL", "TSQL", "NULL", "TRUE", "FALSE",
    "TODO", "TBD", "MAX", "MIN", "AVG", "SUM", "CNT", "ASC", "DESC", "AND", "NOT", "FOR",
})


def legacy_object_names(path: Path, category: str, text: str) -> list[str]:
    """Real object names inside legacy artefacts (CREATE TABLE names, XSD elements, `Name=` object lines, Access
    prefixed object identifiers) for zero-leak lists. Filters generic XSD/XML envelope & audit column tokens
    (e.g. `dataroot`, `CreatedOn`) so Stage 4B/6 UiLeak checks never fire on ordinary domain words."""
    names: dict[str, None] = {}
    if category not in LEGACY_CATEGORIES:
        return []
    for m in re.finditer(r"CREATE\s+(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"\[]?([A-Za-z_][\w$]*)", text, re.IGNORECASE):
        tok = m.group(1)
        if tok.lower() not in GENERIC_XSD_XML_STOPWORDS:
            names.setdefault(tok, None)
    for m in re.finditer(r"<xs(?:d)?:element\s+[^>]*?name=\"([A-Za-z_][\w$]*)\"", text):
        tok = m.group(1)
        if tok.lower() not in GENERIC_XSD_XML_STOPWORDS:
            names.setdefault(tok, None)
    for m in re.finditer(r"^\s*Name\s*=\s*\"?([A-Za-z_][\w]{2,})", text, re.MULTILINE):
        tok = m.group(1)
        if tok.lower() not in GENERIC_XSD_XML_STOPWORDS:
            names.setdefault(tok, None)  # object names only; captions are human labels and stay allowed
    for m in re.finditer(r"\b((?:tbl|frm|rpt|qry|cmd|txt|cbo|lst|chk)[A-Z][A-Za-z0-9_]{2,})\b", text):
        names.setdefault(m.group(1), None)
    return sorted(names)


def extract_unverified_acronyms(texts_by_rel: dict[str, str]) -> list[str]:
    """Detect 3-6 letter uppercase domain acronyms appearing in inputs without an explicit `Phrase (ACR)` or
    `ACR: Phrase` definition in the input corpus, enforcing the Strict Acronym Provenance Rule."""
    combined = "\n".join(texts_by_rel.values())
    if not combined.strip():
        return []
    defined: set[str] = set()
    for m in re.finditer(r"\b[A-Z][A-Za-z0-9/& -]{4,60}\(\s*([A-Z]{3,6})\s*\)", combined):
        defined.add(m.group(1))
    for m in re.finditer(r"\b([A-Z]{3,6})\s*\(\s*[A-Z][A-Za-z0-9/& -]{4,60}\)", combined):
        defined.add(m.group(1))
    for m in re.finditer(r"^\s*[-*]?\s*\*\*?([A-Z]{3,6})\*\*?\s*[:—–-]\s+[A-Za-z]{3,}", combined, re.MULTILINE):
        defined.add(m.group(1))

    counts: dict[str, int] = {}
    for m in re.finditer(r"\b([A-Z]{3,6})\b", combined):
        tok = m.group(1)
        if tok in COMMON_TECH_ACRONYMS or tok in defined:
            continue
        # Ignore SQL keywords and ALL-CAPS table/column headers when they appear as common English words
        if re.search(rf"\b{re.escape(tok.capitalize())}\b", combined) or re.search(rf"\b{re.escape(tok.lower())}\b", combined):
            continue
        counts[tok] = counts.get(tok, 0) + 1
    return sorted(k for k, v in counts.items() if v >= 2)[:40]


_DOMAIN_RULE_CONST_RE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*(?:fee|rate|threshold|limit|sla|days|hours|cap|pct|percent|penalty|surcharge|discount|grace|quota|multiplier)[A-Za-z0-9_]*)\b"
    r"\s*(?:=|:=|:|\bis\b)\s*\$?\s*(\d+(?:\.\d+)?)\s*%?",
    re.IGNORECASE,
)
_UI_LAYOUT_NOISE_RE = re.compile(
    r"(?:width|height|left|top|right|bottom|font|margin|padding|border|color|tab|index|column|row|version|port|timeout_ms|pixel|twip)",
    re.IGNORECASE,
)
_EXPLICIT_CONFLICT_MARKER_RE = re.compile(
    r"(?:\[(?:CONFLICT|CONTRADICTION|AMBIGUOUS|TBD|CLARIFY)\]|(?:\bTBD\b|\bFIXME\b|\?\?\?)\s*[:—-]\s*([^\n]{5,120}))",
    re.IGNORECASE,
)


def detect_cross_artifact_ambiguities(texts_by_rel: dict[str, str]) -> list[dict[str, Any]]:
    """Detect cross-file numeric business-rule contradictions (same fee/rate/threshold/limit constant assigned
    conflicting values in different forms, queries, modules, or documents) and explicit TBD/CONFLICT markers."""
    by_ident: dict[str, dict[str, set[str]]] = {}  # lower_ident -> {value_str -> {rel_paths}}
    display_name: dict[str, str] = {}
    explicit_hits: list[dict[str, Any]] = []

    for rel, text in sorted(texts_by_rel.items()):
        if not text:
            continue
        for m in _DOMAIN_RULE_CONST_RE.finditer(text):
            raw_id, raw_val = m.group(1), m.group(2)
            if _UI_LAYOUT_NOISE_RE.search(raw_id) or len(raw_id) < 4:
                continue
            key = raw_id.lower().replace("_", "")
            display_name.setdefault(key, raw_id)
            norm_val = f"{float(raw_val):g}"
            by_ident.setdefault(key, {}).setdefault(norm_val, set()).add(rel)

        for m_exp in _EXPLICIT_CONFLICT_MARKER_RE.finditer(text):
            snippet = m_exp.group(0).strip()[:120]
            explicit_hits.append({
                "kind": "explicit-ambiguity-marker",
                "identifier": Path(rel).name,
                "summary": f"Unresolved ambiguity/conflict marker in `{rel}`: `{snippet}`",
                "files": [rel],
            })
            if len(explicit_hits) >= 10:
                break

    contradictions: list[dict[str, Any]] = []
    for key, val_map in sorted(by_ident.items()):
        if len(val_map) < 2:
            continue
        all_files = sorted({f for fs in val_map.values() for f in fs})
        if len(all_files) < 2:
            continue  # Same file having tier 1 vs tier 2 assignments is normal; cross-artifact divergence is a BA conflict!
        parts = [f"{v} (in {', '.join(sorted(fs)[:2])})" for v, fs in sorted(val_map.items())]
        ident = display_name[key]
        contradictions.append({
            "kind": "conflicting-numeric-rule",
            "identifier": ident,
            "summary": f"Conflicting values for `{ident}` across input artifacts: {' vs. '.join(parts)}",
            "files": all_files[:6],
        })

    return (contradictions + explicit_hits)[:20]


def build_dependency_dag(
    files: list[dict[str, Any]],
    texts_by_rel: dict[str, str],
    deterministic: bool,
) -> tuple[dict[str, Any], dict[str, Any], int]:
    """Build a static, deterministic Current-State Dependency DAG across schemas, queries, forms/reports, and source modules."""
    nodes: dict[str, dict[str, Any]] = {}
    known_symbols: dict[str, str] = {}  # lowercase symbol -> node id
    top_modules: set[str] = set()

    for f in files:
        cat = f["category"]
        rel = f["relativePath"]
        parts = Path(rel).parts
        # e.g. resources/inputs/<module>/... -> <module>
        if len(parts) >= 3 and parts[0] == "resources" and parts[1] == "inputs":
            top_modules.add(parts[2])
        if cat not in LEGACY_CATEGORIES:
            continue
        stem = Path(rel).stem
        nid = f"{cat}:{stem}"
        nodes[nid] = {
            "id": nid,
            "name": stem,
            "kind": cat,
            "sourcePath": rel,
        }
        known_symbols.setdefault(stem.lower(), nid)
        text = texts_by_rel.get(rel, "")
        for m in re.finditer(r"CREATE\s+(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"\[]?([A-Za-z_][\w$]*)", text, re.IGNORECASE):
            tname = m.group(1)
            tid = f"table:{tname}"
            nodes.setdefault(tid, {"id": tid, "name": tname, "kind": "table", "sourcePath": rel})
            known_symbols[tname.lower()] = tid
        for m in re.finditer(r"<xs(?:d)?:element\s+[^>]*?name=\"((?:tbl|TB)[A-Za-z0-9_]*)\"", text):
            tname = m.group(1)
            tid = f"table:{tname}"
            nodes.setdefault(tid, {"id": tid, "name": tname, "kind": "table", "sourcePath": rel})
            known_symbols[tname.lower()] = tid
        for m in re.finditer(r"\bDbSet<\s*([A-Za-z_][A-Za-z0-9_]*)\s*>\s+([A-Za-z_][A-Za-z0-9_]*)", text):
            ename, prop_name = m.group(1), m.group(2)
            tid = f"table:{prop_name}"
            nodes.setdefault(tid, {"id": tid, "name": prop_name, "kind": "table", "sourcePath": rel})
            known_symbols.setdefault(prop_name.lower(), tid)
            known_symbols.setdefault(ename.lower(), tid)

    edges_set: set[tuple[str, str, str]] = set()
    ref_patterns: list[tuple[re.Pattern[str], str]] = [
        (re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE|REFERENCES)\s+[`\"\[]?([A-Za-z_][\w$]*)", re.IGNORECASE), "data-access"),
        (re.compile(r"^\s*(?:RecordSource|RowSource|SourceObject)\s*=\s*\"?([A-Za-z_][\w$.]*)", re.MULTILINE | re.IGNORECASE), "record-source"),
        (re.compile(r"\b(?:OpenForm|OpenReport|OpenQuery)\s*[(\s]*\"([A-Za-z_][\w$]*)\"", re.IGNORECASE), "ui-navigation"),
        (re.compile(r"\b(?:CALL|COPY)\s+['\"]?([A-Za-z0-9_-]{3,})['\"]?", re.IGNORECASE), "module-call"),
        (re.compile(r"^\s*(?:import|from|using)\s+([A-Za-z_][A-Za-z0-9_.]*)", re.MULTILINE), "module-import"),
        (re.compile(r"<ProjectReference\s+[^>]*Include=\"([^\"]+)\"", re.IGNORECASE), "project-reference"),
    ]

    for f in files:
        cat = f["category"]
        if cat not in LEGACY_CATEGORIES:
            continue
        rel = f["relativePath"]
        src_id = f"{cat}:{Path(rel).stem}"
        text = texts_by_rel.get(rel, "")
        for rx, rel_kind in ref_patterns:
            for m in rx.finditer(text):
                captured = m.group(1).strip()
                if rel_kind == "project-reference":
                    raw_sym = Path(captured.replace("\\", "/")).stem
                else:
                    raw_sym = captured.split(".")[-1].strip()
                dst_id = known_symbols.get(raw_sym.lower())
                if dst_id and dst_id != src_id:
                    edges_set.add((src_id, dst_id, rel_kind))
        # Direct prefixed identifier mentions (e.g. tbl*, qry*, frm*, rpt*)
        for m in re.finditer(r"\b((?:tbl|frm|rpt|qry)[A-Z][A-Za-z0-9_]{2,})\b", text):
            dst_id = known_symbols.get(m.group(1).lower())
            if dst_id and dst_id != src_id:
                edges_set.add((src_id, dst_id, "object-reference"))

    edges = [
        {"from": s, "to": d, "relationship": k}
        for s, d, k in sorted(edges_set)
    ]

    # Deterministic bottom-up topological tiering (leaf data tables = tier 0; callers = higher tiers; cycles grouped cleanly)
    adj_deps: dict[str, set[str]] = {nid: set() for nid in nodes}
    for s, d, _ in edges_set:
        if s in adj_deps and d in adj_deps:
            adj_deps[s].add(d)

    remaining = set(nodes.keys())
    tiers: list[list[str]] = []
    has_cycles = False
    while remaining:
        ready = sorted(nid for nid in remaining if not (adj_deps[nid] & remaining))
        if not ready:
            has_cycles = True
            # Break cycle deterministically by picking nodes with fewest remaining dependencies
            min_deg = min(len(adj_deps[nid] & remaining) for nid in remaining)
            ready = sorted(nid for nid in remaining if len(adj_deps[nid] & remaining) == min_deg)
        tiers.append(ready)
        remaining -= set(ready)

    dag_doc = {
        "schemaVersion": dlc.SCHEMA_VERSION,
        "generatedAtUtc": dlc.utc_now_iso(deterministic),
        "nodeCount": len(nodes),
        "edgeCount": len(edges),
        "tierCount": len(tiers),
        "hasCycles": has_cycles,
        "tiers": tiers,
        "nodes": [nodes[k] for k in sorted(nodes)],
        "edges": edges,
    }
    summary = {
        "dagFile": "specs/dependency_dag.json",
        "nodeCount": len(nodes),
        "edgeCount": len(edges),
        "tierCount": len(tiers),
        "hasCycles": has_cycles,
        "tiers": tiers,
    }
    return dag_doc, summary, len(top_modules)


def extract_runtime_readiness_signals(
    files: list[dict[str, Any]],
    texts_by_rel: dict[str, str],
    scenario: str,
) -> dict[str, Any]:
    """Deterministically inspect project manifests (.csproj, packages.config, web.config, pom.xml) and source files
    for brownfield framework versions, Windows-to-Linux OS blockers, ORM/database drivers, proprietary cloud SDKs,
    and horizontal-scaling session hazards (complementing Google Cloud Migration Center `codmod` MCP assessments)."""
    frameworks: set[str] = set()
    packages: set[str] = set()
    os_blockers: list[dict[str, str]] = []
    seen_blockers: set[tuple[str, str]] = set()
    db_coupling: set[str] = set()
    cloud_sdks: set[str] = set()
    scaling_hazards: list[dict[str, str]] = []
    seen_hazards: set[tuple[str, str]] = set()

    has_modernizable_oop_manifest = False
    has_obsolete_non_oop_legacy = False

    blocker_patterns: list[tuple[str, str, re.Pattern[str]]] = [
        ("System.Drawing (Windows GDI+ native dependency)", "windows-gdi", re.compile(r"\bSystem\.Drawing\b")),
        ("System.Web / IIS pipeline (using System.Web / IHttpModule / IHttpHandler / HttpContext.Current)", "iis-system-web", re.compile(r"(?:^\s*using\s+System\.Web\s*;|\bHttpContext\.Current\b|\b(?:System\.Web\.(?:HttpContext|UI|Mvc|HttpRuntime)|IHttpModule|IHttpHandler)\b)", re.MULTILINE)),
        ("Windows Communication Foundation (System.ServiceModel / WCF)", "wcf", re.compile(r"\bSystem\.ServiceModel\b")),
        ("Windows Registry API (Microsoft.Win32.Registry)", "windows-registry", re.compile(r"\bMicrosoft\.Win32\.Registry\b")),
        ("Native Win32 P/Invoke ([DllImport])", "win32-pinvoke", re.compile(r"\[\s*DllImport\s*\(")),
        ("Active Directory / Integrated Windows Authentication", "windows-auth-ad", re.compile(r"(?:\bSystem\.DirectoryServices\b|<authentication\s+[^>]*mode\s*=\s*[\"']Windows[\"'])", re.IGNORECASE)),
        ("COM+ / System.EnterpriseServices", "windows-com-plus", re.compile(r"\bSystem\.EnterpriseServices\b")),
    ]
    hazard_patterns: list[tuple[str, re.Pattern[str]]] = [
        ("In-memory ASP.NET Session state (HttpContext.Session / mode='InProc')", re.compile(r"(?:\bHttpContext(?:\.Current)?\.Session\b|<sessionState\b[^>]*\bmode\s*=\s*[\"']InProc[\"'])", re.IGNORECASE)),
        ("Process-wide HttpApplicationState (Application[...])", re.compile(r"\bHttpContext\.Current\.Application\s*\[")),
        ("Servlet HttpSession in-memory state (request.getSession)", re.compile(r"\brequest\.getSession\s*\(")),
        ("Mutable static collection in application code", re.compile(r"\bstatic\s+(?!readonly\b|final\b)(?:ConcurrentDictionary|Dictionary|List|HashSet|HashMap|ArrayList)\s*<")),
    ]

    for f in files:
        rel = f["relativePath"]
        ext = f["extension"]
        name_low = f["name"].lower()
        text = texts_by_rel.get(rel, "")

        if ext in (".accdb", ".mdb", ".dbf", ".frm", ".cbl", ".cob", ".cpy", ".jcl", ".prc", ".proc", ".bms", ".pli", ".pl1", ".asm", ".hlasm", ".rpg", ".rpgle", ".dspf", ".asp", ".aspx", ".vbs"):
            has_obsolete_non_oop_legacy = True
        if ext in (".cbl", ".cob", ".cpy", ".jcl", ".prc", ".proc", ".bms") or re.search(r"\bIDENTIFICATION\s+DIVISION\b|\bEXEC\s+CICS\b", text, re.IGNORECASE):
            frameworks.add("Mainframe COBOL / JCL")
            if re.search(r"\bEXEC\s+CICS\b", text, re.IGNORECASE) or ext == ".bms":
                frameworks.add("IBM CICS / BMS")
            if re.search(r"\bCOMP-3\b|\bPACKED-DECIMAL\b", text, re.IGNORECASE):
                os_blockers.append({"signal": "COBOL COMP-3 packed-decimal arithmetic (requires exact fixed-point Decimal parity)", "category": "mainframe-comp3", "file": rel})
            if re.search(r"\bEXEC\s+SQL\b", text, re.IGNORECASE):
                db_coupling.add("Embedded EXEC SQL (DB2 / Mainframe SQL)")
        if ext in (".csproj", ".fsproj") or name_low in ("pom.xml", "build.gradle", "build.gradle.kts"):
            has_modernizable_oop_manifest = True

        if ext in (".csproj", ".vbproj", ".fsproj", ".props"):
            for m in re.finditer(r"<TargetFrameworks?>\s*([^<\s]+)\s*</TargetFrameworks?>", text, re.IGNORECASE):
                for tfm in m.group(1).split(";"):
                    if tfm.strip():
                        frameworks.add(f".NET ({tfm.strip()})")
            for m in re.finditer(r"<TargetFrameworkVersion>\s*([^<\s]+)\s*</TargetFrameworkVersion>", text, re.IGNORECASE):
                frameworks.add(f".NET Framework ({m.group(1).strip()})")
                has_obsolete_non_oop_legacy = has_obsolete_non_oop_legacy or name_low.endswith(".vbproj")
            for m in re.finditer(r"<PackageReference\s+[^>]*Include=\"([^\"]+)\"(?:[^>]*Version=\"([^\"]+)\")?", text, re.IGNORECASE):
                pkg = f"{m.group(1)}@{m.group(2)}" if m.group(2) else m.group(1)
                packages.add(pkg)
        elif name_low == "packages.config":
            for m in re.finditer(r"<package\s+[^>]*id=\"([^\"]+)\"(?:[^>]*version=\"([^\"]+)\")?", text, re.IGNORECASE):
                pkg = f"{m.group(1)}@{m.group(2)}" if m.group(2) else m.group(1)
                packages.add(pkg)
        elif name_low == "pom.xml":
            for m in re.finditer(r"<(?:java\.version|maven\.compiler\.(?:source|target))>\s*([^<\s]+)\s*</", text):
                frameworks.add(f"Java ({m.group(1).strip()})")
            if "spring-boot" in text:
                frameworks.add("Spring Boot")
            if "struts2" in text or "org.apache.struts" in text:
                frameworks.add("Apache Struts")
        elif ext == ".asax":
            os_blockers.append({"signal": "Global.asax legacy ASP.NET HTTP pipeline", "category": "iis-system-web", "file": rel})
        elif ext == ".svc":
            os_blockers.append({"signal": "WCF .svc endpoint definition", "category": "wcf", "file": rel})

        if not text:
            continue

        if LEGACY_TEXT_MARKERS.search(text[:4000]):
            has_obsolete_non_oop_legacy = True

        for sig, cat, rx in blocker_patterns:
            if (sig, rel) not in seen_blockers and rx.search(text):
                seen_blockers.add((sig, rel))
                os_blockers.append({"signal": sig, "category": cat, "file": rel})

        for sig, rx in hazard_patterns:
            if (sig, rel) not in seen_hazards and rx.search(text):
                seen_hazards.add((sig, rel))
                scaling_hazards.append({"signal": sig, "file": rel})

        if re.search(r"\bUseSqlServer\b|Microsoft\.EntityFrameworkCore\.SqlServer", text):
            db_coupling.add("EF Core SQL Server (UseSqlServer)")
        if re.search(r"\bSystem\.Data\.Entity\b|<entityFramework\b", text):
            db_coupling.add("Legacy Entity Framework 6 (System.Data.Entity)")
        if re.search(r"\b(?:System|Microsoft)\.Data\.SqlClient\b", text):
            db_coupling.add("ADO.NET SqlClient (SQL Server)")
        if re.search(r"\bNpgsql\b|\bUseNpgsql\b", text):
            db_coupling.add("Npgsql (PostgreSQL)")
        if re.search(r"\bOracle\.ManagedDataAccess\b|\bSystem\.Data\.OracleClient\b", text):
            db_coupling.add("Oracle Data Provider (.NET)")
        if re.search(r"jdbc:sqlserver:|com\.microsoft\.sqlserver\.jdbc", text):
            db_coupling.add("JDBC SQL Server")
        if re.search(r"jdbc:oracle:|oracle\.jdbc", text):
            db_coupling.add("JDBC Oracle")

        if re.search(r"\b(?:Azure\.|Microsoft\.WindowsAzure\.|com\.azure\.|@azure/|from\s+azure\b)", text):
            cloud_sdks.add("Microsoft Azure SDK")
        if re.search(r"\b(?:AWSSDK\.|Amazon\.|software\.amazon\.awssdk|com\.amazonaws|boto3\b|@aws-sdk/)", text):
            cloud_sdks.add("Amazon Web Services (AWS) SDK")
        if re.search(r"\b(?:Google\.Cloud\.|com\.google\.cloud|google\.cloud\b|@google-cloud/)", text):
            cloud_sdks.add("Google Cloud SDK")

    if scenario == "SCENARIO_LEGACY_APP" and has_modernizable_oop_manifest and not has_obsolete_non_oop_legacy:
        rec_mode = "in-place-upgrade"
        rec_reason = (
            "Structured OOP build manifest(s) (.csproj / pom.xml / build.gradle) detected without obsolete desktop/mainframe/WebForms "
            "containers — candidate for human-approved 'in-place-upgrade' (framework/ORM/container modernization preserving existing "
            "code structure) or 'clean-room-rebuild' (confirm at Gate 1 / Stage 4A)."
        )
    else:
        rec_mode = "clean-room-rebuild"
        rec_reason = (
            "Clean-room Goldfish specification-driven rebuild recommended (greenfield requirements document or legacy desktop/form/mainframe/script estate)."
        )

    return {
        "detectedFrameworks": sorted(frameworks),
        "nugetOrMavenPackages": sorted(packages)[:60],
        "osAndPlatformBlockers": os_blockers[:50],
        "databaseAndOrmCoupling": sorted(db_coupling),
        "cloudSdkCoupling": sorted(cloud_sdks),
        "statelessScalingHazards": scaling_hazards[:50],
        "recommendedModernizationMode": rec_mode,
        "recommendationReason": rec_reason,
    }


def _sha256_and_size(path: Path, chunk: int = 1 << 20) -> tuple[str, int]:
    """Stream the file through SHA-256 in 1 MiB chunks (database containers / backups can be large)."""
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
            size += len(b)
    return h.hexdigest(), size


def _is_generated_reference(path: Path, bucket: str) -> bool:
    """Generated capture artefacts (manifest + screenshots) are never user-provided design references, even when a
    pre-v4.1 run left them under resources/design_references/."""
    if bucket != "design_references":
        return False
    return path.name in GENERATED_REFERENCE_NAMES or "screenshots" in path.parts


DOC_TYPE_PREFIX_RE = re.compile(
    r"^\s*(?:(?:business|product|software|system|functional)\s+requirements?\s+(?:document|specification|spec)"
    r"|requirements?\s+(?:document|specification|spec)|specification|statement\s+of\s+work|request\s+for\s+proposal"
    r"|BRD|PRD|SRS|RFP|SOW)\s*(?:[-—–:|]\s*)+",
    re.IGNORECASE,
)


def strip_doc_type_prefix(title: str) -> str:
    """Drop a leading document-type label ('Business Requirements Document — …', 'PRD: …') from an H1 so the
    domain slug names the business domain, not the document type."""
    stripped = DOC_TYPE_PREFIX_RE.sub("", title, count=1).strip()
    return stripped or title


def _is_ignored_path(path: Path, root_dir: Path) -> bool:
    """Return True if `path` is inside an ignored VCS/build/dependency directory or is a build/lock artifact."""
    if path.name.startswith(".") or path.name.lower() in IGNORED_FILES:
        return True
    if path.suffix.lower() in IGNORED_EXT:
        return True
    try:
        rel_parts = path.resolve().relative_to(root_dir.resolve()).parts[:-1]
    except ValueError:
        rel_parts = tuple(p for p in path.parts[:-1] if p not in (".", ".."))
    return any(p.lower() in IGNORED_DIRS or (p.startswith(".") and p not in (".", "..")) for p in rel_parts)


# --------------------------------------------------------------------------------------------------
def scan(
    root: Path,
    input_dirs: list[Path],
    domain_slug_flag: str | None,
    deterministic: bool,
    source_repo_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    buckets: list[tuple[str, Path]] = [("inputs", d) for d in input_dirs]
    for b in ("policies_and_statutes", "design_references", "shared_services"):
        buckets.append((b, root / "resources" / b))

    files: list[dict[str, Any]] = []
    texts_by_rel: dict[str, str] = {}
    seen: set[str] = set()
    legacy_names: dict[str, None] = {}
    legacy_stems: dict[str, None] = {}
    user_design_refs: list[dict[str, str]] = []
    primary_doc: tuple[int, str, str, str] | None = None  # (size, heading, relpath, heading-source)
    narrative_candidates: list[tuple[int, int, str, str]] = []  # (size, files-index, heading, heading-source) for promotion
    resources_root = (root / "resources").resolve()

    for bucket, d in buckets:
        if not d.exists():
            continue
        targets = [d] if d.is_file() else sorted((x for x in d.rglob("*") if x.is_file()), key=lambda x: str(x))
        for f in targets:
            if not d.is_file() and _is_ignored_path(f, d):
                continue
            if d.is_file() and (f.name.startswith(".") or f.name.lower() in IGNORED_FILES):
                continue
            if f.is_symlink():
                # A symlink may only point inside resources/ (or the explicitly given input dir) — never escape
                # into the home directory, /etc or another project.
                try:
                    target = f.resolve(strict=True)
                    allowed = (resources_root, d.resolve()) if not d.is_file() else (resources_root,)
                    if not any(str(target).startswith(str(a) + os.sep) or target == a for a in allowed):
                        raise ValueError(target)
                except (OSError, ValueError):
                    dlc.warn(f"skipping symlink that points outside resources/: {f}")
                    continue
            if _is_generated_reference(f, bucket):
                continue
            try:
                rel = str(f.resolve().relative_to(root.resolve()))
            except ValueError:
                rel = os.path.relpath(str(f.resolve()), str(root.resolve())).replace("\\", "/")
            if rel in seen:
                continue
            seen.add(rel)
            text = head_text(f)
            if bucket == "inputs" and text:
                texts_by_rel[rel] = text
            cat, reason = categorise(f, bucket, text)
            sha, size = _sha256_and_size(f)
            entry = {
                "relativePath": rel, "name": f.name, "extension": f.suffix.lower(), "sizeBytes": size,
                "sha256": sha, "category": cat,
                "scenarioWeight": WEIGHTS[cat] if bucket == "inputs" else 0, "categoryReason": reason,
            }
            files.append(entry)
            for n in legacy_object_names(f, cat, text):
                legacy_names.setdefault(n, None)
            if cat in LEGACY_CATEGORIES and len(f.stem) >= 3 and f.stem.lower() not in GENERIC_SOURCE_STEM_STOPWORDS:
                legacy_stems.setdefault(f.stem, None)
            if cat == "design_reference" and bucket != "shared_services":
                user_design_refs.append({"relativePath": rel, "designType": design_type(f)})
            if bucket == "inputs" and f.suffix.lower() in NARRATIVE_DOC_EXT and cat in ("requirements_doc", "other"):
                h, h_src = first_heading(text, f.suffix.lower()), "primary-document-h1"
                if not printable_title(h):
                    # No printable heading (binary garbage, PDF, empty) -> the file name is the only safe title
                    h, h_src = title_from_filename(f), "primary-document-filename"
                if cat == "requirements_doc":
                    if primary_doc is None or size > primary_doc[0]:
                        primary_doc = (size, h, rel, h_src)
                else:
                    narrative_candidates.append((size, len(files) - 1, h, h_src))
            elif cat == "requirements_doc" and bucket == "inputs":
                # .txt / .html requirements documents: title from the first heading when printable
                h, h_src = first_heading(text, f.suffix.lower()), "primary-document-h1"
                if not printable_title(h):
                    h, h_src = title_from_filename(f), "primary-document-filename"
                if primary_doc is None or size > primary_doc[0]:
                    primary_doc = (size, h, rel, h_src)

    # A narrative .md/.docx/.pdf without requirement keywords still counts as the requirements document when it is
    # the only / largest document in resources/inputs and no keyword-bearing requirements document exists.
    if primary_doc is None and narrative_candidates:
        size, idx, h, h_src = max(narrative_candidates, key=lambda c: c[0])
        e = files[idx]
        e["category"] = "requirements_doc"
        e["scenarioWeight"] = WEIGHTS["requirements_doc"]
        e["categoryReason"] = f"{e['extension']} narrative document promoted: only/largest document in resources/inputs (no requirements keywords found)"
        primary_doc = (size, h, e["relativePath"], h_src)

    files.sort(key=lambda e: e["relativePath"])
    legacy_w = sum(e["scenarioWeight"] for e in files if e["category"] in LEGACY_CATEGORIES)
    req_w = sum(e["scenarioWeight"] for e in files if e["category"] == "requirements_doc")
    legacy_n = sum(1 for e in files if e["category"] in LEGACY_CATEGORIES and e["scenarioWeight"] > 0)
    req_n = sum(1 for e in files if e["category"] == "requirements_doc" and e["scenarioWeight"] > 0)
    total = legacy_w + req_w
    margin = abs(legacy_w - req_w)
    scenario = "SCENARIO_LEGACY_APP" if legacy_w > req_w else "SCENARIO_REQUIREMENTS_DOC"
    confidence = "HIGH" if total > 0 and margin >= 3 and margin / total >= 0.2 else "LOW"

    if domain_slug_flag:
        slug, slug_src = dlc.slugify(domain_slug_flag), "flag"
    elif source_repo_meta and source_repo_meta.get("repositoryName") and scenario == "SCENARIO_LEGACY_APP":
        slug, slug_src = dlc.slugify(str(source_repo_meta["repositoryName"])), "source-repository"
    elif primary_doc and primary_doc[1] and printable_title(primary_doc[1]):
        slug, slug_src = dlc.slugify(strip_doc_type_prefix(primary_doc[1])), primary_doc[3]
    else:
        slug, slug_src = dlc.slugify(root.name), "project-directory-name"

    hasher_input = "".join(f"{e['relativePath']}:{e['sha256']}\n" for e in files).encode("utf-8")
    policy_files = [e for e in files if e["category"] == "policy"]

    dag_doc, dag_summary, top_module_count = build_dependency_dag(files, texts_by_rel, deterministic)
    if dag_doc["nodeCount"] > 0:
        dlc.write_json(root / "specs" / "dependency_dag.json", dag_doc)
    else:
        dag_summary["dagFile"] = None
    unverified_acronyms = extract_unverified_acronyms(texts_by_rel)
    detected_ambiguities = detect_cross_artifact_ambiguities(texts_by_rel)
    runtime_signals = extract_runtime_readiness_signals(files, texts_by_rel, scenario)
    security_signals = dlc_security_runner.run_stage1_legacy_scan(
        root, input_dirs, texts_by_rel, deterministic=deterministic
    )
    if security_signals.get("securityOverrideRecommended") and runtime_signals.get("recommendedModernizationMode") == "in-place-upgrade":
        runtime_signals["recommendedModernizationMode"] = "clean-room-rebuild"
        runtime_signals["recommendationReason"] = (
            f"Security posture override: {security_signals['findingCount']} security finding(s) "
            f"({security_signals['criticalCount']} CRITICAL, {security_signals['highCount']} HIGH) detected in input codebase — "
            "overriding 'in-place-upgrade' to 'clean-room-rebuild' (confirm action with human via Grill-Me)."
        )
    large_repo_mr = bool(top_module_count > 15 or len(files) > 60)

    result: dict[str, Any] = {
        "schemaVersion": dlc.SCHEMA_VERSION,
        "scannedAtUtc": dlc.utc_now_iso(deterministic),
        "projectRoot": ".",
        "domainSlug": slug,
        "domainSlugSource": slug_src,
        "primaryRequirementsDoc": primary_doc[2] if primary_doc else None,
        "inputScenario": scenario,
        "scenarioEvidence": {
            "legacyArtifactCount": legacy_n, "requirementsDocCount": req_n,
            "legacyWeight": legacy_w, "requirementsWeight": req_w, "decisionRule": DECISION_RULE,
        },
        "scenarioConfidence": confidence,
        "includeModernizationEnhancementsInSpec": scenario == "SCENARIO_LEGACY_APP",
        "hasPoliciesOrStatutes": len(policy_files) > 0,
        "hasUserProvidedDesignReferences": len(user_design_refs) > 0,
        "userProvidedDesignReferences": user_design_refs,
        "legacyObjectNames": sorted(legacy_names) if scenario == "SCENARIO_LEGACY_APP" or legacy_n else [],
        "legacyFileStems": sorted(legacy_stems) if scenario == "SCENARIO_LEGACY_APP" or legacy_n else [],
        "dependencyDagSummary": dag_summary,
        "topLevelModuleCount": top_module_count,
        "largeRepoMapReduceRecommended": large_repo_mr,
        "unverifiedAcronyms": unverified_acronyms,
        "detectedAmbiguities": detected_ambiguities,
        "runtimeReadinessSignals": runtime_signals,
        "securityPostureSignals": security_signals,
        "inputFingerprintSha256": dlc.sha256_bytes(hasher_input),
        "totalFilesScanned": len(files),
        "files": files,
    }
    if source_repo_meta is not None:
        result["sourceRepository"] = source_repo_meta
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument("--input-dir", nargs="+", default=["resources/inputs"], help="Input dir(s)/file(s), relative to project root (or absolute path)")
    ap.add_argument("--ado-repo", default=None, help="Azure DevOps Git repository URL (https://dev.azure.com/<org>/<project>/_git/<repo>) or repository name to ingest into resources/inputs/<repo>")
    ap.add_argument("--ado-org-url", default=None, help="Azure DevOps Organization URL (overrides ADO_ORG_URL when --ado-repo is a repo name)")
    ap.add_argument("--ado-project", default=None, help="Azure DevOps Project name (overrides ADO_PROJECT when --ado-repo is a repo name)")
    ap.add_argument("--ado-branch", default=None, help="Optional Azure DevOps Git branch/tag to clone (overrides ADO_BRANCH)")
    ap.add_argument("--git-repo", default=None, help="Generic Git repository URL (GitHub/GitLab/Bitbucket/etc.) to ingest into resources/inputs/<repo>")
    ap.add_argument("--git-branch", default=None, help="Optional Git branch/tag to clone")
    ap.add_argument("--domain-slug", default=None, help="Override the kebab-case domain slug")
    ap.add_argument("--output", default="specs/input_inventory.json")
    ap.add_argument("--deterministic", action="store_true", help="Freeze timestamp for byte-identical output")
    ap.add_argument("--allow-empty", action="store_true", help="Allow zero input files during dry-run checks")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = dlc.resolve_project_root(args.project_root)
    load_env_files(root)
    dlc.require_gate_approved(root, "gate_0_setup", "Stage 1 (01-discovery-and-grouping / scan_input_sources.py)", deterministic=args.deterministic)

    # Enforce Stage 0 setup & ADO project confirmation before ingesting an ADO repository in interactive mode
    if args.ado_repo and not dlc.is_autonomous_or_golden(root, deterministic=args.deterministic):
        ga = dlc.load_gate_approvals(root)
        g0_status = ((ga.get("gates") or {}).get("gate_0_setup") or {}).get("status")
        if g0_status not in ("APPROVED_BY_USER", "PRE_APPROVED_AUTONOMOUS"):
            raise dlc.GateFailure(
                "ADO repository ingestion requires completing Stage 0 (`00-setup-and-connection`) and human Gate 0 approval first.\n"
                "  1. Run `setup_project_connection.py --action list-ado-projects` and ask the user WHICH ADO Project they want to work on.\n"
                "  2. Run `setup_project_connection.py --action list-ado-repos --ado-project <PROJECT>` and confirm the repository.\n"
                "  3. Save `specs/project_setup.json` (`--action save-setup`), STOP, and wait for human Gate 0 approval (`gate_0_setup`)."
            )

    for folder in ["resources/inputs", "resources/design_references", "resources/policies_and_statutes",
                   "resources/shared_services", "specs"]:
        (root / folder).mkdir(parents=True, exist_ok=True)

    # Auto-populate input source from Stage 0 `specs/project_setup.json` when CLI flags were not explicitly repeated
    setup_path = root / "specs" / "project_setup.json"
    if setup_path.is_file() and not args.ado_repo and not args.git_repo:
        setup_doc = dlc.read_json(setup_path)
        inp_cfg = (setup_doc.get("inputSource") or {}) if isinstance(setup_doc, dict) else {}
        kind = inp_cfg.get("kind")
        if kind == "ado" and (inp_cfg.get("repositoryUrl") or inp_cfg.get("repositoryName")):
            repo_target = inp_cfg.get("repositoryUrl") or inp_cfg.get("repositoryName")
            rname = inp_cfg.get("repositoryName") or "ado-repo"
            if not (root / "resources" / "inputs" / dlc.slugify(str(rname))).exists():
                args.ado_repo = str(repo_target)
                args.ado_org_url = args.ado_org_url or inp_cfg.get("adoOrgUrl")
                args.ado_project = args.ado_project or inp_cfg.get("adoProject")
                args.ado_branch = args.ado_branch or inp_cfg.get("branch")
        elif kind == "git" and inp_cfg.get("repositoryUrl"):
            rname = inp_cfg.get("repositoryName") or Path(urllib.parse.urlparse(str(inp_cfg["repositoryUrl"])).path).stem
            if not (root / "resources" / "inputs" / dlc.slugify(str(rname))).exists():
                args.git_repo = str(inp_cfg["repositoryUrl"])
                args.git_branch = args.git_branch or inp_cfg.get("branch")
        elif kind == "local-dir" and inp_cfg.get("localPath") and args.input_dir == ["resources/inputs"]:
            args.input_dir = [str(inp_cfg["localPath"])]

    out = dlc.project_path(root, args.output)
    source_repo_meta: dict[str, Any] | None = None

    if args.ado_repo:
        org_url, proj, repo_name, clone_url = resolve_ado_repo_coordinates(
            args.ado_repo, args.ado_org_url, args.ado_project
        )
        pat = os.environ.get("ADO_PAT")  # env / .env only — never a CLI flag (argv is visible in `ps` and shell history)
        branch = args.ado_branch or os.environ.get("ADO_BRANCH")
        source_repo_meta = ingest_remote_repository(
            root=root,
            provider="ado",
            repo_url=clone_url,
            repo_name=repo_name,
            branch=branch,
            pat_or_token=pat,
            ado_org_url=org_url,
            ado_project=proj,
        )
    elif args.git_repo:
        raw_git = args.git_repo.strip()
        repo_name = Path(urllib.parse.urlparse(raw_git).path).stem or "git-repo"
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]
        token = os.environ.get("GIT_TOKEN") or os.environ.get("GITHUB_TOKEN")  # env / .env only — never a CLI flag
        branch = args.git_branch or os.environ.get("GIT_BRANCH")
        source_repo_meta = ingest_remote_repository(
            root=root,
            provider="git",
            repo_url=raw_git,
            repo_name=repo_name,
            branch=branch,
            pat_or_token=token,
        )
    elif out.exists():
        # Preserve prior sourceRepository metadata on verify-only re-scans
        try:
            prev_inv = dlc.read_json(out)
            if isinstance(prev_inv, dict) and isinstance(prev_inv.get("sourceRepository"), dict):
                source_repo_meta = prev_inv["sourceRepository"]
        except SystemExit:
            pass

    input_dirs = [dlc.project_path(root, d) for d in args.input_dir]
    missing = [str(d) for d in input_dirs if not d.exists()]
    if missing:
        dlc.warn(f"input path(s) not found: {', '.join(missing)}")

    domain_slug = args.domain_slug
    if not domain_slug and out.exists():
        # A slug the user chose earlier (--domain-slug) survives re-scans by the verify pipeline.
        try:
            prev = dlc.read_json(out)
            if isinstance(prev, dict) and prev.get("domainSlugSource") == "flag" and prev.get("domainSlug"):
                domain_slug = str(prev["domainSlug"])
        except SystemExit:
            pass
    inv = scan(root, input_dirs, domain_slug, args.deterministic, source_repo_meta=source_repo_meta)
    errs = dlc.validate_against_schema(inv, dlc.load_schema("input_inventory.schema.json"))
    if errs:
        raise dlc.GateFailure("scan produced an inventory violating schemas/input_inventory.schema.json:\n  " + "\n  ".join(errs))
    dlc.write_json(out, inv)

    ev = inv["scenarioEvidence"]
    dlc.info(f"wrote {out}")
    dlc.info(f"files={inv['totalFilesScanned']} legacy(n={ev['legacyArtifactCount']},w={ev['legacyWeight']}) "
             f"requirements(n={ev['requirementsDocCount']},w={ev['requirementsWeight']}) -> {inv['inputScenario']} "
             f"[{inv['scenarioConfidence']}] slug={inv['domainSlug']} ({inv['domainSlugSource']})")
    if inv["totalFilesScanned"] == 0:
        if not args.allow_empty and not dlc.is_autonomous_or_golden(root, deterministic=args.deterministic):
            raise dlc.GateFailure(
                "Zero input files found in Stage 1 scan — refusing to proceed without confirmed inputs.\n"
                "  Run Stage 0 (`00-setup-and-connection`) first: ask the user where their input source is located "
                "(`resources/inputs/`, local directory, Azure DevOps project/repository, or Git repository), "
                "save `specs/project_setup.json`, and wait for human Gate 0 approval before running Stage 1."
            )
        dlc.warn("no input files found — Stage 0/1 must ask the user where their input source is located (resources/inputs/, local folder, Azure DevOps repo, or Git repo).")

    # Initialize specs/gate_approvals.json on new interactive runs started directly with local files so Stage 2+ gates are enforced
    if (
        not dlc.is_autonomous_or_golden(root, deterministic=args.deterministic)
        and not dlc.gate_approvals_path(root).exists()
        and not (root / "specs" / "application_spec.md").exists()
    ):
        now_iso = dlc.utc_now_iso(False)
        dlc.write_json(
            dlc.gate_approvals_path(root),
            {
                "schemaVersion": dlc.SCHEMA_VERSION,
                "gates": {
                    "gate_0_setup": {
                        "gateId": "gate_0_setup",
                        "stage": dlc.GATE_DEFINITIONS["gate_0_setup"],
                        "status": "APPROVED_BY_USER",
                        "readyAtUtc": now_iso,
                        "readyAtEpoch": None,
                        "approvedAtUtc": now_iso,
                        "userResponse": "Direct local input scan initiated with populated input files",
                        "summary": "Local input files provided directly at Stage 1 entry.",
                    }
                },
            },
        )
    if inv["scenarioConfidence"] == "LOW":
        dlc.warn("scenario confidence LOW — Gate 1 must ask the user to confirm SCENARIO_LEGACY_APP vs SCENARIO_REQUIREMENTS_DOC.")
    sec_sig = inv.get("securityPostureSignals") or {}
    if int(sec_sig.get("findingCount") or 0) > 0 and not dlc.is_golden_run():
        dlc.warn(
            f"Stage 1 security scan found {sec_sig['findingCount']} vulnerability finding(s) "
            f"({sec_sig.get('criticalCount', 0)} CRITICAL, {sec_sig.get('highCount', 0)} HIGH) -> "
            "Grill-Me (`clarification-griller --stage pre-spec`) MUST quiz the user on what action to take before Stage 2!"
        )
    if not inv["hasUserProvidedDesignReferences"]:
        dlc.info("no design references found — ask the user (Gate 1) or proceed with the default design system.")
    if not args.quiet:
        print(json.dumps({k: v for k, v in inv.items() if k != "files"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
