"""Settings window: dry-run toggle, deletion propagation toggle, and sync
interval in minutes. Changes apply immediately and are persisted to config."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

import config as config_module


class SettingsWindow(Adw.PreferencesWindow):
    def __init__(self, app, cfg, on_apply):
        super().__init__(application=app, title="Paramètres — Proton Drive Sync")
        self.cfg = dict(cfg)
        self.on_apply = on_apply
        self.set_default_size(480, 340)
        self.set_search_enabled(False)

        page = Adw.PreferencesPage()
        self.add(page)

        sync_group = Adw.PreferencesGroup(
            title="Synchronisation",
            description="Les changements s'appliquent immédiatement, sans redémarrer le démon.",
        )
        page.add(sync_group)

        self.dry_run_row = Adw.SwitchRow(
            title="Mode simulation (dry-run)",
            subtitle="Rien n'est modifié : le journal d'activité indique seulement ce qui serait fait",
        )
        self.dry_run_row.set_active(bool(self.cfg.get("dry_run", True)))
        self.dry_run_row.connect("notify::active", self._on_change)
        sync_group.add(self.dry_run_row)

        self.deletions_row = Adw.SwitchRow(
            title="Propager les suppressions",
            subtitle="Si désactivé, un fichier supprimé d'un côté reste présent de l'autre",
        )
        self.deletions_row.set_active(bool(self.cfg.get("sync_deletions", True)))
        self.deletions_row.connect("notify::active", self._on_change)
        sync_group.add(self.deletions_row)

        current_minutes = max(1, int(self.cfg.get("interval_seconds", 900)) // 60)
        self.interval_adjustment = Gtk.Adjustment(
            value=current_minutes, lower=1, upper=1440,
            step_increment=1, page_increment=5,
        )
        self.interval_row = Adw.SpinRow(
            title="Intervalle de synchronisation",
            subtitle="En minutes — évite de descendre trop bas (fair-use Proton)",
            adjustment=self.interval_adjustment,
        )
        self.interval_adjustment.connect("value-changed", self._on_change)
        sync_group.add(self.interval_row)

        scope_group = Adw.PreferencesGroup(title="Périmètre (lecture seule ici)")
        page.add(scope_group)
        scope_row = Adw.ActionRow(
            title=self.cfg.get("remote_root", "/my-files"),
            subtitle=f"↔ {self.cfg.get('local_root', '')}",
        )
        scope_row.add_prefix(Gtk.Image.new_from_icon_name("folder-symbolic"))
        scope_group.add(scope_row)
        note_row = Adw.ActionRow(
            subtitle="Pour changer le dossier local ou distant, édite "
                     "~/.config/proton-drive-sync/config.json puis redémarre le démon."
        )
        scope_group.add(note_row)

    def _on_change(self, *args):
        self.cfg["dry_run"] = self.dry_run_row.get_active()
        self.cfg["sync_deletions"] = self.deletions_row.get_active()
        self.cfg["interval_seconds"] = int(self.interval_adjustment.get_value()) * 60
        config_module.save_config(self.cfg)
        if self.on_apply:
            self.on_apply(dict(self.cfg))
