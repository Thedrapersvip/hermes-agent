"""Tests for execution receipts system."""

import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def isolated_hermes_home(tmp_path, monkeypatch):
    """Use a temporary HERMES_HOME for receipt tests."""
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    # Also patch get_hermes_home to return our temp dir
    monkeypatch.setattr("hermes_constants.get_hermes_home", lambda: hermes_home)
    return hermes_home


class TestExecutionReceipt:
    """Test the ExecutionReceipt dataclass."""

    def test_create_default_receipt(self, isolated_hermes_home):
        from tools.execution_receipts import ExecutionReceipt
        receipt = ExecutionReceipt()
        assert receipt.receipt_id
        assert receipt.status == "completed"
        assert receipt.timestamp > 0

    def test_to_dict_roundtrip(self, isolated_hermes_home):
        from tools.execution_receipts import ExecutionReceipt
        receipt = ExecutionReceipt(
            task_id="task_123",
            status="failed",
            duration_seconds=5.5,
            files_modified=["a.py", "b.py"],
        )
        d = receipt.to_dict()
        restored = ExecutionReceipt.from_dict(d)
        assert restored.task_id == "task_123"
        assert restored.status == "failed"
        assert restored.files_modified == ["a.py", "b.py"]

    def test_save_creates_json_file(self, isolated_hermes_home):
        from tools.execution_receipts import ExecutionReceipt
        receipt = ExecutionReceipt(task_id="test_task")
        path = receipt.save()
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["task_id"] == "test_task"


class TestReceiptLedger:
    """Test the SQLite receipt ledger."""

    def test_create_and_get_receipt(self, isolated_hermes_home):
        from tools.execution_receipts import create_receipt, get_receipt
        receipt = create_receipt(task_id="task_1", execution_path="direct")
        assert receipt.receipt_id
        loaded = get_receipt(receipt.receipt_id)
        assert loaded is not None
        assert loaded.task_id == "task_1"

    def test_list_receipts(self, isolated_hermes_home):
        from tools.execution_receipts import create_receipt, list_receipts
        create_receipt(task_id="task_a")
        create_receipt(task_id="task_b")
        create_receipt(task_id="task_a")
        results = list_receipts(limit=10)
        assert len(results) == 3

    def test_list_receipts_filter_by_task(self, isolated_hermes_home):
        from tools.execution_receipts import create_receipt, list_receipts
        create_receipt(task_id="task_a")
        create_receipt(task_id="task_b")
        create_receipt(task_id="task_a")
        results = list_receipts(task_id="task_a")
        assert len(results) == 2

    def test_query_by_status(self, isolated_hermes_home):
        from tools.execution_receipts import create_receipt, finalize_receipt, query_receipts
        r1 = create_receipt(task_id="t1")
        finalize_receipt(r1, status="completed")
        r2 = create_receipt(task_id="t2")
        finalize_receipt(r2, status="failed")
        r3 = create_receipt(task_id="t3")
        finalize_receipt(r3, status="completed")

        completed = query_receipts(status="completed")
        assert len(completed) == 2
        failed = query_receipts(status="failed")
        assert len(failed) == 1

    def test_query_by_since(self, isolated_hermes_home):
        from tools.execution_receipts import create_receipt, query_receipts
        create_receipt(task_id="old_task")
        # Query from 1 hour ago — should find the receipt
        results = query_receipts(since=time.time() - 3600)
        assert len(results) == 1
        # Query from 1 second in the future — should find nothing
        results = query_receipts(since=time.time() + 1)
        assert len(results) == 0

    def test_prune_receipts(self, isolated_hermes_home):
        from tools.execution_receipts import create_receipt, list_receipts, prune_receipts
        for i in range(15):
            create_receipt(task_id=f"task_{i}")

        assert len(list_receipts(limit=20)) == 15
        result = prune_receipts(older_than_hours=0, keep_min=5)
        assert result["pruned"] == 10
        assert result["remaining"] == 5
        assert len(list_receipts(limit=20)) == 5

    def test_prune_removes_json_files(self, isolated_hermes_home):
        from tools.execution_receipts import create_receipt, prune_receipts, _get_receipts_dir
        r = create_receipt(task_id="to_prune")
        assert (_get_receipts_dir() / f"{r.receipt_id}.json").exists()
        prune_receipts(older_than_hours=0, keep_min=0)
        assert not (_get_receipts_dir() / f"{r.receipt_id}.json").exists()

    def test_reconcile(self, isolated_hermes_home):
        from tools.execution_receipts import create_receipt, reconcile_receipts
        create_receipt(task_id="t1")
        create_receipt(task_id="t2")
        result = reconcile_receipts()
        assert result["consistent"]
        assert result["json_files"] == 2
        assert result["db_entries"] == 2

    def test_reconcile_fixes_orphaned_json(self, isolated_hermes_home):
        from tools.execution_receipts import (
            _get_receipts_dir, _get_connection, reconcile_receipts,
        )
        # Create a JSON file without DB entry
        fake_receipt = _get_receipts_dir() / "fake123.json"
        fake_receipt.write_text(json.dumps({
            "receipt_id": "fake123",
            "task_id": "orphan",
            "timestamp": time.time(),
            "status": "completed",
            "duration_seconds": 1.0,
            "execution_path": "direct",
            "worker_mode": "",
            "runtime_kind": "",
            "runtime_id": "",
            "runtime_reused": False,
            "tool_calls": [],
            "files_modified": [],
            "summary": "",
            "error": "",
            "metadata": {},
        }))
        result = reconcile_receipts()
        assert result["reindexed"] == 1

    def test_maintenance_status(self, isolated_hermes_home):
        from tools.execution_receipts import create_receipt, maintenance_status
        create_receipt(task_id="t1")
        status = maintenance_status()
        assert status["total_receipts"] == 1
        assert status["json_files"] == 1
        assert status["consistent"]


class TestReceiptsToolSurface:
    """Test the execution_receipts tool."""

    def test_tool_list(self, isolated_hermes_home):
        from tools.execution_receipts import create_receipt
        from tools.execution_receipts_tool import _handle_receipts
        create_receipt(task_id="test_task")
        result = json.loads(_handle_receipts({"action": "list"}))
        assert result["count"] == 1
        assert result["receipts"][0]["task_id"] == "test_task"

    def test_tool_get(self, isolated_hermes_home):
        from tools.execution_receipts import create_receipt
        from tools.execution_receipts_tool import _handle_receipts
        r = create_receipt(task_id="get_test")
        result = json.loads(_handle_receipts({"action": "get", "receipt_id": r.receipt_id}))
        assert result["task_id"] == "get_test"

    def test_tool_get_not_found(self, isolated_hermes_home):
        from tools.execution_receipts_tool import _handle_receipts
        result = json.loads(_handle_receipts({"action": "get", "receipt_id": "nonexistent"}))
        assert "error" in result

    def test_tool_query(self, isolated_hermes_home):
        from tools.execution_receipts import create_receipt, finalize_receipt
        from tools.execution_receipts_tool import _handle_receipts
        r = create_receipt(task_id="q1")
        finalize_receipt(r, status="failed")
        create_receipt(task_id="q2")
        result = json.loads(_handle_receipts({"action": "query", "status": "failed"}))
        assert result["count"] == 1

    def test_tool_prune(self, isolated_hermes_home):
        from tools.execution_receipts import create_receipt
        from tools.execution_receipts_tool import _handle_receipts
        for i in range(5):
            create_receipt(task_id=f"p{i}")
        result = json.loads(_handle_receipts({"action": "prune", "older_than_hours": 0}))
        assert result["pruned"] >= 0

    def test_tool_reconcile(self, isolated_hermes_home):
        from tools.execution_receipts import create_receipt
        from tools.execution_receipts_tool import _handle_receipts
        create_receipt(task_id="r1")
        result = json.loads(_handle_receipts({"action": "reconcile"}))
        assert result["consistent"]

    def test_tool_maintenance_status(self, isolated_hermes_home):
        from tools.execution_receipts_tool import _handle_receipts
        result = json.loads(_handle_receipts({"action": "maintenance_status"}))
        assert "total_receipts" in result


class TestDelegateReceiptIntegration:
    """Test that delegation automatically creates receipts."""

    def test_run_single_child_creates_receipt(self, isolated_hermes_home):
        """Running a child task should automatically create a receipt."""
        from unittest.mock import MagicMock
        from tools.execution_receipts import list_receipts, _get_receipts_dir

        # Create a mock child agent that returns a result
        mock_child = MagicMock()
        mock_child.session_id = "test_session_123"
        mock_child.tool_progress_callback = None
        mock_child.run_conversation.return_value = {
            "final_response": "Task completed successfully",
            "completed": True,
            "interrupted": False,
            "api_calls": 3,
            "messages": [],
        }
        mock_child._credential_pool = None
        mock_child._delegate_saved_tool_names = []
        mock_child.get_activity_summary.return_value = {}

        # Run the child
        from tools.delegate_tool import _run_single_child
        result = _run_single_child(
            task_index=0,
            goal="Test goal",
            child=mock_child,
            parent_agent=None,
        )

        assert result["status"] == "completed"

        # Verify receipt was created
        receipts = list_receipts(limit=10)
        assert len(receipts) >= 1
        r = receipts[0]
        assert r["status"] == "completed"
        assert r["execution_path"] == "delegation"

    def test_run_single_child_error_creates_failed_receipt(self, isolated_hermes_home):
        """A child that throws should create a failed receipt."""
        from unittest.mock import MagicMock
        from tools.execution_receipts import list_receipts

        mock_child = MagicMock()
        mock_child.session_id = "error_session"
        mock_child.run_conversation.side_effect = RuntimeError("something broke")
        mock_child._credential_pool = None
        mock_child._delegate_saved_tool_names = []

        from tools.delegate_tool import _run_single_child
        result = _run_single_child(
            task_index=0,
            goal="This will fail",
            child=mock_child,
            parent_agent=None,
        )

        assert result["status"] == "error"

        receipts = list_receipts(limit=10)
        assert len(receipts) >= 1
        assert receipts[0]["status"] == "failed"
        assert "something broke" in receipts[0].get("error", "")
