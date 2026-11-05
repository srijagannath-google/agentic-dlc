#!/usr/bin/env python3
"""Stage 1 — Automated Reference Portal Crawler & UI Token/Topology Extractor (01-discovery-and-grouping).

When the user provides a live reference URL (via --url or an explicit `resources/design_references/*.url` /
`*.url.json` bookmark) or a local `*.html` prototype under `resources/design_references/`, this script:
  1. Launches headless Playwright (chromium) at desktop (1440x900) and mobile (390x844) viewports
     (falling back to Chrome headless `--dump-dom` + `--screenshot` of the URL itself when Python playwright is
     unavailable — the fetched page is never re-hosted in a local harness file);
  2. Discovers and activates every `[role="tab"]` and in-page / same-origin navigation link (never external links);
  3. Extracts and writes `specs/design_reference/reference_ui_manifest.json` (a generated artefact — it is NOT
     written into `resources/design_references/`, which holds user-provided inputs only):
     - `designTokens`: CSS custom properties (`--*`), header/banner background colors, primary/accent button
       colors, surface background colors, font families, and border radii;
     - `views`: every tab/route label, its visible heading, interactive pattern type (`multi-step-wizard`,
       `triage-queue-table`, `kpi-ledger-console`, `searchable-registry`, `detail-workspace`), wizard steps,
       primary CTA button labels and `sourceKind` (`tab` for `[role="tab"]`, `anchor` for in-page links);
  4. Saves full-page PNG screenshots per tab (`specs/design_reference/screenshots/tab-01-*.png`).

Only `http://` and `https://` targets are crawled. `file:`, `javascript:`, `data:` and other schemes are rejected,
and loopback / link-local / private-range hosts are refused unless `--allow-private-hosts` is given. Local HTML
prototypes are accepted only as files that live inside the project root.

Usage:
    python3 capture_design_reference.py --project-root <PROJECT_ROOT> [--url <REFERENCE_URL> ...]
                                        [--output specs/design_reference/reference_ui_manifest.json]
                                        [--allow-private-hosts] [--deterministic]
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import dlc_common as dlc  # noqa: E402

DEFAULT_OUTPUT = "specs/design_reference/reference_ui_manifest.json"
CHROME_CANDIDATES = [
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge",
    "/opt/google/chrome/chrome", "/usr/bin/google-chrome", "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]
# Navigation candidates: ARIA tabs plus in-page / same-origin links. External links are filtered in Python.
NAV_CANDIDATE_SELECTOR = '[role="tab"], nav a[href], .nav-tab, [data-tab]'

# In-page JS extractor evaluated by Playwright on the live page (page.evaluate) — never injected into a copy.
EXTRACTOR_JS = r"""
(() => {
  function vis(el) {
    if (!el || !el.isConnected || el.hidden || el.getAttribute('aria-hidden') === 'true') return false;
    let cur = el;
    while (cur && cur.nodeType === 1) {
      const cs = window.getComputedStyle(cur);
      if (cs.display === 'none' || cs.visibility === 'hidden' || cur.hidden) return false;
      cur = cur.parentElement;
    }
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }
  function text(el) {
    return el ? (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim() : '';
  }
  function classifyPattern(root) {
    if (!root) return 'detail-workspace';
    const steps = root.querySelectorAll('[data-step], .wizard-step, .stepper, [aria-label*="step" i]');
    if (steps.length >= 2) return 'multi-step-wizard';
    const tables = root.querySelectorAll('table, [role="table"], [role="grid"]');
    const kpis = root.querySelectorAll('.kpi, [data-kpi], .stat-card, .metric-card');
    const search = root.querySelectorAll('input[type="search"], input[placeholder*="search" i], input[placeholder*="filter" i]');
    if (tables.length && kpis.length >= 2) return 'kpi-ledger-console';
    if (tables.length && search.length) return 'searchable-registry';
    if (tables.length) return 'triage-queue-table';
    if (search.length) return 'searchable-registry';
    return 'detail-workspace';
  }
  function extractTokens() {
    const customProps = {};
    for (const sheet of Array.from(document.styleSheets || [])) {
      let rules;
      try { rules = sheet.cssRules || []; } catch (e) { continue; }
      for (const r of Array.from(rules)) {
        if (r.style) {
          for (let i = 0; i < r.style.length; i++) {
            const name = r.style[i];
            if (name && name.startsWith('--')) {
              customProps[name] = r.style.getPropertyValue(name).trim();
            }
          }
        }
      }
    }
    const rootCs = window.getComputedStyle(document.documentElement);
    const bodyCs = window.getComputedStyle(document.body || document.documentElement);
    const hdr = document.querySelector('header, [role="banner"], .app-header, nav');
    const hdrCs = hdr ? window.getComputedStyle(hdr) : null;
    const btn = document.querySelector('.btn-primary, [data-emphasis="primary"], button.primary, button[type="submit"], button');
    const btnCs = btn ? window.getComputedStyle(btn) : null;
    const card = document.querySelector('.card, [role="tabpanel"], section, main');
    const cardCs = card ? window.getComputedStyle(card) : null;
    return {
      cssCustomProperties: customProps,
      bodyBackgroundColor: bodyCs.backgroundColor || '',
      bodyTextColor: bodyCs.color || '',
      fontFamily: bodyCs.fontFamily || rootCs.fontFamily || '',
      headerBackgroundColor: hdrCs ? hdrCs.backgroundColor : '',
      headerTextColor: hdrCs ? hdrCs.color : '',
      primaryButtonBackgroundColor: btnCs ? btnCs.backgroundColor : '',
      primaryButtonTextColor: btnCs ? btnCs.color : '',
      primaryButtonBorderRadius: btnCs ? btnCs.borderRadius : '',
      surfaceBorderRadius: cardCs ? cardCs.borderRadius : '',
    };
  }
  function navCandidates() {
    // Describe every navigation candidate so Python can decide which ones are safe to activate.
    return Array.from(document.querySelectorAll('[role="tab"], nav a[href], .nav-tab, [data-tab]')).map((el, idx) => ({
      index: idx,
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') || '',
      href: el.getAttribute('href') || '',
      target: el.getAttribute('target') || '',
      label: text(el),
      visible: vis(el),
    }));
  }
  function snapshotCurrentView(tabEl, idx) {
    const panelId = tabEl ? (tabEl.getAttribute('aria-controls') || tabEl.getAttribute('data-target') || '') : '';
    let panel = panelId ? document.getElementById(panelId.replace(/^#/, '')) : null;
    if (!panel) {
      const panels = Array.from(document.querySelectorAll('[role="tabpanel"], [data-view], main section, main')).filter(vis);
      panel = panels[0] || document.body;
    }
    const h = panel.querySelector('h1, h2, h3') || document.querySelector('h1, h2');
    const actionButtons = Array.from(panel.querySelectorAll('button, [role="button"], input[type="submit"]'))
      .filter(vis)
      .map(b => text(b))
      .filter(Boolean)
      .slice(0, 8);
    const wizSteps = Array.from(panel.querySelectorAll('[data-step], .wizard-step, .step-indicator, [role="listitem"]'))
      .map(s => text(s))
      .filter(s => s && s.length <= 60)
      .slice(0, 10);
    const label = tabEl ? text(tabEl) : (text(h) || 'Main View');
    const isTab = !!(tabEl && tabEl.getAttribute('role') === 'tab');
    const tid = tabEl ? (tabEl.getAttribute('data-testid') ? `[data-testid="${tabEl.getAttribute('data-testid')}"]` : (tabEl.id ? `#${tabEl.id}` : (isTab ? `[role="tab"]:nth-of-type(${idx + 1})` : `a[href="${tabEl.getAttribute('href') || ''}"]`))) : 'main';
    return {
      viewId: `VIEW-${String(idx + 1).padStart(2, '0')}`,
      tabLabel: label,
      tabSelector: tid,
      sourceKind: tabEl ? (isTab ? 'tab' : 'anchor') : 'main',
      panelId: panel && panel.id ? panel.id : (panelId || ''),
      heading: text(h) || label,
      patternType: classifyPattern(panel),
      wizardSteps: wizSteps,
      primaryActions: actionButtons,
    };
  }
  return { extractTokens, snapshotCurrentView, navCandidates };
})()
"""


# ------------------------------------------------------------------------------------------ chrome / sandbox
def which_chrome() -> str | None:
    """Locate a Chrome/Chromium binary (honours CHROME_BIN); prefers dlc.find_chrome_binary() when available."""
    finder = getattr(dlc, "find_chrome_binary", None)
    if callable(finder):
        try:
            found = finder()
            if found:
                return str(found)
        except Exception:
            pass
    for c in ([os.environ.get("CHROME_BIN", "")] + CHROME_CANDIDATES):
        if not c:
            continue
        if os.path.sep in c:
            if Path(c).exists():
                return c
        else:
            w = shutil.which(c)
            if w:
                return w
    return None


def chrome_base_flags(profile_dir: Path | None = None) -> list[str]:
    """Headless flags. `--no-sandbox` is only added when running as root or when DLC_CHROME_NO_SANDBOX=1.
    A private `--user-data-dir` avoids blocking on the default profile lock when another Chrome is running."""
    flags = ["--headless=new", "--disable-gpu", "--disable-dev-shm-usage", "--hide-scrollbars"]
    if profile_dir is not None:
        flags.append(f"--user-data-dir={profile_dir}")
    is_root = hasattr(os, "geteuid") and os.geteuid() == 0
    if is_root or os.environ.get("DLC_CHROME_NO_SANDBOX") == "1":
        flags.append("--no-sandbox")
    return flags


# ------------------------------------------------------------------------------------------ target discovery
def _host_is_private(host: str) -> bool:
    """True for loopback, link-local, private-range, multicast, reserved or unspecified hosts (literal or resolved)."""
    h = host.strip().strip("[]").lower()
    if not h or h in ("localhost", "localhost.localdomain", "ip6-localhost") or h.endswith(".localhost") or h.endswith(".local"):
        return True
    addrs: list[str] = []
    try:
        addrs.append(str(ipaddress.ip_address(h)))
    except ValueError:
        try:
            for fam, _t, _p, _c, sa in socket.getaddrinfo(h, None):
                addrs.append(str(sa[0]))
        except (socket.gaierror, OSError):
            return False  # unresolvable: the crawler will fail on its own; nothing private to protect
    for a in addrs:
        try:
            ip = ipaddress.ip_address(a.split("%")[0])
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return True
    return False


def validate_remote_url(raw: str, allow_private_hosts: bool) -> str | None:
    """Return a normalised http(s) URL or None (with a warning) when the URL is not allowed."""
    u = raw.strip()
    if not u:
        return None
    parts = urllib.parse.urlsplit(u)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        dlc.warn(f"design reference URL rejected (only http/https are crawled): {u[:120]!r}")
        return None
    if not parts.hostname:
        dlc.warn(f"design reference URL rejected (no host): {u[:120]!r}")
        return None
    if parts.username or parts.password:
        dlc.warn(f"design reference URL rejected (embedded credentials): {u[:120]!r}")
        return None
    if not allow_private_hosts and _host_is_private(parts.hostname):
        dlc.warn(f"design reference URL rejected (loopback/link-local/private host; pass --allow-private-hosts to permit): {u[:120]!r}")
        return None
    return urllib.parse.urlunsplit((scheme, parts.netloc, parts.path or "/", parts.query, ""))


def _local_html_target(cand: Path, root: Path) -> str | None:
    """Accept a local HTML prototype only when it resolves inside the project root."""
    try:
        resolved = cand.resolve()
        resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        dlc.warn(f"local design reference rejected (outside the project root): {cand}")
        return None
    if not resolved.is_file() or resolved.suffix.lower() not in (".html", ".htm"):
        dlc.warn(f"local design reference rejected (not an .html file): {cand}")
        return None
    return resolved.as_uri()


def discover_reference_targets(root: Path, explicit_urls: list[str], allow_private_hosts: bool = False) -> list[str]:
    """Collect reference targets from --url flags and explicit bookmarks / local prototypes in resources/design_references/.

    Honoured sources: `--url`, `*.url` (one URL per line, or INI `URL=`), `*.url.json` (`{"url": ...}`) and local
    `*.html` prototypes. URLs are never collected from arbitrary `.txt` / `.md` / `.json` files.
    """
    targets: list[str] = []
    for raw_u in explicit_urls:
        u = raw_u.strip()
        if not u:
            continue
        if re.match(r"^[a-z][a-z0-9+.-]*:", u, re.IGNORECASE):
            ok = validate_remote_url(u, allow_private_hosts)
            if ok:
                targets.append(ok)
            continue
        cand = Path(u).expanduser()
        if not cand.is_absolute():
            cand = root / cand
        local = _local_html_target(cand, root)
        if local:
            targets.append(local)
    ref_dir = root / "resources" / "design_references"
    if not ref_dir.is_dir():
        return list(dict.fromkeys(targets))
    for p in sorted(ref_dir.rglob("*")):
        if not p.is_file() or p.name.startswith(".") or p.name == "reference_ui_manifest.json" or "screenshots" in p.parts:
            continue
        if p.is_symlink():
            try:
                p.resolve().relative_to(root.resolve())
            except (OSError, ValueError):
                continue
        name = p.name.lower()
        if name.endswith((".html", ".htm")):
            local = _local_html_target(p, root)
            if local:
                targets.append(local)
        elif name.endswith(".url.json"):
            try:
                obj = json.loads(dlc.read_text(p))
            except Exception:
                dlc.warn(f"unreadable bookmark {p}")
                continue
            if isinstance(obj, dict) and obj.get("url"):
                ok = validate_remote_url(str(obj["url"]), allow_private_hosts)
                if ok:
                    targets.append(ok)
        elif name.endswith(".url"):
            for line in dlc.read_text(p).splitlines():
                line = line.strip()
                if not line or line.startswith(("#", ";", "[")):
                    continue
                if "=" in line and not re.match(r"^https?://", line, re.IGNORECASE):
                    key, _, val = line.partition("=")
                    if key.strip().lower() != "url":
                        continue
                    line = val.strip()
                ok = validate_remote_url(line, allow_private_hosts)
                if ok:
                    targets.append(ok)
    return list(dict.fromkeys(targets))


def _same_origin(a: str, b: str) -> bool:
    pa, pb = urllib.parse.urlsplit(a), urllib.parse.urlsplit(b)
    return (pa.scheme.lower(), pa.hostname, pa.port) == (pb.scheme.lower(), pb.hostname, pb.port)


def nav_candidate_allowed(cand: dict[str, Any], page_url: str) -> bool:
    """Only `[role=tab]` elements and in-page / same-origin links may be activated; never external links."""
    if not cand.get("visible"):
        return False
    if str(cand.get("role") or "").lower() == "tab":
        return True
    if str(cand.get("target") or "").lower() == "_blank":
        return False
    href = str(cand.get("href") or "").strip()
    if cand.get("tag") != "a":
        return not href or href.startswith("#")
    if not href or href.startswith("#"):
        return True
    if re.match(r"^[a-z][a-z0-9+.-]*:", href, re.IGNORECASE):
        return href.lower().startswith(("http://", "https://")) and _same_origin(urllib.parse.urljoin(page_url, href), page_url)
    if href.startswith("//"):
        return False
    return _same_origin(urllib.parse.urljoin(page_url, href), page_url)


# ------------------------------------------------------------------------------------------ playwright
def capture_with_playwright(url: str, shots_dir: Path, shots_rel: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Crawl a reference URL with Playwright at desktop (1440x900) and mobile (390x844) viewports."""
    from playwright.sync_api import sync_playwright  # type: ignore

    shots: list[str] = []
    views: list[dict[str, Any]] = []
    tokens: dict[str, Any] = {}

    def shoot(page: Any, slug: str, idx: int, v: dict[str, Any]) -> None:
        page.set_viewport_size({"width": 1440, "height": 900})
        page.wait_for_timeout(100)
        desk_p = shots_dir / f"tab-{idx:02d}-{slug}-desktop.png"
        page.screenshot(path=str(desk_p), full_page=True)
        v["desktopScreenshot"] = f"{shots_rel}/{desk_p.name}"
        shots.append(v["desktopScreenshot"])
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(100)
        mob_p = shots_dir / f"tab-{idx:02d}-{slug}-mobile.png"
        page.screenshot(path=str(mob_p), full_page=True)
        v["mobileScreenshot"] = f"{shots_rel}/{mob_p.name}"
        shots.append(v["mobileScreenshot"])

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(url, wait_until="load", timeout=30000)
            page.wait_for_timeout(200)
            base_url = page.url

            tokens = page.evaluate(f"{EXTRACTOR_JS}.extractTokens()")
            candidates = page.evaluate(f"{EXTRACTOR_JS}.navCandidates()") or []
            allowed = [c for c in candidates if nav_candidate_allowed(c, base_url)]
            skipped = len(candidates) - len(allowed)
            if skipped:
                dlc.info(f"skipped {skipped} external / non-tab navigation candidate(s) on {base_url}")

            if not allowed:
                v = page.evaluate(f"{EXTRACTOR_JS}.snapshotCurrentView(null, 0)")
                shoot(page, "main", 1, v)
                views.append(v)
            else:
                seen_labels: set[str] = set()
                nav_loc = page.locator(NAV_CANDIDATE_SELECTOR)
                for cand in allowed[:12]:
                    i = int(cand["index"])
                    page.set_viewport_size({"width": 1440, "height": 900})
                    loc = nav_loc.nth(i)
                    try:
                        if not loc.is_visible():
                            continue
                        loc.click(timeout=2500)
                        page.wait_for_timeout(150)
                    except Exception:
                        continue
                    if not _same_origin(page.url, base_url):
                        dlc.warn(f"navigation left the reference origin ({page.url}); returning to {base_url}")
                        page.goto(base_url, wait_until="load", timeout=30000)
                        continue
                    v = page.evaluate(
                        f"([idx]) => {{ const tabs = document.querySelectorAll('{NAV_CANDIDATE_SELECTOR}'); return ({EXTRACTOR_JS}).snapshotCurrentView(tabs[idx], idx); }}",
                        [i],
                    )
                    lbl = str(v.get("tabLabel") or f"tab-{i + 1}").strip()
                    if lbl.lower() in seen_labels:
                        continue
                    seen_labels.add(lbl.lower())
                    idx = len(views) + 1
                    v["viewId"] = f"VIEW-{idx:02d}"
                    shoot(page, dlc.slugify(lbl)[:32] or f"view-{idx:02d}", idx, v)
                    views.append(v)
        finally:
            browser.close()
    return tokens, views, shots


# ------------------------------------------------------------------------------------------ chrome --dump-dom
class _DomDigest(HTMLParser):
    """Stdlib parser over a Chrome `--dump-dom` snapshot: navigation candidates, headings, buttons, pattern hints, tokens."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.in_nav = 0
        self.in_style = False
        self.style_css: list[str] = []
        self.inline_styles: list[str] = []
        self.open: list[dict[str, Any]] = []  # elements whose text we are collecting
        self.nav: list[dict[str, Any]] = []
        self.headings: list[str] = []
        self.buttons: list[str] = []
        self.wizard_steps: list[str] = []
        self.counts = {"table": 0, "kpi": 0, "search": 0, "step": 0}

    def _attr(self, attrs: list[tuple[str, str | None]], k: str) -> str:
        return next((v or "" for a, v in attrs if a == k), "")

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "template", "noscript"):
            self.skip += 1
            return
        if tag == "style":
            self.in_style = True
            return
        if tag == "nav":
            self.in_nav += 1
        cls = self._attr(attrs, "class").lower()
        role = self._attr(attrs, "role").lower()
        style = self._attr(attrs, "style")
        if style:
            self.inline_styles.append(style)
        if tag == "table" or role in ("table", "grid"):
            self.counts["table"] += 1
        if any(c in cls.split() for c in ("kpi", "stat-card", "metric-card")) or self._attr(attrs, "data-kpi"):
            self.counts["kpi"] += 1
        if tag == "input":
            itype = self._attr(attrs, "type").lower()
            ph = self._attr(attrs, "placeholder").lower()
            if itype == "search" or "search" in ph or "filter" in ph:
                self.counts["search"] += 1
            if itype == "submit" and self._attr(attrs, "value"):
                self.buttons.append(self._attr(attrs, "value").strip())
        is_step = bool(self._attr(attrs, "data-step")) or any(c in cls.split() for c in ("wizard-step", "stepper", "step-indicator")) \
            or "step" in self._attr(attrs, "aria-label").lower()
        if is_step:
            self.counts["step"] += 1
        is_nav = role == "tab" or (tag == "a" and self.in_nav and self._attr(attrs, "href")) or "nav-tab" in cls.split() \
            or any(a == "data-tab" for a, _ in attrs)
        kind = None
        if is_nav:
            kind = "nav"
        elif tag in ("h1", "h2", "h3"):
            kind = "heading"
        elif tag == "button" or role == "button":
            kind = "button"
        elif is_step:
            kind = "step"
        if kind:
            self.open.append({
                "kind": kind, "tag": tag, "text": [], "role": role, "href": self._attr(attrs, "href"),
                "target": self._attr(attrs, "target"), "id": self._attr(attrs, "id"), "testid": self._attr(attrs, "data-testid"),
                "hidden": any(a in ("hidden",) for a, _ in attrs) or self._attr(attrs, "aria-hidden") == "true",
            })

    def handle_endtag(self, tag):
        if tag in ("script", "template", "noscript"):
            if self.skip:
                self.skip -= 1
            return
        if tag == "style":
            self.in_style = False
            return
        if tag == "nav" and self.in_nav:
            self.in_nav -= 1
        for i in range(len(self.open) - 1, -1, -1):
            if self.open[i]["tag"] == tag:
                el = self.open.pop(i)
                txt = re.sub(r"\s+", " ", " ".join(el["text"])).strip()
                if el["kind"] == "nav":
                    self.nav.append({**el, "label": txt, "index": len(self.nav)})
                elif el["kind"] == "heading" and txt:
                    self.headings.append(txt)
                elif el["kind"] == "button" and txt:
                    self.buttons.append(txt)
                elif el["kind"] == "step" and txt and len(txt) <= 60:
                    self.wizard_steps.append(txt)
                break

    def handle_data(self, data):
        if self.in_style:
            self.style_css.append(data)
            return
        if self.skip:
            return
        for el in self.open:
            el["text"].append(data)


def _tokens_from_css(css: str, inline: list[str]) -> dict[str, Any]:
    custom = {m.group(1): m.group(2).strip() for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;}]+)", css)}
    blob = css + "\n" + "\n".join(inline)

    def first(prop_re: str, selector_re: str | None = None) -> str:
        if selector_re:
            m = re.search(selector_re + r"[^{]*\{([^}]*)\}", css, re.IGNORECASE | re.DOTALL)
            body = m.group(1) if m else ""
            m2 = re.search(prop_re + r"\s*:\s*([^;}]+)", body, re.IGNORECASE)
            if m2:
                return m2.group(1).strip()
            return ""
        m2 = re.search(prop_re + r"\s*:\s*([^;}]+)", blob, re.IGNORECASE)
        return m2.group(1).strip() if m2 else ""

    return {
        "cssCustomProperties": custom,
        "bodyBackgroundColor": first(r"background(?:-color)?", r"(?:^|[\s,}])body"),
        "bodyTextColor": first(r"(?<![\w-])color", r"(?:^|[\s,}])body"),
        "fontFamily": first(r"font-family"),
        "headerBackgroundColor": first(r"background(?:-color)?", r"(?:^|[\s,}])(?:header|\.app-header|nav|\[role=\"?banner\"?\])"),
        "headerTextColor": first(r"(?<![\w-])color", r"(?:^|[\s,}])(?:header|\.app-header|nav)"),
        "primaryButtonBackgroundColor": first(r"background(?:-color)?", r"(?:\.btn-primary|button\.primary|button)"),
        "primaryButtonTextColor": first(r"(?<![\w-])color", r"(?:\.btn-primary|button\.primary|button)"),
        "primaryButtonBorderRadius": first(r"border-radius", r"(?:\.btn-primary|button\.primary|button)"),
        "surfaceBorderRadius": first(r"border-radius", r"(?:\.card|\[role=\"?tabpanel\"?\]|section|main)"),
    }


def _classify_counts(c: dict[str, int]) -> str:
    if c["step"] >= 2:
        return "multi-step-wizard"
    if c["table"] and c["kpi"] >= 2:
        return "kpi-ledger-console"
    if c["table"] and c["search"]:
        return "searchable-registry"
    if c["table"]:
        return "triage-queue-table"
    if c["search"]:
        return "searchable-registry"
    return "detail-workspace"


def views_from_dom_dump(dom_html: str, page_url: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Derive tokens + views from a DOM snapshot without executing any page script locally."""
    d = _DomDigest()
    d.feed(dom_html)
    tokens = _tokens_from_css("\n".join(d.style_css), d.inline_styles)
    pattern = _classify_counts(d.counts)
    heading = d.headings[0] if d.headings else ""
    actions = list(dict.fromkeys(b for b in d.buttons if b))[:8]
    views: list[dict[str, Any]] = []
    seen: set[str] = set()
    for n in d.nav:
        cand = {"visible": not n["hidden"], "role": n["role"], "href": n["href"], "target": n["target"], "tag": n["tag"]}
        if not nav_candidate_allowed(cand, page_url):
            continue
        lbl = n["label"] or ""
        if not lbl or lbl.lower() in seen:
            continue
        seen.add(lbl.lower())
        is_tab = n["role"] == "tab"
        if n["testid"]:
            sel = f'[data-testid="{n["testid"]}"]'
        elif n["id"]:
            sel = f'#{n["id"]}'
        elif is_tab:
            sel = f'[role="tab"]:nth-of-type({n["index"] + 1})'
        else:
            sel = f'a[href="{n["href"]}"]'
        views.append({
            "viewId": f"VIEW-{len(views) + 1:02d}", "tabLabel": lbl, "tabSelector": sel,
            "sourceKind": "tab" if is_tab else "anchor", "panelId": "", "heading": heading or lbl,
            "patternType": pattern, "wizardSteps": d.wizard_steps[:10], "primaryActions": actions,
        })
        if len(views) >= 12:
            break
    if not views:
        views.append({
            "viewId": "VIEW-01", "tabLabel": heading or "Main View", "tabSelector": "main", "sourceKind": "main",
            "panelId": "", "heading": heading or "Main View", "patternType": pattern,
            "wizardSteps": d.wizard_steps[:10], "primaryActions": actions,
        })
    return tokens, views


def capture_with_chrome_headless(binary: str, url: str, shots_dir: Path, shots_rel: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Fallback crawler: headless Chrome `--screenshot` + `--dump-dom` of the URL itself (never a re-hosted copy)."""
    shots: list[str] = []
    views: list[dict[str, Any]] = []
    tokens: dict[str, Any] = {}
    profile_dir = Path(tempfile.mkdtemp(prefix="dlc-chrome-profile-"))
    base = chrome_base_flags(profile_dir)

    desk_p = shots_dir / "tab-01-reference-desktop.png"
    mob_p = shots_dir / "tab-01-reference-mobile.png"
    for out_png, vp in ((desk_p, "1440,900"), (mob_p, "390,844")):
        cmd = [binary, *base, f"--window-size={vp}", f"--screenshot={out_png}", url]
        try:
            # stdout/stderr -> DEVNULL: Chrome's crashpad helper inherits the pipes and would keep communicate() waiting
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
        except subprocess.TimeoutExpired:
            dlc.warn(f"chrome headless screenshot timed out after 30s for {url} ({vp})")
        except OSError as e:
            dlc.warn(f"chrome headless screenshot failed for {url}: {e}")
        if out_png.is_file():
            shots.append(f"{shots_rel}/{out_png.name}")

    dom = ""
    try:
        cp = subprocess.run(
            [binary, *base, "--virtual-time-budget=3000", "--dump-dom", url],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=30, check=False,
        )
        dom = cp.stdout or ""
    except subprocess.TimeoutExpired:
        dlc.warn(f"chrome headless --dump-dom timed out after 30s for {url}")
    except OSError as e:
        dlc.warn(f"chrome headless --dump-dom failed for {url}: {e}")
    shutil.rmtree(profile_dir, ignore_errors=True)
    if dom.strip():
        tokens, views = views_from_dom_dump(dom, url)
        for v in views:
            if desk_p.is_file():
                v.setdefault("desktopScreenshot", f"{shots_rel}/{desk_p.name}")
            if mob_p.is_file():
                v.setdefault("mobileScreenshot", f"{shots_rel}/{mob_p.name}")
    return tokens, views, shots


# ------------------------------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument("--url", action="append", default=[],
                    help="Reference portal http(s) URL or a local .html prototype inside the project (may be passed multiple times)")
    ap.add_argument("--output", default=DEFAULT_OUTPUT, help=f"Manifest path relative to the project root (default {DEFAULT_OUTPUT})")
    ap.add_argument("--allow-private-hosts", action="store_true",
                    help="Permit loopback / link-local / private-range reference hosts (e.g. a prototype served on localhost)")
    ap.add_argument("--deterministic", action="store_true")
    args = ap.parse_args()

    root = dlc.resolve_project_root(args.project_root)
    targets = discover_reference_targets(root, args.url, args.allow_private_hosts)
    out_path = dlc.project_path(root, args.output)
    try:
        out_path.resolve().relative_to(root.resolve())
    except ValueError:
        raise dlc.GateFailure(f"--output {out_path} must be inside the project root {root}.")
    if out_path.resolve().is_relative_to((root / "resources").resolve()):
        raise dlc.GateFailure(
            f"--output {out_path} points into resources/ (user-provided inputs only). "
            f"Generated manifests belong in {DEFAULT_OUTPUT}."
        )
    shots_dir = out_path.parent / "screenshots"
    try:
        shots_rel = shots_dir.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        shots_rel = shots_dir.as_posix()

    if not targets:
        print("[dlc] No reference URLs (--url, *.url, *.url.json) or local HTML prototypes found in resources/design_references/.")
        return 0

    shots_dir.mkdir(parents=True, exist_ok=True)
    engine = "none"
    all_views: list[dict[str, Any]] = []
    merged_tokens: dict[str, Any] = {}
    all_shots: list[str] = []

    has_pw = False
    try:
        import playwright  # type: ignore  # noqa: F401
        has_pw = True
    except Exception:
        has_pw = False

    chrome_bin = which_chrome()

    for url in targets:
        dlc.info(f"capturing design reference: {url}")
        if has_pw:
            try:
                t, v, s = capture_with_playwright(url, shots_dir, shots_rel)
                engine = "playwright"
                merged_tokens = merged_tokens or t
                all_views.extend(v)
                all_shots.extend(s)
                continue
            except Exception as e:
                dlc.warn(f"playwright capture failed ({e}); falling back to chrome-headless")
        if chrome_bin:
            t, v, s = capture_with_chrome_headless(chrome_bin, url, shots_dir, shots_rel)
            engine = "chrome-headless"
            merged_tokens = merged_tokens or t
            all_views.extend(v)
            all_shots.extend(s)
        else:
            raise dlc.GateFailure("Neither Playwright nor a headless Chrome/Chromium binary is available to capture design reference.")

    for idx, v in enumerate(all_views, 1):
        v["viewId"] = f"VIEW-{idx:02d}"

    manifest = {
        "schemaVersion": dlc.SCHEMA_VERSION,
        "capturedAtUtc": dlc.utc_now_iso(args.deterministic),
        "captureEngine": engine,
        "sourceUrls": targets,
        "designTokens": merged_tokens,
        "views": all_views,
        "screenshots": list(dict.fromkeys(all_shots)),
    }
    dlc.write_json(out_path, manifest)
    print(f"[dlc] wrote {out_path} (engine={engine}, views={len(all_views)}, screenshots={len(manifest['screenshots'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
