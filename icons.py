"""Installs the bundled SVG tray icons into the user's icon theme.

Tray/AppIndicator icons are rendered by the desktop shell (e.g. gnome-shell),
a *different process* from this daemon. An in-process
Gtk.IconTheme.add_search_path() would only affect icon lookups inside this
process, so it would not help the shell find custom icons. The portable,
universally-supported approach is to place them in the standard user icon
theme directory, which every desktop environment's icon lookup already
scans.
"""

import os
import re
import shutil
import subprocess

from icon_version import ICON_VERSION

SUFFIX = f"-v{ICON_VERSION}"

ICON_NAMES = [
    f"protondrive-sync-idle{SUFFIX}",
    f"protondrive-sync-dryrun{SUFFIX}",
    f"protondrive-sync-paused{SUFFIX}",
    f"protondrive-sync-error{SUFFIX}",
] + [f"protondrive-sync-syncing-{i}{SUFFIX}" for i in range(8)]

SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
DEST_DIR = os.path.expanduser("~/.local/share/icons/hicolor/scalable/apps")

_BASE_NAME_RE = re.compile(r"^(protondrive-sync-.+?)-v\d+$")


def install_icons():
    """Copy bundled SVGs into ~/.local/share/icons (idempotent), remove any
    icon files left over from a previous ICON_VERSION, then refresh the
    icon cache if a cache tool is available. Returns True if anything was
    (re)installed or removed."""
    os.makedirs(DEST_DIR, exist_ok=True)
    changed = False

    wanted_filenames = {f"{name}.svg" for name in ICON_NAMES}
    for existing in os.listdir(DEST_DIR):
        if existing.startswith("protondrive-sync-") and existing not in wanted_filenames:
            try:
                os.remove(os.path.join(DEST_DIR, existing))
                changed = True
            except OSError:
                pass

    for name in ICON_NAMES:
        src = os.path.join(SRC_DIR, f"{name}.svg")
        dst = os.path.join(DEST_DIR, f"{name}.svg")
        if not os.path.exists(src):
            continue
        if not os.path.exists(dst) or os.path.getmtime(src) > os.path.getmtime(dst):
            shutil.copyfile(src, dst)
            changed = True

    if changed:
        for tool in ("gtk4-update-icon-cache", "gtk-update-icon-cache"):
            tool_path = shutil.which(tool)
            if tool_path:
                try:
                    subprocess.run(
                        [tool_path, "-f", "-t", os.path.expanduser("~/.local/share/icons/hicolor")],
                        capture_output=True, timeout=10,
                    )
                except Exception:
                    pass
                break
    return changed


def discover_installed_icons():
    """Scan DEST_DIR for whatever protondrive-sync-*.svg files are ACTUALLY
    present right now, and return {base_name: exact_installed_name}
    (both without the .svg extension, e.g. "protondrive-sync-idle" ->
    "protondrive-sync-idle-v2"). This sidesteps any risk of the code
    computing a name that doesn't match what's really on disk — the tray
    icon should always reference a name confirmed to exist."""
    result = {}
    if not os.path.isdir(DEST_DIR):
        return result
    for fname in os.listdir(DEST_DIR):
        if not (fname.startswith("protondrive-sync-") and fname.endswith(".svg")):
            continue
        name = fname[:-4]  # strip ".svg"
        m = _BASE_NAME_RE.match(name)
        base = m.group(1) if m else name
        result[base] = name
    return result
