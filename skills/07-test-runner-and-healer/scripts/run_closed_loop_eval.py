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

Usage:
  python3 run_closed_loop_eval.py --project-root <PROJECT_ROOT> [--iteration N] [--browser auto|playwright|chrome|none]
                                  [--chrome-binary PATH] [--skip-backend] [--deterministic]
Exit codes: 0 verdict PASS and guardrail status CLEAR (or approved) · 1 verdict FAIL · 3 verdict PASS but
GUARDRAIL_REVIEW_STATUS is FLAGGED_REQUIRES_HUMAN_APPROVAL (Gate 4 — re-run with --approve-guardrail-flags after review).
"""
from __future__ import annotations

import argparse
import concurrent.futures
import difflib
import html as html_mod
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
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
    "api-path": re.compile(r"(^|\s)/api/[\w/\-{}]+"),
    "long-hex-hash": re.compile(r"\b[0-9a-f]{32,}\b"),
    "raw-model-sku": re.compile(r"\b(gemini-[0-9]+\.[0-9]+-(?:flash|pro|ultra)|gpt-4[o0-9-]*|claude-3[-a-z0-9]*)\b", re.I),
}
# Default mapping of TC-UI-LEAK-NN → forbiddenUiTokens classes (a TC may override with "tokenClasses": [...]).
LEAK_CLASS_BY_INDEX = {
    1: ["schemaIdentifiers"],
    2: ["enumCodes"],
    3: ["legacyIdentifiers", "engineeringNotePatterns", "internalIds"],
    4: ["piiPatterns"],
}
LEAK_REGEX_CLASSES = {"piiPatterns", "engineeringNotePatterns"}  # these classes hold regexes, not literal tokens
LEAK_SKIP_CLASSES = {"schemaIdentifiersIgnored", "enumCodesWarnOnly"}  # never FAIL-scanned (see LEAK_WARN_CLASSES)
LEAK_WARN_CLASSES = ["enumCodesWarnOnly"]  # literal tokens reported as warnings only
DEFERRED_ACTIONS = {"expectAllControlsWired", "expectA11yBaseline", "expectNoVisibleTextMatching"}  # need every rendered state

# Guardrail-sensitive patterns for the audit report (§3). State names / triggers / rule identifiers are
# added at runtime from the spec — nothing domain-specific lives here.
GUARDRAIL_PATTERNS: dict[str, re.Pattern[str]] = {
    "role/permission check": re.compile(r"\b(role|roles|permission|permissions|allowed|allow|deny|canTransition|isInternal|isExternal|authori[sz]e[d]?|rbac|currentRole|actorRole)\b", re.I),
    "state guard": re.compile(r"\b(transition|transitions|guard|guards|fromState|toState|currentState|nextState|allowedFrom|prerequisite)\b", re.I),
    "masking / PII": re.compile(r"\b(mask|masked|masking|redact|redacted|pii|sensitive)\b", re.I),
    "accessibility": re.compile(r"(aria-[\w-]+|\brole=|<label\b|\btabindex\b|\balt=|\blang=|\bfor=)", re.I),
    "leakage label mapping": re.compile(r"(label\s*map|_LABELS\b|labelFor|toLabel|displayName|statusLabel|humanLabel|enumLabel|LABELS\s*[=:])", re.I),
}


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
    are safely archived under test/history/iter-M/, test/.snapshots/iter-M/, and test/*.iter-MM.*
    so prior run results and remediation records are never overwritten or lost.
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
    if not snap_dir.exists():
        snapshot_src(root, prev_it)
    else:
        snap_dir.mkdir(parents=True, exist_ok=True)
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
        for target_p in (hist_dir / base_name, snap_dir / base_name, root / "test" / numbered_name):
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


def snapshot_src(root: Path, iteration: int) -> Path:
    dest = root / "test" / ".snapshots" / f"iter-{iteration}"
    src = root / "src"
    if src.exists():
        shutil.copytree(src, dest, ignore=SNAPSHOT_IGNORE, dirs_exist_ok=True)
    else:
        dest.mkdir(parents=True, exist_ok=True)
    return dest


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
        self.log_dir = log_dir
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
        if self.healthcheck and self._healthy(timeout=1):
            # Reap any stale backend process left over from a previous /tmp/dlc-* run before checking again.
            my_pids = {os.getpid(), os.getppid()}
            for proc_dir in Path("/proc").glob("[0-9]*"):
                try:
                    pid = int(proc_dir.name)
                    if pid in my_pids:
                        continue
                    cwd = os.readlink(proc_dir / "cwd") if (proc_dir / "cwd").exists() else ""
                    if cwd.startswith("/tmp/dlc-"):
                        os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass
            time.sleep(0.3)
        if self.healthcheck and self._healthy(timeout=1):
            dlc.warn(f"{self.healthcheck} already answers BEFORE the start command ran — a stale server (previous run?) owns the port; "
                     "the new process would fail to bind and results would come from stale code. Stop it first or pass --skip-backend.")
            self.error = "port already in use by a process this run did not start"
            return self
        log = open(self.log_dir / "backend.log", "wb")
        env = dict(os.environ)
        if self.healthcheck:
            port = urllib.parse.urlsplit(self.healthcheck).port
            if port:
                env.setdefault("PORT", str(port))
        dlc.info(f"starting backend: {self.start_cmd}")
        kwargs: dict[str, Any] = {}
        if os.name != "nt":
            kwargs["preexec_fn"] = os.setsid
        else:
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        self.proc = subprocess.Popen(self.start_cmd, shell=True, cwd=str(self.root), stdout=log, stderr=subprocess.STDOUT, env=env, **kwargs)
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
        try:
            if os.name != "nt":
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            else:
                self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name != "nt":
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                else:
                    self.proc.kill()
        except ProcessLookupError:
            pass
        except Exception as e:  # pragma: no cover
            dlc.warn(f"could not stop backend cleanly: {e}")

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

    def base_href(self) -> str:
        if self.is_url:
            return self.raw if self.raw.endswith("/") else self.raw.rsplit("/", 1)[0] + "/"
        assert self.path is not None
        return self.path.parent.resolve().as_uri() + "/"


# ======================================================================================
# Browser adapters
# ======================================================================================
class ChromeAdapter:
    name = "chrome-headless"

    def __init__(self, binary: str, ui: UiEntry, tmp: Path, timeout_s: int = 60):
        self.binary = binary
        self.ui = ui
        self.tmp = tmp
        self.timeout_s = timeout_s
        self.driver = dlc.read_text(DRIVER_JS)
        self.profile = tmp / "chrome-profile"
        self.profile.mkdir(parents=True, exist_ok=True)

    def build_harness(self, app_html: str, steps: list[dict[str, Any]], settle_ms: int) -> str:
        prelude = f"<script data-dlc=\"prelude\">\n{self.driver}\nwindow.__dlcInstallPrelude();\n</script>"
        base = f'<base href="{html_mod.escape(self.ui.base_href())}">' if not re.search(r"<base\b", app_html, re.I) else ""
        head_inject = base + prelude
        if re.search(r"<head[^>]*>", app_html, re.I):
            doc = re.sub(r"(<head[^>]*>)", lambda m: m.group(1) + head_inject, app_html, count=1, flags=re.I)
        elif re.search(r"<html[^>]*>", app_html, re.I):
            doc = re.sub(r"(<html[^>]*>)", lambda m: m.group(1) + "<head>" + head_inject + "</head>", app_html, count=1, flags=re.I)
        else:
            doc = head_inject + app_html
        steps_json = json.dumps(steps).replace("</", "<\\/")
        runner = f"""<script data-dlc="runner">
(function(){{
  function emit(obj){{
    var s=document.createElement('script'); s.type='application/json'; s.id='__dlc_results';
    s.textContent=JSON.stringify(obj).replace(/</g,'\\\\u003c'); document.documentElement.appendChild(s);
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

    def run(self, tc: dict[str, Any], app_html: str) -> dict[str, Any]:
        steps = tc.get("steps") or []
        settle = int(tc.get("settleMs", 150))
        wait_total = sum(int(s.get("ms", 0)) for s in steps if s.get("action") == "wait")
        budget = min(60000, 4000 + settle + wait_total + 400 * len(steps))
        harness = self.build_harness(app_html, steps, settle)
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", tc.get("id", "tc"))
        hp = self.tmp / f"harness-{safe_id}.html"
        hp.write_text(harness, encoding="utf-8")
        prof = self.tmp / f"prof-{safe_id}"
        prof.mkdir(parents=True, exist_ok=True)
        cmd = [self.binary, "--headless=new", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage", "--hide-scrollbars",
               "--disable-web-security", "--allow-file-access-from-files", "--disable-extensions", "--no-first-run",
               "--no-default-browser-check", "--password-store=basic", "--use-mock-keychain",
               f"--user-data-dir={prof}", f"--virtual-time-budget={budget}", "--run-all-compositor-stages-before-draw",
               "--dump-dom", hp.resolve().as_uri()]
        t0 = now_ms()
        try:
            cp = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout_s)
        except subprocess.TimeoutExpired:
            shutil.rmtree(prof, ignore_errors=True)
            return {"status": "ERROR", "message": f"chrome timed out after {self.timeout_s}s", "actual": "", "durationMs": now_ms() - t0}
        except OSError as e:
            shutil.rmtree(prof, ignore_errors=True)
            return {"status": "ERROR", "message": f"could not launch chrome: {e}", "actual": "", "durationMs": now_ms() - t0}
        shutil.rmtree(prof, ignore_errors=True)
        m = re.search(r'<script type="application/json" id="__dlc_results">(.*?)</script>', cp.stdout, re.S)
        if not m:
            tail = (cp.stderr or "").strip().splitlines()[-5:]
            return {"status": "ERROR", "message": "harness produced no results (page JS may have thrown before load, or chrome failed)",
                    "actual": " | ".join(tail)[:500], "durationMs": now_ms() - t0}
        try:
            res = json.loads(html_mod.unescape(m.group(1)))
        except json.JSONDecodeError as e:
            return {"status": "ERROR", "message": f"could not parse harness results: {e}", "actual": m.group(1)[:300], "durationMs": now_ms() - t0}
        res["durationMs"] = now_ms() - t0
        if res.get("status") in ("FAIL", "ERROR") and getattr(self, "screenshot_dir", None):
            shot_path = self.screenshot_dir / f"fail-{safe_id}.png"
            if self._take_screenshot(hp.resolve().as_uri(), shot_path, budget):
                res["screenshot"] = str(shot_path)
        return res

    def _take_screenshot(self, uri: str, out_png: Path, budget: int = 800) -> bool:
        out_png.parent.mkdir(parents=True, exist_ok=True)
        prof = self.tmp / f"prof-shot-{out_png.stem}"
        prof.mkdir(parents=True, exist_ok=True)
        cmd = [self.binary, "--headless=new", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage", "--hide-scrollbars",
               "--disable-web-security", "--allow-file-access-from-files", "--disable-extensions", "--no-first-run",
               "--no-default-browser-check", "--password-store=basic", "--use-mock-keychain",
               f"--user-data-dir={prof}", "--window-size=1440,900", f"--virtual-time-budget={min(budget, 1200)}",
               f"--screenshot={out_png}", uri]
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=6)
            return out_png.exists() and out_png.stat().st_size > 0
        except Exception:
            return False
        finally:
            shutil.rmtree(prof, ignore_errors=True)

    def capture_visual_evidence(self, app_html: str, screenshot_dir: Path, root: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        """Capture initial landing screenshot + per-tab screenshots and verify tab-switch layout changes."""
        self.screenshot_dir = screenshot_dir
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        shots: list[dict[str, str]] = []
        unwired_tabs: list[dict[str, str]] = []
        # 1. Initial landing view
        init_harness = self.build_harness(app_html, [{"action": "goto", "target": "ui"}], 150)
        hp_init = self.tmp / "shot-landing.html"
        hp_init.write_text(init_harness, encoding="utf-8")
        init_png = screenshot_dir / "landing-initial.png"
        if self._take_screenshot(hp_init.resolve().as_uri(), init_png):
            rel = str(init_png.relative_to(root)) if init_png.is_relative_to(root) else str(init_png)
            shots.append({"label": "Initial landing view (1440x900)", "path": rel, "kind": "landing"})
        # 2. Discover top-level [role="tab"] selectors from HTML source and capture each tab view
        tab_matches = re.findall(r'<[^>]*\brole\s*=\s*["\']tab["\'][^>]*>', app_html, re.I)
        for idx, tag_html in enumerate(tab_matches[:8]):
            m_tid = re.search(r'\bdata-testid\s*=\s*["\']([^"\']+)["\']', tag_html, re.I)
            m_id = re.search(r'\bid\s*=\s*["\']([^"\']+)["\']', tag_html, re.I)
            m_ctrl = re.search(r'\baria-controls\s*=\s*["\']([^"\']+)["\']', tag_html, re.I)
            sel = f"[data-testid={m_tid.group(1)}]" if m_tid else (f"#{m_id.group(1)}" if m_id else None)
            if not sel:
                continue
            slug = re.sub(r"[^a-z0-9]+", "-", (m_tid.group(1) if m_tid else m_id.group(1)).lower()).strip("-")
            tab_harness = self.build_harness(app_html, [{"action": "goto", "target": "ui"}, {"action": "click", "selector": sel}], 150)
            hp_tab = self.tmp / f"shot-tab-{idx + 1:02d}.html"
            hp_tab.write_text(tab_harness, encoding="utf-8")
            tab_png = screenshot_dir / f"tab-{idx + 1:02d}-{slug}.png"
            if self._take_screenshot(hp_tab.resolve().as_uri(), tab_png):
                rel = str(tab_png.relative_to(root)) if tab_png.is_relative_to(root) else str(tab_png)
                shots.append({"label": f"Tab {idx + 1}: {sel}" + (f" -> #{m_ctrl.group(1)}" if m_ctrl else ""), "path": rel, "kind": "tab"})
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
    for i, step in enumerate(tc.get("steps") or []):
        action = step.get("action")
        if action == "expectNoVisibleTextMatching":
            try:
                rx = re.compile(step.get("pattern", ""), re.M)
            except re.error as e:
                return {"status": "ERROR", "failedStep": i, "message": f"Step {i}: invalid regex /{step.get('pattern')}/: {e}", "actual": "", "durationMs": now_ms() - t0}
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
    cats: list[str] = []
    changed = [ln[1:] for ln in hunk if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))]
    for name, rx in pats.items():
        if any(rx.search(ln) for ln in changed):
            cats.append(name)
    return cats


def compute_snapshot_file_changes(snaps_dir: Path, from_it: int, to_it: int) -> tuple[list[str], list[tuple[str, str, list[list[str]]]]]:
    """Return (changed_rel_paths, [(rel, tag, hunks)]) between iter-{from_it} and iter-{to_it}."""
    prev_d = snaps_dir / f"iter-{from_it}"
    cur_d = snaps_dir / f"iter-{to_it}"
    if from_it < 1 or not prev_d.exists() or not cur_d.exists():
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
        diff = list(difflib.unified_diff(a, b, fromfile=f"iter-{from_it}/{rel}", tofile=f"iter-{to_it}/{rel}", lineterm="", n=2))
        hunks = split_hunks(diff)
        changed_paths.append(rel)
        detailed.append((rel, tag, hunks))
    return changed_paths, detailed


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
        changed_files, detailed_diffs = compute_snapshot_file_changes(snaps, it - 1, it) if it > 1 else ([], [])
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


def write_audit_report(root: Path, iteration: int, results: list[dict[str, Any]], out_path: Path, spec_md: str, deterministic: bool) -> str:
    snaps = root / "test" / ".snapshots"
    cur_dir = snaps / f"iter-{iteration}"
    prev_dir = snaps / f"iter-{iteration - 1}"
    now_ts = dlc.utc_now_iso(deterministic)
    history_rows = build_cumulative_history_rows(root, iteration, results, now_ts)
    lines = [
        f"# Remediation & Guardrail Audit Report — Iteration {iteration}",
        "",
        f"Generated: {now_ts}  ",
        f"Project: `{root.name}`  ",
        f"Compared: `test/.snapshots/iter-{iteration - 1}` → `test/.snapshots/iter-{iteration}`  ",
        f"Preserved Per-Run Archive: `test/history/iter-{iteration}/` · `test/*.iter-{iteration:02d}.*`",
        "",
        "## 0. Cumulative Run & Remediation History (All Iterations)",
        "",
        "> Every evaluation run and remediation iteration is permanently archived under `test/history/iter-<N>/`, `test/.snapshots/iter-<N>/`, and `test/*.iter-<NN>.*` so earlier failure runs and remediation diffs are never overwritten.",
        "",
        "| Iter | Timestamp (UTC) | Verdict | PASS / Total | FAIL | NOT_RUN | ERROR | Failed Test IDs | Remediated Test IDs | Modified Files (`src/`) | Preserved Run Artifacts |",
        "| --: | :-- | :-- | --: | --: | --: | --: | :-- | :-- | :-- | :-- |",
    ]
    for hr in history_rows:
        it_num = hr["iteration"]
        f_str = ", ".join(f"`{t}`" for t in hr["failedIds"][:8]) + (f" (+{len(hr['failedIds']) - 8} more)" if len(hr["failedIds"]) > 8 else "") if hr["failedIds"] else "—"
        r_str = ", ".join(f"`{t}`" for t in hr["remediatedIds"][:8]) + (f" (+{len(hr['remediatedIds']) - 8} more)" if len(hr["remediatedIds"]) > 8 else "") if hr["remediatedIds"] else "—"
        m_str = ", ".join(f"`{f}`" for f in hr["changedFiles"][:5]) + (f" (+{len(hr['changedFiles']) - 5} more)" if len(hr["changedFiles"]) > 5 else "") if hr["changedFiles"] else ("initial snapshot" if it_num == 1 else "—")
        art_str = f"`{hr['historyDir']}/` · `{hr['evalReportFile']}` · `{hr['auditReportFile']}`"
        lines.append(
            f"| **{it_num}** | `{hr['evaluatedAtUtc']}` | **{hr['verdict']}** | {hr['pass']}/{hr['total']} | {hr['fail']} | {hr['notRun']} | {hr['error']} | {f_str} | {r_str} | {m_str} | {art_str} |"
        )
    lines.append("")

    status = "CLEAR"
    # §1 what failed
    lines += ["## 1. What failed", ""]
    prev_doc = load_iteration_eval(root, iteration - 1) if iteration > 1 else None
    prev_fail: dict[str, dict[str, Any]] = {}
    if isinstance(prev_doc, dict):
        prev_fail = {r["id"]: r for r in (prev_doc.get("results") or []) if isinstance(r, dict) and r.get("id") and r.get("status") in ("FAIL", "ERROR", "NOT_RUN")}
    cur_fail = {r["id"]: r for r in results if r.get("status") in ("FAIL", "ERROR", "NOT_RUN")}
    if iteration == 1 or not prev_dir.exists():
        lines += [f"This is iteration {iteration} and no previous snapshot exists — there is no prior failure set to compare against.", ""]
    else:
        lines += [f"Previous iteration ({iteration - 1}) had **{len(prev_fail)}** non-passing test(s); this iteration has **{len(cur_fail)}**.", ""]
        if prev_fail or cur_fail:
            lines += ["| Test ID | Previous status | Current status | Current message |", "| :-- | :-- | :-- | :-- |"]
            for tid in sorted(set(prev_fail) | set(cur_fail)):
                p = prev_fail.get(tid, {}).get("status", "PASS")
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
    pats = build_guardrail_patterns(spec_md)
    if iteration == 1 or not prev_dir.exists():
        lines += ["Iteration 1 — nothing to diff against. All files under `src/` are new in this iteration:", ""]
        for rel in sorted(list_files(cur_dir)):
            lines.append(f"- `{rel}` (new)")
        lines.append("")
    else:
        _, detailed_changes = compute_snapshot_file_changes(snaps, iteration - 1, iteration)
        total_hunks = 0
        for rel, tag, hunks in detailed_changes:
            if tag == "binary-modified":
                lines += [f"### `{rel}` — binary file changed (not diffed; data files are not guardrail-classified)", ""]
                continue
            lines += [f"### `{rel}` — {tag}, {len(hunks)} hunk(s)", ""]
            for hi, h in enumerate(hunks, 1):
                total_hunks += 1
                cats = [] if Path(rel).suffix.lower() in DOC_SUFFIXES else classify_hunk(h, pats)
                if cats:
                    flagged.append({"file": rel, "hunk": hi, "header": h[0] if h else "", "categories": cats,
                                    "changed": [ln for ln in h if ln.startswith(("+", "-"))][:6]})
                shown = h if len(h) <= 60 else h[:60] + [f"… ({len(h) - 60} more lines truncated)"]
                lines += [f"<details><summary>Hunk {hi}{' — ⚠ ' + ', '.join(cats) if cats else ''}</summary>", "", "```diff", *shown, "```", "</details>", ""]
        if total_hunks == 0:
            lines += ["No file under `src/` changed between the two iterations.", ""]
    # §3 guardrail classification
    lines += ["## 3. Automated guardrail & guideline compliance check", ""]
    if flagged:
        status = "FLAGGED_REQUIRES_HUMAN_APPROVAL"
        lines += [f"**{len(flagged)}** hunk(s) touch guardrail-sensitive regions and need explicit human approval before the iteration is accepted:", "",
                  "| File | Hunk | Guardrail region(s) | Changed lines (first 6) |", "| :-- | :-- | :-- | :-- |"]
        for f in flagged:
            ch = "<br>".join(html_mod.escape(x, quote=False)[:110] for x in f["changed"])
            lines.append(f"| `{f['file']}` | {f['hunk']} `{f['header'][:30]}` | {', '.join(f['categories'])} | {ch} |")
        lines += ["", "Review each hunk: confirm it does not relax a role check, a workflow prerequisite, a business-rule formula, PII masking, an accessibility attribute or an enum→label mapping. Record the decision in this file.", ""]
    else:
        lines += ["No modified hunk matched a guardrail-sensitive pattern (role/permission checks, state guards, spec §3.3 state names/triggers, spec §3.4 rule identifiers, masking/PII, accessibility attributes, label mappings).", ""]
    lines += [f"`GUARDRAIL_REVIEW_STATUS: {status}`", ""]

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
    return status


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
        lines += ["> NOT_RUN never counts as a pass. The verdict is PASS only when zero FAIL/ERROR/NOT_RUN remain among non-optional tests.", ""]
    lines += [
        "## Run History & Preserved Per-Iteration Artifacts",
        "",
        "| Iter | Timestamp (UTC) | Verdict | PASS / Total | FAIL | NOT_RUN | ERROR | Failed Tests | Remediated Tests | Preserved Files |",
        "| --: | :-- | :-- | --: | --: | --: | --: | :-- | :-- | :-- |",
    ]
    for hr in history_rows:
        f_str = ", ".join(f"`{t}`" for t in hr["failedIds"][:6]) + (f" (+{len(hr['failedIds']) - 6})" if len(hr["failedIds"]) > 6 else "") if hr["failedIds"] else "—"
        r_str = ", ".join(f"`{t}`" for t in hr["remediatedIds"][:6]) + (f" (+{len(hr['remediatedIds']) - 6})" if len(hr["remediatedIds"]) > 6 else "") if hr["remediatedIds"] else "—"
        lines.append(
            f"| **{hr['iteration']}** | `{hr['evaluatedAtUtc']}` | **{hr['verdict']}** | {hr['pass']}/{hr['total']} | "
            f"{hr['fail']} | {hr['notRun']} | {hr['error']} | {f_str} | {r_str} | "
            f"`{hr['historyDir']}/` · `{hr['evalReportFile']}` · `{hr['auditReportFile']}` |"
        )
    lines.append("")
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
        it_k = hr["iteration"]
        index_entries.append({
            "iteration": it_k,
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
                "snapshotDir": hr["snapshotDir"],
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
        "| Iter | Timestamp (UTC) | Verdict | PASS / Total | FAIL | NOT_RUN | ERROR | Failed Test IDs | Remediated Test IDs | Modified Files (`src/`) | Preserved Run Results & Remediation Files |",
        "| --: | :-- | :-- | --: | --: | --: | --: | :-- | :-- | :-- | :-- |",
    ]
    for e in index_entries:
        f_str = ", ".join(f"`{t}`" for t in e["failedTestIds"][:8]) if e["failedTestIds"] else "—"
        r_str = ", ".join(f"`{t}`" for t in e["remediatedTestIds"][:8]) if e["remediatedTestIds"] else "—"
        m_str = ", ".join(f"`{f}`" for f in e["modifiedSourceFiles"][:5]) if e["modifiedSourceFiles"] else ("initial snapshot" if e["iteration"] == 1 else "—")
        art = e["artifacts"]
        md_lines.append(
            f"| **{e['iteration']}** | `{e['evaluatedAtUtc']}` | **{e['verdict']}** | {e['pass']}/{e['total']} | "
            f"{e['fail']} | {e['notRun']} | {e['error']} | {f_str} | {r_str} | {m_str} | "
            f"`{art['evalResultsJson']}` · `{art['evalReportMd']}` · `{art['remediationAuditReportMd']}` |"
        )
    md_lines.append("")
    dlc.write_text(hist_root / "README.md", "\n".join(md_lines))
    return saved


# ======================================================================================
# Main
# ======================================================================================
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument("--iteration", type=int, default=None, help="Iteration number (default: next under test/.snapshots)")
    ap.add_argument("--test-cases", default="test/test_cases.json")
    ap.add_argument("--browser", choices=["auto", "playwright", "chrome", "none"], default="auto")
    ap.add_argument("--chrome-binary", default=None)
    ap.add_argument("--skip-backend", action="store_true", help="Do not start commands.start (assume it is running or not needed)")
    ap.add_argument("--deterministic", action="store_true", help="Stable timestamps for golden comparisons")
    ap.add_argument("--json-out", default="test/eval_results.json")
    ap.add_argument("--report", default="test/eval_report.md")
    ap.add_argument("--audit-report", default="test/remediation_and_guardrail_audit_report.md")
    ap.add_argument("--chrome-timeout", type=int, default=60)
    ap.add_argument("--approve-guardrail-flags", action="store_true", help="Human has reviewed flagged hunks; record approval instead of exiting 3")
    ap.add_argument("--skip-alm-sync", action="store_true", help="Skip automatic synchronization of user story statuses from evaluation results")
    args = ap.parse_args()

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

    iteration = resolve_iteration(root, args.iteration)
    snap_dir = snapshot_src(root, iteration)
    dlc.info(f"iteration {iteration}: snapshot of src/ → {snap_dir.relative_to(root)}")

    stack = dlc.load_target_stack(root)
    commands = stack.get("commands") or {}
    backend_kind = (stack.get("backend") or {}).get("kind", "none")
    ui = UiEntry(root, commands.get("uiEntry") or "src/ui/index.html")
    spec_md = dlc.read_text(root / "specs" / "application_spec.md") if (root / "specs" / "application_spec.md").exists() else ""
    if not spec_md:
        dlc.warn("specs/application_spec.md missing — audit report cannot use spec state names / rule identifiers")

    results: list[dict[str, Any]] = []
    texts_for_leak: dict[str, str] = {}
    controls_acc: dict[str, dict[str, Any]] = {}
    a11y_acc: dict[str, dict[str, str]] = {}
    ux_acc: dict[str, Any] = {}
    browser_name = "none"
    browser_binary = ""
    backend_started = False
    backend_error = ""
    browser_states_reached = 0

    tmp = Path(tempfile.mkdtemp(prefix="dlc-eval-"))
    adapter = None
    try:
        with Backend(root, commands, args.skip_backend or backend_kind == "none", root / "test" / ".build_logs") as be:
            backend_started, backend_error = be.started, be.error
            ui_source = ui.source()
            if ui_source:
                texts_for_leak["static:uiEntry source"] = dlc.html_visible_text(ui_source)
                for f in a11y_lint(ui_source):
                    a11y_acc.setdefault(f"{f['rule']}|{f['message']}", f)
            browser_tcs = [t for t in test_cases if t.get("runtime") == "browser"]
            screenshots: list[dict[str, str]] = []
            unwired_from_probe: list[dict[str, str]] = []
            if browser_tcs and args.browser != "none":
                adapter, browser_name = pick_browser(args.browser, args.chrome_binary, ui, tmp)
                if adapter is not None:
                    adapter_timeout = getattr(adapter, "timeout_s", None)
                    if adapter_timeout is not None:
                        adapter.timeout_s = args.chrome_timeout
                    browser_binary = getattr(adapter, "binary", "")
                    dlc.info(f"browser adapter: {browser_name} {browser_binary}")
                    if ui_source and hasattr(adapter, "capture_visual_evidence"):
                        screenshots, unwired_from_probe = adapter.capture_visual_evidence(
                            ui_source, snap_dir / "screenshots", root
                        )
                else:
                    dlc.warn(BROWSER_INSTALL_HINT)

            special = re.compile(r"^TC-(UI-LEAK|UI-INTERACT|A11Y|UX-SIMPLE)-\d+$")
            deferred: list[dict[str, Any]] = []
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
                    results.append({**base, "status": "NOT_RUN", "durationMs": 0, "failedStep": None, "message": "steps not authored yet (Stage 4B testing-agent must fill `steps`)", "actual": ""})
                    continue
                if runtime == "browser":
                    if adapter is None:
                        results.append({**base, "status": "NOT_RUN", "durationMs": 0, "failedStep": None, "message": BROWSER_INSTALL_HINT if args.browser != "none" else "browser runtime disabled (--browser none)", "actual": ""})
                        continue
                    if not ui_source:
                        results.append({**base, "status": "ERROR", "durationMs": 0, "failedStep": None, "message": ui.error or "UI entry unavailable", "actual": ""})
                        continue
                    res = adapter.run(tc, ui_source)
                    browser_states_reached += 1
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
            unwired = [{"selector": c["selector"], "text": c.get("text", ""), "reason": c["reason"], "seenIn": c.get("seenIn", "")} for c in controls_acc.values() if not c.get("hasHandler")]
            for u_tab in unwired_from_probe:
                if not any(u["selector"] == u_tab["selector"] for u in unwired):
                    unwired.append({**u_tab, "seenIn": "interactivityProbe"})
            a11y_findings = list(a11y_acc.values())
            no_browser_note = "" if browser_states_reached else " (no browser state reached — static source only)"
            static_ctx = {"browserStatesReached": browser_states_reached, "unwired": unwired, "a11yFindings": a11y_findings}
            for tc in deferred:
                tid = tc["id"]
                base = {"id": tid, "category": tc.get("category", ""), "title": tc.get("title", ""), "expected": tc.get("expected", ""),
                        "runtime": "static", "optional": bool(tc.get("optional", False)), "durationMs": 0, "failedStep": None,
                        "storyRef": tc.get("storyRef"), "acRef": tc.get("acRef"), "corpora": sorted(texts_for_leak)}
                if tc.get("steps"):
                    if not ui_source:
                        results.append({**base, "status": "ERROR", "message": ui.error or "UI entry unavailable", "actual": ""})
                    else:
                        results.append({**base, **run_static_steps(tc, ui_source, texts_for_leak, static_ctx)})
                    continue
                m = re.match(r"^TC-UI-LEAK-(\d+)$", tid)
                if m:
                    classes = tc.get("tokenClasses") or LEAK_CLASS_BY_INDEX.get(int(m.group(1)), [])
                    my_hits = [h for h in hits if h["tokenClass"] in classes]
                    n_tokens = sum(len(forbidden.get(c) or []) for c in classes)
                    if not classes or n_tokens == 0:
                        st, msg = "PASS", f"no tokens declared for classes {classes or '(none mapped)'} in forbiddenUiTokens — nothing to leak{no_browser_note}"
                        if tc.get("requireTokens"):
                            st, msg = "NOT_RUN", f"forbiddenUiTokens has no entries for {classes}; Stage 4B must derive them"
                    elif my_hits:
                        uniq = sorted({h["token"] for h in my_hits})
                        st, msg = "FAIL", f"{len(uniq)} forbidden token(s) visible in {len({h['source'] for h in my_hits})} source(s): " + ", ".join(uniq[:8])
                    else:
                        st, msg = "PASS", f"{n_tokens} token(s) of {', '.join(classes)} absent from all rendered visible text{no_browser_note}"
                    results.append({**base, "status": st, "message": msg, "actual": "; ".join(h["context"][:100] for h in my_hits[:3])})
                elif tid.startswith("TC-UI-INTERACT"):
                    if not browser_states_reached:
                        results.append({**base, "status": "NOT_RUN", "message": "requires a browser runtime to observe listeners; " + BROWSER_INSTALL_HINT, "actual": ""})
                    elif unwired:
                        results.append({**base, "status": "FAIL", "message": f"{len(unwired)} control(s) without any handler: " + ", ".join(u['selector'] for u in unwired[:6]), "actual": "; ".join(f"{u['selector']} ({u['text']})" for u in unwired[:6])})
                    else:
                        results.append({**base, "status": "PASS", "message": f"all {len(controls_acc)} observed controls are wired", "actual": ""})
                elif tid.startswith("TC-A11Y"):
                    if a11y_findings:
                        results.append({**base, "status": "FAIL", "message": f"{len(a11y_findings)} accessibility finding(s): " + "; ".join(f"{f['rule']}" for f in a11y_findings[:5]), "actual": "; ".join(f["message"] for f in a11y_findings[:4])})
                    else:
                        results.append({**base, "status": "PASS", "message": f"labels, alt text, single h1, lang, tabindex and accessible names verified{no_browser_note}", "actual": ""})
                elif tid.startswith("TC-UX-SIMPLE"):
                    n = int(re.search(r"(\d+)$", tid).group(1))
                    if not ux_acc:
                        results.append({**base, "status": "NOT_RUN", "optional": True, "message": "UX guardrail metrics require a browser runtime (reported as WARN-equivalent; marked optional)", "actual": ""})
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
    verdict = "PASS" if active_total and not non_opt_bad else "FAIL"
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
    audit_out = dlc.project_path(root, args.audit_report)
    gstatus = write_audit_report(root, iteration, results, audit_out, spec_md, args.deterministic)
    if gstatus != "CLEAR" and args.approve_guardrail_flags:
        dlc.write_text(audit_out, dlc.read_text(audit_out) + "\n`GUARDRAIL_HUMAN_DECISION: APPROVED_BY_USER` (recorded via --approve-guardrail-flags)\n")
    data["guardrailReviewStatus"] = ("NOT_REQUIRED" if gstatus == "CLEAR" else ("APPROVED_BY_USER" if args.approve_guardrail_flags else gstatus))
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
    bridge = Path(__file__).resolve().parents[2] / "03-story-and-sprint-planner" / "scripts" / "alm_jira_ado_bridge.py"
    if not args.skip_alm_sync and bridge.is_file() and (root / "backlog" / "user_stories.json").is_file():
        cmd = [
            sys.executable, str(bridge),
            "--project-root", str(root),
            "--action", "sync-status-from-eval",
        ] + (["--deterministic"] if args.deterministic else [])
        cp = subprocess.run(cmd, cwd=str(root))
        if cp.returncode not in (0, 2):
            dlc.warn(f"ALM status synchronization from evaluation returned {cp.returncode}")
        archive_iteration_artifacts(root, iteration, json_out, report_out, audit_out, data, args.deterministic)

    print("\n=== Stage 6 closed-loop evaluation — iteration", iteration, "===")
    print(f"browser={browser_name} backendStarted={backend_started} statesReached={browser_states_reached}")
    print(f"total={total} pass={counts['PASS']} fail={counts['FAIL']} notRun={counts['NOT_RUN']} error={counts['ERROR']} "
          f"leakHits={len(hits)} unwired={len(unwired)} a11yFindings={len(a11y_findings)}")
    for r in results:
        if r["status"] != "PASS":
            print(f"  - {r['id']:<20} {r['status']:<8} step={r.get('failedStep')} {r.get('message', '')[:110]}")
    print(f"GUARDRAIL_REVIEW_STATUS: {gstatus}")
    print(f"PRESERVED_RUN_ARCHIVE: test/history/iter-{iteration}/ , test/.snapshots/iter-{iteration}/ , test/*.iter-{iteration:02d}.*")
    print(f"VERDICT: {verdict}  → {json_out.relative_to(root)}, {Path(args.report)}, {Path(args.audit_report)}")
    if verdict != "PASS":
        return 1
    if gstatus != "CLEAR" and not args.approve_guardrail_flags:
        print("Gate 4: guardrail-sensitive hunks need human approval (exit 3). Re-run with --approve-guardrail-flags once reviewed.")
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
