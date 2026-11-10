#!/usr/bin/env python3
"""Stage 4B — derive the executable test-case skeleton (05-test-plan-designer).

Implements docs/ARCHITECTURE.md §4.6 and _shared/workflow_chain_of_custody.md Stage 4B. Everything is derived
from upstream artefacts — stories (backlog/user_stories.json), the frozen state machine and roles
(specs/application_spec.md §3.3/§3.5), contracts (design/.contracts_index.json, src/db/schema.sql) and the
input inventory. The LLM then completes `steps` for every TC with `needsSteps: true` and writes test_plan.md.

Idempotent: if test/test_cases.json already exists, authored `steps` are preserved for test cases with the same
`derivationKey` (or id), and test cases that are no longer derived are recorded under `retiredTestCases`.

Usage:
    python3 derive_test_cases.py --project-root <PROJECT_ROOT> [--output test/test_cases.json] [--deterministic]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import dlc_common as dlc  # noqa: E402

# Shared legacy-identifier classification lives next to the DDL legacy check (04/extract_contracts.py) so both
# gates agree on what is a real legacy object name (FAIL) vs. a bare file stem (WARN). Follow-up: move to dlc_common.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "04-solution-architect" / "scripts"))
from extract_contracts import legacy_identifier_sets  # noqa: E402

CATEGORY_PREFIX = {"Positive": "POS", "Negative": "NEG", "Edge": "EDGE", "State": "STATE", "Interact": "UI-INTERACT",
                   "UiLeak": "UI-LEAK", "A11y": "A11Y", "Api": "API", "Parity": "PARITY"}
ENGINEERING_NOTE_PATTERNS = [r"\bTODO\b", r"\bFIXME\b", r"\bparity\b", r"\bTraceback\b", r"\bSELECT\s+.+\s+FROM\b",
                             r"\bNullPointer|\bundefined is not\b", r"/api/[a-z0-9_/{}-]+", r"\blorem ipsum\b"]
UUID_PATTERN = r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
# HTTP methods that get a derived smoke test; HEAD/OPTIONS are contract metadata, not business operations, and are
# outside the httpRequest.method enum in schemas/test_cases.schema.json.
API_SMOKE_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
DEFERRED_STEP_NOTE = ("Deferred: the parent story's capability group is not in specs/target_stack.json#selectedCapabilityGroups "
                      "— not executed in this increment; steps are authored when the group is scheduled.")
SKELETON_STEP_NOTE = "Skeleton seed — replace or extend this step with concrete actions and at least one assertion."


def to_upper_snake(s: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", s.upper()).strip("_")


def word_regex(tokens: list[str]) -> str:
    return r"(?<![A-Za-z0-9_])(?:" + "|".join(re.escape(t) for t in tokens) + r")(?![A-Za-z0-9_])"


class Counter:
    def __init__(self) -> None:
        self.n: dict[str, int] = {}

    def next_id(self, category: str) -> str:
        p = CATEGORY_PREFIX[category]
        self.n[p] = self.n.get(p, 0) + 1
        return f"TC-{p}-{self.n[p]:02d}"


def tc(counter: Counter, category: str, title: str, expected: str, runtime: str, key: str, *, story: str | None = None,
       ac: str | None = None, reqs: list[str] | None = None, role: str | None = None, steps: list[dict] | None = None,
       derivation: dict | None = None, tc_id: str | None = None) -> dict[str, Any]:
    needs_steps = not steps
    if needs_steps:
        # Skeleton seed only (schemas/test_cases.schema.json requires >= 1 step): every UI test starts by opening the
        # application; the testing-agent replaces/extends it with real actions and >= 1 assertion (Gate 4b).
        steps = [{"action": "goto", "target": "ui", "note": SKELETON_STEP_NOTE}]
    return {
        "id": tc_id or counter.next_id(category), "category": category, "storyRef": story, "acRef": ac,
        "requirementRefs": reqs or [], "title": title, "expected": expected, "runtime": runtime, "role": role,
        "needsSteps": needs_steps, "derivationKey": key, "derivation": derivation or {}, "steps": steps,
    }


def collect_pii_patterns(spec: str) -> list[str]:
    """Opportunistic: regexes written in backticks inside the Security pillar (e.g. `\\d{3}-\\d{2}-\\d{4}`)."""
    sec = dlc.md_section(spec, r"pillar\s*2") or spec
    out = []
    for m in re.finditer(r"`([^`\n]{4,80})`", sec):
        cand = m.group(1)
        if re.search(r"\\d|\[0-9\]|\{\d", cand):
            try:
                re.compile(cand)
                out.append(cand)
            except re.error:
                pass
    return list(dict.fromkeys(out))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument("--output", default="test/test_cases.json")
    ap.add_argument("--group-state-tests", action="store_true",
                    help="Group illegal (state, trigger) pairs per trigger and unauthorized (role, trigger) pairs per role into matrix TCs")
    ap.add_argument("--deterministic", action="store_true")
    args = ap.parse_args()

    root = dlc.resolve_project_root(args.project_root)
    dlc.require_gate_approved(root, "gate_3_backlog", "Stage 4B (05-test-plan-designer / derive_test_cases.py)", deterministic=args.deterministic)
    inv = dlc.load_inventory(root)
    legacy = inv.get("inputScenario") == "SCENARIO_LEGACY_APP"
    stories = dlc.load_stories(root)
    # Content hash ignoring mutable ALM runtime fields (status, jiraKey, …) so board syncs do not make tests stale.
    stories_sha = dlc.stories_content_sha256(root / "backlog" / "user_stories.json")
    spec_path = root / "specs" / "application_spec.md"
    spec = dlc.load_spec(root)
    spec_sha = dlc.sha256_file(spec_path)
    sm = dlc.parse_state_machine(spec)
    if not sm.transitions:
        raise dlc.GateFailure("specs/application_spec.md §3.3 has no parsable transition table — fix the spec (run 02/scripts/lint_spec_structure.py).")
    roles = dlc.parse_roles(spec)
    if not roles:
        raise dlc.GateFailure("specs/application_spec.md §3.5 Roles table missing — fix the spec (run 02/scripts/lint_spec_structure.py).")
    views = dlc.parse_view_topology(spec)
    stack = dlc.load_target_stack(root)
    backend_kind = (stack.get("backend") or {}).get("kind", "none")
    frontend_kind = (stack.get("frontend") or {}).get("kind", "static-html")
    ui_runtime = "browser" if frontend_kind != "none" else "http"

    ci_path = root / "design" / ".contracts_index.json"
    contracts = dlc.read_json(ci_path) if ci_path.exists() else None
    if contracts is None:
        dlc.warn("design/.contracts_index.json missing (run 04/scripts/extract_contracts.py) — schema identifiers and API tests will be incomplete; re-run after Stage 4A.")

    # ---------------------------------------------------------------- forbidden tokens
    schema_ids: list[str] = []
    ignored: list[str] = []
    if contracts:
        for t in contracts.get("tables", []):
            schema_ids.append(t["name"])
            schema_ids += t.get("columns", [])
        schema_ids += contracts.get("internalFields", [])
    else:
        ddl = root / "src" / "db" / "schema.sql"
        if ddl.exists():
            txt = dlc.read_text(ddl)
            schema_ids += re.findall(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?(\w+)", txt, re.IGNORECASE)
    kept = []
    for s in dict.fromkeys(schema_ids):
        if "_" in s or any(ch.isdigit() for ch in s):
            kept.append(s)
        else:
            ignored.append(s)  # single plain words (a table/column literally named like a UI label) -> false positives
    schema_ids = sorted(kept)

    # Raw codes: UPPER_SNAKE forms of every state and trigger (never rendered — labels from spec §3.3 are) + OpenAPI enums.
    # Multi-word codes (IN_REVIEW, SUBMIT_FOR_APPROVAL) are unmistakable machine tokens -> FAIL-level `enumCodes`.
    # Single-word codes (DRAFT, APPROVED, SUBMIT) collide with legitimate upper-case words in headings/buttons/legal
    # text -> warn-only `enumCodesWarnOnly` (the eval runner reads both keys from forbiddenUiTokens).
    enum_codes: list[str] = []
    enum_warn_only: list[str] = []
    for code in [to_upper_snake(s) for s in sm.states] + [to_upper_snake(t) for t in sm.triggers()]:
        if not code:
            continue
        (enum_codes if "_" in code else enum_warn_only).append(code)
    if contracts:
        for e in contracts.get("enums", []):
            e = str(e)
            if not re.fullmatch(r"[A-Z][A-Z0-9_]+", e) or e in enum_codes or e in enum_warn_only:
                continue
            (enum_codes if "_" in e else enum_warn_only).append(e)
    enum_codes = sorted(dict.fromkeys(enum_codes))
    enum_warn_only = sorted(dict.fromkeys(enum_warn_only))

    legacy_ids: list[str] = []
    legacy_ids_warn: list[str] = []
    if legacy:
        fail_set, warn_set = legacy_identifier_sets(inv)
        # keep original casing for readable regexes; classification is case-insensitive via the shared helper
        originals = {str(n).lower(): str(n) for n in inv.get("legacyObjectNames", [])}
        stems_raw = inv.get("legacyFileStems")
        if not isinstance(stems_raw, list):
            stems_raw = [Path(str(f.get("name", ""))).stem for f in inv.get("files", []) if str(f.get("category", "")).startswith("legacy_")]
        originals.update({str(s).lower(): str(s) for s in stems_raw if str(s).lower() not in originals})
        legacy_ids = [originals.get(x, x) for x in fail_set]
        legacy_ids_warn = [originals.get(x, x) for x in warn_set]
    legacy_ids = sorted(dict.fromkeys(x for x in legacy_ids if len(x) >= 3))
    legacy_ids_warn = sorted(dict.fromkeys(x for x in legacy_ids_warn if len(x) >= 3))
    pii_patterns = collect_pii_patterns(spec)
    forbidden = {"schemaIdentifiers": schema_ids, "schemaIdentifiersIgnored": sorted(ignored), "enumCodes": enum_codes,
                 "enumCodesWarnOnly": enum_warn_only,
                 "legacyIdentifiers": legacy_ids, "legacyIdentifiersWarnOnly": legacy_ids_warn,
                 "piiPatterns": pii_patterns, "engineeringNotePatterns": ENGINEERING_NOTE_PATTERNS}

    # ---------------------------------------------------------------- derive
    counter = Counter()
    tcs: list[dict[str, Any]] = []
    role_names = [r["role"] for r in roles]
    external_roles = [r["role"] for r in roles if r["kind"] == "external"]

    # Generic interact + a11y first so TC-UI-INTERACT-01 / TC-A11Y-01 are stable ids
    tcs.append(tc(counter, "Interact", "Every interactive control is wired to a handler and produces a DOM change",
                  "Every button, tab, link-button, select and drop-zone has a bound handler; activating it changes the DOM "
                  "(state badge, view, validation banner or list). Zero dead controls.", "static", "generic:interact",
                  steps=[{"action": "goto", "target": "ui"}, {"action": "expectAllControlsWired"}]))
    # Mutual Tab Exclusivity & Layout Switching tests (TC-UI-INTERACT-TAB-01..N) from §4.2 View & Component Topology
    default_role = external_roles[0] if external_roles else (role_names[0] if role_names else None)
    if ui_runtime == "browser" and len(views) >= 2:
        view_slugs = [re.sub(r"[^a-z0-9]+", "-", v["viewId"].lower()).strip("-") for v in views]
        for idx, v in enumerate(views):
            v_slug = view_slugs[idx]
            tab_sel = f"[data-testid=tab-{v_slug}]"
            panel_sel = f"[data-testid=panel-{v_slug}]"
            sib_panels = [f"[data-testid=panel-{s}]" for j, s in enumerate(view_slugs) if j != idx]
            b_roles = v.get("boundRoles") or []
            needs_role_switch = bool(
                b_roles
                and default_role
                and default_role.lower() not in {r.lower() for r in b_roles}
                and "all" not in {r.lower() for r in b_roles}
            )
            tab_steps: list[dict[str, Any]] = [{"action": "goto", "target": "ui"}]
            if needs_role_switch:
                tab_steps.append({"action": "setRole", "value": b_roles[0]})
            tab_steps += [
                {"action": "click", "selector": tab_sel},
                {"action": "expectAttribute", "selector": tab_sel, "attribute": "aria-selected", "equals": "true"},
                {"action": "expectVisible", "selector": panel_sel},
            ] + [{"action": "expectHidden", "selector": sib} for sib in sib_panels]
            tcs.append(tc(
                counter, "Interact",
                f"Mutual tab exclusivity & layout switching: '{v['tabLabel']}' ({v['viewId']}) shows its panel and hides all sibling panels",
                f"Clicking tab '{v['tabLabel']}' ({tab_sel}) sets aria-selected='true', renders {panel_sel} with a non-zero bounding box, "
                f"and hides all sibling tab panels ({', '.join(sib_panels)}).",
                ui_runtime, f"tab:{v['viewId']}",
                reqs=["REQ-UX-01"],
                role=b_roles[0] if b_roles else default_role,
                steps=tab_steps,
                derivation={"viewId": v["viewId"], "tabLabel": v["tabLabel"], "uiPattern": v["uiPattern"],
                            "tabSelector": tab_sel, "panelSelector": panel_sel, "siblingPanels": sib_panels},
                tc_id=f"TC-UI-INTERACT-TAB-{idx + 1:02d}",
            ))
    tcs.append(tc(counter, "A11y", "Accessibility baseline: labels, names, roles, landmarks, live regions",
                  "Every input has a bound label; icon-only buttons have accessible names; one main landmark and a "
                  "heading hierarchy exist; status/validation regions use aria-live/role=alert; no positive tabindex.",
                  "static", "generic:a11y", steps=[{"action": "goto", "target": "ui"}, {"action": "expectA11yBaseline"}]))

    # One TC per AC (honouring specs/target_stack.json#selectedCapabilityGroups: specific GRP-* vs. ALL)
    is_all, selected_groups = dlc.active_capability_groups(root)
    for s in stories:
        sid = s.get("id", "US-?")
        reqs = list(s.get("requirementRefs", []))
        s_roles = s.get("roles") or []
        role = s_roles[0] if len(s_roles) == 1 else None
        cg = str(s.get("capabilityGroup") or "").strip().upper() or None
        in_selected = dlc.is_story_in_selected_group(s, is_all, selected_groups)
        for ac in s.get("acceptanceCriteria", []):
            cat = dlc.ac_category(ac["tag"])
            title = f"{sid}/{ac['id']} [{ac['tag']}] {ac['when'] or ac['then']}".strip()
            expected = ac["then"] or "(see acceptance criterion)"
            t_item = tc(counter, cat, title[:200], expected, ui_runtime, f"ac:{sid}/{ac['id']}", story=sid, ac=ac["id"],
                        reqs=reqs, role=role, derivation={"tag": ac["tag"], "given": ac["given"], "when": ac["when"]})
            if cg:
                t_item["capabilityGroup"] = cg
            if not in_selected:
                # Not executed this increment; a single annotated goto keeps the record schema-valid (steps.minItems=1)
                # without inventing assertions. validate_test_cases.py recomputes deferral from target_stack.json.
                t_item["optional"] = True
                t_item["deferredByGroupSelection"] = True
                t_item["needsSteps"] = False
                t_item["steps"] = [{"action": "goto", "target": "ui", "note": DEFERRED_STEP_NOTE}]
            tcs.append(t_item)

    # Synthesised state tests: illegal (state, trigger) pairs. Triggers that only originate from the pseudo-state
    # [*] create a record (they have no "current state") and are covered by the (role, trigger) tests below.
    creation_triggers = {t.trigger for t in sm.transitions if t.src == "[*]"} - {t.trigger for t in sm.transitions if t.src != "[*]"}
    illegal_pairs = [(st_name, tr_name) for st_name, tr_name in sm.illegal_pairs() if tr_name not in creation_triggers]
    if args.group_state_tests:
        by_trig: dict[str, list[str]] = {}
        for st_name, tr_name in illegal_pairs:
            by_trig.setdefault(tr_name, []).append(st_name)
        for trig, states_list in by_trig.items():
            owners = sorted({r for t in sm.transitions if t.trigger == trig for r in t.roles})
            t_grp = tc(
                counter, "State",
                f"Blocked matrix: '{trig}' must not be possible in states {', '.join(states_list)}",
                f"Across non-eligible states ({', '.join(states_list)}), '{trig}' is hidden or disabled for every role "
                f"({', '.join(owners) or 'all roles'}) and any direct request leaves the state unchanged.",
                ui_runtime, f"illegal-group:{trig}", role=owners[0] if owners else None,
                derivation={"trigger": trig, "blockedStates": states_list, "ownerRoles": owners},
            )
            t_grp["matrixCases"] = [{"state": st_name, "trigger": trig} for st_name in states_list]
            tcs.append(t_grp)
        for r in role_names:
            unauth_trigs: list[dict[str, Any]] = []
            for trig in sm.triggers():
                owners = {x.lower() for t in sm.transitions if t.trigger == trig for x in t.roles}
                if r.lower() in owners:
                    continue
                legal_from = sorted({t.src for t in sm.transitions if t.trigger == trig})
                unauth_trigs.append({"role": r, "trigger": trig, "legalFrom": legal_from})
            if unauth_trigs:
                tr_labels = ", ".join(x["trigger"] for x in unauth_trigs)
                t_role = tc(
                    counter, "State",
                    f"Role matrix: '{r}' must not see or invoke unauthorized controls ({tr_labels})",
                    f"Signed in as '{r}', unauthorized controls ({tr_labels}) are never rendered and direct attempts are rejected.",
                    ui_runtime, f"role-group:{r}", role=r,
                    derivation={"role": r, "unauthorizedTriggers": unauth_trigs},
                )
                t_role["matrixCases"] = unauth_trigs
                tcs.append(t_role)
    else:
        for state, trig in illegal_pairs:
            owners = sorted({r for t in sm.transitions if t.trigger == trig for r in t.roles})
            tcs.append(tc(counter, "State", f"Blocked: '{trig}' must not be possible while the record is '{state}'",
                          f"With a record in state '{state}', the control for '{trig}' is hidden or disabled for every role "
                          f"({', '.join(owners) or 'all roles'}); any attempt leaves the state '{state}' and shows a user-readable reason.",
                          ui_runtime, f"illegal:{state}/{trig}", role=owners[0] if owners else None,
                          derivation={"state": state, "trigger": trig, "ownerRoles": owners}))
        # Synthesised state tests: (role, trigger) the role does not own
        for r in role_names:
            for trig in sm.triggers():
                owners = {x.lower() for t in sm.transitions if t.trigger == trig for x in t.roles}
                if r.lower() in owners:
                    continue
                legal_from = sorted({t.src for t in sm.transitions if t.trigger == trig})
                tcs.append(tc(counter, "State", f"Role '{r}' must not see or use the '{trig}' control",
                              f"Signed in as '{r}' viewing a record in {', '.join(legal_from) or 'any state'}, no '{trig}' control is "
                              f"rendered{' (external role — internal controls never appear on external views)' if r in external_roles else ''}; "
                              f"a direct attempt is rejected with a user-readable message and no state change.",
                              ui_runtime, f"role:{r}/{trig}", role=r, derivation={"role": r, "trigger": trig, "legalFrom": legal_from}))

    # Default Landing Persona Entry-to-Submit Journey (TC-POS-JOURNEY-01) without setRole override
    if ui_runtime == "browser":
        init_state = sm.initial[0] if sm.initial else (sm.states[0] if sm.states else "Draft")
        entry_transitions = [t for t in sm.transitions if t.src == init_state] or [t for t in sm.transitions if t.src == "[*]"]
        first_trig = entry_transitions[0].trigger if entry_transitions else "Submit"
        next_state = entry_transitions[0].dst if entry_transitions else "Submitted"
        tcs.append(tc(
            counter, "Positive",
            f"Default landing persona ({default_role or 'primary'}) entry-to-{first_trig.lower().replace(' ', '-')} journey without setRole override",
            f"Starting from a fresh goto('ui') without calling setRole, the default landing persona ('{default_role or 'primary'}') "
            f"sees the initial state ('{init_state}'), steps through any multi-step wizard, clicks '{first_trig}', and transitions the record to '{next_state}'.",
            ui_runtime, "journey:default-persona",
            reqs=["REQ-UX-01"],
            role=default_role,
            derivation={"defaultRole": default_role, "initialState": init_state, "trigger": first_trig, "nextState": next_state},
            tc_id="TC-POS-JOURNEY-01",
        ))

    # UI leak tests (fully specified; static)
    def leak(title: str, expected: str, key: str, patterns: list[str], note: str = "") -> dict[str, Any]:
        steps = [{"action": "goto", "target": "ui"}] + [{"action": "expectNoVisibleTextMatching", "pattern": p} for p in patterns]
        t = tc(counter, "UiLeak", title, expected, "static", key, steps=steps if patterns else [])
        if not patterns:
            t["derivation"] = {"note": note}
        return t

    tcs.append(leak("Zero database table/column identifiers in visible UI text",
                    f"None of the {len(schema_ids)} schema identifiers appears in rendered visible text (attributes such as data-testid are allowed).",
                    "leak:schema", [word_regex(schema_ids)] if schema_ids else [],
                    "no schema identifiers known — run 04/scripts/extract_contracts.py then re-derive, or add patterns"))
    tcs.append(leak("Zero raw enum / state / error codes in visible UI text",
                    "No UPPER_SNAKE_CASE state, trigger or error code is rendered; the human label from spec §3.3 is shown instead.",
                    "leak:enum", [word_regex(enum_codes)] if enum_codes else [],
                    "no multi-word UPPER_SNAKE codes in the state machine / OpenAPI enums — single-word codes are warn-only "
                    "(forbiddenUiTokens.enumCodesWarnOnly); add steps or set optional:true with a reason"))
    tcs.append(leak("Zero internal UUIDs, primary keys, legacy identifiers or engineering notes in visible UI text",
                    "No UUIDs, raw numeric primary keys labelled as ids, legacy object names, 'parity'/'TODO' notes, SQL or API paths are visible.",
                    "leak:legacy", [UUID_PATTERN] + ([word_regex(legacy_ids)] if legacy_ids else []) + ENGINEERING_NOTE_PATTERNS))
    tcs.append(leak("Zero unmasked sensitive identifiers (PII) in visible UI text",
                    "Sensitive identifiers listed in spec Pillar 2 render only in their masked form.",
                    "leak:pii", pii_patterns,
                    "no PII regex found in spec Pillar 2 (write patterns in backticks, e.g. `\\d{3}-\\d{2}-\\d{4}`) — add steps or set optional:true with a reason"))

    # API smoke tests
    if backend_kind != "none" and contracts and contracts.get("paths"):
        skipped_methods: list[str] = []
        for p in contracts["paths"]:
            method, path, op = p["method"], p["path"], p.get("operationId") or ""
            if method not in API_SMOKE_METHODS:
                skipped_methods.append(f"{method} {path}")
                continue
            has_params = "{" in path
            if method == "GET":
                status: Any = 200
            elif method == "POST":
                status = [201, 200, 400]
            elif method in ("PUT", "PATCH"):
                status = [200, 204, 400]
            else:
                status = [200, 204, 404]
            step = {"action": "httpRequest", "method": method, "path": path, "expectStatus": status}
            if method in ("POST", "PUT", "PATCH"):
                step["json"] = {}
            t = tc(counter, "Api", f"{method} {path}{' (' + op + ')' if op else ''} responds per contract",
                   f"{method} {path} returns {status}; 4xx bodies carry a user-readable message; transition endpoints validate (fromState, trigger, role).",
                   "http", f"api:{method} {path}", steps=[step], derivation={"method": method, "path": path, "operationId": op})
            t["needsSteps"] = has_params or method != "GET"  # LLM must add ids / payloads
            tcs.append(t)
        if skipped_methods:
            dlc.info(f"no TC-API-* derived for HEAD/OPTIONS operations (metadata, not business operations): {', '.join(skipped_methods[:6])}")
    elif backend_kind != "none":
        dlc.warn("backend.kind != none but no OpenAPI operations in design/.contracts_index.json — no TC-API-* derived.")

    # Structured Business-Rule Decision Vectors (`TC-EDGE-BR-*`) from `specs/application_spec.md` §3.4 `Examples` column
    for br in dlc.parse_business_rules(spec):
        rid = str(br.get("id") or "").strip()
        vectors = br.get("parsedExamples") or []
        for v_idx, vec in enumerate(vectors, 1):
            inp_str = vec.get("input", "")
            exp_str = vec.get("expected", "")
            t_br = tc(
                counter,
                "Edge",
                f"{rid} decision vector #{v_idx}: given ({inp_str}) => expected ({exp_str})"[:200],
                f"Evaluating business rule {rid} ({br.get('rule', '').strip()}) on ({inp_str}) produces ({exp_str})."[:300],
                ui_runtime,
                f"br-vector:{rid}#{v_idx}",
                reqs=[rid],
                derivation={"ruleId": rid, "formula": br.get("rule", ""), "input": inp_str, "expected": exp_str},
                tc_id=f"TC-EDGE-{rid}-{v_idx:02d}",
            )
            tcs.append(t_br)

    # Differential Behavioral Parity Oracles (`TC-PARITY-*`) from `test/legacy_parity_goldens.jsonl`
    parity_jsonl = root / "test" / "legacy_parity_goldens.jsonl"
    if parity_jsonl.is_file():
        for line_idx, raw_line in enumerate(dlc.read_text(parity_jsonl).splitlines(), 1):
            s_line = raw_line.strip()
            if not s_line or s_line.startswith("#"):
                continue
            try:
                rec = json.loads(s_line)
            except json.JSONDecodeError as exc:
                raise dlc.GateFailure(f"Invalid JSON on line {line_idx} of {parity_jsonl}: {exc}") from exc
            if not isinstance(rec, dict):
                continue
            op_name = str(rec.get("operation") or rec.get("path") or f"case-{line_idx}").strip()
            div_ref = str(rec["intentionalDivergenceRef"]).strip() if rec.get("intentionalDivergenceRef") else None
            legacy_out = rec.get("legacyExpectedOutput")
            modern_out = rec.get("modernExpectedOutput") if div_ref and "modernExpectedOutput" in rec else legacy_out
            p_path = str(rec.get("path") or "").strip()
            p_method = str(rec.get("method") or "POST").upper()
            p_runtime = "http" if (p_path.startswith("/") and backend_kind != "none") else ui_runtime
            p_steps: list[dict[str, Any]] | None = None
            if p_runtime == "http" and p_path:
                st_obj: dict[str, Any] = {
                    "action": "httpRequest",
                    "method": p_method,
                    "path": p_path,
                    "expectStatus": rec.get("expectStatus", [200, 201]),
                }
                if rec.get("input") is not None:
                    st_obj["json"] = rec["input"]
                if isinstance(modern_out, dict) and rec.get("expectJsonPath"):
                    st_obj["expectJsonPath"] = str(rec["expectJsonPath"])
                    if "equals" in rec:
                        st_obj["equals"] = rec["equals"]
                elif modern_out is not None and not isinstance(modern_out, (dict, list)):
                    st_obj["expectBodyContains"] = str(modern_out)
                p_steps = [st_obj]
            exp_desc = (
                f"Documented modernization divergence ({div_ref}): modern output matches {modern_out!r} "
                f"(legacy output was {legacy_out!r})."
                if div_ref
                else f"Strict behavioral parity: output matches legacy golden oracle {legacy_out!r} for input {rec.get('input')!r}."
            )
            t_par = tc(
                counter, "Parity",
                f"Behavioral parity oracle ({op_name})" + (f" [divergence {div_ref}]" if div_ref else ""),
                exp_desc[:300],
                p_runtime,
                f"parity:{rec.get('id') or op_name}:{line_idx}",
                reqs=[div_ref] if div_ref else [],
                steps=p_steps,
                derivation={"line": line_idx, "operation": op_name, "input": rec.get("input"),
                            "legacyExpectedOutput": legacy_out, "modernExpectedOutput": modern_out},
                tc_id=str(rec["id"]) if str(rec.get("id", "")).startswith("TC-PARITY-") else None,
            )
            if div_ref:
                t_par["intentionalDivergenceRef"] = div_ref
            if p_steps is not None:
                t_par["needsSteps"] = bool(rec.get("needsSteps", False))
            tcs.append(t_par)

    # ---------------------------------------------------------------- merge with existing
    out_path = dlc.project_path(root, args.output)
    retired: list[dict[str, str]] = []
    preserved = 0
    if out_path.exists():
        old = dlc.read_json(out_path)
        old_tcs = old.get("testCases", []) if isinstance(old, dict) else []
        by_key = {t.get("derivationKey"): t for t in old_tcs if t.get("derivationKey")}
        by_id = {t.get("id"): t for t in old_tcs}
        new_keys = {t["derivationKey"] for t in tcs}
        new_ids = {t["id"] for t in tcs}
        for t in tcs:
            prev = by_key.get(t["derivationKey"]) or (by_id.get(t["id"]) if by_id.get(t["id"], {}).get("derivationKey") in (None, t["derivationKey"]) else None)
            if prev and prev.get("deferredByGroupSelection") and not t.get("deferredByGroupSelection"):
                prev = None  # group newly scheduled: the deferral marker step is not authored content
            if prev and prev.get("steps") and not prev.get("needsSteps", False):
                t["steps"] = prev["steps"]  # authored steps survive, even when the group is deferred again
                t["needsSteps"] = False
                if prev.get("role") is not None:
                    t["role"] = prev["role"]
                if prev.get("runtime") in ("browser", "http", "static"):
                    t["runtime"] = prev["runtime"]  # the testing-agent may move an AC test to the http/static runtime
                for extra in ("settleMs", "failOnScriptError", "tokenClasses", "intentionalDivergenceRef", "matrixCases"):
                    if extra in prev:
                        t[extra] = prev[extra]
                if prev.get("optional") and not prev.get("deferredByGroupSelection"):
                    t["optional"] = True
                preserved += 1
        for t in old_tcs:
            if t.get("derivationKey") not in new_keys and t.get("id") not in new_ids:
                retired.append({"id": t.get("id", "?"), "title": t.get("title", ""), "reason": "no longer derived from current stories/spec/contracts"})
        retired += [r for r in old.get("retiredTestCases", []) if r.get("id") not in new_ids]

    payload = {
        "schemaVersion": dlc.SCHEMA_VERSION,
        "derivedAtUtc": dlc.utc_now_iso(args.deterministic),
        "derivedFrom": {"userStoriesSha256": stories_sha, "specSha256": spec_sha,
                        "contractsIndexSha256": dlc.sha256_file(ci_path) if ci_path.exists() else None,
                        "inputInventoryFingerprint": inv.get("inputFingerprintSha256")},
        "forbiddenUiTokens": forbidden,
        "retiredTestCases": retired,
        "testCases": tcs,
    }
    errs = dlc.validate_against_schema(payload, dlc.load_schema("test_cases.schema.json"))
    if errs:
        raise dlc.GateFailure("derived test_cases.json violates schemas/test_cases.schema.json:\n  " + "\n  ".join(errs[:20]))
    dlc.write_json(out_path, payload)

    # ---------------------------------------------------------------- summary for the LLM (test_plan.md)
    cats: dict[str, int] = {}
    for t in tcs:
        cats[t["category"]] = cats.get(t["category"], 0) + 1
    needing = [t for t in tcs if t["needsSteps"]]
    ac_total = sum(len(s.get("acceptanceCriteria", [])) for s in stories)
    print("## Derived Test Inventory")
    print(f"- Source: {len(stories)} stories / {ac_total} acceptance criteria; state machine {len(sm.states)} states, "
          f"{len(sm.transitions)} transitions, {len(sm.triggers())} triggers; {len(roles)} roles; "
          f"{len(contracts.get('paths', [])) if contracts else 0} API operations.")
    print(f"- Written: `{out_path.relative_to(root) if out_path.is_relative_to(root) else out_path}` — {len(tcs)} test cases "
          f"({preserved} with preserved authored steps, {len(retired)} retired).")
    print("\n| Category | Count |\n| :-- | :-: |")
    for c in ["Positive", "Negative", "Edge", "State", "Interact", "UiLeak", "A11y", "Api", "Parity"]:
        if cats.get(c):
            print(f"| {c} | {cats[c]} |")
    print(f"\n- Forbidden UI tokens: {len(schema_ids)} schema identifiers ({len(ignored)} plain words ignored), "
          f"{len(enum_codes)} enum codes, {len(legacy_ids)} legacy identifiers, {len(pii_patterns)} PII patterns.")
    print(f"- **{len(needing)} test case(s) need steps** (Gate 4b fails until each has steps and needsSteps=false):")
    for t in needing[:400]:
        print(f"  - {t['id']} — {t['title'][:110]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
