import json
import requests
import os

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; research-scraper/1.0)"}

def load_sources(path="config/sources.json"):
    with open(path) as f:
        return json.load(f)

os.makedirs("cache", exist_ok=True)

for source in load_sources():
    print(f"Capturing {source['name']}...")
    headers = {**HEADERS, "User-Agent": source.get("user_agent", HEADERS["User-Agent"])}
    response = requests.get(source["url"], headers=headers)
    response.raise_for_status()
    ext = "json" if "json" in response.headers.get("content-type", "") else "html"
    path = f"cache/{source['name']}.{ext}"
    with open(path, "w", encoding="utf-8") as f:
        f.write(response.text)
    print(f"  Saved to {path}")