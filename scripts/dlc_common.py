#!/usr/bin/env python3
"""Shared helpers for agentic-dlc v4 scripts.

Import from a skill script with:

    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "scripts"))
    import dlc_common as dlc

Only the Python standard library is used. Python >= 3.10.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "4.0"
INSTALLER_DIR_PATTERN = re.compile(r"^.*agentic-dlc", re.IGNORECASE)
PLUGIN_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------------------
# Exit / logging helpers
# --------------------------------------------------------------------------------------
class GateFailure(SystemExit):
    """Raised to stop a stage with a non-zero exit code and a human-readable reason."""

    def __init__(self, message: str, code: int = 1):
        print(f"\n[GATE FAILED] {message}", file=sys.stderr)
        super().__init__(code)


def info(msg: str) -> None:
    print(f"[dlc] {msg}")


def warn(msg: str) -> None:
    print(f"[dlc][warn] {msg}", file=sys.stderr)


def require_file(path: Path, produced_by: str) -> Path:
    """Fail loudly (never fall back to a template) if an upstream artefact is missing."""
    if not path.exists() or path.stat().st_size == 0:
        raise GateFailure(
            f"Required artefact missing or empty: {path}\n"
            f"  It must be authored by: {produced_by}\n"
            f"  v4 scripts never substitute templates. Run that stage first."
        )
    return path


# --------------------------------------------------------------------------------------
# Project root
# --------------------------------------------------------------------------------------
def is_installer_dir(p: Path) -> bool:
    return bool(INSTALLER_DIR_PATTERN.match(p.name))


def resolve_project_root(explicit: str | None = None) -> Path:
    """Resolve <PROJECT_ROOT> per _shared/project_root.md. Never returns the installer dir."""
    candidates: list[Path] = []
    if explicit:
        ex = Path(explicit).expanduser()
        if is_installer_dir(ex):
            raise GateFailure(f"--project-root {ex} is the plugin/installer directory — never a <PROJECT_ROOT> (see _shared/project_root.md).")
        candidates.append(ex)
    cfg = Path.home() / ".gemini" / "config" / "project_root.txt"
    if cfg.exists():
        txt = cfg.read_text(encoding="utf-8").strip()
        if txt:
            candidates.append(Path(txt).expanduser())
    cwd = Path.cwd()
    candidates.append(cwd)
    if is_installer_dir(cwd) and cwd.parent.name not in {"Downloads", "Desktop", "Documents", Path.home().name}:
        candidates.append(cwd.parent)
    for c in candidates:
        try:
            c = c.resolve()
        except OSError:
            continue
        if c.is_dir() and not is_installer_dir(c):
            return c
    raise GateFailure(
        "Could not resolve <PROJECT_ROOT>. Pass --project-root <dir> (must not be the plugin/installer directory)."
    )


def add_project_root_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-root", default=None, help="Project root (see _shared/project_root.md)")


def project_path(root: Path, rel: str | Path) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else root / p


# --------------------------------------------------------------------------------------
# IO helpers
# --------------------------------------------------------------------------------------
def utc_now_iso(deterministic: bool = False) -> str:
    if deterministic:
        return "1970-01-01T00:00:00Z"
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(p.read_bytes())


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def read_json(p: Path) -> Any:
    try:
        return json.loads(read_text(p))
    except json.JSONDecodeError as e:
        raise GateFailure(f"Invalid JSON in {p}: {e}")


def write_json(p: Path, data: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")


def write_text(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return re.sub(r"-{2,}", "-", s) or "application"


def normalise_ws(text: str) -> str:
    """Collapse whitespace and lowercase — used for verbatim-evidence matching."""
    return re.sub(r"\s+", " ", text).strip().lower()


def schema_path(name: str) -> Path:
    """Path of a schema under <plugin>/schemas (e.g. 'test_cases.schema.json')."""
    return PLUGIN_ROOT / "schemas" / name


def load_schema(name: str) -> dict[str, Any]:
    p = schema_path(name)
    if not p.exists():
        raise GateFailure(f"Plugin schema missing: {p}")
    return read_json(p)


# --------------------------------------------------------------------------------------
# Minimal JSON-Schema (draft 2020-12 subset) validator — stdlib only
# --------------------------------------------------------------------------------------
_JSON_TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool, "null": type(None),
}


def _is_type(value: Any, t: str) -> bool:
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, _JSON_TYPES[t]) if t in _JSON_TYPES else True


def _resolve_ref(ref: str, root: dict[str, Any]) -> dict[str, Any]:
    if not ref.startswith("#/"):
        return {}
    node: Any = root
    for part in ref[2:].split("/"):
        node = node.get(part, {}) if isinstance(node, dict) else {}
    return node if isinstance(node, dict) else {}


def validate_against_schema(data: Any, schema: dict[str, Any], root: dict[str, Any] | None = None, path: str = "$") -> list[str]:
    """Return a list of '<json-path>: <problem>' strings (empty == valid).

    Supports: type, enum, const, required, properties, additionalProperties, items, minItems, maxItems,
    minLength, pattern, minimum, maximum, anyOf, oneOf, allOf, $ref (local '#/…' only).
    """
    root = root if root is not None else schema
    errs: list[str] = []
    if "$ref" in schema:
        schema = {**_resolve_ref(schema["$ref"], root), **{k: v for k, v in schema.items() if k != "$ref"}}
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_is_type(data, x) for x in types):
            errs.append(f"{path}: expected type {'|'.join(types)}, got {type(data).__name__}")
            return errs
    if "enum" in schema and data not in schema["enum"]:
        errs.append(f"{path}: value {data!r} not in enum {schema['enum']}")
    if "const" in schema and data != schema["const"]:
        errs.append(f"{path}: expected const {schema['const']!r}")
    if isinstance(data, str):
        if "minLength" in schema and len(data) < schema["minLength"]:
            errs.append(f"{path}: string shorter than {schema['minLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], data):
            errs.append(f"{path}: {data!r} does not match /{schema['pattern']}/")
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        if "minimum" in schema and data < schema["minimum"]:
            errs.append(f"{path}: {data} < minimum {schema['minimum']}")
        if "maximum" in schema and data > schema["maximum"]:
            errs.append(f"{path}: {data} > maximum {schema['maximum']}")
    if isinstance(data, dict):
        for req in schema.get("required", []):
            if req not in data:
                errs.append(f"{path}: missing required key '{req}'")
        props = schema.get("properties", {})
        for k, v in data.items():
            if k in props:
                errs += validate_against_schema(v, props[k], root, f"{path}.{k}")
            elif schema.get("additionalProperties") is False:
                errs.append(f"{path}: unexpected key '{k}'")
            elif isinstance(schema.get("additionalProperties"), dict):
                errs += validate_against_schema(v, schema["additionalProperties"], root, f"{path}.{k}")
    if isinstance(data, list):
        if "minItems" in schema and len(data) < schema["minItems"]:
            errs.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(data) > schema["maxItems"]:
            errs.append(f"{path}: more than {schema['maxItems']} items")
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(data):
                errs += validate_against_schema(item, schema["items"], root, f"{path}[{i}]")
    for comb in ("anyOf", "oneOf"):
        if comb in schema:
            results = [validate_against_schema(data, s, root, path) for s in schema[comb]]
            ok = [r for r in results if not r]
            if (comb == "anyOf" and not ok) or (comb == "oneOf" and len(ok) != 1):
                errs.append(f"{path}: does not satisfy {comb} ({'; '.join(min(results, key=len)[:2]) if results else 'no alternatives'})")
    for s in schema.get("allOf", []):
        errs += validate_against_schema(data, s, root, path)
    return errs


# --------------------------------------------------------------------------------------
# Markdown parsing helpers
# --------------------------------------------------------------------------------------
def md_fenced_blocks(md: str, lang: str | None = None) -> list[str]:
    """Return contents of ```lang fenced blocks (lang=None -> all)."""
    out = []
    for m in re.finditer(r"```([^\n`]*)\n(.*?)```", md, flags=re.DOTALL):
        tag = m.group(1).strip().lower()
        if lang is None or tag == lang.lower() or tag.startswith(lang.lower() + " "):
            out.append(m.group(2))
    return out


def md_section(md: str, heading_regex: str) -> str:
    """Return text of the first heading matching regex up to the next heading of same-or-higher level."""
    lines = md.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m and re.search(heading_regex, m.group(2), flags=re.IGNORECASE):
            level = len(m.group(1))
            j = i + 1
            while j < len(lines):
                m2 = re.match(r"^(#{1,6})\s+", lines[j])
                if m2 and len(m2.group(1)) <= level:
                    break
                j += 1
            return "\n".join(lines[i:j])
    return ""


def md_tables(md: str) -> list[list[dict[str, str]]]:
    """Parse all GitHub-style pipe tables into lists of row dicts keyed by normalised header."""
    tables: list[list[dict[str, str]]] = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-+:?\s*(\||$)", lines[i + 1]):
            headers = [h.strip().strip("*`").lower() for h in lines[i].strip().strip("|").split("|")]
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                row = {headers[k]: (cells[k] if k < len(cells) else "") for k in range(len(headers))}
                rows.append(row)
                i += 1
            tables.append(rows)
        else:
            i += 1
    return tables


def find_table(md: str, required_headers: Iterable[str]) -> list[dict[str, str]]:
    req = [h.lower() for h in required_headers]
    for t in md_tables(md):
        if t and all(any(r in h for h in t[0].keys()) for r in req):
            return t
    return []


def extract_ids(text: str, prefix: str) -> list[str]:
    """Ordered unique IDs like REQ-FUNC-01, US-TECH-03, BR-07, TC-STATE-12."""
    seen: dict[str, None] = {}
    for m in re.finditer(rf"\b{re.escape(prefix)}[A-Z0-9]*-?\d+\b", text):
        seen.setdefault(m.group(0), None)
    return list(seen)


def strip_md(s: str) -> str:
    """Remove inline markdown emphasis markers (backticks, asterisks, emphasis underscores) without touching
    underscores inside identifiers such as UPPER_SNAKE state codes or snake_case names."""
    s = re.sub(r"[`*]", "", s)
    s = s.replace("__", "")
    return re.sub(r"(?<!\w)_|_(?!\w)", "", s).strip()


# --------------------------------------------------------------------------------------
# State machine
# --------------------------------------------------------------------------------------
@dataclass
class Transition:
    src: str
    dst: str
    trigger: str
    roles: list[str] = field(default_factory=list)
    guard: str = ""


@dataclass
class StateMachine:
    states: list[str] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    initial: list[str] = field(default_factory=list)
    terminal: list[str] = field(default_factory=list)

    def triggers(self) -> list[str]:
        seen: dict[str, None] = {}
        for t in self.transitions:
            seen.setdefault(t.trigger, None)
        return list(seen)

    def allowed(self, state: str, trigger: str) -> list[Transition]:
        return [t for t in self.transitions if t.src == state and t.trigger == trigger]

    def illegal_pairs(self) -> list[tuple[str, str]]:
        out = []
        for s in self.states:
            for trig in self.triggers():
                if not self.allowed(s, trig):
                    out.append((s, trig))
        return out

    def roles(self) -> list[str]:
        seen: dict[str, None] = {}
        for t in self.transitions:
            for r in t.roles:
                seen.setdefault(r, None)
        return list(seen)


def _norm_state(s: str) -> str:
    s = s.strip()
    if s in ("[*]", "*"):
        return "[*]"
    return strip_md(s).strip().strip('"')


def parse_state_table(md: str) -> StateMachine:
    """Parse the mandatory `| From | To | Trigger | Actor Role | Guard |` table (spec §3.3)."""
    rows = find_table(md, ["from", "to", "trigger"])
    sm = StateMachine()
    for r in rows:
        src = _norm_state(r.get("from", ""))
        dst = _norm_state(r.get("to", ""))
        trig = strip_md(r.get("trigger", ""))
        if not src or not dst or not trig:
            continue
        role_cell = next((v for k, v in r.items() if "role" in k or "actor" in k), "")
        roles = [strip_md(x) for x in re.split(r"[,/;]| or ", role_cell) if strip_md(x)]
        guard = strip_md(next((v for k, v in r.items() if "guard" in k or "condition" in k), ""))
        sm.transitions.append(Transition(src, dst, trig, roles, guard))
        for s in (src, dst):
            if s not in ("[*]", "*") and s not in sm.states:
                sm.states.append(s)
    srcs = {t.src for t in sm.transitions}
    dsts = {t.dst for t in sm.transitions}
    sm.initial = [t.dst for t in sm.transitions if t.src in ("[*]", "*")] or [s for s in sm.states if s not in dsts]
    sm.terminal = [s for s in sm.states if s not in srcs]
    return sm


def parse_mermaid_state_diagram(md: str) -> StateMachine:
    """Fallback parser for ```mermaid stateDiagram-v2 blocks (no roles/guards available)."""
    sm = StateMachine()
    for block in md_fenced_blocks(md, "mermaid"):
        if "statediagram" not in block.lower():
            continue
        for line in block.splitlines():
            m = re.match(r"\s*([\w\[\]\*\"' -]+?)\s*-->\s*([\w\[\]\*\"' -]+?)\s*(?::\s*(.*))?$", line)
            if not m:
                continue
            src, dst, label = _norm_state(m.group(1)), _norm_state(m.group(2)), (m.group(3) or "").strip()
            sm.transitions.append(Transition(src, dst, label or f"{src}->{dst}"))
            for s in (src, dst):
                if s not in ("[*]", "*") and s not in sm.states:
                    sm.states.append(s)
    srcs = {t.src for t in sm.transitions}
    dsts = {t.dst for t in sm.transitions}
    sm.initial = [t.dst for t in sm.transitions if t.src in ("[*]", "*")] or [s for s in sm.states if s not in dsts]
    sm.terminal = [s for s in sm.states if s not in srcs]
    return sm


def parse_state_machine(spec_md: str) -> StateMachine:
    sm = parse_state_table(spec_md)
    if sm.transitions:
        return sm
    return parse_mermaid_state_diagram(spec_md)


def parse_roles(spec_md: str) -> list[dict[str, str]]:
    """Parse spec §3.5 `| Role | Kind | Views | Allowed Transitions |`."""
    rows = find_table(spec_md, ["role", "kind"])
    out = []
    for r in rows:
        name = strip_md(r.get("role", ""))
        if not name:
            continue
        kind = strip_md(next((v for k, v in r.items() if k.startswith("kind") or "external" in k), "")).lower()
        out.append({
            "role": name,
            "kind": "external" if "external" in kind or "public" in kind else "internal",
            "views": strip_md(next((v for k, v in r.items() if "view" in k), "")),
            "transitions": strip_md(next((v for k, v in r.items() if "transition" in k), "")),
        })
    return out


def parse_business_rules(spec_md: str) -> list[dict[str, str]]:
    """Parse spec §3.4 `| Rule ID | Formula / Rule | Inputs | Source |`."""
    rows = find_table(spec_md, ["rule id", "formula"])
    out = []
    for r in rows:
        rid = strip_md(r.get("rule id", ""))
        if rid:
            out.append({
                "id": rid,
                "rule": next((v for k, v in r.items() if "formula" in k or "rule" == k), ""),
                "inputs": next((v for k, v in r.items() if "input" in k), ""),
                "source": next((v for k, v in r.items() if "source" in k), ""),
            })
    return out


def parse_view_topology(spec_md: str) -> list[dict[str, Any]]:
    """Parse spec §4.2 `| View ID | Navigation Tab / Route | UI Pattern | Bound Role(s) | Primary CTA & Lifecycle Trigger |`."""
    rows = find_table(spec_md, ["view id", "pattern"])
    if not rows:
        rows = find_table(spec_md, ["view id", "navigation"])
    out: list[dict[str, Any]] = []
    for r in rows:
        vid = strip_md(next((v for k, v in r.items() if "view id" in k or k == "view"), ""))
        if not vid:
            continue
        tab_label = strip_md(next((v for k, v in r.items() if "tab" in k or "route" in k or "navigation" in k), ""))
        pattern = strip_md(next((v for k, v in r.items() if "pattern" in k), ""))
        role_cell = next((v for k, v in r.items() if "role" in k), "")
        bound_roles = [strip_md(x) for x in re.split(r"[,/;]| or ", role_cell) if strip_md(x)]
        cta = strip_md(next((v for k, v in r.items() if "cta" in k or "trigger" in k or "action" in k), ""))
        tab_sel = strip_md(next((v for k, v in r.items() if "selector" in k or "testid" in k), ""))
        panel_sel = strip_md(next((v for k, v in r.items() if "panel" in k), ""))
        out.append({
            "viewId": vid,
            "tabLabel": tab_label,
            "uiPattern": pattern,
            "boundRoles": bound_roles,
            "primaryCta": cta,
            "tabSelector": tab_sel,
            "panelSelector": panel_sel,
        })
    return out


def parse_capability_groups(md: str) -> list[dict[str, Any]]:
    """Parse discovery §6.1 `| Group ID | Group Name | Grouping Dimension | Capabilities | Prerequisite Groups / Shared | ... |`."""
    rows = find_table(md, ["group id", "group name"])
    if not rows:
        rows = find_table(md, ["group id", "capabilit"])
    out: list[dict[str, Any]] = []
    for r in rows:
        gid = strip_md(next((v for k, v in r.items() if "group id" in k or k == "group"), ""))
        if not gid:
            continue
        gname = strip_md(next((v for k, v in r.items() if "group name" in k or k == "name"), ""))
        dim_raw = strip_md(next((v for k, v in r.items() if "dimension" in k or "unit" in k or "department" in k), "")).lower()
        if "shared" in dim_raw or "foundation" in dim_raw:
            dim = "shared-foundation"
        elif "unit" in dim_raw or "department" in dim_raw or "dept" in dim_raw:
            dim = "business-unit"
        else:
            dim = "functional"
        cap_cell = next((v for k, v in r.items() if "capabilit" in k), "")
        caps = extract_ids(cap_cell, "CAP-") or [strip_md(x) for x in re.split(r"[,;]", cap_cell) if strip_md(x)]
        prereq_cell = next((v for k, v in r.items() if "prereq" in k or "depend" in k or "shared" in k), "")
        deps = [d.upper() for d in extract_ids(prereq_cell, "GRP-") if d.upper() != gid.upper()]
        is_shared = (
            gid.upper() in ("SHARED", "GRP-SHARED")
            or dim == "shared-foundation"
            or bool(re.search(r"\bshared\b|\bfoundation\b|\bpre-?req(?:uisite)?\s+for\s+all\b", prereq_cell, re.IGNORECASE))
        )
        out.append({
            "id": gid.upper(),
            "name": gname,
            "dimension": dim,
            "capabilities": caps,
            "isSharedFoundation": is_shared,
            "dependsOnGroups": deps,
        })
    return out


def capability_group_definitions(root: Path) -> dict[str, dict[str, Any]]:
    """Return a map `group_id -> group_dict` merged from `specs/discovery_architecture_and_inventory.md` §6.1 and `specs/target_stack.json#capabilityGroups`."""
    defs: dict[str, dict[str, Any]] = {}
    disc_p = root / "specs" / "discovery_architecture_and_inventory.md"
    if disc_p.is_file():
        for g in parse_capability_groups(read_text(disc_p)):
            defs[g["id"].upper()] = dict(g)
    stack_p = root / "specs" / "target_stack.json"
    if stack_p.is_file():
        stack = read_json(stack_p)
        if isinstance(stack, dict):
            for g in stack.get("capabilityGroups") or []:
                if isinstance(g, dict) and g.get("id"):
                    gid = str(g["id"]).strip().upper()
                    merged = dict(defs.get(gid, {}))
                    merged.update(g)
                    merged["id"] = gid
                    merged["dependsOnGroups"] = [str(d).strip().upper() for d in (merged.get("dependsOnGroups") or []) if str(d).strip()]
                    merged["isSharedFoundation"] = bool(merged.get("isSharedFoundation", False))
                    defs[gid] = merged
    return defs


def resolve_group_closure(root: Path, requested_groups: Iterable[str]) -> tuple[set[str], list[str]]:
    """Expand `requested_groups` with any `isSharedFoundation` groups and transitive `dependsOnGroups` prerequisites.
    Returns `(effective_set, topologically_ordered_list_prereqs_first)`.
    """
    defs = capability_group_definitions(root)
    req = {str(g).strip().upper() for g in requested_groups if str(g).strip()}
    effective: set[str] = set(req)
    # Automatically include any group marked isSharedFoundation
    for gid, g in defs.items():
        if g.get("isSharedFoundation"):
            effective.add(gid)
    # Transitive closure of dependsOnGroups
    queue = list(effective)
    while queue:
        cur = queue.pop(0)
        for dep in (defs.get(cur) or {}).get("dependsOnGroups") or []:
            dep_u = str(dep).strip().upper()
            if dep_u and dep_u not in effective:
                effective.add(dep_u)
                queue.append(dep_u)

    # Topological sort so shared foundation & prerequisite groups always come first (Group 1 / Sprint 1)
    visited: set[str] = set()
    ordered: list[str] = []

    def visit(gid: str) -> None:
        if gid in visited:
            return
        visited.add(gid)
        for dep in (defs.get(gid) or {}).get("dependsOnGroups") or []:
            dep_u = str(dep).strip().upper()
            if dep_u in effective:
                visit(dep_u)
        ordered.append(gid)

    # Visit shared foundation groups first, then remaining in sorted order
    for gid in sorted(effective, key=lambda x: (0 if (defs.get(x) or {}).get("isSharedFoundation") else 1, x)):
        visit(gid)
    return effective, ordered


def active_capability_groups(root: Path) -> tuple[bool, set[str]]:
    """Return `(is_all_groups, effective_selected_group_ids_including_prereqs_and_shared)` from `specs/target_stack.json#selectedCapabilityGroups`.
    Defaults to `(True, set())` when `selectedCapabilityGroups` is absent, empty, or contains `'ALL'` / `'*'`.
    """
    stack_p = root / "specs" / "target_stack.json"
    if not stack_p.is_file():
        return True, set()
    stack = read_json(stack_p)
    raw = stack.get("selectedCapabilityGroups") if isinstance(stack, dict) else None
    if not raw or not isinstance(raw, list):
        return True, set()
    norm = {str(x).strip().upper() for x in raw if str(x).strip()}
    if not norm or "ALL" in norm or "*" in norm:
        return True, set()
    effective, _ = resolve_group_closure(root, norm)
    return False, effective


def is_story_in_selected_group(story: dict[str, Any], is_all: bool, selected_groups: set[str]) -> bool:
    """True when `is_all` is True, or the story is a shared/technical enabler, or its `capabilityGroup` is in `selected_groups`."""
    if is_all:
        return True
    cg = str(story.get("capabilityGroup") or "").strip().upper()
    stype = str(story.get("type") or "").strip().lower()
    sid = str(story.get("id") or "").strip().upper()
    if cg == "SHARED" or stype == "technical" or sid.startswith("US-TECH"):
        return True
    if cg:
        return cg in selected_groups
    sprint = str(story.get("sprint") or "").strip().lower()
    return bool(sprint) and not (sprint == "backlog" or sprint.startswith("product backlog"))


# --------------------------------------------------------------------------------------
# Acceptance criteria normalisation
# --------------------------------------------------------------------------------------
AC_TAG_RE = re.compile(r"^\s*\[([^\]]+)\]\s*(.*)$", re.DOTALL)
GWT_RE = re.compile(r"GIVEN\s+(.*?)\s+WHEN\s+(.*?)\s+THEN\s+(.*)$", re.IGNORECASE | re.DOTALL)


def normalise_ac(ac: Any, index: int) -> dict[str, str]:
    """Accept both the v3 string form and the v4 object form; return the v4 object form."""
    if isinstance(ac, dict):
        return {
            "id": ac.get("id") or f"AC-{index + 1:02d}",
            "tag": (ac.get("tag") or "POSITIVE").upper(),
            "given": ac.get("given", ""),
            "when": ac.get("when", ""),
            "then": ac.get("then", ""),
        }
    text = str(ac)
    tag = "POSITIVE"
    m = AC_TAG_RE.match(text)
    if m:
        tag, text = m.group(1).upper(), m.group(2)
    g = GWT_RE.search(text)
    given, when, then = (g.group(1), g.group(2), g.group(3)) if g else ("", "", text)
    return {"id": f"AC-{index + 1:02d}", "tag": tag.strip(), "given": given.strip(), "when": when.strip(), "then": then.strip()}


def ac_category(tag: str) -> str:
    t = tag.upper()
    if "EDGE" in t or "BOUNDARY" in t:
        return "Edge"
    if "ROLE VISIBILITY" in t or "PREREQUISITE" in t or "STATE" in t:
        return "State"
    if "INTERACTIVE" in t:
        return "Interact"
    if "NEGATIVE" in t:
        return "Negative"
    return "Positive"


ALM_RUNTIME_STORY_KEYS = {
    "status", "statusReason", "statusUpdatedAtUtc", "jiraKey", "adoWorkItemId", "lastSyncedAtUtc", "traceability",
}


def stories_content_sha256(p: Path) -> str:
    """SHA-256 of user_stories.json ignoring mutable ALM runtime fields (status, jiraKey, adoWorkItemId)."""
    data = read_json(p)
    if isinstance(data, dict) and isinstance(data.get("stories"), list):
        cleaned = dict(data)
        cleaned["stories"] = [
            {k: v for k, v in s.items() if k not in ALM_RUNTIME_STORY_KEYS}
            if isinstance(s, dict) else s
            for s in data["stories"]
        ]
        return sha256_bytes(json.dumps(cleaned, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return sha256_file(p)


def load_stories(root: Path) -> list[dict[str, Any]]:
    p = require_file(root / "backlog" / "user_stories.json", "Stage 3 (03-story-and-sprint-planner / sprint-planner-agent)")
    data = read_json(p)
    stories = data.get("stories", data) if isinstance(data, dict) else data
    if not isinstance(stories, list) or not stories:
        raise GateFailure(f"{p} contains no stories.")
    for s in stories:
        s["acceptanceCriteria"] = [normalise_ac(a, i) for i, a in enumerate(s.get("acceptanceCriteria", []))]
    return stories


def load_inventory(root: Path) -> dict[str, Any]:
    return read_json(require_file(root / "specs" / "input_inventory.json", "Stage 1 (01/scripts/scan_input_sources.py)"))


def load_spec(root: Path) -> str:
    return read_text(require_file(root / "specs" / "application_spec.md", "Stage 2 (02-spec-architect-and-judge / discovery-architect)"))


def load_target_stack(root: Path, allow_default: bool = True) -> dict[str, Any]:
    p = root / "specs" / "target_stack.json"
    if p.exists():
        return read_json(p)
    if not allow_default:
        raise GateFailure(f"{p} missing — Gate 1 / Stage 4A must record the target stack (see docs/ARCHITECTURE.md §4.2).")
    warn("specs/target_stack.json missing — Future-State technology stack is 'tbd' (pending-stage-4a); Stage 4A must ask the human to select the target technology stack.")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "frontend": {"kind": "tbd"},
        "backend": {"kind": "tbd"},
        "database": {"kind": "tbd"},
        "almPlatform": "none",
        "accessibilityStandard": ["WCAG 2.1 AA"],
        "regulations": [],
        "commands": {},
        "decidedBy": "pending-stage-4a",
    }


# --------------------------------------------------------------------------------------
# Visible-text extraction from HTML (stdlib only)
# --------------------------------------------------------------------------------------
def html_visible_text(html: str) -> str:
    from html.parser import HTMLParser

    class _P(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.skip = 0
            self.parts: list[str] = []

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style", "template", "noscript"):
                self.skip += 1
            for k, v in attrs:
                if k in ("title", "alt", "aria-label", "placeholder") and v:
                    self.parts.append(v)

        def handle_endtag(self, tag):
            if tag in ("script", "style", "template", "noscript") and self.skip:
                self.skip -= 1

        def handle_data(self, data):
            if not self.skip and data.strip():
                self.parts.append(data.strip())

    p = _P()
    p.feed(html)
    return "\n".join(p.parts)


# --------------------------------------------------------------------------------------
# Machine-Enforced Human Gate Ledger (specs/gate_approvals.json)
# --------------------------------------------------------------------------------------
GATE_DEFINITIONS: dict[str, str] = {
    "gate_0_setup": "Gate 0 — Stage 0 Setup, Connection & ADO/Jira Project Selection",
    "gate_1_discovery": "Gate 1 — Stage 1 Current-State ('As-Is') Discovery & Capability Group Selection",
    "gate_2_spec": "Gate 2 — Stage 2 5-Pillar Specification & Spec Judge Scorecard Review",
    "gate_3_backlog": "Gate 3 — Stage 3 User Stories, Sprint Plan & ALM Board Staging Approval",
    "gate_4_design_and_tests": "Gate 4A/4B — Stage 4 Target Tech Stack, 7-Perspective Architecture Suite & Test Plan Review",
    "gate_5_build": "Gate 5 — Stage 5 Runnable Target-Stack Application Build Review",
    "gate_6_eval": "Gate 6 — Stage 6 Closed-Loop Evaluation & Remediation/Guardrail Audit Approval",
    "gate_7_packaging": "Gate 7 — Stage 7 Cloud-Agnostic OCI Containers & GDC Multi-Cloud Packaging Approval",
}


def is_autonomous_or_golden(root: Path, deterministic: bool = False) -> bool:
    """Return True only for explicit --autonomous runs, deterministic CI verification, or repo examples/."""
    if os.environ.get("DLC_AUTONOMOUS", "").strip() in ("1", "true", "TRUE", "yes"):
        return True
    if deterministic:
        return True
    try:
        parts = root.resolve().parts
        if "examples" in parts:
            return True
    except OSError:
        pass
    return False


def gate_approvals_path(root: Path) -> Path:
    return root / "specs" / "gate_approvals.json"


def load_gate_approvals(root: Path) -> dict[str, Any]:
    p = gate_approvals_path(root)
    if p.exists():
        data = read_json(p)
        if isinstance(data, dict) and isinstance(data.get("gates"), dict):
            return data
    return {"schemaVersion": SCHEMA_VERSION, "gates": {}}


def mark_gate_awaiting_human(
    root: Path,
    gate_id: str,
    summary: str = "",
    deterministic: bool = False,
    force_reset: bool = False,
) -> None:
    """Stamp `gate_id` as AWAITING_HUMAN_REVIEW in `specs/gate_approvals.json` and print a mandatory STOP notice."""
    if is_autonomous_or_golden(root, deterministic=deterministic):
        return
    import time as _time

    data = load_gate_approvals(root)
    gates = data.setdefault("gates", {})
    existing = gates.get(gate_id) if isinstance(gates.get(gate_id), dict) else {}
    if existing.get("status") == "APPROVED_BY_USER" and not force_reset:
        # Preserve an already-granted human approval during subsequent validation re-runs (e.g. Stage 6 healing).
        return
    label = GATE_DEFINITIONS.get(gate_id, gate_id)
    now_iso = utc_now_iso(False)
    gates[gate_id] = {
        "gateId": gate_id,
        "stage": label,
        "status": "AWAITING_HUMAN_REVIEW",
        "readyAtUtc": now_iso,
        "readyAtEpoch": round(_time.time(), 3),
        "approvedAtUtc": None,
        "userResponse": None,
        "summary": summary or f"{label} artifacts validated and ready for human review.",
    }
    write_json(gate_approvals_path(root), data)
    tracker_cmd = (
        f'python3 "{PLUGIN_ROOT / "scripts" / "gate_tracker.py"}" '
        f'--project-root "{root}" --action approve --gate {gate_id} '
        f'--user-response "<verbatim quote from user approval reply>"'
    )
    print(
        f"\n{'=' * 78}\n"
        f"[STOP — HUMAN APPROVAL REQUIRED AT {gate_id.upper()}]\n"
        f"  Gate   : {label}\n"
        f"  Status : AWAITING_HUMAN_REVIEW\n"
        f"  Action : 1) Present this stage's deliverables and open questions to the user.\n"
        f"           2) END YOUR TURN NOW (call no more tools) and wait for the user's reply.\n"
        f"           3) NEVER self-approve or start the next stage in the same turn!\n"
        f"           4) Only AFTER the human replies approving this gate in a subsequent turn, run:\n"
        f"              {tracker_cmd}\n"
        f"{'=' * 78}"
    )


def require_gate_approved(
    root: Path,
    upstream_gate_id: str,
    current_stage_name: str,
    deterministic: bool = False,
) -> None:
    """Enforce that `upstream_gate_id` was explicitly approved by the human before `current_stage_name` executes.

    Blocks progression whenever `specs/gate_approvals.json` exists and `upstream_gate_id` is not `APPROVED_BY_USER`
    (or `PRE_APPROVED_AUTONOMOUS`).
    """
    if is_autonomous_or_golden(root, deterministic=deterministic):
        return
    p = gate_approvals_path(root)
    if not p.exists():
        return
    data = load_gate_approvals(root)
    entry = (data.get("gates") or {}).get(upstream_gate_id)
    status = entry.get("status") if isinstance(entry, dict) else "NOT_STARTED"
    if status in ("APPROVED_BY_USER", "PRE_APPROVED_AUTONOMOUS"):
        return
    label = GATE_DEFINITIONS.get(upstream_gate_id, upstream_gate_id)
    tracker_cmd = (
        f'python3 "{PLUGIN_ROOT / "scripts" / "gate_tracker.py"}" '
        f'--project-root "{root}" --action approve --gate {upstream_gate_id} '
        f'--user-response "<verbatim quote from user approval reply>"'
    )
    raise GateFailure(
        f"Cannot start {current_stage_name} because {label} ({upstream_gate_id}) is '{status}' (not 'APPROVED_BY_USER').\n"
        f"  MANDATORY RULE: Every stage requires explicit human review and approval before advancing to the next stage.\n"
        f"  1. Present the upstream stage deliverables and questions to the user in chat.\n"
        f"  2. END YOUR TURN immediately and wait for the human to review and approve.\n"
        f"  3. Once the human replies approving {upstream_gate_id}, record their approval with:\n"
        f"     {tracker_cmd}"
    )
