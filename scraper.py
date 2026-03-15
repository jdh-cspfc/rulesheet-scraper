import json
import sqlite3
from datetime import date
import requests
from bs4 import BeautifulSoup
import db
import os
from urllib.parse import urljoin
import re


HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; research-scraper/1.0)"}

def extract_author(a_tag, author_pattern: dict) -> str | None:
    if not author_pattern:
        return None
    
    pattern_type = author_pattern.get("type")
    
    if pattern_type == "parens_in_parent":
        # e.g. <span>...<a>Title</a> (Author Name)</span>
        parent_text = a_tag.parent.get_text(strip=True)
        match = re.search(r'\(([^)]+)\)', parent_text)
        return match.group(1) if match else None
    
    elif pattern_type == "sibling_text":
        # Text node immediately after the <a> tag
        sibling = a_tag.next_sibling
        if sibling and isinstance(sibling, str):
            match = re.search(r'\(([^)]+)\)', sibling.strip())
            return match.group(1) if match else sibling.strip() or None
        return None
    
    elif pattern_type == "attribute":
        # Author stored in an attribute on the <a> tag itself
        # e.g. {"type": "attribute", "name": "data-author"}
        attr = author_pattern.get("name")
        return a_tag.get(attr) if attr else None
    
    elif pattern_type == "selector":
        # Author in a separate element found relative to the <a> tag
        # e.g. {"type": "selector", "selector": ".author-name"}
        sel = author_pattern.get("selector")
        el = a_tag.find_parent().select_one(sel) if sel else None
        return el.get_text(strip=True) if el else None
    
    return None

def load_sources(path:str = "config/sources.json") -> list[dict]:
    with open(path, "r") as f:
        return json.load(f)
    
def deduplicate_records(records: list[dict]) -> list[dict]:
    seen = set()
    deduped = []
    for r in records:
        if r["url"] not in seen:
            seen.add(r["url"])
            deduped.append(r)
    return deduped

def scrape_source(source: dict) -> list[dict]:
    headers = {**HEADERS, "User-Agent": source.get("user_agent", HEADERS["User-Agent"])}
    response = requests.get(source["url"], headers=headers)
    response.raise_for_status()

    json_path = source.get("json_content_path")
    if json_path:
        data = response.json()
        html = data
        for key in json_path:
            html = html[key]
    else:
        html = response.text

    soup = BeautifulSoup(html, "html.parser")
    today = date.today().isoformat()

    json_in_script = source.get("json_in_script")
    if json_in_script:
        search_text = json_in_script["search_text"]
        script_tags = soup.find_all("script")
        machines_data = None
        for script in script_tags:
            if script.string and search_text in script.string:
                # Data is double-escaped inside a Next.js push call
                # First decode the outer string layer
                inner = script.string
                inner = inner.replace('\\"', '"').replace('\\\\', '\\')
                # Find the start of the machines array
                start_marker = '"machines":['
                start_idx = inner.find(start_marker)
                if start_idx != -1:
                    array_start = start_idx + len(start_marker) - 1  # position of '['
                    # Use json decoder to extract just the array
                    try:
                        decoder = json.JSONDecoder()
                        machines_data, _ = decoder.raw_decode(inner, array_start)
                        break
                    except json.JSONDecodeError as e:
                        print(f"  DEBUG: JSON parse error: {e}")
                        continue
        if machines_data is None:
            print(f"  WARNING: Could not find machines data in page")
            return []
        results = []
        for machine in machines_data:
            name = machine.get(json_in_script["name_key"], "").strip()
            machine_id = machine.get(json_in_script["id_key"], "")
            if not name or not machine_id:
                continue
            url_path = json_in_script["url_template"].replace("{id}", machine_id)
            full_url = source["base_url"] + url_path
            results.append({
                "url": full_url,
                "source": source["url"],
                "source_name": source["name"],
                "title": name,
                "author": None,
                "first_seen": today,
                "last_seen": today,
                "status": "active"
            })
        return deduplicate_records(results)

    links = soup.select(source["selector"])

    stop_before = source.get("stop_before")
    skip_hrefs = source.get("skip_hrefs", [])

    if stop_before:
        filtered = []
        for a in links:
            prev = a.find_previous(string=lambda t: stop_before in t)
            if prev:
                break
            filtered.append(a)
        links = filtered

    href_prefix = source.get("href_prefix")
    author_pattern = source.get("author_pattern")

    results = []
    for a in links:
        title = a.get_text(strip=True)
        href = a.get("href", "")
        
        if href in skip_hrefs:
            continue
        
        if href_prefix:
            if not href.startswith(href_prefix):
                continue
            full_url = source["base_url"] + href
        else:
            if not href or href.startswith("#"):
                continue
            full_url = urljoin(source["url"], href)

        results.append({
            "url": full_url,
            "source": source["url"],
            "source_name": source["name"],
            "title": title,
            "author": extract_author(a, author_pattern),
            "first_seen": today,
            "last_seen": today,
            "status": "active"
        })

    return deduplicate_records(results)

def run():
    sources = load_sources()

    for source in sources:
        print(f"Scraping {source['name']}...")
        new_records = scrape_source(source)
        print(f"Found {len(new_records)} links")

        db_path = db.get_db_path(source["name"])
        today = date.today().isoformat()

        # If no DB exists yet, just write fresh
        if not os.path.exists(db_path):
            print("No existing DB found, writing fresh...")
            conn = sqlite3.connect(db_path)
            db.init_db(conn)
            db.write_records(conn, new_records)
            conn.close()
            print(f"Written to {db_path}")
            continue

        # DB exists - read active records and diff
        conn = sqlite3.connect(db_path)
        old_active = db.read_active_records(conn)
        old_removed = db.read_removed_records(conn)
        conn.close()

        if not db.diff_records(old_active, old_removed, new_records):
            print(f"No changes detected for {source['name']}, skipping...")
            continue

        # Changes detected - archive old DB and write fresh
        print(f"Changes detected for {source['name']}, archiving and writing fresh DB...")
        db.archive_db(source["name"])

        # Build full record set - active + carried over removed
        carried_removed = []
        new_url_set = {r["url"] for r in new_records}

        for old_record in old_active:
            if old_record["url"] not in new_url_set:
                carried_removed.append({
                    "url": old_record["url"],
                    "source": source["url"],
                    "source_name": source["name"],
                    "title": old_record["title"],
                    "first_seen": old_record["first_seen"],
                    "last_seen": today,
                    "status": "removed"
                })
        
        # Also carry over previously removed records, skipping any that have reappeared
        for r in old_removed:
            if r["url"] not in new_url_set:
                carried_removed.append({
                    "url": r["url"],
                    "source": r["source"],
                    "source_name": r["source_name"],
                    "title": r["title"],
                    "first_seen": r["first_seen"],
                    "last_seen": r["last_seen"],
                    "status": "removed"
                })
        

        # Delete old DB and write fresh
        os.remove(db_path)
        conn = sqlite3.connect(db_path)
        db.init_db(conn)
        db.write_records(conn, new_records)
        db.write_records(conn, carried_removed)
        conn.close()
        print(f"Written to {db_path}")

if __name__ == "__main__":
    run()