"""Kernel-backed process lifetime bindings shared by CryoDAQ child owners."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
from typing import Any

PARENT_PID_ENV = "CRYODAQ_PARENT_PID"
PR_SET_PDEATHSIG = 1


def parent_pid_environment(expected_parent: int) -> dict[str, str]:
    """Return the exact child environment grant for one Linux parent."""

    if type(expected_parent) is not int or expected_parent <= 1:
        raise ValueError("expected parent PID must be an integer greater than one")
    return {PARENT_PID_ENV: str(expected_parent)}


def bind_child_lifetime_to_parent(
    expected_parent: int,
    *,
    platform: str | None = None,
    refusal_logger: logging.Logger | None = None,
    refusal_message: str | None = None,
) -> None:
    """Bind this Linux child to a parent captured before spawn, or exit.

    Reading the expected parent in the child is insufficient: a child first
    scheduled after its parent dies may already have been reparented to a
    subreaper.  The post-``prctl`` identity check closes the other race, where
    the parent dies between the initial check and installation of PDEATHSIG.
    """

    if type(expected_parent) is not int or expected_parent <= 1:
        os._exit(0)
    if os.getppid() != expected_parent:
        os._exit(0)
    actual_platform = sys.platform if platform is None else platform
    if not actual_platform.startswith("linux"):
        if refusal_logger is not None and refusal_message is not None:
            refusal_logger.warning(refusal_message, actual_platform)
        os._exit(0)
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        if libc.prctl(PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "prctl(PR_SET_PDEATHSIG) failed")
    except Exception:
        # An unbound child must not advance into code that can own resources.
        os._exit(0)
    if os.getppid() != expected_parent:
        os._exit(0)


def bind_child_lifetime_from_environment() -> None:
    """Consume the launcher's exact Linux parent grant and install binding."""

    raw_parent = os.environ.pop(PARENT_PID_ENV, None)
    if raw_parent is None:
        return
    try:
        expected_parent = int(raw_parent, 10)
    except (TypeError, ValueError):
        os._exit(0)
    if raw_parent != str(expected_parent):
        os._exit(0)
    bind_child_lifetime_to_parent(expected_parent)


class WindowsKillOnCloseJob:
    """A Windows Job Object that kills its assigned child tree on close."""

    def __init__(self, process: subprocess.Popen[Any]) -> None:
        import ctypes
        from ctypes import wintypes

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        info = ExtendedLimitInformation()
        # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        info.BasicLimitInformation.LimitFlags = 0x00002000
        if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(job)
            raise OSError(error, "SetInformationJobObject failed")
        process_handle = wintypes.HANDLE(int(process._handle))  # type: ignore[attr-defined]
        if not kernel32.AssignProcessToJobObject(job, process_handle):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(job)
            raise OSError(error, "AssignProcessToJobObject failed")
        self._kernel32 = kernel32
        self._handle = job

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


def create_windows_kill_on_close_job(process: subprocess.Popen[Any]) -> WindowsKillOnCloseJob:
    """Assign a child to a kill-on-close Windows Job Object."""

    return WindowsKillOnCloseJob(process)


def resume_windows_process(process: subprocess.Popen[Any]) -> None:
    """Resume a suspended Windows child after its Job owns the process."""

    if not windows_job_objects_available():
        raise RuntimeError("Windows process resume requires native Windows")
    import psutil

    psutil.Process(process.pid).resume()


def windows_job_objects_available() -> bool:
    """Return whether this interpreter is running on native Windows."""

    return os.name == "nt" and sys.platform == "win32"
