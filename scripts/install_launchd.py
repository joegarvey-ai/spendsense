"""Generate and install launchd plist for scheduled syncs.

Usage:
    python scripts/install_launchd.py
"""

import shutil
import sys
from pathlib import Path


def main():
    project_root = Path(__file__).parent.parent
    launchd_dir = project_root / "launchd"
    agents_dir = Path.home() / "Library" / "LaunchAgents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    plist_files = list(launchd_dir.glob("*.plist"))
    if not plist_files:
        print("No plist files found in launchd/")
        sys.exit(1)

    for plist in plist_files:
        dest = agents_dir / plist.name
        print(f"Installing {plist.name} → {dest}")
        shutil.copy2(plist, dest)
        print(f"  Run: launchctl load {dest}")
        print(f"  Stop: launchctl unload {dest}")
        print()

    print("Done. Load the agents with the commands above.")
    print("To verify: launchctl list | grep com.spendsense")


if __name__ == "__main__":
    main()
