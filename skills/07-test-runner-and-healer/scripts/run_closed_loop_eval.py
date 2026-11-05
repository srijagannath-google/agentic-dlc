#!/usr/bin/env python3
"""Stage 6 — Closed-loop behavioural evaluator for agentic-dlc v4.

Executes `test/test_cases.json` against the built application:

  * runtime=browser  → adapter chain: playwright (python) → chrome-headless (any Chrome/Chromium/Edge binary,
                       zero deps; a harness HTML inlines `dom_driver.js` and results are read back from
                       `--dump-dom`) → none (NOT_RUN with an install hint).
  * runtime=http     → `urllib` against `target_stack.commands.start`, after polling `commands.healthcheck`.
  * runtime=static   → stdlib `html.parser` over the UI entry source (leakage scan, a11y lint).

Cross-cutting checks computed from every rendered DOM state the browser reached:
  TC-UI-LEAK-01..04 (token classes from `forbiddenUiTokens`), TC-UI-INTERACT-01 (dead controls),
  TC-A11Y-01 (labels / alt / h1 / lang / tabindex / names), TC-UX-SIMPLE-01..03 (_shared/ux_guardrails.md).

Before running it snapshots `src/` → `test/.snapshots/iter-N/`; afterwards it writes
`test/eval_results.json` (docs/ARCHITECTURE.md §4.7), `test/eval_report.md` and
`test/remediation_and_guardrail_audit_report.md` (real `difflib.unified_diff` between iterations,
guardrail-sensitive hunks flagged for Gate 4). Nothing in here prints a static PASS.

Gate 4 state is persisted in `test/.guardrail_state.json` (pending / approved hunk hashes + the approved baseline
iteration) so a flag cannot be cleared by simply re-running with an unchanged tree; `--approve-guardrail-flags`
moves the pending hashes to the approved set. The chrome-headless harness is served over http://127.0.0.1 by a
tiny in-process reverse proxy (same origin as the app), so Chrome runs without `--disable-web-security` /
`--allow-file-access-from-files`.

Usage:
  python3 run_closed_loop_eval.py --project-root <PROJECT_ROOT> [--iteration N] [--browser auto|playwright|chrome|none]
                                  [--chrome-binary PATH] [--skip-backend] [--deterministic] [--alm-sync]
                                  [--approve-guardrail-flags] [--selftest-guardrail-patterns]
Exit codes: 0 verdict PASS and guardrail status CLEAR (or approved) · 1 verdict FAIL · 3 verdict PASS but
GUARDRAIL_REVIEW_STATUS is FLAGGED_REQUIRES_HUMAN_APPROVAL (Gate 4 — re-run with --approve-guardrail-flags after review).
"""
from __future__ import annotations

import argparse
import base64
import difflib
import hashlib
import html as html_mod
import http.server
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import dlc_common as dlc  # noqa: E402

HERE = Path(__file__).resolve().parent
DRIVER_JS = HERE / "dom_driver.js"
SNAPSHOT_IGNORE = shutil.ignore_patterns("node_modules", "__pycache__", ".venv", "venv", ".git", "dist", "build", "*.pyc",
                                         "*.sqlite", "*.sqlite3", "*.db", "*.log")  # runtime data files are not source
CHROME_CANDIDATES = [
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge",
    "/opt/google/chrome/chrome", "/usr/bin/google-chrome", "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]
BROWSER_INSTALL_HINT = ("No browser runtime found. Install Google Chrome / Chromium / Edge (any version with --headless), "
                        "or `pip install playwright && playwright install chromium`, or pass --chrome-binary / $CHROME_BIN.")

# Generic heuristics → warnings only (see _shared/zero_leak.md)
HEURISTIC_PATTERNS = {
    "upper-snake-token": re.compile(r"\b[A-Z]{2,}_[A-Z0-9_]{3,}\b"),
    "uuid": re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),
    "sql-fragment": re.compile(r"\b(SELECT\s+.+\s+FROM|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|JOIN\s+\w+\s+ON)\b", re.I),
    "stack-trace": re.compile(r"(Traceback \(most recent call last\)|\bat\s+\w+(\.\w+)+\(|Exception in thread|TypeError:|ReferenceError:|NullPointerException)"),
    "engineering-note": re.compile(r"\b(TODO|FIXME|XXX|HACK|parity)\b", re.I),
    "raw-model-sku": re.compile(r"\b(gemini-[0-9]+\.[0-9]+-(?:flash|pro|ultra)|gpt-4[o0-9-]*|claude-3[-a-z0-9]*)\b", re.I),
    "api-path": re.compile(r"(^|\s)/api/[\w/\-{}]+"),
    "long-hex-hash": re.compile(r"\b[0-9a-f]{32,}\b"),
}
# Default mapping of TC-UI-LEAK-NN → forbiddenUiTokens classes (a TC may override with "tokenClasses": [...]).
LEAK_CLASS_BY_INDEX = {
    1: ["schemaIdentifiers"],
    2: ["enumCodes"],
    3: ["legacyIdentifiers", "engineeringNotePatterns", "internalIds", "internalHarnessLeak"],
    4: ["piiPatterns"],
}
LEAK_REGEX_CLASSES = {"piiPatterns", "engineeringNotePatterns"}  # these classes hold regexes, not literal tokens
LEAK_SKIP_CLASSES = {"schemaIdentifiersIgnored", "enumCodesWarnOnly"}  # never FAIL-scanned (see LEAK_WARN_CLASSES)
LEAK_WARN_CLASSES = ["enumCodesWarnOnly"]  # literal tokens reported as warnings only
DEFERRED_ACTIONS = {"expectAllControlsWired", "expectA11yBaseline", "expectNoVisibleTextMatching"}  # need every rendered state
MIN_STATIC_CORPUS_CHARS = 40  # below this, a static-only visible-text corpus (SPA shell) cannot support a leak verdict

# Guardrail-sensitive patterns for the audit report (§3). State names / triggers / rule identifiers are
# added at runtime from the spec — nothing domain-specific lives here.
# Stems are matched case-insensitively with a LEFT boundary only (no `\b` on the right) so plurals/suffixes match, and
# additionally in camelCase position (a Capitalised stem right after a lowercase letter/digit/underscore) so
# `allowedRoles`, `userRole`, `hasRole(`, `canApprove(`, `@PreAuthorize`, `hasPermission(`, `checkRole(` and
# `ALLOWED_TRANSITIONS` are all caught (`--selftest-guardrail-patterns` asserts exactly that list, see GUARDRAIL_SELFTEST).
def stem_regex(stems: list[str], extra: list[str] | None = None) -> re.Pattern[str]:
    alt = "|".join(stems)
    camel = "|".join(s[:1].upper() + s[1:] for s in stems)
    parts = [rf"(?<![A-Za-z])(?i:{alt})", rf"(?<=[a-z0-9_])(?:{camel})"] + list(extra or [])
    return re.compile("|".join(parts))


GUARDRAIL_PATTERNS: dict[str, re.Pattern[str]] = {
    "role/permission check": stem_regex(["role", "permission", "allowed", "allow", "deny", "denied", "authori[sz]", "preauthori[sz]", "rbac", "canapprove", "cantransition",
                                         "isinternal", "isexternal", "actorrole", "currentrole", "privilege", "forbidden", "unauthori[sz]"],
                                        [r"@PreAuthorize", r"@Secured", r"@RolesAllowed", r"hasAnyAuthority", r"hasAuthority"]),
    "state guard": stem_regex(["transition", "guard", "fromstate", "tostate", "currentstate", "nextstate", "allowedfrom", "prerequisite", "statemachine"]),
    "masking / PII": stem_regex(["mask", "redact", "pii", "sensitive", "anonymi[sz]", "obfuscat"]),
    "accessibility": re.compile(r"(aria-|\brole=|<label\b|tabindex|\balt=|\blang=|\bfor=|accesskey)", re.I),
    "leakage label mapping": re.compile(r"(label\s*map|_LABELS\b|labelFor|toLabel|displayName|statusLabel|humanLabel|enumLabel|LABELS\s*[=:])", re.I),
    "business formula / threshold": stem_regex(["formula", "rate", "threshold", "accrual", "balance", "penalt", "surcharge", "percent", "rounding"], [r"\bround\("]),
}
# Every identifier here must be matched by at least one GUARDRAIL_PATTERNS entry (checked by --selftest-guardrail-patterns).
GUARDRAIL_SELFTEST = ["allowedRoles", "userRole", "hasRole(", "canApprove(", "@PreAuthorize", "hasPermission(", "checkRole(",
                      "ALLOWED_TRANSITIONS", "aria-label", "maskSsn", "redactEmail", "ROLE_PERMISSIONS", "isTransitionAllowed",
                      "guardFor(", "nextState", "APPROVAL_THRESHOLD", "accrualRate", "<label for=", "tabindex=\"0\"",
                      "STATUS_LABELS", "authorizeTransition", "can_transition("]
DIFF_CONTEXT_LINES = 6  # unified-diff context so a one-line change inside a guard function is classified with its surroundings
GUARDRAIL_STATE_FILE = "test/.guardrail_state.json"
BACKEND_PIDFILE = "test/.build_logs/backend.pid"  # process-group id of the backend started by validate_build.py / this script


def selftest_guardrail_patterns() -> list[str]:
    """Return the identifiers in GUARDRAIL_SELFTEST that no guardrail pattern matches (empty list == OK)."""
    return [ident for ident in GUARDRAIL_SELFTEST if not any(rx.search(ident) for rx in GUARDRAIL_PATTERNS.values())]


# ======================================================================================
# Small utilities
# ======================================================================================
def now_ms() -> int:
    return int(time.time() * 1000)


def existing_iterations(root: Path) -> list[int]:
    nums: set[int] = set()
    for d in (root / "test" / ".snapshots", root / "test" / "history"):
        if d.is_dir():
            for p in d.glob("iter-*"):
                if m := re.match(r"^iter-(\d+)$", p.name):
                    nums.add(int(m.group(1)))
    test_dir = root / "test"
    if test_dir.is_dir():
        for p in test_dir.glob("eval_results.iter-*.json"):
            if m := re.match(r"^eval_results\.iter-(\d+)\.json$", p.name):
                nums.add(int(m.group(1)))
    return sorted(nums)


def preserve_existing_top_level_eval_artifacts(root: Path) -> None:
    """Before starting a new run, ensure any pre-existing top-level evaluation or remediation files
    are safely archived under test/history/iter-M/, test/.snapshots/iter-M/ (only if that snapshot already
    exists — a baseline is never fabricated from the current tree) and test/*.iter-MM.* so prior run results
    and remediation records are never overwritten or lost.
    """
    prev_json_p = root / "test" / "eval_results.json"
    if not prev_json_p.is_file():
        return
    try:
        prev_data = dlc.read_json(prev_json_p)
        prev_it = int(prev_data.get("iteration") or 1) if isinstance(prev_data, dict) else 1
    except Exception:
        prev_it = 1
    hist_dir = root / "test" / "history" / f"iter-{prev_it}"
    snap_dir = root / "test" / ".snapshots" / f"iter-{prev_it}"
    hist_dir.mkdir(parents=True, exist_ok=True)
    artifacts = [
        (root / "test" / "eval_results.json", "eval_results.json", f"eval_results.iter-{prev_it:02d}.json"),
        (root / "test" / "eval_report.md", "eval_report.md", f"eval_report.iter-{prev_it:02d}.md"),
        (root / "test" / "remediation_and_guardrail_audit_report.md", "remediation_and_guardrail_audit_report.md", f"remediation_and_guardrail_audit_report.iter-{prev_it:02d}.md"),
        (root / "backlog" / "defects.json", "defects.json", f"defects.iter-{prev_it:02d}.json"),
        (root / "backlog" / "defects.md", "defects.md", f"defects.iter-{prev_it:02d}.md"),
    ]
    for src_p, base_name, numbered_name in artifacts:
        if not src_p.is_file():
            continue
        targets = [hist_dir / base_name, root / "test" / numbered_name]
        if snap_dir.is_dir():
            targets.insert(1, snap_dir / base_name)
        for target_p in targets:
            if not target_p.exists():
                target_p.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_p, target_p)


def next_iteration(snap_dir: Path, root: Path | None = None) -> int:
    proj_root = root or snap_dir.parent.parent
    nums = existing_iterations(proj_root)
    return (max(nums) + 1) if nums else 1


def resolve_iteration(root: Path, requested: int | None) -> int:
    preserve_existing_top_level_eval_artifacts(root)
    nums = existing_iterations(root)
    nxt = (max(nums) + 1) if nums else 1
    if requested is None:
        return nxt
    snap_exists = (root / "test" / ".snapshots" / f"iter-{requested}").exists()
    hist_exists = (root / "test" / "history" / f"iter-{requested}").exists()
    numbered_exists = (root / "test" / f"eval_results.iter-{requested:02d}.json").exists()
    if requested in nums or snap_exists or hist_exists or numbered_exists:
        dlc.info(
            f"Iteration {requested} already has preserved artifacts in test/.snapshots or test/history — "
            f"auto-advancing to iteration {nxt} so prior run results and remediation files are never overwritten."
        )
        return nxt
    return requested


def snapshot_src(root: Path, iteration: int) -> tuple[Path, Path | None]:
    """Snapshot src/ → test/.snapshots/iter-N. An existing iter-N is never overwritten silently: it is moved to
    iter-N.prev (returned as the second element) so the audit report can diff against it."""
    dest = root / "test" / ".snapshots" / f"iter-{iteration}"
    displaced: Path | None = None
    if dest.exists():
        displaced = dest.with_name(f"iter-{iteration}.prev")
        if displaced.exists():
            shutil.rmtree(displaced)
        dest.rename(displaced)
        dlc.warn(f"snapshot iter-{iteration} already existed — moved to {displaced.name}; this run is diffed against it")
    src = root / "src"
    if src.exists():
        shutil.copytree(src, dest, ignore=SNAPSHOT_IGNORE, dirs_exist_ok=True)
    else:
        dest.mkdir(parents=True, exist_ok=True)
    return dest, displaced


def load_iteration_eval(root: Path, iteration: int) -> dict[str, Any] | None:
    for cand in (
        root / "test" / "history" / f"iter-{iteration}" / "eval_results.json",
        root / "test" / ".snapshots" / f"iter-{iteration}" / "eval_results.json",
        root / "test" / f"eval_results.iter-{iteration:02d}.json",
    ):
        if cand.is_file():
            try:
                doc = dlc.read_json(cand)
                if isinstance(doc, dict):
                    return doc
            except Exception:
                pass
    return None


# ---- process-group helpers (prefer dlc_common's if present; local fallback otherwise) ----
def start_process_group(cmd: str, cwd: Path, env: dict[str, str], log_path: Path) -> subprocess.Popen:
    fn = getattr(dlc, "start_process_group", None)
    if fn is not None:
        try:
            return fn(cmd, cwd, env, log_path)
        except TypeError:
            pass  # signature mismatch — use the local implementation
    log = open(log_path, "wb")
    kwargs: dict[str, Any] = {}
    if os.name != "nt":
        kwargs["start_new_session"] = True
    else:
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(cmd, shell=True, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT, env=env, **kwargs)


def stop_process_group(proc: subprocess.Popen, timeout: float = 5) -> None:
    fn = getattr(dlc, "stop_process_group", None)
    if fn is not None:
        try:
            fn(proc, timeout=timeout)
            return
        except TypeError:
            pass
    try:
        if os.name != "nt":
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        else:
            proc.terminate()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
            proc.wait(timeout=timeout)
    except ProcessLookupError:
        pass
    except Exception as e:  # pragma: no cover
        dlc.warn(f"could not stop process group cleanly: {e}")


def _pgid_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def reap_pidfile(pidfile: Path) -> bool:
    """If a previous run (this script or validate_build.py) left its backend process group recorded in `pidfile`
    and that group is still alive, stop it (TERM → KILL). Never touches any process we did not record ourselves."""
    if not pidfile.exists() or os.name == "nt":
        return False
    try:
        pgid = int(dlc.read_text(pidfile).strip() or "0")
    except (ValueError, OSError):
        pgid = 0
    reaped = False
    if pgid > 1 and pgid != os.getpid() and _pgid_alive(pgid):
        dlc.warn(f"stale backend process group {pgid} recorded in {pidfile.name} is still alive — stopping it")
        try:
            os.killpg(pgid, signal.SIGTERM)
            deadline = time.time() + 5
            while time.time() < deadline and _pgid_alive(pgid):
                time.sleep(0.2)
            if _pgid_alive(pgid):
                os.killpg(pgid, signal.SIGKILL)
                time.sleep(0.3)
            reaped = True
        except Exception as e:
            dlc.warn(f"could not stop stale process group {pgid}: {e}")
    pidfile.unlink(missing_ok=True)
    return reaped


def chrome_sandbox_flags() -> list[str]:
    """`--no-sandbox` only where the sandbox cannot work: running as root, or when the user opts in explicitly."""
    try:
        is_root = os.geteuid() == 0  # type: ignore[attr-defined]
    except AttributeError:
        is_root = False
    return ["--no-sandbox"] if (is_root or os.environ.get("DLC_CHROME_NO_SANDBOX") == "1") else []


def run_chrome(cmd: list[str], timeout_s: float) -> tuple[int, str, str]:
    """Run a one-shot headless Chrome in its own session; on timeout kill the whole process group."""
    kwargs: dict[str, Any] = {"start_new_session": True} if os.name != "nt" else {}
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kwargs)
    try:
        out, err = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        try:
            if os.name != "nt":
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except Exception:
            pass
        proc.communicate()
        raise
    return proc.returncode, out or "", err or ""


def run_alm_bridge(root: Path, stack: dict[str, Any], action_args: list[str], deterministic: bool, skip: bool, force: bool) -> bool:
    """Call 03/scripts/alm_jira_ado_bridge.py unless (a) --skip-alm-sync, (b) target_stack.almPlatform is `none`/missing,
    or (c) --deterministic (golden runs) — (b) and (c) can be overridden with --alm-sync. Returns True when the bridge ran."""
    if skip:
        return False
    helper = getattr(dlc, "run_alm_bridge", None)
    if helper is not None:
        try:
            return bool(helper(root, action_args, deterministic=deterministic, force=force))
        except TypeError:
            pass
    platform = str(stack.get("almPlatform") or "none").strip().lower()
    if not force:
        if platform in ("", "none"):
            dlc.info("ALM sync skipped: target_stack.almPlatform is 'none' (pass --alm-sync to update backlog/ anyway)")
            return False
        if deterministic:
            dlc.info("ALM sync skipped under --deterministic (pass --alm-sync to force)")
            return False
    bridge = Path(__file__).resolve().parents[2] / "03-story-and-sprint-planner" / "scripts" / "alm_jira_ado_bridge.py"
    if not bridge.is_file() or not (root / "backlog" / "user_stories.json").is_file():
        return False
    cmd = [sys.executable, str(bridge), "--project-root", str(root), *action_args] + (["--deterministic"] if deterministic else [])
    cp = subprocess.run(cmd, cwd=str(root))
    if cp.returncode not in (0, 2):
        dlc.warn(f"ALM bridge ({' '.join(action_args)}) returned {cp.returncode}")
    return True


def status_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    c = {"PASS": 0, "FAIL": 0, "NOT_RUN": 0, "ERROR": 0, "WARN": 0}
    for r in results:
        c[r["status"]] = c.get(r["status"], 0) + 1
    return c


def json_path(obj: Any, path: str) -> Any:
    """Resolve simple `$.a.b[0].c` JSON paths."""
    path = path.strip()
    if path.startswith("$"):
        path = path[1:]
    for tok in re.findall(r"\.?([^.\[\]]+)|\[(\d+)\]", path):
        key, idx = tok
        if key:
            if not isinstance(obj, dict) or key not in obj:
                raise KeyError(key)
            obj = obj[key]
        else:
            if not isinstance(obj, list) or int(idx) >= len(obj):
                raise KeyError(f"[{idx}]")
            obj = obj[int(idx)]
    return obj


def which_browser(explicit: str | None) -> str | None:
    cands = ([explicit] if explicit else []) + ([os.environ["CHROME_BIN"]] if os.environ.get("CHROME_BIN") else []) + CHROME_CANDIDATES
    for c in cands:
        if not c:
            continue
        if os.path.sep in c or (os.name == "nt" and ":" in c):
            if Path(c).exists():
                return c
        else:
            w = shutil.which(c)
            if w:
                return w
    return None


# ======================================================================================
# Backend lifecycle
# ======================================================================================
class Backend:
    def __init__(self, root: Path, commands: dict[str, Any], skip: bool, log_dir: Path):
        self.root = root
        self.start_cmd = (commands.get("start") or "").strip()
        self.healthcheck = (commands.get("healthcheck") or "").strip()
        self.skip = skip or not self.start_cmd
        self.proc: subprocess.Popen | None = None
        self.started = False
        self.error = ""
        self.stale_port = False  # True when a server this run did not start owns the port → every runtime-dependent TC is ERROR
        self.log_dir = log_dir
        self.pidfile = root / BACKEND_PIDFILE
        self.base_url = ""
        if self.healthcheck:
            u = urllib.parse.urlsplit(self.healthcheck)
            self.base_url = f"{u.scheme}://{u.netloc}"

    def __enter__(self) -> "Backend":
        if self.skip:
            if self.healthcheck and self._healthy(timeout=2):
                self.started = True  # something already serving (e.g. started by the user)
                dlc.info(f"backend already answering at {self.healthcheck} (not started by this run)")
            return self
        self.log_dir.mkdir(parents=True, exist_ok=True)
        # Reap only the backend a previous validate_build.py / eval run recorded in the pidfile (never a /proc-wide sweep).
        if reap_pidfile(self.pidfile):
            time.sleep(0.3)
        if self.healthcheck and self._healthy(timeout=1):
            dlc.warn(f"{self.healthcheck} already answers BEFORE the start command ran — a stale server (previous run?) owns the port; "
                     "the new process would fail to bind and results would come from stale code. Stop it first or pass --skip-backend.")
            self.error = "port already in use by a process this run did not start"
            self.stale_port = True
            return self
        env = dict(os.environ)
        if self.healthcheck:
            port = urllib.parse.urlsplit(self.healthcheck).port
            if port:
                env.setdefault("PORT", str(port))
        dlc.info(f"starting backend: {self.start_cmd}")
        self.proc = start_process_group(self.start_cmd, self.root, env, self.log_dir / "backend.log")
        try:
            pgid = os.getpgid(self.proc.pid) if os.name != "nt" else self.proc.pid
            dlc.write_text(self.pidfile, str(pgid))
        except Exception:
            pass
        if not self.healthcheck:
            time.sleep(2)
            self.started = self.proc.poll() is None
            if not self.started:
                self.error = "start command exited early (no healthcheck configured)"
            return self
        if self._healthy(timeout=30):
            self.started = True
            dlc.info(f"backend healthy at {self.healthcheck}")
        else:
            self.error = f"healthcheck {self.healthcheck} did not return 2xx within 30s"
            if self.proc.poll() is not None:
                self.error += f" (process exited with code {self.proc.returncode})"
            dlc.warn(self.error)
        return self

    def _healthy(self, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(self.healthcheck, timeout=2) as resp:
                    if 200 <= resp.status < 300:
                        return True
            except Exception:
                pass
            if self.proc is not None and self.proc.poll() is not None:
                return False
            time.sleep(0.4)
        return False

    def __exit__(self, *exc: Any) -> None:
        if self.proc is None:
            return
        stop_process_group(self.proc, timeout=5)
        self.pidfile.unlink(missing_ok=True)

    def log_tail(self, n: int = 30) -> str:
        p = self.log_dir / "backend.log"
        if not p.exists():
            return ""
        return "\n".join(dlc.read_text(p).splitlines()[-n:])


# ======================================================================================
# UI entry resolution
# ======================================================================================
class UiEntry:
    def __init__(self, root: Path, ui_entry: str):
        self.raw = ui_entry or "src/ui/index.html"
        self.is_url = bool(re.match(r"^https?://", self.raw))
        self.path = None if self.is_url else dlc.project_path(root, self.raw)
        self.error = ""

    def source(self) -> str:
        if self.is_url:
            try:
                with urllib.request.urlopen(self.raw, timeout=10) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except Exception as e:
                self.error = f"could not fetch uiEntry {self.raw}: {e}"
                return ""
        if self.path and self.path.exists():
            return dlc.read_text(self.path)
        self.error = f"uiEntry file not found: {self.path}"
        return ""

    def entry_path(self) -> str:
        """URL path of the entry document as the app sees it (used for <base href> / history.replaceState in the harness)."""
        if self.is_url:
            return urllib.parse.urlsplit(self.raw).path or "/"
        assert self.path is not None
        return "/" + self.path.name


# ======================================================================================
# Harness server — serves the chrome-headless harness over http://127.0.0.1 on the app's own origin
# ======================================================================================
class HarnessServer:
    """Tiny stdlib ThreadingHTTPServer on an ephemeral localhost port.

    * uiEntry is an http URL  → every request except `/__dlc_harness/<token>` is reverse-proxied to the backend origin,
      so the injected harness page, the app's assets and its `fetch('/api/…')` calls all share ONE origin
      (no CORS, no `--disable-web-security`, no `file://` tricks).
    * uiEntry is a file         → files are served from the entry document's directory instead.
    """

    HARNESS_PREFIX = "/__dlc_harness/"

    def __init__(self, ui: UiEntry):
        self.ui = ui
        self.upstream: str | None = None
        self.static_dir: Path | None = None
        if ui.is_url:
            u = urllib.parse.urlsplit(ui.raw)
            self.upstream = f"{u.scheme}://{u.netloc}"
        else:
            assert ui.path is not None
            self.static_dir = ui.path.parent.resolve()
        self.entry_path = ui.entry_path()
        self.docs: dict[str, str] = {}
        self.lock = threading.Lock()
        self._seq = 0
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a: Any) -> None:  # silence per-request logging
                pass

            def _send(self, status: int, body: bytes, ctype: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _handle(self) -> None:
                m = re.match(r"^" + re.escape(HarnessServer.HARNESS_PREFIX) + r"([A-Za-z0-9_-]+)(?:[/?#].*)?$", self.path)
                if m:
                    with outer.lock:
                        doc = outer.docs.get(m.group(1))
                    if doc is None:
                        self._send(404, b"unknown harness token", "text/plain; charset=utf-8")
                    else:
                        self._send(200, doc.encode("utf-8"), "text/html; charset=utf-8")
                    return
                if outer.upstream:
                    self._proxy()
                else:
                    self._static()

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _handle

            def _proxy(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else None
                if body is None and self.command in ("POST", "PUT", "PATCH"):
                    body = b""
                headers = {k: v for k, v in self.headers.items()
                           if k.lower() not in ("host", "connection", "content-length", "accept-encoding", "keep-alive")}
                req = urllib.request.Request(outer.upstream + self.path, data=body, method=self.command, headers=headers)  # type: ignore[operator]
                try:
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        status, hdrs, data = resp.status, list(resp.getheaders()), resp.read()
                except urllib.error.HTTPError as e:
                    status, hdrs, data = e.code, list(e.headers.items()), e.read()
                except Exception as e:
                    self._send(502, f"harness proxy could not reach {outer.upstream}: {e}".encode("utf-8"), "text/plain; charset=utf-8")
                    return
                self.send_response(status)
                for k, v in hdrs:
                    if k.lower() in ("transfer-encoding", "connection", "content-length", "content-encoding", "keep-alive"):
                        continue
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(data)

            def _static(self) -> None:
                import mimetypes
                assert outer.static_dir is not None
                rel = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path).lstrip("/")
                if not rel or rel.endswith("/"):
                    rel = (rel + outer.entry_path.lstrip("/")) if rel else outer.entry_path.lstrip("/")
                p = (outer.static_dir / rel).resolve()
                if not str(p).startswith(str(outer.static_dir)) or not p.is_file():
                    self._send(404, b"not found", "text/plain; charset=utf-8")
                    return
                ctype = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                    ctype += "; charset=utf-8"
                self._send(200, p.read_bytes(), ctype)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True  # type: ignore[attr-defined]
        self.origin = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
        self.thread.start()

    def base_href(self) -> str:
        d = self.entry_path.rsplit("/", 1)[0] + "/"
        return self.origin + d

    def register(self, doc: str) -> tuple[str, str]:
        with self.lock:
            self._seq += 1
            token = f"h{self._seq}-{hashlib.sha1(doc.encode('utf-8')).hexdigest()[:10]}"
            self.docs[token] = doc
        return token, f"{self.origin}{self.HARNESS_PREFIX}{token}"

    def unregister(self, token: str) -> None:
        with self.lock:
            self.docs.pop(token, None)

    def close(self) -> None:
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass


# ======================================================================================
# Browser adapters
# ======================================================================================
class ChromeAdapter:
    name = "chrome-headless"

    def __init__(self, binary: str, ui: UiEntry, tmp: Path, timeout_s: int = 90):
        self.binary = binary
        self.ui = ui
        self.tmp = tmp
        self.timeout_s = timeout_s
        self.driver = dlc.read_text(DRIVER_JS)
        self.server = HarnessServer(ui)
        self.force_no_sandbox = False  # set when Chrome itself reports it cannot set up its sandbox here
        self.screenshot_dir: Path | None = None

    def close(self) -> None:
        self.server.close()

    def _chrome_flags(self, prof: Path) -> list[str]:
        flags = [self.binary, "--headless=new", "--disable-gpu", "--disable-dev-shm-usage", "--hide-scrollbars",
                 "--disable-extensions", "--no-first-run", "--no-default-browser-check", "--password-store=basic",
                 "--use-mock-keychain", f"--user-data-dir={prof}"]
        flags += chrome_sandbox_flags() or (["--no-sandbox"] if self.force_no_sandbox else [])
        return flags

    def build_harness(self, app_html: str, steps: list[dict[str, Any]], settle_ms: int) -> str:
        prelude = f"<script data-dlc=\"prelude\">\n{self.driver}\nwindow.__dlcInstallPrelude();\n</script>"
        base = f'<base href="{html_mod.escape(self.server.base_href())}">' if not re.search(r"<base\b", app_html, re.I) else ""
        # The harness lives at /__dlc_harness/<token>; present the app with its real entry path (same origin, so allowed).
        path_fix = f"<script data-dlc=\"path\">try{{history.replaceState(null,'',{json.dumps(self.server.entry_path)});}}catch(e){{}}</script>"
        head_inject = base + path_fix + prelude
        if re.search(r"<head[^>]*>", app_html, re.I):
            doc = re.sub(r"(<head[^>]*>)", lambda m: m.group(1) + head_inject, app_html, count=1, flags=re.I)
        elif re.search(r"<html[^>]*>", app_html, re.I):
            doc = re.sub(r"(<html[^>]*>)", lambda m: m.group(1) + "<head>" + head_inject + "</head>", app_html, count=1, flags=re.I)
        else:
            doc = head_inject + app_html
        steps_json = json.dumps(steps).replace("</", "<\\/")
        # Results are emitted base64(utf-8 JSON) so --dump-dom serialisation (entity encoding, `</`) can never corrupt them.
        runner = f"""<script data-dlc="runner">
(function(){{
  function emit(obj){{
    var s=document.createElement('script'); s.type='application/json'; s.id='__dlc_results';
    var json=JSON.stringify(obj);
    try {{ s.textContent='b64:'+btoa(unescape(encodeURIComponent(json))); }}
    catch(e) {{ s.textContent=json.replace(/</g,'\\\\u003c'); }}
    document.documentElement.appendChild(s);
  }}
  function go(){{
    window.__dlcRun({steps_json}, {{settleMs:{settle_ms}}}).then(emit).catch(function(e){{
      emit({{status:'ERROR', failedStep:null, message:'driver crashed: '+(e&&e.message||e), actual:'', steps:[], controls:[], a11y:[], visibleText:'', visibleTextAllStates:''}});
    }});
  }}
  if (document.readyState==='complete') go(); else window.addEventListener('load', go);
}})();
</script>"""
        if re.search(r"</body>", doc, re.I):
            doc = re.sub(r"</body>", lambda m: runner + "</body>", doc, count=1, flags=re.I)
        else:
            doc += runner
        return doc

    @staticmethod
    def _decode_results(payload: str) -> dict[str, Any]:
        payload = payload.strip()
        if payload.startswith("b64:"):
            return json.loads(base64.b64decode(payload[4:]).decode("utf-8"))
        # legacy path: only unescape when the dump actually entity-encoded the JSON
        if "&quot;" in payload or "&lt;" in payload or "&amp;" in payload:
            payload = html_mod.unescape(payload)
        return json.loads(payload)

    def _run_harness(self, app_html: str, steps: list[dict[str, Any]], settle: int, safe_id: str) -> tuple[dict[str, Any], str, str]:
        """Serve the harness for `steps`, run Chrome once (--dump-dom) and parse the results.
        Returns (result, harness_url, token) — the caller must `self.server.unregister(token)` when done with the URL."""
        wait_total = sum(int(s.get("ms", 0)) for s in steps if s.get("action") == "wait")
        budget = min(60000, 4000 + settle + wait_total + 400 * len(steps))
        harness = self.build_harness(app_html, steps, settle)
        token, url = self.server.register(harness)
        self._last_budget = budget
        t0 = now_ms()
        attempt = 0
        while True:
            attempt += 1
            prof = self.tmp / f"prof-{safe_id}-{attempt}"
            prof.mkdir(parents=True, exist_ok=True)
            cmd = self._chrome_flags(prof) + [f"--virtual-time-budget={budget}", "--run-all-compositor-stages-before-draw", "--dump-dom", url]
            timeout_s = max(float(self.timeout_s), budget / 1000.0 + 15)  # wall-clock must exceed the virtual-time budget
            try:
                rc, out, err = run_chrome(cmd, timeout_s)
            except subprocess.TimeoutExpired:
                return {"status": "ERROR", "message": f"chrome timed out after {timeout_s:.0f}s (virtual-time budget {budget}ms)", "actual": "", "durationMs": now_ms() - t0}, url, token
            except OSError as e:
                return {"status": "ERROR", "message": f"could not launch chrome: {e}", "actual": "", "durationMs": now_ms() - t0}, url, token
            finally:
                shutil.rmtree(prof, ignore_errors=True)
            m = re.search(r'<script type="application/json" id="__dlc_results">(.*?)</script>', out, re.S)
            if m:
                break
            low = (err or "").lower()
            if attempt == 1 and not self.force_no_sandbox and not chrome_sandbox_flags() and ("sandbox" in low or "zygote" in low):
                dlc.warn("chrome could not start its sandbox in this environment — retrying with --no-sandbox (set DLC_CHROME_NO_SANDBOX=1 to skip this probe)")
                self.force_no_sandbox = True
                continue
            tail = (err or "").strip().splitlines()[-5:]
            return {"status": "ERROR", "message": f"harness produced no results (page JS may have thrown before load, or chrome failed, rc={rc})",
                    "actual": " | ".join(tail)[:500], "durationMs": now_ms() - t0}, url, token
        try:
            res = self._decode_results(m.group(1))
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as e:
            return {"status": "ERROR", "message": f"could not parse harness results: {e}", "actual": m.group(1)[:300], "durationMs": now_ms() - t0}, url, token
        res["durationMs"] = now_ms() - t0
        return res, url, token

    def run(self, tc: dict[str, Any], app_html: str) -> dict[str, Any]:
        steps = tc.get("steps") or []
        settle = int(tc.get("settleMs", 150))
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", tc.get("id", "tc"))
        res, url, token = self._run_harness(app_html, steps, settle, safe_id)
        try:
            if res.get("status") in ("FAIL", "ERROR") and self.screenshot_dir:
                shot_path = self.screenshot_dir / f"fail-{safe_id}.png"
                if self._take_screenshot(url, shot_path, getattr(self, "_last_budget", 800)):
                    res["screenshot"] = str(shot_path)
        finally:
            self.server.unregister(token)
        return res

    def _take_screenshot(self, url: str, out_png: Path, budget: int = 800) -> bool:
        out_png.parent.mkdir(parents=True, exist_ok=True)
        prof = self.tmp / f"prof-shot-{out_png.stem}"
        prof.mkdir(parents=True, exist_ok=True)
        cmd = self._chrome_flags(prof) + ["--window-size=1440,900", f"--virtual-time-budget={min(budget, 1200)}", f"--screenshot={out_png}", url]
        try:
            run_chrome(cmd, 10)
            return out_png.exists() and out_png.stat().st_size > 0
        except Exception:
            return False
        finally:
            shutil.rmtree(prof, ignore_errors=True)

    def capture_visual_evidence(self, app_html: str, screenshot_dir: Path, root: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        """Capture initial landing screenshot + per-tab screenshots; each tab is clicked through the in-page driver, whose
        click step verifies the controlled panel gets a non-zero bounding box and sibling panels hide (unwired tabs are reported)."""
        self.screenshot_dir = screenshot_dir
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        shots: list[dict[str, str]] = []
        unwired_tabs: list[dict[str, str]] = []

        def rel_of(p: Path) -> str:
            return str(p.relative_to(root)) if p.is_relative_to(root) else str(p)

        # 1. Initial landing view
        token, url = self.server.register(self.build_harness(app_html, [{"action": "goto", "target": "ui"}], 150))
        try:
            init_png = screenshot_dir / "landing-initial.png"
            if self._take_screenshot(url, init_png):
                shots.append({"label": "Initial landing view (1440x900)", "path": rel_of(init_png), "kind": "landing"})
        finally:
            self.server.unregister(token)
        # 2. Discover top-level [role="tab"] selectors from HTML source, click each through the driver and capture the view
        tab_matches = re.findall(r'<[^>]*\brole\s*=\s*["\']tab["\'][^>]*>', app_html, re.I)
        for idx, tag_html in enumerate(tab_matches[:8]):
            m_tid = re.search(r'\bdata-testid\s*=\s*["\']([^"\']+)["\']', tag_html, re.I)
            m_id = re.search(r'\bid\s*=\s*["\']([^"\']+)["\']', tag_html, re.I)
            m_ctrl = re.search(r'\baria-controls\s*=\s*["\']([^"\']+)["\']', tag_html, re.I)
            sel = f"[data-testid={m_tid.group(1)}]" if m_tid else (f"#{m_id.group(1)}" if m_id else None)
            if not sel:
                continue
            slug = re.sub(r"[^a-z0-9]+", "-", (m_tid.group(1) if m_tid else m_id.group(1)).lower()).strip("-")
            res, url, token = self._run_harness(app_html, [{"action": "goto", "target": "ui"}, {"action": "click", "selector": sel}], 150, f"tab-{idx + 1:02d}")
            try:
                actual = str(res.get("actual") or res.get("message") or "")
                if res.get("status") == "FAIL" and res.get("failedStep") == 1:
                    role_gated = bool(re.search(r"not visible|zero bounding box|not found|hidden", actual, re.I)) and "panel" not in actual.lower()
                    if not role_gated:  # a tab hidden for the default persona is role-gated, not dead (the Playwright probe skips those too)
                        unwired_tabs.append({"selector": sel, "text": slug, "reason": actual[:200] or "tab click failed"})
                elif res.get("status") == "ERROR":
                    dlc.warn(f"tab probe {sel}: {res.get('message', '')}")
                tab_png = screenshot_dir / f"tab-{idx + 1:02d}-{slug}.png"
                if self._take_screenshot(url, tab_png):
                    shots.append({"label": f"Tab {idx + 1}: {sel}" + (f" -> #{m_ctrl.group(1)}" if m_ctrl else ""), "path": rel_of(tab_png), "kind": "tab"})
            finally:
                self.server.unregister(token)
        return shots, unwired_tabs


class PlaywrightAdapter:
    """Native Playwright browser adapter: executes real pointer/keyboard actions, hit-testing, bounding-box visibility checks,
    automatic [role='tab'] / [role='tabpanel'] mutual-exclusivity verification, and viewport PNG screenshots."""
    name = "playwright"

    def __init__(self, ui: UiEntry, tmp: Path):
        from playwright.sync_api import sync_playwright  # type: ignore
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=True)
        self.ui = ui
        self.tmp = tmp
        self.driver = dlc.read_text(DRIVER_JS)
        self.screenshot_dir: Path | None = None

    def close(self) -> None:
        try:
            self.browser.close()
            self._pw.stop()
        except Exception:
            pass

    def _entry_url(self) -> str:
        return self.ui.raw if self.ui.is_url else self.ui.path.resolve().as_uri()  # type: ignore[union-attr]

    @staticmethod
    def _resolve_locator(page: Any, selector: str, prefer_visible: bool = True) -> Any:
        selector = str(selector or "").strip()
        loc = page.locator(selector)
        cnt = loc.count()
        if cnt <= 1 or not prefer_visible:
            return loc.first
        for idx in range(cnt):
            cand = loc.nth(idx)
            try:
                if cand.is_visible():
                    box = cand.bounding_box()
                    if box and box.get("width", 0) > 0 and box.get("height", 0) > 0:
                        return cand
            except Exception:
                pass
        return loc.first

    @staticmethod
    def _has_nonzero_box(loc: Any) -> tuple[bool, dict[str, float] | None]:
        try:
            if not loc.is_visible():
                return False, None
            box = loc.bounding_box()
            if box is not None and box.get("width", 0) > 0 and box.get("height", 0) > 0:
                return True, box
        except Exception:
            pass
        return False, None

    @staticmethod
    def _match_text(actual: str, step: dict[str, Any]) -> bool:
        if step.get("equals") is not None:
            return actual == str(step["equals"])
        if step.get("contains") is not None:
            return str(step["contains"]).lower() in actual.lower()
        if step.get("matches") is not None:
            flags = re.I if "i" in str(step.get("flags", "i")).lower() else 0
            return bool(re.search(str(step["matches"]), actual, flags))
        return len(actual) > 0

    @staticmethod
    def _read_text(loc: Any) -> str:
        try:
            tag = (loc.evaluate("el => el.tagName") or "").upper()
            if tag in ("INPUT", "TEXTAREA"):
                return str(loc.input_value() or "").strip()
            if tag == "SELECT":
                return str(loc.evaluate("el => el.selectedIndex >= 0 ? (el.options[el.selectedIndex].text || el.value || '') : (el.value || '')") or "").strip()
            return re.sub(r"\s+", " ", str(loc.inner_text() or "")).strip()
        except Exception:
            return ""

    def _exec_step(self, page: Any, step: dict[str, Any]) -> tuple[bool, str]:
        a = step.get("action")
        sel = str(step.get("selector") or "").strip()
        if a == "goto":
            target = str(step.get("target") or "ui")
            url = self._entry_url() if target == "ui" else target
            page.goto(url, wait_until="load", timeout=10000)
            return True, f"loaded {page.url}"
        if a == "wait":
            page.wait_for_timeout(int(step.get("ms") or 100))
            return True, ""
        if a == "setRole":
            val = str(step.get("value") or step.get("role") or "").strip()
            sw = page.locator("select[data-testid=role-switcher], select#role-switcher, select[name=role]")
            if sw.count() > 0 and sw.first.is_visible():
                try:
                    sw.first.select_option(value=val, timeout=2000)
                except Exception:
                    sw.first.select_option(label=val, timeout=2000)
                page.wait_for_timeout(60)
                return True, f"role-switcher select -> {val}"
            slug = re.sub(r"[^a-z0-9]+", "-", val.lower()).strip("-")
            btn = page.locator(f'[data-testid="role-{slug}"]')
            if btn.count() == 0:
                btn = page.get_by_role("button", name=val)
            if btn.count() == 0:
                btn = page.get_by_role("tab", name=val)
            if btn.count() == 0:
                return False, f'No role switcher found for role "{val}"'
            btn.first.click(timeout=2500)
            page.wait_for_timeout(60)
            return True, f"clicked role {val}"
        if a == "fill":
            loc = self._resolve_locator(page, sel, True)
            if page.locator(sel).count() == 0:
                return False, f"Element not found: {sel}"
            tag = (loc.evaluate("el => el.tagName") or "").upper()
            val = "" if step.get("value") is None else str(step.get("value"))
            if tag == "SELECT":
                try:
                    loc.select_option(value=val, timeout=2500)
                except Exception:
                    loc.select_option(label=val, timeout=2500)
                return True, f"select={val}"
            inp_type = (loc.get_attribute("type") or "").lower()
            if inp_type in ("checkbox", "radio"):
                loc.set_checked(bool(val and val.lower() != "false"), timeout=2500)
                return True, f"checked={val}"
            loc.fill(val, timeout=2500)
            loc.dispatch_event("keyup", {"key": "Unidentified"})
            return True, f"value={val}"
        if a == "select":
            loc = self._resolve_locator(page, sel, True)
            if page.locator(sel).count() == 0:
                return False, f"Element not found: {sel}"
            val = str(step.get("value") or "")
            try:
                loc.select_option(value=val, timeout=2500)
            except Exception:
                loc.select_option(label=val, timeout=2500)
            return True, f"selected={val}"
        if a in ("check", "uncheck"):
            loc = self._resolve_locator(page, sel, True)
            if page.locator(sel).count() == 0:
                return False, f"Element not found: {sel}"
            if a == "check":
                loc.check(timeout=2500)
            else:
                loc.uncheck(timeout=2500)
            return True, a
        if a == "click":
            if page.locator(sel).count() == 0:
                return False, f"Element not found: {sel}"
            loc = self._resolve_locator(page, sel, True)
            vis, box = self._has_nonzero_box(loc)
            if not vis or not box:
                return False, f"Target element is hidden or has zero bounding box: {sel}"
            loc.click(timeout=2500)
            page.wait_for_timeout(60)
            role_attr = loc.get_attribute("role")
            panel_id = loc.get_attribute("aria-controls")
            if role_attr == "tab" and panel_id:
                panel_loc = page.locator(f"#{panel_id}").first
                p_vis, p_box = self._has_nonzero_box(panel_loc)
                if not p_vis or not p_box:
                    return False, f"Tab click on {sel} did not render controlled panel #{panel_id} with a non-zero bounding box"
                sib_ids = loc.evaluate("""el => {
                    const list = el.closest('[role="tablist"]') || document;
                    return Array.from(list.querySelectorAll('[role="tab"][aria-controls]'))
                      .map(t => t.getAttribute('aria-controls'))
                      .filter(id => id && id !== el.getAttribute('aria-controls'));
                }""") or []
                still_vis = []
                for sid in sib_ids:
                    s_vis, _ = self._has_nonzero_box(page.locator(f"#{sid}").first)
                    if s_vis:
                        still_vis.append(f"#{sid}")
                if still_vis:
                    return False, f"Tab mutual exclusivity failed after clicking {sel} — sibling panel(s) still visible: {', '.join(still_vis)}"
            return True, f"clicked bbox={int(box['width'])}x{int(box['height'])}"
        if a == "pressKey":
            key = str(step.get("key") or "Enter")
            if sel:
                loc = self._resolve_locator(page, sel, True)
                loc.press(key, timeout=2500)
            else:
                page.keyboard.press(key)
            page.wait_for_timeout(60)
            return True, f"pressed {key}"
        if a == "expectText":
            deadline = time.time() + 1.5
            last = ""
            while time.time() < deadline:
                if page.locator(sel).count() > 0:
                    loc = self._resolve_locator(page, sel, True)
                    last = self._read_text(loc)
                    if self._match_text(last, step):
                        return True, last
                else:
                    last = f"element not found: {sel}"
                page.wait_for_timeout(50)
            return False, last
        if a == "expectVisible":
            deadline = time.time() + 1.5
            while time.time() < deadline:
                all_loc = page.locator(sel)
                cnt = all_loc.count()
                for idx in range(cnt):
                    vis, box = self._has_nonzero_box(all_loc.nth(idx))
                    if vis and box:
                        return True, f"visible ({int(box['width'])}x{int(box['height'])})"
                page.wait_for_timeout(50)
            cnt = page.locator(sel).count()
            return False, f"present but hidden/zero-bbox ({cnt})" if cnt else "not in DOM"
        if a == "expectHidden":
            deadline = time.time() + 1.5
            last_vis = ""
            while time.time() < deadline:
                all_loc = page.locator(sel)
                cnt = all_loc.count()
                vis_boxes = []
                for idx in range(cnt):
                    vis, box = self._has_nonzero_box(all_loc.nth(idx))
                    if vis and box:
                        vis_boxes.append(f"{int(box['width'])}x{int(box['height'])}")
                if not vis_boxes:
                    return True, "hidden"
                last_vis = f"still visible with bbox {', '.join(vis_boxes)}"
                page.wait_for_timeout(50)
            return False, last_vis
        if a in ("expectDisabled", "expectEnabled"):
            want_disabled = (a == "expectDisabled")
            deadline = time.time() + 1.5
            last = ""
            while time.time() < deadline:
                if page.locator(sel).count() > 0:
                    loc = self._resolve_locator(page, sel, True)
                    dis = bool(loc.is_disabled() or loc.get_attribute("aria-disabled") == "true")
                    last = "disabled" if dis else "enabled"
                    if dis == want_disabled:
                        return True, last
                else:
                    last = f"element not found: {sel}"
                page.wait_for_timeout(50)
            return False, last
        if a == "expectCount":
            deadline = time.time() + 1.5
            last_n = 0
            while time.time() < deadline:
                all_loc = page.locator(sel)
                cnt = all_loc.count()
                if step.get("includeHidden"):
                    last_n = cnt
                else:
                    last_n = sum(1 for idx in range(cnt) if self._has_nonzero_box(all_loc.nth(idx))[0])
                ok = True
                if step.get("equals") is not None:
                    ok = ok and (last_n == int(step["equals"]))
                if step.get("min") is not None:
                    ok = ok and (last_n >= int(step["min"]))
                if step.get("max") is not None:
                    ok = ok and (last_n <= int(step["max"]))
                if ok:
                    return True, f"count={last_n}"
                page.wait_for_timeout(50)
            return False, f"count={last_n}"
        if a == "expectAttribute":
            attr_name = str(step.get("attribute") or step.get("name") or "")
            deadline = time.time() + 1.5
            last = ""
            while time.time() < deadline:
                if page.locator(sel).count() > 0:
                    loc = page.locator(sel).first
                    v = loc.get_attribute(attr_name)
                    last = f"{attr_name}={json.dumps(v)}"
                    ok = (v == str(step["equals"])) if step.get("equals") is not None else (str(step["contains"]) in (v or "") if step.get("contains") is not None else v is not None)
                    if ok:
                        return True, last
                else:
                    last = f"element not found: {sel}"
                page.wait_for_timeout(50)
            return False, last
        if a == "expectNoVisibleTextMatching":
            txt = str(page.evaluate("() => window.__dlcVisibleText ? window.__dlcVisibleText() : document.body.innerText") or "")
            flags = re.I if "i" in str(step.get("flags", "")).lower() else 0
            m = re.search(str(step.get("pattern") or ""), txt, flags)
            if m:
                return False, f'matched "{m.group(0)}"'
            return True, "no match"
        return False, f"Unknown step action: {a}"

    def run(self, tc: dict[str, Any], app_html: str) -> dict[str, Any]:
        t0 = now_ms()
        page = self.browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            page.add_init_script(self.driver + "\nwindow.__dlcInstallPrelude();")
            page.goto(self._entry_url(), wait_until="load", timeout=10000)
            page.wait_for_timeout(int(tc.get("settleMs", 150)))

            text_lines: dict[str, int] = {}
            controls_acc: dict[str, dict[str, Any]] = {}
            a11y_acc: dict[str, dict[str, str]] = {}
            ux_best: dict[str, Any] = {}

            def snapshot_state() -> None:
                snap = page.evaluate("""() => ({
                    visibleText: window.__dlcVisibleText ? window.__dlcVisibleText() : '',
                    controls: window.__dlcControlAudit ? window.__dlcControlAudit() : [],
                    ux: window.__dlcUx ? window.__dlcUx() : null,
                    a11y: window.__dlcA11y ? window.__dlcA11y() : []
                })""")
                for ln in (snap.get("visibleText") or "").splitlines():
                    if ln:
                        text_lines[ln] = 1
                for c in snap.get("controls") or []:
                    k = f"{c['selector']}|{c.get('text', '')}"
                    if k not in controls_acc or not c.get("hasHandler"):
                        controls_acc[k] = c
                for f in snap.get("a11y") or []:
                    a11y_acc[f"{f['rule']}|{f['message']}"] = f
                m = snap.get("ux")
                if m:
                    for k in ("primaryVisible", "tabsVisible", "inputsVisibleMaxPerContainer"):
                        if m.get(k, 0) > ux_best.get(k, -1):
                            ux_best[k] = m.get(k, 0)
                            if k == "primaryVisible":
                                ux_best["primarySelectors"] = m.get("primarySelectors", [])
                            if k == "inputsVisibleMaxPerContainer":
                                ux_best["inputsWorstContainer"] = m.get("inputsWorstContainer", "")
                    ux_best.setdefault("mainMaxWidth", m.get("mainMaxWidth", ""))

            snapshot_state()
            step_logs: list[dict[str, Any]] = []
            status = "PASS"
            failed_step: int | None = None
            message = ""
            actual = ""
            steps = tc.get("steps") or []
            for idx, step in enumerate(steps):
                st0 = now_ms()
                try:
                    ok, act = self._exec_step(page, step)
                except Exception as e:
                    ok, act = False, str(e)
                step_logs.append({
                    "index": idx,
                    "action": step.get("action"),
                    "selector": step.get("selector") or step.get("value") or step.get("pattern") or "",
                    "ok": bool(ok),
                    "actual": act,
                    "ms": now_ms() - st0,
                })
                if step.get("action") in ("setRole", "click", "fill", "select", "check", "uncheck", "pressKey"):
                    page.wait_for_timeout(40)
                    snapshot_state()
                if not ok:
                    status = "FAIL"
                    failed_step = idx
                    sel_note = f" {step.get('selector')}" if step.get("selector") else ""
                    message = f"Step {idx} ({step.get('action')}{sel_note}) failed"
                    actual = act
                    break

            snapshot_state()
            shot_str: str | None = None
            if status in ("FAIL", "ERROR") and self.screenshot_dir is not None:
                self.screenshot_dir.mkdir(parents=True, exist_ok=True)
                sp = self.screenshot_dir / f"fail-{re.sub(r'[^A-Za-z0-9_-]', '_', tc.get('id', 'tc'))}.png"
                try:
                    page.screenshot(path=str(sp), full_page=True)
                    shot_str = str(sp)
                except Exception:
                    pass
            errs = page.evaluate("() => (window.__dlcErrors || []).slice(0, 10)") or []
            return {
                "status": status,
                "failedStep": failed_step,
                "message": message,
                "actual": actual,
                "steps": step_logs,
                "visibleText": page.evaluate("() => window.__dlcVisibleText ? window.__dlcVisibleText() : ''") or "",
                "visibleTextAllStates": "\n".join(text_lines.keys()),
                "controls": list(controls_acc.values()),
                "ux": ux_best,
                "a11y": list(a11y_acc.values()),
                "scriptErrors": errs,
                "screenshot": shot_str,
                "durationMs": now_ms() - t0,
            }
        except Exception as e:
            return {"status": "ERROR", "message": f"playwright: {e}", "actual": "", "durationMs": now_ms() - t0}
        finally:
            page.close()

    def capture_visual_evidence(self, app_html: str, screenshot_dir: Path, root: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        """Capture initial landing screenshot + click each [role='tab'] via Playwright to verify bounding-box layout shifts & capture tab PNGs."""
        self.screenshot_dir = screenshot_dir
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        shots: list[dict[str, str]] = []
        unwired_tabs: list[dict[str, str]] = []
        page = self.browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            page.goto(self._entry_url(), wait_until="load", timeout=10000)
            page.wait_for_timeout(150)
            init_png = screenshot_dir / "landing-initial.png"
            page.screenshot(path=str(init_png), full_page=True)
            rel_init = str(init_png.relative_to(root)) if init_png.is_relative_to(root) else str(init_png)
            shots.append({"label": "Initial landing view (1440x900)", "path": rel_init, "kind": "landing"})

            tabs = page.locator('[role="tab"]')
            cnt = tabs.count()
            for idx in range(min(cnt, 8)):
                t_loc = tabs.nth(idx)
                vis, _ = self._has_nonzero_box(t_loc)
                if not vis:
                    continue
                tid = t_loc.get_attribute("data-testid") or t_loc.get_attribute("id") or f"tab-{idx + 1}"
                ctrl = t_loc.get_attribute("aria-controls")
                label_txt = self._read_text(t_loc) or tid
                try:
                    t_loc.click(timeout=2000)
                    page.wait_for_timeout(100)
                    if ctrl:
                        p_vis, _ = self._has_nonzero_box(page.locator(f"#{ctrl}").first)
                        if not p_vis:
                            unwired_tabs.append({"selector": f"[data-testid={tid}]" if t_loc.get_attribute("data-testid") else f"#{tid}",
                                                 "text": label_txt, "reason": f"clicking tab did not give controlled panel #{ctrl} a non-zero bounding box"})
                    slug = re.sub(r"[^a-z0-9]+", "-", tid.lower()).strip("-")
                    tab_png = screenshot_dir / f"tab-{idx + 1:02d}-{slug}.png"
                    page.screenshot(path=str(tab_png), full_page=True)
                    rel_tab = str(tab_png.relative_to(root)) if tab_png.is_relative_to(root) else str(tab_png)
                    shots.append({"label": f"Tab {idx + 1}: {label_txt}" + (f" (#{ctrl})" if ctrl else ""), "path": rel_tab, "kind": "tab"})
                except Exception as e:
                    unwired_tabs.append({"selector": tid, "text": label_txt, "reason": f"playwright tab click failed: {e}"})
        except Exception:
            pass
        finally:
            page.close()
        return shots, unwired_tabs


def pick_browser(choice: str, chrome_binary: str | None, ui: UiEntry, tmp: Path) -> tuple[Any, str]:
    if choice in ("auto", "playwright"):
        try:
            import playwright  # type: ignore  # noqa: F401
            return PlaywrightAdapter(ui, tmp), "playwright"
        except Exception as e:
            if choice == "playwright":
                dlc.warn(f"playwright requested but unavailable ({e}); falling back")
    if choice in ("auto", "chrome", "playwright"):
        binary = which_browser(chrome_binary)
        if binary:
            return ChromeAdapter(binary, ui, tmp), "chrome-headless"
        if choice == "chrome":
            dlc.warn("chrome requested but no binary found")
    return None, "none"


# ======================================================================================
# HTTP runtime
# ======================================================================================
def run_http_steps(tc: dict[str, Any], base_url: str) -> dict[str, Any]:
    t0 = now_ms()
    steps = tc.get("steps") or []
    last_json: Any = None
    for i, step in enumerate(steps):
        action = step.get("action")
        if action == "wait":
            time.sleep(int(step.get("ms", 100)) / 1000)
            continue
        if action != "httpRequest":
            return {"status": "ERROR", "failedStep": i, "message": f"Step {i}: action '{action}' is not valid for runtime=http (use httpRequest/wait)", "actual": "", "durationMs": now_ms() - t0}
        if not base_url:
            return {"status": "NOT_RUN", "failedStep": i, "message": "no backend base URL (target_stack.commands.healthcheck missing or backend not started)", "actual": "", "durationMs": now_ms() - t0}
        path = step.get("path") or step.get("url") or "/"
        url = path if re.match(r"^https?://", path) else urllib.parse.urljoin(base_url + "/", path.lstrip("/"))
        method = (step.get("method") or "GET").upper()
        headers = {"Accept": "application/json", **(step.get("headers") or {})}
        body = None
        if step.get("json") is not None:
            body = json.dumps(step["json"]).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        elif step.get("body") is not None:
            body = str(step["body"]).encode("utf-8")
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        except Exception as e:
            return {"status": "FAIL", "failedStep": i, "message": f"Step {i}: {method} {url} failed", "actual": str(e), "durationMs": now_ms() - t0}
        text = raw.decode("utf-8", errors="replace")
        exp = step.get("expectStatus")
        if exp is not None:
            allowed = exp if isinstance(exp, list) else [exp]
            if status not in [int(x) for x in allowed]:
                return {"status": "FAIL", "failedStep": i, "message": f"Step {i}: {method} {path} expected status {exp}", "actual": f"status={status} body={text[:300]}", "durationMs": now_ms() - t0}
        elif not (200 <= status < 300):
            # No explicit expectation → a request that does not succeed (2xx) is a failure, never a silent pass.
            return {"status": "FAIL", "failedStep": i, "message": f"Step {i}: {method} {path} returned {status} (no expectStatus given, 2xx expected by default)", "actual": f"status={status} body={text[:300]}", "durationMs": now_ms() - t0}
        try:
            last_json = json.loads(text) if text.strip() else None
        except json.JSONDecodeError:
            last_json = None
        jp = step.get("expectJsonPath")
        if jp:
            if last_json is None:
                return {"status": "FAIL", "failedStep": i, "message": f"Step {i}: response is not JSON but expectJsonPath={jp}", "actual": text[:300], "durationMs": now_ms() - t0}
            try:
                val = json_path(last_json, jp)
            except KeyError as e:
                return {"status": "FAIL", "failedStep": i, "message": f"Step {i}: JSON path {jp} not found ({e})", "actual": text[:300], "durationMs": now_ms() - t0}
            if "equals" in step and val != step["equals"] and str(val) != str(step["equals"]):
                return {"status": "FAIL", "failedStep": i, "message": f"Step {i}: {jp} expected == {step['equals']!r}", "actual": repr(val), "durationMs": now_ms() - t0}
            if "contains" in step and str(step["contains"]).lower() not in str(val).lower():
                return {"status": "FAIL", "failedStep": i, "message": f"Step {i}: {jp} expected to contain {step['contains']!r}", "actual": repr(val), "durationMs": now_ms() - t0}
            if "matches" in step and not re.search(str(step["matches"]), str(val)):
                return {"status": "FAIL", "failedStep": i, "message": f"Step {i}: {jp} expected to match /{step['matches']}/", "actual": repr(val), "durationMs": now_ms() - t0}
        if "expectBodyContains" in step and str(step["expectBodyContains"]) not in text:
            return {"status": "FAIL", "failedStep": i, "message": f"Step {i}: body expected to contain {step['expectBodyContains']!r}", "actual": text[:300], "durationMs": now_ms() - t0}
    return {"status": "PASS", "failedStep": None, "message": f"{len(steps)} http step(s) passed", "actual": "", "durationMs": now_ms() - t0}


# ======================================================================================
# Static runtime (html.parser)
# ======================================================================================
class A11yParser(HTMLParser):
    VOID = {"input", "img", "br", "hr", "meta", "link"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.findings: list[dict[str, str]] = []
        self.lang = None
        self.h1 = 0
        self.label_for: set[str] = set()
        self.inputs: list[dict[str, str]] = []
        self.stack: list[tuple[str, dict[str, str]]] = []
        self.in_label = 0
        self.button_stack: list[tuple[dict[str, str], list[str]]] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "html":
            self.lang = a.get("lang", "")
        elif tag == "h1":
            self.h1 += 1
        elif tag == "label":
            self.in_label += 1
            if a.get("for"):
                self.label_for.add(a["for"])
        elif tag == "img" and "alt" not in a:
            self.findings.append({"rule": "img-alt", "message": f"<img src={a.get('src', '')!r}> missing alt"})
        elif tag in ("input", "select", "textarea"):
            if a.get("type", "").lower() not in ("hidden", "submit", "button", "reset", "image"):
                self.inputs.append({**a, "_tag": tag, "_wrapped": "1" if self.in_label else ""})
        if tag == "button" or a.get("role") == "button":
            self.button_stack.append((a, []))
        if a.get("tabindex", "").lstrip("-").isdigit() and int(a["tabindex"]) > 0:
            self.findings.append({"rule": "positive-tabindex", "message": f"<{tag} id={a.get('id', '')!r}> tabindex={a['tabindex']}"})
        if tag not in self.VOID:
            self.stack.append((tag, a))

    def handle_data(self, data):
        if self.button_stack and data.strip():
            self.button_stack[-1][1].append(data.strip())

    def handle_endtag(self, tag):
        if tag == "label" and self.in_label:
            self.in_label -= 1
        if tag == "button" and self.button_stack:
            a, texts = self.button_stack.pop()
            if not (texts or a.get("aria-label") or a.get("title") or a.get("aria-labelledby")):
                self.findings.append({"rule": "accessible-name", "message": f"<button id={a.get('id', '')!r} data-testid={a.get('data-testid', '')!r}> has no accessible name"})
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def finish(self) -> list[dict[str, str]]:
        if not self.lang:
            self.findings.append({"rule": "html-lang", "message": "<html> has no lang attribute"})
        if self.h1 != 1:
            self.findings.append({"rule": "single-h1", "message": f"expected exactly one <h1>, found {self.h1}"})
        for inp in self.inputs:
            labelled = inp.get("aria-label") or inp.get("aria-labelledby") or inp.get("title") or inp.get("_wrapped") or (inp.get("id") and inp["id"] in self.label_for)
            if not labelled:
                self.findings.append({"rule": "form-label", "message": f"<{inp['_tag']} id={inp.get('id', '')!r} data-testid={inp.get('data-testid', '')!r}> has no label"})
        return self.findings


def a11y_lint(html_text: str) -> list[dict[str, str]]:
    p = A11yParser()
    try:
        p.feed(html_text)
    except Exception as e:  # pragma: no cover
        return [{"rule": "parse-error", "message": str(e)}]
    return p.finish()


def run_static_steps(tc: dict[str, Any], ui_source: str, texts: dict[str, str] | None = None,
                     ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Static / cross-cutting steps. `texts` = every visible-text corpus reached (static source + each browser TC's
    union of rendered states); `ctx` carries the aggregated interactivity / a11y results for the deferred actions."""
    t0 = now_ms()
    texts = texts or {"static:uiEntry source": dlc.html_visible_text(ui_source)}
    ctx = ctx or {}
    static_corpus_len = len((texts.get("static:uiEntry source") or "").strip())
    for i, step in enumerate(tc.get("steps") or []):
        action = step.get("action")
        if action == "expectNoVisibleTextMatching":
            try:
                rx = re.compile(step.get("pattern", ""), re.M)
            except re.error as e:
                return {"status": "ERROR", "failedStep": i, "message": f"Step {i}: invalid regex /{step.get('pattern')}/: {e}", "actual": "", "durationMs": now_ms() - t0}
            if not ctx.get("browserStatesReached") and static_corpus_len < MIN_STATIC_CORPUS_CHARS:
                # An SPA shell with (almost) no static text proves nothing about what the rendered UI shows.
                return {"status": "NOT_RUN", "failedStep": i, "message": f"Step {i}: no browser state reached and the static visible text is only {static_corpus_len} chars — "
                        "a negative text match over an empty corpus is not evidence; " + BROWSER_INSTALL_HINT, "actual": "", "durationMs": now_ms() - t0}
            for label, text in texts.items():
                m = rx.search(text)
                if m:
                    return {"status": "FAIL", "failedStep": i, "message": f"Step {i}: visible text matches /{step['pattern'][:80]}/ in {label}",
                            "actual": f"'{m.group(0)}' near: " + _context(text, m.start(), m.end()), "durationMs": now_ms() - t0}
        elif action == "expectAllControlsWired":
            if not ctx.get("browserStatesReached"):
                return {"status": "NOT_RUN", "failedStep": i, "message": "requires a browser runtime to observe listeners; " + BROWSER_INSTALL_HINT, "actual": "", "durationMs": now_ms() - t0}
            unwired = ctx.get("unwired") or []
            if unwired:
                return {"status": "FAIL", "failedStep": i, "message": f"Step {i}: {len(unwired)} control(s) without any handler: " + ", ".join(u["selector"] for u in unwired[:6]),
                        "actual": "; ".join(f"{u['selector']} ({u.get('text', '')}): {u['reason']}" for u in unwired[:4]), "durationMs": now_ms() - t0}
        elif action == "expectA11yBaseline":
            findings = ctx.get("a11yFindings") or []
            if findings:
                return {"status": "FAIL", "failedStep": i, "message": f"Step {i}: {len(findings)} accessibility finding(s): " + "; ".join(sorted({f['rule'] for f in findings})),
                        "actual": "; ".join(f["message"] for f in findings[:5]), "durationMs": now_ms() - t0}
        elif action == "expectSourceContains":
            if str(step.get("value", "")) not in ui_source:
                return {"status": "FAIL", "failedStep": i, "message": f"Step {i}: UI source lacks {step.get('value')!r}", "actual": "", "durationMs": now_ms() - t0}
        elif action == "expectSourceMatches":
            if not re.search(step.get("pattern", ""), ui_source):
                return {"status": "FAIL", "failedStep": i, "message": f"Step {i}: UI source does not match /{step.get('pattern')}/", "actual": "", "durationMs": now_ms() - t0}
        elif action in ("goto", "wait"):
            continue
        else:
            return {"status": "ERROR", "failedStep": i, "message": f"Step {i}: action '{action}' is not valid for runtime=static", "actual": "", "durationMs": now_ms() - t0}
    n = len(tc.get("steps") or [])
    return {"status": "PASS", "failedStep": None, "message": f"{n} static step(s) passed over {len(texts)} rendered/static text corpus(es)", "actual": "", "durationMs": now_ms() - t0}


# ======================================================================================
# Leakage scan
# ======================================================================================
def _context(text: str, start: int, end: int) -> str:
    return text[max(0, start - 50): end + 50].replace("\n", " | ")


def leakage_scan(forbidden: dict[str, Any], texts: dict[str, str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Return (hits, warnings, tokens_scanned). texts = {source_label: visible_text}."""
    hits: list[dict[str, Any]] = []
    warns: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    scanned = 0
    for cls, tokens in (forbidden or {}).items():
        if not isinstance(tokens, list) or cls in LEAK_SKIP_CLASSES:
            continue
        for tok in tokens:
            tok = str(tok).strip()
            if not tok:
                continue
            scanned += 1
            if cls in LEAK_REGEX_CLASSES:
                try:
                    rx = re.compile(tok)
                except re.error:
                    continue
            else:
                # identifiers: word boundary, case-sensitive; a token that is a plain English-looking word
                # is still a hit because the list is derived from DDL/enums/legacy stems, not prose.
                rx = re.compile(r"(?<![\w-])" + re.escape(tok) + r"(?![\w-])")
            for label, text in texts.items():
                for m in rx.finditer(text):
                    key = (tok, label)
                    if key in seen:
                        break
                    seen.add(key)
                    hits.append({"token": tok, "tokenClass": cls, "source": label, "severity": "fail", "context": _context(text, m.start(), m.end())})
                    break
    warn_seen: set[tuple[str, str]] = set()
    # Warn-only token classes (e.g. short all-caps OpenAPI enum members that are also legitimate words).
    for cls in LEAK_WARN_CLASSES:
        for tok in (forbidden or {}).get(cls, []) or []:
            tok = str(tok).strip()
            if not tok:
                continue
            rx = re.compile(r"(?<![\w-])" + re.escape(tok) + r"(?![\w-])")
            for label, text in texts.items():
                m = rx.search(text)
                if m and (cls, tok) not in warn_seen:
                    warn_seen.add((cls, tok))
                    warns.append({"heuristic": cls, "match": tok, "source": label, "context": _context(text, m.start(), m.end())})
    for name, rx in HEURISTIC_PATTERNS.items():
        for label, text in texts.items():
            for m in rx.finditer(text):
                key = (name, m.group(0))
                if key in warn_seen:
                    continue
                warn_seen.add(key)
                warns.append({"heuristic": name, "match": m.group(0), "source": label, "context": _context(text, m.start(), m.end())})
    return hits, warns, scanned


# ======================================================================================
# Audit report (Gate 4) & Non-Overwriting Run History Archival
# ======================================================================================
SNAPSHOT_META_FILES = {
    "eval_results.json",
    "eval_report.md",
    "remediation_and_guardrail_audit_report.md",
    "defects.json",
    "defects.md",
}


def list_files(d: Path) -> dict[str, Path]:
    out = {}
    if not d.exists():
        return out
    for p in d.rglob("*"):
        # evaluator outputs (results/reports) and screenshots/ are copied next to the snapshot — they are not application source
        if (
            p.is_file()
            and p.name not in SNAPSHOT_META_FILES
            and not any(part in ("node_modules", "__pycache__", ".venv", ".git", "screenshots") for part in p.parts)
        ):
            out[str(p.relative_to(d)).replace(os.sep, "/")] = p
    return out


def _is_binary(p: Path) -> bool:
    try:
        chunk = p.read_bytes()[:4096]
    except OSError:
        return False
    return b"\x00" in chunk


def split_hunks(diff_lines: list[str]) -> list[list[str]]:
    hunks: list[list[str]] = []
    cur: list[str] = []
    for ln in diff_lines:
        if ln.startswith("@@"):
            if cur:
                hunks.append(cur)
            cur = [ln]
        elif ln.startswith(("---", "+++")):
            continue
        else:
            cur.append(ln)
    if cur:
        hunks.append(cur)
    return hunks


def build_guardrail_patterns(spec_md: str) -> dict[str, re.Pattern[str]]:
    pats = dict(GUARDRAIL_PATTERNS)
    if spec_md:
        sm = dlc.parse_state_machine(spec_md)
        words = [re.escape(s) for s in sm.states if len(s) >= 3] + [re.escape(t) for t in sm.triggers() if len(t) >= 3]
        if words:
            pats["state name / trigger from spec §3.3"] = re.compile(r"(?<![\w])(" + "|".join(words) + r")(?![\w])", re.I)
        rules = dlc.parse_business_rules(spec_md)
        idents: set[str] = set()
        for r in rules:
            for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", f"{r.get('inputs', '')} {r.get('rule', '')}"):
                if w.lower() not in {"with", "from", "that", "this", "when", "then", "each", "must", "shall", "where", "than", "into", "only", "rule", "formula", "value", "values"}:
                    idents.add(w)
        if idents:
            alt = "|".join(sorted(map(re.escape, idents), key=len, reverse=True)[:200])
            pats["business rule (spec §3.4) formula"] = re.compile(r"(?i)(?<![\w])(" + alt + r")(?![\w]).*([-+*/<>=]|\d)|([-+*/<>=]|\d).*(?<![\w])(" + alt + r")(?![\w])")
        if rules:
            pats["business rule id"] = re.compile(r"\bBR-\d+\b")
    return pats


DOC_SUFFIXES = {".md", ".txt", ".rst"}  # documentation under src/ is never a guardrail (no behaviour)


def classify_hunk(hunk: list[str], pats: dict[str, re.Pattern[str]]) -> list[str]:
    """Classify a unified-diff hunk. The WHOLE hunk (changed + context lines) is inspected: a one-line change
    inside `if (!allowedRoles.includes(role))` is guardrail-sensitive even when the changed line itself is bland."""
    cats: list[str] = []
    body = [ln[1:] if ln[:1] in "+- " else ln for ln in hunk if not ln.startswith(("@@", "+++", "---"))]
    for name, rx in pats.items():
        if any(rx.search(ln) for ln in body):
            cats.append(name)
    return cats


def hunk_hash(rel: str, hunk: list[str]) -> str:
    """Stable identity of a flagged hunk: file + changed lines (header line numbers excluded so unrelated edits above
    the hunk do not change its identity)."""
    changed = [ln for ln in hunk if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))]
    return hashlib.sha256((rel + "\n" + "\n".join(changed)).encode("utf-8")).hexdigest()


def load_guardrail_state(root: Path) -> dict[str, Any]:
    p = root / GUARDRAIL_STATE_FILE
    state: dict[str, Any] = {"schemaVersion": dlc.SCHEMA_VERSION, "pendingHunks": [], "approvedHunks": [], "flaggedAtIteration": None, "baselineIteration": None, "baselineSnapshot": None}
    if p.exists():
        try:
            data = dlc.read_json(p)
            if isinstance(data, dict):
                state.update({k: data.get(k, state[k]) for k in state})
        except Exception as e:
            dlc.warn(f"{GUARDRAIL_STATE_FILE} is unreadable ({e}) — treating as no recorded state")
    state["pendingHunks"] = [str(h) for h in (state.get("pendingHunks") or [])]
    state["approvedHunks"] = [str(h) for h in (state.get("approvedHunks") or [])]
    return state


def compute_snapshot_file_changes(prev_d: Path, cur_d: Path, from_label: str, to_label: str) -> tuple[list[str], list[tuple[str, str, list[list[str]]]]]:
    """Return (changed_rel_paths, [(rel, tag, hunks)]) between two snapshot directories (context DIFF_CONTEXT_LINES)."""
    if not prev_d.exists() or not cur_d.exists():
        return [], []
    prev_files, cur_files = list_files(prev_d), list_files(cur_d)
    changed_paths: list[str] = []
    detailed: list[tuple[str, str, list[list[str]]]] = []
    for rel in sorted(set(prev_files) | set(cur_files)):
        if any(_is_binary(f[rel]) for f in (prev_files, cur_files) if rel in f):
            if (rel in prev_files) != (rel in cur_files) or prev_files[rel].read_bytes() != cur_files[rel].read_bytes():
                changed_paths.append(rel)
                detailed.append((rel, "binary-modified", []))
            continue
        a = dlc.read_text(prev_files[rel]).splitlines() if rel in prev_files else []
        b = dlc.read_text(cur_files[rel]).splitlines() if rel in cur_files else []
        if a == b:
            continue
        tag = "modified" if rel in prev_files and rel in cur_files else ("new" if rel in cur_files else "deleted")
        diff = list(difflib.unified_diff(a, b, fromfile=f"{from_label}/{rel}", tofile=f"{to_label}/{rel}", lineterm="", n=DIFF_CONTEXT_LINES))
        hunks = split_hunks(diff)
        changed_paths.append(rel)
        detailed.append((rel, tag, hunks))
    return changed_paths, detailed


def compute_iteration_changes(snaps_dir: Path, from_it: int, to_it: int) -> tuple[list[str], list[tuple[str, str, list[list[str]]]]]:
    if from_it < 1:
        return [], []
    return compute_snapshot_file_changes(snaps_dir / f"iter-{from_it}", snaps_dir / f"iter-{to_it}", f"iter-{from_it}", f"iter-{to_it}")


def build_cumulative_history_rows(root: Path, current_it: int, current_results: list[dict[str, Any]], current_ts: str) -> list[dict[str, Any]]:
    """Collect a chronological record of every evaluation iteration 1..current_it."""
    snaps = root / "test" / ".snapshots"
    all_its = sorted(set(existing_iterations(root)) | {current_it})
    rows: list[dict[str, Any]] = []
    prev_failed_ids: set[str] = set()
    for it in all_its:
        if it > current_it:
            continue
        if it == current_it:
            res_list = current_results
            cnt = status_counts(res_list)
            non_opt_bad = [r for r in res_list if r.get("status") in ("FAIL", "ERROR", "NOT_RUN") and not r.get("optional")]
            active_tot = sum(1 for r in res_list if not r.get("deferredByGroupSelection"))
            verdict = "PASS" if active_tot and not non_opt_bad else "FAIL"
            ts = current_ts
        else:
            doc = load_iteration_eval(root, it) or {}
            res_list = doc.get("results") or []
            s = doc.get("summary") or {}
            cnt = {
                "PASS": s.get("pass", sum(1 for r in res_list if r.get("status") == "PASS")),
                "FAIL": s.get("fail", sum(1 for r in res_list if r.get("status") == "FAIL")),
                "NOT_RUN": s.get("notRun", sum(1 for r in res_list if r.get("status") == "NOT_RUN")),
                "ERROR": s.get("error", sum(1 for r in res_list if r.get("status") == "ERROR")),
            }
            verdict = s.get("verdict") or ("PASS" if res_list and cnt["FAIL"] == 0 and cnt["ERROR"] == 0 and cnt["NOT_RUN"] == 0 else "FAIL")
            ts = str(doc.get("evaluatedAtUtc") or "—")
        failed_entries = [r for r in res_list if isinstance(r, dict) and r.get("status") in ("FAIL", "ERROR", "NOT_RUN") and not r.get("optional")]
        failed_ids = sorted(str(r.get("id")) for r in failed_entries if r.get("id"))
        passed_ids = {str(r.get("id")) for r in res_list if isinstance(r, dict) and r.get("status") == "PASS" and r.get("id")}
        remediated_ids = sorted(prev_failed_ids & passed_ids)
        changed_files, detailed_diffs = compute_iteration_changes(snaps, it - 1, it) if it > 1 else ([], [])
        rows.append({
            "iteration": it,
            "evaluatedAtUtc": ts,
            "verdict": verdict,
            "total": len(res_list),
            "pass": cnt["PASS"],
            "fail": cnt["FAIL"],
            "notRun": cnt["NOT_RUN"],
            "error": cnt["ERROR"],
            "failedIds": failed_ids,
            "failedEntries": failed_entries,
            "remediatedIds": remediated_ids,
            "changedFiles": changed_files,
            "detailedDiffs": detailed_diffs,
            "historyDir": f"test/history/iter-{it}",
            "snapshotDir": f"test/.snapshots/iter-{it}",
            "evalResultsFile": f"test/eval_results.iter-{it:02d}.json",
            "evalReportFile": f"test/eval_report.iter-{it:02d}.md",
            "auditReportFile": f"test/remediation_and_guardrail_audit_report.iter-{it:02d}.md",
        })
        prev_failed_ids = set(failed_ids)
    return rows


def history_table_lines(history_rows: list[dict[str, Any]], max_ids: int = 8, with_files: bool = True) -> list[str]:
    hdr = "| Iter | Timestamp (UTC) | Verdict | PASS / Total | FAIL | NOT_RUN | ERROR | Failed Test IDs | Remediated Test IDs |" + (" Modified Files (`src/`) |" if with_files else "") + " Preserved Run Artifacts |"
    sep = "| --: | :-- | :-- | --: | --: | --: | --: | :-- | :-- |" + (" :-- |" if with_files else "") + " :-- |"
    out = [hdr, sep]

    def trunc(items: list[str], n: int, empty: str = "—") -> str:
        if not items:
            return empty
        return ", ".join(f"`{t}`" for t in items[:n]) + (f" (+{len(items) - n} more)" if len(items) > n else "")

    for hr in history_rows:
        it_num = hr["iteration"]
        cells = [f"**{it_num}**", f"`{hr['evaluatedAtUtc']}`", f"**{hr['verdict']}**", f"{hr['pass']}/{hr['total']}", str(hr["fail"]), str(hr["notRun"]), str(hr["error"]),
                 trunc(hr["failedIds"], max_ids), trunc(hr["remediatedIds"], max_ids)]
        if with_files:
            cells.append(trunc(hr["changedFiles"], 5, "initial snapshot" if it_num == 1 else "—"))
        cells.append(f"`{hr['historyDir']}/` · `{hr['evalReportFile']}` · `{hr['auditReportFile']}`")
        out.append("| " + " | ".join(cells) + " |")
    return out


def write_audit_report(root: Path, iteration: int, results: list[dict[str, Any]], out_path: Path, spec_md: str, deterministic: bool,
                       displaced: Path | None = None, approve: bool = False, had_prior_results: bool = False) -> dict[str, Any]:
    """Write test/remediation_and_guardrail_audit_report.md and update test/.guardrail_state.json.

    Returns {"status": CLEAR | FLAGGED_REQUIRES_HUMAN_APPROVAL | UNKNOWN_BASELINE, "pending": [...], "approvedNow": [...], "baseline": "iter-N"}.
    The diff baseline is the last APPROVED iteration recorded in the state file while a flag is pending (so an
    unchanged re-run cannot clear it), the displaced `iter-N.prev` when --iteration N re-used an existing number,
    otherwise iter-(N-1)."""
    snaps = root / "test" / ".snapshots"
    cur_dir = snaps / f"iter-{iteration}"
    state = load_guardrail_state(root)
    prev_pending = list(state["pendingHunks"])
    approved: set[str] = set(state["approvedHunks"])
    baseline_label = f"iter-{iteration - 1}"
    prev_dir = snaps / baseline_label
    recorded = str(state.get("baselineSnapshot") or (f"iter-{state['baselineIteration']}" if state.get("baselineIteration") else ""))
    if prev_pending and recorded and (snaps / recorded).exists() and recorded != f"iter-{iteration}":
        baseline_label = recorded
        prev_dir = snaps / baseline_label
    elif displaced is not None and displaced.exists():
        baseline_label = displaced.name
        prev_dir = displaced
    elif prev_pending and recorded:
        dlc.warn(f"guardrail state refers to baseline {recorded} which no longer exists — diffing against {baseline_label}")
    has_baseline = prev_dir.exists()
    now_ts = dlc.utc_now_iso(deterministic)
    history_rows = build_cumulative_history_rows(root, iteration, results, now_ts)
    lines = [f"# Remediation & Guardrail Audit Report — Iteration {iteration}", "",
             f"Generated: {now_ts}  ", f"Project: `{root.name}`  ",
             f"Compared: `{baseline_label}` → `iter-{iteration}`" + ("" if has_baseline else " (baseline missing)") + "  ",
             f"Preserved Per-Run Archive: `test/history/iter-{iteration}/` · `test/*.iter-{iteration:02d}.*`", "",
             "## 0. Cumulative Run & Remediation History (All Iterations)", "",
             "> Every evaluation run and remediation iteration is permanently archived under `test/history/iter-<N>/` and `test/*.iter-<NN>.*` so earlier failure runs and remediation diffs are never overwritten.", ""]
    lines += history_table_lines(history_rows) + [""]
    # §1 what failed
    lines += ["## 1. What failed", ""]
    prev_results_p = prev_dir / "eval_results.json"
    prev_fail: dict[str, dict[str, Any]] = {}
    prev_results_note = ""
    prev_doc: dict[str, Any] | None = None
    if prev_results_p.exists():
        try:
            prev_doc = dlc.read_json(prev_results_p)
        except Exception as e:
            prev_results_note = f"> ⚠ `{baseline_label}/eval_results.json` could not be read ({e}) — the previous failure set is unknown, not zero."
            dlc.warn(prev_results_note.lstrip("> ⚠ "))
    elif has_baseline:
        m_base = re.match(r"iter-(\d+)$", baseline_label)
        prev_doc = load_iteration_eval(root, int(m_base.group(1))) if m_base else None  # archived copy under test/history or test/*.iter-NN.json
        if prev_doc is None:
            prev_results_note = f"> ⚠ `{baseline_label}/eval_results.json` is missing — the previous failure set is unknown, not zero."
    if isinstance(prev_doc, dict):
        prev_fail = {r["id"]: r for r in (prev_doc.get("results") or []) if isinstance(r, dict) and r.get("id") and r.get("status") in ("FAIL", "ERROR", "NOT_RUN")}
    cur_fail = {r["id"]: r for r in results if r.get("status") in ("FAIL", "ERROR", "NOT_RUN")}
    if not has_baseline:
        lines += [f"This is iteration {iteration} and no previous snapshot exists — there is no prior failure set to compare against.", ""]
    else:
        if prev_results_note:
            lines += [prev_results_note, ""]
        lines += [f"Baseline ({baseline_label}) had **{len(prev_fail) if not prev_results_note else '?'}** non-passing test(s); this iteration has **{len(cur_fail)}**.", ""]
        if prev_fail or cur_fail:
            lines += ["| Test ID | Previous status | Current status | Current message |", "| :-- | :-- | :-- | :-- |"]
            for tid in sorted(set(prev_fail) | set(cur_fail)):
                p = prev_fail.get(tid, {}).get("status", "PASS" if not prev_results_note else "?")
                c = next((r for r in results if r["id"] == tid), None)
                cs = c["status"] if c else "—"
                msg = (c or {}).get("message", "") if c else ""
                lines.append(f"| {tid} | {p} | {cs} | {msg[:140].replace('|', '/')} |")
            lines.append("")
    if cur_fail:
        lines += ["### Current failures (detail)", "", "| Test ID | Category | Status | Failed step | Expected | Actual |", "| :-- | :-- | :-- | :-- | :-- | :-- |"]
        for r in cur_fail.values():
            lines.append(f"| {r['id']} | {r.get('category', '')} | {r['status']} | {r.get('failedStep') if r.get('failedStep') is not None else '—'} | {str(r.get('expected', ''))[:100].replace('|', '/')} | {str(r.get('actual') or r.get('message', ''))[:160].replace('|', '/').replace(chr(10), ' ')} |")
        lines.append("")
    else:
        lines += ["No failing tests in this iteration.", ""]
    # §2 what was modified
    lines += ["## 2. What was modified (real unified diff between snapshots)", ""]
    flagged: list[dict[str, Any]] = []
    if not has_baseline:
        lines += [f"No baseline snapshot — nothing to diff against. All files under `src/` are new in iteration {iteration}:", ""]
        for rel in sorted(list_files(cur_dir)):
            lines.append(f"- `{rel}` (new)")
        lines.append("")
    else:
        pats = build_guardrail_patterns(spec_md)
        total_hunks = 0
        _, detailed_changes = compute_snapshot_file_changes(prev_dir, cur_dir, baseline_label, f"iter-{iteration}")
        for rel, tag, hunks in detailed_changes:
            if tag == "binary-modified":
                lines += [f"### `{rel}` — binary file changed (not diffed; data files are not guardrail-classified)", ""]
                continue
            lines += [f"### `{rel}` — {tag}, {len(hunks)} hunk(s)", ""]
            for hi, h in enumerate(hunks, 1):
                total_hunks += 1
                cats = [] if Path(rel).suffix.lower() in DOC_SUFFIXES else classify_hunk(h, pats)
                hh = hunk_hash(rel, h)
                if cats:
                    flagged.append({"file": rel, "hunk": hi, "header": h[0] if h else "", "categories": cats, "hash": hh,
                                    "changed": [ln for ln in h if ln.startswith(("+", "-"))][:6]})
                shown = h if len(h) <= 60 else h[:60] + [f"… ({len(h) - 60} more lines truncated)"]
                mark = (" — ⚠ " + ", ".join(cats) + (" (approved)" if hh in approved else "")) if cats else ""
                lines += [f"<details><summary>Hunk {hi}{mark} `{hh[:12]}`</summary>", "", "```diff", *shown, "```", "</details>", ""]
        if total_hunks == 0:
            lines += [f"No file under `src/` changed between `{baseline_label}` and `iter-{iteration}`.", ""]
    # §3 guardrail classification — persisted across runs
    lines += ["## 3. Automated guardrail & guideline compliance check", ""]
    current_flagged = {f["hash"]: f for f in flagged}
    pending = [h for h in current_flagged if h not in approved]
    stale_pending = [h for h in prev_pending if h not in current_flagged and h not in approved]
    approved_now: list[str] = []
    if approve and pending:
        approved_now = list(pending)
        approved.update(pending)
        pending = []
    if pending:
        status = "FLAGGED_REQUIRES_HUMAN_APPROVAL"
    elif had_prior_results and not has_baseline:
        status = "UNKNOWN_BASELINE"
    else:
        status = "CLEAR"
    unapproved_rows = [f for f in flagged if f["hash"] not in approved]
    approved_rows = [f for f in flagged if f["hash"] in approved]
    if unapproved_rows:
        lines += [f"**{len(unapproved_rows)}** hunk(s) touch guardrail-sensitive regions and need explicit human approval before the iteration is accepted:", "",
                  "| File | Hunk | Hash | Guardrail region(s) | Changed lines (first 6) |", "| :-- | :-- | :-- | :-- | :-- |"]
        for f in unapproved_rows:
            ch = "<br>".join(html_mod.escape(x, quote=False)[:110] for x in f["changed"])
            lines.append(f"| `{f['file']}` | {f['hunk']} `{f['header'][:30]}` | `{f['hash'][:12]}` | {', '.join(f['categories'])} | {ch} |")
        lines += ["", "Review each hunk: confirm it does not relax a role check, a workflow prerequisite, a business-rule formula, PII masking, an accessibility attribute or an enum→label mapping. Record the decision in this file, then re-run with `--approve-guardrail-flags`.", ""]
    if approved_rows:
        lines += [f"{len(approved_rows)} guardrail-sensitive hunk(s) in this diff were previously approved: " + ", ".join(f"`{f['hash'][:12]}`" for f in approved_rows), ""]
    if not flagged:
        lines += ["No modified hunk matched a guardrail-sensitive pattern (role/permission checks, state guards, spec §3.3 state names/triggers, spec §3.4 rule identifiers, masking/PII, accessibility attributes, label mappings, formulas/thresholds).", ""]
    if stale_pending:
        lines += [f"{len(stale_pending)} previously pending hunk(s) no longer appear in the diff against the approved baseline (reverted) and were dropped from the pending set.", ""]
    if status == "UNKNOWN_BASELINE":
        lines += ["> ⚠ `test/eval_results.json` existed before this run but no snapshot did: the change history is unknown, so this report cannot assert CLEAR. "
                  "The next iteration will be diffed against this snapshot.", ""]
    lines += [f"`GUARDRAIL_REVIEW_STATUS: {status}`", ""]
    if approve:
        if approved_now:
            lines += [f"`GUARDRAIL_HUMAN_DECISION: APPROVED_BY_USER` — {len(approved_now)} hunk(s) approved via --approve-guardrail-flags at iteration {iteration}: " + ", ".join(f"`{h[:12]}`" for h in approved_now), ""]
        else:
            lines += ["`GUARDRAIL_HUMAN_DECISION: APPROVED_BY_USER` (recorded via --approve-guardrail-flags; nothing was pending)", ""]

    # §4 preserved failure & remediation details from all prior iterations
    prior_rows = [hr for hr in history_rows if hr["iteration"] < iteration and (hr["failedEntries"] or hr["detailedDiffs"])]
    if prior_rows:
        lines += [
            "## 4. Preserved Failure & Remediation Log from Prior Iterations",
            "",
            "> Preserved below so that subsequent passing or verification runs never obscure earlier test failures or the code changes that remediated them.",
            "",
        ]
        for hr in prior_rows:
            it_k = hr["iteration"]
            lines += [
                f"### Iteration {it_k} (`{hr['evaluatedAtUtc']}`) — Verdict: **{hr['verdict']}** (Preserved in `{hr['historyDir']}/`)",
                "",
            ]
            if hr["failedEntries"]:
                lines += [
                    f"#### Failures detected in Iteration {it_k} ({len(hr['failedEntries'])} non-passing test(s))",
                    "",
                    "| Test ID | Category | Status | Failed step | Expected | Actual / Diagnostic Message |",
                    "| :-- | :-- | :-- | :-- | :-- | :-- |",
                ]
                for r in hr["failedEntries"]:
                    lines.append(
                        f"| {r.get('id', '')} | {r.get('category', '')} | {r.get('status', '')} | "
                        f"{r.get('failedStep') if r.get('failedStep') is not None else '—'} | "
                        f"{str(r.get('expected', ''))[:100].replace('|', '/')} | "
                        f"{str(r.get('actual') or r.get('message', ''))[:160].replace('|', '/').replace(chr(10), ' ')} |"
                    )
                lines.append("")
            if hr["remediatedIds"]:
                lines += [
                    f"- **Tests Remediated in Iteration {it_k} (FAIL → PASS):** {', '.join(f'`{t}`' for t in hr['remediatedIds'])}",
                    "",
                ]
            if hr["detailedDiffs"]:
                lines += [f"#### Code Remediation Diffs (`iter-{it_k - 1}` → `iter-{it_k}`)", ""]
                for rel, tag, hunks in hr["detailedDiffs"]:
                    if tag == "binary-modified":
                        lines += [f"- `{rel}` (binary file modified)", ""]
                        continue
                    lines += [f"- **`{rel}`** ({tag}, {len(hunks)} hunk(s))", ""]
                    for hi, h in enumerate(hunks, 1):
                        shown = h if len(h) <= 40 else h[:40] + [f"… ({len(h) - 40} more lines truncated)"]
                        lines += [f"<details><summary>Iter {it_k} · {rel} · Hunk {hi}</summary>", "", "```diff", *shown, "```", "</details>", ""]
    dlc.write_text(out_path, "\n".join(lines))
    # persist state: baseline advances only when nothing is pending
    new_state = {
        "schemaVersion": dlc.SCHEMA_VERSION,
        "pendingHunks": pending,
        "approvedHunks": sorted(approved),
        "flaggedAtIteration": iteration if pending else None,
        "baselineSnapshot": baseline_label if pending else f"iter-{iteration}",
        "baselineIteration": (int(m.group(1)) if (m := re.match(r"iter-(\d+)$", baseline_label if pending else f"iter-{iteration}")) else None),
        "lastIteration": iteration,
        "lastStatus": status,
        "updatedAtUtc": dlc.utc_now_iso(deterministic),
    }
    dlc.write_json(root / GUARDRAIL_STATE_FILE, new_state)
    return {"status": status, "pending": pending, "approvedNow": approved_now, "baseline": baseline_label, "flaggedTotal": len(flagged)}


# ======================================================================================
# Eval report
# ======================================================================================
def write_eval_report(out_path: Path, data: dict[str, Any], root: Path, backend_error: str, ui_error: str) -> None:
    s = data["summary"]
    rt = data["runtime"]
    results = data["results"]
    iteration = int(data["iteration"])
    history_rows = build_cumulative_history_rows(root, iteration, results, str(data["evaluatedAtUtc"]))
    lines = [f"# Closed-Loop Evaluation Report — Iteration {iteration}", "",
             f"Generated: {data['evaluatedAtUtc']}  ", f"Project: `{root.name}`  ",
             f"Browser runtime: **{rt['browser']}**{' (' + rt.get('browserBinary', '') + ')' if rt.get('browserBinary') else ''}  ",
             f"Backend started: **{rt['backendStarted']}**{' — ' + backend_error if backend_error else ''}  ",
             f"UI entry: `{rt.get('uiEntry', '')}`{' — ' + ui_error if ui_error else ''}  ",
             f"Preserved Per-Run Archive: `test/history/iter-{iteration}/` · `test/eval_report.iter-{iteration:02d}.md` · `test/eval_results.iter-{iteration:02d}.json`", "",
             f"## Verdict: **{s['verdict']}** — {s['pass']}/{s['total']} passed (score {s['score']:.1f}%)", "",
             "| Total | PASS | FAIL | NOT_RUN | ERROR | Optional skipped |", "| --: | --: | --: | --: | --: | --: |",
             f"| {s['total']} | {s['pass']} | {s['fail']} | {s['notRun']} | {s['error']} | {s.get('optionalNonPassing', 0)} |", ""]
    if s["verdict"] != "PASS":
        lines += ["> NOT_RUN never counts as a pass. The verdict is PASS only when zero FAIL/ERROR/NOT_RUN remain among non-optional tests, with zero leakage hits and zero unwired controls.", ""]
        if s.get("verdictBlockers"):
            lines += ["Verdict blockers: " + "; ".join(s["verdictBlockers"]), ""]
    if s.get("optionalNonPassingIds"):
        lines += [f"> ⚠ **{len(s['optionalNonPassingIds'])} optional test(s) are not passing** (authored `optional: true`; they do not block the verdict but must be reviewed, never ignored): "
                  + ", ".join(f"`{i}`" for i in s["optionalNonPassingIds"]), ""]
    g = data.get("guardrail") or {}
    if g:
        lines += [f"Guardrail review: **{g.get('status')}** (baseline `{g.get('baseline')}`, pending hunks: {len(g.get('pendingHunks') or [])})", ""]
    lines += ["## Run History & Preserved Per-Iteration Artifacts", ""]
    lines += history_table_lines(history_rows, max_ids=6, with_files=False) + [""]
    cats: dict[str, dict[str, int]] = {}
    for r in results:
        c = cats.setdefault(r.get("category", "?"), {"total": 0, "PASS": 0, "FAIL": 0, "NOT_RUN": 0, "ERROR": 0})
        c["total"] += 1
        c[r["status"]] = c.get(r["status"], 0) + 1
    lines += ["## Per category", "", "| Category | Total | PASS | FAIL | NOT_RUN | ERROR |", "| :-- | --: | --: | --: | --: | --: |"]
    for k in sorted(cats):
        c = cats[k]
        lines.append(f"| {k} | {c['total']} | {c['PASS']} | {c['FAIL']} | {c['NOT_RUN']} | {c['ERROR']} |")
    lines += ["", "## All results", "", "| Test ID | Category | Runtime | Status | ms | Failed step | Message |", "| :-- | :-- | :-- | :-- | --: | :-- | :-- |"]
    for r in results:
        lines.append(f"| {r['id']} | {r.get('category', '')} | {r.get('runtime', '')} | {r['status']} | {r.get('durationMs', 0)} | {r.get('failedStep') if r.get('failedStep') is not None else '—'} | {str(r.get('message', ''))[:120].replace('|', '/')} |")
    failures = [r for r in results if r["status"] in ("FAIL", "ERROR", "NOT_RUN")]
    lines += ["", "## Failures (expected vs actual)", ""]
    if not failures:
        lines.append("None.")
    for r in failures:
        lines += [f"### {r['id']} — {r['status']} ({r.get('category', '')})", "",
                  f"- **Title:** {r.get('title', '')}", f"- **Expected:** {r.get('expected', '')}",
                  f"- **Failed step:** {r.get('failedStep') if r.get('failedStep') is not None else '—'}",
                  f"- **Message:** {r.get('message', '')}", f"- **Actual:** `{str(r.get('actual', ''))[:400]}`"]
        if r.get("stepLog"):
            lines += ["", "<details><summary>Step log</summary>", "", "| # | action | target | ok | actual |", "| --: | :-- | :-- | :-- | :-- |"]
            for st in r["stepLog"]:
                lines.append(f"| {st['index']} | {st['action']} | `{str(st.get('selector', ''))[:50]}` | {'✓' if st['ok'] else '✗'} | {str(st.get('actual', ''))[:100].replace('|', '/')} |")
            lines += ["</details>"]
        lines.append("")
    lk = data["leakage"]
    lines += ["## Zero-leakage scan (TC-UI-LEAK-01..04)", "", f"Tokens scanned: {lk['tokensScanned']} · exact hits: **{len(lk['hits'])}** · heuristic warnings: {len(lk.get('warnings', []))}", ""]
    if lk["hits"]:
        lines += ["| Token | Class | Seen in | Context |", "| :-- | :-- | :-- | :-- |"]
        for h in lk["hits"]:
            lines.append(f"| `{h['token']}` | {h['tokenClass']} | {h['source']} | {h['context'][:140].replace('|', '/')} |")
        lines.append("")
    if lk.get("warnings"):
        lines += ["<details><summary>Heuristic warnings (not failures — review for false positives)</summary>", "", "| Heuristic | Match | Seen in | Context |", "| :-- | :-- | :-- | :-- |"]
        for w in lk["warnings"][:60]:
            lines.append(f"| {w['heuristic']} | `{w['match'][:40]}` | {w['source']} | {w['context'][:120].replace('|', '/')} |")
        lines += ["</details>", ""]
    it = data["interactivity"]
    lines += ["## Interactive control audit (TC-UI-INTERACT-01)", "", f"Controls observed across all reached DOM states: {it['controls']} · unwired: **{len(it['unwired'])}**", ""]
    if it["unwired"]:
        lines += ["| Control | Text | Reason |", "| :-- | :-- | :-- |"]
        for u in it["unwired"]:
            lines.append(f"| `{u['selector']}` | {u.get('text', '')[:40]} | {u['reason']} |")
        lines.append("")
    a11y = data["a11y"]
    lines += ["## Accessibility lint (TC-A11Y-01)", "", f"Findings: **{len(a11y['findings'])}**", ""]
    if a11y["findings"]:
        lines += ["| Rule | Detail |", "| :-- | :-- |"]
        for f in a11y["findings"][:80]:
            lines.append(f"| {f['rule']} | {f['message'][:140].replace('|', '/')} |")
        lines.append("")
    ux = data.get("ux") or {}
    if ux:
        lines += ["## UX guardrail metrics (TC-UX-SIMPLE-01..03)", "",
                  f"- Max visible primary buttons on one screen: {ux.get('primaryVisible')} (≤ 1) {ux.get('primarySelectors', '')}",
                  f"- Max visible tabs/nav items: {ux.get('tabsVisible')} (≤ 3)",
                  f"- Max visible inputs outside `<details>` in one step container: {ux.get('inputsVisibleMaxPerContainer')} (≤ 5) in `{ux.get('inputsWorstContainer', '')}`",
                  f"- Main container max-width: {ux.get('mainMaxWidth') or 'n/a'}", ""]
    shots = data.get("screenshots") or []
    if shots:
        lines += ["## Visual evidence & viewport screenshots", "",
                  "| View / Capture | Kind | Artifact Path |",
                  "| :-- | :-- | :-- |"]
        for sh in shots:
            lines.append(f"| {sh.get('label', '')} | `{sh.get('kind', 'view')}` | `{sh.get('path', '')}` |")
        lines.append("")
    dlc.write_text(out_path, "\n".join(lines))


# ======================================================================================
# Main
# ======================================================================================
def archive_iteration_artifacts(
    root: Path,
    iteration: int,
    json_out: Path,
    report_out: Path,
    audit_out: Path,
    data: dict[str, Any],
    deterministic: bool,
) -> dict[str, str]:
    """Persist non-overwritten copies of the run results, evaluation report, remediation & guardrail audit report,
    and defect logs into `test/history/iter-{iteration}/`, `test/.snapshots/iter-{iteration}/`, and numbered
    sibling files under `test/*.iter-{iteration:02d}.*`, plus update `test/history/run_index.json` and `README.md`.
    """
    hist_dir = root / "test" / "history" / f"iter-{iteration}"
    snap_dir = root / "test" / ".snapshots" / f"iter-{iteration}"
    hist_dir.mkdir(parents=True, exist_ok=True)
    snap_dir.mkdir(parents=True, exist_ok=True)

    pairs = [
        (json_out, "eval_results.json", root / "test" / f"eval_results.iter-{iteration:02d}.json"),
        (report_out, "eval_report.md", root / "test" / f"eval_report.iter-{iteration:02d}.md"),
        (audit_out, "remediation_and_guardrail_audit_report.md", root / "test" / f"remediation_and_guardrail_audit_report.iter-{iteration:02d}.md"),
        (root / "backlog" / "defects.json", "defects.json", root / "test" / f"defects.iter-{iteration:02d}.json"),
        (root / "backlog" / "defects.md", "defects.md", root / "test" / f"defects.iter-{iteration:02d}.md"),
    ]
    saved: dict[str, str] = {}
    for src_p, base_name, numbered_p in pairs:
        if not src_p.is_file():
            continue
        for dst_p in (hist_dir / base_name, snap_dir / base_name, numbered_p):
            dst_p.parent.mkdir(parents=True, exist_ok=True)
            if src_p.resolve() != dst_p.resolve():
                shutil.copy2(src_p, dst_p)
        saved[base_name] = str(hist_dir.relative_to(root) / base_name)

    # Update test/history/run_index.json and test/history/README.md
    history_rows = build_cumulative_history_rows(root, iteration, data.get("results") or [], str(data.get("evaluatedAtUtc") or ""))
    index_entries: list[dict[str, Any]] = []
    for hr in history_rows:
        index_entries.append({
            "iteration": hr["iteration"],
            "evaluatedAtUtc": hr["evaluatedAtUtc"],
            "verdict": hr["verdict"],
            "total": hr["total"],
            "pass": hr["pass"],
            "fail": hr["fail"],
            "notRun": hr["notRun"],
            "error": hr["error"],
            "failedTestIds": hr["failedIds"],
            "remediatedTestIds": hr["remediatedIds"],
            "modifiedSourceFiles": hr["changedFiles"],
            "artifacts": {
                "historyDir": hr["historyDir"],
                "evalResultsJson": f"{hr['historyDir']}/eval_results.json",
                "evalReportMd": f"{hr['historyDir']}/eval_report.md",
                "remediationAuditReportMd": f"{hr['historyDir']}/remediation_and_guardrail_audit_report.md",
                "numberedEvalResultsJson": hr["evalResultsFile"],
                "numberedEvalReportMd": hr["evalReportFile"],
                "numberedRemediationAuditReportMd": hr["auditReportFile"],
                "defectsJson": f"{hr['historyDir']}/defects.json" if (root / hr["historyDir"] / "defects.json").is_file() else None,
                "defectsMd": f"{hr['historyDir']}/defects.md" if (root / hr["historyDir"] / "defects.md").is_file() else None,
            },
        })
    hist_root = root / "test" / "history"
    hist_root.mkdir(parents=True, exist_ok=True)
    dlc.write_json(hist_root / "run_index.json", {
        "schemaVersion": dlc.SCHEMA_VERSION,
        "updatedAtUtc": dlc.utc_now_iso(deterministic),
        "latestIteration": iteration,
        "totalRuns": len(index_entries),
        "runs": index_entries,
    })
    md_lines = [
        "# Stage 6 Closed-Loop Evaluation & Remediation Run History (`test/history/`)",
        "",
        f"- **Updated:** `{dlc.utc_now_iso(deterministic)}`",
        f"- **Total Preserved Runs:** `{len(index_entries)}` (`iter-1` .. `iter-{iteration}`)",
        "",
        "> Every evaluation and remediation run is archived in its own immutable `test/history/iter-<N>/` directory (and `test/*.iter-<NN>.*` files) so failed runs, test diagnostics, and code remediation diffs are never overwritten.",
        "",
    ]
    md_lines += history_table_lines(history_rows) + [""]
    dlc.write_text(hist_root / "README.md", "\n".join(md_lines))
    return saved


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument("--iteration", type=int, default=None, help="Iteration number (default: next under test/.snapshots; an existing iter-N is moved to iter-N.prev, never overwritten)")
    ap.add_argument("--test-cases", default="test/test_cases.json")
    ap.add_argument("--browser", choices=["auto", "playwright", "chrome", "none"], default="auto")
    ap.add_argument("--chrome-binary", default=None)
    ap.add_argument("--skip-backend", action="store_true", help="Do not start commands.start (assume it is running or not needed)")
    ap.add_argument("--deterministic", action="store_true", help="Stable timestamps for golden comparisons (also skips ALM sync unless --alm-sync)")
    ap.add_argument("--json-out", default="test/eval_results.json")
    ap.add_argument("--report", default="test/eval_report.md")
    ap.add_argument("--audit-report", default="test/remediation_and_guardrail_audit_report.md")
    ap.add_argument("--chrome-timeout", type=int, default=90, help="Wall-clock seconds per headless-Chrome run (always ≥ virtual-time budget + 15s)")
    ap.add_argument("--approve-guardrail-flags", action="store_true", help="Human has reviewed the pending flagged hunks; move them to the approved set in test/.guardrail_state.json")
    ap.add_argument("--skip-alm-sync", action="store_true", help="Skip automatic synchronization of user story statuses from evaluation results")
    ap.add_argument("--alm-sync", action="store_true", help="Force the ALM bridge call even when almPlatform is 'none' or --deterministic is set")
    ap.add_argument("--selftest-guardrail-patterns", action="store_true", help="Assert the guardrail classifier matches its reference identifiers and exit")
    args = ap.parse_args()

    if args.selftest_guardrail_patterns:
        missed = selftest_guardrail_patterns()
        for ident in GUARDRAIL_SELFTEST:
            print(f"  {'✗' if ident in missed else '✓'} {ident}")
        if missed:
            print(f"GUARDRAIL PATTERN SELFTEST: FAIL — {len(missed)} identifier(s) not matched: {missed}")
            return 1
        print(f"GUARDRAIL PATTERN SELFTEST: PASS ({len(GUARDRAIL_SELFTEST)} identifiers)")
        return 0

    root = dlc.resolve_project_root(args.project_root)
    dlc.require_gate_approved(root, "gate_5_build", "Stage 6 (07-test-runner-and-healer / run_closed_loop_eval.py)", deterministic=args.deterministic)
    tc_path = dlc.require_file(dlc.project_path(root, args.test_cases), "Stage 4B (05/scripts/derive_test_cases.py skeleton + testing-agent fills steps)")
    suite = dlc.read_json(tc_path)
    retired = {str(r.get("id") if isinstance(r, dict) else r) for r in (suite.get("retiredTestCases") or [])}
    test_cases: list[dict[str, Any]] = [t for t in (suite.get("testCases") or []) if t.get("id") not in retired]
    if retired:
        dlc.info(f"ignoring {len(retired)} retired test case id(s)")
    if not test_cases:
        raise dlc.GateFailure(f"{tc_path} has no testCases — Stage 4B must derive them.")
    forbidden = suite.get("forbiddenUiTokens") or {}

    snap_root = root / "test" / ".snapshots"
    # Must be computed BEFORE resolve_iteration() archives the previous top-level results (it never fabricates a snapshot).
    had_prior_results = dlc.project_path(root, args.json_out).exists() and not any(snap_root.glob("iter-*"))
    if had_prior_results:
        dlc.warn(f"{args.json_out} exists but test/.snapshots/ has no iteration — the change history is unknown (audit report will say UNKNOWN_BASELINE, not CLEAR)")
    iteration = resolve_iteration(root, args.iteration)
    snap_dir, displaced = snapshot_src(root, iteration)
    dlc.info(f"iteration {iteration}: snapshot of src/ → {snap_dir.relative_to(root)}")

    stack = dlc.load_target_stack(root)
    commands = stack.get("commands") or {}
    backend_kind = (stack.get("backend") or {}).get("kind", "none")
    fe_kind = str((stack.get("frontend") or {}).get("kind") or "").strip()
    ui = UiEntry(root, commands.get("uiEntry") or "src/ui/index.html")
    spec_md = dlc.read_text(root / "specs" / "application_spec.md") if (root / "specs" / "application_spec.md").exists() else ""
    if not spec_md:
        dlc.warn("specs/application_spec.md missing — audit report cannot use spec state names / rule identifiers")

    results: list[dict[str, Any]] = []
    texts_for_leak: dict[str, str] = {}
    controls_acc: dict[str, dict[str, Any]] = {}
    a11y_acc: dict[str, dict[str, str]] = {}  # findings from rendered DOM states
    a11y_static: dict[str, dict[str, str]] = {}  # findings from the static uiEntry source (only authoritative for static-html / no browser)
    ux_acc: dict[str, Any] = {}
    browser_name = "none"
    browser_binary = ""
    backend_started = False
    backend_error = ""
    browser_states_reached = 0  # browser TCs that produced an observed DOM state (PASS/FAIL with a control audit)
    screenshots: list[dict[str, str]] = []
    unwired: list[dict[str, Any]] = []
    a11y_findings: list[dict[str, str]] = []
    hits: list[dict[str, Any]] = []
    warns: list[dict[str, Any]] = []
    scanned = 0

    tmp = Path(tempfile.mkdtemp(prefix="dlc-eval-"))
    adapter = None
    try:
        with Backend(root, commands, args.skip_backend or backend_kind == "none", root / "test" / ".build_logs") as be:
            backend_started, backend_error = be.started, be.error
            runtime_blocked = be.stale_port  # a server this run did not start owns the port → nothing observed is trustworthy
            ui_source = ui.source() if not runtime_blocked else ""
            if ui_source:
                texts_for_leak["static:uiEntry source"] = dlc.html_visible_text(ui_source)
                for f in a11y_lint(ui_source):
                    a11y_static.setdefault(f"{f['rule']}|{f['message']}", f)
            browser_tcs = [t for t in test_cases if t.get("runtime") == "browser"]
            unwired_from_probe: list[dict[str, str]] = []
            if browser_tcs and args.browser != "none" and not runtime_blocked:
                adapter, browser_name = pick_browser(args.browser, args.chrome_binary, ui, tmp)
                if adapter is not None:
                    adapter_timeout = getattr(adapter, "timeout_s", None)
                    if adapter_timeout is not None:
                        adapter.timeout_s = args.chrome_timeout
                    browser_binary = getattr(adapter, "binary", "")
                    dlc.info(f"browser adapter: {browser_name} {browser_binary}")
                    if ui_source and hasattr(adapter, "capture_visual_evidence"):
                        hist_shots_dir = root / "test" / "history" / f"iter-{iteration}" / "screenshots"
                        screenshots, unwired_from_probe = adapter.capture_visual_evidence(
                            ui_source, hist_shots_dir, root
                        )
                        if hist_shots_dir.is_dir():
                            shutil.copytree(hist_shots_dir, snap_dir / "screenshots", dirs_exist_ok=True)
                else:
                    dlc.warn(BROWSER_INSTALL_HINT)

            special = re.compile(r"^TC-(UI-LEAK|UI-INTERACT|A11Y|UX-SIMPLE)-\d+$")
            deferred: list[dict[str, Any]] = []
            stale_msg = f"backend port is owned by a server this run did not start ({be.error}); results would reflect stale code — stop it or pass --skip-backend"
            for tc in test_cases:
                tid = tc.get("id", "?")
                runtime = tc.get("runtime") or ("browser" if tc.get("steps") else "static")
                base = {"id": tid, "category": tc.get("category", ""), "title": tc.get("title", ""), "expected": tc.get("expected", ""),
                        "runtime": runtime, "optional": bool(tc.get("optional", False)), "storyRef": tc.get("storyRef"), "acRef": tc.get("acRef")}
                steps = tc.get("steps") or []
                if tc.get("deferredByGroupSelection"):
                    results.append({**base, "optional": True, "deferredByGroupSelection": True, "status": "NOT_RUN", "durationMs": 0, "failedStep": None, "message": f"deferred — unselected capability group ({tc.get('capabilityGroup') or 'Product Backlog'})", "actual": ""})
                    continue
                if (special.match(tid) and not steps) or (runtime == "static" and steps and any(st.get("action") in DEFERRED_ACTIONS for st in steps)):
                    deferred.append(tc)  # needs every rendered browser state → evaluated after the browser TCs
                    continue
                if not steps or tc.get("needsSteps"):
                    results.append({**base, "status": "NOT_RUN", "durationMs": 0, "failedStep": None, "message": "steps not authored yet (Stage 4B test specification must populate `steps`)", "actual": ""})
                    continue
                if runtime_blocked and runtime in ("browser", "http", "static"):
                    # Every runtime-dependent TC — browser included — is ERROR, never a verdict against stale code.
                    results.append({**base, "status": "ERROR", "durationMs": 0, "failedStep": None, "message": stale_msg, "actual": ""})
                    continue
                if runtime == "browser":
                    if adapter is None:
                        results.append({**base, "status": "NOT_RUN", "durationMs": 0, "failedStep": None, "message": BROWSER_INSTALL_HINT if args.browser != "none" else "browser runtime disabled (--browser none)", "actual": ""})
                        continue
                    if not ui_source:
                        results.append({**base, "status": "ERROR", "durationMs": 0, "failedStep": None, "message": ui.error or "UI entry unavailable", "actual": ""})
                        continue
                    res = adapter.run(tc, ui_source)
                    if res.get("status") in ("PASS", "FAIL") and res.get("controls") is not None:
                        browser_states_reached += 1  # only an observed DOM (with a control audit) counts as a reached state
                    for key in ("visibleTextAllStates",):
                        if res.get(key):
                            texts_for_leak[f"browser:{tid}"] = res[key]
                    for c in res.get("controls") or []:
                        k = f"{c['selector']}|{c.get('text', '')}"
                        if k not in controls_acc or not c.get("hasHandler"):
                            controls_acc[k] = {**c, "seenIn": tid}
                    for f in res.get("a11y") or []:
                        a11y_acc.setdefault(f"{f['rule']}|{f['message']}", f)
                    ux = res.get("ux") or {}
                    if ux:
                        for k in ("primaryVisible", "tabsVisible", "inputsVisibleMaxPerContainer"):
                            if ux.get(k, 0) > ux_acc.get(k, -1):
                                ux_acc[k] = ux.get(k, 0)
                                if k == "primaryVisible":
                                    ux_acc["primarySelectors"] = ux.get("primarySelectors", [])
                                    ux_acc["primaryTc"] = tid
                                if k == "inputsVisibleMaxPerContainer":
                                    ux_acc["inputsWorstContainer"] = ux.get("inputsWorstContainer", "")
                        ux_acc.setdefault("mainMaxWidth", ux.get("mainMaxWidth", ""))
                    entry = {**base, "status": res.get("status", "ERROR"), "durationMs": res.get("durationMs", 0), "failedStep": res.get("failedStep"),
                             "message": res.get("message", ""), "actual": str(res.get("actual", ""))[:600], "stepLog": res.get("steps", [])}
                    if res.get("screenshot"):
                        sp = Path(res["screenshot"])
                        rel_sp = str(sp.relative_to(root)) if sp.is_relative_to(root) else str(sp)
                        entry["screenshot"] = rel_sp
                        screenshots.append({"label": f"Failure snapshot: {tid}", "path": rel_sp, "kind": "failure"})
                    if res.get("scriptErrors"):
                        entry["scriptErrors"] = res["scriptErrors"]
                        if entry["status"] == "PASS" and tc.get("failOnScriptError", False):
                            entry["status"] = "FAIL"
                            entry["message"] = "page threw script errors: " + "; ".join(res["scriptErrors"])
                    if entry["status"] == "PASS" and not entry["message"]:
                        entry["message"] = f"{len(steps)} step(s) passed"
                    results.append(entry)
                elif runtime == "http":
                    if backend_kind == "none" and not be.base_url:
                        results.append({**base, "status": "NOT_RUN", "durationMs": 0, "failedStep": None, "message": "target_stack.backend.kind is none — no HTTP backend to test", "actual": ""})
                    elif not be.started:
                        results.append({**base, "status": "NOT_RUN", "durationMs": 0, "failedStep": None, "message": f"backend not available: {be.error or 'not started'}", "actual": be.log_tail(8)})
                    else:
                        results.append({**base, **run_http_steps(tc, be.base_url)})
                elif runtime == "static":
                    if not ui_source:
                        results.append({**base, "status": "ERROR", "durationMs": 0, "failedStep": None, "message": ui.error, "actual": ""})
                    else:
                        results.append({**base, **run_static_steps(tc, ui_source)})
                else:
                    results.append({**base, "status": "ERROR", "durationMs": 0, "failedStep": None, "message": f"unknown runtime '{runtime}'", "actual": ""})

            # ---- cross-cutting checks (computed, never hard-coded) ----
            hits, warns, scanned = leakage_scan(forbidden, texts_for_leak)
            for leak_msg in dlc.scan_deliverable_internal_leaks(root):
                m_tok = re.search(r"exposes internal harness detail '([^']+)'", leak_msg)
                tok_val = m_tok.group(1) if m_tok else "internal-harness-detail"
                src_loc = leak_msg.split(" exposes ", 1)[0]
                hits.append({
                    "token": tok_val,
                    "tokenClass": "internalHarnessLeak",
                    "source": f"deliverable:{src_loc}",
                    "severity": "fail",
                    "context": leak_msg[:220],
                })
            unwired = [{"selector": c["selector"], "text": c.get("text", ""), "reason": c["reason"], "seenIn": c.get("seenIn", "")} for c in controls_acc.values() if not c.get("hasHandler")]
            for u_tab in unwired_from_probe:
                if not any(u["selector"] == u_tab["selector"] for u in unwired):
                    unwired.append({**u_tab, "seenIn": "interactivityProbe"})
            # Static a11y lint of an SPA shell is misleading (e.g. single-h1 before the app renders): it is authoritative only
            # when no DOM state was observed, or when the frontend really is static HTML.
            use_static_a11y = (browser_states_reached == 0) or (fe_kind == "static-html")
            a11y_findings = list(a11y_acc.values()) + (list(a11y_static.values()) if use_static_a11y else [])
            seen_keys: set[str] = set()
            a11y_findings = [f for f in a11y_findings if not (f"{f['rule']}|{f['message']}" in seen_keys or seen_keys.add(f"{f['rule']}|{f['message']}"))]  # type: ignore[func-returns-value]
            no_browser_note = "" if browser_states_reached else " (no browser state reached — static source only)"
            static_corpus_len = len((texts_for_leak.get("static:uiEntry source") or "").strip())
            static_ctx = {"browserStatesReached": browser_states_reached, "unwired": unwired, "a11yFindings": a11y_findings}
            for tc in deferred:
                tid = tc["id"]
                base = {"id": tid, "category": tc.get("category", ""), "title": tc.get("title", ""), "expected": tc.get("expected", ""),
                        "runtime": "static", "optional": bool(tc.get("optional", False)), "durationMs": 0, "failedStep": None,
                        "storyRef": tc.get("storyRef"), "acRef": tc.get("acRef"), "corpora": sorted(texts_for_leak)}
                if runtime_blocked:
                    results.append({**base, "status": "ERROR", "message": stale_msg, "actual": ""})
                    continue
                if tc.get("steps"):
                    if not ui_source:
                        results.append({**base, "status": "ERROR", "message": ui.error or "UI entry unavailable", "actual": ""})
                    else:
                        results.append({**base, **run_static_steps(tc, ui_source, texts_for_leak, static_ctx)})
                    continue
                m = re.match(r"^TC-UI-LEAK-(\d+)$", tid)
                if m:
                    classes = list(tc.get("tokenClasses") or LEAK_CLASS_BY_INDEX.get(int(m.group(1)), []))
                    if int(m.group(1)) == 3 and "internalHarnessLeak" not in classes:
                        classes.append("internalHarnessLeak")
                    my_hits = [h for h in hits if h["tokenClass"] in classes]
                    n_tokens = sum(len(forbidden.get(c) or []) for c in classes)
                    if not classes or n_tokens == 0:
                        # requireTokens defaults to true: a leak class with nothing to scan for is unproven, not passed.
                        if tc.get("requireTokens", True):
                            st, msg = "NOT_RUN", f"forbiddenUiTokens has no entries for {classes or '(none mapped)'}; Stage 4B must derive them (set requireTokens=false only if the class is genuinely empty by design)"
                        else:
                            st, msg = "PASS", f"no tokens declared for classes {classes or '(none mapped)'} in forbiddenUiTokens — requireTokens=false, nothing to leak{no_browser_note}"
                    elif my_hits:
                        uniq = sorted({h["token"] for h in my_hits})
                        st, msg = "FAIL", f"{len(uniq)} forbidden token(s) visible in {len({h['source'] for h in my_hits})} source(s): " + ", ".join(uniq[:8])
                    elif not browser_states_reached and static_corpus_len < MIN_STATIC_CORPUS_CHARS:
                        st, msg = "NOT_RUN", f"no browser state reached and the static visible text is only {static_corpus_len} chars — absence of tokens in an empty corpus is not evidence; " + BROWSER_INSTALL_HINT
                    else:
                        st, msg = "PASS", f"{n_tokens} token(s) of {', '.join(classes)} absent from all rendered visible text{no_browser_note}"
                    results.append({**base, "status": st, "message": msg, "actual": "; ".join(h["context"][:100] for h in my_hits[:3])})
                elif tid.startswith("TC-UI-INTERACT"):
                    if not browser_states_reached:
                        results.append({**base, "status": "NOT_RUN", "message": "requires a browser runtime to observe listeners; " + BROWSER_INSTALL_HINT, "actual": ""})
                    elif unwired:
                        results.append({**base, "status": "FAIL", "message": f"{len(unwired)} control(s) without any handler: " + ", ".join(u['selector'] for u in unwired[:6]), "actual": "; ".join(f"{u['selector']} ({u['text']})" for u in unwired[:6])})
                    elif not controls_acc:
                        results.append({**base, "status": "NOT_RUN", "message": f"{browser_states_reached} browser state(s) reached but no interactive control was observed — nothing to audit", "actual": ""})
                    else:
                        results.append({**base, "status": "PASS", "message": f"all {len(controls_acc)} observed controls are wired", "actual": ""})
                elif tid.startswith("TC-A11Y"):
                    if a11y_findings:
                        results.append({**base, "status": "FAIL", "message": f"{len(a11y_findings)} accessibility finding(s): " + "; ".join(f"{f['rule']}" for f in a11y_findings[:5]), "actual": "; ".join(f["message"] for f in a11y_findings[:4])})
                    else:
                        src_note = no_browser_note if use_static_a11y else " (rendered DOM states only — static shell lint not used for a non-static frontend)"
                        results.append({**base, "status": "PASS", "message": f"labels, alt text, single h1, lang, tabindex and accessible names verified{src_note}", "actual": ""})
                elif tid.startswith("TC-UX-SIMPLE"):
                    n = int(re.search(r"(\d+)$", tid).group(1))
                    if not ux_acc:
                        # `optional` stays exactly as authored — the runner never relaxes a test to make a verdict pass.
                        results.append({**base, "status": "NOT_RUN", "message": "UX guardrail metrics require a browser runtime; " + BROWSER_INSTALL_HINT, "actual": ""})
                        continue
                    limit = {1: ("primaryVisible", 1, "visible primary buttons per screen"), 2: ("tabsVisible", 3, "visible tabs / nav items"), 3: ("inputsVisibleMaxPerContainer", 5, "visible inputs outside <details> per step")}.get(n)
                    if not limit:
                        results.append({**base, "status": "NOT_RUN", "message": f"no measurement defined for {tid}", "actual": ""})
                        continue
                    key, mx, label = limit
                    val = ux_acc.get(key, 0)
                    ok = val <= mx
                    results.append({**base, "status": "PASS" if ok else "FAIL", "message": f"{label}: {val} (limit {mx})" + (f" in {ux_acc.get('inputsWorstContainer')}" if key.startswith('inputs') else "") + (f" {ux_acc.get('primarySelectors')}" if key == 'primaryVisible' and not ok else ""), "actual": str(val)})
    finally:
        if adapter is not None and hasattr(adapter, "close"):
            adapter.close()
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- summary & verdict ----
    counts = status_counts(results)
    non_opt_bad = [r for r in results if r["status"] in ("FAIL", "ERROR", "NOT_RUN") and not r.get("optional")]
    opt_bad = [r for r in results if r["status"] in ("FAIL", "ERROR", "NOT_RUN") and r.get("optional")]
    total = len(results)
    active_total = sum(1 for r in results if not r.get("deferredByGroupSelection"))
    verdict_blockers: list[str] = []
    if not active_total:
        verdict_blockers.append("no active test case")
    if non_opt_bad:
        verdict_blockers.append(f"{len(non_opt_bad)} non-optional test(s) not passing")
    # Leakage hits and dead controls fail the verdict on their own — whether or not a TC-UI-LEAK-* / TC-UI-INTERACT-* exists,
    # is optional, or was retired.
    if hits:
        verdict_blockers.append(f"{len(hits)} forbidden token(s) visible")
    if unwired:
        verdict_blockers.append(f"{len(unwired)} unwired control(s)")
    verdict = "PASS" if not verdict_blockers else "FAIL"
    data = {
        "schemaVersion": dlc.SCHEMA_VERSION,
        "evaluatedAtUtc": dlc.utc_now_iso(args.deterministic),
        "iteration": iteration,
        "runtime": {"browser": browser_name, "browserBinary": browser_binary, "backendStarted": backend_started, "backendError": backend_error,
                    "uiEntry": ui.raw, "backendKind": backend_kind, "browserStatesReached": browser_states_reached},
        "results": results,
        "summary": {"total": total, "pass": counts["PASS"], "fail": counts["FAIL"], "notRun": counts["NOT_RUN"], "error": counts["ERROR"],
                    "score": round(100.0 * counts["PASS"] / active_total, 1) if active_total else 0.0, "verdict": verdict, "optionalNonPassing": len(opt_bad)},
        "leakage": {"tokensScanned": scanned, "hits": hits, "warnings": warns, "sourcesScanned": sorted(texts_for_leak)},
        "interactivity": {"controls": len(controls_acc), "unwired": unwired},
        "a11y": {"findings": a11y_findings},
        "ux": ux_acc,
        "screenshots": screenshots,
    }
    if verdict_blockers:
        data["summary"]["verdictBlockers"] = verdict_blockers
    if opt_bad:
        data["summary"]["optionalNonPassingIds"] = [r["id"] for r in opt_bad]
    audit_out = dlc.project_path(root, args.audit_report)
    audit = write_audit_report(root, iteration, results, audit_out, spec_md, args.deterministic,
                               displaced=displaced, approve=args.approve_guardrail_flags, had_prior_results=had_prior_results)
    gstatus = audit["status"]
    # eval_results.schema.json enum: NOT_REQUIRED | FLAGGED_REQUIRES_HUMAN_APPROVAL | APPROVED_BY_USER
    if audit["pending"]:
        data["guardrailReviewStatus"] = "FLAGGED_REQUIRES_HUMAN_APPROVAL"
    elif audit["approvedNow"]:
        data["guardrailReviewStatus"] = "APPROVED_BY_USER"
    else:
        data["guardrailReviewStatus"] = "NOT_REQUIRED"
    data["guardrail"] = {"status": gstatus, "baseline": audit["baseline"], "pendingHunks": audit["pending"], "approvedNow": audit["approvedNow"],
                         "flaggedHunksInDiff": audit["flaggedTotal"], "stateFile": GUARDRAIL_STATE_FILE}
    schema_errors: list[str] = []
    try:
        schema_errors = dlc.validate_against_schema(data, dlc.load_schema("eval_results.schema.json"))
    except SystemExit:
        dlc.warn("schemas/eval_results.schema.json not found — skipping self-validation")
    if schema_errors:
        raise dlc.GateFailure("eval_results.json would violate schemas/eval_results.schema.json (bug in the runner):\n  " + "\n  ".join(schema_errors[:15]))
    json_out = dlc.project_path(root, args.json_out)
    report_out = dlc.project_path(root, args.report)
    dlc.write_json(json_out, data)
    write_eval_report(report_out, data, root, backend_error, ui.error)
    archive_iteration_artifacts(root, iteration, json_out, report_out, audit_out, data, args.deterministic)

    # Automatically synchronize story statuses ('To Do' / 'In Progress' / 'Done') to local backlog + Jira/ADO
    if run_alm_bridge(root, stack, ["--action", "sync-status-from-eval"], args.deterministic, args.skip_alm_sync, args.alm_sync):
        archive_iteration_artifacts(root, iteration, json_out, report_out, audit_out, data, args.deterministic)  # defects.* may have changed

    print("\n=== Stage 6 closed-loop evaluation — iteration", iteration, "===")
    print(f"browser={browser_name} backendStarted={backend_started} statesReached={browser_states_reached}")
    print(f"total={total} pass={counts['PASS']} fail={counts['FAIL']} notRun={counts['NOT_RUN']} error={counts['ERROR']} "
          f"leakHits={len(hits)} unwired={len(unwired)} a11yFindings={len(a11y_findings)} optionalNonPassing={len(opt_bad)}")
    for r in results:
        if r["status"] != "PASS":
            print(f"  - {r['id']:<20} {r['status']:<8} step={r.get('failedStep')} {'[optional] ' if r.get('optional') else ''}{r.get('message', '')[:110]}")
    if opt_bad:
        print(f"OPTIONAL NON-PASSING ({len(opt_bad)}): " + ", ".join(r["id"] for r in opt_bad) + " — authored as optional; they do not block the verdict but must not be ignored.")
    if verdict_blockers:
        print("VERDICT BLOCKERS: " + "; ".join(verdict_blockers))
    print(f"GUARDRAIL_REVIEW_STATUS: {gstatus}" + (f" (pending hunks: {len(audit['pending'])}, baseline {audit['baseline']}, state in {GUARDRAIL_STATE_FILE})" if audit["pending"] else ""))
    if audit["approvedNow"]:
        print(f"Gate 4: {len(audit['approvedNow'])} flagged hunk(s) recorded as APPROVED_BY_USER in {GUARDRAIL_STATE_FILE}")
    print(f"PRESERVED_RUN_ARCHIVE: test/history/iter-{iteration}/ , test/.snapshots/iter-{iteration}/ , test/*.iter-{iteration:02d}.*")
    print(f"VERDICT: {verdict}  → {json_out.relative_to(root)}, {Path(args.report)}, {Path(args.audit_report)}")
    if verdict != "PASS":
        return 1
    if audit["pending"]:
        print("Gate 4: guardrail-sensitive hunks need human approval (exit 3). Review them in the audit report, then re-run with --approve-guardrail-flags.")
        return 3
    dlc.mark_gate_awaiting_human(
        root,
        "gate_6_eval",
        summary=f"Stage 6 Closed-Loop Evaluation PASSED ({counts['PASS']}/{total} passed, guardrail={gstatus}). Present test/eval_report.md & audit report to user and STOP for Gate 6 approval before Stage 7 Packaging.",
        deterministic=args.deterministic,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
