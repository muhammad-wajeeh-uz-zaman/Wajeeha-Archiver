# Wajeeha Archiver

Create, open and extract archives from one friendly window - and from the Explorer right-click menu.

---

## 1. Run it (3 steps)

1. Install **Python 3.9 or newer** from python.org (during setup keep **"tcl/tk and IDLE"** ticked and tick **"Add python.exe to PATH"**).
2. Open this folder, click the address bar, type `cmd` and press Enter. Then run:
   ```
   pip install -r requirements.txt
   ```
   (Optional but recommended - it unlocks 7Z, password-protected ZIP, RAR opening, drag & drop and Recycle-Bin delete.)
3. Double-click **run.bat**.

## 2. Get the right-click menu

Either double-click **install_right_click_menu.bat**, or open the app and go to
**Settings > Explorer integration > Add to right-click menu**.

You then get, when you right-click:

| On this...        | You get                                                                               |
|-------------------|---------------------------------------------------------------------------------------|
| any file / folder | Add to archive...  /  Add to ZIP archive  /  Add to 7Z archive                         |
| an archive        | Extract files...  /  Extract Here  /  Extract to subfolder  /  Test archive  /  Open |

* Select **many files** and choose "Add to archive..." - you get **one** dialog for all of them.
* **Windows 11:** classic menu entries live under **Show more options** (or press **Shift+F10**).
* To remove everything: **remove_right_click_menu.bat**. Nothing needs administrator rights.
* To make double-click open archives with this app: right-click an archive > *Open with* > *Wajeeha Archiver* > *Always*.

## 3. Using the window

* **File list** - browses your disk. Double-click a folder to enter it, double-click an archive to open it, `Backspace` goes up.
* **Toolbar** - Add, Extract To, Test, View, Delete, Find, Convert, Info, Repair (also `Alt+A`, `Alt+E`, `Alt+T`, `Alt+V`, `Alt+F`, `Alt+I`, `Alt+R`).
* **Add** shows format, compression level, password, split-into-parts, skip-patterns and a comment box.
* **Extract To** has a folder picker, "ask / replace / skip / keep both", and update modes.
* **Convert** re-packs any archive into another format. **Repair** rebuilds a damaged ZIP.
* Drag files onto the window (needs `tkinterdnd2`) to create an archive, or onto an open archive to add to it.
* Light and dark theme: **Settings**.

## 4. Formats

| Format | Open | Create | Passwords | Needs |
|---|---|---|---|---|
| ZIP | yes | yes | AES-256 | built in (`pyzipper` for passwords) |
| TAR, TAR.GZ, TAR.BZ2, TAR.XZ | yes | yes | - | built in |
| GZ, BZ2, XZ (single file) | yes | - | - | built in |
| 7Z | yes | yes | AES-256 (+ hide names) | `pip install py7zr` |
| RAR | yes | yes | yes (+ hidden names) | open: `pip install rarfile` + `UnRAR.exe` or `Rar.exe` or 7-Zip; create: `Rar.exe` - see `tools\README.txt` |
| ISO, CAB, WIM, ARJ, LZH, CPIO, RPM, DEB, DMG, VHD ... | yes | - | - | 7-Zip (`7z.exe`) |
| Split parts `name.zip.001`, `.002` ... | yes | yes | - | built in |

**RAR files:** copy `Rar.exe` (+ `rarreg.key`, `Default.SFX`) from your RAR installation into the `tools` folder - that unlocks
creating RAR archives, recovery records, self-extracting `.exe` files and Repair. `UnRAR.exe` alone is enough just to open them.
Files are recognised by their **content**, so archives with a wrong or missing extension still open.

## 5. Make a normal program (.exe)

Double-click **build_exe.bat** and wait a few minutes. You get `dist\WajeehaArchiver\WajeehaArchiver.exe`.
Keep the whole `WajeehaArchiver` folder together (copy it anywhere, e.g. `C:\Program Files\`), open the exe once and
use **Settings > Explorer integration** so the right-click menu points at the exe.
(A folder build starts instantly, which matters for right-click commands. For a single-file exe replace `--windowed`
with `--onefile --windowed` in `build_exe.bat` - it just starts slower.)

## 6. If the right-click menu does not show up

1. Open **Settings > Explorer integration** and press **Add / refresh right-click menu**. The line under the buttons says whether it is installed and what program it starts.
2. **Windows 11:** classic entries are hidden behind **Show more options** (or **Shift+F10**). Press the Windows 11 button in the same tab to show them straight away (Explorer restarts once).
3. After moving or rebuilding the program the entries are refreshed automatically the next time you open the window.
4. Selecting a lot of files? Windows hides classic entries above 15 selected files unless the entry allows it - this app's entries allow up to 100.
5. **Windows Sandbox / a fresh PC:** everything is reset each time it starts, so the program offers to add the menu on first launch.
6. Any error is shown in a message and saved to `%APPDATA%\WajeehaArchiver\error.log`.

## 7. Safety and checks

* Archives are never allowed to write outside the folder you chose (`..\` and absolute paths are blocked, link entries are skipped).
* New archives are written to a temporary name first, so a cancelled or failed job never leaves a half-written archive.
* Run `python selftest.py` to check the archive engine on your machine.
* If something unexpected happens, details are saved to `%APPDATA%\WajeehaArchiver\error.log`.

## Files

```
wajeeha_archiver.py     start here
wajeeha/core.py         archive engine (all formats)
wajeeha/shell.py        Explorer right-click integration
wajeeha/ui.py           theme + dialogs
wajeeha/app.py          main window + command line
wajeeha/icons.py        built-in vector icons (no image files needed)
selftest.py             engine self-test
```

Command line: `wajeeha_archiver.py add|extract|extract-here|extract-to|test|open <paths>`,
`--register-shell`, `--unregister-shell`, `--export-reg <file.reg>`.
