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

## Database Architecture (Current)

The project uses a **single shared SQLite database**:

```
data/main.db
```

### Tables

#### machines (ACTIVE)

Stores canonical machine data from OPDB.

This table is now **fully populated and kept in sync with OPDB** via `sync_opdb.py`.

```
machine_id    TEXT PRIMARY KEY  
name          TEXT  
manufacturer  TEXT  
year          INTEGER  
group_id      TEXT  
```

---

#### links (ACTIVE)

Stores all scraped links across all sources.

```
id            INTEGER PRIMARY KEY AUTOINCREMENT  
machine_id    TEXT (nullable, canonical OPDB ID)  
group_id      TEXT (nullable)  
alias_id      TEXT (nullable)  
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

## Core Scraper Behavior

The scraper performs **in-place synchronization per source**:

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
* `last_seen` is NOT updated

**Reappeared link**

* `status = active`
* `last_seen = today`
* `first_seen` preserved

---

## OPDB Integration (NEW)

### `sync_opdb.py` (IMPLEMENTED)

This script syncs canonical machine data from OPDB into the `machines` table.

Source dataset:
https://mp-data.sfo3.cdn.digitaloceanspaces.com/latest-opdb.json

---

### OPDB Data Model

OPDB JSON contains:

* `machineGroups` (group-level records)
* `machines` (canonical machine records)
* `aliases` (variants / editions)

Only **canonical machines (2-part IDs)** are stored in the `machines` table.

---

### ID Structure

OPDB-style IDs:

```
Group ID     → G5W6N
Machine ID   → G5W6N-MLe6V
Alias ID     → G5W6N-MLe6V-A9Y63
```

Scraper logic extracts:

```
(group_id, machine_id, alias_id)
```

---

### Sync Behavior (IMPORTANT)

`machines` table is a **true mirror of OPDB canonical machines**.

Each sync:

1. Upserts all current OPDB machine records
2. Detects machine IDs no longer present in OPDB
3. For removed machine IDs:

   * Clears identity fields on matching links:

     ```
     machine_id = NULL
     group_id   = NULL
     alias_id   = NULL
     ```
   * Deletes those machine rows from `machines`

---

### Design Rationale

* OPDB is treated as the **source of truth**
* Stale IDs from external sources are considered **untrusted**
* Clearing all identity fields prevents:

  * partial/stale matches
  * incorrect enrichment bias
  * misleading "half-resolved" links

Re-enrichment is expected to reassign correct IDs later.

---

## Logging (Implemented)

Each scraper run generates a JSON log file in `logs/`.

Per-source log data:

* source_name
* links_added
* links_removed
* total_active_links
* new_links
* removed_links
* warnings

Logging uses the same diff logic as DB sync.

---

## Key Files

* `scraper.py` — scraping + sync + logging
* `db.py` — schema + link sync + machine sync
* `sync_opdb.py` — OPDB → machines sync
* `sources.json` — source definitions
* `capture.py` — offline cache support

---

## Architecture Notes

* Scraping is config-driven

* Each source defines:

  * selectors
  * JSON parsing (optional)
  * title/author extraction (optional)

* All sources write into a shared `links` table

* Diffing is scoped per `source_name`

* Machine identity is layered:

  * Source-provided IDs (scraper)
  * Canonical IDs (OPDB + enrichment)

---

## Current Status Summary

✔ Scraper stable across multiple sources
✔ Diff-based syncing implemented
✔ Logging implemented
✔ OPDB sync implemented
✔ Machines table populated and maintained
✔ Identity clearing strategy implemented

---

## The Plan Going Forward

### Step 2: Enrichment (NEXT)

Goal:
Populate `machine_id` in `links`

Approach:

* Use fuzzy matching (`rapidfuzz`)
* Match `title` → `machines.name`
* High confidence → auto assign
* Low confidence → manual review

---

### Known Sources with IDs

* BobsGuide → provides `machine_id`
* PinballVideos → provides `group_id`
* PinballPrimer → URLs contain `group_id`

These should be prioritized and trusted over fuzzy matches.

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
* Add YPSI pinball cheat sheets as source
* What to do regarding official Stern PDFs? No single source of links. Manual collection seems tiresome, and per game links likely change after code updates?

---

## Tech Stack

* Python
* SQLite
* BeautifulSoup
* requests

Currently script-based.
Web app and API planned later.
