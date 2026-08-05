"""Sprint 1 memory management integration for the agent."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pymongo import MongoClient

from ..config.settings import get_memory_sprint1_config, load_settings
from ..memory.context_compiler import ContextCompiler
from ..memory.mongo_memory_store import CheckpointStore, TaskStore
from ..memory.redaction import redact_value
from ..memory.schemas import Checkpoint, SessionSummary, TaskState

logger = logging.getLogger(__name__)


class Sprint1MemoryManager:
    """
    Manages Sprint 1 memory features for the agent.

    This class provides:
    - Task state tracking and persistence
    - Checkpointing after each agent step
    - Context compilation with structured sections
    - Secret redaction before persistence

    It is designed to be opt-in via feature flag and falls back gracefully
    if disabled or if errors occur.
    """

    def __init__(self, mongo_client: Optional[MongoClient] = None):
        """
        Initialize the Sprint 1 memory manager.

        Args:
            mongo_client: MongoDB client instance. If None, will try to create from config.
        """
        self.config = load_settings()
        self.sprint1_config = get_memory_sprint1_config(self.config)
        self.enabled = self.sprint1_config.get("enabled", False)

        self._mongo_client = mongo_client
        self._task_store: Optional[TaskStore] = None
        self._checkpoint_store: Optional[CheckpointStore] = None
        self._context_compiler: Optional[ContextCompiler] = None

        # Current task state
        self._current_task_id: Optional[str] = None
        self._current_session_id: Optional[str] = None
        self._step_counter: int = 0

        if self.enabled:
            self._initialize_stores()

    def _initialize_stores(self) -> None:
        """Initialize MongoDB stores if enabled."""
        if not self.enabled:
            return

        try:
            if self._mongo_client is None:
                # Try to create from config
                db_config = self.config.get("database", {})
                mongo_uri = db_config.get("mongo_uri", "")
                db_name = db_config.get("db_name", "coding_agent")

                if mongo_uri:
                    self._mongo_client = MongoClient(mongo_uri)
                else:
                    logger.warning("No MongoDB URI configured; Sprint 1 features disabled")
                    self.enabled = False
                    return

            db_name = self.config.get("database", {}).get("db_name", "coding_agent")
            self._task_store = TaskStore(self._mongo_client, db_name)
            self._checkpoint_store = CheckpointStore(self._mongo_client, db_name)

            # Get system prompt for context compiler
            # Note: In a real implementation, this would come from prompts module
            system_prompt = "You are a helpful coding assistant."
            self._context_compiler = ContextCompiler(
                system_prompt=system_prompt,
                max_recent_turns=self.sprint1_config.get("max_recent_turns_in_context", 12),
                max_checkpoint_observation_chars=self.sprint1_config.get(
                    "max_checkpoint_observation_chars", 2000
                ),
            )

            logger.info("Sprint 1 memory manager initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Sprint 1 stores: {e}")
            self.enabled = False

    def ensure_task_exists(
        self, session_id: str, goal: str, repo: Optional[str] = None
    ) -> Optional[str]:
        """
        Ensure a task exists for the given session.

        Args:
            session_id: The session ID.
            goal: The task goal/objective.
            repo: Optional repository path.

        Returns:
            Task ID if successful, None otherwise.
        """
        if not self.enabled or not self._task_store:
            return None

        try:
            # Check if task already exists for this session
            existing_task = self._task_store.get_task_by_session(session_id)
            if existing_task:
                self._current_task_id = existing_task["task_id"]
                self._current_session_id = session_id
                logger.debug(f"Using existing task: {self._current_task_id}")
                return self._current_task_id

            # Create new task
            task_id = f"task-{uuid.uuid4().hex[:12]}"
            task_state = TaskState(
                task_id=task_id,
                session_id=session_id,
                repo=repo,
                goal=goal[:500],  # Truncate goal if too long
                status="in_progress",
                plan=[],
                completed_steps=[],
                failed_attempts=[],
            )

            if self._task_store.create_task(task_state):
                self._current_task_id = task_id
                self._current_session_id = session_id
                self._step_counter = 0
                logger.info(f"Created new task: {task_id}")
                return task_id
            else:
                logger.error("Failed to create task")
                return None

        except Exception as e:
            logger.error(f"Error ensuring task exists: {e}")
            return None

    def save_checkpoint(
        self,
        last_action: Optional[str] = None,
        last_observation: Optional[str] = None,
        next_action: Optional[str] = None,
        files_modified: Optional[List[str]] = None,
        plan_state: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Save a checkpoint after an agent step.

        Args:
            last_action: Description of the last action taken.
            last_observation: Observation from the last action.
            next_action: Description of the next action.
            files_modified: List of files modified.
            plan_state: Current plan state dictionary.

        Returns:
            True if saved successfully, False otherwise.
        """
        if not self.enabled or not self._checkpoint_store or not self._current_task_id:
            return False

        try:
            self._step_counter += 1

            # Redact sensitive data from observation
            redacted_observation = None
            if last_observation:
                redacted_observation = redact_value(last_observation)
                # Truncate if needed
                max_chars = self.sprint1_config.get("max_checkpoint_observation_chars", 2000)
                if len(redacted_observation) > max_chars:
                    redacted_observation = redacted_observation[:max_chars] + "... [truncated]"

            checkpoint = Checkpoint(
                checkpoint_id=f"ckpt-{uuid.uuid4().hex[:12]}",
                task_id=self._current_task_id,
                session_id=self._current_session_id,
                step=self._step_counter,
                plan_state=plan_state or {},
                files_modified=files_modified or [],
                last_action=last_action,
                last_observation=redacted_observation,
                next_action=next_action,
            )

            success = self._checkpoint_store.save_checkpoint(checkpoint)
            if success:
                logger.debug(f"Saved checkpoint {checkpoint.checkpoint_id} for step {self._step_counter}")
            return success

        except Exception as e:
            logger.error(f"Error saving checkpoint: {e}")
            return False

    def update_task_status(self, status: str) -> bool:
        """
        Update the status of the current task.

        Args:
            status: New status value (pending, in_progress, completed, failed, cancelled).

        Returns:
            True if updated successfully, False otherwise.
        """
        if not self.enabled or not self._task_store or not self._current_task_id:
            return False

        try:
            return self._task_store.set_task_status(self._current_task_id, status)
        except Exception as e:
            logger.error(f"Error updating task status: {e}")
            return False

    def append_completed_step(self, step_description: str) -> bool:
        """
        Append a completed step to the current task.

        Args:
            step_description: Description of the completed step.

        Returns:
            True if appended successfully, False otherwise.
        """
        if not self.enabled or not self._task_store or not self._current_task_id:
            return False

        try:
            return self._task_store.append_completed_step(self._current_task_id, step_description)
        except Exception as e:
            logger.error(f"Error appending completed step: {e}")
            return False

    def compile_context(
        self,
        recent_turns: List[Dict[str, Any]],
        task: Optional[TaskState] = None,
        checkpoint: Optional[Checkpoint] = None,
        session_summary: Optional[SessionSummary] = None,
        system_prompt_override: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Compile context using structured sections.

        Args:
            recent_turns: Recent conversation turns.
            task: Current task state (optional).
            checkpoint: Latest checkpoint (optional).
            session_summary: Session summary (optional).
            system_prompt_override: Override default system prompt (optional).

        Returns:
            List of message dicts for LLM API.
        """
        if not self.enabled or not self._context_compiler:
            return None

        try:
            # Use override if provided, otherwise use default
            if system_prompt_override:
                compiler = ContextCompiler(
                    system_prompt=system_prompt_override,
                    max_recent_turns=self.sprint1_config.get("max_recent_turns_in_context", 12),
                    max_checkpoint_observation_chars=self.sprint1_config.get(
                        "max_checkpoint_observation_chars", 2000
                    ),
                )
            else:
                compiler = self._context_compiler

            return compiler.compile(
                task=task,
                checkpoint=checkpoint,
                session_summary=session_summary,
                recent_turns=recent_turns,
            )

        except Exception as e:
            logger.error(f"Error compiling context: {e}")
            return None

    def get_latest_checkpoint(self) -> Optional[Dict[str, Any]]:
        """
        Get the latest checkpoint for the current task.

        Returns:
            Checkpoint document as dict, or None if not found.
        """
        if not self.enabled or not self._checkpoint_store or not self._current_task_id:
            return None

        try:
            return self._checkpoint_store.get_latest_checkpoint(self._current_task_id)
        except Exception as e:
            logger.error(f"Error getting latest checkpoint: {e}")
            return None

    def reset(self) -> None:
        """Reset the current task state."""
        self._current_task_id = None
        self._current_session_id = None
        self._step_counter = 0
        logger.debug("Sprint 1 memory manager reset")

    def close(self) -> None:
        """Close MongoDB connection if owned."""
        if self._mongo_client and self._mongo_client is not None:
            try:
                self._mongo_client.close()
                logger.debug("MongoDB connection closed")
            except Exception as e:
                logger.warning(f"Error closing MongoDB connection: {e}")
