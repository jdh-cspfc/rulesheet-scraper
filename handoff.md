Project: Pinball Rules Scraper

I'm building a web scraper that aggregates pinball machine rulesheets, tutorials, and other reference content from multiple sources into a unified database, eventually to be served via a web app and API.

---

## Current State

The scraper is working and currently has 8 sources:

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

```text
data/main.db
```

### Tables

#### machines (ACTIVE)

Stores canonical machine data from OPDB.

This table is fully populated and kept in sync with OPDB via `sync_opdb.py`.

```text
machine_id    TEXT PRIMARY KEY
name          TEXT
manufacturer  TEXT
year          INTEGER
group_id      TEXT
```

---

#### links (ACTIVE)

Stores all scraped links across all sources.

```text
id            INTEGER PRIMARY KEY AUTOINCREMENT
machine_id    TEXT (nullable, canonical OPDB ID)
group_id      TEXT (nullable)
alias_id      TEXT (nullable)
manufacturer  TEXT (nullable, scraped/source-derived)
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

### Important Distinction

* `machines.manufacturer` = canonical manufacturer from OPDB
* `links.manufacturer` = scraped/source-derived manufacturer when available

The links table is intentionally allowed to hold partial metadata before enrichment.

---

## Core Scraper Behavior

The scraper performs **in-place synchronization per source**.

For each source:

1. Scrape current links
2. Load existing links for that `source_name`
3. Diff old vs new
4. Apply updates directly to the `links` table

### State Transitions

**New link**

* Insert row
* `first_seen = today`
* `last_seen = today`
* `status = active`

**Existing link (still present)**

* Update fields (`title`, `author`, `manufacturer`, etc.)
* `last_seen = today`
* `status = active`

**Missing link (was active)**

* `status = removed`
* `last_seen` is **not** updated

**Reappeared link**

* `status = active`
* `last_seen = today`
* `first_seen` preserved

### Metadata Preservation Rule

For identity-style fields and manufacturer, if a new scrape does **not** provide a value, the scraper keeps the existing stored value rather than wiping it out.

This currently applies to:

* `machine_id`
* `group_id`
* `alias_id`
* `manufacturer`

---

## OPDB Integration

### `sync_opdb.py` (IMPLEMENTED)

This script syncs canonical machine data from OPDB into the `machines` table.

Source dataset:
`https://mp-data.sfo3.cdn.digitaloceanspaces.com/latest-opdb.json`

### OPDB Data Model

OPDB JSON contains:

* `machineGroups` (group-level records)
* `machines` (canonical machine records)
* `aliases` (variants / editions)

Only **canonical machines (2-part IDs)** are stored in the `machines` table.

### ID Structure

OPDB-style IDs:

```text
Group ID     → G5W6N
Machine ID   → G5W6N-MLe6V
Alias ID     → G5W6N-MLe6V-A9Y63
```

Scraper logic classifies source-provided IDs into:

```text
(group_id, machine_id, alias_id)
```

### Sync Behavior (IMPORTANT)

The `machines` table is a **true mirror of OPDB canonical machines**.

Each sync:

1. Upserts all current OPDB machine records
2. Detects machine IDs no longer present in OPDB
3. For removed machine IDs:
   * Clears identity fields on matching links:

     ```text
     machine_id = NULL
     group_id   = NULL
     alias_id   = NULL
     ```

   * Deletes those machine rows from `machines`

### Design Rationale

* OPDB is treated as the **source of truth**
* Stale IDs from external sources are considered **untrusted**
* Clearing all identity fields prevents:
  * partial/stale matches
  * incorrect enrichment bias
  * misleading "half-resolved" links

Re-enrichment is expected to reassign correct IDs later.

---

## Identity Handling Rules

The scraper **takes what the source gives it**.

It does **not** try to promote or guess IDs during scrape time.

That means:

* group IDs stay in `group_id`
* machine IDs stay in `machine_id`
* alias IDs stay in `alias_id`
* no scrape-time upgrading from group → machine
* no scrape-time guessing from title → OPDB ID

This keeps source truth separate from later enrichment.

---

## Manufacturer Extraction (NEW)

A `manufacturer` column has been added to the `links` table to support later enrichment and tie-breaking when multiple machines have similar names.

### Current Strategy

Manufacturer is only populated when it is:

* explicitly available from the source, or
* safely derivable from a predictable title format

No fuzzy or guessed manufacturer assignment happens during scraping.

### Currently Implemented Manufacturer Extraction

#### PinballPrimer_RuleSheets

This is the main source currently benefiting from title parsing.

Examples of supported formats:

* `24 (Stern Pinball, DMD, 2009)`
* `Gigi (Gottlieb, 1963)`
* `Black Jack (Bally, SS/EM, 1977/1978)`
* `Walking Dead, The (Pro Edition) (Stern Pinball, 2014)`

The scraper now inspects the **final parenthetical metadata block**, extracts the manufacturer from the first comma-separated field, and stores:

* cleaned title in `links.title`
* manufacturer in `links.manufacturer`

This replaced an earlier overly strict regex that only handled a narrow 3-part metadata format.

#### Smaller manufacturer-tag cases

There is also conservative title-based extraction for a smaller set of titles in:

* `TiltForums_RuleSheets`
* `PinballVideos_Tutorials`

This only applies when the trailing parentheses clearly look like a manufacturer tag.

### Manufacturer Normalization

A small alias map currently normalizes obvious short forms such as:

* `DE` → `Data East`
* `JJP` → `Jersey Jack Pinball`
* `CGC` → `Chicago Gaming Company`

Other manufacturers are kept literal unless deliberately normalized.

---

## Source-Specific ID Notes

### BobsGuide_RuleSheets

* Provides OPDB-like IDs in the source data
* Usually machine IDs
* Sometimes alias IDs
* These are classified and stored accordingly

### PinballVideos_Tutorials

* Source JSON includes machine records keyed by PinballVideos machine IDs
* Those machine records include `opdb_id`
* The scraper looks up the related machine record and uses `opdb_id`
* In practice this source is currently supplying **group IDs**
* Earlier bug: scraper incorrectly looked for `machine.get("machine_id")`; fixed to use `machine.get("opdb_id")`

### PinballPrimer_RuleSheets

* URLs encode OPDB group IDs directly
* Example:
  `https://pinballprimer.github.io/medieval_G5pe4.html`
* Scraper extracts the trailing underscore-suffixed token before `.html`
* That value is classified and currently lands in `group_id`
* Earlier regression: HTML scrape path stopped extracting this ID; this has been fixed

---

## Logging (Implemented)

Each scraper run generates a JSON log file in `logs/`.

Per-source log data includes:

* `source_name`
* `links_added`
* `links_removed`
* `total_active_links`
* `new_links`
* `removed_links`
* `warnings`

Logging uses the same diff logic as DB sync.

---

## Key Files

* `scraper.py` — scraping + title/manufacturer cleanup + sync + logging
* `db.py` — schema + link sync + machine sync
* `sync_opdb.py` — OPDB → machines sync
* `sources.json` — source definitions
* `capture.py` — offline cache support
* `latest-opdb.json` — local OPDB snapshot when working offline

---

## Architecture Notes

* Scraping is config-driven where possible
* Each source defines selectors / JSON parsing / title extraction rules as needed
* Source-specific cleanup logic is added in helper functions when a source has a predictable pattern
* All sources write into a shared `links` table
* Diffing is scoped per `source_name`
* Machine identity is layered:
  * source-provided IDs (scraper)
  * canonical machine records (OPDB)
  * future enrichment / matching

---

## Current Status Summary

✔ Scraper stable across 8 sources
✔ Diff-based syncing implemented
✔ Logging implemented
✔ OPDB sync implemented
✔ Machines table populated and maintained
✔ Identity clearing strategy implemented
✔ Source ID classification implemented (`group_id` / `machine_id` / `alias_id`)
✔ PinballVideos `opdb_id` bug fixed
✔ PinballPrimer URL `group_id` extraction fixed
✔ Manufacturer column added to `links`
✔ Manufacturer extraction implemented for PinballPrimer and a few conservative title-tag cases

---

## The Plan Going Forward

### Next Step: Enrichment

Goal:
Populate missing identity fields on `links`, primarily `machine_id`, using structured matching rather than scrape-time guesses.

Likely inputs:

* `links.title`
* `links.manufacturer`
* existing `group_id` / `alias_id` / `machine_id`
* canonical `machines` table

Likely approach:

* use fuzzy matching (`rapidfuzz`)
* prefer trusted source IDs over fuzzy matches
* use manufacturer to break ties where names are ambiguous
* high confidence → auto assign
* lower confidence → manual review path

### Trusted Source Signals

These should be prioritized over name-based fuzzy matching:

* BobsGuide → source provides machine IDs and alias IDs
* PinballVideos → source provides group IDs via `opdb_id`
* PinballPrimer → URLs provide group IDs

---

## Future Step

Generate Pintips links:

```
https://app.matchplay.events/opdb/entries/{machine_id}/pintips
```

Insert into `links` table.

No scraping required.

---

## Planned Future Enhancements

* Add PinballRebel as a source (instruction cards)
* Add JLP's pinball cards as a source (`https://cards.pinballcards.net/pinballcards`)
* Add YPSI pinball cheat sheets as a source
* Decide how to handle official Stern PDFs:
  * no single stable source of links
  * manual collection may be required
  * direct per-game PDF URLs may change after code updates
* Possibly expand manufacturer extraction from more sources if they expose it clearly in HTML or JSON

---

## Tech Stack

* Python
* SQLite
* BeautifulSoup
* requests

Currently script-based.
Web app and API planned later.
