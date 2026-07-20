"""
Watches a local directory tree for changes using Gio.FileMonitor — GLib's
native wrapper around inotify on Linux. No extra process, no polling, no
new dependency: Gio is already part of PyGObject.

Gio.FileMonitor only watches the direct children of one directory, so this
sets up one monitor per directory in the tree and adds/removes monitors as
subfolders are created/deleted.
"""

import os

from gi.repository import Gio, GLib


class LocalWatcher:
    def __init__(self, root, on_change, debounce_ms=1500):
        self.root = root
        self.on_change = on_change
        self.debounce_ms = debounce_ms
        self._monitors = {}  # path -> Gio.FileMonitor
        self._debounce_source = None
        self._watch_tree(root)

    # ---------- setup ----------
    def _watch_tree(self, path):
        self._watch_dir(path)
        try:
            with os.scandir(path) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        self._watch_tree(entry.path)
        except OSError:
            pass

    def _watch_dir(self, path):
        if path in self._monitors:
            return
        gfile = Gio.File.new_for_path(path)
        try:
            monitor = gfile.monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
        except GLib.Error:
            return
        monitor.connect("changed", self._on_dir_changed)
        self._monitors[path] = monitor

    def _unwatch_dir(self, path):
        monitor = self._monitors.pop(path, None)
        if monitor:
            monitor.cancel()

    # ---------- events ----------
    def _on_dir_changed(self, monitor, gfile, other_file, event_type):
        path = gfile.get_path()

        if event_type == Gio.FileMonitorEvent.CREATED and path and os.path.isdir(path):
            # Start watching a newly created subfolder (and anything
            # already inside it, e.g. a folder pasted in with content).
            self._watch_tree(path)
        elif event_type in (Gio.FileMonitorEvent.DELETED, Gio.FileMonitorEvent.MOVED_OUT):
            if path in self._monitors:
                self._unwatch_dir(path)

        self._schedule_debounced_callback()

    def _schedule_debounced_callback(self):
        # Coalesce bursts (e.g. copying many files at once, or our own
        # sync writing several downloads) into a single sync trigger.
        if self._debounce_source is not None:
            GLib.source_remove(self._debounce_source)
        self._debounce_source = GLib.timeout_add(self.debounce_ms, self._fire)

    def _fire(self):
        self._debounce_source = None
        self.on_change()
        return False  # one-shot

    def stop(self):
        for path in list(self._monitors):
            self._unwatch_dir(path)
