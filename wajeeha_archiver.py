# -*- coding: utf-8 -*-
"""Wajeeha Archiver - launcher.   Run:  python wajeeha_archiver.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    try:
        from wajeeha.app import main
    except ImportError as exc:
        if "tkinter" in str(exc).lower():
            msg = ("Python's Tk component (tkinter) is missing.\n"
                   "Install Python from python.org and keep 'tcl/tk and IDLE' ticked.")
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(0, msg, "Wajeeha Archiver", 0x10)
            except Exception:
                print(msg)
            sys.exit(1)
        raise
    sys.exit(main())
