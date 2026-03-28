import os
import shutil
import sqlite3
from datetime import date


DATA_DIR = "data"


def get_db_path(source_name: str) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, f"{source_name}.db")


def init_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            url          TEXT PRIMARY KEY,
            source       TEXT NOT NULL,
            source_name  TEXT NOT NULL,
            title        TEXT NOT NULL,
            author       TEXT,
            opdb_id      TEXT,
            channel      TEXT,
            first_seen   DATE NOT NULL,
            last_seen    DATE NOT NULL,
            status       TEXT NOT NULL DEFAULT 'active',
            content_type TEXT,
            enrichment   TEXT
        )
    """)
    conn.commit()


def write_records(conn: sqlite3.Connection, records: list[dict]):
    conn.executemany("""
        INSERT OR IGNORE INTO articles
            (url, source, source_name, title, author, opdb_id, channel, first_seen, last_seen, status, content_type, enrichment)
        VALUES
            (:url, :source, :source_name, :title, :author, :opdb_id, :channel, :first_seen, :last_seen, :status, :content_type, NULL)
    """, records)
    conn.commit()


def read_active_records(conn: sqlite3.Connection) -> list[dict]:
    cursor = conn.execute("""
        SELECT url, title, author, opdb_id, channel, first_seen
        FROM articles
        WHERE status = 'active'
    """)

    return [
        {
            "url": row[0],
            "title": row[1],
            "author": row[2],
            "opdb_id": row[3],
            "channel": row[4],
            "first_seen": row[5],
        }
        for row in cursor.fetchall()
    ]


def read_removed_records(conn: sqlite3.Connection) -> list[dict]:
    cursor = conn.execute("""
        SELECT url, source, source_name, title, author, opdb_id, channel, first_seen, last_seen
        FROM articles
        WHERE status = 'removed'
    """)

    return [
        {
            "url": row[0],
            "source": row[1],
            "source_name": row[2],
            "title": row[3],
            "author": row[4],
            "opdb_id": row[5],
            "channel": row[6],
            "first_seen": row[7],
            "last_seen": row[8],
        }
        for row in cursor.fetchall()
    ]


def get_diff_details(old_active: list[dict], old_removed: list[dict], new_records: list[dict]) -> dict:
    old_active_map = {record["url"]: record["title"] for record in old_active}
    old_active_urls = set(old_active_map.keys())

    old_removed_urls = {record["url"] for record in old_removed}

    new_map = {record["url"]: record["title"] for record in new_records}
    new_urls = set(new_map.keys())

    added_urls = sorted(new_urls - old_active_urls)
    removed_urls = sorted(old_active_urls - new_urls)

    changed_titles = sorted(
        url
        for url in (old_active_urls & new_urls)
        if old_active_map[url] != new_map[url]
    )

    reappeared_urls = sorted(new_urls & old_removed_urls)

    has_changes = bool(added_urls or removed_urls or changed_titles or reappeared_urls)

    return {
        "has_changes": has_changes,
        "added_urls": added_urls,
        "removed_urls": removed_urls,
        "changed_titles": changed_titles,
        "reappeared_urls": reappeared_urls,
    }


def archive_db(source_name: str):
    archive_dir = os.path.join(DATA_DIR, "archive")
    os.makedirs(archive_dir, exist_ok=True)

    source_path = get_db_path(source_name)
    archive_path = os.path.join(
        archive_dir,
        f"{source_name}_{date.today().isoformat()}.db"
    )

    shutil.copy2(source_path, archive_path)
    print(f"Archived to {archive_path}")