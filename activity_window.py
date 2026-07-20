"""GTK4/libadwaita window listing recent sync activity (a la Nextcloud
client's activity panel)."""

import datetime

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Pango

ACTION_ICONS = {
    "upload": "document-send-symbolic",
    "download": "folder-download-symbolic",
    "delete_local": "user-trash-symbolic",
    "delete_local_folder": "user-trash-symbolic",
    "trash_remote": "user-trash-symbolic",
    "trash_remote_folder": "user-trash-symbolic",
    "mkdir_local": "folder-new-symbolic",
    "mkdir_remote": "folder-new-symbolic",
    "conflict_keep_both_download": "dialog-warning-symbolic",
    "conflict_upload_local": "dialog-warning-symbolic",
    "baseline_file": "emblem-default-symbolic",
    "baseline_folder": "emblem-default-symbolic",
    "error": "dialog-error-symbolic",
}

ACTION_LABELS = {
    "upload": "Envoyé vers Proton Drive",
    "download": "Téléchargé depuis Proton Drive",
    "delete_local": "Supprimé localement",
    "delete_local_folder": "Dossier supprimé localement",
    "trash_remote": "Mis à la corbeille (distant)",
    "trash_remote_folder": "Dossier mis à la corbeille (distant)",
    "mkdir_local": "Dossier créé localement",
    "mkdir_remote": "Dossier créé (distant)",
    "conflict_keep_both_download": "Conflit — copie distante conservée à part",
    "conflict_upload_local": "Conflit — copie locale envoyée",
    "baseline_file": "Déjà synchronisé (référence)",
    "baseline_folder": "Déjà synchronisé (référence)",
    "error": "Erreur",
}


class ActivityWindow(Adw.ApplicationWindow):
    def __init__(self, app, db, cfg):
        super().__init__(application=app, title="Proton Drive Sync — Activité",
                          default_width=640, default_height=520)
        self.db = db
        self.cfg = cfg

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(box)

        header = Adw.HeaderBar()
        box.append(header)

        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Actualiser")
        refresh_btn.connect("clicked", lambda *_: self.refresh())
        header.pack_start(refresh_btn)

        self.status_label = Gtk.Label()
        header.set_title_widget(self.status_label)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        box.append(scrolled)
        self.listbox = Gtk.ListBox()
        self.listbox.add_css_class("boxed-list")
        self.listbox.set_margin_top(8)
        self.listbox.set_margin_bottom(8)
        self.listbox.set_margin_start(8)
        self.listbox.set_margin_end(8)
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        scrolled.set_child(self.listbox)

        self.refresh()

    def refresh(self):
        mode = "SIMULATION (dry-run)" if self.cfg.get("dry_run") else "actif"
        self.status_label.set_text(
            f"{self.cfg.get('remote_root')} ↔ {self.cfg.get('local_root')} — mode {mode}"
        )

        child = self.listbox.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.listbox.remove(child)
            child = nxt

        rows = self.db.recent_activity(200)
        if not rows:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label="Aucune activité pour l'instant.")
            label.set_margin_top(12)
            label.set_margin_bottom(12)
            row.set_child(label)
            self.listbox.append(row)
            return

        for ts, action, relpath, detail, status in rows:
            row = Gtk.ListBoxRow()
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            hbox.set_margin_top(6)
            hbox.set_margin_bottom(6)
            hbox.set_margin_start(8)
            hbox.set_margin_end(8)

            icon_name = "dialog-error-symbolic" if status == "error" else ACTION_ICONS.get(action, "text-x-generic-symbolic")
            hbox.append(Gtk.Image.new_from_icon_name(icon_name))

            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
            title = ACTION_LABELS.get(action, action)
            if status == "dry-run" and not action.startswith("baseline"):
                title += " (simulation)"
            name_label = Gtk.Label(label=f"{title} — {relpath or '(racine)'}", xalign=0,
                                    ellipsize=Pango.EllipsizeMode.END)
            vbox.append(name_label)
            if detail:
                detail_label = Gtk.Label(label=detail, xalign=0, ellipsize=Pango.EllipsizeMode.END)
                detail_label.add_css_class("dim-label")
                detail_label.add_css_class("caption")
                vbox.append(detail_label)
            hbox.append(vbox)

            dt = datetime.datetime.fromtimestamp(ts)
            time_label = Gtk.Label(label=dt.strftime("%d/%m %H:%M:%S"))
            time_label.add_css_class("dim-label")
            hbox.append(time_label)

            row.set_child(hbox)
            self.listbox.append(row)
