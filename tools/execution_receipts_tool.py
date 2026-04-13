"""Execution receipts tool — operator-facing receipt operations.

Registers as a Hermes tool for use by the agent and slash commands.
"""

import json
import logging
import time
from typing import Any, Dict

from tools.execution_receipts import (
    ExecutionReceipt,
    create_receipt,
    finalize_receipt,
    get_receipt,
    list_receipts,
    query_receipts,
    prune_receipts,
    reconcile_receipts,
    maintenance_status,
)
from tools.registry import registry, tool_error

logger = logging.getLogger(__name__)

RECEIPTS_TOOL_SCHEMA = {
    "name": "execution_receipts",
    "description": "Manage execution receipts — auditable records of delegated task execution. "
                   "Use list to see recent receipts, query to filter, prune to clean old ones, "
                   "reconcile to fix inconsistencies, and maintenance_status to check system health.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "query", "get", "prune", "reconcile", "maintenance_status"],
                "description": "Action to perform: list (recent), query (filtered), get (by ID), "
                               "prune (remove old), reconcile (fix inconsistencies), maintenance_status (health check)",
            },
            "receipt_id": {
                "type": "string",
                "description": "Receipt ID for 'get' action",
            },
            "task_id": {
                "type": "string",
                "description": "Filter by task ID (for 'list' action)",
            },
            "status": {
                "type": "string",
                "enum": ["completed", "failed", "timeout", "cancelled", ""],
                "description": "Filter by status (for 'query' action)",
            },
            "execution_path": {
                "type": "string",
                "description": "Filter by execution path (for 'query' action)",
            },
            "since_hours": {
                "type": "number",
                "description": "Query receipts from the last N hours (for 'query' action)",
            },
            "older_than_hours": {
                "type": "number",
                "description": "Prune receipts older than N hours (default: 72)",
                "default": 72,
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results (default: 20)",
                "default": 20,
            },
        },
        "required": ["action"],
    },
}


def _handle_receipts(args: Dict[str, Any], **kw: Any) -> str:
    """Handle execution_receipts tool calls."""
    action = args.get("action", "list")

    try:
        if action == "list":
            task_id = args.get("task_id", "")
            limit = args.get("limit", 20)
            results = list_receipts(limit=limit, task_id=task_id)
            return json.dumps({
                "receipts": results,
                "count": len(results),
            }, ensure_ascii=False)

        elif action == "query":
            status = args.get("status", "")
            execution_path = args.get("execution_path", "")
            since_hours = args.get("since_hours", 0)
            limit = args.get("limit", 50)
            since = time.time() - (since_hours * 3600) if since_hours > 0 else 0.0
            results = query_receipts(
                status=status,
                execution_path=execution_path,
                since=since,
                limit=limit,
            )
            return json.dumps({
                "receipts": results,
                "count": len(results),
            }, ensure_ascii=False)

        elif action == "get":
            receipt_id = args.get("receipt_id", "")
            if not receipt_id:
                return tool_error("receipt_id is required for 'get' action")
            receipt = get_receipt(receipt_id)
            if not receipt:
                return tool_error(f"Receipt not found: {receipt_id}")
            return json.dumps(receipt.to_dict(), ensure_ascii=False)

        elif action == "prune":
            older_than_hours = args.get("older_than_hours", 72)
            result = prune_receipts(older_than_hours=older_than_hours)
            return json.dumps(result, ensure_ascii=False)

        elif action == "reconcile":
            result = reconcile_receipts()
            return json.dumps(result, ensure_ascii=False)

        elif action == "maintenance_status":
            result = maintenance_status()
            return json.dumps(result, ensure_ascii=False)

        else:
            return tool_error(f"Unknown action: {action}")

    except Exception as e:
        logger.error("Execution receipts error: %s", e)
        return tool_error(str(e))


def _check_receipts_available() -> bool:
    """Check if execution receipts are available."""
    try:
        from hermes_constants import get_hermes_home
        get_hermes_home()
        return True
    except Exception:
        return False


registry.register(
    name="execution_receipts",
    toolset="execution",
    schema=RECEIPTS_TOOL_SCHEMA,
    handler=_handle_receipts,
    check_fn=_check_receipts_available,
    emoji="🧾",
    max_result_size_chars=50_000,
)
