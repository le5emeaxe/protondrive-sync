"""JSON configuration for proton-drive-sync, stored in
~/.config/proton-drive-sync/config.json. Every field is user-editable."""

import json
import os

CONFIG_DIR = os.path.expanduser("~/.config/proton-drive-sync")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULTS = {
    # Local folder that mirrors Proton Drive.
    "local_root": os.path.expanduser("~/protondrive"),
    # Remote scope to sync. Deliberately NOT "/" (the virtual root also lists
    # trash, shared-with-me, photos, etc. which shouldn't be treated as a
    # plain bidirectional folder tree).
    "remote_root": "/my-files",
    # How often (seconds) the background daemon polls for changes.
    "interval_seconds": 900,
    # Whether a deletion on one side is propagated to the other side.
    "sync_deletions": True,
    # Safety net: log what WOULD happen without touching any file.
    # Flip to false once you've reviewed the activity log and trust it.
    "dry_run": True,
}


def load_config():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULTS)
        return dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        data = {}
    merged = dict(DEFAULTS)
    merged.update(data)
    return merged


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
