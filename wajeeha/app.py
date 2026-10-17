# -*- coding: utf-8 -*-
"""Wajeeha Archiver - main window, operations and command-line entry point."""
import datetime as dt
import fnmatch
import os
import sys
import time
import tkinter as tk
import traceback
from dataclasses import dataclass
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from . import config, core, shell, ui
from .config import settings
from .ui import THEME

try:  # optional: drag & drop from Explorer  (pip install tkinterdnd2)
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:  # pragma: no cover
    TkinterDnD, DND_FILES = None, None


@dataclass
class Node:
    name: str
    path: str
    is_dir: bool
    size: int = 0
    packed: int = 0
    mtime: Optional[dt.datetime] = None
    crc: Optional[int] = None
    encrypted: bool = False


def log_error(exc):
    try:
        os.makedirs(config.APP_DATA, exist_ok=True)
        p = os.path.join(config.APP_DATA, "error.log")
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"--- {dt.datetime.now()}\n")
            f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        return p
    except OSError:
        return ""


# ====================================================================
#  Operations shared by the main window and the Explorer-launched flows
# ====================================================================
class Operations:
    root = None

    # hooks the main window overrides
    def set_status(self, text):
        pass

    def after_change(self, select=None):
        pass

    # ---- helpers
    def ask_password(self, path, wrong=False):
        return ui.PasswordDialog(self.root, os.path.basename(path), wrong).show()

    def _ask_overwrite(self, dlg, path, size, mtime):
        return ui.OverwriteDialog(dlg, path, size, mtime).show() or "cancel"

    def finish(self, exc, job, success_text):
        """Report the outcome of a job. Returns True when it worked."""
        if exc is not None:
            if isinstance(exc, core.Cancelled):
                self.set_status("Cancelled.")
                return False
            if isinstance(exc, core.ArchiveError):
                ui.error_box(self.root, str(exc))
                return False
            where = log_error(exc)
            ui.error_box(self.root, f"Something unexpected went wrong:\n{exc}\n\n"
                                    + (f"Details were saved to:\n{where}" if where else ""))
            return False
        if job.errors:
            ui.ReportDialog(self.root, "Finished with problems",
                            f"{len(job.errors)} problem(s) were found", job.errors).show()
            self.set_status(f"{success_text} with {len(job.errors)} problem(s).")
            return False
        self.set_status(success_text)
        return True

    # ---- create / add
    def add_files(self, sources, dest_dir=None):
        res = ui.AddDialog(self.root, sources, dest_dir=dest_dir).show()
        if not res:
            return False
        dest, opts = res
        return self.do_build(dest, sources, opts)

    def do_build(self, dest, sources, opts, existing_password=None):
        def work(job, dlg):
            return core.build_archive(dest, sources, opts, job, existing_password)
        val, exc, job = ui.run_job(self.root, "Adding to " + os.path.basename(dest), work)
        ok = self.finish(exc, job, "Archive ready: " + os.path.basename(dest))
        created = [p for p in (val or []) if os.path.exists(p)] or ([dest] if os.path.exists(dest) else [])
        if created:
            self.after_change(select=os.path.basename(created[0]))
        return ok

    def quick_add(self, fmt, paths):
        if not core.can_create(fmt):
            ui.error_box(self.root, "7Z needs the 'py7zr' package.\nInstall it with:  pip install py7zr" if fmt == "7z"
                         else "Creating RAR archives needs Rar.exe in the tools folder (see tools\\README.txt).")
            return False
        dest_dir = os.path.dirname(os.path.abspath(paths[0]))
        if len(paths) == 1:
            p = os.path.abspath(paths[0])
            base = os.path.splitext(os.path.basename(p))[0] if os.path.isfile(p) else os.path.basename(p)
        else:
            base = os.path.basename(dest_dir.rstrip("\\/")) or "Archive"
        dest = core.unique_path(os.path.join(dest_dir, base + core.FORMAT_EXT[fmt]))
        return self.do_build(dest, paths, core.AddOptions(fmt=fmt, level=int(settings["default_level"])))

    # ---- extract
    def run_extract(self, archive_path, dest, names=None, strip="", overwrite="ask", password=None):
        pw = password
        while True:
            def work(job, dlg, pw=pw):
                a = core.open_archive(archive_path, pw)
                try:
                    policy = core.ExtractPolicy(
                        overwrite, ask=lambda p, s, m: dlg.call_main(self._ask_overwrite, dlg, p, s, m))
                    return a.extract(dest, names, job, policy, strip)
                finally:
                    a.close()
            _val, exc, job = ui.run_job(self.root, "Extracting " + os.path.basename(archive_path), work)
            if isinstance(exc, (core.PasswordRequired, core.WrongPassword)):
                pw = self.ask_password(archive_path, isinstance(exc, core.WrongPassword))
                if pw is None:
                    return False
                continue
            break
        return self.finish(exc, job, "Extracted to " + dest)

    def extract_archives(self, paths, default_dest=None):
        if not paths:
            return
        first = paths[0]
        label = os.path.basename(first) if len(paths) == 1 else f"{len(paths)} archives"
        sub = core.archive_stem(first) if len(paths) == 1 else ""
        dest0 = default_dest or os.path.dirname(os.path.abspath(first))
        res = ui.ExtractDialog(self.root, label, dest0, sub).show()
        if not res:
            return
        for p in paths:
            dest = res["dest"] if len(paths) == 1 else os.path.join(res["dest"], core.archive_stem(p))
            ok = self.run_extract(p, dest, None, "", res["overwrite"])
            if ok and res["delete_archive"]:
                try:
                    os.remove(p)
                except OSError:
                    pass
            if ok and res["open_after"] and p is paths[-1]:
                ui.reveal_folder(res["dest"])
        self.after_change()

    # ---- test
    def test_archive(self, path, password=None):
        pw = password
        while True:
            def work(job, dlg, pw=pw):
                a = core.open_archive(path, pw)
                try:
                    return a.test(job)
                finally:
                    a.close()
            _val, exc, job = ui.run_job(self.root, "Testing " + os.path.basename(path), work)
            if isinstance(exc, (core.PasswordRequired, core.WrongPassword)):
                pw = self.ask_password(path, isinstance(exc, core.WrongPassword))
                if pw is None:
                    return
                continue
            break
        if exc is not None:
            self.finish(exc, job, "")
            return
        if job.errors:
            ui.ReportDialog(self.root, "Test result", f"Problems found in {os.path.basename(path)}", job.errors).show()
        else:
            ui.info_box(self.root, "Test result", f"No errors found in\n{os.path.basename(path)}")

    # ---- convert / repair
    def convert_archive(self, path, password=None):
        res = ui.ConvertDialog(self.root, path).show()
        if not res:
            return
        dest, opts = res
        pw = password
        while True:
            def work(job, dlg, pw=pw):
                return core.convert_archive(path, dest, opts, pw, job)
            _val, exc, job = ui.run_job(self.root, "Converting " + os.path.basename(path), work)
            if isinstance(exc, (core.PasswordRequired, core.WrongPassword)):
                pw = self.ask_password(path, isinstance(exc, core.WrongPassword))
                if pw is None:
                    return
                continue
            break
        if self.finish(exc, job, "Converted to " + os.path.basename(dest)):
            self.after_change(select=os.path.basename(dest))

    def repair_archive(self, path):
        fmt = core.detect_format(path)
        if fmt == "rar":
            def work_rar(job, dlg):
                return core.repair_rar(path, job)
            val, exc, job = ui.run_job(self.root, "Repairing " + os.path.basename(path), work_rar)
            if exc is not None:
                self.finish(exc, job, "")
                return
            ui.info_box(self.root, "Repair finished", f"A repaired copy was saved as\n{os.path.basename(val)}")
            self.after_change(select=os.path.basename(val))
            return
        if fmt not in ("zip", None) and not path.lower().endswith(".zip"):
            ui.info_box(self.root, "Repair", "Repair works on ZIP and RAR archives.")
            return
        out = filedialog.asksaveasfilename(
            parent=self.root, title="Save the repaired archive as", defaultextension=".zip",
            initialfile=core.archive_stem(path) + "_repaired.zip", initialdir=os.path.dirname(path))
        if not out:
            return

        def work(job, dlg):
            return core.repair_zip(path, out, job)
        val, exc, job = ui.run_job(self.root, "Repairing " + os.path.basename(path), work)
        if exc is not None:
            self.finish(exc, job, "")
            return
        recovered, skipped = val
        if skipped:
            ui.ReportDialog(self.root, "Repair finished", f"Recovered {recovered} file(s); {len(skipped)} could not be saved",
                            skipped).show()
        else:
            ui.info_box(self.root, "Repair finished", f"Recovered {recovered} file(s) into\n{os.path.basename(out)}")
        self.after_change(select=os.path.basename(out))

    def show_info(self, path):
        try:
            pw = None
            while True:
                try:
                    a = core.open_archive(path, pw)
                    break
                except (core.PasswordRequired, core.WrongPassword) as e:
                    pw = self.ask_password(path, isinstance(e, core.WrongPassword))
                    if pw is None:
                        return
            try:
                info = core.archive_info(a)
            finally:
                a.close()
            ui.InfoDialog(self.root, info).show()
        except core.ArchiveError as e:
            ui.error_box(self.root, str(e))


# ====================================================================
#  Main window
# ====================================================================
TOOLS = [("add", "Add"), ("extract", "Extract To"), ("test", "Test"), ("view", "View"), ("delete", "Delete"),
         ("find", "Find"), ("convert", "Convert"), ("info", "Info"), ("repair", "Repair")]
COLS = [("size", "Size", 90, "e"), ("packed", "Packed", 90, "e"), ("type", "Type", 130, "w"),
        ("modified", "Modified", 140, "w"), ("crc", "CRC32", 90, "w")]


class MainWindow(Operations):
    def __init__(self, root, open_path=None):
        self.root = root
        self.mode = "fs"                  # fs | archive
        self.cwd = ""
        self.arc = None
        self.arc_path = ""
        self.password = None
        self.sub = ""
        self.index = {}
        self.search_hits = None
        self.row_nodes = {}
        self.sort_col = settings["sort_col"]
        self.sort_rev = bool(settings["sort_rev"])
        self.tool_btns = {}
        self._msg_time = 0.0
        root.title(core.APP_NAME)
        try:
            root.geometry(settings["geometry"])
        except tk.TclError:
            root.geometry("1060x660")
        root.minsize(760, 440)
        ui.set_window_icon(root)
        self._build()
        root.protocol("WM_DELETE_WINDOW", self.quit)
        start = settings["last_dir"] if os.path.isdir(settings["last_dir"] or "") else os.path.expanduser("~")
        if open_path and os.path.isfile(open_path):
            self.go_fs(os.path.dirname(os.path.abspath(open_path)))
            root.after(50, lambda: self.open_archive(open_path))
        else:
            self.go_fs(start)
            self.set_status("Tip: double-click an archive to open it, or select files and press Add.")
        root.after(700, self._check_shell)

    def _check_shell(self):
        """Offer the right-click menu on first run, and repair it if the program was moved or rebuilt."""
        if not shell.available():
            return
        try:
            if shell.is_registered():
                if shell.needs_refresh():
                    shell.register(cascade=bool(settings["cascade_menu"]))
                    self.set_status("The right-click menu was updated to point at this copy of the program.")
            elif not settings["shell_asked"]:
                settings["shell_asked"] = True
                settings.save()
                extra = ("\n\nOn Windows 11 the entries are under 'Show more options' (Shift+F10). "
                         "Settings > Explorer integration can show them directly." if shell.is_win11() else "")
                if messagebox.askyesno(core.APP_NAME,
                                       "Add Wajeeha Archiver to the Explorer right-click menu?\n\n"
                                       "You get 'Add to archive...', 'Extract Here' and more. "
                                       "You can remove it any time in Settings." + extra, parent=self.root):
                    shell.register(cascade=bool(settings["cascade_menu"]))
                    self.set_status("Right-click menu added.")
        except Exception as e:  # noqa
            log_error(e)

    # ------------------------------------------------------------ build
    def _build(self):
        r = self.root
        self._build_menu()
        self.toolbar = ttk.Frame(r, style="Toolbar.TFrame", padding=(8, 6))
        self.toolbar.pack(fill="x")
        self._build_toolbar()
        ttk.Separator(r).pack(fill="x")

        nav = ttk.Frame(r, style="Panel.TFrame", padding=(8, 6))
        nav.pack(fill="x")
        self.up_btn = ttk.Button(nav, image=ui.get_image("up", 16), style="Nav.TButton", command=self.go_up)
        self.up_btn.pack(side="left")
        self.addr_var = tk.StringVar()
        self.addr = ttk.Entry(nav, textvariable=self.addr_var)
        self.addr.pack(side="left", fill="x", expand=True, padx=8)
        self.addr.bind("<Return>", lambda e: self.navigate_text())
        if os.name == "nt":
            self.drive_var = tk.StringVar()
            self._drive_list = ui.FolderTree._drives()
            self.drives = ttk.Combobox(nav, textvariable=self.drive_var, values=self._drive_list, width=5,
                                       state="readonly")
            self.drives.pack(side="left")
            self.drives.bind("<<ComboboxSelected>>", lambda e: self.go_fs(self.drive_var.get()))
        ttk.Separator(r).pack(fill="x")

        status = ttk.Frame(r, style="Toolbar.TFrame")
        status.pack(fill="x", side="bottom")
        self.status_l = ttk.Label(status, text="", style="Status.TLabel")
        self.status_l.pack(side="left", fill="x", expand=True)
        self.status_r = ttk.Label(status, text="", style="Status.TLabel")
        self.status_r.pack(side="right")

        body = ttk.Frame(r, style="Panel.TFrame")
        body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(body, columns=[c[0] for c in COLS], selectmode="extended", show="tree headings")
        ys = ttk.Scrollbar(body, command=self.tree.yview)
        xs = ttk.Scrollbar(body, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        ys.pack(side="right", fill="y")
        xs.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.heading("#0", text="Name", anchor="w", command=lambda: self.sort_by("name"))
        self.tree.column("#0", width=int(380 * ui.SCALE), minwidth=180, stretch=True)
        for key, text, w, anchor in COLS:
            self.tree.heading(key, text=text, anchor=anchor, command=lambda k=key: self.sort_by(k))
            self.tree.column(key, width=int(w * ui.SCALE), anchor=anchor, stretch=False, minwidth=50)
        self.tree.tag_configure("alt", background=THEME["row_alt"])

        t = self.tree
        t.bind("<<TreeviewSelect>>", lambda e: self._selection_changed())
        t.bind("<Double-1>", self.on_double)
        t.bind("<Return>", lambda e: self.open_selected())
        t.bind("<BackSpace>", lambda e: self.go_up())
        t.bind("<Delete>", lambda e: self.act_delete())
        t.bind("<Control-a>", lambda e: (self.select_all(), "break")[1])
        t.bind("<Button-3>", self.context_menu)
        t.bind("<Button-2>", self.context_menu)
        r.bind("<Control-o>", lambda e: self.open_dialog())
        r.bind("<Control-w>", lambda e: self.close_archive())
        r.bind("<F5>", lambda e: self.refresh())
        for key, fn in (("a", self.act_add), ("e", self.act_extract), ("t", self.act_test), ("v", self.act_view),
                        ("f", self.act_find), ("i", self.act_info), ("r", self.act_repair)):
            r.bind(f"<Alt-{key}>", lambda e, f=fn: f())
        if TkinterDnD is not None:
            try:
                t.drop_target_register(DND_FILES)
                t.dnd_bind("<<Drop>>", self.on_drop)
            except Exception:
                pass

    def _build_toolbar(self):
        for w in self.toolbar.winfo_children():
            w.destroy()
        self.tool_btns = {}
        for name, label in TOOLS:
            b = ttk.Button(self.toolbar, text=label, compound="top", style="Tool.TButton",
                           image=(ui.get_image(name, 28), "disabled", ui.get_image(name, 28, gray=True)),
                           command=getattr(self, "act_" + name), width=9)
            b.pack(side="left", padx=2)
            self.tool_btns[name] = b
        g = ttk.Button(self.toolbar, text="Settings", compound="top", style="Tool.TButton",
                       image=ui.get_image("gear", 28), command=self.act_settings, width=9)
        g.pack(side="right", padx=2)

    def _build_menu(self):
        r = self.root
        m = tk.Menu(r)
        r.configure(menu=m)
        f = tk.Menu(m, tearoff=0, postcommand=self._rebuild_recent)
        m.add_cascade(label="File", menu=f)
        f.add_command(label="Open archive...", accelerator="Ctrl+O", command=self.open_dialog)
        self.recent_menu = tk.Menu(f, tearoff=0)
        f.add_cascade(label="Open recent", menu=self.recent_menu)
        f.add_command(label="Close archive", accelerator="Ctrl+W", command=self.close_archive)
        f.add_separator()
        f.add_command(label="Archive comment...", command=self.act_comment)
        f.add_separator()
        f.add_command(label="Exit", command=self.quit)
        c = tk.Menu(m, tearoff=0)
        m.add_cascade(label="Commands", menu=c)
        c.add_command(label="Add files to archive...", accelerator="Alt+A", command=self.act_add)
        c.add_command(label="Extract to...", accelerator="Alt+E", command=self.act_extract)
        c.add_command(label="Extract here", command=self.act_extract_here)
        c.add_command(label="Test archive", accelerator="Alt+T", command=self.act_test)
        c.add_command(label="View file", accelerator="Alt+V", command=self.act_view)
        c.add_command(label="Delete", accelerator="Del", command=self.act_delete)
        c.add_separator()
        c.add_command(label="Find files...", accelerator="Alt+F", command=self.act_find)
        c.add_command(label="Select all", accelerator="Ctrl+A", command=self.select_all)
        c.add_command(label="Refresh", accelerator="F5", command=self.refresh)
        t = tk.Menu(m, tearoff=0)
        m.add_cascade(label="Tools", menu=t)
        t.add_command(label="Convert archive format...", command=self.act_convert)
        t.add_command(label="Repair damaged ZIP / RAR...", accelerator="Alt+R", command=self.act_repair)
        t.add_command(label="Archive information", accelerator="Alt+I", command=self.act_info)
        o = tk.Menu(m, tearoff=0)
        m.add_cascade(label="Options", menu=o)
        o.add_command(label="Settings...", command=self.act_settings)
        o.add_command(label="Right-click menu in Explorer...", command=self.act_settings)
        h = tk.Menu(m, tearoff=0)
        m.add_cascade(label="Help", menu=h)
        h.add_command(label="About " + core.APP_NAME, command=lambda: ui.AboutDialog(self.root).show())

    def _rebuild_recent(self):
        self.recent_menu.delete(0, "end")
        items = [p for p in settings["recent_archives"] if os.path.isfile(p)]
        if not items:
            self.recent_menu.add_command(label="(none)", state="disabled")
        for p in items:
            self.recent_menu.add_command(label=p, command=lambda p=p: self.open_archive(p))

    # ------------------------------------------------------- status/title
    def set_status(self, text):
        self._msg_time = time.time()
        try:
            self.status_l.configure(text=text)
        except tk.TclError:
            pass

    def after_change(self, select=None):
        if self.mode == "archive" and self.arc_path and os.path.isfile(self.arc_path):
            self.reload_archive()
        else:
            self.refresh(select=select)

    def quit(self):
        try:
            settings["geometry"] = self.root.geometry()
            settings["sort_col"], settings["sort_rev"] = self.sort_col, self.sort_rev
            settings.save()
        except Exception:
            pass
        self._drop_archive()
        self.root.destroy()

    # --------------------------------------------------------- navigation
    def _drop_archive(self):
        if self.arc is not None:
            try:
                self.arc.close()
            except Exception:
                pass
        self.arc = None
        self.index = {}

    def go_fs(self, path, select=None):
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            self.root.bell()
            self.set_status("That folder does not exist.")
            return
        self._drop_archive()
        self.mode, self.cwd, self.search_hits = "fs", path, None
        settings["last_dir"] = path
        self.refresh(select=select)

    def close_archive(self):
        if self.mode == "archive":
            self.go_fs(os.path.dirname(self.arc_path), select=os.path.basename(self.arc_path))

    def go_up(self):
        if self.search_hits is not None:
            self.search_hits = None
            self.refresh()
        elif self.mode == "archive":
            if self.sub:
                came = self.sub.rpartition("/")[2]
                self.sub = self.sub.rpartition("/")[0]
                self.refresh(select=(self.sub + "/" + came).lstrip("/"))
            else:
                self.close_archive()
        else:
            parent = os.path.dirname(self.cwd.rstrip("\\/"))
            if parent and parent != self.cwd:
                self.go_fs(parent, select=os.path.basename(self.cwd))

    def navigate_text(self):
        text = self.addr_var.get().strip().strip('"')
        if os.path.isdir(text):
            self.go_fs(text)
        elif os.path.isfile(text):
            self.open_archive(text)
        else:
            self.root.bell()
            self.set_status("Nothing was found at that location.")

    def open_dialog(self):
        types = [("Archives", " ".join("*" + e for e in sorted(core.ARCHIVE_EXTS))), ("All files", "*.*")]
        p = filedialog.askopenfilename(parent=self.root, title="Open archive", filetypes=types,
                                       initialdir=self.cwd or None)
        if p:
            self.open_archive(p)

    def _load_archive(self, path, pw):
        def work(job, dlg=None):
            a = core.open_archive(path, pw)
            a.entries()
            return a
        if os.path.getsize(path) < 30 * 1024 * 1024:
            return work(None)
        val, exc, _job = ui.run_job(self.root, "Opening " + os.path.basename(path), work)
        if exc:
            raise exc
        return val

    def open_archive(self, path, password=None, keep_sub=""):
        path = os.path.abspath(path)
        pw = password
        while True:
            try:
                arc = self._load_archive(path, pw)
                break
            except (core.PasswordRequired, core.WrongPassword) as e:
                pw = self.ask_password(path, isinstance(e, core.WrongPassword))
                if pw is None:
                    return False
            except core.ArchiveError as e:
                ui.error_box(self.root, str(e), "Cannot open archive")
                return False
            except Exception as e:  # noqa
                where = log_error(e)
                ui.error_box(self.root, f"Could not open this file:\n{e}\n\n{where}")
                return False
        self._drop_archive()
        self.arc, self.arc_path, self.password = arc, arc.source_path, pw
        self.mode, self.sub, self.search_hits = "archive", keep_sub, None
        self._build_index()
        settings.add_recent("recent_archives", self.arc_path)
        settings.save()
        self.refresh()
        return True

    def reload_archive(self):
        path, sub, pw = self.arc_path, self.sub, self.password
        self._drop_archive()
        if not self.open_archive(path, pw, keep_sub=sub):
            self.go_fs(os.path.dirname(path))

    def _build_index(self):
        idx = {"": {}}
        for e in self.arc.entries():
            parts = e.name.split("/")
            for i in range(len(parts) - 1):
                folder, child = "/".join(parts[:i]), parts[i]
                full = "/".join(parts[:i + 1])
                idx.setdefault(folder, {})
                if child not in idx[folder]:
                    idx[folder][child] = Node(child, full, True)
                idx.setdefault(full, {})
            folder, leaf = "/".join(parts[:-1]), parts[-1]
            idx.setdefault(folder, {})
            if e.is_dir:
                node = idx[folder].get(leaf) or Node(leaf, e.name, True)
                node.mtime = e.mtime
                idx[folder][leaf] = node
                idx.setdefault(e.name, {})
            else:
                idx[folder][leaf] = Node(leaf, e.name, False, e.size, e.packed, e.mtime, e.crc, e.encrypted)
        self.index = idx

    def on_double(self, event):
        if self.tree.identify_region(event.x, event.y) in ("heading", "separator"):
            return
        self.open_selected()

    def open_selected(self):
        sel = self.selected_nodes()
        if not sel:
            return
        n = sel[0]
        if self.mode == "fs":
            if n.is_dir:
                self.go_fs(n.path)
            elif core.is_archive_name(n.name):
                self.open_archive(n.path)
            else:
                ui.open_with_default(n.path)
        else:
            if n.is_dir:
                self.search_hits = None
                self.sub = n.path
                self.refresh()
            else:
                self.view_member(n)

    def on_drop(self, event):
        try:
            paths = [p for p in self.root.tk.splitlist(event.data) if os.path.exists(p)]
        except Exception:
            return
        if not paths:
            return
        if self.mode == "archive":
            self.add_to_open_archive(paths)
        elif len(paths) == 1 and os.path.isfile(paths[0]) and core.is_archive_name(paths[0]):
            self.open_archive(paths[0])
        else:
            self.add_files(paths)

    # ------------------------------------------------------------- listing
    def _nodes(self):
        if self.search_hits is not None:
            return list(self.search_hits)
        if self.mode == "archive":
            return list(self.index.get(self.sub, {}).values())
        out = []
        try:
            with os.scandir(self.cwd) as it:
                for e in it:
                    try:
                        st = e.stat()
                        is_dir = e.is_dir()
                    except OSError:
                        continue
                    hidden = e.name.startswith(".") or bool(getattr(st, "st_file_attributes", 0) & 2)
                    if hidden and not settings["show_hidden"]:
                        continue
                    try:
                        mt = dt.datetime.fromtimestamp(st.st_mtime)
                    except (OSError, OverflowError, ValueError):
                        mt = None
                    out.append(Node(e.name, e.path, is_dir, 0 if is_dir else st.st_size, 0, mt))
        except OSError as e:
            self.set_status(f"Cannot open this folder: {e}")
        return out

    def _sorted(self, nodes):
        col = self.sort_col
        keys = {"name": lambda n: n.name.lower(), "size": lambda n: n.size, "packed": lambda n: n.packed,
                "type": lambda n: type_key(n), "modified": lambda n: n.mtime or dt.datetime.min,
                "crc": lambda n: n.crc or 0}
        key = keys.get(col, keys["name"])
        dirs = sorted((n for n in nodes if n.is_dir), key=key, reverse=self.sort_rev)
        files = sorted((n for n in nodes if not n.is_dir), key=key, reverse=self.sort_rev)
        return dirs + files

    def sort_by(self, col):
        if col == self.sort_col:
            self.sort_rev = not self.sort_rev
        else:
            self.sort_col, self.sort_rev = col, False
        self.refresh()

    def refresh(self, select=None):
        t = self.tree
        t.delete(*t.get_children())
        self.row_nodes = {}
        arch = self.mode == "archive"
        t.configure(displaycolumns=[c[0] for c in COLS] if arch else ("size", "type", "modified"))
        nodes = self._sorted(self._nodes())
        want = None
        for i, n in enumerate(nodes):
            iid = str(i)
            self.row_nodes[iid] = n
            icon = ui.get_image("folder" if n.is_dir else "file:" + ui.file_kind(n.name), 16)
            vals = ("" if n.is_dir else core.human_size(n.size), "" if n.is_dir or not arch else core.human_size(n.packed),
                    ui.type_name(n.name, n.is_dir), ui.fmt_dt(n.mtime),
                    f"{n.crc:08X}" if n.crc is not None else "")
            t.insert("", "end", iid=iid, text=n.name if self.search_hits is None else n.path, image=icon, values=vals,
                     tags=("alt",) if i % 2 else ())
            if select is not None and (n.path == select or n.name == select):
                want = iid
        for key in ["#0"] + [c[0] for c in COLS]:
            base = "Name" if key == "#0" else dict((c[0], c[1]) for c in COLS)[key]
            mark = ""
            if (key == "#0" and self.sort_col == "name") or key == self.sort_col:
                mark = "  \u25B2" if not self.sort_rev else "  \u25BC"
            t.heading(key, text=base + mark)
        if want:
            t.selection_set(want)
            t.see(want)
        self._update_address()
        self._selection_changed()

    def _update_address(self):
        if self.mode == "archive":
            where = self.arc_path + (os.sep + self.sub.replace("/", os.sep) if self.sub else "")
            if self.search_hits is not None:
                where += "   (search results)"
            self.addr_var.set(where)
            self.root.title(f"{os.path.basename(self.arc_path)} - {core.APP_NAME}")
        else:
            self.addr_var.set(self.cwd)
            self.root.title(f"{os.path.basename(self.cwd.rstrip(chr(92) + '/')) or self.cwd} - {core.APP_NAME}")
            if os.name == "nt" and self.cwd[:3] in self._drive_list:
                self.drive_var.set(self.cwd[:3])

    def selected_nodes(self):
        return [self.row_nodes[i] for i in self.tree.selection() if i in self.row_nodes]

    def select_all(self):
        self.tree.selection_set(self.tree.get_children())

    def _selection_changed(self):
        sel = self.selected_nodes()
        nodes = list(self.row_nodes.values())
        nd, nf = sum(n.is_dir for n in nodes), sum(not n.is_dir for n in nodes)
        if sel:
            sd, sf = sum(n.is_dir for n in sel), sum(not n.is_dir for n in sel)
            parts = ([f"{sd} folder{'s' if sd != 1 else ''}"] if sd else []) + ([f"{sf} file{'s' if sf != 1 else ''}"] if sf else [])
            self.status_l.configure(text="Selected " + " and ".join(parts) +
                                    (f":  {core.human_size(sum(n.size for n in sel))}" if sf else ""))
        elif self.mode == "archive" and self.arc is not None and time.time() - self._msg_time > 8:
            es = [e for e in self.arc.entries() if not e.is_dir]
            lock = "\U0001F512 password protected   " if self.arc.encrypted else ""
            self.status_l.configure(text=f"{self.arc.label} archive   {lock}"
                                         f"{len(es):,} files, {core.human_size(sum(e.size for e in es))} unpacked")
        self.status_r.configure(text=f"{nd} folders, {nf} files" if self.search_hits is None else f"{len(nodes)} found")
        self._update_tools(sel)

    def _update_tools(self, sel):
        arch_sel = [n for n in sel if not n.is_dir and core.is_archive_name(n.name)]
        if self.mode == "fs":
            en = dict(add=True, extract=bool(arch_sel), test=bool(arch_sel), view=bool(sel), delete=bool(sel),
                      find=False, convert=bool(arch_sel), info=bool(arch_sel), repair=bool(arch_sel))
        else:
            en = dict(add=True, extract=True, test=True, view=any(not n.is_dir for n in sel) or bool(sel),
                      delete=bool(sel), find=True, convert=True, info=True,
                      repair=self.arc is not None and (self.arc.kind == "zip" or self.arc.label == "RAR"))
        for name, b in self.tool_btns.items():
            b.state(["!disabled"] if en.get(name) else ["disabled"])
        self.up_btn.state(["!disabled"])

    # ------------------------------------------------------ context menu
    def context_menu(self, event):
        row = self.tree.identify_row(event.y)
        if row and row not in self.tree.selection():
            self.tree.selection_set(row)
        elif not row:
            self.tree.selection_remove(self.tree.selection())
        sel = self.selected_nodes()
        m = tk.Menu(self.root, tearoff=0)
        if self.mode == "fs":
            arcs = [n for n in sel if not n.is_dir and core.is_archive_name(n.name)]
            if sel:
                if len(sel) == 1 and arcs:
                    p = sel[0]
                    stem = core.archive_stem(p.name)
                    m.add_command(label="Open archive", command=lambda: self.open_archive(p.path))
                    m.add_separator()
                    m.add_command(label="Extract files...", command=self.act_extract)
                    m.add_command(label="Extract Here", command=self.act_extract_here)
                    m.add_command(label=f'Extract to "{stem}\\"', command=lambda: self._extract_to_named(p))
                    m.add_command(label="Test archive", command=self.act_test)
                    m.add_separator()
                elif len(sel) == 1 and not sel[0].is_dir:
                    m.add_command(label="Open", command=self.open_selected)
                    m.add_separator()
                elif len(sel) == 1:
                    m.add_command(label="Open folder", command=self.open_selected)
                    m.add_separator()
                base = os.path.splitext(sel[0].name)[0] if len(sel) == 1 and not sel[0].is_dir else (
                    sel[0].name if len(sel) == 1 else os.path.basename(self.cwd.rstrip("\\/")) or "Archive")
                m.add_command(label="Add to archive...", command=self.act_add)
                m.add_command(label=f'Add to "{base}.zip"', command=lambda: self.quick_add("zip", [n.path for n in sel]))
                if core.can_create("7z"):
                    m.add_command(label=f'Add to "{base}.7z"', command=lambda: self.quick_add("7z", [n.path for n in sel]))
                m.add_separator()
                m.add_command(label="Delete", command=self.act_delete)
            else:
                m.add_command(label="Add files to archive...", command=self.act_add)
                m.add_command(label="Select all", command=self.select_all)
                m.add_command(label="Refresh", command=self.refresh)
        else:
            if sel:
                m.add_command(label="Open" if sel[0].is_dir else "View", command=self.open_selected)
                m.add_command(label="Extract to...", command=self.act_extract)
                m.add_separator()
                m.add_command(label="Delete from archive", command=self.act_delete)
            else:
                m.add_command(label="Extract all to...", command=self.act_extract)
                m.add_command(label="Add files...", command=self.act_add)
                m.add_command(label="Select all", command=self.select_all)
                m.add_command(label="Archive information", command=self.act_info)
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    # -------------------------------------------------------- actions
    def _fs_archives(self):
        return [n.path for n in self.selected_nodes() if not n.is_dir and core.is_archive_name(n.name)]

    def _target_archive(self):
        if self.mode == "archive":
            return self.arc_path
        a = self._fs_archives()
        return a[0] if a else None

    def act_add(self):
        if self.mode == "archive":
            m = tk.Menu(self.root, tearoff=0)
            m.add_command(label="Add files...", command=self._pick_files_to_add)
            m.add_command(label="Add folder...", command=self._pick_folder_to_add)
            b = self.tool_btns["add"]
            try:
                m.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())
            finally:
                m.grab_release()
            return
        sel = [n.path for n in self.selected_nodes()]
        if not sel:
            sel = list(filedialog.askopenfilenames(parent=self.root, title="Choose files to archive", initialdir=self.cwd))
        if sel:
            self.add_files(sel, dest_dir=self.cwd)

    def _pick_files_to_add(self):
        p = filedialog.askopenfilenames(parent=self.root, title="Add files to the archive")
        if p:
            self.add_to_open_archive(list(p))

    def _pick_folder_to_add(self):
        p = ui.ask_folder(self.root, None, "Add a folder to the archive")
        if p:
            self.add_to_open_archive([os.path.normpath(p)])

    def add_to_open_archive(self, paths):
        arc = self.arc
        is_rar = arc.label == "RAR"
        if (is_rar and not core.can_create("rar")) or (not is_rar and arc.kind not in ("zip", "tar", "7z")):
            ui.info_box(self.root, "Add files", f"Files cannot be added to {arc.label} archives here.\n"
                                                "Use Tools > Convert archive format first.")
            return
        fmt = "rar" if is_rar else ("tar" if arc.kind == "tar" else arc.kind)
        opts = core.AddOptions(fmt=fmt, level=int(settings["default_level"]), prefix=self.sub,
                               password=self.password if arc.encrypted and arc.kind == "zip" else None)
        path = self.arc_path
        self.arc.close()
        self.do_build(path, paths, opts, existing_password=self.password)

    def act_extract(self):
        if self.mode == "fs":
            arcs = self._fs_archives()
            if not arcs:
                ui.info_box(self.root, "Extract", "Select an archive in the list first.")
                return
            self.extract_archives(arcs)
            return
        sel = self.selected_nodes()
        names = [n.path for n in sel] if sel else None
        label = os.path.basename(self.arc_path)
        dest0 = os.path.dirname(self.arc_path)
        res = ui.ExtractDialog(self.root, label, dest0, core.archive_stem(self.arc_path), len(sel) or None).show()
        if not res:
            return
        strip = self.sub if names and self.search_hits is None else ""
        ok = self.run_extract(self.arc_path, res["dest"], names, strip, res["overwrite"], self.password)
        if ok and res["open_after"]:
            ui.reveal_folder(res["dest"])

    def act_extract_here(self):
        arcs = self._fs_archives() if self.mode == "fs" else [self.arc_path]
        for p in arcs:
            self.run_extract(p, os.path.dirname(p), None, "", "ask", self.password if self.mode == "archive" else None)
        self.after_change()

    def _extract_to_named(self, node):
        self.run_extract(node.path, os.path.join(os.path.dirname(node.path), core.archive_stem(node.name)), None, "", "ask")
        self.refresh()

    def act_test(self):
        p = self._target_archive()
        if not p:
            ui.info_box(self.root, "Test", "Select an archive in the list first.")
            return
        self.test_archive(p, self.password if self.mode == "archive" else None)

    def act_view(self):
        sel = self.selected_nodes()
        if not sel:
            return
        if self.mode == "fs":
            self.open_selected()
        elif not sel[0].is_dir:
            self.view_member(sel[0])
        else:
            self.open_selected()

    def view_member(self, node):
        tmp = core.new_temp_dir("view")
        strip = node.path.rpartition("/")[0]
        if not self.run_extract(self.arc_path, tmp, [node.path], strip, "overwrite", self.password):
            return
        final = os.path.join(tmp, core.clean_component(node.name))
        if not os.path.isfile(final):
            return
        ext = os.path.splitext(node.name.lower())[1]
        if ext in ui.TEXT_EXTS and os.path.getsize(final) < 5 * 1024 * 1024:
            raw = open(final, "rb").read()
            for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
                try:
                    text = raw.decode(enc)
                    break
                except (UnicodeDecodeError, UnicodeError):
                    continue
            ui.TextViewer(self.root, node.name, text, lambda: ui.open_with_default(final)).show()
        else:
            ui.open_with_default(final)

    def act_delete(self):
        sel = self.selected_nodes()
        if not sel:
            return
        names = ", ".join(n.name for n in sel[:3]) + ("..." if len(sel) > 3 else "")
        if self.mode == "archive":
            if settings["confirm_delete"] and not messagebox.askyesno(
                    core.APP_NAME, f"Delete {len(sel)} item(s) from the archive?\n\n{names}", parent=self.root):
                return
            path = self.arc_path
            self.arc.close()
            pw = self.password

            def work(job, dlg):
                core.delete_entries(path, [n.path for n in sel], job, pw)
            _v, exc, job = ui.run_job(self.root, "Deleting from " + os.path.basename(path), work)
            self.finish(exc, job, "Deleted.")
            self.reload_archive()
            return
        try:
            from send2trash import send2trash  # optional: moves to the Recycle Bin
        except Exception:
            send2trash = None
        warn = "" if send2trash else "\n\nThis cannot be undone."
        if settings["confirm_delete"] and not messagebox.askyesno(
                core.APP_NAME, f"Delete {len(sel)} item(s)?\n\n{names}{warn}", parent=self.root, icon="warning"):
            return
        for n in sel:
            try:
                if send2trash:
                    send2trash(n.path)
                else:
                    core.delete_path(n.path)
            except Exception as e:
                ui.error_box(self.root, f"Could not delete {n.name}:\n{e}")
        self.refresh()

    def act_find(self):
        if self.mode != "archive":
            return
        res = ui.FindDialog(self.root, getattr(self, "_last_find", "")).show()
        if not res:
            return
        pat, whole = res
        self._last_find = pat
        pl = pat.lower()
        wild = any(c in pl for c in "*?[")
        hits = []
        for e in self.arc.entries():
            if not whole and e.name.rpartition("/")[0] != self.sub:
                continue
            leaf = e.name.rpartition("/")[2].lower()
            if (fnmatch.fnmatchcase(leaf, pl) if wild else pl in leaf):
                hits.append(Node(e.name.rpartition("/")[2], e.name, e.is_dir, e.size, e.packed, e.mtime, e.crc, e.encrypted))
        self.search_hits = hits
        self.refresh()
        self.set_status(f"Found {len(hits)} item(s) for '{pat}'. Press Backspace to go back.")

    def act_convert(self):
        p = self._target_archive()
        if not p:
            ui.info_box(self.root, "Convert", "Open or select an archive first.")
            return
        self.convert_archive(p, self.password if self.mode == "archive" else None)

    def act_info(self):
        p = self._target_archive()
        if p:
            self.show_info(p)

    def act_repair(self):
        p = self._target_archive()
        if p:
            self.repair_archive(p)

    def act_comment(self):
        if self.mode != "archive":
            return
        zip_ok = self.arc.kind == "zip"
        txt = ui.CommentDialog(self.root, self.arc.comment(), zip_ok).show()
        if txt is None or not zip_ok or txt == self.arc.comment():
            return
        path = self.arc_path
        self.arc.close()
        try:
            core.set_zip_comment(path, txt)
        except Exception as e:
            ui.error_box(self.root, f"Could not save the comment:\n{e}")
        self.reload_archive()

    def act_settings(self):
        dlg = ui.SettingsDialog(self.root)
        if dlg.show() and dlg.theme_changed:
            ui.apply_theme(self.root)
            self.root.configure(menu="")
            self._build_menu()
            self._build_toolbar()
            self.tree.tag_configure("alt", background=THEME["row_alt"])
            self.up_btn.configure(image=ui.get_image("up", 16))
            ui.set_window_icon(self.root)
            self.refresh()
        else:
            self.refresh()


def type_key(n):
    return ui.type_name(n.name, n.is_dir).lower()


# ====================================================================
#  Explorer-launched flows (no main window)
# ====================================================================
class ShellRunner(Operations):
    def __init__(self, root):
        self.root = root

    def run(self, verb, fmt, paths):
        paths = [p for p in paths if os.path.exists(p)]
        if not paths:
            return
        if verb == "add":
            self.add_files(paths)
        elif verb == "add-quick":
            self.quick_add(fmt, paths)
        elif verb == "extract":
            self.extract_archives(paths)
        elif verb == "extract-here":
            for p in paths:
                self.run_extract(p, os.path.dirname(os.path.abspath(p)), None, "", "ask")
        elif verb == "extract-to":
            for p in paths:
                self.run_extract(p, os.path.join(os.path.dirname(os.path.abspath(p)), core.archive_stem(p)), None, "", "ask")
        elif verb == "test":
            for p in paths:
                self.test_archive(p)


# ====================================================================
#  Entry point
# ====================================================================
SHELL_VERBS = {"add", "add-quick", "extract", "extract-here", "extract-to", "test"}


def _prepare_process():
    if os.name == "nt":
        try:
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                ctypes.windll.user32.SetProcessDPIAware()
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Wajeeha.Archiver")
        except Exception:
            pass


def _show_callback_error(exc, val, tb):
    where = log_error(val) if val is not None else ""
    try:
        messagebox.showerror(core.APP_NAME, f"Something unexpected went wrong:\n{val}\n\n"
                             + (f"Details were saved to:\n{where}" if where else ""))
    except Exception:
        pass


def make_root():
    root = TkinterDnD.Tk() if TkinterDnD is not None else tk.Tk()
    root.report_callback_exception = _show_callback_error
    ui.apply_theme(root)
    if os.name == "nt":
        try:
            from . import icons
            ico = os.path.join(config.APP_DATA, "wajeeha.ico")
            if not os.path.isfile(ico):
                os.makedirs(config.APP_DATA, exist_ok=True)
                icons.make_ico(ico)
            root.iconbitmap(default=ico)
        except Exception:
            pass
    return root


def run_gui(open_path=None):
    root = make_root()
    MainWindow(root, open_path)
    root.mainloop()


def run_shell(verb, fmt, paths):
    root = make_root()
    root.withdraw()
    try:
        ShellRunner(root).run(verb, fmt, paths)
    except Exception as e:  # noqa
        where = log_error(e)
        messagebox.showerror(core.APP_NAME, f"Something unexpected went wrong:\n{e}\n\n{where}")
    root.destroy()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    _prepare_process()
    if argv and argv[0] == "--register-shell":
        n = shell.register(cascade=bool(settings["cascade_menu"]))
        print(f"Added the right-click menu ({n} registry values).")
        return 0
    if argv and argv[0] == "--unregister-shell":
        shell.unregister()
        print("Removed the right-click menu.")
        return 0
    if argv and argv[0] == "--export-reg" and len(argv) > 1:
        spec = shell.build_spec(shell.command_prefix(), shell.icon_value(), bool(settings["cascade_menu"]))
        with open(argv[1], "w", encoding="utf-16") as f:
            f.write(shell.to_reg(spec))
        print("Saved", argv[1])
        return 0
    if argv and argv[0] in SHELL_VERBS:
        verb, rest, fmt, key = argv[0], argv[1:], None, argv[0]
        if verb == "add-quick":
            if len(rest) < 2:
                return 0
            fmt, rest, key = rest[0], rest[1:], "add-quick-" + rest[0]
        if not rest:
            return 0
        paths = shell.collect(key, rest)
        if paths is None:
            return 0
        run_shell(verb, fmt, paths)
        return 0
    open_path = None
    if argv and argv[0] == "open" and len(argv) > 1:
        open_path = argv[1]
    elif argv and os.path.isfile(argv[0]):
        open_path = argv[0]
    run_gui(open_path)
    return 0
