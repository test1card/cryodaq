"""Tests for the first-run wizard's pure config-detection and yaml-writing
logic. No Qt/QApplication needed — see module docstring in
``cryodaq.gui.first_run_config``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from cryodaq.gui import first_run_config as cfg

INSTRUMENTS_YAML = """
instruments:
  - type: lakeshore_218s
    name: "LS218_1"
    resource: "GPIB0::12::INSTR"
    poll_interval_s: 2.0
    channels:
      1: "T1"
  - type: keithley_2604b
    name: "Keithley_1"
    resource: "USB0::0x05E6::0x2604::04052028::INSTR"
    poll_interval_s: 1.0
  - type: thyracont_vsp63d
    name: "VSP63D_1"
    resource: "COM3"
    baudrate: 9600
    poll_interval_s: 2.0
  - type: etalon_multiline
    name: "MultiLine_1"
    host: "localhost"
    port: 2001
    channels: [1, 2, 3, 4]

keithley:
  watchdog:
    mode: "best_effort"
    timeout_s: 5.0

chamber:
  volume_l: 0.0
"""


# ---------------------------------------------------------------------------
# needs_first_run / mark_first_run_done
# ---------------------------------------------------------------------------


def test_needs_first_run_true_on_genuinely_fresh_config_dir(tmp_path: Path) -> None:
    (tmp_path / "instruments.yaml").write_text("instruments: []", encoding="utf-8")
    assert cfg.needs_first_run(tmp_path) is True


def test_needs_first_run_false_when_valid_legacy_instruments_local_exists(tmp_path: Path) -> None:
    (tmp_path / "instruments.local.yaml").write_text("instruments: []", encoding="utf-8")
    assert cfg.needs_first_run(tmp_path) is False


@pytest.mark.parametrize("name", ["web.local.yaml", "rag.local.yaml", "notifications.local.yaml"])
def test_needs_first_run_ignores_unrelated_or_partial_local_files(tmp_path: Path, name: str) -> None:
    (tmp_path / name).write_text("enabled: true\n", encoding="utf-8")
    assert cfg.needs_first_run(tmp_path) is True


def test_needs_first_run_false_when_marker_present(tmp_path: Path) -> None:
    cfg.mark_first_run_done(tmp_path)
    assert cfg.needs_first_run(tmp_path) is False


def test_needs_first_run_true_when_pending_transaction_present(tmp_path: Path) -> None:
    (tmp_path / "instruments.local.yaml").write_text("instruments: []", encoding="utf-8")
    (tmp_path / cfg.FIRST_RUN_PENDING_NAME).touch()
    assert cfg.needs_first_run(tmp_path) is True


def test_needs_first_run_pending_overrides_existing_done_marker(tmp_path: Path) -> None:
    old_txn = "0" * 32
    (tmp_path / cfg.FIRST_RUN_MARKER_NAME).write_text(
        json.dumps({"version": cfg.FIRST_RUN_DONE_VERSION, "txn_id": old_txn})
    )
    (tmp_path / cfg.FIRST_RUN_PENDING_NAME).write_text("{}", encoding="utf-8")
    assert cfg.needs_first_run(tmp_path) is True


def test_mark_first_run_done_writes_marker(tmp_path: Path) -> None:
    assert not (tmp_path / cfg.FIRST_RUN_MARKER_NAME).exists()
    cfg.mark_first_run_done(tmp_path)
    assert (tmp_path / cfg.FIRST_RUN_MARKER_NAME).exists()
    # idempotent — calling twice must not raise
    cfg.mark_first_run_done(tmp_path)


def test_load_instruments_config_prefers_existing_local_when_requested(tmp_path: Path) -> None:
    (tmp_path / "instruments.yaml").write_text("source: base\n", encoding="utf-8")
    (tmp_path / "instruments.local.yaml").write_text("source: local\n", encoding="utf-8")
    assert cfg.load_instruments_config(tmp_path, prefer_local=True) == {"source": "local"}


# ---------------------------------------------------------------------------
# instruments.local.yaml
# ---------------------------------------------------------------------------


def test_extract_instrument_defaults_only_the_three_wizard_types(tmp_path: Path) -> None:
    (tmp_path / "instruments.yaml").write_text(INSTRUMENTS_YAML, encoding="utf-8")
    data = cfg.load_instruments_config(tmp_path)
    defaults = cfg.extract_instrument_defaults(data)

    assert set(defaults) == {"LS218_1", "Keithley_1", "VSP63D_1"}
    assert "MultiLine_1" not in defaults, "etalon_multiline must not be wizard-editable"
    assert defaults["LS218_1"]["resource"] == "GPIB0::12::INSTR"
    assert defaults["VSP63D_1"]["baudrate"] == 9600
    assert "baudrate" not in defaults["Keithley_1"]


def test_apply_instrument_overrides_patches_only_named_fields(tmp_path: Path) -> None:
    (tmp_path / "instruments.yaml").write_text(INSTRUMENTS_YAML, encoding="utf-8")
    data = cfg.load_instruments_config(tmp_path)

    patched = cfg.apply_instrument_overrides(data, {"LS218_1": {"resource": "GPIB0::99::INSTR"}})

    ls218 = next(e for e in patched["instruments"] if e["name"] == "LS218_1")
    assert ls218["resource"] == "GPIB0::99::INSTR"
    # untouched fields survive verbatim
    assert ls218["channels"] == {1: "T1"}
    assert ls218["poll_interval_s"] == 2.0
    # keithley/chamber blocks and the multiline entry pass through unchanged
    assert patched["keithley"]["watchdog"]["mode"] == "best_effort"
    assert patched["chamber"]["volume_l"] == 0.0
    multiline = next(e for e in patched["instruments"] if e["name"] == "MultiLine_1")
    assert multiline["host"] == "localhost"
    # original dict is not mutated
    original_ls218 = next(e for e in data["instruments"] if e["name"] == "LS218_1")
    assert original_ls218["resource"] == "GPIB0::12::INSTR"


def test_apply_instrument_overrides_empty_is_a_pure_copy(tmp_path: Path) -> None:
    (tmp_path / "instruments.yaml").write_text(INSTRUMENTS_YAML, encoding="utf-8")
    data = cfg.load_instruments_config(tmp_path)
    patched = cfg.apply_instrument_overrides(data, {})
    assert patched == data
    assert patched is not data


def test_write_instruments_local_round_trips_and_has_header(tmp_path: Path) -> None:
    data = {"instruments": [{"type": "keithley_2604b", "name": "K1", "resource": "X"}]}
    path = cfg.write_instruments_local(tmp_path, data)

    assert path == tmp_path / "instruments.local.yaml"
    text = path.read_text(encoding="utf-8")
    assert "ЗАМЕНА, НЕ СЛИЯНИЕ" in text
    assert yaml.safe_load(text) == data


def test_write_instruments_local_is_atomic(tmp_path: Path) -> None:
    with patch("cryodaq.gui.first_run_config.atomic_write_text") as atomic_write:
        cfg.write_instruments_local(tmp_path, {"instruments": []})
    atomic_write.assert_called_once()


def test_write_setup_transaction_rolls_back_and_remains_retryable(tmp_path: Path) -> None:
    original = "# operator comment\ninstruments:\n  - name: live\n"
    instrument_path = tmp_path / "instruments.local.yaml"
    instrument_path.write_text(original, encoding="utf-8")

    real_atomic_write = cfg.atomic_write_text
    calls = 0

    def fail_notification(path: Path, content: str, *, encoding: str = "utf-8") -> None:
        nonlocal calls
        calls += 1
        if path.name == "notifications.local.yaml":
            raise OSError("disk full")
        real_atomic_write(path, content, encoding=encoding)

    with patch("cryodaq.gui.first_run_config.atomic_write_text", side_effect=fail_notification):
        with pytest.raises(OSError, match="disk full"):
            cfg.write_setup_transaction(
                tmp_path,
                instruments={"instruments": [{"name": "new"}]},
                notifications={"telegram": {"bot_token": "secret", "chat_id": 42}},
            )

    assert instrument_path.read_text(encoding="utf-8") == original
    assert not (tmp_path / "notifications.local.yaml").exists()
    assert not (tmp_path / cfg.FIRST_RUN_MARKER_NAME).exists()
    assert cfg.needs_first_run(tmp_path) is False  # original live config remains authoritative


def test_fresh_setup_partial_failure_retries_on_next_launch(tmp_path: Path) -> None:
    real_atomic_write = cfg.atomic_write_text

    def fail_notification(path: Path, content: str, *, encoding: str = "utf-8") -> None:
        if path.name == "notifications.local.yaml":
            raise OSError("disk full")
        real_atomic_write(path, content, encoding=encoding)

    with patch("cryodaq.gui.first_run_config.atomic_write_text", side_effect=fail_notification):
        with pytest.raises(OSError, match="disk full"):
            cfg.write_setup_transaction(
                tmp_path,
                instruments={"instruments": [{"name": "new"}]},
                notifications={"telegram": {"bot_token": "secret", "chat_id": 42}},
            )

    assert not (tmp_path / "instruments.local.yaml").exists()
    assert not (tmp_path / "notifications.local.yaml").exists()
    assert cfg.needs_first_run(tmp_path) is True


def test_write_setup_transaction_marker_is_last(tmp_path: Path) -> None:
    writes: list[str] = []
    real_atomic_write = cfg.atomic_write_text

    def record(path: Path, content: str, *, encoding: str = "utf-8") -> None:
        writes.append(path.name)
        real_atomic_write(path, content, encoding=encoding)

    with patch("cryodaq.gui.first_run_config.atomic_write_text", side_effect=record):
        cfg.write_setup_transaction(tmp_path, instruments={"instruments": []})

    assert writes[-1] == cfg.FIRST_RUN_MARKER_NAME
    assert not (tmp_path / cfg.FIRST_RUN_PENDING_NAME).exists()


def test_write_setup_transaction_backup_preserves_existing_comments(tmp_path: Path) -> None:
    path = tmp_path / "instruments.local.yaml"
    original = "# operator comment\ninstruments: []\n"
    path.write_text(original, encoding="utf-8")

    cfg.write_setup_transaction(
        tmp_path,
        instruments={"instruments": [{"name": "new"}]},
        backup_existing=True,
    )

    assert (tmp_path / "instruments.local.yaml.bak").read_text(encoding="utf-8") == original


def _seed_established_install(tmp_path: Path) -> dict[str, bytes]:
    previous_txn = "0" * 32
    originals = {
        "instruments.local.yaml": b"# old instruments\ninstruments:\n  - name: live\n",
        "notifications.local.yaml": b"telegram:\n  bot_token: old-secret\n  chat_id: 1\n",
        cfg.FIRST_RUN_MARKER_NAME: json.dumps(
            {"version": cfg.FIRST_RUN_DONE_VERSION, "txn_id": previous_txn},
            separators=(",", ":"),
        ).encode()
        + b"\n",
    }
    for name, content in originals.items():
        (tmp_path / name).write_bytes(content)
    return originals


def _new_setup_payloads() -> tuple[dict, dict]:
    return (
        {"instruments": [{"name": "new"}]},
        {"telegram": {"bot_token": "new-secret", "chat_id": 2}},
    )


def _suppress_in_process_recovery():
    return patch(
        "cryodaq.gui.first_run_config.recover_pending_setup",
        side_effect=cfg.FirstRunConfigError("simulated process death"),
    )


def _crash_after_atomic_boundary(kind: str, path_match: str, occurrence: int = 1):
    target = f"cryodaq.gui.first_run_config.atomic_write_{kind}"
    real = getattr(cfg, f"atomic_write_{kind}")
    seen = 0

    def crash(path: Path, content, **kwargs) -> None:
        nonlocal seen
        real(path, content, **kwargs)
        matches = path.name == path_match or (
            path_match == cfg.RECOVERY_SNAPSHOT_PREFIX and path.name.startswith(cfg.RECOVERY_SNAPSHOT_PREFIX)
        )
        if matches:
            seen += 1
            if seen == occurrence:
                raise SystemExit(f"crash after {path.name}")

    return patch(target, side_effect=crash)


@pytest.mark.parametrize(
    "kind,path_match,occurrence,committed",
    [
        pytest.param("text", cfg.FIRST_RUN_PENDING_NAME, 1, False, id="prepared-manifest"),
        pytest.param("bytes", cfg.RECOVERY_SNAPSHOT_PREFIX, 1, False, id="instrument-snapshot"),
        pytest.param("bytes", cfg.RECOVERY_SNAPSHOT_PREFIX, 2, False, id="notification-snapshot"),
        pytest.param("bytes", cfg.RECOVERY_SNAPSHOT_PREFIX, 3, False, id="done-snapshot"),
        pytest.param("text", cfg.FIRST_RUN_PENDING_NAME, 2, False, id="replacing-manifest"),
        pytest.param("text", "instruments.local.yaml", 1, False, id="instrument-replace"),
        pytest.param("text", "notifications.local.yaml", 1, False, id="notification-replace"),
        pytest.param("text", cfg.FIRST_RUN_MARKER_NAME, 1, True, id="done-commit"),
    ],
)
def test_established_systemexit_recovers_each_transaction_boundary(
    tmp_path: Path,
    kind: str,
    path_match: str,
    occurrence: int,
    committed: bool,
) -> None:
    originals = _seed_established_install(tmp_path)
    instruments, notifications = _new_setup_payloads()

    with _crash_after_atomic_boundary(kind, path_match, occurrence), _suppress_in_process_recovery():
        with pytest.raises(SystemExit):
            cfg.write_setup_transaction(
                tmp_path,
                instruments=instruments,
                notifications=notifications,
                backup_existing=True,
            )

    assert (tmp_path / cfg.FIRST_RUN_PENDING_NAME).exists()
    cfg.recover_pending_setup(tmp_path)

    if committed:
        assert (
            yaml.safe_load((tmp_path / "instruments.local.yaml").read_text(encoding="utf-8"))["instruments"][0]["name"]
            == "new"
        )
        assert (
            yaml.safe_load((tmp_path / "notifications.local.yaml").read_text(encoding="utf-8"))["telegram"]["chat_id"]
            == 2
        )
        done = json.loads((tmp_path / cfg.FIRST_RUN_MARKER_NAME).read_text(encoding="utf-8"))
        assert done["txn_id"] != "0" * 32
    else:
        for name, content in originals.items():
            assert (tmp_path / name).read_bytes() == content
    assert not (tmp_path / cfg.FIRST_RUN_PENDING_NAME).exists()
    assert not list(tmp_path.glob(f"{cfg.RECOVERY_SNAPSHOT_PREFIX}*"))


@pytest.mark.parametrize(
    "kind,path_match,occurrence,committed",
    [
        pytest.param("text", cfg.FIRST_RUN_PENDING_NAME, 1, False, id="prepared-manifest"),
        pytest.param("text", cfg.FIRST_RUN_PENDING_NAME, 2, False, id="replacing-manifest"),
        pytest.param("text", "instruments.local.yaml", 1, False, id="instrument-replace"),
        pytest.param("text", "notifications.local.yaml", 1, False, id="notification-replace"),
        pytest.param("text", cfg.FIRST_RUN_MARKER_NAME, 1, True, id="done-commit"),
    ],
)
def test_fresh_systemexit_recovers_each_transaction_boundary(
    tmp_path: Path,
    kind: str,
    path_match: str,
    occurrence: int,
    committed: bool,
) -> None:
    instruments, notifications = _new_setup_payloads()
    with _crash_after_atomic_boundary(kind, path_match, occurrence), _suppress_in_process_recovery():
        with pytest.raises(SystemExit):
            cfg.write_setup_transaction(
                tmp_path,
                instruments=instruments,
                notifications=notifications,
            )

    cfg.recover_pending_setup(tmp_path)
    if committed:
        assert (tmp_path / "instruments.local.yaml").exists()
        assert (tmp_path / "notifications.local.yaml").exists()
        assert (tmp_path / cfg.FIRST_RUN_MARKER_NAME).exists()
    else:
        assert not (tmp_path / "instruments.local.yaml").exists()
        assert not (tmp_path / "notifications.local.yaml").exists()
        assert not (tmp_path / cfg.FIRST_RUN_MARKER_NAME).exists()
    assert not (tmp_path / cfg.FIRST_RUN_PENDING_NAME).exists()


def test_committed_cleanup_failure_never_rolls_back_outputs(tmp_path: Path) -> None:
    originals = _seed_established_install(tmp_path)
    instruments, notifications = _new_setup_payloads()

    with (
        patch(
            "cryodaq.gui.first_run_config._cleanup_recovery_artifacts",
            side_effect=SystemExit("cleanup interrupted"),
        ),
        _suppress_in_process_recovery(),
    ):
        with pytest.raises(SystemExit):
            cfg.write_setup_transaction(
                tmp_path,
                instruments=instruments,
                notifications=notifications,
                backup_existing=True,
            )

    assert (tmp_path / cfg.FIRST_RUN_PENDING_NAME).exists()
    assert (tmp_path / "instruments.local.yaml").read_bytes() != originals["instruments.local.yaml"]
    cfg.recover_pending_setup(tmp_path)
    assert (
        yaml.safe_load((tmp_path / "instruments.local.yaml").read_text(encoding="utf-8"))["instruments"][0]["name"]
        == "new"
    )
    assert not (tmp_path / cfg.FIRST_RUN_PENDING_NAME).exists()


def test_fresh_committed_cleanup_failure_keeps_new_outputs(tmp_path: Path) -> None:
    instruments, notifications = _new_setup_payloads()
    with (
        patch(
            "cryodaq.gui.first_run_config._cleanup_recovery_artifacts",
            side_effect=SystemExit("cleanup interrupted"),
        ),
        _suppress_in_process_recovery(),
    ):
        with pytest.raises(SystemExit):
            cfg.write_setup_transaction(
                tmp_path,
                instruments=instruments,
                notifications=notifications,
            )

    cfg.recover_pending_setup(tmp_path)
    assert (
        yaml.safe_load((tmp_path / "instruments.local.yaml").read_text(encoding="utf-8"))["instruments"][0]["name"]
        == "new"
    )
    assert (
        yaml.safe_load((tmp_path / "notifications.local.yaml").read_text(encoding="utf-8"))["telegram"]["chat_id"] == 2
    )
    assert (tmp_path / cfg.FIRST_RUN_MARKER_NAME).exists()
    assert not (tmp_path / cfg.FIRST_RUN_PENDING_NAME).exists()


def test_systemexit_is_rolled_back_in_process_and_original_is_reraised(tmp_path: Path) -> None:
    originals = _seed_established_install(tmp_path)
    instruments, notifications = _new_setup_payloads()

    with _crash_after_atomic_boundary("text", "notifications.local.yaml"):
        with pytest.raises(SystemExit, match="crash after notifications.local.yaml"):
            cfg.write_setup_transaction(
                tmp_path,
                instruments=instruments,
                notifications=notifications,
                backup_existing=True,
            )

    for name, content in originals.items():
        assert (tmp_path / name).read_bytes() == content
    assert not (tmp_path / cfg.FIRST_RUN_PENDING_NAME).exists()
    assert not list(tmp_path.glob(f"{cfg.RECOVERY_SNAPSHOT_PREFIX}*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits")
def test_recovery_manifest_and_secret_snapshots_are_owner_only_and_cleaned(tmp_path: Path) -> None:
    _seed_established_install(tmp_path)
    instruments, notifications = _new_setup_payloads()

    with (
        patch(
            "cryodaq.gui.first_run_config._cleanup_recovery_artifacts",
            side_effect=SystemExit("inspect recovery files"),
        ),
        _suppress_in_process_recovery(),
    ):
        with pytest.raises(SystemExit):
            cfg.write_setup_transaction(
                tmp_path,
                instruments=instruments,
                notifications=notifications,
                backup_existing=True,
            )

    manifest_path = tmp_path / cfg.FIRST_RUN_PENDING_NAME
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert manifest["version"] == cfg.FIRST_RUN_MANIFEST_VERSION
    assert "old-secret" not in manifest_text
    assert "new-secret" not in manifest_text
    assert {target["name"] for target in manifest["targets"]} == {
        "instruments.local.yaml",
        "notifications.local.yaml",
    }
    assert all(target["existed"] and target["snapshot"] for target in manifest["targets"])
    done = json.loads((tmp_path / cfg.FIRST_RUN_MARKER_NAME).read_text(encoding="utf-8"))
    assert done["txn_id"] == manifest["txn_id"]
    assert manifest_path.stat().st_mode & 0o077 == 0
    snapshots = list(tmp_path.glob(f"{cfg.RECOVERY_SNAPSHOT_PREFIX}*"))
    assert snapshots
    assert all(path.stat().st_mode & 0o077 == 0 for path in snapshots)

    cfg.recover_pending_setup(tmp_path)
    assert not manifest_path.exists()
    assert not list(tmp_path.glob(f"{cfg.RECOVERY_SNAPSHOT_PREFIX}*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits")
def test_notifications_local_is_owner_only(tmp_path: Path) -> None:
    path = cfg.write_notifications_local(tmp_path, {"telegram": {"bot_token": "secret", "chat_id": 42}})
    assert path.stat().st_mode & 0o077 == 0


# ---------------------------------------------------------------------------
# safety.yaml review-gate summary
# ---------------------------------------------------------------------------


def test_read_safety_summary_extracts_expected_values(tmp_path: Path) -> None:
    (tmp_path / "safety.yaml").write_text(
        "critical_channels: ['T1']\nstale_timeout_s: 10.0\nrate_limits:\n  max_dT_dt_K_per_min: 5.0\n",
        encoding="utf-8",
    )
    (tmp_path / "instruments.yaml").write_text(INSTRUMENTS_YAML, encoding="utf-8")

    summary = cfg.read_safety_summary(tmp_path)

    assert summary["rate_limit"] == 5.0
    assert summary["stale_timeout_s"] == 10.0
    assert summary["watchdog_mode"] == "best_effort"


def test_read_safety_summary_prefers_local_instruments_yaml(tmp_path: Path) -> None:
    (tmp_path / "safety.yaml").write_text("critical_channels: ['T1']\nstale_timeout_s: 10.0\n", encoding="utf-8")
    (tmp_path / "instruments.yaml").write_text(INSTRUMENTS_YAML, encoding="utf-8")
    (tmp_path / "instruments.local.yaml").write_text('keithley:\n  watchdog:\n    mode: "required"\n', encoding="utf-8")

    summary = cfg.read_safety_summary(tmp_path)
    assert summary["watchdog_mode"] == "required"


def test_read_safety_summary_missing_file_is_invalid(tmp_path: Path) -> None:
    with pytest.raises(cfg.FirstRunConfigError, match="not found"):
        cfg.read_safety_summary(tmp_path)


def test_read_safety_summary_malformed_file_is_invalid(tmp_path: Path) -> None:
    (tmp_path / "safety.yaml").write_text("critical_channels: [\n", encoding="utf-8")
    with pytest.raises(cfg.FirstRunConfigError, match="invalid"):
        cfg.read_safety_summary(tmp_path)


# ---------------------------------------------------------------------------
# notifications.local.yaml
# ---------------------------------------------------------------------------


def test_load_notifications_template_prefers_example(tmp_path: Path) -> None:
    (tmp_path / "notifications.yaml").write_text("telegram:\n  bot_token: base\n", encoding="utf-8")
    (tmp_path / "notifications.local.yaml.example").write_text(
        "telegram:\n  bot_token: example\nescalation:\n  - chat_id: 0\n    delay_minutes: 0\n",
        encoding="utf-8",
    )

    template = cfg.load_notifications_template(tmp_path)
    assert "escalation" in template


def test_load_notifications_template_prefers_existing_local_when_requested(tmp_path: Path) -> None:
    (tmp_path / "notifications.local.yaml.example").write_text("telegram:\n  bot_token: example\n", encoding="utf-8")
    (tmp_path / "notifications.local.yaml").write_text("telegram:\n  bot_token: live\ncustom: keep\n", encoding="utf-8")
    template = cfg.load_notifications_template(tmp_path, prefer_local=True)
    assert template["telegram"]["bot_token"] == "live"
    assert template["custom"] == "keep"


def test_malformed_existing_notification_never_becomes_write_source(tmp_path: Path) -> None:
    (tmp_path / "notifications.local.yaml").write_text(
        "telegram:\n  bot_token: TOPSECRET\n  broken: [\n", encoding="utf-8"
    )
    with pytest.raises(cfg.FirstRunConfigError, match="invalid YAML") as exc_info:
        cfg.load_notifications_template(tmp_path, prefer_local=True)
    assert "TOPSECRET" not in str(exc_info.value)


def test_apply_telegram_overrides_sets_token_and_int_chat_id() -> None:
    base = {"telegram": {"bot_token": "PLACEHOLDER", "chat_id": 0}, "periodic_report": {}}
    patched = cfg.apply_telegram_overrides(base, "abc123", "42")

    assert patched["telegram"]["bot_token"] == "abc123"
    assert patched["telegram"]["chat_id"] == 42
    assert patched["periodic_report"] == {}
    assert base["telegram"]["bot_token"] == "PLACEHOLDER", "must not mutate input"


def test_apply_telegram_overrides_blank_chat_id_leaves_default() -> None:
    base = {"telegram": {"bot_token": "PLACEHOLDER", "chat_id": 0}}
    patched = cfg.apply_telegram_overrides(base, "abc123", "")
    assert patched["telegram"]["chat_id"] == 0


def test_write_notifications_local_round_trips(tmp_path: Path) -> None:
    data = {"telegram": {"bot_token": "abc123", "chat_id": 42}}
    path = cfg.write_notifications_local(tmp_path, data)

    assert path == tmp_path / "notifications.local.yaml"
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == data
