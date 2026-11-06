#!/usr/bin/env python3
"""Stage 9 (Day-2 Evolution) — Continuous Spec-to-Code & Contract Drift Detector (10-drift-and-evolution).

Audits six alignment planes between upstream approved artefacts and `src/` without modifying application code:
  1. Cryptographic lineage freshness (spec -> scorecard & test_cases, solution_design -> .contracts_index)
  2. OpenAPI 3.1 contract paths (`src/contracts/openapi.yaml`) vs backend routes in `src/backend/`
  3. 3NF SQL DDL tables (`src/db/schema.sql`) vs backend persistence / schema loader in `src/backend/`
  4. Lifecycle state triggers & actor roles (`specs/application_spec.md` §3.3 / §3.5) vs `src/`
  5. Contract-first `data-testid` selectors (`test/.testid_contract.json`) vs `src/ui/`
  6. Architecture Decision Records (`design/adrs/ADR-*.md`) & `@dlc-guard` / `@dlc-rule` / `@dlc-mask` / `@dlc-a11y` pragmas

Writes `test/drift_report.json` (validated against `schemas/drift_report.schema.json`) and `test/drift_report.md`.

Usage:
    python3 check_spec_code_drift.py --project-root <PROJECT_ROOT>
            [--json-out test/drift_report.json] [--report-out test/drift_report.md]
            [--deterministic] [--fail-on-drift] [--json]
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

CODE_EXTENSIONS = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".java", ".kt", ".cs", ".rb", ".rs", ".php", ".sql", ".html",
}
PRAGMA_RE = re.compile(r"@dlc-(?:guard|rule|mask|a11y)\b", re.IGNORECASE)
TESTID_IN_UI_RE = re.compile(r'data-testid\s*=\s*["\']?([A-Za-z0-9_.:-]+)["\']?')


def _read_tree_corpus(directory: Path) -> tuple[str, list[Path]]:
    if not directory.is_dir():
        return "", []
    parts: list[str] = []
    files: list[Path] = []
    for p in sorted(directory.rglob("*")):
        if not p.is_file():
            continue
        if any(seg in ("node_modules", "__pycache__", ".venv", "venv", "dist", "build", "target", ".git") for seg in p.parts):
            continue
        if p.suffix.lower() in CODE_EXTENSIONS:
            files.append(p)
            parts.append(dlc.read_text(p))
    return "\n".join(parts), files


def _static_route_anchor(openapi_path: str) -> str:
    """Extract the leading static path anchor before `{param}` (e.g. `/api/requests/{id}/approve` -> `/api/requests`)."""
    segs = [s for s in openapi_path.strip().split("/") if s]
    static_segs: list[str] = []
    for s in segs:
        if s.startswith("{") and s.endswith("}"):
            break
        static_segs.append(s)
    return "/" + "/".join(static_segs) if static_segs else "/"


def _render_markdown(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        "# Continuous Specification-to-Code Drift Report",
        "",
        f"- **Evaluated At (UTC):** `{report['checkedAtUtc']}`",
        f"- **Alignment Verdict:** `{report['verdict']}`",
        f"- **Blocking Drift Errors:** `{s['errors']}`",
        f"- **Advisory Drift Warnings:** `{s['warnings']}`",
        f"- **Recorded Architecture Decision Records (`design/adrs/`):** `{s['adrsRecorded']}`",
        f"- **Contract Guardrail Pragmas in `src/`:** `{s['contractPragmasFound']}`",
        "",
        "## Drift Findings",
        "",
    ]
    findings = report.get("findings") or []
    if not findings:
        lines.append("All audited specification, API contract, database schema, UI selector, and lifecycle artifacts are aligned.")
    else:
        lines.extend([
            "| ID | Severity | Category | Upstream Artifact | Code Location | Description | Recommended Action |",
            "| :-- | :-: | :-- | :-- | :-- | :-- | :-- |",
        ])
        for f in findings:
            desc = str(f["description"]).replace("|", "\\|").replace("\n", " ")
            rem = str(f["remediation"]).replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| `{f['id']}` | `{f['severity']}` | `{f['category']}` | `{f['artifact']}` | "
                f"`{f['codeLocation']}` | {desc} | {rem} |"
            )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument("--json-out", default="test/drift_report.json")
    ap.add_argument("--report-out", default="test/drift_report.md")
    ap.add_argument("--deterministic", action="store_true")
    ap.add_argument("--fail-on-drift", action="store_true", help="Exit 1 whenever any blocking drift error is found")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = dlc.resolve_project_root(args.project_root)
    findings: list[dict[str, Any]] = []

    def add_finding(severity: str, category: str, artifact: str, code_loc: str, desc: str, remediation: str) -> None:
        fid = f"DRIFT-{len(findings) + 1:02d}"
        findings.append({
            "id": fid,
            "severity": severity,
            "category": category,
            "artifact": artifact,
            "codeLocation": code_loc,
            "description": desc,
            "remediation": remediation,
        })

    # 1. Artifact cryptographic lineage freshness
    spec_p = root / "specs" / "application_spec.md"
    sc_p = root / "specs" / "application_eval_scorecard.json"
    tc_p = root / "test" / "test_cases.json"
    sol_p = root / "design" / "solution_design.md"
    ci_p = root / "design" / ".contracts_index.json"

    spec_txt = dlc.read_text(spec_p) if spec_p.is_file() else ""
    if spec_p.is_file():
        spec_sha = dlc.sha256_file(spec_p)
        if sc_p.is_file():
            sc = dlc.read_json(sc_p)
            if isinstance(sc, dict) and sc.get("specSha256") != spec_sha:
                add_finding(
                    "error", "artifact-hash", "specs/application_spec.md", "specs/application_eval_scorecard.json",
                    "Specification content changed after the quality scorecard was recorded.",
                    "Re-run specification quality evaluation so the scorecard matches the updated specification.",
                )
        if tc_p.is_file():
            tc_doc = dlc.read_json(tc_p)
            df = (tc_doc.get("derivedFrom") or {}) if isinstance(tc_doc, dict) else {}
            if df.get("specSha256") and df.get("specSha256") != spec_sha:
                add_finding(
                    "error", "artifact-hash", "specs/application_spec.md", "test/test_cases.json",
                    "Specification changed after the executable test suite was derived.",
                    "Refresh the derived test suite so acceptance and state-transition tests match the current specification.",
                )
    if sol_p.is_file() and ci_p.is_file():
        sol_sha = dlc.sha256_file(sol_p)
        ci_doc = dlc.read_json(ci_p)
        if isinstance(ci_doc, dict) and ci_doc.get("designSha256") != sol_sha:
            add_finding(
                "error", "artifact-hash", "design/solution_design.md", "src/contracts/openapi.yaml",
                "Solution design changed after OpenAPI and database schema contracts were extracted.",
                "Refresh extracted API and database contracts from the updated solution design.",
            )

    # Read source corpora
    backend_corpus, _ = _read_tree_corpus(root / "src" / "backend")
    ui_corpus, _ = _read_tree_corpus(root / "src" / "ui")
    full_src_corpus, _ = _read_tree_corpus(root / "src")
    pragma_count = len(PRAGMA_RE.findall(full_src_corpus))

    # 2. OpenAPI 3.1 paths vs backend implementation
    stack = dlc.read_json(root / "specs" / "target_stack.json") if (root / "specs" / "target_stack.json").is_file() else {}
    backend_kind = ((stack.get("backend") or {}).get("kind") or "none") if isinstance(stack, dict) else "none"
    if backend_kind != "none" and ci_p.is_file() and backend_corpus:
        ci_doc = dlc.read_json(ci_p)
        paths = (ci_doc.get("paths") or []) if isinstance(ci_doc, dict) else []
        checked_anchors: set[str] = set()
        for op in paths:
            raw_path = str(op.get("path") or "")
            anchor = _static_route_anchor(raw_path)
            if not anchor or anchor in checked_anchors:
                continue
            checked_anchors.add(anchor)
            # Accept full static anchor, trailing slash-route in modular routers, or segment-tuple routers (e.g. parts == ["queues", "manager"])
            tail_seg = "/" + anchor.strip("/").split("/")[-1] if anchor.strip("/") else "/"
            meaningful_segs = [
                seg for seg in anchor.strip("/").split("/")
                if seg and seg.lower() not in ("api", "v1", "v2", "v3")
            ]
            seg_literals_present = bool(meaningful_segs) and all(
                (f'"{seg}"' in backend_corpus or f"'{seg}'" in backend_corpus)
                for seg in meaningful_segs
            )
            if anchor not in backend_corpus and tail_seg not in backend_corpus and not seg_literals_present:
                add_finding(
                    "error", "openapi-route", f"src/contracts/openapi.yaml ({raw_path})", "src/backend/",
                    f"Contract route anchor '{anchor}' was not found in backend source files.",
                    "Implement the missing API route in src/backend/ or update design/solution_design.md and ADR records.",
                )

    # 3. SQL DDL tables vs backend persistence
    ddl_p = root / "src" / "db" / "schema.sql"
    if backend_kind != "none" and ddl_p.is_file() and backend_corpus:
        ddl_txt = dlc.read_text(ddl_p)
        loads_schema_file = "schema.sql" in backend_corpus
        ddl_tables = re.findall(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"\[]?([A-Za-z_][A-Za-z0-9_]*)", ddl_txt, re.IGNORECASE)
        for tbl in dict.fromkeys(ddl_tables):
            if not loads_schema_file and not re.search(rf"\b{re.escape(tbl)}\b", backend_corpus, re.IGNORECASE):
                add_finding(
                    "warning", "ddl-schema", f"src/db/schema.sql ({tbl})", "src/backend/",
                    f"Database table '{tbl}' is declared in schema.sql but not referenced in backend persistence logic.",
                    "Verify persistence queries for this table or record an ADR if the table is reserved for a later wave.",
                )

    # 4. Lifecycle state machine triggers vs src/
    if spec_txt and full_src_corpus:
        sm = dlc.parse_state_machine(spec_txt)
        src_lower = full_src_corpus.lower()
        for st in sm.states:
            slug_st = dlc.slugify(st).replace("-", "_")
            if st.lower() not in src_lower and slug_st not in src_lower:
                add_finding(
                    "warning", "state-machine", f"specs/application_spec.md (§3.3 state '{st}')", "src/",
                    f"Lifecycle state '{st}' from §3.3 was not detected in application source files.",
                    "Ensure the state label and transition guards in src/ match the frozen §3.3 state table.",
                )

    # 5. Contract-first data-testid hooks vs src/ui/
    tid_contract_p = root / "test" / ".testid_contract.json"
    if tid_contract_p.is_file() and ui_corpus:
        tid_doc = dlc.read_json(tid_contract_p)
        req_tids = (tid_doc.get("testIds") or []) if isinstance(tid_doc, dict) else []
        found_tids = set(TESTID_IN_UI_RE.findall(ui_corpus))
        for tid in req_tids:
            # Dynamic template expressions like `data-testid="role-${slug}"` may construct role-* or tab-* hooks dynamically
            if tid not in found_tids and tid not in ui_corpus:
                prefix = tid.split("-")[0] + "-"
                if f"data-testid" in ui_corpus and prefix in ui_corpus and ("${" in ui_corpus or "+ " in ui_corpus):
                    continue
                add_finding(
                    "error", "testid-contract", f"test/test_cases.json ([data-testid={tid}])", "src/ui/",
                    f"Contract-first selector '[data-testid={tid}]' is missing from UI source files.",
                    "Restore the data-testid attribute in src/ui/ or update the test specification if views changed intentionally.",
                )

    # 6. Architecture Decision Records (design/adrs/ADR-*.md or specs/adr/ADR-*.md)
    adr_files: list[Path] = []
    for adrs_dir in (root / "design" / "adrs", root / "specs" / "adr"):
        if adrs_dir.is_dir():
            adr_files.extend(sorted(adrs_dir.glob("ADR-*.md")))
    for adr_f in adr_files:
        adr_txt = dlc.read_text(adr_f)
        for req_sec in ("Status", "Context", "Decision", "Consequences"):
            if not re.search(rf"(?:^#+\s*{req_sec}\b|\*\*{req_sec}:?\*\*)", adr_txt, re.IGNORECASE | re.MULTILINE):
                add_finding(
                    "warning", "adr-coverage", str(adr_f.relative_to(root)), str(adr_f.parent.relative_to(root)) + "/",
                    f"Architecture Decision Record '{adr_f.name}' is missing a '{req_sec}' section.",
                    "Include Status, Context, Decision, and Consequences in every ADR file.",
                )

    err_count = sum(1 for f in findings if f["severity"] == "error")
    warn_count = sum(1 for f in findings if f["severity"] == "warning")
    verdict = "DRIFT_DETECTED" if err_count > 0 else "ALIGNED"

    openapi_p = root / "src" / "contracts" / "openapi.yaml"
    report: dict[str, Any] = {
        "schemaVersion": dlc.SCHEMA_VERSION,
        "checkedAtUtc": dlc.utc_now_iso(args.deterministic),
        "verdict": verdict,
        "specSha256": dlc.sha256_file(spec_p) if spec_p.is_file() else None,
        "openapiSha256": dlc.sha256_file(openapi_p) if openapi_p.is_file() else None,
        "schemaSqlSha256": dlc.sha256_file(ddl_p) if ddl_p.is_file() else None,
        "summary": {
            "totalFindings": len(findings),
            "errors": err_count,
            "warnings": warn_count,
            "adrsRecorded": len(adr_files),
            "contractPragmasFound": pragma_count,
        },
        "findings": findings,
        "adrs": [str(f.relative_to(root)) for f in adr_files],
    }

    schema_errs = dlc.validate_against_schema(report, dlc.load_schema("drift_report.schema.json"))
    if schema_errs:
        raise dlc.GateFailure("drift_report.json failed schema validation:\n  " + "\n  ".join(schema_errs))

    json_out_p = dlc.project_path(root, args.json_out)
    md_out_p = dlc.project_path(root, args.report_out)
    dlc.write_json(json_out_p, report)
    dlc.write_text(md_out_p, _render_markdown(report))

    leak_errs = dlc.scan_deliverable_internal_leaks(root, [args.json_out, args.report_out])
    if leak_errs:
        raise dlc.GateFailure("Deliverable hygiene violation in drift report:\n  " + "\n  ".join(leak_errs))

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"[dlc] Stage 9 drift check: {verdict} — errors={err_count}, warnings={warn_count}, "
            f"ADRs={len(adr_files)}, pragmas={pragma_count} -> {args.json_out}, {args.report_out}"
        )
        for f in findings[:15]:
            print(f"  [{f['severity'].upper()}] {f['id']} ({f['category']}): {f['description']}")
    if err_count > 0 and args.fail_on_drift:
        return 1
    return 0 if err_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
