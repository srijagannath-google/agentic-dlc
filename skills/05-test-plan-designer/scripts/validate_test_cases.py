#!/usr/bin/env python3
"""Gate 4b — validate `test/test_cases.json` (05-test-plan-designer).

Checks: schema (schemas/test_cases.schema.json, stdlib validator), freshness against stories/spec, every AC of
every story covered by a TC, no TC with `needsSteps: true` or empty `steps` (the Gate 4b condition), every step
action allowed with the fields it needs, non-empty selectors, and writes `test/.testid_contract.json` — the
sorted unique list of `[data-testid=…]` hooks the coding agent must implement (contract-first).

Usage:
    python3 validate_test_cases.py --project-root <PROJECT_ROOT> [--file test/test_cases.json] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import dlc_common as dlc  # noqa: E402

SELECTOR_ACTIONS = {"fill", "select", "click", "expectText", "expectVisible", "expectHidden", "expectDisabled", "expectEnabled", "expectCount",
                    "check", "uncheck", "expectAttribute"}
NEEDS_VALUE = {"fill", "select", "setRole"}
TESTID_RE = re.compile(r"\[data-testid\s*=\s*[\"']?([^\]\"']+)[\"']?\]")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument("--file", default="test/test_cases.json")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = dlc.resolve_project_root(args.project_root)
    path = dlc.require_file(dlc.project_path(root, args.file), "Stage 4B (05/scripts/derive_test_cases.py, then the LLM completes steps)")
    data = dlc.read_json(path)
    schema = dlc.load_schema("test_cases.schema.json")
    stories = dlc.load_stories(root)

    fails: list[str] = []
    warns: list[str] = []
    fails += [f"schema: {e}" for e in dlc.validate_against_schema(data, schema)]
    tcs = data.get("testCases", []) if isinstance(data, dict) else []
    allowed_actions = set(schema["$defs"]["step"]["properties"]["action"]["enum"])

    # Freshness (accept either raw file sha256 or content sha256 ignoring mutable ALM status/key fields)
    df = data.get("derivedFrom", {}) if isinstance(data, dict) else {}
    stories_p = root / "backlog" / "user_stories.json"
    valid_stories_shas = {dlc.sha256_file(stories_p), dlc.stories_content_sha256(stories_p)}
    if df.get("userStoriesSha256") not in valid_stories_shas:
        fails.append("stale: backlog/user_stories.json changed since derivation — re-run 05/scripts/derive_test_cases.py (authored steps are preserved).")
    spec_p = root / "specs" / "application_spec.md"
    if spec_p.exists() and df.get("specSha256") != dlc.sha256_file(spec_p):
        fails.append("stale: specs/application_spec.md changed since derivation — re-run 05/scripts/derive_test_cases.py.")

    # Ids unique
    ids = [t.get("id") for t in tcs]
    for d in sorted({i for i in ids if ids.count(i) > 1}):
        fails.append(f"duplicate test id {d}")

    # AC coverage
    covered = {(t.get("storyRef"), t.get("acRef")) for t in tcs}
    story_ids = set()
    for s in stories:
        story_ids.add(s["id"])
        for ac in s.get("acceptanceCriteria", []):
            if (s["id"], ac["id"]) not in covered:
                fails.append(f"no test case for {s['id']}/{ac['id']} ({ac['tag']})")
    for t in tcs:
        if t.get("storyRef") and t["storyRef"] not in story_ids:
            warns.append(f"{t.get('id')}: storyRef {t['storyRef']} not in backlog")

    # Steps (skip step requirement on test cases deferred by capability group selection when selectedCapabilityGroups != ['ALL'])
    needing = []
    deferred_by_group = []
    testids: set[str] = set()
    for t in tcs:
        tid = t.get("id", "?")
        steps = t.get("steps") or []
        if t.get("deferredByGroupSelection"):
            deferred_by_group.append(tid)
            continue
        if t.get("needsSteps") or not steps:
            needing.append(tid)
        for i, st in enumerate(steps):
            a = st.get("action")
            if a not in allowed_actions:
                fails.append(f"{tid} step {i}: unknown action {a!r}")
                continue
            if a in SELECTOR_ACTIONS:
                sel = str(st.get("selector", "")).strip()
                if not sel:
                    fails.append(f"{tid} step {i}: '{a}' requires a non-empty selector")
                else:
                    testids.update(TESTID_RE.findall(sel))
            if a in NEEDS_VALUE and not str(st.get("value", "")).strip():
                fails.append(f"{tid} step {i}: '{a}' requires a value")
            if a == "expectText" and not (st.get("contains") or st.get("equals") is not None):
                fails.append(f"{tid} step {i}: expectText needs 'contains' or 'equals'")
            if a == "expectCount" and not any(isinstance(st.get(k), int) and not isinstance(st.get(k), bool) for k in ("equals", "min", "max")):
                fails.append(f"{tid} step {i}: expectCount needs an integer 'equals', 'min' or 'max'")
            if a == "expectNoVisibleTextMatching":
                try:
                    re.compile(str(st.get("pattern", "")))
                except re.error as e:
                    fails.append(f"{tid} step {i}: invalid regex pattern ({e})")
                if not st.get("pattern"):
                    fails.append(f"{tid} step {i}: expectNoVisibleTextMatching needs 'pattern'")
            if a == "httpRequest":
                for k in ("method", "path", "expectStatus"):
                    if k not in st:
                        fails.append(f"{tid} step {i}: httpRequest needs '{k}'")
                if t.get("runtime") != "http":
                    warns.append(f"{tid}: httpRequest step inside a '{t.get('runtime')}' test — runtime should be 'http'")
            if a == "goto" and not st.get("target"):
                fails.append(f"{tid} step {i}: goto needs 'target' ('ui' or a URL)")
            if a == "wait" and not isinstance(st.get("ms"), int):
                fails.append(f"{tid} step {i}: wait needs integer 'ms'")
        if t.get("runtime") == "browser" and steps and steps[0].get("action") != "goto":
            warns.append(f"{tid}: browser test should start with a 'goto' step")

        # Tab-exclusivity rule: any tab-navigation test case (TC-UI-INTERACT-TAB-* or any test clicking [role="tab"]
        # or an Interact test clicking a tab-* selector) must assert expectHidden on at least one sibling panel.
        tab_click_indices = [
            idx for idx, st in enumerate(steps)
            if st.get("action") == "click" and (
                re.search(r"role\s*=\s*[\"']?tab[\"']?", str(st.get("selector", "")), re.IGNORECASE)
                or (
                    (tid.startswith("TC-UI-INTERACT-TAB-") or t.get("category") == "Interact")
                    and re.search(r"data-testid\s*=\s*[\"']?tab-|\btab\b", str(st.get("selector", "")), re.IGNORECASE)
                )
            )
        ]
        if tid.startswith("TC-UI-INTERACT-TAB-") and not tab_click_indices and steps:
            fails.append(f"{tid}: tab exclusivity test must include a 'click' step targeting its navigation tab")
        for c_idx in tab_click_indices:
            subsequent = steps[c_idx + 1:]
            if not any(s.get("action") == "expectHidden" for s in subsequent):
                fails.append(f"{tid} step {c_idx}: clicking a navigation tab ({steps[c_idx].get('selector')!r}) must assert 'expectHidden' on at least one previously active sibling panel")

        # Default landing persona journey rule: TC-POS-JOURNEY-01 must not call setRole before triggering the entry transition
        if tid == "TC-POS-JOURNEY-01":
            if any(s.get("action") == "setRole" for s in steps):
                fails.append("TC-POS-JOURNEY-01: default landing persona journey must walk from initial goto('ui') to primary transition CTA without calling 'setRole'")

    # Check presence of TC-POS-JOURNEY-01 and TC-UI-INTERACT-TAB-* when spec defines §4.2 views and frontend != none
    stack = dlc.load_target_stack(root)
    frontend_kind = (stack.get("frontend") or {}).get("kind", "static-html")
    if frontend_kind != "none":
        if "TC-POS-JOURNEY-01" not in ids:
            fails.append("missing TC-POS-JOURNEY-01 (Default Landing Persona Entry-to-Submit Journey) — re-run 05/scripts/derive_test_cases.py")
        if spec_p.exists():
            views = dlc.parse_view_topology(dlc.read_text(spec_p))
            if len(views) >= 2:
                tab_tcs = [i for i in ids if str(i).startswith("TC-UI-INTERACT-TAB-")]
                if len(tab_tcs) < len(views):
                    fails.append(f"spec §4.2 defines {len(views)} views, but only {len(tab_tcs)} TC-UI-INTERACT-TAB-* test(s) exist — re-run 05/scripts/derive_test_cases.py")

    if needing:
        fails.append(f"Gate 4b: {len(needing)} test case(s) still need steps (needsSteps=true or empty steps): "
                     + ", ".join(needing[:40]) + (" …" if len(needing) > 40 else ""))

    contract = {"schemaVersion": dlc.SCHEMA_VERSION, "sourceSha256": dlc.sha256_file(path),
                "testIds": sorted(testids), "selectors": [f"[data-testid={t}]" for t in sorted(testids)]}
    dlc.write_json(root / "test" / ".testid_contract.json", contract)

    result = {"passed": not fails, "testCases": len(tcs), "needingSteps": needing, "testIds": len(testids), "failures": fails, "warnings": warns}
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for w in warns:
            dlc.warn(w)
        for f in fails:
            print(f"  ✗ {f}")
        print(f"[dlc] Gate 4b test cases: {'PASS' if not fails else 'FAIL'} — {len(tcs)} TCs, {len(needing)} need steps, "
              f"{len(testids)} data-testid hooks -> test/.testid_contract.json")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
