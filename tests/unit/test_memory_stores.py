"""Unit tests for task and checkpoint stores using mongomock."""

import pytest
from datetime import datetime, timezone

try:
    import mongomock
    HAS_MONGOMOCK = True
except ImportError:
    HAS_MONGOMOCK = False

from src.memory.mongo_memory_store import CheckpointStore, TaskStore
from src.memory.schemas import Checkpoint, TaskState


@pytest.mark.skipif(not HAS_MONGOMOCK, reason="mongomock not installed")
class TestTaskStore:
    """Tests for TaskStore."""

    @pytest.fixture
    def task_store(self):
        """Create a task store with mocked MongoDB."""
        client = mongomock.MongoClient()
        return TaskStore(client, "test_db")

    def test_create_task(self, task_store, sample_task_data):
        """Test creating a task."""
        task = TaskState(**sample_task_data)
        
        result = task_store.create_task(task)
        
        assert result is True
        
        # Retrieve and verify
        retrieved = task_store.get_task("task-test-123")
        assert retrieved is not None
        assert retrieved["goal"] == "Fix the bug in login function"

    def test_get_task_by_session(self, task_store):
        """Test getting task by session ID."""
        task = TaskState(
            task_id="task-1",
            session_id="session-1",
            goal="Goal 1",
        )
        task_store.create_task(task)
        
        retrieved = task_store.get_task_by_session("session-1")
        
        assert retrieved is not None
        assert retrieved["task_id"] == "task-1"

    def test_update_task(self, task_store):
        """Test updating a task."""
        task = TaskState(
            task_id="task-1",
            session_id="session-1",
            goal="Original goal",
            status="pending",
        )
        task_store.create_task(task)
        
        result = task_store.update_task("task-1", {"status": "in_progress", "next_action": "Do something"})
        
        assert result is True
        
        retrieved = task_store.get_task("task-1")
        assert retrieved["status"] == "in_progress"
        assert retrieved["next_action"] == "Do something"

    def test_set_task_status(self, task_store):
        """Test setting task status."""
        task = TaskState(
            task_id="task-1",
            session_id="session-1",
            goal="Goal",
        )
        task_store.create_task(task)
        
        result = task_store.set_task_status("task-1", "completed")
        
        assert result is True
        assert task_store.get_task("task-1")["status"] == "completed"

    def test_append_completed_step(self, task_store):
        """Test appending a completed step."""
        task = TaskState(
            task_id="task-1",
            session_id="session-1",
            goal="Goal",
            completed_steps=["Step 1"],
        )
        task_store.create_task(task)
        
        result = task_store.append_completed_step("task-1", "Step 2")
        
        assert result is True
        
        retrieved = task_store.get_task("task-1")
        assert len(retrieved["completed_steps"]) == 2
        assert "Step 2" in retrieved["completed_steps"]

    def test_append_failed_attempt(self, task_store):
        """Test appending a failed attempt."""
        task = TaskState(
            task_id="task-1",
            session_id="session-1",
            goal="Goal",
        )
        task_store.create_task(task)
        
        result = task_store.append_failed_attempt("task-1", "Failed to connect")
        
        assert result is True
        
        retrieved = task_store.get_task("task-1")
        assert "Failed to connect" in retrieved["failed_attempts"]

    def test_get_nonexistent_task(self, task_store):
        """Test getting a task that doesn't exist."""
        result = task_store.get_task("nonexistent")
        assert result is None


@pytest.mark.skipif(not HAS_MONGOMOCK, reason="mongomock not installed")
class TestCheckpointStore:
    """Tests for CheckpointStore."""

    @pytest.fixture
    def checkpoint_store(self):
        """Create a checkpoint store with mocked MongoDB."""
        client = mongomock.MongoClient()
        return CheckpointStore(client, "test_db")

    def test_save_checkpoint(self, checkpoint_store, sample_checkpoint_data):
        """Test saving a checkpoint."""
        checkpoint = Checkpoint(**sample_checkpoint_data)
        
        result = checkpoint_store.save_checkpoint(checkpoint)
        
        assert result is True
        
        # Retrieve and verify
        retrieved = checkpoint_store.get_latest_checkpoint("task-test-123")
        assert retrieved is not None
        assert retrieved["step"] == 5

    def test_get_latest_checkpoint(self, checkpoint_store):
        """Test getting the latest checkpoint."""
        # Save multiple checkpoints
        for step in range(1, 6):
            checkpoint = Checkpoint(
                checkpoint_id=f"ckpt-{step}",
                task_id="task-1",
                session_id="session-1",
                step=step,
                last_action=f"action-{step}",
            )
            checkpoint_store.save_checkpoint(checkpoint)
        
        latest = checkpoint_store.get_latest_checkpoint("task-1")
        
        assert latest is not None
        assert latest["step"] == 5
        assert latest["last_action"] == "action-5"

    def test_list_checkpoints(self, checkpoint_store):
        """Test listing checkpoints."""
        # Save multiple checkpoints
        for step in range(1, 11):
            checkpoint = Checkpoint(
                checkpoint_id=f"ckpt-{step}",
                task_id="task-1",
                session_id="session-1",
                step=step,
            )
            checkpoint_store.save_checkpoint(checkpoint)
        
        checkpoints = checkpoint_store.list_checkpoints("task-1", limit=5)
        
        assert len(checkpoints) == 5
        # Should be in chronological order
        assert checkpoints[0]["step"] == 6
        assert checkpoints[-1]["step"] == 10

    def test_get_nonexistent_checkpoint(self, checkpoint_store):
        """Test getting a checkpoint that doesn't exist."""
        result = checkpoint_store.get_latest_checkpoint("nonexistent")
        assert result is None
