OPTIONAL HELPER TOOLS      (the app works without them - each one adds a feature)
=========================================================================
Put the files in THIS folder. When you build the program with build_exe.bat this folder is copied to
dist\WajeehaArchiver\tools automatically (or just drop the files in there yourself).


RAR  - open, extract AND create
-------------------------------
Copy these from the folder where your RAR program is installed:

    Rar.exe       Creates RAR archives, and also opens/extracts them.  Stand-alone: one file, no DLLs.
    UnRAR.exe     Only opens/extracts RAR. Not needed if you copied Rar.exe.  Stand-alone.
    rarreg.key    Your licence key, if you have one.  Keep it in the SAME folder as Rar.exe.
    Default.SFX   Only needed for "Self-extracting archive (.exe)".  Keep it beside Rar.exe.

You do NOT need: the main program, RarExt*.dll (its own right-click menu), *.chm help, Uninstall.exe.

Also run:  pip install rarfile    (lets Wajeeha Archiver browse RAR files quickly)

With Rar.exe present you also get: RAR in the format list, "Add to RAR archive" in the right-click menu,
recovery records, solid archives, self-extracting .exe, password with hidden file names, Repair for RAR,
and adding/deleting files inside an existing RAR.

Rar.exe is licensed software. Use your own licensed copy on your own computers and do not hand it to others.


ISO, CAB, WIM, ARJ, LZH, DMG, VHD ...  and another way to open RAR
-------------------------------------------------------------------
Copy from a free 7-Zip install (C:\Program Files\7-Zip):

    7z.exe
    7z.dll

(If 7-Zip is already installed you do not need to copy anything - it is found automatically.)
