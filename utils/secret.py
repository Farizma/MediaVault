"""API keys at rest, encrypted with Windows' own Data Protection API (DPAPI, CryptProtectData).

DPAPI ties the encryption to this Windows user on this PC: no password to manage, and the database alone (a copy,
a backup, another account) cannot be read. Stored as "dpapi:<base64>". On other systems, or if DPAPI fails, the
value is kept as it was. A key that cannot be decrypted (a backup restored on another PC) reads as empty, and
Settings asks for it again.
"""
import base64
import ctypes
import logging
import sys

PREFIX = "dpapi:"
_ENTROPY = b"MediaVault API key v1"        # extra input: other apps using DPAPI for this user cannot decrypt it
log = logging.getLogger(__name__)


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes):
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _take(blob: _Blob) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob.pbData)


def available() -> bool:
    return sys.platform == "win32"


def protect(text: str) -> str:
    """Encrypt for this Windows user. Empty stays empty."""
    if not text or text.startswith(PREFIX) or not available():
        return text
    try:
        src, _a = _blob(text.encode("utf-8"))
        ent, _b = _blob(_ENTROPY)
        out = _Blob()
        if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(src), "Media Vault", ctypes.byref(ent), None, None,
                                                      0x1, ctypes.byref(out)):     # 0x1: no UI
            raise ctypes.WinError()
        return PREFIX + base64.b64encode(_take(out)).decode("ascii")
    except Exception:
        log.warning("DPAPI could not encrypt a key; it is stored as typed", exc_info=True)
        return text


def unprotect(stored: str | None) -> str:
    """The key in plain text, for the moment it is used. Unencrypted values (older versions) pass through."""
    if not stored or not stored.startswith(PREFIX):
        return stored or ""
    if not available():
        return ""
    try:
        src, _a = _blob(base64.b64decode(stored[len(PREFIX):]))
        ent, _b = _blob(_ENTROPY)
        out = _Blob()
        if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(src), None, ctypes.byref(ent), None, None,
                                                        0x1, ctypes.byref(out)):
            raise ctypes.WinError()
        return _take(out).decode("utf-8")
    except Exception:
        log.warning("an API key could not be decrypted (made by another Windows user or PC?)")
        return ""
