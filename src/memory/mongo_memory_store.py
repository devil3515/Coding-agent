"""MongoDB stores for tasks and checkpoints."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pymongo import MongoClient

from .schemas import Checkpoint, TaskState

logger = logging.getLogger(__name__)


class TaskStore:
    """MongoDB store for task state persistence."""

    def __init__(self, client: MongoClient, db_name: str = "coding_agent"):
        """
        Initialize the task store.

        Args:
            client: MongoDB client instance.
            db_name: Name of the database to use.
        """
        self.client = client
        self.db = client[db_name]
        self.collection = self.db["tasks"]
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        """Create indexes if they don't exist."""
        try:
            # Unique index on task_id
            self.collection.create_index("task_id", unique=True)
            # Index on session_id
            self.collection.create_index("session_id")
            # Index on repo
            self.collection.create_index("repo")
            # Index on status
            self.collection.create_index("status")
            # Index on updated_at
            self.collection.create_index("updated_at")
            logger.debug("Task store indexes ensured")
        except Exception as e:
            logger.warning(f"Failed to create task indexes: {e}")

    def create_task(self, task: TaskState) -> bool:
        """
        Create a new task document.

        Args:
            task: TaskState object to persist.

        Returns:
            True if created successfully, False otherwise.
        """
        try:
            doc = task.model_dump(mode="json")
            self.collection.insert_one(doc)
            logger.debug(f"Created task: {task.task_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to create task: {e}")
            return False

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a task by ID.

        Args:
            task_id: The task ID to retrieve.

        Returns:
            Task document as dict, or None if not found.
        """
        try:
            doc = self.collection.find_one({"task_id": task_id})
            if doc:
                # Remove _id for cleaner return
                doc.pop("_id", None)
            return doc
        except Exception as e:
            logger.error(f"Failed to get task: {e}")
            return None

    def get_task_by_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve the most recent task for a session.

        Args:
            session_id: The session ID to search for.

        Returns:
            Most recent task document as dict, or None if not found.
        """
        try:
            doc = self.collection.find_one(
                {"session_id": session_id}, sort=[("updated_at", -1)]
            )
            if doc:
                doc.pop("_id", None)
            return doc
        except Exception as e:
            logger.error(f"Failed to get task by session: {e}")
            return None

    def update_task(self, task_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update a task document.

        Args:
            task_id: The task ID to update.
            updates: Dictionary of fields to update.

        Returns:
            True if updated successfully, False otherwise.
        """
        try:
            updates["updated_at"] = datetime.now(timezone.utc)
            result = self.collection.update_one(
                {"task_id": task_id}, {"$set": updates}
            )
            success = result.modified_count > 0 or result.matched_count > 0
            if success:
                logger.debug(f"Updated task: {task_id}")
            return success
        except Exception as e:
            logger.error(f"Failed to update task: {e}")
            return False

    def set_task_status(self, task_id: str, status: str) -> bool:
        """
        Set the status of a task.

        Args:
            task_id: The task ID to update.
            status: New status value.

        Returns:
            True if updated successfully, False otherwise.
        """
        return self.update_task(task_id, {"status": status})

    def append_completed_step(self, task_id: str, step: str) -> bool:
        """
        Append a completed step to a task.

        Args:
            task_id: The task ID to update.
            step: Description of the completed step.

        Returns:
            True if updated successfully, False otherwise.
        """
        try:
            updates = {
                "$push": {"completed_steps": step},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            }
            result = self.collection.update_one({"task_id": task_id}, updates)
            success = result.modified_count > 0
            if success:
                logger.debug(f"Appended completed step to task: {task_id}")
            return success
        except Exception as e:
            logger.error(f"Failed to append completed step: {e}")
            return False

    def append_failed_attempt(self, task_id: str, attempt: str) -> bool:
        """
        Append a failed attempt to a task.

        Args:
            task_id: The task ID to update.
            attempt: Description of the failed attempt.

        Returns:
            True if updated successfully, False otherwise.
        """
        try:
            updates = {
                "$push": {"failed_attempts": attempt},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            }
            result = self.collection.update_one({"task_id": task_id}, updates)
            success = result.modified_count > 0
            if success:
                logger.debug(f"Appended failed attempt to task: {task_id}")
            return success
        except Exception as e:
            logger.error(f"Failed to append failed attempt: {e}")
            return False

    def set_next_action(self, task_id: str, next_action: str) -> bool:
        """
        Set the next action for a task.

        Args:
            task_id: The task ID to update.
            next_action: Description of the next action.

        Returns:
            True if updated successfully, False otherwise.
        """
        return self.update_task(task_id, {"next_action": next_action})


class CheckpointStore:
    """MongoDB store for checkpoint persistence."""

    def __init__(self, client: MongoClient, db_name: str = "coding_agent"):
        """
        Initialize the checkpoint store.

        Args:
            client: MongoDB client instance.
            db_name: Name of the database to use.
        """
        self.client = client
        self.db = client[db_name]
        self.collection = self.db["checkpoints"]
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        """Create indexes if they don't exist."""
        try:
            # Unique index on checkpoint_id
            self.collection.create_index("checkpoint_id", unique=True)
            # Index on task_id
            self.collection.create_index("task_id")
            # Index on session_id
            self.collection.create_index("session_id")
            # Index on created_at
            self.collection.create_index("created_at")
            logger.debug("Checkpoint store indexes ensured")
        except Exception as e:
            logger.warning(f"Failed to create checkpoint indexes: {e}")

    def save_checkpoint(self, checkpoint: Checkpoint) -> bool:
        """
        Save a checkpoint document.

        Args:
            checkpoint: Checkpoint object to persist.

        Returns:
            True if saved successfully, False otherwise.
        """
        try:
            doc = checkpoint.model_dump(mode="json")
            self.collection.insert_one(doc)
            logger.debug(f"Saved checkpoint: {checkpoint.checkpoint_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to save checkpoint: {e}")
            return False

    def get_latest_checkpoint(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve the most recent checkpoint for a task.

        Args:
            task_id: The task ID to search for.

        Returns:
            Most recent checkpoint document as dict, or None if not found.
        """
        try:
            doc = self.collection.find_one(
                {"task_id": task_id}, sort=[("created_at", -1)]
            )
            if doc:
                doc.pop("_id", None)
            return doc
        except Exception as e:
            logger.error(f"Failed to get latest checkpoint: {e}")
            return None

    def list_checkpoints(
        self, task_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        List checkpoints for a task.

        Args:
            task_id: The task ID to search for.
            limit: Maximum number of checkpoints to return.

        Returns:
            List of checkpoint documents as dicts.
        """
        try:
            cursor = self.collection.find({"task_id": task_id}).sort(
                "created_at", -1
            ).limit(limit)
            results = []
            for doc in cursor:
                doc.pop("_id", None)
                results.append(doc)
            # Reverse to get chronological order
            results.reverse()
            return results
        except Exception as e:
            logger.error(f"Failed to list checkpoints: {e}")
            return []
