#!/usr/bin/env python3
"""Conditional Decision-Tree Clarification & Modernization Ambition Helper (`clarification-griller`).

Detects whether a Gate 1 or Stage 4A clarification interview ('grill-me' frontier round) is needed based on
concrete gaps in Stage 1 / Stage 4A artifacts, manages the open decision frontier, and persists auditable
`DECISION-NN` records + Legacy `capabilityDispositions` into `specs/clarification_decisions.json`.

Actions:
  detect                  Evaluate inputs/blueprint/stack and output `needsClarification`, `triggerReasons`,
                          and `suggestedRootFrontier` (with `--auto-bypass-if-clear` to write CLEAR_AUTO_BYPASSED)
  save-frontier           Save active `openFrontier` questions (`clarificationStatus = IN_PROGRESS`)
  record-round            Append resolved `DECISION-NN` items (+ optional `capabilityDispositions`) and update
                          `openFrontier` (`RESOLVED_BY_HUMAN` when `openFrontier` becomes empty)
  accept-recommendations  Resolve all remaining `openFrontier` items using `recommendedAnswer`
  status                  Print current `specs/clarification_decisions.json` summary
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import dlc_common as dlc  # noqa: E402


def decisions_path(root: Path) -> Path:
    return root / "specs" / "clarification_decisions.json"


def load_or_init_ledger(root: Path, deterministic: bool = False) -> dict[str, Any]:
    p = decisions_path(root)
    if p.is_file():
        data = dlc.read_json(p)
        if isinstance(data, dict):
            return data
    return {
        "schemaVersion": dlc.SCHEMA_VERSION,
        "updatedAtUtc": dlc.utc_now_iso(deterministic),
        "clarificationStatus": "IN_PROGRESS",
        "roundsCompleted": 0,
        "triggerReasons": [],
        "capabilityDispositions": [],
        "decisions": [],
        "openFrontier": [],
    }


def save_and_validate_ledger(root: Path, ledger: dict[str, Any], deterministic: bool = False) -> Path:
    ledger["schemaVersion"] = dlc.SCHEMA_VERSION
    ledger["updatedAtUtc"] = dlc.utc_now_iso(deterministic)
    errs = dlc.validate_against_schema(ledger, dlc.load_schema("clarification_decisions.schema.json"))
    if errs:
        raise dlc.GateFailure(
            "specs/clarification_decisions.json violates schemas/clarification_decisions.schema.json:\n  - "
            + "\n  - ".join(errs)
        )
    out = decisions_path(root)
    dlc.write_json(out, ledger)
    return out


def _next_decision_id(existing: list[dict[str, Any]]) -> str:
    max_n = 0
    for d in existing:
        did = str(d.get("id") or "")
        if did.startswith("DECISION-"):
            try:
                max_n = max(max_n, int(did.split("-", 1)[1]))
            except ValueError:
                pass
    return f"DECISION-{max_n + 1:02d}"


def build_detection_report(root: Path, stage: str) -> dict[str, Any]:
    assessment = dlc.assess_clarification_triggers(root, stage=stage)
    frontier: list[dict[str, Any]] = []
    q_idx = 1

    if stage == "gate1":
        inv_path = root / "specs" / "input_inventory.json"
        inv = dlc.read_json(inv_path) if inv_path.is_file() else {}
        doc_path = root / "specs" / "discovery_architecture_and_inventory.md"
        md = dlc.read_text(doc_path) if doc_path.is_file() else ""
        cap_groups = dlc.parse_capability_groups(md) if md else []
        grp_labels = ", ".join(f"{g['id']} ({g['name']})" for g in cap_groups[:6]) or "discovered capability groups"

        if "LEGACY_MODERNIZATION_AMBITION_UNSETTLED" in assessment["triggerReasons"]:
            frontier.append({
                "questionId": f"Q{q_idx}",
                "round": 1,
                "parentDecisionId": None,
                "category": "capability-disposition",
                "evidenceSource": "specs/discovery_architecture_and_inventory.md (§5 Pain Points & §6.1 Capability Groupings)",
                "question": (
                    f"Modernizing a legacy application goes beyond 1:1 lift-and-shift. Across {grp_labels}, "
                    "which capabilities should be (a) Re-imagined with new enhancements (`REQ-ENH-*`: self-service UX, "
                    "automated workflow/notifications, live rule engine, or grounded AI copilot), (b) Kept at strict "
                    "1:1 parity, or (c) Retired/deprecated?"
                ),
                "recommendedAnswer": (
                    "Re-imagine core operational & intake capabilities with self-service UX, live rule validation, "
                    "and automated status notifications derived from §5 pain points; keep deterministic core "
                    "calculations at 1:1 parity; retire obsolete manual batch export forms."
                ),
                "options": [
                    "(Recommended) Re-imagine core workflows (REQ-ENH-*) + keep core formulas at parity + retire manual exports",
                    "Add AI-assisted triage / copilot surface alongside re-imagined self-service workflows",
                    "Strict 1:1 functional parity across all discovered capabilities (modernize architecture/UI only)",
                ],
            })
            q_idx += 1

            rrs = (inv.get("runtimeReadinessSignals") or {}) if isinstance(inv, dict) else {}
            rec_mode = rrs.get("recommendedModernizationMode") or "clean-room-rebuild"
            blockers = (rrs.get("osAndPlatformBlockers") or []) + (rrs.get("statelessScalingHazards") or [])
            ev_detail = f"runtimeReadinessSignals (recommended={rec_mode}, blockers={len(blockers)})"
            frontier.append({
                "questionId": f"Q{q_idx}",
                "round": 1,
                "parentDecisionId": None,
                "category": "modernization-ambition",
                "evidenceSource": f"specs/input_inventory.json ({ev_detail})",
                "question": (
                    "Which modernization execution approach and initial delivery wave should govern implementation: "
                    "`clean-room-rebuild` (pure target codebase from contracts) vs. `in-place-upgrade` (refactor existing "
                    "OOP repository in-place), and first foundational Strangler wave (`GRP-01`) vs. `ALL` groups?"
                ),
                "recommendedAnswer": (
                    f"Use `{rec_mode}` and deliver foundational wave `GRP-01` first (or `ALL` if estate is small) "
                    "while eliminating any stateful/OS container blockers."
                ),
                "options": [
                    f"(Recommended) {rec_mode} — prioritize foundational wave GRP-01 first",
                    f"{rec_mode} — take ALL capability groups forward in one release",
                    "Switch modernizationMode (clean-room-rebuild <-> in-place-upgrade)",
                ],
            })
            q_idx += 1

        for oq in assessment.get("openWorkflowQuestions", [])[:2]:
            if q_idx > 4:
                break
            frontier.append({
                "questionId": f"Q{q_idx}",
                "round": 1,
                "parentDecisionId": None,
                "category": "workflow-state",
                "evidenceSource": "specs/discovery_architecture_and_inventory.md (§3.1 Open Workflow Questions)",
                "question": oq,
                "recommendedAnswer": (
                    "Adopt the most restrictive role-gated workflow transition (explicit supervisor/reviewer role "
                    "required; rejected records return to an editable revision state with mandatory reason)."
                ),
            })
            q_idx += 1

        unv = assessment.get("unverifiedAcronyms") or []
        if unv and q_idx <= 4:
            acr_list = ", ".join(unv[:6])
            frontier.append({
                "questionId": f"Q{q_idx}",
                "round": 1,
                "parentDecisionId": None,
                "category": "acronym-definition",
                "evidenceSource": "specs/input_inventory.json (unverifiedAcronyms)",
                "question": f"Please confirm the authoritative domain expansion/meaning for undefined acronym(s): {acr_list}.",
                "recommendedAnswer": f"Keep literal acronym(s) ({acr_list}) without unverified expansion unless domain glossary defines them.",
            })
            q_idx += 1

    elif stage == "stage4a":
        if any("TARGET_STACK_TBD" in r for r in assessment["triggerReasons"]):
            frontier.append({
                "questionId": "Q1",
                "round": 1,
                "parentDecisionId": None,
                "category": "architecture-stack",
                "evidenceSource": "specs/target_stack.json (decidedBy != 'user' or stack kind == 'tbd')",
                "question": (
                    "Which Future-State ('To-Be') frontend framework, backend runtime/framework, relational database, "
                    "and GDC target environments should Stage 4A design and Stage 5 build?"
                ),
                "recommendedAnswer": (
                    "React + TypeScript (Vite, M3/ShadCN tokens), stateless REST backend (FastAPI / Spring Boot / ASP.NET Core 8 "
                    "matching team skill), PostgreSQL 16 (3NF), targeting GDC multi-cloud overlays."
                ),
            })

    return {
        **assessment,
        "suggestedRootFrontier": frontier[:4],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument(
        "--action",
        required=True,
        choices=["detect", "save-frontier", "record-round", "accept-recommendations", "status"],
    )
    ap.add_argument("--stage", default="gate1", choices=["gate1", "stage4a"])
    ap.add_argument("--auto-bypass-if-clear", action="store_true",
                    help="When detect finds needsClarification=false, persist CLEAR_AUTO_BYPASSED to specs/clarification_decisions.json")
    ap.add_argument("--frontier-json", default=None, help="JSON array of openFrontier question objects")
    ap.add_argument("--decisions-json", default=None, help="JSON array of resolved decision objects")
    ap.add_argument("--dispositions-json", default=None, help="JSON array of capabilityDispositions objects")
    ap.add_argument("--next-frontier-json", default="[]", help="JSON array of dependent child frontier questions for the next round")
    ap.add_argument("--deterministic", action="store_true")
    args = ap.parse_args()

    root = dlc.resolve_project_root(args.project_root)

    if args.action == "detect":
        report = build_detection_report(root, stage=args.stage)
        if not report["needsClarification"] and args.auto_bypass_if_clear and not decisions_path(root).is_file():
            ledger = load_or_init_ledger(root, args.deterministic)
            ledger["clarificationStatus"] = (
                "AUTONOMOUS_ASSUMPTIONS" if dlc.is_autonomous_or_golden(root) else "CLEAR_AUTO_BYPASSED"
            )
            ledger["triggerReasons"] = []
            ledger["openFrontier"] = []
            save_and_validate_ledger(root, ledger, args.deterministic)
        print(json.dumps(report, indent=2))
        return 0

    if args.action == "save-frontier":
        if not args.frontier_json:
            raise dlc.GateFailure("--frontier-json is required for --action save-frontier.")
        frontier = json.loads(args.frontier_json)
        if not isinstance(frontier, list) or not (1 <= len(frontier) <= 4):
            raise dlc.GateFailure("--frontier-json must be a JSON array of 1..4 independent frontier questions.")
        report = build_detection_report(root, stage=args.stage)
        ledger = load_or_init_ledger(root, args.deterministic)
        ledger["clarificationStatus"] = "IN_PROGRESS"
        if report["triggerReasons"]:
            ledger["triggerReasons"] = list(dict.fromkeys(ledger["triggerReasons"] + report["triggerReasons"]))
        elif not ledger["triggerReasons"]:
            ledger["triggerReasons"] = ["MANUAL_GRILL_REQUESTED"]
        ledger["openFrontier"] = frontier
        out = save_and_validate_ledger(root, ledger, args.deterministic)
        print(json.dumps({"saved": str(out), "clarificationStatus": ledger["clarificationStatus"], "openFrontierCount": len(frontier)}, indent=2))
        return 0

    if args.action == "record-round":
        if not args.decisions_json:
            raise dlc.GateFailure("--decisions-json is required for --action record-round.")
        incoming_decisions = json.loads(args.decisions_json)
        next_frontier = json.loads(args.next_frontier_json or "[]")
        incoming_disps = json.loads(args.dispositions_json) if args.dispositions_json else []
        if not isinstance(incoming_decisions, list) or not incoming_decisions:
            raise dlc.GateFailure("--decisions-json must be a non-empty JSON array.")
        if not isinstance(next_frontier, list) or len(next_frontier) > 4:
            raise dlc.GateFailure("--next-frontier-json must be a JSON array of 0..4 questions.")

        ledger = load_or_init_ledger(root, args.deterministic)
        new_round = int(ledger.get("roundsCompleted") or 0) + 1
        for item in incoming_decisions:
            if not isinstance(item, dict):
                raise dlc.GateFailure("Each entry in --decisions-json must be an object.")
            entry = dict(item)
            entry.setdefault("id", _next_decision_id(ledger["decisions"]))
            entry.setdefault("round", new_round)
            entry.setdefault("resolvedBy", "user")
            ledger["decisions"].append(entry)

        if incoming_disps:
            by_target = {d["targetId"]: d for d in ledger.get("capabilityDispositions") or [] if isinstance(d, dict) and d.get("targetId")}
            for disp in incoming_disps:
                if isinstance(disp, dict) and disp.get("targetId"):
                    by_target[str(disp["targetId"])] = disp
            ledger["capabilityDispositions"] = list(by_target.values())

        ledger["roundsCompleted"] = new_round
        ledger["openFrontier"] = next_frontier
        ledger["clarificationStatus"] = "IN_PROGRESS" if next_frontier else "RESOLVED_BY_HUMAN"
        if not ledger["triggerReasons"]:
            report = build_detection_report(root, stage=args.stage)
            ledger["triggerReasons"] = report["triggerReasons"] or ["USER_CLARIFICATION_RECORDED"]
        out = save_and_validate_ledger(root, ledger, args.deterministic)
        print(json.dumps({
            "saved": str(out),
            "clarificationStatus": ledger["clarificationStatus"],
            "roundsCompleted": ledger["roundsCompleted"],
            "totalDecisions": len(ledger["decisions"]),
            "openFrontierCount": len(ledger["openFrontier"]),
        }, indent=2))
        return 0

    if args.action == "accept-recommendations":
        ledger = load_or_init_ledger(root, args.deterministic)
        open_items = ledger.get("openFrontier") or []
        if not open_items:
            report = build_detection_report(root, stage=args.stage)
            open_items = report.get("suggestedRootFrontier") or []
            if report.get("triggerReasons") and not ledger.get("triggerReasons"):
                ledger["triggerReasons"] = report["triggerReasons"]
        if open_items:
            new_round = int(ledger.get("roundsCompleted") or 0) + 1
            for q in open_items:
                ledger["decisions"].append({
                    "id": _next_decision_id(ledger["decisions"]),
                    "round": int(q.get("round") or new_round),
                    "parentDecisionId": q.get("parentDecisionId"),
                    "category": q.get("category", "workflow-state"),
                    "evidenceSource": q.get("evidenceSource", "Stage 1 discovery blueprint"),
                    "question": q["question"],
                    "recommendedAnswer": q["recommendedAnswer"],
                    "resolvedAnswer": q["recommendedAnswer"],
                    "resolvedBy": "accepted-recommendation",
                })
            ledger["roundsCompleted"] = new_round
        ledger["openFrontier"] = []
        ledger["clarificationStatus"] = "ACCEPTED_RECOMMENDATIONS"
        out = save_and_validate_ledger(root, ledger, args.deterministic)
        print(json.dumps({
            "saved": str(out),
            "clarificationStatus": ledger["clarificationStatus"],
            "totalDecisions": len(ledger["decisions"]),
            "openFrontierCount": 0,
        }, indent=2))
        return 0

    if args.action == "status":
        p = decisions_path(root)
        if not p.is_file():
            print(json.dumps({"present": False, "clarificationStatus": "NOT_STARTED"}, indent=2))
            return 0
        ledger = dlc.read_json(p)
        print(json.dumps({
            "present": True,
            "clarificationStatus": ledger.get("clarificationStatus"),
            "roundsCompleted": ledger.get("roundsCompleted", 0),
            "decisionIds": [d.get("id") for d in (ledger.get("decisions") or [])],
            "capabilityDispositions": ledger.get("capabilityDispositions") or [],
            "openFrontierCount": len(ledger.get("openFrontier") or []),
        }, indent=2))
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
