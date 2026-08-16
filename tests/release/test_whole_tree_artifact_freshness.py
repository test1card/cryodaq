"""Release-time whole-tree artifact check (OB-006).

The registered whole-tree guards now run in the default-CI ``remaining``
partition; this release suite carries the remaining unregistered whole-tree
binding that still runs on a ``v*`` tag.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from functools import cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: Path) -> str:
    """Read required UTF-8 evidence; missing or invalid input must fail."""
    return path.read_text(encoding="utf-8")


def _svg_metadata(path: Path) -> dict[str, object]:
    root = ET.parse(path).getroot()
    records = [element for element in root if element.tag.endswith("metadata")]
    assert len(records) == 1 and records[0].text
    payload = json.loads(records[0].text)
    assert type(payload) is dict
    return payload


def _svg_nodes(path: Path) -> list[str]:
    root = ET.parse(path).getroot()
    return [
        element.attrib["data-path"]
        for element in root.iter()
        if element.tag.endswith("g") and element.attrib.get("class") == "file-node"
    ]


@cache
def _architecture_inventory() -> tuple[object, tuple[str, ...], dict[str, bytes]]:
    import tools.generate_montana_architecture_svgs as generator

    snapshot = generator.target_snapshot()
    paths = tuple(snapshot.paths)
    return snapshot, paths, {path: snapshot.read(path) for path in paths}


def test_checked_in_montana_architecture_svgs_match_frozen_index_snapshot(tmp_path: Path) -> None:
    """Narrowed to the one surviving architecture graph (manifest SVG decision).

    Previously checked both the exhaustive 1,085-file "all-files" map and the
    legible "important" map. The manifest kept only the latter — the
    all-files map is a provenance artifact, not a document a human or a weak
    model can read, and the two before/after comparison maps are pure
    campaign evidence. Only ``docs/architecture-montana-important.svg``
    (moved out of the campaign-named ``docs/refactor/``) ships in PR-A, so
    this is the only checked-in SVG this test can still verify.
    """
    import tools.generate_montana_architecture_svgs as generator

    snapshot, frozen_paths, contents = _architecture_inventory()
    paths = list(frozen_paths)
    reader = contents.__getitem__
    assert paths
    assert not any(generator._is_generated_output(path) for path in paths)

    important_svg = REPO_ROOT / "docs/architecture-montana-important.svg"
    important = list(generator.IMPORTANT_MONTANA)
    assert _svg_metadata(important_svg) == generator.metadata_payload(
        "montana-important",
        important,
        len(generator.EDGES_MONTANA),
        reader,
        snapshot,
    )
    assert _svg_nodes(important_svg) == important
    generator.verify(important_svg, important, exhaustive=False)
    rendered = tmp_path / important_svg.name
    generator.important_svg("montana", paths, reader, rendered, snapshot)
    generator.verify(rendered, important, exhaustive=False)
    assert rendered.read_bytes() == generator._git_bytes("show", ":docs/architecture-montana-important.svg")
