"""Doc-lint: CLAUDE.md module index must match the live src/cryodaq tree.

Two invariants, checked against the "### Индекс модулей" section only:

1. Forward — every live module (``src/cryodaq/**/*.py``, excluding
   ``__pycache__``, ``__init__.py`` and private ``_*`` modules) is listed.
2. Reverse — every ``src/cryodaq/...py`` path mentioned in the index
   exists on disk (no dead entries).
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "cryodaq"


def _index_section() -> str:
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    start = text.index("### Индекс модулей")
    # section ends at the next h2 heading
    end = re.search(r"^## ", text[start:], re.MULTILINE)
    return text[start : start + end.start()] if end else text[start:]


def _live_modules() -> list[str]:
    out = []
    for p in SRC.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        if p.name == "__init__.py" or p.name.startswith("_"):
            continue
        out.append(p.relative_to(REPO_ROOT).as_posix())
    return sorted(out)


def test_all_live_modules_indexed():
    section = _index_section()
    missing = [m for m in _live_modules() if m not in section]
    assert not missing, "Modules missing from CLAUDE.md index:\n" + "\n".join(missing)


def test_no_dead_paths_in_index():
    section = _index_section()
    mentioned = set(re.findall(r"src/cryodaq/[\w./]+\.py", section))
    dead = sorted(p for p in mentioned if not (REPO_ROOT / p).is_file())
    assert not dead, "Dead paths in CLAUDE.md index:\n" + "\n".join(dead)
