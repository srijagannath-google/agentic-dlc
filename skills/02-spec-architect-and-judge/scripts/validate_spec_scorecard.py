#!/usr/bin/env python3
"""Gate 2 — validate the LLM spec-judge scorecard (02-spec-architect-and-judge).

Implements docs/ARCHITECTURE.md §4.4: every rubric criterion present, awarded ≤ max, pillar totals and total
add up, `specSha256` matches the current spec (stale scorecards fail), verbatim evidence for every criterion
awarded > 0, and verdict == (total ≥ passingScore and no blocking criterion scored 0). It then regenerates
`specs/application_eval_scorecard.md` from the JSON so the two never drift.

Usage:
    python3 validate_spec_scorecard.py --project-root <PROJECT_ROOT>
            [--scorecard specs/application_eval_scorecard.json] [--rubric <plugin>/schemas/spec_rubric.json]
            [--no-markdown] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import dlc_common as dlc  # noqa: E402

QUOTE_SPLIT_RE = re.compile(r"\s+(?:…|\.\.\.|\[\.\.\.\]|\[…\])\s+")
MIN_EVIDENCE_CHARS = 25
MIN_EVIDENCE_WORDS = 5
PILLAR_HEADING_RE = {1: r"pillar\s*1\b", 2: r"pillar\s*2\b", 3: r"pillar\s*3\b", 4: r"pillar\s*4\b", 5: r"pillar\s*5\b"}


def split_quotes(evidence: str) -> list[str]:
    out = []
    for q in QUOTE_SPLIT_RE.split(evidence):
        q = q.strip().strip('"“”\'')
        if q:
            out.append(q)
    return out


def evidence_found(evidence: str, spec_norm: str) -> tuple[bool, list[str]]:
    """All ' … '-separated quotes must be present (whitespace-normalised, case-insensitive, md markers ignored)."""
    missing = []
    for q in split_quotes(evidence):
        qn = dlc.normalise_ws(dlc.strip_md(q))
        if qn and qn not in spec_norm:
            missing.append(q)
    return (not missing, missing)


def evidence_substance(evidence: str, criterion_id: str) -> str | None:
    """Reject token-sized 'evidence' (a single word, a bare id, the criterion id itself). Returns a reason or None."""
    norm = dlc.normalise_ws(dlc.strip_md(" ".join(split_quotes(evidence))))
    if norm == criterion_id.lower() or re.fullmatch(r"p[1-5]-c\d+", norm):
        return "evidence is just the criterion id"
    if len(norm) < MIN_EVIDENCE_CHARS or len(norm.split()) < MIN_EVIDENCE_WORDS:
        return f"evidence too short to be a verbatim quote ({len(norm)} chars / {len(norm.split())} words; need ≥ {MIN_EVIDENCE_CHARS} chars and ≥ {MIN_EVIDENCE_WORDS} words)"
    return None


def render_markdown(sc: dict, rubric: dict, checks_failed: list[str], computed_verdict: str, spec_rel: str) -> str:
    crit_by_id = {c["id"]: c for c in rubric["criteria"]}
    pillar_meta = {p["pillar"]: p for p in rubric["pillars"]}
    out = [
        "# Specification Quality Scorecard (Gate 2)",
        "",
        f"- **Specification Audited:** `{spec_rel}` (sha256 `{sc.get('specSha256', '')[:12]}…`)",
        f"- **Input Scenario:** {dlc.scenario_display_label(sc.get('inputScenario', ''))}",
        f"- **Rubric Version:** `{sc.get('rubricVersion', '')}`",
        f"- **Judged At (UTC):** `{sc.get('judgedAtUtc', 'n/a')}`",
        f"- **TOTAL_SCORE:** `{sc.get('totalScore', 0)}/{rubric.get('maxScore', 100)}` (pass threshold `{rubric.get('passingScore', 90)}`)",
        f"- **OVERALL_VERDICT:** `{computed_verdict}`",
        "",
        "> Synchronized from `specs/application_eval_scorecard.json`.",
        "",
    ]
    for pn in sorted(pillar_meta):
        meta = pillar_meta[pn]
        tot = sc.get("pillarTotals", {}).get(str(pn), 0)
        out += [f"## Pillar {pn} — {meta['title']} (`{tot}/{meta['maxPoints']}`)", "",
                "| Criterion | Title | Awarded | Max | Blocking | Evidence (verbatim) | Gap |",
                "| :-- | :-- | :-: | :-: | :-: | :-- | :-- |"]
        for c in sc.get("criteria", []):
            if c.get("pillar") != pn:
                continue
            r = crit_by_id.get(c["id"], {})
            ev = str(c.get("evidence", "")).replace("|", "\\|").replace("\n", " ")
            gap = str(c.get("gap", "")).replace("|", "\\|").replace("\n", " ")
            out.append(f"| `{c['id']}` | {r.get('title', '')} | {c.get('awarded', 0)} | {c.get('maxPoints', r.get('maxPoints', 0))} | "
                       f"{'yes' if r.get('blocking') else 'no'} | {ev[:400]} | {gap[:300]} |")
        out.append("")
    out += ["## Blocking Gaps", ""]
    out += [f"- {g}" for g in sc.get("blockingGaps", [])] or ["- None"]
    out += ["", "## Validator Findings", ""]
    out += [f"- ✗ {f}" for f in checks_failed] or ["- All structural checks passed."]
    out.append("")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument("--scorecard", default="specs/application_eval_scorecard.json")
    ap.add_argument("--rubric", default=str(dlc.schema_path("spec_rubric.json")))
    ap.add_argument("--markdown-out", default="specs/application_eval_scorecard.md")
    ap.add_argument("--no-markdown", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = dlc.resolve_project_root(args.project_root)
    dlc.require_gate_approved(root, "gate_1_discovery", "Stage 2 (02-spec-architect-and-judge / validate_spec_scorecard.py)")
    inv = dlc.load_inventory(root)
    scenario = inv.get("inputScenario", "SCENARIO_REQUIREMENTS_DOC")
    spec_path = root / "specs" / "application_spec.md"
    spec = dlc.load_spec(root)
    spec_norm = dlc.normalise_ws(dlc.strip_md(spec))
    # Per-pillar scope for the (WARN-only) "evidence belongs to its pillar" check. The header block (before the first
    # `## ` heading: scenario, slug, ASSUMPTION-NN), the parsed lifecycle tables (§3.3–§3.5) and the traceability
    # section are cited legitimately from every pillar, so they are part of every pillar's scope.
    header_block = re.split(r"^##\s+", spec, maxsplit=1, flags=re.MULTILINE)[0]

    def _section(*patterns: str) -> str:
        for pat in patterns:
            sec = dlc.md_section(spec, pat)
            if sec:
                return sec
        return ""

    shared_scope = "\n".join([
        header_block,
        _section(r"^3\.3\b", r"lifecycle state machine|state[- ]transition"),
        _section(r"^3\.4\b", r"business rules\s*(?:&|and)\s*formulas"),
        _section(r"^3\.5\b", r"^roles\b"),
        _section(r"^6\b.*traceability", r"^traceability"),
    ])
    shared_norm = dlc.normalise_ws(dlc.strip_md(shared_scope))
    pillar_norm = {pn: dlc.normalise_ws(dlc.strip_md(dlc.md_section(spec, pat))) + "\n" + shared_norm for pn, pat in PILLAR_HEADING_RE.items()}
    spec_sha = dlc.sha256_file(spec_path)
    rubric = dlc.read_json(dlc.require_file(Path(args.rubric), "plugin schemas/spec_rubric.json"))
    sc_path = dlc.require_file(dlc.project_path(root, args.scorecard), "Stage 2 LLM judge (spec-judge) — write the JSON scorecard against schemas/spec_rubric.json")
    sc = dlc.read_json(sc_path)

    fails: list[str] = []
    warns: list[str] = []
    fails += dlc.validate_against_schema(sc, dlc.load_schema("spec_scorecard.schema.json"))

    # Rubric sanity (points per pillar must sum)
    pillar_max = {p["pillar"]: p["maxPoints"] for p in rubric["pillars"]}
    for pn, mx in pillar_max.items():
        s = sum(c["maxPoints"] for c in rubric["criteria"] if c["pillar"] == pn)
        if s != mx:
            fails.append(f"Rubric inconsistency: pillar {pn} criteria sum to {s}, declared {mx}.")

    # Freshness & scenario
    if sc.get("specSha256") != spec_sha:
        fails.append(f"stale: scorecard specSha256 {str(sc.get('specSha256'))[:12]}… ≠ current spec {spec_sha[:12]}… — re-judge the current specs/application_spec.md.")
    if sc.get("inputScenario") != scenario:
        fails.append(f"Scorecard inputScenario {sc.get('inputScenario')} ≠ inventory {scenario}.")
    if str(sc.get("rubricVersion")) != str(rubric.get("rubricVersion")):
        warns.append(f"rubricVersion {sc.get('rubricVersion')} ≠ rubric file {rubric.get('rubricVersion')}.")

    # Criteria coverage & scoring
    got = {c.get("id"): c for c in sc.get("criteria", []) if isinstance(c, dict)}
    rubric_ids = [c["id"] for c in rubric["criteria"]]
    for rid in rubric_ids:
        if rid not in got:
            fails.append(f"Criterion {rid} missing from scorecard.")
    for cid in got:
        if cid not in rubric_ids:
            fails.append(f"Unknown criterion {cid} (not in rubric).")
    dup = [cid for cid in rubric_ids if sum(1 for c in sc.get("criteria", []) if c.get("id") == cid) > 1]
    if dup:
        fails.append(f"Duplicate criteria: {', '.join(dup)}")

    pillar_sum = {pn: 0 for pn in pillar_max}
    blocking_zero: list[str] = []
    for rc in rubric["criteria"]:
        c = got.get(rc["id"])
        if not c:
            continue
        awarded = c.get("awarded", 0)
        if not isinstance(awarded, int) or isinstance(awarded, bool):
            fails.append(f"{rc['id']}: awarded must be an integer.")
            continue
        if c.get("maxPoints") != rc["maxPoints"]:
            fails.append(f"{rc['id']}: maxPoints {c.get('maxPoints')} ≠ rubric {rc['maxPoints']}.")
        if c.get("pillar") != rc["pillar"]:
            fails.append(f"{rc['id']}: pillar {c.get('pillar')} ≠ rubric {rc['pillar']}.")
        if awarded < 0 or awarded > rc["maxPoints"]:
            fails.append(f"{rc['id']}: awarded {awarded} outside 0..{rc['maxPoints']}.")
        pillar_sum[rc["pillar"]] = pillar_sum.get(rc["pillar"], 0) + awarded
        applies = rc.get("appliesTo")
        if applies and scenario not in applies:
            if awarded != rc["maxPoints"]:
                fails.append(f"{rc['id']}: not applicable to {scenario} — must be awarded maxPoints ({rc['maxPoints']}) with evidence 'N/A …'.")
            continue
        ev = str(c.get("evidence", "")).strip()
        if awarded > 0:
            if not ev:
                fails.append(f"{rc['id']}: awarded {awarded} but evidence is empty.")
            else:
                weak = evidence_substance(ev, rc["id"])
                if weak:
                    fails.append(f"{rc['id']}: {weak}: {ev[:120]!r}")
                ok, missing = evidence_found(ev, spec_norm)
                if not ok:
                    fails.append(f"{rc['id']}: evidence not found verbatim in spec: {missing[0][:120]!r}")
                elif not weak:
                    # At least one quote should come from the criterion's own pillar section (WARN: the lifecycle tables
                    # §3.3–§3.5 and the header block are legitimately cited across pillars, but when *no* quote touches
                    # the pillar being scored the judge usually scored the wrong thing).
                    sec_norm = pillar_norm.get(rc["pillar"], "")
                    for extra_pat in rc.get("evidenceSections") or []:
                        sec_norm += "\n" + dlc.normalise_ws(dlc.strip_md(_section(str(extra_pat))))
                    if sec_norm.strip():
                        quotes = [dlc.normalise_ws(dlc.strip_md(q)) for q in split_quotes(ev)]
                        if quotes and not any(q in sec_norm for q in quotes):
                            warns.append(f"{rc['id']}: none of the evidence quotes is inside the Pillar {rc['pillar']} section: {ev[:100]!r}")
        if awarded < rc["maxPoints"] and not str(c.get("gap", "")).strip():
            warns.append(f"{rc['id']}: awarded {awarded}/{rc['maxPoints']} but gap is empty.")
        if rc.get("blocking") and awarded == 0:
            blocking_zero.append(rc["id"])

    for pn, mx in pillar_max.items():
        declared = sc.get("pillarTotals", {}).get(str(pn))
        if declared != pillar_sum[pn]:
            fails.append(f"pillarTotals[{pn}] = {declared} but criteria sum to {pillar_sum[pn]}.")
    total_calc = sum(pillar_sum.values())
    if sc.get("totalScore") != total_calc:
        fails.append(f"totalScore {sc.get('totalScore')} ≠ sum of criteria {total_calc}.")

    passing = rubric.get("passingScore", 90)
    computed = "PASS" if total_calc >= passing and not blocking_zero and not fails else "FAIL"
    expected_verdict = "PASS" if total_calc >= passing and not blocking_zero else "FAIL"
    if sc.get("verdict") != expected_verdict:
        fails.append(f"verdict {sc.get('verdict')} inconsistent — total {total_calc} ≥ {passing}: {total_calc >= passing}; blocking criteria at 0: {blocking_zero or 'none'} ⇒ {expected_verdict}.")
    if blocking_zero and not sc.get("blockingGaps"):
        warns.append(f"blocking criteria scored 0 ({', '.join(blocking_zero)}) but blockingGaps is empty.")
    fails.extend(dlc.scan_deliverable_internal_leaks(root, ["specs/application_spec.md", "specs/traceability_matrix.md", args.scorecard]))
    if fails:
        computed = "FAIL"

    if not args.no_markdown:
        md_out = dlc.project_path(root, args.markdown_out)
        try:
            spec_rel = str(spec_path.relative_to(root))
        except ValueError:
            spec_rel = str(spec_path)
        md_content = render_markdown(sc, rubric, fails, computed, spec_rel)
        # Preserve each scorecard run in specs/history/iter-N/ so failed/prior judge runs are never overwritten
        hist_root = root / "specs" / "history"
        existing_iters = [
            int(m.group(1))
            for p in (hist_root.glob("iter-*") if hist_root.is_dir() else [])
            if (m := re.match(r"^iter-(\d+)$", p.name))
        ]
        sc_bytes = sc_path.read_bytes() if sc_path.is_file() else b""
        latest_hist_json = (hist_root / f"iter-{max(existing_iters)}" / "application_eval_scorecard.json") if existing_iters else None
        if latest_hist_json is None or not latest_hist_json.is_file() or latest_hist_json.read_bytes() != sc_bytes:
            next_it = (max(existing_iters) + 1) if existing_iters else int(sc.get("iteration") or 1)
            if (hist_root / f"iter-{next_it}").exists():
                next_it = max(existing_iters) + 1
            it_dir = hist_root / f"iter-{next_it}"
            it_dir.mkdir(parents=True, exist_ok=True)
            if sc_path.is_file():
                dlc.write_text(it_dir / "application_eval_scorecard.json", dlc.read_text(sc_path))
            dlc.write_text(it_dir / "application_eval_scorecard.md", md_content)
        dlc.write_text(md_out, md_content)

    result = {"verdict": computed, "totalScore": total_calc, "pillarTotals": pillar_sum, "blockingZero": blocking_zero,
              "failures": fails, "warnings": warns}
    dlc.record_validation_diagnostic(root, "validate_spec_scorecard.py", computed == "PASS", fails, warns)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for w in warns:
            dlc.warn(w)
        for f in fails:
            print(f"  ✗ {f}")
        print(f"[dlc] Gate 2 scorecard: {computed} — total {total_calc}/{rubric.get('maxScore', 100)}, "
              f"pillars {pillar_sum}, blocking@0={blocking_zero or 'none'}")
        if computed == "PASS":
            if dlc.active_spec_lifecycle_mode(root) != "retro-spec":
                seeded_stories = dlc.auto_seed_clarification_stage(root, "pre-stories")
                if seeded_stories.get("needsClarification") and seeded_stories.get("openFrontier"):
                    print("\n" + dlc.format_grill_me_banner("pre-stories", seeded_stories["openFrontier"]))
            dlc.mark_gate_awaiting_human(
                root,
                "gate_2_spec",
                summary=f"Stage 2 5-Pillar Specification passed Spec Judge ({total_calc}/{rubric.get('maxScore', 100)}). Present application_spec.md, scorecard, and any 🔥 Pre-Stories BA Grill-Me questions to user and STOP for Gate 2 approval before Stage 3.",
            )
    return 0 if computed == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
