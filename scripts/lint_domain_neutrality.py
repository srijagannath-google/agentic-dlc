#!/usr/bin/env python3
"""Domain-neutrality, vendor-neutrality, and credential/path sanitization linter for agentic-dlc.

1. Fails (exit 1) if any business-domain literal from worked examples or vendor-specific methodology branding
   leaks into the generic parts of the plugin (`rules/`, `agents/`, `skills/`, `scripts/`, `_shared/`,
   `schemas/`, `docs/`, `README.md`, `plugin.json`, `bootstrap.*`, `push-to-github.sh`).
2. Fails (exit 1) if any credential pattern, workstation home path, corporate email domain, or committed
   runtime SQLite database (`.db` / `.sqlite`) appears anywhere in the repository (including `examples/` and
   `.docx` XML metadata).
3. Supports an optional external denylist via `DLC_EXTRA_FORBIDDEN_FILE` (one regex per line, `#` comments
   ignored) so teams can enforce organization-specific sanitization without committing sensitive tokens into
   source control.

Usage:  python3 scripts/lint_domain_neutrality.py [--plugin-root DIR] [--allow-file PATH ...]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile
from pathlib import Path

# 1. Worked-example domain literals and vendor-marketing phrases forbidden outside examples/
FORBIDDEN_CORE = [
    r"business-licensing-portal",
    r"leave-request-portal",
    r"frmbusinesslicense",
    r"tblbusinesslicense",
    r"rptbusinesslicense",
    r"qrybusinesslicense",
    r"command163",
    r"#002855",
    r"applicant-workspace-card",
    r"view-portal",
    r"agent roster",
    r"attestation & fees",
    r"first-time buyer",
    r"under-bonded",
    r"\bfein\b",
    r"\bbond\b",
    r"\bssn\b",  # PII examples should be described generically ("national/tax identifier")
]

# 2. Credential, workstation-path, and non-RFC-2606 email patterns forbidden EVERYWHERE
FORBIDDEN_REPO_WIDE = [
    r"\b[A-Za-z0-9._%+-]+@(?!localhost\b)(?![A-Za-z0-9.-]*\.(?:example|test|invalid|localhost|example\.(?:com|org|net|gov)|iam\.gserviceaccount\.com)\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    r"/Users/[A-Za-z0-9._-]+/",
    r"/home/(?!nonroot\b|appuser\b|runner\b|ubuntu\b|user\b)[A-Za-z0-9._-]+/",
    r"\bgh[pousr]_[A-Za-z0-9]{20,}\b",
    r"\bATATT3x[A-Za-z0-9_-]{16,}",
    r"Authorization:\s*Basic\s+[A-Za-z0-9+/=]{20,}",
]

GENERIC_DIRS = ["rules", "agents", "skills", "scripts", "_shared", "schemas", "docs"]
GENERIC_FILES = ["README.md", "plugin.json", "bootstrap.sh", "bootstrap.ps1", "push-to-github.sh"]
TEXT_EXT = {".md", ".py", ".json", ".txt", ".yaml", ".yml", ".sh", ".ps1", ".csv", ".html", ".css", ".js", ".sql", ".xsd"}


def _load_extra_patterns() -> list[str]:
    extra_file = os.environ.get("DLC_EXTRA_FORBIDDEN_FILE", "").strip()
    if not extra_file:
        return []
    p = Path(extra_file).expanduser()
    if not p.is_file():
        raise SystemExit(f"DLC_EXTRA_FORBIDDEN_FILE={extra_file} does not exist.")
    out: list[str] = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plugin-root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--allow-file", action="append", default=[], help="Relative paths to skip")
    args = ap.parse_args()
    root = Path(args.plugin_root).resolve()

    extra_repo = _load_extra_patterns()
    core_pattern = re.compile("|".join(FORBIDDEN_CORE), re.IGNORECASE)
    repo_pattern = re.compile("|".join(FORBIDDEN_REPO_WIDE + extra_repo), re.IGNORECASE)
    # Compare POSIX-style relative paths so the allowlist works identically on Windows, macOS and Linux.
    allow = {Path(a).as_posix() for a in args.allow_file}
    allow.add("scripts/lint_domain_neutrality.py")

    core_files: list[Path] = []
    for d in GENERIC_DIRS:
        p = root / d
        if p.exists():
            core_files += [f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in TEXT_EXT]
    core_files += [root / f for f in GENERIC_FILES if (root / f).exists()]

    hits = 0
    for f in sorted(set(core_files)):
        rel = f.relative_to(root).as_posix()
        if rel in allow:
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for m in core_pattern.finditer(line):
                hits += 1
                print(f"[CORE] {rel}:{n}: '{m.group(0)}'  | {line.strip()[:120]}")

    all_files = [
        f for f in sorted(root.rglob("*"))
        if f.is_file()
        and ".git" not in f.parts
        and "__pycache__" not in f.parts
        and not f.name.endswith(".denylist")
        and f.name != ".dlc_denylist"
    ]
    for f in all_files:
        rel = f.relative_to(root).as_posix()
        if rel in allow:
            continue
        for m in repo_pattern.finditer(rel):
            hits += 1
            print(f"[FILENAME] {rel}: '{m.group(0)}'")
        suf = f.suffix.lower()
        if suf in (".db", ".sqlite", ".sqlite3"):
            hits += 1
            print(f"[BINARY-DB] {rel}: runtime SQLite database files must not be committed (seed from schema.sql at startup)")
            continue
        if suf in TEXT_EXT or suf == ".svg":
            for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                for m in repo_pattern.finditer(line):
                    hits += 1
                    print(f"[REPO] {rel}:{n}: '{m.group(0)}'  | {line.strip()[:120]}")
        elif suf == ".docx":
            with zipfile.ZipFile(f, "r") as zf:
                for zname in zf.namelist():
                    if zname.endswith(".xml"):
                        ztxt = zf.read(zname).decode("utf-8", errors="replace")
                        for m in repo_pattern.finditer(ztxt):
                            hits += 1
                            print(f"[DOCX] {rel}#{zname}: '{m.group(0)}'")

    if hits:
        print(f"\nDomain-neutrality & sanitization lint FAILED: {hits} hit(s).")
        return 1
    print(f"Domain-neutrality & sanitization lint PASSED over {len(core_files)} core files and {len(all_files)} total repo files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
