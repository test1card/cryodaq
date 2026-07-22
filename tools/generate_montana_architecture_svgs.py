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
import json
import math
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
BASE_SHA = "f5d6434d20dffae62c9f03fbc12f68b03f48351b"
BASE_REF = BASE_SHA
OUT = ROOT / "docs" / "refactor"

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
        "utf-8", errors="strict"
    )


def _git_bytes(*args: str, env: dict[str, str] | None = None) -> bytes:
    return subprocess.run(
        ("git", *args),
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    ).stdout


def _is_generated_output(path: str) -> bool:
    return PurePosixPath(path).match("docs/refactor/architecture-*.svg")


@dataclass(frozen=True, slots=True)
class GitEntry:
    path: str
    mode: str
    object_type: str
    oid: str

    @property
    def kind(self) -> str:
        if self.mode == "120000":
            return "symlink"
        if self.mode == "160000" or self.object_type == "commit":
            return "gitlink"
        return "blob"


@dataclass(frozen=True, slots=True)
class GitSnapshot:
    """One immutable Git tree and its exact object bytes.

    Generated architecture SVGs are omitted before the tree is created.  That
    prevents a self-reference while keeping every represented path bound to a
    real Git object, including symlink target blobs and gitlink commit IDs.
    """

    tree_sha: str
    source: str
    entries: tuple[GitEntry, ...]
    blobs: dict[str, bytes]

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(entry.path for entry in self.entries)

    def entry(self, path: str) -> GitEntry:
        for entry in self.entries:
            if entry.path == path:
                return entry
        raise KeyError(path)

    def read(self, path: str) -> bytes:
        entry = self.entry(path)
        if entry.kind == "gitlink":
            return entry.oid.encode("ascii")
        return self.blobs[entry.oid]

    def object_manifest_sha256(self, paths: list[str] | tuple[str, ...] | None = None) -> str:
        selected = self.paths if paths is None else tuple(paths)
        digest = hashlib.sha256()
        for path in selected:
            entry = self.entry(path)
            encoded = path.encode("utf-8", errors="strict")
            for value in (entry.mode.encode("ascii"), entry.object_type.encode("ascii"), entry.oid.encode("ascii")):
                digest.update(str(len(value)).encode("ascii"))
                digest.update(b":")
                digest.update(value)
            digest.update(str(len(encoded)).encode("ascii"))
            digest.update(b":")
            digest.update(encoded)
            digest.update(b"\x00")
        return digest.hexdigest()


def _tree_entries(tree_sha: str) -> tuple[GitEntry, ...]:
    raw = _git_bytes("ls-tree", "-rz", "--full-tree", tree_sha)
    entries: list[GitEntry] = []
    for record in raw.split(b"\x00"):
        if not record:
            continue
        try:
            header, raw_path = record.split(b"\t", 1)
            mode, object_type, oid = header.decode("ascii").split(" ", 2)
            path = raw_path.decode("utf-8", errors="strict")
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError("Git tree contains an undecodable architecture path or entry") from exc
        entries.append(GitEntry(path=path, mode=mode, object_type=object_type, oid=oid))
    return tuple(sorted(entries, key=lambda item: item.path))


def _cat_blobs(oids: tuple[str, ...]) -> dict[str, bytes]:
    requested = tuple(dict.fromkeys(oids))
    if not requested:
        return {}
    completed = subprocess.run(
        ("git", "cat-file", "--batch"),
        cwd=ROOT,
        input=b"".join(oid.encode("ascii") + b"\n" for oid in requested),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    raw = completed.stdout
    offset = 0
    blobs: dict[str, bytes] = {}
    for expected_oid in requested:
        header_end = raw.find(b"\n", offset)
        if header_end < 0:
            raise RuntimeError("truncated git cat-file batch header")
        fields = raw[offset:header_end].split()
        if len(fields) != 3:
            raise RuntimeError(f"unexpected git cat-file header: {raw[offset:header_end]!r}")
        actual_oid, object_type, raw_size = fields
        if actual_oid.decode("ascii") != expected_oid or object_type != b"blob":
            raise RuntimeError(f"unexpected Git object for {expected_oid}")
        size = int(raw_size)
        content_start = header_end + 1
        content_end = content_start + size
        if content_end >= len(raw) or raw[content_end : content_end + 1] != b"\n":
            raise RuntimeError(f"truncated git cat-file payload for {expected_oid}")
        blobs[expected_oid] = raw[content_start:content_end]
        offset = content_end + 1
    if offset != len(raw):
        raise RuntimeError("unexpected trailing bytes from git cat-file batch")
    return blobs


def _index_entries() -> tuple[GitEntry, ...]:
    """Read one coherent staged-index manifest without refreshing or locking it."""

    raw = _git_bytes("ls-files", "--stage", "-z")
    entries: list[GitEntry] = []
    for record in raw.split(b"\x00"):
        if not record:
            continue
        try:
            header, raw_path = record.split(b"\t", 1)
            mode, oid, stage = header.decode("ascii").split(" ", 2)
            path = raw_path.decode("utf-8", errors="strict")
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError("Git index contains an undecodable architecture entry") from exc
        if stage != "0":
            raise RuntimeError(f"unmerged Git index entry cannot be diagrammed: {path}")
        if set(oid) == {"0"}:
            raise RuntimeError(f"intent-to-add Git index entry has no frozen blob: {path}")
        object_type = "commit" if mode == "160000" else "blob"
        entries.append(GitEntry(path=path, mode=mode, object_type=object_type, oid=oid))
    return tuple(sorted(entries, key=lambda item: item.path))


def _tree_object_sha(entries: tuple[GitEntry, ...]) -> str:
    """Compute Git's canonical root-tree object ID without writing an object."""

    object_format = _git_bytes("rev-parse", "--show-object-format").decode("ascii").strip()
    if object_format not in {"sha1", "sha256"}:
        raise RuntimeError(f"unsupported Git object format: {object_format}")
    oid_size = 20 if object_format == "sha1" else 32
    root: dict[bytes, object] = {}
    for entry in entries:
        parts = entry.path.encode("utf-8", errors="strict").split(b"/")
        node = root
        for part in parts[:-1]:
            existing = node.setdefault(part, {})
            if not isinstance(existing, dict):
                raise RuntimeError(f"Git path collides with a file: {entry.path}")
            node = existing
        leaf = parts[-1]
        if leaf in node:
            raise RuntimeError(f"duplicate Git path in architecture tree: {entry.path}")
        node[leaf] = entry

    def hash_node(node: dict[bytes, object]) -> str:
        records: list[tuple[bytes, bytes]] = []
        for name, value in node.items():
            if isinstance(value, dict):
                mode = b"40000"
                oid = bytes.fromhex(hash_node(value))
                order = name + b"/"
            else:
                if not isinstance(value, GitEntry):
                    raise RuntimeError("invalid architecture tree entry")
                mode = value.mode.encode("ascii")
                oid = bytes.fromhex(value.oid)
                order = name
            if len(oid) != oid_size:
                raise RuntimeError("Git object ID length does not match repository format")
            records.append((order, mode + b" " + name + b"\x00" + oid))
        body = b"".join(record for _order, record in sorted(records, key=lambda item: item[0]))
        digest = hashlib.new(object_format)
        digest.update(b"tree " + str(len(body)).encode("ascii") + b"\x00" + body)
        return digest.hexdigest()

    return hash_node(root)


def _snapshot_from_entries(entries: tuple[GitEntry, ...], source: str) -> GitSnapshot:
    filtered = tuple(entry for entry in entries if not _is_generated_output(entry.path))
    tree_sha = _tree_object_sha(filtered)
    blobs = _cat_blobs(tuple(entry.oid for entry in filtered if entry.kind != "gitlink"))
    return GitSnapshot(tree_sha=tree_sha, source=source, entries=filtered, blobs=blobs)


def _load_snapshot(treeish: str, source: str) -> GitSnapshot:
    tree_sha = _git_bytes("rev-parse", f"{treeish}^{{tree}}").decode("ascii").strip()
    entries = _tree_entries(tree_sha)
    return _snapshot_from_entries(entries, source)


_BASE_SNAPSHOT: GitSnapshot | None = None
_TARGET_SNAPSHOT: GitSnapshot | None = None


def base_snapshot(*, refresh: bool = False) -> GitSnapshot:
    global _BASE_SNAPSHOT
    if refresh or _BASE_SNAPSHOT is None:
        _BASE_SNAPSHOT = _load_snapshot(BASE_REF, f"git:{BASE_REF}")
    return _BASE_SNAPSHOT


def target_snapshot(*, refresh: bool = False) -> GitSnapshot:
    """Freeze the exact Git index, excluding generated diagram outputs.

    Untracked and unstaged worktree bytes are intentionally absent.  Once this
    object exists, later index or worktree edits cannot alter the render.
    """

    global _TARGET_SNAPSHOT
    if refresh or _TARGET_SNAPSHOT is None:
        entries = _index_entries()
        _TARGET_SNAPSHOT = _snapshot_from_entries(entries, "git-index")
    return _TARGET_SNAPSHOT


def base_paths() -> list[str]:
    return list(base_snapshot().paths)


def target_paths() -> list[str]:
    return list(target_snapshot().paths)


def read_base(path: str) -> bytes:
    try:
        return base_snapshot().read(path)
    except KeyError:
        # A Montana-only path has no baseline blob; churn is its full text.
        return b""


def read_target(path: str) -> bytes:
    return target_snapshot().read(path)


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


def import_edges(
    paths: list[str],
    reader,
    snapshot_info: GitSnapshot | None = None,
) -> set[tuple[str, str]]:
    modules = {m: p for p in paths if (m := python_module(p))}
    edges: set[tuple[str, str]] = set()
    for path in paths:
        module = python_module(path)
        if not module:
            continue
        if snapshot_info is not None and snapshot_info.entry(path).kind != "blob":
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
        if is_text(content):
            content = content.replace(b"\r\n", b"\n")
        digest.update(path.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b"\x00")
        digest.update(content)
    return digest.hexdigest()


def metadata_payload(
    snapshot: str,
    paths: list[str],
    edge_count: int,
    reader,
    snapshot_info: GitSnapshot | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "generator": "tools/generate_montana_architecture_svgs.py",
        "base_ref": BASE_REF,
        "base_sha": BASE_SHA,
        "snapshot": snapshot,
        "manifest_file_count": len(paths),
        "edge_count": edge_count,
        "manifest_sha256": hashlib.sha256("\n".join(paths).encode()).hexdigest(),
        "content_sha256": content_fingerprint(paths, reader),
        "generated_outputs_excluded": "docs/refactor/architecture-*.svg (self-referential generated files)",
        "metric_note": "text load = UTF-8 LOC plus internal import degree; binary files report bytes; Montana heat = text churn versus pinned baseline",
    }
    if snapshot_info is not None:
        payload.update(
            {
                "source_tree_sha": snapshot_info.tree_sha,
                "source_tree_file_count": len(snapshot_info.paths),
                "snapshot_source": snapshot_info.source,
                "selected_object_manifest_sha256": snapshot_info.object_manifest_sha256(paths),
            }
        )
    return payload


def metadata(
    snapshot: str,
    paths: list[str],
    edge_count: int,
    reader,
    snapshot_info: GitSnapshot | None = None,
) -> str:
    payload = metadata_payload(snapshot, paths, edge_count, reader, snapshot_info)
    return esc(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def all_files_svg(
    snapshot: str,
    paths: list[str],
    reader,
    destination: Path,
    snapshot_info: GitSnapshot | None = None,
) -> None:
    edges = import_edges(paths, reader, snapshot_info)
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
        else "CryoDAQ Montana candidate — exhaustive repository map"
    )
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
        f'<title id="title">{esc(title)}</title>',
        '<desc id="desc">Every intended repository file appears exactly once. Lines are Python imports. Larger dots indicate higher internal dependency degree; warm borders indicate Montana churn.</desc>',
        f"<metadata>{metadata(snapshot, paths, len(edges), reader, snapshot_info)}</metadata>",
        '<defs><marker id="arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#607188"/></marker></defs>',
        '<rect width="100%" height="100%" fill="#0b1118"/>',
        f'<text x="60" y="62" fill="#f4f7fb" font-family="Segoe UI, sans-serif" font-size="30" font-weight="700">{esc(title)}</text>',
        f'<text x="60" y="96" fill="#aebaca" font-family="Segoe UI, sans-serif" font-size="15">{len(paths)} files • {len(edges)} internal Python imports • deterministic inventory</text>',
        '<g aria-label="Legend" font-family="Segoe UI, sans-serif" font-size="13"><text x="60" y="130" fill="#cbd5e1">Node: full path · L=lines · D=internal import degree · Δ=changed text lines from pinned v0.64.1 baseline</text><text x="60" y="153" fill="#cbd5e1">Larger right dot means more internal import edges, not runtime CPU load. Amber/red border means source churn, not defect severity. Every path is searchable and has a tooltip.</text></g>',
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
        lines = loc(content)
        delta = churn(read_base(p), content) if snapshot == "montana" else 0
        d = degree[p]
        fill, ink = COLORS[category(p)]
        border = "#e4572e" if delta >= 500 else "#f0a23a" if delta >= 100 else "#45576a"
        radius = min(10, 2.5 + math.sqrt(d))
        entry = snapshot_info.entry(p) if snapshot_info is not None else None
        kind = entry.kind if entry is not None else ("binary" if not is_text(content) else "text")
        if kind == "symlink":
            target = content.decode("utf-8", errors="replace")
            lines = 0
            load = f"symlink to {target}"
            metric_prefix = f"LINK {target}"
        elif kind == "gitlink":
            oid = entry.oid if entry is not None else content.decode("ascii")
            lines = 0
            load = f"gitlink commit {oid}"
            metric_prefix = f"GITLINK {oid[:12]}"
        elif not is_text(content):
            kind = "binary"
            load = f"{len(content)} bytes (binary)"
            metric_prefix = f"B{len(content)}"
        else:
            kind = "text"
            load = f"{lines} LOC"
            metric_prefix = f"L{lines}"
        tooltip = f"{p} | {load} | internal degree {d}" + (f" | Montana churn {delta}" if snapshot == "montana" else "")
        metric = f"{metric_prefix} D{d}" + (f" delta={delta}" if snapshot == "montana" and delta else "")
        display = p if len(p) <= 44 else p[:20] + "…" + p[-21:]
        out.append(
            f'<g class="file-node" data-path="{esc(p)}" data-kind="{kind}" data-loc="{lines}" data-degree="{d}" data-churn="{delta}" role="group" aria-label="{esc(tooltip)}"><title>{esc(tooltip)}</title><desc>Full repository path: {esc(p)}</desc><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="5" fill="{fill}" stroke="{border}" stroke-width="{2 if delta >= 100 else 1}"/><text x="{x + 8}" y="{y + 14}" fill="{ink}">{esc(display)}</text><text x="{x + 8}" y="{y + 28}" fill="#a9b6c5">{esc(metric)}</text><circle cx="{x + w - 12}" cy="{y + h / 2}" r="{radius:.1f}" fill="#69b9e8"><title>Dependency load: {d}</title></circle></g>'
        )
    out.extend(("</g>", "</svg>"))
    destination.write_text("\n".join(out), encoding="utf-8", newline="\n")


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
    "src/cryodaq/core/experiment.py",
    "src/cryodaq/engine_wiring/experiment_recording_owner.py",
    "src/cryodaq/engine_wiring/recording_lifecycle_feed.py",
    "src/cryodaq/storage/parquet_archive.py",
    "src/cryodaq/storage/cold_rotation.py",
    "src/cryodaq/storage/archive_reader.py",
    "src/cryodaq/engine.py",
    "src/cryodaq/engine_wiring/persistence_authority_owner.py",
    "src/cryodaq/storage/operator_snapshot_revision.py",
    "src/cryodaq/engine_wiring/operator_snapshot_production.py",
    "src/cryodaq/core/operator_snapshot_ingress.py",
    "src/cryodaq/core/zmq_bridge.py",
    "src/cryodaq/gui/state/operator_snapshot_ingress.py",
    "src/cryodaq/gui/shell/main_window_v2.py",
    "src/cryodaq/gui/dashboard/dashboard_view.py",
    "src/cryodaq/launcher.py",
    "src/cryodaq/gui/tray_status.py",
    "src/cryodaq/web/server.py",
    "src/cryodaq/web/rest_api.py",
    "src/cryodaq/agents/assistant/shared/engine_client.py",
    "src/cryodaq/agents/assistant/periodic_runtime.py",
    "src/cryodaq/report_process.py",
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
    (0, 1, "declared capabilities", "control"),
    (1, 5, "allowlisted drivers", "control"),
    (2, 3, "descriptor schema", "data"),
    (4, 3, "anchored Windows read", "control"),
    (3, 5, "qualified identity", "data"),
    (5, 6, "persist first", "data"),
    (6, 7, "receipt-authorized publish", "data"),
    (7, 8, "safety feed", "control"),
    (8, 9, "safety context", "control"),
    (9, 10, "exact activation", "control"),
    (11, 12, "journaled lifecycle", "control"),
    (12, 13, "recording outcome", "data"),
    (6, 15, "verified hot cut", "data"),
    (15, 14, "verified Parquet", "data"),
    (15, 16, "complete archive", "data"),
    (6, 16, "hot + cold union", "data"),
    (8, 17, "safety authority", "control"),
    (11, 17, "experiment commands", "control"),
    (17, 18, "persistence outcomes", "data"),
    (13, 20, "recording truth", "data"),
    (18, 20, "persistence truth", "data"),
    (8, 20, "safety truth", "data"),
    (20, 19, "allocate revision", "data"),
    (20, 22, "revisioned PUB", "boundary"),
    (22, 21, "snapshot frames", "boundary"),
    (21, 23, "bounded queue", "boundary"),
    (23, 24, "GUI-thread Store", "data"),
    (24, 25, "panoramic truth", "data"),
    (26, 24, "owns GUI lifecycle", "control"),
    (26, 27, "fail-visible shutdown", "data"),
    (22, 28, "monitoring transport", "boundary"),
    (28, 29, "strict REST facade", "boundary"),
    (22, 30, "allowlisted query", "boundary"),
    (30, 31, "observational stream", "boundary"),
    (31, 32, "bounded child", "boundary"),
    (32, 33, "render request", "data"),
    (16, 33, "durable evidence", "data"),
)


def important_svg(
    snapshot: str,
    paths: list[str],
    reader,
    destination: Path,
    snapshot_info: GitSnapshot | None = None,
) -> None:
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
        else "Montana candidate: explicit authority, identity and observational boundaries"
    )
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
        f'<title id="title">{esc(title)}</title>',
        '<desc id="desc">Simplified logical architecture. Solid cyan lines carry data or evidence, red lines carry control or safety authority, and dashed violet lines cross process or trust boundaries. Arrows are reviewed responsibility flows, not a claim that every relation is a direct Python import.</desc>',
        f"<metadata>{metadata(snapshot + '-important', nodes, len(edges), reader, snapshot_info)}</metadata>",
        '<defs><marker id="dataArrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#61c8f4"/></marker><marker id="controlArrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#ff7067"/></marker><marker id="boundaryArrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#c59cff"/></marker></defs>',
        '<rect width="100%" height="100%" fill="#0b1118"/>',
        f'<text x="70" y="58" fill="#f4f7fb" font-family="Segoe UI, sans-serif" font-size="31" font-weight="700">{esc(title)}</text>',
        '<text x="70" y="95" fill="#aebaca" font-family="Segoe UI, sans-serif" font-size="16">Selected load-bearing files; exhaustive companion map contains every repository file.</text>',
        '<g aria-label="Legend" font-family="Segoe UI, sans-serif" font-size="14"><line x1="70" y1="135" x2="120" y2="135" stroke="#61c8f4" stroke-width="3"/><text x="130" y="140" fill="#cbd5e1">data/evidence</text><line x1="290" y1="135" x2="340" y2="135" stroke="#ff7067" stroke-width="3"/><text x="350" y="140" fill="#cbd5e1">control/safety authority</text><line x1="570" y1="135" x2="620" y2="135" stroke="#c59cff" stroke-width="3" stroke-dasharray="7 5"/><text x="630" y="140" fill="#cbd5e1">process or trust boundary</text><text x="70" y="174" fill="#cbd5e1">Node metric: LOC and internal import degree. Amber/red border = high Montana churn.</text></g>',
        '<g class="architecture-edges" fill="none">',
    ]
    all_edges = import_edges(paths, reader, snapshot_info)
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
        kind = snapshot_info.entry(p).kind if snapshot_info is not None else "text"
        out.append(
            f'<g class="file-node" data-path="{esc(p)}" data-kind="{kind}" role="group" aria-label="{esc(tooltip)}"><title>{esc(tooltip)}</title><rect x="{x}" y="{y}" width="{card_w}" height="{card_h}" rx="11" fill="#142230" stroke="{border}" stroke-width="2"/><text x="{x + 14}" y="{y + 27}" fill="#f1f5f9" font-size="12" font-weight="700">{esc(PurePosixPath(p).name)}</text><text x="{x + 14}" y="{y + 48}" fill="#aebaca" font-size="9.5">{esc(str(PurePosixPath(p).parent))}</text><text x="{x + 14}" y="{y + 72}" fill="#7dd3fc" font-size="11">{lines} LOC · degree {d}{f" · Δ {delta}" if delta else ""}</text></g>'
        )
    out.extend(("</g>", "</svg>"))
    destination.write_text("\n".join(out), encoding="utf-8", newline="\n")


def verify(path: Path, expected: list[str], exhaustive: bool) -> None:
    root = ET.parse(path).getroot()
    nodes = [e for e in root.iter() if e.tag.endswith("g") and e.attrib.get("class") == "file-node"]
    represented = [e.attrib["data-path"] for e in nodes]
    if any(_is_generated_output(item) for item in represented):
        raise RuntimeError(f"generated output included in {path}")
    if len(represented) != len(set(represented)):
        raise RuntimeError(f"duplicate nodes in {path}")
    if represented != expected:
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
    """Render atomically from one baseline tree and one frozen Git-index tree."""

    OUT.mkdir(parents=True, exist_ok=True)
    before_snapshot = base_snapshot(refresh=True)
    montana_snapshot = target_snapshot(refresh=True)
    outputs = (
        ("before", before_snapshot, OUT / "architecture-before-all-files.svg", True),
        ("montana", montana_snapshot, OUT / "architecture-montana-all-files.svg", True),
        ("before", before_snapshot, OUT / "architecture-before-important.svg", False),
        ("montana", montana_snapshot, OUT / "architecture-montana-important.svg", False),
    )
    with tempfile.TemporaryDirectory(prefix="architecture-render-", dir=OUT) as temporary:
        rendered: list[tuple[Path, Path, str, int | str]] = []
        temporary_root = Path(temporary)
        for snapshot, frozen, path, exhaustive in outputs:
            paths = list(frozen.paths)
            reader = frozen.read
            temporary_path = temporary_root / path.name
            (all_files_svg if exhaustive else important_svg)(
                snapshot,
                paths,
                reader,
                temporary_path,
                frozen,
            )
            expected = paths if exhaustive else list(IMPORTANT_BEFORE if snapshot == "before" else IMPORTANT_MONTANA)
            verify(temporary_path, expected, exhaustive)
            rendered.append(
                (temporary_path, path, path.relative_to(ROOT).as_posix(), len(paths) if exhaustive else "selected")
            )
        for temporary_path, path, _label, _count in rendered:
            temporary_path.replace(path)
        for _temporary_path, _path, label, count in rendered:
            print(f"{label}: {count} files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    generate()
