#!/usr/bin/env python3
"""
Generates the tray icon set for proton-drive-sync: a purple-gradient folder
(inspired by Proton's brand palette, not a copy of any official logo) with a
small status badge in the bottom-right corner.

Produces SVGs in ./icons/:
    protondrive-sync-idle.svg      (green dot — active, synced)
    protondrive-sync-dryrun.svg    (blue dot  — simulation mode)
    protondrive-sync-paused.svg    (grey dot  — paused)
    protondrive-sync-error.svg     (red dot   — last sync failed)
    protondrive-sync-syncing-0..7.svg  (green dot, opacity pulsing — blink
                                        while a sync is running)

Run: python3 generate_icons.py
"""

import math
import os
import shutil

import icons
from icon_version import EMBLEM_VERSION, ICON_VERSION

EMBLEM_DEST_DIR = os.path.expanduser("~/.local/share/icons/hicolor/scalable/emblems")

EMBLEM_DOT_TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <circle cx="32" cy="32" r="26" fill="{color}" stroke="#ffffff" stroke-width="5"/>
</svg>
"""

# Mêmes couleurs que les pastilles du tray, pour rester cohérent visuellement.
EMBLEM_COLORS = {
    "synced": "#2ECC71",
    "error": "#EF4444",
    "paused": "#9CA3AF",
    "dryrun": "#3B82F6",
}


def write_emblem_dots():
    """Génère et installe les pastilles colorées utilisées par
    nautilus_protondrive_emblem.py (badge sur le dossier ~/protondrive
    dans Nautilus). Versionnées comme les icônes du tray, pour la même
    raison : éviter tout souci de cache d'icônes.

    Installées à la fois dans hicolor/scalable/emblems/ (ce que Nautilus
    a semblé attendre selon un message d'erreur) ET hicolor/scalable/apps/
    (l'emplacement déjà éprouvé pour toutes nos autres icônes) — pour ne
    plus avoir à deviner lequel des deux Nautilus consulte réellement sur
    ce poste."""
    wanted_names = set()
    for status, color in EMBLEM_COLORS.items():
        name = f"protondrive-emblem-{status}-v{EMBLEM_VERSION}"
        wanted_names.add(f"{name}.svg")
        svg_content = EMBLEM_DOT_TEMPLATE.format(color=color)
        for dest_dir in (EMBLEM_DEST_DIR, icons.DEST_DIR):
            os.makedirs(dest_dir, exist_ok=True)
            path = os.path.join(dest_dir, f"{name}.svg")
            with open(path, "w", encoding="utf-8") as f:
                f.write(svg_content)

    # Nettoyage des anciennes versions, dans les deux dossiers.
    for dest_dir in (EMBLEM_DEST_DIR, icons.DEST_DIR):
        if not os.path.isdir(dest_dir):
            continue
        for existing in os.listdir(dest_dir):
            if existing.startswith("protondrive-emblem-") and existing not in wanted_names:
                try:
                    os.remove(os.path.join(dest_dir, existing))
                except OSError:
                    pass

    print(f"{len(EMBLEM_COLORS)} pastille(s) d'emblème installée(s) dans {EMBLEM_DEST_DIR} "
          f"ET {icons.DEST_DIR} (version {EMBLEM_VERSION})")

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")

SUFFIX = f"-v{ICON_VERSION}"

# Proton-inspired purple gradient (not a copy of the official logo geometry).
GRAD_START = "#8B5CF6"   # lighter violet, top-left
GRAD_END = "#4C1D95"     # deep indigo/purple, bottom-right

FOLDER_BODY = """
  <defs>
    <linearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{start}"/>
      <stop offset="100%" stop-color="{end}"/>
    </linearGradient>
  </defs>
  <rect x="20" y="26" width="100" height="46" rx="18" fill="url(#grad)"/>
  <rect x="6" y="58" width="244" height="192" rx="32" fill="url(#grad)"/>
  <rect x="6" y="96" width="244" height="154" rx="28" fill="#ffffff" opacity="0.06"/>
""".format(start=GRAD_START, end=GRAD_END)

# Small idle/status badge (bottom-right corner dot).
BADGE_RING = '<circle cx="212" cy="210" r="38" fill="{color}" stroke="#ffffff" stroke-width="7" opacity="{opacity}"/>'

SYNCING_COLOR = "#2ECC71"  # same green as idle — it's the same badge, just blinking
SYNCING_FRAME_COUNT = 8

SVG_TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
{body}
</svg>
"""


def write_icon(name, extra_svg):
    path = os.path.join(OUT_DIR, f"{name}{SUFFIX}.svg")
    with open(path, "w", encoding="utf-8") as f:
        f.write(SVG_TEMPLATE.format(body=FOLDER_BODY + extra_svg))
    return path


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # Remove old-version icon files so ~/proton-drive-sync/icons/ (and later
    # the installed copies) never accumulate stale artwork from a previous
    # ICON_VERSION.
    for f in os.listdir(OUT_DIR):
        if f.startswith("protondrive-sync-") and f.endswith(".svg") and SUFFIX not in f:
            os.remove(os.path.join(OUT_DIR, f))

    written = []

    written.append(write_icon("protondrive-sync-idle", BADGE_RING.format(color="#2ECC71", opacity=1.0)))
    written.append(write_icon("protondrive-sync-dryrun", BADGE_RING.format(color="#3B82F6", opacity=1.0)))
    written.append(write_icon("protondrive-sync-paused", BADGE_RING.format(color="#9CA3AF", opacity=1.0)))
    written.append(write_icon("protondrive-sync-error", BADGE_RING.format(color="#EF4444", opacity=1.0)))

    # Smooth blink: opacity follows a cosine wave from 1.0 down to ~0.25 and
    # back up over SYNCING_FRAME_COUNT steps. Cosine is periodic, so frame
    # N-1 flows seamlessly back into frame 0 when the sequence loops.
    for i in range(SYNCING_FRAME_COUNT):
        phase = 2 * math.pi * i / SYNCING_FRAME_COUNT
        opacity = 0.25 + 0.75 * (0.5 * (1 + math.cos(phase)))
        written.append(write_icon(
            f"protondrive-sync-syncing-{i}",
            BADGE_RING.format(color=SYNCING_COLOR, opacity=f"{opacity:.2f}"),
        ))

    # Stable-named app icon (no version suffix) for use by a .desktop
    # launcher entry — same look as the idle tray badge. Unlike the tray
    # icons, this one doesn't need cache-busting versioning: regular
    # application icon lookup (launcher, alt-tab, Nautilus...) isn't
    # affected by the StatusNotifierItem-specific quirks we hit earlier.
    app_icon_path = os.path.join(OUT_DIR, "protondrive-sync.svg")
    with open(app_icon_path, "w", encoding="utf-8") as f:
        f.write(SVG_TEMPLATE.format(body=FOLDER_BODY + BADGE_RING.format(color="#2ECC71", opacity=1.0)))
    dest = os.path.join(icons.DEST_DIR, "protondrive-sync.svg")
    os.makedirs(icons.DEST_DIR, exist_ok=True)
    shutil.copyfile(app_icon_path, dest)
    print(f"Icône d'application (nom stable) installée: {dest}")

    print(f"{len(written)} icônes écrites dans {OUT_DIR} (version {ICON_VERSION})")

    changed = icons.install_icons()
    if changed:
        print(f"Installées dans {icons.DEST_DIR}")
    else:
        print(f"Déjà à jour dans {icons.DEST_DIR} (rien à copier)")

    write_emblem_dots()


if __name__ == "__main__":
    main()
