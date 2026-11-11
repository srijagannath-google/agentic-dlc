#!/usr/bin/env python3
"""Machine-enforced Human Gate Ledger CLI (`specs/gate_approvals.json`).

Records and verifies explicit human approval at every stage boundary (`gate_0_setup` .. `gate_9_deployment`)
so skills and subagents NEVER auto-advance to the next stage without pausing for human review.

Usage:
    python3 gate_tracker.py --project-root <PROJECT_ROOT> --action init [--autonomous]
    python3 gate_tracker.py --project-root <PROJECT_ROOT> --action status
    python3 gate_tracker.py --project-root <PROJECT_ROOT> --action mark-ready --gate <gate_id> [--summary "..."]
    python3 gate_tracker.py --project-root <PROJECT_ROOT> --action approve --gate <gate_id> --user-response "<verbatim user approval>"
    python3 gate_tracker.py --project-root <PROJECT_ROOT> --action reset [--gate <gate_id>]
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dlc_common as dlc  # noqa: E402

MIN_HUMAN_REVIEW_SECONDS = 8.0


def _validate_and_write_ledger(root: Path, data: dict) -> None:
    errs = dlc.validate_against_schema(data, dlc.load_schema("gate_approvals.schema.json"))
    if errs:
        raise dlc.GateFailure("gate_approvals.json schema error:\n  " + "\n  ".join(errs))
    dlc.write_json(dlc.gate_approvals_path(root), data)


def cmd_init(root: Path, autonomous: bool, track: str | None = None) -> int:
    path = dlc.gate_approvals_path(root)
    resolved_track = track if track in dlc.CEREMONY_TRACKS else dlc.active_ceremony_track(root)
    fresh = dlc.new_gate_ledger(autonomous=autonomous, ceremony_track=resolved_track)
    if path.exists():
        existing = dlc.load_gate_approvals(root)
        ex_gates = existing.get("gates") or {}
        for gid, default_entry in fresh["gates"].items():
            cur = ex_gates.get(gid)
            if isinstance(cur, dict) and cur.get("status") in dlc.GATE_APPROVED_STATUSES:
                fresh["gates"][gid] = cur
            elif isinstance(cur, dict) and cur.get("status") == dlc.GATE_STATUS_AWAITING and not autonomous:
                fresh["gates"][gid] = cur
        if existing.get("initializedAtUtc"):
            fresh["initializedAtUtc"] = existing["initializedAtUtc"]
        if track is None and existing.get("ceremonyTrack") in dlc.CEREMONY_TRACKS:
            fresh["ceremonyTrack"] = existing["ceremonyTrack"]
    _validate_and_write_ledger(root, fresh)
    setup_p = root / "specs" / "project_setup.json"
    if track in dlc.CEREMONY_TRACKS and setup_p.is_file():
        setup_obj = dlc.read_json(setup_p)
        if isinstance(setup_obj, dict):
            setup_obj["ceremonyTrack"] = track
            dlc.write_json(setup_p, setup_obj)
    dlc.info(
        f"initialised human gate ledger at {path} (ceremonyTrack={fresh.get('ceremonyTrack', 'standard')})"
        + (" (autonomous defaults applied to Gates 0/1/3/4)" if autonomous else "")
    )
    return 0


def cmd_set_track(root: Path, track: str) -> int:
    if track not in dlc.CEREMONY_TRACKS:
        raise dlc.GateFailure(f"Invalid track '{track}'. Choose from: {', '.join(dlc.CEREMONY_TRACKS)}")
    data = dlc.load_gate_approvals(root)
    if not data.get("gates"):
        data = dlc.new_gate_ledger(autonomous=False, ceremony_track=track)
    else:
        data["ceremonyTrack"] = track
    _validate_and_write_ledger(root, data)
    setup_p = root / "specs" / "project_setup.json"
    if setup_p.is_file():
        setup_obj = dlc.read_json(setup_p)
        if isinstance(setup_obj, dict):
            setup_obj["ceremonyTrack"] = track
            dlc.write_json(setup_p, setup_obj)
    dlc.info(f"updated ceremonyTrack -> '{track}' in {dlc.gate_approvals_path(root)}")
    return 0


def cmd_status(root: Path) -> int:
    p = dlc.gate_approvals_path(root)
    track = dlc.active_ceremony_track(root)
    if not p.exists():
        print(f"Human Gate Approval Ledger — {p} (MISSING — run `--action init` or Stage 0 first)")
    else:
        print(f"Human Gate Approval Ledger — {p}")
    print(f"Active Ceremony Track: {track}")
    data = dlc.load_gate_approvals(root)
    gates = data.get("gates") or {}
    print(f"{'Gate ID':<26} {'Status':<30} {'Approved At':<22} Stage")
    print("-" * 112)
    for gid, label in dlc.GATE_DEFINITIONS.items():
        entry = gates.get(gid) if isinstance(gates.get(gid), dict) else {}
        st = entry.get("status", "NOT_STARTED")
        app_at = entry.get("approvedAtUtc") or "—"
        brief = entry.get("decisionBriefPath")
        extra = f" [brief: {brief}]" if brief else ""
        print(f"{gid:<26} {st:<30} {str(app_at):<22} {label}{extra}")
    return 0


def _artifact_sha_for_gate(root: Path, gate_id: str) -> str | None:
    """Compute canonical SHA-256 of the primary artifact governed by `gate_id` when present."""
    mapping = {
        "gate_1_discovery": root / "specs" / "discovery_architecture_and_inventory.md",
        "gate_2_spec": root / "specs" / "application_spec.md",
        "gate_4_design_and_tests": root / "design" / "solution_design.md",
        "gate_7_drift": root / "test" / "drift_report.json",
    }
    if gate_id == "gate_3_backlog":
        sp = root / "backlog" / "user_stories.json"
        return dlc.stories_content_sha256(sp) if sp.is_file() else None
    target = mapping.get(gate_id)
    return dlc.sha256_file(target) if (target and target.is_file()) else None


def cmd_approve(
    root: Path,
    gate_id: str,
    user_response: str | None,
    autonomous: bool,
    approvers_raw: list[str] | None = None,
    original_author: str | None = None,
    pair_raw: list[str] | None = None,
    verified_by: str | None = None,
    strict_2pc: bool = False,
) -> int:
    if gate_id not in dlc.GATE_DEFINITIONS:
        raise dlc.GateFailure(
            f"Unknown gate '{gate_id}'. Valid gates: {', '.join(dlc.GATE_DEFINITIONS.keys())}"
        )
    if not autonomous:
        resp = (user_response or "").strip()
        if len(resp) < 2:
            raise dlc.GateFailure(
                f"--user-response is required when approving {gate_id} in interactive mode.\n"
                "  You MUST stop at the gate, wait for the human's reply in chat, and pass their verbatim approval text."
            )
    else:
        resp = (user_response or "Pre-approved via --autonomous mode").strip()

    approvers, rejected_bots = dlc.sanitize_human_identities(approvers_raw or [])
    if rejected_bots:
        raise dlc.GateFailure(
            f"Cannot approve {gate_id}: excluded robot/agent/bot identity(ies) in --approvers: {', '.join(rejected_bots)}.\n"
            "  Human gate sign-off strictly requires genuine human usernames."
        )
    pair_humans, pair_bots = dlc.sanitize_human_identities(pair_raw or [])
    if pair_bots:
        raise dlc.GateFailure(f"Invalid robot/bot identity in --pair: {', '.join(pair_bots)}.")
    if original_author:
        oa_humans, oa_bots = dlc.sanitize_human_identities([original_author])
        if oa_bots or not oa_humans:
            raise dlc.GateFailure(f"--original-author must be a single human username (got {original_author!r}).")
        original_author = oa_humans[0]
    if verified_by:
        vb_humans, vb_bots = dlc.sanitize_human_identities([verified_by])
        if vb_bots or not vb_humans:
            raise dlc.GateFailure(f"--verified-by must be a human verifier username (got {verified_by!r}).")
        verified_by = vb_humans[0]

    track = dlc.active_ceremony_track(root)
    if not autonomous and (strict_2pc or (track == "regulated" and approvers_raw is not None)):
        if len(approvers) < 2:
            raise dlc.GateFailure(
                f"Two-Person Review requirement failed for {gate_id} on '{track}' track: "
                f"expected >= 2 distinct human approvers (got {len(approvers)}: {approvers or 'none'})."
            )

    data = dlc.load_gate_approvals(root)
    gates = data.setdefault("gates", {})
    existing = gates.get(gate_id) if isinstance(gates.get(gate_id), dict) else {}

    # Anti-self-approval turn-boundary guard:
    # In interactive mode, the stage validator MUST have stamped AWAITING_HUMAN_REVIEW (setting readyAtEpoch),
    # and at least MIN_HUMAN_REVIEW_SECONDS must have elapsed before `approve` is accepted. This blocks both
    # `reset` -> `approve` bypasses (readyAtEpoch is None) and same-turn validation + self-approval.
    if not autonomous:
        ready_epoch = existing.get("readyAtEpoch")
        if ready_epoch is None or existing.get("status") not in (dlc.GATE_STATUS_AWAITING, dlc.GATE_STATUS_APPROVED):
            raise dlc.GateFailure(
                f"Cannot approve {gate_id}: gate has not been marked ready for human review yet (status='{existing.get('status', 'NOT_STARTED')}').\n"
                "  Run the stage's validation script (or `--action mark-ready --gate "
                f"{gate_id}`) first, present the deliverables to the user, END YOUR TURN, and wait for their reply."
            )
        elapsed = time.time() - float(ready_epoch)
        if elapsed < MIN_HUMAN_REVIEW_SECONDS:
            raise dlc.GateFailure(
                f"Refusing to self-approve {gate_id} ({elapsed:.1f}s after stage completion < {MIN_HUMAN_REVIEW_SECONDS:.0f}s human-turn boundary)!\n"
                "  NEVER call `gate_tracker.py --action approve` in the same turn a stage completes.\n"
                "  Present the deliverables to the user, END YOUR TURN, and wait for the human's explicit approval reply!"
            )

    # Extra validation for Gate 0: ensure ADO project / input source has been selected in specs/project_setup.json
    setup_file = root / "specs" / "project_setup.json"
    if gate_id == "gate_0_setup" and setup_file.exists():
        setup_data = dlc.read_json(setup_file)
        inp = setup_data.get("inputSource") or {}
        if inp.get("kind") in (None, "", "tbd"):
            raise dlc.GateFailure(
                "Cannot approve gate_0_setup: inputSource.kind in specs/project_setup.json is still 'tbd'. "
                "Ask the user which input source / ADO project & repository they want to use first."
            )
        if inp.get("kind") == "ado" and not inp.get("adoProject"):
            raise dlc.GateFailure(
                "Cannot approve gate_0_setup: inputSource.adoProject is missing in specs/project_setup.json. "
                "Ask the user which Azure DevOps Project (and repository) they want to work on before proceeding!"
            )
        setup_data["setupStatus"] = "PRE_APPROVED_AUTONOMOUS" if autonomous else "APPROVED_BY_USER"
        setup_data["updatedAtUtc"] = dlc.utc_now_iso(False)
        dlc.write_json(setup_file, setup_data)

    # Enforce Pre-Spec & Pre-Stories Grill-Me resolution before unlocking Gate 1 or Gate 3 in interactive mode
    if not autonomous and gate_id in ("gate_1_discovery", "gate_3_backlog"):
        clar_file = root / "specs" / "clarification_decisions.json"
        req_stage = "pre-spec" if gate_id == "gate_1_discovery" else "pre-stories"
        if clar_file.is_file():
            clar_obj = dlc.read_json(clar_file)
            open_f = (clar_obj.get("openFrontier") or []) if isinstance(clar_obj, dict) else []
            matching_open = [
                q for q in open_f
                if not isinstance(q, dict) or dlc.normalize_clarification_stage(q.get("stage")) in (req_stage, "anytime")
            ]
            if matching_open:
                raise dlc.GateFailure(
                    f"Cannot approve {gate_id}: {len(matching_open)} unresolved 🔥 Grill-Me question(s) remain in "
                    f"specs/clarification_decisions.json for stage '{req_stage}'.\n"
                    "  Engage the Business Analyst / human on those questions first and record their answers via:\n"
                    f"  python3 \"{dlc.PLUGIN_ROOT / 'skills/clarification-griller/scripts/clarification_interview.py'}\" "
                    f"--project-root \"{root}\" --stage {req_stage} --action record-round --decisions-json '[...]'\n"
                    "  (or `--action accept-recommendations` if the user accepted the recommended answers)."
                )

    now_iso = dlc.utc_now_iso(False)
    status_val = dlc.GATE_STATUS_PRE_APPROVED if autonomous else dlc.GATE_STATUS_APPROVED
    entry_out = {
        "gateId": gate_id,
        "stage": dlc.GATE_DEFINITIONS[gate_id],
        "status": status_val,
        "readyAtUtc": existing.get("readyAtUtc") or now_iso,
        "readyAtEpoch": existing.get("readyAtEpoch"),
        "approvedAtUtc": now_iso,
        "userResponse": resp,
        "summary": existing.get("summary") or f"{dlc.GATE_DEFINITIONS[gate_id]} approved.",
        "decisionBriefPath": existing.get("decisionBriefPath"),
        "artifactSha256": _artifact_sha_for_gate(root, gate_id),
    }
    if approvers:
        entry_out["approvers"] = approvers
    elif existing.get("approvers"):
        entry_out["approvers"] = existing["approvers"]
    if original_author or existing.get("originalAuthor"):
        entry_out["originalAuthor"] = original_author or existing.get("originalAuthor")
    if pair_humans:
        # Universal non-exclusion invariant: reviewers who steer implementation remain in `approvers` AND appear in `pairCollaborators`
        entry_out["pairCollaborators"] = pair_humans
    elif existing.get("pairCollaborators"):
        entry_out["pairCollaborators"] = existing["pairCollaborators"]
    if verified_by or existing.get("manuallyVerifiedBy"):
        entry_out["manuallyVerifiedBy"] = verified_by or existing.get("manuallyVerifiedBy")
    gates[gate_id] = entry_out
    _validate_and_write_ledger(root, data)

    # Keep Stage 3 sprint_plan.md / sprint_plan.json marker synchronized when gate_3_backlog is approved
    if gate_id == "gate_3_backlog":
        sp_md = root / "backlog" / "sprint_plan.md"
        marker = "PRE_APPROVED_BY_USER" if autonomous else "APPROVED_BY_USER"
        if sp_md.exists():
            txt = dlc.read_text(sp_md)
            if "SPRINT_ALIGNMENT_APPROVAL:" in txt:
                txt = re.sub(r"SPRINT_ALIGNMENT_APPROVAL:\s*[A-Z_]+", f"SPRINT_ALIGNMENT_APPROVAL: {marker}", txt)
                dlc.write_text(sp_md, txt)
        sp_json = root / "backlog" / "sprint_plan.json"
        if sp_json.exists():
            sp_obj = dlc.read_json(sp_json)
            if isinstance(sp_obj, dict):
                sp_obj["approvalStatus"] = marker
                dlc.write_json(sp_json, sp_obj)

    dlc.info(f"recorded {status_val} for {gate_id} ({dlc.GATE_DEFINITIONS[gate_id]})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument("--action", required=True, choices=["init", "status", "approve", "mark-ready", "reset", "set-track"])
    ap.add_argument("--gate", default=None, help=f"Gate ID ({', '.join(dlc.GATE_DEFINITIONS.keys())})")
    ap.add_argument("--track", default=None, choices=list(dlc.CEREMONY_TRACKS), help="Adaptive ceremony track (quick | standard | regulated)")
    ap.add_argument("--user-response", default=None, help="Verbatim quote from the human's chat reply approving the gate")
    ap.add_argument("--approvers", nargs="*", default=None, help="Comma- or space-separated human approver usernames (bot accounts rejected)")
    ap.add_argument("--original-author", default=None, help="Primary human requester / feature owner username")
    ap.add_argument("--pair", nargs="*", default=None, help="Human collaborator(s) / steering reviewer(s) for dual attribution")
    ap.add_argument("--verified-by", default=None, help="Human UAT / manual verifier username")
    ap.add_argument("--strict-2pc", action="store_true", help="Enforce >= 2 distinct human approvers on this approval")
    ap.add_argument("--summary", default="", help="Optional summary when marking a gate ready")
    ap.add_argument("--autonomous", action="store_true", help="Pre-approve only when the user explicitly requested autonomous mode")
    args = ap.parse_args()

    root = dlc.resolve_project_root(args.project_root)
    if args.action == "init":
        return cmd_init(root, autonomous=args.autonomous, track=args.track)
    if args.action == "set-track":
        if not args.track:
            raise dlc.GateFailure("--track is required for --action set-track")
        return cmd_set_track(root, args.track)
    if args.action == "status":
        return cmd_status(root)
    if args.action == "mark-ready":
        if not args.gate or args.gate not in dlc.GATE_DEFINITIONS:
            raise dlc.GateFailure(f"--gate must be one of: {', '.join(dlc.GATE_DEFINITIONS.keys())}")
        # Force interactive stamping even if DLC_AUTONOMOUS is unset; validate schema afterwards.
        dlc.mark_gate_awaiting_human(root, args.gate, summary=args.summary, force_reset=True)
        return 0
    if args.action == "approve":
        if not args.gate:
            raise dlc.GateFailure("--gate is required for --action approve")
        return cmd_approve(
            root,
            args.gate,
            args.user_response,
            args.autonomous,
            approvers_raw=args.approvers,
            original_author=args.original_author,
            pair_raw=args.pair,
            verified_by=args.verified_by,
            strict_2pc=args.strict_2pc,
        )
    if args.action == "reset":
        if args.gate and args.gate not in dlc.GATE_DEFINITIONS:
            raise dlc.GateFailure(f"--gate must be one of: {', '.join(dlc.GATE_DEFINITIONS.keys())}")
        if not args.gate:
            fresh = dlc.new_gate_ledger(autonomous=False, ceremony_track=args.track or dlc.active_ceremony_track(root))
            _validate_and_write_ledger(root, fresh)
        else:
            data = dlc.load_gate_approvals(root)
            gates = data.setdefault("gates", {})
            label = dlc.GATE_DEFINITIONS[args.gate]
            gates[args.gate] = {
                "gateId": args.gate,
                "stage": label,
                "status": dlc.GATE_STATUS_PENDING,
                "readyAtUtc": None,
                "readyAtEpoch": None,
                "approvedAtUtc": None,
                "userResponse": None,
                "summary": f"{label} — reset to pending.",
                "decisionBriefPath": None,
            }
            _validate_and_write_ledger(root, data)
        dlc.info(f"reset gate ledger ({args.gate or 'ALL'}) in {dlc.gate_approvals_path(root)}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
