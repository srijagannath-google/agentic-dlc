#!/usr/bin/env python3
"""Stage 3 backlog audit + ALM bridge (Atlassian Jira Cloud REST v3 / Agile 1.0 and Azure DevOps REST 7.1).

v4 contract (docs/ARCHITECTURE.md §1, §4.5, §5 Gate 3):
  * The LLM authors `backlog/user_stories.json`; this script NEVER substitutes a template. If the file is
    missing the script exits non-zero naming the stage that must produce it.
  * Gate 3 audit (no network): every `REQ-*` id in `specs/application_spec.md` (and `specs/.spec_index.json`
    when present) is referenced by >= 1 story (FAIL -> blocks sync unless `--allow-partial-coverage`);
    every `BR-NN` business rule is referenced (WARN); storyPoints <= 8 (FAIL); >= 4 ACs per story (WARN);
    >= 1 NEGATIVE-tagged AC per story (WARN); every story has a `sprint` field (FAIL).
  * Writes `backlog/sprint_plan.json` (sprints / productBacklog / coverage / approvalStatus),
    `backlog/jira_import.csv`, `backlog/jira_state.json`, `backlog/azure_devops_state.json`.
  * Live sync is idempotent (upsert by `[US-ID]` title prefix). Offline mode or missing credentials produce a
    local export only and say so explicitly; a live sync is never reported unless it happened.

Actions:  test-connection | audit | sync-stories | sync-sprints (--approved) | transition-stories | sync-status-from-eval | set-approval | export-csv

Environment / flags:
  JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_PROJECT_KEY (optional; auto-discovered), JIRA_BOARD_ID (optional),
  JIRA_ISSUE_TYPE (default Story)
  ADO_ORG_URL (https://dev.azure.com/<org>), ADO_PROJECT, ADO_PAT, ADO_WORK_ITEM_TYPE (default "User Story")
  DLC_OFFLINE_MODE=1 (same as --offline)
  Values may also live in ./.env, <PROJECT_ROOT>/.env or ~/.gemini/config/agentic-dlc.env.

Python >= 3.10, standard library only.
"""
from __future__ import annotations

import argparse
import base64
import csv
import difflib
import html
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import dlc_common as dlc  # noqa: E402

APPROVAL_STATES = ("PENDING_HUMAN_APPROVAL", "APPROVED_BY_USER", "PRE_APPROVED_BY_USER")
STORY_STATUSES = ("To Do", "In Progress", "Done")
STORY_STATUS_ALIASES: dict[str, str] = {
    "to do": "To Do", "todo": "To Do", "to-do": "To Do", "to_do": "To Do", "new": "To Do", "open": "To Do", "backlog": "To Do",
    "in progress": "In Progress", "in-progress": "In Progress", "in_progress": "In Progress", "inprogress": "In Progress",
    "active": "In Progress", "doing": "In Progress", "in development": "In Progress", "in review": "In Progress",
    "done": "Done", "closed": "Done", "resolved": "Done", "complete": "Done", "completed": "Done",
}
JIRA_STATUS_CATEGORY: dict[str, str] = {"To Do": "new", "In Progress": "indeterminate", "Done": "done"}
JIRA_STATUS_ALIASES: dict[str, set[str]] = {
    "To Do": {"to do", "todo", "open", "backlog", "new", "reopen", "reopened", "selected for development"},
    "In Progress": {"in progress", "in development", "in review", "start progress", "work in progress", "doing", "active"},
    "Done": {"done", "closed", "close", "resolved", "resolve", "complete", "completed", "finish"},
}
ADO_STATE_CANDIDATES: dict[str, list[str]] = {
    "To Do": ["New", "To Do", "Proposed"],
    "In Progress": ["Active", "Doing", "In Progress", "Committed"],
    "Done": ["Closed", "Done", "Resolved", "Completed"],
}
REQ_PREFIXES = ("REQ-FUNC", "REQ-ENH", "REQ-SEC", "REQ-A11Y", "REQ-UX", "REQ-ARCH")
MAX_STORY_POINTS = 8
MIN_ACS_PER_STORY = 4
JIRA_SPRINT_NAME_MAX = 30
ADO_API = "7.1"
STORY_ID_PREFIX_RE = re.compile(r"^\[([A-Za-z0-9_-]+)\]")
SPRINT_LABEL_RE = re.compile(r"^\s*sprint\s*(\d+)", re.IGNORECASE)


# ======================================================================================
# Section 0 — environment, HTTP plumbing
# ======================================================================================
def load_env_files(project_root: Path | None = None) -> None:
    """Populate os.environ from dotenv-style files without overriding real environment variables."""
    candidates = [Path.cwd() / ".env", Path.cwd() / ".env.jira", Path.home() / ".gemini" / "config" / "agentic-dlc.env"]
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
            k, v = k.strip(), v.strip().strip("'").strip('"')
            if k and k not in os.environ:
                os.environ[k] = v


def build_ssl_context() -> ssl.SSLContext:
    """Default context; on macOS Python 3.13+ prefer /etc/ssl/cert.pem when present (pip certifi not required)."""
    try:
        ctx = ssl.create_default_context()
        if sys.platform == "darwin" and Path("/etc/ssl/cert.pem").exists():
            ctx.load_verify_locations(cafile="/etc/ssl/cert.pem")
        return ctx
    except (ssl.SSLError, OSError):
        if Path("/etc/ssl/cert.pem").exists():
            return ssl.create_default_context(cafile="/etc/ssl/cert.pem")
        return ssl.create_default_context()


class HttpError(Exception):
    def __init__(self, method: str, url: str, status: int, body: str):
        self.method, self.url, self.status, self.body = method, url, status, body
        super().__init__(f"{method} {url} -> HTTP {status}: {body[:240]}")


def http_json(method: str, url: str, headers: dict[str, str], body: Any = None, timeout: int = 20) -> tuple[int, Any]:
    """Perform one HTTPS request; return (status, parsed-json-or-text-or-None). Raises HttpError."""
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    ctx = build_ssl_context()
    try:
        try:
            resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
        except urllib.error.URLError as e:
            if "CERTIFICATE_VERIFY_FAILED" in str(e) and Path("/etc/ssl/cert.pem").exists():
                resp = urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context(cafile="/etc/ssl/cert.pem"))
            else:
                raise
        with resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as e:
        raise HttpError(method, url, e.code, e.read().decode("utf-8", errors="replace")) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise HttpError(method, url, 0, f"{type(e).__name__}: {e}") from None
    if not raw:
        return status, None
    try:
        return status, json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return status, raw.decode("utf-8", errors="replace")


def basic_auth_header(user: str, secret: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{secret}".encode("utf-8")).decode("ascii")


# ======================================================================================
# Section 1 — story helpers
# ======================================================================================
def ac_to_text(ac: dict[str, str]) -> str:
    """Render a normalised (v4 object) acceptance criterion as one human-readable line."""
    tag = ac.get("tag") or "POSITIVE"
    given, when, then = ac.get("given", ""), ac.get("when", ""), ac.get("then", "")
    if given or when:
        return f"[{tag}] GIVEN {given} WHEN {when} THEN {then}".strip()
    return f"[{tag}] {then}".strip()


def story_acs(story: dict[str, Any]) -> list[dict[str, str]]:
    return story.get("acceptanceCriteria", [])


def story_type_label(story: dict[str, Any]) -> str:
    t = str(story.get("type", "")).strip()
    if not t:
        t = "Technical" if str(story.get("id", "")).upper().startswith("US-TECH") else "Functional"
    return t.split("(")[0].strip()


def sprint_label(story: dict[str, Any]) -> str:
    return str(story.get("sprint") or "").strip()


def is_product_backlog(label: str) -> bool:
    low = label.lower()
    return low == "backlog" or low.startswith("product backlog")


def sprint_short_name(label: str) -> str:
    """'Sprint 2: Some goal' -> 'Sprint 2'; otherwise the text before ':' (<= 30 chars)."""
    m = SPRINT_LABEL_RE.match(label)
    if m:
        return f"Sprint {int(m.group(1))}"
    return label.split(":")[0].strip()[:JIRA_SPRINT_NAME_MAX]


def sprint_sort_key(label: str) -> tuple[int, str]:
    m = SPRINT_LABEL_RE.match(label)
    return (int(m.group(1)) if m else 10_000, label.lower())


def story_points(story: dict[str, Any]) -> float | None:
    raw = story.get("storyPoints")
    try:
        return float(raw) if raw is not None and str(raw).strip() != "" else None
    except (TypeError, ValueError):
        return None


def normalise_story_status(raw: str | None, strict: bool = False) -> str:
    val = str(raw or "").strip().lower()
    if val in STORY_STATUS_ALIASES:
        return STORY_STATUS_ALIASES[val]
    for canon in STORY_STATUSES:
        if val == canon.lower():
            return canon
    if strict:
        raise dlc.GateFailure(f"Unknown story status '{raw}'. Use one of: {', '.join(STORY_STATUSES)}.")
    return "To Do"


def story_status(story: dict[str, Any]) -> str:
    return normalise_story_status(story.get("status"))


def story_status_counts(stories: list[dict[str, Any]]) -> dict[str, int]:
    counts = {st: 0 for st in STORY_STATUSES}
    for s in stories:
        st = story_status(s)
        counts[st] = counts.get(st, 0) + 1
    return counts


def compute_story_statuses_from_eval(root: Path, stories: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Derive each story's status ('To Do' | 'In Progress' | 'Done') from test/eval_results.json + test/test_cases.json."""
    eval_path = dlc.require_file(root / "test" / "eval_results.json", "Stage 6 (07/scripts/run_closed_loop_eval.py)")
    eval_data = dlc.read_json(eval_path)
    if not isinstance(eval_data, dict):
        raise dlc.GateFailure(f"{eval_path} is not a JSON object.")

    summary = eval_data.get("summary") or {}
    verdict = str(summary.get("verdict") or eval_data.get("overallVerdict") or "").strip().upper()
    guardrail_status = str(eval_data.get("guardrailReviewStatus") or "NOT_REQUIRED").strip().upper()
    guardrail_blocked = guardrail_status == "FLAGGED_REQUIRES_HUMAN_APPROVAL"
    overall_pass = (verdict == "PASS") and not guardrail_blocked

    results_by_id: dict[str, str] = {}
    for r in eval_data.get("results") or eval_data.get("testResults") or []:
        if isinstance(r, dict) and r.get("id"):
            results_by_id[str(r["id"])] = str(r.get("status") or "NOT_RUN").strip().upper()

    tc_path = root / "test" / "test_cases.json"
    tcs: list[dict[str, Any]] = []
    if tc_path.is_file():
        tc_doc = dlc.read_json(tc_path)
        tcs = tc_doc.get("testCases", tc_doc) if isinstance(tc_doc, dict) else []

    is_all, selected_groups = dlc.active_capability_groups(root)
    out: dict[str, dict[str, Any]] = {}
    for s in stories:
        sid = str(s.get("id") or "").strip()
        if not sid:
            continue
        prev = story_status(s)
        in_selected = dlc.is_story_in_selected_group(s, is_all, selected_groups)
        if not in_selected:
            cg = str(s.get("capabilityGroup") or "Product Backlog").strip()
            out[sid] = {
                "storyId": sid,
                "previousStatus": prev,
                "status": "To Do",
                "targetStatus": "To Do",
                "reason": f"Deferred — unselected capability group ({cg}) in Product Backlog",
                "linkedTestsTotal": 0,
                "linkedTestsPassed": 0,
                "linkedTestsFailed": 0,
            }
            continue
        s_reqs = set(s.get("requirementRefs") or [])
        direct = [t for t in tcs if isinstance(t, dict) and not t.get("optional") and t.get("storyRef") == sid]
        if not direct and s_reqs:
            direct = [t for t in tcs if isinstance(t, dict) and not t.get("optional") and (set(t.get("requirementRefs") or []) & s_reqs)]

        statuses = [results_by_id.get(str(t.get("id")), "NOT_RUN") for t in direct]
        total = len(statuses)
        passed = sum(1 for st in statuses if st == "PASS")
        failed = sum(1 for st in statuses if st in ("FAIL", "ERROR"))
        not_run = sum(1 for st in statuses if st == "NOT_RUN")

        if total > 0:
            if failed > 0:
                target = "In Progress"
                reason = f"{failed}/{total} linked test(s) failing — in remediation"
            elif not_run == total:
                target = "To Do" if is_product_backlog(sprint_label(s)) else "In Progress"
                reason = f"0/{total} linked test(s) executed yet"
            elif passed == total:
                if guardrail_blocked:
                    target = "In Progress"
                    reason = f"All {passed}/{total} linked tests passed; awaiting Gate 4 human guardrail approval"
                else:
                    target = "Done"
                    reason = f"All {passed}/{total} linked tests passed and verified"
            else:
                target = "In Progress"
                reason = f"{passed}/{total} passed, {not_run} not run"
        else:
            if overall_pass:
                target = "Done"
                reason = "Overall Stage 6 evaluation passed"
            elif is_product_backlog(sprint_label(s)):
                target = "To Do"
                reason = "Product Backlog (not yet evaluated)"
            else:
                target = "In Progress"
                reason = f"Overall evaluation verdict is {verdict or 'INCOMPLETE'}"

        out[sid] = {
            "storyId": sid,
            "previousStatus": prev,
            "status": target,
            "targetStatus": target,
            "reason": reason,
            "linkedTestsTotal": total,
            "linkedTestsPassed": passed,
            "linkedTestsFailed": failed,
        }
    return out


def update_markdown_story_statuses(root: Path, stories_or_map: list[dict[str, Any]] | dict[str, str]) -> list[str]:
    """Update or insert `- **Status:**` and `- **Traceability:**` lines inside each story section in backlog/user_stories.md."""
    status_by_id: dict[str, str] = (
        {s["id"]: story_status(s) for s in stories_or_map if isinstance(s, dict) and s.get("id")}
        if isinstance(stories_or_map, list) else dict(stories_or_map)
    )
    story_by_id: dict[str, dict[str, Any]] = (
        {s["id"]: s for s in stories_or_map if isinstance(s, dict) and s.get("id")}
        if isinstance(stories_or_map, list) else {}
    )
    touched: list[str] = []
    stories_md = root / "backlog" / "user_stories.md"
    if stories_md.is_file():
        orig = dlc.read_text(stories_md)
        text = orig
        for sid, st in status_by_id.items():
            sec_re = re.compile(rf"(^###?\s+[^\n]*\b{re.escape(sid)}\b[^\n]*\n(?:(?!^###?\s).*\n)*?)(- \*\*Status:\*\*[ \t]*`?[^`\n]+`?)", re.MULTILINE)
            if sec_re.search(text):
                text = sec_re.sub(rf"\1- **Status:** `{st}`", text, count=1)
            else:
                hdr_re = re.compile(rf"(^###?\s+[^\n]*\b{re.escape(sid)}\b[^\n]*\n)", re.MULTILINE)
                if hdr_re.search(text):
                    text = hdr_re.sub(rf"\1- **Status:** `{st}`\n", text, count=1)
            s_obj = story_by_id.get(sid)
            tr = (s_obj or {}).get("traceability") if isinstance(s_obj, dict) else None
            if isinstance(tr, dict):
                tr_line = format_traceability_markdown_line(tr)
                tr_re = re.compile(rf"(^###?\s+[^\n]*\b{re.escape(sid)}\b[^\n]*\n(?:(?!^###?\s).*\n)*?)(- \*\*Traceability:\*\*[^\n]*)", re.MULTILINE)
                if tr_re.search(text):
                    text = tr_re.sub(rf"\1- **Traceability:** {tr_line}", text, count=1)
                else:
                    st_re = re.compile(rf"(^###?\s+[^\n]*\b{re.escape(sid)}\b[^\n]*\n(?:(?!^###?\s).*\n)*?- \*\*Status:\*\*[^\n]*\n)", re.MULTILINE)
                    if st_re.search(text):
                        text = st_re.sub(rf"\1- **Traceability:** {tr_line}\n", text, count=1)
        if text != orig:
            dlc.write_text(stories_md, text)
            touched.append(str(stories_md))
    return touched


def format_traceability_markdown_line(tr: dict[str, Any]) -> str:
    """Format a compact single-line summary of end-to-end traceability for backlog/user_stories.md."""
    reqs = ", ".join(tr.get("requirementRefs") or []) or "—"
    brs = ", ".join(tr.get("businessRuleRefs") or []) or "—"
    src_files = ", ".join(f"`{f}`" for f in (tr.get("targetSourceFiles") or [])) or "—"
    tcs = ", ".join(f"`{t['id']}` ({t.get('status', 'NOT_RUN')})" for t in (tr.get("testCases") or []) if isinstance(t, dict) and t.get("id")) or "—"
    bugs = ", ".join(tr.get("defectRefs") or []) or "None"
    apis = ", ".join(f"`{a}`" for a in (tr.get("apiContracts") or [])[:4]) or "—"
    tbls = ", ".join(f"`{tb}`" for tb in (tr.get("databaseTables") or [])[:4]) or "—"
    return f"Reqs: {reqs} | Rules: {brs} | API: {apis} | DB: {tbls} | Code: {src_files} | Tests: {tcs} | Defects: {bugs}"


def enrich_story_traceability(root: Path, stories: list[dict[str, Any]], defects: list[dict[str, Any]] | None = None) -> None:
    """Populate `story['traceability']` on every story linking Legacy/Input Sources -> Requirements & Business Rules ->
    Design Contracts (OpenAPI/DDL) -> Target Source Code (`src/`) & UI `data-testid` hooks -> Test Cases (`TC-*`) -> Defects (`BUG-*`)."""
    # 1. Discover input sources (legacy files or BRDs)
    inv_files: list[str] = []
    inv_p = root / "specs" / "input_inventory.json"
    if inv_p.is_file():
        inv_doc = dlc.read_json(inv_p)
        if isinstance(inv_doc, dict):
            for f_item in inv_doc.get("files") or inv_doc.get("inputs") or []:
                if isinstance(f_item, dict) and f_item.get("path"):
                    inv_files.append(str(f_item["path"]))
                elif isinstance(f_item, str):
                    inv_files.append(f_item)

    # 2. Discover design contracts (API operations & DB tables)
    api_ops: list[str] = []
    db_tables: list[str] = []
    cidx_p = root / "design" / ".contracts_index.json"
    if cidx_p.is_file():
        cidx = dlc.read_json(cidx_p)
        if isinstance(cidx, dict):
            for op in cidx.get("openapiOperations") or cidx.get("apiEndpoints") or []:
                if isinstance(op, dict):
                    m = str(op.get("method") or "").upper()
                    p = str(op.get("path") or "")
                    if m and p:
                        api_ops.append(f"{m} {p}")
                elif isinstance(op, str):
                    api_ops.append(op)
            for tb in cidx.get("ddlTables") or cidx.get("tables") or []:
                if isinstance(tb, dict) and tb.get("name"):
                    db_tables.append(str(tb["name"]))
                elif isinstance(tb, str):
                    db_tables.append(tb)
    if not api_ops and (root / "src" / "contracts" / "openapi.yaml").is_file():
        oa_txt = dlc.read_text(root / "src" / "contracts" / "openapi.yaml")
        cur_path = ""
        for ln in oa_txt.splitlines():
            m_path = re.match(r"^\s{2}(/[A-Za-z0-9_/{}-]+):\s*$", ln)
            if m_path:
                cur_path = m_path.group(1)
            m_meth = re.match(r"^\s{4}(get|post|put|patch|delete):\s*$", ln, re.I)
            if m_meth and cur_path:
                op_str = f"{m_meth.group(1).upper()} {cur_path}"
                if op_str not in api_ops:
                    api_ops.append(op_str)
    if not db_tables and (root / "src" / "db" / "schema.sql").is_file():
        sql_txt = dlc.read_text(root / "src" / "db" / "schema.sql")
        for m_tb in re.finditer(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"']?([A-Za-z0-9_]+)[`\"']?", sql_txt, re.I):
            tb_name = m_tb.group(1)
            if tb_name not in db_tables:
                db_tables.append(tb_name)

    # 3. Discover target source files under src/
    src_files: list[str] = []
    src_dir = root / "src"
    if src_dir.is_dir():
        for p in sorted(src_dir.rglob("*")):
            if p.is_file() and not any(part in ("__pycache__", "node_modules", ".venv", ".git") for part in p.parts):
                if p.suffix.lower() in (".html", ".js", ".ts", ".tsx", ".css", ".py", ".sql", ".yaml", ".yml", ".go", ".java"):
                    src_files.append(str(p.relative_to(root)).replace(os.sep, "/"))

    # 4. Load test cases & latest evaluation statuses
    tc_list: list[dict[str, Any]] = []
    tc_p = root / "test" / "test_cases.json"
    if tc_p.is_file():
        tc_doc = dlc.read_json(tc_p)
        if isinstance(tc_doc, dict):
            tc_list = [t for t in (tc_doc.get("testCases") or []) if isinstance(t, dict)]
    eval_status_by_tc: dict[str, str] = {}
    eval_p = root / "test" / "eval_results.json"
    if eval_p.is_file():
        eval_doc = dlc.read_json(eval_p)
        if isinstance(eval_doc, dict):
            for r in eval_doc.get("results") or eval_doc.get("testResults") or []:
                if isinstance(r, dict) and r.get("id"):
                    eval_status_by_tc[str(r["id"])] = str(r.get("status") or "NOT_RUN").strip().upper()

    # 5. Load defects if not passed in
    if defects is None:
        defects = load_defects(root)

    # 6. Load GDC deployment evaluation report if present (Stage 8)
    dep_eval: dict[str, Any] | None = None
    dep_eval_p = root / "deploy" / "deployment_eval_report.json"
    if dep_eval_p.is_file():
        doc = dlc.read_json(dep_eval_p)
        if isinstance(doc, dict):
            dep_eval = doc
    wave_by_group: dict[str, int] = {}
    if dep_eval:
        for w in dep_eval.get("rolloutWaves") or []:
            if isinstance(w, dict) and w.get("capabilityGroup"):
                wave_by_group[str(w["capabilityGroup"]).upper()] = int(w.get("wave") or 1)

    for s in stories:
        sid = str(s.get("id") or "").strip()
        if not sid:
            continue
        legacy_srcs = [str(x) for x in (s.get("legacyArtifactsReplaced") or []) if str(x).strip()]
        if not legacy_srcs and inv_files:
            legacy_srcs = list(inv_files[:4])
        s_reqs = [str(x) for x in (s.get("requirementRefs") or []) if str(x).strip()]
        s_brs = [str(x) for x in (s.get("businessRuleRefs") or []) if str(x).strip()]
        s_trans = [str(x) for x in (s.get("workflowTransitions") or []) if str(x).strip()]

        # Linked test cases for this story
        s_req_set = set(s_reqs)
        linked_tcs = [t for t in tc_list if t.get("storyRef") == sid]
        for t in tc_list:
            if t not in linked_tcs and (set(t.get("requirementRefs") or []) & s_req_set):
                linked_tcs.append(t)

        # Extract UI data-testid selectors and HTTP endpoints exercised by the story's linked test cases
        ui_testids: list[str] = []
        story_apis: list[str] = []
        for t in linked_tcs:
            for st in t.get("steps") or []:
                if not isinstance(st, dict):
                    continue
                sel = str(st.get("selector") or "")
                for m_tid in re.finditer(r"data-testid=['\"]?([A-Za-z0-9_-]+)['\"]?", sel):
                    tid_val = m_tid.group(1)
                    if tid_val not in ui_testids:
                        ui_testids.append(tid_val)
                if st.get("action") == "httpRequest":
                    meth = str(st.get("method") or "GET").upper()
                    pth = str(st.get("path") or st.get("url") or "")
                    if pth:
                        op_label = f"{meth} {pth.split('?')[0]}"
                        if op_label not in story_apis:
                            story_apis.append(op_label)
        if not story_apis and api_ops:
            story_apis = list(api_ops[:6])

        tc_summaries = [
            {
                "id": str(t.get("id")),
                "category": str(t.get("category") or ""),
                "status": eval_status_by_tc.get(str(t.get("id")), "NOT_RUN"),
            }
            for t in linked_tcs if t.get("id")
        ]
        story_bugs = [
            f"{b['id']} ({b.get('status', 'In Progress')}" + (f", Jira: {b['jiraKey']}" if b.get("jiraKey") else "") + ")"
            for b in (defects or []) if isinstance(b, dict) and b.get("storyRef") == sid
        ]
        tr_obj: dict[str, Any] = {
            "legacySourceArtifacts": legacy_srcs,
            "requirementRefs": s_reqs,
            "businessRuleRefs": s_brs,
            "workflowTransitions": s_trans,
            "apiContracts": story_apis,
            "databaseTables": list(db_tables[:8]),
            "targetSourceFiles": list(src_files),
            "uiTestIds": ui_testids[:12],
            "testCases": tc_summaries,
            "defectRefs": story_bugs,
        }
        if dep_eval:
            cg_u = str(s.get("capabilityGroup") or "GRP-01").strip().upper()
            tr_obj["gdcDeployment"] = {
                "abstractionPlane": str(dep_eval.get("abstractionPlane") or "gdc-fleet"),
                "targetEnvironments": list(dep_eval.get("targetEnvironments") or ["on-prem-gdc", "gcp", "aws", "azure"]),
                "rolloutWave": wave_by_group.get(cg_u, 1),
                "verdict": str((dep_eval.get("summary") or {}).get("verdict") or "PASS"),
            }
        s["traceability"] = tr_obj


def load_defects(root: Path) -> list[dict[str, Any]]:
    """Load existing defect records from backlog/defects.json if present."""
    p = root / "backlog" / "defects.json"
    if p.is_file():
        doc = dlc.read_json(p)
        if isinstance(doc, dict) and isinstance(doc.get("defects"), list):
            return [d for d in doc["defects"] if isinstance(d, dict)]
    return []


def compute_snapshot_diff_steps(root: Path, from_iter: int, to_iter: int) -> tuple[list[str], list[str], str]:
    """Compare test/.snapshots/iter-<from_iter> -> iter-<to_iter> (or current src/) and extract human-readable fix steps,
    modified file paths, and a compact unified diff summary."""
    snaps = root / "test" / ".snapshots"
    prev_dir = snaps / f"iter-{from_iter}"
    cur_dir = snaps / f"iter-{to_iter}"
    if not cur_dir.is_dir():
        cur_dir = root / "src"

    meta_skip = {
        "eval_results.json",
        "eval_report.md",
        "remediation_and_guardrail_audit_report.md",
        "defects.json",
        "defects.md",
    }

    def _collect(base: Path, is_src_root: bool = False) -> dict[str, Path]:
        out: dict[str, Path] = {}
        if not base.is_dir():
            return out
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.name not in meta_skip and not any(pt in ("__pycache__", "node_modules", ".venv", ".git", "screenshots") for pt in p.parts):
                rel = str(p.relative_to(base)).replace(os.sep, "/")
                if is_src_root and not rel.startswith("src/"):
                    rel = f"src/{rel}"
                elif not rel.startswith("src/"):
                    rel = f"src/{rel}"
                out[rel] = p
        return out

    prev_files = _collect(prev_dir)
    cur_files = _collect(cur_dir, is_src_root=(cur_dir == root / "src"))
    files_modified: list[str] = []
    steps_taken: list[str] = []
    diff_chunks: list[str] = []

    if prev_files and cur_files:
        for rel in sorted(set(prev_files) | set(cur_files)):
            a_lines = dlc.read_text(prev_files[rel]).splitlines() if rel in prev_files else []
            b_lines = dlc.read_text(cur_files[rel]).splitlines() if rel in cur_files else []
            if a_lines == b_lines:
                continue
            files_modified.append(rel)
            added = sum(1 for ln in difflib.ndiff(a_lines, b_lines) if ln.startswith("+ "))
            removed = sum(1 for ln in difflib.ndiff(a_lines, b_lines) if ln.startswith("- "))
            udiff = list(difflib.unified_diff(
                a_lines, b_lines,
                fromfile=f"iter-{from_iter}/{rel}",
                tofile=f"iter-{to_iter}/{rel}",
                lineterm="", n=2,
            ))
            # Extract modified symbols/selectors from +/- lines
            symbols: list[str] = []
            for ln in udiff:
                if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---")):
                    for m_sym in re.finditer(r"(?:def|function|class)\s+([A-Za-z0-9_]+)|data-testid=['\"]([A-Za-z0-9_-]+)['\"]", ln):
                        sym = m_sym.group(1) or m_sym.group(2)
                        if sym and sym not in symbols:
                            symbols.append(sym)
            sym_note = f" touching {', '.join(f'`{s}`' for s in symbols[:6])}" if symbols else ""
            steps_taken.append(f"Modified `{rel}` (+{added}/-{removed} lines){sym_note} between Iteration {from_iter} and Iteration {to_iter}.")
            diff_chunks.extend(udiff[:25])

    if not files_modified and cur_files:
        files_modified = sorted(cur_files.keys())
        steps_taken.append(f"Updated implementation in {', '.join(f'`{f}`' for f in files_modified[:5])} and re-verified in Iteration {to_iter}.")

    diff_summary = "\n".join(diff_chunks[:45])
    return steps_taken, files_modified, diff_summary


def sync_defects_from_eval(root: Path, stories: list[dict[str, Any]], deterministic: bool) -> list[dict[str, Any]]:
    """Inspect Stage 6 evaluation history (test/.snapshots/iter-*/eval_results.json + test/eval_results.json):
      1. Whenever a non-optional test case fails ('FAIL' or 'ERROR'), create/update a Bug record (`BUG-01..N`) with
         issueType='Bug', detailed description of what the bug was, and full traceability to story/reqs/code/tests.
      2. When a subsequent Stage 6 iteration fixes the failing test(s) (status == 'PASS'), record a remediation comment
         detailing the exact code changes & steps taken to fix the defect and transition the Bug to 'Done'.
    """
    eval_path = root / "test" / "eval_results.json"
    if not eval_path.is_file():
        return load_defects(root)

    cur_eval = dlc.read_json(eval_path)
    if not isinstance(cur_eval, dict):
        return load_defects(root)
    cur_iter = int(cur_eval.get("iteration") or 1)
    now_iso = dlc.utc_now_iso(deterministic)

    # Collect chronological evaluation snapshots (iter-1 .. cur_iter) from test/.snapshots and test/history
    eval_by_iter: dict[int, dict[str, Any]] = {}
    for base_d in (root / "test" / ".snapshots", root / "test" / "history"):
        if base_d.is_dir():
            for snap_p in sorted(base_d.glob("iter-*/eval_results.json")):
                m_it = re.search(r"iter-(\d+)", snap_p.parent.name)
                it_num = int(m_it.group(1)) if m_it else 1
                if it_num in eval_by_iter:
                    continue
                try:
                    ed = dlc.read_json(snap_p)
                    if isinstance(ed, dict):
                        eval_by_iter[it_num] = ed
                except Exception:
                    pass
    eval_by_iter.setdefault(cur_iter, cur_eval)
    eval_history: list[tuple[int, dict[str, Any]]] = sorted(eval_by_iter.items(), key=lambda x: x[0])

    # Build lookup of test cases -> parent storyRef
    tc_by_id: dict[str, dict[str, Any]] = {}
    tc_p = root / "test" / "test_cases.json"
    if tc_p.is_file():
        tc_doc = dlc.read_json(tc_p)
        if isinstance(tc_doc, dict):
            for t in tc_doc.get("testCases") or []:
                if isinstance(t, dict) and t.get("id"):
                    tc_by_id[str(t["id"])] = t

    story_by_id = {str(s["id"]): s for s in stories if s.get("id")}
    default_tech_story = next((str(s["id"]) for s in stories if str(s.get("id", "")).startswith("US-TECH")), next(iter(story_by_id), "US-FUNC-01"))

    def _resolve_story_for_tc(tid: str, res_obj: dict[str, Any]) -> str:
        sref = str(res_obj.get("storyRef") or tc_by_id.get(tid, {}).get("storyRef") or "").strip()
        if sref and sref in story_by_id:
            return sref
        tc_reqs = set(tc_by_id.get(tid, {}).get("requirementRefs") or [])
        if tc_reqs:
            for s in stories:
                if set(s.get("requirementRefs") or []) & tc_reqs:
                    return str(s["id"])
        return default_tech_story

    existing_defects = load_defects(root)
    defect_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    next_bug_num = 1
    for d in existing_defects:
        m_num = re.match(r"^BUG-(\d+)$", str(d.get("id") or ""))
        if m_num:
            next_bug_num = max(next_bug_num, int(m_num.group(1)) + 1)
        f_tcs = d.get("failingTestCases") or []
        first_tc = str(f_tcs[0].get("id")) if f_tcs and isinstance(f_tcs[0], dict) else ""
        if d.get("storyRef") and first_tc:
            defect_by_key[(str(d["storyRef"]), first_tc)] = d

    # Process each evaluation snapshot in chronological order
    for it_num, ed in eval_history:
        results = [r for r in (ed.get("results") or ed.get("testResults") or []) if isinstance(r, dict) and r.get("id")]
        res_by_id = {str(r["id"]): r for r in results}

        # 1. Create or update defects for any non-optional FAIL / ERROR test cases in this iteration
        for r in results:
            if r.get("optional") or r.get("deferredByGroupSelection"):
                continue
            st = str(r.get("status") or "").strip().upper()
            if st not in ("FAIL", "ERROR"):
                continue
            tid = str(r["id"])
            sref = _resolve_story_for_tc(tid, r)
            parent_story = story_by_id.get(sref, {})
            key = (sref, tid)
            tc_meta = tc_by_id.get(tid, {})
            fail_entry = {
                "id": tid,
                "category": str(r.get("category") or tc_meta.get("category") or "Functional"),
                "title": str(r.get("title") or tc_meta.get("title") or tid),
                "failedStep": r.get("failedStep"),
                "expected": str(r.get("expected") or tc_meta.get("expected") or "Test case should pass"),
                "actual": str(r.get("actual") or r.get("message") or "Test failed"),
                "message": str(r.get("message") or "Assertion failed"),
                "status": st,
            }
            what_desc = (
                f"During Stage 6 closed-loop evaluation (Iteration {it_num}), test case `{tid}` "
                f"({fail_entry['category']} — {fail_entry['title']}) failed against story `{sref}` "
                f"({parent_story.get('title', '')}).\n"
                f"- Failed Step: {fail_entry['failedStep'] if fail_entry['failedStep'] is not None else 'n/a'}\n"
                f"- Expected Behavior: {fail_entry['expected']}\n"
                f"- Actual Observed Behavior: {fail_entry['actual']}\n"
                f"- Failure Diagnostic Message: {fail_entry['message']}"
            )
            if key not in defect_by_key:
                bug_id = f"BUG-{next_bug_num:02d}"
                next_bug_num += 1
                tr_story = parent_story.get("traceability") or {}
                defect_by_key[key] = {
                    "id": bug_id,
                    "issueType": "Bug",
                    "title": f"Defect in {sref} ({tid}): {fail_entry['title'][:80]} — {fail_entry['message'][:90]}",
                    "storyRef": sref,
                    "capabilityGroup": str(parent_story.get("capabilityGroup") or "SHARED"),
                    "sprint": sprint_label(parent_story) or "Sprint 1",
                    "priority": "High",
                    "status": "In Progress",
                    "detectedInIteration": it_num,
                    "resolvedInIteration": None,
                    "whatWasTheBug": what_desc,
                    "rootCause": f"{tid} ({fail_entry['category']}): {fail_entry['message']}",
                    "failingTestCases": [fail_entry],
                    "traceability": {
                        "storyRef": sref,
                        "requirementRefs": list(parent_story.get("requirementRefs") or []),
                        "businessRuleRefs": list(parent_story.get("businessRuleRefs") or []),
                        "legacySourceArtifacts": list(parent_story.get("legacyArtifactsReplaced") or tr_story.get("legacySourceArtifacts") or []),
                        "apiContracts": list(tr_story.get("apiContracts") or []),
                        "databaseTables": list(tr_story.get("databaseTables") or []),
                        "targetSourceFiles": list(tr_story.get("targetSourceFiles") or []),
                        "testCaseIds": [tid],
                    },
                    "remediationComments": [],
                    "jiraKey": None,
                    "adoWorkItemId": None,
                }
            else:
                bug = defect_by_key[key]
                bug["status"] = "In Progress"
                bug["resolvedInIteration"] = None
                bug["failingTestCases"] = [fail_entry]

        # 2. Check if any previously open defect is now FIXED (PASS) in this iteration
        for key, bug in defect_by_key.items():
            f_tcs = bug.get("failingTestCases") or []
            if not f_tcs:
                continue
            all_now_passing = True
            for ft in f_tcs:
                cur_r = res_by_id.get(str(ft.get("id")))
                if not cur_r or str(cur_r.get("status") or "").strip().upper() != "PASS":
                    all_now_passing = False
                    break
            if all_now_passing and bug.get("status") != "Done":
                det_iter = int(bug.get("detectedInIteration") or max(1, it_num - 1))
                steps_taken, files_mod, diff_sum = compute_snapshot_diff_steps(root, det_iter, it_num)
                tc_ids_str = ", ".join(str(ft.get("id")) for ft in f_tcs)
                full_steps = [
                    f"Diagnosed defect {bug['id']} in Iteration {det_iter}: {bug.get('rootCause', '')}",
                    *steps_taken,
                    f"Re-executed Stage 6 automated test suite in Iteration {it_num}: verified `{tc_ids_str}` transitioned from FAIL -> PASS.",
                ]
                already_has_iter = any(int(c.get("iteration") or 0) == it_num for c in (bug.get("remediationComments") or []))
                if not already_has_iter:
                    bug.setdefault("remediationComments", []).append({
                        "iteration": it_num,
                        "createdAtUtc": now_iso,
                        "author": "Stage 6 Self-Healing Agent (07-test-runner-and-healer)",
                        "summary": f"Defect {bug['id']} resolved in Iteration {it_num}; verified by {tc_ids_str} passing.",
                        "stepsTaken": full_steps,
                        "filesModified": files_mod,
                        "diffSummary": diff_sum,
                        "verificationResult": f"PASS — {tc_ids_str} passed in Stage 6 Iteration {it_num} with zero regressions.",
                        "jiraCommentId": None,
                        "adoCommentSynced": False,
                    })
                for ft in f_tcs:
                    ft["status"] = "PASS"
                bug["status"] = "Done"
                bug["resolvedInIteration"] = it_num

    all_defects = sorted(defect_by_key.values(), key=lambda d: str(d.get("id") or ""))
    # Refresh traceability on each defect now that stories have traceability
    for bug in all_defects:
        ps = story_by_id.get(str(bug.get("storyRef") or ""), {})
        tr_s = ps.get("traceability") or {}
        if tr_s:
            bug["traceability"]["apiContracts"] = list(tr_s.get("apiContracts") or [])
            bug["traceability"]["databaseTables"] = list(tr_s.get("databaseTables") or [])
            bug["traceability"]["targetSourceFiles"] = list(tr_s.get("targetSourceFiles") or [])

    write_defects_artifacts(root, all_defects, deterministic, cur_iter)
    return all_defects


def write_defects_artifacts(root: Path, defects: list[dict[str, Any]], deterministic: bool, iteration: int | None = None) -> None:
    """Write backlog/defects.json and backlog/defects.md, plus non-overwritten per-iteration copies."""
    out_dir = root / "backlog"
    out_dir.mkdir(parents=True, exist_ok=True)
    open_cnt = sum(1 for d in defects if d.get("status") != "Done")
    resolved_cnt = sum(1 for d in defects if d.get("status") == "Done")
    doc = {
        "schemaVersion": dlc.SCHEMA_VERSION,
        "updatedAtUtc": dlc.utc_now_iso(deterministic),
        "iteration": iteration,
        "totalDefects": len(defects),
        "openDefects": open_cnt,
        "resolvedDefects": resolved_cnt,
        "defects": defects,
    }
    dlc.write_json(out_dir / "defects.json", doc)

    lines = [
        "# Stage 6 Automated Defect Log & Self-Healing Audit Trail (`backlog/defects.md`)",
        "",
        f"- **Updated:** `{doc['updatedAtUtc']}`",
        f"- **Total Defects Tracked:** `{len(defects)}` (`{open_cnt}` Open / In Progress, `{resolved_cnt}` Resolved / Done)",
        "",
    ]
    if not defects:
        lines += [
            "> Zero defects detected during Stage 6 closed-loop evaluation.",
            "",
        ]
    else:
        lines += [
            "| Defect ID | Issue Type | Linked Story | Failing Test(s) | Status | Detected Iter | Resolved Iter | Jira Key / ADO ID |",
            "| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |",
        ]
        for d in defects:
            tcs = ", ".join(f"`{t['id']}`" for t in (d.get("failingTestCases") or []))
            alm_ref = d.get("jiraKey") or (f"#{d['adoWorkItemId']}" if d.get("adoWorkItemId") else "—")
            lines.append(
                f"| `{d['id']}` | `{d.get('issueType', 'Bug')}` | `{d.get('storyRef', '')}` | {tcs} | "
                f"**{d.get('status', 'In Progress')}** | Iter {d.get('detectedInIteration', 1)} | "
                f"{'Iter ' + str(d['resolvedInIteration']) if d.get('resolvedInIteration') else '—'} | `{alm_ref}` |"
            )
        lines.append("")
        for d in defects:
            tr = d.get("traceability") or {}
            lines += [
                f"## `[{d['id']}]` {d.get('title', '')}",
                "",
                f"- **Issue Type:** `Bug`",
                f"- **Status:** `{d.get('status', 'In Progress')}`",
                f"- **Linked User Story:** `{d.get('storyRef', '')}` (`{d.get('sprint', '')}`)",
                f"- **Traceability:** Reqs: `{', '.join(tr.get('requirementRefs') or []) or '—'}` | "
                f"Rules: `{', '.join(tr.get('businessRuleRefs') or []) or '—'}` | "
                f"Source Files: `{', '.join(tr.get('targetSourceFiles') or []) or '—'}` | "
                f"Tests: `{', '.join(tr.get('testCaseIds') or []) or '—'}`",
                "",
                "### What the Bug Was",
                d.get("whatWasTheBug", ""),
                "",
            ]
            comments = d.get("remediationComments") or []
            if comments:
                lines += ["### Remediation Steps & Resolution Comments", ""]
                for c in comments:
                    lines += [
                        f"#### Resolved in Iteration {c.get('iteration')} (`{c.get('createdAtUtc', '')}`)",
                        f"- **Verification Result:** {c.get('verificationResult', '')}",
                        "- **Steps Taken to Fix the Defect:**",
                    ]
                    for st in c.get("stepsTaken") or []:
                        lines.append(f"  - {st}")
                    if c.get("diffSummary"):
                        lines += ["", "```diff", c["diffSummary"], "```"]
                    lines.append("")
    md_text = "\n".join(lines)
    dlc.write_text(out_dir / "defects.md", md_text)
    if iteration is not None and iteration >= 1:
        for archive_d in (
            root / "test" / "history" / f"iter-{iteration}",
            root / "test" / ".snapshots" / f"iter-{iteration}",
            root / "backlog" / "history" / f"iter-{iteration}",
        ):
            archive_d.mkdir(parents=True, exist_ok=True)
            dlc.write_json(archive_d / "defects.json", doc)
            dlc.write_text(archive_d / "defects.md", md_text)
        for numbered_d in (root / "test", root / "backlog"):
            if numbered_d.is_dir():
                dlc.write_json(numbered_d / f"defects.iter-{iteration:02d}.json", doc)
                dlc.write_text(numbered_d / f"defects.iter-{iteration:02d}.md", md_text)


def pack_stories_into_sprints(
    stories_list: list[dict[str, Any]],
    effective_groups: list[str],
    select_all: bool,
    selected_list: list[str],
    capacity_points: int = 21,
) -> dict[str, list[str]]:
    """Assign stories to Sprint 1..N dynamically based on capability-group topological order and velocity capacity
    (`capacity_points` SP per sprint, default 21 SP) — never hardcoded to 3 sprints."""
    cap = max(8, int(capacity_points)) if capacity_points and capacity_points > 0 else 10_000
    foundation: list[dict[str, Any]] = []
    by_group: dict[str, list[dict[str, Any]]] = {g: [] for g in effective_groups}
    other_active: list[dict[str, Any]] = []

    for s in stories_list:
        cg = str(s.get("capabilityGroup") or "").strip().upper()
        stype = str(s.get("type") or "").strip().lower()
        sid = str(s.get("id") or "").strip().upper()
        if cg == "SHARED" or stype == "technical" or sid.startswith("US-TECH"):
            foundation.append(s)
        elif cg in by_group:
            by_group[cg].append(s)
        elif select_all:
            other_active.append(s)
        else:
            s["sprint"] = "Product Backlog"
            s["status"] = "To Do"
            s["statusReason"] = f"Deferred — capability group {cg} not in selectedCapabilityGroups ({', '.join(selected_list)})"

    sprint_num = 1
    cur_points = 0.0
    group_sprints: dict[str, list[str]] = {}

    # 1. Pack shared technical foundation stories starting in Sprint 1
    for s in foundation:
        sp = story_points(s) or 5.0
        if cur_points > 0 and (cur_points + sp) > cap:
            sprint_num += 1
            cur_points = 0.0
        s["sprint"] = f"Sprint {sprint_num}"
        cur_points += sp
        group_sprints.setdefault("SHARED", [])
        if s["sprint"] not in group_sprints["SHARED"]:
            group_sprints["SHARED"].append(s["sprint"])

    # 2. Pack each capability group in topological prerequisite-first order.
    # The first capability group shares Sprint 1 with foundation stories if capacity permits;
    # each subsequent capability group starts on a new sprint boundary and spans as many sprints (Sprint k..m) as its story points require.
    for idx, g in enumerate(effective_groups):
        g_stories = by_group.get(g) or []
        if not g_stories:
            continue
        if idx > 0 and cur_points > 0:
            sprint_num += 1
            cur_points = 0.0
        for s in g_stories:
            sp = story_points(s) or 5.0
            if cur_points > 0 and (cur_points + sp) > cap:
                sprint_num += 1
                cur_points = 0.0
            lbl = f"Sprint {sprint_num}"
            s["sprint"] = lbl
            cur_points += sp
            group_sprints.setdefault(g, [])
            if lbl not in group_sprints[g]:
                group_sprints[g].append(lbl)

    # 3. Any remaining active stories when select_all is true
    for s in other_active:
        sp = story_points(s) or 5.0
        if cur_points > 0 and (cur_points + sp) > cap:
            sprint_num += 1
            cur_points = 0.0
        s["sprint"] = f"Sprint {sprint_num}"
        cur_points += sp

    return group_sprints


def persist_stories_metadata(root: Path, stories: list[dict[str, Any]], deterministic: bool) -> None:
    """Persist mutable ALM fields (sprint, capabilityGroup, status, traceability, jiraKey, adoWorkItemId) to
    backlog/user_stories.json while keeping test/test_cases.json#derivedFrom.userStoriesSha256 synchronized."""
    stories_path = root / "backlog" / "user_stories.json"
    if not stories_path.is_file():
        return
    old_sha = dlc.sha256_file(stories_path)
    data = dlc.read_json(stories_path)
    if isinstance(data, dict) and isinstance(data.get("stories"), list):
        by_id = {s["id"]: s for s in stories if s.get("id")}
        for orig in data["stories"]:
            if not isinstance(orig, dict):
                continue
            src = by_id.get(orig.get("id"), {})
            for k in ("sprint", "capabilityGroup", "capabilityGroupName", "status", "statusReason",
                      "statusUpdatedAtUtc", "jiraKey", "adoWorkItemId", "traceability"):
                if k in src:
                    orig[k] = src[k]
        dlc.write_json(stories_path, data)
        new_sha = dlc.sha256_file(stories_path)
        tc_path = root / "test" / "test_cases.json"
        if new_sha != old_sha and tc_path.is_file():
            tc_doc = dlc.read_json(tc_path)
            if isinstance(tc_doc, dict) and isinstance(tc_doc.get("derivedFrom"), dict):
                if tc_doc["derivedFrom"].get("userStoriesSha256") == old_sha:
                    tc_doc["derivedFrom"]["userStoriesSha256"] = new_sha
                    dlc.write_json(tc_path, tc_doc)


def story_search_text(story: dict[str, Any]) -> str:
    """All text in which requirement / business-rule references may legitimately appear."""
    parts = [str(story.get("title", "")), str(story.get("narrative", ""))]
    parts += [str(x) for x in story.get("requirementRefs", [])]
    parts += [str(x) for x in story.get("businessRuleRefs", [])]
    parts += [ac_to_text(a) for a in story_acs(story)]
    return "\n".join(parts)


# ======================================================================================
# Section 2 — Gate 3 audit (no network)
# ======================================================================================
def spec_requirement_ids(root: Path) -> tuple[list[str], list[str]]:
    """REQ ids from specs/application_spec.md plus specs/.spec_index.json (if present). Returns (ids, sources)."""
    spec_md = dlc.load_spec(root)
    ids: dict[str, None] = {}
    sources = ["specs/application_spec.md"]
    for prefix in REQ_PREFIXES:
        for rid in dlc.extract_ids(spec_md, prefix):
            ids.setdefault(rid, None)
    index_path = root / "specs" / ".spec_index.json"
    if index_path.is_file():
        try:
            index_text = json.dumps(dlc.read_json(index_path))
            for prefix in REQ_PREFIXES:
                for rid in dlc.extract_ids(index_text, prefix):
                    ids.setdefault(rid, None)
            sources.append("specs/.spec_index.json")
        except SystemExit:
            dlc.warn(f"{index_path} is not valid JSON — ignored for coverage.")
    return list(ids), sources


def spec_business_rule_ids(root: Path) -> list[str]:
    spec_md = dlc.load_spec(root)
    ids = [r["id"] for r in dlc.parse_business_rules(spec_md) if r.get("id")]
    if not ids:
        section = dlc.md_section(spec_md, r"business rules") or spec_md
        ids = dlc.extract_ids(section, "BR-")
    return ids


def audit_backlog(root: Path, stories: list[dict[str, Any]], allow_partial_coverage: bool = False) -> dict[str, Any]:
    """Gate 3 audit. `failures` block sync; `warnings` do not."""
    failures: list[str] = []
    warnings: list[str] = []

    req_ids, req_sources = spec_requirement_ids(root)
    br_ids = spec_business_rule_ids(root)
    if not req_ids:
        failures.append("specs/application_spec.md contains no REQ-FUNC/ENH/SEC/A11Y/UX/ARCH ids — Stage 2 must author them (docs/ARCHITECTURE.md §4.3).")

    covered_reqs: dict[str, list[str]] = {}
    covered_brs: dict[str, list[str]] = {}
    per_story: list[dict[str, Any]] = []
    sprints_seen: set[str] = set()
    backlog_count = 0
    is_all, selected_groups = dlc.active_capability_groups(root)
    groups_seen: dict[str, int] = {}

    for s in stories:
        sid = str(s.get("id") or "").strip()
        if not sid:
            failures.append("A story has no 'id'.")
            continue
        cg = str(s.get("capabilityGroup") or "").strip().upper()
        if cg:
            groups_seen[cg] = groups_seen.get(cg, 0) + 1
        text = story_search_text(s)
        refs = {r for p in REQ_PREFIXES for r in dlc.extract_ids(text, p)}
        for r in refs:
            covered_reqs.setdefault(r, []).append(sid)
        brs = set(dlc.extract_ids(text, "BR-"))
        for b in brs:
            covered_brs.setdefault(b, []).append(sid)

        sp = story_points(s)
        if sp is None:
            failures.append(f"{sid}: storyPoints missing or non-numeric (must be 1..{MAX_STORY_POINTS}).")
        elif sp > MAX_STORY_POINTS:
            failures.append(f"{sid}: {sp:g} SP exceeds the {MAX_STORY_POINTS} SP maximum — split the story.")

        acs = story_acs(s)
        if len(acs) < MIN_ACS_PER_STORY:
            warnings.append(f"{sid}: only {len(acs)} acceptance criteria (expected >= {MIN_ACS_PER_STORY}).")
        if not any("NEGATIVE" in (a.get("tag") or "").upper() for a in acs):
            warnings.append(f"{sid}: no NEGATIVE-tagged acceptance criterion.")

        label = sprint_label(s)
        if not label:
            failures.append(f"{sid}: no 'sprint' field (use 'Sprint N' or 'Product Backlog').")
        elif is_product_backlog(label):
            backlog_count += 1
            if not is_all and cg and cg in selected_groups:
                warnings.append(f"{sid}: belongs to selected capabilityGroup '{cg}' but is in Product Backlog instead of an active Sprint.")
        else:
            if not SPRINT_LABEL_RE.match(label):
                warnings.append(f"{sid}: sprint label '{label}' does not start with 'Sprint N'.")
            sprints_seen.add(sprint_short_name(label))
            if not is_all and cg and cg != "SHARED" and cg not in selected_groups:
                failures.append(f"{sid}: belongs to unselected capabilityGroup '{cg}' (selected: {sorted(selected_groups)}) but is assigned to '{label}' instead of 'Product Backlog'.")

        unknown_refs = sorted(r for r in refs if req_ids and r not in req_ids)
        if unknown_refs:
            warnings.append(f"{sid}: references requirement ids not found in the spec: {', '.join(unknown_refs)}.")
        per_story.append({
            "id": sid,
            "capabilityGroup": cg or None,
            "storyPoints": sp,
            "acCount": len(acs),
            "negativeAcCount": sum(1 for a in acs if "NEGATIVE" in (a.get("tag") or "").upper()),
            "requirementRefs": sorted(refs),
            "businessRuleRefs": sorted(brs),
            "sprint": label,
        })

    if not sprints_seen:
        failures.append("No story is assigned to a 'Sprint N' — at least one Release 1 sprint is required.")

    # Verify prerequisite group ordering (dependsOnGroups & isSharedFoundation)
    group_defs = dlc.capability_group_definitions(root)
    group_min_sprint: dict[str, int] = {}
    for p in per_story:
        cg = p.get("capabilityGroup")
        sp_lbl = str(p.get("sprint") or "")
        m_sp = SPRINT_LABEL_RE.match(sp_lbl)
        if cg and m_sp:
            sp_num = int(m_sp.group(1))
            group_min_sprint[cg] = min(sp_num, group_min_sprint.get(cg, sp_num))
    for cg, sp_num in sorted(group_min_sprint.items()):
        for dep in (group_defs.get(cg) or {}).get("dependsOnGroups") or []:
            dep_u = str(dep).strip().upper()
            if dep_u not in group_min_sprint and groups_seen.get(dep_u, 0) > 0:
                failures.append(f"Capability group '{cg}' (in Sprint {sp_num}) depends on prerequisite group '{dep_u}', "
                                f"but '{dep_u}' has no stories in an active Sprint (all are in Product Backlog).")
            elif dep_u in group_min_sprint and group_min_sprint[dep_u] > sp_num:
                warnings.append(f"Capability group '{cg}' is scheduled in Sprint {sp_num} before its prerequisite group '{dep_u}' (Sprint {group_min_sprint[dep_u]}) — prerequisite groups should be built in Sprint 1 / earlier sprints.")

    missing_reqs = [r for r in req_ids if r not in covered_reqs]
    missing_brs = [b for b in br_ids if b not in covered_brs]
    if missing_reqs:
        msg = f"{len(missing_reqs)} requirement id(s) have no story: {', '.join(missing_reqs)}."
        if allow_partial_coverage:
            warnings.append("[allowed by --allow-partial-coverage] " + msg)
        else:
            failures.append(msg)
    if missing_brs:
        warnings.append(f"{len(missing_brs)} business rule(s) not referenced by any story: {', '.join(missing_brs)}.")

    coverage_pct = 100.0 if not req_ids else round(100.0 * (len(req_ids) - len(missing_reqs)) / len(req_ids), 1)
    return {
        "requirementSources": req_sources,
        "specRequirementsFound": req_ids,
        "coveredRequirements": sorted(covered_reqs),
        "missingRequirements": missing_reqs,
        "coveragePercent": coverage_pct,
        "businessRulesFound": br_ids,
        "missingBusinessRules": missing_brs,
        "maxStoryPoints": MAX_STORY_POINTS,
        "oversizedStories": [p["id"] for p in per_story if p["storyPoints"] is not None and p["storyPoints"] > MAX_STORY_POINTS],
        "storiesBelowMinAcs": [p["id"] for p in per_story if p["acCount"] < MIN_ACS_PER_STORY],
        "storiesWithoutNegativeAc": [p["id"] for p in per_story if p["negativeAcCount"] == 0],
        "release1Sprints": sorted(sprints_seen, key=sprint_sort_key),
        "productBacklogStories": backlog_count,
        "selectedCapabilityGroups": ["ALL"] if is_all else sorted(selected_groups),
        "capabilityGroupsStoryCounts": groups_seen,
        "allowPartialCoverage": allow_partial_coverage,
        "perStory": per_story,
        "warnings": warnings,
        "failures": failures,
        "passed": not failures,
    }


def print_audit(audit: dict[str, Any]) -> None:
    print(f"[audit] requirements: {len(audit['specRequirementsFound'])} in spec, coverage {audit['coveragePercent']}%"
          f" (missing: {len(audit['missingRequirements'])}); business rules: {len(audit['businessRulesFound'])}"
          f" (unreferenced: {len(audit['missingBusinessRules'])})")
    print(f"[audit] sprints: {', '.join(audit['release1Sprints']) or '-'}; product backlog stories: {audit['productBacklogStories']}")
    for w in audit["warnings"]:
        print(f"[audit][WARN] {w}")
    for f in audit["failures"]:
        print(f"[audit][FAIL] {f}")
    print(f"[audit] verdict: {'PASS' if audit['passed'] else 'FAIL'}")


# ======================================================================================
# Section 3 — sprint plan summary, approval status, local exports
# ======================================================================================
def read_sprint_plan_json(root: Path) -> dict[str, Any]:
    p = root / "backlog" / "sprint_plan.json"
    if p.is_file():
        data = dlc.read_json(p)
        if isinstance(data, dict):
            return data
    return {}


def current_approval_status(root: Path) -> str:
    """Approval status from sprint_plan.json, else from the SPRINT_ALIGNMENT_APPROVAL line in sprint_plan.md."""
    status = str(read_sprint_plan_json(root).get("approvalStatus", "")).strip().upper()
    if status in APPROVAL_STATES:
        return status
    md = root / "backlog" / "sprint_plan.md"
    if md.is_file():
        m = re.search(r"SPRINT_ALIGNMENT_APPROVAL\**:\**\s*`?\s*([A-Z_]+)", dlc.read_text(md))
        if m and m.group(1) in APPROVAL_STATES:
            return m.group(1)
    return "PENDING_HUMAN_APPROVAL"


def build_sprint_plan_summary(stories: list[dict[str, Any]], audit: dict[str, Any], approval_status: str,
                              platform: str, deterministic: bool) -> dict[str, Any]:
    sprints: dict[str, dict[str, Any]] = {}
    backlog: list[str] = []
    by_id = {s["id"]: s for s in stories}
    for s in stories:
        label = sprint_label(s)
        if is_product_backlog(label):
            backlog.append(s["id"])
            continue
        name = sprint_short_name(label) if label else "UNASSIGNED"
        entry = sprints.setdefault(name, {"name": name, "fullLabel": label, "storyIds": [], "totalPoints": 0})
        entry["storyIds"].append(s["id"])
        entry["totalPoints"] += story_points(s) or 0
    ordered = sorted(sprints.values(), key=lambda e: sprint_sort_key(e["name"]))
    for e in ordered:
        e["totalPoints"] = int(e["totalPoints"]) if float(e["totalPoints"]).is_integer() else e["totalPoints"]
        e["storyStatuses"] = {sid: story_status(by_id[sid]) for sid in e["storyIds"] if sid in by_id}
    return {
        "schemaVersion": dlc.SCHEMA_VERSION,
        "generatedAtUtc": dlc.utc_now_iso(deterministic),
        "approvalStatus": approval_status,
        "selectedPlatform": platform,
        "totalStories": len(stories),
        "functionalStories": sum(1 for s in stories if "functional" in story_type_label(s).lower()),
        "technicalStories": sum(1 for s in stories if "technical" in story_type_label(s).lower()),
        "totalStoryPoints": sum(story_points(s) or 0 for s in stories),
        "totalAcceptanceCriteria": sum(len(story_acs(s)) for s in stories),
        "storyStatusCounts": story_status_counts(stories),
        "sprints": ordered,
        "productBacklog": backlog,
        "coverage": {k: v for k, v in audit.items() if k != "perStory"},
    }


def write_sprint_plan_json(path: Path, summary: dict[str, Any]) -> Path:
    """Write sprint_plan.json, carrying over the last live-sync pointers when this run did not sync."""
    if path.is_file():
        previous = dlc.read_json(path)
        if isinstance(previous, dict):
            for key in ("jira", "azureDevOps"):
                if key in previous and key not in summary:
                    summary[key] = previous[key]
    dlc.write_json(path, summary)
    return path


def set_approval_status(root: Path, status: str, deterministic: bool) -> list[str]:
    """Update approvalStatus in sprint_plan.json and the SPRINT_ALIGNMENT_APPROVAL line in sprint_plan.md."""
    if status not in APPROVAL_STATES:
        raise dlc.GateFailure(f"Unknown approval status '{status}'. Use one of: {', '.join(APPROVAL_STATES)}")
    touched: list[str] = []
    plan_path = root / "backlog" / "sprint_plan.json"
    plan = read_sprint_plan_json(root)
    plan["approvalStatus"] = status
    plan["approvalUpdatedAtUtc"] = dlc.utc_now_iso(deterministic)
    plan.setdefault("schemaVersion", dlc.SCHEMA_VERSION)
    dlc.write_json(plan_path, plan)
    touched.append(str(plan_path))

    md_path = root / "backlog" / "sprint_plan.md"
    if md_path.is_file():
        text = dlc.read_text(md_path)
        line_re = re.compile(r"^(?P<prefix>.*?SPRINT_ALIGNMENT_APPROVAL\**:\**[ \t]*)(?P<value>.*)$", re.MULTILINE)
        if line_re.search(text):
            def _repl(m: re.Match[str]) -> str:
                value = f"`{status}`" if m.group("value").lstrip().startswith("`") else status
                return m.group("prefix") + value
            text = line_re.sub(_repl, text, count=1)
        else:
            lines = text.splitlines()
            insert_at = 1 if lines and lines[0].startswith("#") else 0
            lines.insert(insert_at, f"\n- **SPRINT_ALIGNMENT_APPROVAL:** `{status}`")
            text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
        dlc.write_text(md_path, text)
        touched.append(str(md_path))
    return touched


def write_jira_csv(stories: list[dict[str, Any]], csv_path: Path, project_key: str | None,
                   defects: list[dict[str, Any]] | None = None) -> Path:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Issue Type", "Summary", "Description", "Status", "Priority", "Story Points", "Acceptance Criteria Count",
                    "Sprint", "Capability Group", "Requirement Refs", "Business Rule Refs", "Legacy Artifacts Replaced",
                    "Design Contracts (API/DB)", "Target Source Files", "Linked Test Cases", "Linked Defects",
                    "Labels", "Project Key"])
        for s in stories:
            acs = story_acs(s)
            tr = s.get("traceability") or {}
            tr_block = "\n".join(f"- {ln}" for ln in traceability_bullet_lines(s))
            desc = (
                f"{s.get('narrative', '')}\n\n"
                f"Acceptance Criteria ({len(acs)}):\n" + "\n".join(f"- {ac_to_text(a)}" for a in acs) +
                (f"\n\nEnd-to-End Traceability Matrix:\n{tr_block}" if tr_block else "")
            )
            labels = " ".join(jira_labels(s))
            contracts = ", ".join((tr.get("apiContracts") or []) + [f"table:{tb}" for tb in (tr.get("databaseTables") or [])])
            target_files = ", ".join(tr.get("targetSourceFiles") or [])
            linked_tcs = ", ".join(f"{t['id']}:{t.get('status', 'NOT_RUN')}" for t in (tr.get("testCases") or []) if isinstance(t, dict) and t.get("id"))
            linked_bugs = ", ".join(tr.get("defectRefs") or [])
            w.writerow(["Story", f"[{s['id']}] {s.get('title', '')}", desc, story_status(s), s.get("priority", "Medium"),
                        story_points(s) if story_points(s) is not None else "", len(acs), sprint_label(s),
                        s.get("capabilityGroup", ""),
                        ", ".join(s.get("requirementRefs", [])), ", ".join(s.get("businessRuleRefs", [])),
                        ", ".join(s.get("legacyArtifactsReplaced", [])),
                        contracts, target_files, linked_tcs, linked_bugs,
                        labels, project_key or ""])
        for bug in defects or []:
            tr_b = bug.get("traceability") or {}
            rem_lines = []
            for c in bug.get("remediationComments") or []:
                rem_lines.append(f"Resolved in Iteration {c.get('iteration')}: {c.get('verificationResult', '')}")
                for st in c.get("stepsTaken") or []:
                    rem_lines.append(f"  * {st}")
            b_desc = (
                f"What the Bug Was:\n{bug.get('whatWasTheBug', '')}\n\n"
                f"Linked Story: {bug.get('storyRef', '')}\n"
                + ("\nRemediation Steps:\n" + "\n".join(rem_lines) if rem_lines else "")
            )
            b_contracts = ", ".join((tr_b.get("apiContracts") or []) + [f"table:{tb}" for tb in (tr_b.get("databaseTables") or [])])
            b_files = ", ".join(tr_b.get("targetSourceFiles") or [])
            b_tcs = ", ".join(f"{ft['id']}:{ft.get('status', 'FAIL')}" for ft in (bug.get("failingTestCases") or []) if isinstance(ft, dict) and ft.get("id"))
            w.writerow(["Bug", f"[{bug['id']}] {bug.get('title', '')}", b_desc, bug.get("status", "In Progress"),
                        bug.get("priority", "High"), "", 0, bug.get("sprint", ""), bug.get("capabilityGroup", ""),
                        ", ".join(tr_b.get("requirementRefs") or []), ", ".join(tr_b.get("businessRuleRefs") or []),
                        ", ".join(tr_b.get("legacySourceArtifacts") or []),
                        b_contracts, b_files, b_tcs, bug.get("storyRef", ""),
                        f"Bug {bug.get('storyRef', '')}".strip(), project_key or ""])
    return csv_path


def jira_labels(story: dict[str, Any]) -> list[str]:
    def clean(x: str) -> str:
        return re.sub(r"[^A-Za-z0-9_-]+", "_", x).strip("_")
    labels = [clean(story_type_label(story))]
    cg = str(story.get("capabilityGroup") or "").strip()
    if cg:
        labels.append(clean(cg))
    label = sprint_label(story)
    if label:
        labels.append(clean("Product_Backlog" if is_product_backlog(label) else sprint_short_name(label)))
    return [l for l in dict.fromkeys(labels) if l]


def traceability_bullet_lines(story: dict[str, Any]) -> list[str]:
    """Return human-readable traceability lines for a story (used in Jira ADF, ADO HTML, and CSV)."""
    tr = story.get("traceability") or {}
    cg = str(story.get("capabilityGroup") or "SHARED")
    cg_name = str(story.get("capabilityGroupName") or "").strip()
    cg_label = f"{cg} — {cg_name}" if cg_name else cg
    legacy = ", ".join(tr.get("legacySourceArtifacts") or story.get("legacyArtifactsReplaced") or []) or "Greenfield / BRD specification"
    reqs = ", ".join(tr.get("requirementRefs") or story.get("requirementRefs") or []) or "n/a"
    brs = ", ".join(tr.get("businessRuleRefs") or story.get("businessRuleRefs") or []) or "n/a"
    trans = ", ".join(tr.get("workflowTransitions") or story.get("workflowTransitions") or []) or "n/a"
    apis = ", ".join(tr.get("apiContracts") or []) or "n/a"
    tbls = ", ".join(tr.get("databaseTables") or []) or "n/a"
    src_files = ", ".join(tr.get("targetSourceFiles") or []) or "Pending Stage 5 build"
    testids = ", ".join(tr.get("uiTestIds") or []) or "n/a"
    tcs = ", ".join(
        f"{t['id']} [{t.get('category', 'Test')}: {t.get('status', 'NOT_RUN')}]"
        for t in (tr.get("testCases") or []) if isinstance(t, dict) and t.get("id")
    ) or "Pending Stage 4B test derivation"
    bugs = ", ".join(tr.get("defectRefs") or []) or "None (0 defects)"
    return [
        f"Capability Group: {cg_label}",
        f"Legacy / Input Source Artifacts: {legacy}",
        f"Requirements & Business Rules: {reqs} | Rules: {brs} | Workflow Transitions: {trans}",
        f"Architecture & Design Contracts: APIs: {apis} | DB Tables: {tbls}",
        f"Implemented Target Source Code: {src_files} | UI data-testid Hooks: {testids}",
        f"Shift-Left Test Cases & Stage 6 Status: {tcs}",
        f"Linked Stage 6 Defects (Bugs): {bugs}",
    ]


# ======================================================================================
# Section 4 — Jira Cloud client (REST v3 + Agile 1.0)
# ======================================================================================
def to_adf_document(story: dict[str, Any]) -> dict[str, Any]:
    acs = story_acs(story)
    meta = (f"Sprint: {sprint_label(story) or 'n/a'} | Capability Group: {story.get('capabilityGroup') or 'SHARED'}"
            f" | Story Points: {story_points(story) if story_points(story) is not None else 'n/a'}"
            f" | ACs: {len(acs)} | Requirements: {', '.join(story.get('requirementRefs', [])) or 'n/a'}"
            f" | Business Rules: {', '.join(story.get('businessRuleRefs', [])) or 'n/a'}")
    legacy = story.get("legacyArtifactsReplaced") or []
    if legacy:
        meta += f" | Replaces: {', '.join(legacy)}"
    text = lambda t: {"type": "text", "text": t}  # noqa: E731
    tr_lines = traceability_bullet_lines(story)
    return {
        "type": "doc", "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": f"[{story_type_label(story)}] ", "marks": [{"type": "strong"}]}, text(meta)]},
            {"type": "heading", "attrs": {"level": 3}, "content": [text("User Story")]},
            {"type": "paragraph", "content": [text(str(story.get("narrative", "")) or "(no narrative)")]},
            {"type": "heading", "attrs": {"level": 3}, "content": [text(f"Acceptance Criteria ({len(acs)})")]},
            {"type": "bulletList", "content": [
                {"type": "listItem", "content": [{"type": "paragraph", "content": [text(ac_to_text(a))]}]} for a in acs
            ] or [{"type": "listItem", "content": [{"type": "paragraph", "content": [text("(none)")]}]}]},
            {"type": "heading", "attrs": {"level": 3}, "content": [text("End-to-End Traceability Matrix (Source Code, Requirements, Design, Tests & Defects)")]},
            {"type": "bulletList", "content": [
                {"type": "listItem", "content": [{"type": "paragraph", "content": [text(ln)]}]} for ln in tr_lines
            ]},
        ],
    }


def to_bug_adf_document(bug: dict[str, Any]) -> dict[str, Any]:
    """Build Jira ADF description for an automated Stage 6 Bug issue (`BUG-01..N`)."""
    text = lambda t: {"type": "text", "text": str(t)}  # noqa: E731
    tr = bug.get("traceability") or {}
    meta = (
        f"Linked Story: {bug.get('storyRef', 'n/a')} | Sprint: {bug.get('sprint', 'n/a')} | "
        f"Capability Group: {bug.get('capabilityGroup', 'SHARED')} | "
        f"Detected in Stage 6 Iteration: {bug.get('detectedInIteration', 1)} | "
        f"Status: {bug.get('status', 'In Progress')}"
    )
    f_tcs = bug.get("failingTestCases") or []
    tc_bullets = [
        f"{ft.get('id')} ({ft.get('category', 'Test')} — {ft.get('title', '')}): "
        f"Step {ft.get('failedStep') if ft.get('failedStep') is not None else 'n/a'} | "
        f"Expected: {ft.get('expected', '')} | Actual: {ft.get('actual', '')} | Message: {ft.get('message', '')}"
        for ft in f_tcs if isinstance(ft, dict)
    ] or ["(see diagnostic details above)"]
    tr_bullets = [
        f"Parent User Story: {tr.get('storyRef') or bug.get('storyRef', 'n/a')}",
        f"Requirements & Business Rules: {', '.join(tr.get('requirementRefs') or []) or 'n/a'} | Rules: {', '.join(tr.get('businessRuleRefs') or []) or 'n/a'}",
        f"Legacy / Input Source Artifacts: {', '.join(tr.get('legacySourceArtifacts') or []) or 'n/a'}",
        f"Architecture & Design Contracts: APIs: {', '.join(tr.get('apiContracts') or []) or 'n/a'} | DB Tables: {', '.join(tr.get('databaseTables') or []) or 'n/a'}",
        f"Target Source Code Files: {', '.join(tr.get('targetSourceFiles') or []) or 'n/a'}",
        f"Failing Test Case IDs: {', '.join(tr.get('testCaseIds') or []) or 'n/a'}",
    ]
    return {
        "type": "doc", "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "[Stage 6 Automated Defect] ", "marks": [{"type": "strong"}]}, text(meta)]},
            {"type": "heading", "attrs": {"level": 3}, "content": [text("What the Bug Was (Symptom & Diagnostic Root Cause)")]},
            {"type": "paragraph", "content": [text(bug.get("whatWasTheBug") or bug.get("rootCause") or "Test failure detected during Stage 6 closed-loop evaluation.")]},
            {"type": "heading", "attrs": {"level": 3}, "content": [text(f"Failing Test Cases ({len(f_tcs)})")]},
            {"type": "bulletList", "content": [
                {"type": "listItem", "content": [{"type": "paragraph", "content": [text(b)]}]} for b in tc_bullets
            ]},
            {"type": "heading", "attrs": {"level": 3}, "content": [text("End-to-End Traceability (Story, Requirements, Contracts & Source Code)")]},
            {"type": "bulletList", "content": [
                {"type": "listItem", "content": [{"type": "paragraph", "content": [text(b)]}]} for b in tr_bullets
            ]},
        ],
    }


def to_remediation_comment_adf(bug: dict[str, Any], comment: dict[str, Any]) -> dict[str, Any]:
    """Build Jira ADF comment body detailing the steps taken to fix a Stage 6 defect."""
    text = lambda t: {"type": "text", "text": str(t)}  # noqa: E731
    steps = comment.get("stepsTaken") or ["Applied self-healing code remediation and re-verified all linked test cases."]
    files = ", ".join(comment.get("filesModified") or []) or "src/"
    content: list[dict[str, Any]] = [
        {"type": "heading", "attrs": {"level": 3}, "content": [text(f"Defect {bug.get('id')} Fixed & Verified (Stage 6 Iteration {comment.get('iteration', 1)})")]},
        {"type": "paragraph", "content": [
            {"type": "text", "text": "Verification Result: ", "marks": [{"type": "strong"}]},
            text(comment.get("verificationResult", "All linked test cases passed.")),
        ]},
        {"type": "paragraph", "content": [
            {"type": "text", "text": "Modified Source Files: ", "marks": [{"type": "strong"}]},
            text(files),
        ]},
        {"type": "heading", "attrs": {"level": 4}, "content": [text("Steps Taken to Fix the Defect")]},
        {"type": "bulletList", "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": [text(st)]}]} for st in steps
        ]},
    ]
    if comment.get("diffSummary"):
        content.append({"type": "codeBlock", "attrs": {"language": "diff"}, "content": [text(str(comment["diffSummary"])[:3500])]})
    return {"type": "doc", "version": 1, "content": content}


def to_story_traceability_comment_adf(story: dict[str, Any]) -> dict[str, Any]:
    """Build Jira ADF comment recording Stage 6 verification & end-to-end traceability on a User Story."""
    text = lambda t: {"type": "text", "text": str(t)}  # noqa: E731
    lines = traceability_bullet_lines(story)
    return {
        "type": "doc", "version": 1,
        "content": [
            {"type": "heading", "attrs": {"level": 4}, "content": [text(f"Stage 6 Verification & End-to-End Traceability ({story_status(story)})")]},
            {"type": "paragraph", "content": [text(str(story.get("statusReason") or "Updated from Stage 6 evaluation."))]},
            {"type": "bulletList", "content": [
                {"type": "listItem", "content": [{"type": "paragraph", "content": [text(ln)]}]} for ln in lines
            ]},
        ],
    }


class JiraClient:
    def __init__(self, url: str, email: str, token: str, project_key: str | None, board_id: str | None, issue_type: str = "Story"):
        self.base = url.rstrip("/")
        self.headers = {"Authorization": basic_auth_header(email, token), "Accept": "application/json", "Content-Type": "application/json"}
        self.project_key = project_key or None
        self.board_id = board_id or None
        self.issue_type = issue_type
        self.errors: list[str] = []

    # -- helpers ----------------------------------------------------------------------
    def _call(self, method: str, path: str, body: Any = None, timeout: int = 20) -> Any:
        _, data = http_json(method, f"{self.base}{path}", self.headers, body, timeout)
        return data

    def _record(self, context: str, e: Exception) -> str:
        msg = f"{context}: {e}"
        self.errors.append(msg)
        return msg

    # -- discovery --------------------------------------------------------------------
    def myself(self) -> dict[str, Any]:
        return self._call("GET", "/rest/api/3/myself", timeout=15) or {}

    def discover_project_and_board(self) -> None:
        """Validate/auto-discover the project key (single-project sites) and the first board for that project."""
        try:
            data = self._call("GET", "/rest/api/3/project/search?maxResults=100", timeout=15) or {}
            keys = [p.get("key") for p in data.get("values", []) if p.get("key")]
            if self.project_key and self.project_key not in keys:
                self.errors.append(f"Jira project key '{self.project_key}' not visible to this user (visible: {', '.join(keys) or 'none'}).")
            elif not self.project_key:
                if len(keys) == 1:
                    self.project_key = keys[0]
                    dlc.info(f"Jira project auto-discovered: {self.project_key}")
                else:
                    self.errors.append(f"Jira project key not given and could not be inferred (visible: {', '.join(keys) or 'none'}). Pass --jira-project-key or set JIRA_PROJECT_KEY.")
        except HttpError as e:
            self._record("Jira project discovery", e)
        if self.project_key and not self.board_id:
            try:
                q = urllib.parse.urlencode({"projectKeyOrId": self.project_key})
                data = self._call("GET", f"/rest/agile/1.0/board?{q}", timeout=15) or {}
                boards = data.get("values", [])
                if boards:
                    self.board_id = str(boards[0].get("id"))
                    dlc.info(f"Jira board auto-discovered: {self.board_id} ({boards[0].get('name', '')})")
                else:
                    self.errors.append(f"No Jira board found for project {self.project_key}; sprints cannot be staged (set JIRA_BOARD_ID).")
            except HttpError as e:
                self._record("Jira board discovery", e)

    def test_connection(self) -> dict[str, Any]:
        me = self.myself()
        self.discover_project_and_board()
        project: dict[str, Any] = {}
        if self.project_key:
            try:
                project = self._call("GET", f"/rest/api/3/project/{self.project_key}", timeout=15) or {}
            except HttpError as e:
                self._record("Jira project lookup", e)
        return {"platform": "jira", "connected": bool(me.get("accountId")), "jiraUrl": self.base,
                "authenticatedUser": me.get("displayName"), "accountId": me.get("accountId"),
                "projectKey": project.get("key", self.project_key), "projectName": project.get("name"),
                "boardId": self.board_id, "errors": self.errors}

    # -- issues -----------------------------------------------------------------------
    def existing_issue_map(self) -> dict[str, str]:
        """Map '[US-ID]' or '[BUG-ID]' summary prefixes to existing issue keys (idempotent upsert)."""
        jql = urllib.parse.quote(f'project = "{self.project_key}" ORDER BY created ASC')
        mapping: dict[str, str] = {}
        last_error: Exception | None = None
        for path in (f"/rest/api/3/search/jql?jql={jql}&fields=summary&maxResults=500", f"/rest/api/3/search?jql={jql}&fields=summary&maxResults=500"):
            try:
                data = self._call("GET", path, timeout=20) or {}
            except HttpError as e:
                last_error = e
                continue
            for issue in data.get("issues", []):
                m = STORY_ID_PREFIX_RE.match((issue.get("fields", {}).get("summary") or "").strip())
                if m and issue.get("key"):
                    mapping.setdefault(m.group(1), issue["key"])
            return mapping
        if last_error:
            self._record("Jira existing-issue lookup (duplicates possible)", last_error)
        return mapping

    def add_comment(self, issue_key: str, adf_body: dict[str, Any]) -> str | None:
        """Post an ADF comment to `/rest/api/3/issue/{issue_key}/comment` and return the created comment ID."""
        try:
            resp = self._call("POST", f"/rest/api/3/issue/{issue_key}/comment", {"body": adf_body}, timeout=15) or {}
            return str(resp.get("id")) if resp.get("id") else "posted"
        except HttpError as e:
            self._record(f"Jira comment on {issue_key}", e)
            return None

    def link_issue_to_story(self, bug_key: str, story_key: str) -> None:
        """Create a Jira issue link between `bug_key` and its parent `story_key` (best-effort)."""
        if not bug_key or not story_key or bug_key == story_key:
            return
        for link_type in ("Relates", "Blocks", "Problem/Incident"):
            try:
                self._call("POST", "/rest/api/3/issueLink", {
                    "type": {"name": link_type},
                    "inwardIssue": {"key": bug_key},
                    "outwardIssue": {"key": story_key},
                }, timeout=10)
                return
            except HttpError:
                continue

    def upsert_stories(self, stories: list[dict[str, Any]]) -> list[dict[str, Any]]:
        existing = self.existing_issue_map()
        results: list[dict[str, Any]] = []
        for s in stories:
            summary = f"[{s['id']}] {s.get('title', '')}"
            fields = {"summary": summary, "description": to_adf_document(s), "labels": jira_labels(s)}
            key = existing.get(s["id"]) or s.get("jiraKey")
            entry = {"storyId": s["id"], "summary": summary, "sprint": sprint_label(s), "acCount": len(story_acs(s)), "liveSynced": False}
            try:
                if key:
                    try:
                        self._call("PUT", f"/rest/api/3/issue/{key}", {"fields": fields})
                        entry.update(key=key, operation="UPDATED_EXISTING", url=f"{self.base}/browse/{key}", liveSynced=True)
                        s["jiraKey"] = key
                        results.append(entry)
                        continue
                    except HttpError as e:
                        if e.status != 404:
                            raise
                        key = None  # stale key -> create
                created = self._call("POST", "/rest/api/3/issue", {"fields": {**fields, "project": {"key": self.project_key}, "issuetype": {"name": self.issue_type}}}) or {}
                key = created.get("key")
                s["jiraKey"] = key
                entry.update(key=key, id=created.get("id"), operation="CREATED_NEW", url=f"{self.base}/browse/{key}", liveSynced=True)
            except HttpError as e:
                entry["error"] = self._record(f"Jira upsert {s['id']}", e)
            results.append(entry)
        return results

    def upsert_defects(self, defects: list[dict[str, Any]], story_key_map: dict[str, str]) -> list[dict[str, Any]]:
        """Create or update Stage 6 Bug issues (`issuetype: Bug`), link to parent Story, post fix-steps comments, and transition."""
        if not defects:
            return []
        existing = self.existing_issue_map()
        results: list[dict[str, Any]] = []
        for bug in defects:
            bid = bug["id"]
            summary = f"[{bid}] {bug.get('title', '')}"[:250]
            labels = ["Stage6_Defect", re.sub(r"[^A-Za-z0-9_-]+", "_", str(bug.get("storyRef") or "Story"))]
            fields = {"summary": summary, "description": to_bug_adf_document(bug), "labels": labels}
            key = existing.get(bid) or bug.get("jiraKey")
            entry: dict[str, Any] = {
                "defectId": bid, "issueType": "Bug", "storyRef": bug.get("storyRef"),
                "summary": summary, "status": bug.get("status", "In Progress"),
                "sprint": bug.get("sprint", ""), "liveSynced": False, "commentsPosted": 0,
            }
            try:
                if key:
                    try:
                        self._call("PUT", f"/rest/api/3/issue/{key}", {"fields": fields})
                        entry.update(key=key, operation="UPDATED_EXISTING", url=f"{self.base}/browse/{key}", liveSynced=True)
                        bug["jiraKey"] = key
                    except HttpError as e:
                        if e.status != 404:
                            raise
                        key = None
                if not key:
                    created = None
                    last_err = None
                    for type_candidate in ("Bug", "Defect", self.issue_type):
                        try:
                            created = self._call("POST", "/rest/api/3/issue", {
                                "fields": {**fields, "project": {"key": self.project_key}, "issuetype": {"name": type_candidate}}
                            }) or {}
                            entry["issueType"] = type_candidate
                            break
                        except HttpError as e:
                            last_err = e
                    if created is None and last_err is not None:
                        raise last_err
                    key = (created or {}).get("key")
                    bug["jiraKey"] = key
                    entry.update(key=key, id=(created or {}).get("id"), operation="CREATED_NEW", url=f"{self.base}/browse/{key}", liveSynced=True)
                    parent_key = story_key_map.get(str(bug.get("storyRef") or ""))
                    if key and parent_key:
                        self.link_issue_to_story(key, parent_key)

                # Post any unsynced remediation comments (steps taken to fix the defect)
                if key:
                    for c in bug.get("remediationComments") or []:
                        if not c.get("jiraCommentId"):
                            cid = self.add_comment(key, to_remediation_comment_adf(bug, c))
                            if cid:
                                c["jiraCommentId"] = cid
                                entry["commentsPosted"] = int(entry.get("commentsPosted", 0)) + 1

                    # Transition Bug status ('In Progress' when open, 'Done' when fixed)
                    pseudo_story = {"id": bid, "jiraKey": key}
                    tr_res = self.transition_stories([pseudo_story], {bid: str(bug.get("status") or "In Progress")})
                    if tr_res:
                        entry["transition"] = tr_res[0]
            except HttpError as e:
                entry["error"] = self._record(f"Jira defect upsert {bid}", e)
            results.append(entry)
        return results

    # -- sprints ----------------------------------------------------------------------
    def reconcile_sprints(self, issue_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Create/rename board sprints (<= 30 chars), assign Sprint N issues, move Product Backlog issues to the
        backlog drawer, delete empty orphan future sprints."""
        if not self.board_id:
            self.errors.append("No Jira board id — sprint staging skipped.")
            return []
        wanted: dict[str, dict[str, Any]] = {}
        backlog_keys: list[str] = []
        for r in issue_results:
            if not r.get("key") or not r.get("liveSynced"):
                continue
            label = r.get("sprint") or ""
            if not label or is_product_backlog(label):
                backlog_keys.append(r["key"])
            else:
                name = sprint_short_name(label)[:JIRA_SPRINT_NAME_MAX]
                wanted.setdefault(name, {"name": name, "goal": label, "keys": []})["keys"].append(r["key"])

        existing: list[dict[str, Any]] = []
        try:
            existing = (self._call("GET", f"/rest/agile/1.0/board/{self.board_id}/sprint?state=future,active") or {}).get("values", [])
        except HttpError as e:
            self._record("Jira list board sprints", e)

        used: set[int] = set()
        out: list[dict[str, Any]] = []
        for name, info in sorted(wanted.items(), key=lambda kv: sprint_sort_key(kv[0])):
            match = next((ex for ex in existing if ex.get("id") not in used and
                          ((ex.get("name") or "").strip().lower() == name.lower() or name.lower() in (ex.get("name") or "").lower())), None)
            sprint_id: int | None = None
            try:
                if match:
                    sprint_id = match["id"]
                    used.add(sprint_id)
                    self._call("PUT", f"/rest/agile/1.0/sprint/{sprint_id}", {"name": name, "state": match.get("state", "future"), "goal": info["goal"]})
                else:
                    created = self._call("POST", "/rest/agile/1.0/sprint", {"name": name, "originBoardId": int(self.board_id), "goal": info["goal"]}) or {}
                    sprint_id = created.get("id")
                    if sprint_id:
                        used.add(sprint_id)
                self._call("POST", f"/rest/agile/1.0/sprint/{sprint_id}/issue", {"issues": info["keys"]})
                out.append({"sprintId": sprint_id, "name": name, "goal": info["goal"], "assignedIssues": info["keys"], "liveSynced": True})
            except (HttpError, ValueError) as e:
                out.append({"sprintId": sprint_id, "name": name, "assignedIssues": info["keys"], "liveSynced": False,
                            "error": self._record(f"Jira sprint '{name}'", e)})

        if backlog_keys:
            try:
                self._call("POST", "/rest/agile/1.0/backlog/issue", {"issues": backlog_keys})
                out.append({"sprintId": "BACKLOG_DRAWER", "name": "Product Backlog", "assignedIssues": backlog_keys, "liveSynced": True})
            except HttpError as e:
                out.append({"sprintId": "BACKLOG_DRAWER", "name": "Product Backlog", "assignedIssues": backlog_keys, "liveSynced": False,
                            "error": self._record("Jira move to backlog drawer", e)})

        for ex in existing:  # orphan cleanup: delete empty future sprints we did not use
            if ex.get("id") in used or ex.get("state") != "future":
                continue
            try:
                total = (self._call("GET", f"/rest/agile/1.0/sprint/{ex['id']}/issue?maxResults=1", timeout=15) or {}).get("total", 0)
                if total == 0:
                    self._call("DELETE", f"/rest/agile/1.0/sprint/{ex['id']}", timeout=15)
                    out.append({"sprintId": ex["id"], "name": ex.get("name"), "operation": "DELETED_EMPTY_ORPHAN", "liveSynced": True})
            except HttpError as e:
                self._record(f"Jira orphan sprint cleanup ({ex.get('name')})", e)
        return out

    # -- issue status transitions (REST API v3) ---------------------------------------
    def _issue_status(self, key: str) -> tuple[str, str]:
        """Return (status_name, status_category_key) for a Jira issue."""
        data = self._call("GET", f"/rest/api/3/issue/{key}?fields=status", timeout=15) or {}
        st = (data.get("fields") or {}).get("status") or {}
        name = str(st.get("name") or "").strip()
        cat = str((st.get("statusCategory") or {}).get("key") or "").strip().lower()
        return name, cat

    @staticmethod
    def _status_matches(cur_name: str, cur_cat: str, target: str) -> bool:
        want_cat = JIRA_STATUS_CATEGORY.get(target, "")
        aliases = JIRA_STATUS_ALIASES.get(target, ())
        low = cur_name.lower()
        return bool((low and low in aliases) or (want_cat and cur_cat == want_cat))

    @staticmethod
    def _pick_transition(transitions: list[dict[str, Any]], target: str) -> dict[str, Any] | None:
        want_cat = JIRA_STATUS_CATEGORY.get(target, "")
        aliases = JIRA_STATUS_ALIASES.get(target, ())
        # 1. Exact target status name or transition name match
        for t in transitions:
            to_st = t.get("to") or {}
            to_name = str(to_st.get("name") or "").strip().lower()
            t_name = str(t.get("name") or "").strip().lower()
            if to_name == target.lower() or t_name == target.lower():
                return t
        # 2. Alias match on target status name or transition name
        for t in transitions:
            to_st = t.get("to") or {}
            to_name = str(to_st.get("name") or "").strip().lower()
            t_name = str(t.get("name") or "").strip().lower()
            if to_name in aliases or t_name in aliases:
                return t
        # 3. Jira statusCategory.key match ("new" | "indeterminate" | "done")
        for t in transitions:
            to_cat = str(((t.get("to") or {}).get("statusCategory") or {}).get("key") or "").strip().lower()
            if want_cat and to_cat == want_cat:
                return t
        return None

    def transition_stories(self, stories: list[dict[str, Any]], target_by_id: dict[str, str],
                           refresh_description: bool = False) -> list[dict[str, Any]]:
        """Transition Jira issues to their target statuses via GET/POST /rest/api/3/issue/{key}/transitions.
        Supports multi-hop workflows (e.g. To Do -> In Progress -> Done when a board disallows direct To Do -> Done)."""
        existing: dict[str, str] | None = None
        results: list[dict[str, Any]] = []
        for s in stories:
            sid = s["id"]
            if sid not in target_by_id:
                continue
            target = normalise_story_status(target_by_id[sid])
            key = s.get("jiraKey")
            if not key and self.project_key:
                if existing is None:
                    existing = self.existing_issue_map()
                key = existing.get(sid)
                if key:
                    s["jiraKey"] = key
            entry: dict[str, Any] = {"storyId": sid, "key": key, "targetStatus": target, "liveTransitioned": False}
            if not key:
                entry["error"] = self._record(f"Jira transition {sid}", ValueError("No Jira issue key found for story"))
                results.append(entry)
                continue
            try:
                if refresh_description and s.get("title"):
                    try:
                        self._call("PUT", f"/rest/api/3/issue/{key}", {"fields": {"description": to_adf_document(s)}})
                    except HttpError:
                        pass
                cur_name, cur_cat = self._issue_status(key)
                entry["previousStatus"] = cur_name
                if self._status_matches(cur_name, cur_cat, target):
                    entry.update(currentStatus=cur_name, operation="ALREADY_IN_TARGET_STATUS", liveTransitioned=True)
                    results.append(entry)
                    continue

                tdata = self._call("GET", f"/rest/api/3/issue/{key}/transitions", timeout=15) or {}
                transitions = tdata.get("transitions") or []
                chosen = self._pick_transition(transitions, target)

                # Multi-hop fallback: if moving to Done from To Do and board requires In Progress first
                hops: list[str] = []
                if chosen is None and target == "Done" and cur_cat != "indeterminate":
                    mid = self._pick_transition(transitions, "In Progress")
                    if mid and mid.get("id"):
                        self._call("POST", f"/rest/api/3/issue/{key}/transitions", {"transition": {"id": str(mid["id"])}})
                        hops.append(str((mid.get("to") or {}).get("name") or mid.get("name") or "In Progress"))
                        tdata = self._call("GET", f"/rest/api/3/issue/{key}/transitions", timeout=15) or {}
                        transitions = tdata.get("transitions") or []
                        chosen = self._pick_transition(transitions, target)

                if chosen is None or not chosen.get("id"):
                    avail = ", ".join(f"{t.get('name')}->{(t.get('to') or {}).get('name')}" for t in transitions) or "none"
                    raise HttpError(f"/rest/api/3/issue/{key}/transitions", 400,
                                    f"No transition to '{target}' available from '{cur_name}' (available: {avail})")

                self._call("POST", f"/rest/api/3/issue/{key}/transitions", {"transition": {"id": str(chosen["id"])}})
                to_name = str((chosen.get("to") or {}).get("name") or chosen.get("name") or target)
                hops.append(to_name)
                if refresh_description and s.get("title"):
                    self.add_comment(key, to_story_traceability_comment_adf(s))
                entry.update(
                    transitionId=str(chosen["id"]),
                    transitionName=chosen.get("name"),
                    currentStatus=to_name,
                    hops=hops,
                    operation="TRANSITIONED",
                    liveTransitioned=True,
                )
            except HttpError as e:
                entry["error"] = self._record(f"Jira transition {sid} ({key} -> {target})", e)
            results.append(entry)
        return results


def jira_state_document(stories: list[dict[str, Any]], client: JiraClient | None, project_key: str | None, approval: str,
                        audit: dict[str, Any], issue_results: list[dict[str, Any]], sprint_results: list[dict[str, Any]],
                        errors: list[str], mode: str, deterministic: bool,
                        transition_results: list[dict[str, Any]] | None = None,
                        defects: list[dict[str, Any]] | None = None,
                        defect_results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    defects = defects or []
    return {
        "schemaVersion": dlc.SCHEMA_VERSION,
        "platform": "Atlassian Jira Cloud (REST API v3 + Agile 1.0)",
        "mode": mode,
        "jiraUrl": client.base if client else None,
        "projectKey": (client.project_key if client else None) or project_key,
        "boardId": client.board_id if client else None,
        "sprintAlignmentApprovalStatus": approval,
        "syncedAtUtc": dlc.utc_now_iso(deterministic),
        "totalStories": len(stories),
        "totalAcceptanceCriteria": sum(len(story_acs(s)) for s in stories),
        "storyStatusCounts": story_status_counts(stories),
        "totalDefects": len(defects),
        "openDefects": sum(1 for d in defects if d.get("status") != "Done"),
        "resolvedDefects": sum(1 for d in defects if d.get("status") == "Done"),
        "specCoverageAudit": {k: v for k, v in audit.items() if k != "perStory"},
        "liveSyncResults": issue_results,
        "liveSprintSyncResults": sprint_results,
        "liveTransitionResults": transition_results or [],
        "liveDefectSyncResults": defect_results or [],
        "liveSyncErrors": errors,
        "issues": [{
            "key": s.get("jiraKey"), "storyId": s["id"], "status": story_status(s),
            "acceptanceCriteriaCount": len(story_acs(s)),
            "traceability": s.get("traceability") or {},
            "fields": {"summary": f"[{s['id']}] {s.get('title', '')}", "issuetype": {"name": "Story"},
                       "status": {"name": story_status(s)},
                       "priority": {"name": s.get("priority", "Medium")}, "storyPoints": story_points(s),
                       "sprint": sprint_label(s), "labels": jira_labels(s), "description": to_adf_document(s)},
        } for s in stories],
        "defectIssues": [{
            "key": d.get("jiraKey"), "defectId": d["id"], "storyRef": d.get("storyRef"),
            "status": d.get("status", "In Progress"),
            "remediationComments": d.get("remediationComments") or [],
            "fields": {"summary": f"[{d['id']}] {d.get('title', '')}", "issuetype": {"name": "Bug"},
                       "status": {"name": d.get("status", "In Progress")},
                       "priority": {"name": d.get("priority", "High")},
                       "sprint": d.get("sprint", ""), "description": to_bug_adf_document(d)},
        } for d in defects],
    }


# ======================================================================================
# Section 5 — Azure DevOps client (REST 7.1, Work Items + Iterations)
# ======================================================================================
def ado_patch_document(story: dict[str, Any], iteration_path: str, include_state: bool = False) -> list[dict[str, Any]]:
    acs = story_acs(story)
    ac_html = "<ul>" + "".join(f"<li>{html.escape(ac_to_text(a))}</li>" for a in acs) + "</ul>"
    desc = html.escape(str(story.get("narrative", "")))
    meta = html.escape(f"Requirements: {', '.join(story.get('requirementRefs', [])) or 'n/a'} | Business rules: "
                       f"{', '.join(story.get('businessRuleRefs', [])) or 'n/a'} | Sprint: {sprint_label(story) or 'n/a'}")
    tr_html = "<h4>End-to-End Traceability Matrix</h4><ul>" + "".join(
        f"<li>{html.escape(ln)}</li>" for ln in traceability_bullet_lines(story)
    ) + "</ul>"
    ops = [
        {"op": "add", "path": "/fields/System.Title", "value": f"[{story['id']}] {story.get('title', '')}"[:255]},
        {"op": "add", "path": "/fields/System.Description", "value": f"<p>{desc}</p><p><em>{meta}</em></p>{tr_html}"},
        {"op": "add", "path": "/fields/Microsoft.VSTS.Common.AcceptanceCriteria", "value": ac_html},
        {"op": "add", "path": "/fields/System.IterationPath", "value": iteration_path},
        {"op": "add", "path": "/fields/System.Tags", "value": "; ".join(jira_labels(story) + [story["id"]])},
    ]
    sp = story_points(story)
    if sp is not None:
        ops.append({"op": "add", "path": "/fields/Microsoft.VSTS.Scheduling.StoryPoints", "value": sp})
    if include_state:
        candidates = ADO_STATE_CANDIDATES.get(story_status(story), ("New",))
        ops.append({"op": "add", "path": "/fields/System.State", "value": candidates[0]})
    return ops


def ado_bug_patch_document(bug: dict[str, Any], iteration_path: str, include_state: bool = False) -> list[dict[str, Any]]:
    tr = bug.get("traceability") or {}
    what_html = "<p>" + html.escape(str(bug.get("whatWasTheBug", ""))).replace("\n", "<br/>") + "</p>"
    tr_html = (
        "<h4>End-to-End Traceability</h4><ul>"
        f"<li>Parent Story: {html.escape(str(bug.get('storyRef', '')))}</li>"
        f"<li>Requirements: {html.escape(', '.join(tr.get('requirementRefs') or []))}</li>"
        f"<li>Target Source Code: {html.escape(', '.join(tr.get('targetSourceFiles') or []))}</li>"
        f"<li>Failing Test Cases: {html.escape(', '.join(tr.get('testCaseIds') or []))}</li>"
        "</ul>"
    )
    ops = [
        {"op": "add", "path": "/fields/System.Title", "value": f"[{bug['id']}] {bug.get('title', '')}"[:255]},
        {"op": "add", "path": "/fields/System.Description", "value": f"{what_html}{tr_html}"},
        {"op": "add", "path": "/fields/Microsoft.VSTS.TCM.ReproSteps", "value": f"{what_html}{tr_html}"},
        {"op": "add", "path": "/fields/System.IterationPath", "value": iteration_path},
        {"op": "add", "path": "/fields/System.Tags", "value": f"Bug; Stage6_Defect; {bug['id']}; {bug.get('storyRef', '')}"},
    ]
    if include_state:
        candidates = ADO_STATE_CANDIDATES.get(str(bug.get("status") or "In Progress"), ("Active",))
        ops.append({"op": "add", "path": "/fields/System.State", "value": candidates[0]})
    return ops


class AdoClient:
    def __init__(self, org_url: str, project: str, pat: str, work_item_type: str = "User Story"):
        self.org = org_url.rstrip("/")
        self.project = project
        self.work_item_type = work_item_type
        self.headers = {"Authorization": basic_auth_header("", pat), "Accept": "application/json", "Content-Type": "application/json"}
        self.patch_headers = {**self.headers, "Content-Type": "application/json-patch+json"}
        self.errors: list[str] = []

    def _url(self, path: str, project_scoped: bool = True, **params: str) -> str:
        params.setdefault("api-version", ADO_API)
        scope = f"/{urllib.parse.quote(self.project, safe='')}" if project_scoped else ""
        return f"{self.org}{scope}{path}?{urllib.parse.urlencode(params, safe='$,')}"

    def _record(self, context: str, e: Exception) -> str:
        msg = f"{context}: {e}"
        self.errors.append(msg)
        return msg

    def iteration_root(self) -> str:
        return self.project

    def iteration_path_for(self, label: str) -> str:
        return self.iteration_root() if (not label or is_product_backlog(label)) else f"{self.project}\\{sprint_short_name(label)}"

    # -- connection -------------------------------------------------------------------
    def test_connection(self) -> dict[str, Any]:
        project: dict[str, Any] = {}
        try:
            _, project = http_json("GET", self._url(f"/_apis/projects/{urllib.parse.quote(self.project, safe='')}", project_scoped=False), self.headers, timeout=15)
        except HttpError as e:
            self._record("ADO project lookup", e)
        return {"platform": "ado", "connected": bool(project.get("id")), "organizationUrl": self.org,
                "project": project.get("name", self.project), "projectId": project.get("id"), "errors": self.errors}

    # -- work items -------------------------------------------------------------------
    def existing_work_item_map(self) -> dict[str, int]:
        """Map '[US-ID]' or '[BUG-ID]' title prefixes to existing work item ids via WIQL + batch field read."""
        mapping: dict[str, int] = {}
        wiql = {"query": "SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project "
                         "AND ([System.Title] CONTAINS '[US-' OR [System.Title] CONTAINS '[BUG-') "
                         "AND [System.State] <> 'Removed' ORDER BY [System.Id]"}
        try:
            _, data = http_json("POST", self._url("/_apis/wit/wiql"), self.headers, wiql)
        except HttpError as e:
            self._record("ADO WIQL lookup (duplicates possible)", e)
            return mapping
        ids = [str(w["id"]) for w in (data or {}).get("workItems", []) if w.get("id")]
        for i in range(0, len(ids), 200):
            try:
                _, batch = http_json("GET", self._url("/_apis/wit/workitems", ids=",".join(ids[i:i + 200]), fields="System.Title"), self.headers)
            except HttpError as e:
                self._record("ADO work item batch read", e)
                continue
            for wi in (batch or {}).get("value", []):
                m = STORY_ID_PREFIX_RE.match((wi.get("fields", {}).get("System.Title") or "").strip())
                if m:
                    mapping.setdefault(m.group(1), int(wi["id"]))
        return mapping

    def upsert_stories(self, stories: list[dict[str, Any]], iteration_paths: dict[str, str]) -> list[dict[str, Any]]:
        existing = self.existing_work_item_map()
        results: list[dict[str, Any]] = []
        for s in stories:
            path = iteration_paths.get(s["id"], self.iteration_root())
            ops = ado_patch_document(s, path)
            wid = existing.get(s["id"]) or s.get("adoWorkItemId")
            entry = {"storyId": s["id"], "iterationPath": path, "sprint": sprint_label(s), "acCount": len(story_acs(s)), "liveSynced": False}
            try:
                if wid:
                    try:
                        _, data = http_json("PATCH", self._url(f"/_apis/wit/workitems/{wid}"), self.patch_headers, ops)
                        entry.update(operation="UPDATED_EXISTING")
                    except HttpError as e:
                        if e.status != 404:
                            raise
                        wid = None
                if not wid:
                    _, data = http_json("POST", self._url(f"/_apis/wit/workitems/${urllib.parse.quote(self.work_item_type)}"), self.patch_headers, ops)
                    entry.update(operation="CREATED_NEW")
                wid = int((data or {}).get("id") or wid)
                s["adoWorkItemId"] = wid
                entry.update(id=wid, url=((data or {}).get("_links", {}).get("html", {}).get("href")) or f"{self.org}/{urllib.parse.quote(self.project)}/_workitems/edit/{wid}", liveSynced=True)
            except (HttpError, ValueError, TypeError) as e:
                entry["error"] = self._record(f"ADO upsert {s['id']}", e)
            results.append(entry)
        return results

    def upsert_defects(self, defects: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Create/update Stage 6 Bug work items in Azure DevOps, append System.History fix comments, and transition."""
        if not defects:
            return []
        existing = self.existing_work_item_map()
        results: list[dict[str, Any]] = []
        for bug in defects:
            bid = bug["id"]
            path = self.iteration_path_for(str(bug.get("sprint") or ""))
            ops = ado_bug_patch_document(bug, path)
            wid = existing.get(bid) or bug.get("adoWorkItemId")
            entry: dict[str, Any] = {
                "defectId": bid, "workItemType": "Bug", "storyRef": bug.get("storyRef"),
                "status": bug.get("status", "In Progress"), "liveSynced": False, "commentsPosted": 0,
            }
            try:
                if wid:
                    try:
                        _, data = http_json("PATCH", self._url(f"/_apis/wit/workitems/{wid}"), self.patch_headers, ops)
                        entry.update(operation="UPDATED_EXISTING")
                    except HttpError as e:
                        if e.status != 404:
                            raise
                        wid = None
                if not wid:
                    data = None
                    last_err = None
                    for wtype in ("Bug", "Issue", self.work_item_type):
                        try:
                            _, data = http_json("POST", self._url(f"/_apis/wit/workitems/${urllib.parse.quote(wtype)}"), self.patch_headers, ops)
                            entry["workItemType"] = wtype
                            entry["operation"] = "CREATED_NEW"
                            break
                        except HttpError as e:
                            last_err = e
                    if data is None and last_err is not None:
                        raise last_err
                wid = int((data or {}).get("id") or wid)
                bug["adoWorkItemId"] = wid
                entry.update(id=wid, url=((data or {}).get("_links", {}).get("html", {}).get("href")) or f"{self.org}/{urllib.parse.quote(self.project)}/_workitems/edit/{wid}", liveSynced=True)

                # Post remediation steps comments via /fields/System.History
                for c in bug.get("remediationComments") or []:
                    if not c.get("adoCommentSynced"):
                        steps_html = "<ul>" + "".join(f"<li>{html.escape(st)}</li>" for st in (c.get("stepsTaken") or [])) + "</ul>"
                        hist_html = (
                            f"<h4>Defect {html.escape(bid)} Fixed in Stage 6 Iteration {c.get('iteration')}</h4>"
                            f"<p><strong>Verification:</strong> {html.escape(str(c.get('verificationResult', '')))}</p>"
                            f"<p><strong>Steps Taken to Fix the Defect:</strong></p>{steps_html}"
                        )
                        try:
                            http_json("PATCH", self._url(f"/_apis/wit/workitems/{wid}"), self.patch_headers,
                                      [{"op": "add", "path": "/fields/System.History", "value": hist_html}])
                            c["adoCommentSynced"] = True
                            entry["commentsPosted"] = int(entry.get("commentsPosted", 0)) + 1
                        except HttpError as e:
                            self._record(f"ADO comment {bid}", e)

                pseudo_story = {"id": bid, "adoWorkItemId": wid}
                tr_res = self.transition_stories([pseudo_story], {bid: str(bug.get("status") or "In Progress")})
                if tr_res:
                    entry["transition"] = tr_res[0]
            except (HttpError, ValueError, TypeError) as e:
                entry["error"] = self._record(f"ADO defect upsert {bid}", e)
            results.append(entry)
        return results

    def transition_stories(self, stories: list[dict[str, Any]], target_by_id: dict[str, str]) -> list[dict[str, Any]]:
        """Patch /fields/System.State on Azure DevOps work items, trying Agile/Scrum/Basic state candidates."""
        existing: dict[str, int] | None = None
        results: list[dict[str, Any]] = []
        for s in stories:
            sid = s["id"]
            if sid not in target_by_id:
                continue
            target = normalise_story_status(target_by_id[sid])
            wid = s.get("adoWorkItemId")
            if not wid:
                if existing is None:
                    existing = self.existing_work_item_map()
                wid = existing.get(sid)
                if wid:
                    s["adoWorkItemId"] = wid
            entry: dict[str, Any] = {"storyId": sid, "id": wid, "targetStatus": target, "liveTransitioned": False}
            if not wid:
                entry["error"] = self._record(f"ADO transition {sid}", ValueError("No ADO work item ID found for story"))
                results.append(entry)
                continue
            candidates = ADO_STATE_CANDIDATES.get(target, ("New",))
            last_err: Exception | None = None
            for state_val in candidates:
                ops = [{"op": "add", "path": "/fields/System.State", "value": state_val}]
                try:
                    http_json("PATCH", self._url(f"/_apis/wit/workitems/{wid}"), self.patch_headers, ops)
                    entry.update(currentState=state_val, operation="TRANSITIONED", liveTransitioned=True)
                    last_err = None
                    break
                except HttpError as e:
                    last_err = e
            if last_err is not None:
                entry["error"] = self._record(f"ADO transition {sid} (#{wid} -> {target})", last_err)
            results.append(entry)
        return results

    # -- iterations -------------------------------------------------------------------
    def ensure_iterations(self, sprint_names: list[str]) -> list[dict[str, Any]]:
        """Create missing 'Sprint N' classification nodes and subscribe them to the default team's iterations."""
        out: list[dict[str, Any]] = []
        existing: dict[str, dict[str, Any]] = {}
        try:
            _, tree = http_json("GET", self._url("/_apis/wit/classificationnodes/iterations", **{"$depth": "2"}), self.headers)
            for child in (tree or {}).get("children", []) or []:
                existing[str(child.get("name", "")).lower()] = child
        except HttpError as e:
            self._record("ADO list iterations", e)
        team_iter_ids: set[str] = set()
        try:
            _, team = http_json("GET", self._url("/_apis/work/teamsettings/iterations"), self.headers)
            team_iter_ids = {str(i.get("id")) for i in (team or {}).get("value", [])}
        except HttpError as e:
            self._record("ADO list team iterations", e)

        for name in sorted(sprint_names, key=sprint_sort_key):
            node = existing.get(name.lower())
            entry: dict[str, Any] = {"name": name, "iterationPath": f"{self.project}\\{name}", "liveSynced": False}
            try:
                if node:
                    entry["operation"] = "REUSED_EXISTING"
                else:
                    _, node = http_json("POST", self._url("/_apis/wit/classificationnodes/iterations"), self.headers, {"name": name})
                    entry["operation"] = "CREATED_NEW"
                identifier = (node or {}).get("identifier")
                entry["identifier"] = identifier
                if identifier and identifier not in team_iter_ids:
                    http_json("POST", self._url("/_apis/work/teamsettings/iterations"), self.headers, {"id": identifier})
                    entry["addedToTeam"] = True
                entry["liveSynced"] = True
            except HttpError as e:
                entry["error"] = self._record(f"ADO iteration '{name}'", e)
            out.append(entry)
        return out


def ado_state_document(stories: list[dict[str, Any]], org_url: str | None, project: str | None, approval: str, audit: dict[str, Any],
                       work_items: list[dict[str, Any]], iterations: list[dict[str, Any]], errors: list[str], mode: str,
                       deterministic: bool, transition_results: list[dict[str, Any]] | None = None,
                       defects: list[dict[str, Any]] | None = None,
                       defect_results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    root = project or "<ADO_PROJECT>"
    defects = defects or []
    return {
        "schemaVersion": dlc.SCHEMA_VERSION,
        "platform": "Microsoft Azure DevOps Boards (REST API 7.1)",
        "mode": mode,
        "organizationUrl": org_url,
        "project": project,
        "sprintAlignmentApprovalStatus": approval,
        "syncedAtUtc": dlc.utc_now_iso(deterministic),
        "totalStories": len(stories),
        "storyStatusCounts": story_status_counts(stories),
        "totalDefects": len(defects),
        "openDefects": sum(1 for d in defects if d.get("status") != "Done"),
        "resolvedDefects": sum(1 for d in defects if d.get("status") == "Done"),
        "specCoverageAudit": {k: v for k, v in audit.items() if k != "perStory"},
        "liveSyncResults": work_items,
        "liveIterationResults": iterations,
        "liveTransitionResults": transition_results or [],
        "liveDefectSyncResults": defect_results or [],
        "liveSyncErrors": errors,
        "localPayload": [{
            "storyId": s["id"], "status": story_status(s),
            "traceability": s.get("traceability") or {},
            "workItemType": os.environ.get("ADO_WORK_ITEM_TYPE", "User Story"),
            "id": s.get("adoWorkItemId"),
            "operations": ado_patch_document(s, root if (not sprint_label(s) or is_product_backlog(sprint_label(s))) else f"{root}\\{sprint_short_name(sprint_label(s))}", include_state=True),
        } for s in stories],
        "localDefectsPayload": [{
            "defectId": d["id"], "storyRef": d.get("storyRef"), "status": d.get("status", "In Progress"),
            "workItemType": "Bug", "id": d.get("adoWorkItemId"),
            "remediationComments": d.get("remediationComments") or [],
            "operations": ado_bug_patch_document(d, root if (not d.get("sprint") or is_product_backlog(str(d.get("sprint")))) else f"{root}\\{sprint_short_name(str(d.get('sprint')))}", include_state=True),
        } for d in defects],
    }


# ======================================================================================
# Section 6 — orchestration
# ======================================================================================
def resolve_platform(arg: str | None, root: Path) -> str:
    if arg:
        return "ado" if arg == "azure-devops" else arg
    stack = root / "specs" / "target_stack.json"
    if stack.is_file():
        value = str((dlc.read_json(stack) or {}).get("almPlatform", "none")).strip().lower()
        if value in ("jira", "ado", "both", "none"):
            return value
        if value in ("azure-devops", "azuredevops", "azure devops"):
            return "ado"
    return "none"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Stage 3 Gate 3 audit + idempotent Jira / Azure DevOps backlog, defect & status transition bridge (v4).")
    p.add_argument("--action", default="sync-stories",
                   choices=["test-connection", "audit", "sync-stories", "sync-sprints", "set-approval", "export-csv",
                            "transition-stories", "sync-status-from-eval", "sync-deployment-status", "select-groups"])
    p.add_argument("--platform", default=None, choices=["jira", "ado", "azure-devops", "both", "none"],
                   help="Default: specs/target_stack.json#almPlatform, else none.")
    dlc.add_project_root_arg(p)
    p.add_argument("--output-dir", default="backlog", help="Relative to project root (default backlog).")
    p.add_argument("--approved", "--approve-sprint-plan", dest="approved", action="store_true",
                   help="Human approved the sprint alignment (required by sync-sprints).")
    p.add_argument("--set-approval", choices=list(APPROVAL_STATES), default=None, help="Status for --action set-approval.")
    p.add_argument("--select-groups", default=None,
                   help="Comma-separated Capability Group IDs (e.g. 'GRP-01,GRP-02') or 'ALL' to take all capability groupings forward.")
    p.add_argument("--select-all-groups", action="store_true",
                   help="Convenience alias for --select-groups ALL (schedule all capability groupings across Release 1 Sprints 1..N).")
    p.add_argument("--sprint-capacity-points", type=int, default=None,
                   help="Target story-point velocity capacity per sprint (default: target_stack.json#sprintCapacityPoints or 21 SP). Large capability groups automatically span multiple sprints (Sprint 1..N).")
    p.add_argument("--target-status", default=None,
                   help="Target story status for --action transition-stories ('To Do', 'In Progress', or 'Done').")
    p.add_argument("--scope", choices=["all", "active-sprints"], default="all",
                   help="Story scope for --action transition-stories: 'all' or 'active-sprints' (non-Product-Backlog stories).")
    p.add_argument("--story-ids", default=None,
                   help="Comma-separated story IDs to transition (overrides --scope).")
    p.add_argument("--only-from-todo", action="store_true",
                   help="When transitioning to 'In Progress', only update stories currently in 'To Do' (do not regress 'Done' stories).")
    p.add_argument("--allow-partial-coverage", action="store_true", help="Downgrade REQ coverage gaps from FAIL to WARN.")
    p.add_argument("--offline", action="store_true", help="Never touch the network (also DLC_OFFLINE_MODE=1).")
    p.add_argument("--deterministic", action="store_true", help="Fixed timestamps for golden comparisons.")
    p.add_argument("--jira-url", default=None)
    p.add_argument("--jira-email", default=None)
    p.add_argument("--jira-token", default=None)
    p.add_argument("--jira-project-key", "--jira-project", dest="jira_project_key", default=None)
    p.add_argument("--jira-board-id", default=None)
    p.add_argument("--jira-issue-type", default=None)
    p.add_argument("--ado-org-url", default=None)
    p.add_argument("--ado-project", default=None)
    p.add_argument("--ado-pat", default=None)
    return p


def resolve_sprint_capacity(args: argparse.Namespace, root: Path) -> int:
    if args.sprint_capacity_points is not None:
        return int(args.sprint_capacity_points)
    env_cap = os.environ.get("DLC_SPRINT_CAPACITY_POINTS")
    if env_cap and env_cap.strip().isdigit():
        return int(env_cap.strip())
    stack_p = root / "specs" / "target_stack.json"
    if stack_p.is_file():
        stack_doc = dlc.read_json(stack_p)
        if isinstance(stack_doc, dict) and isinstance(stack_doc.get("sprintCapacityPoints"), (int, float)):
            return int(stack_doc["sprintCapacityPoints"])
    return 21


def jira_client_from(args: argparse.Namespace, offline: bool) -> tuple[JiraClient | None, str]:
    url = args.jira_url or os.environ.get("JIRA_URL", "")
    email = args.jira_email or os.environ.get("JIRA_EMAIL", "")
    token = args.jira_token or os.environ.get("JIRA_API_TOKEN", "")
    key = args.jira_project_key or os.environ.get("JIRA_PROJECT_KEY") or None
    if offline:
        return None, "offline mode requested"
    if not (url and email and token) or "your-domain" in url:
        return None, "JIRA_URL / JIRA_EMAIL / JIRA_API_TOKEN not set"
    return JiraClient(url, email, token, key, args.jira_board_id or os.environ.get("JIRA_BOARD_ID") or None,
                      args.jira_issue_type or os.environ.get("JIRA_ISSUE_TYPE", "Story")), ""


def ado_client_from(args: argparse.Namespace, offline: bool) -> tuple[AdoClient | None, str]:
    org = args.ado_org_url or os.environ.get("ADO_ORG_URL", "")
    project = args.ado_project or os.environ.get("ADO_PROJECT", "")
    pat = args.ado_pat or os.environ.get("ADO_PAT", "")
    if offline:
        return None, "offline mode requested"
    if not (org and project and pat):
        return None, "ADO_ORG_URL / ADO_PROJECT / ADO_PAT not set"
    return AdoClient(org, project, pat, os.environ.get("ADO_WORK_ITEM_TYPE", "User Story")), ""


def main() -> int:
    args = build_parser().parse_args()
    root = dlc.resolve_project_root(args.project_root)
    load_env_files(root)
    offline = args.offline or bool(os.environ.get("DLC_OFFLINE_MODE"))
    platform = resolve_platform(args.platform, root)
    out_dir = dlc.project_path(root, args.output_dir)
    deterministic = args.deterministic

    # ---- test-connection (no project artefacts needed) -------------------------------
    if args.action == "test-connection":
        report: dict[str, Any] = {"platform": platform, "offline": offline, "results": []}
        for name, factory in (("jira", jira_client_from), ("ado", ado_client_from)):
            if platform not in (name, "both"):
                continue
            client, reason = factory(args, offline)
            if client is None:
                report["results"].append({"platform": name, "connected": False, "reason": reason})
                continue
            try:
                report["results"].append(client.test_connection())
            except HttpError as e:
                report["results"].append({"platform": name, "connected": False, "error": str(e)})
        if platform == "none":
            report["results"].append({"platform": "none", "connected": False, "reason": "no ALM platform selected (--platform or specs/target_stack.json#almPlatform)"})
        print(json.dumps(report, indent=2))
        return 0 if report["results"] and all(r.get("connected") for r in report["results"]) else 1

    # Enforce Gate 2 (Spec approval) before Stage 3 backlog authoring/staging actions
    if args.action in ("audit", "sync-stories", "sync-sprints", "set-approval", "select-groups", "export-csv"):
        dlc.require_gate_approved(root, "gate_2_spec", f"Stage 3 (03-story-and-sprint-planner / {args.action})", deterministic=deterministic)

    # ---- set-approval -----------------------------------------------------------------
    if args.action == "set-approval":
        if not args.set_approval:
            raise dlc.GateFailure("--action set-approval requires --set-approval <STATUS>.")
        if args.set_approval != "PENDING_HUMAN_APPROVAL":
            stories = dlc.load_stories(root)
            audit = audit_backlog(root, stories, args.allow_partial_coverage)
            print_audit(audit)
            if not audit["passed"]:
                raise dlc.GateFailure(f"Cannot mark sprint plan {args.set_approval}: Gate 3 audit failed (see [FAIL] lines).")
        if args.set_approval == "APPROVED_BY_USER" and not dlc.is_autonomous_or_golden(root, deterministic=deterministic):
            import time as _time
            ga = dlc.load_gate_approvals(root)
            g3 = (ga.get("gates") or {}).get("gate_3_backlog") or {}
            if g3.get("readyAtEpoch") is not None:
                elapsed = _time.time() - float(g3["readyAtEpoch"])
                if elapsed < 8.0:
                    raise dlc.GateFailure(
                        f"Refusing to self-approve gate_3_backlog ({elapsed:.1f}s after staging < 8s human-turn boundary)!\n"
                        "  Present stories + sprint plan to the user, END YOUR TURN, and wait for human approval before calling set-approval."
                    )
            now_iso = dlc.utc_now_iso(False)
            ga.setdefault("gates", {})["gate_3_backlog"] = {
                "gateId": "gate_3_backlog",
                "stage": dlc.GATE_DEFINITIONS["gate_3_backlog"],
                "status": "APPROVED_BY_USER",
                "readyAtUtc": g3.get("readyAtUtc") or now_iso,
                "readyAtEpoch": g3.get("readyAtEpoch"),
                "approvedAtUtc": now_iso,
                "userResponse": "Approved via alm_jira_ado_bridge.py --action set-approval",
                "summary": g3.get("summary") or "Stage 3 backlog & sprint alignment approved by human.",
            }
            dlc.write_json(dlc.gate_approvals_path(root), ga)
        elif args.set_approval == "PRE_APPROVED_BY_USER" and dlc.gate_approvals_path(root).exists():
            ga = dlc.load_gate_approvals(root)
            now_iso = dlc.utc_now_iso(deterministic)
            ga.setdefault("gates", {})["gate_3_backlog"] = {
                "gateId": "gate_3_backlog",
                "stage": dlc.GATE_DEFINITIONS["gate_3_backlog"],
                "status": "PRE_APPROVED_AUTONOMOUS",
                "readyAtUtc": now_iso,
                "readyAtEpoch": None,
                "approvedAtUtc": now_iso,
                "userResponse": "Pre-approved via --autonomous mode",
                "summary": "Stage 3 backlog pre-approved in autonomous mode.",
            }
            dlc.write_json(dlc.gate_approvals_path(root), ga)
        touched = set_approval_status(root, args.set_approval, deterministic)
        print(json.dumps({"approvalStatus": args.set_approval, "updated": touched}, indent=2))
        return 0

    # ---- select-groups (update selectedCapabilityGroups & re-align sprints by group + capacity) --
    if args.action == "select-groups":
        if getattr(args, "select_all_groups", False) and not args.select_groups:
            args.select_groups = "ALL"
        if not args.select_groups:
            raise dlc.GateFailure("--action select-groups requires --select-groups <GRP-01,GRP-02|ALL> (or --select-all-groups).")
        raw_tokens = [t.strip().upper() for t in args.select_groups.split(",") if t.strip()]
        if not raw_tokens:
            raise dlc.GateFailure("--select-groups cannot be empty.")
        select_all = "ALL" in raw_tokens or "*" in raw_tokens
        selected_list = ["ALL"] if select_all else sorted(dict.fromkeys(raw_tokens))
        cap_points = resolve_sprint_capacity(args, root)

        stack_p = root / "specs" / "target_stack.json"
        if stack_p.is_file():
            stack_doc = dlc.read_json(stack_p)
            if isinstance(stack_doc, dict):
                stack_doc["selectedCapabilityGroups"] = selected_list
                if args.sprint_capacity_points is not None:
                    stack_doc["sprintCapacityPoints"] = cap_points
                dlc.write_json(stack_p, stack_doc)

        stories_p = root / "backlog" / "user_stories.json"
        effective_groups: list[str] = []
        auto_included_prereqs: list[str] = []
        group_sprints: dict[str, list[str]] = {}
        if stories_p.is_file():
            stories_doc = dlc.read_json(stories_p)
            stories_list = stories_doc.get("stories", []) if isinstance(stories_doc, dict) else []
            ordered_groups: list[str] = []
            for s in stories_list:
                cg = str(s.get("capabilityGroup") or "").strip().upper()
                if cg and cg != "SHARED" and cg not in ordered_groups:
                    ordered_groups.append(cg)
            req_groups = ordered_groups if select_all else selected_list
            eff_set, topo_ordered = dlc.resolve_group_closure(root, req_groups)
            effective_groups = [g for g in topo_ordered if g in set(ordered_groups) or g in eff_set]
            for g in ordered_groups:
                if (select_all or g in eff_set) and g not in effective_groups:
                    effective_groups.append(g)
            if not select_all:
                auto_included_prereqs = [g for g in effective_groups if g not in set(selected_list)]

            group_sprints = pack_stories_into_sprints(stories_list, effective_groups, select_all, selected_list, cap_points)
            enrich_story_traceability(root, stories_list)
            persist_stories_metadata(root, stories_list, deterministic)
            audit = audit_backlog(root, stories_list, args.allow_partial_coverage)
            approval = current_approval_status(root)
            summary = build_sprint_plan_summary(stories_list, audit, approval, platform, deterministic)
            write_sprint_plan_json(out_dir / "sprint_plan.json", summary)
        print(json.dumps({
            "selectedCapabilityGroups": selected_list,
            "effectiveCapabilityGroups": ["ALL"] if select_all else effective_groups,
            "autoIncludedPrerequisiteGroups": auto_included_prereqs,
            "sprintCapacityPoints": cap_points,
            "groupSprintAllocation": group_sprints,
            "allGroupsSelected": select_all,
        }, indent=2))
        return 0

    # ---- everything else needs stories + audit ---------------------------------------
    stories = dlc.load_stories(root)  # GateFailure if Stage 3 has not authored backlog/user_stories.json
    for s in stories:
        if "id" not in s or "title" not in s:
            raise dlc.GateFailure("Every story in backlog/user_stories.json needs 'id' and 'title' (docs/ARCHITECTURE.md §4.5).")
    defects = load_defects(root)
    enrich_story_traceability(root, stories, defects)
    audit = audit_backlog(root, stories, args.allow_partial_coverage)
    print_audit(audit)
    approval = current_approval_status(root)

    if args.action == "audit":
        persist_stories_metadata(root, stories, deterministic)
        summary = build_sprint_plan_summary(stories, audit, approval, platform, deterministic)
        write_sprint_plan_json(out_dir / "sprint_plan.json", summary)
        print(f"[dlc] sprint plan summary -> {out_dir / 'sprint_plan.json'}")
        if audit["passed"] and approval == "PENDING_HUMAN_APPROVAL":
            dlc.mark_gate_awaiting_human(
                root,
                "gate_3_backlog",
                summary="Stage 3 User Stories & Sprint Plan audited. Sync stories to board (`--action sync-stories`), present stories + sprint plan to user, and STOP for Gate 3 approval.",
                deterministic=deterministic,
            )
        return 0 if audit["passed"] else 1

    jira_key_hint = args.jira_project_key or os.environ.get("JIRA_PROJECT_KEY") or None
    if args.action == "export-csv":
        persist_stories_metadata(root, stories, deterministic)
        path = write_jira_csv(stories, out_dir / "jira_import.csv", jira_key_hint, defects)
        print(f"[dlc] Jira CSV export -> {path}" + ("" if audit["passed"] else "  (audit FAILED — fix before syncing)"))
        return 0

    if args.action == "sync-deployment-status":
        persist_stories_metadata(root, stories, deterministic)
        update_markdown_story_statuses(root, stories)
        write_jira_csv(stories, out_dir / "jira_import.csv", jira_key_hint, defects)
        dep_eval_p = root / "deploy" / "deployment_eval_report.json"
        dep_summary = dlc.read_json(dep_eval_p).get("summary", {}) if dep_eval_p.is_file() else {}
        print(json.dumps({
            "action": "sync-deployment-status",
            "storiesUpdated": len(stories),
            "deploymentVerdict": dep_summary.get("verdict", "UNKNOWN"),
        }, indent=2))
        return 0

    # ---- transition-stories / sync-status-from-eval -----------------------------------
    if args.action in ("transition-stories", "sync-status-from-eval"):
        target_by_id: dict[str, str] = {}
        now_iso = dlc.utc_now_iso(deterministic)
        if args.action == "transition-stories":
            if not args.target_status:
                raise dlc.GateFailure("--action transition-stories requires --target-status ('To Do', 'In Progress', or 'Done').")
            target = normalise_story_status(args.target_status, strict=True)
            explicit_ids = {x.strip() for x in (args.story_ids or "").split(",") if x.strip()}
            for s in stories:
                sid = s["id"]
                if explicit_ids and sid not in explicit_ids:
                    continue
                if not explicit_ids and args.scope == "active-sprints" and is_product_backlog(sprint_label(s)):
                    continue
                if args.only_from_todo and story_status(s) != "To Do":
                    continue
                prev = story_status(s)
                s["status"] = target
                s["statusReason"] = f"Transitioned from '{prev}' to '{target}' via transition-stories ({args.scope})"
                s["statusUpdatedAtUtc"] = now_iso
                target_by_id[sid] = target
                print(f"[dlc][status] {sid}: {prev} -> {target}")
        else:
            # 1. Create/update Stage 6 defects (`BUG-01..N`) from failing tests & record fix-steps comments when fixed
            defects = sync_defects_from_eval(root, stories, deterministic)
            # 2. Recompute story statuses ('To Do' / 'In Progress' / 'Done')
            computed = compute_story_statuses_from_eval(root, stories)
            for s in stories:
                sid = s["id"]
                info = computed.get(sid)
                if not info:
                    continue
                prev = story_status(s)
                target = info["status"]
                s["status"] = target
                s["statusReason"] = info["reason"]
                s["statusUpdatedAtUtc"] = now_iso
                target_by_id[sid] = target
                print(f"[dlc][status] {sid}: {prev} -> {target} ({info['reason']})")
            # 3. Refresh end-to-end traceability on all stories (including test statuses & linked BUG-* defects)
            enrich_story_traceability(root, stories, defects)

        persist_stories_metadata(root, stories, deterministic)
        update_markdown_story_statuses(root, stories)
        write_jira_csv(stories, out_dir / "jira_import.csv", jira_key_hint, defects)

        all_errors: list[str] = []
        live_summary: dict[str, Any] = {}

        if platform in ("jira", "both") or (out_dir / "jira_state.json").is_file():
            client, reason = jira_client_from(args, offline) if platform in ("jira", "both") else (None, "platform not jira")
            transition_results: list[dict[str, Any]] = []
            defect_results: list[dict[str, Any]] = []
            prev_jira = dlc.read_json(out_dir / "jira_state.json") if (out_dir / "jira_state.json").is_file() else {}
            issue_results = prev_jira.get("liveSyncResults", []) if isinstance(prev_jira, dict) else []
            sprint_results = prev_jira.get("liveSprintSyncResults", []) if isinstance(prev_jira, dict) else []
            mode = "OFFLINE_EXPORT_ONLY"
            if client is None:
                if platform in ("jira", "both"):
                    print(f"[dlc] Jira transition: offline update only ({reason}) — local backlog & defect statuses updated.")
            else:
                try:
                    client.myself()
                    client.discover_project_and_board()
                    transition_results = client.transition_stories(
                        stories, target_by_id,
                        refresh_description=(args.action == "sync-status-from-eval"),
                    )
                    if defects:
                        story_key_map = {s["id"]: str(s["jiraKey"]) for s in stories if s.get("jiraKey")}
                        defect_results = client.upsert_defects(defects, story_key_map)
                    mode = "LIVE_REST_API_V3" if (any(r.get("liveTransitioned") for r in transition_results) or any(d.get("liveSynced") for d in defect_results)) else "LIVE_SYNC_FAILED"
                except HttpError as e:
                    client.errors.append(f"Jira live status transition aborted: {e}")
                    mode = "LIVE_SYNC_FAILED"
                for err in client.errors:
                    print(f"[dlc][jira][error] {err}", file=sys.stderr)
                all_errors += client.errors
            if defects:
                write_defects_artifacts(root, defects, deterministic)
                enrich_story_traceability(root, stories, defects)
            persist_stories_metadata(root, stories, deterministic)
            state = jira_state_document(
                stories, client, jira_key_hint or (prev_jira.get("projectKey") if isinstance(prev_jira, dict) else None),
                approval, audit, issue_results, sprint_results,
                client.errors if client else ([reason] if platform in ("jira", "both") else []),
                mode, deterministic, transition_results=transition_results,
                defects=defects, defect_results=defect_results,
            )
            dlc.write_json(out_dir / "jira_state.json", state)
            live_summary["jira"] = {
                "mode": mode, "projectKey": state["projectKey"], "boardId": state["boardId"],
                "issuesSynced": sum(1 for r in issue_results if r.get("liveSynced")),
                "sprintsSynced": sum(1 for r in sprint_results if r.get("liveSynced")),
                "issuesTransitioned": sum(1 for r in transition_results if r.get("liveTransitioned")),
                "defectsSynced": sum(1 for d in defect_results if d.get("liveSynced")),
                "errors": len(state["liveSyncErrors"]),
            }

        if platform in ("ado", "both") or (out_dir / "azure_devops_state.json").is_file():
            client_a, reason = ado_client_from(args, offline) if platform in ("ado", "both") else (None, "platform not ado")
            transition_results_a: list[dict[str, Any]] = []
            defect_results_a: list[dict[str, Any]] = []
            prev_ado = dlc.read_json(out_dir / "azure_devops_state.json") if (out_dir / "azure_devops_state.json").is_file() else {}
            work_items = prev_ado.get("liveSyncResults", []) if isinstance(prev_ado, dict) else []
            iterations = prev_ado.get("liveIterationResults", []) if isinstance(prev_ado, dict) else []
            mode = "OFFLINE_EXPORT_ONLY"
            org = client_a.org if client_a else (args.ado_org_url or os.environ.get("ADO_ORG_URL") or (prev_ado.get("organizationUrl") if isinstance(prev_ado, dict) else None))
            project = client_a.project if client_a else (args.ado_project or os.environ.get("ADO_PROJECT") or (prev_ado.get("project") if isinstance(prev_ado, dict) else None))
            if client_a is None:
                if platform in ("ado", "both"):
                    print(f"[dlc] ADO transition: offline update only ({reason}) — local backlog & defect statuses updated.")
            else:
                transition_results_a = client_a.transition_stories(stories, target_by_id)
                if defects:
                    defect_results_a = client_a.upsert_defects(defects)
                mode = "LIVE_REST_API_V7_1" if (any(r.get("liveTransitioned") for r in transition_results_a) or any(d.get("liveSynced") for d in defect_results_a)) else "LIVE_SYNC_FAILED"
                for err in client_a.errors:
                    print(f"[dlc][ado][error] {err}", file=sys.stderr)
                all_errors += client_a.errors
            if defects:
                write_defects_artifacts(root, defects, deterministic)
                enrich_story_traceability(root, stories, defects)
            persist_stories_metadata(root, stories, deterministic)
            state_a = ado_state_document(
                stories, org, project, approval, audit, work_items, iterations,
                client_a.errors if client_a else ([reason] if platform in ("ado", "both") else []),
                mode, deterministic, transition_results=transition_results_a,
                defects=defects, defect_results=defect_results_a,
            )
            dlc.write_json(out_dir / "azure_devops_state.json", state_a)
            live_summary["azureDevOps"] = {
                "mode": mode, "project": project,
                "workItemsSynced": sum(1 for w in work_items if w.get("liveSynced")),
                "iterationsSynced": sum(1 for i in iterations if i.get("liveSynced")),
                "workItemsTransitioned": sum(1 for r in transition_results_a if r.get("liveTransitioned")),
                "defectsSynced": sum(1 for d in defect_results_a if d.get("liveSynced")),
                "errors": len(state_a["liveSyncErrors"]),
            }

        summary = build_sprint_plan_summary(stories, audit, approval, platform, deterministic)
        summary["totalDefects"] = len(defects)
        summary["openDefects"] = sum(1 for d in defects if d.get("status") != "Done")
        summary["resolvedDefects"] = sum(1 for d in defects if d.get("status") == "Done")
        summary.update(live_summary)
        write_sprint_plan_json(out_dir / "sprint_plan.json", summary)
        print(json.dumps({
            "action": args.action,
            "storyStatusCounts": story_status_counts(stories),
            "transitionedStories": len(target_by_id),
            "totalDefects": len(defects),
            "openDefects": summary["openDefects"],
            "resolvedDefects": summary["resolvedDefects"],
            **live_summary,
        }, indent=2))
        if all_errors:
            print(f"[dlc][warn] {len(all_errors)} live transition error(s) recorded in the state file(s).", file=sys.stderr)
            return 2
        return 0

    # sync-stories / sync-sprints
    if not audit["passed"]:
        raise dlc.GateFailure("Gate 3 audit failed — sync blocked. Fix the [FAIL] items (or pass --allow-partial-coverage for REQ gaps only).")
    if args.action == "sync-sprints":
        if not args.approved:
            raise dlc.GateFailure("--action sync-sprints requires --approved (human Gate 3 approval).")
        dlc.require_gate_approved(root, "gate_3_backlog", "Stage 3 (alm_jira_ado_bridge.py --action sync-sprints)", deterministic=deterministic)
        if approval == "PENDING_HUMAN_APPROVAL":
            approval = "APPROVED_BY_USER"
            set_approval_status(root, approval, deterministic)
    elif args.approved and approval == "PENDING_HUMAN_APPROVAL":
        approval = "APPROVED_BY_USER"
        set_approval_status(root, approval, deterministic)

    # If Stage 6 eval_results.json already exists, sync defects and infer story statuses if still in To Do
    if (root / "test" / "eval_results.json").is_file():
        defects = sync_defects_from_eval(root, stories, deterministic)
        if all(story_status(s) == "To Do" for s in stories):
            computed = compute_story_statuses_from_eval(root, stories)
            now_iso = dlc.utc_now_iso(deterministic)
            for s in stories:
                info = computed.get(s["id"])
                if info:
                    s["status"] = info["status"]
                    s["statusReason"] = info["reason"]
                    s["statusUpdatedAtUtc"] = now_iso
        enrich_story_traceability(root, stories, defects)
        update_markdown_story_statuses(root, stories)

    target_by_id_sync = {s["id"]: story_status(s) for s in stories if story_status(s) != "To Do"}

    all_errors = []
    live_summary = {}
    write_jira_csv(stories, out_dir / "jira_import.csv", jira_key_hint, defects)

    if platform in ("jira", "both"):
        client, reason = jira_client_from(args, offline)
        issue_results: list[dict[str, Any]] = []
        sprint_results: list[dict[str, Any]] = []
        transition_results_j: list[dict[str, Any]] = []
        defect_results_j: list[dict[str, Any]] = []
        mode = "OFFLINE_EXPORT_ONLY"
        if client is None:
            print(f"[dlc] Jira: offline export only ({reason}) — nothing was pushed to Jira.")
        else:
            try:
                client.myself()
                client.discover_project_and_board()
                if client.project_key:
                    issue_results = client.upsert_stories(stories)
                    mode = "LIVE_REST_API_V3"
                    sprint_results = client.reconcile_sprints(issue_results)
                    if target_by_id_sync:
                        transition_results_j = client.transition_stories(stories, target_by_id_sync)
                    if defects:
                        story_key_map = {s["id"]: str(s["jiraKey"]) for s in stories if s.get("jiraKey")}
                        defect_results_j = client.upsert_defects(defects, story_key_map)
            except HttpError as e:
                client.errors.append(f"Jira live sync aborted: {e}")
            if client.errors:
                mode = mode if issue_results else "LIVE_SYNC_FAILED"
                for err in client.errors:
                    print(f"[dlc][jira][error] {err}", file=sys.stderr)
            all_errors += client.errors
        state = jira_state_document(stories, client, jira_key_hint, approval, audit, issue_results, sprint_results,
                                    client.errors if client else [reason], mode, deterministic,
                                    transition_results=transition_results_j,
                                    defects=defects, defect_results=defect_results_j)
        dlc.write_json(out_dir / "jira_state.json", state)
        live_summary["jira"] = {"mode": mode, "projectKey": state["projectKey"], "boardId": state["boardId"],
                                "issuesSynced": sum(1 for r in issue_results if r.get("liveSynced")),
                                "sprintsSynced": sum(1 for r in sprint_results if r.get("liveSynced")),
                                "issuesTransitioned": sum(1 for r in transition_results_j if r.get("liveTransitioned")),
                                "defectsSynced": sum(1 for d in defect_results_j if d.get("liveSynced")),
                                "errors": len(state["liveSyncErrors"])}
        print(f"[dlc] Jira state ({mode}) -> {out_dir / 'jira_state.json'}")

    if platform in ("ado", "both"):
        client_a, reason = ado_client_from(args, offline)
        work_items: list[dict[str, Any]] = []
        iterations: list[dict[str, Any]] = []
        transition_results_ado: list[dict[str, Any]] = []
        defect_results_ado: list[dict[str, Any]] = []
        mode = "OFFLINE_EXPORT_ONLY"
        org = client_a.org if client_a else (args.ado_org_url or os.environ.get("ADO_ORG_URL") or None)
        project = client_a.project if client_a else (args.ado_project or os.environ.get("ADO_PROJECT") or None)
        if client_a is None:
            print(f"ADO: offline export only (no credentials) — {reason}; nothing was pushed to Azure DevOps.")
        else:
            sprint_names = sorted({sprint_short_name(sprint_label(s)) for s in stories if sprint_label(s) and not is_product_backlog(sprint_label(s))}, key=sprint_sort_key)
            iterations = client_a.ensure_iterations(sprint_names)
            ok_iterations = {i["name"] for i in iterations if i.get("liveSynced")}
            paths = {s["id"]: (client_a.iteration_path_for(sprint_label(s)) if sprint_short_name(sprint_label(s)) in ok_iterations or is_product_backlog(sprint_label(s))
                               else client_a.iteration_root()) for s in stories}
            work_items = client_a.upsert_stories(stories, paths)
            if target_by_id_sync:
                transition_results_ado = client_a.transition_stories(stories, target_by_id_sync)
            if defects:
                defect_results_ado = client_a.upsert_defects(defects)
            mode = "LIVE_REST_API_V7_1" if any(w.get("liveSynced") for w in work_items) else "LIVE_SYNC_FAILED"
            for err in client_a.errors:
                print(f"[dlc][ado][error] {err}", file=sys.stderr)
            all_errors += client_a.errors
        state = ado_state_document(stories, org, project, approval, audit, work_items, iterations,
                                   client_a.errors if client_a else [reason], mode, deterministic,
                                   transition_results=transition_results_ado,
                                   defects=defects, defect_results=defect_results_ado)
        dlc.write_json(out_dir / "azure_devops_state.json", state)
        live_summary["azureDevOps"] = {"mode": mode, "project": project,
                                       "workItemsSynced": sum(1 for w in work_items if w.get("liveSynced")),
                                       "iterationsSynced": sum(1 for i in iterations if i.get("liveSynced")),
                                       "workItemsTransitioned": sum(1 for r in transition_results_ado if r.get("liveTransitioned")),
                                       "defectsSynced": sum(1 for d in defect_results_ado if d.get("liveSynced")),
                                       "errors": len(state["liveSyncErrors"])}
        print(f"[dlc] Azure DevOps state ({mode}) -> {out_dir / 'azure_devops_state.json'}")

    if platform == "none":
        print("[dlc] No ALM platform selected — local artefacts only (set --platform or specs/target_stack.json#almPlatform).")

    persist_stories_metadata(root, stories, deterministic)

    summary = build_sprint_plan_summary(stories, audit, approval, platform, deterministic)
    summary["totalDefects"] = len(defects)
    summary["openDefects"] = sum(1 for d in defects if d.get("status") != "Done")
    summary["resolvedDefects"] = sum(1 for d in defects if d.get("status") == "Done")
    summary.update(live_summary)
    write_sprint_plan_json(out_dir / "sprint_plan.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "coverage"}, indent=2))
    if args.action == "sync-stories" and audit["passed"] and approval == "PENDING_HUMAN_APPROVAL":
        dlc.mark_gate_awaiting_human(
            root,
            "gate_3_backlog",
            summary="Stage 3 User Stories & Sprint Plan staged on ALM board. Present stories + sprint plan + board links to user and STOP for Gate 3 approval before Stage 4.",
            deterministic=deterministic,
        )
    if all_errors:
        print(f"[dlc][warn] {len(all_errors)} live sync error(s) recorded in the state file(s); the live sync is incomplete.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
