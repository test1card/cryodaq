"""Handle-anchored, no-reparse reads for Windows configuration files."""

from __future__ import annotations

import os
from pathlib import PureWindowsPath
from typing import Final

DEFAULT_MAX_BYTES: Final = 8 * 1024 * 1024


class SecureRelativeReadError(OSError):
    """A relative file could not be selected and read without following links."""


def read_secure_relative_bytes(
    root: os.PathLike[str] | str,
    relative_path: os.PathLike[str] | str,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> bytes:
    """Read one local-drive file while retaining every traversed directory handle.

    The Windows implementation rejects junctions, symbolic links, and all other
    reparse points in both ``root`` and ``relative_path``.  It opens each name
    relative to its already-open parent, then reads from the final native handle.
    UNC/device roots are deliberately unsupported so the trust anchor is the
    local drive root rather than a remotely resolved namespace.
    """

    if os.name != "nt":
        raise SecureRelativeReadError("secure relative reads are Windows-only")
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")

    root_path, root_parts = _local_absolute_root(root)
    relative_parts = _safe_relative_parts(relative_path)
    return _read_windows(root_path.drive, (*root_parts, *relative_parts), max_bytes)


def _local_absolute_root(root: os.PathLike[str] | str) -> tuple[PureWindowsPath, tuple[str, ...]]:
    raw = os.fspath(root)
    if not isinstance(raw, str) or "\0" in raw:
        raise SecureRelativeReadError("root must be a text path without NUL")
    path = PureWindowsPath(raw)
    drive = path.drive
    if not path.is_absolute() or len(drive) != 2 or drive[1] != ":" or not drive[0].isalpha() or path.root != "\\":
        raise SecureRelativeReadError("root must be an absolute local-drive path")
    parts = tuple(path.parts[1:])
    _validate_components(parts)
    return path, parts


def _safe_relative_parts(relative_path: os.PathLike[str] | str) -> tuple[str, ...]:
    raw = os.fspath(relative_path)
    if not isinstance(raw, str) or not raw or "\0" in raw:
        raise SecureRelativeReadError("relative_path must be non-empty text without NUL")
    path = PureWindowsPath(raw)
    if path.is_absolute() or path.drive or path.root:
        raise SecureRelativeReadError("relative_path must be relative")
    parts = path.parts
    _validate_components(parts)
    if not parts:
        raise SecureRelativeReadError("relative_path must name a file")
    return parts


def _validate_components(parts: tuple[str, ...]) -> None:
    for part in parts:
        if part in {"", ".", ".."} or ":" in part or part[-1:] in {" ", "."}:
            raise SecureRelativeReadError("path contains an unsafe component")
        if len(part.encode("utf-16-le")) > 510:
            raise SecureRelativeReadError("path component exceeds the NTFS limit")


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _FILE_READ_DATA: Final = 0x0001
    _FILE_LIST_DIRECTORY: Final = 0x0001
    _FILE_TRAVERSE: Final = 0x0020
    _FILE_READ_ATTRIBUTES: Final = 0x0080
    _SYNCHRONIZE: Final = 0x00100000
    _FILE_SHARE_READ: Final = 0x00000001
    _FILE_SHARE_WRITE: Final = 0x00000002
    _FILE_SHARE_DELETE: Final = 0x00000004
    _OPEN_EXISTING: Final = 3
    _FILE_ATTRIBUTE_REPARSE_POINT: Final = 0x00000400
    _FILE_ATTRIBUTE_DIRECTORY: Final = 0x00000010
    _FILE_FLAG_BACKUP_SEMANTICS: Final = 0x02000000
    _FILE_FLAG_OPEN_REPARSE_POINT: Final = 0x00200000
    _FILE_OPEN: Final = 1
    _FILE_DIRECTORY_FILE: Final = 0x00000001
    _FILE_SYNCHRONOUS_IO_NONALERT: Final = 0x00000020
    _FILE_OPEN_REPARSE_POINT: Final = 0x00200000
    _DRIVE_FIXED: Final = 3
    _FILE_ATTRIBUTE_TAG_INFO_CLASS: Final = 9
    _FILE_NAME_INFO_CLASS: Final = 2
    _INVALID_HANDLE_VALUE: Final = ctypes.c_void_p(-1).value

    class _UnicodeString(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.USHORT),
            ("MaximumLength", wintypes.USHORT),
            ("Buffer", wintypes.LPWSTR),
        ]

    class _ObjectAttributes(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.ULONG),
            ("RootDirectory", wintypes.HANDLE),
            ("ObjectName", ctypes.POINTER(_UnicodeString)),
            ("Attributes", wintypes.ULONG),
            ("SecurityDescriptor", wintypes.LPVOID),
            ("SecurityQualityOfService", wintypes.LPVOID),
        ]

    class _IoStatusValue(ctypes.Union):
        _fields_ = [("Status", ctypes.c_long), ("Pointer", wintypes.LPVOID)]

    class _IoStatusBlock(ctypes.Structure):
        _anonymous_ = ("value",)
        _fields_ = [("value", _IoStatusValue), ("Information", ctypes.c_size_t)]

    class _FileAttributeTagInfo(ctypes.Structure):
        _fields_ = [("FileAttributes", wintypes.DWORD), ("ReparseTag", wintypes.DWORD)]

    class _ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("FileAttributes", wintypes.DWORD),
            ("CreationTime", wintypes.FILETIME),
            ("LastAccessTime", wintypes.FILETIME),
            ("LastWriteTime", wintypes.FILETIME),
            ("VolumeSerialNumber", wintypes.DWORD),
            ("FileSizeHigh", wintypes.DWORD),
            ("FileSizeLow", wintypes.DWORD),
            ("NumberOfLinks", wintypes.DWORD),
            ("FileIndexHigh", wintypes.DWORD),
            ("FileIndexLow", wintypes.DWORD),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")

    _CreateFileW = _kernel32.CreateFileW
    _CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    _CreateFileW.restype = wintypes.HANDLE

    _GetDriveTypeW = _kernel32.GetDriveTypeW
    _GetDriveTypeW.argtypes = (wintypes.LPCWSTR,)
    _GetDriveTypeW.restype = wintypes.UINT

    _CloseHandle = _kernel32.CloseHandle
    _CloseHandle.argtypes = (wintypes.HANDLE,)
    _CloseHandle.restype = wintypes.BOOL

    _GetFileInformationByHandleEx = _kernel32.GetFileInformationByHandleEx
    _GetFileInformationByHandleEx.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    _GetFileInformationByHandleEx.restype = wintypes.BOOL

    _GetFileInformationByHandle = _kernel32.GetFileInformationByHandle
    _GetFileInformationByHandle.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_ByHandleFileInformation),
    )
    _GetFileInformationByHandle.restype = wintypes.BOOL

    _ReadFile = _kernel32.ReadFile
    _ReadFile.argtypes = (
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    )
    _ReadFile.restype = wintypes.BOOL

    _NtCreateFile = _ntdll.NtCreateFile
    _NtCreateFile.argtypes = (
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        ctypes.POINTER(_ObjectAttributes),
        ctypes.POINTER(_IoStatusBlock),
        ctypes.c_void_p,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        ctypes.c_void_p,
        wintypes.ULONG,
    )
    _NtCreateFile.restype = ctypes.c_long

    _RtlNtStatusToDosError = _ntdll.RtlNtStatusToDosError
    _RtlNtStatusToDosError.argtypes = (ctypes.c_long,)
    _RtlNtStatusToDosError.restype = wintypes.ULONG


def _read_windows(drive: str, parts: tuple[str, ...], max_bytes: int) -> bytes:
    handles: list[int] = []
    try:
        current = _open_drive_root(drive)
        handles.append(current)
        for part in parts[:-1]:
            current = _open_relative(current, part, directory=True)
            handles.append(current)
        final = _open_relative(current, parts[-1], directory=False)
        handles.append(final)
        return _read_handle(final, max_bytes)
    except SecureRelativeReadError:
        raise
    except (OSError, ValueError) as exc:
        raise SecureRelativeReadError("secure relative read failed") from exc
    finally:
        for handle in reversed(handles):
            _CloseHandle(handle)


def _open_drive_root(drive: str) -> int:
    if _GetDriveTypeW(f"{drive}\\") != _DRIVE_FIXED:
        raise SecureRelativeReadError("secure relative reads require a fixed local drive")
    handle = _CreateFileW(
        f"\\\\?\\{drive}\\",
        _FILE_LIST_DIRECTORY | _FILE_TRAVERSE | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle == _INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        _require_kind(handle, directory=True)
    except BaseException:
        _CloseHandle(handle)
        raise
    return handle


def _open_relative(parent: int, name: str, *, directory: bool) -> int:
    name_buffer = ctypes.create_unicode_buffer(name)
    byte_length = len(name.encode("utf-16-le"))
    unicode_name = _UnicodeString(
        byte_length,
        byte_length + ctypes.sizeof(ctypes.c_wchar),
        ctypes.cast(name_buffer, wintypes.LPWSTR),
    )
    attributes = _ObjectAttributes(
        ctypes.sizeof(_ObjectAttributes),
        parent,
        ctypes.pointer(unicode_name),
        0,
        None,
        None,
    )
    io_status = _IoStatusBlock()
    handle = wintypes.HANDLE()
    desired = _FILE_READ_ATTRIBUTES | _SYNCHRONIZE
    share = _FILE_SHARE_READ | _FILE_SHARE_DELETE
    options = _FILE_SYNCHRONOUS_IO_NONALERT | _FILE_OPEN_REPARSE_POINT
    if directory:
        desired |= _FILE_LIST_DIRECTORY | _FILE_TRAVERSE
        share |= _FILE_SHARE_WRITE
        options |= _FILE_DIRECTORY_FILE
    else:
        desired |= _FILE_READ_DATA
    status = _NtCreateFile(
        ctypes.byref(handle),
        desired,
        ctypes.byref(attributes),
        ctypes.byref(io_status),
        None,
        0,
        share,
        _FILE_OPEN,
        options,
        None,
        0,
    )
    if status < 0:
        raise ctypes.WinError(_RtlNtStatusToDosError(status))
    value = handle.value
    if value is None:
        raise SecureRelativeReadError("native open returned no handle")
    try:
        _require_kind(value, directory=directory)
        _require_exact_component(value, name)
    except BaseException:
        _CloseHandle(value)
        raise
    return value


def _require_exact_component(handle: int, expected: str) -> None:
    buffer = ctypes.create_string_buffer(65_536)
    if not _GetFileInformationByHandleEx(
        handle,
        _FILE_NAME_INFO_CLASS,
        buffer,
        len(buffer),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    byte_length = wintypes.DWORD.from_buffer(buffer).value
    if byte_length > len(buffer) - ctypes.sizeof(wintypes.DWORD) or byte_length % 2:
        raise SecureRelativeReadError("native file name metadata is invalid")
    name = ctypes.wstring_at(
        ctypes.addressof(buffer) + ctypes.sizeof(wintypes.DWORD),
        byte_length // ctypes.sizeof(ctypes.c_wchar),
    )
    if name.rsplit("\\", 1)[-1] != expected:
        raise SecureRelativeReadError("opened path component does not exactly match authority")


def _require_kind(handle: int, *, directory: bool) -> None:
    info = _FileAttributeTagInfo()
    if not _GetFileInformationByHandleEx(
        handle,
        _FILE_ATTRIBUTE_TAG_INFO_CLASS,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    if info.FileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        if directory:
            raise SecureRelativeReadError("path traversal encountered an ancestor reparse point")
        raise SecureRelativeReadError("final file is a reparse point; file must have exactly one hard link")
    is_directory = bool(info.FileAttributes & _FILE_ATTRIBUTE_DIRECTORY)
    if is_directory != directory:
        raise SecureRelativeReadError("path object has the wrong file type")
    if not directory:
        identity = _ByHandleFileInformation()
        if not _GetFileInformationByHandle(handle, ctypes.byref(identity)):
            raise ctypes.WinError(ctypes.get_last_error())
        if identity.NumberOfLinks != 1:
            raise SecureRelativeReadError("file must have exactly one hard link")


def _read_handle(handle: int, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    buffer = ctypes.create_string_buffer(64 * 1024)
    while True:
        read = wintypes.DWORD()
        if not _ReadFile(handle, buffer, len(buffer), ctypes.byref(read), None):
            raise ctypes.WinError(ctypes.get_last_error())
        if read.value == 0:
            return b"".join(chunks)
        total += read.value
        if total > max_bytes:
            raise SecureRelativeReadError("file exceeds max_bytes")
        chunks.append(buffer.raw[: read.value])
