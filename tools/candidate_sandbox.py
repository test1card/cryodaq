"""Drop candidate commands below the authority of their sealed export."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path


def _windows_low_integrity() -> None:
    from ctypes import wintypes

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("sid", ctypes.c_void_p), ("attributes", wintypes.DWORD)]

    class TokenMandatoryLabel(ctypes.Structure):
        _fields_ = [("label", SidAndAttributes)]

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
    advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetLengthSid.argtypes = [ctypes.c_void_p]
    advapi32.GetLengthSid.restype = wintypes.DWORD
    advapi32.SetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
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
    sid = ctypes.c_void_p()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(),
        0x0008 | 0x0020 | 0x0080,  # TOKEN_QUERY | TOKEN_ADJUST_PRIVILEGES | TOKEN_ADJUST_DEFAULT
        ctypes.byref(token),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 3, None, 0, ctypes.byref(required))
        privileges = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token,
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
        change_notify = Luid()
        if not advapi32.LookupPrivilegeValueW(None, "SeChangeNotifyPrivilege", ctypes.byref(change_notify)):
            raise ctypes.WinError(ctypes.get_last_error())
        for privilege in privilege_set.privileges:
            if (privilege.luid.low, privilege.luid.high) != (change_notify.low, change_notify.high):
                privilege.attributes = 0x00000004  # SE_PRIVILEGE_REMOVED
        if not advapi32.AdjustTokenPrivileges(
            token,
            False,
            ctypes.byref(privilege_set),
            0,
            None,
            None,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if not advapi32.ConvertStringSidToSidW("S-1-16-4096", ctypes.byref(sid)):
            raise ctypes.WinError(ctypes.get_last_error())
        label = TokenMandatoryLabel(SidAndAttributes(sid, 0x20))
        size = ctypes.sizeof(label) + advapi32.GetLengthSid(sid)
        if not advapi32.SetTokenInformation(token, 25, ctypes.byref(label), size):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if sid:
            kernel32.LocalFree(sid)
        kernel32.CloseHandle(token)


def _drop_posix(state_root: Path) -> None:
    import pwd

    if os.geteuid() != 0:
        raise PermissionError("POSIX candidate sandbox requires passwordless sudo")
    nobody = pwd.getpwnam("nobody")
    for current, directories, files in os.walk(state_root):
        for name in (*directories, *files):
            os.chown(Path(current) / name, nobody.pw_uid, nobody.pw_gid)
    os.chown(state_root, nobody.pw_uid, nobody.pw_gid)
    os.setgroups([])
    os.setgid(nobody.pw_gid)
    os.setuid(nobody.pw_uid)


def _diagnose_posix_directory_walk(cwd: Path) -> None:
    """Report the first strict directory-open failure after dropping authority."""

    flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    directory_fd = os.open(cwd.anchor, flags)
    walked = Path(cwd.anchor)
    try:
        for component in cwd.parts[1:]:
            walked /= component
            metadata: os.stat_result | None = None
            try:
                metadata = os.stat(component, dir_fd=directory_fd, follow_symlinks=False)
                next_fd = os.open(component, flags, dir_fd=directory_fd)
            except OSError as exc:
                identity = (
                    "mode=unavailable uid=unavailable gid=unavailable"
                    if metadata is None
                    else f"mode={metadata.st_mode & 0o7777:o} uid={metadata.st_uid} gid={metadata.st_gid}"
                )
                print(
                    "candidate-sandbox-directory-open-failed "
                    f"path={walked} errno={exc.errno} strerror={exc.strerror!r} "
                    f"{identity} "
                    f"euid={os.geteuid()} egid={os.getegid()} groups={os.getgroups()}",
                    file=sys.stderr,
                    flush=True,
                )
                return
            os.close(directory_fd)
            directory_fd = next_fd
        print("candidate-sandbox-directory-open-ok", file=sys.stderr, flush=True)
    finally:
        os.close(directory_fd)


def main() -> int:
    separator = sys.argv.index("--")
    cwd = Path(sys.argv[1]).resolve(strict=True)
    state_root = Path(sys.argv[2]).resolve(strict=True)
    command = sys.argv[separator + 1 :]
    if not command:
        raise ValueError("candidate command is empty")
    if os.name == "nt":
        environment = dict(os.environ)
        _windows_low_integrity()
    else:
        environment = json.loads(sys.stdin.buffer.read())
        if not isinstance(environment, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in environment.items()
        ):
            raise ValueError("candidate environment is malformed")
        _drop_posix(state_root)
        _diagnose_posix_directory_walk(cwd)
    os.chdir(cwd)
    return subprocess.run(command, env=environment, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
