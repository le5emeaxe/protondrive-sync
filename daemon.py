#!/usr/bin/env python3
"""
Proton Drive Sync — background daemon with a tray icon, à la
nextcloud-client-desktop, backed by the official proton-drive CLI.

Runs a periodic bidirectional sync between ~/protondrive (configurable) and
/my-files on Proton Drive, shows a tray icon with status, and offers an
activity window listing recent sync events.

Dependencies:
    pip install trayer --break-system-packages
    sudo pacman -S python-gobject gtk4 libadwaita   # Arch
    # On GNOME you also need the AppIndicator extension:
    #   https://extensions.gnome.org/extension/615/appindicator-support/

Run manually:
    python3 daemon.py

Or install as a systemd --user service (see protondrive-sync.service).
"""

import json
import os
import subprocess
import sys
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib

from trayer import TrayIcon

import about_window
import activity_window
import backend
import config
import icons
import local_watcher
import settings_window
import state_db
import sync_engine
import trayer_patch

STATE_DIR = os.path.expanduser("~/.local/share/proton-drive-sync")
STATE_DB_PATH = os.path.join(STATE_DIR, "state.db")
STATUS_PATH = os.path.expanduser("~/.cache/proton-drive-sync/status.json")

SPINNER_FRAME_COUNT = 8
SPINNER_INTERVAL_MS = 200


class SyncDaemon:
    def __init__(self):
        # Sets WM_CLASS on X11 (and feeds the app_id used for window
        # matching on Wayland) for every window this app creates — must be
        # called before any window/GtkApplication activity.
        GLib.set_prgname("protondrive")
        GLib.set_application_name("Proton Drive Sync")

        os.makedirs(STATE_DIR, exist_ok=True)
        self.cfg = config.load_config()
        self.db = state_db.StateDB(STATE_DB_PATH)

        self.paused = False
        self.syncing = False
        self.activity_win = None
        self.settings_win = None
        self.about_win = None
        self.timer_source_id = None
        self.spinner_source_id = None
        self.spinner_frame = 0
        self.watcher = None
        self.suppress_watch_until = 0.0
        self.authenticated = None  # None = not checked yet
        self.account_email = None

        self.app = Adw.Application(application_id="fr.andytoys.protondrivesync")
        self.app.connect("activate", self.on_activate)

    # ---------- lifecycle ----------
    def on_activate(self, app):
        app.hold()  # keep the process alive even though no window is shown

        icons.install_icons()

        # Never trust a computed name — scan what's REALLY on disk and use
        # that. Falls back to a standard system icon (guaranteed to exist)
        # for anything missing, printing a warning so the mismatch is
        # visible instead of silently showing nothing.
        discovered = icons.discover_installed_icons()

        def resolve(base, fallback="folder"):
            name = discovered.get(base)
            if name is None:
                print(f"ATTENTION: icône introuvable sur le disque pour '{base}', "
                      f"utilisation de secours '{fallback}'", file=sys.stderr)
                return fallback
            return name

        self.icon_idle = resolve("protondrive-sync-idle")
        self.icon_dryrun = resolve("protondrive-sync-dryrun")
        self.icon_paused = resolve("protondrive-sync-paused")
        self.icon_error = resolve("protondrive-sync-error", fallback="dialog-warning")
        self.icon_syncing_frames = [
            resolve(f"protondrive-sync-syncing-{i}", fallback="view-refresh")
            for i in range(SPINNER_FRAME_COUNT)
        ]

        # trayer doesn't expose IconThemePath (StatusNotifierItem property
        # telling the host where to find icons outside the system theme),
        # so hosts that don't already search our custom icon location can
        # register the item fine but never actually draw anything. Point it
        # at the same hicolor tree we just installed into.
        # The GNOME extension's IconThemePath handling appears to do a flat
        # lookup (IconThemePath + "/" + name + ".svg"), not the usual
        # hicolor-style size/context subdirectory search (confirmed by its
        # own log: "Impossible to lookup icon for 'utilities-terminal' in
        # .../hicolor" — it failed on a STANDARD icon too, once we gave it
        # a theme ROOT instead of a flat directory). Point it straight at
        # the flat directory that actually contains our icon files.
        trayer_patch.apply(icon_theme_path=icons.DEST_DIR)

        self.tray = TrayIcon(
            app_id="fr.andytoys.protondrivesync",
            title="Proton Drive Sync",
            icon_name=self.icon_dryrun if self.cfg["dry_run"] else self.icon_idle,
        )
        self.tray.set_left_click(self.show_activity)
        self._rebuild_menu()
        self.tray.setup()

        self._schedule_timer(self.cfg.get("interval_seconds", 900))
        GLib.timeout_add_seconds(5, self._initial_sync)  # small delay after launch

        os.makedirs(self.cfg["local_root"], exist_ok=True)
        self.watcher = local_watcher.LocalWatcher(self.cfg["local_root"], on_change=self.on_local_change)

        self.check_auth()

    def _initial_sync(self):
        self.sync_now()
        return False  # one-shot

    def _schedule_timer(self, interval_seconds):
        """(Re)schedule the periodic sync timer. Safe to call anytime,
        including while already running, to apply a new interval live."""
        if self.timer_source_id is not None:
            GLib.source_remove(self.timer_source_id)
        interval = max(60, int(interval_seconds))
        self.timer_source_id = GLib.timeout_add_seconds(interval, self._on_timer)

    def _on_timer(self):
        if not self.paused:
            self.sync_now()
        return True  # keep repeating

    def on_local_change(self):
        """Called (debounced) by LocalWatcher when a file/folder was added,
        removed, or moved under the local root."""
        if self.paused or self.syncing:
            return
        if time.monotonic() < self.suppress_watch_until:
            # Almost certainly our own sync's downloads still settling —
            # not a genuine user-initiated change.
            return
        self.sync_now()

    # ---------- authentication ----------
    def check_auth(self, then=None):
        """Runs the (blocking) CLI-based auth check in a background
        thread. `then`, if given, is called after the state is updated —
        used to chain a sync attempt right after a fresh login."""
        def work():
            try:
                ok, detail = backend.check_auth()
                email = backend.get_account_email(self.cfg["remote_root"]) if ok else None
            except Exception as e:  # noqa: BLE001 — never let this thread die uncaught
                ok, email, detail = False, None, str(e)
            GLib.idle_add(self._on_auth_checked, ok, email, detail, then)

        threading.Thread(target=work, daemon=True).start()

    def _on_auth_checked(self, ok, email, detail, then):
        was_authenticated = self.authenticated
        self.authenticated = ok
        self.account_email = email
        if ok != was_authenticated:
            self._rebuild_menu()
        if not ok and detail:
            print(f"Vérification d'authentification: {detail}", file=sys.stderr)
        if then:
            then()
        return False

    def run_auth_login(self):
        """Triggered from the tray menu when not authenticated. Launches
        `proton-drive auth login`, which typically opens the system
        browser — the user completes the login there."""
        self.db.log("auth_login", "", "Authentification lancée (vérifiez votre navigateur)…", "info")

        def work():
            error = None
            try:
                backend.run_auth_login()
            except backend.ProtonDriveError as e:
                error = str(e)
            GLib.idle_add(self._on_auth_login_done, error)

        threading.Thread(target=work, daemon=True).start()

    def _on_auth_login_done(self, error):
        if error:
            self.db.log("auth_login", "", f"Échec de l'authentification: {error}", "error")
        else:
            self.db.log("auth_login", "", "Authentification terminée", "ok")
        # Re-check status, then try a sync right away if we're now logged in.
        self.check_auth(then=self.sync_now)
        return False

    def _rebuild_menu(self):
        self.tray.menu_items.clear()
        self.tray.add_menu_item("Synchroniser maintenant", callback=self.sync_now)
        self.tray.add_menu_item("Voir l'activité", callback=self.show_activity)
        self.tray.add_menu_item("Ouvrir le dossier local", callback=self.open_folder)
        self.tray.add_menu_separator()

        if self.authenticated is False:
            self.tray.add_menu_item("⚠ Authentification", callback=self.run_auth_login)
            self.tray.add_menu_separator()
        elif self.authenticated is True:
            account_label = f"Compte : {self.account_email}" if self.account_email else "Authentifié"
            self.tray.add_menu_item(account_label, callback=None, enabled=False)
            self.tray.add_menu_separator()

        self.tray.add_menu_item("Reprendre" if self.paused else "Mettre en pause",
                                 callback=self.toggle_pause)
        self.tray.add_menu_item("Paramètres…", callback=self.show_settings)
        self.tray.add_menu_separator()
        mode = "Mode: SIMULATION (dry-run)" if self.cfg["dry_run"] else "Mode: actif"
        self.tray.add_menu_item(mode, callback=None, enabled=False)
        self.tray.add_menu_item(f"Toutes les {self.cfg['interval_seconds'] // 60} min", callback=None, enabled=False)
        self.tray.add_menu_separator()
        self.tray.add_menu_item("À propos", callback=self.show_about)
        self.tray.add_menu_item("Quitter", callback=self.quit)
        self.tray.update_menu()

    # ---------- sync ----------
    def sync_now(self):
        if self.syncing:
            return
        self.syncing = True
        self._start_spinner()

        def work():
            engine = sync_engine.SyncEngine(
                local_root=self.cfg["local_root"],
                remote_root=self.cfg["remote_root"],
                db=self.db,
                dry_run=self.cfg["dry_run"],
                sync_deletions=self.cfg["sync_deletions"],
                logger=lambda msg: None,
            )
            error = None
            try:
                engine.run()
            except Exception as e:  # noqa: BLE001
                error = str(e)
            GLib.idle_add(self._on_sync_done, error)

        threading.Thread(target=work, daemon=True).start()

    def _start_spinner(self):
        self.spinner_frame = 0
        if self.spinner_source_id is not None:
            self._remove_spinner_source()
        self._safe_change_icon(self.icon_syncing_frames[self.spinner_frame % SPINNER_FRAME_COUNT])
        self.spinner_source_id = GLib.timeout_add(SPINNER_INTERVAL_MS, self._spinner_tick)

    def _spinner_tick(self):
        self.spinner_frame += 1
        self._safe_change_icon(self.icon_syncing_frames[self.spinner_frame % SPINNER_FRAME_COUNT])
        return True  # keep animating until _stop_spinner() removes it

    def _stop_spinner(self):
        if self.spinner_source_id is not None:
            self._remove_spinner_source()
            self.spinner_source_id = None

    def _remove_spinner_source(self):
        # If change_icon() ever raised inside _spinner_tick (e.g. a
        # transient D-Bus hiccup), GLib silently drops that timeout on its
        # own without us knowing — leaving self.spinner_source_id stale.
        # GLib.source_remove() on a stale id raises, which (if uncaught)
        # would abort _on_sync_done() BEFORE it gets to restore the
        # idle/badge icon. Swallow that specific failure so the icon
        # always gets reset regardless.
        try:
            GLib.source_remove(self.spinner_source_id)
        except Exception as e:
            print(f"(spinner déjà arrêté, ignoré: {e})", file=sys.stderr)

    def _safe_change_icon(self, icon_name):
        try:
            self.tray.change_icon(icon_name)
        except Exception as e:
            print(f"Erreur en changeant l'icône du tray (ignorée): {e}", file=sys.stderr)

    def _set_final_icon(self, icon_name, dbus_status, sync_status):
        self._safe_change_icon(icon_name)
        self.tray.change_status(dbus_status)
        self._write_status_file(sync_status)
        # gnome-shell loads each icon asynchronously; after a burst of rapid
        # spinner frame changes, a late-resolving stale frame can overwrite
        # the display *after* we've already switched to the final icon.
        # Re-sending the same final icon shortly after acts as a cheap,
        # harmless "nudge" that resolves this without needing to know the
        # exact timing of the shell's internal race.
        def nudge():
            self._safe_change_icon(icon_name)
            return False  # one-shot

        GLib.timeout_add(400, nudge)

    def _write_status_file(self, sync_status):
        """Petit fichier lu par l'extension Nautilus (embl/badge sur le
        dossier ~/protondrive, façon client Nextcloud) — voir
        nautilus_protondrive_emblem.py. Inclut le PID pour que le lecteur
        puisse détecter si le démon s'est arrêté depuis (sinon le badge
        resterait figé sur le dernier statut connu indéfiniment, même
        démon éteint)."""
        try:
            os.makedirs(os.path.dirname(STATUS_PATH), exist_ok=True)
            with open(STATUS_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "status": sync_status,  # "synced" | "error" | "paused" | "dryrun"
                    "local_root": self.cfg["local_root"],
                    "last_sync": time.time(),
                    "pid": os.getpid(),
                }, f)
        except OSError as e:
            print(f"Impossible d'écrire le fichier de statut (ignoré): {e}", file=sys.stderr)

    def _on_sync_done(self, error):
        self.syncing = False
        self._stop_spinner()
        # Give the filesystem a couple seconds to settle before trusting
        # local change events again — this sync's own downloads/deletes
        # would otherwise immediately retrigger the watcher.
        self.suppress_watch_until = time.monotonic() + 2.0
        if error:
            self._set_final_icon(self.icon_error, "NeedsAttention", "error")
            if self._looks_like_auth_error(error) and self.authenticated is not False:
                self.authenticated = False
                self.account_email = None
                self._rebuild_menu()
        elif self.paused:
            self._set_final_icon(self.icon_paused, "Active", "paused")
        elif self.cfg["dry_run"]:
            self._set_final_icon(self.icon_dryrun, "Active", "dryrun")
        else:
            self._set_final_icon(self.icon_idle, "Active", "synced")
        if self.activity_win is not None:
            self.activity_win.refresh()
        return False  # don't repeat (this is called via idle_add, one-shot)

    @staticmethod
    def _looks_like_auth_error(error_text):
        """Heuristic only — this CLI version doesn't expose a stable error
        code we can match on, just free-form text, so this may need
        adjusting if the wording differs in practice."""
        text = error_text.lower()
        return any(kw in text for kw in ("auth", "login", "unauthorized", "unauthenticated", "session", "credential"))

    # ---------- menu actions ----------
    def toggle_pause(self):
        self.paused = not self.paused
        if self.paused:
            self._safe_change_icon(self.icon_paused)
        else:
            self._safe_change_icon(self.icon_dryrun if self.cfg["dry_run"] else self.icon_idle)
        self._rebuild_menu()

    def open_folder(self):
        subprocess.Popen(["xdg-open", self.cfg["local_root"]])

    def show_activity(self):
        # Reload config in case it was hand-edited since startup, so the
        # activity window always reflects the current scope/mode.
        self.cfg = config.load_config()
        if self.activity_win is None:
            self.activity_win = activity_window.ActivityWindow(self.app, self.db, self.cfg)
            self.activity_win.connect("close-request", self._on_activity_closed)
        else:
            self.activity_win.cfg = self.cfg
            self.activity_win.refresh()
        self.activity_win.present()

    def _on_activity_closed(self, *_):
        self.activity_win = None
        return False

    def show_settings(self):
        if self.settings_win is None:
            self.settings_win = settings_window.SettingsWindow(self.app, self.cfg, self.on_settings_applied)
            self.settings_win.connect("close-request", self._on_settings_closed)
        self.settings_win.present()

    def _on_settings_closed(self, *_):
        self.settings_win = None
        return False

    def show_about(self):
        if self.about_win is None:
            self.about_win = about_window.AboutWindow(self.app, self.icon_idle)
            self.about_win.connect("close-request", self._on_about_closed)
        self.about_win.present()

    def _on_about_closed(self, *_):
        self.about_win = None
        return False

    def on_settings_applied(self, new_cfg):
        """Called live (on every toggle/spin change) from SettingsWindow."""
        self.cfg = new_cfg
        self._schedule_timer(self.cfg["interval_seconds"])
        if not self.syncing and not self.paused:
            self._safe_change_icon(self.icon_dryrun if self.cfg["dry_run"] else self.icon_idle)
        self._rebuild_menu()
        if self.activity_win is not None:
            self.activity_win.cfg = self.cfg
            self.activity_win.refresh()

    def quit(self):
        if self.watcher is not None:
            self.watcher.stop()
        self.app.quit()

    def run(self):
        self.app.run(None)


if __name__ == "__main__":
    SyncDaemon().run()
