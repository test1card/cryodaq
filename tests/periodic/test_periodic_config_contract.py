from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

import cryodaq.periodic_config as periodic_config_module
from cryodaq.notifications._secrets import SecretStr
from cryodaq.periodic_config import (
    PeriodicPngConfig,
    load_periodic_png_config,
    probe_periodic_png,
    select_notifications_path,
)

TOKEN = "123456:abcdefghijklmnopqrstuvwxyzABCDE"


def _yaml(*, token: str = TOKEN, chat: str = "-100123", periodic: str = "") -> str:
    return (
        "telegram:\n"
        f"  bot_token: {token!r}\n"
        f"  chat_id: {chat}\n"
        "  timeout_s: 10\n"
        "  verify_ssl: true\n"
        "  send_cleared: true\n"
        "periodic_report:\n"
        "  enabled: true\n"
        f"{periodic}"
        "commands:\n"
        "  enabled: false\n"
    )


def test_local_lexists_is_whole_file_authority(tmp_path: Path) -> None:
    tracked = tmp_path / "notifications.yaml"
    local = tmp_path / "notifications.local.yaml"
    tracked.write_text(_yaml(chat="-101"), encoding="utf-8")
    local.write_text(_yaml(chat="-202"), encoding="utf-8")

    assert select_notifications_path(tmp_path) == local
    probe = probe_periodic_png(tmp_path)
    loaded = load_periodic_png_config(tmp_path)
    assert probe.selected_path == local
    assert probe.requested is True
    assert loaded.runnable is True
    assert loaded.config is not None
    assert loaded.config.telegram_chat_id == -202


@pytest.mark.parametrize("kind", ["dangling", "symlink", "oversized", "future"])
def test_unsafe_local_never_falls_back_to_tracked(tmp_path: Path, kind: str) -> None:
    tracked = tmp_path / "notifications.yaml"
    local = tmp_path / "notifications.local.yaml"
    tracked.write_text(_yaml(), encoding="utf-8")
    if kind == "dangling":
        local.symlink_to(tmp_path / "absent.yaml")
    elif kind == "symlink":
        target = tmp_path / "secret.yaml"
        target.write_text(_yaml(), encoding="utf-8")
        local.symlink_to(target)
    elif kind == "oversized":
        local.write_bytes(b"#" * (64 * 1024 + 1))
    else:
        local.write_text(_yaml(), encoding="utf-8")
        future = time.time() + 301
        os.utime(local, (future, future))

    probe = probe_periodic_png(tmp_path)
    loaded = load_periodic_png_config(tmp_path)
    assert probe.selected_path == local
    assert probe.requested is False
    assert probe.error_code is not None
    assert loaded.selected_path == local
    assert loaded.runnable is False
    assert loaded.error_code is not None


@pytest.mark.parametrize("enabled", ["'true'", "1", "0", "null", "[]", "{}"])
def test_enabled_must_be_exact_boolean(tmp_path: Path, enabled: str) -> None:
    (tmp_path / "notifications.yaml").write_text(
        _yaml().replace("enabled: true", f"enabled: {enabled}"), encoding="utf-8"
    )
    probe = probe_periodic_png(tmp_path)
    loaded = load_periodic_png_config(tmp_path)
    assert probe.requested is False
    assert probe.error_code == "invalid_enabled"
    assert loaded.requested is False
    assert loaded.runnable is False


def test_requested_invalid_config_is_distinct_from_runnable(tmp_path: Path) -> None:
    (tmp_path / "notifications.yaml").write_text(
        _yaml(periodic="  report_interval_s: 59\n"), encoding="utf-8"
    )
    probe = probe_periodic_png(tmp_path)
    loaded = load_periodic_png_config(tmp_path)
    assert probe.requested is True
    assert probe.error_code is None
    assert loaded.requested is True
    assert loaded.runnable is False
    assert loaded.error_code == "invalid_report_interval_s"


def test_disabled_does_not_require_credentials(tmp_path: Path) -> None:
    (tmp_path / "notifications.yaml").write_text(
        "periodic_report:\n  enabled: false\n  future_optional_key: 1\n", encoding="utf-8"
    )
    loaded = load_periodic_png_config(tmp_path)
    assert loaded.requested is False
    assert loaded.runnable is False
    assert loaded.error_code is None


@pytest.mark.parametrize(
    "periodic,code",
    [
        ("  report_interval_s: 60.0\n", "invalid_report_interval_s"),
        ("  max_points_per_channel: true\n", "invalid_max_points_per_channel"),
        ("  max_total_points: 1\n", "invalid_max_total_points"),
        ("  chart_hours: .nan\n", "invalid_chart_hours"),
        ("  render_timeout_s: .inf\n", "invalid_render_timeout_s"),
        ("  backoff_base_s: 30\n  backoff_cap_s: 29\n", "invalid_backoff_cap_s"),
        ("  include_channels: [T1, T1]\n", "invalid_include_channels"),
        ("  unexpected_bound: 3\n", "unknown_periodic_key"),
    ],
)
def test_strict_numeric_collection_and_key_validation(
    tmp_path: Path, periodic: str, code: str
) -> None:
    (tmp_path / "notifications.yaml").write_text(_yaml(periodic=periodic), encoding="utf-8")
    loaded = load_periodic_png_config(tmp_path)
    assert loaded.requested is True
    assert loaded.runnable is False
    assert loaded.error_code == code


@pytest.mark.parametrize("chat", ["0", "true", "'01'", "'+123'", "'@'"])
def test_chat_id_is_exact_and_canonical(tmp_path: Path, chat: str) -> None:
    (tmp_path / "notifications.yaml").write_text(_yaml(chat=chat), encoding="utf-8")
    loaded = load_periodic_png_config(tmp_path)
    assert loaded.requested is True
    assert loaded.runnable is False
    assert loaded.error_code == "invalid_chat_id"


def test_valid_bounds_channels_and_secret_wrapper(tmp_path: Path) -> None:
    periodic = (
        "  report_interval_s: 60\n"
        "  chart_hours: 0.016666666666666666\n"
        "  include_channels: [T10, T2, T1]\n"
        "  max_points_per_channel: 2\n"
        "  max_total_points: 2\n"
        "  max_input_bytes: 65536\n"
        "  render_timeout_s: 5\n"
        "  max_render_attempts: 1\n"
        "  max_delivery_attempts: 10\n"
        "  backoff_base_s: 1\n"
        "  backoff_cap_s: 86400\n"
    )
    (tmp_path / "notifications.yaml").write_text(_yaml(periodic=periodic), encoding="utf-8")
    loaded = load_periodic_png_config(tmp_path)
    assert loaded.runnable is True
    assert loaded.config is not None
    assert loaded.config.chart_window_s == 60
    assert loaded.config.include_channels == ("T1", "T2", "T10")
    assert isinstance(loaded.config.telegram_token, SecretStr)
    assert TOKEN not in repr(loaded)


def test_fingerprint_is_canonical_and_excludes_token(tmp_path: Path) -> None:
    path = tmp_path / "notifications.yaml"
    path.write_text(
        _yaml(token=TOKEN, periodic="  include_channels: [T10, T2]\n"), encoding="utf-8"
    )
    first = load_periodic_png_config(tmp_path)
    path.write_text(
        _yaml(
            token="654321:ZYXWVUTSRQPONMLKJIHGFEDCBA98765",
            periodic="  include_channels: [T2, T10]\n",
        ),
        encoding="utf-8",
    )
    second = load_periodic_png_config(tmp_path)
    assert first.config is not None and second.config is not None
    assert first.config.config_fingerprint == second.config.config_fingerprint
    assert TOKEN not in repr(first)


@pytest.mark.parametrize(
    "token",
    [
        "123456:" + "A" * 20,
        "9" * 20 + ":" + "z" * 256,
    ],
)
def test_bot_token_grammar_accepts_exact_boundaries(tmp_path: Path, token: str) -> None:
    (tmp_path / "notifications.yaml").write_text(_yaml(token=token), encoding="utf-8")
    loaded = load_periodic_png_config(tmp_path)
    assert loaded.runnable is True


@pytest.mark.parametrize(
    "token",
    [
        "",
        " ",
        "012345:" + "A" * 20,
        "12345:" + "A" * 20,
        "1" * 21 + ":" + "A" * 20,
        "123456" + "A" * 20,
        "123456::" + "A" * 20,
        "123456:" + "A" * 19,
        "123456:" + "A" * 257,
        "123456:" + "A" * 20 + "/x",
        "123456:" + "A" * 20 + "?x",
        "123456:" + "A" * 20 + "#x",
        "123456:" + "A" * 19 + "é",
        "123456:" + "A" * 19 + "\n",
        "your_bot_token_here",
    ],
)
def test_bot_token_grammar_rejects_invalid_path_and_shape(tmp_path: Path, token: str) -> None:
    (tmp_path / "notifications.yaml").write_text(_yaml(token=token), encoding="utf-8")
    loaded = load_periodic_png_config(tmp_path)
    assert loaded.requested is True
    assert loaded.runnable is False
    assert loaded.error_code == "invalid_bot_token"


def test_yaml_failure_never_echoes_token_bearing_line(tmp_path: Path) -> None:
    path = tmp_path / "notifications.yaml"
    path.write_text(f"telegram: [bot_token: {TOKEN}\n", encoding="utf-8")
    loaded = load_periodic_png_config(tmp_path)
    assert loaded.error_code == "invalid_yaml"
    assert TOKEN not in loaded.error_text
    assert TOKEN not in repr(loaded)


@pytest.mark.parametrize(
    "body",
    [
        _yaml(periodic=f"  chart_hours: {'9' * 1_000}\n"),
        _yaml(chat="9" * 5_000),
        "periodic_report:\n  enabled: true\n  include_channels: "
        + "[" * 2_000
        + "T1"
        + "]" * 2_000
        + "\n",
    ],
)
def test_size_bounded_hostile_yaml_never_escapes_public_boundary(
    tmp_path: Path, body: str
) -> None:
    assert len(body.encode("utf-8")) <= 64 * 1024
    (tmp_path / "notifications.yaml").write_text(body, encoding="utf-8")

    probe = probe_periodic_png(tmp_path)
    loaded = load_periodic_png_config(tmp_path)

    assert probe.error_code is not None or probe.requested is True
    assert loaded.runnable is False
    assert loaded.error_code is not None
    assert TOKEN not in repr(probe)
    assert TOKEN not in repr(loaded)


@pytest.mark.parametrize(
    "body",
    [
        _yaml() + "telegram: {}\n",
        _yaml().replace(
            "  enabled: true\n", "  enabled: true\n  enabled: false\n"
        ),
        _yaml().replace("  chat_id: -100123\n", "  chat_id: -1\n  chat_id: -2\n"),
    ],
)
def test_duplicate_yaml_keys_are_rejected_without_diagnostics_leak(
    tmp_path: Path, body: str
) -> None:
    (tmp_path / "notifications.yaml").write_text(body, encoding="utf-8")
    probe = probe_periodic_png(tmp_path)
    loaded = load_periodic_png_config(tmp_path)
    assert probe.error_code == "invalid_yaml"
    assert loaded.error_code == "invalid_yaml"
    assert TOKEN not in probe.error_text
    assert TOKEN not in loaded.error_text


def test_config_mutation_during_read_is_rejected(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "notifications.yaml"
    path.write_text(_yaml(), encoding="utf-8")
    real_read = periodic_config_module.os.read
    changed = False

    def mutating_read(fd: int, size: int) -> bytes:
        nonlocal changed
        if not changed:
            changed = True
            future = time.time() + 3_600
            os.utime(path, (future, future))
        return real_read(fd, size)

    monkeypatch.setattr(periodic_config_module.os, "read", mutating_read)
    loaded = load_periodic_png_config(tmp_path)
    assert loaded.runnable is False
    assert loaded.error_code == "unsafe_config"


def test_config_dataclass_refuses_plaintext_secret() -> None:
    with pytest.raises(TypeError, match="SecretStr"):
        PeriodicPngConfig(
            enabled=True,
            interval_s=1800,
            chart_window_s=7200,
            include_channels=None,
            max_points_per_channel=20_000,
            max_total_points=100_000,
            max_input_bytes=8 * 1024 * 1024,
            render_timeout_s=120.0,
            max_render_attempts=5,
            max_delivery_attempts=5,
            backoff_base_s=30.0,
            backoff_cap_s=3600.0,
            telegram_token=TOKEN,  # type: ignore[arg-type]
            telegram_chat_id=-100123,
            telegram_timeout_s=10.0,
            telegram_verify_ssl=True,
            config_fingerprint="sha256:" + "a" * 64,
        )
