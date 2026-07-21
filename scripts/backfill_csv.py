"""Import historical CSV exports into the database.

This is a convenience wrapper around the CLI backfill command.
Drop CSV files into data/csv_imports/ and run this script.

Usage:
    python scripts/backfill_csv.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.loader import settings
from src.cli import cli


def main():
    csv_dir = settings.CSV_IMPORT_DIR
    if not csv_dir.exists():
        print(f"CSV import directory not found: {csv_dir}")
        print("Create it and drop your CSV exports there.")
        return

    csv_files = list(csv_dir.glob("*.csv"))
    if not csv_files:
        print(f"No CSV files found in {csv_dir}")
        return

    print(f"Found {len(csv_files)} CSV file(s) in {csv_dir}:")
    for f in csv_files:
        print(f"  - {f.name}")

    print()
    for f in csv_files:
        account = input(f"Account name for '{f.name}' (or 'skip'): ").strip()
        if account.lower() == "skip":
            continue
        # Invoke the CLI backfill command
        sys.argv = ["cli", "backfill", "--file", str(f), "--account", account]
        try:
            cli(standalone_mode=False)
        except SystemExit:
            pass


if __name__ == "__main__":
    main()
