#!/usr/bin/env python3
"""Domain-neutrality and PII/customer-sanitization linter for the agentic-dlc plugin.

1. Fails (exit 1) if any business-domain literal from worked examples leaks into the generic parts of the
   plugin (rules/, agents/, skills/, scripts/, _shared/, schemas/, docs/, README.md, plugin.json, bootstrap.*).
2. Fails (exit 1) if any customer/organization/employee/host-path token (including inside examples/, .docx
   XML metadata/documents, or SQLite .db tables) appears anywhere in the repository.

Usage:  python3 scripts/lint_domain_neutrality.py [--plugin-root DIR] [--allow-file PATH ...]
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import zipfile
from pathlib import Path

# 1. Domain literals forbidden outside examples/
FORBIDDEN_CORE = [
    r"timber", r"\bidnr\b", r"\bilcs\b", r"surety", r"harvest", r"\bplss\b", r"pocket card", r"agent card",
    r"conservation police", r"township", r"\brange/section\b", r"prairie oak", r"\$125\b", r"\$250\b",
    r"\$15\.00", r"\$8,?500\b", r"\$3,?500\b", r"\$10,000\b", r"\$1,000\b", r"\$85,000", r"ctas", r"ictasledger",
    r"80-byte", r"\biitaa\b", r"illinois", r"5-tab", r"five-tab", r"triage queue", r"licensing supervisor",
    r"frmtimber", r"tbltimber", r"rpttimber", r"qrytimber", r"command163",
    r"#002855", r"applicant-workspace-card", r"view-portal", r"state\.harvestfees", r"buyer profile",
    r"agent roster", r"attestation & fees", r"first-time buyer", r"under-bonded", r"\bfein\b", r"\bbond\b",
    r"\bssn\b",
]

# 2. Organization, customer, employee, and host-path tokens forbidden EVERYWHERE (including examples/)
FORBIDDEN_REPO_WIDE = [
    r"\bdoit\b", r"doit-", r"\.doit\.", r"\billinois\b", r"\bidnr\b", r"\bidoa\b", r"\biita\b", r"\biitaa\b",
    r"\bilcs\b", r"\bsled\b", r"timber", r"caregiver", r"larison", r"deborah", r"corpagent", r"srijagannath",
    r"sangamon", r"shawnee", r"peoria", r"carbondale", r"public_sector", r"acolver", r"slujan", r"bradburns",
]

GENERIC_DIRS = ["rules", "agents", "skills", "scripts", "_shared", "schemas", "docs"]
GENERIC_FILES = ["README.md", "plugin.json", "bootstrap.sh", "bootstrap.ps1", "push-to-github.sh"]
TEXT_EXT = {".md", ".py", ".json", ".txt", ".yaml", ".yml", ".sh", ".ps1", ".csv", ".html", ".css", ".js", ".sql", ".xsd"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plugin-root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--allow-file", action="append", default=[], help="Relative paths to skip")
    args = ap.parse_args()
    root = Path(args.plugin_root).resolve()
    core_pattern = re.compile("|".join(FORBIDDEN_CORE), re.IGNORECASE)
    repo_pattern = re.compile("|".join(FORBIDDEN_REPO_WIDE), re.IGNORECASE)
    allow = {str(Path(a)) for a in args.allow_file}
    allow.add("scripts/lint_domain_neutrality.py")

    core_files: list[Path] = []
    for d in GENERIC_DIRS:
        p = root / d
        if p.exists():
            core_files += [f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in TEXT_EXT]
    core_files += [root / f for f in GENERIC_FILES if (root / f).exists()]

    hits = 0
    for f in sorted(set(core_files)):
        rel = str(f.relative_to(root))
        if rel in allow:
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for m in core_pattern.finditer(line):
                hits += 1
                print(f"[CORE] {rel}:{n}: '{m.group(0)}'  | {line.strip()[:120]}")

    all_files = [
        f for f in sorted(root.rglob("*"))
        if f.is_file() and ".git" not in f.parts and "__pycache__" not in f.parts
    ]
    for f in all_files:
        rel = str(f.relative_to(root))
        if rel in allow:
            continue
        for m in repo_pattern.finditer(rel):
            hits += 1
            print(f"[FILENAME] {rel}: '{m.group(0)}'")
        suf = f.suffix.lower()
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
        elif suf in (".db", ".sqlite"):
            con = sqlite3.connect(str(f))
            cur = con.cursor()
            tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            for t in tables:
                for m in repo_pattern.finditer(t):
                    hits += 1
                    print(f"[SQLITE-TABLE] {rel}#{t}: '{m.group(0)}'")
                rows = cur.execute(f"SELECT * FROM {t}").fetchall()
                for row in rows:
                    blob = " ".join(str(c) for c in row if c is not None)
                    for m in repo_pattern.finditer(blob):
                        hits += 1
                        print(f"[SQLITE-ROW] {rel}#{t}: '{m.group(0)}' | {blob[:100]}")
            con.close()

    if hits:
        print(f"\nDomain-neutrality & sanitization lint FAILED: {hits} hit(s).")
        return 1
    print(f"Domain-neutrality & sanitization lint PASSED over {len(core_files)} core files and {len(all_files)} total repo files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
