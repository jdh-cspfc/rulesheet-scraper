import os
import sqlite3


DATA_DIR = "data"
MAIN_DB_NAME = "main.db"


def get_main_db_path() -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, MAIN_DB_NAME)


def init_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS machines (
            opdb_id      TEXT PRIMARY KEY,
            name         TEXT,
            manufacturer TEXT,
            year         INTEGER,
            group_id     TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS links (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            opdb_id      TEXT,
            group_id     TEXT,
            alias_id     TEXT,
            url          TEXT NOT NULL,
            source_name  TEXT NOT NULL,
            content_type TEXT NOT NULL,
            title        TEXT NOT NULL,
            author       TEXT,
            channel      TEXT,
            first_seen   DATE NOT NULL,
            last_seen    DATE NOT NULL,
            status       TEXT NOT NULL CHECK (status IN ('active', 'removed')),
            UNIQUE (source_name, url)
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_links_source_name
        ON links (source_name)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_links_source_url
        ON links (source_name, url)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_links_status
        ON links (status)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_links_opdb_id
        ON links (opdb_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_links_group_id
        ON links (group_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_links_alias_id
        ON links (alias_id)
    """)

    conn.commit()


def read_links_for_source(conn: sqlite3.Connection, source_name: str) -> list[dict]:
    cursor = conn.execute("""
        SELECT
            id,
            opdb_id,
            group_id,
            alias_id,
            url,
            source_name,
            content_type,
            title,
            author,
            channel,
            first_seen,
            last_seen,
            status
        FROM links
        WHERE source_name = ?
    """, (source_name,))

    return [
        {
            "id": row[0],
            "opdb_id": row[1],
            "group_id": row[2],
            "alias_id": row[3],
            "url": row[4],
            "source_name": row[5],
            "content_type": row[6],
            "title": row[7],
            "author": row[8],
            "channel": row[9],
            "first_seen": row[10],
            "last_seen": row[11],
            "status": row[12],
        }
        for row in cursor.fetchall()
    ]


def count_active_links_for_source(conn: sqlite3.Connection, source_name: str) -> int:
    cursor = conn.execute("""
        SELECT COUNT(*)
        FROM links
        WHERE source_name = ? AND status = 'active'
    """, (source_name,))

    return cursor.fetchone()[0]


def insert_link(conn: sqlite3.Connection, record: dict):
    conn.execute("""
        INSERT INTO links (
            opdb_id,
            group_id,
            alias_id,
            url,
            source_name,
            content_type,
            title,
            author,
            channel,
            first_seen,
            last_seen,
            status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        record.get("opdb_id"),
        record.get("group_id"),
        record.get("alias_id"),
        record["url"],
        record["source_name"],
        record["content_type"],
        record["title"],
        record.get("author"),
        record.get("channel"),
        record["first_seen"],
        record["last_seen"],
        record["status"],
    ))


def update_link_from_scrape(conn: sqlite3.Connection, existing: dict, new: dict, today: str):
    opdb_id = new.get("opdb_id") if new.get("opdb_id") is not None else existing.get("opdb_id")
    group_id = new.get("group_id") if new.get("group_id") is not None else existing.get("group_id")
    alias_id = new.get("alias_id") if new.get("alias_id") is not None else existing.get("alias_id")

    conn.execute("""
        UPDATE links
        SET
            opdb_id = ?,
            group_id = ?,
            alias_id = ?,
            content_type = ?,
            title = ?,
            author = ?,
            channel = ?,
            last_seen = ?,
            status = 'active'
        WHERE url = ? AND source_name = ?
    """, (
        opdb_id,
        group_id,
        alias_id,
        new["content_type"],
        new["title"],
        new.get("author"),
        new.get("channel"),
        today,
        existing["url"],
        existing["source_name"],
    ))


def mark_link_removed(conn: sqlite3.Connection, url: str, source_name: str):
    conn.execute("""
        UPDATE links
        SET status = 'removed'
        WHERE url = ? AND source_name = ?
    """, (url, source_name))


def sync_source_records(
    conn: sqlite3.Connection,
    source: dict,
    new_records: list[dict],
    today: str,
) -> dict:
    source_name = source["name"]

    existing_records = read_links_for_source(conn, source_name)

    existing_by_url = {record["url"]: record for record in existing_records}
    new_by_url = {record["url"]: record for record in new_records}

    added_urls = []
    removed_urls = []
    changed_urls = []
    reappeared_urls = []

    for url, new_record in new_by_url.items():
        if url not in existing_by_url:
            insert_link(conn, new_record)
            added_urls.append(url)
            continue

        existing = existing_by_url[url]

        if existing["status"] == "removed":
            reappeared_urls.append(url)

        if (
            existing["title"] != new_record["title"]
            or existing.get("author") != new_record.get("author")
            or existing.get("channel") != new_record.get("channel")
            or existing.get("content_type") != new_record.get("content_type")
            or (
                new_record.get("opdb_id") is not None
                and existing.get("opdb_id") != new_record.get("opdb_id")
            )
            or (
                new_record.get("group_id") is not None
                and existing.get("group_id") != new_record.get("group_id")
            )
            or (
                new_record.get("alias_id") is not None
                and existing.get("alias_id") != new_record.get("alias_id")
            )
        ):
            changed_urls.append(url)

        update_link_from_scrape(conn, existing, new_record, today)

    for url, existing in existing_by_url.items():
        if existing["status"] == "active" and url not in new_by_url:
            mark_link_removed(conn, url, source_name)
            removed_urls.append(url)

    conn.commit()

    return {
        "has_changes": bool(added_urls or removed_urls or changed_urls or reappeared_urls),
        "added_urls": sorted(added_urls),
        "removed_urls": sorted(removed_urls),
        "changed_urls": sorted(changed_urls),
        "reappeared_urls": sorted(reappeared_urls),
    }