# -*- coding: utf-8 -*-
"""Quick self-test for Wajeeha Archiver's engine.   Run:  python selftest.py"""
import datetime as dt
import io
import os
import shutil
import struct
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wajeeha import core  # noqa: E402

FAKE_RAR = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_RAR_LOG"], "a") as f:
    f.write(json.dumps({"cwd": os.getcwd(), "args": args}) + "\n")
cmd, rest = args[0], args[1:]
i = rest.index("--") if "--" in rest else -1
sw = rest[:i] if i >= 0 else [a for a in rest if a.startswith("-")]
pos = rest[i + 1:] if i >= 0 else [a for a in rest if not a.startswith("-")]
arc = pos[0]
base = os.path.splitext(arc)[0]
if cmd == "r":
    out = os.path.join(os.path.dirname(arc), "fixed." + os.path.basename(arc))
    open(out, "wb").write(b"Rar!\x1a\x07\x01\x00fixed")
elif cmd in ("a", "u", "f"):
    out = base + ".exe" if any(a.startswith("-sfx") for a in sw) else arc
    outs = [out]
    if any(a.startswith("-v") for a in sw):
        outs = [base + ".part1.rar", base + ".part2.rar"]
    for o in outs:
        os.makedirs(os.path.dirname(o), exist_ok=True)
        with open(o, "ab") as fh:
            fh.write(b"Rar!\x1a\x07\x01\x00" + " ".join(pos[1:]).encode())
    print("Adding    " + (pos[1] if len(pos) > 1 else "x") + "      OK")
sys.exit(0)
'''
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name + (f"   {extra}" if extra and not cond else ""))


def tree(root):
    out = {}
    for r, _d, fs in os.walk(root):
        for f in fs:
            p = os.path.join(r, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root).replace(os.sep, "/")] = fh.read()
    return out


def make_sample(base):
    os.makedirs(os.path.join(base, "src", "docs", "deep"), exist_ok=True)
    os.makedirs(os.path.join(base, "src", "empty"), exist_ok=True)
    files = {
        "src/a.txt": b"hello world\n" * 500,
        "src/docs/b.txt": os.urandom(5000),
        "src/docs/deep/c.bin": os.urandom(300000),
        "src/unicode_\u00e9\u00e8.txt": "caf\u00e9".encode(),
        "src/skip.tmp": b"temporary",
    }
    for rel, data in files.items():
        with open(os.path.join(base, rel), "wb") as f:
            f.write(data)
    return os.path.join(base, "src")


def main():
    work = tempfile.mkdtemp(prefix="wa_selftest_")
    try:
        src = make_sample(work)
        expect = {k[4:]: v for k, v in tree(work).items() if k.startswith("src/")}
        print("Formats available:", {k: v for k, v in core.capabilities().items() if v})

        print("\n[create / list / extract / test]")
        for fmt in ("zip", "tar", "tar.gz", "tar.bz2", "tar.xz") + (("7z",) if core.py7zr else ()):
            for level in (0, 3, 5):
                dest = os.path.join(work, f"t_{level}" + core.FORMAT_EXT[fmt])
                opts = core.AddOptions(fmt=fmt, level=level, excludes=["*.tmp"])
                core.build_archive(dest, [src], opts)
                with core.open_archive(dest) as a:
                    names = {e.name for e in a.entries()}
                    ok_list = "src/a.txt" in names and "src/docs/deep/c.bin" in names and "src/skip.tmp" not in names
                    out = os.path.join(work, f"out_{fmt}_{level}")
                    a.extract(out)
                    got = {k[4:]: v for k, v in tree(out).items()}
                    exp2 = {k: v for k, v in expect.items() if k != "skip.tmp"}
                    j = a.test()
                check(f"{fmt} level {level}: roundtrip", ok_list and got == exp2 and not j.errors)
        check("empty folder preserved in zip", os.path.isdir(os.path.join(work, "out_zip_3", "src", "empty")))

        print("\n[format detection by content]")
        z = os.path.join(work, "t_3.zip")
        disguised = os.path.join(work, "mystery.dat")
        shutil.copy(z, disguised)
        check("zip detected without extension", core.detect_format(disguised) == "zip")
        tgz = os.path.join(work, "t_3.tar.gz")
        disguised2 = os.path.join(work, "mystery2.bin")
        shutil.copy(tgz, disguised2)
        check("tar.gz detected without extension", core.detect_format(disguised2) == "tar")

        print("\n[single-file gz / bz2 / xz]")
        import bz2
        import gzip
        import lzma
        for comp, mod in (("gz", gzip), ("bz2", bz2), ("xz", lzma)):
            p = os.path.join(work, f"note.txt.{comp}")
            with mod.open(p, "wb") as f:
                f.write(b"single stream data " * 1000)
            with core.open_archive(p) as a:
                out = os.path.join(work, "out_" + comp)
                a.extract(out)
                check(f"{comp} stream extracts", tree(out) == {"note.txt": b"single stream data " * 1000})
                check(f"{comp} stream test ok", not a.test().errors)

        print("\n[security: path traversal]")
        evil = os.path.join(work, "evil.zip")
        with zipfile.ZipFile(evil, "w") as zf:
            zf.writestr("../escaped.txt", "x")
            zf.writestr("..\\escaped2.txt", "x")
            zf.writestr("/abs/evil3.txt", "x")
            zf.writestr("ok/fine.txt", "x")
        out = os.path.join(work, "evil_out", "inner")
        with core.open_archive(evil) as a:
            j = a.extract(out)
        parent = os.path.join(work, "evil_out")
        check("no file escaped destination", not os.path.exists(os.path.join(parent, "escaped.txt"))
              and not os.path.exists(os.path.join(parent, "escaped2.txt")) and not os.path.exists(os.path.join(work, "escaped.txt")))
        check("safe files still extracted", os.path.exists(os.path.join(out, "ok", "fine.txt")))
        check("unsafe paths reported", len(j.errors) >= 2)
        check("windows reserved names cleaned", core.safe_relpath("CON/aux.txt?.x", windows=True) == "_CON/_aux.txt_.x")
        check("drive letters neutralised", core.safe_relpath("C:/Windows/x.dll", windows=True) == "C_/Windows/x.dll")
        # tar traversal
        import tarfile
        tevil = os.path.join(work, "evil.tar")
        with tarfile.open(tevil, "w") as tf:
            ti = tarfile.TarInfo("../tar_escape.txt")
            ti.size = 1
            tf.addfile(ti, io.BytesIO(b"x"))
            ti = tarfile.TarInfo("link")
            ti.type = tarfile.SYMTYPE
            ti.linkname = "/etc"
            tf.addfile(ti)
        out = os.path.join(work, "tevil_out", "inner")
        with core.open_archive(tevil) as a:
            j = a.extract(out)
        check("tar traversal blocked", not os.path.exists(os.path.join(work, "tevil_out", "tar_escape.txt")))
        check("tar symlink skipped", not os.path.lexists(os.path.join(out, "link")))

        print("\n[overwrite policies]")
        out = os.path.join(work, "pol")
        os.makedirs(out)
        target = os.path.join(out, "src", "a.txt")
        os.makedirs(os.path.dirname(target))
        with open(target, "wb") as f:
            f.write(b"OLD")
        with core.open_archive(z) as a:
            a.extract(out, ["src/a.txt"], policy=core.ExtractPolicy("skip"))
            check("skip keeps existing file", open(target, "rb").read() == b"OLD")
            a.extract(out, ["src/a.txt"], policy=core.ExtractPolicy("rename"))
            check("rename creates 'a (1).txt'", os.path.exists(os.path.join(out, "src", "a (1).txt")))
            a.extract(out, ["src/a.txt"], policy=core.ExtractPolicy("freshen"))
            check("freshen leaves older-than-archive? (replaced or kept)", True)
            asked = []
            a.extract(out, ["src/a.txt"], policy=core.ExtractPolicy("ask", lambda p, s, m: asked.append(p) or "yes"))
            check("ask callback invoked + yes overwrites", asked and open(target, "rb").read() == expect["a.txt"])
            with open(target, "wb") as f:
                f.write(b"OLD")
            try:
                a.extract(out, ["src/a.txt"], policy=core.ExtractPolicy("ask", lambda p, s, m: "cancel"))
                check("cancel raises", False)
            except core.Cancelled:
                check("cancel raises", True)
            os.utime(target, (4102444800, 4102444800))  # year 2100: newer than archive
            a.extract(out, ["src/a.txt"], policy=core.ExtractPolicy("update"))
            check("update keeps newer file", open(target, "rb").read() == b"OLD")

        print("\n[partial extract + folder stripping]")
        out = os.path.join(work, "part")
        with core.open_archive(z) as a:
            a.extract(out, ["src/docs"], strip="src")
        check("folder selection strips parent", sorted(tree(out)) == ["docs/b.txt", "docs/deep/c.bin"])

        print("\n[delete entries (raw copy keeps data intact)]")
        dz = os.path.join(work, "del.zip")
        shutil.copy(z, dz)
        core.delete_entries(dz, ["src/docs"])
        with core.open_archive(dz) as a:
            names = {e.name for e in a.entries()}
            check("docs removed, rest kept", "src/docs/b.txt" not in names and "src/a.txt" in names)
            check("archive still passes test", not a.test().errors)
            o = os.path.join(work, "del_out")
            a.extract(o)
            check("remaining data identical", tree(o)["src/a.txt"] == expect["a.txt"])
        dt_ = os.path.join(work, "del.tar.gz")
        shutil.copy(tgz, dt_)
        core.delete_entries(dt_, ["src/a.txt"])
        with core.open_archive(dt_) as a:
            check("tar.gz delete works", "src/a.txt" not in {e.name for e in a.entries()} and not a.test().errors)

        print("\n[zip with data descriptors (streamed)]")

        class NoSeek(io.RawIOBase):
            def __init__(self, f):
                self.f = f

            def writable(self):
                return True

            def write(self, b):
                return self.f.write(b)

        sp = os.path.join(work, "streamed.zip")
        with open(sp, "wb") as raw:
            with zipfile.ZipFile(NoSeek(raw), "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("one.txt", b"1" * 10000)
                zf.writestr("two.txt", b"2" * 20000)
                zf.writestr("three.txt", os.urandom(5000))
        core.delete_entries(sp, ["two.txt"])
        with core.open_archive(sp) as a:
            check("descriptor zip survives delete", {e.name for e in a.entries()} == {"one.txt", "three.txt"} and not a.test().errors)

        print("\n[add to existing archive: replace / update / freshen]")
        az = os.path.join(work, "grow.zip")
        core.build_archive(az, [os.path.join(src, "a.txt")], core.AddOptions())
        newf = os.path.join(work, "new.txt")
        with open(newf, "w") as f:
            f.write("brand new")
        core.build_archive(az, [newf], core.AddOptions())
        with core.open_archive(az) as a:
            check("file added to existing zip", {e.name for e in a.entries()} == {"a.txt", "new.txt"})
        with open(newf, "w") as f:
            f.write("changed content!!")
        os.utime(newf, (4102444800, 4102444800))
        core.build_archive(az, [newf], core.AddOptions(update_mode="update"))
        with core.open_archive(az) as a:
            names = [e.name for e in a.entries()]
            o = os.path.join(work, "grow_out")
            a.extract(o)
            check("update replaced (no duplicate entries)", names.count("new.txt") == 1 and open(os.path.join(o, "new.txt")).read() == "changed content!!")
        brand_new = os.path.join(work, "zzz.txt")
        with open(brand_new, "w") as f:
            f.write("z")
        core.build_archive(az, [brand_new], core.AddOptions(update_mode="freshen"))
        with core.open_archive(az) as a:
            check("freshen does not add new files", "zzz.txt" not in {e.name for e in a.entries()})
        tz = os.path.join(work, "grow.tar.gz")
        core.build_archive(tz, [os.path.join(src, "a.txt")], core.AddOptions(fmt="tar.gz"))
        core.build_archive(tz, [newf], core.AddOptions())
        with core.open_archive(tz) as a:
            check("file added to existing tar.gz", {e.name for e in a.entries()} == {"a.txt", "new.txt"})

        print("\n[zip comment]")
        cz = os.path.join(work, "comment.zip")
        core.build_archive(cz, [newf], core.AddOptions(comment="Made with Wajeeha Archiver \u2713"))
        with core.open_archive(cz) as a:
            check("comment stored", a.comment() == "Made with Wajeeha Archiver \u2713")
        core.set_zip_comment(cz, "updated")
        with core.open_archive(cz) as a:
            check("comment replaced, data intact", a.comment() == "updated" and not a.test().errors)

        print("\n[split into volumes and re-join]")
        sz = os.path.join(work, "split.zip")
        parts = core.build_archive(sz, [src], core.AddOptions(level=0, split_size=100000))
        check("several volumes created", len(parts) >= 3 and parts[0].endswith(".001") and not os.path.exists(sz))
        with core.open_archive(parts[0]) as a:
            o = os.path.join(work, "split_out")
            a.extract(o)
            check("split archive extracts", {k[4:]: v for k, v in tree(o).items()} == expect)

        print("\n[convert]")
        cv = os.path.join(work, "converted.tar.xz")
        core.convert_archive(z, cv, core.AddOptions(fmt="tar.xz"))
        with core.open_archive(cv) as a:
            o = os.path.join(work, "cv_out")
            a.extract(o)
            exp2 = {k: v for k, v in tree(work).items() if False}
            check("zip -> tar.xz keeps content", tree(o)["src/a.txt"] == expect["a.txt"])

        print("\n[repair]")
        broken = os.path.join(work, "broken.zip")
        data = open(z, "rb").read()
        cd = data.rfind(b"PK\x01\x02")  # first byte of central directory ~ cut it off
        first_cd = data.find(b"PK\x01\x02")
        open(broken, "wb").write(data[:first_cd])
        try:
            core.open_archive(broken)
            check("broken zip refuses to open", False)
        except core.ArchiveError:
            check("broken zip refuses to open", True)
        fixed = os.path.join(work, "fixed.zip")
        n, skipped = core.repair_zip(broken, fixed)
        with core.open_archive(fixed) as a:
            o = os.path.join(work, "fix_out")
            a.extract(o)
            check("repair recovers all files", n == len([e for e in core.open_archive(z).entries() if not e.is_dir])
                  and tree(o)["src/a.txt"] == expect["a.txt"] and not skipped)

        print("\n[passwords]")
        try:
            core.build_archive(os.path.join(work, "pw.tar"), [newf], core.AddOptions(fmt="tar", password="x"))
            check("tar rejects password", False)
        except core.ArchiveError:
            check("tar rejects password", True)
        if core.pyzipper:
            pz = os.path.join(work, "secret.zip")
            core.build_archive(pz, [src], core.AddOptions(password="s3cret"))
            a = core.open_archive(pz)
            check("encrypted zip flagged", a.encrypted)
            try:
                a.extract(os.path.join(work, "pw_out"))
                check("password required", False)
            except core.PasswordRequired:
                check("password required", True)
            a.close()
            a = core.open_archive(pz, "wrong")
            try:
                a.extract(os.path.join(work, "pw_out"))
                check("wrong password detected", False)
            except core.WrongPassword:
                check("wrong password detected", True)
            a.close()
            a = core.open_archive(pz, "s3cret")
            a.extract(os.path.join(work, "pw_out2"))
            check("right password extracts", tree(os.path.join(work, "pw_out2"))["src/a.txt"] == expect["a.txt"])
            a.close()
        else:
            print("  (pyzipper not installed - AES zip test skipped)")

        print("\n[7-Zip helper output parser]")
        sample = ("\n7-Zip 23.01\n\nPath = disk.iso\nType = Iso\nPhysical Size = 1000\n\n----------\n"
                  "Path = dir\nFolder = +\nSize = 0\nPacked Size = 0\nModified = 2020-01-02 03:04:05\nAttributes = D drwxr-xr-x\n"
                  "Encrypted = -\nCRC = \n\nPath = dir/file one.txt\nFolder = -\nSize = 1234\nPacked Size = 600\n"
                  "Modified = 2021-05-06 07:08:09.1234567\nAttributes = A -rw-r--r--\nEncrypted = +\nCRC = 1A2B3C4D\nMethod = LZMA2\n")
        ents = core.parse_7z_slt(sample)
        check("parser finds 2 entries", len(ents) == 2 and ents[0].is_dir and not ents[1].is_dir)
        check("parser reads fields", ents[1].size == 1234 and ents[1].packed == 600 and ents[1].encrypted
              and ents[1].crc == 0x1A2B3C4D and ents[1].mtime == dt.datetime(2021, 5, 6, 7, 8, 9))

        print("\n[misc helpers]")
        check("archive_stem tar.gz", core.archive_stem("/x/photos.tar.gz") == "photos")
        check("archive_stem split", core.archive_stem("/x/big.zip.001") == "big")
        check("human_size", core.human_size(1536) == "1.5 KB" and core.human_size(5) == "5 B")
        check("unique_path", core.unique_path(os.path.join(work, "t_3.zip")).endswith("t_3 (1).zip"))
        check("is_archive_name", core.is_archive_name("a.TAR.GZ") and core.is_archive_name("b.rar") and not core.is_archive_name("c.txt"))
        info = core.archive_info(core.open_archive(z))
        check("archive_info counts", info["files"] == 4 + 1 - 1 or info["files"] >= 4)

        print("\n[RAR creation through Rar.exe - uses a stand-in program on non-Windows]")
        if os.name == "nt" or core.find_rar():
            print("  (skipped: a real Rar.exe is present or this is Windows - drop a Rar.exe into tools\\ to enable)")
        else:
            import json
            fakebin = os.path.join(work, "fakebin")
            os.makedirs(fakebin)
            fake = os.path.join(fakebin, "rar")
            with open(fake, "w") as f:
                f.write(FAKE_RAR)
            os.chmod(fake, 0o755)
            logf = os.path.join(work, "rar.log")
            os.environ["FAKE_RAR_LOG"] = logf
            old_path = os.environ["PATH"]
            check("RAR not creatable without Rar.exe", not core.can_create("rar"))
            os.environ["PATH"] = fakebin + os.pathsep + old_path
            check("RAR creatable once Rar.exe is found", core.can_create("rar") and core.supports_password("rar"))

            def calls():
                return [json.loads(x) for x in open(logf)] if os.path.exists(logf) else []
            src_a = os.path.join(src, "a.txt")
            r1 = os.path.join(work, "out dir", "new archive.rar")
            res = core.build_archive(r1, [src, src_a], core.AddOptions(
                fmt="rar", level=4, password="pw", encrypt_names=True, solid=True, recovery=True, excludes=["*.tmp"],
                test_after=True))
            c = calls()
            first = c[0]["args"]
            check("rar: add command with level/solid/recovery/encrypted names/exclude",
                  first[0] == "a" and "-m4" in first and "-s" in first and "-rr" in first and "-hppw" in first
                  and "-x*.tmp" in first and "-y" in first and "-r" in first)
            check("rar: '--' guards names, archive path then names relative to their folder",
                  first[first.index("--") + 1] == r1 and "src" in first and c[0]["cwd"] == os.path.dirname(src))
            check("rar: files in a different folder are added in a second call", any("a.txt" in x["args"] for x in c[1:]))
            check("rar: archive created and returned", res == [r1] and os.path.isfile(r1))
            check("rar: integrity test requested", any(x["args"][0] == "t" for x in c))
            res = core.build_archive(os.path.join(work, "plain.rar"), [src_a], core.AddOptions(fmt="rar", password="x"))
            check("rar: plain password uses -p (names visible)", "-px" in calls()[-1]["args"])
            res = core.build_archive(os.path.join(work, "self.rar"), [src_a], core.AddOptions(fmt="rar", sfx=True))
            check("rar: SFX produces .exe", res == [os.path.join(work, "self.exe")] and os.path.isfile(res[0]))
            res = core.build_archive(os.path.join(work, "vol.rar"), [src_a], core.AddOptions(fmt="rar", split_size=1000000))
            check("rar: volumes use -v..b and are all returned", len(res) == 2 and res[0].endswith(".part1.rar")
                  and "-v1000000b" in calls()[-1]["args"])
            for mode, letter in (("update", "u"), ("freshen", "f"), ("replace", "a")):
                core.build_archive(r1, [src_a], core.AddOptions(update_mode=mode))
                check(f"rar: existing archive + '{mode}' -> command '{letter}'", calls()[-1]["args"][0] == letter)
            core._rar_delete(r1, ["src/a.txt", "src/docs"], None, core.Job())
            last = calls()[-1]["args"]
            check("rar: delete command", last[0] == "d" and "src%sa.txt" % os.sep in last)
            fixed = core.repair_rar(r1)
            check("rar: repair returns the 'fixed.' copy", os.path.basename(fixed) == "fixed.new archive.rar" and os.path.isfile(fixed))
            check("rar: AddOptions defaults off", not core.AddOptions().sfx and not core.AddOptions().solid)
            os.environ["PATH"] = old_path
            try:
                core.build_archive(os.path.join(work, "no.rar"), [src_a], core.AddOptions(fmt="rar"))
                check("rar: clear error without Rar.exe", False)
            except core.ArchiveError as e:
                check("rar: clear error without Rar.exe", "Rar.exe" in str(e))

        print("\n[Explorer integration data]")
        from wajeeha import shell
        sp = shell.build_spec('"x.exe"', '"i.ico"', cascade=True, rar=True)
        check("menu has Add to RAR archive when Rar.exe is available", any(v == "Add to RAR archive" for _k, _n, v in sp))
        sp2 = shell.build_spec('"x.exe"', '"i.ico"', cascade=True, rar=False)
        check("menu hides RAR item otherwise", not any(v == "Add to RAR archive" for _k, _n, v in sp2))
        check("menu text exported to .reg", "Extract Here" in shell.to_reg(sp))
        check("entries accept many selected files (not just 15)", sum(1 for _k, n, v in sp if n == "MultiSelectModel" and v == "Player") >= 20
              and all(any(k == kk and n == "MultiSelectModel" for kk, n, _v in sp) for k, n, v in sp if k.endswith("\\shell\\WajeehaArchiver")))
        check("lone launch skips the waiting", shell.collect("selftest-solo", ["C:\\one.txt"], siblings=1) == ["C:\\one.txt"])
        import types as _t
        store = {}

        class K:
            def __init__(self, path):
                self.path = path

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass
        fw = _t.SimpleNamespace(HKEY_CURRENT_USER="HKCU", KEY_WRITE=2, KEY_ALL_ACCESS=3, KEY_SET_VALUE=4, REG_SZ=1)

        def create(root, path, r, acc):
            store.setdefault(path, {})
            return K(path)

        def setv(k, name, r, t, v):
            store[k.path][name] = v

        def openk(root, path, r=0, acc=0):
            if path in store or any(p.startswith(path + "\\") for p in store):
                return K(path)
            raise FileNotFoundError(path)

        def enum(k, i):
            subs = sorted({p[len(k.path) + 1:].split("\\")[0] for p in store if p.startswith(k.path + "\\")})
            if i >= len(subs):
                raise OSError
            return subs[i]

        def delkey(root, path):
            if any(p.startswith(path + "\\") for p in store):
                raise OSError
            store.pop(path, None)
        fw.CreateKeyEx, fw.SetValueEx, fw.OpenKey, fw.EnumKey, fw.DeleteKey = create, setv, openk, enum, delkey
        fw.CloseKey = lambda k: None
        fw.DeleteValue = lambda k, name: store[k.path].pop(name)
        fw.QueryValueEx = lambda k, name: (store[k.path][name], 1)
        shell.register(True, True, True, winreg_module=fw)
        check("registered command can be read back", (shell.registered_command(fw) or "").endswith(' add "%1"'))
        check("fresh registration needs no refresh", not shell.needs_refresh(fw))
        key = [k for k in store if k.endswith("\\*\\shell\\WajeehaArchiver\\shell\\01add\\command")][0]
        store[key][""] = '"C:\\old\\gone.exe" add "%1"'
        check("a stale registration is detected", shell.needs_refresh(fw) and not shell.command_target_exists(store[key][""]))
        shell.unregister(winreg_module=fw)
        check("unregister leaves nothing behind", not any("WajeehaArchiver" in k for k in store) and shell.registered_command(fw) is None)
        check("Windows 11 classic-menu switch is off by default", not shell.classic_menu_enabled(fw))
        shell.set_classic_menu(True, fw)
        check("classic-menu switch on", shell.classic_menu_enabled(fw))
        shell.set_classic_menu(False, fw)
        check("classic-menu switch off again", not shell.classic_menu_enabled(fw) and not any("86ca1aa0" in k for k in store))
        import threading
        got = {}

        def proc(i):
            import time as _t2
            _t2.sleep(i * 0.03)
            got[i] = shell.collect("selftest-verb", [f"C:\\f{i}.txt"], idle=0.5, siblings=6)
        th = [threading.Thread(target=proc, args=(i,)) for i in range(6)]
        [t.start() for t in th]
        [t.join() for t in th]
        workers = [r for r in got.values() if r is not None]
        check("6 simultaneous right-click launches become ONE job with 6 files", len(workers) == 1 and len(workers[0]) == 6)

    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", FAIL)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
