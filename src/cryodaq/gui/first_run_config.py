"""Pure config detection and local-YAML persistence for the first-run wizard.

Deliberately NO Qt imports — kept separate from ``first_run_wizard.py`` so
detection and yaml-writing can be unit-tested without a ``QApplication``.
Mirrors the style of ``cryodaq.gui._theme_loader`` (plain ``yaml.safe_load`` /
``yaml.safe_dump``, no heavy config-class dependency).
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

import yaml

from cryodaq._owned_yaml import OwnedSafeLoader
from cryodaq.core.atomic_write import atomic_write_bytes, atomic_write_text

FIRST_RUN_MARKER_NAME = ".first_run_done"
FIRST_RUN_PENDING_NAME = ".first_run_pending"
FIRST_RUN_MANIFEST_VERSION = 1
FIRST_RUN_DONE_VERSION = 1
RECOVERY_SNAPSHOT_PREFIX = ".first_run_recovery."

_TRANSACTION_STATES = frozenset({"preparing", "replacing", "rolled_back"})
_TRANSACTION_TARGETS = {
    "instruments.local.yaml": False,
    "channel_descriptors.local.yaml": False,
    "notifications.local.yaml": True,
}


class FirstRunConfigError(RuntimeError):
    """A first-run config cannot be safely read, validated, or persisted."""


# The three instrument classes actually deployed at АКЦ ФИАН (see
# docs/deployment.md §5 "Актуальный стек"). ``etalon_multiline`` is a newer,
# optional integration — left untouched (copied through verbatim) rather
# than exposed on the wizard's instrument page.
WIZARD_INSTRUMENT_TYPES = frozenset({"lakeshore_218s", "keithley_2604b", "thyracont_vsp63d"})


def needs_first_run(config_dir: Path) -> bool:
    """Return whether interactive setup is still pending.

    The launcher resolves a pending recovery manifest before calling this
    function. If one is nevertheless present it always wins over ``done``.
    For pre-marker installations, only a valid instruments override counts as
    legacy setup; unrelated web/RAG/notification overrides do not.
    """
    if (config_dir / FIRST_RUN_PENDING_NAME).exists():
        return True
    # A local instruments authority always selects the matching local descriptor
    # authority at engine startup.  Older wizard versions wrote only the former;
    # reopen setup so finishing the wizard repairs that incomplete authority pair.
    if (config_dir / "instruments.local.yaml").exists() and not (
        config_dir / "channel_descriptors.local.yaml"
    ).exists():
        return True
    if _read_done_txn(config_dir / FIRST_RUN_MARKER_NAME) is not None:
        return False
    legacy_instruments = config_dir / "instruments.local.yaml"
    try:
        data = _load_yaml_mapping(legacy_instruments)
    except FirstRunConfigError:
        return True
    return not isinstance(data.get("instruments"), list)


def mark_first_run_done(config_dir: Path, txn_id: str | None = None) -> str:
    """Atomically write a transaction-tagged completion marker."""
    txn_id = txn_id or uuid.uuid4().hex
    try:
        valid_txn = uuid.UUID(hex=txn_id).hex == txn_id
    except (ValueError, AttributeError):
        valid_txn = False
    if not valid_txn:
        raise ValueError("txn_id must be a lowercase UUID hex string")
    payload = {
        "version": FIRST_RUN_DONE_VERSION,
        "txn_id": txn_id,
    }
    atomic_write_text(
        config_dir / FIRST_RUN_MARKER_NAME,
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
    )
    _restrict_owner_only(config_dir / FIRST_RUN_MARKER_NAME)
    return txn_id


def _safe_load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=OwnedSafeLoader)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Strict loader for files the wizard may use as a write source."""
    if not path.exists():
        raise FirstRunConfigError(f"{path.name} not found")
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=OwnedSafeLoader)
    except Exception as exc:
        # Parser text can quote the source line containing a Telegram token.
        raise FirstRunConfigError(f"{path.name} is invalid YAML") from exc
    if not isinstance(data, dict):
        raise FirstRunConfigError(f"{path.name} must contain a mapping")
    return data


def load_instruments_config(config_dir: Path, *, prefer_local: bool = False) -> dict[str, Any]:
    """Load instruments as a plain dict, optionally preferring live overrides."""
    local = config_dir / "instruments.local.yaml"
    path = local if prefer_local and local.exists() else config_dir / "instruments.yaml"
    return _load_yaml_mapping(path)


def extract_instrument_defaults(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return ``{name: {"type":, "resource":, ["baudrate":]}}`` for the three
    wizard-editable instrument types, in file order (dict preserves order)."""
    out: dict[str, dict[str, Any]] = {}
    for entry in data.get("instruments") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") not in WIZARD_INSTRUMENT_TYPES:
            continue
        name = entry.get("name")
        if not name:
            continue
        fields: dict[str, Any] = {"type": entry["type"], "resource": entry.get("resource", "")}
        if "baudrate" in entry:
            fields["baudrate"] = entry["baudrate"]
        out[name] = fields
    return out


def apply_instrument_overrides(data: dict[str, Any], overrides: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Deep-copy ``data`` and patch resource/baudrate for the named instruments.

    Only the fields present in ``overrides[name]`` change — channels,
    poll_interval_s, ``keithley.watchdog``, ``chamber``, and the
    ``etalon_multiline`` block pass through unchanged. This is what keeps the
    written file matching the ``*.local.yaml.example`` schema exactly: it
    is a full copy of the base template with a few leaf values patched, not
    a hand-built subset.
    """
    result = copy.deepcopy(data)
    if not overrides:
        return result
    for entry in result.get("instruments") or []:
        if not isinstance(entry, dict):
            continue
        patch = overrides.get(entry.get("name"))
        if not patch:
            continue
        if patch.get("resource"):
            entry["resource"] = patch["resource"]
        if patch.get("baudrate") is not None:
            entry["baudrate"] = patch["baudrate"]
    return result


_INSTRUMENTS_LOCAL_HEADER = """\
# Локальная конфигурация приборов — создано мастером первого запуска CryoDAQ.
# Этот файл НЕ коммитится в git (*.local.yaml в .gitignore).
#
# ЗАМЕНА, НЕ СЛИЯНИЕ: engine читает ТОЛЬКО этот файл вместо instruments.yaml
# целиком, если он существует. Блоки keithley/chamber перенесены ниже —
# не удаляйте их без замены, иначе watchdog/leak-rate тихо отключатся.
# Полный шаблон с комментариями: config/instruments.local.yaml.example

"""

_CHANNEL_DESCRIPTORS_LOCAL_HEADER = """\
# Local channel descriptor authority — generated with instruments.local.yaml by
# the CryoDAQ first-run wizard. Do not edit one file without regenerating the
# other: both are complete replacement authorities selected together at startup.
#
# This file is not committed to git (*.local.yaml is in .gitignore).

"""


def write_instruments_local(config_dir: Path, data: dict[str, Any]) -> Path:
    """Atomically dump a validated ``instruments.local.yaml``."""
    path = config_dir / "instruments.local.yaml"
    _write_yaml(path, data, _INSTRUMENTS_LOCAL_HEADER)
    return path


def build_channel_descriptors_local(config_dir: Path, instruments: dict[str, Any]) -> dict[str, Any]:
    """Derive the complete local descriptor authority for configured instruments.

    The shipped local descriptor example is the reviewed descriptor vocabulary.
    This function selects exactly the configured instrument identities and
    rebuilds emitted-channel bindings from their live wizard configuration, so
    the local instruments and descriptor authorities cannot be assembled from
    unrelated snapshots.
    """
    template_path = config_dir / "channel_descriptors.local.yaml.example"
    if not template_path.exists():
        template_path = config_dir / "channel_descriptors.yaml"
    template = _load_yaml_mapping(template_path)
    instruments_template_path = config_dir / "instruments.local.yaml.example"
    if not instruments_template_path.exists():
        instruments_template_path = config_dir / "instruments.yaml"
    instruments_template = _load_yaml_mapping(instruments_template_path)

    entries = instruments.get("instruments")
    descriptors = template.get("descriptors")
    bindings = template.get("bindings")
    template_entries = instruments_template.get("instruments")
    if (
        not isinstance(entries, list)
        or not isinstance(descriptors, list)
        or not isinstance(bindings, list)
        or not isinstance(template_entries, list)
    ):
        raise FirstRunConfigError("cannot derive local descriptor authority from an invalid template")

    configured: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("name"), str)
            or not isinstance(entry.get("type"), str)
        ):
            raise FirstRunConfigError("cannot derive local descriptor authority from invalid instruments")
        name = entry["name"]
        if name in configured:
            raise FirstRunConfigError("cannot derive local descriptor authority from duplicate instrument names")
        configured[name] = entry

    template_types: dict[str, str] = {}
    for entry in template_entries:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("name"), str)
            or not isinstance(entry.get("type"), str)
        ):
            raise FirstRunConfigError("instrument template has an invalid instrument entry")
        template_types[entry["name"]] = entry["type"]

    descriptor_by_channel: dict[str, dict[str, Any]] = {}
    for row in descriptors:
        if not isinstance(row, dict) or not isinstance(row.get("channel_id"), str):
            raise FirstRunConfigError("descriptor template has an invalid descriptor entry")
        channel_id = row["channel_id"]
        if channel_id in descriptor_by_channel:
            raise FirstRunConfigError("descriptor template has duplicate channel identities")
        descriptor_by_channel[channel_id] = row

    binding_by_channel: dict[str, dict[str, Any]] = {}
    for row in bindings:
        if not isinstance(row, dict) or not isinstance(row.get("channel_id"), str):
            raise FirstRunConfigError("descriptor template has an invalid binding entry")
        channel_id = row["channel_id"]
        if channel_id in binding_by_channel:
            raise FirstRunConfigError("descriptor template has duplicate channel bindings")
        binding_by_channel[channel_id] = row

    descriptors_by_template_instrument: dict[str, list[dict[str, Any]]] = {}
    for row in descriptors:
        if not isinstance(row, dict) or not isinstance(row.get("instrument_id"), str):
            raise FirstRunConfigError("descriptor template has an invalid descriptor entry")
        descriptors_by_template_instrument.setdefault(row["instrument_id"], []).append(row)

    selected_descriptors: list[dict[str, Any]] = []
    used_template_instruments: set[str] = set()
    for name, instrument in configured.items():
        candidates = [
            template_name
            for template_name, template_type in template_types.items()
            if template_type == instrument["type"]
            and template_name not in used_template_instruments
            and template_name in descriptors_by_template_instrument
        ]
        if name in candidates:
            template_name = name
        elif candidates:
            template_name = candidates[0]
        else:
            raise FirstRunConfigError(
                f"descriptor template lacks a {instrument['type']!r} instrument slot for {name!r}"
            )
        used_template_instruments.add(template_name)
        for row in descriptors_by_template_instrument[template_name]:
            copied = copy.deepcopy(row)
            copied["instrument_id"] = name
            selected_descriptors.append(copied)

    selected_descriptors = [
        row
        for row in selected_descriptors
        if _descriptor_is_emitted_by_instrument(row, configured[row["instrument_id"]])
    ]
    selected_ids = {row["channel_id"] for row in selected_descriptors}
    selected_bindings: list[dict[str, Any]] = []
    for descriptor in selected_descriptors:
        channel_id = descriptor["channel_id"]
        template_binding = binding_by_channel.get(channel_id)
        if template_binding is None:
            raise FirstRunConfigError(f"descriptor template lacks binding for {channel_id!r}")
        binding = copy.deepcopy(template_binding)
        instrument = configured[descriptor["instrument_id"]]
        binding["instrument_id"] = instrument["name"]
        binding["emitted_channel"] = _emitted_channel_for_descriptor(descriptor, instrument, binding)
        selected_bindings.append(binding)

    if (
        len(selected_ids) != len(selected_descriptors)
        or {row["channel_id"] for row in selected_bindings} != selected_ids
    ):
        raise FirstRunConfigError("derived local descriptor authority is not one-to-one")
    return {
        "schema_version": 1,
        "descriptors": selected_descriptors,
        "bindings": selected_bindings,
    }


def _descriptor_is_emitted_by_instrument(descriptor: dict[str, Any], instrument: dict[str, Any]) -> bool:
    """Return whether this reviewed descriptor is emitted by the configured driver."""
    if instrument["type"] != "etalon_multiline":
        return True
    source_key = descriptor.get("source_key")
    if not isinstance(source_key, str) or not source_key.startswith("length."):
        return True
    try:
        channel_number = int(source_key.removeprefix("length."))
    except ValueError:
        return False
    channels = instrument.get("channels")
    return isinstance(channels, list) and channel_number in channels


def _emitted_channel_for_descriptor(
    descriptor: dict[str, Any],
    instrument: dict[str, Any],
    binding: dict[str, Any],
) -> str:
    """Build a binding key from the same values passed to the driver."""
    source_key = descriptor.get("source_key")
    if instrument["type"] == "lakeshore_218s" and isinstance(source_key, str) and source_key.startswith("input."):
        parts = source_key.split(".")
        if len(parts) == 3 and parts[1].isdigit() and parts[2] in {"temperature", "raw_sensor"}:
            channel_number = int(parts[1])
            channels = instrument.get("channels")
            label = (
                channels.get(channel_number, f"CH{channel_number}")
                if isinstance(channels, dict)
                else f"CH{channel_number}"
            )
            return f"{label}_raw" if parts[2] == "raw_sensor" else str(label)
    if instrument["type"] == "etalon_multiline" and isinstance(source_key, str):
        if source_key.startswith("length."):
            return f"{instrument['name']}/length_ch{source_key.removeprefix('length.')}"
        if source_key in {"env.temperature", "env.pressure", "env.humidity"}:
            return f"{instrument['name']}/env_{source_key.removeprefix('env.')}"
    emitted = binding.get("emitted_channel")
    if not isinstance(emitted, str):
        raise FirstRunConfigError("descriptor template has an invalid emitted channel")
    if "/" in emitted:
        return f"{instrument['name']}/{emitted.split('/', 1)[1]}"
    return emitted


def read_safety_summary(config_dir: Path) -> dict[str, Any]:
    """Read display-only safety values for the wizard's review-gate page.

    The production ``SafetyManager`` validator is intentionally reused so the
    review gate cannot acknowledge a file the engine would reject.
    """
    safety_path = config_dir / "safety.yaml"
    try:
        from cryodaq.core.safety_broker import SafetyBroker
        from cryodaq.core.safety_manager import SafetyManager

        SafetyManager(SafetyBroker()).load_config(safety_path)
        loaded = yaml.load(safety_path.read_text(encoding="utf-8"), Loader=OwnedSafeLoader)
    except Exception as exc:
        raise FirstRunConfigError(f"safety configuration invalid: {exc}") from exc

    if not isinstance(loaded, dict):  # defensive; production validator also checks this
        raise FirstRunConfigError("safety configuration invalid: expected a mapping")
    safety = loaded
    rate_limit = (safety.get("rate_limits") or {}).get("max_dT_dt_K_per_min")
    stale_timeout = safety.get("stale_timeout_s")

    # watchdog mode lives under instruments*.yaml (keithley.watchdog.mode),
    # not safety.yaml — same local-overrides-replace-base precedence the
    # engine itself uses (local.yaml wins whole-file if present).
    instruments_path = config_dir / "instruments.local.yaml"
    if not instruments_path.exists():
        instruments_path = config_dir / "instruments.yaml"
    instruments = _safe_load_yaml(instruments_path)
    watchdog_mode = ((instruments.get("keithley") or {}).get("watchdog") or {}).get("mode")

    return {
        "rate_limit": rate_limit,
        "stale_timeout_s": stale_timeout,
        "watchdog_mode": watchdog_mode,
    }


def load_notifications_template(config_dir: Path, *, prefer_local: bool = False) -> dict[str, Any]:
    """Base structure for notifications.local.yaml — the ``.example`` schema
    (escalation chain, periodic_report, commands included), falling back to
    the tracked ``notifications.yaml`` template if the example is absent."""
    local = config_dir / "notifications.local.yaml"
    if prefer_local and local.exists():
        return _load_yaml_mapping(local)
    example = config_dir / "notifications.local.yaml.example"
    if example.exists():
        return _load_yaml_mapping(example)
    return _load_yaml_mapping(config_dir / "notifications.yaml")


def apply_telegram_overrides(data: dict[str, Any], bot_token: str, chat_id: str) -> dict[str, Any]:
    """Deep-copy ``data`` and patch only ``telegram.bot_token``/``chat_id``."""
    result = copy.deepcopy(data)
    telegram = result.setdefault("telegram", {})
    if bot_token:
        telegram["bot_token"] = bot_token
    if chat_id:
        try:
            telegram["chat_id"] = int(chat_id)
        except ValueError:
            telegram["chat_id"] = chat_id
    return result


_NOTIFICATIONS_LOCAL_HEADER = """\
# Локальная конфигурация уведомлений — создано мастером первого запуска CryoDAQ.
# Этот файл НЕ коммитится в git (*.local.yaml в .gitignore).

"""


def write_notifications_local(config_dir: Path, data: dict[str, Any]) -> Path:
    """Atomically dump notifications and restrict its plaintext secret."""
    path = config_dir / "notifications.local.yaml"
    _write_yaml(path, data, _NOTIFICATIONS_LOCAL_HEADER)
    _restrict_owner_only(path)
    return path


def _serialize_yaml(data: dict[str, Any], header: str) -> str:
    """Serialize and verify semantic round-trip before touching a target."""
    try:
        body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        loaded = yaml.load(body, Loader=OwnedSafeLoader)
    except Exception as exc:
        raise FirstRunConfigError(f"cannot serialize setup YAML: {exc}") from exc
    if loaded != data:
        raise FirstRunConfigError("serialized setup YAML did not round-trip")
    return header + body


def _write_yaml(path: Path, data: dict[str, Any], header: str) -> None:
    atomic_write_text(path, _serialize_yaml(data, header))


def _restrict_owner_only(path: Path) -> None:
    """Restrict plaintext secrets on POSIX; Windows ACLs are installer-owned."""
    if os.name != "nt":
        os.chmod(path, 0o600)


def _read_done_txn(path: Path) -> str | None:
    """Return a valid transaction id from a completion marker."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        txn_id = payload.get("txn_id")
        if (
            type(payload.get("version")) is not int
            or payload["version"] != FIRST_RUN_DONE_VERSION
            or not isinstance(txn_id, str)
        ):
            return None
        return txn_id if uuid.UUID(hex=txn_id).hex == txn_id else None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _snapshot_metadata(txn_id: str, label: str, content: bytes | None) -> dict[str, Any] | None:
    if content is None:
        return None
    return {
        "name": f"{RECOVERY_SNAPSHOT_PREFIX}{txn_id}.{label}.snapshot",
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _write_manifest(config_dir: Path, manifest: dict[str, Any]) -> None:
    path = config_dir / FIRST_RUN_PENDING_NAME
    atomic_write_text(path, json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n")
    _restrict_owner_only(path)


def _validate_snapshot_metadata(meta: Any, *, txn_id: str, required: bool) -> None:
    if not required:
        if meta is not None:
            raise FirstRunConfigError("recovery manifest has an unexpected snapshot")
        return
    if not isinstance(meta, dict):
        raise FirstRunConfigError("recovery manifest is missing snapshot metadata")
    name = meta.get("name")
    size = meta.get("size")
    digest = meta.get("sha256")
    expected_prefix = f"{RECOVERY_SNAPSHOT_PREFIX}{txn_id}."
    if (
        not isinstance(name, str)
        or Path(name).name != name
        or not name.startswith(expected_prefix)
        or not name.endswith(".snapshot")
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size < 0
        or not isinstance(digest, str)
        or len(digest) != 64
    ):
        raise FirstRunConfigError("recovery manifest has invalid snapshot metadata")


def _load_manifest(config_dir: Path) -> dict[str, Any]:
    path = config_dir / FIRST_RUN_PENDING_NAME
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise FirstRunConfigError("pending setup recovery manifest is unreadable") from exc
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("version")) is not int
        or manifest["version"] != FIRST_RUN_MANIFEST_VERSION
    ):
        raise FirstRunConfigError("pending setup recovery manifest has an unsupported version")
    txn_id = manifest.get("txn_id")
    try:
        valid_txn = isinstance(txn_id, str) and uuid.UUID(hex=txn_id).hex == txn_id
    except (ValueError, AttributeError):
        valid_txn = False
    if not valid_txn:
        raise FirstRunConfigError("pending setup recovery manifest has an invalid transaction id")
    if manifest.get("state") not in _TRANSACTION_STATES:
        raise FirstRunConfigError("pending setup recovery manifest has an invalid state")

    targets = manifest.get("targets")
    if not isinstance(targets, list):
        raise FirstRunConfigError("pending setup recovery manifest has invalid targets")
    seen: set[str] = set()
    snapshot_names: set[str] = set()
    for target in targets:
        if not isinstance(target, dict):
            raise FirstRunConfigError("pending setup recovery manifest has an invalid target")
        name = target.get("name")
        existed = target.get("existed")
        if (
            not isinstance(name, str)
            or name not in _TRANSACTION_TARGETS
            or name in seen
            or not isinstance(existed, bool)
        ):
            raise FirstRunConfigError("pending setup recovery manifest has an invalid target")
        seen.add(name)
        metadata = target.get("snapshot")
        _validate_snapshot_metadata(metadata, txn_id=txn_id, required=existed)
        if metadata is not None:
            if metadata["name"] in snapshot_names:
                raise FirstRunConfigError("pending setup recovery manifest reuses a snapshot")
            snapshot_names.add(metadata["name"])

    done = manifest.get("done")
    if not isinstance(done, dict) or not isinstance(done.get("existed"), bool):
        raise FirstRunConfigError("pending setup recovery manifest has invalid done metadata")
    _validate_snapshot_metadata(
        done.get("snapshot"),
        txn_id=txn_id,
        required=done["existed"],
    )
    if done.get("snapshot") is not None and done["snapshot"]["name"] in snapshot_names:
        raise FirstRunConfigError("pending setup recovery manifest reuses a snapshot")
    return manifest


def _snapshot_path(config_dir: Path, metadata: dict[str, Any]) -> Path:
    return config_dir / metadata["name"]


def _read_recovery_snapshot(config_dir: Path, metadata: dict[str, Any]) -> bytes:
    path = _snapshot_path(config_dir, metadata)
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise FirstRunConfigError(f"recovery snapshot {path.name} is unavailable") from exc
    if len(content) != metadata["size"] or hashlib.sha256(content).hexdigest() != metadata["sha256"]:
        raise FirstRunConfigError(f"recovery snapshot {path.name} failed integrity validation")
    return content


def _manifest_snapshot_paths(config_dir: Path, manifest: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for item in [*manifest["targets"], manifest["done"]]:
        metadata = item.get("snapshot")
        if metadata is not None:
            paths.append(_snapshot_path(config_dir, metadata))
    return paths


def _cleanup_recovery_artifacts(config_dir: Path, manifest: dict[str, Any]) -> None:
    """Remove recovery snapshots first and the manifest last; safe to retry."""
    for path in _manifest_snapshot_paths(config_dir, manifest):
        path.unlink(missing_ok=True)
    (config_dir / FIRST_RUN_PENDING_NAME).unlink(missing_ok=True)


def _restore_incomplete_transaction(config_dir: Path, manifest: dict[str, Any]) -> None:
    """Restore every target and prior done marker before cleanup."""
    target_snapshots: dict[str, bytes] = {}
    for target in manifest["targets"]:
        if target["existed"]:
            target_snapshots[target["name"]] = _read_recovery_snapshot(
                config_dir,
                target["snapshot"],
            )
    done_snapshot: bytes | None = None
    if manifest["done"]["existed"]:
        done_snapshot = _read_recovery_snapshot(config_dir, manifest["done"]["snapshot"])

    for target in manifest["targets"]:
        path = config_dir / target["name"]
        if target["existed"]:
            atomic_write_bytes(path, target_snapshots[target["name"]])
            if _TRANSACTION_TARGETS[target["name"]]:
                _restrict_owner_only(path)
        else:
            path.unlink(missing_ok=True)

    done_path = config_dir / FIRST_RUN_MARKER_NAME
    if manifest["done"]["existed"]:
        assert done_snapshot is not None
        atomic_write_bytes(done_path, done_snapshot)
        _restrict_owner_only(done_path)
    else:
        done_path.unlink(missing_ok=True)

    manifest["state"] = "rolled_back"
    _write_manifest(config_dir, manifest)


def recover_pending_setup(config_dir: Path) -> bool:
    """Recover or finalize an interrupted first-run transaction.

    Must run under the launcher single-instance lock before any wizard, tray,
    or engine path. Returns ``True`` when a pending manifest was handled.
    """
    pending = config_dir / FIRST_RUN_PENDING_NAME
    if not pending.exists():
        return False
    manifest = _load_manifest(config_dir)
    txn_id = manifest["txn_id"]
    if _read_done_txn(config_dir / FIRST_RUN_MARKER_NAME) == txn_id:
        _cleanup_recovery_artifacts(config_dir, manifest)
        return True
    if manifest["state"] == "replacing":
        _restore_incomplete_transaction(config_dir, manifest)
    _cleanup_recovery_artifacts(config_dir, manifest)
    return True


def write_setup_transaction(
    config_dir: Path,
    *,
    instruments: dict[str, Any] | None = None,
    notifications: dict[str, Any] | None = None,
    backup_existing: bool = False,
) -> None:
    """Persist outputs with crash recovery and a transaction-tagged commit.

    An instruments authority is always persisted with the descriptor authority
    derived from that exact in-memory configuration. The recovery manifest
    rolls back both files until the completion marker is committed.
    """
    outputs: list[tuple[Path, str, bool, bytes | None]] = []
    if instruments is not None:
        instruments_path = config_dir / "instruments.local.yaml"
        descriptors_path = config_dir / "channel_descriptors.local.yaml"
        descriptors = build_channel_descriptors_local(config_dir, instruments)
        outputs.append(
            (
                instruments_path,
                _serialize_yaml(instruments, _INSTRUMENTS_LOCAL_HEADER),
                False,
                instruments_path.read_bytes() if instruments_path.exists() else None,
            )
        )
        outputs.append(
            (
                descriptors_path,
                _serialize_yaml(descriptors, _CHANNEL_DESCRIPTORS_LOCAL_HEADER),
                False,
                descriptors_path.read_bytes() if descriptors_path.exists() else None,
            )
        )
    if notifications is not None:
        path = config_dir / "notifications.local.yaml"
        outputs.append(
            (
                path,
                _serialize_yaml(notifications, _NOTIFICATIONS_LOCAL_HEADER),
                True,
                path.read_bytes() if path.exists() else None,
            )
        )

    done = config_dir / FIRST_RUN_MARKER_NAME
    prior_done = done.read_bytes() if done.exists() else None
    txn_id = uuid.uuid4().hex
    targets: list[dict[str, Any]] = []
    snapshot_payloads: list[tuple[dict[str, Any], bytes]] = []
    for index, (path, _, _, snapshot) in enumerate(outputs):
        metadata = _snapshot_metadata(txn_id, f"target-{index}", snapshot)
        targets.append(
            {
                "name": path.name,
                "existed": snapshot is not None,
                "snapshot": metadata,
            }
        )
        if metadata is not None and snapshot is not None:
            snapshot_payloads.append((metadata, snapshot))
    done_metadata = _snapshot_metadata(txn_id, "done", prior_done)
    if done_metadata is not None and prior_done is not None:
        snapshot_payloads.append((done_metadata, prior_done))
    manifest: dict[str, Any] = {
        "version": FIRST_RUN_MANIFEST_VERSION,
        "txn_id": txn_id,
        "state": "preparing",
        "done": {
            "existed": prior_done is not None,
            "snapshot": done_metadata,
        },
        "targets": targets,
    }

    try:
        _write_manifest(config_dir, manifest)
        for metadata, snapshot in snapshot_payloads:
            snapshot_path = _snapshot_path(config_dir, metadata)
            atomic_write_bytes(snapshot_path, snapshot)
            _restrict_owner_only(snapshot_path)

        manifest["state"] = "replacing"
        _write_manifest(config_dir, manifest)

        if backup_existing:
            for path, _, secret, snapshot in outputs:
                if snapshot is None:
                    continue
                backup = path.with_name(f"{path.name}.bak")
                atomic_write_bytes(backup, snapshot)
                if secret:
                    _restrict_owner_only(backup)

        for path, content, secret, _ in outputs:
            atomic_write_text(path, content)
            if secret:
                _restrict_owner_only(path)

        mark_first_run_done(config_dir, txn_id)
        _cleanup_recovery_artifacts(config_dir, manifest)
    except BaseException as exc:
        try:
            recover_pending_setup(config_dir)
        except BaseException as recovery_exc:
            exc.add_note(f"first-run recovery also failed: {type(recovery_exc).__name__}")
        raise
