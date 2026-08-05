"""Pydantic schemas for Sprint 1 memory management."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class TaskState(BaseModel):
    """Represents the state of a task being executed by the agent."""

    task_id: str = Field(..., description="Unique identifier for the task")
    session_id: str = Field(..., description="Session ID this task belongs to")
    repo: Optional[str] = Field(None, description="Repository path or identifier")
    goal: str = Field(..., description="The goal or objective of the task")
    status: Literal["pending", "in_progress", "completed", "failed", "cancelled"] = Field(
        "pending", description="Current status of the task"
    )
    plan: List[str] = Field(default_factory=list, description="List of planned steps")
    completed_steps: List[str] = Field(
        default_factory=list, description="List of completed steps"
    )
    failed_attempts: List[str] = Field(
        default_factory=list, description="List of failed attempts with descriptions"
    )
    current_hypothesis: Optional[str] = Field(
        None, description="Current hypothesis about what to do next"
    )
    next_action: Optional[str] = Field(
        None, description="Description of the next action to take"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the task was created",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the task was last updated",
    )

    class Config:
        """Pydantic config for JSON serialization."""

        json_schema_extra = {
            "example": {
                "task_id": "task-123",
                "session_id": "session-456",
                "repo": "/workspace/my-project",
                "goal": "Fix the bug in the login function",
                "status": "in_progress",
                "plan": ["Identify bug", "Write fix", "Test fix"],
                "completed_steps": ["Identify bug"],
                "failed_attempts": [],
                "current_hypothesis": "The issue is with password validation",
                "next_action": "Read the login function source code",
            }
        }


class Checkpoint(BaseModel):
    """Represents a checkpoint saved during task execution."""

    checkpoint_id: str = Field(..., description="Unique identifier for the checkpoint")
    task_id: str = Field(..., description="Task ID this checkpoint belongs to")
    session_id: str = Field(..., description="Session ID this checkpoint belongs to")
    step: int = Field(..., description="Step number in the agent loop")
    plan_state: Dict[str, Any] = Field(
        default_factory=dict, description="Current state of the plan"
    )
    files_modified: List[str] = Field(
        default_factory=list, description="List of files modified up to this point"
    )
    last_action: Optional[str] = Field(
        None, description="Description of the last action taken"
    )
    last_observation: Optional[str] = Field(
        None, description="Observation from the last action (truncated and redacted)"
    )
    next_action: Optional[str] = Field(
        None, description="Description of the next action to take"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the checkpoint was created",
    )

    class Config:
        """Pydantic config for JSON serialization."""

        json_schema_extra = {
            "example": {
                "checkpoint_id": "ckpt-789",
                "task_id": "task-123",
                "session_id": "session-456",
                "step": 5,
                "plan_state": {"current_step": 2, "total_steps": 5},
                "files_modified": ["src/main.py"],
                "last_action": "write_file",
                "last_observation": "File written successfully",
                "next_action": "Run tests",
            }
        }


class SessionSummary(BaseModel):
    """Represents a summary of a session for context compression."""

    summary: str = Field(..., description="Summary of the session so far")
    important_decisions: List[str] = Field(
        default_factory=list, description="List of important decisions made"
    )
    open_questions: List[str] = Field(
        default_factory=list, description="List of open questions to resolve"
    )
    files_touched: List[str] = Field(
        default_factory=list, description="List of files touched during the session"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the summary was last updated",
    )

    class Config:
        """Pydantic config for JSON serialization."""

        json_schema_extra = {
            "example": {
                "summary": "Working on fixing login bug. Identified issue in password validation.",
                "important_decisions": ["Use bcrypt for password hashing"],
                "open_questions": ["What is the expected password format?"],
                "files_touched": ["src/auth/login.py", "tests/test_login.py"],
            }
        }


class ContextSections(BaseModel):
    """Represents the structured sections for context assembly."""

    system_policy: str = Field(..., description="System policy and instructions")
    task: Optional[str] = Field(None, description="Current task description")
    plan: Optional[str] = Field(None, description="Current plan state")
    checkpoint: Optional[str] = Field(None, description="Latest checkpoint state")
    session_summary: Optional[str] = Field(None, description="Session summary")
    recent_turns: List[Dict[str, Any]] = Field(
        default_factory=list, description="Recent conversation turns"
    )
    extra: Optional[Dict[str, Any]] = Field(
        None, description="Extra context sections for future extension"
    )

    class Config:
        """Pydantic config for JSON serialization."""

        arbitrary_types_allowed = True
