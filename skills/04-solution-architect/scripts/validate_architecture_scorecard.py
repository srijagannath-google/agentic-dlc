#!/usr/bin/env python3
"""Gate 4A — validate the Multi-Persona Architecture Red-Team Scorecard (04-solution-architect).

Validates `design/architecture_eval_scorecard.json` against `schemas/architecture_scorecard.schema.json` and
`schemas/architecture_rubric.json`:
  - `architectureSha256` matches current `design/architecture_design.md`
  - `solutionDesignSha256` matches current `design/solution_design.md`
  - Every rubric criterion (`ARCH-DL-*`, `ARCH-SEC-*`, `ARCH-RES-*`, `ARCH-OPS-*`) is present with valid integer score
  - Dimension totals (`DomainLogic`, `SecurityZeroTrust`, `ResilienceScale`, `OperabilityFinOps`) and `totalScore` sum accurately
  - Verbatim evidence quotes exist across the Stage 4A `design/*.md` suite for every criterion awarded > 0
  - `verdict == PASS` iff `totalScore >= passingScore` (90) and zero blocking criteria scored 0
  - Regenerates `design/architecture_eval_scorecard.md` cleanly (zero internal harness leak tokens).

Usage:
    python3 validate_architecture_scorecard.py --project-root <PROJECT_ROOT>
            [--scorecard design/architecture_eval_scorecard.json]
            [--rubric <plugin>/schemas/architecture_rubric.json]
            [--markdown-out design/architecture_eval_scorecard.md] [--no-markdown] [--json]
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


def split_quotes(evidence: str) -> list[str]:
    out: list[str] = []
    for q in QUOTE_SPLIT_RE.split(evidence):
        q = q.strip().strip('"“”\'')
        if q:
            out.append(q)
    return out


def evidence_found(evidence: str, corpus_norm: str) -> tuple[bool, list[str]]:
    missing: list[str] = []
    for q in split_quotes(evidence):
        qn = dlc.normalise_ws(dlc.strip_md(q))
        if qn and qn not in corpus_norm:
            missing.append(q)
    return (not missing, missing)


def evidence_substance(evidence: str, criterion_id: str) -> str | None:
    norm = dlc.normalise_ws(dlc.strip_md(" ".join(split_quotes(evidence))))
    if norm == criterion_id.lower() or re.fullmatch(r"arch-[a-z]+-\d+", norm):
        return "evidence is just the criterion id"
    if len(norm) < MIN_EVIDENCE_CHARS or len(norm.split()) < MIN_EVIDENCE_WORDS:
        return (
            f"evidence too short to be a verbatim quote ({len(norm)} chars / {len(norm.split())} words; "
            f"need >= {MIN_EVIDENCE_CHARS} chars and >= {MIN_EVIDENCE_WORDS} words)"
        )
    return None


def render_markdown(sc: dict, rubric: dict, checks_failed: list[str], computed_verdict: str) -> str:
    crit_by_id = {c["id"]: c for c in rubric["criteria"]}
    dim_meta = {d["dimension"]: d for d in rubric["dimensions"]}
    out = [
        "# Multi-Persona Architecture Red-Team Scorecard (Stage 4A)",
        "",
        f"- **Architecture Index Hash:** `{str(sc.get('architectureSha256', ''))[:12]}…`",
        f"- **Solution Design Hash:** `{str(sc.get('solutionDesignSha256', ''))[:12]}…`",
        f"- **Delivery Scenario:** {dlc.scenario_display_label(sc.get('inputScenario', ''))}",
        f"- **Rubric Version:** `{sc.get('rubricVersion', '')}`",
        f"- **Evaluated At (UTC):** `{sc.get('judgedAtUtc', 'n/a')}`",
        f"- **TOTAL_SCORE:** `{sc.get('totalScore', 0)}/{rubric.get('maxScore', 100)}` (pass threshold `{rubric.get('passingScore', 90)}`)",
        f"- **OVERALL_VERDICT:** `{computed_verdict}`",
        "",
    ]
    for dim_key, meta in dim_meta.items():
        tot = (sc.get("dimensionTotals") or {}).get(dim_key, 0)
        out += [
            f"## {meta['title']} — Persona: `{meta['persona']}` (`{tot}/{meta['maxPoints']}`)",
            "",
            "| Criterion | Title | Awarded | Max | Blocking | Evidence (verbatim) | Adversarial Critique & Gap |",
            "| :-- | :-- | :-: | :-: | :-: | :-- | :-- |",
        ]
        for c in sc.get("criteria", []):
            if c.get("dimension") != dim_key:
                continue
            r = crit_by_id.get(c["id"], {})
            ev = str(c.get("evidence", "")).replace("|", "\\|").replace("\n", " ")
            crit_txt = str(c.get("critique", "")).replace("|", "\\|").replace("\n", " ")
            gap_txt = str(c.get("gap", "")).replace("|", "\\|").replace("\n", " ")
            combined = f"{crit_txt} {('Gap: ' + gap_txt) if gap_txt else ''}".strip()
            out.append(
                f"| `{c['id']}` | {r.get('title', '')} | {c.get('awarded', 0)} | "
                f"{c.get('maxPoints', r.get('maxPoints', 0))} | {'yes' if r.get('blocking') else 'no'} | "
                f"{ev[:360]} | {combined[:320]} |"
            )
        out.append("")
    out += ["## Blocking Gaps", ""]
    out += [f"- {g}" for g in sc.get("blockingGaps", [])] or ["- None"]
    out += ["", "## Verification Findings", ""]
    out += [f"- ✗ {f}" for f in checks_failed] or ["- All structural and evidence checks passed."]
    out.append("")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument("--scorecard", default="design/architecture_eval_scorecard.json")
    ap.add_argument("--rubric", default=str(dlc.schema_path("architecture_rubric.json")))
    ap.add_argument("--markdown-out", default="design/architecture_eval_scorecard.md")
    ap.add_argument("--no-markdown", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = dlc.resolve_project_root(args.project_root)
    dlc.require_gate_approved(root, "gate_3_backlog", "Stage 4A (04-solution-architect / validate_architecture_scorecard.py)")

    inv = dlc.load_inventory(root)
    scenario = inv.get("inputScenario", "SCENARIO_REQUIREMENTS_DOC")
    arch_path = dlc.require_file(root / "design" / "architecture_design.md", "Stage 4A solution-architect")
    sol_path = dlc.require_file(root / "design" / "solution_design.md", "Stage 4A solution-architect")
    arch_sha = dlc.sha256_file(arch_path)
    sol_sha = dlc.sha256_file(sol_path)

    design_corpus_parts: list[str] = []
    for p in sorted((root / "design").glob("*.md")):
        if p.name == Path(args.markdown_out).name:
            continue
        design_corpus_parts.append(dlc.read_text(p))
    corpus_norm = dlc.normalise_ws(dlc.strip_md("\n\n".join(design_corpus_parts)))

    rubric = dlc.read_json(dlc.require_file(Path(args.rubric), "plugin schemas/architecture_rubric.json"))
    sc_path = dlc.require_file(
        dlc.project_path(root, args.scorecard),
        "Stage 4A architecture-critic — score design/*.md against schemas/architecture_rubric.json",
    )
    sc = dlc.read_json(sc_path)

    fails: list[str] = []
    warns: list[str] = []
    fails += dlc.validate_against_schema(sc, dlc.load_schema("architecture_scorecard.schema.json"))

    dim_max = {d["dimension"]: d["maxPoints"] for d in rubric["dimensions"]}
    for dk, mx in dim_max.items():
        s = sum(c["maxPoints"] for c in rubric["criteria"] if c["dimension"] == dk)
        if s != mx:
            fails.append(f"Rubric inconsistency: dimension {dk} criteria sum to {s}, declared {mx}.")

    if sc.get("architectureSha256") != arch_sha:
        fails.append(
            f"stale: scorecard architectureSha256 {str(sc.get('architectureSha256'))[:12]}… != "
            f"current design/architecture_design.md {arch_sha[:12]}… — re-run architecture red-team evaluation."
        )
    if sc.get("solutionDesignSha256") != sol_sha:
        fails.append(
            f"stale: scorecard solutionDesignSha256 {str(sc.get('solutionDesignSha256'))[:12]}… != "
            f"current design/solution_design.md {sol_sha[:12]}… — re-run architecture red-team evaluation."
        )
    if sc.get("inputScenario") != scenario:
        fails.append(f"Scorecard inputScenario {sc.get('inputScenario')} != inventory {scenario}.")

    got = {c.get("id"): c for c in sc.get("criteria", []) if isinstance(c, dict)}
    rubric_ids = [c["id"] for c in rubric["criteria"]]
    for rid in rubric_ids:
        if rid not in got:
            fails.append(f"Criterion {rid} missing from architecture scorecard.")
    for cid in got:
        if cid not in rubric_ids:
            fails.append(f"Unknown criterion {cid} (not in architecture_rubric.json).")

    dim_sum = {dk: 0 for dk in dim_max}
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
            fails.append(f"{rc['id']}: maxPoints {c.get('maxPoints')} != rubric {rc['maxPoints']}.")
        if c.get("dimension") != rc["dimension"]:
            fails.append(f"{rc['id']}: dimension {c.get('dimension')} != rubric {rc['dimension']}.")
        if awarded < 0 or awarded > rc["maxPoints"]:
            fails.append(f"{rc['id']}: awarded {awarded} outside 0..{rc['maxPoints']}.")
        dim_sum[rc["dimension"]] = dim_sum.get(rc["dimension"], 0) + awarded

        applies = rc.get("appliesTo")
        if applies and scenario not in applies:
            if awarded != rc["maxPoints"]:
                fails.append(
                    f"{rc['id']}: not applicable to {scenario} — must be awarded maxPoints ({rc['maxPoints']}) with 'N/A …' evidence."
                )
            continue

        ev = str(c.get("evidence", "")).strip()
        if awarded > 0:
            if not ev:
                fails.append(f"{rc['id']}: awarded {awarded} but evidence is empty.")
            else:
                weak = evidence_substance(ev, rc["id"])
                if weak:
                    fails.append(f"{rc['id']}: {weak}: {ev[:120]!r}")
                ok, missing = evidence_found(ev, corpus_norm)
                if not ok:
                    fails.append(f"{rc['id']}: evidence quote not found verbatim in design/*.md: {missing[0][:120]!r}")
        if awarded < rc["maxPoints"] and not str(c.get("gap", "")).strip():
            warns.append(f"{rc['id']}: awarded {awarded}/{rc['maxPoints']} but gap is empty.")
        if rc.get("blocking") and awarded == 0:
            blocking_zero.append(rc["id"])

    for dk in dim_max:
        declared = (sc.get("dimensionTotals") or {}).get(dk)
        if declared != dim_sum[dk]:
            fails.append(f"dimensionTotals[{dk}] = {declared} but criteria sum to {dim_sum[dk]}.")
    total_calc = sum(dim_sum.values())
    if sc.get("totalScore") != total_calc:
        fails.append(f"totalScore {sc.get('totalScore')} != sum of criteria {total_calc}.")

    passing = rubric.get("passingScore", 90)
    expected_verdict = "PASS" if total_calc >= passing and not blocking_zero else "FAIL"
    if sc.get("verdict") != expected_verdict:
        fails.append(
            f"verdict {sc.get('verdict')} inconsistent — total {total_calc} >= {passing}: {total_calc >= passing}; "
            f"blocking criteria at 0: {blocking_zero or 'none'} => {expected_verdict}."
        )

    md_rel = args.markdown_out
    if not args.no_markdown:
        md_out = dlc.project_path(root, md_rel)
        md_content = render_markdown(sc, rubric, fails, expected_verdict if not fails else "FAIL")
        dlc.write_text(md_out, md_content)

    leak_targets = [args.scorecard] + ([md_rel] if not args.no_markdown else [])
    fails.extend(dlc.scan_deliverable_internal_leaks(root, leak_targets))
    computed = "PASS" if expected_verdict == "PASS" and not fails else "FAIL"

    result = {
        "verdict": computed,
        "totalScore": total_calc,
        "dimensionTotals": dim_sum,
        "blockingZero": blocking_zero,
        "failures": fails,
        "warnings": warns,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for w in warns:
            dlc.warn(w)
        for f in fails:
            print(f"  ✗ {f}")
        print(
            f"[dlc] Stage 4A architecture red-team scorecard: {computed} — total {total_calc}/{rubric.get('maxScore', 100)}, "
            f"dimensions {dim_sum}, blocking@0={blocking_zero or 'none'}"
        )
    return 0 if computed == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
