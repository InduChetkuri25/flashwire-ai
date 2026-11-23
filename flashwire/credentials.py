import ctypes
import os
from ctypes import wintypes
from pathlib import Path
from tempfile import NamedTemporaryFile


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def protect(data, decrypt=False):
    if os.name != "nt":
        raise ValueError("This credential store requires Windows.")
    source = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    input_blob, result = Blob(len(data), source), Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    release = ctypes.WinDLL("kernel32", use_last_error=True).LocalFree
    release.argtypes = (ctypes.c_void_p,)
    release.restype = ctypes.c_void_p
    operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    operation.argtypes = (ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob))
    operation.restype = wintypes.BOOL
    if not operation(ctypes.byref(input_blob), None, None, None, None, 1, ctypes.byref(result)):
        raise ValueError("Windows could not access the credential for this user.")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        ctypes.memset(result.data, 0, result.size)
        release(ctypes.cast(result.data, ctypes.c_void_p))
        ctypes.memset(source, 0, len(data))


def save_token(path, token):
    path = Path(path)
    payload = protect(token.encode("utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(payload)
    staging = Path(temporary.name)
    try:
        staging.replace(path)
    finally:
        staging.unlink(missing_ok=True)


def read_token(path):
    try:
        return protect(Path(path).read_bytes(), decrypt=True).decode("utf-8")
    except OSError:
        raise ValueError("Connect the Meta account before running the publisher.") from None
