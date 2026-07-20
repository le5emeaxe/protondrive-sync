"""Simple, self-contained "About" window — deliberately not using
Adw.AboutWindow/AboutDialog since that API has changed across libadwaita
versions; a hand-built window avoids any version-compatibility risk."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

APP_NAME = "Proton Drive Sync"
DEV_DATE = "Juillet 2026"


class AboutWindow(Adw.Window):
    def __init__(self, app, icon_name):
        super().__init__(application=app, title="À propos", default_width=340,
                          default_height=400, resizable=False)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(outer)

        header = Adw.HeaderBar()
        outer.append(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(24)
        content.set_margin_bottom(28)
        content.set_margin_start(32)
        content.set_margin_end(32)
        content.set_halign(Gtk.Align.CENTER)
        outer.append(content)

        image = Gtk.Image.new_from_icon_name(icon_name)
        image.set_pixel_size(96)
        content.append(image)

        title = Gtk.Label(label=APP_NAME)
        title.add_css_class("title-1")
        content.append(title)

        subtitle = Gtk.Label(label="Synchronisation Proton Drive en tâche de fond")
        subtitle.add_css_class("dim-label")
        subtitle.set_justify(Gtk.Justification.CENTER)
        subtitle.set_wrap(True)
        content.append(subtitle)

        sep = Gtk.Separator()
        sep.set_margin_top(10)
        sep.set_margin_bottom(6)
        content.append(sep)

        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content.append(info_box)

        def add_info_row(label, value):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                           halign=Gtk.Align.CENTER)
            l = Gtk.Label(label=label)
            l.add_css_class("dim-label")
            v = Gtk.Label(label=value)
            v.add_css_class("heading")
            row.append(l)
            row.append(v)
            info_box.append(row)

        add_info_row("Développeur :", "Claude")
        add_info_row("Architecte :", "Nitrix")
        add_info_row("Développé en :", DEV_DATE)
