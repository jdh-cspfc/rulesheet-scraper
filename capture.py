import json
import os
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; research-scraper/1.0)"}


def load_sources(path="config/sources.json"):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def slugify_url(url: str) -> str:
    """Convert a URL to a safe filename — must match scraper.py."""
    url = re.sub(r"https?://[^/]+", "", url)
    url = re.sub(r"[^a-zA-Z0-9_-]", "_", url)
    return url.strip("_")[:200]


def ensure_cache_dirs():
    os.makedirs("cache", exist_ok=True)
    os.makedirs("cache/pages", exist_ok=True)


def read_manual_source_file(source_name: str) -> tuple[str | None, str | None]:
    manual_html = f"cache/{source_name}.html"
    manual_json = f"cache/{source_name}.json"

    if os.path.exists(manual_html):
        with open(manual_html, encoding="utf-8") as f:
            return f.read(), manual_html

    if os.path.exists(manual_json):
        with open(manual_json, encoding="utf-8") as f:
            return f.read(), manual_json

    return None, None


def capture_source_file(source: dict, headers: dict) -> str | None:
    try:
        response = requests.get(source["url"], headers=headers, timeout=30)
        response.raise_for_status()

        extension = "json" if "json" in response.headers.get("content-type", "") else "html"
        path = f"cache/{source['name']}.{extension}"

        with open(path, "w", encoding="utf-8") as f:
            f.write(response.text)

        print(f"  Saved to {path}")
        return response.text

    except Exception as e:
        print(f"  WARNING: failed to capture source {source['name']}: {e}")
        return None


def build_full_url(source: dict, href: str) -> str:
    if source.get("href_prefix"):
        return source["base_url"] + href

    return urljoin(source["url"], href)


def capture_article_pages(source: dict, raw: str, headers: dict):
    fetch_title = source.get("fetch_title")
    if not fetch_title:
        return

    print(f"  Capturing article pages for {source['name']}...")

    soup = BeautifulSoup(raw, "html.parser")
    links = soup.select(source["selector"])
    total = len(links)

    print(f"  Found {total} article links")

    for index, a_tag in enumerate(links, start=1):
        href = a_tag.get("href", "")
        if not href:
            continue

        skip_hrefs = source.get("skip_hrefs", [])
        if href in skip_hrefs:
            continue

        if source.get("href_prefix") and not href.startswith(source["href_prefix"]):
            continue

        full_url = build_full_url(source, href)
        slug = slugify_url(full_url)
        page_path = f"cache/pages/{slug}.html"

        if os.path.exists(page_path):
            print(f"  [{index}/{total}] already cached, skipping")
            continue

        time.sleep(fetch_title.get("delay", 1))

        try:
            response = requests.get(full_url, headers=headers, timeout=10)
            response.raise_for_status()

            with open(page_path, "w", encoding="utf-8") as f:
                f.write(response.text)

            print(f"  [{index}/{total}] {full_url}")

        except Exception as e:
            print(f"  [{index}/{total}] WARNING: failed to capture {full_url}: {e}")


def main():
    ensure_cache_dirs()

    for source in load_sources():
        print(f"Capturing {source['name']}...")
        headers = {**HEADERS, "User-Agent": source.get("user_agent", HEADERS["User-Agent"])}

        raw, manual_path = read_manual_source_file(source["name"])

        if manual_path:
            print(f"  Using manually saved file: {manual_path}")
        else:
            raw = capture_source_file(source, headers)
            if raw is None:
                continue

        capture_article_pages(source, raw, headers)


if __name__ == "__main__":
    main()