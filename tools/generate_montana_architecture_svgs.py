#!/usr/bin/env python3
# ruff: noqa: E501, UP022
"""Generate deterministic, dependency-free architecture maps for Montana.

The exhaustive maps contain one node for every file in their declared
manifest.  Python import edges are extracted with ``ast``; non-Python files
remain visible because configuration, evidence and documentation are part of
the delivered system even when they do not create import edges.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import html
import io
import json
import math
import subprocess
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
BASE_SHA = "f5d6434d20dffae62c9f03fbc12f68b03f48351b"
BASE_REF = BASE_SHA
OUT = ROOT / "docs" / "refactor"

# The delivery target is the tracked Montana tree plus these explicitly owned,
# reviewed additions.  Do not infer intent from arbitrary untracked debris.
INTENDED_ADDITIONS = (
    "docs/design-system/governance/change-impact.md",
    "docs/design-system/patterns/operator-evidence-and-retention.md",
    "src/cryodaq/core/annunciation.py",
    "src/cryodaq/gui/presentation_severity.py",
    "src/cryodaq/storage/_windows_secure_read.py",
    "tests/core/test_annunciation_protocol.py",
    "tests/gui/test_presentation_severity.py",
    "tests/storage/test_windows_secure_read.py",
    "docs/MONTANA_REFACTOR_REPORT.md",
    "tools/generate_montana_architecture_svgs.py",
    "tests/web/test_static_alarm_severity_contract.py",
)

COLORS = {
    "src": ("#17334d", "#8fd3ff"),
    "tests": ("#293e31", "#9ce5ad"),
    "config": ("#4a3a20", "#ffd27a"),
    "docs": ("#3d3152", "#d7b7ff"),
    "scripts": ("#49302b", "#ffb4a6"),
    "other": ("#30343b", "#d6d9df"),
}


def run(*args: str) -> str:
    return subprocess.run(args, cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode(
        "utf-8", errors="replace"
    )


def base_paths() -> list[str]:
    return sorted(run("git", "ls-tree", "-r", "--name-only", BASE_REF).splitlines())


def target_paths() -> list[str]:
    return sorted(set(run("git", "ls-files").splitlines()) | set(INTENDED_ADDITIONS))


_BASE_CONTENTS: dict[str, bytes] | None = None
_TARGET_CONTENTS: dict[str, bytes] = {}


def read_base(path: str) -> bytes:
    global _BASE_CONTENTS
    if _BASE_CONTENTS is None:
        archive = subprocess.run(
            ("git", "archive", "--format=tar", BASE_REF),
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tf:
            _BASE_CONTENTS = {
                member.name: (tf.extractfile(member).read() if member.isfile() else b"")
                for member in tf.getmembers()
                if member.isfile()
            }
    return _BASE_CONTENTS.get(path, b"")


def read_target(path: str) -> bytes:
    if path not in _TARGET_CONTENTS:
        p = ROOT / path
        _TARGET_CONTENTS[path] = p.read_bytes() if p.is_file() else b""
    return _TARGET_CONTENTS[path]


def text(content: bytes) -> str:
    return content.decode("utf-8", errors="replace")


def is_text(content: bytes) -> bool:
    if b"\x00" in content:
        return False
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def loc(content: bytes) -> int:
    return len(content.splitlines()) if is_text(content) else 0


def churn(old: bytes, new: bytes) -> int:
    if old == new:
        return 0
    if not is_text(old) or not is_text(new):
        return 0
    a, b = text(old).splitlines(), text(new).splitlines()
    return sum(
        max(i2 - i1, j2 - j1)
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes()
        if tag != "equal"
    )


def category(path: str) -> str:
    first = path.split("/", 1)[0]
    return first if first in COLORS else "other"


def python_module(path: str) -> str | None:
    if not path.endswith(".py"):
        return None
    parts = list(PurePosixPath(path).parts)
    if parts[0] == "src":
        parts = parts[1:]
    elif parts[0] != "tests":
        return None
    parts[-1] = parts[-1][:-3]
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def import_edges(paths: list[str], reader) -> set[tuple[str, str]]:
    modules = {m: p for p in paths if (m := python_module(p))}
    edges: set[tuple[str, str]] = set()
    for path in paths:
        module = python_module(path)
        if not module:
            continue
        try:
            tree = ast.parse(text(reader(path)), filename=path)
        except (SyntaxError, ValueError):
            continue
        package = module if path.endswith("/__init__.py") else module.rpartition(".")[0]
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    anchor = package.split(".") if package else []
                    anchor = anchor[: max(0, len(anchor) - node.level + 1)]
                    base = ".".join(anchor + ([base] if base else []))
                names = [base] + [f"{base}.{a.name}" for a in node.names if base]
            for name in names:
                probe = name
                while probe:
                    if probe in modules and modules[probe] != path:
                        edges.add((path, modules[probe]))
                        break
                    probe = probe.rpartition(".")[0]
    return edges


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def content_fingerprint(paths: list[str], reader) -> str:
    digest = hashlib.sha256()
    for path in paths:
        content = reader(path)
        digest.update(path.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b"\x00")
        digest.update(content)
    return digest.hexdigest()


def metadata(snapshot: str, paths: list[str], edge_count: int, reader) -> str:
    payload = {
        "generator": "tools/generate_montana_architecture_svgs.py",
        "base_ref": BASE_REF,
        "base_sha": BASE_SHA,
        "target_head_sha": run("git", "rev-parse", "HEAD").strip(),
        "snapshot": snapshot,
        "manifest_file_count": len(paths),
        "edge_count": edge_count,
        "manifest_sha256": hashlib.sha256("\n".join(paths).encode()).hexdigest(),
        "content_sha256": content_fingerprint(paths, reader),
        "generated_outputs_excluded": "docs/refactor/architecture-*.svg (self-referential generated files)",
        "metric_note": "text load = UTF-8 LOC plus internal import degree; binary files report bytes; Montana heat = text churn versus pinned baseline",
    }
    return esc(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def all_files_svg(snapshot: str, paths: list[str], reader, destination: Path) -> None:
    edges = import_edges(paths, reader)
    degree = {p: 0 for p in paths}
    for a, b in edges:
        degree[a] += 1
        degree[b] += 1

    groups: dict[str, list[str]] = {}
    for p in paths:
        key = p.split("/", 1)[0]
        groups.setdefault(key, []).append(p)

    columns = 4
    card_w, card_h, gap_x, gap_y = 320, 36, 34, 9
    band_w = card_w + gap_x
    margin, header = 60, 190
    ordered_groups = sorted(groups, key=lambda k: (-len(groups[k]), k))
    col_heights = [header] * columns
    boxes: dict[str, tuple[float, float, float, float]] = {}
    group_boxes: list[tuple[str, float, float, float, float, int]] = []
    for name in ordered_groups:
        col = min(range(columns), key=lambda i: col_heights[i])
        x = margin + col * band_w
        y = col_heights[col]
        items = sorted(groups[name])
        gh = 34 + len(items) * (card_h + gap_y) + 12
        group_boxes.append((name, x - 10, y - 28, card_w + 20, gh, len(items)))
        for p in items:
            boxes[p] = (x, y, card_w, card_h)
            y += card_h + gap_y
        col_heights[col] += gh + 25
    width = margin * 2 + columns * band_w
    height = max(col_heights) + 70

    title = (
        "CryoDAQ before Montana — exhaustive repository map"
        if snapshot == "before"
        else "CryoDAQ after Montana — exhaustive repository map"
    )
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
        f'<title id="title">{esc(title)}</title>',
        '<desc id="desc">Every intended repository file appears exactly once. Lines are Python imports. Larger dots indicate higher internal dependency degree; warm borders indicate Montana churn.</desc>',
        f"<metadata>{metadata(snapshot, paths, len(edges), reader)}</metadata>",
        '<defs><marker id="arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#607188"/></marker></defs>',
        '<rect width="100%" height="100%" fill="#0b1118"/>',
        f'<text x="60" y="62" fill="#f4f7fb" font-family="Segoe UI, sans-serif" font-size="30" font-weight="700">{esc(title)}</text>',
        f'<text x="60" y="96" fill="#aebaca" font-family="Segoe UI, sans-serif" font-size="15">{len(paths)} files • {len(edges)} internal Python imports • deterministic inventory</text>',
        '<g aria-label="Legend" font-family="Segoe UI, sans-serif" font-size="13"><text x="60" y="130" fill="#cbd5e1">Node: full path · L=lines · D=import degree · Δ=changed lines from master</text><text x="60" y="153" fill="#cbd5e1">Load hotspot: larger right dot. Montana change hotspot: amber/red border. Every path is searchable and has a tooltip.</text></g>',
    ]
    for name, x, y, w, h, count in group_boxes:
        out.append(
            f'<g class="cluster" aria-label="{esc(name)} cluster"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="#101a25" stroke="#2b3b4e"/><text x="{x + 12}" y="{y + 20}" fill="#91a4ba" font-family="Segoe UI, sans-serif" font-size="13" font-weight="700">{esc(name)} · {count}</text></g>'
        )
    out.append('<g class="import-edges" fill="none" stroke="#607188" stroke-opacity="0.12" stroke-width="0.8">')
    for a, b in sorted(edges):
        ax, ay, aw, ah = boxes[a]
        bx, by, bw, bh = boxes[b]
        out.append(
            f'<path d="M {ax + aw} {ay + ah / 2} C {ax + aw + 18} {ay + ah / 2}, {bx - 18} {by + bh / 2}, {bx} {by + bh / 2}"/>'
        )
    out.append("</g>")
    out.append('<g class="files" font-family="Consolas, monospace" font-size="8.5">')
    for p in paths:
        x, y, w, h = boxes[p]
        content = reader(p)
        binary = not is_text(content)
        lines = loc(content)
        delta = churn(read_base(p), content) if snapshot == "montana" else 0
        d = degree[p]
        fill, ink = COLORS[category(p)]
        border = "#e4572e" if delta >= 500 else "#f0a23a" if delta >= 100 else "#45576a"
        radius = min(10, 2.5 + math.sqrt(d))
        load = f"{len(content)} bytes (binary)" if binary else f"{lines} LOC"
        tooltip = f"{p} | {load} | internal degree {d}" + (f" | Montana churn {delta}" if snapshot == "montana" else "")
        metric = (f"B{len(content)} D{d}" if binary else f"L{lines} D{d}") + (
            f" delta={delta}" if snapshot == "montana" and delta else ""
        )
        display = p if len(p) <= 44 else p[:20] + "…" + p[-21:]
        out.append(
            f'<g class="file-node" data-path="{esc(p)}" data-loc="{lines}" data-degree="{d}" data-churn="{delta}" role="group" aria-label="{esc(tooltip)}"><title>{esc(tooltip)}</title><desc>Full repository path: {esc(p)}</desc><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="5" fill="{fill}" stroke="{border}" stroke-width="{2 if delta >= 100 else 1}"/><text x="{x + 8}" y="{y + 14}" fill="{ink}">{esc(display)}</text><text x="{x + 8}" y="{y + 28}" fill="#a9b6c5">{esc(metric)}</text><circle cx="{x + w - 12}" cy="{y + h / 2}" r="{radius:.1f}" fill="#69b9e8"><title>Dependency load: {d}</title></circle></g>'
        )
    out.extend(("</g>", "</svg>"))
    destination.write_text("\n".join(out), encoding="utf-8")


IMPORTANT_BEFORE = (
    "src/cryodaq/drivers/base.py",
    "src/cryodaq/drivers/instruments/keithley_2604b.py",
    "src/cryodaq/core/scheduler.py",
    "src/cryodaq/storage/sqlite_writer.py",
    "src/cryodaq/core/broker.py",
    "src/cryodaq/core/safety_manager.py",
    "src/cryodaq/core/alarm_v2.py",
    "src/cryodaq/engine.py",
    "src/cryodaq/core/zmq_bridge.py",
    "src/cryodaq/gui/app.py",
    "src/cryodaq/gui/shell/main_window_v2.py",
    "src/cryodaq/web/server.py",
    "src/cryodaq/web/rest_api.py",
    "src/cryodaq/agents/assistant/query/agent.py",
    "src/cryodaq/reporting/generator.py",
)

IMPORTANT_MONTANA = (
    "src/cryodaq/drivers/contracts.py",
    "src/cryodaq/drivers/registry.py",
    "src/cryodaq/channels/descriptors.py",
    "src/cryodaq/storage/channel_descriptors.py",
    "src/cryodaq/storage/_windows_secure_read.py",
    "src/cryodaq/core/scheduler.py",
    "src/cryodaq/storage/sqlite_writer.py",
    "src/cryodaq/core/broker.py",
    "src/cryodaq/core/safety_manager.py",
    "src/cryodaq/core/alarm_v2.py",
    "src/cryodaq/core/annunciation.py",
    "src/cryodaq/engine.py",
    "src/cryodaq/engine_wiring/persistence_authority_owner.py",
    "src/cryodaq/engine_wiring/operator_snapshot_production.py",
    "src/cryodaq/core/operator_snapshot_ingress.py",
    "src/cryodaq/core/zmq_bridge.py",
    "src/cryodaq/gui/shell/main_window_v2.py",
    "src/cryodaq/gui/dashboard/dashboard_view.py",
    "src/cryodaq/web/server.py",
    "src/cryodaq/web/rest_api.py",
    "src/cryodaq/agents/assistant/shared/engine_client.py",
    "src/cryodaq/agents/assistant/periodic_runtime.py",
    "src/cryodaq/reporting/generator.py",
)

EDGES_BEFORE = (
    (0, 1, "driver contract", "data"),
    (1, 2, "raw readings", "data"),
    (2, 3, "write first", "data"),
    (3, 4, "then publish", "data"),
    (4, 5, "safety feed", "control"),
    (5, 7, "state authority", "control"),
    (6, 7, "alarm evaluation", "control"),
    (7, 8, "telemetry / commands", "boundary"),
    (8, 9, "IPC", "boundary"),
    (9, 10, "UI ownership", "data"),
    (8, 11, "web transport", "boundary"),
    (11, 12, "strict REST facade", "boundary"),
    (7, 13, "in-process query", "data"),
    (4, 13, "broker observations", "data"),
    (3, 13, "durable observations", "data"),
    (3, 14, "persisted evidence", "data"),
)

EDGES_MONTANA = (
    (0, 1, "capability checked", "control"),
    (1, 2, "stable identity", "data"),
    (2, 3, "strict manifest authority", "data"),
    (4, 3, "anchored Windows read", "control"),
    (3, 5, "qualified reading", "data"),
    (5, 6, "write immediate", "data"),
    (6, 7, "publish after durability", "data"),
    (7, 8, "safety feed", "control"),
    (8, 9, "alarm truth", "control"),
    (9, 10, "exact activation", "control"),
    (8, 11, "state authority", "control"),
    (11, 12, "single persistence owner", "control"),
    (11, 13, "one snapshot owner", "data"),
    (13, 15, "revisioned PUB", "boundary"),
    (15, 14, "qualified ingress", "boundary"),
    (14, 16, "coherent store", "data"),
    (16, 17, "panoramic operator truth", "data"),
    (15, 18, "web transport", "boundary"),
    (18, 19, "strict REST facade", "boundary"),
    (15, 20, "allowlisted query", "boundary"),
    (15, 21, "private barrier / stream", "boundary"),
    (21, 22, "observational report", "data"),
    (6, 22, "durable evidence", "data"),
)


def important_svg(snapshot: str, paths: list[str], reader, destination: Path) -> None:
    wanted = IMPORTANT_BEFORE if snapshot == "before" else IMPORTANT_MONTANA
    missing = sorted(set(wanted) - set(paths))
    if missing:
        raise RuntimeError(f"important map selection missing from {snapshot}: {missing}")
    nodes = list(wanted)
    source_indices = {i: i for i in range(len(nodes))}
    raw_edges = EDGES_BEFORE if snapshot == "before" else EDGES_MONTANA
    edges = [(source_indices[a], source_indices[b], label, kind) for a, b, label, kind in raw_edges]
    cols, card_w, card_h = 4, 310, 92
    gap_x, gap_y, margin, header = 80, 80, 70, 215
    rows = math.ceil(len(nodes) / cols)
    width = margin * 2 + cols * card_w + (cols - 1) * gap_x
    height = header + rows * card_h + (rows - 1) * gap_y + 120
    pos = {
        i: (margin + (i % cols) * (card_w + gap_x), header + (i // cols) * (card_h + gap_y)) for i in range(len(nodes))
    }
    title = (
        "Before Montana: concentrated ownership and implicit seams"
        if snapshot == "before"
        else "After Montana: explicit authority, identity and observational boundaries"
    )
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
        f'<title id="title">{esc(title)}</title>',
        '<desc id="desc">Simplified architecture. Solid cyan lines carry data, red lines carry control or safety authority, and dashed violet lines cross process or trust boundaries.</desc>',
        f"<metadata>{metadata(snapshot + '-important', nodes, len(edges), reader)}</metadata>",
        '<defs><marker id="dataArrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#61c8f4"/></marker><marker id="controlArrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#ff7067"/></marker><marker id="boundaryArrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#c59cff"/></marker></defs>',
        '<rect width="100%" height="100%" fill="#0b1118"/>',
        f'<text x="70" y="58" fill="#f4f7fb" font-family="Segoe UI, sans-serif" font-size="31" font-weight="700">{esc(title)}</text>',
        '<text x="70" y="95" fill="#aebaca" font-family="Segoe UI, sans-serif" font-size="16">Selected load-bearing files; exhaustive companion map contains every repository file.</text>',
        '<g aria-label="Legend" font-family="Segoe UI, sans-serif" font-size="14"><line x1="70" y1="135" x2="120" y2="135" stroke="#61c8f4" stroke-width="3"/><text x="130" y="140" fill="#cbd5e1">data/evidence</text><line x1="290" y1="135" x2="340" y2="135" stroke="#ff7067" stroke-width="3"/><text x="350" y="140" fill="#cbd5e1">control/safety authority</text><line x1="570" y1="135" x2="620" y2="135" stroke="#c59cff" stroke-width="3" stroke-dasharray="7 5"/><text x="630" y="140" fill="#cbd5e1">process or trust boundary</text><text x="70" y="174" fill="#cbd5e1">Node metric: LOC and internal import degree. Amber/red border = high Montana churn.</text></g>',
        '<g class="architecture-edges" fill="none">',
    ]
    all_edges = import_edges(paths, reader)
    degree = {p: 0 for p in paths}
    for a, b in all_edges:
        degree[a] += 1
        degree[b] += 1
    for a, b, label, kind in edges:
        ax, ay = pos[a]
        bx, by = pos[b]
        color = {"data": "#61c8f4", "control": "#ff7067", "boundary": "#c59cff"}[kind]
        dash = ' stroke-dasharray="7 5"' if kind == "boundary" else ""
        x1, y1, x2, y2 = ax + card_w, ay + card_h / 2, bx, by + card_h / 2
        if b <= a or abs((a % cols) - (b % cols)) > 1:
            y1, y2 = ay + card_h, by
            x1, x2 = ax + card_w / 2, bx + card_w / 2
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        out.append(
            f'<path d="M{x1},{y1} C{mx},{y1} {mx},{y2} {x2},{y2}" stroke="{color}" stroke-width="2.2" marker-end="url(#{kind}Arrow)"{dash}><title>{esc(nodes[a])} → {esc(nodes[b])}: {esc(label)}</title></path><rect x="{mx - 44}" y="{my - 11}" width="88" height="18" rx="4" fill="#0b1118" opacity=".9"/><text x="{mx}" y="{my + 3}" text-anchor="middle" fill="{color}" font-family="Segoe UI, sans-serif" font-size="10">{esc(label)}</text>'
        )
    out.append('</g><g class="important-files" font-family="Segoe UI, sans-serif">')
    for i, p in enumerate(nodes):
        x, y = pos[i]
        content = reader(p)
        lines = loc(content)
        d = degree[p]
        delta = churn(read_base(p), content) if snapshot == "montana" else 0
        border = "#e4572e" if delta >= 500 else "#f0a23a" if delta >= 100 else "#48627a"
        tooltip = f"{p} | {lines} LOC | internal degree {d}" + (f" | churn {delta}" if snapshot == "montana" else "")
        out.append(
            f'<g class="file-node" data-path="{esc(p)}" role="group" aria-label="{esc(tooltip)}"><title>{esc(tooltip)}</title><rect x="{x}" y="{y}" width="{card_w}" height="{card_h}" rx="11" fill="#142230" stroke="{border}" stroke-width="2"/><text x="{x + 14}" y="{y + 27}" fill="#f1f5f9" font-size="12" font-weight="700">{esc(PurePosixPath(p).name)}</text><text x="{x + 14}" y="{y + 48}" fill="#aebaca" font-size="9.5">{esc(str(PurePosixPath(p).parent))}</text><text x="{x + 14}" y="{y + 72}" fill="#7dd3fc" font-size="11">{lines} LOC · degree {d}{f" · Δ {delta}" if delta else ""}</text></g>'
        )
    out.extend(("</g>", "</svg>"))
    destination.write_text("\n".join(out), encoding="utf-8")


def verify(path: Path, expected: list[str], exhaustive: bool) -> None:
    root = ET.parse(path).getroot()
    nodes = [e for e in root.iter() if e.tag.endswith("g") and e.attrib.get("class") == "file-node"]
    represented = [e.attrib["data-path"] for e in nodes]
    if len(represented) != len(set(represented)):
        raise RuntimeError(f"duplicate nodes in {path}")
    if exhaustive and represented != expected:
        missing = sorted(set(expected) - set(represented))
        extra = sorted(set(represented) - set(expected))
        raise RuntimeError(f"manifest mismatch in {path}: missing={missing}, extra={extra}")
    view_box = [float(v) for v in root.attrib["viewBox"].split()]
    if view_box[2] <= 0 or view_box[3] <= 0:
        raise RuntimeError(f"invalid viewBox in {path}")
    limits = {
        "x": view_box[2],
        "x1": view_box[2],
        "x2": view_box[2],
        "cx": view_box[2],
        "y": view_box[3],
        "y1": view_box[3],
        "y2": view_box[3],
        "cy": view_box[3],
    }
    for element in root.iter():
        for attribute, limit in limits.items():
            raw = element.attrib.get(attribute)
            if raw is None or raw.endswith("%"):
                continue
            coordinate = float(raw)
            if not 0 <= coordinate <= limit:
                raise RuntimeError(f"{attribute}={coordinate} outside viewBox in {path}")


def generate() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    before, montana = base_paths(), target_paths()
    outputs = (
        ("before", before, read_base, OUT / "architecture-before-all-files.svg", True),
        ("montana", montana, read_target, OUT / "architecture-montana-all-files.svg", True),
        ("before", before, read_base, OUT / "architecture-before-important.svg", False),
        ("montana", montana, read_target, OUT / "architecture-montana-important.svg", False),
    )
    for snapshot, paths, reader, path, exhaustive in outputs:
        (all_files_svg if exhaustive else important_svg)(snapshot, paths, reader, path)
        verify(path, paths, exhaustive)
        print(f"{path.relative_to(ROOT)}: {len(paths) if exhaustive else 'selected'} files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    generate()
