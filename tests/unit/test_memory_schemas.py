"""Unit tests for memory schemas."""

import pytest
from datetime import datetime, timezone

from src.memory.schemas import TaskState, Checkpoint, SessionSummary, ContextSections


class TestTaskState:
    """Tests for TaskState schema."""

    def test_create_valid_task(self, sample_task_data):
        """Test creating a valid task state."""
        task = TaskState(**sample_task_data)
        
        assert task.task_id == "task-test-123"
        assert task.session_id == "session-test-456"
        assert task.goal == "Fix the bug in login function"
        assert task.status == "in_progress"
        assert len(task.plan) == 3
        assert len(task.completed_steps) == 1

    def test_task_default_values(self):
        """Test task default values."""
        task = TaskState(
            task_id="task-1",
            session_id="session-1",
            goal="Test goal",
        )
        
        assert task.status == "pending"
        assert task.plan == []
        assert task.completed_steps == []
        assert task.failed_attempts == []
        assert task.current_hypothesis is None
        assert task.next_action is None
        assert isinstance(task.created_at, datetime)
        assert task.created_at.tzinfo == timezone.utc

    def test_task_invalid_status(self):
        """Test that invalid status raises validation error."""
        with pytest.raises(Exception):  # pydantic.ValidationError
            TaskState(
                task_id="task-1",
                session_id="session-1",
                goal="Test",
                status="invalid_status",
            )


class TestCheckpoint:
    """Tests for Checkpoint schema."""

    def test_create_valid_checkpoint(self, sample_checkpoint_data):
        """Test creating a valid checkpoint."""
        checkpoint = Checkpoint(**sample_checkpoint_data)
        
        assert checkpoint.checkpoint_id == "ckpt-test-789"
        assert checkpoint.task_id == "task-test-123"
        assert checkpoint.step == 5
        assert checkpoint.last_action == "write_file"
        assert checkpoint.files_modified == ["src/auth/login.py"]

    def test_checkpoint_default_values(self):
        """Test checkpoint default values."""
        checkpoint = Checkpoint(
            checkpoint_id="ckpt-1",
            task_id="task-1",
            session_id="session-1",
            step=1,
        )
        
        assert checkpoint.plan_state == {}
        assert checkpoint.files_modified == []
        assert checkpoint.last_action is None
        assert checkpoint.last_observation is None
        assert checkpoint.next_action is None
        assert isinstance(checkpoint.created_at, datetime)


class TestSessionSummary:
    """Tests for SessionSummary schema."""

    def test_create_valid_summary(self, sample_session_summary_data):
        """Test creating a valid session summary."""
        summary = SessionSummary(**sample_session_summary_data)
        
        assert "login bug" in summary.summary
        assert len(summary.important_decisions) == 1
        assert len(summary.open_questions) == 1
        assert len(summary.files_touched) == 2

    def test_summary_default_values(self):
        """Test summary default values."""
        summary = SessionSummary(summary="Test summary")
        
        assert summary.important_decisions == []
        assert summary.open_questions == []
        assert summary.files_touched == []
        assert isinstance(summary.updated_at, datetime)


class TestContextSections:
    """Tests for ContextSections schema."""

    def test_create_valid_sections(self):
        """Test creating valid context sections."""
        sections = ContextSections(
            system_policy="You are a helpful assistant.",
            task="Fix the bug",
            recent_turns=[
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
            ],
        )
        
        assert sections.system_policy == "You are a helpful assistant."
        assert sections.task == "Fix the bug"
        assert len(sections.recent_turns) == 2
        assert sections.plan is None
        assert sections.checkpoint is None

    def test_sections_with_all_fields(self):
        """Test context sections with all optional fields."""
        sections = ContextSections(
            system_policy="Policy",
            task="Task",
            plan="Plan",
            checkpoint="Checkpoint",
            session_summary="Summary",
            recent_turns=[],
            extra={"custom": "data"},
        )
        
        assert sections.plan == "Plan"
        assert sections.checkpoint == "Checkpoint"
        assert sections.session_summary == "Summary"
        assert sections.extra == {"custom": "data"}
