"""
Monkeypatch for the `trayer` package (v0.1.1): it never exposes the
StatusNotifierItem "IconThemePath" property, so hosts that don't already
search ~/.local/share/icons (or that only search the active GTK theme's
directories) can't find custom app icons — the item registers fine on
D-Bus, but nothing is drawn.

IconThemePath is part of the StatusNotifierItem spec precisely for this
case: it tells the host an extra icon-theme-style directory to search,
in addition to its normal theme lookup.

IMPORTANT: dbus-python's `@dbus.service.method(...)` decorator is what
makes Get/GetAll visible to D-Bus introspection/dispatch in the first
place — it's not just a plain Python method. Replacing them with an
undecorated function breaks ALL property access for the item (not just
IconThemePath), which is worse than doing nothing. The replacements below
carry the exact same decorator/signature as the originals.

Import this module once, before creating any TrayIcon, e.g.:
    import trayer_patch
    trayer_patch.apply(icon_theme_path="/path/to/icons")
"""

import dbus
import dbus.service
import trayer.tray_icon as _t

_ICON_THEME_PATH = None


def apply(icon_theme_path):
    """Patch trayer._StatusNotifierItem.Get/GetAll to also report
    IconThemePath. Safe to call multiple times."""
    global _ICON_THEME_PATH
    _ICON_THEME_PATH = icon_theme_path

    if getattr(_t._StatusNotifierItem, "_icon_theme_path_patched", False):
        return
    _t._StatusNotifierItem._icon_theme_path_patched = True

    original_get = _t._StatusNotifierItem.Get
    original_get_all = _t._StatusNotifierItem.GetAll

    @dbus.service.method(dbus_interface='org.freedesktop.DBus.Properties',
                         in_signature='ss', out_signature='v')
    def patched_get(self, interface, prop):
        if interface == _t.SNI_INTERFACE and prop == "IconThemePath":
            return dbus.String(_ICON_THEME_PATH or "")
        return original_get(self, interface, prop)

    @dbus.service.method(dbus_interface='org.freedesktop.DBus.Properties',
                         in_signature='s', out_signature='a{sv}')
    def patched_get_all(self, interface):
        result = original_get_all(self, interface)
        if interface == _t.SNI_INTERFACE:
            result["IconThemePath"] = dbus.String(_ICON_THEME_PATH or "")
        return result

    _t._StatusNotifierItem.Get = patched_get
    _t._StatusNotifierItem.GetAll = patched_get_all
