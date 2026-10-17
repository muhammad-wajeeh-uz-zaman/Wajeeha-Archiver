# -*- coding: utf-8 -*-
"""User settings, stored as JSON in %APPDATA%\\WajeehaArchiver\\settings.json"""
import json
import os

APP_DATA = os.path.join(os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config"),
                        "WajeehaArchiver")

DEFAULTS = {
    "theme": "light",            # light | dark
    "default_format": "zip",
    "default_level": 3,
    "confirm_delete": True,
    "show_hidden": False,
    "open_dest_after_extract": True,
    "cascade_menu": True,
    "shell_asked": False,
    "geometry": "1060x660",
    "last_dir": "",
    "recent_archives": [],
    "recent_dests": [],
    "sort_col": "name",
    "sort_rev": False,
}


class Settings:
    def __init__(self, path=None):
        self.path = path or os.path.join(APP_DATA, "settings.json")
        self.data = dict(DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                self.data.update(stored)
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def __getitem__(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def __setitem__(self, key, value):
        self.data[key] = value

    def add_recent(self, key, value, limit=12):
        items = [v for v in self.data.get(key, []) if v != value]
        items.insert(0, value)
        self.data[key] = items[:limit]


settings = Settings()
