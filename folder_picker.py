#!/usr/bin/python3
"""Open a GTK folder chooser outside the Quickshell process."""

from __future__ import annotations

import os
import sys

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402


def choose_folder(initial_path: str) -> int:
    Gtk.init()
    loop = GLib.MainLoop()
    result_code = 1

    chooser = Gtk.FileDialog(title="Choose Codex profiles folder", modal=True)

    initial_path = os.path.abspath(os.path.expanduser(initial_path))
    if os.path.isdir(initial_path):
        chooser.set_initial_folder(Gio.File.new_for_path(initial_path))

    def on_selected(dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        nonlocal result_code
        try:
            selected = dialog.select_folder_finish(result)
            path = selected.get_path()
            if path:
                print(path, flush=True)
                result_code = 0
        except GLib.Error:
            pass
        loop.quit()

    chooser.select_folder(None, None, on_selected)
    loop.run()
    return result_code


if __name__ == "__main__":
    start = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~")
    raise SystemExit(choose_folder(start))
