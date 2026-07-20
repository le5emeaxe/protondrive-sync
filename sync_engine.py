"""
Bidirectional poll-based sync between a local folder and a Proton Drive
remote folder.

There is no live "events" API exposed by the CLI, so this walks both trees
on every run and diffs against the last known state (stored in StateDB) to
figure out what changed on which side since the previous run:

  - only local, unknown           -> new local file/folder  -> upload / mkdir remote
  - only remote, unknown          -> new remote file/folder -> download / mkdir local
  - known, missing on one side    -> was deleted there       -> propagate deletion (if enabled)
  - present both sides, changed
    on local only                 -> upload (replace)
  - present both sides, changed
    on remote only                -> download (replace)
  - present both sides, changed
    on BOTH sides                 -> real conflict -> keep both (never silently overwrite)

All mutating operations go through `_apply`, which honours dry_run (logs
what would happen, touches nothing) and always logs to the activity table.
"""

import os
import shutil

import backend


def local_scan(local_root):
    """dict[relpath] -> {"is_folder", "size", "mtime"} for everything under local_root."""
    result = {}
    for dirpath, dirnames, filenames in os.walk(local_root):
        rel_dir = os.path.relpath(dirpath, local_root)
        if rel_dir == ".":
            rel_dir = ""
        for d in dirnames:
            rel = os.path.join(rel_dir, d) if rel_dir else d
            result[rel] = {"is_folder": True, "size": 0, "mtime": None}
        for f in filenames:
            full = os.path.join(dirpath, f)
            rel = os.path.join(rel_dir, f) if rel_dir else f
            try:
                st = os.stat(full)
            except OSError:
                continue
            result[rel] = {"is_folder": False, "size": st.st_size, "mtime": st.st_mtime}
    return result


def remote_scan(remote_root):
    """dict[relpath] -> {"is_folder", "size", "mtime", "uid"} for everything under remote_root."""
    result = {}
    prefix = remote_root.rstrip("/") + "/"
    for entry in backend.walk_remote(remote_root):
        if not entry.path.startswith(prefix):
            continue
        rel = entry.path[len(prefix):]
        result[rel] = {
            "is_folder": entry.is_folder,
            "size": entry.size,
            "mtime": entry.mtime,
            "uid": entry.uid,
        }
    return result


class SyncEngine:
    def __init__(self, local_root, remote_root, db, dry_run=True, sync_deletions=True, logger=None):
        self.local_root = local_root
        self.remote_root = remote_root.rstrip("/") or "/my-files"
        self.db = db
        self.dry_run = dry_run
        self.sync_deletions = sync_deletions
        self.logger = logger or (lambda msg: None)

    # ---------- public entry point ----------
    def run(self):
        os.makedirs(self.local_root, exist_ok=True)

        local = local_scan(self.local_root)
        try:
            remote = remote_scan(self.remote_root)
        except backend.ProtonDriveError as e:
            self.db.log("error", "", str(e), "error")
            self.logger(f"ERREUR de synchronisation: {e}")
            return

        known = self.db.get_known()
        all_paths = set(local) | set(remote) | set(known)

        def is_folder_path(p):
            return bool((local.get(p) or {}).get("is_folder")
                         or (remote.get(p) or {}).get("is_folder")
                         or (known.get(p) or {}).get("is_folder"))

        folders = sorted((p for p in all_paths if is_folder_path(p)), key=lambda p: p.count("/"))
        files = sorted(p for p in all_paths if p not in set(folders))

        for rel in folders:
            self._sync_folder(rel, local.get(rel), remote.get(rel), known.get(rel))
        for rel in files:
            self._sync_file(rel, local.get(rel), remote.get(rel), known.get(rel))

    # ---------- helpers ----------
    def _remote_full(self, rel):
        return self.remote_root + "/" + rel if rel else self.remote_root

    def _local_full(self, rel):
        return os.path.join(self.local_root, rel) if rel else self.local_root

    def _apply(self, action, rel, fn, on_success=None):
        """Run fn() unless dry_run. Always logs. Only calls on_success() (state
        bookkeeping) after a REAL, successful execution — never in dry-run."""
        if self.dry_run:
            self.db.log(action, rel, "SIMULATION (dry-run) — aucune action réelle", "dry-run")
            self.logger(f"[simulation] {action}: {rel}")
            return
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - surface any failure to the log
            self.db.log(action, rel, str(e), "error")
            self.logger(f"ERREUR {action} {rel}: {e}")
            return
        self.db.log(action, rel, "", "ok")
        self.logger(f"{action}: {rel}")
        if on_success:
            on_success()

    def _record_file_state_after_write(self, rel):
        """Re-read the ground truth (local stat + remote info) after a file's
        content changed, instead of trusting pre-write snapshot values."""
        remote_full = self._remote_full(rel)
        local_full = self._local_full(rel)
        try:
            remote_info = backend.info(remote_full)
        except backend.ProtonDriveError:
            remote_info = None
        try:
            st = os.stat(local_full)
            local_mtime, local_size = st.st_mtime, st.st_size
        except OSError:
            local_mtime, local_size = None, None

        remote_uid = remote_mtime = remote_size = None
        if remote_info:
            remote_uid = remote_info.get("uid")
            remote_mtime = remote_info.get("modificationTime")
            remote_size = remote_info.get("totalStorageSize")

        self.db.set_known(rel, False, remote_uid=remote_uid, remote_mtime=remote_mtime,
                           remote_size=remote_size, local_mtime=local_mtime, local_size=local_size)

    # ---------- folders ----------
    def _sync_folder(self, rel, l, r, k):
        local_full = self._local_full(rel)
        remote_full = self._remote_full(rel)

        if l and not r:
            if k:
                if self.sync_deletions:
                    self._apply("delete_local_folder", rel,
                                 lambda: shutil.rmtree(local_full, ignore_errors=True),
                                 on_success=lambda: self.db.remove_known(rel))
                return
            parent = os.path.dirname(rel)
            parent_remote = self._remote_full(parent) if parent else self.remote_root
            self._apply("mkdir_remote", rel,
                         lambda: backend.create_folder(parent_remote, os.path.basename(rel)),
                         on_success=lambda: self.db.set_known(rel, True))
            return

        if r and not l:
            if k:
                if self.sync_deletions:
                    self._apply("trash_remote_folder", rel,
                                 lambda: backend.trash([remote_full]),
                                 on_success=lambda: self.db.remove_known(rel))
                return
            self._apply("mkdir_local", rel,
                         lambda: os.makedirs(local_full, exist_ok=True),
                         on_success=lambda: self.db.set_known(rel, True, remote_uid=r.get("uid")))
            return

        if l and r and not k:
            if self.dry_run:
                self.db.log("baseline_folder", rel, "SIMULATION — dossier déjà présent des deux côtés", "dry-run")
            else:
                self.db.set_known(rel, True, remote_uid=r.get("uid"))

    # ---------- files ----------
    def _sync_file(self, rel, l, r, k):
        local_full = self._local_full(rel)
        remote_full = self._remote_full(rel)
        parent = os.path.dirname(rel)
        parent_remote = self._remote_full(parent) if parent else self.remote_root
        local_dir = os.path.dirname(local_full) or self.local_root

        if l and not r:
            if k:
                if self.sync_deletions:
                    self._apply("delete_local", rel,
                                 lambda: os.remove(local_full),
                                 on_success=lambda: self.db.remove_known(rel))
                return
            self._apply("upload", rel,
                         lambda: backend.upload([local_full], parent_remote),
                         on_success=lambda: self._record_file_state_after_write(rel))
            return

        if r and not l:
            if k:
                if self.sync_deletions:
                    self._apply("trash_remote", rel,
                                 lambda: backend.trash([remote_full]),
                                 on_success=lambda: self.db.remove_known(rel))
                return
            os.makedirs(local_dir, exist_ok=True)
            self._apply("download", rel,
                         lambda: backend.download([remote_full], local_dir),
                         on_success=lambda: self._record_file_state_after_write(rel))
            return

        if l and r:
            local_changed = (
                not k
                or k.get("local_size") != l["size"]
                or k.get("local_mtime") is None
                or abs((k.get("local_mtime") or 0) - l["mtime"]) > 1
            )
            remote_changed = (
                not k
                or k.get("remote_mtime") != r["mtime"]
                or k.get("remote_size") != r["size"]
            )

            if k and local_changed and remote_changed:
                # Both sides moved on since the last sync: never silently pick
                # a winner. Fetch the remote version alongside (renamed by the
                # CLI's own keep-both logic), then push the local version as
                # the canonical copy.
                os.makedirs(local_dir, exist_ok=True)
                self._apply("conflict_keep_both_download", rel,
                             lambda: backend.download([remote_full], local_dir,
                                                       file_strategy="keep-both",
                                                       folder_strategy="keep-both"))
                self._apply("conflict_upload_local", rel,
                             lambda: backend.upload([local_full], parent_remote, file_strategy="replace"),
                             on_success=lambda: self._record_file_state_after_write(rel))
            elif local_changed:
                self._apply("upload", rel,
                             lambda: backend.upload([local_full], parent_remote, file_strategy="replace"),
                             on_success=lambda: self._record_file_state_after_write(rel))
            elif remote_changed:
                self._apply("download", rel,
                             lambda: backend.download([remote_full], local_dir, file_strategy="replace"),
                             on_success=lambda: self._record_file_state_after_write(rel))
            elif not k:
                if self.dry_run:
                    self.db.log("baseline_file", rel, "SIMULATION — fichier déjà présent des deux côtés", "dry-run")
                else:
                    self.db.set_known(rel, False, remote_uid=r.get("uid"), remote_mtime=r.get("mtime"),
                                       remote_size=r.get("size"), local_mtime=l["mtime"], local_size=l["size"])
