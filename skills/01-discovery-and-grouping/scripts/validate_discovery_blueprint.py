#!/usr/bin/env python3
"""Gate 1 — validate `specs/discovery_architecture_and_inventory.md` (01-discovery-and-grouping).

Scenario-conditional structural gate (docs/ARCHITECTURE.md §1.3, §4.1, §5 Gate 1). Reads
`specs/input_inventory.json` to know the scenario and whether policy or regulatory documents exist, then checks the LLM-authored
Current-State ("As-Is") discovery document. Enforces that Stage 1 stays strictly Current-State ("As-Is") and
does NOT mix in Future-State ("To-Be") 3NF ERDs, target SQL DDL, OpenAPI contracts, or Legacy-to-Target entity
mappings (which belong in Stage 4A `design/solution_design.md`). Nothing here authors content; it exits 1 with
itemised reasons.

Usage:
    python3 validate_discovery_blueprint.py --project-root <PROJECT_ROOT>
            [--file specs/discovery_architecture_and_inventory.md] [--allow-missing-target-stack] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import dlc_common as dlc  # noqa: E402

TECH_WORDS = [
    "java", "spring", "angular", "react", "vue", "python", "fastapi", "flask", "django", "node", "express",
    "postgres", "postgresql", "mysql", "sqlite", "cloud sql", "cloud run", "kubernetes", "docker", ".net", "c#",
    "typescript", "javascript", "html", "css",
]
PLACEHOLDER_RE = re.compile(r"<[^>]+>|\bTODO\b|\bTBD\b|lorem ipsum", re.IGNORECASE)
FUTURE_STATE_HEADING_RE = re.compile(
    r"future[- ]state|to[- ]be\s+(?:architecture|erd|domain|schema|design|model|flow)|"
    r"normali[sz]ed\s+3nf\s+erd|legacy[- ]to[- ](?:modern|target)|legacy\s*(?:->|→)\s*target",
    re.IGNORECASE,
)


def heading_present(md: str, pattern: str) -> bool:
    return any(re.search(pattern, h, re.IGNORECASE) for h in re.findall(r"^#{1,6}\s+(.*)$", md, re.MULTILINE))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument("--file", default="specs/discovery_architecture_and_inventory.md")
    ap.add_argument("--allow-missing-target-stack", action="store_true",
                    help="Downgrade a missing specs/target_stack.json from FAIL to WARN (pre-Gate-1 dry run)")
    ap.add_argument("--json", action="store_true", help="Print machine-readable result")
    args = ap.parse_args()

    root = dlc.resolve_project_root(args.project_root)
    dlc.require_gate_approved(root, "gate_0_setup", "Stage 1 (01-discovery-and-grouping / validate_discovery_blueprint.py)")
    inv = dlc.load_inventory(root)
    doc_path = dlc.require_file(dlc.project_path(root, args.file), "Stage 1 (01-discovery-and-grouping / discovery-architect)")
    md = dlc.read_text(doc_path)
    scenario = inv.get("inputScenario", "SCENARIO_REQUIREMENTS_DOC")
    legacy = scenario == "SCENARIO_LEGACY_APP"
    stack = dlc.read_json(root / "specs" / "target_stack.json") if (root / "specs" / "target_stack.json").exists() else None
    has_statutes = bool(inv.get("hasPoliciesOrStatutes")) or bool(stack and stack.get("regulations"))

    fails: list[str] = []
    warns: list[str] = []

    # 1. Project name — business/domain name only
    m = re.search(r"\*\*Project Name:?\*\*:?\s*`?([^`\n]+)`?", md)
    if not m:
        fails.append("Missing '- **Project Name:** <name>' header line.")
    else:
        name = m.group(1).strip()
        if not name or PLACEHOLDER_RE.search(name):
            fails.append(f"Project Name looks like a placeholder: {name!r}")
        # Whole-word match only ('java' must not fire on 'javelin'); WARN because a business name may legitimately
        # contain such a word — the human confirms at Gate 1.
        for w in TECH_WORDS:
            if re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", name.lower()):
                warns.append(f"Project Name should be the business/domain name only — it contains a target tech-stack word ('{w}'): {name!r}")

    # 2. Scenario header must agree with the inventory (human-readable label required; SCENARIO_* enum forbidden by leak scan)
    parsed_scn = dlc.parse_scenario_label(md)
    if not parsed_scn:
        fails.append(
            f"Missing '- **Input Scenario Mode:** {dlc.scenario_display_label(scenario)}' header line."
        )
    elif parsed_scn != scenario:
        fails.append(
            f"Document states scenario '{dlc.scenario_display_label(parsed_scn)}' but specs/input_inventory.json says "
            f"{scenario} ({dlc.scenario_display_label(scenario)}). Confirm with the user or fix the document."
        )

    # 3. Narrative §1 subsections
    if not heading_present(md, r"business context|mission|purpose"):
        fails.append("Missing §1 narrative subsection on Business Context & Mission.")
    if not heading_present(md, r"current[- ]state|assessment|risks|as-is|pain points|problem statement"):
        fails.append("Missing §1 narrative subsection on Current-State Assessment & Risks (legacy) / Problem Statement (requirements document).")
    if has_statutes and not heading_present(md, r"statut|regulat|legislat|polic|mandate"):
        fails.append("resources/policies_and_statutes is non-empty (or regulations declared) but no Policy/Regulatory section exists.")

    # 4. Current-State ("As-Is") ERD & strict separation from Future-State ("To-Be") design
    er_blocks = [b for b in dlc.md_fenced_blocks(md, "mermaid") if "erdiagram" in b.lower()]
    if not er_blocks:
        fails.append("Missing ```mermaid erDiagram block (Current-State 'As-Is' data model / entity diagram).")
    elif not re.search(r"\w+\s+[|}o][|o]?--[|o][|{o]?\s+\w+", er_blocks[0]) and not re.search(r"^\s*\w+\s*\{", er_blocks[0], re.MULTILINE):
        fails.append("erDiagram block contains no entities or relationships.")

    bad_headings = [
        h.strip() for h in re.findall(r"^#{1,6}\s+(.*)$", md, re.MULTILINE)
        if FUTURE_STATE_HEADING_RE.search(h)
    ]
    if bad_headings:
        fails.append(
            "Stage 1 discovery blueprint must document the Current State ('As-Is') only — found Future-State / "
            f"3NF / Legacy-to-Target heading(s) {bad_headings!r}. Move all Future-State 3NF ERDs, flow diagrams, "
            "and Legacy-to-Target mappings to Stage 4A (design/solution_design.md)."
        )
    sql_ddl_blocks = [b for b in dlc.md_fenced_blocks(md, "sql") if re.search(r"CREATE\s+TABLE", b, re.IGNORECASE)]
    yaml_api_blocks = [b for b in dlc.md_fenced_blocks(md, "yaml") + dlc.md_fenced_blocks(md, "yml") if re.search(r"^openapi:", b, re.MULTILINE)]
    if sql_ddl_blocks or yaml_api_blocks:
        fails.append(
            "Stage 1 discovery blueprint must not contain Future-State SQL DDL ('CREATE TABLE') or OpenAPI contracts — "
            "those belong exclusively in Stage 4A (design/solution_design.md)."
        )

    # 5. State machine: diagram + transition table
    sd_blocks = [b for b in dlc.md_fenced_blocks(md, "mermaid") if "statediagram" in b.lower()]
    if not sd_blocks:
        fails.append("Missing ```mermaid stateDiagram-v2 block.")
    sm_tbl = dlc.parse_state_table(md)
    if not sm_tbl.transitions:
        fails.append("Missing or empty '| From | To | Trigger | Actor Role | Guard |' transition table (scripts parse this table, not the diagram).")
    else:
        no_role = [f"{t.src}->{t.dst} ({t.trigger})" for t in sm_tbl.transitions if not t.roles]
        if no_role:
            warns.append(f"{len(no_role)} transition(s) have no Actor Role — list them under Open Workflow Questions: {', '.join(no_role[:5])}")
        if sd_blocks:
            diag = dlc.parse_mermaid_state_diagram(md)
            missing = sorted(set(diag.states) - set(sm_tbl.states))
            if missing:
                warns.append(f"States drawn in the diagram but absent from the table: {', '.join(missing)}")
    if not heading_present(md, r"open workflow questions"):
        fails.append("Missing 'Open Workflow Questions' subsection (must exist; may state 'None').")

    # 6. Capability inventory & Business Capability Groupings (§6.1)
    if not heading_present(md, r"capability inventory"):
        fails.append("Missing 'Capability Inventory' section.")
    cap_rows = dlc.find_table(md, ["capability"])
    if not cap_rows:
        fails.append("Capability Inventory table missing or empty (needs ≥ 1 row with a 'Capability' column).")
    cap_groups = dlc.parse_capability_groups(md)
    if not cap_groups:
        warns.append("No §6.1 Business Capability Groupings table ('| Group ID | Group Name | ... |') found — add capability groupings (by business functionality or business unit / department) so the user can select specific group(s) or ALL.")
    else:
        known_gids = {g["id"] for g in cap_groups}
        for g in cap_groups:
            for dep in g.get("dependsOnGroups") or []:
                if dep not in known_gids:
                    fails.append(f"§6.1 capability group {g['id']} lists unknown prerequisite group '{dep}' (known: {sorted(known_gids)}).")

    # 7. Legacy-only: Current-State Legacy Object Inventory (no Target mapping in Stage 1)
    if legacy:
        if not heading_present(md, r"legacy.*inventory|current[- ]state.*(?:inventory|object)|legacy\s+object"):
            fails.append(
                "SCENARIO_LEGACY_APP requires a '§2.1 Current-State Legacy Object Inventory' subsection in Stage 1 "
                "(Future-State Legacy-to-Target 3NF entity mapping belongs in Stage 4A design/solution_design.md)."
            )
        inv_rows = dlc.find_table(md, ["legacy", "evidence"]) or dlc.find_table(md, ["object", "evidence"])
        if not inv_rows:
            fails.append("Current-State Legacy Object Inventory table missing or empty (columns must include 'Legacy Object' and 'Evidence').")
        if dlc.find_table(md, ["legacy", "target"]):
            fails.append(
                "Stage 1 discovery blueprint contains a 'Legacy -> Target' entity mapping table — keep Stage 1 strictly "
                "Current-State ('As-Is') and move Legacy-to-Target 3NF entity mapping to Stage 4A (design/solution_design.md §2.1)."
            )
    else:
        if re.search(r"REQ-ENH-\d+", md):
            warns.append("REQ-ENH ids present in a SCENARIO_REQUIREMENTS_DOC discovery — enhancements are not allowed in the spec for this scenario.")

    # 8. Gate 1 checklist
    if not heading_present(md, r"gate 1"):
        fails.append("Missing 'Gate 1' user context confirmation checklist section.")

    # 9. target_stack.json (Gate 1 output)
    if stack is None:
        msg = "specs/target_stack.json missing — Gate 1 must record the target stack (docs/ARCHITECTURE.md §4.2; zero-dependency default allowed in autonomous mode)."
        (warns if args.allow_missing_target_stack else fails).append(msg)
    else:
        errs = dlc.validate_against_schema(stack, dlc.load_schema("target_stack.schema.json"))
        backend = (stack.get("backend") or {}).get("kind", "none")
        cmds = stack.get("commands") or {}
        if backend not in ("none", "tbd") and stack.get("decidedBy") != "pending-stage-4a":
            # commands.* are enforced at Gate 4a (04/scripts/extract_contracts.py); at Gate 1 they are advisory.
            for k in ("start", "healthcheck", "uiEntry"):
                if not cmds.get(k):
                    warns.append(f"specs/target_stack.json#commands.{k} is not set yet (backend.kind={backend!r}) — required by Stage 4A (extract_contracts.py).")
        if errs:
            fails.append("specs/target_stack.json violates schemas/target_stack.schema.json:\n    - " + "\n    - ".join(errs))
        sel_groups = [str(g).strip().upper() for g in (stack.get("selectedCapabilityGroups") or []) if str(g).strip()]
        if sel_groups and "ALL" not in sel_groups and "*" not in sel_groups:
            known_ids = {g["id"].upper() for g in cap_groups} | {str(g.get("id", "")).upper() for g in (stack.get("capabilityGroups") or []) if isinstance(g, dict)}
            if known_ids:
                unknown = sorted(set(sel_groups) - known_ids)
                if unknown:
                    fails.append(f"specs/target_stack.json#selectedCapabilityGroups contains unknown group ID(s) {unknown} (known: {sorted(known_ids)} or 'ALL').")

    # 9b. Strict Acronym Provenance Check (warn if unverified domain acronyms are expanded without provenance marker)
    unverified_acrs = inv.get("unverifiedAcronyms") or []
    for acr in unverified_acrs:
        if re.search(rf"\b[A-Z][A-Za-z0-9/& -]{{4,60}}\(\s*{re.escape(str(acr))}\s*\)", md):
            if "UNVERIFIED_ACRONYM" not in md and not re.search(rf"\b{re.escape(str(acr))}\b.*(?:\?|confirm|verify|open)", md, re.IGNORECASE):
                warns.append(
                    f"Acronym '{acr}' had no definition in scanned inputs (`unverifiedAcronyms`), yet appears expanded in {args.file}. "
                    f"Verify expansion against input sources or tag as `[UNVERIFIED_ACRONYM]` for Gate 1 confirmation."
                )

    # 10. Zero internal harness workings leak check
    fails.extend(dlc.scan_deliverable_internal_leaks(root, [args.file]))

    result = {
        "file": str(doc_path), "inputScenario": scenario, "hasPoliciesOrStatutes": has_statutes,
        "transitions": len(sm_tbl.transitions), "states": sm_tbl.states, "roles": sm_tbl.roles(),
        "capabilityGroups": [g["id"] for g in cap_groups],
        "selectedCapabilityGroups": (stack.get("selectedCapabilityGroups") if isinstance(stack, dict) else None) or ["ALL"],
        "passed": not fails, "failures": fails, "warnings": warns,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for w in warns:
            dlc.warn(w)
        for f in fails:
            print(f"  ✗ {f}")
        print(f"[dlc] Gate 1 discovery blueprint: {'PASS' if not fails else 'FAIL'} "
              f"({len(fails)} failure(s), {len(warns)} warning(s); states={len(sm_tbl.states)} transitions={len(sm_tbl.transitions)})")
        if not fails:
            dlc.mark_gate_awaiting_human(
                root,
                "gate_1_discovery",
                summary="Stage 1 Current-State ('As-Is') Discovery Blueprint validated. Present discovery summary, §6.1 Capability Groupings, and Gate 1 intake questions to user and STOP.",
            )
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
