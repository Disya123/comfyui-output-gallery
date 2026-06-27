"""SQLite storage for the Output Gallery.

Single connection guarded by a lock (the DB is small and all access goes
through this module). The schema is created on first use and versioned with
``PRAGMA user_version`` so future migrations are possible.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from typing import Any, Optional

from .settings_paths import get_db_path

_LOGGER = logging.getLogger(__name__)

_SCHEMA_VERSION = 1

_lock = threading.RLock()
_conn: Optional[sqlite3.Connection] = None


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        path = get_db_path(create_dir=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _init_schema(conn)
        _conn = conn
    return _conn


def get_conn() -> sqlite3.Connection:
    """Return the shared connection (thread-safe via the module lock)."""

    with _lock:
        return _connect()


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS images (
    filename      TEXT PRIMARY KEY,   -- path relative to output dir, forward slashes
    rel_path      TEXT NOT NULL,
    mtime         REAL NOT NULL,
    size_bytes    INTEGER NOT NULL,
    width         INTEGER NOT NULL,
    height        INTEGER NOT NULL,
    positive      TEXT,
    negative      TEXT,
    params        TEXT,                -- JSON {seed, steps, cfg, sampler, scheduler, model, denoise}
    raw_prompt    TEXT,
    raw_workflow  TEXT,
    indexed_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS favorites (
    filename  TEXT PRIMARY KEY,
    added_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS image_tags (
    filename  TEXT NOT NULL,
    tag_id    INTEGER NOT NULL,
    PRIMARY KEY (filename, tag_id),
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_images_mtime ON images(mtime);
CREATE INDEX IF NOT EXISTS idx_favorites_filename ON favorites(filename);
"""

_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS images_fts USING fts5(
    positive,
    negative,
    filename UNINDEXED,
    content='images',
    content_rowid='rowid'
);
"""

# Keep the FTS table in sync with the images table.
_FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS images_ai AFTER INSERT ON images BEGIN
    INSERT INTO images_fts(rowid, positive, negative, filename)
    VALUES (new.rowid, coalesce(new.positive,''), coalesce(new.negative,''), new.filename);
END;
CREATE TRIGGER IF NOT EXISTS images_ad AFTER DELETE ON images BEGIN
    INSERT INTO images_fts(images_fts, rowid, positive, negative, filename)
    VALUES ('delete', old.rowid, coalesce(old.positive,''), coalesce(old.negative,''), old.filename);
END;
CREATE TRIGGER IF NOT EXISTS images_au AFTER UPDATE ON images BEGIN
    INSERT INTO images_fts(images_fts, rowid, positive, negative, filename)
    VALUES ('delete', old.rowid, coalesce(old.positive,''), coalesce(old.negative,''), old.filename);
    INSERT INTO images_fts(rowid, positive, negative, filename)
    VALUES (new.rowid, coalesce(new.positive,''), coalesce(new.negative,''), new.filename);
END;
"""


def _init_schema(conn: sqlite3.Connection) -> None:
    with conn:  # single transaction
        conn.executescript(_SCHEMA_SQL)
        try:
            conn.executescript(_FTS_SQL)
            conn.executescript(_FTS_TRIGGERS)
        except sqlite3.OperationalError as exc:
            # FTS5 may be unavailable on minimal SQLite builds.
            _LOGGER.warning("FTS5 unavailable, search will be disabled: %s", exc)
        conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")


# --------------------------------------------------------------------------- #
# Image write/read
# --------------------------------------------------------------------------- #


def upsert_image(record: dict) -> None:
    """Insert or replace an image record (dict keys match the columns)."""

    conn = get_conn()
    params_json = record.get("params")
    if isinstance(params_json, (dict, list)):
        params_json = json.dumps(params_json, ensure_ascii=False)
    with _lock, conn:
        conn.execute(
            """
            INSERT INTO images
                (filename, rel_path, mtime, size_bytes, width, height,
                 positive, negative, params, raw_prompt, raw_workflow, indexed_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(filename) DO UPDATE SET
                rel_path=excluded.rel_path,
                mtime=excluded.mtime,
                size_bytes=excluded.size_bytes,
                width=excluded.width,
                height=excluded.height,
                positive=excluded.positive,
                negative=excluded.negative,
                params=excluded.params,
                raw_prompt=excluded.raw_prompt,
                raw_workflow=excluded.raw_workflow,
                indexed_at=excluded.indexed_at
            """,
            (
                record["filename"],
                record["rel_path"],
                record["mtime"],
                record["size_bytes"],
                record["width"],
                record["height"],
                record.get("positive"),
                record.get("negative"),
                params_json,
                record.get("raw_prompt"),
                record.get("raw_workflow"),
                record.get("indexed_at"),
            ),
        )


def delete_image(filename: str) -> None:
    conn = get_conn()
    with _lock, conn:
        conn.execute("DELETE FROM image_tags WHERE filename=?", (filename,))
        conn.execute("DELETE FROM favorites WHERE filename=?", (filename,))
        conn.execute("DELETE FROM images WHERE filename=?", (filename,))


def get_image_mtime(filename: str) -> Optional[float]:
    conn = get_conn()
    with _lock:
        row = conn.execute(
            "SELECT mtime FROM images WHERE filename=?", (filename,)
        ).fetchone()
    return row["mtime"] if row else None


def _row_to_summary(row: sqlite3.Row) -> dict:
    filename = row["filename"]
    return {
        "filename": filename,
        "url": f"{_static_base()}/{filename}",
        "thumb": f"/api/gallery/thumb?name={_quote(filename)}&w=512",
        "width": row["width"],
        "height": row["height"],
        "positive": row["positive"] or "",
        "negative": row["negative"] or "",
        "params": _loads(row["params"]),
        "favorite": row["is_favorite"] == 1,
        "tags": _split_tags(row["tags"]),
        "mtime": row["mtime"],
        "size_bytes": row["size_bytes"],
    }


def get_image(filename: str) -> Optional[dict]:
    conn = get_conn()
    with _lock:
        row = conn.execute(
            """
            SELECT i.*, (SELECT 1 FROM favorites f WHERE f.filename = i.filename) AS is_favorite,
                   (SELECT group_concat(t.name, '\x1f') FROM image_tags it
                    JOIN tags t ON t.id = it.tag_id
                    WHERE it.filename = i.filename) AS tags
            FROM images i WHERE i.filename = ?
            """,
            (filename,),
        ).fetchone()
    if row is None:
        return None
    base = _row_to_summary(row)
    base["raw_prompt"] = row["raw_prompt"]
    base["raw_workflow"] = row["raw_workflow"]
    return base


def query_images(
    *,
    query: str = "",
    tag: str = "",
    favorite: bool = False,
    min_width: int = 0,
    sort: str = "date",
    page: int = 1,
    limit: int = 48,
) -> dict:
    """Return a paginated, filtered, sorted list of image summaries."""

    conn = get_conn()
    order = {
        "date": "i.mtime DESC",
        "name": "i.filename ASC",
        "size": "i.size_bytes DESC",
        "width": "i.width DESC",
    }.get(sort, "i.mtime DESC")

    where = []
    params: list = []
    if favorite:
        where.append("EXISTS (SELECT 1 FROM favorites f WHERE f.filename = i.filename)")
    if min_width > 0:
        where.append("i.width >= ?")
        params.append(min_width)
    if tag:
        where.append(
            "EXISTS (SELECT 1 FROM image_tags it JOIN tags t ON t.id=it.tag_id "
            "WHERE it.filename = i.filename AND t.name = ?)"
        )
        params.append(tag)

    fts_available = _fts_available(conn)
    if query and fts_available:
        # FTS5 prefix match for fast exact-token search, plus LIKE fallback
        # for substring matches across token boundaries (e.g. "girl" → "1girl").
        fts_q = _fts_query(query)
        like = f"%{query}%"
        where.append(
            "(i.rowid IN (SELECT rowid FROM images_fts WHERE images_fts MATCH ?)"
            " OR i.positive LIKE ? OR i.negative LIKE ?)"
        )
        params.extend([fts_q, like, like])
    elif query:
        # Fallback: LIKE search when FTS5 is missing.
        like = f"%{query}%"
        where.append("(i.positive LIKE ? OR i.negative LIKE ?)")
        params.extend([like, like])

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    with _lock:
        total = conn.execute(
            f"SELECT COUNT(*) FROM images i{where_sql}", params
        ).fetchone()[0]

        offset = (page - 1) * limit
        rows = conn.execute(
            f"""
            SELECT i.*, (SELECT 1 FROM favorites f WHERE f.filename = i.filename) AS is_favorite,
                   (SELECT group_concat(t.name, '\x1f') FROM image_tags it
                    JOIN tags t ON t.id = it.tag_id
                    WHERE it.filename = i.filename) AS tags
            FROM images i{where_sql}
            ORDER BY {order}
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()

    return {
        "items": [_row_to_summary(r) for r in rows],
        "total": total,
        "page": page,
        "limit": limit,
    }


# --------------------------------------------------------------------------- #
# Favorites
# --------------------------------------------------------------------------- #


def set_favorite(filename: str, favorite: bool) -> None:
    import time

    conn = get_conn()
    with _lock, conn:
        if favorite:
            conn.execute(
                "INSERT INTO favorites(filename, added_at) VALUES (?, ?) "
                "ON CONFLICT(filename) DO NOTHING",
                (filename, time.time()),
            )
        else:
            conn.execute("DELETE FROM favorites WHERE filename=?", (filename,))


# --------------------------------------------------------------------------- #
# Tags
# --------------------------------------------------------------------------- #


def _tag_id(conn: sqlite3.Connection, name: str, create: bool) -> Optional[int]:
    row = conn.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()
    if row is not None:
        return row["id"]
    if not create:
        return None
    cur = conn.execute("INSERT INTO tags(name) VALUES (?)", (name,))
    return cur.lastrowid


def add_tag(filename: str, name: str) -> None:
    conn = get_conn()
    with _lock, conn:
        tid = _tag_id(conn, name, create=True)
        conn.execute(
            "INSERT INTO image_tags(filename, tag_id) VALUES (?, ?) "
            "ON CONFLICT DO NOTHING",
            (filename, tid),
        )


def remove_tag(filename: str, name: str) -> None:
    conn = get_conn()
    with _lock, conn:
        tid = _tag_id(conn, name, create=False)
        if tid is None:
            return
        conn.execute(
            "DELETE FROM image_tags WHERE filename=? AND tag_id=?", (filename, tid)
        )
        # Prune unused tags.
        conn.execute(
            "DELETE FROM tags WHERE id=? AND NOT EXISTS "
            "(SELECT 1 FROM image_tags WHERE tag_id=?)",
            (tid, tid),
        )


def list_tags() -> list:
    conn = get_conn()
    with _lock:
        rows = conn.execute(
            """
            SELECT t.name, COUNT(it.filename) AS count
            FROM tags t
            LEFT JOIN image_tags it ON it.tag_id = t.id
            GROUP BY t.id
            ORDER BY t.name COLLATE NOCASE
            """
        ).fetchall()
    return [{"name": r["name"], "count": r["count"]} for r in rows]


# --------------------------------------------------------------------------- #
# Stats
# --------------------------------------------------------------------------- #


def get_stats() -> dict:
    conn = get_conn()
    with _lock:
        total = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        fav = conn.execute("SELECT COUNT(*) FROM favorites").fetchone()[0]
        latest = conn.execute("SELECT MAX(indexed_at) FROM images").fetchone()[0]
    return {"total_images": total, "favorites": fav, "last_indexed": latest}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _fts_available(conn: sqlite3.Connection) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='images_fts'"
        ).fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False


def _fts_query(query: str) -> str:
    """Build an FTS5 MATCH expression from a free-text query."""

    query = (query or "").strip()
    if not query:
        return ""
    
    import re
    # Replace punctuation with spaces to allow exact word matching
    query = re.sub(r'[^\w\s]', ' ', query)
    tokens = [t for t in query.split() if t]
    # Use prefix match for better search
    quoted = ['"' + t.replace('"', '""') + '"*' for t in tokens]
    return " ".join(quoted)


def _static_base() -> str:
    from . import config

    return config.GALLERY_STATIC_URL


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


def _loads(value):
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _split_tags(value) -> list:
    if not value:
        return []
    return [t for t in value.split("\x1f") if t]
