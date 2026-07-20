"""Bump ICON_VERSION any time the icon artwork changes.

GNOME Shell (and other StatusNotifierItem hosts) cache a resolved icon by
NAME in memory once loaded — overwriting the SVG file on disk with the same
name is not guaranteed to be picked up without restarting the shell. Baking
a version number into the icon name sidesteps this entirely: a version bump
means genuinely new names that have never been loaded before, so they are
read fresh from disk with no stale cache possible.
"""

ICON_VERSION = 5

# Séparé de ICON_VERSION : les embl Nautilus (pastilles colorées sur le
# dossier ~/protondrive dans le gestionnaire de fichiers) sont un jeu
# d'icônes distinct du tray, avec son propre cycle de vie.
EMBLEM_VERSION = 1
