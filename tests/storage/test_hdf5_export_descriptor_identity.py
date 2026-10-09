from pathlib import Path

import h5py

from cryodaq.storage.hdf5_export import HDF5Exporter


def test_hdf5_exports_descriptor_hash_and_leaves_missing_hash_empty(tmp_path: Path) -> None:
    output_path = tmp_path / "identity.h5"
    rows = [
        ("2026-03-14T10:00:00+00:00", "ls218s", "T_STAGE", 4.235, "K", "ok", "sha256:declared"),
        ("2026-03-14T10:00:01+00:00", "ls218s", "T_STAGE", 4.240, "K", "ok", None),
    ]

    with h5py.File(str(output_path), "w") as hf:
        HDF5Exporter(tmp_path)._write_readings(hf, rows)

    with h5py.File(str(output_path), "r") as hf:
        group = hf["ls218s"]["T_STAGE"]
        assert "descriptor_hash" in group, f"descriptor_hash column missing: {list(group.keys())}"
        hashes = [value.decode() if isinstance(value, bytes) else value for value in group["descriptor_hash"]]
        assert hashes == ["sha256:declared", ""], f"unexpected descriptor_hash cells: {hashes}"
