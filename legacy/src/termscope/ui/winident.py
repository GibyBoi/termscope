"""Give a top-level window an explicit Windows AppUserModelID.

Setting the *process* AUMID (SetCurrentProcessExplicitAppUserModelID) turned out
not to propagate to Tk's window here, so the window kept an empty AUMID and the
taskbar gave it a standalone "python (windowed)" button. Writing the AUMID
directly onto the window via SHGetPropertyStoreForWindow + IPropertyStore is what
actually makes Windows group the window under the matching pinned shortcut.
"""
from __future__ import annotations

import ctypes
import uuid


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_ulong)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort),
                ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("data", ctypes.c_void_p), ("data2", ctypes.c_void_p)]


def _mkguid(s: str) -> _GUID:
    u = uuid.UUID(s)
    g = _GUID()
    g.Data1, g.Data2, g.Data3 = u.time_low, u.time_mid, u.time_hi_version
    for i in range(8):
        g.Data4[i] = u.bytes[8 + i]
    return g


# PKEY_AppUserModel_ID = fmtid {9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}, pid 5
_PKEY_FMTID = "9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"
_IID_IPropertyStore = "886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"


def set_window_aumid(hwnd: int, aumid: str) -> bool:
    """Stamp `aumid` onto the window so the taskbar groups it under that identity."""
    try:
        shell32 = ctypes.windll.shell32
        ole32 = ctypes.windll.ole32

        iid = _mkguid(_IID_IPropertyStore)
        store = ctypes.c_void_p()
        fn = shell32.SHGetPropertyStoreForWindow
        fn.restype = ctypes.c_long
        fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
        if fn(ctypes.c_void_p(hwnd), ctypes.byref(iid), ctypes.byref(store)) != 0 or not store:
            return False

        # COM vtable: [0]QueryInterface [1]AddRef [2]Release ... [6]SetValue [7]Commit
        vtbl = ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p))[0]
        funcs = ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))
        SetValue = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_PROPERTYKEY),
            ctypes.POINTER(_PROPVARIANT))(funcs[6])
        Commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(funcs[7])
        Release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(funcs[2])

        pk = _PROPERTYKEY()
        pk.fmtid = _mkguid(_PKEY_FMTID)
        pk.pid = 5

        s = aumid + "\0"
        ole32.CoTaskMemAlloc.restype = ctypes.c_void_p
        ole32.CoTaskMemAlloc.argtypes = [ctypes.c_size_t]
        buf = ole32.CoTaskMemAlloc(len(s) * 2)
        ctypes.memmove(buf, ctypes.create_unicode_buffer(s), len(s) * 2)
        pv = _PROPVARIANT()
        pv.vt = 31  # VT_LPWSTR
        pv.data = buf

        SetValue(store, ctypes.byref(pk), ctypes.byref(pv))  # store copies the value
        Commit(store)
        Release(store)
        ole32.CoTaskMemFree(buf)
        return True
    except Exception:  # noqa: BLE001
        return False
