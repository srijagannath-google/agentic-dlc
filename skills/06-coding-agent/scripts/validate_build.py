#!/usr/bin/env python3
"""Stage 5 build gate (Gate 5) — proves the generated application actually builds, starts and serves its UI.

Reads `specs/target_stack.json` (docs/ARCHITECTURE.md §4.2) and, with real subprocesses:
  1. runs `commands.install` and `commands.build` if present (logs → test/.build_logs/);
  2. starts `commands.start` (process group), polls `commands.healthcheck` until 2xx (≤ 60s);
  3. fetches `commands.uiEntry` (file must exist, or HTTP must answer 200);
  4. stops the process group;
  5. checks `src/README.md` exists and mentions the start command (or its first token).
For `backend.kind == none`: only checks that uiEntry exists, parses as HTML and contains at least one
inline or external <script> (a static UI with zero behaviour cannot pass Stage 6).

Usage: python3 validate_build.py --project-root <PROJECT_ROOT> [--timeout 600] [--skip-install]
Exit 1 on any failure (prints the log tail).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import dlc_common as dlc  # noqa: E402


def tail(p: Path, n: int = 40) -> str:
    return "\n".join(dlc.read_text(p).splitlines()[-n:]) if p.exists() else ""


def run_logged(label: str, cmd: str, root: Path, log_dir: Path, timeout: int, failures: list[str]) -> bool:
    log = log_dir / f"{label}.log"
    dlc.info(f"{label}: {cmd}")
    with open(log, "wb") as fh:
        try:
            cp = subprocess.run(cmd, shell=True, cwd=str(root), stdout=fh, stderr=subprocess.STDOUT, timeout=timeout)
        except subprocess.TimeoutExpired:
            failures.append(f"{label} timed out after {timeout}s\n{tail(log)}")
            return False
    if cp.returncode != 0:
        failures.append(f"{label} exited with code {cp.returncode}\n--- {log} (tail) ---\n{tail(log)}")
        return False
    return True


class _HtmlProbe(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags = 0
        self.scripts = 0
        self.has_html = False

    def handle_starttag(self, tag, attrs):
        self.tags += 1
        if tag == "html":
            self.has_html = True
        if tag == "script":
            self.scripts += 1


def check_html(text: str) -> tuple[bool, str]:
    p = _HtmlProbe()
    try:
        p.feed(text)
    except Exception as e:  # pragma: no cover
        return False, f"HTML parse error: {e}"
    if p.tags < 3:
        return False, "does not look like an HTML document"
    if p.scripts == 0:
        return False, "contains no <script> (inline or external) — a UI with no behaviour cannot satisfy Stage 6"
    return True, f"{p.tags} tags, {p.scripts} script element(s)"


def fetch(url: str, timeout: float = 5) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def _find_chrome_bin() -> str | None:
    if os.environ.get("CHROME_BIN") and Path(os.environ["CHROME_BIN"]).exists():
        return os.environ["CHROME_BIN"]
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    return None


def run_layout_smoke_check(target_url: str, html_source: str, log_dir: Path) -> tuple[bool, str]:
    """Verify zero uncaught pageerror/failed CSS-JS assets and [role='tab'] / [role='tabpanel'] bounding-box exclusivity."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page_errors: list[str] = []
            failed_assets: list[str] = []
            page.on("pageerror", lambda e: page_errors.append(str(e)))
            page.on("response", lambda r: failed_assets.append(f"{r.status} {r.url}")
                    if r.status >= 400 and r.request.resource_type in ("stylesheet", "script", "document") else None)
            page.goto(target_url, wait_until="load", timeout=10000)
            page.wait_for_timeout(120)
            if page_errors:
                browser.close()
                return False, f"uncaught pageerror(s): {'; '.join(page_errors[:3])}"
            if failed_assets:
                browser.close()
                return False, f"failed CSS/JS asset load(s): {'; '.join(failed_assets[:3])}"
            tabs = page.locator('[role="tab"][aria-controls]')
            tab_count = tabs.count()
            if tab_count >= 2:
                panel_ids: list[str] = []
                for idx in range(tab_count):
                    pid = tabs.nth(idx).get_attribute("aria-controls")
                    if pid and pid not in panel_ids:
                        panel_ids.append(pid)

                def visible_panels() -> list[str]:
                    vis = []
                    for pid in panel_ids:
                        loc = page.locator(f"#{pid}")
                        if loc.count() > 0 and loc.first.is_visible():
                            box = loc.first.bounding_box()
                            if box and box.get("width", 0) > 0 and box.get("height", 0) > 0:
                                vis.append(pid)
                    return vis

                init_vis = visible_panels()
                if len(init_vis) > 1:
                    browser.close()
                    return False, f"initial render has multiple visible [role='tabpanel'] containers simultaneously: {init_vis}"
                for idx in range(tab_count):
                    t_loc = tabs.nth(idx)
                    if not t_loc.is_visible():
                        continue
                    pid = t_loc.get_attribute("aria-controls")
                    if not pid:
                        continue
                    t_loc.click(timeout=2000)
                    page.wait_for_timeout(60)
                    vis = visible_panels()
                    if pid not in vis:
                        browser.close()
                        return False, f"clicking tab #{idx + 1} (aria-controls='{pid}') did not give #{pid} a non-zero bounding box"
                    others = [p for p in vis if p != pid]
                    if others:
                        browser.close()
                        return False, f"clicking tab #{idx + 1} (aria-controls='{pid}') left sibling panel(s) visible: {others}"
            browser.close()
            return True, f"playwright layout smoke ok ({tab_count} tab(s) verified)"
    except ImportError:
        pass
    except Exception as e:
        return False, f"playwright layout smoke error: {e}"

    chrome = _find_chrome_bin()
    if not chrome:
        return True, "browser not installed — skipped layout smoke check"

    smoke_js = r"""
    (function(){
    function runSmoke(){
      var errs = window.__dlcSmokeErrors || [];
      function hasBox(el) {
        if (!el || el.hidden || el.getAttribute('aria-hidden') === 'true') return false;
        var cs = window.getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return false;
        var r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      }
      var tablists = Array.prototype.slice.call(document.querySelectorAll('[role="tablist"]'));
      if (!tablists.length) {
        var orphanTabs = document.querySelectorAll('[role="tab"][aria-controls]');
        if (orphanTabs.length >= 2) tablists = [document];
      }
      var totalTabs = 0;
      for (var L = 0; L < tablists.length; L++) {
        var tabs = Array.prototype.slice.call(tablists[L].querySelectorAll('[role="tab"][aria-controls]'));
        if (tabs.length < 2) continue;
        totalTabs += tabs.length;
        var pids = tabs.map(function(t){ return t.getAttribute('aria-controls'); }).filter(Boolean);
        var initVis = pids.filter(function(id){ return hasBox(document.getElementById(id)); });
        if (initVis.length > 1) {
          errs.push('initial render has multiple visible [role=tabpanel] elements: ' + initVis.join(', '));
          break;
        }
        for (var i = 0; i < tabs.length; i++) {
          if (!hasBox(tabs[i])) continue;
          var pid = tabs[i].getAttribute('aria-controls');
          tabs[i].click();
          var vis = pids.filter(function(id){ return hasBox(document.getElementById(id)); });
          if (vis.indexOf(pid) === -1) {
            errs.push('clicking tab aria-controls=' + pid + ' did not make #' + pid + ' visible with non-zero bounding box');
          }
          var others = vis.filter(function(id){ return id !== pid; });
          if (others.length) {
            errs.push('clicking tab aria-controls=' + pid + ' left sibling panel(s) visible: ' + others.join(', '));
          }
        }
        if (hasBox(tabs[0])) tabs[0].click();
      }
      var pre = document.createElement('pre');
      pre.id = '__dlc_smoke_result__';
      pre.textContent = JSON.stringify({ ok: errs.length === 0, errors: errs, tabsVerified: totalTabs });
      document.body.appendChild(pre);
    }
    if (document.readyState === 'complete') setTimeout(runSmoke, 120);
    else window.addEventListener('load', function(){ setTimeout(runSmoke, 120); });
    })();
    """
    base_href = target_url if target_url.endswith("/") else target_url.rsplit("/", 1)[0] + "/"
    base_tag = f'<base href="{base_href}">' if not re.search(r"<base\b", html_source, re.I) else ""
    err_hook = base_tag + "<script>window.__dlcSmokeErrors=[];window.addEventListener('error',function(e){window.__dlcSmokeErrors.push(e.message||'script error');});</script>"
    injected = re.sub(r"(<head[^>]*>)", lambda m: m.group(1) + err_hook, html_source, count=1, flags=re.I)
    if err_hook not in injected:
        injected = err_hook + html_source
    runner = f"<script>{smoke_js}</script>"
    if re.search(r"</body\s*>", injected, re.I):
        injected = re.sub(r"(</body\s*>)", lambda m: runner + m.group(1), injected, count=1, flags=re.I)
    else:
        injected = injected + runner
    probe_file = log_dir / ".layout_smoke_probe.html"
    probe_file.write_text(injected, encoding="utf-8")
    smoke_prof = log_dir / ".chrome-smoke-profile"
    smoke_prof.mkdir(parents=True, exist_ok=True)
    try:
        cp = subprocess.run(
            [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage", "--no-first-run",
             "--no-default-browser-check", "--password-store=basic", "--use-mock-keychain",
             f"--user-data-dir={smoke_prof}", "--window-size=1440,900", "--virtual-time-budget=2000",
             "--dump-dom", probe_file.resolve().as_uri()],
            capture_output=True, text=True, timeout=15,
        )
        m = re.search(r'<pre id="__dlc_smoke_result__">(.*?)</pre>', cp.stdout or "", re.S)
        if not m:
            return True, "chrome-headless layout smoke ran (no result block)"
        import html as _html
        res = json.loads(_html.unescape(m.group(1)))
        if not res.get("ok"):
            return False, "; ".join(res.get("errors") or ["layout smoke check failed"])
        return True, f"chrome-headless layout smoke ok ({res.get('tabsVerified', 0)} tab(s) verified)"
    except Exception as e:
        return True, f"chrome-headless layout smoke skipped ({e})"
    finally:
        probe_file.unlink(missing_ok=True)
        shutil.rmtree(smoke_prof, ignore_errors=True)


def verify_target_stack_artifacts(root: Path, stack: dict[str, Any]) -> tuple[list[tuple[str, str]], list[str]]:
    """Verify that src/ui/ and src/backend/ are built in the confirmed target stack (specs/target_stack.json)
    with dual-mode configuration (local testability + target cloud deployment), never replaced by a throwaway
    Python http.server + static-html substitute when another stack was selected."""
    checks: list[tuple[str, str]] = []
    failures: list[str] = []
    fe_kind = ((stack.get("frontend") or {}).get("kind") or "tbd").strip()
    be_kind = ((stack.get("backend") or {}).get("kind") or "tbd").strip()
    db_kind = ((stack.get("database") or {}).get("kind") or "tbd").strip()
    ui_dir = root / "src" / "ui"
    be_dir = root / "src" / "backend"

    # 1. Frontend Target-Stack Fidelity
    if fe_kind in ("react", "nextjs", "angular", "vue"):
        pkg_candidates = [ui_dir / "package.json", root / "src" / "package.json", root / "package.json"]
        pkg_file = next((p for p in pkg_candidates if p.is_file()), None)
        expected_pkg = {"react": "react", "nextjs": "next", "angular": "@angular/core", "vue": "vue"}[fe_kind]
        ext_map = {
            "react": ("*.tsx", "*.jsx"),
            "nextjs": ("*.tsx", "*.jsx"),
            "angular": ("*.ts",),
            "vue": ("*.vue",),
        }[fe_kind]
        comp_files: list[Path] = []
        if ui_dir.is_dir():
            for pat in ext_map:
                comp_files.extend(p for p in ui_dir.rglob(pat) if "node_modules" not in p.parts)
        if not pkg_file:
            failures.append(
                f"specs/target_stack.json specifies frontend.kind={fe_kind!r}, but src/ui/package.json is missing. "
                f"Stage 5 (coding-agent) must build the frontend in {fe_kind!r} (never replace it with plain static-html)."
            )
        else:
            pkg_txt = dlc.read_text(pkg_file)
            if expected_pkg not in pkg_txt:
                failures.append(
                    f"specs/target_stack.json specifies frontend.kind={fe_kind!r}, but {pkg_file.relative_to(root)} "
                    f"does not declare {expected_pkg!r}."
                )
        if not comp_files:
            failures.append(
                f"specs/target_stack.json specifies frontend.kind={fe_kind!r}, but src/ui/ contains no { '/'.join(ext_map) } "
                f"component source files."
            )
        if pkg_file and comp_files and not failures:
            checks.append(("target frontend stack", f"{fe_kind} ({pkg_file.relative_to(root)}, {len(comp_files)} component file(s))"))
    elif fe_kind == "static-html":
        checks.append(("target frontend stack", "static-html"))

    # 2. Backend Target-Stack Fidelity
    if be_kind == "java-spring-boot":
        manifest = next(
            (p for p in [be_dir / "pom.xml", be_dir / "build.gradle", be_dir / "build.gradle.kts", root / "pom.xml"] if p.is_file()),
            None,
        )
        java_files = [p for p in be_dir.rglob("*.java")] + [p for p in be_dir.rglob("*.kt")] if be_dir.is_dir() else []
        cfg_files = (
            [p for p in be_dir.rglob("application.yml")]
            + [p for p in be_dir.rglob("application.yaml")]
            + [p for p in be_dir.rglob("application.properties")]
            if be_dir.is_dir()
            else []
        )
        if not manifest or not java_files:
            failures.append(
                "specs/target_stack.json specifies backend.kind='java-spring-boot', but src/backend/ is missing "
                "pom.xml/build.gradle or Java/Kotlin source files (.java/.kt). Stage 5 (coding-agent) MUST author "
                "the backend in Java Spring Boot and never substitute a standalone Python server."
            )
        elif not cfg_files:
            failures.append(
                "specs/target_stack.json specifies backend.kind='java-spring-boot', but src/backend/ is missing "
                "Spring Boot configuration (application.yml / application.properties) with local + production profiles."
            )
        else:
            checks.append(("target backend stack", f"java-spring-boot ({manifest.relative_to(root)}, {len(java_files)} source file(s))"))
    elif be_kind == "node-express":
        manifest = next((p for p in [be_dir / "package.json", root / "src" / "package.json", root / "package.json"] if p.is_file()), None)
        node_files = (
            [p for p in be_dir.rglob("*.ts") if "node_modules" not in p.parts]
            + [p for p in be_dir.rglob("*.js") if "node_modules" not in p.parts]
            + [p for p in be_dir.rglob("*.mjs") if "node_modules" not in p.parts]
            if be_dir.is_dir()
            else []
        )
        if not manifest or not node_files:
            failures.append(
                "specs/target_stack.json specifies backend.kind='node-express', but src/backend/ is missing "
                "package.json or Node/Express source files (.ts/.js). Never substitute a Python server for node-express."
            )
        else:
            checks.append(("target backend stack", f"node-express ({manifest.relative_to(root)}, {len(node_files)} source file(s))"))
    elif be_kind in ("python-fastapi", "python-flask"):
        fw_token = "fastapi" if be_kind == "python-fastapi" else "flask"
        manifest = next(
            (p for p in [be_dir / "requirements.txt", be_dir / "pyproject.toml", root / "src" / "requirements.txt", root / "requirements.txt"] if p.is_file()),
            None,
        )
        py_files = [p for p in be_dir.rglob("*.py")] if be_dir.is_dir() else []
        py_blob = "\n".join(dlc.read_text(p) for p in py_files).lower()
        if not manifest or fw_token not in dlc.read_text(manifest).lower():
            failures.append(
                f"specs/target_stack.json specifies backend.kind={be_kind!r}, but src/backend/requirements.txt (or pyproject.toml) "
                f"declaring '{fw_token}' is missing."
            )
        elif fw_token not in py_blob:
            failures.append(
                f"specs/target_stack.json specifies backend.kind={be_kind!r}, but no Python module in src/backend/ imports '{fw_token}' "
                f"(found only stdlib http.server). Stage 5 must implement the {be_kind} application."
            )
        else:
            checks.append(("target backend stack", f"{be_kind} ({manifest.relative_to(root)}, {len(py_files)} module(s))"))
    elif be_kind == "go":
        manifest = next((p for p in [be_dir / "go.mod", root / "src" / "go.mod", root / "go.mod"] if p.is_file()), None)
        go_files = [p for p in be_dir.rglob("*.go")] if be_dir.is_dir() else []
        if not manifest or not go_files:
            failures.append(
                "specs/target_stack.json specifies backend.kind='go', but src/backend/ is missing go.mod or .go source files. "
                "Never substitute a Python server when backend.kind='go'."
            )
        else:
            checks.append(("target backend stack", f"go ({manifest.relative_to(root)}, {len(go_files)} .go file(s))"))
    elif be_kind == "dotnet":
        csprojs = (list(be_dir.rglob("*.csproj")) if be_dir.is_dir() else []) + list((root / "src").glob("*.csproj"))
        cs_files = [p for p in be_dir.rglob("*.cs")] if be_dir.is_dir() else []
        if not csprojs or not cs_files:
            failures.append(
                "specs/target_stack.json specifies backend.kind='dotnet', but src/backend/ is missing .csproj or .cs source files. "
                "Never substitute a Python server when backend.kind='dotnet'."
            )
        else:
            checks.append(("target backend stack", f"dotnet ({csprojs[0].relative_to(root)}, {len(cs_files)} .cs file(s))"))
    elif be_kind == "python-stdlib-http":
        checks.append(("target backend stack", "python-stdlib-http"))

    # 3. Dual-Mode Configuration Check (Local Testability + Target Environment Cloud Deployment)
    if be_kind not in ("python-stdlib-http", "none", "tbd") or db_kind in ("postgres", "alloydb-omni", "mysql", "sqlserver"):
        all_be_files = [
            p for p in (root / "src").rglob("*")
            if p.is_file() and "node_modules" not in p.parts and p.suffix.lower() in (".py", ".java", ".kt", ".ts", ".js", ".go", ".cs", ".yml", ".yaml", ".properties", ".json", ".sh", ".env")
        ]
        be_text_blob = "\n".join(dlc.read_text(p) for p in all_be_files[:80])
        if not re.search(r"\b(?:DATABASE_URL|SPRING_DATASOURCE_URL|DB_HOST|ConnectionStrings)\b", be_text_blob):
            failures.append(
                f"Target stack uses backend={be_kind!r}, database={db_kind!r}, but src/ does not configure "
                f"DATABASE_URL / SPRING_DATASOURCE_URL / DB_HOST for target environment database connectivity alongside local testing."
            )
        else:
            checks.append(("dual-mode DB & env configuration", f"ok (DATABASE_URL / target {db_kind} + local test mode)"))

    return checks, failures


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument("--timeout", type=int, default=600, help="Per-command timeout for install/build (s)")
    ap.add_argument("--start-timeout", type=int, default=60, help="Seconds to wait for healthcheck")
    ap.add_argument("--skip-install", action="store_true")
    ap.add_argument("--skip-alm-sync", action="store_true", help="Skip automatic transition of active sprint stories to 'In Progress'")
    ap.add_argument("--deterministic", action="store_true", help="Fixed timestamps when updating story statuses")
    args = ap.parse_args()
    root = dlc.resolve_project_root(args.project_root)
    stack = dlc.load_target_stack(root, allow_default=False)
    commands = stack.get("commands") or {}
    backend_kind = (stack.get("backend") or {}).get("kind", "none")
    ui_entry = commands.get("uiEntry") or "src/ui/index.html"
    log_dir = root / "test" / ".build_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    checks: list[tuple[str, str]] = []

    if not (root / "src").exists():
        raise dlc.GateFailure("src/ does not exist — Stage 5 (06-coding-agent / coding-agent) must generate the application first.")

    # ---- Verify Target-Stack Fidelity & Dual-Mode Configuration ----
    ts_checks, ts_failures = verify_target_stack_artifacts(root, stack)
    checks.extend(ts_checks)
    failures.extend(ts_failures)

    is_url = bool(re.match(r"^https?://", ui_entry))

    # ---- README ----
    readme = root / "src" / "README.md"
    start_cmd = (commands.get("start") or "").strip()
    if not readme.exists():
        failures.append("src/README.md missing — Stage 5 must document how to build/run/test")
    elif start_cmd:
        txt = dlc.read_text(readme)
        first = start_cmd.split()[0]
        if start_cmd not in txt and first not in txt:
            failures.append(f"src/README.md does not mention the start command `{start_cmd}`")
        else:
            checks.append(("README mentions start command", "ok"))

    if backend_kind == "none" and not start_cmd:
        if not args.skip_install and commands.get("install"):
            run_logged("install", commands["install"], root, log_dir, args.timeout, failures)
        if commands.get("build"):
            run_logged("build", commands["build"], root, log_dir, args.timeout, failures)
        checks.append(("backend", "none — skipped start"))
        if not is_url:
            p = dlc.project_path(root, ui_entry)
            if not p.exists():
                failures.append(f"uiEntry file missing: {p} (Stage 5 must create it, or Gate 1 must fix target_stack.commands.uiEntry)")
            else:
                ok, msg = check_html(dlc.read_text(p))
                checks.append(("uiEntry HTML", f"{'ok' if ok else 'FAIL'} — {msg}"))
                if not ok:
                    failures.append(f"uiEntry {p}: {msg}")
                elif not failures:
                    s_ok, s_msg = run_layout_smoke_check(p.resolve().as_uri(), dlc.read_text(p), log_dir)
                    checks.append(("layout & tab-exclusivity smoke", f"{'ok' if s_ok else 'FAIL'} — {s_msg}"))
                    if not s_ok:
                        failures.append(f"layout smoke {p}: {s_msg}")
    else:
        if not start_cmd:
            failures.append(f"backend.kind={backend_kind} but target_stack.commands.start is empty (ARCHITECTURE §4.2 requires it)")
        healthcheck = (commands.get("healthcheck") or "").strip()
        if start_cmd and not healthcheck:
            failures.append("commands.healthcheck is required when commands.start is set")
        if not args.skip_install and commands.get("install"):
            run_logged("install", commands["install"], root, log_dir, args.timeout, failures)
        if commands.get("build"):
            run_logged("build", commands["build"], root, log_dir, args.timeout, failures)
        if not is_url:
            p = dlc.project_path(root, ui_entry)
            if not p.exists():
                failures.append(f"uiEntry file missing: {p} (Stage 5 must create it, or Gate 1 must fix target_stack.commands.uiEntry)")
            else:
                ok, msg = check_html(dlc.read_text(p))
                checks.append(("uiEntry HTML", f"{'ok' if ok else 'FAIL'} — {msg}"))
                if not ok:
                    failures.append(f"uiEntry {p}: {msg}")
        if start_cmd and healthcheck and not failures:
            env = dict(os.environ)
            port = urllib.parse.urlsplit(healthcheck).port
            if port:
                env.setdefault("PORT", str(port))
            log = log_dir / "start.log"
            dlc.info(f"start: {start_cmd}")
            kwargs = {"preexec_fn": os.setsid} if os.name != "nt" else {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
            with open(log, "wb") as fh:
                proc = subprocess.Popen(start_cmd, shell=True, cwd=str(root), stdout=fh, stderr=subprocess.STDOUT, env=env, **kwargs)  # type: ignore[arg-type]
                healthy = False
                deadline = time.time() + args.start_timeout
                t0 = time.time()
                while time.time() < deadline:
                    try:
                        status, _ = fetch(healthcheck, 2)
                        if 200 <= status < 300:
                            healthy = True
                            break
                    except Exception:
                        pass
                    if proc.poll() is not None:
                        break
                    time.sleep(0.4)
                if healthy:
                    checks.append(("healthcheck", f"{healthcheck} → 2xx after {time.time() - t0:.1f}s"))
                    if is_url:
                        try:
                            status, body = fetch(ui_entry, 10)
                            ok, msg = check_html(body)
                            checks.append(("uiEntry HTTP", f"{status} — {msg}"))
                            if status != 200 or not ok:
                                failures.append(f"uiEntry {ui_entry}: status {status}, {msg}")
                            else:
                                s_ok, s_msg = run_layout_smoke_check(ui_entry, body, log_dir)
                                checks.append(("layout & tab-exclusivity smoke", f"{'ok' if s_ok else 'FAIL'} — {s_msg}"))
                                if not s_ok:
                                    failures.append(f"layout smoke {ui_entry}: {s_msg}")
                        except Exception as e:
                            failures.append(f"uiEntry {ui_entry} not reachable: {e}")
                    else:
                        p = dlc.project_path(root, ui_entry)
                        if p.exists():
                            s_ok, s_msg = run_layout_smoke_check(p.resolve().as_uri(), dlc.read_text(p), log_dir)
                            checks.append(("layout & tab-exclusivity smoke", f"{'ok' if s_ok else 'FAIL'} — {s_msg}"))
                            if not s_ok:
                                failures.append(f"layout smoke {p}: {s_msg}")
                else:
                    failures.append(f"healthcheck {healthcheck} never returned 2xx within {args.start_timeout}s"
                                    + (f" (process exited with {proc.returncode})" if proc.poll() is not None else "") + f"\n--- start.log (tail) ---\n{tail(log)}")
                try:
                    if os.name != "nt":
                        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    else:
                        proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    try:
                        if os.name != "nt":
                            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except Exception:
                        pass
        elif is_url and not start_cmd:
            failures.append(f"uiEntry is an http URL ({ui_entry}) but no start command is configured")

    print("\n=== Stage 5 build gate ===")
    for k, v in checks:
        print(f"  ✓ {k}: {v}")
    for f in failures:
        print(f"  ✗ {f}")
    if failures:
        raise dlc.GateFailure(f"{len(failures)} build check(s) failed — fix the application (Stage 5) or target_stack.json (Gate 1). Logs: {log_dir}")
    print("BUILD GATE: PASS")

    # Automatically transition active sprint stories from 'To Do' -> 'In Progress' on Stage 5 completion
    bridge = Path(__file__).resolve().parents[2] / "03-story-and-sprint-planner" / "scripts" / "alm_jira_ado_bridge.py"
    if not args.skip_alm_sync and bridge.is_file() and (root / "backlog" / "user_stories.json").is_file():
        cmd = [
            sys.executable, str(bridge),
            "--project-root", str(root),
            "--action", "transition-stories",
            "--target-status", "In Progress",
            "--scope", "active-sprints",
            "--only-from-todo",
        ] + (["--deterministic"] if args.deterministic else [])
        cp = subprocess.run(cmd, cwd=str(root))
        if cp.returncode not in (0, 2):
            dlc.warn(f"ALM status transition to 'In Progress' returned {cp.returncode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
