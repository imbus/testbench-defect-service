"""Encrypt and decrypt data with the Windows Data Protection API (DPAPI).

The key is managed by Windows and tied to the current user account (or, with
``machine_scope``, to the machine), so there is no key to store. Uses ``ctypes``
against ``crypt32.dll``; no extra entropy is used, which keeps the blobs compatible
with .NET's ``ProtectedData`` and thereby PowerShell.
"""

import sys

__all__ = ["DpapiError", "is_available", "protect", "unprotect"]

_CRYPTPROTECT_UI_FORBIDDEN = 0x1
_CRYPTPROTECT_LOCAL_MACHINE = 0x4


class DpapiError(OSError):
    """Raised when DPAPI is unavailable or refuses to encrypt/decrypt."""


def is_available() -> bool:
    """Return True on Windows, the only platform with DPAPI."""
    return sys.platform == "win32"


def protect(data: bytes, *, machine_scope: bool = False) -> bytes:
    """Encrypt ``data`` for the current Windows user, or for the machine.

    With ``machine_scope`` every account on this machine can decrypt the result.
    Raises ``DpapiError`` off Windows or when Windows refuses.
    """
    flags = _CRYPTPROTECT_UI_FORBIDDEN
    if machine_scope:
        flags |= _CRYPTPROTECT_LOCAL_MACHINE
    return _crypt(data, flags, encrypt=True)


def unprotect(data: bytes) -> bytes:
    """Decrypt a blob created by ``protect`` (user or machine scope).

    Raises ``DpapiError`` off Windows, or when this account or machine cannot
    decrypt the blob.
    """
    return _crypt(data, _CRYPTPROTECT_UI_FORBIDDEN, encrypt=False)


def _crypt(data: bytes, flags: int, *, encrypt: bool) -> bytes:
    if sys.platform != "win32":
        raise DpapiError("DPAPI is only available on Windows")

    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    class DataBlob(ctypes.Structure):
        _fields_ = (
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        )

    blob_pointer = ctypes.POINTER(DataBlob)
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.LocalFree.restype = ctypes.c_void_p

    # Both functions share the layout (in, description, entropy, reserved, prompt, flags, out);
    # only the description differs (LPCWSTR in, LPWSTR* out) and is always NULL here.
    function = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    function.argtypes = (
        blob_pointer,
        ctypes.c_void_p,
        blob_pointer,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        blob_pointer,
    )
    function.restype = wintypes.BOOL

    buffer = ctypes.create_string_buffer(data, len(data))
    blob_in = DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = DataBlob()

    if not function(ctypes.byref(blob_in), None, None, None, None, flags, ctypes.byref(blob_out)):
        code = ctypes.get_last_error()
        raise DpapiError(code, ctypes.FormatError(code).strip())
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))
