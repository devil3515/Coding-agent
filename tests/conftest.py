"""Pytest configuration and fixtures."""

import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_mongo_client():
    """Create a mock MongoDB client for testing."""
    client = MagicMock()
    db = MagicMock()
    client.__getitem__ = MagicMock(return_value=db)
    client.get_database = MagicMock(return_value=db)
    return client


@pytest.fixture
def sample_task_data():
    """Sample task data for testing."""
    return {
        "task_id": "task-test-123",
        "session_id": "session-test-456",
        "repo": "/workspace/test-repo",
        "goal": "Fix the bug in login function",
        "status": "in_progress",
        "plan": ["Identify bug", "Write fix", "Test fix"],
        "completed_steps": ["Identify bug"],
        "failed_attempts": [],
        "current_hypothesis": "Password validation issue",
        "next_action": "Read login.py",
    }


@pytest.fixture
def sample_checkpoint_data():
    """Sample checkpoint data for testing."""
    return {
        "checkpoint_id": "ckpt-test-789",
        "task_id": "task-test-123",
        "session_id": "session-test-456",
        "step": 5,
        "plan_state": {"current_step": 2, "total_steps": 5},
        "files_modified": ["src/auth/login.py"],
        "last_action": "write_file",
        "last_observation": "File written successfully",
        "next_action": "Run tests",
    }


@pytest.fixture
def sample_session_summary_data():
    """Sample session summary data for testing."""
    return {
        "summary": "Working on fixing login bug. Identified issue in password validation.",
        "important_decisions": ["Use bcrypt for password hashing"],
        "open_questions": ["What is the expected password format?"],
        "files_touched": ["src/auth/login.py", "tests/test_login.py"],
    }
