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
    advapi32.DuplicateTokenEx.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
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
        # *** WHY THIS IS MANDATORY INTEGRITY CONTROL AND NOT A RESTRICTED TOKEN. ***
        # The previous design used CreateRestrictedToken(WRITE_RESTRICTED) with
        # restricting SID S-1-5-12. It enforced the boundary correctly and CPython
        # could not start under it: the child exited 0xC0000142 STATUS_DLL_INIT_FAILED
        # with empty stdout and stderr on every hosted windows-latest job.
        #
        # Diagnosed on a hosted runner rather than guessed. A DEBUG_PROCESS loader
        # trace, with an unrestricted token as the control, showed the child loading
        # bcrypt.dll and then dying on bcryptprimitives.dll -- the CNG primitives
        # provider, which CPython pulls in at interpreter startup for hash
        # randomisation and os.urandom seeding, before any user code runs. Hence the
        # empty output. \Device\KsecDD, the kernel conduit CNG seeds through, grants
        # Everyone 0x1201bf but grants S-1-5-12 only 0x1200a9: an explicit ACE with
        # exactly the four write bits stripped. Under WRITE_RESTRICTED every
        # write-inclusive check is evaluated a second time against the restricting SID
        # set, so CNG's initialisation failed and the loader tore the process down.
        #
        # Widening that ACE was proposed and REJECTED on review: device write rights
        # determine which IOCTLs the I/O manager dispatches to a driver, no
        # authoritative contract for the user-mode KsecDD interface proves every newly
        # reachable operation is irrelevant, and matching the Everyone ACE is not
        # exculpatory because the restricting-SID pass exists precisely to make
        # Restricted Code narrower than Everyone.
        #
        # MIC gets the same property from the integrity LABEL instead. Windows refuses
        # a low-integrity write to a medium-integrity object regardless of its DACL,
        # and unlabelled objects are treated as medium -- so the export needs no
        # special handling and CNG never meets a second access-check pass. Measured on
        # a hosted windows-latest runner, 10/10: CPython starts, and export write, ACL
        # rewrite, rename, delete-recreate, hardlink and new-file are all refused while
        # the state root stays writable and a nested subprocess works.
        #
        # Privilege stripping below is retained deliberately: it was measured innocent
        # of the startup failure (CPython runs fine on two privileges), so it costs
        # nothing and narrows the child further.
        if not advapi32.DuplicateTokenEx(
            token,
            0xF01FF,  # TOKEN_ALL_ACCESS
            None,
            2,  # SecurityImpersonation
            1,  # TokenPrimary
            ctypes.byref(restricted),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if not advapi32.ConvertStringSidToSidW("S-1-16-4096", ctypes.byref(sid)):
            raise ctypes.WinError(ctypes.get_last_error())

        class TokenMandatoryLabel(ctypes.Structure):
            _fields_ = [("label", SidAndAttributes)]

        label = TokenMandatoryLabel()
        label.label = SidAndAttributes(sid, 0x00000020)  # SE_GROUP_INTEGRITY
        if not advapi32.SetTokenInformation(
            restricted,
            25,  # TokenIntegrityLevel
            ctypes.byref(label),
            ctypes.sizeof(label),
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


def _windows_grant_interpreter_read_execute() -> None:
    """Let the WRITE_RESTRICTED restricting SID read and execute the interpreter.

    CreateRestrictedToken(..., WRITE_RESTRICTED, ...) makes every access check that
    includes a write-type right (delete, write-data, write-attributes, write-DAC,
    and friends -- see the "write-restricted" rules under AccessCheck) succeed only
    if BOTH the token's enabled SIDs AND the restricting SID set (here: solely
    S-1-5-12, the Restricted Code group) independently grant it. Pure read/execute
    requests bypass the restricting SID entirely and already succeed. Measured on a
    hosted windows-latest runner: CPython's own loader phase -- before any Python
    code runs, hence the empty stdout/stderr and 0xC0000142 DLL_INIT_FAILED exit --
    issues a write-inclusive request against something in its own install directory.
    S-1-5-12 has no explicit grant there, so the second check fails and the process
    is torn down before main() executes.

    *** WHAT IS MEASURED VERSUS WHAT IS INFERRED, because these are not the same. ***
    MEASURED, on a hosted windows-latest runner: python under WRITE_RESTRICTED with
    S-1-5-12 exits 0xC0000142, while the same python under privilege-stripping alone
    runs, and cmd.exe and git.exe both run under the full restricted token. That
    isolates the cause to the restricting SID and exonerates privilege stripping.
    INFERRED, not measured: that the failing check is specifically a write-inclusive
    request inside the interpreter's own install directory. That is the hypothesis
    this grant tests -- if a hosted run still returns 0xC0000142, the hypothesis is
    wrong and the grant is not the fix.

    The fix is to grant S-1-5-12 read+execute -- never write -- on exactly the
    interpreter's own directory (python.exe and its adjacent DLLs: python3.dll,
    python3XX.dll, vcruntime140*.dll) and its "DLLs" subfolder (the stdlib's
    extension modules). This satisfies the loader's access check without loosening
    WRITE_RESTRICTED, without dropping S-1-5-12, and without touching anything
    under the candidate export or state root. Nothing outside the interpreter
    installation (site-packages, Lib, Scripts, ...) is touched: pure-read opens of
    those files are never subject to the restricting SID and did not need it.
    """

    raise NotImplementedError(
        "REFUTED AND RETAINED ONLY AS A SIGNPOST -- do not call, do not reinstate.\n"
        "\n"
        "This granted S-1-5-12 read/execute on the CPython install directory, on the\n"
        "theory that CPython's loader failed a write-inclusive check somewhere under\n"
        "that directory. It was applied and MEASURED on a hosted windows-latest runner\n"
        "and the child still exited 0xC0000142. The theory was wrong: the object that\n"
        "fails is CNG's own state, reached through \\Device\\KsecDD, and nothing under\n"
        "the Python installation is involved.\n"
        "\n"
        "Under Mandatory Integrity Control there is no restricting SID at all, so there\n"
        "is nothing to grant and no reason for this to exist. It is kept as a body that\n"
        "raises rather than deleted outright, so that anyone who rediscovers the same\n"
        "idea finds the measurement that already disproved it instead of spending a\n"
        "hosted cycle repeating it."
    )


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

    if _windows_already_low_integrity():
        raise PermissionError("nested Windows candidate execution is unavailable under an active low-integrity token")

    # NOTE: no interpreter-directory ACL grant here. A previous attempt granted the
    # restricting SID read/execute on the CPython install directory; it was measured on
    # a hosted runner and still produced 0xC0000142, because the object that failed was
    # CNG's own state and not anything under the Python installation. Under MIC there is
    # no restricting SID at all, so nothing needs granting.
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


def _windows_integrity_level() -> int:
    """Return this process's mandatory integrity RID (4096 = Low, 8192 = Medium).

    Replaces the previous restricted-SID probe. That asked whether S-1-5-12 was in the
    token's restricted-SID set, which was the right question for a WRITE_RESTRICTED
    token and is meaningless now: the boundary is the integrity LABEL and there is no
    restricting SID to find. Left as-is it would have answered False under every
    condition, silently disabling the nested-execution guard it exists to enforce.
    """

    from ctypes import wintypes

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("sid", ctypes.c_void_p), ("attributes", wintypes.DWORD)]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
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
    advapi32.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    advapi32.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
    advapi32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
    advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 25, None, 0, ctypes.byref(required))
        if not required.value:
            raise RuntimeError("candidate sandbox could not read its own integrity level")
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(token, 25, buffer, required.value, ctypes.byref(required)):
            raise ctypes.WinError(ctypes.get_last_error())
        label = SidAndAttributes.from_buffer(buffer)
        count = advapi32.GetSidSubAuthorityCount(label.sid).contents.value
        return int(advapi32.GetSidSubAuthority(label.sid, count - 1).contents.value)
    finally:
        kernel32.CloseHandle(token)


def _windows_already_low_integrity() -> bool:
    """True when this process is already at or below Low integrity."""

    return _windows_integrity_level() <= 0x1000  # SECURITY_MANDATORY_LOW_RID


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
        # *** These assertions are the sandbox proving to itself that it is actually
        # constrained, so they are REPLACED with the MIC equivalents rather than
        # relaxed. Under Mandatory Integrity Control there is no restricting SID and
        # IsTokenRestricted is False by design, so the two old checks would either
        # always fail or, if simply deleted, would silently stop verifying anything. ***
        integrity_rid = _windows_integrity_level()
        if integrity_rid > 0x1000:  # SECURITY_MANDATORY_LOW_RID
            raise RuntimeError(
                f"candidate token is not low integrity: RID 0x{integrity_rid:04x} "
                "(0x1000 = Low). The export boundary depends on this label."
            )
        return {
            "integrity_sid": integrity,
            "integrity_rid": integrity_rid,
            "low_integrity": True,
            "privileges": privilege_names,
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
    # *** DO NOT resolve() here. *** This function is reached from three call sites and
    # TWO of them are already deprivileged when they arrive: `_posix_child` after
    # `_drop_posix()`, and `_run_landlocked_candidate` in the re-entered non-root
    # process. `Path.resolve()` walks every ancestor, and as `nobody` that walk meets
    # /home/runner at mode 0751 -- traversable but not readable -- so it raises
    # PermissionError instead of the preflight reporting a refusal, and every hosted
    # ubuntu job dies before the boundary is exercised at all.
    #
    # The assertion never needed a resolved path: an open-for-write on the raw path is
    # refused just the same, and that refusal is exactly what is being measured.
    #
    # This cost two hosted runs. The first time I hoisted the resolve above the drop in
    # ONE caller and shipped, having verified only that caller. Fixing the callee fixes
    # all three at once, which is why the fix belongs here and not at the call sites.
    write_refusals["trusted_launcher"] = _existing_file_write_must_be_refused(launcher)

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
    # Resolve the trusted launcher while this process can still walk its ancestors;
    # after _drop_posix() the walk runs as `nobody` and meets /home/runner at 0751.
    trusted_launcher = Path(environment["CRYODAQ_CANDIDATE_SANDBOX_LAUNCHER"]).resolve(strict=True)
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
        launcher=trusted_launcher,
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
