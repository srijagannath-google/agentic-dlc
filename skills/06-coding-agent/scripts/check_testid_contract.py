#!/usr/bin/env python3
"""Stage 5 contract-first check — every `data-testid` the test plan declares must exist in the UI source.

Source of truth, in order:
  1. `test/.testid_contract.json` — written by Stage 4B (`05/scripts/validate_test_cases.py`):
     either a JSON list of selectors / test ids, or `{"testIds": [...]}`;
  2. otherwise derived here from every `[data-testid=…]` selector inside `test/test_cases.json#testCases[].steps`
     (plus role switcher ids implied by `setRole` steps: `role-switcher` or `role-<slug>` — either is accepted).

Searches `src/ui/**` (html, js, jsx, ts, tsx, vue, svelte, css) and any `*.html` under `src/backend/**`
(server templates); `node_modules/`, `dist/`, `build/`, `.next/`, `coverage/`, `.venv/` are never scanned (built or
vendored output is not the contract). Only ATTRIBUTE-EMITTING patterns count as an implementation:
`data-testid="x"`, `data-testid='x'`, `data-testid=x`, `data-testid={"x"}`, `'data-testid': 'x'` / `"data-testid": "x"`
inside JSX/props objects, `dataset.testid = "x"`, `setAttribute('data-testid', 'x')` and `testid="x"`-style template
helpers. Mentions in `querySelector('[data-testid=x]')`, array literals or comments are reported separately as
"weak evidence" and do NOT satisfy the contract.

Usage: python3 check_testid_contract.py --project-root <PROJECT_ROOT> [--write-derived]
Exit 1 if any declared test id is missing from the UI source.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import dlc_common as dlc  # noqa: E402

UI_EXT = {".html", ".htm", ".js", ".mjs", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".css", ".py", ".java", ".go", ".kt", ".cs", ".php", ".rb", ".erb", ".jinja", ".jinja2", ".j2", ".tpl", ".hbs", ".ejs"}
EXCLUDED_DIRS = {"node_modules", "dist", "build", ".next", ".nuxt", ".svelte-kit", "coverage", ".venv", "venv", "__pycache__", ".git", "out", "target"}
TESTID_IN_SELECTOR = re.compile(r"data-testid\s*[*^$|~]?=\s*[\"']?([A-Za-z0-9_.:\-]+)[\"']?")
_ID = r"([A-Za-z0-9_.:\-]+)"
# Attribute-emitting patterns (strong evidence — these put the attribute on an element)
STRONG_PATTERNS = [
    re.compile(r"(?<![\[\w.-])data-testid\s*=\s*\{?\s*[\"'`]" + _ID + r"[\"'`]"),       # data-testid="x" / data-testid={'x'} (not inside [...] selectors)
    re.compile(r"(?<![\[\w.-])data-testid\s*=\s*" + _ID + r"(?=[\s>/])"),               # data-testid=x (unquoted HTML attribute)
    re.compile(r"[\"']data-testid[\"']\s*:\s*[\"'`]" + _ID + r"[\"'`]"),                 # {'data-testid': 'x'} props / attrs objects
    re.compile(r"dataset\.testid\s*=\s*[\"'`]" + _ID + r"[\"'`]"),
    re.compile(r"setAttribute\(\s*[\"']data-testid[\"']\s*,\s*[\"'`]" + _ID + r"[\"'`]"),
    re.compile(r"(?<![\w.-])testid\s*=\s*[\"'`]" + _ID + r"[\"'`]"),                      # testid="x" template helpers (<Comp testid="x">)
    re.compile(r"(?<![\w.\"'-])testid\s*:\s*[\"'`]" + _ID + r"[\"'`]"),                   # testid: 'x' inside a props/attrs object literal
    re.compile(r"\b(?:testId|dataTestId|data_testid)\s*[:=]\s*[\"'`]" + _ID + r"[\"'`]"),  # React/Vue prop spellings
]
# Query / selector / comment mentions (weak evidence — they look for the attribute, they do not create it)
WEAK_PATTERNS = [
    re.compile(r"\[data-testid\s*[*^$|~]?=\s*[\"']?" + _ID + r"[\"']?\]"),
    re.compile(r"(?://|#|\*|<!--)[^\n]*?\bdata-testid\b[^\n]*?[\"'`]" + _ID + r"[\"'`]"),
]


def declared_ids_from_steps(suite: dict) -> tuple[list[str], list[str]]:
    ids: dict[str, None] = {}
    roles: dict[str, None] = {}
    for tc in suite.get("testCases") or []:
        for st in tc.get("steps") or []:
            sel = st.get("selector") or ""
            for m in TESTID_IN_SELECTOR.finditer(sel):
                ids.setdefault(m.group(1), None)
            if st.get("action") == "setRole" and st.get("value"):
                roles.setdefault(dlc.slugify(str(st["value"])), None)
    return list(ids), list(roles)


def _strip_comments(txt: str, suffix: str) -> str:
    """Blank out block/line comments so a commented-out `data-testid="x"` never counts as an implementation."""
    txt = re.sub(r"/\*.*?\*/", lambda m: " " * len(m.group(0)), txt, flags=re.S)
    txt = re.sub(r"<!--.*?-->", lambda m: " " * len(m.group(0)), txt, flags=re.S)
    txt = re.sub(r"(?m)^\s*//[^\n]*", "", txt)
    if suffix in (".py", ".rb"):
        txt = re.sub(r"(?m)^\s*#[^\n]*", "", txt)
    return txt


def collect_source_ids(files: list[Path]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Return (strong, weak): test id → files. Only `strong` (attribute-emitting) evidence satisfies the contract."""
    strong: dict[str, set[str]] = {}
    weak: dict[str, set[str]] = {}
    for f in files:
        raw = dlc.read_text(f)
        txt = _strip_comments(raw, f.suffix.lower())
        for rx in STRONG_PATTERNS:
            for m in rx.finditer(txt):
                strong.setdefault(m.group(1), set()).add(str(f))
        for rx in WEAK_PATTERNS:
            for m in rx.finditer(raw):
                weak.setdefault(m.group(1), set()).add(str(f))
    return strong, weak


# Dynamic test ids: `data-testid="open-${ref}"`, `data-testid="row-" + ref`, `dataset.testid = 'open-' + ref`,
# `setAttribute('data-testid', `queue-row-${r}`)`. Only the literal prefix (ending in '-') is visible in the source.
DYNAMIC_PATTERNS = [
    re.compile(r"data-testid\s*=\s*[\"'`]([A-Za-z0-9_.:\-]*-)\$\{"),
    re.compile(r"data-testid\s*=\s*[\"'`]([A-Za-z0-9_.:\-]*-)[\"'`]\s*\+"),
    re.compile(r"[\"']data-testid[\"']\s*:\s*[\"'`]([A-Za-z0-9_.:\-]*-)(?:\$\{|[\"'`]\s*\+)"),  # {'data-testid': 'row-' + id}
    re.compile(r"dataset\.testid\s*=\s*[\"'`]([A-Za-z0-9_.:\-]*-)(?:\$\{|[\"'`]\s*\+)"),
    re.compile(r"setAttribute\(\s*[\"']data-testid[\"']\s*,\s*[\"'`]([A-Za-z0-9_.:\-]*-)(?:\$\{|[\"'`]\s*\+)"),
]
ABSENCE_ACTIONS = {"expectHidden"}


def collect_dynamic_prefixes(files: list[Path]) -> set[str]:
    out: set[str] = set()
    for f in files:
        txt = dlc.read_text(f)
        for rx in DYNAMIC_PATTERNS:
            for m in rx.finditer(txt):
                if len(m.group(1)) >= 3:
                    out.add(m.group(1))
    return out


def absence_only_ids(suite: dict) -> set[str]:
    """Test ids that the plan only ever asserts to be absent (expectHidden / expectCount equals 0). A control that
    must never exist for any role (e.g. a system-only transition) legitimately has no markup."""
    positive: set[str] = set()
    negative: set[str] = set()
    for tc in suite.get("testCases") or []:
        for st in tc.get("steps") or []:
            ids = [m.group(1) for m in TESTID_IN_SELECTOR.finditer(st.get("selector") or "")]
            absent = st.get("action") in ABSENCE_ACTIONS or (st.get("action") == "expectCount" and st.get("equals") == 0)
            (negative if absent else positive).update(ids)
    return negative - positive


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument("--contract", default="test/.testid_contract.json")
    ap.add_argument("--test-cases", default="test/test_cases.json")
    ap.add_argument("--write-derived", action="store_true", help="Write the derived contract file if it was absent")
    args = ap.parse_args()
    root = dlc.resolve_project_root(args.project_root)
    dlc.require_gate_approved(root, "gate_4_design_and_tests", "Stage 5 (06-coding-agent / check_testid_contract.py)")

    contract_p = dlc.project_path(root, args.contract)
    role_slugs: list[str] = []
    if contract_p.exists():
        data = dlc.read_json(contract_p)
        raw = data.get("testIds", data) if isinstance(data, dict) else data
        declared = []
        for x in raw or []:
            m = TESTID_IN_SELECTOR.search(str(x))
            declared.append(m.group(1) if m else str(x).strip())
        role_slugs = list((data.get("roleSlugs") if isinstance(data, dict) else None) or [])
        source = str(contract_p.relative_to(root))
    else:
        tc_p = dlc.require_file(dlc.project_path(root, args.test_cases), "Stage 4B (05/scripts/derive_test_cases.py + testing-agent)")
        declared, role_slugs = declared_ids_from_steps(dlc.read_json(tc_p))
        source = f"derived from {tc_p.relative_to(root)} steps"
        if args.write_derived:
            dlc.write_json(contract_p, {"schemaVersion": dlc.SCHEMA_VERSION, "testIds": declared, "roleSlugs": role_slugs, "derivedFrom": str(tc_p.relative_to(root))})
    declared = list(dict.fromkeys(d for d in declared if d))

    def _scannable(p: Path) -> bool:
        return p.is_file() and not any(part in EXCLUDED_DIRS for part in p.relative_to(root).parts)

    ui_files = sorted(p for p in (root / "src" / "ui").rglob("*") if _scannable(p) and p.suffix.lower() in UI_EXT) if (root / "src" / "ui").exists() else []
    tpl_files = sorted(p for p in (root / "src" / "backend").rglob("*.html") if _scannable(p)) if (root / "src" / "backend").exists() else []
    tpl_files += sorted(p for p in (root / "src").rglob("*.html") if _scannable(p) and p not in ui_files and p not in tpl_files)
    files = ui_files + tpl_files
    if not files:
        raise dlc.GateFailure("No UI source files under src/ui/ (or templates under src/) — Stage 5 (06-coding-agent) must generate the UI first.")
    found, weak = collect_source_ids(files)
    prefixes = collect_dynamic_prefixes(files)
    tc_p2 = dlc.project_path(root, args.test_cases)
    absence_only = absence_only_ids(dlc.read_json(tc_p2)) if tc_p2.exists() else set()

    def present(d: str) -> bool:
        return d in found or any(d.startswith(p) and len(d) > len(p) for p in prefixes)

    missing = [d for d in declared if not present(d) and d not in absence_only]
    absent_ok = [d for d in declared if not present(d) and d in absence_only]
    dynamic_ok = [d for d in declared if d not in found and present(d)]
    weak_only = [d for d in missing if d in weak]  # mentioned in a selector / comment but never emitted as an attribute
    role_missing = [r for r in role_slugs if "role-switcher" not in found and f"role-{r}" not in found]

    print(f"=== data-testid contract check ({source}) ===")
    print(f"declared: {len(declared)} · present: {len(declared) - len(missing) - len(absent_ok)} · dynamic-prefix matches: {len(dynamic_ok)} · "
          f"absence-only (never rendered by design): {len(absent_ok)} · missing: {len(missing)} (weak evidence only: {len(weak_only)}) · scanned files: {len(files)}")
    for d in absent_ok:
        print(f"  · absence-only id (only asserted hidden by the test plan): {d}")
    for d in missing:
        if d in weak:
            print(f"  ✗ missing data-testid: {d}  (only referenced by a selector/comment in {', '.join(sorted(Path(x).name for x in weak[d])[:3])} — never emitted as an attribute)")
        else:
            print(f"  ✗ missing data-testid: {d}")
    for r in role_missing:
        print(f"  ✗ setRole('{r}') needs [data-testid=role-switcher] (select) or [data-testid=role-{r}] (button/tab)")
    if not declared:
        dlc.warn("no data-testid selectors are declared by the test plan — Stage 4B should declare them contract-first (steps use CSS selectors on data-testid)")
    if missing or role_missing:
        raise dlc.GateFailure(f"{len(missing) + len(role_missing)} declared test id(s) are not implemented in the UI. Stage 5 must implement the test plan's data-testid contract (never rename them in the tests).")
    print("TESTID CONTRACT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
