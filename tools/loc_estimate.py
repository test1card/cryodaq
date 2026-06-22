#!/usr/bin/env python3
"""Defensible SLOC counter for CryoDAQ cost estimation.

Counts code/comment/blank by category, with explicit exclusions for generated
data, vendored assets, logs and auto-generated artifacts so the base is not inflated.
"""
import os, sys, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Directories excluded wholesale (generated data, logs, artifacts, vcs, caches).
EXCLUDE_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "build", "dist",
    ".venv313", ".worktrees", ".tox", "site-packages", "egg-info", ".eggs",
    "data",            # 1.5G of generated measurement JSON
    "logs",            # 44M runtime logs
    "artifacts",       # 19M run artifacts / handoffs
    "graphify-out", "graphify-out.stale-pre-merge",  # generated knowledge graph
    "agentswarm",      # AI agent session logs (md/json), not product code
    ".omc", ".pytest_cache", ".mypy_cache", ".ruff_cache", "cooldown_v5",
    "yandex", "tsp", "vault", "Vault",
    ".swarm", ".scratch", ".claude", ".github_backup", ".idea", ".vscode",
}

# Specific files excluded (auto-generated / lock / backups).
EXCLUDE_FILE_NAMES = {
    "CHANGELOG.md",            # auto-generated changelog
    "requirements-lock.txt",   # lock file
    "skills-lock.json",        # lock file
    "THIRD_PARTY_NOTICES.md",  # generated notices
}
EXCLUDE_SUFFIXES_IN_NAME = (".local-backup", ".stale-pre-merge")

PROD_EXT = {".py"}
CONFIG_EXT = {".toml", ".yaml", ".yml", ".ini", ".cfg", ".json", ".bat", ".sh", ".ps1"}
DOC_EXT = {".md", ".rst", ".txt"}
WEB_EXT = {".html", ".css", ".js", ".ts", ".tsx", ".jsx"}

def categorize(path: Path):
    rel = path.relative_to(ROOT)
    parts = rel.parts
    ext = path.suffix.lower()
    # production vs tests vs tooling
    if ext == ".py":
        if parts[0] == "tests":
            return "tests_py"
        if parts[0] == "src":
            return "prod_py"
        if parts[0] in ("tools", "build_scripts", "scripts", "plugins"):
            return "tooling_py"
        return "other_py"
    if ext in CONFIG_EXT:
        return "config"
    if ext in DOC_EXT:
        return "docs"
    if ext in WEB_EXT:
        return "web"
    return None

def count_py(path):
    code = comment = blank = 0
    in_doc = False
    docq = None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return 0, 0, 0
    for ln in lines:
        s = ln.strip()
        if not s:
            blank += 1; continue
        if in_doc:
            comment += 1
            if docq in s:
                in_doc = False
            continue
        if s.startswith("#"):
            comment += 1; continue
        if s.startswith(('"""', "'''")):
            docq = s[:3]
            # single-line docstring?
            if len(s) > 3 and s.endswith(docq):
                comment += 1; continue
            in_doc = True; comment += 1; continue
        code += 1
    return code, comment, blank

def count_plain(path):
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return 0, 0
    code = sum(1 for l in lines if l.strip())
    blank = len(lines) - code
    return code, blank

agg = {}  # cat -> [files, code, comment, blank]
def add(cat, files, code, comment, blank):
    a = agg.setdefault(cat, [0,0,0,0])
    a[0]+=files; a[1]+=code; a[2]+=comment; a[3]+=blank

for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
    for fn in filenames:
        if fn in EXCLUDE_FILE_NAMES: continue
        if any(suf in fn for suf in EXCLUDE_SUFFIXES_IN_NAME): continue
        p = Path(dirpath)/fn
        cat = categorize(p)
        if cat is None: continue
        if p.suffix.lower()==".py":
            c,cm,b = count_py(p)
            add(cat,1,c,cm,b)
        else:
            c,b = count_plain(p)
            add(cat,1,c,0,b)

print(f"{'category':<14}{'files':>7}{'code':>9}{'comment':>9}{'blank':>8}")
tot=[0,0,0,0]
for cat in sorted(agg):
    f,c,cm,b = agg[cat]
    tot[0]+=f;tot[1]+=c;tot[2]+=cm;tot[3]+=b
    print(f"{cat:<14}{f:>7}{c:>9}{cm:>9}{b:>8}")
print(f"{'TOTAL':<14}{tot[0]:>7}{tot[1]:>9}{tot[2]:>9}{tot[3]:>8}")
print(json.dumps({k:dict(zip(['files','code','comment','blank'],v)) for k,v in agg.items()}))
