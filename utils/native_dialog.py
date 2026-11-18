"""Windows' own Explorer file dialogs (IFileOpenDialog / IFileSaveDialog), called directly through COM.

Qt's QFileDialog asks Windows for the same dialog, but quietly falls back to its own widget dialog in some setups
(an always-on-top flag, COM state, a style plugin). Going to the shell ourselves always gives the real Explorer
window: Quick access, search, previews, the address bar. Off Windows, and if COM fails here, callers use Qt's.

Each function returns None when this way is not available (not Windows, or COM failed), so the caller can fall
back; a cancelled dialog returns [] or "".
"""
import ctypes
import logging
import os
import sys
from ctypes import POINTER, byref, c_uint, c_void_p, c_wchar_p

log = logging.getLogger(__name__)

FOS_OVERWRITEPROMPT = 0x2
FOS_STRICTFILETYPES = 0x4
FOS_PICKFOLDERS = 0x20
FOS_FORCEFILESYSTEM = 0x40
FOS_ALLOWMULTISELECT = 0x200
FOS_PATHMUSTEXIST = 0x800
FOS_FILEMUSTEXIST = 0x1000
SIGDN_FILESYSPATH = 0x80058000
CANCELLED = 0x800704C7 - 2 ** 32                # HRESULT_FROM_WIN32(ERROR_CANCELLED), as a signed HRESULT

# vtable slots: IUnknown 0-2, IModalWindow 3, IFileDialog 4-26, IFileOpenDialog 27-28, IFileSaveDialog 27-31
_RELEASE, _SHOW, _SET_FILE_TYPES, _SET_FILE_TYPE_INDEX, _SET_OPTIONS, _GET_OPTIONS = 2, 3, 4, 5, 9, 10
_SET_FOLDER, _SET_FILE_NAME, _SET_TITLE, _GET_RESULT, _SET_DEFAULT_EXTENSION, _GET_RESULTS = 12, 15, 17, 20, 22, 27
_ITEM_GET_DISPLAY_NAME = 5
_ARRAY_GET_COUNT, _ARRAY_GET_ITEM_AT = 7, 8


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, text: str) -> "GUID":
        h = text.strip("{}").replace("-", "")
        g = cls(int(h[0:8], 16), int(h[8:12], 16), int(h[12:16], 16))
        for i in range(8):
            g.Data4[i] = int(h[16 + 2 * i:18 + 2 * i], 16)
        return g


class FILTERSPEC(ctypes.Structure):
    _fields_ = [("pszName", c_wchar_p), ("pszSpec", c_wchar_p)]


CLSID_FileOpenDialog = "{DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7}"
CLSID_FileSaveDialog = "{C0B4E2F3-BA21-4773-8DBA-335EC946EB8B}"
IID_IFileOpenDialog = "{d57c7288-d4ad-4768-be02-9d969532d960}"
IID_IFileSaveDialog = "{84bccd23-5fde-4cdb-aea4-af64b83d78ab}"
IID_IShellItem = "{43826d1e-e718-42ee-bc55-a1e261c37bfe}"


def _method(ptr, slot: int, *argtypes):
    """A COM method of the object at ptr, by its vtable slot."""
    vtable = ctypes.cast(ptr, POINTER(POINTER(c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, *argtypes)
    fn = proto(vtable[slot])
    return lambda *args: fn(ptr, *args)


def _check(hr: int, what: str):
    if hr < 0:
        raise OSError(f"{what} failed: 0x{hr & 0xFFFFFFFF:08X}")


def _release(ptr):
    if ptr:
        _method(ptr, _RELEASE)()


def _item_path(item) -> str:
    out = c_wchar_p()
    _check(_method(item, _ITEM_GET_DISPLAY_NAME, c_uint, POINTER(c_wchar_p))(SIGDN_FILESYSPATH, byref(out)), "GetDisplayName")
    try:
        return out.value or ""
    finally:
        ctypes.windll.ole32.CoTaskMemFree(out)


def parse_filter(qt_filter: str) -> list[tuple[str, str]]:
    """Qt's "Images (*.png *.jpg);;All files (*)" as Windows' [("Images", "*.png;*.jpg"), ...]."""
    out = []
    for part in (qt_filter or "").split(";;"):
        part = part.strip()
        if not part:
            continue
        if "(" in part and part.endswith(")"):
            name, spec = part[:part.rindex("(")].strip(), part[part.rindex("(") + 1:-1]
        else:
            name, spec = part, part
        out.append((name or spec, ";".join(spec.split())))
    return out


def _run(save: bool, title: str, start: str, qt_filter: str, options: int, owner: int, file_name: str = "",
         default_ext: str = ""):
    if sys.platform != "win32":
        return None
    ole32 = ctypes.windll.ole32
    ole32.CoInitializeEx(None, 0x2)              # apartment-threaded; already so on Qt's thread (S_FALSE / changed mode)
    dialog = c_void_p()
    hr = ole32.CoCreateInstance(byref(GUID.of(CLSID_FileSaveDialog if save else CLSID_FileOpenDialog)), None, 1,
                                byref(GUID.of(IID_IFileSaveDialog if save else IID_IFileOpenDialog)), byref(dialog))
    if hr < 0 or not dialog:
        log.warning("Explorer dialog unavailable (0x%08X); using Qt's", hr & 0xFFFFFFFF)
        return None
    keep = []                                    # ctypes objects the dialog points at, alive until it closes
    try:
        cur = c_uint()
        _check(_method(dialog, _GET_OPTIONS, POINTER(c_uint))(byref(cur)), "GetOptions")
        _check(_method(dialog, _SET_OPTIONS, c_uint)(cur.value | options | FOS_FORCEFILESYSTEM), "SetOptions")
        if title:
            _method(dialog, _SET_TITLE, c_wchar_p)(title)
        specs = parse_filter(qt_filter) if not options & FOS_PICKFOLDERS else []
        if specs:
            arr = (FILTERSPEC * len(specs))(*[FILTERSPEC(n, s) for n, s in specs])
            keep.append(arr)
            _method(dialog, _SET_FILE_TYPES, c_uint, c_void_p)(len(specs), ctypes.cast(arr, c_void_p))
            _method(dialog, _SET_FILE_TYPE_INDEX, c_uint)(1)
        if default_ext:
            _method(dialog, _SET_DEFAULT_EXTENSION, c_wchar_p)(default_ext.lstrip("."))
        if file_name:
            _method(dialog, _SET_FILE_NAME, c_wchar_p)(file_name)
        if start and os.path.isdir(start):
            folder = c_void_p()
            if ctypes.windll.shell32.SHCreateItemFromParsingName(c_wchar_p(os.path.abspath(start)), None,
                                                                  byref(GUID.of(IID_IShellItem)), byref(folder)) >= 0:
                _method(dialog, _SET_FOLDER, c_void_p)(folder)
                _release(folder)
        hr = _method(dialog, _SHOW, c_void_p)(c_void_p(owner or None))
        if hr == CANCELLED:
            return []
        _check(hr, "Show")
        if save or not options & FOS_ALLOWMULTISELECT:
            item = c_void_p()
            _check(_method(dialog, _GET_RESULT, POINTER(c_void_p))(byref(item)), "GetResult")
            try:
                return [_item_path(item)]
            finally:
                _release(item)
        items = c_void_p()
        _check(_method(dialog, _GET_RESULTS, POINTER(c_void_p))(byref(items)), "GetResults")
        try:
            n = c_uint()
            _check(_method(items, _ARRAY_GET_COUNT, POINTER(c_uint))(byref(n)), "GetCount")
            paths = []
            for i in range(n.value):
                item = c_void_p()
                if _method(items, _ARRAY_GET_ITEM_AT, c_uint, POINTER(c_void_p))(i, byref(item)) >= 0:
                    try:
                        paths.append(_item_path(item))
                    finally:
                        _release(item)
            return [p for p in paths if p]
        finally:
            _release(items)
    except Exception:
        log.warning("Explorer dialog failed; using Qt's", exc_info=True)
        return None
    finally:
        _release(dialog)


def open_files(title: str, start: str = "", qt_filter: str = "", many: bool = False, owner: int = 0):
    """Paths chosen ([] if cancelled), or None when the Explorer dialog is not available."""
    return _run(False, title, start, qt_filter, FOS_FILEMUSTEXIST | FOS_PATHMUSTEXIST |
                (FOS_ALLOWMULTISELECT if many else 0), owner)


def open_folder(title: str, start: str = "", owner: int = 0):
    got = _run(False, title, start, "", FOS_PICKFOLDERS | FOS_PATHMUSTEXIST, owner)
    return None if got is None else (got[0] if got else "")


def save_file(title: str, suggested: str, qt_filter: str = "", owner: int = 0):
    """suggested: a full path; its folder opens and its name is filled in. "" if cancelled, None if unavailable."""
    folder, name = os.path.split(suggested)
    ext = os.path.splitext(name)[1]
    got = _run(True, title, folder, qt_filter, FOS_OVERWRITEPROMPT | FOS_PATHMUSTEXIST | FOS_STRICTFILETYPES, owner,
               file_name=name, default_ext=ext)
    return None if got is None else (got[0] if got else "")
