Project: Pinball Rules Scraper

I'm building a web scraper that aggregates pinball machine rulesheets, tutorials, and other reference content from multiple sources into a unified database, eventually to be served via a web app and API.

---

## Current State

The scraper is working and has 8 sources:

**Rulesheets**

* TiltForums_RuleSheets
* PAPA_RuleSheets
* PinballOrg_RuleSheets
* Zaccaria_RuleSheets
* PinballPrimer_RuleSheets
* BobsGuide_RuleSheets

**Tutorials**

* PinballVideos_Tutorials
* Kineticist_Tutorials

Each source currently writes to its own SQLite `.db` file in a `data/` directory.

### Core Behavior

* The scraper diffs each run against the previous DB
* If changes are detected:

  * The old DB is archived
  * A fresh DB is written
* If no changes:

  * The source is skipped

There is also a `capture.py` script that snapshots source pages locally for offline testing. The scraper supports a `--cache` flag to use these snapshots instead of hitting live servers.

---

## Logging (Implemented)

Each scraper run now generates a JSON log file in a `logs/` directory.

### Log contents per source:

* source_name
* links_added
* links_removed
* total_active_links
* new_links (list of URLs)
* removed_links (list of URLs)
* warnings (list of warning messages)

This acts as a lightweight observability/debug layer for scraper behavior over time.

---

## Kineticist Fix (Resolved)

Kineticist scraping previously had two issues:

1. Title extraction returned messy article text instead of machine name
2. Author extraction returned multiple contributors (including non-authors)

### Current solution:

**Machine Name**

* Extracted from a dedicated metadata section on the page:

  ```html
  <div class="flex flex-wrap gap-x-3 gap-y-1">
    <a href="/games/pinball/...">Machine Name</a>
  </div>
  ```
* Selector used:

  ```css
  div.flex.flex-wrap.gap-x-3.gap-y-1 a[href^='/games/pinball/']
  ```
* This avoids:

  * nav bar links (e.g. "Best Machines")
  * body links
  * malformed text

**Author**

* Extracted from:

  ```html
  <meta property="article:author" content="Author Name">
  ```
* Uses attribute-based extraction (`content`)

### Result:

* Clean machine names (e.g. "AC/DC")
* Single correct author (e.g. "James McFatter")

---

## Key Files

* `scraper.py` — main scraper + diff + logging
* `db.py` — SQLite helpers
* `sources.json` — source configuration
* `capture.py` — cache snapshots for offline testing

---

## Architecture Notes

* Scraping is config-driven via `sources.json`

* Each source defines:

  * selector strategy
  * optional JSON parsing
  * optional fetch_title behavior

* Title and author extraction can be overridden per source

* Diffing is done per source using:

  * URL comparison
  * title change detection
  * removed/reappeared detection

---

## The Plan Going Forward (Execute in Order)

### Step 2: Build `sync_opdb.py`

The full OPDB dataset is available at:
https://mp-data.sfo3.cdn.digitaloceanspaces.com/latest-opdb.json

This script should:

* Download the dataset
* Populate a `machines` table in a new `main.db`

#### Important OPDB concepts:

* Each machine has a unique `opdb_id`
* Machines belong to a `group_id`

  * Reskins/rethemes share a group
  * Rules are usually identical, but not always
* Below machines there are "variants" which are purely cosmetic differences — variants should be mapped up to their parent machine ID with no information loss

#### Schema (minimum):

machines
opdb_id       TEXT PRIMARY KEY
name          TEXT
manufacturer  TEXT
year          INTEGER
group_id      TEXT

---

### Step 3: Create `main.db` schema and migrate scraper

Move from per-source DBs → unified database.

#### Schema:

machines
opdb_id       TEXT PRIMARY KEY
name          TEXT
manufacturer  TEXT
year          INTEGER
group_id      TEXT

links
id            INTEGER PRIMARY KEY AUTOINCREMENT
opdb_id       TEXT (nullable, filled by enrichment)
group_id      TEXT (nullable)
url           TEXT UNIQUE
source_name   TEXT
content_type  TEXT (rulesheet, tutorial, tips)
title         TEXT
author        TEXT
channel       TEXT
first_seen    DATE
last_seen     DATE
status        TEXT (active, removed)

#### Notes:

* Wipe old per-source DBs
* Diff logic remains the same but scoped by `source_name`

---

### Step 4: Build `sync_pintips.py`

Pintips URL format:
https://app.matchplay.events/opdb/entries/{opdb_id}/pintips

This script should:

* Iterate all machines in `main.db`
* Insert Pintips links into `links` table
* No scraping required

---

### Step 5: Fuzzy Matching / Enrichment

Goal:
Populate `opdb_id` for links missing it.

Approach:

* Use `rapidfuzz` or similar
* Match link titles → machines table
* High confidence → auto assign
* Low confidence → manual review

#### Sources with built-in OPDB data:

* BobsGuide → provides `opdb_id`
* PinballVideos → provides `opdb_id`
* PinballPrimer → URLs contain `group_id` (extract via regex)

---

## Known Future Enhancements

* Add PinballRebel (instruction cards)
* Possibly ignore Stern PDFs (no reliable index)

---

## Tech Stack

* Python
* SQLite
* BeautifulSoup
* requests

No framework yet — currently script-based. Web app and API planned later.
