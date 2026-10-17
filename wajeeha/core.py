# -*- coding: utf-8 -*-
"""
Wajeeha Archiver - archive engine (no GUI code in here).

Built-in (pure Python, no extra packages):
    ZIP, TAR, TAR.GZ, TAR.BZ2, TAR.XZ, single-file GZ / BZ2 / XZ
Optional packages (pip install pyzipper py7zr rarfile):
    pyzipper -> AES-256 encrypted ZIP
    py7zr    -> 7Z create / extract (with passwords)
    rarfile  -> RAR extract (also needs an unpacker tool, see find_tools())
Optional external tool: 7-Zip's 7z.exe next to the app or on PATH enables
extracting ISO, CAB, WIM, ARJ, LZH, CPIO, RPM, DEB, DMG, VHD ... and RAR.
"""
from __future__ import annotations

import atexit
import bz2
import copy
import datetime as dt
import fnmatch
import glob
import gzip
import io
import lzma
import mmap
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
import zlib
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional

try:
    import pyzipper
except Exception:  # pragma: no cover
    pyzipper = None
try:
    import py7zr
except Exception:  # pragma: no cover
    py7zr = None
try:
    import rarfile
except Exception:  # pragma: no cover
    rarfile = None

APP_NAME = "Wajeeha Archiver"
APP_VERSION = "1.0.0"
CHUNK = 256 * 1024
IS_WIN = os.name == "nt"

# ------------------------------------------------------------------ errors


class ArchiveError(Exception):
    pass


class PasswordRequired(ArchiveError):
    pass


class WrongPassword(ArchiveError):
    pass


class Cancelled(ArchiveError):
    pass


class UnsupportedFormat(ArchiveError):
    pass


# ------------------------------------------------------------- small utils
def human_size(n) -> str:
    if n is None:
        return ""
    n = float(n)
    if n < 1024:
        return f"{int(n)} B"
    for unit in ("KB", "MB", "GB", "TB"):
        n /= 1024.0
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
    return f"{n:.1f} TB"


def fmt_time(seconds) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def norm_name(name: str) -> str:
    name = name.replace("\\", "/")
    while name.startswith("./"):
        name = name[2:]
    return name.strip("/")


def _ts(d: Optional[dt.datetime]) -> float:
    try:
        return time.mktime(d.timetuple())
    except Exception:
        return 0.0


_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def clean_component(p: str, windows: bool = IS_WIN) -> str:
    p = p.replace("\x00", "")
    if windows:
        p = re.sub(r'[<>:"|?*\x01-\x1f]', "_", p)
        p = p.rstrip(". ")
        if p.split(".")[0].upper() in _RESERVED:
            p = "_" + p
    return p


def safe_relpath(name: str, windows: bool = IS_WIN) -> Optional[str]:
    """Sanitised relative path (forward slashes) or None if it tries to escape."""
    parts = []
    for comp in name.replace("\\", "/").split("/"):
        if comp in ("", "."):
            continue
        if comp == "..":
            return None
        comp = clean_component(comp, windows)
        if comp:
            parts.append(comp)
    return "/".join(parts) or None


def join_safe(dest: str, rel: str) -> Optional[str]:
    """dest + rel, but only if the result stays inside dest (zip-slip guard)."""
    try:
        root = os.path.normpath(os.path.abspath(dest))
        target = os.path.normpath(os.path.abspath(os.path.join(root, *rel.split("/"))))
        if os.path.normcase(os.path.commonpath([root, target])) != os.path.normcase(root):
            return None
        return target
    except (ValueError, OSError):
        return None


def unique_path(path: str) -> str:
    if not os.path.lexists(path):
        return path
    base, ext = os.path.splitext(path)
    if base.lower().endswith(".tar") and ext:
        base, ext2 = os.path.splitext(base)
        ext = ext2 + ext
    i = 1
    while True:
        cand = f"{base} ({i}){ext}"
        if not os.path.lexists(cand):
            return cand
        i += 1


def archive_stem(path: str) -> str:
    """'photos.tar.gz' -> 'photos', 'a.zip' -> 'a'."""
    name = os.path.basename(path)
    low = name.lower()
    for ext in (".tar.gz", ".tar.bz2", ".tar.xz", ".tar.z"):
        if low.endswith(ext):
            return name[: -len(ext)]
    name = re.sub(r"\.\d{3}$", "", name)
    stem = os.path.splitext(name)[0]
    return stem or name


# ----------------------------------------------------- temp dir management
_TEMP_DIRS: List[str] = []


def new_temp_dir(prefix: str = "wa") -> str:
    root = os.path.join(tempfile.gettempdir(), "WajeehaArchiver")
    os.makedirs(root, exist_ok=True)
    d = tempfile.mkdtemp(prefix=prefix + "_", dir=root)
    _TEMP_DIRS.append(d)
    return d


def cleanup_temp():
    for d in list(_TEMP_DIRS):
        shutil.rmtree(d, ignore_errors=True)
    _TEMP_DIRS.clear()


atexit.register(cleanup_temp)


# --------------------------------------------------------------- job state
class Job:
    """Shared progress / cancel state between a worker thread and the UI."""

    def __init__(self):
        self.total = 0
        self.done = 0
        self.current = ""
        self.files_total = 0
        self.files_done = 0
        self.cancelled = False
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.started = time.time()

    def check(self):
        if self.cancelled:
            raise Cancelled()

    def advance(self, n: int):
        self.done += n

    def cancel(self):
        self.cancelled = True


@dataclass
class Entry:
    name: str
    is_dir: bool = False
    size: int = 0
    packed: int = 0
    mtime: Optional[dt.datetime] = None
    crc: Optional[int] = None
    encrypted: bool = False
    method: str = ""
    raw: object = field(default=None, repr=False, compare=False)


class ExtractPolicy:
    """overwrite: ask | overwrite | skip | rename | update | freshen"""

    def __init__(self, overwrite: str = "overwrite", ask: Optional[Callable] = None):
        self.overwrite = overwrite
        self.ask = ask


# ------------------------------------------------------------ format info
CREATE_FORMATS = ["zip", "7z", "rar", "tar", "tar.gz", "tar.bz2", "tar.xz"]
FORMAT_EXT = {"zip": ".zip", "7z": ".7z", "rar": ".rar", "tar": ".tar", "tar.gz": ".tar.gz",
              "tar.bz2": ".tar.bz2", "tar.xz": ".tar.xz"}
FORMAT_LABEL = {"zip": "ZIP", "7z": "7Z", "rar": "RAR", "tar": "TAR", "tar.gz": "TAR.GZ",
                "tar.bz2": "TAR.BZ2", "tar.xz": "TAR.XZ"}
FORMAT_HINT = {
    "zip": "Opens everywhere, on every computer. Good all-round choice. Passwords use AES-256.",
    "7z": "Smallest files for most data. Passwords can also hide file names.",
    "rar": "Strong compression, optional recovery record and self-extracting .exe. Needs Rar.exe in the tools folder.",
    "tar": "Bundles files without compressing them. No password support.",
    "tar.gz": "Fast and common on Linux and macOS. No password support.",
    "tar.bz2": "Smaller than TAR.GZ but slower. No password support.",
    "tar.xz": "Very small files, slow to create. No password support.",
}
NEEDS = {"7z": "needs py7zr", "rar": "needs Rar.exe in tools"}
LEVEL_NAMES = ["Store (no compression)", "Fastest", "Fast", "Normal", "Good", "Best"]
UPDATE_MODES = [("replace", "Add and replace files"),
                ("update", "Add and update files (newer only)"),
                ("freshen", "Update existing files only")]

OTHER_EXTS = {
    ".iso": "iso", ".cab": "cab", ".wim": "wim", ".arj": "arj", ".lzh": "lzh", ".lha": "lzh",
    ".z": "z", ".cpio": "cpio", ".rpm": "rpm", ".deb": "deb", ".dmg": "dmg", ".vhd": "vhd",
    ".vhdx": "vhd", ".chm": "chm", ".msi": "msi", ".xar": "xar", ".squashfs": "squashfs",
}
ARCHIVE_EXTS = {".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".tbz2", ".tbz", ".xz", ".txz",
                ".jar", ".war", ".apk", ".001"} | set(OTHER_EXTS)
# extensions that get right-click "Extract" entries in Explorer
SHELL_EXTRACT_EXTS = [".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".tbz2", ".xz", ".txz",
                      ".iso", ".cab", ".arj", ".lzh", ".wim", ".001"]


def is_archive_name(name: str) -> bool:
    low = name.lower()
    return low.endswith(".tar.gz") or os.path.splitext(low)[1] in ARCHIVE_EXTS


def can_create(fmt: str) -> bool:
    if fmt == "7z":
        return py7zr is not None
    if fmt == "rar":
        return find_rar() is not None
    return True


def supports_password(fmt: str) -> bool:
    if fmt == "zip":
        return pyzipper is not None
    if fmt == "7z":
        return py7zr is not None
    if fmt == "rar":
        return find_rar() is not None
    return False


# ------------------------------------------------------- external tools
def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _which(*names) -> Optional[str]:
    dirs = [app_dir(), os.path.join(app_dir(), "tools")]
    if getattr(sys, "frozen", False):
        dirs.append(os.path.dirname(sys.executable))
        dirs.append(os.path.join(os.path.dirname(sys.executable), "tools"))
    for d in dirs:
        for n in names:
            p = os.path.join(d, n)
            if os.path.isfile(p):
                return p
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    if IS_WIN:
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if base:
                p = os.path.join(base, "7-Zip", "7z.exe")
                if "7z.exe" in names and os.path.isfile(p):
                    return p
    return None


def find_7z() -> Optional[str]:
    return _which("7z.exe", "7za.exe", "7zr.exe", "7z", "7zz", "7za")


def find_rar() -> Optional[str]:
    """Rar.exe (the command-line RAR packer) - needed to CREATE rar archives."""
    return _which("Rar.exe", "rar.exe", "rar")


def find_unrar() -> Optional[str]:
    """UnRAR.exe - or Rar.exe, which can unpack too."""
    return _which("UnRAR.exe", "unrar.exe", "unrar") or find_rar()


def _setup_rarfile():
    if rarfile is None:
        return False
    try:
        t = find_unrar()
        if t:
            rarfile.UNRAR_TOOL = t
        z = find_7z()
        if z and hasattr(rarfile, "SEVENZIP_TOOL"):
            rarfile.SEVENZIP_TOOL = z
        tar = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe")
        if IS_WIN and os.path.isfile(tar) and hasattr(rarfile, "BSDTAR_TOOL"):
            rarfile.BSDTAR_TOOL = tar
        if hasattr(rarfile, "tool_setup"):
            try:
                rarfile.tool_setup(force=True)
            except TypeError:
                rarfile.tool_setup()
        return True
    except Exception:
        return True


def capabilities() -> Dict[str, object]:
    return {
        "zip": True, "tar": True, "gz/bz2/xz": True,
        "zip-aes": pyzipper is not None,
        "7z": py7zr is not None,
        "rar": rarfile is not None and (find_unrar() is not None or find_7z() is not None),
        "rar-reader": rarfile is not None,
        "rar-create": find_rar(),
        "7z-tool": find_7z(),
        "unrar-tool": find_unrar(),
    }


def _popen_kwargs():
    kw = {}
    if IS_WIN:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kw["startupinfo"] = si
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return kw


def _run_tool(cmd, cwd=None, job=None, on_chunk=None):
    """Run a console helper; returns (exit code, output text). Honours job.cancel()."""
    p = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, **_popen_kwargs())
    out = bytearray()
    try:
        while True:
            chunk = p.stdout.read1(4096)
            if not chunk:
                break
            if len(out) < 200000:
                out += chunk
            if on_chunk:
                on_chunk(chunk)
            if job is not None and job.cancelled:
                p.terminate()
                raise Cancelled()
    finally:
        p.stdout.close()
        p.wait()
    return p.returncode, out.decode("utf-8", "replace")


def _tool_tail(text, n=5):
    return "\n".join([ln.strip() for ln in text.strip().splitlines() if ln.strip()][-n:])


# ------------------------------------------------------ format detection
def _is_tar(path: str) -> bool:
    try:
        return tarfile.is_tarfile(path)
    except Exception:
        return False


def detect_format(path: str) -> Optional[str]:
    """Identify an archive by its content (extension only as a fallback)."""
    try:
        with open(path, "rb") as f:
            head = f.read(560)
            f.seek(0x8001)
            iso = f.read(5)
    except OSError as e:
        raise ArchiveError(f"Cannot read {path}: {e}")
    low = path.lower()
    if head[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        return "zip"
    if head[:6] == b"7z\xbc\xaf\x27\x1c":
        return "7z"
    if head[:7] == b"Rar!\x1a\x07\x00" or head[:8] == b"Rar!\x1a\x07\x01\x00":
        return "rar"
    kind = None
    if head[:2] == b"\x1f\x8b":
        kind = "gz"
    elif head[:3] == b"BZh":
        kind = "bz2"
    elif head[:6] == b"\xfd7zXZ\x00":
        kind = "xz"
    if kind:
        return "tar" if _is_tar(path) else kind
    if head[257:262] == b"ustar":
        return "tar"
    if iso == b"CD001":
        return "iso"
    if head[:4] == b"MSCF":
        return "cab"
    if head[:8] == b"MSWIM\x00\x00\x00":
        return "wim"
    if head[:2] == b"\x60\xea":
        return "arj"
    ext = os.path.splitext(low)[1]
    if ext in OTHER_EXTS:
        return OTHER_EXTS[ext]
    if low.endswith(".tar") and _is_tar(path):
        return "tar"
    try:
        if zipfile.is_zipfile(path):
            return "zip"
    except Exception:
        pass
    return None


def tar_write_mode(path: str) -> str:
    with open(path, "rb") as f:
        h = f.read(6)
    if h[:2] == b"\x1f\x8b":
        return "w:gz"
    if h[:3] == b"BZh":
        return "w:bz2"
    if h[:6] == b"\xfd7zXZ\x00":
        return "w:xz"
    return "w"


def tar_format_of(path: str) -> str:
    return {"w:gz": "tar.gz", "w:bz2": "tar.bz2", "w:xz": "tar.xz", "w": "tar"}[tar_write_mode(path)]


# ---------------------------------------------------- shared write helpers
def _set_mtime(path: str, mtime: Optional[dt.datetime]):
    if not mtime:
        return
    try:
        ts = _ts(mtime)
        if ts > 0:
            os.utime(path, (ts, ts))
    except OSError:
        pass


def _copy_out(fsrc, final: str, job: Job, mtime: Optional[dt.datetime] = None):
    """Stream fsrc into `final` via a temp name; remove partial files on failure."""
    tmp = final + ".wapart"
    try:
        with open(tmp, "wb") as out:
            while True:
                b = fsrc.read(CHUNK)
                if not b:
                    break
                out.write(b)
                job.advance(len(b))
                job.check()
        try:
            os.replace(tmp, final)
        except PermissionError:
            os.chmod(final, stat.S_IWRITE | stat.S_IREAD)
            os.replace(tmp, final)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    _set_mtime(final, mtime)


def resolve_target(path: str, policy: ExtractPolicy, size: int = 0, mtime=None) -> Optional[str]:
    """Apply the overwrite policy. Returns the path to write, or None to skip."""
    mode = policy.overwrite
    if not os.path.lexists(path):
        return None if mode == "freshen" else path
    if os.path.isdir(path):
        return None
    if mode == "ask":
        ans = policy.ask(path, size, mtime) if policy.ask else "yes"
        if ans == "cancel":
            raise Cancelled()
        if ans == "yes_all":
            policy.overwrite = "overwrite"
            return path
        if ans == "no_all":
            policy.overwrite = "skip"
            return None
        if ans == "rename":
            return unique_path(path)
        return path if ans == "yes" else None
    if mode == "overwrite":
        return path
    if mode == "skip":
        return None
    if mode == "rename":
        return unique_path(path)
    if mode in ("update", "freshen"):
        if mtime is None:
            return path
        try:
            return path if _ts(mtime) > os.path.getmtime(path) + 1 else None
        except OSError:
            return path
    return path


def _strip(name: str, strip: str) -> Optional[str]:
    if not strip:
        return name
    if name == strip:
        return None
    if name.startswith(strip + "/"):
        return name[len(strip) + 1:]
    return None


def select_entries(entries: List[Entry], names: Optional[Iterable[str]]) -> List[Entry]:
    if names is None:
        return list(entries)
    sel = {norm_name(n) for n in names}
    out = []
    for e in entries:
        p = e.name
        while p:
            if p in sel:
                out.append(e)
                break
            p = p.rpartition("/")[0]
    return out


def _target_for(e_name: str, dest: str, strip: str, job: Job) -> Optional[str]:
    rel = _strip(e_name, strip)
    if rel is None:
        return None
    rel = safe_relpath(rel)
    if rel is None:
        job.errors.append(f"Skipped unsafe path: {e_name}")
        return None
    target = join_safe(dest, rel)
    if target is None:
        job.errors.append(f"Skipped unsafe path: {e_name}")
    return target


def commit_staged(stage: str, dest: str, strip: str, policy: ExtractPolicy, job: Job):
    """Move files extracted by an external library from `stage` into `dest`,
    applying the overwrite policy and stripping `strip`."""
    for root, dirs, files in os.walk(stage):
        rel_root = os.path.relpath(root, stage).replace(os.sep, "/")
        rel_root = "" if rel_root == "." else rel_root
        for d in dirs:
            name = f"{rel_root}/{d}" if rel_root else d
            target = _target_for(name, dest, strip, job)
            if target and policy.overwrite != "freshen":
                os.makedirs(target, exist_ok=True)
        for f in files:
            name = f"{rel_root}/{f}" if rel_root else f
            target = _target_for(name, dest, strip, job)
            if not target:
                continue
            src = os.path.join(root, f)
            try:
                st = os.stat(src)
                mt = dt.datetime.fromtimestamp(st.st_mtime)
                size = st.st_size
            except OSError:
                mt, size = None, 0
            final = resolve_target(target, policy, size, mt)
            if final is None:
                continue
            os.makedirs(os.path.dirname(final), exist_ok=True)
            if os.path.lexists(final):
                try:
                    os.chmod(final, stat.S_IWRITE | stat.S_IREAD)
                    os.remove(final)
                except OSError:
                    pass
            shutil.move(src, final)
            job.check()


# ============================================================== readers
class Archive:
    kind = "?"
    label = "Archive"

    def __init__(self, path: str, password: Optional[str] = None):
        self.path = path
        self.source_path = path
        self.password = password
        self._entries: Optional[List[Entry]] = None
        self.cleanup: List[str] = []

    # --- to implement
    def _load(self) -> List[Entry]:
        raise NotImplementedError

    def extract(self, dest, names=None, job=None, policy=None, strip="") -> Job:
        raise NotImplementedError

    def test(self, job=None) -> Job:
        raise NotImplementedError

    # --- shared
    def entries(self) -> List[Entry]:
        if self._entries is None:
            self._entries = self._load()
        return self._entries

    def comment(self) -> str:
        return ""

    @property
    def header_encrypted(self) -> bool:
        return False

    @property
    def encrypted(self) -> bool:
        return self.header_encrypted or any(e.encrypted for e in self.entries())

    def _prep(self, job, names):
        ents = select_entries(self.entries(), names)
        job.total = sum(e.size for e in ents if not e.is_dir)
        job.files_total = sum(1 for e in ents if not e.is_dir)
        return ents

    def close(self):
        for p in self.cleanup:
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    os.remove(p)
            except OSError:
                pass
        self.cleanup = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


_ZIP_METHODS = {0: "Store", 8: "Deflate", 9: "Deflate64", 12: "BZip2", 14: "LZMA", 93: "Zstd", 99: "AES"}


class ZipArchive(Archive):
    kind = "zip"
    label = "ZIP"

    def __init__(self, path, password=None):
        super().__init__(path, password)
        cls = pyzipper.AESZipFile if pyzipper else zipfile.ZipFile
        try:
            self.zf = cls(path, "r")
        except zipfile.BadZipFile as e:
            raise ArchiveError(f"This is not a valid ZIP archive, or it is damaged ({e}). "
                               "Try Tools > Repair archive.")

    def _load(self):
        out = []
        for zi in self.zf.infolist():
            name = norm_name(zi.filename)
            if not name:
                continue
            try:
                mt = dt.datetime(*zi.date_time)
            except ValueError:
                mt = None
            out.append(Entry(name, zi.is_dir(), zi.file_size, zi.compress_size, mt, zi.CRC,
                             bool(zi.flag_bits & 1), _ZIP_METHODS.get(zi.compress_type, str(zi.compress_type)), zi))
        return out

    def comment(self):
        try:
            return self.zf.comment.decode("utf-8", "replace")
        except Exception:
            return ""

    def _pwd(self):
        return self.password.encode("utf-8") if self.password else None

    def _open(self, e: Entry):
        try:
            return self.zf.open(e.raw, pwd=self._pwd())
        except RuntimeError as ex:
            self._pw_error(ex)
        except NotImplementedError:
            raise ArchiveError("This ZIP uses AES encryption or an unsupported method. "
                               "Install the 'pyzipper' package (pip install pyzipper).")

    def _pw_error(self, ex):
        if "password" in str(ex).lower():
            raise (WrongPassword("Wrong password.") if self.password else PasswordRequired("Password required."))
        raise ArchiveError(str(ex))

    def extract(self, dest, names=None, job=None, policy=None, strip=""):
        job = job or Job()
        policy = policy or ExtractPolicy()
        ents = self._prep(job, names)
        os.makedirs(dest, exist_ok=True)
        for e in ents:
            job.check()
            job.current = e.name
            target = _target_for(e.name, dest, strip, job)
            if not target:
                continue
            if e.is_dir:
                if policy.overwrite != "freshen":
                    os.makedirs(target, exist_ok=True)
                continue
            if e.encrypted and not self.password:
                raise PasswordRequired("Password required.")
            final = resolve_target(target, policy, e.size, e.mtime)
            if final is None:
                job.advance(e.size)
                job.files_done += 1
                continue
            os.makedirs(os.path.dirname(final), exist_ok=True)
            try:
                with self._open(e) as src:
                    _copy_out(src, final, job, e.mtime)
            except RuntimeError as ex:
                self._pw_error(ex)
            except (zipfile.BadZipFile, zlib.error, EOFError) as ex:
                if e.encrypted:
                    raise WrongPassword("Wrong password, or the file is damaged.")
                job.errors.append(f"{e.name}: {ex}")
            job.files_done += 1
        return job

    def test(self, job=None):
        job = job or Job()
        ents = [e for e in self._prep(job, None) if not e.is_dir]
        for e in ents:
            job.check()
            job.current = e.name
            if e.encrypted and not self.password:
                raise PasswordRequired("Password required.")
            try:
                with self._open(e) as src:
                    while True:
                        b = src.read(CHUNK)
                        if not b:
                            break
                        job.advance(len(b))
                        job.check()
            except RuntimeError as ex:
                self._pw_error(ex)
            except (zipfile.BadZipFile, zlib.error, EOFError) as ex:
                if e.encrypted and self.password:
                    raise WrongPassword("Wrong password, or the file is damaged.")
                job.errors.append(f"{e.name}: {ex}")
            job.files_done += 1
        return job

    def close(self):
        try:
            self.zf.close()
        except Exception:
            pass
        super().close()


def _tar_entry_time(ti):
    try:
        return dt.datetime.fromtimestamp(ti.mtime)
    except (OSError, OverflowError, ValueError):
        return None


class TarArchive(Archive):
    kind = "tar"
    label = "TAR"

    def __init__(self, path, password=None):
        super().__init__(path, password)
        try:
            with tarfile.open(path, "r:*"):
                pass
        except (tarfile.TarError, EOFError, OSError) as e:
            raise ArchiveError(f"Cannot read this TAR archive: {e}")
        mode = tar_write_mode(path)
        self.label = {"w": "TAR", "w:gz": "TAR.GZ", "w:bz2": "TAR.BZ2", "w:xz": "TAR.XZ"}[mode]

    def _load(self):
        out = []
        try:
            with tarfile.open(self.path, "r:*") as tf:
                for ti in tf:
                    name = norm_name(ti.name)
                    if not name:
                        continue
                    if not (ti.isreg() or ti.isdir() or ti.issym() or ti.islnk()):
                        continue
                    out.append(Entry(name, ti.isdir(), ti.size if ti.isreg() else 0, 0,
                                     _tar_entry_time(ti), None, False, "tar"))
        except (tarfile.TarError, EOFError, OSError) as e:
            raise ArchiveError(f"The TAR archive is damaged: {e}")
        return out

    def extract(self, dest, names=None, job=None, policy=None, strip=""):
        job = job or Job()
        policy = policy or ExtractPolicy()
        ents = self._prep(job, names)
        wanted = {e.name for e in ents}
        os.makedirs(dest, exist_ok=True)
        try:
            with tarfile.open(self.path, "r:*") as tf:
                for ti in tf:
                    name = norm_name(ti.name)
                    if name not in wanted:
                        continue
                    job.check()
                    job.current = name
                    if ti.issym() or ti.islnk():
                        job.warnings.append(f"Skipped link: {name}")
                        continue
                    target = _target_for(name, dest, strip, job)
                    if not target:
                        continue
                    if ti.isdir():
                        if policy.overwrite != "freshen":
                            os.makedirs(target, exist_ok=True)
                        continue
                    if not ti.isreg():
                        continue
                    mt = _tar_entry_time(ti)
                    final = resolve_target(target, policy, ti.size, mt)
                    if final is None:
                        job.advance(ti.size)
                        job.files_done += 1
                        continue
                    os.makedirs(os.path.dirname(final), exist_ok=True)
                    src = tf.extractfile(ti)
                    _copy_out(src, final, job, mt)
                    job.files_done += 1
        except (tarfile.TarError, EOFError, zlib.error, lzma.LZMAError) as e:
            job.errors.append(f"Archive is damaged or truncated: {e}")
        return job

    def test(self, job=None):
        job = job or Job()
        self._prep(job, None)
        try:
            with tarfile.open(self.path, "r:*") as tf:
                for ti in tf:
                    job.check()
                    job.current = ti.name
                    if ti.isreg():
                        src = tf.extractfile(ti)
                        while True:
                            b = src.read(CHUNK)
                            if not b:
                                break
                            job.advance(len(b))
                            job.check()
                        job.files_done += 1
        except (tarfile.TarError, EOFError, zlib.error, lzma.LZMAError, OSError) as e:
            job.errors.append(f"Archive is damaged or truncated: {e}")
        return job


class StreamArchive(Archive):
    """A single compressed file: .gz, .bz2 or .xz that is not a tarball."""
    kind = "stream"

    def __init__(self, path, password=None, comp="gz"):
        super().__init__(path, password)
        self.comp = comp
        self.label = comp.upper()
        self._open_fn = {"gz": gzip.open, "bz2": bz2.open, "xz": lzma.open}[comp]

    def _inner_name(self):
        base = os.path.basename(self.source_path)
        stem, ext = os.path.splitext(base)
        return stem if ext.lower() in (".gz", ".bz2", ".xz") and stem else base + ".out"

    def _load(self):
        size = 0
        if self.comp == "gz":
            try:
                with open(self.path, "rb") as f:
                    f.seek(-4, os.SEEK_END)
                    size = struct.unpack("<I", f.read(4))[0]
            except OSError:
                pass
        try:
            mt = dt.datetime.fromtimestamp(os.path.getmtime(self.path))
        except OSError:
            mt = None
        return [Entry(self._inner_name(), False, size, os.path.getsize(self.path), mt, None, False, self.comp)]

    def extract(self, dest, names=None, job=None, policy=None, strip=""):
        job = job or Job()
        policy = policy or ExtractPolicy()
        e = self.entries()[0]
        if names is not None and e.name not in {norm_name(n) for n in names}:
            return job
        job.total = e.size or os.path.getsize(self.path) * 3
        job.files_total = 1
        os.makedirs(dest, exist_ok=True)
        target = _target_for(e.name, dest, "", job)
        if not target:
            return job
        job.current = e.name
        final = resolve_target(target, policy, e.size, e.mtime)
        if final is None:
            return job
        try:
            with self._open_fn(self.path, "rb") as src:
                _copy_out(src, final, job, e.mtime)
        except (OSError, EOFError, zlib.error, lzma.LZMAError) as ex:
            job.errors.append(f"{e.name}: {ex}")
        job.files_done = 1
        return job

    def test(self, job=None):
        job = job or Job()
        job.total = self.entries()[0].size or os.path.getsize(self.path) * 3
        try:
            with self._open_fn(self.path, "rb") as src:
                while True:
                    b = src.read(CHUNK)
                    if not b:
                        break
                    job.advance(len(b))
                    job.check()
        except (OSError, EOFError, zlib.error, lzma.LZMAError) as ex:
            job.errors.append(str(ex))
        return job


class SevenZArchive(Archive):
    kind = "7z"
    label = "7Z"

    def __init__(self, path, password=None):
        super().__init__(path, password)
        if py7zr is None:
            raise UnsupportedFormat("7Z support needs the 'py7zr' package.\nInstall it with:  pip install py7zr")
        self._hdr_enc = False
        self.z = self._open()

    def _open(self):
        try:
            return py7zr.SevenZipFile(self.path, "r", password=self.password)
        except Exception as e:
            msg = str(e).lower()
            if "password" in msg or "encrypted" in msg:
                self._hdr_enc = True
                raise (WrongPassword("Wrong password.") if self.password else PasswordRequired("Password required."))
            raise ArchiveError(f"Cannot open this 7Z archive: {e}")

    @property
    def header_encrypted(self):
        return self._hdr_enc

    def _load(self):
        out = []
        for fi in self.z.list():
            name = norm_name(getattr(fi, "filename", ""))
            if not name:
                continue
            mt = getattr(fi, "creationtime", None)
            try:
                if mt is not None:
                    mt = mt.astimezone().replace(tzinfo=None)
            except Exception:
                mt = None
            out.append(Entry(name, bool(getattr(fi, "is_directory", False)),
                             int(getattr(fi, "uncompressed", 0) or 0),
                             int(getattr(fi, "compressed", 0) or 0), mt,
                             getattr(fi, "crc32", None), False, "7z"))
        try:
            enc = bool(self.z.needs_password())
        except Exception:
            enc = False
        if enc:
            for e in out:
                e.encrypted = not e.is_dir
        return out

    def _map_error(self, ex):
        msg = str(ex).lower()
        if isinstance(ex, Cancelled):
            raise ex
        if "password" in msg or "decrypt" in msg or "crc" in msg and self.password:
            raise (WrongPassword("Wrong password.") if self.password else PasswordRequired("Password required."))
        raise ArchiveError(f"7Z error: {ex}")

    def extract(self, dest, names=None, job=None, policy=None, strip=""):
        job = job or Job()
        policy = policy or ExtractPolicy()
        ents = self._prep(job, names)
        os.makedirs(dest, exist_ok=True)
        if any(e.encrypted for e in ents) and not self.password:
            raise PasswordRequired("Password required.")
        stage = tempfile.mkdtemp(dir=dest, prefix=".wa_")
        try:
            targets = None if names is None else [e.name for e in ents if not e.is_dir]
            z = py7zr.SevenZipFile(self.path, "r", password=self.password)
            try:
                cb = None
                try:
                    cb = _make_7z_callback(job)
                except Exception:
                    cb = None
                try:
                    if cb is not None:
                        z.extract(path=stage, targets=targets, callback=cb)
                    else:
                        z.extract(path=stage, targets=targets)
                except TypeError:
                    z.close()
                    z = py7zr.SevenZipFile(self.path, "r", password=self.password)
                    z.extract(path=stage, targets=targets)
            finally:
                z.close()
            job.done = job.total
            commit_staged(stage, dest, strip, policy, job)
        except ArchiveError:
            raise
        except Exception as ex:
            self._map_error(ex)
        finally:
            shutil.rmtree(stage, ignore_errors=True)
        return job

    def test(self, job=None):
        job = job or Job()
        self._prep(job, None)
        try:
            z = py7zr.SevenZipFile(self.path, "r", password=self.password)
            try:
                bad = z.testzip()
            finally:
                z.close()
            if bad:
                job.errors.append(f"Damaged file: {bad}")
        except Exception as ex:
            self._map_error(ex)
        job.done = job.total
        return job

    def close(self):
        try:
            self.z.close()
        except Exception:
            pass
        super().close()


def _make_7z_callback(job: Job):
    from py7zr.callbacks import ExtractCallback

    class _CB(ExtractCallback):
        def report_start_preparation(self):
            pass

        def report_start(self, processing_file_path, processing_bytes):
            job.current = str(processing_file_path)
            job.check()

        def report_update(self, decompressed_bytes):
            try:
                job.done += int(decompressed_bytes)
            except Exception:
                pass
            job.check()

        def report_end(self, processing_file_path, wrote_bytes):
            job.files_done += 1
            job.check()

        def report_warning(self, message):
            job.warnings.append(str(message))

        def report_postprocess(self):
            pass
    return _CB()


class RarArchive(Archive):
    kind = "rar"
    label = "RAR"

    def __init__(self, path, password=None):
        super().__init__(path, password)
        if rarfile is None:
            raise UnsupportedFormat("RAR support needs the 'rarfile' package.\nInstall it with:  pip install rarfile\n"
                                    "and put UnRAR.exe or 7z.exe next to the app (or install 7-Zip).")
        _setup_rarfile()
        try:
            self.rf = rarfile.RarFile(path)
            if password:
                self.rf.setpassword(password)
        except Exception as e:
            self._map(e, opening=True)

    def _map(self, e, opening=False):
        name = type(e).__name__
        msg = str(e)
        if isinstance(e, Cancelled):
            raise e
        if "PasswordRequired" in name or "need password" in msg.lower():
            raise PasswordRequired("Password required.")
        if "WrongPassword" in name or "wrong password" in msg.lower() or "bad password" in msg.lower():
            raise WrongPassword("Wrong password.")
        if "CannotExec" in name or "Cannot find working tool" in msg or "tool" in msg.lower() and "not found" in msg.lower():
            raise UnsupportedFormat("To extract RAR files this app needs a free helper tool.\n"
                                    "Install 7-Zip (7-zip.org) or put UnRAR.exe next to Wajeeha Archiver.")
        raise ArchiveError(f"RAR error: {msg}")

    @property
    def header_encrypted(self):
        try:
            return bool(self.rf.needs_password()) and not self.rf.infolist()
        except Exception:
            return False

    def _load(self):
        out = []
        try:
            infos = self.rf.infolist()
        except Exception as e:
            self._map(e)
        for ri in infos:
            name = norm_name(ri.filename)
            if not name:
                continue
            try:
                mt = dt.datetime(*ri.date_time)
            except Exception:
                mt = None
            try:
                enc = bool(ri.needs_password())
            except Exception:
                enc = False
            out.append(Entry(name, ri.is_dir(), ri.file_size, ri.compress_size, mt, getattr(ri, "CRC", None),
                             enc, "rar", ri))
        return out

    def comment(self):
        try:
            return self.rf.comment or ""
        except Exception:
            return ""

    def extract(self, dest, names=None, job=None, policy=None, strip=""):
        job = job or Job()
        policy = policy or ExtractPolicy()
        ents = self._prep(job, names)
        os.makedirs(dest, exist_ok=True)
        if any(e.encrypted for e in ents) and not self.password:
            raise PasswordRequired("Password required.")
        stage = tempfile.mkdtemp(dir=dest, prefix=".wa_")
        try:
            members = None if names is None else [e.raw for e in ents if not e.is_dir]
            job.current = "Extracting..."
            self.rf.extractall(path=stage, members=members, pwd=self.password)
            job.done = job.total
            commit_staged(stage, dest, strip, policy, job)
        except ArchiveError:
            raise
        except Exception as ex:
            self._map(ex)
        finally:
            shutil.rmtree(stage, ignore_errors=True)
        return job

    def test(self, job=None):
        job = job or Job()
        self._prep(job, None)
        try:
            self.rf.testrar(pwd=self.password) if _accepts_pwd(self.rf.testrar) else self.rf.testrar()
        except Exception as ex:
            self._map(ex)
        job.done = job.total
        return job


def _accepts_pwd(fn) -> bool:
    try:
        import inspect
        return "pwd" in inspect.signature(fn).parameters
    except Exception:
        return False


def parse_7z_slt(text: str) -> List[Entry]:
    body = text
    marker = text.find("\n----------")
    if marker >= 0:
        body = text[marker + 11:]
    entries = []
    for block in re.split(r"\r?\n\r?\n", body.strip()):
        kv = {}
        for line in block.splitlines():
            k, sep, v = line.partition(" = ")
            if sep:
                kv[k.strip()] = v.strip()
        if "Path" not in kv:
            continue
        name = norm_name(kv["Path"])
        if not name:
            continue
        attr = kv.get("Attributes", "")
        is_dir = kv.get("Folder") == "+" or ("D" in attr.split(" ")[0] if attr else False)
        mt = None
        m = kv.get("Modified", "")
        if m:
            try:
                mt = dt.datetime.strptime(m[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                mt = None

        def num(key):
            try:
                return int(kv.get(key, "0") or 0)
            except ValueError:
                return 0
        crc = None
        if kv.get("CRC"):
            try:
                crc = int(kv["CRC"], 16)
            except ValueError:
                pass
        entries.append(Entry(name, is_dir, num("Size"), num("Packed Size"), mt, crc,
                             kv.get("Encrypted", "-") == "+", kv.get("Method", "")))
    return entries


class CliArchive(Archive):
    """Anything 7-Zip can read, using 7z(.exe) as a helper (ISO, CAB, WIM, RAR ...)."""
    kind = "cli"

    def __init__(self, path, password=None, label="Archive"):
        super().__init__(path, password)
        self.tool = find_7z()
        if not self.tool:
            raise UnsupportedFormat(
                "This format needs the free 7-Zip tool.\nInstall 7-Zip (7-zip.org) or copy 7z.exe and 7z.dll "
                "into the 'tools' folder next to Wajeeha Archiver.")
        self.label = label.upper()
        self._hdr_enc = False

    def _pw_args(self):
        return [f"-p{self.password}"] if self.password else []

    def _run(self, args, job=None):
        def on_chunk(chunk):
            pcts = re.findall(rb"(\d{1,3})%", chunk)
            if pcts and job is not None and job.total:
                job.done = int(job.total * min(100, int(pcts[-1])) / 100)
        return _run_tool([self.tool] + args, job=job, on_chunk=on_chunk)

    def _check_errors(self, rc, text):
        low = text.lower()
        if "wrong password" in low or "enter password" in low or "can not open encrypted" in low:
            raise (WrongPassword("Wrong password.") if self.password else PasswordRequired("Password required."))
        if rc not in (0, 1):
            tail = "\n".join(text.strip().splitlines()[-4:])
            raise ArchiveError(f"7-Zip reported an error:\n{tail}")

    def _load(self):
        rc, text = self._run(["l", "-slt", "-y", "-sccUTF-8"] + self._pw_args() + [self.path])
        self._check_errors(rc, text)
        return parse_7z_slt(text)

    def extract(self, dest, names=None, job=None, policy=None, strip=""):
        job = job or Job()
        policy = policy or ExtractPolicy()
        ents = self._prep(job, names)
        os.makedirs(dest, exist_ok=True)
        stage = tempfile.mkdtemp(dir=dest, prefix=".wa_")
        listfile = None
        try:
            args = ["x", "-y", "-bsp1", "-aoa", f"-o{stage}"] + self._pw_args() + [self.path]
            if names is not None:
                fd, listfile = tempfile.mkstemp(suffix=".txt")
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write("\n".join(e.name for e in ents if not e.is_dir))
                args = ["x", "-y", "-bsp1", "-aoa", "-scsUTF-8", f"-o{stage}"] + self._pw_args() + \
                       [self.path, "@" + listfile]
            job.current = "Extracting..."
            rc, text = self._run(args, job)
            self._check_errors(rc, text)
            job.done = job.total
            commit_staged(stage, dest, strip, policy, job)
        finally:
            shutil.rmtree(stage, ignore_errors=True)
            if listfile:
                try:
                    os.remove(listfile)
                except OSError:
                    pass
        return job

    def test(self, job=None):
        job = job or Job()
        self._prep(job, None)
        rc, text = self._run(["t", "-y", "-bsp1"] + self._pw_args() + [self.path], job)
        self._check_errors(rc, text)
        if rc != 0:
            job.errors.append("7-Zip found problems in this archive.")
        job.done = job.total
        return job


# ------------------------------------------------------- volumes (.001)
def find_volumes(first: str) -> List[str]:
    base = first[:-4]
    parts = [first]
    i = 2
    while os.path.exists(f"{base}.{i:03d}"):
        parts.append(f"{base}.{i:03d}")
        i += 1
    return parts


def join_volumes(first: str, job: Optional[Job] = None) -> str:
    parts = find_volumes(first)
    tmpdir = new_temp_dir("join")
    out = os.path.join(tmpdir, os.path.basename(first)[:-4] or "joined")
    with open(out, "wb") as fo:
        for p in parts:
            with open(p, "rb") as fi:
                while True:
                    b = fi.read(CHUNK)
                    if not b:
                        break
                    fo.write(b)
                    if job:
                        job.advance(len(b))
                        job.check()
    return out


def split_file(path: str, size: int, job: Optional[Job] = None) -> List[str]:
    parts = []
    with open(path, "rb") as fi:
        i = 1
        while True:
            chunk = fi.read(min(size, CHUNK))
            if not chunk:
                break
            part = f"{path}.{i:03d}"
            written = 0
            with open(part, "wb") as fo:
                while chunk:
                    fo.write(chunk)
                    written += len(chunk)
                    if job:
                        job.check()
                    if written >= size:
                        break
                    chunk = fi.read(min(size - written, CHUNK))
            parts.append(part)
            i += 1
    os.remove(path)
    return parts


def open_archive(path: str, password: Optional[str] = None) -> Archive:
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise ArchiveError(f"File not found:\n{path}")
    cleanup: List[str] = []
    real = path
    if re.search(r"\.001$", path, re.I) and os.path.exists(path[:-3] + "002"):
        real = join_volumes(path)
        cleanup.append(os.path.dirname(real))
    fmt = detect_format(real)
    if fmt == "zip":
        arc = ZipArchive(real, password)
    elif fmt == "tar":
        arc = TarArchive(real, password)
    elif fmt in ("gz", "bz2", "xz"):
        arc = StreamArchive(real, password, fmt)
    elif fmt == "7z":
        arc = SevenZArchive(real, password) if py7zr is not None else CliArchive(real, password, "7z")
    elif fmt == "rar":
        if rarfile is not None and (find_unrar() or not find_7z()):
            arc = RarArchive(real, password)
        else:
            arc = CliArchive(real, password, "rar")
    elif fmt:
        arc = CliArchive(real, password, fmt)
    else:
        raise UnsupportedFormat("Wajeeha Archiver does not recognise this file as an archive.")
    arc.source_path = path
    arc.cleanup.extend(cleanup)
    return arc


# ============================================================== writers
@dataclass
class AddOptions:
    fmt: str = "zip"
    level: int = 3                     # 0 store, 1 fastest, 2 fast, 3 normal, 4 good, 5 best
    password: Optional[str] = None
    encrypt_names: bool = False
    excludes: List[str] = field(default_factory=list)
    comment: str = ""
    update_mode: str = "replace"       # replace | update | freshen
    split_size: int = 0                # bytes, 0 = no split
    delete_after: bool = False
    test_after: bool = False
    prefix: str = ""                   # folder inside the archive
    solid: bool = False                # RAR only
    recovery: bool = False             # RAR only: add a recovery record
    sfx: bool = False                  # RAR only: self-extracting .exe


@dataclass
class Item:
    path: str
    arc: str
    is_dir: bool
    size: int


_LV_DEFLATE = [1, 1, 3, 6, 8, 9]
_LV_BZ2 = [1, 1, 3, 5, 7, 9]
_LV_XZ = [0, 0, 2, 6, 8, 9]
_LV_7Z = [0, 1, 3, 5, 7, 9]


def _excluded(rel: str, base: str, pats: List[str]) -> bool:
    rel_l, base_l = rel.lower(), base.lower()
    for p in pats:
        p = p.lower()
        if fnmatch.fnmatchcase(base_l, p) or fnmatch.fnmatchcase(rel_l, p):
            return True
    return False


def collect_items(sources: Iterable[str], excludes: Iterable[str] = (), skip_path: Optional[str] = None,
                  prefix: str = "", job: Optional[Job] = None) -> List[Item]:
    pats = [p.strip() for p in excludes if p and p.strip()]
    skip = os.path.normcase(os.path.abspath(skip_path)) if skip_path else None
    pre = (norm_name(prefix) + "/") if prefix else ""
    items: List[Item] = []
    for src in sources:
        src = os.path.abspath(src)
        base_name = os.path.basename(src.rstrip("\\/")) or src.replace(":", "").replace("\\", "").replace("/", "") or "root"
        if os.path.isdir(src):
            items.append(Item(src, pre + base_name, True, 0))
            for root, dirs, files in os.walk(src):
                dirs.sort()
                rel_root = os.path.relpath(root, src).replace(os.sep, "/")
                rel_root = "" if rel_root == "." else rel_root + "/"
                keep = []
                for d in dirs:
                    if _excluded(rel_root + d, d, pats):
                        continue
                    keep.append(d)
                    items.append(Item(os.path.join(root, d), f"{pre}{base_name}/{rel_root}{d}", True, 0))
                dirs[:] = keep
                for f in sorted(files):
                    full = os.path.join(root, f)
                    if skip and os.path.normcase(os.path.abspath(full)) == skip:
                        continue
                    if _excluded(rel_root + f, f, pats):
                        continue
                    try:
                        size = os.path.getsize(full)
                    except OSError:
                        if job:
                            job.warnings.append(f"Cannot read: {full}")
                        continue
                    items.append(Item(full, f"{pre}{base_name}/{rel_root}{f}", False, size))
        elif os.path.exists(src):
            if skip and os.path.normcase(src) == skip:
                continue
            if _excluded(base_name, base_name, pats):
                continue
            items.append(Item(src, pre + base_name, False, os.path.getsize(src)))
    return items


class _ProgressReader:
    def __init__(self, f, job):
        self.f, self.job = f, job

    def read(self, n=-1):
        b = self.f.read(n)
        if b:
            self.job.advance(len(b))
            self.job.check()
        return b


def _raw_copy_zip(src: str, dst: str, drop=frozenset()):
    """Copy a ZIP without recompressing, leaving out entries named in `drop`."""
    with zipfile.ZipFile(src, "r") as zin, zipfile.ZipFile(dst, "w", allowZip64=True) as zout:
        zout.comment = zin.comment
        fin, fout = zin.fp, zout.fp
        for zi in zin.infolist():
            if norm_name(zi.filename) in drop:
                continue
            fin.seek(zi.header_offset)
            lh = fin.read(30)
            if len(lh) < 30 or lh[:4] != b"PK\x03\x04":
                raise ArchiveError("The ZIP archive is damaged (bad entry header).")
            nlen, elen = struct.unpack("<HH", lh[26:30])
            flag = struct.unpack("<H", lh[6:8])[0]
            new = copy.copy(zi)
            new.header_offset = fout.tell()
            fin.seek(zi.header_offset)
            remaining = 30 + nlen + elen + zi.compress_size
            while remaining:
                chunk = fin.read(min(CHUNK, remaining))
                if not chunk:
                    raise ArchiveError("The ZIP archive is truncated.")
                fout.write(chunk)
                remaining -= len(chunk)
            if flag & 0x08:
                big = zi.file_size > 0xFFFFFFFF or zi.compress_size > 0xFFFFFFFF
                d = fin.read(4)
                if d == b"PK\x07\x08":
                    fout.write(d + fin.read(20 if big else 12))
                else:
                    fout.write(d + fin.read(16 if big else 8))
            zout.filelist.append(new)
            zout.NameToInfo[new.filename] = new
            zout._didModify = True
        zout.start_dir = fout.tell()   # central directory goes after the raw data we copied


def _write_zip(dest: str, items: List[Item], opts: AddOptions, job: Job,
               existing: Optional[str] = None, drop=frozenset()):
    if existing:
        _raw_copy_zip(existing, dest, drop)
    mode = "a" if existing else "w"
    comp = zipfile.ZIP_STORED if opts.level == 0 else zipfile.ZIP_DEFLATED
    lvl = _LV_DEFLATE[opts.level] if comp == zipfile.ZIP_DEFLATED else None
    aes = bool(opts.password)
    if aes:
        if pyzipper is None:
            raise ArchiveError("Password-protected ZIP files need the 'pyzipper' package.\n"
                               "Install it with:  pip install pyzipper\n(or choose the 7Z format.)")
        zf = pyzipper.AESZipFile(dest, mode, compression=comp, compresslevel=lvl, allowZip64=True,
                                 strict_timestamps=False, encryption=pyzipper.WZ_AES)
        zf.setpassword(opts.password.encode("utf-8"))
        zf.setencryption(pyzipper.WZ_AES, nbits=256)
    else:
        zf = zipfile.ZipFile(dest, mode, compression=comp, compresslevel=lvl, allowZip64=True,
                             strict_timestamps=False)
    with zf:
        for it in items:
            job.check()
            job.current = it.arc
            if it.is_dir:
                zf.write(it.path, it.arc)
            elif aes:
                zf.write(it.path, it.arc)
                job.advance(it.size)
            else:
                zi = zipfile.ZipInfo.from_file(it.path, it.arc, strict_timestamps=False)
                zi.compress_type = comp
                zi._compresslevel = lvl
                with open(it.path, "rb") as fin, zf.open(zi, "w", force_zip64=it.size > 0x7FFFFFFF) as fout:
                    while True:
                        b = fin.read(CHUNK)
                        if not b:
                            break
                        fout.write(b)
                        job.advance(len(b))
                        job.check()
            job.files_done += 1
        if opts.comment:
            zf.comment = opts.comment.encode("utf-8")[:65535]


def _write_tar(dest: str, items: List[Item], opts: AddOptions, job: Job, fmt: str,
               existing: Optional[str] = None, drop=frozenset()):
    mode = {"tar": "w", "tar.gz": "w:gz", "tar.bz2": "w:bz2", "tar.xz": "w:xz"}[fmt]
    kw = {}
    if fmt == "tar.gz":
        kw["compresslevel"] = _LV_DEFLATE[opts.level]
    elif fmt == "tar.bz2":
        kw["compresslevel"] = _LV_BZ2[opts.level]
    elif fmt == "tar.xz":
        kw["preset"] = _LV_XZ[opts.level]
    with tarfile.open(dest, mode, **kw) as tout:
        if existing:
            with tarfile.open(existing, "r:*") as tin:
                for ti in tin:
                    job.check()
                    if norm_name(ti.name) in drop:
                        continue
                    tout.addfile(ti, tin.extractfile(ti) if ti.isreg() else None)
        for it in items:
            job.check()
            job.current = it.arc
            ti = tout.gettarinfo(it.path, it.arc)
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = ""
            if ti.isreg():
                with open(it.path, "rb") as f:
                    tout.addfile(ti, _ProgressReader(f, job))
            else:
                tout.addfile(ti)
            job.files_done += 1


def _write_7z(dest: str, items: List[Item], opts: AddOptions, job: Job):
    if py7zr is None:
        raise ArchiveError("7Z support needs the 'py7zr' package.\nInstall it with:  pip install py7zr")
    lvl = _LV_7Z[opts.level]
    if lvl == 0:
        filters = [{"id": py7zr.FILTER_COPY}]
    else:
        filters = [{"id": py7zr.FILTER_LZMA2, "preset": lvl}]
    kw = {"filters": filters}
    if opts.password:
        kw["password"] = opts.password
        kw["header_encryption"] = bool(opts.encrypt_names)
    with py7zr.SevenZipFile(dest, "w", **kw) as z:
        for it in items:
            job.check()
            job.current = it.arc
            z.write(it.path, it.arc)
            job.advance(it.size)
            job.files_done += 1


def _filter_for_update(items: List[Item], existing: Dict[str, Optional[dt.datetime]], mode: str) -> List[Item]:
    if mode == "replace":
        return items
    out = []
    for it in items:
        known = existing.get(it.arc)
        if it.is_dir:
            if mode == "update" and it.arc not in existing:
                out.append(it)
            continue
        if it.arc not in existing:
            if mode == "update":
                out.append(it)
            continue
        try:
            newer = os.path.getmtime(it.path) > _ts(known) + 2 if known else True
        except OSError:
            newer = False
        if newer:
            out.append(it)
    return out


def _rebuild_via_temp(path: str, fmt: str, opts: AddOptions, job: Job, items: List[Item],
                      drop=frozenset(), password: Optional[str] = None):
    """For formats we cannot modify in place (7z, compressed tar): unpack, change, repack."""
    tmp = new_temp_dir("rebuild")
    arc = open_archive(path, password)
    try:
        sub = Job()
        arc.extract(tmp, None, sub)
    finally:
        arc.close()
    for name in drop:
        p = join_safe(tmp, name)
        if p and os.path.exists(p):
            shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)
    for it in items:
        target = join_safe(tmp, it.arc)
        if not target:
            continue
        if it.is_dir:
            os.makedirs(target, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(it.path, target)
    new_items = collect_items([os.path.join(tmp, n) for n in sorted(os.listdir(tmp))])
    job.total = sum(i.size for i in new_items)
    out = path + ".wa_tmp"
    try:
        if fmt == "7z":
            o = copy.copy(opts)
            o.password = opts.password or password
            _write_7z(out, new_items, o, job)
        else:
            _write_tar(out, new_items, opts, job, fmt)
        os.replace(out, path)
    finally:
        if os.path.exists(out):
            os.remove(out)
        shutil.rmtree(tmp, ignore_errors=True)


def build_archive(dest: str, sources: List[str], opts: AddOptions, job: Optional[Job] = None,
                  existing_password: Optional[str] = None) -> List[str]:
    """Create `dest` (or add to it when it already exists). Returns the files produced
    (several when split into volumes)."""
    job = job or Job()
    dest = os.path.abspath(dest)
    exists = os.path.isfile(dest)
    if exists:
        kind = detect_format(dest)
        if kind == "tar":
            fmt = tar_format_of(dest)
        elif kind in ("zip", "7z", "rar"):
            fmt = kind
        else:
            raise ArchiveError(f"Files cannot be added to this kind of archive ({kind or 'unknown'}).\n"
                               "Use ZIP, 7Z or TAR archives, or convert it first.")
    else:
        fmt = opts.fmt
    if fmt not in CREATE_FORMATS:
        raise ArchiveError(f"Unknown archive format: {fmt}")
    if opts.password and not supports_password(fmt):
        if fmt in ("zip", "7z"):
            raise ArchiveError(f"Passwords for {fmt.upper()} need an extra package:\n"
                               f"pip install {'pyzipper' if fmt == 'zip' else 'py7zr'}")
        raise ArchiveError(f"{FORMAT_LABEL[fmt]} archives cannot be password protected.\nChoose ZIP or 7Z.")

    items = collect_items(sources, opts.excludes, dest, opts.prefix, job)
    if fmt == "rar":
        return _build_rar_archive(dest, sources, items, opts, job, exists, existing_password)
    drop = set()
    old_entries: Dict[str, Optional[dt.datetime]] = {}
    if exists:
        try:
            a = open_archive(dest, existing_password)
            old_entries = {e.name: e.mtime for e in a.entries()}
            a.close()
        except PasswordRequired:
            raise
        except ArchiveError:
            old_entries = {}
        items = _filter_for_update(items, old_entries, opts.update_mode)
        drop = {it.arc for it in items if not it.is_dir and it.arc in old_entries}
    if not items:
        if exists:
            job.warnings.append("Nothing to update.")
            return [dest]
        raise ArchiveError("There is nothing to add - no files were found.")
    job.total = sum(i.size for i in items)
    job.files_total = sum(1 for i in items if not i.is_dir)
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    tmp = dest + ".wa_tmp"
    try:
        if fmt == "zip":
            _write_zip(tmp, items, opts, job, dest if exists else None, drop)
            os.replace(tmp, dest)
        elif fmt.startswith("tar"):
            if exists:
                _write_tar(tmp, items, opts, job, fmt, dest, drop)
                os.replace(tmp, dest)
            else:
                _write_tar(tmp, items, opts, job, fmt)
                os.replace(tmp, dest)
        else:  # 7z
            if exists:
                _rebuild_via_temp(dest, "7z", opts, job, items, drop, existing_password)
            else:
                _write_7z(tmp, items, opts, job)
                os.replace(tmp, dest)
    except BaseException:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        if not exists and os.path.exists(dest) and isinstance(sys.exc_info()[1], (Cancelled, ArchiveError)):
            try:
                os.remove(dest)
            except OSError:
                pass
        raise
    created = [dest]
    if opts.test_after and not opts.split_size:
        a = open_archive(dest, opts.password or existing_password)
        try:
            tj = Job()
            a.test(tj)
        finally:
            a.close()
        if tj.errors:
            raise ArchiveError("The new archive failed the integrity test:\n" + "\n".join(tj.errors[:5]))
    if opts.split_size and os.path.getsize(dest) > opts.split_size:
        created = split_file(dest, opts.split_size, job)
    if opts.delete_after:
        for s in sources:
            delete_path(s)
    return created


def delete_path(p: str):
    try:
        if os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(p)
        elif os.path.exists(p):
            os.remove(p)
    except OSError:
        pass


def delete_entries(path: str, names: Iterable[str], job: Optional[Job] = None, password: Optional[str] = None):
    """Remove files/folders from an existing archive (ZIP, TAR, 7Z)."""
    job = job or Job()
    if detect_format(path) == "rar":
        a = open_archive(path, password)
        try:
            names_to_drop = [e.name for e in select_entries(a.entries(), names)]
        finally:
            a.close()
        _rar_delete(path, names_to_drop, password, job)
        return
    arc = open_archive(path, password)
    kind = arc.kind
    try:
        drop = {e.name for e in select_entries(arc.entries(), names)}
    finally:
        arc.close()
    if not drop:
        return
    tmp = path + ".wa_tmp"
    try:
        if kind == "zip":
            _raw_copy_zip(path, tmp, frozenset(drop))
            os.replace(tmp, path)
        elif kind == "tar":
            mode = tar_write_mode(path)
            with tarfile.open(path, "r:*") as tin, tarfile.open(tmp, mode) as tout:
                for ti in tin:
                    job.check()
                    if norm_name(ti.name) in drop:
                        continue
                    tout.addfile(ti, tin.extractfile(ti) if ti.isreg() else None)
            os.replace(tmp, path)
        elif kind == "7z":
            _rebuild_via_temp(path, "7z", AddOptions(fmt="7z", password=password), job, [], drop, password)
        else:
            raise ArchiveError("Files cannot be deleted from this kind of archive.")
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


# ------------------------------------------------------------ RAR (via Rar.exe)
_NO_RAR = ("Creating RAR archives needs Rar.exe.\nCopy Rar.exe (plus rarreg.key and Default.SFX if you have them) "
           "into the 'tools' folder next to Wajeeha Archiver - see tools\\README.txt.")


def _rar_outputs(dest: str, opts: AddOptions, exists: bool) -> List[str]:
    base = os.path.splitext(dest)[0]
    if opts.sfx and not exists:
        for cand in (base + ".exe", dest):
            if os.path.isfile(cand):
                return [cand]
    if opts.split_size and not opts.sfx and not exists:
        parts = sorted(glob.glob(glob.escape(base) + ".part*.rar"))
        if parts:
            return parts
    return [dest]


def _build_rar_archive(dest, sources, items, opts, job, exists, existing_password):
    tool = find_rar()
    if not tool:
        raise ArchiveError(_NO_RAR)
    if not items:
        raise ArchiveError("There is nothing to add - no files were found.")
    job.total = sum(i.size for i in items)
    job.files_total = sum(1 for i in items if not i.is_dir) or 1
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    password = opts.password or existing_password
    cmd = {"replace": "a", "update": "u", "freshen": "f"}.get(opts.update_mode, "a") if exists else "a"
    sw = ["-y", "-r", f"-m{max(0, min(5, opts.level))}"]
    if opts.solid:
        sw.append("-s")
    if opts.recovery:
        sw.append("-rr")
    if password:
        sw.append(("-hp" if opts.encrypt_names else "-p") + password)
    if opts.prefix:
        sw.append("-ap" + norm_name(opts.prefix).replace("/", os.sep))
    for pat in opts.excludes:
        sw.append("-x" + pat)
    if not exists:
        if opts.sfx:
            sw.append("-sfx")
        elif opts.split_size:
            sw.append(f"-v{int(opts.split_size)}b")
    groups = {}
    for s_ in sources:
        s_ = os.path.abspath(s_).rstrip("\\/")
        base = os.path.basename(s_)
        if base:
            groups.setdefault(os.path.dirname(s_), []).append(base)

    def on_chunk(chunk):
        m = re.findall(rb"(?:Adding|Updating|Freshening)\s+(.+?)\s{2,}", chunk)
        if m:
            job.current = m[-1].decode("utf-8", "replace").strip()
        n = len(re.findall(rb"\bOK\b", chunk))
        if n:
            job.files_done += n
            job.done = int(job.total * min(1.0, job.files_done / job.files_total))
    ok_codes = (0, 1, 10) if cmd in ("u", "f") else (0, 1)
    try:
        for parent, names in groups.items():
            for i in range(0, len(names), 80):
                rc, text = _run_tool([tool, cmd] + sw + ["--", dest] + names[i:i + 80], cwd=parent, job=job,
                                     on_chunk=on_chunk)
                if rc not in ok_codes:
                    raise ArchiveError(f"Rar reported a problem (code {rc}):\n{_tool_tail(text)}")
    except BaseException:
        if not exists:
            for f in _rar_outputs(dest, opts, False) + [dest]:
                try:
                    if os.path.isfile(f):
                        os.remove(f)
                except OSError:
                    pass
        raise
    job.done = job.total
    created = _rar_outputs(dest, opts, exists)
    if opts.test_after and not (opts.split_size and not exists):
        pw = [f"-p{password}"] if password else []
        rc, text = _run_tool([tool, "t", "-y"] + pw + ["--", created[0]], job=job)
        if rc not in (0, 1):
            raise ArchiveError("The new archive failed the integrity test:\n" + _tool_tail(text))
    if opts.delete_after:
        for s_ in sources:
            delete_path(s_)
    return created


def _rar_delete(path, names, password, job):
    tool = find_rar()
    if not tool:
        raise ArchiveError("Deleting from RAR archives needs Rar.exe in the tools folder (see tools\\README.txt).")
    pw = [f"-p{password}"] if password else []
    for i in range(0, len(names), 100):
        batch = [n.replace("/", os.sep) for n in names[i:i + 100]]
        rc, text = _run_tool([tool, "d", "-y"] + pw + ["--", path] + batch, job=job)
        if rc not in (0, 1, 10):
            raise ArchiveError(f"Rar reported a problem (code {rc}):\n{_tool_tail(text)}")


def repair_rar(path: str, job: Optional[Job] = None) -> str:
    """Use Rar.exe's repair command. Returns the path of the repaired copy it writes next to the original."""
    tool = find_rar()
    if not tool:
        raise ArchiveError("Repairing RAR archives needs Rar.exe in the tools folder (see tools\\README.txt).")
    path = os.path.abspath(path)
    folder, base = os.path.dirname(path), os.path.basename(path)
    rc, text = _run_tool([tool, "r", "-y", path], cwd=folder, job=job)
    for prefix in ("fixed.", "rebuilt."):
        cand = os.path.join(folder, prefix + base)
        if os.path.isfile(cand):
            return cand
    raise ArchiveError("The repair did not produce a new archive:\n" + _tool_tail(text))


def set_zip_comment(path: str, text: str):
    tmp = path + ".wa_tmp"
    _raw_copy_zip(path, tmp)
    with zipfile.ZipFile(tmp, "a") as zf:
        zf.comment = text.encode("utf-8")[:65535]
    os.replace(tmp, path)


def convert_archive(src: str, dst: str, opts: AddOptions, password: Optional[str] = None,
                    job: Optional[Job] = None) -> List[str]:
    """Re-pack an archive into another format."""
    job = job or Job()
    tmp = new_temp_dir("convert")
    try:
        arc = open_archive(src, password)
        try:
            sub = Job()
            sub.cancelled = False
            arc.extract(tmp, None, sub)
            job.errors.extend(sub.errors)
        finally:
            arc.close()
        sources = [os.path.join(tmp, n) for n in sorted(os.listdir(tmp))]
        if os.path.exists(dst):
            os.remove(dst)
        return build_archive(dst, sources, opts, job)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _dos_datetime(d, t):
    try:
        y, mo, da = (d >> 9) + 1980, (d >> 5) & 15, d & 31
        h, mi, s = t >> 11, (t >> 5) & 63, (t & 31) * 2
        return (y, max(1, mo), max(1, da), min(h, 23), min(mi, 59), min(s, 59))
    except Exception:
        return (1980, 1, 1, 0, 0, 0)


def repair_zip(src: str, dst: str, job: Optional[Job] = None):
    """Rebuild a damaged ZIP by scanning for file headers.
    Returns (recovered_count, skipped_names)."""
    job = job or Job()
    recovered, skipped = 0, []
    size = os.path.getsize(src)
    job.total = max(size, 1)
    with open(src, "rb") as f:
        if size == 0:
            raise ArchiveError("The file is empty.")
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as out:
                pos = 0
                while True:
                    i = mm.find(b"PK\x03\x04", pos)
                    if i < 0 or i + 30 > size:
                        break
                    job.check()
                    job.done = i
                    (_s, _v, flag, comp, mtime, mdate, crc, csize, usize, nlen, elen) = \
                        struct.unpack("<4sHHHHHIIIHH", mm[i:i + 30])
                    name = bytes(mm[i + 30:i + 30 + nlen]).decode("utf-8" if flag & 0x800 else "cp437", "replace")
                    start = i + 30 + nlen + elen
                    pos = i + 4
                    job.current = name
                    if flag & 1:
                        skipped.append(name + " (encrypted)")
                        continue
                    try:
                        if comp == 0:
                            if flag & 8 and csize == 0 and not name.endswith("/"):
                                skipped.append(name)
                                continue
                            data = bytes(mm[start:start + csize])
                            if len(data) != csize:
                                raise EOFError
                            pos = start + csize
                        elif comp == 8:
                            d = zlib.decompressobj(-15)
                            parts = []
                            p = start
                            while not d.eof:
                                chunk = bytes(mm[p:p + 65536])
                                if not chunk:
                                    raise EOFError
                                parts.append(d.decompress(chunk))
                                p += len(chunk)
                            data = b"".join(parts)
                            pos = p - len(d.unused_data)
                        else:
                            skipped.append(name + " (unsupported method)")
                            continue
                    except (zlib.error, EOFError):
                        skipped.append(name)
                        continue
                    if not (flag & 8) and crc != (zlib.crc32(data) & 0xFFFFFFFF):
                        skipped.append(name + " (checksum)")
                        continue
                    zi = zipfile.ZipInfo(name, _dos_datetime(mdate, mtime))
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    if name.endswith("/"):
                        zi.external_attr = (0o40775 << 16) | 0x10
                    else:
                        zi.external_attr = 0o100644 << 16
                    out.writestr(zi, b"" if name.endswith("/") else data)
                    if not name.endswith("/"):
                        recovered += 1
        finally:
            mm.close()
    job.done = job.total
    if recovered == 0:
        try:
            os.remove(dst)
        except OSError:
            pass
        raise ArchiveError("No files could be recovered from this archive.")
    return recovered, skipped


def archive_info(arc: Archive) -> Dict[str, object]:
    ents = arc.entries()
    files = [e for e in ents if not e.is_dir]
    folders = {e.name for e in ents if e.is_dir}
    for e in ents:
        p = e.name.rpartition("/")[0]
        while p:
            folders.add(p)
            p = p.rpartition("/")[0]
    unpacked = sum(e.size for e in files)
    try:
        arch_size = os.path.getsize(arc.source_path)
        modified = dt.datetime.fromtimestamp(os.path.getmtime(arc.source_path))
    except OSError:
        arch_size, modified = 0, None
    return {
        "name": os.path.basename(arc.source_path), "path": os.path.dirname(arc.source_path),
        "format": arc.label, "size": arch_size, "files": len(files), "folders": len(folders),
        "unpacked": unpacked, "ratio": (arch_size / unpacked * 100) if unpacked else None,
        "encrypted": arc.encrypted, "comment": arc.comment(), "modified": modified,
    }
