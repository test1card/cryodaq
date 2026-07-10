from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path

import pytest

from cryodaq.periodic_state import PeriodicArtifact
from cryodaq.report_process import (
    ReportProcessError,
    ReportProcessRunner,
    build_periodic_report_command,
    build_report_command,
    read_periodic_artifact_bytes,
    read_result_file,
    result_file_path,
)
from cryodaq.report_state import build_current_manifest, promote_generation
from cryodaq.reporting.periodic_input import MAX_PNG_BYTES

_PERIODIC_GENERATION = "a" * 32


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _periodic_png(*, width: int = 640, height: int = 480) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", b"bounded-test-data")
        + _png_chunk(b"IEND", b"")
    )


def _install_periodic_artifact(
    data_dir: Path, *, raw: bytes | None = None, **overrides: object
) -> tuple[PeriodicArtifact, Path, bytes]:
    content = _periodic_png() if raw is None else raw
    final = (
        data_dir
        / "reporting"
        / "periodic"
        / "generations"
        / _PERIODIC_GENERATION
    )
    final.mkdir(parents=True)
    png = final / "periodic.png"
    png.write_bytes(content)
    values: dict[str, object] = {
        "path": f"periodic/generations/{_PERIODIC_GENERATION}/periodic.png",
        "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
        "size": len(content),
        "width": 640,
        "height": 480,
        "mime": "image/png",
    }
    values.update(overrides)
    return PeriodicArtifact(**values), png, content  # type: ignore[arg-type]


def test_periodic_artifact_reader_supports_ready_and_delivery_retry_without_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, _png, raw = _install_periodic_artifact(tmp_path)

    def forbidden_path_read(_path: Path) -> bytes:
        raise AssertionError("artifact authority must use a bounded fd read")

    monkeypatch.setattr(Path, "read_bytes", forbidden_path_read)
    assert read_periodic_artifact_bytes(tmp_path, artifact) == raw
    assert read_periodic_artifact_bytes(tmp_path, artifact) == raw
    assert not (tmp_path / "reporting" / "periodic_state.json").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("path", f"periodic/generations/{'b' * 32}/periodic.png"),
        ("path", f"periodic/generations/{_PERIODIC_GENERATION}/../periodic.png"),
        ("sha256", "sha256:" + "0" * 64),
        ("sha256", "not-a-hash"),
        ("size", 1),
        ("size", True),
        ("width", 641),
        ("width", True),
        ("height", 481),
        ("mime", "image/jpeg"),
    ],
)
def test_periodic_artifact_reader_revalidates_every_descriptor_field(
    tmp_path: Path, field: str, value: object
) -> None:
    artifact, _png, _raw = _install_periodic_artifact(tmp_path, **{field: value})
    with pytest.raises(ReportProcessError, match="periodic artifact|periodic PNG"):
        read_periodic_artifact_bytes(tmp_path, artifact)


@pytest.mark.skipif(os.name == "nt", reason="POSIX link semantics")
@pytest.mark.parametrize(
    "attack", ["file_symlink", "file_hardlink", "generation_symlink", "periodic_symlink"]
)
def test_periodic_artifact_reader_rejects_linked_file_or_directory(
    tmp_path: Path, attack: str
) -> None:
    artifact, png, raw = _install_periodic_artifact(tmp_path)
    if attack == "file_symlink":
        outside = tmp_path / "outside.png"
        outside.write_bytes(raw)
        png.unlink()
        png.symlink_to(outside)
    elif attack == "file_hardlink":
        os.link(png, tmp_path / "second-link.png")
    elif attack == "generation_symlink":
        final = png.parent
        outside = tmp_path / "outside-generation"
        outside.mkdir()
        (outside / "periodic.png").write_bytes(raw)
        png.unlink()
        final.rmdir()
        final.symlink_to(outside, target_is_directory=True)
    else:
        periodic = png.parents[2]
        outside = tmp_path / "outside-periodic"
        periodic.rename(outside)
        periodic.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ReportProcessError, match="directory|single-link|unsafe"):
        read_periodic_artifact_bytes(tmp_path, artifact)


@pytest.mark.parametrize("replacement", ["file", "generation_directory"])
def test_periodic_artifact_reader_rejects_replacement_during_fd_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
) -> None:
    import cryodaq.report_process as module

    artifact, png, raw = _install_periodic_artifact(tmp_path)
    real_read = module.os.read
    replaced = False

    def replace_after_read(fd: int, amount: int) -> bytes:
        nonlocal replaced
        chunk = real_read(fd, amount)
        if chunk and not replaced:
            replaced = True
            if replacement == "file":
                candidate = png.with_name("replacement.png")
                candidate.write_bytes(raw)
                os.replace(candidate, png)
            else:
                final = png.parent
                moved = final.with_name(f"{final.name}.moved")
                final.rename(moved)
                final.mkdir()
                (final / "periodic.png").write_bytes(raw)
        return chunk

    monkeypatch.setattr(module.os, "read", replace_after_read)
    with pytest.raises(ReportProcessError, match="changed"):
        read_periodic_artifact_bytes(tmp_path, artifact)
    assert replaced is True


def test_periodic_artifact_reader_rejects_oversized_file_before_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cryodaq.report_process as module

    raw = b"x" * (MAX_PNG_BYTES + 1)
    artifact, _png, _raw = _install_periodic_artifact(
        tmp_path, raw=raw, size=MAX_PNG_BYTES
    )
    monkeypatch.setattr(
        module.os,
        "read",
        lambda *_args: (_ for _ in ()).throw(AssertionError("oversized file was read")),
    )
    with pytest.raises(ReportProcessError, match="size|large"):
        read_periodic_artifact_bytes(tmp_path, artifact)


def _assert_fixed_artifact_io_failure(error: ReportProcessError) -> None:
    assert error.error_code == "invalid_periodic_artifact"
    assert error.error_text == "periodic PNG could not be read safely"
    assert "injected" not in str(error)
    assert error.__cause__ is None


@pytest.mark.parametrize(
    "fault", ["read", "post_read_fstat", "post_read_stat", "directory_verify", "close"]
)
def test_periodic_artifact_reader_normalizes_dirfd_io_faults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    import cryodaq.report_process as module

    artifact, _png, _raw = _install_periodic_artifact(tmp_path)
    assert module.os.open in module.os.supports_dir_fd
    read_finished = False
    real_read_bounded = module._read_open_fd_bounded
    real_fstat = module.os.fstat
    real_stat = module.os.stat
    real_close = module.os.close

    if fault == "read":
        monkeypatch.setattr(
            module.os,
            "read",
            lambda *_args: (_ for _ in ()).throw(OSError("injected read path")),
        )
    elif fault in {"post_read_fstat", "post_read_stat"}:

        def mark_read_finished(fd: int, maximum: int) -> bytes:
            nonlocal read_finished
            raw = real_read_bounded(fd, maximum)
            read_finished = True
            return raw

        monkeypatch.setattr(module, "_read_open_fd_bounded", mark_read_finished)
        if fault == "post_read_fstat":

            def fail_fstat(fd: int):
                if read_finished:
                    raise OSError("injected fstat path")
                return real_fstat(fd)

            monkeypatch.setattr(module.os, "fstat", fail_fstat)
        else:

            def fail_stat(*args: object, **kwargs: object):
                if read_finished:
                    raise OSError("injected stat path")
                return real_stat(*args, **kwargs)

            monkeypatch.setattr(module.os, "stat", fail_stat)
            monkeypatch.setattr(
                module.os,
                "supports_dir_fd",
                {*module.os.supports_dir_fd, fail_stat},
            )
    elif fault == "directory_verify":
        monkeypatch.setattr(
            module,
            "_verify_open_directory_chain",
            lambda *_args: (_ for _ in ()).throw(OSError("injected directory path")),
        )
    else:
        failed = False

        def fail_close(fd: int) -> None:
            nonlocal failed
            real_close(fd)
            if not failed:
                failed = True
                raise OSError("injected close path")

        monkeypatch.setattr(module.os, "close", fail_close)

    with pytest.raises(ReportProcessError) as exc_info:
        read_periodic_artifact_bytes(tmp_path, artifact)
    _assert_fixed_artifact_io_failure(exc_info.value)


@pytest.mark.parametrize("fault", ["read", "post_read_fstat", "close"])
def test_periodic_artifact_reader_fallback_normalizes_io_faults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    import cryodaq.report_process as module

    artifact, _png, _raw = _install_periodic_artifact(tmp_path)
    monkeypatch.setattr(module.os, "supports_dir_fd", set())
    read_finished = False
    real_read_bounded = module._read_open_fd_bounded
    real_fstat = module.os.fstat
    real_close = module.os.close
    if fault == "read":
        monkeypatch.setattr(
            module.os,
            "read",
            lambda *_args: (_ for _ in ()).throw(OSError("injected fallback read")),
        )
    elif fault == "post_read_fstat":

        def mark_read_finished(fd: int, maximum: int) -> bytes:
            nonlocal read_finished
            raw = real_read_bounded(fd, maximum)
            read_finished = True
            return raw

        def fail_fstat(fd: int):
            if read_finished:
                raise OSError("injected fallback fstat")
            return real_fstat(fd)

        monkeypatch.setattr(module, "_read_open_fd_bounded", mark_read_finished)
        monkeypatch.setattr(module.os, "fstat", fail_fstat)
    else:
        failed = False

        def fail_close(fd: int) -> None:
            nonlocal failed
            real_close(fd)
            if not failed:
                failed = True
                raise OSError("injected fallback close")

        monkeypatch.setattr(module.os, "close", fail_close)

    with pytest.raises(ReportProcessError) as exc_info:
        read_periodic_artifact_bytes(tmp_path, artifact)
    _assert_fixed_artifact_io_failure(exc_info.value)


def test_periodic_artifact_reader_close_fault_preserves_existing_contract_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cryodaq.report_process as module

    artifact, _png, _raw = _install_periodic_artifact(tmp_path)
    real_close = module.os.close
    failed = False

    monkeypatch.setattr(
        module.os,
        "read",
        lambda *_args: (_ for _ in ()).throw(
            ReportProcessError("sentinel_contract", "original contract failure")
        ),
    )

    def fail_close(fd: int) -> None:
        nonlocal failed
        real_close(fd)
        if not failed:
            failed = True
            raise OSError("injected masking close")

    monkeypatch.setattr(module.os, "close", fail_close)
    with pytest.raises(ReportProcessError) as exc_info:
        read_periodic_artifact_bytes(tmp_path, artifact)
    assert exc_info.value.error_code == "sentinel_contract"
    assert exc_info.value.error_text == "original contract failure"


@pytest.mark.parametrize("mutation", ["trailing", "bad_crc", "missing_idat", "truncated"])
def test_periodic_artifact_reader_rejects_invalid_full_png_contract(
    tmp_path: Path, mutation: str
) -> None:
    valid = _periodic_png()
    if mutation == "trailing":
        raw = valid + b"trailing"
    elif mutation == "bad_crc":
        raw = bytearray(valid)
        raw[45] ^= 1
        raw = bytes(raw)
    elif mutation == "missing_idat":
        ihdr = struct.pack(">IIBBBBB", 640, 480, 8, 2, 0, 0, 0)
        raw = b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr) + _png_chunk(
            b"IEND", b""
        )
    else:
        raw = valid[:-1]
    artifact, _png, _raw = _install_periodic_artifact(tmp_path, raw=raw)
    with pytest.raises(ReportProcessError, match="periodic PNG"):
        read_periodic_artifact_bytes(tmp_path, artifact)


def test_development_command_uses_module_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    command = build_report_command("exp-1", "generation-token-0001", deadline_epoch=123.0)
    assert command[:4] == [sys.executable, "-m", "cryodaq.reporting", "experiment"]
    assert "--experiment-id=exp-1" in command
    assert "--generation-id=generation-token-0001" in command


def test_frozen_command_reinvokes_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/opt/CryoDAQ.exe")
    command = build_report_command("exp-1", "generation-token-0001", deadline_epoch=123.0)
    assert command[:3] == ["/opt/CryoDAQ.exe", "--mode=report-render", "experiment"]
    assert "-m" not in command


@pytest.mark.parametrize("frozen", [False, True])
def test_periodic_development_and_frozen_commands_are_fixed(
    monkeypatch: pytest.MonkeyPatch, frozen: bool
) -> None:
    if frozen:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", "/opt/CryoDAQ.exe")
        prefix = ["/opt/CryoDAQ.exe", "--mode=report-render", "periodic"]
    else:
        monkeypatch.delattr(sys, "frozen", raising=False)
        prefix = [sys.executable, "-m", "cryodaq.reporting", "periodic"]
    command = build_periodic_report_command(
        "a" * 32, deadline_epoch=123.0, max_input_bytes=65_536
    )
    assert command[: len(prefix)] == prefix
    assert command[-3:] == [
        f"--generation-id={'a' * 32}",
        "--deadline-epoch=123.000000",
        "--max-input-bytes=65536",
    ]
    assert not any("token" in item or "chat" in item or "/input" in item for item in command)


def test_automatic_command_carries_locked_state_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    command = build_report_command(
        "exp-1",
        "generation-token-0001",
        deadline_epoch=123.0,
        automatic=True,
    )
    assert "--automatic" in command


@pytest.mark.parametrize("frozen", [False, True])
def test_force_command_uses_fixed_argv_elements_only(
    monkeypatch: pytest.MonkeyPatch,
    frozen: bool,
) -> None:
    if frozen:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", "/opt/CryoDAQ.exe")
    else:
        monkeypatch.delattr(sys, "frozen", raising=False)
    command = build_report_command(
        "exp-1",
        "generation-token-0001",
        deadline_epoch=123.0,
        force=True,
        force_context="a" * 64,
        operator="Operator Name",
    )
    assert command[-3:] == [
        "--force",
        f"--force-context={'a' * 64}",
        "--operator=Operator Name",
    ]
    assert "--automatic" not in command


@pytest.mark.parametrize(
    "kwargs",
    [
        {"force": True},
        {"force": True, "force_context": "a" * 64, "operator": "bad\nname"},
        {"force_context": "a" * 64},
        {"automatic": True, "force": True, "force_context": "a" * 64, "operator": "Op"},
    ],
)
def test_force_command_rejects_incomplete_or_ambiguous_authority(kwargs: dict) -> None:
    with pytest.raises(ReportProcessError, match="invalid_force"):
        build_report_command(
            "exp-1",
            "generation-token-0001",
            deadline_epoch=123.0,
            **kwargs,
        )


def test_process_error_preserves_bounded_structured_code() -> None:
    error = ReportProcessError("force_required", "confirmation required")
    assert error.error_code == "force_required"
    assert error.error_text == "confirmation required"


def test_legacy_one_argument_process_error_preserves_known_prefix() -> None:
    error = ReportProcessError("busy: another child owns the lock")
    assert str(error) == "busy: another child owns the lock"
    assert error.error_code == "busy"
    assert error.error_text == "another child owns the lock"


def test_result_file_is_size_and_schema_bounded(tmp_path: Path) -> None:
    result = tmp_path / "result.json"
    result.write_text(json.dumps({"schema": 1, "ok": True, "report": {}}), encoding="utf-8")
    with pytest.raises(ReportProcessError):
        read_result_file(result)
    result.write_bytes(b"{" + b"x" * (128 * 1024) + b"}")
    with pytest.raises(ReportProcessError, match="too large"):
        read_result_file(result)


def test_result_schema_rejects_json_boolean(tmp_path: Path) -> None:
    result = tmp_path / "result.json"
    result.write_text(
        json.dumps(
            {
                "schema": True,
                "ok": False,
                "generation_id": "generation-token-0001",
                "report": None,
                "error_code": "failed",
                "error_text": "",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ReportProcessError, match="unsupported schema"):
        read_result_file(result)


def test_parent_recovers_nonzero_child_after_manifest_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.report_process as module

    experiment_root = tmp_path / "experiments" / "exp-1"
    experiment_root.mkdir(parents=True)
    (experiment_root / "metadata.json").write_text("{}", encoding="utf-8")
    generation_id = "generation-token-0001"
    staging = experiment_root / "reports" / ".staging" / generation_id
    staging.mkdir(parents=True)
    (staging / "assets").mkdir()
    (staging / "report_editable.docx").write_bytes(b"docx")
    manifest = build_current_manifest(
        experiment_root,
        generation_id=generation_id,
        source_fingerprint="sha256:" + "1" * 64,
        sections=("title_page",),
        skipped=False,
        reason="",
    )
    promote_generation(experiment_root, generation_id, manifest)
    runner = ReportProcessRunner(tmp_path, timeout_s=0.5)
    monkeypatch.setattr(module.secrets, "token_hex", lambda _n: generation_id)
    monkeypatch.setattr(runner, "_run_process", lambda *_args, **_kwargs: 7)

    report = runner.generate_experiment("exp-1")

    assert report["docx_path"].endswith("reports/generations/generation-token-0001/report_editable.docx")


def test_parent_does_not_recover_nonzero_without_valid_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.report_process as module

    experiment_root = tmp_path / "experiments" / "exp-1"
    experiment_root.mkdir(parents=True)
    (experiment_root / "metadata.json").write_text("{}", encoding="utf-8")
    generation_id = "generation-token-0001"
    runner = ReportProcessRunner(tmp_path, timeout_s=0.5)
    monkeypatch.setattr(module.secrets, "token_hex", lambda _n: generation_id)
    monkeypatch.setattr(runner, "_run_process", lambda *_args, **_kwargs: 7)

    with pytest.raises(ReportProcessError):
        runner.generate_experiment("exp-1")


@pytest.mark.parametrize("result_kind", ["valid_success", "valid_failure", "malformed"])
def test_parent_nonzero_always_trusts_matching_manifest_over_result_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    result_kind: str,
) -> None:
    import cryodaq.report_process as module

    experiment_root = tmp_path / "experiments" / "exp-1"
    experiment_root.mkdir(parents=True)
    (experiment_root / "metadata.json").write_text("{}", encoding="utf-8")
    generation_id = "generation-token-0001"
    staging = experiment_root / "reports" / ".staging" / generation_id
    staging.mkdir(parents=True)
    (staging / "assets").mkdir()
    (staging / "report_editable.docx").write_bytes(b"docx")
    manifest = build_current_manifest(
        experiment_root,
        generation_id=generation_id,
        source_fingerprint="sha256:" + "1" * 64,
        sections=("title_page",),
        skipped=False,
        reason="",
    )
    promote_generation(experiment_root, generation_id, manifest)
    runner = ReportProcessRunner(tmp_path, timeout_s=0.5)
    monkeypatch.setattr(module.secrets, "token_hex", lambda _n: generation_id)

    def nonzero_with_result(*_args, **_kwargs) -> int:
        path = result_file_path(tmp_path, generation_id)
        if result_kind == "malformed":
            path.write_text("{", encoding="utf-8")
        else:
            ok = result_kind == "valid_success"
            payload = {
                "schema": 1,
                "ok": ok,
                "generation_id": generation_id,
                "report": (
                    {
                        "docx_path": "/untrusted/docx",
                        "pdf_path": None,
                        "assets_dir": "/untrusted/assets",
                        "sections": [],
                        "skipped": False,
                        "reason": "",
                    }
                    if ok
                    else None
                ),
                "error_code": None if ok else "crashed",
                "error_text": "" if ok else "after commit",
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
        return 7

    monkeypatch.setattr(runner, "_run_process", nonzero_with_result)

    report = runner.generate_experiment("exp-1")
    assert report["docx_path"].endswith("reports/generations/generation-token-0001/report_editable.docx")


def test_forced_parent_surfaces_audit_failure_after_manifest_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.report_process as module

    experiment_root = tmp_path / "experiments" / "exp-1"
    experiment_root.mkdir(parents=True)
    (experiment_root / "metadata.json").write_text("{}", encoding="utf-8")
    generation_id = "generation-token-0001"
    staging = experiment_root / "reports" / ".staging" / generation_id
    staging.mkdir(parents=True)
    (staging / "assets").mkdir()
    (staging / "report_editable.docx").write_bytes(b"docx")
    manifest = build_current_manifest(
        experiment_root,
        generation_id=generation_id,
        source_fingerprint="sha256:" + "1" * 64,
        sections=("title_page",),
        skipped=False,
        reason="",
    )
    promote_generation(experiment_root, generation_id, manifest)
    runner = ReportProcessRunner(tmp_path, timeout_s=0.5)
    monkeypatch.setattr(module.secrets, "token_hex", lambda _n: generation_id)

    def audit_failure_result(*_args, **_kwargs) -> int:
        result_file_path(tmp_path, generation_id).write_text(
            json.dumps(
                {
                    "schema": 1,
                    "ok": False,
                    "generation_id": generation_id,
                    "report": None,
                    "error_code": "force_audit_incomplete",
                    "error_text": "completion audit failed",
                }
            ),
            encoding="utf-8",
        )
        return 3

    monkeypatch.setattr(runner, "_run_process", audit_failure_result)

    with pytest.raises(ReportProcessError) as exc_info:
        runner.generate_experiment_detailed(
            "exp-1",
            force=True,
            force_context="a" * 64,
            operator="Operator",
        )
    assert exc_info.value.error_code == "force_audit_incomplete"


@pytest.mark.skipif(os.name == "nt", reason="POSIX process group assertion")
def test_timeout_kills_nested_descendant(tmp_path: Path) -> None:
    pid_file = tmp_path / "nested.pid"
    fake_soffice = tmp_path / "fake_soffice.py"
    fake_soffice.write_text("import time; time.sleep(60)\n", encoding="utf-8")
    script = tmp_path / "report_child.py"
    script.write_text(
        "import subprocess,sys,time\n"
        "p=subprocess.Popen([sys.executable,sys.argv[1]])\n"
        "open(sys.argv[2],'w').write(str(p.pid))\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    runner = ReportProcessRunner(tmp_path, timeout_s=0.5)
    with pytest.raises(ReportProcessError, match="timed out"):
        runner._run_process([sys.executable, str(script), str(fake_soffice), str(pid_file)])
    pid = int(pid_file.read_text(encoding="ascii"))
    for _ in range(30):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"nested child {pid} survived report timeout")


def test_windows_cleanup_abstraction_uses_taskkill(monkeypatch: pytest.MonkeyPatch) -> None:
    import cryodaq.report_process as module

    calls: list[list[str]] = []
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda argv, **_kwargs: calls.append(list(argv)) or subprocess.CompletedProcess(argv, 0),
    )
    module.terminate_process_tree(321, grace_s=0.0)
    assert calls == [["taskkill", "/PID", "321", "/T", "/F"]]


def test_windows_job_closes_on_ordinary_nonzero_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.report_process as module

    events: list[str] = []

    class FakeProcess:
        pid = 321

        def wait(self, timeout: float | None = None) -> int:
            events.append("wait")
            return 7

    class FakeJob:
        closed = False

        def close(self) -> None:
            events.append("close")
            self.closed = True

    process = FakeProcess()
    job = FakeJob()
    runner = ReportProcessRunner(tmp_path, timeout_s=0.5)
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setattr(module, "_creation_kwargs", lambda: {})
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(
        module,
        "_create_windows_job",
        lambda _process: events.append("assign") or job,
    )

    assert runner._run_process(["fixed-child"]) == 7
    assert job.closed is True
    assert events == ["assign", "wait", "close"]


def test_windows_job_closes_on_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.report_process as module

    class FakeProcess:
        pid = 321
        waits = 0

        def wait(self, timeout: float | None = None) -> int:
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("fixed-child", timeout)
            return 1

        def kill(self) -> None:
            pass

    class FakeJob:
        closes = 0

        def close(self) -> None:
            self.closes += 1

    process = FakeProcess()
    job = FakeJob()
    runner = ReportProcessRunner(tmp_path, timeout_s=0.5)
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setattr(module, "_creation_kwargs", lambda: {})
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(module, "_create_windows_job", lambda _process: job)

    with pytest.raises(ReportProcessError, match="timed out"):
        runner._run_process(["fixed-child"])
    assert job.closes >= 1


def test_windows_job_assignment_failure_kills_tree_and_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.report_process as module

    class FakeProcess:
        pid = 321

        def wait(self, timeout: float | None = None) -> int:
            return 1

    events: list[int] = []
    runner = ReportProcessRunner(tmp_path, timeout_s=0.5)
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setattr(module, "_creation_kwargs", lambda: {})
    monkeypatch.setattr(
        module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: FakeProcess(),
    )
    monkeypatch.setattr(
        module,
        "_create_windows_job",
        lambda _process: (_ for _ in ()).throw(OSError("assignment failed")),
    )
    monkeypatch.setattr(
        module,
        "terminate_process_tree",
        lambda pid: events.append(pid),
    )

    with pytest.raises(ReportProcessError, match="Windows Job Object"):
        runner._run_process(["fixed-child"])
    assert events == [321]


def test_windows_job_assignment_failure_forces_kill_when_wait_times_out(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.report_process as module

    class FakeProcess:
        pid = 321
        waits = 0
        killed = False

        def wait(self, timeout: float | None = None) -> int:
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("fixed-child", timeout)
            return 1

        def kill(self) -> None:
            self.killed = True

    process = FakeProcess()
    runner = ReportProcessRunner(tmp_path, timeout_s=0.5)
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setattr(module, "_creation_kwargs", lambda: {})
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(
        module,
        "_create_windows_job",
        lambda _process: (_ for _ in ()).throw(OSError("assignment failed")),
    )
    monkeypatch.setattr(module, "terminate_process_tree", lambda _pid: None)

    with pytest.raises(ReportProcessError, match="Windows Job Object"):
        runner._run_process(["fixed-child"])
    assert process.killed is True
    assert process.waits == 2


def test_windows_job_assignment_failure_survives_throwing_taskkill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.report_process as module

    class FakeProcess:
        pid = 321
        waits = 0
        killed = False

        def wait(self, timeout: float | None = None) -> int:
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("fixed-child", timeout)
            return 1

        def kill(self) -> None:
            self.killed = True

    process = FakeProcess()
    runner = ReportProcessRunner(tmp_path, timeout_s=0.5)
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setattr(module, "_creation_kwargs", lambda: {})
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(
        module,
        "_create_windows_job",
        lambda _process: (_ for _ in ()).throw(OSError("assignment failed")),
    )
    monkeypatch.setattr(
        module,
        "terminate_process_tree",
        lambda _pid: (_ for _ in ()).throw(subprocess.TimeoutExpired("taskkill", 2.0)),
    )

    with pytest.raises(ReportProcessError, match="Windows Job Object"):
        runner._run_process(["fixed-child"])
    assert process.killed is True
    assert process.waits == 2


def test_reporting_package_and_engine_do_not_eagerly_import_generator() -> None:
    code = (
        "import sys; import cryodaq.reporting; import cryodaq.engine; "
        "assert 'cryodaq.reporting.generator' not in sys.modules; "
        "assert 'cryodaq.reporting.sections' not in sys.modules; "
        "assert 'cryodaq.notifications.periodic_report' not in sys.modules; "
        "assert 'docx' not in sys.modules; "
        "assert 'matplotlib' not in sys.modules"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
