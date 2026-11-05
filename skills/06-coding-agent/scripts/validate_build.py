#!/usr/bin/env python3
"""Stage 5 build gate (Gate 5) — proves the generated application actually builds, starts and serves its UI.

Reads `specs/target_stack.json` (docs/ARCHITECTURE.md §4.2) and, with real subprocesses:
  1. runs `commands.install` and `commands.build` if present (logs → test/.build_logs/);
  2. refuses to start when `commands.healthcheck` already answers (a stale server owns the port — results would come
     from stale code), after reaping only the process group a previous run recorded in test/.build_logs/backend.pid;
  3. starts `commands.start` (own process group, pgid written to the pidfile), polls `commands.healthcheck` until 2xx (≤ 60s);
  4. fetches `commands.uiEntry` (file must exist, or HTTP must answer 200) and runs a tri-state layout smoke check
     (ok / FAIL / SKIPPED-with-reason — never a silent pass) through Playwright or headless Chrome served over http://127.0.0.1;
  5. runs `commands.test` if present (bounded timeout, non-zero exit → FAIL);
  6. stops the process group;
  7. checks `src/README.md` exists and literally mentions the start command, the run script or the healthcheck URL;
  8. for every backend kind other than python-stdlib-http / none: requires 12-factor dual-mode handling of
     `APP_ENV`, `AUTH_MODE` and a database URL token in src/backend/** or src/run.sh.
For `backend.kind == none`: only checks that uiEntry exists, parses as HTML and contains at least one
inline or external <script> (a static UI with zero behaviour cannot pass Stage 6).

Usage: python3 validate_build.py --project-root <PROJECT_ROOT> [--timeout 600] [--skip-install] [--skip-test] [--alm-sync]
Exit 1 on any failure (prints the log tail).
"""
from __future__ import annotations

import argparse
import base64
import http.server
import json
import os
import re
import shutil
import signal
import subprocess
import sys
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

BACKEND_PIDFILE = "test/.build_logs/backend.pid"  # shared with 07/scripts/run_closed_loop_eval.py so each reaps the other's leftovers


def tail(p: Path, n: int = 40) -> str:
    return "\n".join(dlc.read_text(p).splitlines()[-n:]) if p.exists() else ""


# ---- process-group helpers (prefer dlc_common's if present; local fallback otherwise) ----
def start_process_group(cmd: str, cwd: Path, env: dict[str, str], log_path: Path) -> subprocess.Popen:
    fn = getattr(dlc, "start_process_group", None)
    if fn is not None:
        try:
            return fn(cmd, cwd, env, log_path)
        except TypeError:
            pass
    log = open(log_path, "wb")
    kwargs: dict[str, Any] = {"start_new_session": True} if os.name != "nt" else {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
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
            proc.wait(timeout=timeout)  # reap after SIGKILL so no zombie / dangling port remains
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
    """Stop the backend process group a previous validate_build.py / run_closed_loop_eval.py run recorded in `pidfile`
    if it is still alive (TERM → KILL). Never touches processes this harness did not record."""
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
    """One-shot headless Chrome in its own session; on timeout the whole process group is killed."""
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


class ProbeServer:
    """Serves the smoke-probe page over http://127.0.0.1:<ephemeral> on the app's own origin: requests other than
    `/__dlc_probe` are reverse-proxied to the backend (http uiEntry) or served from the entry file's directory, so
    Chrome needs neither `file://` access nor `--disable-web-security`."""

    def __init__(self, target_url: str, probe_html: str):
        self.upstream: str | None = None
        self.static_dir: Path | None = None
        if re.match(r"^https?://", target_url):
            u = urllib.parse.urlsplit(target_url)
            self.upstream = f"{u.scheme}://{u.netloc}"
            self.entry_path = u.path or "/"
        else:
            p = Path(urllib.parse.unquote(urllib.parse.urlsplit(target_url).path)) if target_url.startswith("file:") else Path(target_url)
            self.static_dir = p.parent.resolve()
            self.entry_path = "/" + p.name
        self.probe_html = probe_html
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a: Any) -> None:
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
                if self.path.split("?", 1)[0] == "/__dlc_probe":
                    self._send(200, outer.probe_html.encode("utf-8"), "text/html; charset=utf-8")
                elif outer.upstream:
                    self._proxy()
                else:
                    self._static()

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _handle

            def _proxy(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else (b"" if self.command in ("POST", "PUT", "PATCH") else None)
                headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "connection", "content-length", "accept-encoding", "keep-alive")}
                req = urllib.request.Request(outer.upstream + self.path, data=body, method=self.command, headers=headers)  # type: ignore[operator]
                try:
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        status, hdrs, data = resp.status, list(resp.getheaders()), resp.read()
                except urllib.error.HTTPError as e:
                    status, hdrs, data = e.code, list(e.headers.items()), e.read()
                except Exception as e:
                    self._send(502, f"probe proxy could not reach {outer.upstream}: {e}".encode("utf-8"), "text/plain; charset=utf-8")
                    return
                self.send_response(status)
                for k, v in hdrs:
                    if k.lower() not in ("transfer-encoding", "connection", "content-length", "content-encoding", "keep-alive"):
                        self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(data)

            def _static(self) -> None:
                import mimetypes
                assert outer.static_dir is not None
                rel = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path).lstrip("/") or outer.entry_path.lstrip("/")
                p = (outer.static_dir / rel).resolve()
                if not str(p).startswith(str(outer.static_dir)) or not p.is_file():
                    self._send(404, b"not found", "text/plain; charset=utf-8")
                    return
                ctype = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
                self._send(200, p.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith("text/") or ctype.endswith("javascript") else ""))

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True  # type: ignore[attr-defined]
        self.origin = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True).start()

    def base_href(self) -> str:
        return self.origin + self.entry_path.rsplit("/", 1)[0] + "/"

    def close(self) -> None:
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass


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
    fn = getattr(dlc, "find_chrome_binary", None)
    if fn is not None:
        try:
            found = fn()
            if found:
                return str(found)
        except Exception:
            pass
    if os.environ.get("CHROME_BIN") and Path(os.environ["CHROME_BIN"]).exists():
        return os.environ["CHROME_BIN"]
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    for p in ("/opt/google/chrome/chrome", "/usr/bin/google-chrome", "/usr/bin/chromium",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium"):
        if Path(p).exists():
            return p
    return None


SMOKE_OK, SMOKE_FAIL, SMOKE_SKIPPED = "ok", "fail", "skipped"


def _playwright_smoke(target_url: str) -> tuple[str, str]:
    """Playwright branch of the smoke check. Returns (SMOKE_SKIPPED, reason) when Playwright is not importable or its
    browser cannot launch (caller falls back to headless Chrome); SMOKE_FAIL / SMOKE_OK otherwise."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        return SMOKE_SKIPPED, "playwright not installed"
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except Exception as e:  # import OK but no browser binaries (`playwright install chromium` not run) → fall back
            return SMOKE_SKIPPED, f"playwright importable but chromium.launch() failed: {str(e).splitlines()[0][:160]}"
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page_errors: list[str] = []
            failed_assets: list[str] = []
            page.on("pageerror", lambda e: page_errors.append(str(e)))
            page.on("response", lambda r: failed_assets.append(f"{r.status} {r.url}")
                    if r.status >= 400 and r.request.resource_type in ("stylesheet", "script", "document") else None)
            page.goto(target_url, wait_until="load", timeout=10000)
            page.wait_for_timeout(120)
            if page_errors:
                return SMOKE_FAIL, f"uncaught pageerror(s): {'; '.join(page_errors[:3])}"
            if failed_assets:
                return SMOKE_FAIL, f"failed CSS/JS asset load(s): {'; '.join(failed_assets[:3])}"
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
                    return SMOKE_FAIL, f"initial render has multiple visible [role='tabpanel'] containers simultaneously: {init_vis}"
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
                        return SMOKE_FAIL, f"clicking tab #{idx + 1} (aria-controls='{pid}') did not give #{pid} a non-zero bounding box"
                    others = [p for p in vis if p != pid]
                    if others:
                        return SMOKE_FAIL, f"clicking tab #{idx + 1} (aria-controls='{pid}') left sibling panel(s) visible: {others}"
            return SMOKE_OK, f"playwright layout smoke ok ({tab_count} tab(s) verified)"
        except Exception as e:
            return SMOKE_FAIL, f"playwright layout smoke error: {e}"
        finally:
            try:
                browser.close()
            except Exception:
                pass


def run_layout_smoke_check(target_url: str, html_source: str, log_dir: Path) -> tuple[str, str]:
    """Verify zero uncaught pageerror/failed CSS-JS assets and [role='tab'] / [role='tabpanel'] bounding-box exclusivity.

    Tri-state result: (SMOKE_OK | SMOKE_FAIL | SMOKE_SKIPPED, message). SKIPPED is reported with its reason and never
    counted as a pass. Chain: Playwright → headless Chrome (probe page served over http://127.0.0.1 on the app's origin)."""
    pw_status, pw_msg = _playwright_smoke(target_url)
    if pw_status != SMOKE_SKIPPED:
        return pw_status, pw_msg
    dlc.info(f"layout smoke: {pw_msg} — trying headless Chrome")

    chrome = _find_chrome_bin()
    if not chrome:
        return SMOKE_SKIPPED, f"{pw_msg}; no Chrome/Chromium/Edge binary found (set CHROME_BIN) — layout smoke check SKIPPED"

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
      var json = JSON.stringify({ ok: errs.length === 0, errors: errs, tabsVerified: totalTabs });
      try { pre.textContent = 'b64:' + btoa(unescape(encodeURIComponent(json))); } catch (e) { pre.textContent = json; }
      document.body.appendChild(pre);
    }
    if (document.readyState === 'complete') setTimeout(runSmoke, 120);
    else window.addEventListener('load', function(){ setTimeout(runSmoke, 120); });
    })();
    """
    server: ProbeServer | None = None
    smoke_prof = log_dir / ".chrome-smoke-profile"
    try:
        server = ProbeServer(target_url, "")  # probe HTML is filled in below once the origin is known
        base_tag = f'<base href="{server.base_href()}">' if not re.search(r"<base\b", html_source, re.I) else ""
        path_fix = f"<script>try{{history.replaceState(null,'',{json.dumps(server.entry_path)});}}catch(e){{}}</script>"
        err_hook = base_tag + path_fix + "<script>window.__dlcSmokeErrors=[];window.addEventListener('error',function(e){window.__dlcSmokeErrors.push(e.message||'script error');});" \
                                        "window.addEventListener('unhandledrejection',function(e){var r=e.reason;window.__dlcSmokeErrors.push('unhandled rejection: '+(r&&(r.message||r)||'?'));});</script>"
        injected = re.sub(r"(<head[^>]*>)", lambda m: m.group(1) + err_hook, html_source, count=1, flags=re.I)
        if err_hook not in injected:
            injected = err_hook + html_source
        runner = f"<script>{smoke_js}</script>"
        if re.search(r"</body\s*>", injected, re.I):
            injected = re.sub(r"(</body\s*>)", lambda m: runner + m.group(1), injected, count=1, flags=re.I)
        else:
            injected = injected + runner
        server.probe_html = injected
        smoke_prof.mkdir(parents=True, exist_ok=True)
        cmd = [chrome, "--headless=new", "--disable-gpu", "--disable-dev-shm-usage", "--no-first-run", "--no-default-browser-check",
               "--password-store=basic", "--use-mock-keychain", "--disable-extensions", f"--user-data-dir={smoke_prof}",
               "--window-size=1440,900", "--virtual-time-budget=2000", "--dump-dom", f"{server.origin}/__dlc_probe"]
        flags = chrome_sandbox_flags()
        for attempt in (1, 2):
            try:
                rc, out, err = run_chrome(cmd[:1] + flags + cmd[1:], 30)
            except subprocess.TimeoutExpired:
                return SMOKE_SKIPPED, "chrome-headless layout smoke SKIPPED: chrome timed out after 30s"
            m = re.search(r'<pre id="__dlc_smoke_result__">(.*?)</pre>', out or "", re.S)
            if m:
                break
            low = (err or "").lower()
            if attempt == 1 and not flags and ("sandbox" in low or "zygote" in low):
                dlc.warn("chrome could not start its sandbox here — retrying with --no-sandbox (set DLC_CHROME_NO_SANDBOX=1 to skip this probe)")
                flags = ["--no-sandbox"]
                continue
            tail_err = " | ".join((err or "").strip().splitlines()[-3:])[:300]
            return SMOKE_SKIPPED, f"chrome-headless layout smoke SKIPPED: no result block (rc={rc}; page JS may have thrown before load) {tail_err}"
        payload = m.group(1).strip()
        try:
            if payload.startswith("b64:"):
                res = json.loads(base64.b64decode(payload[4:]).decode("utf-8"))
            else:
                import html as _html
                res = json.loads(_html.unescape(payload) if "&quot;" in payload else payload)
        except Exception as e:
            return SMOKE_SKIPPED, f"chrome-headless layout smoke SKIPPED: unreadable result block ({e})"
        if not res.get("ok"):
            return SMOKE_FAIL, "; ".join(res.get("errors") or ["layout smoke check failed"])
        return SMOKE_OK, f"chrome-headless layout smoke ok ({res.get('tabsVerified', 0)} tab(s) verified)"
    except Exception as e:
        return SMOKE_SKIPPED, f"chrome-headless layout smoke SKIPPED: {e}"
    finally:
        if server is not None:
            server.close()
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
    # Skipped only for the zero-dependency python-stdlib-http / none / tbd kinds (unless a managed database is declared);
    # every other backend kind must handle APP_ENV, AUTH_MODE and a database URL in real (non-comment) code.
    if be_kind not in ("python-stdlib-http", "none", "tbd") or db_kind in ("postgres", "alloydb-omni", "mysql", "sqlserver"):
        code_exts = (".py", ".java", ".kt", ".ts", ".js", ".mjs", ".go", ".cs", ".yml", ".yaml", ".properties", ".json", ".sh", ".env", ".toml")
        scan_roots = [be_dir, root / "src" / "run.sh", root / "src" / "run.ps1"]
        all_be_files: list[Path] = []
        for sr in scan_roots:
            if sr.is_file():
                all_be_files.append(sr)
            elif sr.is_dir():
                all_be_files.extend(sorted(p for p in sr.rglob("*") if p.is_file() and p.suffix.lower() in code_exts
                                           and not any(part in ("node_modules", "dist", "build", "target", "bin", "obj", ".venv", "venv", "__pycache__") for part in p.parts)))
        comment_rx = re.compile(r"^\s*(#|//|\*|/\*|<!--|--|;)")
        code_lines: list[str] = []
        for p in all_be_files:
            code_lines.extend(ln for ln in dlc.read_text(p).splitlines() if ln.strip() and not comment_rx.match(ln))
        code_blob = "\n".join(code_lines)
        required = {
            "APP_ENV (local vs production mode switch)": re.compile(r"\bAPP_ENV\b"),
            "AUTH_MODE (local-mock vs oidc-iap)": re.compile(r"\bAUTH_MODE\b"),
            f"database URL for {db_kind} (DATABASE_URL / SPRING_DATASOURCE_URL / DB_HOST / ConnectionStrings)": re.compile(r"\b(?:DATABASE_URL|SPRING_DATASOURCE_URL|DB_HOST|ConnectionStrings)\b"),
        }
        missing = [label for label, rx in required.items() if not rx.search(code_blob)]
        if not all_be_files:
            failures.append(f"Dual-mode configuration: no backend source under src/backend/ (or src/run.sh) to inspect for backend={be_kind!r}, database={db_kind!r}.")
        elif missing:
            failures.append(
                f"Dual-mode configuration (12-factor, APP_ENV=local vs production) is incomplete for backend={be_kind!r}, database={db_kind!r} — "
                f"no non-comment line in src/backend/** or src/run.sh references: " + "; ".join(missing) + ". "
                f"Scanned {len(all_be_files)} file(s). Stage 5 must read these from the environment so the same codebase runs locally and in the target environment."
            )
        else:
            checks.append(("dual-mode DB & env configuration", f"ok (APP_ENV + AUTH_MODE + database URL handled in {len(all_be_files)} backend file(s); target {db_kind} + local test mode)"))

    return checks, failures


def readme_mentions_run(txt: str, start_cmd: str, healthcheck: str, root: Path) -> tuple[bool, str]:
    """README must literally contain the start command, the run script, or the healthcheck URL — the first token of the
    start command alone (e.g. `python3`, `npm`) proves nothing."""
    candidates: list[tuple[str, str]] = []
    if start_cmd:
        candidates.append(("start command", start_cmd))
    for rs in ("src/run.sh", "src/run.ps1", "src/run.bat"):
        if (root / rs).is_file():
            candidates += [("run script", rs), ("run script", Path(rs).name)]
    if healthcheck:
        candidates.append(("healthcheck URL", healthcheck))
    for label, needle in candidates:
        if needle and needle in txt:
            return True, f"{label} `{needle}`"
    return False, " / ".join(f"`{n}`" for _, n in candidates) or "(nothing to look for)"


def run_alm_bridge(root: Path, stack: dict[str, Any], action_args: list[str], deterministic: bool, skip: bool, force: bool) -> None:
    """Call 03/scripts/alm_jira_ado_bridge.py unless (a) --skip-alm-sync, (b) target_stack.almPlatform is `none`/missing,
    or (c) --deterministic (golden runs) — (b) and (c) can be overridden with --alm-sync."""
    if skip:
        return
    helper = getattr(dlc, "run_alm_bridge", None)
    if helper is not None:
        try:
            helper(root, action_args, deterministic=deterministic, force=force)
            return
        except TypeError:
            pass
    platform = str(stack.get("almPlatform") or "none").strip().lower()
    if not force:
        if platform in ("", "none"):
            dlc.info("ALM sync skipped: target_stack.almPlatform is 'none' (pass --alm-sync to update backlog/ anyway)")
            return
        if deterministic:
            dlc.info("ALM sync skipped under --deterministic (pass --alm-sync to force)")
            return
    bridge = Path(__file__).resolve().parents[2] / "03-story-and-sprint-planner" / "scripts" / "alm_jira_ado_bridge.py"
    if not bridge.is_file() or not (root / "backlog" / "user_stories.json").is_file():
        return
    cmd = [sys.executable, str(bridge), "--project-root", str(root), *action_args] + (["--deterministic"] if deterministic else [])
    cp = subprocess.run(cmd, cwd=str(root))
    if cp.returncode not in (0, 2):
        dlc.warn(f"ALM bridge ({' '.join(action_args)}) returned {cp.returncode}")


def record_smoke(label: str, status: str, msg: str, checks: list[tuple[str, str]], failures: list[str]) -> None:
    """Tri-state smoke result: ok → check, fail → failure, skipped → printed with its reason (never a silent pass)."""
    if status == SMOKE_OK:
        checks.append(("layout & tab-exclusivity smoke", f"ok — {msg}"))
    elif status == SMOKE_FAIL:
        checks.append(("layout & tab-exclusivity smoke", f"FAIL — {msg}"))
        failures.append(f"layout smoke {label}: {msg}")
    else:
        checks.append(("layout & tab-exclusivity smoke", f"SKIPPED — {msg}"))
        dlc.warn(f"layout smoke {label} SKIPPED: {msg}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument("--timeout", type=int, default=600, help="Per-command timeout for install/build/test (s)")
    ap.add_argument("--start-timeout", type=int, default=60, help="Seconds to wait for healthcheck")
    ap.add_argument("--skip-install", action="store_true")
    ap.add_argument("--skip-test", action="store_true", help="Do not execute commands.test")
    ap.add_argument("--skip-alm-sync", action="store_true", help="Skip automatic transition of active sprint stories to 'In Progress'")
    ap.add_argument("--alm-sync", action="store_true", help="Force the ALM bridge call even when almPlatform is 'none' or --deterministic is set")
    ap.add_argument("--deterministic", action="store_true", help="Fixed timestamps when updating story statuses (also skips ALM sync unless --alm-sync)")
    args = ap.parse_args()
    root = dlc.resolve_project_root(args.project_root)
    dlc.require_gate_approved(root, "gate_4_design_and_tests", "Stage 5 (06-coding-agent / validate_build.py)", deterministic=args.deterministic)
    stack = dlc.load_target_stack(root, allow_default=False)
    commands = stack.get("commands") or {}
    backend_kind = (stack.get("backend") or {}).get("kind", "none")
    ui_entry = commands.get("uiEntry") or "src/ui/index.html"
    log_dir = root / "test" / ".build_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    pidfile = root / BACKEND_PIDFILE
    failures: list[str] = []
    checks: list[tuple[str, str]] = []

    if not (root / "src").exists():
        raise dlc.GateFailure("src/ does not exist — Stage 5 (06-coding-agent / coding-agent) must generate the application first.")

    # ---- Verify Target-Stack Fidelity & Dual-Mode Configuration ----
    ts_checks, ts_failures = verify_target_stack_artifacts(root, stack)
    checks.extend(ts_checks)
    failures.extend(ts_failures)

    is_url = bool(re.match(r"^https?://", ui_entry))
    start_cmd = (commands.get("start") or "").strip()
    healthcheck = (commands.get("healthcheck") or "").strip()
    test_cmd = (commands.get("test") or "").strip()

    # ---- README ----
    readme = root / "src" / "README.md"
    if not readme.exists():
        failures.append("src/README.md missing — Stage 5 must document how to build/run/test")
    elif start_cmd or healthcheck:
        ok, detail = readme_mentions_run(dlc.read_text(readme), start_cmd, healthcheck, root)
        if ok:
            checks.append(("README documents how to run", detail))
        else:
            failures.append(f"src/README.md does not literally mention the start command, the run script or the healthcheck URL (looked for {detail})")

    def run_test_command() -> None:
        """B5: `commands.test` is executed when present (SKILL 06 promises it) — bounded, non-zero exit is a failure."""
        if not test_cmd or args.skip_test:
            if test_cmd:
                checks.append(("commands.test", "SKIPPED (--skip-test)"))
            return
        if run_logged("test", test_cmd, root, log_dir, args.timeout, failures):
            checks.append(("commands.test", f"ok — `{test_cmd}`"))
        else:
            checks.append(("commands.test", f"FAIL — `{test_cmd}` (see {log_dir / 'test.log'})"))

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
                    record_smoke(str(p), *run_layout_smoke_check(str(p.resolve()), dlc.read_text(p), log_dir), checks, failures)
        run_test_command()
    else:
        if not start_cmd:
            failures.append(f"backend.kind={backend_kind} but target_stack.commands.start is empty (ARCHITECTURE §4.2 requires it)")
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
            # B1: reap only the process group a previous harness run recorded, then refuse to start on a busy port.
            if reap_pidfile(pidfile):
                time.sleep(0.3)
            stale = False
            try:
                st, _ = fetch(healthcheck, 2)
                stale = 200 <= st < 300
            except Exception:
                stale = False
            if stale:
                failures.append(f"{healthcheck} already answers BEFORE the start command ran — a stale server (previous run, or another project on the same port) "
                                f"owns the port; the new process would fail to bind and the gate would be judging stale code. Stop that server (or change commands.healthcheck/PORT) and re-run.")
                checks.append(("stale-port check", f"FAIL — {healthcheck} answered before start"))
            else:
                checks.append(("stale-port check", f"ok — {healthcheck} not answering before start"))
                env = dict(os.environ)
                port = urllib.parse.urlsplit(healthcheck).port
                if port:
                    env.setdefault("PORT", str(port))
                log = log_dir / "start.log"
                dlc.info(f"start: {start_cmd}")
                proc = start_process_group(start_cmd, root, env, log)
                try:
                    dlc.write_text(pidfile, str(os.getpgid(proc.pid) if os.name != "nt" else proc.pid))
                except Exception:
                    pass
                try:
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
                                    record_smoke(ui_entry, *run_layout_smoke_check(ui_entry, body, log_dir), checks, failures)
                            except Exception as e:
                                failures.append(f"uiEntry {ui_entry} not reachable: {e}")
                        else:
                            p = dlc.project_path(root, ui_entry)
                            if p.exists():
                                record_smoke(str(p), *run_layout_smoke_check(str(p.resolve()), dlc.read_text(p), log_dir), checks, failures)
                        run_test_command()  # while the backend is up, so integration-style test commands can reach it
                    else:
                        failures.append(f"healthcheck {healthcheck} never returned 2xx within {args.start_timeout}s"
                                        + (f" (process exited with {proc.returncode})" if proc.poll() is not None else "") + f"\n--- start.log (tail) ---\n{tail(log)}")
                finally:
                    stop_process_group(proc, timeout=5)
                    pidfile.unlink(missing_ok=True)
        elif is_url and not start_cmd:
            failures.append(f"uiEntry is an http URL ({ui_entry}) but no start command is configured")

    # ---- Degraded mode (ARCHITECTURE §4.2.2): src/run.sh may fall back to a local dev runner ONLY when the native toolchain
    # is absent, and must then write test/.build_logs/degraded_mode.json. Detected after start; never silent.
    degraded: dict[str, Any] | None = None
    degraded_p = log_dir / "degraded_mode.json"
    if degraded_p.exists():
        try:
            raw = dlc.read_json(degraded_p)
            degraded = raw if isinstance(raw, dict) else {"reason": str(raw)}
        except Exception as e:
            degraded = {"reason": f"unreadable degraded_mode.json ({e})"}
        summary = (f"reason={degraded.get('reason')!r} missingTools={degraded.get('missingTools')} fallback={degraded.get('fallback')!r} "
                   f"recordedAtUtc={degraded.get('recordedAtUtc')}")
        if backend_kind in ("python-stdlib-http", "none", "tbd"):
            failures.append(f"test/.build_logs/degraded_mode.json exists but backend.kind={backend_kind!r} has no native toolchain to fall back from — "
                            f"a degraded-mode marker here means the start command is not what target_stack.json declares ({summary}). Remove the fallback or fix the stack.")
            checks.append(("degraded mode", f"FAIL — unexpected for backend.kind={backend_kind!r}: {summary}"))
        else:
            dlc.warn(f"DEGRADED MODE: src/run.sh fell back to a local dev runner because the native toolchain is absent — {summary}. "
                     f"Gate 5 may pass locally, but Gate 7 (validate_gdc_packaging.py) refuses while the marker exists. Install the toolchain and re-run.")
            checks.append(("degraded mode", f"WARN — {summary}"))

    print("\n=== Stage 5 build gate ===")
    for k, v in checks:
        mark = "✗" if v.startswith("FAIL") else ("•" if v.startswith(("SKIPPED", "WARN")) else "✓")
        print(f"  {mark} {k}: {v}")
    for f in failures:
        print(f"  ✗ {f}")
    if degraded is not None and not failures:
        print(f"  ⚠ degradedMode: {json.dumps(degraded, ensure_ascii=False)}")
    summary_json = {
        "schemaVersion": dlc.SCHEMA_VERSION,
        "recordedAtUtc": dlc.utc_now_iso(args.deterministic),
        "verdict": "FAIL" if failures else "PASS",
        "checks": [{"check": k, "result": v} for k, v in checks],
        "failures": failures,
        "degradedMode": degraded,
    }
    dlc.write_json(log_dir / "build_gate_summary.json", summary_json)
    if failures:
        raise dlc.GateFailure(f"{len(failures)} build check(s) failed — fix the application (Stage 5) or target_stack.json (Gate 1). Logs: {log_dir}")
    print("BUILD GATE: PASS" + (" (DEGRADED MODE — see test/.build_logs/degraded_mode.json)" if degraded is not None else ""))

    # Automatically transition active sprint stories from 'To Do' -> 'In Progress' on Stage 5 completion
    run_alm_bridge(root, stack, ["--action", "transition-stories", "--target-status", "In Progress", "--scope", "active-sprints", "--only-from-todo"],
                   args.deterministic, args.skip_alm_sync, args.alm_sync)
    dlc.mark_gate_awaiting_human(
        root,
        "gate_5_build",
        summary="Stage 5 Runnable Target-Stack Application Build validated. Present src/ build summary & local start instructions to user and STOP for Gate 5 approval before Stage 6 Closed-Loop Evaluation.",
        deterministic=args.deterministic,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
