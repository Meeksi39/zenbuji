"""Optional Nautilus extension: a proper right-click context-menu entry.

This needs the `nautilus-python` package (on Bazzite/Silverblue, layer it with
`rpm-ostree install nautilus-python` or run Files inside a toolbox). Install it
to ~/.local/share/nautilus-python/extensions/ — install.sh does this for you if
nautilus-python is present; otherwise the Scripts entry (zenbuji-script.sh) is
used instead, which needs no extra packages.
"""

import os
import subprocess
from urllib.parse import unquote, urlparse

import gi

gi.require_version("Nautilus", "4.0")
from gi.repository import GObject, Nautilus  # noqa: E402

ZENBUJI = os.environ.get("ZENBUJI_CMD", "zenbuji")
TEXT_SUFFIXES = (".txt", ".md", ".srt", ".ass", ".vtt", ".csv", ".json")


def _path(file_info) -> str:
    return unquote(urlparse(file_info.get_uri()).path)


class ZenbujiMenuProvider(GObject.GObject, Nautilus.MenuProvider):
    def _activate(self, _menu, files):
        for f in files:
            path = _path(f)
            if os.path.isfile(path):
                try:
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        text = fh.read(4000)
                except OSError:
                    continue
                subprocess.Popen([ZENBUJI, "popup", text])
                return
        subprocess.Popen([ZENBUJI, "popup", "--selection"])

    def get_file_items(self, files):
        if not files:
            return []
        wanted = any(
            _path(f).lower().endswith(TEXT_SUFFIXES) for f in files
        )
        if not wanted:
            return []
        item = Nautilus.MenuItem(
            name="Zenbuji::lookup",
            label="zenbuji: furigana + translation",
            tip="Show furigana and EN/DE translation for this text",
        )
        item.connect("activate", self._activate, files)
        return [item]
