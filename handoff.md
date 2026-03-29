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

---

## Database Architecture (Updated)

The scraper now uses a **single shared SQLite database**:

```
data/main.db
```

### Tables

#### machines (not yet populated)

Stores canonical machine data from OPDB.

```
machine_id       TEXT PRIMARY KEY  
name          TEXT  
manufacturer  TEXT  
year          INTEGER  
group_id      TEXT  
```

#### links (actively used)

Stores all scraped links across all sources.

```
id            INTEGER PRIMARY KEY AUTOINCREMENT  
machine_id       TEXT (nullable, filled by enrichment)  
group_id      TEXT (nullable)  
url           TEXT  
source_name   TEXT  
content_type  TEXT  
title         TEXT  
author        TEXT  
channel       TEXT  
first_seen    DATE  
last_seen     DATE  
status        TEXT (active, removed)  
UNIQUE (source_name, url)
```

---

## Core Scraper Behavior (Current)

The scraper now performs **in-place synchronization per source**:

For each source:

1. Scrape current links
2. Load existing links for that `source_name`
3. Diff old vs new
4. Apply updates directly to `links` table

### State Transitions

**New link**

* Insert row
* `first_seen = today`
* `last_seen = today`
* `status = active`

**Existing link (still present)**

* Update fields (title, author, etc.)
* `last_seen = today`
* `status = active`

**Missing link (was active)**

* `status = removed`
* `last_seen` is NOT updated (represents last time seen active)

**Reappeared link**

* `status = active`
* `last_seen = today`
* `first_seen` preserved

### Important Semantics

* `first_seen` = first time ever observed
* `last_seen` = last time confirmed active
* `status` = current state

---

## Logging (Implemented)

Each scraper run generates a JSON log file in `logs/`.

### Per-source log data:

* source_name
* links_added
* links_removed
* total_active_links
* new_links
* removed_links
* warnings

Logging is driven by the same diff logic used for DB updates.

---

## Kineticist Fix (Resolved)

Kineticist scraping now correctly extracts machine names and authors.

### Machine Name

Extracted from a metadata block:

```html
<div class="flex flex-wrap gap-x-3 gap-y-1">
  <a href="/games/pinball/...">Machine Name</a>
</div>
```

Selector:

```css
div.flex.flex-wrap.gap-x-3.gap-y-1 a[href^='/games/pinball/']
```

This avoids:

* nav bar links (e.g. "Best Machines")
* body links
* malformed text

### Author

Extracted from:

```html
<meta property="article:author" content="Author Name">
```

### Result

* Clean machine names (e.g. "AC/DC")
* Correct single author

---

## Key Files

* `scraper.py` — scraping + sync + logging
* `db.py` — database schema + sync logic
* `sources.json` — source definitions
* `capture.py` — offline cache support

---

## Architecture Notes

* Scraping is config-driven
* Each source defines:

  * selectors
  * JSON parsing (optional)
  * title/author extraction (optional)
* All sources write into the same `links` table
* Diffing is scoped per `source_name`

---

## The Plan Going Forward

### Step 1: Build `sync_opdb.py` (NEXT)

The full OPDB dataset is available at:
https://mp-data.sfo3.cdn.digitaloceanspaces.com/latest-opdb.json
latest-opdb.json is a local copy of this web source

This script should:

* Download dataset
* Populate `machines` table in `main.db`

#### Important OPDB concepts:

* Each machine has a unique `machine_id`
* Machines belong to a `group_id`

  * Reskins/rethemes share a group
  * Rules are usually identical (but not always)
* Variants should map to parent machine

---

### Step 2: Enrichment (Match links → machines)

Goal:
Populate `machine_id` in `links`

Approach:

* Use fuzzy matching (`rapidfuzz`)
* Match `title` → `machines.name`
* High confidence → auto assign
* Low confidence → manual review

#### Sources with built-in IDs:

* BobsGuide → provides `machine_id`
* PinballVideos → provides `machine_id`
* PinballPrimer → URLs contain `group_id`

---

### Step 3: Build `sync_pintips.py`

Generate Pintips links:

```
https://app.matchplay.events/opdb/entries/{machine_id}/pintips
```

Insert into `links` table.

No scraping required.

---

## Known Future Enhancements

* Create manufacturer field in main.db, this data is available to scrape directly from some sources. Some machine titles include manufacture information that we can split into a separate field and use to help with the fuzzy matching later.
* Add PinballRebel as a source (instruction cards)
* Add JLP's pinball cards as source (https://cards.pinballcards.net/pinballcards)
* What to do regarding official Stern PDFs? No single source of links. Manual collection seems tiresome, and per game links likely change after code updates?

---

## Tech Stack

* Python
* SQLite
* BeautifulSoup
* requests

No framework yet — currently script-based. Web app and API planned later.
