#!/usr/bin/env python3
"""Stage 5 contract-first check — every `data-testid` the test plan declares must exist in the UI source.

Source of truth, in order:
  1. `test/.testid_contract.json` — written by Stage 4B (`05/scripts/validate_test_cases.py`):
     either a JSON list of selectors / test ids, or `{"testIds": [...]}`;
  2. otherwise derived here from every `[data-testid=…]` selector inside `test/test_cases.json#testCases[].steps`
     (plus role switcher ids implied by `setRole` steps: `role-switcher` or `role-<slug>` — either is accepted).

Searches `src/ui/**` (html, js, jsx, ts, tsx, vue, svelte, css) and any `*.html` under `src/backend/**`
(server templates). Matches `data-testid="x"`, `data-testid='x'`, `data-testid=x`, `data-testid={"x"}`,
`dataset.testid = "x"`, `setAttribute('data-testid', 'x')` and `testid: 'x'`-style object literals.

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
TESTID_IN_SELECTOR = re.compile(r"data-testid\s*[*^$|~]?=\s*[\"']?([A-Za-z0-9_.:\-]+)[\"']?")


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


def collect_source_ids(files: list[Path]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    pats = [
        re.compile(r"data-testid\s*=\s*\{?\s*[\"'`]([^\"'`]+)[\"'`]"),
        re.compile(r"data-testid\s*=\s*([A-Za-z0-9_.:\-]+)"),
        re.compile(r"dataset\.testid\s*=\s*[\"'`]([^\"'`]+)[\"'`]"),
        re.compile(r"setAttribute\(\s*[\"']data-testid[\"']\s*,\s*[\"'`]([^\"'`]+)[\"'`]"),
        re.compile(r"[\"']?testid[\"']?\s*:\s*[\"'`]([^\"'`]+)[\"'`]", re.I),
        re.compile(r"\[data-testid\s*=\s*[\"']?([A-Za-z0-9_.:\-]+)[\"']?\]"),  # querySelector usages in JS count as evidence too
    ]
    for f in files:
        txt = dlc.read_text(f)
        for rx in pats:
            for m in rx.finditer(txt):
                found.setdefault(m.group(1), set()).add(str(f))
    return found


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

    ui_files = [p for p in (root / "src" / "ui").rglob("*") if p.is_file() and p.suffix.lower() in UI_EXT] if (root / "src" / "ui").exists() else []
    tpl_files = [p for p in (root / "src" / "backend").rglob("*.html") if p.is_file()] if (root / "src" / "backend").exists() else []
    tpl_files += [p for p in (root / "src").rglob("*.html") if p.is_file() and p not in ui_files and p not in tpl_files and "node_modules" not in p.parts]
    files = ui_files + tpl_files
    if not files:
        raise dlc.GateFailure("No UI source files under src/ui/ (or templates under src/) — Stage 5 (06-coding-agent) must generate the UI first.")
    found = collect_source_ids(files)
    prefixes = collect_dynamic_prefixes(files)
    tc_p2 = dlc.project_path(root, args.test_cases)
    absence_only = absence_only_ids(dlc.read_json(tc_p2)) if tc_p2.exists() else set()

    def present(d: str) -> bool:
        return d in found or any(d.startswith(p) and len(d) > len(p) for p in prefixes)

    missing = [d for d in declared if not present(d) and d not in absence_only]
    absent_ok = [d for d in declared if not present(d) and d in absence_only]
    dynamic_ok = [d for d in declared if d not in found and present(d)]
    role_missing = [r for r in role_slugs if "role-switcher" not in found and f"role-{r}" not in found]

    print(f"=== data-testid contract check ({source}) ===")
    print(f"declared: {len(declared)} · present: {len(declared) - len(missing) - len(absent_ok)} · dynamic-prefix matches: {len(dynamic_ok)} · "
          f"absence-only (never rendered by design): {len(absent_ok)} · missing: {len(missing)} · scanned files: {len(files)}")
    for d in absent_ok:
        print(f"  · absence-only id (only asserted hidden by the test plan): {d}")
    for d in missing:
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
