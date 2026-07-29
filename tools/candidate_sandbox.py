"""Drop candidate commands below the authority of their sealed export."""

from __future__ import annotations

import ctypes
import errno
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _windows_restricted_token() -> int:
    """Return a write-restricted primary token with only test-required privileges."""

    from ctypes import wintypes

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("sid", ctypes.c_void_p), ("attributes", wintypes.DWORD)]

    class Luid(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.LONG)]

    class LuidAndAttributes(ctypes.Structure):
        _fields_ = [("luid", Luid), ("attributes", wintypes.DWORD)]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.CreateRestrictedToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(SidAndAttributes),
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.AdjustTokenPrivileges.argtypes = [
        wintypes.HANDLE,
        wintypes.BOOL,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    advapi32.LookupPrivilegeValueW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.POINTER(Luid),
    ]
    token = wintypes.HANDLE()
    restricted = wintypes.HANDLE()
    sid = ctypes.c_void_p()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(),
        0x0001 | 0x0002 | 0x0008 | 0x0020 | 0x0080,
        # TOKEN_ASSIGN_PRIMARY | TOKEN_DUPLICATE | TOKEN_QUERY |
        # TOKEN_ADJUST_PRIVILEGES | TOKEN_ADJUST_DEFAULT
        ctypes.byref(token),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not advapi32.ConvertStringSidToSidW("S-1-5-12", ctypes.byref(sid)):
            raise ctypes.WinError(ctypes.get_last_error())
        restricting_sid = SidAndAttributes(sid, 0)
        if not advapi32.CreateRestrictedToken(
            token,
            0x00000008,  # WRITE_RESTRICTED: restricting SIDs apply only to writes
            0,
            None,
            0,
            None,
            1,
            ctypes.byref(restricting_sid),
            ctypes.byref(restricted),
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        required = wintypes.DWORD()
        advapi32.GetTokenInformation(restricted, 3, None, 0, ctypes.byref(required))
        privileges = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            restricted,
            3,
            privileges,
            required.value,
            ctypes.byref(required),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        count = ctypes.cast(privileges, ctypes.POINTER(wintypes.DWORD)).contents.value

        class TokenPrivileges(ctypes.Structure):
            _fields_ = [
                ("count", wintypes.DWORD),
                ("privileges", LuidAndAttributes * count),
            ]

        privilege_set = ctypes.cast(privileges, ctypes.POINTER(TokenPrivileges)).contents
        retained_privileges: set[tuple[int, int]] = set()
        for name in ("SeChangeNotifyPrivilege", "SeCreateSymbolicLinkPrivilege"):
            luid = Luid()
            if not advapi32.LookupPrivilegeValueW(None, name, ctypes.byref(luid)):
                raise ctypes.WinError(ctypes.get_last_error())
            retained_privileges.add((luid.low, luid.high))
        for privilege in privilege_set.privileges:
            if (privilege.luid.low, privilege.luid.high) not in retained_privileges:
                privilege.attributes = 0x00000004  # SE_PRIVILEGE_REMOVED
            else:
                privilege.attributes = 0x00000002  # SE_PRIVILEGE_ENABLED
        ctypes.set_last_error(0)
        if not advapi32.AdjustTokenPrivileges(
            restricted,
            False,
            ctypes.byref(privilege_set),
            0,
            None,
            None,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 1300:  # ERROR_NOT_ALL_ASSIGNED
            raise ctypes.WinError(ctypes.get_last_error())
        value = restricted.value
        restricted = wintypes.HANDLE()
        return value
    finally:
        if sid:
            kernel32.LocalFree(sid)
        kernel32.CloseHandle(token)
        if restricted.value:
            kernel32.CloseHandle(restricted)


def _windows_run_restricted(cwd: Path, state_root: Path, command: list[str]) -> int:
    from ctypes import wintypes

    class StartupInfo(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("reserved", wintypes.LPWSTR),
            ("desktop", wintypes.LPWSTR),
            ("title", wintypes.LPWSTR),
            ("x", wintypes.DWORD),
            ("y", wintypes.DWORD),
            ("x_size", wintypes.DWORD),
            ("y_size", wintypes.DWORD),
            ("x_chars", wintypes.DWORD),
            ("y_chars", wintypes.DWORD),
            ("fill", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("show", wintypes.WORD),
            ("reserved_size", wintypes.WORD),
            ("reserved_bytes", ctypes.POINTER(ctypes.c_ubyte)),
            ("stdin", wintypes.HANDLE),
            ("stdout", wintypes.HANDLE),
            ("stderr", wintypes.HANDLE),
        ]

    class ProcessInformation(ctypes.Structure):
        _fields_ = [
            ("process", wintypes.HANDLE),
            ("thread", wintypes.HANDLE),
            ("process_id", wintypes.DWORD),
            ("thread_id", wintypes.DWORD),
        ]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.CreateProcessAsUserW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(StartupInfo),
        ctypes.POINTER(ProcessInformation),
    ]
    kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel32.GetStdHandle.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    if _windows_has_restricting_sid():
        raise PermissionError(
            "nested Windows candidate execution is unavailable under an active write-restricted token"
        )

    token = wintypes.HANDLE(_windows_restricted_token())
    child_command = [
        sys.executable,
        "-I",
        "-B",
        str(Path(__file__).resolve(strict=True)),
        "--restricted-child",
        str(cwd),
        str(state_root),
        "--",
        *command,
    ]
    command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(child_command))
    startup = StartupInfo()
    startup.cb = ctypes.sizeof(startup)
    startup.flags = 0x00000100  # STARTF_USESTDHANDLES
    startup.stdin = kernel32.GetStdHandle(wintypes.DWORD(-10).value)
    startup.stdout = kernel32.GetStdHandle(wintypes.DWORD(-11).value)
    startup.stderr = kernel32.GetStdHandle(wintypes.DWORD(-12).value)
    process = ProcessInformation()
    try:
        if not advapi32.CreateProcessAsUserW(
            token,
            sys.executable,
            command_line,
            None,
            None,
            True,
            0,
            None,
            str(state_root),
            ctypes.byref(startup),
            ctypes.byref(process),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if kernel32.WaitForSingleObject(process.process, 0xFFFFFFFF) != 0:
                raise ctypes.WinError(ctypes.get_last_error())
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(process.process, ctypes.byref(exit_code)):
                raise ctypes.WinError(ctypes.get_last_error())
            return exit_code.value
        finally:
            kernel32.CloseHandle(process.thread)
            kernel32.CloseHandle(process.process)
    finally:
        kernel32.CloseHandle(token)


def _windows_has_restricting_sid() -> bool:
    from ctypes import wintypes

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("sid", ctypes.c_void_p), ("attributes", wintypes.DWORD)]

    class TokenGroups(ctypes.Structure):
        _fields_ = [("count", wintypes.DWORD), ("groups", SidAndAttributes * 1)]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    token = wintypes.HANDLE()
    expected = ctypes.c_void_p()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not advapi32.ConvertStringSidToSidW("S-1-5-12", ctypes.byref(expected)):
            raise ctypes.WinError(ctypes.get_last_error())
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 11, None, 0, ctypes.byref(required))
        if not required.value:
            return False
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token,
            11,
            buffer,
            required.value,
            ctypes.byref(required),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        count = ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD)).contents.value
        first = ctypes.addressof(buffer) + TokenGroups.groups.offset
        return any(
            advapi32.EqualSid(
                SidAndAttributes.from_address(first + index * ctypes.sizeof(SidAndAttributes)).sid,
                expected,
            )
            for index in range(count)
        )
    finally:
        if expected:
            kernel32.LocalFree(expected)
        kernel32.CloseHandle(token)


def _windows_security_diagnostic() -> dict[str, object]:
    from ctypes import wintypes

    class Luid(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.LONG)]

    class LuidAndAttributes(ctypes.Structure):
        _fields_ = [("luid", Luid), ("attributes", wintypes.DWORD)]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi32.LookupPrivilegeNameW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(Luid),
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.IsTokenRestricted.argtypes = [wintypes.HANDLE]

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 25, None, 0, ctypes.byref(required))
        integrity_buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token,
            25,
            integrity_buffer,
            required.value,
            ctypes.byref(required),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        integrity_sid = ctypes.cast(integrity_buffer, ctypes.POINTER(ctypes.c_void_p)).contents
        integrity_text = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(integrity_sid, ctypes.byref(integrity_text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            integrity = integrity_text.value
        finally:
            kernel32.LocalFree(integrity_text)

        required = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 3, None, 0, ctypes.byref(required))
        privilege_buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token,
            3,
            privilege_buffer,
            required.value,
            ctypes.byref(required),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        count = ctypes.cast(privilege_buffer, ctypes.POINTER(wintypes.DWORD)).contents.value

        class TokenPrivileges(ctypes.Structure):
            _fields_ = [
                ("count", wintypes.DWORD),
                ("privileges", LuidAndAttributes * count),
            ]

        privilege_set = ctypes.cast(privilege_buffer, ctypes.POINTER(TokenPrivileges)).contents
        privileges: list[str] = []
        for privilege in privilege_set.privileges:
            size = wintypes.DWORD(0)
            advapi32.LookupPrivilegeNameW(None, ctypes.byref(privilege.luid), None, ctypes.byref(size))
            name = ctypes.create_unicode_buffer(size.value + 1)
            if not advapi32.LookupPrivilegeNameW(None, ctypes.byref(privilege.luid), name, ctypes.byref(size)):
                raise ctypes.WinError(ctypes.get_last_error())
            privileges.append(name.value)
        privilege_names = sorted(privileges)
        expected_privileges = ["SeChangeNotifyPrivilege", "SeCreateSymbolicLinkPrivilege"]
        if privilege_names != expected_privileges:
            raise RuntimeError(f"candidate restricted token privileges are not exact: {privilege_names!r}")
        restricted_code_sid = _windows_has_restricting_sid()
        if not restricted_code_sid:
            raise RuntimeError("candidate token is missing the Restricted Code write SID")
        restricted = bool(advapi32.IsTokenRestricted(token))
        if not restricted:
            raise RuntimeError("candidate token is not reported as restricted")
        return {
            "integrity_sid": integrity,
            "privileges": privilege_names,
            "restricted": restricted,
            "restricted_code_sid": restricted_code_sid,
        }
    finally:
        kernel32.CloseHandle(token)


def _windows_token_escape_diagnostic() -> dict[str, int]:
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]

    ctypes.set_last_error(0)
    duplicate_process = kernel32.OpenProcess(0x0040, False, os.getppid())  # PROCESS_DUP_HANDLE
    duplicate_process_error = ctypes.get_last_error()
    if duplicate_process:
        kernel32.CloseHandle(duplicate_process)
        raise RuntimeError("candidate restricted token can duplicate trusted parent handles")

    ctypes.set_last_error(0)
    parent = kernel32.OpenProcess(0x1000, False, os.getppid())  # PROCESS_QUERY_LIMITED_INFORMATION
    parent_error = ctypes.get_last_error()
    parent_token_error = 0
    if parent:
        try:
            parent_token = wintypes.HANDLE()
            ctypes.set_last_error(0)
            if advapi32.OpenProcessToken(
                parent,
                0x0001 | 0x0002 | 0x0008,  # ASSIGN_PRIMARY | DUPLICATE | QUERY
                ctypes.byref(parent_token),
            ):
                kernel32.CloseHandle(parent_token)
                raise RuntimeError("candidate restricted token can duplicate the trusted parent token")
            parent_token_error = ctypes.get_last_error()
        finally:
            kernel32.CloseHandle(parent)

    current = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(current)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        linked = wintypes.HANDLE()
        returned = wintypes.DWORD()
        ctypes.set_last_error(0)
        if advapi32.GetTokenInformation(
            current,
            19,  # TokenLinkedToken
            ctypes.byref(linked),
            ctypes.sizeof(linked),
            ctypes.byref(returned),
        ):
            kernel32.CloseHandle(linked)
            raise RuntimeError("candidate restricted token exposes an unrestricted linked token")
        linked_token_error = ctypes.get_last_error()
    finally:
        kernel32.CloseHandle(current)
    return {
        "duplicate_parent_process_error": duplicate_process_error,
        "linked_token_error": linked_token_error,
        "parent_process_error": parent_error,
        "parent_token_error": parent_token_error,
    }


def _chown_posix_tree(state_root: Path, uid: int, gid: int) -> None:
    for current, directories, files in os.walk(state_root):
        for name in (*directories, *files):
            os.chown(Path(current) / name, uid, gid, follow_symlinks=False)
    os.chown(state_root, uid, gid, follow_symlinks=False)


def _drop_posix(state_root: Path) -> None:
    import pwd

    if os.geteuid() != 0:
        raise PermissionError("POSIX candidate sandbox requires passwordless sudo")
    nobody = pwd.getpwnam("nobody")
    _chown_posix_tree(state_root, nobody.pw_uid, nobody.pw_gid)
    os.setgroups([])
    os.setgid(nobody.pw_gid)
    os.setuid(nobody.pw_uid)


def _linux_libc() -> ctypes.CDLL:
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mount.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_ulong,
        ctypes.c_void_p,
    ]
    libc.prctl.argtypes = [
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
    ]
    libc.unshare.argtypes = [ctypes.c_int]
    return libc


def _linux_check(result: int, operation: str) -> None:
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, f"{operation}: {os.strerror(error)}")


def _linux_mount(source: Path | None, target: Path, flags: int) -> None:
    libc = _linux_libc()
    encoded_source = None if source is None else os.fsencode(source)
    _linux_check(
        libc.mount(encoded_source, os.fsencode(target), None, flags, None),
        f"mount {source!s} -> {target}",
    )


def _rewrite_path(value: str, source: Path, alias: Path) -> str:
    path = Path(value)
    if not path.is_absolute():
        return value
    try:
        relative = path.relative_to(source)
    except ValueError:
        return value
    return str(alias / relative)


def _rewrite_posix_environment(
    environment: dict[str, str],
    *,
    export_root: Path,
    export_alias: Path,
    state_root: Path,
    state_alias: Path,
) -> dict[str, str]:
    rewritten = dict(environment)
    for key in (
        "COVERAGE_FILE",
        "CRYODAQ_CANDIDATE_PYTEST_BASETEMP",
        "CRYODAQ_STATE_ROOT",
        "MPLCONFIGDIR",
        "NUMBA_CACHE_DIR",
        "PYTHONPYCACHEPREFIX",
        "TEMP",
        "TMP",
        "TMPDIR",
        "XDG_CACHE_HOME",
    ):
        value = rewritten.get(key)
        if value is None:
            continue
        value = _rewrite_path(value, export_root, export_alias)
        rewritten[key] = _rewrite_path(value, state_root, state_alias)
    if "PYTHONPATH" in rewritten:
        paths = []
        for value in rewritten["PYTHONPATH"].split(os.pathsep):
            value = _rewrite_path(value, export_root, export_alias)
            paths.append(_rewrite_path(value, state_root, state_alias))
        rewritten["PYTHONPATH"] = os.pathsep.join(paths)
    return rewritten


def _write_must_be_refused(root: Path, name: str) -> int:
    path = root / f".cryodaq-{name}-write-probe"
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError as exc:
        if exc.errno not in {errno.EACCES, errno.EPERM, errno.EROFS}:
            raise
        return exc.errno
    else:
        os.close(descriptor)
        raise RuntimeError(f"candidate sandbox allowed export write through {root}")


def _existing_file_write_must_be_refused(path: Path) -> int:
    try:
        descriptor = os.open(path, os.O_WRONLY)
    except OSError as exc:
        if exc.errno not in {errno.EACCES, errno.EPERM, errno.EROFS}:
            raise
        return exc.errno
    else:
        os.close(descriptor)
        raise RuntimeError(f"candidate sandbox allowed trusted-launcher write through {path}")


def _candidate_preflight(
    export_root: Path,
    state_root: Path,
    *,
    launcher: Path,
    original_export_root: Path | None = None,
    platform_diagnostic: dict[str, object],
) -> None:
    state_probe = state_root / ".cryodaq-state-write-probe"
    state_probe.write_bytes(b"state-writable")
    state_probe.unlink()

    copy_writable = False
    descriptor_manifest = export_root / "config" / "channel_descriptors.yaml"
    if descriptor_manifest.is_file():
        copied = state_root / ".cryodaq-mode-copy-probe.yaml"
        shutil.copy2(descriptor_manifest, copied)
        copied.write_bytes(copied.read_bytes())
        copied.unlink()
        copy_writable = True

    strict_descriptor_read = "absent"
    if descriptor_manifest.is_file():
        sys.path.insert(0, str(export_root / "src"))
        try:
            from cryodaq.storage.channel_descriptors import load_live_channel_descriptor_catalog

            load_live_channel_descriptor_catalog(descriptor_manifest)
            strict_descriptor_read = "ok"
        finally:
            sys.path.pop(0)

    write_refusals = {"alias": _write_must_be_refused(export_root, "alias")}
    if original_export_root is not None and original_export_root != export_root:
        write_refusals["original"] = _write_must_be_refused(original_export_root, "original")
    write_refusals["trusted_launcher"] = _existing_file_write_must_be_refused(launcher.resolve(strict=True))

    symlink_creation = "not-required"
    if os.name == "nt":
        target = state_root / ".cryodaq-symlink-target"
        link = state_root / ".cryodaq-symlink-probe"
        target.write_bytes(b"target")
        try:
            link.symlink_to(target)
            symlink_creation = "ok"
        finally:
            if link.is_symlink():
                link.unlink()
            target.unlink()

    print(
        "candidate-sandbox-preflight "
        + json.dumps(
            {
                **platform_diagnostic,
                "copy_writable": copy_writable,
                "state_writable": True,
                "strict_descriptor_read": strict_descriptor_read,
                "symlink_creation": symlink_creation,
                "write_refusals": write_refusals,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        file=sys.stderr,
        flush=True,
    )


def _landlock_state_only_writes(state_root: Path) -> int:
    class RulesetAttribute(ctypes.Structure):
        _fields_ = [("handled_access_fs", ctypes.c_uint64)]

    class PathBeneathAttribute(ctypes.Structure):
        _fields_ = [
            ("allowed_access", ctypes.c_uint64),
            ("parent_fd", ctypes.c_int32),
        ]

    libc = _linux_libc()
    libc.syscall.restype = ctypes.c_long

    def landlock_call(number: int, *arguments: object) -> int:
        result = libc.syscall(number, *arguments)
        if result < 0:
            error = ctypes.get_errno()
            raise OSError(error, f"Landlock syscall {number}: {os.strerror(error)}")
        return result

    abi = landlock_call(444, None, 0, 1)  # LANDLOCK_CREATE_RULESET_VERSION
    if abi < 3:
        raise RuntimeError(f"Landlock ABI {abi} lacks refer/truncate enforcement")
    handled = (
        (1 << 1)  # WRITE_FILE
        | (1 << 4)  # REMOVE_DIR
        | (1 << 5)  # REMOVE_FILE
        | (1 << 6)  # MAKE_CHAR
        | (1 << 7)  # MAKE_DIR
        | (1 << 8)  # MAKE_REG
        | (1 << 9)  # MAKE_SOCK
        | (1 << 10)  # MAKE_FIFO
        | (1 << 11)  # MAKE_BLOCK
        | (1 << 12)  # MAKE_SYM
        | (1 << 13)  # REFER
        | (1 << 14)  # TRUNCATE
    )
    ruleset_attribute = RulesetAttribute(handled)
    ruleset = landlock_call(
        444,
        ctypes.byref(ruleset_attribute),
        ctypes.sizeof(ruleset_attribute),
        0,
    )
    state_descriptor = os.open(state_root, os.O_PATH | os.O_CLOEXEC)
    try:
        path_beneath = PathBeneathAttribute(handled, state_descriptor)
        landlock_call(445, ruleset, 1, ctypes.byref(path_beneath), 0)
        _linux_check(libc.prctl(38, 1, 0, 0, 0), "set no_new_privs")
        landlock_call(446, ruleset, 0)
    finally:
        os.close(state_descriptor)
        os.close(ruleset)
    return abi


def _run_landlocked_candidate(
    export_root: Path,
    state_root: Path,
    command: list[str],
    environment: dict[str, str],
) -> int:
    abi = _landlock_state_only_writes(state_root)
    environment = dict(environment)
    environment["CRYODAQ_CANDIDATE_SANDBOX_ACTIVE"] = "1"
    libc = _linux_libc()
    no_new_privs = libc.prctl(39, 0, 0, 0, 0)
    capability_line = next(
        line.split(":", 1)[1].strip()
        for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines()
        if line.startswith("CapEff:")
    )
    _candidate_preflight(
        export_root,
        state_root,
        launcher=Path(environment["CRYODAQ_CANDIDATE_SANDBOX_LAUNCHER"]),
        platform_diagnostic={
            "boundary": "landlock",
            "capability_effective": capability_line,
            "egid": os.getegid(),
            "euid": os.geteuid(),
            "groups": os.getgroups(),
            "landlock_abi": abi,
            "no_new_privs": no_new_privs,
            "platform": "linux",
        },
    )
    os.chdir(export_root)
    return subprocess.run(command, env=environment, check=False).returncode


def _posix_child(
    export_root: Path,
    state_root: Path,
    export_alias: Path,
    state_alias: Path,
    command: list[str],
    environment: dict[str, str],
) -> int:
    libc = _linux_libc()
    _linux_check(libc.unshare(0x00020000), "unshare mount namespace")
    _linux_mount(None, Path("/"), 0x00004000 | 0x00040000)  # MS_REC | MS_PRIVATE
    _linux_mount(export_root, export_alias, 0x00001000 | 0x00004000)  # MS_BIND | MS_REC
    _linux_mount(None, export_alias, 0x00000001 | 0x00000020 | 0x00001000)  # MS_RDONLY | MS_REMOUNT | MS_BIND
    _linux_mount(state_root, state_alias, 0x00001000 | 0x00004000)

    export_identity = export_root.stat()
    export_alias_identity = export_alias.stat()
    state_identity = state_root.stat()
    state_alias_identity = state_alias.stat()
    if (export_identity.st_dev, export_identity.st_ino) != (
        export_alias_identity.st_dev,
        export_alias_identity.st_ino,
    ):
        raise RuntimeError("candidate export bind alias does not identify the original export")
    if (state_identity.st_dev, state_identity.st_ino) != (
        state_alias_identity.st_dev,
        state_alias_identity.st_ino,
    ):
        raise RuntimeError("candidate state bind alias does not identify the original state")
    if not os.statvfs(export_alias).f_flag & os.ST_RDONLY:
        raise RuntimeError("candidate export bind alias is not read-only")
    if os.statvfs(state_alias).f_flag & os.ST_RDONLY:
        raise RuntimeError("candidate state bind alias is not writable")

    environment = _rewrite_posix_environment(
        environment,
        export_root=export_root,
        export_alias=export_alias,
        state_root=state_root,
        state_alias=state_alias,
    )
    environment["CRYODAQ_CANDIDATE_ORIGINAL_EXPORT_ROOT"] = str(export_root)
    environment["CRYODAQ_CANDIDATE_SANDBOX_ACTIVE"] = "1"
    rewritten_command = [
        _rewrite_path(_rewrite_path(part, export_root, export_alias), state_root, state_alias) for part in command
    ]
    _linux_check(libc.prctl(38, 1, 0, 0, 0), "set no_new_privs")
    _drop_posix(state_root)
    no_new_privs = libc.prctl(39, 0, 0, 0, 0)
    if no_new_privs != 1:
        raise RuntimeError("candidate sandbox did not retain no_new_privs")
    capability_line = next(
        line.split(":", 1)[1].strip()
        for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines()
        if line.startswith("CapEff:")
    )
    _candidate_preflight(
        export_alias,
        state_alias,
        launcher=Path(environment["CRYODAQ_CANDIDATE_SANDBOX_LAUNCHER"]),
        original_export_root=export_root,
        platform_diagnostic={
            "alias_export_dev": export_alias_identity.st_dev,
            "alias_export_ino": export_alias_identity.st_ino,
            "alias_export_read_only": True,
            "alias_state_dev": state_alias_identity.st_dev,
            "alias_state_ino": state_alias_identity.st_ino,
            "capability_effective": capability_line,
            "egid": os.getegid(),
            "euid": os.geteuid(),
            "groups": os.getgroups(),
            "no_new_privs": no_new_privs,
            "original_export_dev": export_identity.st_dev,
            "original_export_ino": export_identity.st_ino,
            "original_state_dev": state_identity.st_dev,
            "original_state_ino": state_identity.st_ino,
            "platform": "linux",
        },
    )
    os.chdir(export_alias)
    return subprocess.run(rewritten_command, env=environment, check=False).returncode


def _run_posix_sandbox(
    export_root: Path,
    state_root: Path,
    command: list[str],
    environment: dict[str, str],
) -> int:
    if os.geteuid() != 0:
        if environment.get("CRYODAQ_CANDIDATE_SANDBOX_ACTIVE") == "1":
            return _run_landlocked_candidate(export_root, state_root, command, environment)
        raise PermissionError("POSIX candidate sandbox requires passwordless sudo")
    alias_root = Path(tempfile.mkdtemp(prefix="cryodaq-candidate-", dir="/tmp"))
    export_alias = alias_root / "candidate"
    state_alias = alias_root / "state"
    export_alias.mkdir()
    state_alias.mkdir()
    alias_root.chmod(0o755)
    export_alias.chmod(0o755)
    state_alias.chmod(0o755)
    state_identity = state_root.stat()
    try:
        child = os.fork()
        if child == 0:
            try:
                returncode = _posix_child(
                    export_root,
                    state_root,
                    export_alias,
                    state_alias,
                    command,
                    environment,
                )
            except BaseException:
                import traceback

                traceback.print_exc()
                returncode = 125
            os._exit(returncode)
        _, status = os.waitpid(child, 0)
        if os.WIFEXITED(status):
            return os.WEXITSTATUS(status)
        return 128 + os.WTERMSIG(status)
    finally:
        _chown_posix_tree(state_root, state_identity.st_uid, state_identity.st_gid)
        state_alias.rmdir()
        export_alias.rmdir()
        alias_root.rmdir()


def _restricted_windows_child(
    cwd: Path,
    state_root: Path,
    command: list[str],
) -> int:
    platform_diagnostic: dict[str, object] = {
        "platform": "windows",
        "nested": False,
        **_windows_security_diagnostic(),
        **_windows_token_escape_diagnostic(),
    }
    _candidate_preflight(
        cwd,
        state_root,
        launcher=Path(os.environ["CRYODAQ_CANDIDATE_SANDBOX_LAUNCHER"]),
        platform_diagnostic=platform_diagnostic,
    )
    os.chdir(cwd)
    return subprocess.run(command, env=dict(os.environ), check=False).returncode


def main() -> int:
    restricted_child = os.name == "nt" and len(sys.argv) > 1 and sys.argv[1] == "--restricted-child"
    offset = 2 if restricted_child else 1
    separator = sys.argv.index("--", offset)
    cwd = Path(sys.argv[offset]).resolve(strict=True)
    state_root = Path(sys.argv[offset + 1]).resolve(strict=True)
    command = sys.argv[separator + 1 :]
    if not command:
        raise ValueError("candidate command is empty")
    if restricted_child:
        return _restricted_windows_child(cwd, state_root, command)
    if os.name == "nt":
        return _windows_run_restricted(cwd, state_root, command)

    environment = json.loads(sys.stdin.buffer.read())
    if not isinstance(environment, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in environment.items()
    ):
        raise ValueError("candidate environment is malformed")
    return _run_posix_sandbox(cwd, state_root, command, environment)


if __name__ == "__main__":
    raise SystemExit(main())
