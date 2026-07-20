#!/usr/bin/env python3
"""
Extension Nautilus : ajoute "Partager via Proton Drive" au menu contextuel
d'un fichier situé sous le dossier local synchronisé par proton-drive-sync
(~/protondrive par défaut — le mapping local <-> distant est lu depuis
~/.config/proton-drive-sync/config.json pour rester cohérent si vous
changez les valeurs par défaut).

Au clic : génère un lien de partage via `proton-drive sharing set-url`,
affiche une fenêtre avec l'URL, et permet de l'envoyer par e-mail via
`swaks` (partage@mail.fr -> 192.168.1.6:25, sans TLS ni auth).

Les sous-processus (proton-drive, swaks) sont lancés via Gio.Subprocess
(API asynchrone native de GLib), pas via threading.Thread + subprocess.run :
un thread Python brut lancé depuis l'intérieur du process Nautilus s'est
révélé pouvoir être affamé du GIL pendant plusieurs minutes (contention
avec les threads internes de Nautilus, ex. génération de miniatures) —
Gio.Subprocess s'intègre nativement à la boucle GLib déjà utilisée par
Nautilus et évite ce problème.

Installation :
    sudo pacman -S nautilus-python swaks          # Arch
    # ou : sudo apt install python3-nautilus swaks  # Debian/Ubuntu

    mkdir -p ~/.local/share/nautilus-python/extensions
    cp nautilus_protondrive_share.py ~/.local/share/nautilus-python/extensions/
    nautilus -q   # redémarre Nautilus pour charger l'extension
"""

import json
import os
import time

import gi

try:
    gi.require_version("Nautilus", "4.0")
except ValueError:
    pass
try:
    gi.require_version("Gtk", "4.0")
except ValueError:
    pass

from gi.repository import Gio, GLib, GObject, Gtk, Nautilus

GTK4 = Gtk.get_major_version() >= 4

CONFIG_PATH = os.path.expanduser("~/.config/proton-drive-sync/config.json")
PROTON_DRIVE_BIN = "proton-drive"

FROM_ADDRESS = "partage@mail.fr"
SMTP_SERVER = "192.168.1.6"
SMTP_PORT = "25"

TIMING_LOG_PATH = os.path.expanduser("~/.cache/nautilus-protondrive-share-timing.log")


def _log_timing(label):
    """Instrumentation de diagnostic — peut être retirée une fois le
    fonctionnement confirmé stable."""
    try:
        os.makedirs(os.path.dirname(TIMING_LOG_PATH), exist_ok=True)
        with open(TIMING_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{time.monotonic():.3f}  {label}\n")
    except Exception:  # noqa: BLE001
        pass


def load_sync_config():
    """Réutilise la config de proton-drive-sync pour connaître le mapping
    dossier local <-> dossier distant, avec un repli raisonnable si le
    fichier n'existe pas encore."""
    cfg = {"local_root": os.path.expanduser("~/protondrive"), "remote_root": "/my-files"}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for key in cfg:
            if key in data:
                cfg[key] = data[key]
    except (OSError, json.JSONDecodeError):
        pass
    return cfg


def local_to_remote_path(local_path, cfg):
    """Convertit un chemin local absolu en chemin distant Proton Drive.
    Retourne None si le fichier n'est pas sous local_root."""
    local_root = os.path.realpath(cfg["local_root"])
    local_path = os.path.realpath(local_path)
    if not (local_path == local_root or local_path.startswith(local_root + os.sep)):
        return None
    rel = os.path.relpath(local_path, local_root)
    remote_root = cfg["remote_root"].rstrip("/")
    if rel == ".":
        return remote_root
    return remote_root + "/" + rel.replace(os.sep, "/")


def _run_async(argv, on_done):
    """Lance argv via Gio.Subprocess (async, intégré à la boucle GLib —
    pas de threading.Thread). on_done(returncode, stdout, stderr, error)
    est appelé sur la boucle principale une fois terminé ; error est une
    chaîne si le lancement lui-même a échoué (binaire introuvable etc.),
    sinon None."""
    _log_timing(f"Gio.Subprocess lancement: {' '.join(argv)}")
    try:
        proc = Gio.Subprocess.new(
            argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
        )
    except GLib.Error as e:
        _log_timing(f"Gio.Subprocess ÉCHEC au lancement: {e}")
        on_done(None, "", "", str(e))
        return

    def _on_communicate_done(source, result):
        _log_timing("Gio.Subprocess communicate terminé")
        try:
            ok, stdout, stderr = source.communicate_utf8_finish(result)
        except GLib.Error as e:
            on_done(None, "", "", str(e))
            return
        on_done(source.get_exit_status(), stdout or "", stderr or "", None)

    proc.communicate_utf8_async(None, None, _on_communicate_done)


def get_share_url_async(remote_path, callback):
    """callback(url, error) — error est None en cas de succès."""
    argv = [PROTON_DRIVE_BIN, "sharing", "set-url", "-j", remote_path]

    def on_done(returncode, stdout, stderr, launch_error):
        if launch_error:
            callback(None, launch_error)
            return
        if returncode != 0:
            callback(None, stderr.strip() or stdout.strip() or f"Code de sortie {returncode}")
            return
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as e:
            callback(None, f"Réponse JSON inattendue: {e}\n{stdout[:500]}")
            return
        # Confirmé par un test réel : l'URL vit sous data["publicLink"]["url"].
        public_link = data.get("publicLink") or {}
        url = public_link.get("url")
        if not url:
            callback(None, f"URL introuvable dans la réponse: {data}")
            return
        callback(url, None)

    _run_async(argv, on_done)


def send_share_email_async(to_address, filename, url, callback):
    """callback(error) — error est None en cas de succès."""
    argv = [
        "swaks",
        "--to", to_address,
        "--from", FROM_ADDRESS,
        "--server", f"{SMTP_SERVER}:{SMTP_PORT}",
        "--h-Subject", f"Partage Proton Drive : {filename}",
        "--body", f"Voici le lien de partage pour « {filename} » :\n\n{url}\n",
    ]

    def on_done(returncode, stdout, stderr, launch_error):
        if launch_error:
            callback(launch_error)
            return
        if returncode != 0:
            callback(stderr.strip() or stdout.strip() or f"Code de sortie {returncode}")
            return
        callback(None)

    _run_async(argv, on_done)


def _box_add(box, widget):
    """Box packing differs between GTK3 (pack_start) and GTK4 (append)."""
    if GTK4:
        box.append(widget)
    else:
        box.pack_start(widget, False, False, 0)


class ShareWindow(Gtk.Window):
    """Fenêtre simple (pas Gtk.Dialog — .run() n'existe plus en GTK4)
    affichant l'URL de partage et un champ pour l'envoyer par e-mail."""

    def __init__(self, filename, url):
        super().__init__(title="Partager via Proton Drive")
        self.set_default_size(440, 240)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        if GTK4:
            box.set_margin_top(14)
            box.set_margin_bottom(14)
            box.set_margin_start(14)
            box.set_margin_end(14)
            self.set_child(box)
        else:
            box.set_border_width(14)
            self.add(box)

        _box_add(box, Gtk.Label(label=f"Fichier : {filename}", xalign=0))
        _box_add(box, Gtk.Label(label="Lien de partage :", xalign=0))

        url_entry = Gtk.Entry()
        url_entry.set_text(url)
        url_entry.set_editable(False)
        _box_add(box, url_entry)

        _box_add(box, Gtk.Separator())
        _box_add(box, Gtk.Label(label="Envoyer le lien par e-mail à :", xalign=0))

        email_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.email_entry = Gtk.Entry()
        self.email_entry.set_placeholder_text("destinataire@example.com")
        if GTK4:
            self.email_entry.set_hexpand(True)
        send_btn = Gtk.Button(label="Envoyer")
        send_btn.connect("clicked", self.on_send_clicked)
        _box_add(email_box, self.email_entry)
        _box_add(email_box, send_btn)
        _box_add(box, email_box)

        self.status_label = Gtk.Label(label="", xalign=0)
        _box_add(box, self.status_label)

        close_btn = Gtk.Button(label="Fermer")
        close_btn.connect("clicked", lambda *_: self.close())
        _box_add(box, close_btn)

        self.filename = filename
        self.url = url

        if GTK4:
            self.present()
        else:
            self.show_all()

    def on_send_clicked(self, button):
        to_address = self.email_entry.get_text().strip()
        if not to_address:
            self.status_label.set_text("Entrez une adresse e-mail.")
            return
        self.status_label.set_text("Envoi en cours…")

        def on_done(error):
            if error:
                self.status_label.set_text(f"Échec: {error}")
            else:
                self.status_label.set_text("E-mail envoyé.")
                self.close()

        send_share_email_async(to_address, self.filename, self.url, on_done)


def show_loading_window(filename):
    win = Gtk.Window(title="Proton Drive")
    win.set_default_size(360, 120)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    if GTK4:
        box.set_margin_top(20)
        box.set_margin_bottom(20)
        box.set_margin_start(20)
        box.set_margin_end(20)
        box.set_valign(Gtk.Align.CENTER)
        win.set_child(box)
    else:
        box.set_border_width(20)
        win.add(box)
    label = Gtk.Label(
        label=f"Génération du lien de partage pour «\u00a0{filename}\u00a0»…\n(appel réseau à Proton Drive, quelques secondes)"
    )
    label.set_justify(Gtk.Justification.CENTER)
    label.set_wrap(True)
    _box_add(box, label)
    if GTK4:
        win.present()
    else:
        win.show_all()
    return win


def show_error_window(message):
    win = Gtk.Window(title="Proton Drive — erreur de partage")
    win.set_default_size(420, 160)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    if GTK4:
        box.set_margin_top(14)
        box.set_margin_bottom(14)
        box.set_margin_start(14)
        box.set_margin_end(14)
        win.set_child(box)
    else:
        box.set_border_width(14)
        win.add(box)
    label = Gtk.Label(label=message, xalign=0)
    label.set_wrap(True)
    _box_add(box, label)
    close_btn = Gtk.Button(label="Fermer")
    close_btn.connect("clicked", lambda *_: win.close())
    _box_add(box, close_btn)
    if GTK4:
        win.present()
    else:
        win.show_all()


class ProtonDriveShareExtension(GObject.GObject, Nautilus.MenuProvider):
    def get_file_items(self, *args):
        # Signature selon la version de nautilus-python :
        #   get_file_items(self, window, files)  -- API historique
        #   get_file_items(self, files)           -- API récente (Nautilus 42+)
        files = args[-1]
        if len(files) != 1:
            return []

        file_info = files[0]
        if file_info.is_directory():
            return []
        if file_info.get_uri_scheme() != "file":
            return []

        local_path = file_info.get_location().get_path()
        if not local_path:
            return []

        cfg = load_sync_config()
        remote_path = local_to_remote_path(local_path, cfg)
        if remote_path is None:
            return []  # pas dans le dossier synchronisé -> pas d'entrée de menu

        item = Nautilus.MenuItem(
            name="ProtonDriveShare::share",
            label="Partager via Proton Drive",
            tip="Générer un lien de partage Proton Drive et l'envoyer par e-mail",
        )
        item.connect("activate", self.on_share_activate, local_path, remote_path)
        return [item]

    def on_share_activate(self, menu_item, local_path, remote_path):
        _log_timing("=== clic sur 'Partager via Proton Drive' ===")
        filename = os.path.basename(local_path)
        loading_win = show_loading_window(filename)
        _log_timing("fenêtre de chargement affichée")

        def on_result(url, error):
            _log_timing(f"callback résultat reçu (erreur={error is not None})")
            loading_win.close()
            if error:
                show_error_window(f"Échec de la génération du lien de partage :\n{error}")
            else:
                ShareWindow(filename, url)
            _log_timing("fenêtre finale affichée")

        get_share_url_async(remote_path, on_result)
