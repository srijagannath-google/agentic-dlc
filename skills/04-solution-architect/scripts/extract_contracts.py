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


def _architecture_dsl_blocks(md: str) -> list[str]:
    """Return diagram specification blocks (`diagram-dsl` or `mermaid`) from an architecture perspective file."""
    return dlc.md_fenced_blocks(md, "diagram-dsl") + dlc.md_fenced_blocks(md, "mermaid")


def _resolve_app_title(arch_doc: str, bus_doc: str, spec: str, root: Path) -> str:
    """Resolve a clean human-readable application title without filename/scenario suffixes."""
    for candidate_doc in (bus_doc, arch_doc):
        proj_m = re.search(r"^\s*-\s*\*\*Project:\*\*\s*(.+)$", candidate_doc, re.MULTILINE | re.IGNORECASE)
        if proj_m:
            raw = re.sub(r"`[^`]*`", "", proj_m.group(1)).strip()
            raw = re.sub(r"\(\s*\)", "", raw).strip()
            raw = re.split(r"\s+[—–-]\s+(?:Legacy|Greenfield|Modernization|Architecture)\b", raw, maxsplit=1)[0].strip()
            raw = re.sub(r"\s*\([^)]*\)\s*$", "", raw).strip()
            if raw:
                return raw
    cm_title_m = re.search(r"^\s*%%\s*title\s*:\s*(.+)$", bus_doc, re.MULTILINE | re.IGNORECASE)
    if cm_title_m:
        raw = re.sub(r"\s+Capability\s+Map\s*$", "", cm_title_m.group(1).strip(), flags=re.IGNORECASE).strip()
        if raw and "<" not in raw:
            return raw
    spec_h1_m = re.search(r"^#\s+(.+)$", spec, re.MULTILINE)
    if spec_h1_m:
        raw = re.sub(r"`[^`]*`", "", spec_h1_m.group(1)).strip()
        raw = re.split(r"\s+[—–-]\s+(?:Application\s+Specification|5-Pillar|Specification)\b", raw, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        raw = re.sub(r"\s*\([^)]*\)\s*$", "", raw).strip()
        if raw:
            return raw
    doc_title_m = re.search(r"^#\s+(.+?)(?:\s+[—–-]\s+Architecture\s+Design.*)?$", arch_doc, re.MULTILINE | re.IGNORECASE)
    if doc_title_m:
        raw = re.sub(r"`[^`]*`", "", doc_title_m.group(1)).strip()
        raw = re.sub(r"\(\s*\)", "", raw).strip()
        if raw and not re.search(r"Architecture\s+(?:Portfolio|Design)", raw, re.IGNORECASE):
            return raw
    return root.name.replace("_", " ").replace("-", " ").title()


_FLOWCHART_DSL_BLOCK_RE = re.compile(
    r"<details>\s*<summary>[^<]*</summary>\s*```(?:mermaid|diagram-dsl)[^\n]*\n"
    r"((?:[ \t]*%%[^\n]*\n|[ \t]*\n)*[ \t]*(?:flowchart|graph)\b.*?)```\s*</details>"
    r"|```(?:mermaid|diagram-dsl)[^\n]*\n"
    r"((?:[ \t]*%%[^\n]*\n|[ \t]*\n)*[ \t]*(?:flowchart|graph)\b.*?)```",
    re.DOTALL | re.IGNORECASE,
)


def _strip_outer_fence(raw: str) -> str:
    s = raw.strip()
    m = re.match(r"^```(?:mermaid|diagram-dsl)?[^\n]*\n(.*?)\n```\s*$", s, re.DOTALL | re.IGNORECASE)
    return (m.group(1) if m else s).strip()


def _load_perspective_flowchart_blocks(
    root: Path,
    doc_text: str,
    diagram_stem: str,
    predicate: Any,
) -> list[str]:
    """Load flowchart diagram specification from hidden `design/diagrams/.specs/<stem>.mmd` or inline Markdown.

    Whenever an inline flowchart block is present in `doc_text`, it is persisted to
    `design/diagrams/.specs/<stem>.mmd` so the published Markdown artifact can stay 100% free
    of raw diagram DSL and internal script annotations.
    """
    spec_mmd_path = root / "design" / "diagrams" / ".specs" / f"{diagram_stem}.mmd"
    inline_blocks = [b for b in _architecture_dsl_blocks(doc_text) if predicate(b)]
    if inline_blocks:
        body = _strip_outer_fence(inline_blocks[0]) + "\n"
        dlc.write_text(spec_mmd_path, body)
        return [body.strip()]
    if spec_mmd_path.is_file():
        saved = _strip_outer_fence(dlc.read_text(spec_mmd_path))
        if saved and predicate(saved):
            return [saved]
    return []


def _diagram_files_caption(diagram_stem: str, has_png: bool) -> str:
    if has_png:
        return (
            f"*Standalone diagram files: [Vector SVG](./diagrams/{diagram_stem}.svg) · "
            f"[Raster PNG](./diagrams/{diagram_stem}.png)*"
        )
    return f"*Standalone diagram files: [Vector SVG](./diagrams/{diagram_stem}.svg)*"


def _clean_perspective_diagram_embed(
    doc_path: Path,
    doc_text: str,
    alt_text: str,
    diagram_stem: str,
    svg_path: Path,
    has_png: bool,
) -> str:
    """Embed a universal self-contained `data:image/svg+xml;base64,...` diagram plus standalone `.svg`/`.png` links.

    Guarantees diagrams render visibly in every IDE/Web/sandbox viewer (even when directory-relative webview
    asset resolution or headless Chrome PNG rasterization is unavailable), while stripping inline flowchart DSL
    and leaving `sequenceDiagram` and `erDiagram` Mermaid blocks untouched.
    """
    data_uri = gdr.svg_to_data_uri(dlc.read_text(svg_path))
    caption = _diagram_files_caption(diagram_stem, has_png)
    updated = doc_text

    if not has_png:
        updated = re.sub(
            rf"(?<!!)\[([^\]]*?){re.escape(diagram_stem)}\.png([^\]]*?)\]\((?:\./)?diagrams/{re.escape(diagram_stem)}\.png\)",
            rf"[\1{diagram_stem}.svg\2](./diagrams/{diagram_stem}.svg)",
            updated,
        )
        updated = re.sub(
            rf"(?<!!)\]\((?:\./)?diagrams/{re.escape(diagram_stem)}\.png\)",
            f"](./diagrams/{diagram_stem}.svg)",
            updated,
        )

    existing_embed_re = re.compile(
        rf"!\[([^\]]*)\]\((?:(?:\./)?diagrams/{re.escape(diagram_stem)}\.(?:png|svg)|data:image/svg\+xml;base64,[A-Za-z0-9+/=]+)\)"
        r"(?:\s*\n+\*Standalone diagram files:[^\n]*\*)?",
    )
    has_img_already = bool(existing_embed_re.search(updated))
    if has_img_already:
        updated = existing_embed_re.sub(
            lambda m: f"![{m.group(1) or alt_text}]({data_uri})\n\n{caption}",
            updated,
            count=1,
        )

    inserted_img = False

    def _strip_block(_m: re.Match[str]) -> str:
        nonlocal inserted_img
        if not has_img_already and not inserted_img:
            inserted_img = True
            return f"![{alt_text}]({data_uri})\n\n{caption}"
        return ""

    updated = _FLOWCHART_DSL_BLOCK_RE.sub(_strip_block, updated)
    updated = re.sub(r"\n{3,}", "\n\n", updated).strip() + "\n"

    if updated != doc_text:
        dlc.write_text(doc_path, updated)
    return updated


def _normalize_portfolio_index_embeds(arch_path: Path, arch_doc: str, diagrams_dir: Path) -> str:
    """Embed universal self-contained `data:image/svg+xml;base64,...` diagrams + standalone links in `design/architecture_design.md`."""
    def _build_embed(alt: str, stem: str, fallback: str) -> str:
        svg_file = diagrams_dir / f"{stem}.svg"
        if not svg_file.is_file():
            return fallback
        data_uri = gdr.svg_to_data_uri(dlc.read_text(svg_file))
        has_png = (diagrams_dir / f"{stem}.png").is_file()
        return f"![{alt}]({data_uri})\n\n{_diagram_files_caption(stem, has_png)}"

    existing_data_re = re.compile(
        r"!\[([^\]]*)\]\(data:image/svg\+xml;base64,[A-Za-z0-9+/=]+\)"
        r"\s*\n+\*Standalone diagram files:\s*\[Vector SVG\]\((?:\./)?diagrams/([A-Za-z0-9_.-]+)\.svg\)[^\n]*\*"
    )
    updated = existing_data_re.sub(lambda m: _build_embed(m.group(1), m.group(2), m.group(0)), arch_doc)

    rel_img_re = re.compile(
        r"!\[([^\]]*)\]\((?:\./)?diagrams/([A-Za-z0-9_.-]+)\.(?:png|svg)\)"
        r"(?:\s*\n+\*Standalone diagram files:[^\n]*\*)?"
    )
    updated = rel_img_re.sub(lambda m: _build_embed(m.group(1), m.group(2), m.group(0)), updated)

    def _fix_table_png_link(m: re.Match[str]) -> str:
        label_txt, stem = m.group(1), m.group(2)
        if (diagrams_dir / f"{stem}.png").is_file() or not (diagrams_dir / f"{stem}.svg").is_file():
            return m.group(0)
        new_label = label_txt.replace(f"{stem}.png", f"{stem}.svg")
        return f"[{new_label}](./diagrams/{stem}.svg)"

    updated = re.sub(
        r"(?<!!)\[([^\]]+)\]\((?:\./)?diagrams/([A-Za-z0-9_.-]+)\.png\)",
        _fix_table_png_link,
        updated,
    )
    updated = re.sub(r"\n{3,}", "\n\n", updated).strip() + "\n"

    if updated != arch_doc:
        dlc.write_text(arch_path, updated)
    return updated


def _verify_markdown_image_targets(root: Path, md_rel_paths: list[str]) -> list[str]:
    """Fail closed if any Markdown image target in `design/*.md` points to a missing/empty file or malformed data URI."""
    errs: list[str] = []
    fence_re = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
    img_re = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
    for rel in md_rel_paths:
        md_file = root / rel
        if not md_file.is_file():
            continue
        prose = fence_re.sub("", dlc.read_text(md_file))
        for m in img_re.finditer(prose):
            alt, raw_target = m.group(1), m.group(2).strip()
            if raw_target.startswith("data:image/svg+xml;base64,"):
                b64 = raw_target.split(",", 1)[1]
                if len(b64) < 64 or re.search(r"\s", raw_target):
                    errs.append(f"{rel}: malformed or whitespace-containing SVG data URI on image '{alt}'.")
                continue
            if re.match(r"^https?://", raw_target, re.IGNORECASE):
                continue
            clean_rel = raw_target.split("#", 1)[0].split("?", 1)[0].strip().strip("<>")
            resolved = (md_file.parent / clean_rel).resolve()
            if not resolved.is_file() or resolved.stat().st_size == 0:
                errs.append(
                    f"{rel}: broken Markdown image '![{alt}]({raw_target})' — target file '{clean_rel}' "
                    f"does not exist or is empty relative to '{md_file.parent.relative_to(root)}'."
                )
    return errs


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
        dlc.strip_inline_data_uris(arch_doc + "\n" + design),
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
                dlc.strip_inline_data_uris(p_txt),
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

    bus_doc = perspective_docs.get("design/business_architecture.md", arch_doc)
    bus_blocks = _load_perspective_flowchart_blocks(
        root,
        bus_doc,
        "business_capability_map",
        lambda b: bool(
            re.search(r"^\s*(?:flowchart|graph)\s+T[BD]\b", b, re.IGNORECASE | re.MULTILINE)
            or re.search(r"Foundational\s+Capabilities", b, re.IGNORECASE)
        ),
    )
    app_title = _resolve_app_title(arch_doc, bus_doc + ("\n" + bus_blocks[0] if bus_blocks else ""), spec, root)

    # 1. Business Architecture (`design/business_architecture.md` + `design/diagrams/.specs/business_capability_map.mmd` -> `business_capability_map.{svg,png}`)
    if not bus_blocks:
        fails.append(
            "Missing 'flowchart TB' Business Capability Map diagram specification in design/diagrams/.specs/business_capability_map.mmd "
            "(or inline in design/business_architecture.md) covering Value-Stream Pillars '1. ...' .. '4. ...', Core Business Capabilities, and 'Foundational Capabilities'."
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
            bus_path = root / "design" / "business_architecture.md"
            if bus_path.exists():
                perspective_docs["design/business_architecture.md"] = _clean_perspective_diagram_embed(
                    bus_path,
                    bus_doc,
                    "Business Capability Map",
                    "business_capability_map",
                    cm_svg_written,
                    cm_png_written is not None and cm_png_written.exists(),
                )
            if not args.json:
                extra = f" (+ {cm_png_written.name})" if cm_png_written else ""
                print(f"[dlc] rendered {cm_svg_written}{extra}")

    # 2. High-Level Solution Architecture (`design/high_level_solution_architecture.md` + `.specs/high_level_solution_architecture.mmd`)
    hl_doc = perspective_docs.get("design/high_level_solution_architecture.md", "")
    hl_blocks = _load_perspective_flowchart_blocks(
        root,
        hl_doc,
        "high_level_solution_architecture",
        lambda b: bool(re.search(r"^\s*(?:flowchart|graph)\b", b, re.IGNORECASE | re.MULTILINE)),
    )
    if not hl_blocks:
        fails.append(
            "Missing flowchart diagram specification in design/diagrams/.specs/high_level_solution_architecture.mmd "
            "(or design/high_level_solution_architecture.md) depicting Personas, Engagement Layer, System of Intelligence & AI, and Transactional Systems."
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
            hl_path = root / "design" / "high_level_solution_architecture.md"
            if hl_path.exists():
                perspective_docs["design/high_level_solution_architecture.md"] = _clean_perspective_diagram_embed(
                    hl_path,
                    hl_doc,
                    "High-Level Solution Architecture",
                    "high_level_solution_architecture",
                    hl_svg_written,
                    hl_png_written is not None and hl_png_written.exists(),
                )
            if not args.json:
                extra = f" (+ {hl_png_written.name})" if hl_png_written else ""
                print(f"[dlc] rendered {hl_svg_written}{extra}")

    # 3. Logical Architecture (`design/logical_architecture.md`) & 7. Infrastructure Architecture (`design/infrastructure_architecture.md`)
    log_doc = perspective_docs.get("design/logical_architecture.md", arch_doc)
    inf_doc = perspective_docs.get("design/infrastructure_architecture.md", arch_doc)
    log_lr = _load_perspective_flowchart_blocks(
        root,
        log_doc,
        "logical_architecture",
        lambda b: bool(re.search(r"^\s*flowchart\s+LR\b", b, re.IGNORECASE | re.MULTILINE)),
    )
    inf_lr = _load_perspective_flowchart_blocks(
        root,
        inf_doc,
        "infrastructure_architecture",
        lambda b: bool(re.search(r"^\s*flowchart\s+LR\b", b, re.IGNORECASE | re.MULTILINE)),
    )

    if not log_lr or not inf_lr:
        fails.append(
            f"design/diagrams/.specs/logical_architecture.mmd and design/diagrams/.specs/infrastructure_architecture.mmd "
            f"(or their perspective .md files) must each define a 'flowchart LR' diagram specification "
            f"(found logical={len(log_lr)}, infrastructure={len(inf_lr)})."
        )
    else:
        labels_stems = [
            ("design/logical_architecture.md", "logical_architecture", "Logical Solution Architecture", log_lr[0]),
            ("design/infrastructure_architecture.md", "infrastructure_architecture", "Infrastructure & Deployment Architecture", inf_lr[0]),
        ]
        parsed_specs: list[dict[str, Any]] = [
            gdr.parse_mermaid_flowchart_to_spec(log_lr[0], "logical_architecture"),
            gdr.parse_mermaid_flowchart_to_spec(inf_lr[0], "infrastructure_architecture"),
        ]
        for idx, (label, default_stem, alt_label, fb) in enumerate(labels_stems):
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
                p_doc_path = root / label
                if p_doc_path.exists() and label in perspective_docs:
                    perspective_docs[label] = _clean_perspective_diagram_embed(
                        p_doc_path,
                        perspective_docs[label],
                        alt_label,
                        default_stem,
                        svg_written,
                        png_written is not None and png_written.exists(),
                    )
                if not args.json:
                    extra = f" (+ {png_written.name})" if png_written else ""
                    print(f"[dlc] rendered {svg_written}{extra}")
                if default_stem == "infrastructure_architecture":
                    tech_alias_svg = arch_path.parent / "diagrams" / "technical_architecture.svg"
                    gdr.write_svg_and_png(spec_obj, tech_alias_svg)

    # 4. Application Architecture (`design/application_architecture.md` + `.specs/application_architecture.mmd` + sequenceDiagram)
    app_doc = perspective_docs.get("design/application_architecture.md", "")
    app_flow_blocks = _load_perspective_flowchart_blocks(
        root,
        app_doc,
        "application_architecture",
        lambda b: bool(re.search(r"^\s*(?:flowchart|graph)\b", b, re.IGNORECASE | re.MULTILINE)),
    )
    if not app_flow_blocks:
        fails.append("Missing flowchart diagram specification in design/diagrams/.specs/application_architecture.mmd (or design/application_architecture.md).")
    else:
        app_parsed = gdr.parse_layered_perspective_mermaid(app_flow_blocks[0], app_title=f"{app_title} — Application & AI Architecture")
        app_errs = gdr.validate_perspective_spec(app_parsed, "design/application_architecture.md", min_cards=8)
        if app_errs:
            fails.extend(app_errs)
        else:
            app_svg_out = arch_path.parent / "diagrams" / "application_architecture.svg"
            app_svg_written, app_png_written = gdr.write_application_architecture_svg_and_png(app_parsed, app_svg_out)
            rendered_svgs.append(str(app_svg_written.relative_to(root)))
            app_path = root / "design" / "application_architecture.md"
            if app_path.exists():
                app_doc = _clean_perspective_diagram_embed(
                    app_path,
                    app_doc,
                    "Application Architecture",
                    "application_architecture",
                    app_svg_written,
                    app_png_written is not None and app_png_written.exists(),
                )
                perspective_docs["design/application_architecture.md"] = app_doc
            if not args.json:
                extra = f" (+ {app_png_written.name})" if app_png_written else ""
                print(f"[dlc] rendered {app_svg_written}{extra}")

    # 5. Data Architecture (`design/data_architecture.md` + `.specs/data_architecture.mmd` + erDiagram)
    data_doc = perspective_docs.get("design/data_architecture.md", "")
    data_flow_blocks = _load_perspective_flowchart_blocks(
        root,
        data_doc,
        "data_architecture",
        lambda b: bool(re.search(r"^\s*(?:flowchart|graph)\b", b, re.IGNORECASE | re.MULTILINE)),
    )
    if not data_flow_blocks:
        fails.append("Missing flowchart diagram specification in design/diagrams/.specs/data_architecture.mmd (or design/data_architecture.md).")
    else:
        data_parsed = gdr.parse_layered_perspective_mermaid(data_flow_blocks[0], app_title=f"{app_title} — Data & Information Architecture")
        data_errs = gdr.validate_perspective_spec(data_parsed, "design/data_architecture.md", min_cards=8)
        if data_errs:
            fails.extend(data_errs)
        else:
            data_svg_out = arch_path.parent / "diagrams" / "data_architecture.svg"
            data_svg_written, data_png_written = gdr.write_data_architecture_svg_and_png(data_parsed, data_svg_out)
            rendered_svgs.append(str(data_svg_written.relative_to(root)))
            data_path = root / "design" / "data_architecture.md"
            if data_path.exists():
                data_doc = _clean_perspective_diagram_embed(
                    data_path,
                    data_doc,
                    "Data Architecture",
                    "data_architecture",
                    data_svg_written,
                    data_png_written is not None and data_png_written.exists(),
                )
                perspective_docs["design/data_architecture.md"] = data_doc
            if not args.json:
                extra = f" (+ {data_png_written.name})" if data_png_written else ""
                print(f"[dlc] rendered {data_svg_written}{extra}")

    # 6. Security Architecture (`design/security_architecture.md` + `.specs/security_architecture.mmd`)
    sec_doc = perspective_docs.get("design/security_architecture.md", "")
    sec_flow_blocks = _load_perspective_flowchart_blocks(
        root,
        sec_doc,
        "security_architecture",
        lambda b: bool(re.search(r"^\s*(?:flowchart|graph)\b", b, re.IGNORECASE | re.MULTILINE)),
    )
    if not sec_flow_blocks:
        fails.append("Missing flowchart diagram specification in design/diagrams/.specs/security_architecture.mmd (or design/security_architecture.md).")
    else:
        sec_parsed = gdr.parse_layered_perspective_mermaid(sec_flow_blocks[0], app_title=f"{app_title} — Security, Privacy & AI Trust Architecture")
        sec_errs = gdr.validate_perspective_spec(sec_parsed, "design/security_architecture.md", min_cards=8)
        if sec_errs:
            fails.extend(sec_errs)
        else:
            sec_svg_out = arch_path.parent / "diagrams" / "security_architecture.svg"
            sec_svg_written, sec_png_written = gdr.write_security_architecture_svg_and_png(sec_parsed, sec_svg_out)
            rendered_svgs.append(str(sec_svg_written.relative_to(root)))
            sec_path = root / "design" / "security_architecture.md"
            if sec_path.exists():
                sec_doc = _clean_perspective_diagram_embed(
                    sec_path,
                    sec_doc,
                    "Security Architecture",
                    "security_architecture",
                    sec_svg_written,
                    sec_png_written is not None and sec_png_written.exists(),
                )
                perspective_docs["design/security_architecture.md"] = sec_doc
            if not args.json:
                extra = f" (+ {sec_png_written.name})" if sec_png_written else ""
                print(f"[dlc] rendered {sec_svg_written}{extra}")

    if not fails:
        arch_doc = _normalize_portfolio_index_embeds(arch_path, arch_doc, arch_path.parent / "diagrams")
        all_arch_text = arch_doc + "\n" + "\n".join(perspective_docs.values())
        arch_mermaid_blocks = dlc.md_fenced_blocks(arch_doc, "mermaid")
        fails.extend(
            _verify_markdown_image_targets(
                root,
                [args.architecture, *(p_rel for _, p_rel, _ in perspective_files)],
            )
        )

    # Forbid raw Mermaid flowchart blocks inside the Executive Portfolio Index (`design/architecture_design.md`)
    arch_raw_flow = [
        b for b in arch_mermaid_blocks
        if re.search(r"^\s*(?:flowchart|graph)\b", b, re.IGNORECASE | re.MULTILINE)
    ]
    if arch_raw_flow:
        fails.append(
            f"{args.architecture} must embed rendered diagram images ('diagrams/<perspective>.png') rather than raw "
            f"```mermaid flowchart blocks (found {len(arch_raw_flow)} raw flowchart block(s), which render as vertical stacked boxes)."
        )

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
    design_mermaid_blocks = dlc.md_fenced_blocks(design, "mermaid") + dlc.md_fenced_blocks(design, "diagram-dsl")
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
        ddl_text = "\n\n".join(b.strip() for b in sql_blocks) + "\n"
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

    # ---- Zero internal harness workings leak check across all Stage 4A deliverables
    stage4a_deliverables = [
        args.architecture,
        args.design,
        *(p_rel for _, p_rel, _ in perspective_files),
        args.openapi_out,
        args.ddl_out,
    ]
    if (root / "design" / "data_migration_and_cutover.md").exists():
        stage4a_deliverables.append("design/data_migration_and_cutover.md")
    fails.extend(dlc.scan_deliverable_internal_leaks(root, stage4a_deliverables))

    # ---- Coexistence Boundary Isolation Check (if deploy/coexistence/ exists, src/ must still stay 100% clean)
    coex_dir = root / "deploy" / "coexistence"
    coex_files = sorted(str(p.relative_to(root)) for p in coex_dir.rglob("*") if p.is_file()) if coex_dir.is_dir() else []

    # ---- Guardrail Bindings for Contract-Pinned Stage 6 Diff Auditing (@dlc-guard / @dlc-rule / @dlc-mask / @dlc-a11y)
    spec_rules = dlc.parse_business_rules(spec)
    spec_roles = dlc.parse_roles(spec)
    guardrail_bindings = {
        "stateTransitions": [
            {"from": t.src, "to": t.dst, "trigger": t.trigger, "roles": t.roles, "guard": t.guard}
            for t in sm.transitions
        ],
        "businessRuleIds": [r["id"] for r in spec_rules if r.get("id")],
        "roles": [r["role"] for r in spec_roles if r.get("role")],
        "pragmaAnnotations": [
            "@dlc-guard:<FromState>-><ToState>",
            "@dlc-rule:<BR-ID>",
            "@dlc-mask:<sensitive-field>",
            "@dlc-a11y:<wcag-criterion>",
        ],
    }

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
        "coexistenceStrategy": (stack.get("coexistenceStrategy") if isinstance(stack, dict) else None) or "clean-cutover",
        "coexistenceArtifacts": coex_files,
        "guardrailBindings": guardrail_bindings,
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
