import argparse
import json
import sqlite3
from pathlib import Path

import requests

import db


OPDB_URL = "https://mp-data.sfo3.cdn.digitaloceanspaces.com/latest-opdb.json"
DEFAULT_LOCAL_PATH = "latest-opdb.json"


def load_opdb_from_file(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def download_opdb() -> dict:
    print(f"Downloading OPDB dataset from {OPDB_URL}...")
    response = requests.get(OPDB_URL, timeout=120)
    response.raise_for_status()
    return response.json()


def save_opdb_to_file(data: dict, path: str):
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    print(f"Saved OPDB dataset to {output_path}")


def extract_year(manufacture_date: str | None) -> int | None:
    if not manufacture_date:
        return None

    manufacture_date = manufacture_date.strip()
    if len(manufacture_date) < 4:
        return None

    year_text = manufacture_date[:4]
    if not year_text.isdigit():
        return None

    return int(year_text)


def extract_machine_records(opdb_data: dict) -> list[dict]:
    machines = opdb_data.get("machines", [])
    records = []

    for machine in machines:
        raw_machine_id = machine.get("opdbId")
        if not raw_machine_id:
            continue

        parts = raw_machine_id.split("-")

        # Only keep canonical machine rows, not groups or aliases.
        if len(parts) != 2:
            continue

        group_id = parts[0]

        manufacturer = None
        manufacturer_data = machine.get("manufacturer")
        if isinstance(manufacturer_data, dict):
            manufacturer = manufacturer_data.get("name")

        records.append({
            "machine_id": raw_machine_id,
            "name": machine.get("name"),
            "manufacturer": manufacturer,
            "year": extract_year(machine.get("manufactureDate")),
            "group_id": group_id,
        })

    return records


def print_summary(summary: dict):
    print()
    print("OPDB sync complete")
    print(f"  Inserted: {summary['inserted']}")
    print(f"  Updated: {summary['updated']}")
    print(f"  Deleted: {summary['deleted']}")
    print(f"  Links cleared: {summary['links_cleared']}")
    print(f"  Total canonical machines in feed: {summary['total_in_feed']}")

    removed_count = len(summary["removed_machine_ids"])
    print(f"  Machine IDs removed from local DB: {removed_count}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Sync canonical OPDB machine data into data/main.db"
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download the latest OPDB JSON instead of reading a local file.",
    )
    parser.add_argument(
        "--input",
        default=DEFAULT_LOCAL_PATH,
        help="Path to local OPDB JSON file when not using --download.",
    )
    parser.add_argument(
        "--save-download",
        default=None,
        help="Optional path to save the downloaded OPDB JSON.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.download:
        opdb_data = download_opdb()

        if args.save_download:
            save_opdb_to_file(opdb_data, args.save_download)
    else:
        print(f"Loading OPDB dataset from {args.input}...")
        opdb_data = load_opdb_from_file(args.input)

    records = extract_machine_records(opdb_data)
    print(f"Prepared {len(records)} canonical machine records for sync")

    conn = sqlite3.connect(db.get_main_db_path())
    db.init_db(conn)

    summary = db.sync_machine_records(conn, records)
    print_summary(summary)

    conn.close()


if __name__ == "__main__":
    main()