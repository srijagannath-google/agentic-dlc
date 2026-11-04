#!/usr/bin/env python3
"""Stage 1 — Automated Reference Portal Crawler & UI Token/Topology Extractor (01-discovery-and-grouping).

When the user provides a live reference URL (via --url or inside `resources/design_references/*.url`,
`*.url.json`, `*.txt`, `*.md`, or a local `*.html` prototype in `resources/design_references/`), this script:
  1. Launches headless Playwright (chromium) at desktop (1440x900) and mobile (390x844) viewports
     (falling back to Chrome headless `--dump-dom` + `--screenshot` when Python playwright is unavailable);
  2. Discovers and clicks every top-level navigation link, `[role="tab"]`, and wizard step indicator;
  3. Extracts and writes `resources/design_references/reference_ui_manifest.json`:
     - `designTokens`: CSS custom properties (`--*`), header/banner background colors, primary/accent button
       colors, surface background colors, font families, and border radii;
     - `views`: every tab/route label, its visible heading, interactive pattern type (`multi-step-wizard`,
       `triage-queue-table`, `kpi-ledger-console`, `searchable-registry`, `detail-workspace`), wizard steps,
       and primary CTA button labels;
  4. Saves full-page PNG screenshots per tab (`resources/design_references/screenshots/tab-01-*.png`).

Usage:
    python3 capture_design_reference.py --project-root <PROJECT_ROOT> [--url <REFERENCE_URL> ...]
                                        [--output resources/design_references/reference_ui_manifest.json]
                                        [--deterministic]
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import dlc_common as dlc  # noqa: E402

URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+", re.IGNORECASE)
CHROME_CANDIDATES = [
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge",
    "/opt/google/chrome/chrome", "/usr/bin/google-chrome", "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]

# In-page JS extractor used by both Playwright page.evaluate() and Chrome headless --dump-dom
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
    const tid = tabEl ? (tabEl.getAttribute('data-testid') ? `[data-testid="${tabEl.getAttribute('data-testid')}"]` : (tabEl.id ? `#${tabEl.id}` : `[role="tab"]:nth-of-type(${idx + 1})`)) : 'main';
    return {
      viewId: `VIEW-${String(idx + 1).padStart(2, '0')}`,
      tabLabel: label,
      tabSelector: tid,
      panelId: panel && panel.id ? panel.id : (panelId || ''),
      heading: text(h) || label,
      patternType: classifyPattern(panel),
      wizardSteps: wizSteps,
      primaryActions: actionButtons,
    };
  }
  return { extractTokens, snapshotCurrentView };
})()
"""


def which_chrome() -> str | None:
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


def discover_reference_targets(root: Path, explicit_urls: list[str]) -> list[str]:
    """Collect reference URLs or local HTML file URIs from CLI flags and resources/design_references/."""
    targets: list[str] = []
    for raw_u in explicit_urls:
        u = raw_u.strip()
        if not u:
            continue
        if not u.startswith(("http://", "https://", "file://")):
            cand = Path(u).expanduser()
            if not cand.is_absolute():
                cand = (root / cand).resolve() if (root / cand).exists() else cand.resolve()
            else:
                cand = cand.resolve()
            u = cand.as_uri()
        targets.append(u)
    ref_dir = root / "resources" / "design_references"
    if not ref_dir.is_dir():
        return list(dict.fromkeys(targets))
    for p in sorted(ref_dir.rglob("*")):
        if not p.is_file() or p.name == "reference_ui_manifest.json" or p.name.startswith("."):
            continue
        ext = p.suffix.lower()
        if ext in (".html", ".htm"):
            targets.append(p.resolve().as_uri())
        elif ext in (".url", ".txt", ".md", ".json"):
            try:
                raw = dlc.read_text(p)
                if p.name.endswith(".url.json"):
                    obj = json.loads(raw)
                    if isinstance(obj, dict) and obj.get("url"):
                        targets.append(str(obj["url"]).strip())
                        continue
                for m in URL_RE.finditer(raw):
                    targets.append(m.group(0).rstrip(".,;)"))
            except Exception:
                pass
    return list(dict.fromkeys(targets))


def capture_with_playwright(url: str, shots_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Crawl a reference URL with Playwright at desktop (1440x900) and mobile (390x844) viewports."""
    from playwright.sync_api import sync_playwright  # type: ignore

    shots: list[str] = []
    views: list[dict[str, Any]] = []
    tokens: dict[str, Any] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(url, wait_until="load", timeout=30000)
            page.wait_for_timeout(200)

            tokens = page.evaluate(f"{EXTRACTOR_JS}.extractTokens()")
            tab_loc = page.locator('[role="tab"], nav a[href], .nav-tab, [data-tab]')
            tab_count = tab_loc.count()

            if tab_count == 0:
                v = page.evaluate(f"{EXTRACTOR_JS}.snapshotCurrentView(null, 0)")
                desk_p = shots_dir / "tab-01-main-desktop.png"
                page.screenshot(path=str(desk_p), full_page=True)
                v["desktopScreenshot"] = f"resources/design_references/screenshots/{desk_p.name}"
                shots.append(v["desktopScreenshot"])

                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_timeout(100)
                mob_p = shots_dir / "tab-01-main-mobile.png"
                page.screenshot(path=str(mob_p), full_page=True)
                v["mobileScreenshot"] = f"resources/design_references/screenshots/{mob_p.name}"
                shots.append(v["mobileScreenshot"])
                views.append(v)
            else:
                seen_labels: set[str] = set()
                for i in range(min(tab_count, 12)):
                    page.set_viewport_size({"width": 1440, "height": 900})
                    loc = tab_loc.nth(i)
                    if not loc.is_visible():
                        continue
                    try:
                        loc.click(timeout=2500)
                        page.wait_for_timeout(150)
                    except Exception:
                        continue
                    v = page.evaluate(
                        f"([idx]) => {{ const tabs = document.querySelectorAll('[role=\"tab\"], nav a[href], .nav-tab, [data-tab]'); return ({EXTRACTOR_JS}).snapshotCurrentView(tabs[idx], idx); }}",
                        [i],
                    )
                    lbl = str(v.get("tabLabel") or f"tab-{i + 1}").strip()
                    if lbl.lower() in seen_labels:
                        continue
                    seen_labels.add(lbl.lower())
                    idx = len(views) + 1
                    v["viewId"] = f"VIEW-{idx:02d}"
                    slug = dlc.slugify(lbl)[:32] or f"view-{idx:02d}"
                    desk_p = shots_dir / f"tab-{idx:02d}-{slug}-desktop.png"
                    page.screenshot(path=str(desk_p), full_page=True)
                    v["desktopScreenshot"] = f"resources/design_references/screenshots/{desk_p.name}"
                    shots.append(v["desktopScreenshot"])

                    page.set_viewport_size({"width": 390, "height": 844})
                    page.wait_for_timeout(100)
                    mob_p = shots_dir / f"tab-{idx:02d}-{slug}-mobile.png"
                    page.screenshot(path=str(mob_p), full_page=True)
                    v["mobileScreenshot"] = f"resources/design_references/screenshots/{mob_p.name}"
                    shots.append(v["mobileScreenshot"])
                    views.append(v)
        finally:
            browser.close()
    return tokens, views, shots


def capture_with_chrome_headless(binary: str, url: str, shots_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Fallback crawler using headless Chrome (--dump-dom + --screenshot) when Python playwright is not installed."""
    shots: list[str] = []
    views: list[dict[str, Any]] = []
    tokens: dict[str, Any] = {}
    tmp = Path(tempfile.mkdtemp(prefix="dlc-ref-capture-"))
    try:
        # 1. Capture desktop & mobile screenshots of the reference URL
        desk_p = shots_dir / "tab-01-reference-desktop.png"
        mob_p = shots_dir / "tab-01-reference-mobile.png"
        for out_png, vp in ((desk_p, "1440,900"), (mob_p, "390,844")):
            cmd = [
                binary, "--headless=new", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage",
                "--hide-scrollbars", f"--window-size={vp}", f"--screenshot={out_png}", url,
            ]
            subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if out_png.is_file():
                shots.append(f"resources/design_references/screenshots/{out_png.name}")

        # 2. If local file:// or reachable URL, inject multi-tab crawler script and dump DOM JSON
        if url.startswith("file://"):
            src_path = Path(urllib.parse.unquote(urllib.parse.urlsplit(url).path))
            raw_html = dlc.read_text(src_path) if src_path.is_file() else ""
        else:
            with urllib.request.urlopen(url, timeout=15) as r:
                raw_html = r.read().decode("utf-8", errors="replace")

        probe_script = f"""<script data-dlc="ref-crawler">
window.addEventListener('load', function() {{
  try {{
    var helper = {EXTRACTOR_JS};
    var tokens = helper.extractTokens();
    var tabs = Array.prototype.slice.call(document.querySelectorAll('[role="tab"], nav a[href], .nav-tab, [data-tab]'));
    var views = [];
    var seen = {{}};
    if (!tabs.length) {{
      views.push(helper.snapshotCurrentView(null, 0));
    }} else {{
      tabs.forEach(function(t, idx) {{
        try {{ t.click(); }} catch (e) {{}}
        var v = helper.snapshotCurrentView(t, idx);
        var k = (v.tabLabel || '').toLowerCase();
        if (k && !seen[k]) {{
          seen[k] = 1;
          v.viewId = 'VIEW-' + String(views.length + 1).padStart(2, '0');
          views.push(v);
        }}
      }});
    }}
    var s = document.createElement('script');
    s.type = 'application/json';
    s.id = '__dlc_ref_manifest';
    s.textContent = JSON.stringify({{tokens: tokens, views: views}});
    document.documentElement.appendChild(s);
  }} catch (e) {{}}
}});
</script>"""
        base_tag = f'<base href="{html_mod.escape(url)}">' if not re.search(r"<base\b", raw_html, re.I) else ""
        harness = base_tag + raw_html + probe_script
        hp = tmp / "ref_harness.html"
        hp.write_text(harness, encoding="utf-8")
        cp = subprocess.run(
            [binary, "--headless=new", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage",
             "--allow-file-access-from-files", "--virtual-time-budget=3000", "--dump-dom", hp.resolve().as_uri()],
            capture_output=True, text=True, timeout=30,
        )
        m = re.search(r'<script type="application/json" id="__dlc_ref_manifest">(.*?)</script>', cp.stdout, re.S)
        if m:
            parsed = json.loads(html_mod.unescape(m.group(1)))
            tokens = parsed.get("tokens") or {}
            views = parsed.get("views") or []
            for v in views:
                if desk_p.is_file():
                    v.setdefault("desktopScreenshot", f"resources/design_references/screenshots/{desk_p.name}")
                if mob_p.is_file():
                    v.setdefault("mobileScreenshot", f"resources/design_references/screenshots/{mob_p.name}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return tokens, views, shots


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument("--url", action="append", default=[], help="Reference portal URL or file:// URI (may be passed multiple times)")
    ap.add_argument("--output", default="resources/design_references/reference_ui_manifest.json")
    ap.add_argument("--deterministic", action="store_true")
    args = ap.parse_args()

    root = dlc.resolve_project_root(args.project_root)
    targets = discover_reference_targets(root, args.url)
    out_path = dlc.project_path(root, args.output)
    shots_dir = out_path.parent / "screenshots"

    if not targets:
        print("[dlc] No reference URLs or local HTML prototypes found in --url or resources/design_references/.")
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
                t, v, s = capture_with_playwright(url, shots_dir)
                engine = "playwright"
                merged_tokens = merged_tokens or t
                all_views.extend(v)
                all_shots.extend(s)
                continue
            except Exception as e:
                dlc.warn(f"playwright capture failed ({e}); falling back to chrome-headless")
        if chrome_bin:
            t, v, s = capture_with_chrome_headless(chrome_bin, url, shots_dir)
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
