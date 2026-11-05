#!/usr/bin/env python3
"""Stage 2 — structural lint of `specs/application_spec.md` (02-spec-architect-and-judge).

Checks the LLM-authored specification against docs/ARCHITECTURE.md §4.3 (pillar headings, REQ id families,
scenario rule for REQ-ENH, unique REQ definitions, state-machine table, roles table, business-rules table,
traceability coverage) and emits `specs/.spec_index.json` for downstream scripts. Quality is judged separately
by the LLM against schemas/spec_rubric.json (see validate_spec_scorecard.py); this script only lints shape.

Usage:
    python3 lint_spec_structure.py --project-root <PROJECT_ROOT> [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import dlc_common as dlc  # noqa: E402

PILLARS = {
    1: (r"pillar\s*1\b", "REQ-FUNC"),
    2: (r"pillar\s*2\b", "REQ-SEC"),
    3: (r"pillar\s*3\b", "REQ-A11Y"),
    4: (r"pillar\s*4\b", "REQ-UX"),
    5: (r"pillar\s*5\b", "REQ-ARCH"),
}
REQ_ID_RE = re.compile(r"\bREQ-(FUNC|ENH|SEC|A11Y|UX|ARCH)-\d+\b")
# A "definition" line starts with the id after list/heading/table/bold markers.
DEF_LINE_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)]|#{1,6}|\|)?\s*(?:\*\*|`|__)?\s*(REQ-(?:FUNC|ENH|SEC|A11Y|UX|ARCH)-\d+)\b")
UPPER_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$|^[A-Z]{3,}$")


def headings(md: str) -> list[str]:
    return re.findall(r"^#{1,6}\s+(.*)$", md, re.MULTILINE)


def has_heading(md: str, pattern: str) -> bool:
    return any(re.search(pattern, h, re.IGNORECASE) for h in headings(md))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = dlc.resolve_project_root(args.project_root)
    dlc.require_gate_approved(root, "gate_1_discovery", "Stage 2 (02-spec-architect-and-judge / lint_spec_structure.py)")
    inv = dlc.load_inventory(root)
    scenario = inv.get("inputScenario", "SCENARIO_REQUIREMENTS_DOC")
    legacy = scenario == "SCENARIO_LEGACY_APP"
    spec_path = root / "specs" / "application_spec.md"
    spec = dlc.load_spec(root)
    rtm_path = dlc.require_file(root / "specs" / "traceability_matrix.md", "Stage 2 (02-spec-architect-and-judge / discovery-architect)")
    rtm = dlc.read_text(rtm_path)

    fails: list[str] = []
    warns: list[str] = []

    # Header block
    if not re.search(r"^#\s+\S", spec, re.MULTILINE):
        fails.append("Missing top-level '# <Project Name>' heading.")
    hdr_scn = re.search(r"Input Scenario[^\n]*?(SCENARIO_[A-Z_]+)", spec)
    if not hdr_scn:
        fails.append("Header block must state 'Input Scenario: SCENARIO_…'.")
    elif hdr_scn.group(1) != scenario:
        fails.append(f"Spec header says {hdr_scn.group(1)} but input_inventory.json says {scenario}.")
    if not re.search(r"Domain Slug", spec):
        fails.append("Header block must state 'Domain Slug: <kebab-case>'.")

    # Pillar headings and REQ families
    all_ids = dlc.extract_ids(spec, "REQ-")
    families = {fam: [i for i in all_ids if i.startswith(fam + "-")] for fam in ("REQ-FUNC", "REQ-ENH", "REQ-SEC", "REQ-A11Y", "REQ-UX", "REQ-ARCH")}
    for n, (pat, fam) in PILLARS.items():
        if not has_heading(spec, pat):
            fails.append(f"Missing '## {n} Pillar {n} — …' heading.")
        if not families[fam]:
            fails.append(f"No {fam}-NN requirement found (Pillar {n}).")
    if legacy:
        if not families["REQ-ENH"]:
            fails.append("SCENARIO_LEGACY_APP requires '### 1.4 Modernization Enhancements' with REQ-ENH-NN items.")
        elif not has_heading(spec, r"modernization|enhancement"):
            fails.append("REQ-ENH items exist but no 'Modernization Enhancements' heading.")
    elif families["REQ-ENH"] or has_heading(spec, r"modernization enhancements"):
        fails.append("SCENARIO_REQUIREMENTS_DOC must not contain REQ-ENH-* / Modernization Enhancements (zero scope creep).")

    # Unique definitions
    defs: dict[str, int] = {}
    for line in spec.splitlines():
        m = DEF_LINE_RE.match(line)
        if m:
            defs[m.group(1)] = defs.get(m.group(1), 0) + 1
    for rid in all_ids:
        c = defs.get(rid, 0)
        if c == 0:
            fails.append(f"{rid} is referenced but never defined (a definition line starts with the id: '- **{rid}** …' or a table row).")
        elif c > 1:
            fails.append(f"{rid} is defined {c} times — REQ ids must be unique.")

    # State machine §3.3
    sd_blocks = [b for b in dlc.md_fenced_blocks(spec, "mermaid") if "statediagram" in b.lower()]
    if len(sd_blocks) == 0:
        fails.append("§3.3 must contain exactly one ```mermaid stateDiagram-v2 block (found 0).")
    elif len(sd_blocks) > 1:
        warns.append(f"Found {len(sd_blocks)} stateDiagram-v2 blocks; §3.3 should contain exactly one.")
    sm = dlc.parse_state_table(spec)
    if not sm.transitions:
        fails.append("§3.3 transition table '| From | To | Trigger | Actor Role | Guard |' missing or empty.")
    elif not sm.roles():
        fails.append("§3.3 transition table has no Actor Role values.")

    # Roles §3.5
    roles = dlc.parse_roles(spec)
    if not roles:
        fails.append("§3.5 Roles table '| Role | Kind (external|internal) | Views | Allowed Transitions |' missing or empty.")
    else:
        role_names = {r["role"].lower() for r in roles}
        for r in sm.roles():
            if r.lower() not in role_names and r.lower() not in {"system", "scheduler", "timer", "any"}:
                fails.append(f"Actor Role '{r}' used in §3.3 is not declared in §3.5 Roles.")
        if sm.transitions:
            for r in roles:
                owned = [t.trigger for t in sm.transitions if r["role"].lower() in [x.lower() for x in t.roles]]
                if not owned and r["kind"] == "internal":
                    warns.append(f"Internal role '{r['role']}' owns no transition in §3.3.")

    # Business rules §3.4 (header must exist; rows may be empty)
    if not re.search(r"^\s*\|\s*Rule ID\s*\|[^\n]*Formula", spec, re.IGNORECASE | re.MULTILINE):
        fails.append("§3.4 Business Rules table header '| Rule ID | Formula / Rule | Inputs | Source |' missing.")
    brs = dlc.parse_business_rules(spec)
    br_ids = [b["id"] for b in brs]
    for b in br_ids:
        if not re.fullmatch(r"BR-\d+", b):
            fails.append(f"Business rule id {b!r} must match BR-NN.")
    lines_with_req = [ln for ln in (spec + "\n" + rtm).splitlines() if REQ_ID_RE.search(ln)]
    for b in br_ids:
        if not any(re.search(rf"\b{re.escape(b)}\b", ln) for ln in lines_with_req):
            fails.append(f"{b} is not referenced by any REQ (spec or traceability matrix).")

    # Traceability
    rtm_ids = set(dlc.extract_ids(rtm, "REQ-"))
    missing_rtm = [i for i in all_ids if i not in rtm_ids]
    if missing_rtm:
        fails.append(f"{len(missing_rtm)} REQ id(s) absent from specs/traceability_matrix.md: {', '.join(missing_rtm[:10])}{' …' if len(missing_rtm) > 10 else ''}")

    # §4.2 View & Component Topology table
    views = dlc.parse_view_topology(spec)
    if not views:
        fails.append("§4.2 View & Component Topology table '| View ID | Navigation Tab / Route | UI Pattern | Bound Role(s) | Primary CTA & Lifecycle Trigger |' missing or empty.")
    else:
        role_names_low = {r["role"].lower() for r in roles}
        for v in views:
            for br in v.get("boundRoles", []):
                if role_names_low and br.lower() not in role_names_low and br.lower() not in {"all", "all roles", "any"}:
                    fails.append(f"Bound Role '{br}' in §4.2 View '{v['viewId']}' is not declared in §3.5 Roles.")

    manifest_path = root / "resources" / "design_references" / "reference_ui_manifest.json"
    if manifest_path.is_file():
        manifest = dlc.read_json(manifest_path)
        ref_views = manifest.get("views", []) if isinstance(manifest, dict) else []
        spec_labels = {v["tabLabel"].lower() for v in views}
        spec_ids = {v["viewId"].lower() for v in views}
        for rv in ref_views:
            rlbl = str(rv.get("tabLabel") or "").strip().lower()
            rvid = str(rv.get("viewId") or "").strip().lower()
            if rlbl and rlbl not in spec_labels and rvid not in spec_ids and not any(rlbl in sl or sl in rlbl for sl in spec_labels if sl):
                fails.append(f"Reference UI view '{rv.get('viewId')}: {rv.get('tabLabel')}' from reference_ui_manifest.json is not accounted for in spec §4.2 View & Component Topology table.")

    # Index for downstream scripts
    uses_codes = any(UPPER_CODE_RE.match(s) for s in sm.states)
    index = {
        "schemaVersion": dlc.SCHEMA_VERSION,
        "specSha256": dlc.sha256_file(spec_path),
        "inputScenario": scenario,
        "reqIds": all_ids,
        "brIds": br_ids,
        "states": sm.states,
        "initialStates": sm.initial,
        "terminalStates": sm.terminal,
        "triggers": sm.triggers(),
        "transitions": [{"from": t.src, "to": t.dst, "trigger": t.trigger, "roles": t.roles, "guard": t.guard} for t in sm.transitions],
        "roles": roles,
        "views": views,
        "usesEnumCodes": uses_codes,
    }
    dlc.write_json(root / "specs" / ".spec_index.json", index)

    if args.json:
        print(json.dumps({"passed": not fails, "failures": fails, "warnings": warns, "index": index}, indent=2))
    else:
        for w in warns:
            dlc.warn(w)
        for f in fails:
            print(f"  ✗ {f}")
        print(f"[dlc] spec structure lint: {'PASS' if not fails else 'FAIL'} — {len(all_ids)} REQ, {len(br_ids)} BR, "
              f"{len(sm.states)} states, {len(sm.transitions)} transitions, {len(roles)} roles, {len(views)} views; index -> specs/.spec_index.json")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
