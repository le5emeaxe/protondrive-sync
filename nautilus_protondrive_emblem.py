#!/usr/bin/env python3
"""
Extension Nautilus : affiche un embl (badge) sur l'icône du dossier
~/protondrive lui-même, indiquant l'état de la synchronisation — façon
client Nextcloud (petit rond vert superposé au dossier).

Lit le fichier de statut écrit par proton-drive-sync (daemon.py) après
chaque cycle de synchro : ~/.cache/proton-drive-sync/status.json
Se met à jour en direct via Gio.FileMonitor (pas de polling).

Installation :
    mkdir -p ~/.local/share/nautilus-python/extensions
    cp nautilus_protondrive_emblem.py ~/.local/share/nautilus-python/extensions/
    nautilus -q
"""

import json
import os

import gi

try:
    gi.require_version("Nautilus", "4.0")
except ValueError:
    pass

from gi.repository import Gio, GLib, GObject, Nautilus

CONFIG_PATH = os.path.expanduser("~/.config/proton-drive-sync/config.json")
STATUS_PATH = os.path.expanduser("~/.cache/proton-drive-sync/status.json")

# Doit correspondre à EMBLEM_VERSION dans icon_version.py (côté
# proton-drive-sync) — dupliqué ici volontairement plutôt qu'importé, ce
# fichier vivant seul dans ~/.local/share/nautilus-python/extensions/ sans
# accès garanti aux autres modules du projet.
EMBLEM_VERSION = 1

EMBLEM_BY_STATUS = {
    "synced": f"protondrive-emblem-synced-v{EMBLEM_VERSION}",
    "error": f"protondrive-emblem-error-v{EMBLEM_VERSION}",
    "paused": f"protondrive-emblem-paused-v{EMBLEM_VERSION}",
    "dryrun": f"protondrive-emblem-dryrun-v{EMBLEM_VERSION}",
    # Démon arrêté/planté : même pastille grise que "paused" — pas de
    # nouvel asset dédié, la nuance (pause volontaire vs démon éteint) n'a
    # pas semblé justifier une 5e icône pour l'instant.
    "stopped": f"protondrive-emblem-paused-v{EMBLEM_VERSION}",
}


def get_local_root():
    default = os.path.realpath(os.path.expanduser("~/protondrive"))
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return os.path.realpath(data.get("local_root", default))
    except (OSError, json.JSONDecodeError):
        return default


def read_status_file():
    try:
        with open(STATUS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def is_daemon_alive(pid):
    """Vérifie que le PID existe ET correspond bien à notre démon (pas un
    process quelconque qui aurait hérité de ce PID depuis) — sans ça, le
    badge peut rester figé sur le dernier statut connu (souvent "synced",
    donc vert) même si le démon a été arrêté depuis longtemps."""
    if not pid:
        return False
    cmdline_path = f"/proc/{pid}/cmdline"
    try:
        with open(cmdline_path, "rb") as f:
            cmdline = f.read().decode("utf-8", errors="replace")
    except OSError:
        return False  # /proc/<pid> absent -> le process n'existe plus
    return "daemon.py" in cmdline


def get_effective_status():
    """Statut réel à afficher : celui du fichier si le démon qui l'a écrit
    est toujours vivant, sinon "stopped" (démon éteint/planté depuis)."""
    data = read_status_file()
    if not data:
        return None
    if not is_daemon_alive(data.get("pid")):
        return "stopped"
    return data.get("status")


class ProtonDriveEmblemExtension(GObject.GObject, Nautilus.InfoProvider):
    # Si le démon est tué brutalement (kill -9, crash, fermeture de
    # session), plus rien n'écrit dans status.json — le FileMonitor ne se
    # déclenche donc plus jamais. Cette relecture périodique est le seul
    # moyen de détecter ce cas sans attendre un hasard de rafraîchissement
    # (changer de dossier, etc.).
    RECHECK_INTERVAL_SECONDS = 30

    def __init__(self):
        self._local_root = get_local_root()
        self._known_files = {}  # chemin -> Nautilus.FileInfo, pour pouvoir invalider plus tard
        self._monitor = None
        self._start_watch()
        GLib.timeout_add_seconds(self.RECHECK_INTERVAL_SECONDS, self._periodic_recheck)

    def _periodic_recheck(self):
        self._invalidate_local_root()
        return True  # se répète indéfiniment

    def _invalidate_local_root(self):
        info = self._known_files.get(self._local_root)
        if info is not None:
            info.invalidate_extension_info()

    def _start_watch(self):
        os.makedirs(os.path.dirname(STATUS_PATH), exist_ok=True)
        gfile = Gio.File.new_for_path(STATUS_PATH)
        try:
            self._monitor = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
            self._monitor.connect("changed", self._on_status_changed)
        except GLib.Error:
            self._monitor = None

    def _on_status_changed(self, monitor, gfile, other_file, event_type):
        # Force Nautilus à ré-appeler update_file_info pour le dossier suivi,
        # pour que le badge reflète le nouveau statut sans avoir à rafraîchir
        # la vue manuellement.
        self._invalidate_local_root()

    def update_file_info(self, file):
        local_path = file.get_location().get_path()
        if not local_path:
            return
        local_path = os.path.realpath(local_path)
        if local_path != self._local_root:
            return

        self._known_files[local_path] = file

        status = get_effective_status()
        emblem = EMBLEM_BY_STATUS.get(status)
        if emblem:
            file.add_emblem(emblem)
