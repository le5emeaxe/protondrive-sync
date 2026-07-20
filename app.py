#!/usr/bin/env python3
"""
Proton Drive GTK4 — interface façon Nautilus (Fichiers GNOME).

Sidebar d'emplacements + vue grille (icônes) / vue liste basculable,
barre d'emplacement, recherche, drag-and-drop Nautilus <-> app.

Dépendances (Arch) : sudo pacman -S python-gobject gtk4 libadwaita
Dépendances (Debian/Ubuntu) : sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1

Lancement : python3 app.py
"""

import os
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango

import backend

CACHE_DIR = os.path.expanduser("~/.cache/proton-drive-gtk")

# Places shown in the sidebar: (label, remote path, icon name)
PLACES = [
    ("Mes fichiers", "/my-files", "folder-symbolic"),
    ("Photos", "/photos", "folder-pictures-symbolic"),
    ("Albums", "/albums", "image-x-generic-symbolic"),
    ("Appareils", "/devices", "computer-symbolic"),
    ("Partagés par moi", "/shared-by-me", "send-to-symbolic"),
    ("Partagés avec moi", "/shared-with-me", "emblem-shared-symbolic"),
]
TRASH_PLACE = ("Corbeille", "/trash", "user-trash-symbolic")


def human_size(n):
    try:
        return GLib.format_size(int(n))
    except (TypeError, ValueError):
        return "—"


def format_date(iso):
    if not iso:
        return ""
    try:
        dt = GLib.DateTime.new_from_iso8601(iso, None)
        if dt:
            return dt.format("%d/%m/%Y %H:%M")
    except Exception:
        pass
    return iso


def icon_for(entry, large=False):
    suffix = "" if large else "-symbolic"
    if entry.is_folder:
        if entry.path in ("/trash", "/photos-trash"):
            return "user-trash" + suffix
        if entry.path in ("/photos", "/albums", "/photos-shared-by-me", "/photos-shared-with-me"):
            return "folder-pictures" + suffix
        if entry.path == "/devices":
            return "computer" + suffix
        return "folder" + suffix
    mt = entry.mediatype or ""
    if mt.startswith("image/"):
        return "image-x-generic" + suffix
    if mt.startswith("video/"):
        return "video-x-generic" + suffix
    if mt.startswith("audio/"):
        return "audio-x-generic" + suffix
    if mt == "application/pdf":
        return "x-office-document" + suffix
    return "text-x-generic" + suffix


class DriveItemObject(GObject.Object):
    """Wraps a backend.DriveEntry so it can live in a Gio.ListStore."""

    def __init__(self, entry: backend.DriveEntry):
        super().__init__()
        self.entry = entry
        self.cached_local_path = None
        self.downloading = False


class DriveWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Proton Drive", default_width=1050, default_height=680)

        os.makedirs(CACHE_DIR, exist_ok=True)

        self.current_path = "/my-files"
        self.history = []
        self.search_query = ""

        self.store = Gio.ListStore(item_type=DriveItemObject)
        self.filter = Gtk.CustomFilter.new(self._filter_func)
        self.filter_model = Gtk.FilterListModel(model=self.store, filter=self.filter)
        self.selection = Gtk.MultiSelection(model=self.filter_model)
        self.selection.connect("selection-changed", self.on_selection_changed)

        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.toast_overlay.set_child(outer)

        # ---------- Header bar ----------
        header = Adw.HeaderBar()
        outer.append(header)

        self.back_btn = Gtk.Button(icon_name="go-previous-symbolic", tooltip_text="Précédent")
        self.back_btn.connect("clicked", self.on_back)
        self.back_btn.set_sensitive(False)
        header.pack_start(self.back_btn)

        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Actualiser")
        refresh_btn.connect("clicked", lambda *_: self.load_path(self.current_path))
        header.pack_start(refresh_btn)

        # Location pill (icon + current folder name), shown as the header title widget
        self.location_btn = Gtk.MenuButton()
        self.location_btn.add_css_class("flat")
        loc_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.location_icon = Gtk.Image.new_from_icon_name("folder-symbolic")
        self.location_label = Gtk.Label(label="Mes fichiers")
        loc_box.append(self.location_icon)
        loc_box.append(self.location_label)
        self.location_btn.set_child(loc_box)
        self.breadcrumb_popover = Gtk.Popover()
        self.location_btn.set_popover(self.breadcrumb_popover)
        header.set_title_widget(self.location_btn)

        # Right side icons, packed rightmost-first
        search_btn = Gtk.ToggleButton(icon_name="system-search-symbolic", tooltip_text="Rechercher")
        search_btn.connect("toggled", self.on_search_toggled)
        header.pack_end(search_btn)
        self.search_btn = search_btn

        self.view_toggle_btn = Gtk.ToggleButton(icon_name="view-list-symbolic", tooltip_text="Basculer vue liste/grille")
        self.view_toggle_btn.connect("toggled", self.on_view_toggled)
        header.pack_end(self.view_toggle_btn)

        header.pack_end(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        new_folder_btn = Gtk.Button(icon_name="folder-new-symbolic", tooltip_text="Nouveau dossier")
        new_folder_btn.connect("clicked", self.on_new_folder)
        header.pack_end(new_folder_btn)

        upload_btn = Gtk.Button(icon_name="document-send-symbolic", tooltip_text="Envoyer des fichiers")
        upload_btn.connect("clicked", self.on_upload_clicked)
        header.pack_end(upload_btn)

        self.download_btn = Gtk.Button(icon_name="folder-download-symbolic", tooltip_text="Télécharger la sélection")
        self.download_btn.connect("clicked", self.on_download_clicked)
        self.download_btn.set_sensitive(False)
        header.pack_end(self.download_btn)

        self.delete_btn = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Corbeille / suppression")
        self.delete_btn.connect("clicked", self.on_delete_clicked)
        self.delete_btn.set_sensitive(False)
        header.pack_end(self.delete_btn)

        # ---------- Search bar (revealed) ----------
        self.search_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
        search_bar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        search_bar_box.set_margin_start(10)
        search_bar_box.set_margin_end(10)
        search_bar_box.set_margin_top(6)
        self.search_entry = Gtk.SearchEntry(placeholder_text="Filtrer dans ce dossier…", hexpand=True)
        self.search_entry.connect("search-changed", self.on_search_changed)
        search_bar_box.append(self.search_entry)
        self.search_revealer.set_child(search_bar_box)
        outer.append(self.search_revealer)

        # ---------- Body: sidebar + content ----------
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True)
        outer.append(body)

        sidebar_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        sidebar_scroll.set_size_request(190, -1)
        self.sidebar = Gtk.ListBox()
        self.sidebar.add_css_class("navigation-sidebar")
        self.sidebar.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.sidebar.connect("row-activated", self.on_sidebar_activated)
        sidebar_scroll.set_child(self.sidebar)
        body.append(sidebar_scroll)

        for label, path, icon in PLACES:
            self.sidebar.append(self._make_sidebar_row(label, path, icon))
        self.sidebar.append(Gtk.Separator())
        label, path, icon = TRASH_PLACE
        self.sidebar.append(self._make_sidebar_row(label, path, icon))

        body.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        body.append(content_box)

        self.view_stack = Gtk.Stack(vexpand=True)
        content_box.append(self.view_stack)

        # ----- Grid (icon) view -----
        grid_scroll = Gtk.ScrolledWindow()
        grid_factory = Gtk.SignalListItemFactory()
        grid_factory.connect("setup", self._setup_grid_item)
        grid_factory.connect("bind", self._bind_grid_item)
        self.grid_view = Gtk.GridView(model=self.selection, factory=grid_factory)
        self.grid_view.set_min_columns(3)
        self.grid_view.set_max_columns(12)
        self.grid_view.connect("activate", self.on_row_activated)
        grid_scroll.set_child(self.grid_view)
        self.view_stack.add_named(grid_scroll, "grid")

        # ----- List (column) view -----
        list_scroll = Gtk.ScrolledWindow()
        self.column_view = Gtk.ColumnView(model=self.selection)
        self.column_view.set_show_row_separators(True)

        name_factory = Gtk.SignalListItemFactory()
        name_factory.connect("setup", self._setup_name)
        name_factory.connect("bind", self._bind_name)
        self.column_view.append_column(Gtk.ColumnViewColumn(title="Nom", factory=name_factory, expand=True))

        size_factory = Gtk.SignalListItemFactory()
        size_factory.connect("setup", self._setup_label)
        size_factory.connect("bind", self._bind_size)
        self.column_view.append_column(Gtk.ColumnViewColumn(title="Taille", factory=size_factory))

        date_factory = Gtk.SignalListItemFactory()
        date_factory.connect("setup", self._setup_label)
        date_factory.connect("bind", self._bind_date)
        self.column_view.append_column(Gtk.ColumnViewColumn(title="Modifié", factory=date_factory))

        self.column_view.connect("activate", self.on_row_activated)
        list_scroll.set_child(self.column_view)
        self.view_stack.add_named(list_scroll, "list")

        self.view_stack.set_visible_child_name("grid")

        # Drag & drop applies to whichever view is shown
        drop_target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop_target.connect("drop", self.on_drop)
        self.view_stack.add_controller(drop_target)

        drag_source = Gtk.DragSource()
        drag_source.set_actions(Gdk.DragAction.COPY)
        drag_source.connect("prepare", self.on_drag_prepare)
        self.view_stack.add_controller(drag_source)

        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self.on_key_pressed)
        self.add_controller(key_controller)

        # ---------- Status bar ----------
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        status_box.set_margin_start(10)
        status_box.set_margin_end(10)
        status_box.set_margin_top(4)
        status_box.set_margin_bottom(6)
        self.status_label = Gtk.Label(halign=Gtk.Align.START, hexpand=True)
        self.selection_label = Gtk.Label(halign=Gtk.Align.END)
        self.selection_label.add_css_class("dim-label")
        status_box.append(self.status_label)
        status_box.append(self.selection_label)
        content_box.append(status_box)

        self._select_sidebar_row_for_path(self.current_path)
        self.load_path(self.current_path)

    # ================= Sidebar =================
    def _make_sidebar_row(self, label, path, icon_name):
        row = Gtk.ListBoxRow()
        row.drive_path = path
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.append(Gtk.Image.new_from_icon_name(icon_name))
        box.append(Gtk.Label(label=label, xalign=0))
        row.set_child(box)
        return row

    def _select_sidebar_row_for_path(self, path):
        r = self.sidebar.get_first_child()
        while r:
            if isinstance(r, Gtk.ListBoxRow) and getattr(r, "drive_path", None) == path:
                self.sidebar.select_row(r)
                return
            r = r.get_next_sibling()

    def on_sidebar_activated(self, listbox, row):
        path = getattr(row, "drive_path", None)
        if path:
            self.navigate_to(path)

    # ================= Grid factory (icon view) =================
    def _setup_grid_item(self, factory, item):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_size_request(96, 96)
        icon = Gtk.Image()
        icon.set_pixel_size(64)
        label = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, lines=2,
                           ellipsize=Pango.EllipsizeMode.END, max_width_chars=14)
        box.append(icon)
        box.append(label)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(4)
        box.set_margin_end(4)
        item.set_child(box)

    def _bind_grid_item(self, factory, item):
        box = item.get_child()
        icon = box.get_first_child()
        label = icon.get_next_sibling()
        entry = item.get_item().entry
        icon.set_from_icon_name(icon_for(entry, large=True))
        label.set_text(entry.name)

    # ================= List (column) factories =================
    def _setup_name(self, factory, item):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        icon = Gtk.Image()
        label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        box.append(icon)
        box.append(label)
        item.set_child(box)

    def _bind_name(self, factory, item):
        box = item.get_child()
        icon = box.get_first_child()
        label = icon.get_next_sibling()
        entry = item.get_item().entry
        icon.set_from_icon_name(icon_for(entry))
        label.set_text(entry.name)

    def _setup_label(self, factory, item):
        item.set_child(Gtk.Label(xalign=0))

    def _bind_size(self, factory, item):
        entry = item.get_item().entry
        item.get_child().set_text("—" if entry.is_folder else human_size(entry.size))

    def _bind_date(self, factory, item):
        entry = item.get_item().entry
        item.get_child().set_text(format_date(entry.mtime))

    # ================= View toggle / search =================
    def on_view_toggled(self, btn):
        if btn.get_active():
            self.view_stack.set_visible_child_name("list")
            btn.set_icon_name("view-grid-symbolic")
            btn.set_tooltip_text("Basculer en vue grille")
        else:
            self.view_stack.set_visible_child_name("grid")
            btn.set_icon_name("view-list-symbolic")
            btn.set_tooltip_text("Basculer en vue liste")

    def on_search_toggled(self, btn):
        self.search_revealer.set_reveal_child(btn.get_active())
        if btn.get_active():
            self.search_entry.grab_focus()
        else:
            self.search_entry.set_text("")

    def on_search_changed(self, entry):
        self.search_query = entry.get_text().strip().lower()
        self.filter.changed(Gtk.FilterChange.DIFFERENT)

    def _filter_func(self, item):
        if not self.search_query:
            return True
        return self.search_query in item.entry.name.lower()

    # ================= Navigation =================
    def load_path(self, path):
        self.status_label.set_text(f"Chargement de {path} …")

        def work():
            try:
                entries = backend.list_path(path)
                GLib.idle_add(self._on_loaded, path, entries, None)
            except backend.ProtonDriveError as e:
                GLib.idle_add(self._on_loaded, path, [], str(e))

        threading.Thread(target=work, daemon=True).start()

    def _on_loaded(self, path, entries, error):
        if error:
            self.show_toast(f"Erreur: {error}")
            self.status_label.set_text("Erreur de chargement")
            return False
        self.current_path = path
        self.store.remove_all()
        for e in sorted(entries, key=lambda e: (not e.is_folder, e.name.lower())):
            self.store.append(DriveItemObject(e))
        self.status_label.set_text(f"{len(entries)} élément(s)")
        self.back_btn.set_sensitive(bool(self.history))
        self.update_location(path)
        self._select_sidebar_row_for_path(path)
        return False

    def update_location(self, path):
        name = path.rstrip("/").split("/")[-1] or "Racine"
        icon = "folder-symbolic"
        for label, p, ic in PLACES + [TRASH_PLACE]:
            if p == path:
                name = label
                icon = ic
                break
        self.location_icon.set_from_icon_name(icon)
        self.location_label.set_text(name)
        self._build_breadcrumb_popover(path)

    def _build_breadcrumb_popover(self, path):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        def add_crumb(label, target_path):
            btn = Gtk.Button(label=label)
            btn.add_css_class("flat")
            btn.connect("clicked", lambda *_: (self.breadcrumb_popover.popdown(), self.navigate_to(target_path)))
            box.append(btn)

        add_crumb("🏠 Racine", "/")
        parts = [p for p in path.split("/") if p]
        acc = ""
        for p in parts:
            acc += "/" + p
            add_crumb(p, acc)
        self.breadcrumb_popover.set_child(box)

    def navigate_to(self, path):
        if path == self.current_path:
            return
        self.history.append(self.current_path)
        self.load_path(path)

    def on_back(self, *_):
        if self.history:
            self.load_path(self.history.pop())

    def on_row_activated(self, view, position):
        item = self.selection.get_item(position)
        entry = item.entry
        if entry.is_folder:
            self.navigate_to(entry.path)
        else:
            self.show_toast(f"{entry.name} — utilisez le bouton Télécharger pour le récupérer")

    def on_key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Delete:
            self.on_delete_clicked()
            return True
        return False

    # ================= Selection =================
    def get_selected_items(self):
        items = []
        for i in range(self.filter_model.get_n_items()):
            if self.selection.is_selected(i):
                items.append(self.filter_model.get_item(i))
        return items

    def get_selected_entries(self):
        return [it.entry for it in self.get_selected_items()]

    def on_selection_changed(self, *_):
        entries = self.get_selected_entries()
        has_sel = bool(entries)
        self.delete_btn.set_sensitive(has_sel)
        self.download_btn.set_sensitive(has_sel)

        if not entries:
            self.selection_label.set_text("")
        elif len(entries) == 1:
            e = entries[0]
            size_txt = human_size(e.size) if not e.is_folder else ""
            self.selection_label.set_text(f"« {e.name} » sélectionné" + (f" ({size_txt})" if size_txt else ""))
        else:
            total = sum(e.size for e in entries if not e.is_folder)
            self.selection_label.set_text(f"{len(entries)} éléments sélectionnés ({human_size(total)})")

        for item in self.get_selected_items():
            if not item.entry.is_folder and not item.cached_local_path and not item.downloading:
                self.prefetch_for_drag(item)

    # ================= Upload =================
    def on_upload_clicked(self, *_):
        dialog = Gtk.FileDialog(title="Choisir des fichiers à envoyer")
        dialog.open_multiple(self, None, self._on_upload_files_chosen)

    def _on_upload_files_chosen(self, dialog, result):
        try:
            model = dialog.open_multiple_finish(result)
        except GLib.Error:
            return
        local_paths = []
        for i in range(model.get_n_items()):
            f = model.get_item(i)
            p = f.get_path()
            if p:
                local_paths.append(p)
        if local_paths:
            self.do_upload(local_paths)

    def do_upload(self, local_paths):
        target = self.current_path
        if target == "/":
            self.show_toast("Choisissez d'abord un dossier réel (my-files, ...) avant d'envoyer")
            return
        self.status_label.set_text(f"Envoi de {len(local_paths)} fichier(s)…")

        def work():
            try:
                result = backend.upload(local_paths, target)
                GLib.idle_add(self._on_upload_done, result, None)
            except backend.ProtonDriveError as e:
                GLib.idle_add(self._on_upload_done, None, str(e))

        threading.Thread(target=work, daemon=True).start()

    def _on_upload_done(self, result, error):
        if error:
            self.show_toast(f"Échec de l'envoi: {error}")
        else:
            ok_count = (result or {}).get("transferredItems", 0)
            failed = (result or {}).get("failedItems", 0)
            if failed:
                self.show_toast(f"Envoi terminé — {ok_count} réussi(s), {failed} échec(s)")
            else:
                self.show_toast(f"{ok_count} fichier(s) envoyé(s)")
        self.load_path(self.current_path)
        return False

    # ================= Download =================
    def on_download_clicked(self, *_):
        entries = self.get_selected_entries()
        if not entries:
            return
        dialog = Gtk.FileDialog(title="Choisir le dossier de destination")
        dialog.select_folder(self, None, lambda d, r: self._on_download_folder_chosen(d, r, entries))

    def _on_download_folder_chosen(self, dialog, result, entries):
        try:
            folder = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        local_folder = folder.get_path()
        if local_folder:
            self.do_download([e.path for e in entries], local_folder)

    def do_download(self, remote_paths, local_folder):
        self.status_label.set_text(f"Téléchargement de {len(remote_paths)} élément(s)…")

        def work():
            try:
                backend.download(remote_paths, local_folder)
                GLib.idle_add(self._on_download_done, None, local_folder)
            except backend.ProtonDriveError as e:
                GLib.idle_add(self._on_download_done, str(e), local_folder)

        threading.Thread(target=work, daemon=True).start()

    def _on_download_done(self, error, local_folder):
        if error:
            self.show_toast(f"Échec du téléchargement: {error}")
        else:
            self.show_toast(f"Téléchargé dans {local_folder}")
        self.status_label.set_text(f"{self.store.get_n_items()} élément(s)")
        return False

    # ================= Delete / trash =================
    def on_delete_clicked(self, *_):
        entries = self.get_selected_entries()
        if not entries:
            return
        in_trash = self.current_path.startswith("/trash")
        verb = "supprimer définitivement" if in_trash else "mettre à la corbeille"
        names = ", ".join(e.name for e in entries[:5])
        if len(entries) > 5:
            names += f" (+{len(entries) - 5} autres)"

        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=f"Confirmer : {verb} ?",
            body=names,
        )
        dialog.add_response("cancel", "Annuler")
        dialog.add_response("confirm", "Confirmer")
        dialog.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_delete_confirm, entries, in_trash)
        dialog.present()

    def _on_delete_confirm(self, dialog, response, entries, in_trash):
        if response != "confirm":
            return
        paths = [e.path for e in entries]

        def work():
            try:
                if in_trash:
                    backend.delete_permanently(paths)
                else:
                    backend.trash(paths)
                GLib.idle_add(self._on_delete_done, None)
            except backend.ProtonDriveError as e:
                GLib.idle_add(self._on_delete_done, str(e))

        threading.Thread(target=work, daemon=True).start()

    def _on_delete_done(self, error):
        self.show_toast(f"Échec: {error}" if error else "Terminé")
        self.load_path(self.current_path)
        return False

    # ================= New folder =================
    def on_new_folder(self, *_):
        if self.current_path == "/":
            self.show_toast("Naviguez dans un dossier réel avant d'en créer un nouveau")
            return
        dialog = Adw.MessageDialog(transient_for=self, heading="Nouveau dossier")
        entry = Gtk.Entry()
        entry.set_activates_default(True)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Annuler")
        dialog.add_response("create", "Créer")
        dialog.set_default_response("create")
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", self._on_new_folder_response, entry)
        dialog.present()

    def _on_new_folder_response(self, dialog, response, entry):
        if response != "create":
            return
        name = entry.get_text().strip()
        if not name:
            return
        parent = self.current_path

        def work():
            try:
                backend.create_folder(parent, name)
                GLib.idle_add(self._on_new_folder_done, None)
            except backend.ProtonDriveError as e:
                GLib.idle_add(self._on_new_folder_done, str(e))

        threading.Thread(target=work, daemon=True).start()

    def _on_new_folder_done(self, error):
        self.show_toast(f"Échec: {error}" if error else "Dossier créé")
        self.load_path(self.current_path)
        return False

    # ================= Drag & drop: Nautilus -> app =================
    def on_drop(self, drop_target, value, x, y):
        files = value.get_files()
        local_paths = [f.get_path() for f in files if f.get_path()]
        if not local_paths:
            return False
        self.do_upload(local_paths)
        return True

    # ================= Drag & drop: app -> Nautilus =================
    def prefetch_for_drag(self, item):
        """Pre-download a selected file to a local cache so it can be
        dragged out to Nautilus (GTK drag 'prepare' must return synchronously,
        so the file has to already exist locally by the time the user drags)."""
        item.downloading = True
        entry = item.entry
        dest_dir = os.path.join(CACHE_DIR, entry.uid or str(id(item)))

        def work():
            try:
                os.makedirs(dest_dir, exist_ok=True)
                backend.download([entry.path], dest_dir)
                local_file = os.path.join(dest_dir, entry.name)
                GLib.idle_add(self._on_prefetch_done, item, local_file, None)
            except backend.ProtonDriveError as e:
                GLib.idle_add(self._on_prefetch_done, item, None, str(e))

        threading.Thread(target=work, daemon=True).start()

    def _on_prefetch_done(self, item, local_file, error):
        item.downloading = False
        if not error and local_file and os.path.exists(local_file):
            item.cached_local_path = local_file
        return False

    def on_drag_prepare(self, source, x, y):
        items = self.get_selected_items()
        ready_paths = [it.cached_local_path for it in items if it.cached_local_path]
        if not ready_paths:
            if items:
                self.show_toast("Préparation du fichier en cours, réessayez la glisser dans un instant")
            return None
        uri_list = "\n".join(GLib.filename_to_uri(p, None) for p in ready_paths)
        return Gdk.ContentProvider.new_for_bytes("text/uri-list", GLib.Bytes.new(uri_list.encode("utf-8")))

    # ================= Misc =================
    def show_toast(self, text):
        toast = Adw.Toast.new(text)
        toast.set_timeout(4)
        self.toast_overlay.add_toast(toast)


class ProtonDriveApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="fr.andytoys.protondrivegtk")

    def do_activate(self):
        win = self.props.active_window or DriveWindow(self)
        win.present()


def main():
    ProtonDriveApp().run(None)


if __name__ == "__main__":
    main()
