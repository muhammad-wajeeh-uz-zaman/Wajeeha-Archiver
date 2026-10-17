# -*- coding: utf-8 -*-
"""Theme, helpers and dialogs for Wajeeha Archiver (Tkinter)."""
import datetime as dt
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk

from . import core, icons, shell
from .config import settings

# --------------------------------------------------------------------- theme
LIGHT = dict(
    bg="#F2F4F9", panel="#FFFFFF", fg="#1E2330", muted="#6C7388", accent="#4F6BED", accent_hi="#6B84F5",
    accent_fg="#FFFFFF", border="#D6DAE6", row_alt="#F7F8FC", head_bg="#E9ECF5", sel="#DCE3FF",
    sel_fg="#1E2330", toolbar="#FFFFFF", hover="#E8ECFA", danger="#D64545", input_bg="#FFFFFF",
    icon_fg=(84, 90, 112, 255),
)
DARK = dict(
    bg="#161922", panel="#1D212C", fg="#E7E9F1", muted="#8C93A8", accent="#6C86FF", accent_hi="#869CFF",
    accent_fg="#FFFFFF", border="#2D3242", row_alt="#212633", head_bg="#262B39", sel="#34417F",
    sel_fg="#FFFFFF", toolbar="#1D212C", hover="#2B3042", danger="#FF6B6B", input_bg="#252A38",
    icon_fg=(214, 219, 236, 255),
)
THEME = dict(LIGHT)
SCALE = 1.0
_ROOT = None
_IMG = {}


def apply_theme(root, mode=None):
    """Configure ttk styles for the light or dark palette."""
    global _ROOT, SCALE
    _ROOT = root
    mode = mode or settings["theme"]
    THEME.clear()
    THEME.update(DARK if mode == "dark" else LIGHT)
    c = THEME
    try:
        SCALE = max(1.0, root.winfo_fpixels("1i") / 96.0)
    except tk.TclError:
        SCALE = 1.0
    _IMG.clear()
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    try:
        fam = "Segoe UI" if "Segoe UI" in set(tkfont.families(root)) else tkfont.nametofont("TkDefaultFont").actual("family")
        for nm in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont",
                   "TkSmallCaptionFont", "TkTooltipFont"):
            tkfont.nametofont(nm).configure(family=fam, size=10)
    except tk.TclError:
        pass
    root.configure(bg=c["bg"])
    cfg, mp = st.configure, st.map
    cfg(".", background=c["bg"], foreground=c["fg"], fieldbackground=c["input_bg"], bordercolor=c["border"],
        lightcolor=c["border"], darkcolor=c["border"], troughcolor=c["head_bg"], focuscolor=c["accent"],
        selectbackground=c["sel"], selectforeground=c["sel_fg"], insertcolor=c["fg"])
    cfg("TFrame", background=c["bg"])
    cfg("Panel.TFrame", background=c["panel"])
    cfg("Toolbar.TFrame", background=c["toolbar"])
    cfg("TLabel", background=c["bg"], foreground=c["fg"])
    cfg("Panel.TLabel", background=c["panel"], foreground=c["fg"])
    cfg("Muted.TLabel", background=c["bg"], foreground=c["muted"])
    cfg("Title.TLabel", background=c["bg"], foreground=c["fg"], font=(tkfont.nametofont("TkDefaultFont").actual("family"), 15, "bold"))
    cfg("Status.TLabel", background=c["head_bg"], foreground=c["muted"], padding=(10, 4))
    cfg("TSeparator", background=c["border"])
    cfg("TButton", background=c["head_bg"], foreground=c["fg"], bordercolor=c["border"], lightcolor=c["head_bg"],
        darkcolor=c["head_bg"], padding=(14, 6), relief="flat", focusthickness=0, anchor="center")
    mp("TButton", background=[("disabled", c["bg"]), ("pressed", c["sel"]), ("active", c["hover"])],
       foreground=[("disabled", c["muted"])], bordercolor=[("focus", c["accent"])])
    cfg("Accent.TButton", background=c["accent"], foreground=c["accent_fg"], bordercolor=c["accent"],
        lightcolor=c["accent"], darkcolor=c["accent"], padding=(18, 6))
    mp("Accent.TButton", background=[("disabled", c["border"]), ("pressed", c["accent"]), ("active", c["accent_hi"])],
       foreground=[("disabled", c["muted"])])
    cfg("Tool.TButton", background=c["toolbar"], foreground=c["fg"], bordercolor=c["toolbar"],
        lightcolor=c["toolbar"], darkcolor=c["toolbar"], padding=(8, 6), relief="flat", focusthickness=0)
    mp("Tool.TButton", background=[("disabled", c["toolbar"]), ("pressed", c["sel"]), ("active", c["hover"])],
       foreground=[("disabled", c["muted"])], bordercolor=[("active", c["hover"]), ("pressed", c["sel"])])
    cfg("Nav.TButton", background=c["panel"], foreground=c["fg"], bordercolor=c["panel"], lightcolor=c["panel"],
        darkcolor=c["panel"], padding=(6, 4), relief="flat", focusthickness=0)
    mp("Nav.TButton", background=[("disabled", c["panel"]), ("pressed", c["sel"]), ("active", c["hover"])])
    for w in ("TEntry", "TCombobox", "TSpinbox"):
        cfg(w, fieldbackground=c["input_bg"], foreground=c["fg"], bordercolor=c["border"], lightcolor=c["input_bg"],
            darkcolor=c["input_bg"], padding=5, insertcolor=c["fg"], arrowcolor=c["muted"])
        mp(w, bordercolor=[("focus", c["accent"])], lightcolor=[("focus", c["accent"])],
           darkcolor=[("focus", c["accent"])], fieldbackground=[("readonly", c["input_bg"]), ("disabled", c["bg"])],
           foreground=[("disabled", c["muted"])], selectbackground=[("readonly", c["input_bg"])],
           selectforeground=[("readonly", c["fg"])])
    for w in ("TCheckbutton", "TRadiobutton"):
        cfg(w, background=c["bg"], foreground=c["fg"], focuscolor=c["bg"], indicatorbackground=c["input_bg"],
            indicatorforeground=c["accent"], padding=3)
        mp(w, background=[("active", c["bg"])], foreground=[("disabled", c["muted"])],
           indicatorbackground=[("selected", c["input_bg"]), ("disabled", c["bg"])])
    cfg("TLabelframe", background=c["bg"], bordercolor=c["border"], relief="solid", borderwidth=1)
    cfg("TLabelframe.Label", background=c["bg"], foreground=c["muted"])
    cfg("TNotebook", background=c["bg"], bordercolor=c["border"], tabmargins=(0, 4, 0, 0))
    cfg("TNotebook.Tab", background=c["head_bg"], foreground=c["muted"], padding=(16, 7), bordercolor=c["border"])
    mp("TNotebook.Tab", background=[("selected", c["panel"]), ("active", c["hover"])],
       foreground=[("selected", c["fg"])])
    cfg("TProgressbar", background=c["accent"], troughcolor=c["head_bg"], bordercolor=c["head_bg"],
        lightcolor=c["accent"], darkcolor=c["accent"], thickness=int(14 * SCALE))
    for orient in ("Vertical", "Horizontal"):
        cfg(f"{orient}.TScrollbar", background=c["border"], troughcolor=c["bg"], bordercolor=c["bg"],
            arrowcolor=c["muted"], lightcolor=c["border"], darkcolor=c["border"], relief="flat")
        mp(f"{orient}.TScrollbar", background=[("active", c["muted"])])
    cfg("Treeview", background=c["panel"], fieldbackground=c["panel"], foreground=c["fg"], borderwidth=0,
        rowheight=int(26 * SCALE), relief="flat")
    mp("Treeview", background=_fixed_map(st, "background") + [("selected", c["sel"])],
       foreground=_fixed_map(st, "foreground") + [("selected", c["sel_fg"])])
    cfg("Treeview.Heading", background=c["head_bg"], foreground=c["fg"], relief="flat", padding=(8, 6),
        bordercolor=c["border"], lightcolor=c["head_bg"], darkcolor=c["head_bg"])
    mp("Treeview.Heading", background=[("active", c["hover"])])
    cfg("TMenubutton", background=c["head_bg"], foreground=c["fg"], padding=(10, 5))
    for opt, val in (("*Menu.background", c["panel"]), ("*Menu.foreground", c["fg"]),
                     ("*Menu.activeBackground", c["accent"]), ("*Menu.activeForeground", c["accent_fg"]),
                     ("*Menu.relief", "flat"), ("*Menu.borderWidth", 1), ("*Menu.activeBorderWidth", 0),
                     ("*TCombobox*Listbox.background", c["input_bg"]), ("*TCombobox*Listbox.foreground", c["fg"]),
                     ("*TCombobox*Listbox.selectBackground", c["accent"]),
                     ("*TCombobox*Listbox.selectForeground", c["accent_fg"]),
                     ("*Listbox.background", c["input_bg"]), ("*Listbox.foreground", c["fg"]),
                     ("*Listbox.selectBackground", c["accent"]), ("*Listbox.selectForeground", c["accent_fg"])):
        root.option_add(opt, val)


def _fixed_map(style, option):
    # workaround for the Tk 8.6.9 Treeview tag-colour bug
    try:
        return [e for e in style.map("Treeview", query_opt=option) if e[:2] != ("!disabled", "!selected")]
    except Exception:
        return []


def get_image(name, size, gray=False):
    """Cached tk.PhotoImage for an icon at `size` design-pixels (scaled for the screen)."""
    px = max(8, int(round(size * SCALE)))
    key = (name, px, gray)
    img = _IMG.get(key)
    if img is None:
        img = tk.PhotoImage(master=_ROOT, data=icons.render_b64(name, px, THEME["icon_fg"], gray))
        _IMG[key] = img
    return img


def set_window_icon(win):
    try:
        win.iconphoto(False, get_image("app", 32), get_image("app", 64))
    except tk.TclError:
        pass


def make_text(parent, **kw):
    t = tk.Text(parent, bg=THEME["input_bg"], fg=THEME["fg"], insertbackground=THEME["fg"], relief="flat",
                highlightthickness=1, highlightbackground=THEME["border"], highlightcolor=THEME["accent"],
                selectbackground=THEME["sel"], selectforeground=THEME["sel_fg"], padx=8, pady=6, **kw)
    return t


# ------------------------------------------------------------- misc helpers
FILE_KINDS = {
    "archive": {".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".tbz2", ".xz", ".txz", ".iso", ".cab",
                ".001", ".arj", ".lzh", ".wim", ".jar", ".apk"},
    "image": {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico", ".tif", ".tiff", ".heic"},
    "audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"},
    "video": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".flv", ".m4v"},
    "text": {".txt", ".md", ".log", ".csv", ".rtf", ".doc", ".docx", ".odt", ".xls", ".xlsx", ".ppt", ".pptx",
             ".ini", ".cfg"},
    "code": {".py", ".js", ".ts", ".html", ".htm", ".css", ".json", ".xml", ".java", ".c", ".cpp", ".h", ".cs",
             ".go", ".rs", ".php", ".sh", ".bat", ".yml", ".yaml", ".sql", ".pyw"},
    "exe": {".exe", ".msi", ".dll", ".sys", ".com", ".scr"},
    "pdf": {".pdf"},
}
TEXT_EXTS = FILE_KINDS["text"] | FILE_KINDS["code"] | {".md", ".log", ".csv", ".ini", ".cfg", ".txt", ".tsv"}


def file_kind(name):
    ext = os.path.splitext(name.lower())[1]
    for kind, exts in FILE_KINDS.items():
        if ext in exts:
            return kind
    return "file"


def type_name(name, is_dir):
    if is_dir:
        return "File folder"
    ext = os.path.splitext(name)[1].lstrip(".").upper()
    if core.is_archive_name(name):
        return f"{ext or 'Archive'} archive"
    return f"{ext} file" if ext else "File"


def fmt_dt(d):
    if not d:
        return ""
    try:
        return d.strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError):
        return ""


def open_with_default(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception as e:
        messagebox.showerror(core.APP_NAME, f"Could not open:\n{path}\n\n{e}")
        return False


def reveal_folder(path):
    if sys.platform.startswith("win"):
        try:
            os.startfile(path)  # noqa
        except Exception:
            pass
    else:
        open_with_default(path)


def ask_folder(parent, initial=None, title="Choose a folder"):
    return filedialog.askdirectory(parent=parent, initialdir=initial or os.path.expanduser("~"), title=title,
                                   mustexist=False) or None


# -------------------------------------------------------------------- Dialog
class Dialog(tk.Toplevel):
    def __init__(self, parent, title, resizable=False):
        super().__init__(parent)
        self.withdraw()
        self._parent = parent
        self.result = None
        self.title(title)
        self.configure(bg=THEME["bg"])
        self.resizable(resizable, resizable)
        try:
            if parent is not None and parent.winfo_viewable():
                self.transient(parent)
        except tk.TclError:
            pass
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Escape>", lambda e: self.cancel())
        set_window_icon(self)

    def show(self):
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        p = self._parent
        try:
            if p is not None and p.winfo_viewable():
                x = p.winfo_rootx() + (p.winfo_width() - w) // 2
                y = p.winfo_rooty() + (p.winfo_height() - h) // 3
            else:
                x = (self.winfo_screenwidth() - w) // 2
                y = (self.winfo_screenheight() - h) // 3
        except tk.TclError:
            x = y = 100
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.deiconify()
        try:
            self.wait_visibility()
            self.grab_set()
        except tk.TclError:
            pass
        self.lift()
        try:
            if p is None or not p.winfo_viewable():      # launched from Explorer: come to the front
                self.attributes("-topmost", True)
                self.after(500, lambda: self.attributes("-topmost", False))
        except tk.TclError:
            pass
        self.focus_force()
        self.wait_window(self)
        return self.result

    def finish(self, result=True):
        self.result = result
        self.destroy()

    def cancel(self):
        self.result = None
        self.destroy()

    def buttons(self, parent, items):
        """items: [(text, command, accent?)] - right aligned row."""
        row = ttk.Frame(parent)
        for text, cmd, accent in reversed(items):
            b = ttk.Button(row, text=text, command=cmd, style="Accent.TButton" if accent else "TButton")
            b.pack(side="right", padx=(8, 0))
        return row


def info_box(parent, title, text):
    messagebox.showinfo(title, text, parent=parent)


def error_box(parent, text, title=core.APP_NAME):
    messagebox.showerror(title, text, parent=parent)


# --------------------------------------------------------- password dialog
class PasswordDialog(Dialog):
    def __init__(self, parent, name, wrong=False):
        super().__init__(parent, "Password required")
        f = ttk.Frame(self, padding=20)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="This archive is password protected", style="Title.TLabel").pack(anchor="w")
        ttk.Label(f, text=name, style="Muted.TLabel", wraplength=380).pack(anchor="w", pady=(2, 10))
        if wrong:
            ttk.Label(f, text="That password was not accepted. Please try again.",
                      foreground=THEME["danger"]).pack(anchor="w", pady=(0, 6))
        self.var = tk.StringVar()
        self.entry = ttk.Entry(f, textvariable=self.var, show="\u2022", width=44)
        self.entry.pack(fill="x")
        self.show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="Show password", variable=self.show_var, command=self._toggle).pack(anchor="w", pady=6)
        self.buttons(f, [("OK", self.ok, True), ("Cancel", self.cancel, False)]).pack(fill="x", pady=(10, 0))
        self.bind("<Return>", lambda e: self.ok())
        self.entry.focus_set()

    def _toggle(self):
        self.entry.configure(show="" if self.show_var.get() else "\u2022")

    def ok(self):
        if self.var.get():
            self.finish(self.var.get())


# -------------------------------------------------------- overwrite dialog
class OverwriteDialog(Dialog):
    def __init__(self, parent, path, new_size, new_mtime):
        super().__init__(parent, "File already exists")
        f = ttk.Frame(self, padding=20)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="This file already exists in the destination folder", style="Title.TLabel").pack(anchor="w")
        ttk.Label(f, text=path, style="Muted.TLabel", wraplength=480).pack(anchor="w", pady=(4, 12))
        try:
            st = os.stat(path)
            old = f"{core.human_size(st.st_size)}   {fmt_dt(dt.datetime.fromtimestamp(st.st_mtime))}"
        except OSError:
            old = "?"
        new = f"{core.human_size(new_size)}   {fmt_dt(new_mtime)}"
        grid = ttk.Frame(f)
        grid.pack(fill="x")
        ttk.Label(grid, text="Existing file:", style="Muted.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Label(grid, text=old).grid(row=0, column=1, sticky="w")
        ttk.Label(grid, text="New file:", style="Muted.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=3)
        ttk.Label(grid, text=new).grid(row=1, column=1, sticky="w")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(18, 0))
        for text, code, accent in (("Replace", "yes", True), ("Replace all", "yes_all", False), ("Skip", "no", False),
                                   ("Skip all", "no_all", False), ("Keep both", "rename", False),
                                   ("Cancel", "cancel", False)):
            ttk.Button(row, text=text, style="Accent.TButton" if accent else "TButton",
                       command=lambda c=code: self.finish(c)).pack(side="left", padx=(0, 6))
        self.protocol("WM_DELETE_WINDOW", lambda: self.finish("cancel"))
        self.bind("<Escape>", lambda e: self.finish("cancel"))


# ----------------------------------------------------------- progress dialog
class ProgressDialog(Dialog):
    def __init__(self, parent, title, job, func):
        super().__init__(parent, title)
        self.job, self.func = job, func
        self.value, self.exc = None, None
        self._done = False
        self._requests = queue.Queue()
        self._t0 = time.time()
        self._indet = False
        f = ttk.Frame(self, padding=22)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=title, style="Title.TLabel").pack(anchor="w")
        self.file_lbl = ttk.Label(f, text="Preparing...", style="Muted.TLabel", width=62)
        self.file_lbl.pack(anchor="w", pady=(6, 10))
        self.bar = ttk.Progressbar(f, mode="determinate", maximum=1000, length=int(460 * SCALE))
        self.bar.pack(fill="x")
        self.stats = ttk.Label(f, text="", style="Muted.TLabel")
        self.stats.pack(anchor="w", pady=(8, 0))
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(16, 0))
        self.cancel_btn = ttk.Button(row, text="Cancel", command=self.cancel)
        self.cancel_btn.pack(side="right")

    # called from the worker thread
    def call_main(self, fn, *args):
        ev, box = threading.Event(), {}
        self._requests.put((fn, args, box, ev))
        ev.wait()
        if "exc" in box:
            raise box["exc"]
        return box.get("res")

    def _work(self):
        try:
            self.value = self.func(self.job, self)
        except BaseException as e:  # noqa
            self.exc = e
        finally:
            self._done = True

    def run(self):
        threading.Thread(target=self._work, daemon=True).start()
        self.after(40, self._poll)
        self.show()
        return self.value, self.exc

    def cancel(self):
        self.job.cancel()
        try:
            self.cancel_btn.configure(state="disabled")
            self.file_lbl.configure(text="Cancelling...")
        except tk.TclError:
            pass

    def _poll(self):
        while True:
            try:
                fn, args, box, ev = self._requests.get_nowait()
            except queue.Empty:
                break
            try:
                box["res"] = fn(*args)
            except BaseException as e:  # noqa
                box["exc"] = e
            ev.set()
        if self._done and self._requests.empty():
            self.destroy()
            return
        j = self.job
        elapsed = max(time.time() - self._t0, 0.001)
        try:
            if j.current and not j.cancelled:
                name = j.current if len(j.current) < 70 else "..." + j.current[-67:]
                self.file_lbl.configure(text=name)
            if j.total > 0:
                if self._indet:
                    self.bar.stop()
                    self.bar.configure(mode="determinate")
                    self._indet = False
                frac = min(0.999, j.done / j.total) if not self._done else 1.0
                self.bar["value"] = frac * 1000
                speed = j.done / elapsed
                remain = (j.total - j.done) / speed if speed > 0 else 0
                self.stats.configure(text=f"{int(frac * 100)}%    {core.human_size(speed)}/s    "
                                          f"elapsed {core.fmt_time(elapsed)}    remaining {core.fmt_time(remain)}")
            else:
                if not self._indet:
                    self.bar.configure(mode="indeterminate")
                    self.bar.start(14)
                    self._indet = True
                self.stats.configure(text=f"elapsed {core.fmt_time(elapsed)}")
        except tk.TclError:
            return
        self.after(80, self._poll)


def run_job(parent, title, func):
    """Run func(job, dialog) in a worker thread behind a progress window.
    Returns (value, exception)."""
    job = core.Job()
    return ProgressDialog(parent, title, job, func).run() + (job,)


# ------------------------------------------------------------ report dialog
class ReportDialog(Dialog):
    def __init__(self, parent, title, summary, lines):
        super().__init__(parent, title, resizable=True)
        f = ttk.Frame(self, padding=18)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=summary, style="Title.TLabel", wraplength=560).pack(anchor="w", pady=(0, 8))
        self.buttons(f, [("Close", self.cancel, True)]).pack(fill="x", side="bottom", pady=(12, 0))
        box = ttk.Frame(f)
        box.pack(fill="both", expand=True)
        t = make_text(box, width=72, height=12, wrap="none")
        sb = ttk.Scrollbar(box, command=t.yview)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)
        t.insert("1.0", "\n".join(lines))
        t.configure(state="disabled")


# --------------------------------------------------------------- info dialog
class InfoDialog(Dialog):
    def __init__(self, parent, info):
        super().__init__(parent, "Archive information")
        f = ttk.Frame(self, padding=22)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=info["name"], style="Title.TLabel", wraplength=460).pack(anchor="w")
        ttk.Label(f, text=info["path"], style="Muted.TLabel", wraplength=460).pack(anchor="w", pady=(2, 12))
        g = ttk.Frame(f)
        g.pack(fill="x")
        ratio = f"{info['ratio']:.0f}%" if info["ratio"] is not None else "-"
        rows = [("Format", info["format"]), ("Archive size", core.human_size(info["size"])),
                ("Files", f"{info['files']:,}"), ("Folders", f"{info['folders']:,}"),
                ("Unpacked size", core.human_size(info["unpacked"])), ("Compression ratio", ratio),
                ("Password protected", "Yes" if info["encrypted"] else "No"),
                ("Last modified", fmt_dt(info["modified"]))]
        for i, (k, v) in enumerate(rows):
            ttk.Label(g, text=k, style="Muted.TLabel").grid(row=i, column=0, sticky="w", padx=(0, 24), pady=2)
            ttk.Label(g, text=v).grid(row=i, column=1, sticky="w", pady=2)
        if info["comment"]:
            ttk.Label(f, text="Comment", style="Muted.TLabel").pack(anchor="w", pady=(12, 2))
            t = make_text(f, width=56, height=4, wrap="word")
            t.insert("1.0", info["comment"])
            t.configure(state="disabled")
            t.pack(fill="x")
        self.buttons(f, [("Close", self.cancel, True)]).pack(fill="x", pady=(16, 0))


# --------------------------------------------------------------- find dialog
class FindDialog(Dialog):
    def __init__(self, parent, last=""):
        super().__init__(parent, "Find files")
        f = ttk.Frame(self, padding=20)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="File name contains (wildcards * and ? allowed)").pack(anchor="w")
        self.var = tk.StringVar(value=last)
        e = ttk.Entry(f, textvariable=self.var, width=48)
        e.pack(fill="x", pady=(4, 8))
        self.whole = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="Search the whole archive (not just this folder)", variable=self.whole).pack(anchor="w")
        self.buttons(f, [("Find", self.ok, True), ("Cancel", self.cancel, False)]).pack(fill="x", pady=(14, 0))
        self.bind("<Return>", lambda ev: self.ok())
        e.focus_set()
        e.select_range(0, "end")

    def ok(self):
        if self.var.get().strip():
            self.finish((self.var.get().strip(), self.whole.get()))


# ------------------------------------------------------------ comment dialog
class CommentDialog(Dialog):
    def __init__(self, parent, text, editable):
        super().__init__(parent, "Archive comment", resizable=True)
        self.editable = editable
        f = ttk.Frame(self, padding=18)
        f.pack(fill="both", expand=True)
        items = [("Save", self.ok, True), ("Cancel", self.cancel, False)] if editable else [("Close", self.cancel, True)]
        self.buttons(f, items).pack(fill="x", side="bottom", pady=(12, 0))
        if not editable:
            ttk.Label(f, text="Comments can be edited in ZIP archives only.", style="Muted.TLabel").pack(anchor="w", pady=(0, 6))
        self.t = make_text(f, width=64, height=12, wrap="word")
        self.t.pack(fill="both", expand=True)
        self.t.insert("1.0", text)
        if not editable:
            self.t.configure(state="disabled")

    def ok(self):
        self.finish(self.t.get("1.0", "end").rstrip("\n"))


# --------------------------------------------------------------- text viewer
class TextViewer(Dialog):
    def __init__(self, parent, title, text, open_cb=None):
        super().__init__(parent, title, resizable=True)
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        items = [("Close", self.cancel, True)]
        if open_cb:
            items.insert(0, ("Open with default app", open_cb, False))
        self.buttons(f, items).pack(fill="x", side="bottom", pady=(10, 0))
        xs = ttk.Scrollbar(f, orient="horizontal")
        xs.pack(fill="x", side="bottom")
        box = ttk.Frame(f)
        box.pack(fill="both", expand=True)
        self.t = make_text(box, width=96, height=30, wrap="none", font=tkfont.nametofont("TkFixedFont"))
        ys = ttk.Scrollbar(box, command=self.t.yview)
        xs.configure(command=self.t.xview)
        self.t.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        ys.pack(side="right", fill="y")
        self.t.pack(side="left", fill="both", expand=True)
        self.t.insert("1.0", text)
        self.t.configure(state="disabled")


# ------------------------------------------------------------ folder tree
class FolderTree(ttk.Frame):
    """Lazy-loading folder picker (like a classic 'choose destination' tree)."""

    def __init__(self, parent, on_pick, height=14):
        super().__init__(parent)
        self.on_pick = on_pick
        self._paths = {}
        self._quiet = False
        self.tree = ttk.Treeview(self, show="tree", height=height, selectmode="browse")
        sb = ttk.Scrollbar(self, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewOpen>>", self._on_open)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        home = os.path.expanduser("~")
        for label in ("Desktop", "Documents", "Downloads"):
            p = os.path.join(home, label)
            if os.path.isdir(p):
                self._add_node("", label, p)
        for d in self._drives():
            self._add_node("", d, d)

    @staticmethod
    def _drives():
        if os.name == "nt":
            try:
                import ctypes
                mask = ctypes.windll.kernel32.GetLogicalDrives()
                return [f"{chr(65 + i)}:\\" for i in range(26) if mask & (1 << i)]
            except Exception:
                return ["C:\\"]
        return ["/"]

    def _add_node(self, parent, label, path):
        iid = self.tree.insert(parent, "end", text=label)
        self._paths[iid] = path
        self.tree.insert(iid, "end", text="...")
        return iid

    def _on_open(self, _e):
        iid = self.tree.focus()
        kids = self.tree.get_children(iid)
        if len(kids) == 1 and self.tree.item(kids[0], "text") == "...":
            self.tree.delete(kids[0])
            base = self._paths.get(iid, "")
            try:
                names = sorted((e.name for e in os.scandir(base) if e.is_dir(follow_symlinks=False)), key=str.lower)
            except OSError:
                names = []
            for n in names:
                if n.startswith(".") or n.startswith("$"):
                    continue
                self._add_node(iid, n, os.path.join(base, n))

    def _on_select(self, _e):
        sel = self.tree.selection()
        if sel and not self._quiet:
            self.on_pick(self._paths.get(sel[0], ""))


# --------------------------------------------------------------- add dialog
SPLIT_UNITS = {"KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}


class AddDialog(Dialog):
    def __init__(self, parent, sources, dest_dir=None, default_stem=None, title="Add to archive"):
        super().__init__(parent, title)
        self.sources = list(sources)
        dest_dir = dest_dir or os.path.dirname(os.path.abspath(self.sources[0]))
        if default_stem is None:
            if len(self.sources) == 1:
                p = os.path.abspath(self.sources[0])
                default_stem = os.path.splitext(os.path.basename(p))[0] if os.path.isfile(p) else os.path.basename(p)
            else:
                default_stem = os.path.basename(dest_dir.rstrip("\\/")) or "Archive"
        fmt = settings["default_format"] if settings["default_format"] in core.CREATE_FORMATS else "zip"
        if not core.can_create(fmt):
            fmt = "zip"
        self.fmt_var = tk.StringVar(value=fmt)
        self.name_var = tk.StringVar(value=os.path.join(dest_dir, default_stem + core.FORMAT_EXT[fmt]))
        self.level_var = tk.StringVar(value=core.LEVEL_NAMES[int(settings["default_level"])])
        self.update_var = tk.StringVar(value=core.UPDATE_MODES[0][1])
        self.delete_var = tk.BooleanVar(value=False)
        self.test_var = tk.BooleanVar(value=False)
        self.split_var = tk.StringVar()
        self.unit_var = tk.StringVar(value="MB")
        self.pw_var, self.pw2_var = tk.StringVar(), tk.StringVar()
        self.show_var = tk.BooleanVar(value=False)
        self.names_var = tk.BooleanVar(value=False)
        self.excl_var = tk.StringVar()
        self.solid_var, self.rr_var, self.sfx_var = tk.BooleanVar(), tk.BooleanVar(), tk.BooleanVar()

        outer = ttk.Frame(self, padding=(18, 16, 18, 14))
        outer.pack(fill="both", expand=True)
        top = ttk.Frame(outer)
        top.pack(fill="x")
        ttk.Label(top, text="Archive name").pack(anchor="w")
        row = ttk.Frame(top)
        row.pack(fill="x", pady=(4, 0))
        ttk.Entry(row, textvariable=self.name_var, width=70).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse...", command=self._browse).pack(side="left", padx=(8, 0))
        self.exists_lbl = ttk.Label(top, text="", style="Muted.TLabel")
        self.exists_lbl.pack(anchor="w", pady=(4, 0))

        nb = ttk.Notebook(outer)
        nb.pack(fill="both", expand=True, pady=(10, 0))
        self.nb = nb
        self._tab_general(nb)
        self._tab_password(nb)
        self._tab_advanced(nb)
        self._tab_comment(nb)
        self._tab_files(nb)

        self.buttons(outer, [("OK", self.ok, True), ("Cancel", self.cancel, False)]).pack(fill="x", pady=(14, 0))
        self.bind("<Return>", lambda e: None if (self.focus_get() is not None and
                                                 self.focus_get().winfo_class() == "Text") else self.ok())
        self.name_var.trace_add("write", lambda *a: self._refresh())
        self._refresh()

    # ---- tabs
    def _tab_general(self, nb):
        t = ttk.Frame(nb, padding=16)
        nb.add(t, text="General")
        left = ttk.LabelFrame(t, text="  Format  ", padding=12)
        left.grid(row=0, column=0, sticky="nsw")
        for i, f in enumerate(core.CREATE_FORMATS):
            label = core.FORMAT_LABEL[f] + ("" if core.can_create(f) else "  (" + core.NEEDS.get(f, "unavailable") + ")")
            rb = ttk.Radiobutton(left, text=label, value=f, variable=self.fmt_var, command=self._fmt_changed)
            if not core.can_create(f):
                rb.state(["disabled"])
            rb.grid(row=i, column=0, sticky="w", pady=2)
        right = ttk.Frame(t)
        right.grid(row=0, column=1, sticky="nsew", padx=(24, 0))
        t.columnconfigure(1, weight=1)
        ttk.Label(right, text="Compression").grid(row=0, column=0, sticky="w")
        ttk.Combobox(right, textvariable=self.level_var, values=core.LEVEL_NAMES, state="readonly",
                     width=26).grid(row=1, column=0, sticky="w", pady=(2, 10))
        ttk.Label(right, text="If the archive already exists").grid(row=2, column=0, sticky="w")
        ttk.Combobox(right, textvariable=self.update_var, values=[n for _k, n in core.UPDATE_MODES],
                     state="readonly", width=34).grid(row=3, column=0, sticky="w", pady=(2, 10))
        ttk.Checkbutton(right, text="Delete original files after archiving", variable=self.delete_var).grid(row=4, column=0, sticky="w")
        ttk.Checkbutton(right, text="Test the archive when finished", variable=self.test_var).grid(row=5, column=0, sticky="w")
        sp = ttk.Frame(right)
        sp.grid(row=6, column=0, sticky="w", pady=(10, 0))
        ttk.Label(sp, text="Split into parts of").pack(side="left")
        ttk.Entry(sp, textvariable=self.split_var, width=7).pack(side="left", padx=6)
        ttk.Combobox(sp, textvariable=self.unit_var, values=list(SPLIT_UNITS), state="readonly", width=4).pack(side="left")
        self.hint = ttk.Label(t, text="", style="Muted.TLabel", wraplength=int(560 * SCALE))
        self.hint.grid(row=1, column=0, columnspan=2, sticky="w", pady=(14, 0))

    def _tab_password(self, nb):
        t = ttk.Frame(nb, padding=16)
        nb.add(t, text="Password")
        ttk.Label(t, text="Password (leave empty for no protection)").grid(row=0, column=0, sticky="w")
        self.pw_entry = ttk.Entry(t, textvariable=self.pw_var, show="\u2022", width=40)
        self.pw_entry.grid(row=1, column=0, sticky="w", pady=(2, 8))
        ttk.Label(t, text="Repeat password").grid(row=2, column=0, sticky="w")
        self.pw2_entry = ttk.Entry(t, textvariable=self.pw2_var, show="\u2022", width=40)
        self.pw2_entry.grid(row=3, column=0, sticky="w", pady=(2, 8))
        ttk.Checkbutton(t, text="Show password", variable=self.show_var, command=self._toggle_pw).grid(row=4, column=0, sticky="w")
        self.names_cb = ttk.Checkbutton(t, text="Also hide file names (7Z and RAR)", variable=self.names_var)
        self.names_cb.grid(row=5, column=0, sticky="w", pady=(6, 0))
        self.pw_note = ttk.Label(t, text="", style="Muted.TLabel", wraplength=int(520 * SCALE))
        self.pw_note.grid(row=6, column=0, sticky="w", pady=(12, 0))

    def _tab_advanced(self, nb):
        t = ttk.Frame(nb, padding=16)
        nb.add(t, text="Advanced")
        ttk.Label(t, text="Skip files matching these patterns (separate with ;)").grid(row=0, column=0, sticky="w")
        ttk.Entry(t, textvariable=self.excl_var, width=56).grid(row=1, column=0, sticky="w", pady=(2, 4))
        ttk.Label(t, text="Example:  *.tmp; Thumbs.db; node_modules", style="Muted.TLabel").grid(row=2, column=0, sticky="w")
        box = ttk.LabelFrame(t, text="  RAR options  ", padding=10)
        box.grid(row=3, column=0, sticky="w", pady=(16, 0))
        self.rar_cbs = [
            ttk.Checkbutton(box, text="Solid archive (smaller, slower to change)", variable=self.solid_var),
            ttk.Checkbutton(box, text="Add a recovery record (lets damaged archives be repaired)", variable=self.rr_var),
            ttk.Checkbutton(box, text="Self-extracting archive (.exe, opens on any Windows PC)", variable=self.sfx_var),
        ]
        for cb in self.rar_cbs:
            cb.pack(anchor="w")

    def _tab_comment(self, nb):
        t = ttk.Frame(nb, padding=16)
        nb.add(t, text="Comment")
        ttk.Label(t, text="Shown when the archive is opened (ZIP only)", style="Muted.TLabel").pack(anchor="w", pady=(0, 4))
        self.comment = make_text(t, width=64, height=7, wrap="word")
        self.comment.pack(fill="both", expand=True)

    def _tab_files(self, nb):
        t = ttk.Frame(nb, padding=16)
        nb.add(t, text="Files")
        ttk.Label(t, text=f"{len(self.sources)} item(s) will be added", style="Muted.TLabel").pack(anchor="w", pady=(0, 4))
        box = ttk.Frame(t)
        box.pack(fill="both", expand=True)
        lb = tk.Listbox(box, height=7, relief="flat", highlightthickness=1, highlightbackground=THEME["border"],
                        activestyle="none")
        sb = ttk.Scrollbar(box, command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        lb.pack(side="left", fill="both", expand=True)
        for s in self.sources:
            lb.insert("end", s)

    # ---- behaviour
    def _toggle_pw(self):
        ch = "" if self.show_var.get() else "\u2022"
        self.pw_entry.configure(show=ch)
        self.pw2_entry.configure(show=ch)

    def _strip_ext(self, name):
        low = name.lower()
        for ext in sorted(core.FORMAT_EXT.values(), key=len, reverse=True):
            if low.endswith(ext):
                return name[: -len(ext)]
        return name

    def _fmt_changed(self):
        self.name_var.set(self._strip_ext(self.name_var.get()) + core.FORMAT_EXT[self.fmt_var.get()])
        self._refresh()

    def _refresh(self):
        fmt = self.fmt_var.get()
        self.hint.configure(text=core.FORMAT_HINT.get(fmt, ""))
        name = self.name_var.get().strip().strip('"')
        self.exists_lbl.configure(text="This archive already exists - the files will be added to it." if
                                  name and os.path.isfile(name) else "")
        if fmt == "zip":
            note = ("Passwords use strong AES-256 encryption." if core.supports_password("zip") else
                    "Passwords for ZIP need the 'pyzipper' package:  pip install pyzipper")
        elif fmt == "7z":
            note = ("Passwords use AES-256. Tick the box above to hide file names too." if core.supports_password("7z")
                    else "Passwords for 7Z need the 'py7zr' package:  pip install py7zr")
        elif fmt == "rar":
            note = ("Passwords use AES encryption. Tick the box above to hide file names too." if core.supports_password("rar")
                    else "Creating RAR files needs Rar.exe in the tools folder (see tools\\README.txt).")
        else:
            note = f"{core.FORMAT_LABEL[fmt]} archives cannot be password protected. Choose ZIP, 7Z or RAR."
        self.pw_note.configure(text=note)
        self.names_cb.state(["!disabled"] if fmt in ("7z", "rar") else ["disabled"])
        for cb in getattr(self, "rar_cbs", []):
            cb.state(["!disabled"] if fmt == "rar" else ["disabled"])

    def _browse(self):
        fmt = self.fmt_var.get()
        p = filedialog.asksaveasfilename(parent=self, title="Archive name", initialfile=os.path.basename(self.name_var.get()),
                                         initialdir=os.path.dirname(self.name_var.get()) or None,
                                         defaultextension=core.FORMAT_EXT[fmt], confirmoverwrite=False)
        if p:
            self.name_var.set(os.path.normpath(p))

    def ok(self):
        name = self.name_var.get().strip().strip('"')
        if not name:
            messagebox.showwarning(core.APP_NAME, "Please type a name for the archive.", parent=self)
            return
        fmt = self.fmt_var.get()
        ext = core.FORMAT_EXT[fmt]
        if not name.lower().endswith(ext):
            name = self._strip_ext(name) + ext
        pw = self.pw_var.get()
        if pw:
            if pw != self.pw2_var.get():
                self.nb.select(1)
                messagebox.showwarning(core.APP_NAME, "The two passwords are not the same.", parent=self)
                return
            if not core.supports_password(fmt):
                self.nb.select(1)
                messagebox.showwarning(core.APP_NAME, self.pw_note.cget("text"), parent=self)
                return
        split = 0
        if self.split_var.get().strip():
            try:
                split = int(float(self.split_var.get().replace(",", ".")) * SPLIT_UNITS[self.unit_var.get()])
                if split < 64 * 1024:
                    raise ValueError
            except ValueError:
                self.nb.select(0)
                messagebox.showwarning(core.APP_NAME, "Part size must be a number of at least 64 KB.", parent=self)
                return
        level = core.LEVEL_NAMES.index(self.level_var.get())
        mode = next((k for k, n in core.UPDATE_MODES if n == self.update_var.get()), "replace")
        opts = core.AddOptions(
            fmt=fmt, level=level, password=pw or None, encrypt_names=bool(self.names_var.get() and fmt in ("7z", "rar")),
            solid=bool(self.solid_var.get() and fmt == "rar"), recovery=bool(self.rr_var.get() and fmt == "rar"),
            sfx=bool(self.sfx_var.get() and fmt == "rar"),
            excludes=[p.strip() for p in self.excl_var.get().split(";") if p.strip()],
            comment=self.comment.get("1.0", "end").strip() if fmt == "zip" else "", update_mode=mode,
            split_size=split, delete_after=self.delete_var.get(), test_after=self.test_var.get())
        settings["default_format"], settings["default_level"] = fmt, level
        settings.save()
        self.finish((os.path.abspath(name), opts))


# ----------------------------------------------------------- extract dialog
class ExtractDialog(Dialog):
    def __init__(self, parent, archive_label, default_dest, subfolder_name="", selected=None):
        super().__init__(parent, "Extract files")
        self.base_dest = default_dest
        self.subfolder = subfolder_name
        self.dest_var = tk.StringVar(value=default_dest)
        self.sub_var = tk.BooleanVar(value=False)
        self.update_var = tk.StringVar(value="replace")
        self.over_var = tk.StringVar(value="ask")
        self.open_var = tk.BooleanVar(value=bool(settings["open_dest_after_extract"]))
        self.del_var = tk.BooleanVar(value=False)

        outer = ttk.Frame(self, padding=(18, 16, 18, 14))
        outer.pack(fill="both", expand=True)
        what = archive_label if not selected else f"{selected} selected item(s) from {archive_label}"
        ttk.Label(outer, text="Extract to", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text=what, style="Muted.TLabel", wraplength=int(640 * SCALE)).pack(anchor="w", pady=(2, 10))
        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True)
        ttk.Label(left, text="Destination folder (created if it does not exist)").pack(anchor="w")
        row = ttk.Frame(left)
        row.pack(fill="x", pady=(4, 0))
        ttk.Combobox(row, textvariable=self.dest_var, values=settings["recent_dests"], width=52).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse...", command=self._browse).pack(side="left", padx=(8, 0))
        if subfolder_name:
            ttk.Checkbutton(left, text=f'Put the files in a new folder named "{subfolder_name}"', variable=self.sub_var,
                            command=self._sub_toggled).pack(anchor="w", pady=(8, 0))
        g1 = ttk.LabelFrame(left, text="  Update mode  ", padding=10)
        g1.pack(fill="x", pady=(12, 0))
        for text, val in (("Extract and replace files", "replace"), ("Extract and update files (newer only)", "update"),
                          ("Only refresh files that already exist", "freshen")):
            ttk.Radiobutton(g1, text=text, value=val, variable=self.update_var).pack(anchor="w")
        g2 = ttk.LabelFrame(left, text="  When a file already exists  ", padding=10)
        g2.pack(fill="x", pady=(10, 0))
        for text, val in (("Ask me", "ask"), ("Replace without asking", "overwrite"),
                          ("Skip it", "skip"), ("Keep both (rename the new one)", "rename")):
            ttk.Radiobutton(g2, text=text, value=val, variable=self.over_var).pack(anchor="w")
        ttk.Checkbutton(left, text="Open the destination folder when finished", variable=self.open_var).pack(anchor="w", pady=(10, 0))
        ttk.Checkbutton(left, text="Delete the archive after extracting", variable=self.del_var).pack(anchor="w")
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", padx=(18, 0))
        ttk.Label(right, text="Pick a folder").pack(anchor="w", pady=(0, 4))
        self.tree = FolderTree(right, self._picked, height=17)
        self.tree.pack(fill="both", expand=True)
        self.buttons(outer, [("Extract", self.ok, True), ("Cancel", self.cancel, False)]).pack(fill="x", pady=(14, 0))
        self.bind("<Return>", lambda e: self.ok())

    def _picked(self, path):
        self.base_dest = path
        self._sub_toggled()

    def _sub_toggled(self):
        if self.sub_var.get() and self.subfolder:
            self.dest_var.set(os.path.join(self.base_dest, self.subfolder))
        else:
            self.dest_var.set(self.base_dest)

    def _browse(self):
        p = ask_folder(self, self.dest_var.get(), "Extract to")
        if p:
            self.base_dest = os.path.normpath(p)
            self._sub_toggled()

    def ok(self):
        dest = self.dest_var.get().strip().strip('"')
        if not dest:
            messagebox.showwarning(core.APP_NAME, "Please choose a destination folder.", parent=self)
            return
        mode = self.update_var.get()
        overwrite = self.over_var.get() if mode == "replace" else mode
        settings.add_recent("recent_dests", os.path.normpath(dest))
        settings["open_dest_after_extract"] = bool(self.open_var.get())
        settings.save()
        self.finish({"dest": os.path.abspath(dest), "overwrite": overwrite, "open_after": self.open_var.get(),
                     "delete_archive": self.del_var.get()})


# ----------------------------------------------------------- convert dialog
class ConvertDialog(Dialog):
    def __init__(self, parent, src_path):
        super().__init__(parent, "Convert archive")
        self.src = src_path
        self.fmt_var = tk.StringVar(value="zip" if not src_path.lower().endswith(".zip") else
                                    ("7z" if core.can_create("7z") else "tar.gz"))
        self.level_var = tk.StringVar(value=core.LEVEL_NAMES[3])
        self.name_var = tk.StringVar()
        f = ttk.Frame(self, padding=20)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Convert to another format", style="Title.TLabel").pack(anchor="w")
        ttk.Label(f, text=os.path.basename(src_path), style="Muted.TLabel").pack(anchor="w", pady=(2, 10))
        g = ttk.LabelFrame(f, text="  New format  ", padding=10)
        g.pack(fill="x")
        for i, fm in enumerate(core.CREATE_FORMATS):
            rb = ttk.Radiobutton(g, text=core.FORMAT_LABEL[fm], value=fm, variable=self.fmt_var, command=self._sync)
            if not core.can_create(fm):
                rb.state(["disabled"])
            rb.grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 18), pady=2)
        ttk.Label(f, text="Compression").pack(anchor="w", pady=(10, 0))
        ttk.Combobox(f, textvariable=self.level_var, values=core.LEVEL_NAMES, state="readonly", width=26).pack(anchor="w")
        ttk.Label(f, text="Save as").pack(anchor="w", pady=(10, 0))
        ttk.Entry(f, textvariable=self.name_var, width=60).pack(fill="x")
        self.buttons(f, [("Convert", self.ok, True), ("Cancel", self.cancel, False)]).pack(fill="x", pady=(16, 0))
        self._sync()

    def _sync(self):
        d = os.path.dirname(self.src)
        self.name_var.set(os.path.join(d, core.archive_stem(self.src) + core.FORMAT_EXT[self.fmt_var.get()]))

    def ok(self):
        dest = self.name_var.get().strip()
        if not dest:
            return
        if os.path.abspath(dest) == os.path.abspath(self.src):
            messagebox.showwarning(core.APP_NAME, "Choose a different name so the original is not overwritten.", parent=self)
            return
        opts = core.AddOptions(fmt=self.fmt_var.get(), level=core.LEVEL_NAMES.index(self.level_var.get()))
        self.finish((os.path.abspath(dest), opts))


# ----------------------------------------------------------- settings dialog
class SettingsDialog(Dialog):
    def __init__(self, parent):
        super().__init__(parent, "Settings")
        self.theme_changed = False
        self._old_theme = settings["theme"]
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=14, pady=(14, 0))
        gen = ttk.Frame(nb, padding=18)
        nb.add(gen, text="General")
        self.theme_var = tk.StringVar(value="Dark" if settings["theme"] == "dark" else "Light")
        self.fmt_var = tk.StringVar(value=core.FORMAT_LABEL.get(settings["default_format"], "ZIP"))
        self.level_var = tk.StringVar(value=core.LEVEL_NAMES[int(settings["default_level"])])
        self.confirm_var = tk.BooleanVar(value=bool(settings["confirm_delete"]))
        self.hidden_var = tk.BooleanVar(value=bool(settings["show_hidden"]))
        self.open_var = tk.BooleanVar(value=bool(settings["open_dest_after_extract"]))
        for r, (label, var, vals) in enumerate((("Appearance", self.theme_var, ["Light", "Dark"]),
                                                ("Default format for new archives", self.fmt_var,
                                                 [core.FORMAT_LABEL[f] for f in core.CREATE_FORMATS]),
                                                ("Default compression", self.level_var, core.LEVEL_NAMES))):
            ttk.Label(gen, text=label).grid(row=r * 2, column=0, sticky="w", pady=(0 if r == 0 else 8, 0))
            ttk.Combobox(gen, textvariable=var, values=vals, state="readonly", width=28).grid(row=r * 2 + 1, column=0, sticky="w")
        ttk.Checkbutton(gen, text="Ask before deleting files", variable=self.confirm_var).grid(row=6, column=0, sticky="w", pady=(14, 0))
        ttk.Checkbutton(gen, text="Show hidden files in the file list", variable=self.hidden_var).grid(row=7, column=0, sticky="w")
        ttk.Checkbutton(gen, text="Open the destination folder after extracting", variable=self.open_var).grid(row=8, column=0, sticky="w")

        ex = ttk.Frame(nb, padding=18)
        nb.add(ex, text="Explorer integration")
        self.cascade_var = tk.BooleanVar(value=bool(settings["cascade_menu"]))
        wrap = int(500 * SCALE)
        ttk.Label(ex, text="Right-click menu", style="Title.TLabel").pack(anchor="w")
        ttk.Label(ex, text="Adds 'Add to archive...', 'Extract Here' and more to the right-click menu of files, "
                           "folders and archives. Nothing needs administrator rights.",
                  style="Muted.TLabel", wraplength=wrap).pack(anchor="w", pady=(2, 10))
        self.menu_status = ttk.Label(ex, text="", wraplength=wrap)
        if shell.available():
            ttk.Checkbutton(ex, text="Group the entries in one 'Wajeeha Archiver' sub-menu",
                            variable=self.cascade_var).pack(anchor="w")
            row = ttk.Frame(ex)
            row.pack(anchor="w", pady=10)
            ttk.Button(row, text="Add / refresh right-click menu", style="Accent.TButton",
                       command=self._do_add_menu).pack(side="left")
            ttk.Button(row, text="Remove", command=self._do_remove_menu).pack(side="left", padx=8)
            self.menu_status.pack(anchor="w")
            if shell.is_win11():
                box = ttk.LabelFrame(ex, text="  Windows 11  ", padding=10)
                box.pack(fill="x", pady=(12, 0))
                ttk.Label(box, text="Windows 11 hides classic right-click entries behind 'Show more options' "
                                    "(or Shift+F10). You can make Windows show them straight away:",
                          style="Muted.TLabel", wraplength=wrap - 30).pack(anchor="w")
                self.classic_btn = ttk.Button(box, text="", command=self._do_classic_toggle)
                self.classic_btn.pack(anchor="w", pady=(8, 0))
                self._show_classic_state()
            ttk.Button(ex, text="Choose default apps for .zip, .7z ...",
                       command=lambda: os.startfile("ms-settings:defaultapps")).pack(anchor="w", pady=(12, 0))  # noqa
            self._show_menu_status()
        else:
            ttk.Label(ex, text="Explorer integration is only available on Windows.").pack(anchor="w")
        ttk.Button(ex, text="Save a .reg file instead...", command=self._do_export_reg).pack(anchor="w", pady=(10, 0))
        self.buttons(self, [("Save", self.ok, True), ("Cancel", self.cancel, False)]).pack(fill="x", padx=14, pady=14)

    def _show_menu_status(self):
        try:
            cmd = shell.registered_command()
            if not cmd:
                self.menu_status.configure(text="Status: not installed", foreground=THEME["muted"])
            elif not shell.command_target_exists(cmd):
                self.menu_status.configure(text="Status: installed, but it points to a program that no longer exists. "
                                                "Press 'Add / refresh' to fix it.", foreground=THEME["danger"])
            else:
                self.menu_status.configure(text="Status: installed.   Starts: " + shell.command_target(cmd),
                                           foreground=THEME["fg"])
        except Exception as e:
            self.menu_status.configure(text=f"Status: unknown ({e})")

    def _do_add_menu(self):
        try:
            shell.register(cascade=self.cascade_var.get())
            settings["cascade_menu"] = bool(self.cascade_var.get())
            settings["shell_asked"] = True
            settings.save()
            extra = ("\n\nOn Windows 11, look under 'Show more options' - or use the Windows 11 button below."
                     if shell.is_win11() else "")
            messagebox.showinfo(core.APP_NAME, "Done. Right-click a file, folder or archive in Explorer." + extra,
                                parent=self)
        except Exception as e:
            messagebox.showerror(core.APP_NAME, f"Could not update the right-click menu:\n{e}", parent=self)
        self._show_menu_status()

    def _do_remove_menu(self):
        try:
            shell.unregister()
            settings["shell_asked"] = True
            settings.save()
        except Exception as e:
            messagebox.showerror(core.APP_NAME, f"Could not remove the entries:\n{e}", parent=self)
        self._show_menu_status()

    def _show_classic_state(self):
        on = shell.classic_menu_enabled()
        self.classic_btn.configure(text="Go back to the standard Windows 11 menu" if on else
                                   "Show classic entries directly in the right-click menu")

    def _do_classic_toggle(self):
        want = not shell.classic_menu_enabled()
        try:
            shell.set_classic_menu(want)
        except Exception as e:
            messagebox.showerror(core.APP_NAME, f"Could not change this Windows setting:\n{e}", parent=self)
            return
        self._show_classic_state()
        if messagebox.askyesno(core.APP_NAME, "The change takes effect after Windows Explorer restarts.\n\n"
                                              "Restart Explorer now? (The taskbar disappears for a moment.)", parent=self):
            shell.restart_explorer()

    def _do_export_reg(self):
        p = filedialog.asksaveasfilename(parent=self, defaultextension=".reg", initialfile="wajeeha-archiver-menu.reg",
                                         filetypes=[("Registry file", "*.reg")])
        if p:
            spec = shell.build_spec(shell.command_prefix(), shell.icon_value(), self.cascade_var.get())
            with open(p, "w", encoding="utf-16") as f:
                f.write(shell.to_reg(spec))

    def ok(self):
        settings["theme"] = "dark" if self.theme_var.get() == "Dark" else "light"
        lab = {v: k for k, v in core.FORMAT_LABEL.items()}
        settings["default_format"] = lab.get(self.fmt_var.get(), "zip")
        settings["default_level"] = core.LEVEL_NAMES.index(self.level_var.get())
        settings["confirm_delete"] = bool(self.confirm_var.get())
        settings["show_hidden"] = bool(self.hidden_var.get())
        settings["open_dest_after_extract"] = bool(self.open_var.get())
        settings.save()
        self.theme_changed = settings["theme"] != self._old_theme
        self.finish(True)


# -------------------------------------------------------------- about dialog
class AboutDialog(Dialog):
    def __init__(self, parent):
        super().__init__(parent, "About " + core.APP_NAME)
        f = ttk.Frame(self, padding=24)
        f.pack(fill="both", expand=True)
        ttk.Label(f, image=get_image("app", 64)).pack()
        ttk.Label(f, text=core.APP_NAME, style="Title.TLabel").pack(pady=(8, 0))
        ttk.Label(f, text=f"Version {core.APP_VERSION}", style="Muted.TLabel").pack()
        ttk.Label(f, text="Create, open and extract archives - with a right-click away.",
                  wraplength=int(380 * SCALE), justify="center").pack(pady=(10, 12))
        cap = core.capabilities()

        def yn(v):
            return "ready" if v else "not installed"
        lines = [("ZIP, TAR, GZ, BZ2, XZ", "built in"),
                 ("ZIP passwords (AES-256)", yn(cap["zip-aes"])),
                 ("7Z", yn(cap["7z"])),
                 ("RAR (extract)", yn(cap["rar"])),
                 ("RAR (create)", "ready" if cap["rar-create"] else "needs Rar.exe in tools"),
                 ("ISO, CAB, WIM and more", "ready" if cap["7z-tool"] else "needs 7-Zip")]
        g = ttk.Frame(f)
        g.pack()
        for i, (k, v) in enumerate(lines):
            ttk.Label(g, text=k).grid(row=i, column=0, sticky="w", padx=(0, 20), pady=1)
            ttk.Label(g, text=v, style="Muted.TLabel").grid(row=i, column=1, sticky="w")
        self.buttons(f, [("Close", self.cancel, True)]).pack(fill="x", pady=(18, 0))
