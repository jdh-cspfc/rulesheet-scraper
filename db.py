import sqlite3
import os
from datetime import date


DATA_DIR = "data"

def get_db_path(source_name: str) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, f"{source_name}.db")

def init_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            url         TEXT PRIMARY KEY,
            source      TEXT NOT NULL,
            source_name TEXT NOT NULL,
            title       TEXT NOT NULL,
            author      TEXT,
            opdb_id     TEXT,
            channel     TEXT,
            first_seen  DATE NOT NULL,
            last_seen   DATE NOT NULL,
            status      TEXT NOT NULL DEFAULT 'active',
            content_type TEXT,
            enrichment  TEXT
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
        SELECT url, title, first_seen FROM articles WHERE status = 'active'
    """)
    return [{"url": row[0], "title": row[1], "first_seen": row[2]} for row in cursor.fetchall()]

def read_removed_records(conn: sqlite3.Connection) -> list[dict]:
    cursor = conn.execute("""
        SELECT url, source, source_name, title, author, opdb_id, channel, first_seen, last_seen 
        FROM articles WHERE status = 'removed'
    """)
    return [{"url": row[0], "source": row[1], "source_name": row[2], "title": row[3],
             "author": row[4], "opdb_id": row[5], "channel": row[6],
             "first_seen": row[7], "last_seen": row[8]} for row in cursor.fetchall()]

def diff_records(old_active, old_removed, new_records):
    old_active_map = {r["url"]: r["title"] for r in old_active}
    old_removed_urls = {r["url"] for r in old_removed}
    new_map = {r["url"]: r["title"] for r in new_records}

    for url in new_map:
        if url in old_removed_urls:
            print(f"  DIFF: reappeared URL: {url}")
            return True

    for url, title in new_map.items():
        if old_active_map.get(url) != title:
            print(f"  DIFF: url={url!r} old={old_active_map.get(url)!r} new={title!r}")
            return True

    return False

def archive_db(source_name: str):
    import shutil
    archive_dir = os.path.join(DATA_DIR, "archive")
    os.makedirs(archive_dir, exist_ok=True)
    src = get_db_path(source_name)
    dst = os.path.join(archive_dir, f"{source_name}_{date.today().isoformat()}.db")
    shutil.copy2(src, dst)
    print(f"Archived to {dst}")