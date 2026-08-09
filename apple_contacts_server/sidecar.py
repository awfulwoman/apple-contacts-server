"""Local bookkeeping the Contacts framework can't hold itself: the mapping from
a caller's client-chosen `id` to CNContact's system-assigned `identifier`. Unlike
reminders, there's no LWW/tombstone contract to preserve here (see `store.py`'s
module docstring) so this is just an id lookup table — no `updated_at`, no
`deleted`, no cached content."""
from __future__ import annotations
import os
import sqlite3
import threading

_SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    id TEXT PRIMARY KEY,
    cn_identifier TEXT UNIQUE NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_contacts_cn_identifier ON contacts(cn_identifier);
"""


class Sidecar:
    def __init__(self, db_path: str):
        path = os.path.expanduser(db_path)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        # Handlers now run store calls in a thread pool (see http.py), so this
        # connection is genuinely shared across threads for the first time.
        self._lock = threading.Lock()

    def put(self, id: str, cn_identifier: str) -> None:
        with self._lock:
            # `cn_identifier` is UNIQUE too, so binding it to `id` can conflict
            # with a stale row left over from a diverged sidecar (restored
            # backup, DB copied between machines). That old row is no longer
            # meaningful — the CNContact it named now belongs to `id` — so it's
            # dropped in favour of the new mapping rather than raising.
            self._conn.execute(
                "DELETE FROM contacts WHERE cn_identifier = ? AND id != ?", (cn_identifier, id)
            )
            self._conn.execute(
                "INSERT INTO contacts (id, cn_identifier) VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET cn_identifier=excluded.cn_identifier",
                (id, cn_identifier),
            )
            self._conn.commit()

    def by_id(self, id: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT cn_identifier FROM contacts WHERE id = ?", (id,)).fetchone()
        return row[0] if row else None

    def by_cn_identifier(self, cn_identifier: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT id FROM contacts WHERE cn_identifier = ?", (cn_identifier,)).fetchone()
        return row[0] if row else None

    def all(self) -> list[tuple[str, str]]:
        with self._lock:
            return self._conn.execute("SELECT id, cn_identifier FROM contacts").fetchall()

    def delete_row(self, id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM contacts WHERE id = ?", (id,))
            self._conn.commit()
