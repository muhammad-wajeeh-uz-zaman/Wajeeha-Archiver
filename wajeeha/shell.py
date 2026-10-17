# -*- coding: utf-8 -*-
"""
Explorer right-click integration for Wajeeha Archiver (Windows).

Everything is written under HKEY_CURRENT_USER, so no administrator rights are
needed and removing it is clean.  The registry layout is produced as plain data
(build_spec) so it can be applied with winreg or exported as a .reg file.

Windows starts one process per selected file for classic menu entries.  The
`collect()` helper lets those processes find each other so a multi-file
selection becomes ONE "Add to archive" dialog instead of many.
"""
import json
import os
import re
import socket
import subprocess
import sys
import time
import zlib

from . import core, icons

ROOT = "Software\\Classes"
VERB = "WajeehaArchiver"
PROGID = "WajeehaArchiver.Archive"
APP_TITLE = "Wajeeha Archiver"

ADD_ITEMS = [
    ("01add", "Add to archive...", "add"),
    ("02zip", "Add to ZIP archive", "add-quick zip"),
    ("03seven", "Add to 7Z archive", "add-quick 7z"),
]
RAR_ITEM = ("04rar", "Add to RAR archive", "add-quick rar")
EXTRACT_ITEMS = [
    ("01extract", "Extract files...", "extract"),
    ("02here", "Extract Here", "extract-here"),
    ("03to", "Extract to subfolder", "extract-to"),
    ("04test", "Test archive", "test"),
    ("05open", "Open with " + APP_TITLE, "open"),
]
OPEN_EXTS = [e for e in core.SHELL_EXTRACT_EXTS if e != ".001"]

# --------------------------------------------------------------- commands


def command_prefix() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.isfile(pyw):
        exe = pyw
    script = os.path.join(core.app_dir(), "wajeeha_archiver.py")
    return f'"{exe}" "{script}"'


def icon_value() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}",0'
    from . import config
    path = os.path.join(config.APP_DATA, "wajeeha.ico")
    try:
        os.makedirs(config.APP_DATA, exist_ok=True)
        if not os.path.isfile(path):
            icons.make_ico(path)
        return f'"{path}"'
    except OSError:
        return ""


# ------------------------------------------------------------- registry spec
def build_spec(prefix: str, icon: str, cascade: bool = True, context_menu: bool = True,
               associate: bool = True, rar=None):
    """List of (key path under HKCU, value name ('' = default), value)."""
    spec = []
    add_items = list(ADD_ITEMS)
    if core.can_create("rar") if rar is None else rar:
        add_items.append(RAR_ITEM)

    def put(key, name, value):
        spec.append((key, name, value))

    def menu(target, items):
        base = f"{ROOT}\\{target}\\shell"
        if cascade:
            parent = f"{base}\\{VERB}"
            put(parent, "MUIVerb", APP_TITLE)
            if icon:
                put(parent, "Icon", icon)
            put(parent, "SubCommands", "")
            put(parent, "MultiSelectModel", "Player")
            for ident, label, args in items:
                k = f"{parent}\\shell\\{ident}"
                put(k, "", label)
                put(k, "MultiSelectModel", "Player")
                if icon:
                    put(k, "Icon", icon)
                put(k + "\\command", "", f'{prefix} {args} "%1"')
        else:
            for ident, label, args in items:
                k = f"{base}\\{VERB}.{ident}"
                put(k, "MUIVerb", label)
                put(k, "MultiSelectModel", "Player")
                if icon:
                    put(k, "Icon", icon)
                put(k + "\\command", "", f'{prefix} {args} "%1"')

    if context_menu:
        menu("*", add_items)
        menu("Directory", add_items)
        for ext in core.SHELL_EXTRACT_EXTS:
            menu(f"SystemFileAssociations\\{ext}", EXTRACT_ITEMS + add_items[:1])
    if associate:
        put(f"{ROOT}\\{PROGID}", "", "Archive")
        if icon:
            put(f"{ROOT}\\{PROGID}\\DefaultIcon", "", icon)
        put(f"{ROOT}\\{PROGID}\\shell\\open\\command", "", f'{prefix} open "%1"')
        for ext in OPEN_EXTS:
            put(f"{ROOT}\\{ext}\\OpenWithProgids", PROGID, "")
    return spec


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def to_reg(spec) -> str:
    lines = ["Windows Registry Editor Version 5.00", ""]
    grouped = {}
    for key, name, value in spec:
        grouped.setdefault(key, []).append((name, value))
    for key, vals in grouped.items():
        lines.append(f"[HKEY_CURRENT_USER\\{key}]")
        for name, value in vals:
            lines.append(f'{"@" if name == "" else chr(34) + _esc(name) + chr(34)}="{_esc(value)}"')
        lines.append("")
    return "\r\n".join(lines)


def _targets():
    return ["*", "Directory"] + [f"SystemFileAssociations\\{e}" for e in core.SHELL_EXTRACT_EXTS]


def _delete_keys():
    keys = []
    for t in _targets():
        keys.append(f"{ROOT}\\{t}\\shell\\{VERB}")
        for ident, _l, _a in ADD_ITEMS + [RAR_ITEM] + EXTRACT_ITEMS:
            keys.append(f"{ROOT}\\{t}\\shell\\{VERB}.{ident}")
    keys.append(f"{ROOT}\\{PROGID}")
    return keys


# ------------------------------------------------------------------ winreg
def available() -> bool:
    return os.name == "nt"


def _del_tree(winreg, root, path):
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:
                    sub = winreg.EnumKey(k, 0)
                except OSError:
                    break
                _del_tree(winreg, root, path + "\\" + sub)
        winreg.DeleteKey(root, path)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _notify():
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED
    except Exception:
        pass


def register(cascade=True, context_menu=True, associate=True, winreg_module=None):
    """Write the Explorer entries. Removes older entries first. Returns number of values written."""
    winreg = winreg_module or __import__("winreg")
    unregister(winreg_module=winreg)
    spec = build_spec(command_prefix(), icon_value(), cascade, context_menu, associate)
    for key, name, value in spec:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_WRITE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
    _notify()
    return len(spec)


def unregister(winreg_module=None):
    winreg = winreg_module or __import__("winreg")
    for key in _delete_keys():
        _del_tree(winreg, winreg.HKEY_CURRENT_USER, key)
    for ext in OPEN_EXTS:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{ROOT}\\{ext}\\OpenWithProgids", 0,
                                winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, PROGID)
        except OSError:
            pass
    _notify()


def is_registered(winreg_module=None) -> bool:
    try:
        winreg = winreg_module or __import__("winreg")
    except ImportError:
        return False
    for key in (f"{ROOT}\\*\\shell\\{VERB}", f"{ROOT}\\*\\shell\\{VERB}.01add"):
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, key))
            return True
        except OSError:
            continue
    return False


def registered_command(winreg_module=None):
    """The command Explorer currently runs for 'Add to archive...', or None if not installed."""
    try:
        winreg = winreg_module or __import__("winreg")
    except ImportError:
        return None
    for key in (f"{ROOT}\\*\\shell\\{VERB}\\shell\\01add\\command", f"{ROOT}\\*\\shell\\{VERB}.01add\\command"):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                return winreg.QueryValueEx(k, "")[0]
        except OSError:
            continue
    return None


def _quoted_paths(cmd):
    return [p for p in re.findall(r'"([^"]+)"', cmd) if "%" not in p]


def command_target(cmd) -> str:
    q = _quoted_paths(cmd)
    return q[-1] if q else cmd


def command_target_exists(cmd) -> bool:
    q = _quoted_paths(cmd)
    return bool(q) and all(os.path.exists(p) for p in q)


def needs_refresh(winreg_module=None) -> bool:
    """True when the menu is installed but points somewhere else than this copy of the program."""
    cmd = registered_command(winreg_module)
    return cmd is not None and cmd != f'{command_prefix()} add "%1"'


# --- Windows 11: show classic entries directly instead of under "Show more options"
CLASSIC_PARENT = f"{ROOT}\\CLSID\\{{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}}"


def is_win11() -> bool:
    if os.name != "nt":
        return False
    try:
        return sys.getwindowsversion().build >= 22000
    except Exception:
        return False


def classic_menu_enabled(winreg_module=None) -> bool:
    try:
        winreg = winreg_module or __import__("winreg")
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLASSIC_PARENT + "\\InprocServer32"))
        return True
    except (OSError, ImportError):
        return False


def set_classic_menu(enable: bool, winreg_module=None):
    winreg = winreg_module or __import__("winreg")
    if enable:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, CLASSIC_PARENT + "\\InprocServer32", 0,
                                winreg.KEY_WRITE) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "")
    else:
        _del_tree(winreg, winreg.HKEY_CURRENT_USER, CLASSIC_PARENT)
    _notify()


def restart_explorer():
    subprocess.Popen("taskkill /f /im explorer.exe & start explorer.exe", shell=True, creationflags=0x08000000)


# -------------------------------------------- multi-selection collector
def _siblings():
    """Number of processes with our program name that share our parent (Explorer starts one per selected
    file). Returns None when it cannot be determined (then the collector falls back to waiting briefly)."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class ENTRY(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                        ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                        ("szExeFile", ctypes.c_wchar * 260)]
        k32 = ctypes.windll.kernel32
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ENTRY)]
        k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ENTRY)]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        snap = k32.CreateToolhelp32Snapshot(2, 0)          # TH32CS_SNAPPROCESS
        if not snap or snap == ctypes.c_void_p(-1).value:
            return None
        try:
            e = ENTRY()
            e.dwSize = ctypes.sizeof(ENTRY)
            rows = []
            ok = k32.Process32FirstW(snap, ctypes.byref(e))
            while ok:
                rows.append((e.th32ProcessID, e.th32ParentProcessID, e.szExeFile.lower()))
                ok = k32.Process32NextW(snap, ctypes.byref(e))
        finally:
            k32.CloseHandle(snap)
        me = next((r for r in rows if r[0] == os.getpid()), None)
        if me is None:
            return None
        return sum(1 for r in rows if r[1] == me[1] and r[2] == me[2])
    except Exception:
        return None


def _port(verb: str) -> int:
    return 49500 + (zlib.crc32(verb.encode()) % 400)


def collect(verb: str, paths, idle: float = 1.0, cap: float = 20.0, siblings="auto"):
    """Gather the paths of all processes launched together by Explorer.

    Returns the combined list if THIS process should do the work, or None when
    the paths were handed to another process that is already collecting."""
    if siblings == "auto":
        siblings = _siblings()
    if siblings == 1:                       # we are alone: a single file was selected, no waiting needed
        return list(paths)
    port = _port(verb)
    payload = json.dumps(list(paths)).encode("utf-8") + b"\n"
    give_up = time.time() + 6
    while True:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            srv.bind(("127.0.0.1", port))
            srv.listen(64)
        except OSError:
            srv.close()
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1.0) as c:
                    c.sendall(payload)
                    return None
            except OSError:
                if time.time() > give_up:
                    return list(paths)
                time.sleep(0.05)
                continue
        got = list(paths)
        start = last = time.time()
        srv.settimeout(0.1)

        def drain():
            nonlocal last
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                return False
            except OSError:
                return None
            with conn:
                conn.settimeout(1.0)
                buf = b""
                try:
                    while not buf.endswith(b"\n"):
                        chunk = conn.recv(65536)
                        if not chunk:
                            break
                        buf += chunk
                    got.extend(json.loads(buf.decode("utf-8")))
                except (OSError, ValueError):
                    pass
            last = time.time()
            return True

        while time.time() - last < idle and time.time() - start < cap:
            if drain() is None:
                break
        while drain():          # final sweep so late arrivals are not lost
            pass
        srv.close()
        seen, out = set(), []
        for p in sorted(got, key=lambda s: s.lower()):
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out
