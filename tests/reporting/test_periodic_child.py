from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from cryodaq.notifications._secrets import SecretStr
from cryodaq.periodic_config import PeriodicPngConfig
from cryodaq.periodic_state import (
    PeriodicStatus,
    allocate_pending,
    latest_completed_slot,
    load_periodic_state,
    mark_rendering,
    periodic_generation_dir,
    periodic_input_path,
    write_periodic_state,
)
from cryodaq.report_process import (
    ReportProcessError,
    ReportProcessRunner,
    build_periodic_report_command,
    read_periodic_result_file,
    recover_periodic_generation,
    write_periodic_input_file,
)
from cryodaq.reporting.periodic_input import (
    PeriodicInputError,
    parse_periodic_input_bytes,
    serialize_periodic_input,
    validate_caption_html,
    validate_result_payload,
)

GENERATION = "a" * 32
OWNER = "b" * 32
FINGERPRINT = "sha256:" + "f" * 64
DISPLAY_TIME = "10.07.2026 04:05"


def _config() -> PeriodicPngConfig:
    return PeriodicPngConfig(
        enabled=True,
        interval_s=1_800,
        chart_window_s=7_200,
        include_channels=None,
        max_points_per_channel=20_000,
        max_total_points=100_000,
        max_input_bytes=65_536,
        render_timeout_s=30.0,
        max_render_attempts=5,
        max_delivery_attempts=5,
        backoff_base_s=30.0,
        backoff_cap_s=3_600.0,
        telegram_token=SecretStr("not-sent-to-child"),
        telegram_chat_id=-100123,
        telegram_timeout_s=10.0,
        telegram_verify_ssl=True,
        config_fingerprint=FINGERPRINT,
    )


def _payload(*, slot_end: int = 7_200) -> dict[str, object]:
    slot = latest_completed_slot(float(slot_end), 1_800)
    return {
        "schema": 1,
        "generation_id": GENERATION,
        "owner_token": OWNER,
        "slot": {
            "slot_id": slot.slot_id,
            "slot_start": slot.slot_start,
            "slot_end": slot.slot_end,
            "window_start": 0,
            "window_end": slot.slot_end,
            "config_fingerprint": FINGERPRINT,
        },
        "render": {
            "display_time": DISPLAY_TIME,
            "include_channels": None,
            "max_points_per_channel": 20_000,
            "max_total_points": 100_000,
            "max_input_bytes": 65_536,
            "history_complete": False,
            "alarm_state_complete": True,
            "dropped_points": 1,
            "bad_points": 2,
            "source_errors": [
                "deadline:2026-07-10:sqlite",
                "invalid_row:source-0",
                "issue_overflow:4",
                "live_channel_limit",
            ],
        },
        "readings": [
            {"ts": 7_100.0, "iid": "ls", "ch": "Т1", "v": 4.2, "u": "K", "st": "ok"},
            {
                "ts": 7_110.0,
                "iid": "vac",
                "ch": "vac/pressure",
                "v": 1e-5,
                "u": "mbar",
                "st": "ok",
            },
        ],
        "alarms": [
            {
                "id": "warm",
                "level": "WARNING",
                "channels": ["Т1"],
                "triggered_at": 7_000.0,
                "acknowledged": False,
            }
        ],
    }


def _install_rendering_state(data_dir: Path) -> str:
    config = _config()
    slot = latest_completed_slot(7_200.0, config.interval_s)
    pending = allocate_pending(
        load_periodic_state(data_dir),
        slot,
        config,
        generation_id=GENERATION,
        owner_token=OWNER,
        display_time=DISPLAY_TIME,
        now=7_201.0,
    )
    write_periodic_state(data_dir, pending)
    rendering = mark_rendering(
        pending, slot_id=slot.slot_id, owner_token=OWNER, now=7_202.0
    )
    write_periodic_state(
        data_dir,
        rendering,
        expected_slot_id=slot.slot_id,
        expected_owner_token=OWNER,
        expected_status=PeriodicStatus.PENDING,
    )
    return slot.slot_id


def test_input_exact_schema_and_bounds() -> None:
    payload = _payload()
    raw, validated = serialize_periodic_input(payload, expected_max_input_bytes=65_536)
    assert validated.generation_id == GENERATION
    assert isinstance(validated.readings, tuple)
    assert validated.render.source_errors[-1] == "live_channel_limit"

    for section, key in (
        (payload, "owner_token"),
        (payload["slot"], "slot_id"),
        (payload["render"], "display_time"),
        (payload["readings"][0], "iid"),
        (payload["alarms"][0], "level"),
    ):
        broken = copy.deepcopy(payload)
        target = broken
        if section is payload["slot"]:
            target = broken["slot"]
        elif section is payload["render"]:
            target = broken["render"]
        elif section is payload["readings"][0]:
            target = broken["readings"][0]
        elif section is payload["alarms"][0]:
            target = broken["alarms"][0]
        del target[key]
        with pytest.raises(PeriodicInputError):
            serialize_periodic_input(broken, expected_max_input_bytes=65_536)

    with pytest.raises(PeriodicInputError):
        parse_periodic_input_bytes(
            raw.replace(b'"schema":1', b'"schema":1,"schema":1'),
            expected_max_input_bytes=65_536,
        )


def test_argv_cap_is_independent_input_authority() -> None:
    payload = _payload()
    payload["render"]["max_input_bytes"] = 33_554_432
    raw = json.dumps(payload).encode()
    with pytest.raises(PeriodicInputError, match="does not match"):
        parse_periodic_input_bytes(raw, expected_max_input_bytes=65_536)
    with pytest.raises(PeriodicInputError, match="trusted byte cap"):
        parse_periodic_input_bytes(b" " * 65_537, expected_max_input_bytes=65_536)
    with pytest.raises(ReportProcessError):
        build_periodic_report_command(GENERATION, deadline_epoch=1.0, max_input_bytes=65_535)


@pytest.mark.parametrize(
    ("option", "duplicate"),
    [
        ("--generation-id", GENERATION),
        ("--deadline-epoch", "9999999999"),
        ("--max-input-bytes", "65536"),
    ],
)
def test_periodic_duplicate_authority_argv_is_rejected(
    tmp_path: Path, option: str, duplicate: str
) -> None:
    import cryodaq.reporting.__main__ as child

    argv = [
        "periodic",
        f"--generation-id={GENERATION}",
        "--deadline-epoch=9999999999",
        "--max-input-bytes=65536",
        option,
        duplicate,
    ]
    renderer_was_loaded = "cryodaq.reporting.periodic_renderer" in sys.modules
    assert child.main(argv) == 3
    assert ("cryodaq.reporting.periodic_renderer" in sys.modules) is renderer_was_loaded


@pytest.mark.parametrize(
    "abbreviated",
    ["--generation", "--deadline", "--max-input"],
)
def test_periodic_authority_argv_abbreviations_are_rejected(abbreviated: str) -> None:
    import cryodaq.reporting.__main__ as child

    argv = [
        "periodic",
        f"--generation-id={GENERATION}",
        "--deadline-epoch=9999999999",
        "--max-input-bytes=65536",
        abbreviated,
        "hostile-duplicate",
    ]
    with pytest.raises(SystemExit) as exc:
        child.main(argv)
    assert exc.value.code == 2


def test_existing_experiment_argv_abbreviations_remain_compatible() -> None:
    import cryodaq.reporting.__main__ as child

    args = child._parser().parse_args(
        [
            "experiment",
            "--experiment=exp-1",
            "--generation=generation-token-0001",
            "--deadline=123",
        ]
    )
    assert args.experiment_id == "exp-1"
    assert args.generation_id == "generation-token-0001"
    assert args.deadline_epoch == 123.0


def test_epoch_deadline_converts_once_to_capped_monotonic_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.reporting.__main__ as child

    monkeypatch.setattr(child.time, "time", lambda: 100.0)
    monkeypatch.setattr(child.time, "monotonic", lambda: 50.0)
    assert child._periodic_deadline("1000.0") == 650.0
    assert child._periodic_deadline("125.0") == 75.0
    with pytest.raises(PeriodicInputError, match="expired"):
        child._periodic_deadline("100.0")


def test_input_relational_contract() -> None:
    payload = _payload()
    attacks = []
    duplicate = copy.deepcopy(payload)
    duplicate["readings"].append(copy.deepcopy(duplicate["readings"][-1]))
    attacks.append(duplicate)
    multi = copy.deepcopy(payload)
    multi["readings"].insert(
        0, {"ts": 7_000.0, "iid": "other", "ch": "Т1", "v": 5.0, "u": "K", "st": "ok"}
    )
    attacks.append(multi)
    evidence = copy.deepcopy(payload)
    evidence["render"]["source_errors"] = ["/private/secret"]
    attacks.append(evidence)
    alarm = copy.deepcopy(payload)
    alarm["alarms"][0]["level"] = "warning"
    attacks.append(alarm)
    structural_injection = copy.deepcopy(payload)
    structural_injection["alarms"][0]["id"] = "alarm\n<b>forged</b>"
    attacks.append(structural_injection)
    for attack in attacks:
        with pytest.raises(PeriodicInputError):
            serialize_periodic_input(attack, expected_max_input_bytes=65_536)


def test_success_and_failure_result_closed_schemas() -> None:
    slot_id = _payload()["slot"]["slot_id"]
    failure = {
        "schema": 1,
        "ok": False,
        "generation_id": GENERATION,
        "owner_token": OWNER,
        "slot_id": slot_id,
        "config_fingerprint": FINGERPRINT,
        "artifact": None,
        "caption": "",
        "error_code": "busy",
        "error_text": "renderer is busy",
    }
    assert validate_result_payload(failure, require_success=False)["error_code"] == "busy"
    for mutation in ({**failure, "extra": 1}, {**failure, "artifact": {}}, {**failure, "ok": 1}):
        with pytest.raises(PeriodicInputError):
            validate_result_payload(mutation)

    success = {
        **failure,
        "ok": True,
        "artifact": {
            "path": f"periodic/generations/{GENERATION}/periodic.png",
            "sha256": "sha256:" + "d" * 64,
            "size": 1,
            "width": 640,
            "height": 480,
            "mime": "image/png",
        },
        "error_code": None,
        "error_text": "",
    }
    with pytest.raises(PeriodicInputError, match="caption"):
        validate_result_payload(success, require_success=True)


@pytest.mark.parametrize("hostile_level", [[], {}, 1, True, None])
def test_alarm_level_hostile_types_are_closed_protocol_errors(hostile_level: object) -> None:
    payload = _payload()
    payload["alarms"][0]["level"] = hostile_level
    with pytest.raises(PeriodicInputError):
        serialize_periodic_input(payload, expected_max_input_bytes=65_536)


@pytest.mark.parametrize(
    ("field", "hostile"),
    [
        ("schema", True),
        ("generation_id", []),
        ("owner_token", {}),
        ("slot", []),
        ("render", "not-an-object"),
        ("readings", {}),
        ("alarms", "not-a-list"),
    ],
)
def test_closed_input_parser_hostile_top_level_types_raise_only_protocol_error(
    field: str, hostile: object
) -> None:
    payload = _payload()
    payload[field] = hostile
    with pytest.raises(PeriodicInputError):
        serialize_periodic_input(payload, expected_max_input_bytes=65_536)


@pytest.mark.parametrize(
    ("field", "hostile"),
    [
        ("schema", True),
        ("ok", 1),
        ("generation_id", []),
        ("owner_token", {}),
        ("slot_id", []),
        ("config_fingerprint", {}),
        ("artifact", []),
        ("caption", []),
        ("error_code", []),
        ("error_text", {}),
    ],
)
def test_closed_result_parser_hostile_types_raise_only_protocol_error(
    field: str, hostile: object
) -> None:
    payload = {
        "schema": 1,
        "ok": False,
        "generation_id": GENERATION,
        "owner_token": OWNER,
        "slot_id": _payload()["slot"]["slot_id"],
        "config_fingerprint": FINGERPRINT,
        "artifact": None,
        "caption": "",
        "error_code": "busy",
        "error_text": "renderer is busy",
    }
    payload[field] = hostile
    with pytest.raises(PeriodicInputError):
        validate_result_payload(payload, require_success=False)


@pytest.mark.parametrize(
    "caption",
    [
        "<b>x</b> &amp; &lt; &gt;",
        "Тревог нет ✓",
    ],
)
def test_shared_caption_validator_accepts_only_closed_subset(caption: str) -> None:
    assert validate_caption_html(caption) == caption
    for invalid in (
        "<i>x</i>",
        "<b x>y</b>",
        "x &copy;",
        "<b>x\ny</b>",
        "x < y",
        "x\x00y",
        "x\ry",
        "x\x7fy",
    ):
        with pytest.raises(PeriodicInputError):
            validate_caption_html(invalid)


def test_periodic_real_subprocess_promotes_and_recovers(tmp_path: Path) -> None:
    slot_id = _install_rendering_state(tmp_path)
    write_periodic_input_file(tmp_path, _payload(), expected_max_input_bytes=65_536)
    runner = ReportProcessRunner(tmp_path, timeout_s=20.0)
    result = runner.generate_periodic(
        GENERATION,
        expected_slot_id=slot_id,
        expected_owner_token=OWNER,
        max_input_bytes=65_536,
    )
    assert result.artifact.path.endswith(f"{GENERATION}/periodic.png")
    assert result.caption.startswith("<b>CryoDAQ")
    final = periodic_generation_dir(tmp_path, GENERATION)
    assert {item.name for item in final.iterdir()} == {"periodic.png", "result.json"}
    assert runner.recover_periodic(
        GENERATION,
        expected_slot_id=slot_id,
        expected_owner_token=OWNER,
    ) == result


def test_recovery_rejects_owner_slot_and_status_mismatch(tmp_path: Path) -> None:
    slot_id = _install_rendering_state(tmp_path)
    write_periodic_input_file(tmp_path, _payload(), expected_max_input_bytes=65_536)
    command = build_periodic_report_command(
        GENERATION, deadline_epoch=time.time() + 20, max_input_bytes=65_536
    )
    env = os.environ.copy()
    env["CRYODAQ_REPORT_DATA_DIR"] = str(tmp_path)
    assert subprocess.run(command, env=env, check=False).returncode == 0
    with pytest.raises(ReportProcessError):
        recover_periodic_generation(
            tmp_path,
            GENERATION,
            expected_slot_id=slot_id,
            expected_owner_token="c" * 32,
        )


def test_success_recovery_is_idempotent_and_never_rerenders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    slot_id = _install_rendering_state(tmp_path)
    write_periodic_input_file(tmp_path, _payload(), expected_max_input_bytes=65_536)
    command = build_periodic_report_command(
        GENERATION, deadline_epoch=time.time() + 20, max_input_bytes=65_536
    )
    env = os.environ.copy()
    env["CRYODAQ_REPORT_DATA_DIR"] = str(tmp_path)
    assert subprocess.run(command, env=env, check=False).returncode == 0
    final = periodic_generation_dir(tmp_path, GENERATION)
    before = {item.name: (item.stat().st_ino, item.read_bytes()) for item in final.iterdir()}
    runner = ReportProcessRunner(tmp_path, timeout_s=2.0)

    def forbidden_child(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("an exact final must be recovered before child launch")

    monkeypatch.setattr(runner, "_run_process", forbidden_child)
    first = runner.generate_periodic(
        GENERATION,
        expected_slot_id=slot_id,
        expected_owner_token=OWNER,
        max_input_bytes=65_536,
    )
    second = runner.recover_periodic(
        GENERATION, expected_slot_id=slot_id, expected_owner_token=OWNER
    )
    assert first == second
    assert {item.name: (item.stat().st_ino, item.read_bytes()) for item in final.iterdir()} == before


@pytest.mark.parametrize("mutation", ["extra", "replace_result", "rewrite_png"])
def test_final_recovery_rejects_late_tree_and_entry_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    import cryodaq.report_process as process_module

    slot_id = _install_rendering_state(tmp_path)
    write_periodic_input_file(tmp_path, _payload(), expected_max_input_bytes=65_536)
    runner = ReportProcessRunner(tmp_path, timeout_s=20.0)
    runner.generate_periodic(
        GENERATION,
        expected_slot_id=slot_id,
        expected_owner_token=OWNER,
        max_input_bytes=65_536,
    )
    final = periodic_generation_dir(tmp_path, GENERATION)
    real_fence = process_module._require_rendering_state_fence
    calls = 0

    def mutate_at_last_fence(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        real_fence(*args, **kwargs)
        if calls != 2:
            return
        if mutation == "extra":
            (final / "late-extra").write_bytes(b"x")
        elif mutation == "replace_result":
            result = final / "result.json"
            replacement = final / ".replacement"
            replacement.write_bytes(result.read_bytes())
            os.replace(replacement, result)
        else:
            png = final / "periodic.png"
            original = png.read_bytes()
            png.write_bytes(original)

    monkeypatch.setattr(
        process_module, "_require_rendering_state_fence", mutate_at_last_fence
    )
    with pytest.raises(ReportProcessError, match="changed|extra"):
        process_module.recover_periodic_generation(
            tmp_path,
            GENERATION,
            expected_slot_id=slot_id,
            expected_owner_token=OWNER,
        )


def test_final_recovery_requires_generations_parent_fsync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cryodaq.report_process as process_module

    slot_id = _install_rendering_state(tmp_path)
    write_periodic_input_file(tmp_path, _payload(), expected_max_input_bytes=65_536)
    runner = ReportProcessRunner(tmp_path, timeout_s=20.0)
    runner.generate_periodic(
        GENERATION,
        expected_slot_id=slot_id,
        expected_owner_token=OWNER,
        max_input_bytes=65_536,
    )

    def fail_fsync(_path: Path) -> None:
        raise OSError("injected generations fsync failure")

    monkeypatch.setattr(process_module, "_fsync_dir", fail_fsync)
    with pytest.raises(
        ReportProcessError, match="periodic_durability_failure"
    ) as failure:
        process_module.recover_periodic_generation(
            tmp_path,
            GENERATION,
            expected_slot_id=slot_id,
            expected_owner_token=OWNER,
        )
    assert "injected" not in failure.value.error_text


def test_post_rename_parent_fsync_fault_is_recovered_by_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cryodaq.reporting.__main__ as child

    slot_id = _install_rendering_state(tmp_path)
    write_periodic_input_file(tmp_path, _payload(), expected_max_input_bytes=65_536)
    real_fsync = child._fsync_dir

    def fail_after_rename(path: Path) -> None:
        if path.name == "generations" and periodic_generation_dir(
            tmp_path, GENERATION
        ).exists():
            raise OSError("injected post-rename parent fsync failure")
        real_fsync(path)

    monkeypatch.setattr(child, "_fsync_dir", fail_after_rename)
    args = SimpleNamespace(
        generation_id=GENERATION,
        deadline_epoch=str(time.time() + 20),
        max_input_bytes="65536",
    )
    assert child._run_periodic(args, tmp_path) == 1
    assert periodic_generation_dir(tmp_path, GENERATION).exists()

    recovered = recover_periodic_generation(
        tmp_path,
        GENERATION,
        expected_slot_id=slot_id,
        expected_owner_token=OWNER,
    )
    assert recovered is not None


def test_invalid_periodic_preflight_imports_no_heavy_or_privileged_modules() -> None:
    script = (
        "import sys; import cryodaq.reporting.__main__ as m; "
        "rc=m.main(['periodic','--generation-id="
        + GENERATION
        + "','--deadline-epoch=0','--max-input-bytes=65536']); "
        "print(rc); print('|'.join(sorted(x for x in sys.modules if "
        "x.startswith(('matplotlib','numpy','aiohttp','cryodaq.engine',"
        "'cryodaq.storage','cryodaq.agents')))))"
    )
    env = os.environ.copy()
    env["CRYODAQ_REPORT_DATA_DIR"] = os.getcwd()
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env=env, check=True
    )
    assert completed.stdout.splitlines()[-1] == ""


def test_child_surface_contains_no_destination_or_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    slot_id = _install_rendering_state(tmp_path)
    runner = ReportProcessRunner(tmp_path, timeout_s=2.0)
    captured: dict[str, object] = {}
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret-token-sentinel")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100-secret-chat")
    monkeypatch.setenv("CRYODAQ_OPERATOR", "operator-sentinel")

    def inspect_child(command: object, *, env: object) -> int:
        captured["command"] = command
        captured["env"] = env
        return 1

    monkeypatch.setattr(runner, "_run_process", inspect_child)
    with pytest.raises(ReportProcessError, match="without structured evidence"):
        runner.generate_periodic(
            GENERATION,
            expected_slot_id=slot_id,
            expected_owner_token=OWNER,
            max_input_bytes=65_536,
        )

    surface = repr(captured)
    assert "secret-token-sentinel" not in surface
    assert "secret-chat" not in surface
    assert "operator-sentinel" not in surface
    assert "TELEGRAM" not in surface


def test_input_path_rejects_symlink_and_hardlink(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    _install_rendering_state(data)
    path = periodic_input_path(data, GENERATION)
    path.parent.mkdir(parents=True)
    target = tmp_path / "target"
    target.write_text("{}", encoding="utf-8")
    path.symlink_to(target)
    from cryodaq.reporting.periodic_input import read_periodic_input_file

    with pytest.raises(PeriodicInputError):
        read_periodic_input_file(path, expected_max_input_bytes=65_536)
    path.unlink()
    try:
        os.link(target, path)
    except OSError as exc:
        pytest.skip(f"hard links are unavailable: {exc}")
    with pytest.raises(PeriodicInputError):
        read_periodic_input_file(path, expected_max_input_bytes=65_536)


def test_protocol_directory_creation_is_owner_only_and_rejects_links(tmp_path: Path) -> None:
    from cryodaq.report_process import periodic_failure_result_path

    input_path = write_periodic_input_file(
        tmp_path / "safe", _payload(), expected_max_input_bytes=65_536
    )
    assert input_path.parent.stat().st_mode & 0o077 == 0
    assert input_path.parent.parent.stat().st_mode & 0o077 == 0

    hostile = tmp_path / "hostile"
    reporting = hostile / "reporting"
    reporting.mkdir(parents=True)
    target = tmp_path / "outside"
    target.mkdir()
    (reporting / "periodic").symlink_to(target, target_is_directory=True)
    with pytest.raises(ReportProcessError, match="unsafe"):
        periodic_failure_result_path(hostile, GENERATION)
    assert list(target.iterdir()) == []


def test_escaping_render_lock_parent_is_bounded_protocol_failure(tmp_path: Path) -> None:
    import cryodaq.reporting.__main__ as child

    _install_rendering_state(tmp_path)
    write_periodic_input_file(tmp_path, _payload(), expected_max_input_bytes=65_536)
    outside = tmp_path.parent / f"{tmp_path.name}-outside-locks"
    outside.mkdir()
    (tmp_path / ".report-locks").symlink_to(outside, target_is_directory=True)
    args = SimpleNamespace(
        generation_id=GENERATION,
        deadline_epoch=str(time.time() + 20),
        max_input_bytes="65536",
    )

    assert child._run_periodic(args, tmp_path) == 3
    assert list(outside.iterdir()) == []


def test_contained_symlink_render_lock_parent_is_also_protocol_failure(
    tmp_path: Path,
) -> None:
    import cryodaq.reporting.__main__ as child

    _install_rendering_state(tmp_path)
    write_periodic_input_file(tmp_path, _payload(), expected_max_input_bytes=65_536)
    contained = tmp_path / "contained-locks"
    contained.mkdir()
    (tmp_path / ".report-locks").symlink_to(contained, target_is_directory=True)
    args = SimpleNamespace(
        generation_id=GENERATION,
        deadline_epoch=str(time.time() + 20),
        max_input_bytes="65536",
    )

    assert child._run_periodic(args, tmp_path) == 3
    assert list(contained.iterdir()) == []


def test_failure_side_channel_requires_exact_current_config_fence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cryodaq.report_process import periodic_failure_result_path

    slot_id = _install_rendering_state(tmp_path)
    runner = ReportProcessRunner(tmp_path, timeout_s=2.0)

    def hostile_child(*_args: object, **_kwargs: object) -> int:
        side = periodic_failure_result_path(tmp_path, GENERATION)
        payload = {
            "schema": 1,
            "ok": False,
            "generation_id": GENERATION,
            "owner_token": OWNER,
            "slot_id": slot_id,
            "config_fingerprint": "sha256:" + "e" * 64,
            "artifact": None,
            "caption": "",
            "error_code": "render_failed",
            "error_text": "periodic renderer failed",
        }
        side.write_text(json.dumps(payload), encoding="utf-8")
        return 1

    monkeypatch.setattr(runner, "_run_process", hostile_child)
    with pytest.raises(ReportProcessError, match="fence"):
        runner.generate_periodic(
            GENERATION,
            expected_slot_id=slot_id,
            expected_owner_token=OWNER,
            max_input_bytes=65_536,
        )


def test_failure_side_same_inode_late_mutation_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cryodaq.report_process as process_module

    slot_id = _install_rendering_state(tmp_path)
    runner = ReportProcessRunner(tmp_path, timeout_s=2.0)
    side = process_module.periodic_failure_result_path(tmp_path, GENERATION)

    def failed_child(*_args: object, **_kwargs: object) -> int:
        payload = {
            "schema": 1,
            "ok": False,
            "generation_id": GENERATION,
            "owner_token": OWNER,
            "slot_id": slot_id,
            "config_fingerprint": FINGERPRINT,
            "artifact": None,
            "caption": "",
            "error_code": "render_failed",
            "error_text": "periodic renderer failed",
        }
        side.write_text(json.dumps(payload), encoding="utf-8")
        return 1

    real_fence = process_module._require_rendering_state_fence

    def mutate_after_read(*args: object, **kwargs: object) -> None:
        original = side.read_bytes()
        side.write_bytes(original)
        real_fence(*args, **kwargs)

    monkeypatch.setattr(runner, "_run_process", failed_child)
    monkeypatch.setattr(
        process_module, "_require_rendering_state_fence", mutate_after_read
    )
    with pytest.raises(ReportProcessError, match="changed"):
        runner.generate_periodic(
            GENERATION,
            expected_slot_id=slot_id,
            expected_owner_token=OWNER,
            max_input_bytes=65_536,
        )


def test_failure_side_channel_is_suppressed_after_state_fence_loss(tmp_path: Path) -> None:
    import cryodaq.reporting.__main__ as child

    _install_rendering_state(tmp_path)
    _raw, snapshot = serialize_periodic_input(
        _payload(), expected_max_input_bytes=65_536
    )
    (tmp_path / "reporting" / "periodic_state.json").unlink()

    child._write_periodic_side_failure(
        tmp_path, snapshot, code="render_failed", text="periodic renderer failed"
    )

    assert not (
        tmp_path / "reporting" / "periodic" / "results" / f"{GENERATION}.json"
    ).exists()


def test_failure_side_result_is_atomically_published_by_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cryodaq.reporting.__main__ as child

    _install_rendering_state(tmp_path)
    _raw, snapshot = serialize_periodic_input(
        _payload(), expected_max_input_bytes=65_536
    )
    real_replace = child.os.replace
    observed: dict[str, object] = {}

    def inspect_replace(source: Path, destination: Path) -> None:
        observed["final_absent"] = not os.path.lexists(destination)
        observed["temporary"] = source.read_bytes()
        observed["mode"] = source.stat().st_mode & 0o777
        if os.path.lexists(destination):
            observed["old_code"] = read_periodic_result_file(
                destination, require_success=False
            )["error_code"]
        real_replace(source, destination)

    monkeypatch.setattr(child.os, "replace", inspect_replace)
    child._write_periodic_side_failure(
        tmp_path, snapshot, code="render_failed", text="periodic renderer failed"
    )
    side = tmp_path / "reporting" / "periodic" / "results" / f"{GENERATION}.json"
    first = side.read_bytes()
    assert observed["final_absent"] is True
    assert observed["temporary"] == first
    assert observed["mode"] == 0o600
    assert read_periodic_result_file(side, require_success=False)["ok"] is False
    assert not side.with_name(f".{side.name}.tmp").exists()

    child._write_periodic_side_failure(
        tmp_path, snapshot, code="deadline", text="periodic render deadline expired"
    )
    assert side.read_bytes() != first
    assert observed["old_code"] == "render_failed"
    assert read_periodic_result_file(side, require_success=False)["error_code"] == "deadline"


def test_failure_side_atomic_publish_fault_cleans_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cryodaq.reporting.__main__ as child

    _install_rendering_state(tmp_path)
    _raw, snapshot = serialize_periodic_input(
        _payload(), expected_max_input_bytes=65_536
    )
    monkeypatch.setattr(
        child.os,
        "replace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("injected replace")),
    )
    child._write_periodic_side_failure(
        tmp_path, snapshot, code="render_failed", text="periodic renderer failed"
    )
    side = tmp_path / "reporting" / "periodic" / "results" / f"{GENERATION}.json"
    assert not side.exists()
    assert not side.with_name(f".{side.name}.tmp").exists()


def test_partial_png_crash_has_no_success_and_retry_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cryodaq.reporting.__main__ as child
    import cryodaq.reporting.periodic_renderer as renderer

    slot_id = _install_rendering_state(tmp_path)
    write_periodic_input_file(tmp_path, _payload(), expected_max_input_bytes=65_536)

    def partial_then_crash(_snapshot: object, output_dir: Path, **_kwargs: object) -> object:
        (output_dir / "periodic.png").write_bytes(b"\x89PNG\r\n\x1a\npartial")
        raise OSError("simulated save crash")

    monkeypatch.setattr(renderer, "render_periodic_png", partial_then_crash)
    args = SimpleNamespace(
        generation_id=GENERATION,
        deadline_epoch=str(time.time() + 20),
        max_input_bytes="65536",
    )
    assert child._run_periodic(args, tmp_path) == 1
    assert not periodic_generation_dir(tmp_path, GENERATION).exists()

    runner = ReportProcessRunner(tmp_path, timeout_s=20.0)
    recovered = runner.generate_periodic(
        GENERATION,
        expected_slot_id=slot_id,
        expected_owner_token=OWNER,
        max_input_bytes=65_536,
    )
    assert recovered.artifact.path.endswith("/periodic.png")


def test_input_same_inode_late_mutation_blocks_promotion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cryodaq.reporting.__main__ as child
    import cryodaq.reporting.periodic_renderer as renderer

    _install_rendering_state(tmp_path)
    input_path = write_periodic_input_file(
        tmp_path, _payload(), expected_max_input_bytes=65_536
    )
    real_render = renderer.render_periodic_png

    def mutate_then_render(*args: object, **kwargs: object) -> object:
        with input_path.open("ab") as stream:
            stream.write(b" ")
            stream.flush()
            os.fsync(stream.fileno())
        return real_render(*args, **kwargs)

    monkeypatch.setattr(renderer, "render_periodic_png", mutate_then_render)
    args = SimpleNamespace(
        generation_id=GENERATION,
        deadline_epoch=str(time.time() + 20),
        max_input_bytes="65536",
    )
    assert child._run_periodic(args, tmp_path) == 3
    assert not periodic_generation_dir(tmp_path, GENERATION).exists()


def test_hostile_staging_quarantine_is_bounded_and_non_accumulating(tmp_path: Path) -> None:
    import cryodaq.reporting.__main__ as child

    parent = tmp_path / ".staging"
    parent.mkdir()
    staging = parent / GENERATION
    staging.mkdir()
    for name in ("periodic.png", "result.json", "unexpected"):
        (staging / name).write_bytes(b"x")

    with pytest.raises(PeriodicInputError, match="unknown entries"):
        child._clear_staging_bounded(staging)
    quarantines = list(parent.glob(".quarantine-*"))
    assert len(quarantines) == 1
    assert not staging.exists()

    staging.mkdir()
    (staging / "periodic.png").write_bytes(b"x")
    with pytest.raises(PeriodicInputError, match="quarantine"):
        child._clear_staging_bounded(staging)
    assert list(parent.glob(".quarantine-*")) == quarantines
    assert staging.exists()
