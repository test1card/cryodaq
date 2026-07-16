from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

import cryodaq.storage.channel_descriptors as descriptor_storage
from cryodaq.channels.descriptors import ChannelSafetyClass
from cryodaq.drivers.base import Reading
from cryodaq.storage.channel_descriptors import (
    MAX_LIVE_DESCRIPTOR_CONFIG_BYTES,
    MAX_LIVE_DESCRIPTOR_CONFIG_DEPTH,
    ChannelDescriptorStorageError,
    load_live_channel_descriptor_catalog,
)

ROOT = Path(__file__).parents[2]
BASE_MANIFEST = ROOT / "config" / "channel_descriptors.yaml"


def _reading(instrument_id: str, channel: str, unit: str) -> Reading:
    return Reading(
        timestamp=datetime(2026, 7, 12, tzinfo=UTC),
        instrument_id=instrument_id,
        channel=channel,
        value=1.0,
        unit=unit,
    )


def _one_manifest(*, emitted_channel: str = "probe label", channel_id: str = "probe.1") -> dict:
    return {
        "schema_version": 1,
        "descriptors": [
            {
                "schema_version": 1,
                "channel_id": channel_id,
                "instrument_id": "probe",
                "source_key": "input.1.temperature",
                "quantity": "temperature",
                "unit": "K",
                "role": "primary_measurement",
                "safety_class": "observational",
                "display_group": "probes",
                "display_name": "Probe 1",
                "visible_by_default": True,
                "display_order": 1,
                "descriptor_revision": 1,
            }
        ],
        "bindings": [
            {
                "instrument_id": "probe",
                "emitted_channel": emitted_channel,
                "channel_id": channel_id,
            }
        ],
    }


def _write_manifest(path: Path, payload: object) -> None:
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def test_tracked_manifest_covers_exact_base_driver_outputs_and_compatibility_bindings() -> None:
    owner = load_live_channel_descriptor_catalog(BASE_MANIFEST)
    instruments = yaml.safe_load((ROOT / "config" / "instruments.yaml").read_text(encoding="utf-8"))["instruments"]

    expected_pairs: set[tuple[str, str]] = set()
    for config in instruments:
        name = config["name"]
        match config["type"]:
            case "lakeshore_218s":
                for emitted in config["channels"].values():
                    expected_pairs.add((name, emitted))
                    expected_pairs.add((name, f"{emitted}_raw"))
            case "keithley_2604b":
                for smu in ("smua", "smub"):
                    for quantity in ("voltage", "current", "resistance", "power"):
                        expected_pairs.add((name, f"{name}/{smu}/{quantity}"))
            case "thyracont_vsp63d":
                expected_pairs.add((name, f"{name}/pressure"))
            case "etalon_multiline":
                expected_pairs.update((name, f"{name}/length_ch{number}") for number in config["channels"])
                expected_pairs.update(
                    (name, f"{name}/{suffix}") for suffix in ("env_temperature", "env_pressure", "env_humidity")
                )
            case unexpected:  # pragma: no cover - makes new built-ins fail visibly
                pytest.fail(f"unreviewed base driver type: {unexpected}")

    assert set(owner._bindings) == expected_pairs
    assert len(expected_pairs) == 64
    assert owner.grants_control_authority is False

    temperature = owner.bind(_reading("LS218_1", "Т1 Криостат верх", "K"))
    assert temperature.descriptor.channel_id == "Т1"
    assert temperature.descriptor.display_name == "Криостат верх"
    raw = owner.bind(_reading("LS218_1", "Т1 Криостат верх_raw", "sensor_unit"))
    assert raw.descriptor.channel_id == "Т1.raw"
    source = owner.bind(_reading("Keithley_1", "Keithley_1/smua/power", "W"))
    assert source.descriptor.safety_class is ChannelSafetyClass.HAZARDOUS_SOURCE_READBACK
    assert source.grants_control_authority is False
    assert owner.owns(temperature)


@pytest.mark.parametrize(
    ("instrument_id", "channel", "unit"),
    [
        ("LS218_1", "Криостат верх", "K"),
        ("LS218_1", "Т1", "K"),
        ("lookalike", "Т1 Криостат верх", "K"),
        ("LS218_1", "Т1 Криостат верх", "°C"),
    ],
)
def test_manifest_owner_never_infers_vendor_alias_display_name_or_unit(
    instrument_id: str,
    channel: str,
    unit: str,
) -> None:
    owner = load_live_channel_descriptor_catalog(BASE_MANIFEST)

    with pytest.raises(ChannelDescriptorStorageError):
        owner.bind(_reading(instrument_id, channel, unit))


def test_supplied_local_manifest_is_complete_replacement_and_never_falls_back(tmp_path: Path) -> None:
    local = tmp_path / "channel_descriptors.local.yaml"
    _write_manifest(local, _one_manifest())

    owner = load_live_channel_descriptor_catalog(BASE_MANIFEST, local_path=local)

    assert owner.bind(_reading("probe", "probe label", "K")).descriptor.channel_id == "probe.1"
    with pytest.raises(ChannelDescriptorStorageError):
        owner.bind(_reading("LS218_1", "Т1 Криостат верх", "K"))

    local.unlink()
    with pytest.raises(ChannelDescriptorStorageError, match="unavailable"):
        load_live_channel_descriptor_catalog(BASE_MANIFEST, local_path=local)
    local.write_text("not: [valid", encoding="utf-8")
    with pytest.raises(ChannelDescriptorStorageError, match="strict UTF-8 YAML"):
        load_live_channel_descriptor_catalog(BASE_MANIFEST, local_path=local)


@pytest.mark.parametrize("section", ["root", "descriptor", "binding"])
def test_manifest_schema_is_exact_and_closed(tmp_path: Path, section: str) -> None:
    payload = _one_manifest()
    target = {
        "root": payload,
        "descriptor": payload["descriptors"][0],
        "binding": payload["bindings"][0],
    }[section]
    target["unexpected"] = "rejected"
    path = tmp_path / "manifest.yaml"
    _write_manifest(path, payload)

    with pytest.raises(ChannelDescriptorStorageError, match="schema"):
        load_live_channel_descriptor_catalog(path)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(schema_version=True),
        lambda payload: payload.update(descriptors=[]),
        lambda payload: payload.update(bindings=[]),
        lambda payload: payload["descriptors"][0].update(display_order=True),
        lambda payload: payload["descriptors"][0].update(quantity="vendor_temperature"),
        lambda payload: payload["bindings"][0].update(instrument_id="other"),
        lambda payload: payload["bindings"].append(dict(payload["bindings"][0])),
    ],
)
def test_manifest_rejects_wrong_types_incomplete_or_ambiguous_authority(
    tmp_path: Path,
    mutation,
) -> None:
    payload = _one_manifest()
    mutation(payload)
    path = tmp_path / "manifest.yaml"
    _write_manifest(path, payload)

    with pytest.raises(ChannelDescriptorStorageError):
        load_live_channel_descriptor_catalog(path)


@pytest.mark.parametrize(
    "body",
    [
        "schema_version: 1\nschema_version: 1\ndescriptors: []\nbindings: []\n",
        "schema_version: 1\ndescriptors: &shared []\nbindings: *shared\n",
    ],
)
def test_manifest_rejects_duplicate_keys_and_yaml_aliases(tmp_path: Path, body: str) -> None:
    path = tmp_path / "manifest.yaml"
    path.write_text(body, encoding="utf-8")

    with pytest.raises(ChannelDescriptorStorageError, match="strict UTF-8 YAML"):
        load_live_channel_descriptor_catalog(path)


def test_manifest_rejects_excessive_yaml_nesting_before_schema_validation(tmp_path: Path) -> None:
    nested = "leaf"
    for _ in range(MAX_LIVE_DESCRIPTOR_CONFIG_DEPTH + 1):
        nested = f"[{nested}]"
    path = tmp_path / "manifest.yaml"
    path.write_text(nested, encoding="utf-8")

    with pytest.raises(ChannelDescriptorStorageError, match="strict UTF-8 YAML"):
        load_live_channel_descriptor_catalog(path)


def _symlink_or_skip(link: Path, target: Path, *, target_is_directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        if os.name == "nt" and exc.winerror == 1314:
            pytest.skip("Windows token cannot create symlinks")
        raise


def test_manifest_rejects_symlinked_file(tmp_path: Path) -> None:
    regular = tmp_path / "manifest.yaml"
    _write_manifest(regular, _one_manifest())
    symlink = tmp_path / "link.yaml"
    _symlink_or_skip(symlink, regular)

    with pytest.raises(ChannelDescriptorStorageError, match="single-link regular file"):
        load_live_channel_descriptor_catalog(symlink)


def test_manifest_rejects_hardlinked_files(tmp_path: Path) -> None:
    regular = tmp_path / "manifest.yaml"
    _write_manifest(regular, _one_manifest())
    hardlink = tmp_path / "hardlink.yaml"
    hardlink.hardlink_to(regular)

    for unsafe in (regular, hardlink):
        with pytest.raises(ChannelDescriptorStorageError, match="single-link regular file"):
            load_live_channel_descriptor_catalog(unsafe)


def test_manifest_rejects_oversized_file(tmp_path: Path) -> None:
    oversized = tmp_path / "oversized.yaml"
    oversized.write_bytes(b"x" * (MAX_LIVE_DESCRIPTOR_CONFIG_BYTES + 1))
    with pytest.raises(ChannelDescriptorStorageError, match="bounded file grammar"):
        load_live_channel_descriptor_catalog(oversized)


def test_manifest_rejects_symlinked_parent_authority_path(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    manifest = real_parent / "manifest.yaml"
    _write_manifest(manifest, _one_manifest())
    linked_parent = tmp_path / "linked"
    _symlink_or_skip(linked_parent, real_parent, target_is_directory=True)

    with pytest.raises(ChannelDescriptorStorageError, match="symlink-free|cannot be read safely"):
        load_live_channel_descriptor_catalog(linked_parent / manifest.name)


def test_manifest_rejects_same_inode_same_length_rewrite_with_restored_mtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name == "nt":
        pytest.skip("Windows native-handle replacement coverage is in test_windows_secure_read.py")
    path = tmp_path / "manifest.yaml"
    _write_manifest(path, _one_manifest())
    original = path.read_bytes()
    replacement = original.replace(b"probe label", b"evil! label", 1)
    assert len(replacement) == len(original)
    initial = path.stat()
    real_read = descriptor_storage.os.read
    mutated = False

    def rewrite_after_read(fd: int, count: int) -> bytes:
        nonlocal mutated
        chunk = real_read(fd, count)
        if chunk and not mutated:
            mutated = True
            with path.open("r+b") as handle:
                handle.write(replacement)
                handle.flush()
                os.fsync(handle.fileno())
            os.utime(path, ns=(initial.st_atime_ns, initial.st_mtime_ns))
            assert path.stat().st_ino == initial.st_ino
            assert path.stat().st_size == initial.st_size
            assert path.stat().st_mtime_ns == initial.st_mtime_ns
        return chunk

    monkeypatch.setattr(descriptor_storage.os, "read", rewrite_after_read)

    with pytest.raises(ChannelDescriptorStorageError, match="changed while reading"):
        load_live_channel_descriptor_catalog(path)
    assert mutated


@pytest.mark.skipif(os.name != "nt", reason="Windows ancestor timestamp semantics")
def test_manifest_tolerates_unrelated_windows_sibling_churn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "manifest.yaml"
    _write_manifest(path, _one_manifest())
    real_read = descriptor_storage.read_secure_relative_bytes
    churned = False

    def create_sibling_before_read(*args: object, **kwargs: object) -> bytes:
        nonlocal churned
        churned = True
        (tmp_path / "unrelated.tmp").write_text("noise", encoding="utf-8")
        return real_read(*args, **kwargs)

    monkeypatch.setattr(descriptor_storage, "read_secure_relative_bytes", create_sibling_before_read)

    load_live_channel_descriptor_catalog(path)
    assert churned


@pytest.mark.skipif(os.name != "nt", reason="Windows file identity contract")
def test_windows_lstat_and_open_handle_share_file_identity(tmp_path: Path) -> None:
    path = tmp_path / "manifest.yaml"
    _write_manifest(path, _one_manifest())
    before = path.lstat()
    fd = os.open(path, os.O_RDONLY)
    try:
        opened = os.fstat(fd)
    finally:
        os.close(fd)

    assert (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction contract")
def test_manifest_rejects_windows_junction_ancestor(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    path = real_parent / "manifest.yaml"
    _write_manifest(path, _one_manifest())
    junction = tmp_path / "junction"
    created = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(junction), str(real_parent)],
        check=False,
        capture_output=True,
        text=True,
    )
    if created.returncode != 0:
        pytest.skip(f"junction creation unavailable: {created.stderr.strip()}")

    with pytest.raises(ChannelDescriptorStorageError, match="symlink-free"):
        load_live_channel_descriptor_catalog(junction / path.name)


@pytest.mark.parametrize(
    "emitted_channel",
    [
        "probe\x00label",
        "probe\x1flabel",
        "probe\u200blabel",
        "probe-e\u0301",
    ],
)
def test_manifest_rejects_non_nfc_or_control_bearing_emitted_channel(
    tmp_path: Path,
    emitted_channel: str,
) -> None:
    path = tmp_path / "manifest.yaml"
    _write_manifest(path, _one_manifest(emitted_channel=emitted_channel))

    with pytest.raises(ChannelDescriptorStorageError, match="NFC|control"):
        load_live_channel_descriptor_catalog(path)
