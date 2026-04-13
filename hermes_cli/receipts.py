"""CLI subcommands for execution receipts management."""

import json
import time
from typing import Optional


def handle_receipts_command(args: str) -> None:
    """Handle 'hermes receipts <subcommand>' CLI command.

    Subcommands:
        list [--task-id ID] [--limit N]
        get <receipt_id>
        query [--status STATUS] [--path PATH] [--since HOURS]
        prune [--older-than HOURS]
        reconcile
        status
    """
    from tools.execution_receipts import (
        get_receipt,
        list_receipts,
        query_receipts,
        prune_receipts,
        reconcile_receipts,
        maintenance_status,
    )

    parts = args.strip().split() if args else ["list"]
    subcmd = parts[0].lower() if parts else "list"
    rest = parts[1:]

    def _parse_flag(flags: list[str], name: str) -> Optional[str]:
        """Extract a --flag value from remaining args."""
        for i, f in enumerate(flags):
            if f == f"--{name}" and i + 1 < len(flags):
                return flags[i + 1]
        return None

    if subcmd == "list":
        task_id = _parse_flag(rest, "task-id") or ""
        limit_str = _parse_flag(rest, "limit") or "20"
        limit = int(limit_str)
        receipts = list_receipts(limit=limit, task_id=task_id)

        if not receipts:
            print("  No receipts found.")
            return

        print(f"  {'ID':<14} {'Status':<12} {'Path':<12} {'Duration':<10} {'Age':<20}")
        print(f"  {'─'*14} {'─'*12} {'─'*12} {'─'*10} {'─'*20}")
        for r in receipts:
            age_sec = time.time() - r.get("timestamp", 0)
            if age_sec < 60:
                age = f"{age_sec:.0f}s ago"
            elif age_sec < 3600:
                age = f"{age_sec/60:.0f}m ago"
            else:
                age = f"{age_sec/3600:.1f}h ago"

            dur = r.get("duration_seconds", 0)
            dur_str = f"{dur:.2f}s" if dur < 60 else f"{dur/60:.1f}m"

            print(f"  {r['receipt_id']:<14} {r['status']:<12} {r['execution_path']:<12} "
                  f"{dur_str:<10} {age:<20}")

        print(f"\n  {len(receipts)} receipt(s)")

    elif subcmd == "get":
        if not rest:
            print("  Error: receipt_id required. Usage: hermes receipts get <id>")
            return
        receipt = get_receipt(rest[0])
        if not receipt:
            print(f"  Receipt not found: {rest[0]}")
            return
        print(json.dumps(receipt.to_dict(), indent=2))

    elif subcmd == "query":
        status = _parse_flag(rest, "status") or ""
        path = _parse_flag(rest, "path") or ""
        since_str = _parse_flag(rest, "since") or "0"
        since_hours = float(since_str)
        since = time.time() - (since_hours * 3600) if since_hours > 0 else 0.0

        receipts = query_receipts(status=status, execution_path=path, since=since)

        if not receipts:
            print("  No receipts match the query.")
            return

        for r in receipts:
            age_sec = time.time() - r.get("timestamp", 0)
            age = f"{age_sec/3600:.1f}h ago" if age_sec > 3600 else f"{age_sec/60:.0f}m ago"
            print(f"  {r['receipt_id']}  {r['status']:<10}  {r['execution_path']:<12}  {age}")

        print(f"\n  {len(receipts)} receipt(s)")

    elif subcmd == "prune":
        older_str = _parse_flag(rest, "older-than") or "72"
        older_hours = float(older_str)
        result = prune_receipts(older_than_hours=older_hours)
        print(f"  Pruned {result['pruned']} receipt(s) older than {older_hours}h")
        print(f"  Remaining: {result['remaining']}")

    elif subcmd == "reconcile":
        result = reconcile_receipts()
        print(f"  JSON files: {result['json_files']}")
        print(f"  DB entries: {result['db_entries']}")
        print(f"  Re-indexed: {result['reindexed']}")
        print(f"  Removed from DB: {result['removed_from_db']}")
        print(f"  Consistent: {'Yes' if result['consistent'] else 'No'}")

    elif subcmd in ("status", "maintenance"):
        result = maintenance_status()
        print(f"  Total receipts: {result['total_receipts']}")
        print(f"  JSON files: {result['json_files']}")
        print(f"  DB size: {result['db_size_bytes'] / 1024:.1f} KB")
        print(f"  Directory size: {result['dir_size_bytes'] / 1024:.1f} KB")
        print(f"  Consistent: {'Yes' if result['consistent'] else 'No'}")

    else:
        print(f"  Unknown subcommand: {subcmd}")
        print("  Available: list, get, query, prune, reconcile, status")
