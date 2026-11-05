#!/usr/bin/env python3
"""Gate 4a — validate Future-State ("To-Be") Well-Architected Architecture (`design/architecture_design.md`)
and extract/validate Solution Design & Contracts (`design/solution_design.md`) (04-solution-architect).

Enforces the strict two-document separation in Stage 4A:
1. `design/architecture_design.md` — Dedicated exclusively to the Google Cloud Architecture Framework
   (Well-Architected Framework) Logical Solution Architecture (`§1`), Technical & Multi-Zone GDC Deployment
   Architecture (`§2`), End-to-End Request & Workflow Sequence Diagram (`§3`), Architectural Layering Table (`§4`),
   and 6-Pillar (+ Sustainability) & Failure-Mode Grilling Matrices (`§5`).
2. `design/solution_design.md` — Dedicated to the Normalised 3NF Domain Model (`erDiagram`), Legacy-to-Target
   3NF Entity Mapping (`§1.1` when `inputScenario == SCENARIO_LEGACY_APP`), Target 3NF SQL DDL (`sql ddl` ->
   `src/db/schema.sql`), OpenAPI 3.1 API Contract (`yaml openapi` -> `src/contracts/openapi.yaml`), ViewModel/DTO
   mapping, and component specifications.

Usage:
    python3 extract_contracts.py --project-root <PROJECT_ROOT>
            [--architecture design/architecture_design.md] [--design design/solution_design.md]
            [--openapi-out src/contracts/openapi.yaml] [--ddl-out src/db/schema.sql] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dlc_common as dlc  # noqa: E402
import gcp_diagram_renderer as gdr  # noqa: E402

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
# Table-level constraint clauses (token test — a column named key_number / index_no / check_in_date / period_start
# must NOT be mistaken for a constraint).
CONSTRAINT_RE = re.compile(
    r"^\s*(?:PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|CONSTRAINT|CHECK\s*\(|INDEX|KEY\s*\(|EXCLUDE|PERIOD\s+FOR|LIKE)\b",
    re.IGNORECASE,
)
SNAKE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def legacy_identifier_sets(inv: dict[str, Any]) -> tuple[set[str], set[str]]:
    """Return `(fail_ids, warn_ids)` of lower-cased legacy identifiers from `specs/input_inventory.json`.

    * `fail_ids` — real legacy object names (`legacyObjectNames`: CREATE TABLE / XSD element / `Name=` / prefixed
      Access identifiers). A target table, column or visible UI token equal to one of these is a legacy carry-over.
    * `warn_ids` — bare file-name stems of legacy artefacts (`legacyFileStems`, or derived from `files[]` for
      inventories written before that key existed). Collisions are reported as warnings only.

    Shared by 04/extract_contracts.py and 05/derive_test_cases.py.
    """
    fail_ids = {str(n).strip().lower() for n in inv.get("legacyObjectNames", []) if str(n).strip()}
    stems = inv.get("legacyFileStems")
    if not isinstance(stems, list):
        stems = [Path(str(f.get("name", ""))).stem for f in inv.get("files", []) if str(f.get("category", "")).startswith("legacy_")]
    warn_ids = {str(s).strip().lower() for s in stems if len(str(s).strip()) >= 3}
    return fail_ids, warn_ids - fail_ids


# ------------------------------------------------------------------------------------------ OpenAPI (indent parser)
def parse_openapi(yaml_text: str) -> dict[str, Any]:
    """Tiny indentation-based reader: version, paths/methods/operationIds, enums, x-internal property names."""
    lines = [ln.rstrip("\n") for ln in yaml_text.splitlines()]
    version = ""
    paths: list[dict[str, str]] = []
    enums: list[str] = []
    internal_fields: list[str] = []
    schema_names: list[str] = []

    def indent(s: str) -> int:
        return len(s) - len(s.lstrip(" "))

    in_paths = False
    paths_indent = -1
    cur_path = cur_method = None
    path_indent = method_indent = -1
    last_prop: tuple[str, int] | None = None  # (name, indent)
    in_enum = False
    enum_indent = -1

    for raw in lines:
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        ind = indent(raw)
        s = raw.strip()
        m = re.match(r"^openapi:\s*[\"']?([\d.]+)", s)
        if m and ind == 0:
            version = m.group(1)
        if ind == 0:
            in_paths = s.startswith("paths:")
            paths_indent = 0
            cur_path = cur_method = None
        if in_paths and ind > paths_indent:
            pm = re.match(r"^[\"']?(/[^\"':]*)[\"']?\s*:\s*$", s)
            if pm and (cur_path is None or ind <= path_indent):
                cur_path, path_indent, cur_method = pm.group(1), ind, None
                continue
            mm = re.match(r"^([a-z]+)\s*:\s*$", s)
            if cur_path and mm and mm.group(1) in HTTP_METHODS and ind > path_indent and (cur_method is None or ind <= method_indent):
                cur_method, method_indent = mm.group(1).upper(), ind
                paths.append({"method": cur_method, "path": cur_path, "operationId": ""})
                continue
            om = re.match(r"^operationId:\s*[\"']?([\w.-]+)", s)
            if om and cur_method and paths:
                paths[-1]["operationId"] = om.group(1)
        # enums: inline or block
        em = re.match(r"^enum:\s*\[(.*)\]\s*$", s)
        if em:
            enums += [x.strip().strip("\"'") for x in em.group(1).split(",") if x.strip()]
            in_enum = False
            continue
        if re.match(r"^enum:\s*$", s):
            in_enum, enum_indent = True, ind
            continue
        if in_enum:
            if ind > enum_indent and s.startswith("- "):
                enums.append(s[2:].strip().strip("\"'"))
                continue
            in_enum = False
        # schema names (components.schemas.X) and x-internal properties
        pm2 = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*$", s)
        if pm2:
            last_prop = (pm2.group(1), ind)
            if ind == 4 and pm2.group(1)[0].isupper():
                schema_names.append(pm2.group(1))
        if re.match(r"^x-internal:\s*true", s) and last_prop and ind > last_prop[1]:
            internal_fields.append(last_prop[0])

    uniq = lambda xs: list(dict.fromkeys(xs))  # noqa: E731
    return {"version": version, "paths": paths, "enums": uniq(enums), "internalFields": uniq(internal_fields), "schemas": uniq(schema_names)}


# ------------------------------------------------------------------------------------------ DDL
def split_top_level(body: str) -> list[str]:
    parts, depth, cur = [], 0, []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur).strip())
    return parts


def parse_ddl(sql: str) -> list[dict[str, Any]]:
    sql_nc = re.sub(r"--[^\n]*", "", sql)
    sql_nc = re.sub(r"/\*.*?\*/", "", sql_nc, flags=re.DOTALL)
    tables = []
    for m in re.finditer(r"CREATE\s+(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([`\"\[]?[\w.]+[`\"\]]?)\s*\(", sql_nc, re.IGNORECASE):
        name = m.group(1).strip('`"[]').split(".")[-1]
        start = m.end()
        depth, i = 1, start
        while i < len(sql_nc) and depth:
            depth += {"(": 1, ")": -1}.get(sql_nc[i], 0)
            i += 1
        body = sql_nc[start:i - 1]
        cols, pk = [], False
        for part in split_top_level(body):
            first = part.split()[0].strip('`"[]') if part.split() else ""
            if CONSTRAINT_RE.match(part):
                if re.search(r"PRIMARY\s+KEY", part, re.IGNORECASE):
                    pk = True
                continue
            if re.search(r"PRIMARY\s+KEY", part, re.IGNORECASE):
                pk = True
            if first:
                cols.append(first)
        tables.append({"name": name, "columns": cols, "hasPrimaryKey": pk})
    return tables


# ------------------------------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dlc.add_project_root_arg(ap)
    ap.add_argument("--architecture", default="design/architecture_design.md")
    ap.add_argument("--design", default="design/solution_design.md")
    ap.add_argument("--openapi-out", default="src/contracts/openapi.yaml")
    ap.add_argument("--ddl-out", default="src/db/schema.sql")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    # With --json stdout must stay parseable JSON: route progress messages to stderr.
    log = (lambda m: print(f"[dlc] {m}", file=sys.stderr)) if args.json else dlc.info

    root = dlc.resolve_project_root(args.project_root)
    dlc.require_gate_approved(root, "gate_3_backlog", "Stage 4A (04-solution-architect / extract_contracts.py)")
    inv = dlc.load_inventory(root)
    legacy = inv.get("inputScenario") == "SCENARIO_LEGACY_APP"
    stack = dlc.load_target_stack(root)
    frontend_kind = (stack.get("frontend") or {}).get("kind", "tbd")
    backend_kind = (stack.get("backend") or {}).get("kind", "tbd")
    db_kind = (stack.get("database") or {}).get("kind", "tbd")
    decided_by = stack.get("decidedBy", "")
    arch_path = dlc.require_file(dlc.project_path(root, args.architecture), "Stage 4A (04-solution-architect / solution-architect)")
    arch_doc = dlc.read_text(arch_path)
    design_path = dlc.require_file(dlc.project_path(root, args.design), "Stage 4A (04-solution-architect / solution-architect)")
    design = dlc.read_text(design_path)
    spec = dlc.load_spec(root)
    sm = dlc.parse_state_machine(spec)

    fails: list[str] = []
    warns: list[str] = []

    if decided_by == "pending-stage-4a" or "tbd" in (frontend_kind, backend_kind, db_kind):
        fails.append(
            f"Future-State technology stack in specs/target_stack.json is not yet confirmed "
            f"(frontend={frontend_kind!r}, backend={backend_kind!r}, database={db_kind!r}, decidedBy={decided_by!r}). "
            f"Stage 4A (solution-architect) MUST ask the human what Future-State technology stack to use "
            f"(frontend framework, backend runtime/framework, database engine, and GDC deployment targets) and record "
            f"the answer in specs/target_stack.json with decidedBy='user' instead of assuming static-html + Python."
        )
    elif backend_kind != "none":
        cmds = stack.get("commands") or {}
        for k in ("start", "healthcheck", "uiEntry"):
            if not cmds.get(k):
                fails.append(f"specs/target_stack.json#commands.{k} is required once backend.kind={backend_kind!r} is selected.")
        start_cmd = str(cmds.get("start") or "").strip()
        if backend_kind not in ("python-stdlib-http", "python-fastapi", "python-flask", "other") and re.match(r"^python3?\b", start_cmd):
            fails.append(
                f"specs/target_stack.json declares backend.kind={backend_kind!r}, but commands.start={start_cmd!r} invokes Python directly. "
                f"Never replace the target stack with a standalone Python server — set commands.start to 'bash src/run.sh' (or the "
                f"{backend_kind!r} runtime command) so Stage 5 builds the application in the confirmed target stack with dual-mode local/cloud support."
            )

    # ---- Verify Target-Stack Alignment between specs/target_stack.json and design/architecture_design.md + solution_design.md
    header_and_layer_lines = "\n".join(
        ln for ln in (arch_doc + "\n" + design).splitlines()
        if re.search(r"Future-State Tech Stack|Target Stack|GKE Web Tier|GKE Application Tier|\bLayer\b.*\|", ln, re.IGNORECASE)
        or (ln.strip().startswith("|") and re.search(r"Web\s*/\s*UI|Application\s*/\s*API|Backend|Frontend", ln, re.IGNORECASE))
    )
    if frontend_kind == "static-html":
        fe_mismatch = re.findall(r"\b(React|Angular|Vue(?:\.js)?|Next\.js|NextJS)\b", header_and_layer_lines, re.IGNORECASE)
        if fe_mismatch:
            fails.append(
                f"Architecture/Design document specifies frontend framework {sorted(set(fe_mismatch))}, but specs/target_stack.json "
                f"sets frontend.kind='static-html'. Never downgrade specs/target_stack.json to 'static-html' for local testing — "
                f"record the actual confirmed frontend framework in specs/target_stack.json so Stage 5 builds the real target-stack UI."
            )
    if backend_kind == "python-stdlib-http":
        be_mismatch = re.findall(
            r"\b(Spring\s*Boot|java-spring-boot|FastAPI|python-fastapi|Flask|python-flask|Node\.js|Express|node-express|NestJS|Golang|ASP\.NET|\.NET\s*8|dotnet)\b",
            header_and_layer_lines,
            re.IGNORECASE,
        )
        if be_mismatch:
            fails.append(
                f"Architecture/Design document specifies backend runtime {sorted(set(be_mismatch))}, but specs/target_stack.json "
                f"sets backend.kind='python-stdlib-http'. Never downgrade specs/target_stack.json to 'python-stdlib-http' for local testing — "
                f"record the actual confirmed backend stack in specs/target_stack.json so Stage 5 builds the real target-stack backend."
            )

    # ---- Forbid Local-Testing Mock Mechanics Inside Stage 4A Design Documents (`architecture_design.md` & `solution_design.md`)
    leaked_local_test_tokens = re.findall(
        r"\b(?:APP_ENV=local|AUTH_MODE=local-mock|STORAGE_BACKEND=local-fs|local_dev_runner|APP_DB_RESET|pretotype)\b",
        arch_doc + "\n" + design,
        re.IGNORECASE,
    )
    if leaked_local_test_tokens:
        fails.append(
            f"Design documents ({args.architecture} / {args.design}) contain local-testing mock mechanics "
            f"({sorted(set(leaked_local_test_tokens))}). Stage 4A design documents must describe ONLY the Target State "
            f"('To-Be' architecture, target runtime, target database, OIDC/IAP auth, Cloud Operations); "
            f"local testing belongs strictly in Stage 5/6 implementation (src/)."
        )

    # ---- Multi-Perspective Architecture Suite (`design/*.md`) + Executive Index (`design/architecture_design.md`)
    disc_p = root / "specs" / "discovery_architecture_and_inventory.md"
    disc_txt = dlc.read_text(disc_p) if disc_p.exists() else ""
    cap_group_ids = sorted(set(re.findall(r"\bGRP-\d+\b", spec + "\n" + disc_txt)))

    perspective_files = [
        ("Business Architecture", "design/business_architecture.md", "business_capability_map"),
        ("High-Level Solution Architecture", "design/high_level_solution_architecture.md", "high_level_solution_architecture"),
        ("Logical Architecture", "design/logical_architecture.md", "logical_architecture"),
        ("Application Architecture", "design/application_architecture.md", "application_architecture"),
        ("Data Architecture", "design/data_architecture.md", "data_architecture"),
        ("Security Architecture", "design/security_architecture.md", "security_architecture"),
        ("Infrastructure Architecture", "design/infrastructure_architecture.md", "infrastructure_architecture"),
    ]
    perspective_docs: dict[str, str] = {}
    for p_label, p_rel, _ in perspective_files:
        p_path = root / p_rel
        if not p_path.exists():
            fails.append(
                f"Missing separate '{p_label}' perspective artifact '{p_rel}'. "
                f"Stage 4A requires each architecture perspective (Business, High-Level Solution, Logical, Application, "
                f"Data, Security, and Infrastructure) to be authored in its own separate artifact under design/."
            )
        else:
            p_txt = dlc.read_text(p_path)
            perspective_docs[p_rel] = p_txt
            if re.search(r"^```json\b", p_txt, re.IGNORECASE | re.MULTILINE):
                fails.append(f"{p_rel} must NOT embed raw ```json blocks.")
            leaked_local_p = re.findall(
                r"\b(?:APP_ENV=local|AUTH_MODE=local-mock|STORAGE_BACKEND=local-fs|local_dev_runner|APP_DB_RESET|pretotype)\b",
                p_txt,
                re.IGNORECASE,
            )
            if leaked_local_p:
                fails.append(
                    f"{p_rel} contains local-testing mock mechanics ({sorted(set(leaked_local_p))}). "
                    f"Stage 4A architecture artifacts must describe ONLY the Target State ('To-Be')."
                )

    # Forbid raw JSON blocks inside design/architecture_design.md — SVG/PNG diagrams are rendered directly from Mermaid flowcharts
    if re.search(r"^```json\b", arch_doc, re.IGNORECASE | re.MULTILINE):
        fails.append(
            f"{args.architecture} must NOT embed raw ```json blocks in the Markdown document. "
            f"04/scripts/extract_contracts.py renders all perspective SVG/PNG diagrams directly from the Mermaid blocks."
        )

    all_arch_text = arch_doc + "\n" + "\n".join(perspective_docs.values())
    arch_mermaid_blocks = dlc.md_fenced_blocks(arch_doc, "mermaid")
    rendered_svgs: list[str] = []

    doc_title_m = re.search(r"^#\s+(.+?)(?:\s+[—–-]\s+Architecture\s+Design.*)?$", arch_doc, re.MULTILINE | re.IGNORECASE)
    app_title = (doc_title_m.group(1).strip() if doc_title_m else root.name.replace("_", " ").title())

    # 1. Business Architecture (`design/business_architecture.md` -> `business_capability_map.svg`)
    bus_doc = perspective_docs.get("design/business_architecture.md", arch_doc)
    bus_blocks = [
        b for b in dlc.md_fenced_blocks(bus_doc, "mermaid")
        if re.search(r"^\s*(?:flowchart|graph)\s+T[BD]\b", b, re.IGNORECASE | re.MULTILINE)
        or re.search(r"Foundational\s+Capabilities", b, re.IGNORECASE)
    ]
    if not bus_blocks:
        fails.append(
            "design/business_architecture.md must include a 'flowchart TB' Business Capability Map diagram "
            "(top Value-Stream Pillars '1. ...' .. '4. ...', Core Business Capabilities, and 'Foundational Capabilities')."
        )
    else:
        cm_block = bus_blocks[0]
        cm_sg_ids = re.findall(r"^\s*subgraph\s+([A-Za-z0-9_]+)\b", cm_block, re.MULTILINE)
        for sg_id in cm_sg_ids:
            if not re.search(rf"^\s*style\s+{re.escape(sg_id)}\b", cm_block, re.MULTILINE):
                fails.append(
                    f"Business Capability Map diagram in design/business_architecture.md declares 'subgraph {sg_id}' without an explicit "
                    f"'style {sg_id} ...' statement (violates Zero Default Yellow Subgraphs rule)."
                )
        cm_spec = gdr.parse_capability_map_mermaid(cm_block, app_title=app_title)
        cm_errs = gdr.validate_capability_map_spec(cm_spec, "design/business_architecture.md")
        if cm_errs:
            fails.extend(cm_errs)
        else:
            cm_svg_out = arch_path.parent / "diagrams" / "business_capability_map.svg"
            cm_svg_written, cm_png_written = gdr.write_capability_map_svg_and_png(cm_spec, cm_svg_out)
            rendered_svgs.append(str(cm_svg_written.relative_to(root)))
            if not args.json:
                extra = f" (+ {cm_png_written.name})" if cm_png_written else ""
                print(f"[dlc] rendered {cm_svg_written}{extra}")

    # 2. High-Level Solution Architecture (`design/high_level_solution_architecture.md` -> `high_level_solution_architecture.svg`)
    hl_doc = perspective_docs.get("design/high_level_solution_architecture.md", "")
    hl_blocks = [
        b for b in dlc.md_fenced_blocks(hl_doc, "mermaid")
        if re.search(r"^\s*(?:flowchart|graph)\b", b, re.IGNORECASE | re.MULTILINE)
    ]
    if not hl_blocks:
        fails.append(
            "design/high_level_solution_architecture.md must include a Mermaid flowchart depicting Personas, "
            "Engagement Layer, System of Intelligence & AI (Agentic Layer + Domain Intelligence + Governance), and Transactional Systems."
        )
    else:
        hl_parsed = gdr.parse_layered_perspective_mermaid(hl_blocks[0], app_title=f"Future State Architecture — {app_title}")
        hl_errs = gdr.validate_perspective_spec(hl_parsed, "design/high_level_solution_architecture.md", min_cards=10)
        if hl_errs:
            fails.extend(hl_errs)
        else:
            hl_svg_out = arch_path.parent / "diagrams" / "high_level_solution_architecture.svg"
            hl_svg_written, hl_png_written = gdr.write_high_level_solution_svg_and_png(hl_parsed, hl_svg_out)
            rendered_svgs.append(str(hl_svg_written.relative_to(root)))
            if not args.json:
                extra = f" (+ {hl_png_written.name})" if hl_png_written else ""
                print(f"[dlc] rendered {hl_svg_written}{extra}")

    # 3. Logical Architecture (`design/logical_architecture.md`) & 7. Infrastructure Architecture (`design/infrastructure_architecture.md`)
    log_doc = perspective_docs.get("design/logical_architecture.md", arch_doc)
    inf_doc = perspective_docs.get("design/infrastructure_architecture.md", arch_doc)
    log_lr = [b for b in dlc.md_fenced_blocks(log_doc, "mermaid") if re.search(r"^\s*flowchart\s+LR\b", b, re.IGNORECASE | re.MULTILINE)]
    inf_lr = [b for b in dlc.md_fenced_blocks(inf_doc, "mermaid") if re.search(r"^\s*flowchart\s+LR\b", b, re.IGNORECASE | re.MULTILINE)]

    if not log_lr or not inf_lr:
        fails.append(
            f"design/logical_architecture.md and design/infrastructure_architecture.md must each include a 'flowchart LR' diagram "
            f"(found logical={len(log_lr)}, infrastructure={len(inf_lr)})."
        )
    else:
        labels_stems = [
            ("design/logical_architecture.md", "logical_architecture", log_lr[0]),
            ("design/infrastructure_architecture.md", "infrastructure_architecture", inf_lr[0]),
        ]
        parsed_specs: list[dict[str, Any]] = [
            gdr.parse_mermaid_flowchart_to_spec(log_lr[0], "logical_architecture"),
            gdr.parse_mermaid_flowchart_to_spec(inf_lr[0], "infrastructure_architecture"),
        ]
        for idx, (label, default_stem, fb) in enumerate(labels_stems):
            for req_cls in ("gcpCard", "focal", "gcpBlue", "gcpGreen", "gcpYellow", "gcpRed"):
                if not re.search(rf"\bclassDef\s+{req_cls}\b", fb):
                    fails.append(f"{label} diagram is missing classDef '{req_cls}'.")
            sg_ids = re.findall(r"^\s*subgraph\s+([A-Za-z0-9_]+)\b", fb, re.MULTILINE)
            for sg_id in sg_ids:
                if not re.search(rf"^\s*style\s+{re.escape(sg_id)}\b", fb, re.MULTILINE):
                    fails.append(f"{label} diagram declares 'subgraph {sg_id}' without an explicit 'style {sg_id} ...' statement.")
                if re.search(rf"(?:-->|==>|-\.->)\s*(?:\|[^|]*\|\s*)?{re.escape(sg_id)}\b|\b{re.escape(sg_id)}\s*(?:-->|==>|-\.->)", fb):
                    fails.append(f"{label} diagram connects an edge directly to subgraph ID '{sg_id}'.")
            spec_obj = parsed_specs[idx]
            other_obj = parsed_specs[1 - idx]
            spec_errs = gdr.validate_gcp_diagram_spec(
                spec_obj,
                label,
                other_spec=other_obj,
                cap_group_ids=cap_group_ids,
                target_stack=stack,
            )
            if spec_errs:
                fails.extend(spec_errs)
            else:
                warns.extend(gdr.reference_layout_warnings(spec_obj, label))
                svg_out = arch_path.parent / "diagrams" / f"{default_stem}.svg"
                svg_written, png_written = gdr.write_svg_and_png(spec_obj, svg_out)
                rendered_svgs.append(str(svg_written.relative_to(root)))
                if not args.json:
                    extra = f" (+ {png_written.name})" if png_written else ""
                    print(f"[dlc] rendered {svg_written}{extra}")
                if default_stem == "infrastructure_architecture":
                    tech_alias_svg = arch_path.parent / "diagrams" / "technical_architecture.svg"
                    gdr.write_svg_and_png(spec_obj, tech_alias_svg)

    # 4. Application Architecture (`design/application_architecture.md` -> `application_architecture.svg` + sequenceDiagram)
    app_doc = perspective_docs.get("design/application_architecture.md", "")
    app_flow_blocks = [
        b for b in dlc.md_fenced_blocks(app_doc, "mermaid")
        if re.search(r"^\s*(?:flowchart|graph)\b", b, re.IGNORECASE | re.MULTILINE)
    ]
    if not app_flow_blocks:
        fails.append("design/application_architecture.md must include a Mermaid flowchart depicting the Multi-Tier Application & AI Component Architecture.")
    else:
        app_parsed = gdr.parse_layered_perspective_mermaid(app_flow_blocks[0], app_title=f"{app_title} — Application & AI Architecture")
        app_errs = gdr.validate_perspective_spec(app_parsed, "design/application_architecture.md", min_cards=8)
        if app_errs:
            fails.extend(app_errs)
        else:
            app_svg_out = arch_path.parent / "diagrams" / "application_architecture.svg"
            app_svg_written, app_png_written = gdr.write_application_architecture_svg_and_png(app_parsed, app_svg_out)
            rendered_svgs.append(str(app_svg_written.relative_to(root)))
            if not args.json:
                extra = f" (+ {app_png_written.name})" if app_png_written else ""
                print(f"[dlc] rendered {app_svg_written}{extra}")

    # 5. Data Architecture (`design/data_architecture.md` -> `data_architecture.svg` + erDiagram)
    data_doc = perspective_docs.get("design/data_architecture.md", "")
    data_flow_blocks = [
        b for b in dlc.md_fenced_blocks(data_doc, "mermaid")
        if re.search(r"^\s*(?:flowchart|graph)\b", b, re.IGNORECASE | re.MULTILINE)
    ]
    if not data_flow_blocks:
        fails.append("design/data_architecture.md must include a Mermaid flowchart depicting the End-to-End Data & Information Architecture.")
    else:
        data_parsed = gdr.parse_layered_perspective_mermaid(data_flow_blocks[0], app_title=f"{app_title} — Data & Information Architecture")
        data_errs = gdr.validate_perspective_spec(data_parsed, "design/data_architecture.md", min_cards=8)
        if data_errs:
            fails.extend(data_errs)
        else:
            data_svg_out = arch_path.parent / "diagrams" / "data_architecture.svg"
            data_svg_written, data_png_written = gdr.write_data_architecture_svg_and_png(data_parsed, data_svg_out)
            rendered_svgs.append(str(data_svg_written.relative_to(root)))
            if not args.json:
                extra = f" (+ {data_png_written.name})" if data_png_written else ""
                print(f"[dlc] rendered {data_svg_written}{extra}")

    # 6. Security Architecture (`design/security_architecture.md` -> `security_architecture.svg`)
    sec_doc = perspective_docs.get("design/security_architecture.md", "")
    sec_flow_blocks = [
        b for b in dlc.md_fenced_blocks(sec_doc, "mermaid")
        if re.search(r"^\s*(?:flowchart|graph)\b", b, re.IGNORECASE | re.MULTILINE)
    ]
    if not sec_flow_blocks:
        fails.append("design/security_architecture.md must include a Mermaid flowchart depicting the Defense-in-Depth Security & AI Trust Architecture.")
    else:
        sec_parsed = gdr.parse_layered_perspective_mermaid(sec_flow_blocks[0], app_title=f"{app_title} — Security, Privacy & AI Trust Architecture")
        sec_errs = gdr.validate_perspective_spec(sec_parsed, "design/security_architecture.md", min_cards=8)
        if sec_errs:
            fails.extend(sec_errs)
        else:
            sec_svg_out = arch_path.parent / "diagrams" / "security_architecture.svg"
            sec_svg_written, sec_png_written = gdr.write_security_architecture_svg_and_png(sec_parsed, sec_svg_out)
            rendered_svgs.append(str(sec_svg_written.relative_to(root)))
            if not args.json:
                extra = f" (+ {sec_png_written.name})" if sec_png_written else ""
                print(f"[dlc] rendered {sec_svg_written}{extra}")

    # Validate sequenceDiagram (in application_architecture.md or architecture_design.md)
    seq_blocks = [
        b for b in dlc.md_fenced_blocks(app_doc + "\n" + arch_doc, "mermaid")
        if re.search(r"^\s*sequenceDiagram\b", b, re.IGNORECASE | re.MULTILINE)
    ]
    if not seq_blocks:
        fails.append(
            "Missing End-to-End Request & Workflow Execution Sequence (```mermaid sequenceDiagram) in design/application_architecture.md."
        )
    else:
        seq0 = seq_blocks[0]
        if not re.search(r"^\s*box\s+rgb\s*\(", seq0, re.MULTILINE) or not re.search(r"^\s*rect\s+rgb\s*\(", seq0, re.MULTILINE):
            fails.append(
                "sequenceDiagram must use security-zone 'box rgb(...)' participant groupings and semantic 'rect rgb(...)' execution blocks."
            )
        reserved_seq_ids = {
            "actor", "participant", "box", "rect", "end", "loop", "alt", "else", "opt",
            "par", "and", "critical", "option", "break", "note", "autonumber", "activate",
            "deactivate", "title", "create", "destroy", "links", "link", "properties", "details",
        }
        bad_seq_ids: set[str] = set()
        for m_decl in re.finditer(r"^\s*(?:actor|participant)\s+([A-Za-z0-9_]+)\b", seq0, re.MULTILINE | re.IGNORECASE):
            pid = m_decl.group(1)
            if pid.lower() in reserved_seq_ids:
                bad_seq_ids.add(pid)
        for m_msg in re.finditer(r"^\s*([A-Za-z0-9_]+)\s*(?:->>|-->>|->|-->|-\)|--\)|-x|--x)", seq0, re.MULTILINE):
            pid = m_msg.group(1)
            if pid.lower() in reserved_seq_ids:
                bad_seq_ids.add(pid)
        if bad_seq_ids:
            fails.append(
                f"sequenceDiagram uses reserved Mermaid keyword(s) {sorted(bad_seq_ids)} as a participant ID "
                f"(causes Mermaid Jison parse error: \"Expecting 'ACTOR', got 'INVALID'\"). "
                f"Use a non-reserved identifier such as 'actor User as ...' and 'User->>UI:' instead of 'actor Actor as ...'."
            )
    arch_layer_table = dlc.find_table(all_arch_text, ["layer", "component"]) or dlc.find_table(all_arch_text, ["layer", "responsibilit"]) or dlc.find_table(all_arch_text, ["perspective", "artifact"])
    if not arch_layer_table:
        fails.append(
            "Missing Architectural Layering & Component Responsibilities table in design/architecture_design.md or design/application_architecture.md."
        )
    # ---- Well-Architected Framework Alignment (6 Pillars + Sustainability) & Failure-Mode Grilling Matrix
    wa_pillar_table = dlc.find_table(all_arch_text, ["pillar", "decision"]) or dlc.find_table(all_arch_text, ["pillar", "alignment"]) or dlc.find_table(all_arch_text, ["pillar", "guardrail"])
    if not wa_pillar_table:
        fails.append(
            "Missing 'Well-Architected Framework 6-Pillar (+ Sustainability) Alignment Matrix' table in design/infrastructure_architecture.md or design/architecture_design.md."
        )
    else:
        wa_blob = " ".join(" ".join(str(v) for v in r.values()) for r in wa_pillar_table).lower()
        for req_pillar in ("system design", "operational excellence", "security", "reliability", "cost optimization", "performance optimization", "sustainability"):
            if req_pillar not in wa_blob:
                fails.append(
                    f"Well-Architected Alignment table is missing required pillar '{req_pillar}'."
                )
    wa_grill_table = (
        dlc.find_table(all_arch_text, ["failure", "anti-pattern"])
        or dlc.find_table(all_arch_text, ["grilling", "remediation"])
        or dlc.find_table(all_arch_text, ["failure domain", "remediation"])
    )
    if not wa_grill_table or len(wa_grill_table) < 5:
        fails.append(
            "Missing or incomplete 'First-Principles Failure Mode & Anti-Pattern Grilling Matrix' table (>= 5 grilling vectors required)."
        )
    if any("erdiagram" in b.lower() for b in arch_mermaid_blocks) or dlc.md_fenced_blocks(arch_doc, "sql"):
        fails.append(
            f"{args.architecture} must not embed SQL DDL or erDiagram blocks; "
            f"keep the 3NF erDiagram in design/data_architecture.md and design/solution_design.md, and SQL DDL/OpenAPI in {args.design}."
        )

    # ---- Document 2: Standalone Solution Design & Contracts (`design/solution_design.md`)
    design_mermaid_blocks = dlc.md_fenced_blocks(design, "mermaid")
    design_flow_or_seq = [
        b for b in design_mermaid_blocks
        if re.search(r"^\s*(?:flowchart|graph|sequenceDiagram)\b", b, re.IGNORECASE | re.MULTILINE)
    ]
    if design_flow_or_seq:
        fails.append(
            f"{args.design} must NOT embed Logical/Technical Architecture flowcharts or sequenceDiagrams "
            f"(found {len(design_flow_or_seq)} block(s)). Keep architecture diagrams in {args.architecture} and "
            f"solution design (3NF erDiagram, SQL DDL, OpenAPI 3.1, ViewModel/DTO mapping) in {args.design}."
        )
    er_blocks = [b for b in design_mermaid_blocks if "erdiagram" in b.lower()]
    if not er_blocks:
        (fails if db_kind != "none" else warns).append(
            f"Missing Future-State ('To-Be') normalised 3NF ```mermaid erDiagram block in {args.design} (database.kind={db_kind})."
        )
    elif not re.search(r"\w+\s+[|}o][|o]?--[|o][|{o]?\s+\w+", er_blocks[0]) and not re.search(r"^\s*\w+\s*\{", er_blocks[0], re.MULTILINE):
        fails.append(f"Future-State erDiagram block in {args.design} contains no entities or relationships.")
    else:
        data_er_blocks = [b for b in dlc.md_fenced_blocks(data_doc, "mermaid") if "erdiagram" in b.lower()]
        if db_kind != "none" and data_doc and not data_er_blocks:
            warns.append("design/data_architecture.md has no 3NF ```mermaid erDiagram block mirroring design/solution_design.md.")
        elif data_er_blocks:
            sol_ents = {e.lower() for e in re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\{", er_blocks[0], re.MULTILINE)}
            dat_ents = {e.lower() for e in re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\{", data_er_blocks[0], re.MULTILINE)}
            if sol_ents and dat_ents and sol_ents != dat_ents:
                fails.append(
                    f"3NF erDiagram entity mismatch between design/data_architecture.md ({sorted(dat_ents)}) and "
                    f"{args.design} ({sorted(sol_ents)}). Keep both 3NF entity models synchronized."
                )

    # ---- Legacy-to-Target 3NF Entity Mapping in Stage 4A (for SCENARIO_LEGACY_APP)
    if legacy:
        map_rows = dlc.find_table(design, ["legacy", "target"])
        if not map_rows:
            mig_p = root / "design" / "data_migration_and_cutover.md"
            mig_rows = dlc.find_table(dlc.read_text(mig_p), ["legacy", "target"]) if mig_p.exists() else []
            if not mig_rows:
                fails.append(
                    f"SCENARIO_LEGACY_APP requires a Future-State '§1.1 Legacy-to-Target 3NF Entity Mapping' table "
                    f"(columns including 'Legacy …' and 'Target …') in {args.design}."
                )

    # ---- OpenAPI
    yaml_blocks = [b for b in dlc.md_fenced_blocks(design, "yaml") + dlc.md_fenced_blocks(design, "yml") if re.search(r"^openapi:", b, re.MULTILINE)]
    api: dict[str, Any] = {"version": "", "paths": [], "enums": [], "internalFields": [], "schemas": []}
    if not yaml_blocks:
        (fails if backend_kind != "none" else warns).append(
            f"No ```yaml block containing 'openapi:' in {args.design} (backend.kind={backend_kind}).")
    else:
        if len(yaml_blocks) > 1:
            fails.append(
                f"Found {len(yaml_blocks)} ```yaml blocks containing 'openapi:' in {args.design} — consolidate into a single canonical OpenAPI 3.1 contract."
            )
        openapi_text = yaml_blocks[0]
        api = parse_openapi(openapi_text)
        if not api["version"].startswith("3"):
            fails.append(f"OpenAPI version must be 3.x (found {api['version'] or 'none'}).")
        elif not api["version"].startswith("3.1"):
            warns.append(f"OpenAPI version {api['version']} — 3.1 is the v4 target.")
        if not re.search(r"^paths:\s*$", openapi_text, re.MULTILINE):
            fails.append("OpenAPI document has no top-level 'paths:' section.")
        elif not api["paths"]:
            fails.append("OpenAPI 'paths:' contains no operations (expected '/path:' entries with get/post/… methods).")
        no_op = [f"{p['method']} {p['path']}" for p in api["paths"] if not p["operationId"]]
        if no_op:
            warns.append(f"{len(no_op)} operation(s) without operationId: {', '.join(no_op[:5])}")
        # trigger coverage (WARN only)
        hay = " ".join(f"{p['path']} {p['operationId']}".lower() for p in api["paths"])
        hay_c = re.sub(r"[^a-z0-9]", "", hay)
        for trig in sm.triggers():
            slug = re.sub(r"[^a-z0-9]", "", trig.lower())
            if slug and slug not in hay_c and dlc.slugify(trig) not in hay:
                warns.append(f"State-machine trigger '{trig}' has no OpenAPI path/operationId containing '{dlc.slugify(trig)}'.")
        out_api = dlc.project_path(root, args.openapi_out)
        dlc.write_text(out_api, openapi_text if openapi_text.endswith("\n") else openapi_text + "\n")
        log(f"wrote {out_api} ({len(api['paths'])} operations)")

    # ---- DDL
    sql_blocks = [b for b in dlc.md_fenced_blocks(design, "sql") if re.search(r"CREATE\s+TABLE", b, re.IGNORECASE)]
    tables: list[dict[str, Any]] = []
    if not sql_blocks:
        (fails if db_kind != "none" else warns).append(
            f"No ```sql block containing CREATE TABLE in {args.design} (database.kind={db_kind}).")
    else:
        ddl_text = "\n\n".join(f"-- ---- block {i + 1} (extracted from {args.design}) ----\n{b.strip()}" for i, b in enumerate(sql_blocks)) + "\n"
        tables = parse_ddl(ddl_text)
        if not tables:
            fails.append("CREATE TABLE statements could not be parsed (check parentheses).")
        legacy_fail, legacy_warn = legacy_identifier_sets(inv) if legacy else (set(), set())
        seen_tables = set()
        for t in tables:
            if t["name"] in seen_tables:
                fails.append(f"Table '{t['name']}' defined more than once.")
            seen_tables.add(t["name"])
            if not t["hasPrimaryKey"]:
                fails.append(f"Table '{t['name']}' has no PRIMARY KEY.")
            if not SNAKE_RE.match(t["name"]):
                fails.append(f"Table name '{t['name']}' is not snake_case.")
            for c in t["columns"]:
                if not SNAKE_RE.match(c):
                    fails.append(f"Column '{t['name']}.{c}' is not snake_case.")
            if legacy:
                for ident in [t["name"]] + t["columns"]:
                    low = ident.lower()
                    if low in legacy_fail:
                        fails.append(f"'{t['name']}.{ident}' equals a legacy object identifier from the input estate — rename (clean migration, no legacy carry-over).")
                    elif low in legacy_warn:
                        warns.append(f"'{t['name']}.{ident}' matches bare legacy file stem '{low}' — verify it is a genuine domain noun, not a legacy table/form name.")
        out_ddl = dlc.project_path(root, args.ddl_out)
        dlc.write_text(out_ddl, ddl_text)
        log(f"wrote {out_ddl} ({len(tables)} tables)")

    # ---- Legacy-only artefact
    if legacy and not (root / "design" / "data_migration_and_cutover.md").exists():
        fails.append("SCENARIO_LEGACY_APP requires design/data_migration_and_cutover.md (Stage 4A).")

    # ---- Index
    index = {
        "schemaVersion": dlc.SCHEMA_VERSION,
        "architectureSha256": dlc.sha256_file(arch_path),
        "designSha256": dlc.sha256_file(design_path),
        "openapiVersion": api["version"],
        "tables": [{"name": t["name"], "columns": t["columns"]} for t in tables],
        "paths": api["paths"],
        "enums": api["enums"],
        "internalFields": api["internalFields"],
        "schemas": api["schemas"],
        "stateTriggers": sm.triggers(),
    }
    dlc.write_json(root / "design" / ".contracts_index.json", index)

    if args.json:
        print(json.dumps({"passed": not fails, "failures": fails, "warnings": warns, "index": index}, indent=2))
    else:
        for w in warns:
            dlc.warn(w)
        for f in fails:
            print(f"  ✗ {f}")
        print(f"[dlc] Gate 4a contracts: {'PASS' if not fails else 'FAIL'} — {len(tables)} tables, {len(api['paths'])} operations, "
              f"{len(api['enums'])} enum values; index -> design/.contracts_index.json")
        if not fails:
            dlc.mark_gate_awaiting_human(
                root,
                "gate_4_design_and_tests",
                summary="Stage 4A Multi-Perspective Architecture Suite & Solution Design contracts validated. Once Stage 4B Test Plan is also validated, present design/ & test/ deliverables to user and STOP for Gate 4A/4B approval before Stage 5 Build.",
            )
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
