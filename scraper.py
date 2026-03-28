import glob
import json
import os
import re
import sqlite3
import time
from datetime import date, datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

import db


HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; research-scraper/1.0)"}


def slugify_url(url: str) -> str:
    """Convert a URL to a safe cache filename — must match capture.py."""
    url = re.sub(r"https?://[^/]+", "", url)
    url = re.sub(r"[^a-zA-Z0-9_-]", "_", url)
    return url.strip("_")[:200]


def load_sources(path: str = "config/sources.json") -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def deduplicate_records(records: list[dict]) -> list[dict]:
    seen_urls = set()
    deduplicated = []

    for record in records:
        url = record["url"]
        if url in seen_urls:
            continue

        seen_urls.add(url)
        deduplicated.append(record)

    return deduplicated


def add_warning(warnings: list[str], message: str):
    warnings.append(message)
    print(f"  WARNING: {message}")


def extract_author(a_tag, author_pattern: dict) -> str | None:
    if not author_pattern:
        return None

    pattern_type = author_pattern.get("type")

    if pattern_type == "parens_in_parent":
        parent_text = a_tag.parent.get_text(strip=True)
        match = re.search(r"\(([^)]+)\)", parent_text)
        return match.group(1) if match else None

    if pattern_type == "sibling_text":
        sibling = a_tag.next_sibling
        if sibling and isinstance(sibling, str):
            match = re.search(r"\(([^)]+)\)", sibling.strip())
            return match.group(1) if match else sibling.strip() or None
        return None

    if pattern_type == "attribute":
        attr_name = author_pattern.get("name")
        return a_tag.get(attr_name) if attr_name else None

    if pattern_type == "selector":
        selector = author_pattern.get("selector")
        element = a_tag.find_parent().select_one(selector) if selector else None
        return element.get_text(strip=True) if element else None

    return None


def first_text_node(element) -> str | None:
    """Return the first direct text node of an element, ignoring child tags."""
    if element is None:
        return None

    for child in element.children:
        if isinstance(child, str) and child.strip():
            return child.strip()

    return None


def build_record(
    source: dict,
    today: str,
    url: str,
    title: str,
    author: str | None = None,
    opdb_id: str | None = None,
    group_id: str | None = None,
    channel: str | None = None,
) -> dict:
    return {
        "url": url,
        "source_name": source["name"],
        "title": title,
        "author": author,
        "opdb_id": opdb_id,
        "group_id": group_id,
        "channel": channel,
        "first_seen": today,
        "last_seen": today,
        "status": "active",
        "content_type": source.get("content_type"),
    }


def fetch_page_soup(
    url: str,
    headers: dict,
    use_cache: bool = False,
) -> tuple[BeautifulSoup | None, str | None]:
    try:
        if use_cache:
            slug = slugify_url(url)
            cache_path = f"cache/pages/{slug}.html"

            if os.path.exists(cache_path):
                with open(cache_path, encoding="utf-8") as f:
                    html = f.read()
                return BeautifulSoup(html, "html.parser"), None

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser"), None

    except Exception as e:
        return None, f"Failed to fetch page {url}: {e}"


def fetch_title_from_page(
    url: str,
    title_selector: str,
    author_selector: str | None,
    headers: dict,
    use_cache: bool = False,
    title_filter_text: str | None = None,
    title_strip_suffix: str | None = None,
    title_attribute: str | None = None,
    author_attribute: str | None = None
) -> tuple[str | None, str | None, str | None]:
    """Fetch an article page and extract title and optionally author using CSS selectors."""
    try:
        if use_cache:
            slug = slugify_url(url)
            cache_path = f"cache/pages/{slug}.html"
            if os.path.exists(cache_path):
                with open(cache_path, encoding="utf-8") as f:
                    html = f.read()
                soup = BeautifulSoup(html, "html.parser")
            else:
                response = requests.get(url, headers=headers, timeout=10)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
        else:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

        title = None
        if title_filter_text:
            for el in soup.select(title_selector):
                text = el.get(title_attribute, "").strip() if title_attribute else el.get_text(strip=True)
                if title_filter_text.lower() in text.lower():
                    title = text
                    if title_strip_suffix and title.endswith(title_strip_suffix):
                        title = title[:-len(title_strip_suffix)].strip()
                    break
        else:
            title_el = soup.select_one(title_selector)
            if title_el:
                if title_attribute:
                    title = title_el.get(title_attribute, "").strip() or None
                else:
                    title = title_el.get_text(strip=True) or None

                if title and title_strip_suffix and title.endswith(title_strip_suffix):
                    title = title[:-len(title_strip_suffix)].strip()

        author = None
        if author_selector:
            author_el = soup.select_one(author_selector)
            if author_el:
                if author_attribute:
                    author = author_el.get(author_attribute, "").strip() or None
                else:
                    author = author_el.get_text(strip=True) or None

        return title, author, None

    except Exception as e:
        warning = f"Failed to fetch title from {url}: {e}"
        return None, None, warning


def parse_json_content(response, source: dict) -> tuple[str | dict | list | None, str | None]:
    try:
        json_path = source.get("json_content_path")
        if json_path:
            data = response.json()
            content = data
            for key in json_path:
                content = content[key]
            return content, None

        return response.text, None

    except Exception as e:
        return None, f"Failed to parse source content for {source['name']}: {e}"


def scrape_json_in_script_source(
    source: dict,
    soup: BeautifulSoup,
    today: str,
    warnings: list[str],
) -> list[dict]:
    config = source["json_in_script"]
    search_text = config["search_text"]
    script_tags = soup.find_all("script")

    machines_data = None

    for script in script_tags:
        if not script.string or search_text not in script.string:
            continue

        inner = script.string
        inner = inner.replace('\\"', '"').replace("\\\\", "\\")

        start_marker = '"machines":['
        start_index = inner.find(start_marker)

        if start_index == -1:
            continue

        array_start = start_index + len(start_marker) - 1

        try:
            decoder = json.JSONDecoder()
            machines_data, _ = decoder.raw_decode(inner, array_start)
            break
        except json.JSONDecodeError as e:
            add_warning(warnings, f"JSON parse error in {source['name']}: {e}")

    if machines_data is None:
        add_warning(warnings, f"Could not find machines data in page for {source['name']}")
        return []

    results = []

    for machine in machines_data:
        name = machine.get(config["name_key"], "").strip()
        machine_id = machine.get(config["id_key"], "")

        if not name or not machine_id:
            continue

        url_path = config["url_template"].replace("{id}", machine_id)
        full_url = source["base_url"] + url_path

        results.append(build_record(
            source=source,
            today=today,
            url=full_url,
            title=name,
            author=None,
            opdb_id=machine_id,
            channel=None,
        ))

    return deduplicate_records(results)


def scrape_json_api_source(
    source: dict,
    response,
    today: str,
    warnings: list[str],
) -> list[dict]:
    config = source["json_api"]

    try:
        data = response.json()
    except Exception as e:
        add_warning(warnings, f"Failed to decode JSON API response for {source['name']}: {e}")
        return []

    collection = data.get(config["filter_key"], {})
    filter_where = config["filter_where"]

    matched = None
    for item in collection.values():
        if all(item.get(k) == v for k, v in filter_where.items()):
            matched = item
            break

    if matched is None:
        add_warning(warnings, f"Could not find matching item in API response for {source['name']}")
        return []

    videos_by_youtube_id = {}
    for video in data.get("videos", {}).values():
        youtube_id = video.get("youtube_id")
        if youtube_id:
            videos_by_youtube_id[youtube_id] = video

    machines = data.get("machines", {})
    players = data.get("players", {})

    results = []

    for youtube_id in matched.get(config["items_key"], []):
        video = videos_by_youtube_id.get(youtube_id)
        if not video:
            continue

        machine_id = str(video.get("machine_id", ""))
        machine = machines.get(machine_id, {})
        title = machine.get("name") or f"Tutorial Video {youtube_id}"
        opdb_id = machine.get("opdb_id")
        channel = video.get("channel")

        author = None
        player_ids = video.get("player_ids", [])
        if player_ids:
            player_id = str(player_ids[0])
            player = players.get(player_id, {})
            author = player.get("name")

        full_url = config["url_template"].replace("{id}", youtube_id)

        results.append(build_record(
            source=source,
            today=today,
            url=full_url,
            title=title,
            author=author,
            opdb_id=opdb_id,
            channel=channel,
        ))

    return deduplicate_records(results)


def get_source_response(source: dict, headers: dict, use_cache: bool, warnings: list[str]):
    try:
        if use_cache:
            matches = glob.glob(f"cache/{source['name']}.*")
            if matches:
                with open(matches[0], encoding="utf-8") as f:
                    raw = f.read()

                class CachedResponse:
                    def __init__(self, text):
                        self.text = text

                    def raise_for_status(self):
                        pass

                    def json(self):
                        return json.loads(self.text)

                return CachedResponse(raw)

            add_warning(warnings, f"No cache found for {source['name']}, fetching live...")

        response = requests.get(source["url"], headers=headers, timeout=30)
        response.raise_for_status()
        return response

    except Exception as e:
        add_warning(warnings, f"Failed to fetch source page for {source['name']}: {e}")
        return None


def scrape_html_source(
    source: dict,
    soup: BeautifulSoup,
    headers: dict,
    today: str,
    use_cache: bool,
    warnings: list[str],
) -> list[dict]:
    links = soup.select(source["selector"])

    stop_before = source.get("stop_before")
    skip_hrefs = source.get("skip_hrefs", [])
    href_prefix = source.get("href_prefix")
    author_pattern = source.get("author_pattern")
    fetch_title = source.get("fetch_title")

    if stop_before:
        filtered_links = []
        for a_tag in links:
            previous_text = a_tag.find_previous(string=lambda text: stop_before in text)
            if previous_text:
                break
            filtered_links.append(a_tag)
        links = filtered_links

    results = []
    total = len(links)

    for index, a_tag in enumerate(links, start=1):
        title = a_tag.get_text(strip=True)
        href = a_tag.get("href", "")

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

        author = extract_author(a_tag, author_pattern)

        if fetch_title:
            time.sleep(fetch_title.get("delay", 1))

            fetched_title, fetched_author, warning = fetch_title_from_page(
                url=full_url,
                title_selector=fetch_title["title_selector"],
                author_selector=fetch_title.get("author_selector"),
                headers=headers,
                use_cache=use_cache,
                title_filter_text=fetch_title.get("title_filter_text"),
                title_strip_suffix=fetch_title.get("title_strip_suffix"),
                title_attribute=fetch_title.get("title_attribute"),
                author_attribute=fetch_title.get("author_attribute"),
            )

            if warning:
                add_warning(warnings, warning)

            if fetched_title:
                title = fetched_title
            else:
                add_warning(warnings, f"No title extracted from page for {full_url}")

            if fetched_author:
                author = fetched_author

            print(f"  [{index}/{total}] {title or href}")

        results.append(build_record(
            source=source,
            today=today,
            url=full_url,
            title=title,
            author=author,
        ))

    return deduplicate_records(results)


def scrape_source(source: dict, use_cache: bool = False) -> tuple[list[dict], list[str]]:
    warnings = []
    headers = {**HEADERS, "User-Agent": source.get("user_agent", HEADERS["User-Agent"])}

    response = get_source_response(source, headers, use_cache, warnings)
    if response is None:
        return [], warnings

    content, warning = parse_json_content(response, source)
    if warning:
        add_warning(warnings, warning)
        return [], warnings

    soup = BeautifulSoup(content, "html.parser")
    today = date.today().isoformat()

    if source.get("json_in_script"):
        records = scrape_json_in_script_source(source, soup, today, warnings)
        return records, warnings

    if source.get("json_api"):
        records = scrape_json_api_source(source, response, today, warnings)
        return records, warnings

    records = scrape_html_source(source, soup, headers, today, use_cache, warnings)
    return records, warnings


def build_log_entry(source_name: str, total_active_links: int, stats: dict, warnings: list[str]) -> dict:
    return {
        "source_name": source_name,
        "links_added": len(stats["added_urls"]),
        "links_removed": len(stats["removed_urls"]),
        "total_active_links": total_active_links,
        "new_links": stats["added_urls"],
        "removed_links": stats["removed_urls"],
        "warnings": warnings,
    }


def print_diff_summary(stats: dict):
    if stats["added_urls"]:
        print(f"  Added: {len(stats['added_urls'])}")
    if stats["removed_urls"]:
        print(f"  Removed: {len(stats['removed_urls'])}")
    if stats["changed_urls"]:
        print(f"  Changed: {len(stats['changed_urls'])}")
    if stats["reappeared_urls"]:
        print(f"  Reappeared: {len(stats['reappeared_urls'])}")


def run(use_cache: bool = False):
    run_log = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "sources": [],
    }

    sources = load_sources()
    db_path = db.get_main_db_path()

    conn = sqlite3.connect(db_path)
    db.init_db(conn)

    for source in sources:
        print(f"Scraping {source['name']}...")
        new_records, warnings = scrape_source(source, use_cache=use_cache)
        print(f"Found {len(new_records)} links")

        if not new_records and warnings:
            skip_message = "DB sync skipped because scrape returned 0 records with warnings."
            add_warning(warnings, skip_message)

            total_active_links = db.count_active_links_for_source(conn, source["name"])
            empty_stats = {
                "added_urls": [],
                "removed_urls": [],
                "changed_urls": [],
                "reappeared_urls": [],
            }

            run_log["sources"].append(
                build_log_entry(source["name"], total_active_links, empty_stats, warnings)
            )
            continue

        today = date.today().isoformat()

        stats = db.sync_source_records(
            conn=conn,
            source=source,
            new_records=new_records,
            today=today,
        )

        total_active_links = db.count_active_links_for_source(conn, source["name"])

        run_log["sources"].append(
            build_log_entry(source["name"], total_active_links, stats, warnings)
        )

        if not stats["has_changes"]:
            print(f"No changes detected for {source['name']}, skipping...")
            continue

        print_diff_summary(stats)
        print(f"Synchronized {source['name']} in {db_path}")

    conn.close()
    write_run_log(run_log)


def write_run_log(run_log: dict):
    os.makedirs("logs", exist_ok=True)

    filename = run_log["timestamp"].replace(":", "-") + ".json"
    log_path = os.path.join("logs", filename)

    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(run_log, f, indent=2)

    print(f"Log written to {log_path}")


if __name__ == "__main__":
    import sys

    use_cache = "--cache" in sys.argv
    run(use_cache=use_cache)