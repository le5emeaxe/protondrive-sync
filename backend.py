"""
Wrapper around the official `proton-drive` CLI.

Conflict strategies are ALWAYS passed explicitly (-f/-d). Without them the
CLI prompts interactively for a resolution, which would hang a headless
background daemon forever.
"""

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Iterator, List, Optional

PROTON_DRIVE_BIN = shutil.which("proton-drive") or "proton-drive"


class ProtonDriveError(Exception):
    pass


@dataclass
class DriveEntry:
    path: str                 # full remote path, e.g. /my-files/Documents/foo.pdf
    name: str
    is_folder: bool
    is_virtual_root: bool = False
    size: int = 0
    mtime: str = ""
    mediatype: str = ""
    uid: str = ""


def _run(args: List[str], timeout: Optional[int] = 120) -> str:
    cmd = [PROTON_DRIVE_BIN] + args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise ProtonDriveError("Le binaire 'proton-drive' est introuvable dans le PATH.")
    except subprocess.TimeoutExpired:
        raise ProtonDriveError(f"Commande expirée: {' '.join(cmd)}")

    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip() or f"Code de sortie {proc.returncode}"
        raise ProtonDriveError(msg)

    return proc.stdout


def _run_json(args: List[str], timeout: Optional[int] = 120):
    out = _run(args, timeout=timeout).strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise ProtonDriveError(f"Réponse JSON inattendue: {e}\n{out[:500]}")


def list_path(path: str) -> List[DriveEntry]:
    data = _run_json(["filesystem", "list", "-j", path]) or []
    if not isinstance(data, list):
        raise ProtonDriveError(f"Réponse inattendue pour 'filesystem list {path}': {data!r}")
    entries: List[DriveEntry] = []

    if path == "/":
        for item in data:
            if not isinstance(item, dict):
                continue
            p = item.get("path", "")
            name = p.lstrip("/") or p
            entries.append(DriveEntry(path=p, name=name, is_folder=True, is_virtual_root=True))
        return entries

    for item in data:
        if not isinstance(item, dict):
            continue
        name_field = item.get("name") or {}
        name = name_field.get("value") if isinstance(name_field, dict) else str(name_field or "")
        if not name:
            continue
        is_folder = item.get("type") == "folder"
        full_path = path.rstrip("/") + "/" + name
        entries.append(DriveEntry(
            path=full_path,
            name=name,
            is_folder=is_folder,
            size=item.get("totalStorageSize", 0) or 0,
            mtime=item.get("modificationTime", "") or "",
            mediatype=item.get("mediaType", "") or "",
            uid=item.get("uid", "") or "",
        ))
    return entries


def walk_remote(path: str) -> Iterator[DriveEntry]:
    """Yield every DriveEntry (file or folder) recursively under `path`."""
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            children = list_path(current)
        except ProtonDriveError:
            continue
        for entry in children:
            yield entry
            if entry.is_folder:
                stack.append(entry.path)


def info(path: str):
    return _run_json(["filesystem", "info", "-j", path])


def upload(local_paths: List[str], parent_path: str,
           file_strategy: str = "replace", folder_strategy: str = "merge"):
    return _run_json([
        "filesystem", "upload", "-j",
        "-f", file_strategy, "-d", folder_strategy,
        *local_paths, parent_path,
    ], timeout=None)


def download(remote_paths: List[str], local_folder: str,
             file_strategy: str = "replace", folder_strategy: str = "merge"):
    return _run_json([
        "filesystem", "download", "-j",
        "-f", file_strategy, "-d", folder_strategy,
        *remote_paths, local_folder,
    ], timeout=None)


def create_folder(parent_path: str, name: str):
    return _run_json(["filesystem", "create-folder", "-j", parent_path, name])


def trash(paths: List[str]):
    return _run_json(["filesystem", "trash", "-j", *paths])


def delete_permanently(paths: List[str]):
    return _run_json(["filesystem", "delete", "-j", *paths])


def check_auth():
    """Best-effort authentication check.

    This CLI version has no dedicated `auth status`/`whoami` subcommand
    (confirmed against its --help), so this infers status from whether a
    lightweight read call succeeds. Returns (is_authenticated, detail),
    where detail is the error text when not authenticated (or the check
    itself failed for another reason — this can't fully distinguish "not
    logged in" from e.g. "no network", but is a reasonable proxy).

    Deliberately catches ANY exception, not just ProtonDriveError: an
    unauthenticated call might return a JSON shape we don't expect (an
    error object instead of a list, for instance), and a bug in parsing
    that must never crash the background thread doing this check."""
    try:
        list_path("/")
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def get_account_email(remote_root: str = "/my-files"):
    """Best-effort: read the owner email from a real file/folder's
    metadata (the `ownedBy.email` field seen in `filesystem info`
    output). Returns None if it can't be determined (e.g. empty folder
    and the root node itself doesn't expose it)."""
    try:
        data = info(remote_root)
    except ProtonDriveError:
        data = None
    if data:
        email = (data.get("ownedBy") or {}).get("email")
        if email:
            return email
    try:
        children = list_path(remote_root)
    except ProtonDriveError:
        children = []
    for entry in children[:5]:
        try:
            data = info(entry.path)
        except ProtonDriveError:
            continue
        email = (data.get("ownedBy") or {}).get("email")
        if email:
            return email
    return None


def run_auth_login():
    """Runs `proton-drive auth login`. This typically opens the system
    browser for an OAuth-style login and blocks until it completes, so
    call this from a background thread — it's interactive from the
    user's side (they complete the login in the browser)."""
    return _run(["auth", "login"], timeout=300)
