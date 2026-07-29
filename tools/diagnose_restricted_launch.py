"""Discriminate the OC-020 Windows failure. INSTRUMENTATION ONLY — changes no sandbox behaviour.

The candidate sandbox builds a restricted token — CreateRestrictedToken(WRITE_RESTRICTED)
with restricting SID S-1-5-12 (RESTRICTED CODE), all privileges removed except
SeChangeNotifyPrivilege and SeCreateSymbolicLinkPrivilege — and launches its child with
CreateProcessAsUserW. On windows-latest the child exits 3221225794 = 0xC0000142 =
STATUS_DLL_INIT_FAILED with EMPTY stdout and stderr: it dies during DLL initialisation,
before any Python code runs, and reports nothing.

WHAT IS ALREADY ELIMINATED. The obvious hypothesis was window station / desktop access:
Microsoft documents that a restricted token may need those DACLs widened, and that failure
presents exactly this way. It is REFUTED — S-1-5-12 (SDDL abbreviation `RC`) holds full
access to both objects. `ConvertStringSidToSidW("RC") -> S-1-5-12` confirms the mapping.

WHY THIS RUNS HERE AND NOT ON A DEVELOPER MACHINE. The same experiment run locally failed
at CreateProcessAsUserW with ACCESS_DENIED for every target, because that shell's token
holds ZERO privileges and therefore lacks SeAssignPrimaryTokenPrivilege. It could not create
the process at all, so it discriminated nothing. GitHub's windows-latest runner is
administrative, so the process can actually be created and the failure observed.

THE DISCRIMINATION. Three targets of increasing loader weight, launched through the exact
call shape the sandbox uses:

    A  cmd.exe /c exit 7      minimal loader, no CRT, no Python
    B  python -c ...          full CPython loader
    C  python -I -B -c ...    isolated mode, as the sandbox invokes its child

    A ok, B/C 0xC0000142   -> the fault is what CPython's loader does under a
                              write-restricted token, not process creation
    all three 0xC0000142   -> fundamental to the token itself
    all three ok           -> the token is fine and the fault is in the sandbox's own
                              child script, which would be the most useful answer of all

It also reports the token's privilege count and the restricting-SID state, so the result is
interpretable without re-deriving the setup.

Exit code is always 0: this is a measurement, not a gate.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
from ctypes import wintypes

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

TOKEN_ACCESS = 0x0001 | 0x0002 | 0x0008 | 0x0020 | 0x0080
WRITE_RESTRICTED = 0x00000008
SE_PRIVILEGE_ENABLED = 0x00000002
SE_PRIVILEGE_REMOVED = 0x00000004
STARTF_USESTDHANDLES = 0x00000100
DLL_INIT_FAILED = 3221225794
RETAIN = ("SeChangeNotifyPrivilege", "SeCreateSymbolicLinkPrivilege")


class Luid(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.LONG)]


class LuidAndAttributes(ctypes.Structure):
    _fields_ = [("luid", Luid), ("attributes", wintypes.DWORD)]


class SidAndAttributes(ctypes.Structure):
    _fields_ = [("sid", ctypes.c_void_p), ("attributes", wintypes.DWORD)]


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
        ("cb_reserved2", wintypes.WORD),
        ("reserved2", ctypes.c_void_p),
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


advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
advapi32.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(Luid)]
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


def privilege_count(token: wintypes.HANDLE) -> int:
    needed = wintypes.DWORD()
    advapi32.GetTokenInformation(token, 3, None, 0, ctypes.byref(needed))
    if not needed.value:
        return -1
    buffer = ctypes.create_string_buffer(needed.value)
    if not advapi32.GetTokenInformation(token, 3, buffer, needed.value, ctypes.byref(needed)):
        return -1
    return ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD)).contents.value


def build_token() -> wintypes.HANDLE:
    """The sandbox's token, constructed identically."""
    process_token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_ACCESS, ctypes.byref(process_token)):
        raise ctypes.WinError(ctypes.get_last_error())
    print(f"caller process token privileges: {privilege_count(process_token)}")

    sid = ctypes.c_void_p()
    if not advapi32.ConvertStringSidToSidW("S-1-5-12", ctypes.byref(sid)):
        raise ctypes.WinError(ctypes.get_last_error())
    restricting = SidAndAttributes(sid, 0)
    restricted = wintypes.HANDLE()
    if not advapi32.CreateRestrictedToken(
        process_token,
        WRITE_RESTRICTED,
        0,
        None,
        0,
        None,
        1,
        ctypes.byref(restricting),
        ctypes.byref(restricted),
    ):
        raise ctypes.WinError(ctypes.get_last_error())

    count = privilege_count(restricted)
    print(f"restricted token privileges before stripping: {count}")
    if count > 0:
        needed = wintypes.DWORD()
        advapi32.GetTokenInformation(restricted, 3, None, 0, ctypes.byref(needed))
        buffer = ctypes.create_string_buffer(needed.value)
        advapi32.GetTokenInformation(restricted, 3, buffer, needed.value, ctypes.byref(needed))

        class TokenPrivileges(ctypes.Structure):
            _fields_ = [("count", wintypes.DWORD), ("privileges", LuidAndAttributes * count)]

        privileges = ctypes.cast(buffer, ctypes.POINTER(TokenPrivileges)).contents
        retained: set[tuple[int, int]] = set()
        for name in RETAIN:
            luid = Luid()
            if advapi32.LookupPrivilegeValueW(None, name, ctypes.byref(luid)):
                retained.add((luid.low, luid.high))
        for privilege in privileges.privileges:
            key = (privilege.luid.low, privilege.luid.high)
            privilege.attributes = SE_PRIVILEGE_ENABLED if key in retained else SE_PRIVILEGE_REMOVED
        ctypes.set_last_error(0)
        advapi32.AdjustTokenPrivileges(restricted, False, ctypes.byref(privileges), 0, None, None)
        print(f"restricted token privileges after stripping:  {privilege_count(restricted)}")
    return restricted


def launch(token: wintypes.HANDLE, application: str, argv: list[str]) -> int:
    startup = StartupInfo()
    startup.cb = ctypes.sizeof(startup)
    startup.flags = STARTF_USESTDHANDLES
    startup.stdin = kernel32.GetStdHandle(wintypes.DWORD(-10).value)
    startup.stdout = kernel32.GetStdHandle(wintypes.DWORD(-11).value)
    startup.stderr = kernel32.GetStdHandle(wintypes.DWORD(-12).value)
    process = ProcessInformation()
    line = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
    if not advapi32.CreateProcessAsUserW(
        token,
        application,
        line,
        None,
        None,
        True,
        0,
        None,
        None,
        ctypes.byref(startup),
        ctypes.byref(process),
    ):
        return -ctypes.get_last_error()
    kernel32.WaitForSingleObject(process.process, 60000)
    code = wintypes.DWORD()
    kernel32.GetExitCodeProcess(process.process, ctypes.byref(code))
    kernel32.CloseHandle(process.process)
    kernel32.CloseHandle(process.thread)
    return code.value


def main() -> int:
    if sys.platform != "win32":
        print("not windows; nothing to measure")
        return 0

    comspec = r"C:\Windows\System32\cmd.exe"
    token = build_token()
    print()

    cases = [
        ("A  cmd.exe  (minimal loader)", comspec, [comspec, "/c", "exit 7"]),
        ("B  python   (full CPython loader)", sys.executable, [sys.executable, "-c", "raise SystemExit(7)"]),
        ("C  python -I -B (as the sandbox)", sys.executable, [sys.executable, "-I", "-B", "-c", "raise SystemExit(7)"]),
    ]
    outcomes = {}
    for label, application, argv in cases:
        code = launch(token, application, argv)
        if code == 7:
            verdict, kind = "OK — child ran and exited 7", "ok"
        elif code == DLL_INIT_FAILED:
            verdict, kind = "*** 0xC0000142 STATUS_DLL_INIT_FAILED ***", "dll"
        elif code < 0:
            verdict, kind = f"CreateProcessAsUser FAILED, win32 error {-code}", "nocreate"
        else:
            verdict, kind = f"exit {code} (0x{code & 0xFFFFFFFF:08X})", "other"
        outcomes[label[0]] = kind
        print(f"{label:<38} {verdict}")

    print()
    print("=" * 72)
    kinds = set(outcomes.values())
    if outcomes.get("A") == "ok" and {outcomes.get("B"), outcomes.get("C")} == {"dll"}:
        print("DISCRIMINATED: process creation under this token is FINE. The fault is specific")
        print("to what CPython's loader does under a write-restricted token.")
    elif kinds == {"dll"}:
        print("DISCRIMINATED: every target dies in DLL init, including cmd.exe. The fault is")
        print("fundamental to the restricted token, not to CPython.")
    elif kinds == {"ok"}:
        print("DISCRIMINATED: the token launches everything cleanly. The 0xC0000142 seen in CI")
        print("does NOT come from the token — look at the sandbox's own child script.")
    elif "nocreate" in kinds:
        print("NOT DISCRIMINATING: the process could not be created at all. Check whether this")
        print("runner actually holds SeAssignPrimaryTokenPrivilege.")
    else:
        print(f"MIXED result, no clean discrimination: {outcomes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
