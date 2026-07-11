#!/usr/bin/env python3
import argparse
from datetime import datetime


def main():
    parser = argparse.ArgumentParser(
        description="Safely disable/archive an FQP module without deleting historical data."
    )
    parser.add_argument("module_id")
    parser.add_argument("--archive", action="store_true")
    parser.add_argument("--reason", default="manual maintenance")
    args = parser.parse_args()

    print(f"[FQP] Requested module change: {args.module_id}")
    print("[FQP] Step 1: verify module is not required")
    print("[FQP] Step 2: stop module scheduled jobs")
    print("[FQP] Step 3: hide registered panels")
    print("[FQP] Step 4: keep historical tables and snapshots")
    print("[FQP] Step 5: write module_change_log")
    if args.archive:
        print("[FQP] Archive mode enabled: mark module archived after backup")
    print(f"[FQP] Done as dry-run at {datetime.utcnow().isoformat()}Z")


if __name__ == "__main__":
    main()
