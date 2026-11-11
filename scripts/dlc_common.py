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
import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "4.0"
# Exact plugin directory name only (`agentic-dlc`, `agentic-dlc-v4`, …) — a project called `agentic-dlc-demo-app`
# or `my-agentic-dlc-project` is a legitimate <PROJECT_ROOT>. Checkouts under any other name are still recognised
# by their plugin layout (`plugin.json` + `skills/`), see `is_installer_dir`.
INSTALLER_DIR_PATTERN = re.compile(r"^agentic-dlc(-v\d+)?$", re.IGNORECASE)
PLUGIN_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------------------
# Exit / logging helpers
# --------------------------------------------------------------------------------------
class GateFailure(SystemExit):
    """Raised to stop a stage with a non-zero exit code and a human-readable reason.

    The message is printed to stderr at construction time so that every skill script's bare
    `raise dlc.GateFailure(...)` reports the reason without needing a top-level handler. Helpers that
    *catch* GateFailure (e.g. to probe an optional artefact) must therefore check `path.exists()` first
    and let invalid JSON / schema errors propagate instead of swallowing them silently.
    """

    def __init__(self, message: str, code: int = 1):
        self.message = message
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
    """True for the plugin/installer directory itself: an exact `agentic-dlc[-vN]` name, or any directory that
    carries the plugin layout (`plugin.json` + `skills/`)."""
    if INSTALLER_DIR_PATTERN.match(p.name):
        return True
    try:
        return (p / "plugin.json").is_file() and (p / "skills").is_dir()
    except OSError:
        return False


def resolve_project_root(explicit: str | None = None) -> Path:
    """Resolve <PROJECT_ROOT> per _shared/project_root.md. Never returns the installer dir.

    An explicit `--project-root` is authoritative: it must be an existing directory, otherwise the gate fails
    (it never silently falls through to `project_root.txt` or the cwd).
    """
    candidates: list[Path] = []
    if explicit:
        ex = Path(explicit).expanduser()
        if is_installer_dir(ex):
            raise GateFailure(f"--project-root {ex} is the plugin/installer directory — never a <PROJECT_ROOT> (see _shared/project_root.md).")
        try:
            ex = ex.resolve()
        except OSError as e:
            raise GateFailure(f"--project-root {explicit} cannot be resolved: {e}")
        if not ex.is_dir():
            raise GateFailure(f"--project-root {explicit} is not an existing directory. Create it (bootstrap.sh --project-root <dir>) or fix the path.")
        if is_installer_dir(ex):
            raise GateFailure(f"--project-root {ex} is the plugin/installer directory — never a <PROJECT_ROOT> (see _shared/project_root.md).")
        return ex
    cfg = Path.home() / ".gemini" / "config" / "project_root.txt"
    if cfg.exists():
        txt = cfg.read_text(encoding="utf-8-sig").strip()
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


def project_path(root: Path, rel: str | Path, allow_outside: bool = False) -> Path:
    """Resolve `rel` against `root` and enforce containment.

    Relative paths (the defaults of every `--output`/`--file` flag) resolve under `root`. Absolute paths are
    accepted only when they resolve inside `root`; anything that escapes the project root (`../`, symlinks,
    absolute paths elsewhere) raises GateFailure unless `allow_outside=True` is passed explicitly.
    """
    p = Path(rel).expanduser()
    candidate = p if p.is_absolute() else root / p
    if allow_outside:
        return candidate
    try:
        root_r = Path(root).resolve()
        # resolve(strict=False) follows existing symlink components so a link out of the root is caught
        cand_r = candidate.resolve()
    except OSError as e:
        raise GateFailure(f"Cannot resolve path {candidate}: {e}")
    if cand_r != root_r and not cand_r.is_relative_to(root_r):
        raise GateFailure(f"Path {candidate} resolves outside <PROJECT_ROOT> {root_r}; scripts only read/write inside the project root.")
    return candidate


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


def _atomic_write_text(p: Path, text: str) -> None:
    """Write `text` to `p` atomically: temp file in the same directory, fsync, then os.replace."""
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp", dir=str(p.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        if p.exists():
            try:
                shutil.copymode(p, tmp)
            except OSError:
                pass
        os.replace(tmp, p)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def write_json(p: Path, data: Any) -> None:
    _atomic_write_text(p, json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n")


def write_text(p: Path, text: str) -> None:
    _atomic_write_text(p, text)


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


_REF_UNRESOLVED = object()


def _resolve_ref(ref: str, root: dict[str, Any]) -> dict[str, Any] | object:
    """Resolve a local JSON-pointer `#/…` reference. Returns `_REF_UNRESOLVED` (never `{}`) when the
    reference is external or does not point at an object, so a broken $ref is reported instead of silently
    accepting any value."""
    if not ref.startswith("#/"):
        return _REF_UNRESOLVED
    node: Any = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return _REF_UNRESOLVED
        node = node[part]
    return node if isinstance(node, dict) else _REF_UNRESOLVED


# Validation keywords this subset validator implements.
_SUPPORTED_KEYWORDS = {
    "type", "enum", "const", "required", "properties", "additionalProperties", "items", "minItems", "maxItems",
    "minLength", "pattern", "minimum", "maximum", "anyOf", "oneOf", "allOf", "$ref",
}
# Annotation / structural keywords that carry no validation semantics and are safe to ignore.
_IGNORED_KEYWORDS = {
    "$schema", "$id", "$defs", "definitions", "$comment", "title", "description", "default", "examples",
    "deprecated", "readOnly", "writeOnly", "$anchor", "$vocabulary", "$dynamicAnchor",
}
# Standard JSON-Schema validation keywords that are NOT implemented: a schema using one would silently
# accept invalid data, so their presence is reported as an error.
_UNSUPPORTED_KEYWORDS = {
    "maxLength", "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "uniqueItems", "contains", "minContains",
    "maxContains", "prefixItems", "unevaluatedItems", "minProperties", "maxProperties", "patternProperties",
    "propertyNames", "dependentRequired", "dependentSchemas", "unevaluatedProperties", "not", "if", "then",
    "else", "format", "$dynamicRef", "additionalItems", "dependencies", "contentMediaType", "contentEncoding",
}


def validate_against_schema(data: Any, schema: dict[str, Any], root: dict[str, Any] | None = None, path: str = "$") -> list[str]:
    """Return a list of '<json-path>: <problem>' strings (empty == valid).

    Supports: type, enum, const, required, properties, additionalProperties, items, minItems, maxItems,
    minLength, pattern, minimum, maximum, anyOf, oneOf, allOf, $ref (local '#/…' only).
    An unresolved `$ref` or an unsupported JSON-Schema validation keyword in the schema is reported as an
    error (the validator never degrades to "accept anything").
    """
    root = root if root is not None else schema
    errs: list[str] = []
    if "$ref" in schema:
        target = _resolve_ref(schema["$ref"], root)
        if target is _REF_UNRESOLVED:
            errs.append(f"{path}: schema error — unresolved $ref {schema['$ref']!r}")
            return errs
        schema = {**target, **{k: v for k, v in schema.items() if k != "$ref"}}  # type: ignore[dict-item]
    unsupported = sorted(k for k in schema if k in _UNSUPPORTED_KEYWORDS)
    if unsupported:
        errs.append(f"{path}: schema error — unsupported JSON-Schema keyword(s) {unsupported} (validator subset: {sorted(_SUPPORTED_KEYWORDS)})")
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


_SEP_CELL_RE = re.compile(r"^\s*:?-+:?\s*$")


def _split_table_row(line: str) -> list[str]:
    """Split a pipe-table row into cells, honouring escaped `\\|` (kept as a literal `|` in the cell)."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells = re.split(r"(?<!\\)\|", s)
    return [c.replace("\\|", "|").strip() for c in cells]


def _is_separator_row(line: str, n_headers: int) -> bool:
    cells = _split_table_row(line)
    if not cells or not all(_SEP_CELL_RE.match(c) for c in cells):
        return False
    # GFM requires the delimiter row to have the same number of cells as the header row; tolerate a
    # trailing empty cell produced by stray whitespace / pipes but not a different column count.
    return len(cells) == n_headers


def md_tables(md: str) -> list[list[dict[str, str]]]:
    """Parse all GitHub-style pipe tables into lists of row dicts keyed by normalised header.

    Escaped pipes (`\\|`) inside cells are not treated as column separators. Rows with fewer cells than headers
    are padded with ''; rows with *more* cells than headers keep the surplus by joining it into the last
    column (`a | b`) instead of silently dropping it.
    """
    tables: list[list[dict[str, str]]] = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("|") and i + 1 < len(lines):
            headers = [h.strip().strip("*`").lower() for h in _split_table_row(lines[i])]
            if headers and _is_separator_row(lines[i + 1], len(headers)):
                rows = []
                i += 2
                while i < len(lines) and lines[i].strip().startswith("|"):
                    cells = _split_table_row(lines[i])
                    if len(cells) > len(headers):
                        cells = cells[:len(headers) - 1] + [" | ".join(c for c in cells[len(headers) - 1:])]
                    row = {headers[k]: (cells[k] if k < len(cells) else "") for k in range(len(headers))}
                    rows.append(row)
                    i += 1
                tables.append(rows)
                continue
        i += 1
    return tables


def _norm_header(h: str) -> str:
    """Normalise a header cell / needle for matching: lowercase, markdown emphasis and punctuation → spaces."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", h.lower())).strip()


def _header_matches(needle: str, header: str, mode: str) -> bool:
    n, h = _norm_header(needle), _norm_header(header)
    if not n:
        return False
    if mode == "exact":
        return n == h
    if mode == "word":
        return re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", h) is not None
    # "prefix": needle starts at a word boundary and may be a prefix of the last word (e.g. "capabilit")
    return re.search(rf"(?<![a-z0-9]){re.escape(n)}", h) is not None


def find_table(md: str, required_headers: Iterable[str], section_regex: str | None = None) -> list[dict[str, str]]:
    """Return the first table whose headers match every needle in `required_headers` and that has ≥ 1 data row.

    Matching is header-aware, not substring-based: needles are compared against each header cell (lower-cased,
    stripped of markdown emphasis and punctuation) in three passes of decreasing strictness — exact header
    equality, whole-word match (so `to` never matches `actor` and `from` never matches `derived from` when an
    exact `From` column exists), then word-prefix match (kept for legacy needles such as `capabilit`). When
    `section_regex` is given, tables inside `md_section(md, section_regex)` are tried first, then the whole
    document.
    """
    req = [h for h in required_headers if str(h).strip()]
    if not req:
        return []
    scopes: list[list[list[dict[str, str]]]] = []
    if section_regex:
        sec = md_section(md, section_regex)
        if sec:
            scopes.append(md_tables(sec))
    scopes.append(md_tables(md))
    for mode in ("exact", "word", "prefix"):
        for tables in scopes:
            for t in tables:
                if not t:
                    continue
                headers = list(t[0].keys())
                if all(any(_header_matches(r, h, mode) for h in headers) for r in req):
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
# Heading regexes used to prefer the canonical section's table before falling back to the whole document.
STATE_SECTION_RE = r"(^|\s)3\.3\b|lifecycle\s+state\s+machine|state\s+machine|state\s+transitions?"
RULES_SECTION_RE = r"(^|\s)3\.4\b|business\s+rules"
ROLES_SECTION_RE = r"(^|\s)3\.5\b|^roles?\b|\broles?\s*(&|and)?\s*(permissions|kinds?)?\s*(\*|$)"
VIEWS_SECTION_RE = r"(^|\s)4\.2\b|view\s*(&|and)?\s*(component\s+)?topology"
GROUPS_SECTION_RE = r"(^|\s)6\.1\b|capability\s+group"


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
    rows = find_table(md, ["from", "to", "trigger"], section_regex=STATE_SECTION_RE)
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
    rows = find_table(spec_md, ["role", "kind"], section_regex=ROLES_SECTION_RE)
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


def parse_br_examples(raw_examples: str) -> list[dict[str, str]]:
    """Parse optional structured decision-table / example vectors from a Spec §3.4 cell.

    Supports semicolon- or pipe-delimited pairs such as:
      `amount=100 -> fee=105; amount=0 -> REJECT`
      `days=3, balance=5 => APPROVED`
    Returns a list of `{"input": "...", "expected": "...", "raw": "..."}` dicts.
    """
    cleaned = strip_md(raw_examples or "").strip()
    if not cleaned or cleaned.lower() in ("—", "-", "n/a", "none"):
        return []
    vectors: list[dict[str, str]] = []
    for chunk in re.split(r"[;\n]+", cleaned):
        part = chunk.strip()
        if not part:
            continue
        m = re.match(r"^(.+?)\s*(?:->|=>|→)\s*(.+)$", part)
        if m:
            inp, exp = m.group(1).strip(), m.group(2).strip()
            if inp and exp:
                vectors.append({"input": inp, "expected": exp, "raw": part})
    return vectors


def parse_business_rules(spec_md: str) -> list[dict[str, Any]]:
    """Parse spec §3.4 `| Rule ID | Formula / Rule | Inputs | Source | [Examples] |`."""
    rows = find_table(spec_md, ["rule id", "formula"], section_regex=RULES_SECTION_RE)
    out: list[dict[str, Any]] = []
    for r in rows:
        rid = strip_md(r.get("rule id", ""))
        if rid:
            ex_raw = next((v for k, v in r.items() if "example" in k or "vector" in k or "decision" in k), "")
            entry: dict[str, Any] = {
                "id": rid,
                "rule": next((v for k, v in r.items() if "formula" in k or "rule" == k), ""),
                "inputs": next((v for k, v in r.items() if "input" in k), ""),
                "source": next((v for k, v in r.items() if "source" in k), ""),
            }
            if ex_raw.strip():
                entry["examples"] = ex_raw.strip()
                parsed_ex = parse_br_examples(ex_raw)
                if parsed_ex:
                    entry["parsedExamples"] = parsed_ex
            out.append(entry)
    return out


def parse_view_topology(spec_md: str) -> list[dict[str, Any]]:
    """Parse spec §4.2 `| View ID | Navigation Tab / Route | UI Pattern | Bound Role(s) | Primary CTA & Lifecycle Trigger |`."""
    rows = find_table(spec_md, ["view id", "pattern"], section_regex=VIEWS_SECTION_RE)
    if not rows:
        rows = find_table(spec_md, ["view id", "navigation"], section_regex=VIEWS_SECTION_RE)
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
    rows = find_table(md, ["group id", "group name"], section_regex=GROUPS_SECTION_RE)
    if not rows:
        rows = find_table(md, ["group id", "capabilit"], section_regex=GROUPS_SECTION_RE)
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
    "status", "statusReason", "statusUpdatedAtUtc", "jiraKey", "adoWorkItemId", "lastSyncedAtUtc",
    "traceability", "specPointer", "compactedContext",
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
# Browser discovery & process-group helpers (shared by Stage 1 capture, Stage 5 build and Stage 6 eval)
# --------------------------------------------------------------------------------------
CHROME_CANDIDATES = [
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge",
    "/opt/google/chrome/chrome", "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
    "/snap/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Chromium\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_chrome_binary(explicit: str | None = None) -> str | None:
    """Return the path of a Chrome/Chromium/Edge executable or None.

    Order: `explicit` → `$CHROME_BIN` → well-known command names (via PATH) and install locations on
    Linux / macOS / Windows. Returns None (never raises) when nothing usable is found.
    """
    cands = ([explicit] if explicit else []) + ([os.environ["CHROME_BIN"]] if os.environ.get("CHROME_BIN") else []) + CHROME_CANDIDATES
    for c in cands:
        c = (c or "").strip()
        if not c:
            continue
        c = os.path.expanduser(c)
        if os.path.sep in c or (os.name == "nt" and ":" in c):
            if Path(c).is_file() and os.access(c, os.X_OK):
                return c
            continue
        w = shutil.which(c)
        if w:
            return w
    return None


def start_process_group(cmd: str | list[str], cwd: Path | str | None = None, env: dict[str, str] | None = None,
                        log_path: Path | str | None = None) -> subprocess.Popen:
    """Start `cmd` as the leader of its own process group / session so the whole tree can be stopped later.

    `cmd` may be a shell string (run with `shell=True`, e.g. the `commands.start` of target_stack.json) or an
    argv list. stdout/stderr go to `log_path` (opened in append mode) or to DEVNULL. On POSIX the child is
    started with `start_new_session=True` (setsid); on Windows with CREATE_NEW_PROCESS_GROUP. The returned
    Popen carries `.log_handle` (or None) which `stop_process_group` closes.
    """
    if log_path is not None:
        lp = Path(log_path)
        lp.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(lp, "ab")
    else:
        log_handle = None
    kwargs: dict[str, Any] = {
        "cwd": str(cwd) if cwd is not None else None,
        "env": env,
        "stdout": log_handle if log_handle is not None else subprocess.DEVNULL,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
        "shell": isinstance(cmd, str),
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(cmd, **kwargs)  # noqa: S603 — command comes from the project's own config
    except BaseException:
        if log_handle is not None:
            log_handle.close()
        raise
    proc.log_handle = log_handle  # type: ignore[attr-defined]
    return proc


def stop_process_group(proc: subprocess.Popen | None, timeout: float = 5.0) -> int | None:
    """Terminate the process group started by `start_process_group`: SIGTERM the group, wait up to `timeout`
    seconds, SIGKILL whatever is left, then `wait()` so no zombie remains. Safe to call twice or with None.
    Returns the process return code (None if `proc` is None)."""
    if proc is None:
        return None
    try:
        if proc.poll() is None:
            if os.name == "nt":
                try:
                    proc.send_signal(getattr(signal, "CTRL_BREAK_EVENT", signal.SIGTERM))
                except (OSError, ValueError):
                    proc.terminate()
            else:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    proc.terminate()
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    proc.kill()
                else:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        proc.kill()
                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    pass
        else:
            proc.wait()
    finally:
        lh = getattr(proc, "log_handle", None)
        if lh is not None:
            try:
                lh.close()
            except OSError:
                pass
    return proc.returncode


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
    "gate_7_drift": "Gate 7 — Stage 7 Pre-Deployment Spec-to-Code Drift & ADR Alignment Approval",
    "gate_8_packaging": "Gate 8 — Stage 8 Cloud-Agnostic OCI Containers & GDC Multi-Cloud Packaging Approval",
    "gate_9_deployment": "Gate 9 — Stage 9 GDC Fleet GitOps Deployment, Observability & SLO Verification Approval",
}

# Gates that autonomous mode may pre-approve without a human (AGENTS.md §3: Gates 1, 3 and 4A are skipped in
# autonomous mode; Gate 0 is the Stage 0 setup gate and is likewise defaulted). Gate 2 (spec judge scorecard)
# and the Stage 6 guardrail approval keep their documented semantics inside their own scripts.
AUTONOMOUS_DEFAULT_GATES: tuple[str, ...] = ("gate_0_setup", "gate_1_discovery", "gate_3_backlog", "gate_4_design_and_tests")

# Ledger statuses (schemas/gate_approvals.schema.json#status enum) & Ceremony Tracks.
CEREMONY_TRACKS: tuple[str, ...] = ("quick", "standard", "regulated")
QUICK_TRACK_AUTO_SKIP_GATES: frozenset[str] = frozenset({
    "gate_2_spec",
    "gate_3_backlog",
    "gate_5_build",
    "gate_7_drift",
    "gate_8_packaging",
})

GATE_STATUS_PENDING = "PENDING"
GATE_STATUS_AWAITING = "AWAITING_HUMAN_REVIEW"
GATE_STATUS_APPROVED = "APPROVED_BY_USER"
GATE_STATUS_PRE_APPROVED = "PRE_APPROVED_AUTONOMOUS"
GATE_STATUS_AUTONOMOUS_DEFAULT = "AUTONOMOUS_DEFAULT"
GATE_STATUS_AUTO_SKIPPED_TRACK = "AUTO_SKIPPED_BY_CEREMONY_TRACK"
GATE_APPROVED_STATUSES: frozenset[str] = frozenset({
    GATE_STATUS_APPROVED,
    GATE_STATUS_PRE_APPROVED,
    GATE_STATUS_AUTONOMOUS_DEFAULT,
    GATE_STATUS_AUTO_SKIPPED_TRACK,
})

_TRUE_VALUES = ("1", "true", "yes", "on")


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUE_VALUES


def is_autonomous_mode() -> bool:
    """True only when the pipeline/user explicitly requested autonomous mode (`DLC_AUTONOMOUS=1`, set by
    `run_agentic_dlc_pipeline.py --autonomous`)."""
    return _env_flag("DLC_AUTONOMOUS")


def is_golden_run() -> bool:
    """True only inside `scripts/verify_golden_projects.py` (it exports `DLC_GOLDEN_RUN=1` for the child pipeline)."""
    return _env_flag("DLC_GOLDEN_RUN")


def is_autonomous_or_golden(root: Path | None = None, deterministic: bool = False) -> bool:
    """Return True only when human gates may be bypassed: explicit autonomous mode (`DLC_AUTONOMOUS=1`) or a golden
    project verification run (`DLC_GOLDEN_RUN=1`).

    A plain `--deterministic` flag never bypasses gates (it only freezes timestamps), and the location of the
    project root (e.g. a path containing `examples/`) is irrelevant. `root` / `deterministic` are accepted for
    call-site compatibility only.
    """
    del root, deterministic
    return is_autonomous_mode() or is_golden_run()


def gate_approvals_path(root: Path) -> Path:
    return root / "specs" / "gate_approvals.json"


def gate_tracker_command(root: Path, action: str, gate_id: str | None = None, extra: str = "") -> str:
    """Render the `gate_tracker.py` command line to show in STOP notices and GateFailure messages."""
    cmd = f'python3 "{PLUGIN_ROOT / "scripts" / "gate_tracker.py"}" --project-root "{root}" --action {action}'
    if gate_id:
        cmd += f" --gate {gate_id}"
    if extra:
        cmd += f" {extra}"
    return cmd


def active_ceremony_track(root: Path) -> str:
    """Return the active ceremony track ('quick' | 'standard' | 'regulated', default 'standard')."""
    gp = gate_approvals_path(root)
    if gp.is_file():
        try:
            gdata = read_json(gp)
            if isinstance(gdata, dict) and gdata.get("ceremonyTrack") in CEREMONY_TRACKS:
                return str(gdata["ceremonyTrack"])
        except Exception:
            pass
    sp = root / "specs" / "project_setup.json"
    if sp.is_file():
        try:
            sdata = read_json(sp)
            if isinstance(sdata, dict) and sdata.get("ceremonyTrack") in CEREMONY_TRACKS:
                return str(sdata["ceremonyTrack"])
        except Exception:
            pass
    return "standard"


def _sanitize_brief_line(line: str) -> str:
    """Ensure generated executive gate briefs never contain internal harness script/skill/subagent tokens."""
    cleaned = DELIVERABLE_INTERNAL_LEAK_RE.sub("[governance-check]", line)
    return cleaned.strip()


def generate_gate_decision_brief(
    root: Path,
    gate_id: str,
    summary: str = "",
    deterministic: bool = False,
) -> str:
    """Generate a concise 1-page Executive Gate Decision Brief at `specs/gate_briefs/<gate_id>.md`."""
    label = GATE_DEFINITIONS.get(gate_id, gate_id)
    track = active_ceremony_track(root)
    now_iso = utc_now_iso(deterministic)
    rel_path = f"specs/gate_briefs/{gate_id}.md"

    wave_line = "All selected capabilities (`ALL`)"
    coex_line = "Clean cutover (`clean-cutover`)"
    ts_path = root / "specs" / "target_stack.json"
    if ts_path.is_file():
        try:
            ts = read_json(ts_path)
            if isinstance(ts, dict):
                grps = ts.get("selectedCapabilityGroups")
                if isinstance(grps, list) and grps:
                    wave_line = ", ".join(f"`{g}`" for g in grps)
                if ts.get("coexistenceStrategy"):
                    coex_line = f"`{ts['coexistenceStrategy']}`"
        except Exception:
            pass

    assumptions: list[str] = []
    divergences: list[str] = []
    spec_path = root / "specs" / "application_spec.md"
    if spec_path.is_file():
        spec_txt = read_text(spec_path)
        for raw_line in spec_txt.splitlines():
            s = raw_line.strip()
            if re.search(r"\bASSUMPTION-[0-9]+\b", s):
                assumptions.append(_sanitize_brief_line(s.lstrip("-*|> ")))
            if re.search(r"\bREQ-ENH-[0-9]+\b", s):
                divergences.append(_sanitize_brief_line(s.lstrip("-*|> ")))

    arch_section: list[str] = []
    arch_sc_path = root / "design" / "architecture_eval_scorecard.json"
    if arch_sc_path.is_file():
        try:
            asc = read_json(arch_sc_path)
            if isinstance(asc, dict):
                arch_section.append(
                    f"- **Architecture Red-Team Score:** `{asc.get('totalScore', 'N/A')}/100` "
                    f"(Verdict: `{asc.get('verdict', 'UNKNOWN')}`)"
                )
                for bg in (asc.get("blockingGaps") or [])[:5]:
                    arch_section.append(f"- **Blocking Gap:** {_sanitize_brief_line(str(bg))}")
        except Exception:
            pass

    guardrail_section: list[str] = []
    gr_path = root / "test" / ".guardrail_state.json"
    if gr_path.is_file():
        try:
            gr = read_json(gr_path)
            if isinstance(gr, dict):
                pending = gr.get("pendingHunks") or []
                if pending:
                    guardrail_section.append(f"- **Pending Guardrail Diff Hunks Requiring Sign-Off:** `{len(pending)}`")
                    for h in pending[:5]:
                        if isinstance(h, dict):
                            guardrail_section.append(
                                f"  - `{h.get('file', 'file')}`: {_sanitize_brief_line(str(h.get('reason', 'guardrail touch')))}"
                            )
        except Exception:
            pass

    lines = [
        f"# Executive Gate Decision Brief — {_sanitize_brief_line(label)}",
        "",
        f"- **Gate Identifier:** `{gate_id}`",
        f"- **Generated (UTC):** `{now_iso}`",
        f"- **Ceremony Track:** `{track}`",
        f"- **Active Capability Wave:** {wave_line}",
        f"- **Coexistence Strategy:** {coex_line}",
        "",
        "## 1. Stage Validation Summary",
        _sanitize_brief_line(summary or f"{label} deliverables passed automated verification and are ready for review."),
        "",
        "## 2. Open Assumptions & Scope Decisions",
    ]
    if assumptions:
        for item in dict.fromkeys(assumptions):
            lines.append(f"- {item[:220]}")
    else:
        lines.append("- None recorded in current specification.")

    lines.extend(["", "## 3. Documented Modernization Enhancements & Intentional Divergences"])
    if divergences:
        for item in dict.fromkeys(divergences):
            lines.append(f"- {item[:220]}")
    else:
        lines.append("- None recorded (strict parity or greenfield specification).")

    clar_path = root / "specs" / "clarification_decisions.json"
    if clar_path.is_file():
        try:
            clar = read_json(clar_path)
            if isinstance(clar, dict):
                c_status = clar.get("clarificationStatus", "UNKNOWN")
                decs = clar.get("decisions") or []
                disps = clar.get("capabilityDispositions") or []
                open_f = clar.get("openFrontier") or []
                lines.extend([
                    "",
                    "## 3b. Clarification & Modernization Ambition Decisions",
                    f"- **Clarification Status:** `{c_status}` (Decisions: `{len(decs)}`, Open Frontier: `{len(open_f)}`)",
                ])
                for disp in disps[:6]:
                    if isinstance(disp, dict):
                        lines.append(
                            f"- **Disposition `{disp.get('targetId', '')}` → `{disp.get('disposition', '')}`:** "
                            f"{_sanitize_brief_line(str(disp.get('rationale', '')))[:180]}"
                        )
                for d in decs[:6]:
                    if isinstance(d, dict):
                        lines.append(
                            f"- **`{d.get('id', '')}` (`{d.get('category', '')}`):** "
                            f"{_sanitize_brief_line(str(d.get('resolvedAnswer', '')))[:180]}"
                        )
        except Exception:
            pass

    if arch_section:
        lines.extend(["", "## 4. Architecture Red-Team Review Highlights", *arch_section])

    if guardrail_section:
        lines.extend(["", "## 5. Guardrail-Sensitive Remediation Hunks", *guardrail_section])

    drift_path = root / "test" / "drift_report.json"
    if drift_path.is_file():
        try:
            dr = read_json(drift_path)
            if isinstance(dr, dict):
                ds = dr.get("summary") or {}
                lines.extend([
                    "",
                    "## 6. Pre-Deployment Spec-to-Code Alignment",
                    f"- **Drift Verdict:** `{dr.get('verdict', 'UNKNOWN')}` "
                    f"(Errors: `{ds.get('errors', 0)}`, Warnings: `{ds.get('warnings', 0)}`, "
                    f"Recorded ADRs: `{ds.get('adrsRecorded', 0)}`)",
                ])
        except Exception:
            pass

    spec_sha_short = "—"
    spec_score_str = "—"
    if spec_path.is_file():
        spec_sha_short = sha256_file(spec_path)[:12]
    sc_path = root / "specs" / "application_eval_scorecard.json"
    if sc_path.is_file():
        try:
            sc_obj = read_json(sc_path)
            if isinstance(sc_obj, dict) and sc_obj.get("totalScore") is not None:
                spec_score_str = f"{sc_obj.get('totalScore')}/100 ({sc_obj.get('verdict', 'PASS')})"
        except Exception:
            pass

    start_cmd_str = "bash src/run.sh"
    health_url_str = "http://127.0.0.1:8080/health"
    alm_mode_str = "none"
    if ts_path.is_file():
        try:
            ts_obj = read_json(ts_path)
            if isinstance(ts_obj, dict):
                cmds_obj = ts_obj.get("commands") or {}
                if cmds_obj.get("start"):
                    start_cmd_str = _sanitize_brief_line(str(cmds_obj["start"]))
                if cmds_obj.get("healthcheck"):
                    health_url_str = _sanitize_brief_line(str(cmds_obj["healthcheck"]))
                alm_mode_str = str(ts_obj.get("almPlatform") or "none")
        except Exception:
            pass

    lines.extend([
        "",
        "## Structured Review & Verification Summary (5 Questions)",
        f"1. **Goal:** Validate and approve `{gate_id}` ({_sanitize_brief_line(label)}) for capability scope {wave_line}.",
        f"2. **Big Picture:** Governs contract-first progression under `{track}` ceremony track with coexistence mode {coex_line}.",
        f"3. **Spec Plan Adherence:** Spec SHA-256 prefix `{spec_sha_short}` | Spec Judge Score: `{spec_score_str}`.",
        "4. **Verifier Focus (4-Part Runnable Check):**",
        "   - **Workspace / Branch:** Project root working tree (`specs/`, `design/`, `src/`, `test/`)",
        f"   - **Execution / Start Command:** `{start_cmd_str}`",
        f"   - **Target Health / UI Surface:** `{health_url_str}`",
        "   - **Expected Outcome:** Zero blocking validation errors, zero internal token leakage, and 100% linked contract alignment.",
        f"5. **Reviewer Focus:** Inspect open assumptions ({len(assumptions)}), guardrail hunks ({len(guardrail_section)}), and "
        + ("sync thin-pointer chained stories on the ALM board." if alm_mode_str in ("ado", "jira") else "record human review sign-off via Pull Request + `* **Approvals:**` ledger."),
        "",
        "## Decision Options",
        "1. **Approve Gate:** Confirm scope, assumptions, and validated deliverables to advance to the next stage.",
        "2. **Request Revisions:** Specify any business rule, role permission, architecture, or UX adjustments needed.",
        "3. **Adjust Capability Wave:** Narrow or expand `selectedCapabilityGroups` before continuing.",
        "",
    ])
    write_text(root / rel_path, "\n".join(lines))
    return rel_path


def new_gate_ledger(autonomous: bool = False, ceremony_track: str = "standard") -> dict[str, Any]:
    """Return a fresh ledger with every gate PENDING (with `autonomous=True`, the Gates that autonomous mode may
    skip — `AUTONOMOUS_DEFAULT_GATES` — are recorded as AUTONOMOUS_DEFAULT instead)."""
    now_iso = utc_now_iso(False)
    track = ceremony_track if ceremony_track in CEREMONY_TRACKS else "standard"
    gates: dict[str, Any] = {}
    for gid, label in GATE_DEFINITIONS.items():
        auto = autonomous and gid in AUTONOMOUS_DEFAULT_GATES
        gates[gid] = {
            "gateId": gid,
            "stage": label,
            "status": GATE_STATUS_AUTONOMOUS_DEFAULT if auto else GATE_STATUS_PENDING,
            "readyAtUtc": None,
            "readyAtEpoch": None,
            "approvedAtUtc": now_iso if auto else None,
            "userResponse": "Autonomous mode (--autonomous / DLC_AUTONOMOUS=1) explicitly requested by the user" if auto else None,
            "summary": f"{label} — {'autonomous default (no human stop)' if auto else 'pending: stage not yet validated'}.",
            "decisionBriefPath": None,
        }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "initializedAtUtc": now_iso,
        "ceremonyTrack": track,
        "gates": gates,
    }


def load_gate_approvals(root: Path) -> dict[str, Any]:
    """Load the ledger. Returns an empty ledger structure when the file does not exist; invalid JSON or a file
    without a `gates` object is a GateFailure (never silently treated as 'no gates')."""
    p = gate_approvals_path(root)
    if not p.exists():
        return {"schemaVersion": SCHEMA_VERSION, "gates": {}}
    data = read_json(p)
    if not isinstance(data, dict) or not isinstance(data.get("gates"), dict):
        raise GateFailure(f"{p} is not a valid gate ledger (expected an object with a 'gates' object). "
                          f"Re-initialise it with: {gate_tracker_command(root, 'init')}")
    return data


def gate_status(root: Path, gate_id: str) -> str:
    """Current ledger status of `gate_id` (`NOT_STARTED` when the ledger or the entry is missing)."""
    p = gate_approvals_path(root)
    if not p.exists():
        return "NOT_STARTED"
    entry = (load_gate_approvals(root).get("gates") or {}).get(gate_id)
    return str(entry.get("status") or "NOT_STARTED") if isinstance(entry, dict) else "NOT_STARTED"


def mark_gate_awaiting_human(
    root: Path,
    gate_id: str,
    summary: str = "",
    deterministic: bool = False,
    force_reset: bool = False,
) -> None:
    """Stamp `gate_id` as AWAITING_HUMAN_REVIEW in `specs/gate_approvals.json`, emit a 1-page Executive Decision Brief,
    and print a mandatory STOP notice (or auto-advance intermediate gates when ceremonyTrack == 'quick').

    No-op in autonomous / golden runs (`is_autonomous_or_golden`). An existing APPROVED_BY_USER entry is preserved
    on re-runs (e.g. Stage 6 healing) unless `force_reset=True`.
    """
    if is_autonomous_or_golden(root, deterministic=deterministic):
        return
    import time as _time

    data = load_gate_approvals(root)
    track = active_ceremony_track(root)
    data.setdefault("ceremonyTrack", track)
    gates = data.setdefault("gates", {})
    existing = gates.get(gate_id) if isinstance(gates.get(gate_id), dict) else {}
    if existing.get("status") == GATE_STATUS_APPROVED and not force_reset:
        return
    if existing.get("status") == GATE_STATUS_AUTO_SKIPPED_TRACK and track == "quick" and not force_reset:
        return

    label = GATE_DEFINITIONS.get(gate_id, gate_id)
    now_iso = utc_now_iso(False)
    brief_rel = generate_gate_decision_brief(root, gate_id, summary=summary, deterministic=deterministic)

    if track == "quick" and gate_id in QUICK_TRACK_AUTO_SKIP_GATES and not force_reset:
        gates[gate_id] = {
            "gateId": gate_id,
            "stage": label,
            "status": GATE_STATUS_AUTO_SKIPPED_TRACK,
            "readyAtUtc": now_iso,
            "readyAtEpoch": round(_time.time(), 3),
            "approvedAtUtc": now_iso,
            "userResponse": "Auto-advanced under 'quick' ceremony track after deterministic gate verification passed.",
            "summary": summary or f"{label} auto-advanced under 'quick' ceremony track.",
            "decisionBriefPath": brief_rel,
        }
        write_json(gate_approvals_path(root), data)
        info(f"ceremonyTrack='quick' auto-advanced {gate_id} (decision brief: {brief_rel})")
        return

    gates[gate_id] = {
        "gateId": gate_id,
        "stage": label,
        "status": GATE_STATUS_AWAITING,
        "readyAtUtc": now_iso,
        "readyAtEpoch": round(_time.time(), 3),
        "approvedAtUtc": None,
        "userResponse": None,
        "summary": summary or f"{label} artifacts validated and ready for human review.",
        "decisionBriefPath": brief_rel,
    }
    write_json(gate_approvals_path(root), data)
    tracker_cmd = gate_tracker_command(root, "approve", gate_id, '--user-response "<verbatim quote from user approval reply>"')
    print(
        f"\n{'=' * 78}\n"
        f"[STOP — HUMAN APPROVAL REQUIRED AT {gate_id.upper()}]\n"
        f"  Gate   : {label}\n"
        f"  Track  : {track}\n"
        f"  Brief  : {root / brief_rel}\n"
        f"  Status : {GATE_STATUS_AWAITING}\n"
        f"  Action : 1) Present the Executive Decision Brief ({brief_rel}), stage deliverables, and open questions to the user.\n"
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

    * A missing `specs/gate_approvals.json` is itself a GateFailure: Stage 0 (skill `00-setup-and-connection` /
      `gate_tracker.py --action init`) must initialise the ledger first.
    * Progression is allowed only when the gate is `APPROVED_BY_USER`, `PRE_APPROVED_AUTONOMOUS` or
      `AUTONOMOUS_DEFAULT`.
    * The only bypasses are explicit autonomous mode (`DLC_AUTONOMOUS=1`) or a golden verification run
      (`DLC_GOLDEN_RUN=1`); `deterministic` and the project location never bypass a gate.
    """
    if is_autonomous_or_golden(root, deterministic=deterministic):
        return
    p = gate_approvals_path(root)
    if not p.exists():
        raise GateFailure(
            f"Cannot start {current_stage_name}: the human gate ledger {p} does not exist.\n"
            f"  Stage 0 (skill 00-setup-and-connection) must run first and initialise the ledger, or run:\n"
            f"     {gate_tracker_command(root, 'init')}\n"
            f"  Only an explicitly requested autonomous run (run_agentic_dlc_pipeline.py --autonomous) may proceed without it."
        )
    status = gate_status(root, upstream_gate_id)
    if status in GATE_APPROVED_STATUSES:
        return
    label = GATE_DEFINITIONS.get(upstream_gate_id, upstream_gate_id)
    tracker_cmd = gate_tracker_command(root, "approve", upstream_gate_id, '--user-response "<verbatim quote from user approval reply>"')
    raise GateFailure(
        f"Cannot start {current_stage_name} because {label} ({upstream_gate_id}) is '{status}' (not '{GATE_STATUS_APPROVED}').\n"
        f"  MANDATORY RULE: Every stage requires explicit human review and approval before advancing to the next stage.\n"
        f"  1. Present the upstream stage deliverables and questions to the user in chat.\n"
        f"  2. END YOUR TURN immediately and wait for the human to review and approve.\n"
        f"  3. Once the human replies approving {upstream_gate_id}, record their approval with:\n"
        f"     {tracker_cmd}"
    )


# --------------------------------------------------------------------------------------
# Scenario label helpers & Deliverable internal-workings leak scanner
# --------------------------------------------------------------------------------------
SCENARIO_LABELS = {
    "SCENARIO_LEGACY_APP": "Legacy Application Modernization",
    "SCENARIO_REQUIREMENTS_DOC": "Greenfield Requirements Specification",
}


def scenario_display_label(scenario_code: str) -> str:
    """Return human-readable project scenario label without internal enum constants."""
    return SCENARIO_LABELS.get(str(scenario_code).strip(), "Greenfield Requirements Specification")


def parse_scenario_label(text: str) -> str | None:
    """Extract canonical scenario enum from a Markdown header line supporting human-readable labels or SCENARIO_*."""
    m = re.search(
        r"\*\*(?:Input\s+Scenario(?:\s+Mode)?|Delivery\s+Scenario|Project\s+Scenario):?\*\*:?\s*`?([^\n`]+)`?",
        text,
        re.IGNORECASE,
    )
    if not m:
        m = re.search(r"Input\s+Scenario[^\n:]*:\s*`?([^\n`]+)`?", text, re.IGNORECASE)
    if not m:
        return None
    val = m.group(1).strip()
    if re.search(r"\bSCENARIO_LEGACY_APP\b", val, re.IGNORECASE):
        return "SCENARIO_LEGACY_APP"
    if re.search(r"\bSCENARIO_REQUIREMENTS_DOC\b", val, re.IGNORECASE):
        return "SCENARIO_REQUIREMENTS_DOC"
    if re.search(r"\blegacy\b", val, re.IGNORECASE):
        return "SCENARIO_LEGACY_APP"
    if re.search(r"\b(?:greenfield|requirements?\s+(?:specification|document))\b", val, re.IGNORECASE):
        return "SCENARIO_REQUIREMENTS_DOC"
    return None


DELIVERABLE_INTERNAL_LEAK_CORE_PATTERNS = [
    r"\b(?:0[0-9]|10)/scripts/[A-Za-z0-9_.-]+",
    r"\bscripts/(?:dlc_common|gate_tracker|lint_domain_neutrality|run_agentic_dlc_pipeline|verify_golden_projects)\.py\b",
    r"\b(?:setup_project_connection|scan_input_sources|capture_design_reference|validate_discovery_blueprint|"
    r"lint_spec_structure|validate_spec_scorecard|alm_jira_ado_bridge|extract_contracts|validate_architecture_scorecard|"
    r"gcp_diagram_renderer|derive_test_cases|validate_test_cases|check_testid_contract|validate_build|run_closed_loop_eval|"
    r"validate_gdc_packaging|run_gdc_fleet_deploy_and_verify|check_spec_code_drift|run_agentic_dlc_pipeline|gate_tracker|"
    r"dlc_common|lint_domain_neutrality|verify_golden_projects)\.py\b",
    r"(?<![A-Za-z0-9_/-])_shared/[A-Za-z0-9_.-]+",
    r"\bskills/[0-9]{2}-[A-Za-z0-9_-]+",
    r"\bresources/reference_[A-Za-z0-9_.-]+",
    r"\bschemas/(?:spec_rubric|architecture_rubric|architecture_scorecard|drift_report|input_inventory|target_stack|user_stories|test_cases|eval_results|deployment_eval_results)[A-Za-z0-9_.-]*\.json\b",
    r"\b(?:doit-agentic-dlc|agentic-dlc)\b",
    r"\b(?:00-setup-and-connection|01-discovery-and-grouping|02-spec-architect-and-judge|03-story-and-sprint-planner|04-solution-architect|05-test-plan-designer|06-coding-agent|07-test-runner-and-healer|08-drift-and-evolution|09-container-and-gdc-packager|10-gdc-fleet-deployer-and-observability|08-container-and-gdc-packager|09-gdc-fleet-deployer-and-observability|10-drift-and-evolution)\b",
    r"\b(?:discovery-architect|spec-judge|sprint-planner-agent|solution-architect|architecture-critic|testing-agent|coding-agent|platform-ops-agent)\b",
    r"\bARCHITECTURE(?:\.md|\s*§\d)",
    r"\bdiagram-dsl\b",
    r"\btest/\.snapshots/",
    r"<summary>\s*Architecture Diagram Specification",
    r"extracted from design/solution_design\.md",
    r"Generated by\s+`?[A-Za-z0-9_./-]+\.py",
    r"parsed by\s+`?[A-Za-z0-9_./-]+\.py",
]

DELIVERABLE_INTERNAL_LEAK_RE = re.compile(
    "(?:"
    + "|".join(
        DELIVERABLE_INTERNAL_LEAK_CORE_PATTERNS
        + [
            r"\bSCENARIO_(?:LEGACY_APP|REQUIREMENTS_DOC)\b",
            r":::(?:capCard|capSpan|gcpCard|focal|gcpBlue|gcpGreen|gcpYellow|gcpRed)\b",
        ]
    )
    + ")",
    re.IGNORECASE,
)

DELIVERABLE_JSON_INTERNAL_LEAK_RE = re.compile(
    "(?:" + "|".join(DELIVERABLE_INTERNAL_LEAK_CORE_PATTERNS) + ")",
    re.IGNORECASE,
)

_DELIVERABLE_TEXT_SUFFIXES = {".md", ".html", ".css", ".js", ".ts", ".tsx", ".jsx", ".sql", ".yaml", ".yml", ".sh", ".csv", ".txt"}
INLINE_DATA_URI_RE = re.compile(r"data:image/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=]+", re.IGNORECASE)


def strip_inline_data_uris(text: str) -> str:
    """Replace inline `data:image/...;base64,...` payloads before prose token regex scans."""
    return INLINE_DATA_URI_RE.sub("data:image/svg+xml;base64,REDACTED", text)


def scan_deliverable_internal_leaks(root: Path, rel_paths: list[str] | None = None) -> list[str]:
    """Scan project deliverables for leaked internal DLC script names, plugin paths, subagent slugs, or raw diagram-dsl scaffolding."""
    candidates: list[Path] = []
    if rel_paths is not None:
        for rp in rel_paths:
            p = project_path(root, rp)
            if p.is_file():
                candidates.append(p)
    else:
        for sub in ("specs", "backlog", "design", "test", "src", "deploy"):
            base = root / sub
            if not base.is_dir():
                continue
            for p in sorted(base.rglob("*")):
                if not p.is_file():
                    continue
                rel_parts = p.relative_to(root).parts
                if any(part.startswith(".") for part in rel_parts):
                    continue
                if "history" in rel_parts and p.suffix.lower() == ".json":
                    continue
                candidates.append(p)

    findings: list[str] = []
    for p in candidates:
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            rel = p.as_posix()
        if any(part.startswith(".") for part in Path(rel).parts):
            continue
        suf = p.suffix.lower()
        if suf in _DELIVERABLE_TEXT_SUFFIXES:
            txt = p.read_text(encoding="utf-8", errors="replace")
            for lineno, raw_line in enumerate(txt.splitlines(), 1):
                line = strip_inline_data_uris(raw_line)
                m = DELIVERABLE_INTERNAL_LEAK_RE.search(line)
                if m:
                    findings.append(
                        f"{rel}:{lineno} exposes internal harness detail '{m.group(0)}' — "
                        f"project deliverables must never contain internal script names, plugin paths, subagent slugs, or scenario enum constants."
                    )
        elif suf == ".json" and Path(rel).name not in ("gate_approvals.json",):
            txt = p.read_text(encoding="utf-8", errors="replace")
            for lineno, raw_line in enumerate(txt.splitlines(), 1):
                line = strip_inline_data_uris(raw_line)
                m = DELIVERABLE_JSON_INTERNAL_LEAK_RE.search(line)
                if m:
                    findings.append(
                        f"{rel}:{lineno} exposes internal harness detail '{m.group(0)}' — "
                        f"project JSON deliverables must never reference internal scripts, _shared/ paths, or subagent slugs."
                    )
    return findings


# --------------------------------------------------------------------------------------
# Stateless Container Contract & BuildKit `docker build --check` Helpers (Stages 5 & 8)
# --------------------------------------------------------------------------------------
VALID_DOMAIN_PACKS = (
    "codmod-assessment",
    "mainframe-mat",
    "cloud-dms",
    "bqms",
    "hadoop-oozie-flink",
    "agentic-audit",
)

_STATELESS_EXCLUDED_DIRS = {
    "node_modules", "dist", "build", "target", "bin", "obj", ".git", "__pycache__", ".venv", "venv", "migrations", "Migrations",
}
_STATELESS_SCAN_EXTS = {".cs", ".vb", ".java", ".kt", ".py", ".ts", ".js", ".mjs", ".go", ".config", ".xml"}
_TEST_FILE_RE = re.compile(r"(?:^test_|_test\.|tests?\.(?:cs|java|kt|py|ts|js|go)$|\.spec\.(?:ts|js)$)", re.IGNORECASE)
_COMMENT_LINE_RE = re.compile(r"^\s*(?:#|//|\*|/\*|<!--|--|;)")


def scan_stateless_container_hazards(src_dir: Path, root: Path) -> tuple[list[str], list[str]]:
    """Scan `src/backend/` for Windows-only OS/IIS blockers and sticky in-memory session / mutable static state
    hazards that break rootless Linux containers or horizontal multi-replica scaling (HPA / Cloud Run / GDC).

    Returns `(failures, warnings)`. Individual false-positive lines may opt out explicitly via `@dlc-stateless-safe`.
    """
    be_dir = src_dir / "backend"
    if not be_dir.is_dir():
        return [], []

    candidate_files: list[Path] = []
    full_blob_parts: list[str] = []
    for p in sorted(be_dir.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in _STATELESS_SCAN_EXTS:
            continue
        rel_parts = p.relative_to(be_dir).parts[:-1]
        if any(part in _STATELESS_EXCLUDED_DIRS for part in rel_parts):
            continue
        if _TEST_FILE_RE.search(p.name):
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        candidate_files.append(p)
        full_blob_parts.append(txt)

    full_blob = "\n".join(full_blob_parts)
    has_distributed_dotnet_cache = bool(
        re.search(r"\bAdd(?:StackExchangeRedisCache|DistributedSqlServerCache|DistributedPostgresCache|DistributedMemoryCache)\b", full_blob)
        and re.search(r"\b(?:Redis|Postgres|SqlServer|Npgsql)\b", full_blob)
    )
    has_spring_session = bool(re.search(r"@Enable(?:Redis|Jdbc|Hazelcast)HttpSession|spring\.session\.store-type\s*=\s*(?!none)", full_blob))

    hard_rules: list[tuple[str, re.Pattern[str], bool]] = [
        (
            "Windows IIS System.Web pipeline coupling (incompatible with Linux .NET containers)",
            re.compile(r"(?:^\s*using\s+System\.Web\s*;|\bSystem\.Web\.(?:HttpContext|IHttpModule|IHttpHandler|UI\.Page)\b)"),
            True,
        ),
        (
            "Windows Registry API dependency (incompatible with Linux containers)",
            re.compile(r"\bMicrosoft\.Win32\.Registry\b"),
            True,
        ),
        (
            "Native Win32 P/Invoke [DllImport] coupling in backend service",
            re.compile(r"\[\s*DllImport\s*\("),
            True,
        ),
        (
            "Legacy IIS InProc sessionState or Windows authentication mode in XML config",
            re.compile(r"(?:<sessionState\b[^>]*\bmode\s*=\s*[\"']InProc[\"']|<authentication\b[^>]*\bmode\s*=\s*[\"']Windows[\"'])", re.IGNORECASE),
            True,
        ),
        (
            "Sticky in-memory HttpContext.Session without distributed backing store (breaks multi-replica horizontal scaling)",
            re.compile(r"\bHttpContext(?:\.Current)?\.Session\b"),
            not has_distributed_dotnet_cache,
        ),
        (
            "Sticky servlet HttpSession without distributed Spring Session store (breaks multi-replica horizontal scaling)",
            re.compile(r"\brequest\.getSession\s*\(\s*(?:true)?\s*\)"),
            not has_spring_session,
        ),
    ]

    warn_rules: list[tuple[str, re.Pattern[str]]] = [
        (
            "Mutable static collection in backend service (verify it is not storing per-request/session state across horizontal replicas, or mark lookup constants readonly/final/@dlc-stateless-safe)",
            re.compile(r"\bstatic\s+(?!readonly\b|final\b)(?:ConcurrentDictionary|Dictionary|List|HashSet|HashMap|ArrayList|ConcurrentHashMap)\s*<"),
        ),
        (
            "Express session() configured without an external store (defaults to non-scalable in-memory MemoryStore)",
            re.compile(r"\bsession\s*\(\s*\{(?![^}]*\bstore\s*:)[^}]*\bsecret\s*:"),
        ),
    ]

    failures: list[str] = []
    warnings: list[str] = []
    for p in candidate_files:
        rel = p.relative_to(root).as_posix()
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        for lineno, raw_line in enumerate(lines, 1):
            if not raw_line.strip() or _COMMENT_LINE_RE.match(raw_line) or "@dlc-stateless-safe" in raw_line:
                continue
            for label, rx, active in hard_rules:
                if active and rx.search(raw_line):
                    failures.append(f"Stateless Container Contract violation in {rel}:{lineno} — {label}: `{raw_line.strip()[:120]}`")
                    break
            for label, rx in warn_rules:
                if rx.search(raw_line):
                    warnings.append(f"Horizontal-scaling state warning in {rel}:{lineno} — {label}: `{raw_line.strip()[:120]}`")
                    break
    return failures, warnings


def run_docker_build_check(dockerfile: Path, context_dir: Path, timeout_s: int = 20) -> tuple[str, str]:
    """Run BuildKit `docker build --check` against `dockerfile` when Docker >= 24 / BuildKit >= 0.15 is reachable.

    Tri-state return: `('ok' | 'fail' | 'skipped', detail)` — daemonless or older Docker environments skip cleanly
    with an explicit reason rather than failing air-gapped CI sandboxes.
    """
    if os.environ.get("DLC_SKIP_DOCKER_CHECK") == "1":
        return "skipped", "DLC_SKIP_DOCKER_CHECK=1"
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return "skipped", "docker CLI not on PATH"
    env = dict(os.environ)
    env["DOCKER_BUILDKIT"] = "1"
    try:
        cp = subprocess.run(
            [docker_bin, "build", "--check", "-f", str(dockerfile), str(context_dir)],
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "skipped", f"docker build --check timed out after {timeout_s}s"
    except OSError as exc:
        return "skipped", f"docker invocation failed ({exc})"

    combined = ((cp.stdout or "") + "\n" + (cp.stderr or "")).strip()
    if cp.returncode == 0:
        return "ok", "BuildKit `docker build --check` passed (0 lint violations)"

    low = combined.lower()
    env_skip_markers = (
        "unknown flag: --check",
        "cannot connect to the docker daemon",
        "is the docker daemon running",
        "permission denied while trying to connect",
        "error during connect",
        "dial unix",
        "buildx",
        "not supported",
    )
    if any(tok in low for tok in env_skip_markers):
        first_line = next((ln.strip() for ln in combined.splitlines() if ln.strip()), "daemon/buildkit unavailable")
        return "skipped", first_line[:180]

    tail_lines = " | ".join(ln.strip() for ln in combined.splitlines()[-5:] if ln.strip())[:320]
    return "fail", tail_lines or f"docker build --check exited with code {cp.returncode}"


# --------------------------------------------------------------------------------------
# Spec-Driven Development (SDD) Living Lifecycle, Approvals, Conciseness & Delta Guards
# --------------------------------------------------------------------------------------
SPEC_LIFECYCLE_MODES = ("standard", "delta", "retro-spec")

EXCLUDED_BOT_APPROVER_RE = re.compile(
    r"^(?:groupagent-\S+|agent-\S+|startblock|robot|bot|ci-bot|github-actions(?:\[bot\])?|"
    r"dependabot(?:\[bot\])?|copilot|claude|gemini|chatgpt|"
    r"discovery-architect|spec-judge|sprint-planner-agent|solution-architect|"
    r"architecture-critic|testing-agent|coding-agent|platform-ops-agent)$",
    re.IGNORECASE,
)

_SPEC_STATUS_LINE_RE = re.compile(r"^[\*\-][ \t]+\*\*Status:\*\*[ \t]*(.+)$", re.IGNORECASE | re.MULTILINE)
_APPROVED_BY_LINE_RE = re.compile(r"^[\*\-][ \t]+\*\*Approved by:\*\*[ \t]*(.*)$", re.IGNORECASE)
_APPROVALS_HDR_LINE_RE = re.compile(r"^[\*\-][ \t]+\*\*Approvals:\*\*[ \t]*(.*)$", re.IGNORECASE)
_PHASE_APPROVAL_SUB_RE = re.compile(
    r"^\*\*Phases?[ \t]+([^\*]+?)\*\*[ \t]+-[ \t]+(.+?)(?:[ \t]+-[ \t]+(.+))?$",
    re.IGNORECASE,
)


def sanitize_human_identities(raw_items: Iterable[str]) -> tuple[list[str], list[str]]:
    """Split raw reviewer/approver strings into `(valid_humans, rejected_bots)`.

    Strips leading `@` and trailing `@domain` email suffixes while rejecting robot/agent/bot accounts.
    """
    humans: list[str] = []
    bots: list[str] = []
    for item in raw_items:
        for tok in re.split(r"[,;\s]+", str(item or "").strip()):
            cleaned = tok.strip().lstrip("@")
            if not cleaned:
                continue
            if "@" in cleaned:
                cleaned = cleaned.split("@", 1)[0].strip()
            if not cleaned:
                continue
            if EXCLUDED_BOT_APPROVER_RE.match(cleaned) or cleaned.lower().endswith("-bot"):
                if cleaned not in bots:
                    bots.append(cleaned)
            else:
                if cleaned not in humans:
                    humans.append(cleaned)
    return humans, bots


def validate_spec_approvals_header(
    spec_md: str,
    ceremony_track: str = "standard",
    strict: bool = False,
) -> tuple[list[str], list[str], dict[str, Any]]:
    """Validate living-spec `* **Status:**` and `* **Approved by:**` / multi-phase `* **Approvals:**` headers.

    Enforces:
      - Bot/agent account exclusion in human approval lists (`SD-APPR-02`).
      - Multi-phase delta preservation: resetting single-line `Approved by:` to `PENDING` when completed (`- [x]`)
        tasks or `Delta` phases exist is rejected (`SD-APPR-03`).
      - Two-Person Review (`>= 2` distinct human approvers) when `ceremony_track == 'regulated'` and `strict=True`.
    """
    errors: list[str] = []
    warnings: list[str] = []

    status_m = _SPEC_STATUS_LINE_RE.search(spec_md)
    raw_status = strip_md(status_m.group(1)).strip() if status_m else ""
    has_completed_tasks = bool(re.search(r"^[ \t]*[\*\-][ \t]+\[[xX]\]", spec_md, re.MULTILINE))
    has_delta_markers = bool(
        re.search(r"^##[ \t]+Phase[ \t]+\d+[^\n]*\bDelta\b", spec_md, re.IGNORECASE | re.MULTILINE)
        or re.search(r"^#\s+[^\n]*\bDelta\b", spec_md, re.IGNORECASE | re.MULTILINE)
    )

    header_type = ""
    header_val = ""
    sub_bullets: list[str] = []
    in_block = False
    for line in spec_md.splitlines():
        stripped = line.strip()
        if not in_block:
            m_app = _APPROVALS_HDR_LINE_RE.match(line)
            if m_app:
                header_type = "Approvals"
                header_val = m_app.group(1).strip()
                in_block = True
                continue
            m_by = _APPROVED_BY_LINE_RE.match(line)
            if m_by:
                header_type = "Approved by"
                header_val = m_by.group(1).strip()
                in_block = True
                continue
        else:
            if not stripped:
                break
            m_sub = re.match(r"^[ \t]+[\*\-][ \t]+(.+)$", line)
            if m_sub:
                sub_bullets.append(m_sub.group(1).strip())
            else:
                break

    all_humans: list[str] = []
    has_pending = False

    if not header_type:
        if strict or has_delta_markers:
            errors.append(
                "Missing required specification approvals metadata (`* **Approved by:**` or multi-phase `* **Approvals:**`)."
            )
    elif header_type == "Approved by":
        if has_delta_markers:
            errors.append(
                "Multi-phase living specification delta detected, but flat `* **Approved by:**` is used. "
                "Use structured `* **Approvals:**` with `* **Phases X - Y** - [ref] - <approvers>` sub-bullets."
            )
        if "PENDING" in header_val.upper():
            has_pending = True
            if has_delta_markers or has_completed_tasks:
                errors.append(
                    "Disallowed single-line pending reset in `* **Approved by:**` when completed roadmap items or delta phases exist; "
                    "retain historic phase approvals under `* **Approvals:**` and append a pending sub-bullet for the new delta phase."
                )
            elif strict:
                errors.append("`* **Approved by:**` still contains an unresolved PENDING placeholder.")
        else:
            humans, bots = sanitize_human_identities([header_val])
            if bots:
                errors.append(f"`* **Approved by:**` contains excluded bot/agent identity(ies): {', '.join(bots)}.")
            all_humans.extend(humans)
    else:  # Approvals
        if header_val:
            errors.append("`* **Approvals:**` must place phase entries on indented sub-bullets, not inline on the header line.")
        if not sub_bullets:
            errors.append("`* **Approvals:**` must contain at least one `* **Phases <range>** - <ticket/PR> - <approvers>` sub-bullet.")
        for idx, sb in enumerate(sub_bullets, 1):
            m_ph = _PHASE_APPROVAL_SUB_RE.match(sb)
            if not m_ph:
                errors.append(
                    f"`* **Approvals:**` sub-bullet #{idx} does not match `* **Phases <X - Y>** - <ref> - <approvers>`: `{sb[:100]}`"
                )
                continue
            approver_part = (m_ph.group(3) or "").strip()
            if not approver_part:
                errors.append(f"`* **Approvals:**` sub-bullet #{idx} is missing approvers or `{{{{PENDING_APPROVAL}}}}`.")
                continue
            if "PENDING" in approver_part.upper():
                has_pending = True
                if idx < len(sub_bullets):
                    errors.append(
                        f"`* **Approvals:**` historical sub-bullet #{idx} cannot remain PENDING once newer phase #{len(sub_bullets)} is appended."
                    )
                elif strict:
                    errors.append(f"`* **Approvals:**` sub-bullet #{idx} still has unresolved PENDING approval.")
            else:
                humans, bots = sanitize_human_identities([approver_part])
                if bots:
                    errors.append(f"`* **Approvals:**` sub-bullet #{idx} contains excluded bot/agent identity(ies): {', '.join(bots)}.")
                for h in humans:
                    if h not in all_humans:
                        all_humans.append(h)

    if strict and ceremony_track == "regulated" and len(all_humans) < 2:
        errors.append(
            f"Regulated Two-Person Review requires >= 2 distinct human approvers in specification header (found {len(all_humans)}: {all_humans or 'none'})."
        )

    meta = {
        "lifecycleStatus": raw_status or "ACTIVE",
        "headerType": header_type or None,
        "approvers": all_humans,
        "hasPendingApproval": has_pending,
        "isDeltaMode": has_delta_markers,
        "hasCompletedTasks": has_completed_tasks,
        "phaseApprovalCount": len(sub_bullets),
    }
    return errors, warnings, meta


def audit_spec_conciseness_and_refs(
    spec_md: str,
    root: Path,
    check_codebase: bool = False,
    max_prose_words: int = 3500,
) -> tuple[list[str], list[str], dict[str, Any]]:
    """Enforce SDD narrative conciseness budget (`SD-NARR-01`) and optional physical path existence (`SD-REF-01`)."""
    errors: list[str] = []
    warnings: list[str] = []

    in_fence = False
    prose_words = 0
    table_rows = 0
    for line in spec_md.splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not s:
            continue
        if s.startswith("|") and s.endswith("|"):
            table_rows += 1
            continue
        if s.startswith("#"):
            continue
        prose_words += len(re.findall(r"\b\w+\b", s))

    if prose_words > 12_000:
        errors.append(
            f"SD-NARR-01: Specification non-table prose ({prose_words} words) exceeds 12,000-word ceiling — "
            "express business rules, roles, and transitions in structured tables rather than narrative BRD dumps."
        )
    elif prose_words > max_prose_words:
        warnings.append(
            f"SD-NARR-01: Specification non-table prose ({prose_words} words) exceeds recommended {max_prose_words}-word SDD budget."
        )

    checked_paths = 0
    missing_paths: list[str] = []
    if check_codebase:
        for m in re.finditer(r"`((?:resources|src|specs|design|deploy)/[A-Za-z0-9_./-]+)`", spec_md):
            rel_cand = m.group(1).rstrip(".,;:")
            if "*" in rel_cand or "<" in rel_cand or "{" in rel_cand or "..." in rel_cand:
                continue
            checked_paths += 1
            if not (root / rel_cand).exists():
                if rel_cand not in missing_paths:
                    missing_paths.append(rel_cand)
        for mp in missing_paths:
            errors.append(f"SD-REF-01: Specification cites codebase path `{mp}` which does not exist under project root.")

    return errors, warnings, {
        "proseWordCount": prose_words,
        "structuredTableRows": table_rows,
        "checkedCodebasePaths": checked_paths,
        "missingCodebasePaths": missing_paths,
    }


def verify_delta_preservation(baseline_spec_md: str, candidate_spec_md: str) -> list[str]:
    """Verify byte-for-byte preservation of completed (`- [x]`) roadmap items and historic approved phase sub-bullets
    when evolving a living specification in Phase N+1 Delta Mode."""
    errors: list[str] = []
    cand_lines = {ln.strip() for ln in candidate_spec_md.splitlines() if ln.strip()}

    for ln in baseline_spec_md.splitlines():
        s = ln.strip()
        if re.match(r"^[\*\-][ \t]+\[[xX]\][ \t]+", s):
            if s not in cand_lines:
                errors.append(f"Delta preservation violation: completed roadmap item modified or removed: `{s[:120]}`")
        elif re.match(r"^[\*\-][ \t]+\*\*Phases?[ \t]+", s, re.IGNORECASE) and "PENDING" not in s.upper():
            if s not in cand_lines:
                errors.append(f"Delta preservation violation: historic phase approval modified or dropped: `{s[:120]}`")
    return errors


# --------------------------------------------------------------------------------------
# Conditional Decision-Tree Clarification & Modernization Grilling (`clarification-griller`)
# --------------------------------------------------------------------------------------
_NONE_WORKFLOW_Q_RE = re.compile(
    r"^(?:none|n/?a|no\s+open\s+(?:workflow\s+)?questions?|all\s+workflow\s+transitions?\s+(?:are\s+)?(?:settled|evidenced|resolved))[\s.—-]*$",
    re.IGNORECASE,
)
_EMPTY_GUARD_RE = re.compile(r"^(?:|—|-|n/?a|none|tbd|\?)$", re.IGNORECASE)


def normalize_clarification_stage(stage: str | None) -> str:
    s = (stage or "pre-spec").strip().lower()
    if s in ("gate1", "pre-spec", "spec", "stage1", "stage2"):
        return "pre-spec"
    if s in ("pre-stories", "stories", "stage3", "gate3"):
        return "pre-stories"
    if s in ("stage4a", "gate4", "design", "architecture"):
        return "stage4a"
    return "anytime"


def parse_open_workflow_questions(md: str) -> list[str]:
    """Extract non-empty open workflow questions from `§3.1 Open Workflow Questions` in Stage 1 blueprint."""
    sec = md_section(md, r"open workflow questions")
    if not sec:
        return []
    questions: list[str] = []
    for raw in sec.splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or (s.startswith("|") and re.search(r"^[\|\s:-]+$", s)):
            continue
        if s.startswith("|") and s.endswith("|"):
            cells = [strip_md(c).strip() for c in s.strip("|").split("|")]
            if not cells or cells[0].lower() in {"#", "id", "question", "question id", "item"}:
                continue
            joined = " — ".join(c for c in cells if c)
            if joined and not _NONE_WORKFLOW_Q_RE.match(joined):
                questions.append(joined)
            continue
        cleaned = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", s).strip()
        cleaned_plain = strip_md(cleaned).strip()
        if not cleaned_plain or _NONE_WORKFLOW_Q_RE.match(cleaned_plain):
            continue
        if "?" in cleaned_plain or "UNVERIFIED_ACRONYM" in cleaned or len(questions) > 0 or s.startswith(("-", "*", "1.")):
            questions.append(cleaned_plain)
    return questions


def active_spec_lifecycle_mode(root: Path) -> str:
    """Return configured `specLifecycleMode` from `specs/project_setup.json` (default `'standard'`)."""
    sp = root / "specs" / "project_setup.json"
    if sp.is_file():
        try:
            data = read_json(sp)
            if isinstance(data, dict) and data.get("specLifecycleMode") in SPEC_LIFECYCLE_MODES:
                return str(data["specLifecycleMode"])
        except Exception:
            pass
    return "standard"


def assess_clarification_triggers(root: Path, stage: str = "pre-spec") -> dict[str, Any]:
    """Deterministically evaluate whether `grill-me` (`clarification-griller`) must run before creating
    `specs/application_spec.md` (`pre-spec`), when creating `backlog/user_stories.json` (`pre-stories`),
    at Stage 4A architecture entry (`stage4a`), or whenever contradictions/ambiguities exist."""
    norm_stage = normalize_clarification_stage(stage)
    spec_mode = active_spec_lifecycle_mode(root)
    clar_path = root / "specs" / "clarification_decisions.json"
    if is_autonomous_or_golden(root):
        return {
            "stage": norm_stage,
            "specLifecycleMode": spec_mode,
            "needsClarification": False,
            "bypassReason": "autonomous_or_golden_mode",
            "triggerReasons": [],
            "openWorkflowQuestions": [],
            "unverifiedAcronyms": [],
            "detectedAmbiguities": [],
            "storyAmbiguities": [],
        }

    if clar_path.is_file():
        clar = read_json(clar_path)
        if isinstance(clar, dict):
            c_status = str(clar.get("clarificationStatus") or "")
            open_f = clar.get("openFrontier") or []
            settled = list(clar.get("stagesSettled") or [])
            # Backwards compatibility: a settled v4.6 ledger without `stagesSettled` settled pre-spec
            if not settled and not open_f and c_status in ("RESOLVED_BY_HUMAN", "ACCEPTED_RECOMMENDATIONS", "CLEAR_AUTO_BYPASSED", "AUTONOMOUS_ASSUMPTIONS"):
                settled = ["pre-spec"]
            matching_open = [
                q for q in open_f
                if isinstance(q, dict) and normalize_clarification_stage(q.get("stage")) in (norm_stage, "anytime")
            ]
            if matching_open or (open_f and norm_stage == "anytime"):
                return {
                    "stage": norm_stage,
                    "specLifecycleMode": spec_mode,
                    "needsClarification": True,
                    "bypassReason": None,
                    "triggerReasons": [f"OPEN_FRONTIER_PENDING:{len(matching_open or open_f)}"],
                    "openWorkflowQuestions": [],
                    "unverifiedAcronyms": [],
                    "detectedAmbiguities": [],
                    "storyAmbiguities": [],
                }
            if norm_stage in settled:
                return {
                    "stage": norm_stage,
                    "specLifecycleMode": spec_mode,
                    "needsClarification": False,
                    "bypassReason": f"already_settled:{norm_stage}({c_status})",
                    "triggerReasons": [],
                    "openWorkflowQuestions": [],
                    "unverifiedAcronyms": [],
                    "detectedAmbiguities": [],
                    "storyAmbiguities": [],
                }

    reasons: list[str] = []
    open_qs: list[str] = []
    unverified_acrs: list[str] = []
    detected_ambigs: list[dict[str, Any]] = []
    story_ambigs: list[dict[str, str]] = []

    if norm_stage == "pre-spec":
        inv_path = root / "specs" / "input_inventory.json"
        inv = read_json(inv_path) if inv_path.is_file() else {}
        scenario = inv.get("inputScenario", "SCENARIO_REQUIREMENTS_DOC") if isinstance(inv, dict) else "SCENARIO_REQUIREMENTS_DOC"
        conf = str(inv.get("scenarioConfidence") or "HIGH").upper() if isinstance(inv, dict) else "HIGH"
        unverified_acrs = list(inv.get("unverifiedAcronyms") or []) if isinstance(inv, dict) else []
        detected_ambigs = list(inv.get("detectedAmbiguities") or []) if isinstance(inv, dict) else []

        missing_role_trans: list[str] = []
        doc_path = root / "specs" / "discovery_architecture_and_inventory.md"
        if doc_path.is_file():
            md = read_text(doc_path)
            open_qs = parse_open_workflow_questions(md)
            sm_tbl = parse_state_table(md)
            missing_role_trans = [f"{t.src}->{t.dst} ({t.trigger})" for t in sm_tbl.transitions if not t.roles]

        if conf == "LOW":
            reasons.append("LOW_SCENARIO_CONFIDENCE")
        if scenario == "SCENARIO_LEGACY_APP" and spec_mode in ("standard", "delta"):
            reasons.append("LEGACY_MODERNIZATION_AMBITION_UNSETTLED")
        if detected_ambigs:
            reasons.append(f"CONTRADICTORY_OR_AMBIGUOUS_INPUTS:{len(detected_ambigs)}")
        if open_qs:
            reasons.append(f"OPEN_WORKFLOW_QUESTIONS:{len(open_qs)}")
        if missing_role_trans:
            reasons.append(f"INCOMPLETE_TRANSITION_ROLES:{len(missing_role_trans)}")
        if unverified_acrs:
            reasons.append(f"UNVERIFIED_ACRONYMS:{len(unverified_acrs)}")

    elif norm_stage == "pre-stories":
        spec_path = root / "specs" / "application_spec.md"
        if spec_path.is_file():
            spec_md = read_text(spec_path)
            # 1. Residual ASSUMPTION-NN items in spec that a BA has not explicitly confirmed
            assump_lines = [
                strip_md(ln.strip()).lstrip("-*|> ")
                for ln in spec_md.splitlines()
                if re.search(r"\bASSUMPTION-\d+\b", ln)
            ]
            if assump_lines:
                reasons.append(f"UNCONFIRMED_SPEC_ASSUMPTIONS:{len(assump_lines)}")
                story_ambigs.append({
                    "category": "story-acceptance-criteria",
                    "evidenceSource": "specs/application_spec.md (Assumptions)",
                    "question": (
                        f"Before authoring user stories and GIVEN/WHEN/THEN acceptance criteria, please confirm or "
                        f"adjust the {len(assump_lines)} open specification assumption(s): {'; '.join(assump_lines[:3])}"
                    ),
                    "recommendedAnswer": "Confirm the documented restrictive specification assumptions as authoritative story acceptance criteria.",
                })

            # 2. Business rules (BR-NN) without concrete boundary/negative Examples vectors
            brs = parse_business_rules(spec_md)
            br_no_examples = [b["id"] for b in brs if b.get("id") and not b.get("parsedExamples")]
            if br_no_examples:
                reasons.append(f"STORY_BR_BOUNDARY_EXAMPLES_MISSING:{len(br_no_examples)}")
                story_ambigs.append({
                    "category": "business-rule",
                    "evidenceSource": f"specs/application_spec.md (§3.4 Business Rules: {', '.join(br_no_examples[:5])})",
                    "question": (
                        f"Business rule(s) {', '.join(br_no_examples[:5])} do not yet specify boundary/rejection input->output "
                        "examples. For user story EDGE / BOUNDARY and NEGATIVE acceptance criteria, should exact threshold "
                        "values be inclusive (`>=` / `<=`) and return inline field-level validation errors on violation?"
                    ),
                    "recommendedAnswer": (
                        "Treat stated numeric thresholds as inclusive boundaries (`>=` min, `<=` max), use half-up 2-decimal "
                        "rounding for currency/rates, and reject out-of-range inputs with inline human-readable validation messages."
                    ),
                })

            # 3. Transitions in §3.3 with blank/unspecified Guard conditions on decision triggers
            sm = parse_state_table(spec_md)
            unguarded = [
                f"{t.src}->{t.dst} ({t.trigger})"
                for t in sm.transitions
                if _EMPTY_GUARD_RE.match(str(t.guard or "").strip())
            ]
            if unguarded:
                reasons.append(f"STORY_TRANSITION_GUARD_AMBIGUOUS:{len(unguarded)}")
                story_ambigs.append({
                    "category": "workflow-state",
                    "evidenceSource": f"specs/application_spec.md (§3.3 State Machine: {', '.join(unguarded[:4])})",
                    "question": (
                        f"Workflow transition(s) {', '.join(unguarded[:4])} have no explicit guard condition in §3.3. "
                        "What prerequisite fields, mandatory comments/reasons, or maker-checker separation-of-duties rules "
                        "should the user story acceptance criteria enforce?"
                    ),
                    "recommendedAnswer": (
                        "Require all mandatory intake fields before submission, require a non-empty audit reason on rejection/return "
                        "or override transitions, and enforce role-based separation between requester and approver."
                    ),
                })

        # 4. Multi-group Sprint 1 MVP slicing & prioritization confirmation
        ts_path = root / "specs" / "target_stack.json"
        if ts_path.is_file():
            ts = read_json(ts_path)
            if isinstance(ts, dict):
                cgroups = ts.get("capabilityGroups") or []
                sel = [str(x).upper() for x in (ts.get("selectedCapabilityGroups") or ["ALL"])]
                if len(cgroups) >= 2 and ("ALL" in sel or len(sel) >= 2):
                    grp_names = ", ".join(f"{g.get('id')} ({g.get('name', '')})" for g in cgroups[:5] if isinstance(g, dict))
                    reasons.append(f"MULTI_GROUP_SPRINT_SLICING_UNCONFIRMED:{len(cgroups)}")
                    story_ambigs.append({
                        "category": "story-acceptance-criteria",
                        "evidenceSource": f"specs/target_stack.json ({len(cgroups)} capability groups: {grp_names})",
                        "question": (
                            f"When slicing user stories across {grp_names}, confirm Sprint 1 MVP ordering and story granularity "
                            "(foundational contracts + shared group in Sprint 1 followed by dependent business groups, or re-order "
                            "a specific high-value business workflow earlier?)."
                        ),
                        "recommendedAnswer": (
                            "Schedule foundational schema/API contract slices (`US-TECH-*`) and `GRP-01` core intake/registry in "
                            "Sprint 1, followed by downstream capability groups in topological dependency order (`<= 3` prod files per slice)."
                        ),
                    })

    elif norm_stage == "stage4a":
        ts_path = root / "specs" / "target_stack.json"
        if not ts_path.is_file():
            reasons.append("TARGET_STACK_MISSING")
        else:
            ts = read_json(ts_path)
            if isinstance(ts, dict):
                decided = str(ts.get("decidedBy") or "")
                fe = str((ts.get("frontend") or {}).get("kind") or "tbd")
                be = str((ts.get("backend") or {}).get("kind") or "tbd")
                db = str((ts.get("database") or {}).get("kind") or "tbd")
                if decided != "user" or "tbd" in (fe, be, db):
                    reasons.append(f"TARGET_STACK_TBD(decidedBy={decided},fe={fe},be={be},db={db})")

    return {
        "stage": norm_stage,
        "specLifecycleMode": spec_mode,
        "needsClarification": len(reasons) > 0,
        "bypassReason": None if reasons else "inputs_complete_zero_ambiguity",
        "triggerReasons": reasons,
        "openWorkflowQuestions": open_qs,
        "unverifiedAcronyms": unverified_acrs,
        "detectedAmbiguities": detected_ambigs,
        "storyAmbiguities": story_ambigs,
    }


def build_clarification_frontier(root: Path, stage: str = "pre-spec") -> dict[str, Any]:
    """Build the full detection + suggested `1..4` root `grill-me` frontier questions for `stage`."""
    norm_stage = normalize_clarification_stage(stage)
    assessment = assess_clarification_triggers(root, stage=norm_stage)
    frontier: list[dict[str, Any]] = []
    q_idx = 1

    if norm_stage == "pre-spec":
        inv_path = root / "specs" / "input_inventory.json"
        inv = read_json(inv_path) if inv_path.is_file() else {}
        doc_path = root / "specs" / "discovery_architecture_and_inventory.md"
        md = read_text(doc_path) if doc_path.is_file() else ""
        cap_groups = parse_capability_groups(md) if md else []
        grp_labels = ", ".join(f"{g['id']} ({g['name']})" for g in cap_groups[:6]) or "discovered capability groups"

        # Surface contradictions/conflicts FIRST so BA resolves conflicting business rules immediately!
        for amb in (assessment.get("detectedAmbiguities") or [])[:2]:
            if q_idx > 4:
                break
            frontier.append({
                "questionId": f"Q{q_idx}",
                "stage": "pre-spec",
                "round": 1,
                "parentDecisionId": None,
                "category": "contradiction-conflict",
                "evidenceSource": ", ".join(amb.get("files") or ["resources/inputs"]),
                "question": f"{amb.get('summary')} — Which value or rule is authoritative for `specs/application_spec.md`?",
                "recommendedAnswer": (
                    "Treat the governed policy/query rule from the primary business workflow as authoritative, "
                    "parameterize the threshold in configuration, and document the superseded legacy value."
                ),
            })
            q_idx += 1

        if "LEGACY_MODERNIZATION_AMBITION_UNSETTLED" in assessment["triggerReasons"] and q_idx <= 4:
            frontier.append({
                "questionId": f"Q{q_idx}",
                "stage": "pre-spec",
                "round": 1,
                "parentDecisionId": None,
                "category": "capability-disposition",
                "evidenceSource": "specs/discovery_architecture_and_inventory.md (§5 Pain Points & §6.1 Capability Groupings)",
                "question": (
                    f"Modernizing a legacy application goes beyond 1:1 lift-and-shift. Across {grp_labels}, "
                    "which capabilities should be (a) Re-imagined (`REQ-ENH-*`: self-service UX, automated workflow & "
                    "notifications, live rule engine, or grounded AI copilot), (b) Kept at strict 1:1 parity, or (c) Retired?"
                ),
                "recommendedAnswer": (
                    "Re-imagine core operational & intake capabilities with self-service UX, live rule validation, "
                    "and automated status notifications derived from §5 pain points; keep deterministic core "
                    "calculations at 1:1 parity; retire obsolete manual export/print forms."
                ),
                "options": [
                    "(Recommended) Re-imagine core workflows (REQ-ENH-*) + keep core formulas at parity + retire obsolete manual forms",
                    "Add AI-assisted triage / copilot surface alongside re-imagined self-service workflows",
                    "Strict 1:1 functional parity across all discovered capabilities (modernize architecture/UI only)",
                ],
            })
            q_idx += 1

        if "LEGACY_MODERNIZATION_AMBITION_UNSETTLED" in assessment["triggerReasons"] and q_idx <= 4:
            rrs = (inv.get("runtimeReadinessSignals") or {}) if isinstance(inv, dict) else {}
            rec_mode = rrs.get("recommendedModernizationMode") or "clean-room-rebuild"
            blockers = (rrs.get("osAndPlatformBlockers") or []) + (rrs.get("statelessScalingHazards") or [])
            frontier.append({
                "questionId": f"Q{q_idx}",
                "stage": "pre-spec",
                "round": 1,
                "parentDecisionId": None,
                "category": "modernization-ambition",
                "evidenceSource": f"specs/input_inventory.json (recommended={rec_mode}, blockers={len(blockers)})",
                "question": (
                    "Which modernization execution approach and initial delivery wave should govern implementation: "
                    "`clean-room-rebuild` vs. `in-place-upgrade`, and foundational wave `GRP-01` first vs. `ALL` groups?"
                ),
                "recommendedAnswer": (
                    f"Use `{rec_mode}` and take `ALL` capability groups forward (or `GRP-01` first for phased Strangler "
                    "cutover) while eliminating legacy desktop/OS/session blockers."
                ),
                "options": [
                    f"(Recommended) {rec_mode} — take ALL capability groups forward across ordered sprints",
                    f"{rec_mode} — phased Strangler wave starting with foundational GRP-01 only",
                    "Switch modernizationMode (clean-room-rebuild <-> in-place-upgrade)",
                ],
            })
            q_idx += 1

        for oq in assessment.get("openWorkflowQuestions", [])[:2]:
            if q_idx > 4:
                break
            frontier.append({
                "questionId": f"Q{q_idx}",
                "stage": "pre-spec",
                "round": 1,
                "parentDecisionId": None,
                "category": "workflow-state",
                "evidenceSource": "specs/discovery_architecture_and_inventory.md (§3.1 Open Workflow Questions)",
                "question": oq,
                "recommendedAnswer": (
                    "Adopt the most restrictive role-gated workflow transition (explicit reviewer/supervisor role "
                    "required; rejected records return to an editable revision state with mandatory audit reason)."
                ),
            })
            q_idx += 1

        unv = assessment.get("unverifiedAcronyms") or []
        if unv and q_idx <= 4:
            acr_list = ", ".join(unv[:6])
            frontier.append({
                "questionId": f"Q{q_idx}",
                "stage": "pre-spec",
                "round": 1,
                "parentDecisionId": None,
                "category": "acronym-definition",
                "evidenceSource": "specs/input_inventory.json (unverifiedAcronyms)",
                "question": f"Please confirm the authoritative business expansion/meaning for undefined acronym(s): {acr_list}.",
                "recommendedAnswer": f"Preserve literal acronym(s) ({acr_list}) verbatim unless defined by the Business Analyst.",
            })
            q_idx += 1

    elif norm_stage == "pre-stories":
        for sa in (assessment.get("storyAmbiguities") or [])[:4]:
            frontier.append({
                "questionId": f"Q{q_idx}",
                "stage": "pre-stories",
                "round": 1,
                "parentDecisionId": None,
                "category": sa["category"],
                "evidenceSource": sa["evidenceSource"],
                "question": sa["question"],
                "recommendedAnswer": sa["recommendedAnswer"],
            })
            q_idx += 1

    elif norm_stage == "stage4a":
        if any("TARGET_STACK_TBD" in r for r in assessment["triggerReasons"]):
            frontier.append({
                "questionId": "Q1",
                "stage": "stage4a",
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


def format_grill_me_banner(stage: str, frontier: list[dict[str, Any]]) -> str:
    """Render a prominent, unmistakable Grill-Me round block for terminal & chat presentation."""
    lines = [
        "=" * 78,
        f"[🔥 GRILL-ME CLARIFICATION REQUIRED — STAGE: {stage.upper()} ({len(frontier)} QUESTION(S))]",
        "Engage the Business Analyst / Human with these Frontier Questions BEFORE proceeding",
        "(use `ask_question` UI widget when available, or reply `accept recommendations`):",
        "-" * 78,
    ]
    for q in frontier:
        lines.append(f"❓ **{q.get('questionId', 'Q')}** ({q.get('category', '')} · Source: {q.get('evidenceSource', '')}):")
        lines.append(f"   {q.get('question', '')}")
        lines.append(f"   ➡️ Recommended: {q.get('recommendedAnswer', '')}")
    lines.extend([
        "-" * 78,
        f"Record answers: python3 \"{PLUGIN_ROOT / 'skills/clarification-griller/scripts/clarification_interview.py'}\" "
        f"--project-root \"<PROJECT_ROOT>\" --stage {stage} --action record-round --decisions-json '[...]'",
        f"Or fast-exit  : python3 \"{PLUGIN_ROOT / 'skills/clarification-griller/scripts/clarification_interview.py'}\" "
        f"--project-root \"<PROJECT_ROOT>\" --stage {stage} --action accept-recommendations",
        "=" * 78,
    ])
    return "\n".join(lines)


def auto_seed_clarification_stage(root: Path, stage: str, deterministic: bool = False) -> dict[str, Any]:
    """Deterministically seed `specs/clarification_decisions.json` at stage boundaries (`pre-spec`, `pre-stories`)
    in interactive mode so `grill-me` can NEVER be silently skipped when clarification is needed."""
    norm_stage = normalize_clarification_stage(stage)
    if is_autonomous_or_golden(root, deterministic=deterministic):
        return {"seeded": False, "needsClarification": False, "stage": norm_stage}

    clar_path = root / "specs" / "clarification_decisions.json"
    if clar_path.is_file():
        ledger = read_json(clar_path)
        if not isinstance(ledger, dict):
            ledger = {}
    else:
        ledger = {}

    ledger.setdefault("schemaVersion", SCHEMA_VERSION)
    ledger.setdefault("clarificationStatus", "IN_PROGRESS")
    ledger.setdefault("stagesSettled", [])
    ledger.setdefault("roundsCompleted", 0)
    ledger.setdefault("triggerReasons", [])
    ledger.setdefault("capabilityDispositions", [])
    ledger.setdefault("decisions", [])
    ledger.setdefault("openFrontier", [])

    # Backfill `stagesSettled` for settled pre-v4.7 ledgers
    if not ledger["stagesSettled"] and not ledger["openFrontier"] and ledger["clarificationStatus"] in (
        "RESOLVED_BY_HUMAN", "ACCEPTED_RECOMMENDATIONS", "CLEAR_AUTO_BYPASSED", "AUTONOMOUS_ASSUMPTIONS"
    ):
        ledger["stagesSettled"] = ["pre-spec"]

    # If this stage is already settled and no open frontier exists, leave ledger untouched
    if norm_stage in ledger["stagesSettled"] and not ledger["openFrontier"]:
        return {"seeded": False, "needsClarification": False, "stage": norm_stage, "alreadySettled": True}

    # If openFrontier already contains items for this stage, keep them without overwriting
    existing_stage_open = [
        q for q in ledger["openFrontier"]
        if isinstance(q, dict) and normalize_clarification_stage(q.get("stage")) in (norm_stage, "anytime")
    ]
    if existing_stage_open:
        return {
            "seeded": True,
            "needsClarification": True,
            "stage": norm_stage,
            "openFrontier": existing_stage_open,
        }

    report = build_clarification_frontier(root, stage=norm_stage)
    ledger["updatedAtUtc"] = utc_now_iso(deterministic)
    if report["needsClarification"] and report["suggestedRootFrontier"]:
        ledger["clarificationStatus"] = "IN_PROGRESS"
        ledger["triggerReasons"] = list(dict.fromkeys(ledger["triggerReasons"] + report["triggerReasons"]))
        ledger["openFrontier"] = list(ledger["openFrontier"]) + report["suggestedRootFrontier"]
        write_json(clar_path, ledger)
        return {
            "seeded": True,
            "needsClarification": True,
            "stage": norm_stage,
            "triggerReasons": report["triggerReasons"],
            "openFrontier": report["suggestedRootFrontier"],
        }

    # Inputs are crystal clear for this stage -> mark stage settled automatically (zero noise!)
    if norm_stage not in ledger["stagesSettled"]:
        ledger["stagesSettled"].append(norm_stage)
    if not ledger["openFrontier"] and not ledger["decisions"]:
        ledger["clarificationStatus"] = "CLEAR_AUTO_BYPASSED"
    elif not ledger["openFrontier"] and ledger["clarificationStatus"] == "IN_PROGRESS":
        ledger["clarificationStatus"] = "RESOLVED_BY_HUMAN"
    write_json(clar_path, ledger)
    return {"seeded": True, "needsClarification": False, "stage": norm_stage, "openFrontier": []}


def validate_clarification_ledger_for_spec(
    root: Path,
    spec_md: str,
) -> tuple[list[str], list[str], dict[str, Any]]:
    """Validate `specs/clarification_decisions.json` before Stage 2 spec lint passes.

    Enforces:
      - `SD-GRILL-00` (Interactive Mode): When `specs/gate_approvals.json` exists, `pre-spec` `grill-me` MUST
        have been run/settled (`specs/clarification_decisions.json` cannot be skipped).
      - `SD-GRILL-01`: No unresolved `openFrontier` or `IN_PROGRESS` status when finalizing `application_spec.md`.
      - `SD-GRILL-02`: Capabilities explicitly marked `disposition == 'retire'` must not appear as active
        `REQ-FUNC-*` / `REQ-ENH-*` requirement definitions in Pillar 1.
    """
    errors: list[str] = []
    warnings: list[str] = []
    clar_path = root / "specs" / "clarification_decisions.json"
    interactive_enforced = gate_approvals_path(root).is_file() and not is_autonomous_or_golden(root)

    if not clar_path.is_file():
        if interactive_enforced:
            rep = build_clarification_frontier(root, stage="pre-spec")
            if rep["needsClarification"]:
                errors.append(
                    f"SD-GRILL-00: Pre-Spec Grill-Me clarification has NOT been run yet "
                    f"(reasons={rep['triggerReasons']}). Run `clarification_interview.py --project-root \"{root}\" "
                    "--stage pre-spec --action detect`, engage the Business Analyst / human on the Frontier Questions, "
                    "and record their answers BEFORE creating/finalizing `specs/application_spec.md`."
                )
        return errors, warnings, {"present": False, "decisionIds": [], "retiredTargets": []}

    clar = read_json(clar_path)
    schema_errs = validate_against_schema(clar, load_schema("clarification_decisions.schema.json"))
    if schema_errs:
        errors.append(
            "specs/clarification_decisions.json violates schemas/clarification_decisions.schema.json: "
            + "; ".join(schema_errs[:5])
        )
        return errors, warnings, {"present": True, "decisionIds": [], "retiredTargets": []}

    c_status = str(clar.get("clarificationStatus") or "")
    open_f = clar.get("openFrontier") or []
    pre_spec_open = [
        q for q in open_f
        if not isinstance(q, dict) or normalize_clarification_stage(q.get("stage")) in ("pre-spec", "anytime")
    ]
    if (c_status == "IN_PROGRESS" and pre_spec_open) or pre_spec_open:
        errors.append(
            f"SD-GRILL-01: specs/clarification_decisions.json still has {len(pre_spec_open)} unresolved Pre-Spec "
            f"Grill-Me question(s) (status={c_status!r}). Engage the Business Analyst / human and run "
            "`clarification_interview.py --stage pre-spec --action record-round` (or `--action accept-recommendations`) "
            "before finalizing specs/application_spec.md."
        )
    elif interactive_enforced:
        settled = list(clar.get("stagesSettled") or [])
        if not settled and c_status in ("RESOLVED_BY_HUMAN", "ACCEPTED_RECOMMENDATIONS", "CLEAR_AUTO_BYPASSED", "AUTONOMOUS_ASSUMPTIONS"):
            settled = ["pre-spec"]
        if "pre-spec" not in settled:
            errors.append(
                "SD-GRILL-00: `pre-spec` clarification stage is not marked settled in `specs/clarification_decisions.json`. "
                "Run `clarification_interview.py --stage pre-spec --action detect --auto-bypass-if-clear`."
            )

    retired_targets = [
        str(d.get("targetId")).strip()
        for d in (clar.get("capabilityDispositions") or [])
        if isinstance(d, dict) and d.get("disposition") == "retire" and d.get("targetId")
    ]
    if retired_targets:
        p1_sec = md_section(spec_md, r"pillar\s*1\b") or ""
        for r_id in retired_targets:
            for line in p1_sec.splitlines():
                if re.search(r"\bREQ-(?:FUNC|ENH)-\d+\b", line) and re.search(rf"\b{re.escape(r_id)}\b", line, re.IGNORECASE):
                    if not re.search(r"\b(?:retired?|deprecated?|excluded|out[- ]of[- ]scope)\b", line, re.IGNORECASE):
                        errors.append(
                            f"SD-GRILL-02: Capability `{r_id}` was marked `disposition: 'retire'` in "
                            f"specs/clarification_decisions.json, but appears as an active Pillar 1 requirement: `{line.strip()[:110]}`"
                        )

    decision_ids = [str(d.get("id")) for d in (clar.get("decisions") or []) if isinstance(d, dict) and d.get("id")]
    return errors, warnings, {
        "present": True,
        "clarificationStatus": c_status,
        "stagesSettled": clar.get("stagesSettled") or [],
        "decisionIds": decision_ids,
        "retiredTargets": retired_targets,
    }


def validate_clarification_ledger_for_stories(root: Path) -> tuple[list[str], list[str]]:
    """Enforce `SD-GRILL-03` during Stage 3 (`alm_jira_ado_bridge.py` `audit_backlog`):
    When `specs/gate_approvals.json` exists in interactive mode (or when `openFrontier` has unresolved
    `pre-stories`/`anytime` questions), user stories cannot pass Gate 3 until the `pre-stories` BA `grill-me`
    check/interview is settled."""
    errors: list[str] = []
    warnings: list[str] = []
    if is_autonomous_or_golden(root):
        return errors, warnings

    clar_path = root / "specs" / "clarification_decisions.json"
    interactive_enforced = gate_approvals_path(root).is_file()

    if clar_path.is_file():
        clar = read_json(clar_path)
        if isinstance(clar, dict):
            open_f = clar.get("openFrontier") or []
            story_open = [
                q for q in open_f
                if not isinstance(q, dict) or normalize_clarification_stage(q.get("stage")) in ("pre-stories", "anytime")
            ]
            if story_open:
                errors.append(
                    f"SD-GRILL-03: {len(story_open)} unresolved User-Story / BA Grill-Me question(s) remain in "
                    "`specs/clarification_decisions.json#openFrontier`. Present the `🔥 Grill-Me` questions to the "
                    "Business Analyst / human and run `clarification_interview.py --stage pre-stories --action record-round` "
                    "(or `--action accept-recommendations`) before finalizing Gate 3 user stories."
                )
                return errors, warnings
            settled = list(clar.get("stagesSettled") or [])
            if interactive_enforced and "pre-stories" not in settled:
                rep = build_clarification_frontier(root, stage="pre-stories")
                if rep["needsClarification"]:
                    errors.append(
                        f"SD-GRILL-03: Story-creation Grill-Me check (`--stage pre-stories`) found unsettled BA "
                        f"clarifications ({rep['triggerReasons']}). Run `clarification_interview.py --project-root \"{root}\" "
                        "--stage pre-stories --action detect`, engage the Business Analyst / human, and record their "
                        "answers before finalizing `backlog/user_stories.json`."
                    )
    elif interactive_enforced:
        rep = build_clarification_frontier(root, stage="pre-stories")
        if rep["needsClarification"]:
            errors.append(
                f"SD-GRILL-03: Story-creation Grill-Me check (`--stage pre-stories`) has NOT been run yet "
                f"(reasons={rep['triggerReasons']}). Run `clarification_interview.py --project-root \"{root}\" "
                "--stage pre-stories --action detect` and resolve BA clarifications before Gate 3."
            )
    return errors, warnings
