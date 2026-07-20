"""SQLite-backed known-state table (what we last saw on each side for every
path) and an activity log (what the sync engine actually did / would do)."""

import sqlite3
import time


class StateDB:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS known_state (
                relpath TEXT PRIMARY KEY,
                is_folder INTEGER,
                remote_uid TEXT,
                remote_mtime TEXT,
                remote_size INTEGER,
                local_mtime REAL,
                local_size INTEGER
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                action TEXT,
                relpath TEXT,
                detail TEXT,
                status TEXT
            )
        """)
        self.conn.commit()

    # ---------- known_state ----------
    def get_known(self):
        cur = self.conn.execute(
            "SELECT relpath, is_folder, remote_uid, remote_mtime, remote_size, "
            "local_mtime, local_size FROM known_state"
        )
        result = {}
        for row in cur.fetchall():
            result[row[0]] = {
                "is_folder": bool(row[1]),
                "remote_uid": row[2],
                "remote_mtime": row[3],
                "remote_size": row[4],
                "local_mtime": row[5],
                "local_size": row[6],
            }
        return result

    def set_known(self, relpath, is_folder, remote_uid=None, remote_mtime=None,
                  remote_size=None, local_mtime=None, local_size=None):
        self.conn.execute("""
            INSERT INTO known_state
                (relpath, is_folder, remote_uid, remote_mtime, remote_size, local_mtime, local_size)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(relpath) DO UPDATE SET
                is_folder=excluded.is_folder,
                remote_uid=excluded.remote_uid,
                remote_mtime=excluded.remote_mtime,
                remote_size=excluded.remote_size,
                local_mtime=excluded.local_mtime,
                local_size=excluded.local_size
        """, (relpath, int(is_folder), remote_uid, remote_mtime, remote_size, local_mtime, local_size))
        self.conn.commit()

    def remove_known(self, relpath):
        self.conn.execute("DELETE FROM known_state WHERE relpath = ?", (relpath,))
        self.conn.commit()

    # ---------- activity_log ----------
    def log(self, action, relpath, detail="", status="ok"):
        self.conn.execute(
            "INSERT INTO activity_log (ts, action, relpath, detail, status) VALUES (?, ?, ?, ?, ?)",
            (time.time(), action, relpath, detail, status),
        )
        self.conn.commit()

    def recent_activity(self, limit=200):
        cur = self.conn.execute(
            "SELECT ts, action, relpath, detail, status FROM activity_log ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return cur.fetchall()
