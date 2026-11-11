#!/usr/bin/env python3
"""Conditional Decision-Tree Grill-Me Clarification CLI (`clarification-griller`).

Engages Business Analysts & human stakeholders in bounded Frontier Rounds BEFORE `specs/application_spec.md`
is created (`--stage pre-spec`), WHEN `backlog/user_stories.json` are created (`--stage pre-stories`), at
Stage 4A (`--stage stage4a`), AND anytime an agent encounters unclear, contradictory, conflicting, or
ambiguous inputs (`--action flag-conflict`).

Actions:
  detect                  Evaluate stage artifacts (`pre-spec` | `pre-stories` | `stage4a`) and output
                          `needsClarification`, `triggerReasons`, and `suggestedRootFrontier`
                          (`--auto-bypass-if-clear` persists settled state when clear; `--seed-if-needed`
                          writes `openFrontier` onto disk immediately)
  save-frontier           Save active `openFrontier` questions (`clarificationStatus = IN_PROGRESS`)
  flag-conflict           Called by ANY skill/subagent when encountering unclear, contradictory, conflicting,
                          or ambiguous inputs — pushes a `contradiction-conflict` question onto `openFrontier`
                          and halts downstream gates until resolved with the human/BA
  record-round            Append resolved `DECISION-NN` items (+ optional `capabilityDispositions`), clear
                          answered frontier questions, and mark `stage` settled when `openFrontier` is empty
  accept-recommendations  Resolve all open frontier questions for `stage` using `recommendedAnswer`
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
            data.setdefault("stagesSettled", [])
            data.setdefault("roundsCompleted", 0)
            data.setdefault("triggerReasons", [])
            data.setdefault("capabilityDispositions", [])
            data.setdefault("decisions", [])
            data.setdefault("openFrontier", [])
            return data
    return {
        "schemaVersion": dlc.SCHEMA_VERSION,
        "updatedAtUtc": dlc.utc_now_iso(deterministic),
        "clarificationStatus": "IN_PROGRESS",
        "stagesSettled": [],
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


def _next_question_id(existing_frontier: list[dict[str, Any]]) -> str:
    max_q = 0
    for q in existing_frontier:
        qid = str(q.get("questionId") or "")
        if qid.startswith("Q") and qid[1:].isdigit():
            max_q = max(max_q, int(qid[1:]))
    return f"Q{max_q + 1}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument(
        "--action",
        required=True,
        choices=["detect", "save-frontier", "flag-conflict", "record-round", "accept-recommendations", "status"],
    )
    ap.add_argument(
        "--stage",
        default="pre-spec",
        choices=["gate1", "pre-spec", "pre-stories", "stories", "stage3", "stage4a", "anytime"],
    )
    ap.add_argument("--auto-bypass-if-clear", action="store_true",
                    help="When detect finds needsClarification=false, mark stage settled in specs/clarification_decisions.json")
    ap.add_argument("--seed-if-needed", action="store_true",
                    help="When detect finds needsClarification=true, write suggestedRootFrontier to specs/clarification_decisions.json")
    ap.add_argument("--frontier-json", default=None, help="JSON array of openFrontier question objects")
    ap.add_argument("--decisions-json", default=None, help="JSON array of resolved decision objects")
    ap.add_argument("--dispositions-json", default=None, help="JSON array of capabilityDispositions objects")
    ap.add_argument("--next-frontier-json", default="[]", help="JSON array of dependent child frontier questions for the next round")
    # Flags for `--action flag-conflict`
    ap.add_argument("--category", default="contradiction-conflict")
    ap.add_argument("--evidence", default=None, help="Conflicting/ambiguous file(s) or spec section(s)")
    ap.add_argument("--question", default=None, help="Clear question for the Business Analyst / human")
    ap.add_argument("--recommended", default=None, help="Evidence-backed recommended resolution")
    ap.add_argument("--deterministic", action="store_true")
    args = ap.parse_args()

    root = dlc.resolve_project_root(args.project_root)
    norm_stage = dlc.normalize_clarification_stage(args.stage)

    if args.action == "detect":
        report = dlc.build_clarification_frontier(root, stage=norm_stage)
        if not report["needsClarification"] and args.auto_bypass_if_clear:
            ledger = load_or_init_ledger(root, args.deterministic)
            if norm_stage in ("pre-spec", "pre-stories", "stage4a") and norm_stage not in ledger["stagesSettled"]:
                ledger["stagesSettled"].append(norm_stage)
            if not ledger["openFrontier"] and not ledger["decisions"]:
                ledger["clarificationStatus"] = (
                    "AUTONOMOUS_ASSUMPTIONS" if dlc.is_autonomous_or_golden(root) else "CLEAR_AUTO_BYPASSED"
                )
            elif not ledger["openFrontier"] and ledger["clarificationStatus"] == "IN_PROGRESS":
                ledger["clarificationStatus"] = "RESOLVED_BY_HUMAN"
            save_and_validate_ledger(root, ledger, args.deterministic)
        elif report["needsClarification"] and args.seed_if_needed:
            dlc.auto_seed_clarification_stage(root, norm_stage, deterministic=args.deterministic)
        print(json.dumps(report, indent=2))
        return 0

    if args.action == "save-frontier":
        if not args.frontier_json:
            raise dlc.GateFailure("--frontier-json is required for --action save-frontier.")
        frontier = json.loads(args.frontier_json)
        if not isinstance(frontier, list) or not (1 <= len(frontier) <= 4):
            raise dlc.GateFailure("--frontier-json must be a JSON array of 1..4 independent frontier questions.")
        for q in frontier:
            if isinstance(q, dict):
                q.setdefault("stage", norm_stage)
        report = dlc.build_clarification_frontier(root, stage=norm_stage)
        ledger = load_or_init_ledger(root, args.deterministic)
        ledger["clarificationStatus"] = "IN_PROGRESS"
        if norm_stage in ledger["stagesSettled"]:
            ledger["stagesSettled"] = [s for s in ledger["stagesSettled"] if s != norm_stage]
        if report["triggerReasons"]:
            ledger["triggerReasons"] = list(dict.fromkeys(ledger["triggerReasons"] + report["triggerReasons"]))
        elif not ledger["triggerReasons"]:
            ledger["triggerReasons"] = ["MANUAL_GRILL_REQUESTED"]
        # Replace open frontier items for this stage while keeping other stages' open items
        other_open = [
            q for q in ledger["openFrontier"]
            if isinstance(q, dict) and dlc.normalize_clarification_stage(q.get("stage")) != norm_stage
        ]
        ledger["openFrontier"] = other_open + frontier
        out = save_and_validate_ledger(root, ledger, args.deterministic)
        print(json.dumps({"saved": str(out), "clarificationStatus": ledger["clarificationStatus"], "openFrontierCount": len(ledger["openFrontier"])}, indent=2))
        return 0

    if args.action == "flag-conflict":
        if not args.question or not args.recommended or not args.evidence:
            raise dlc.GateFailure("--action flag-conflict requires --evidence, --question, and --recommended.")
        ledger = load_or_init_ledger(root, args.deterministic)
        qid = _next_question_id(ledger["openFrontier"])
        new_q = {
            "questionId": qid,
            "stage": norm_stage,
            "round": max(1, int(ledger.get("roundsCompleted") or 0) + 1),
            "parentDecisionId": None,
            "category": args.category,
            "evidenceSource": args.evidence,
            "question": args.question,
            "recommendedAnswer": args.recommended,
        }
        ledger["openFrontier"].append(new_q)
        ledger["clarificationStatus"] = "IN_PROGRESS"
        if norm_stage in ledger["stagesSettled"]:
            ledger["stagesSettled"] = [s for s in ledger["stagesSettled"] if s != norm_stage]
        if "AGENT_FLAGGED_CONFLICT_OR_AMBIGUITY" not in ledger["triggerReasons"]:
            ledger["triggerReasons"].append("AGENT_FLAGGED_CONFLICT_OR_AMBIGUITY")
        out = save_and_validate_ledger(root, ledger, args.deterministic)
        print(json.dumps({
            "saved": str(out),
            "clarificationStatus": ledger["clarificationStatus"],
            "flaggedQuestion": new_q,
            "openFrontierCount": len(ledger["openFrontier"]),
        }, indent=2))
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
            entry.setdefault("stage", norm_stage)
            entry.setdefault("round", new_round)
            entry.setdefault("resolvedBy", "user")
            ledger["decisions"].append(entry)

        if incoming_disps:
            by_target = {d["targetId"]: d for d in ledger.get("capabilityDispositions") or [] if isinstance(d, dict) and d.get("targetId")}
            for disp in incoming_disps:
                if isinstance(disp, dict) and disp.get("targetId"):
                    by_target[str(disp["targetId"])] = disp
            ledger["capabilityDispositions"] = list(by_target.values())

        for nq in next_frontier:
            if isinstance(nq, dict):
                nq.setdefault("stage", norm_stage)

        other_open = [
            q for q in ledger["openFrontier"]
            if isinstance(q, dict) and dlc.normalize_clarification_stage(q.get("stage")) not in (norm_stage, "anytime")
        ]
        ledger["roundsCompleted"] = new_round
        ledger["openFrontier"] = other_open + next_frontier
        if not next_frontier and norm_stage in ("pre-spec", "pre-stories", "stage4a") and norm_stage not in ledger["stagesSettled"]:
            ledger["stagesSettled"].append(norm_stage)
        ledger["clarificationStatus"] = "IN_PROGRESS" if ledger["openFrontier"] else "RESOLVED_BY_HUMAN"
        if not ledger["triggerReasons"]:
            report = dlc.build_clarification_frontier(root, stage=norm_stage)
            ledger["triggerReasons"] = report["triggerReasons"] or ["USER_CLARIFICATION_RECORDED"]
        out = save_and_validate_ledger(root, ledger, args.deterministic)
        print(json.dumps({
            "saved": str(out),
            "clarificationStatus": ledger["clarificationStatus"],
            "stagesSettled": ledger["stagesSettled"],
            "roundsCompleted": ledger["roundsCompleted"],
            "totalDecisions": len(ledger["decisions"]),
            "openFrontierCount": len(ledger["openFrontier"]),
        }, indent=2))
        return 0

    if args.action == "accept-recommendations":
        ledger = load_or_init_ledger(root, args.deterministic)
        stage_open = [
            q for q in (ledger.get("openFrontier") or [])
            if isinstance(q, dict) and (
                norm_stage == "anytime"
                or dlc.normalize_clarification_stage(q.get("stage")) in (norm_stage, "anytime")
            )
        ]
        other_open = [q for q in (ledger.get("openFrontier") or []) if q not in stage_open]
        if not stage_open:
            report = dlc.build_clarification_frontier(root, stage=norm_stage)
            stage_open = report.get("suggestedRootFrontier") or []
            if report.get("triggerReasons"):
                ledger["triggerReasons"] = list(dict.fromkeys(ledger["triggerReasons"] + report["triggerReasons"]))
        if stage_open:
            new_round = int(ledger.get("roundsCompleted") or 0) + 1
            for q in stage_open:
                ledger["decisions"].append({
                    "id": _next_decision_id(ledger["decisions"]),
                    "stage": q.get("stage") or norm_stage,
                    "round": int(q.get("round") or new_round),
                    "parentDecisionId": q.get("parentDecisionId"),
                    "category": q.get("category", "workflow-state"),
                    "evidenceSource": q.get("evidenceSource", "Stage discovery/spec review"),
                    "question": q["question"],
                    "recommendedAnswer": q["recommendedAnswer"],
                    "resolvedAnswer": q["recommendedAnswer"],
                    "resolvedBy": "accepted-recommendation",
                })
            ledger["roundsCompleted"] = new_round
        ledger["openFrontier"] = other_open
        if norm_stage in ("pre-spec", "pre-stories", "stage4a") and norm_stage not in ledger["stagesSettled"]:
            ledger["stagesSettled"].append(norm_stage)
        ledger["clarificationStatus"] = "IN_PROGRESS" if ledger["openFrontier"] else "ACCEPTED_RECOMMENDATIONS"
        out = save_and_validate_ledger(root, ledger, args.deterministic)
        print(json.dumps({
            "saved": str(out),
            "clarificationStatus": ledger["clarificationStatus"],
            "stagesSettled": ledger["stagesSettled"],
            "totalDecisions": len(ledger["decisions"]),
            "openFrontierCount": len(ledger["openFrontier"]),
        }, indent=2))
        return 0

    if args.action == "status":
        p = decisions_path(root)
        if not p.is_file():
            print(json.dumps({"present": False, "clarificationStatus": "NOT_STARTED", "stagesSettled": []}, indent=2))
            return 0
        ledger = dlc.read_json(p)
        print(json.dumps({
            "present": True,
            "clarificationStatus": ledger.get("clarificationStatus"),
            "stagesSettled": ledger.get("stagesSettled") or [],
            "roundsCompleted": ledger.get("roundsCompleted", 0),
            "decisionIds": [d.get("id") for d in (ledger.get("decisions") or [])],
            "capabilityDispositions": ledger.get("capabilityDispositions") or [],
            "openFrontierCount": len(ledger.get("openFrontier") or []),
            "openFrontier": ledger.get("openFrontier") or [],
        }, indent=2))
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
