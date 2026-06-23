"""F31 H1 — verify the engine export reads summary_metadata, not summary."""

from __future__ import annotations

from cryodaq.engine import _build_experiment_export


def test_summary_metadata_key_populates_export():
    """The extracted export builder must read ``_metadata["summary_metadata"]``.

    metadata.json's canonical key is ``summary_metadata``; the bare ``summary``
    key is empty, which would produce vault notes with empty ## Summary blocks.
    This exercises the PRODUCTION builder, so a revert to the wrong key fails here.
    """
    exp_info = {
        "experiment_id": "abc12345",
        "title": "t",
        "sample": "s",
        "operator": "o",
        "status": "COMPLETED",
        "template_id": "custom",
    }
    metadata = {"summary_metadata": {"min_temp_K": 4.2, "duration_h": 17.0}}

    export = _build_experiment_export(exp_info, metadata)

    assert export.summary == {"min_temp_K": 4.2, "duration_h": 17.0}
    assert export.experiment_id == "abc12345"


def test_bare_summary_key_is_ignored():
    """Data under the wrong ``summary`` key must NOT leak into the export —
    the builder only reads ``summary_metadata``."""
    metadata = {"summary": {"min_temp_K": 4.2}}

    export = _build_experiment_export({"experiment_id": "x"}, metadata)

    assert export.summary == {}
