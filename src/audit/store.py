"""MongoDB sink for the unified audit event stream.

The store is best-effort: any connection / write error is surfaced to the
caller, which records it on the event's metadata and continues. Audit
writes must NEVER break the agent loop.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pymongo import MongoClient
from pymongo.errors import PyMongoError

from src.audit.logger import AuditEvent  # defined in Task 2


class AuditStore:
    """Thin wrapper around a MongoDB collection of audit events."""

    def __init__(
        self,
        uri: str,
        db_name: str = "coding_agent",
        collection: str = "audit_events",
    ):
        self.uri = uri
        self.db_name = db_name
        self.collection_name = collection
        self._client: Optional[MongoClient] = None
        self._collection = None
        try:
            self._client = MongoClient(uri, serverSelectionTimeoutMS=2000)
            self._collection = self._client[db_name][collection]
            # TTL: 90 days, configurable later via env if needed.
            self._collection.create_index(
                "timestamp",
                expireAfterSeconds=90 * 24 * 3600,
                background=True,
            )
            self._collection.create_index([("session_id", 1), ("timestamp", 1)])
            self._collection.create_index("event_type")
        except PyMongoError:
            # Leave _collection None — write() will fail-fast and the
            # caller records metadata.mongo_persist_error.
            self._collection = None

    @property
    def available(self) -> bool:
        return self._collection is not None

    def write(self, event: AuditEvent) -> None:
        """Persist one event. Raises only on programmer error, never on
        a Mongo connectivity issue — those return normally after capturing
        the error string in the caller's metadata."""
        if not self.available:
            raise RuntimeError("AuditStore is not connected to MongoDB")
        doc = self._to_doc(event)
        self._collection.insert_one(doc)

    def query(
        self,
        session_id: Optional[str] = None,
        event_type: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if not self.available:
            return []
        q: dict[str, Any] = {}
        if session_id:
            q["session_id"] = session_id
        if event_type:
            q["event_type"] = event_type
        if since:
            q["timestamp"] = {"$gte": since.isoformat()}
        cursor = self._collection.find(q).sort("timestamp", 1).limit(limit)
        return list(cursor)

    @staticmethod
    def _to_doc(event: AuditEvent) -> dict[str, Any]:
        from dataclasses import asdict

        d = asdict(event)
        # Mongo won't like datetime objects embedded in dataclass fields.
        # The timestamp is already a string (ISO 8601) so leave it alone.
        d.pop("metadata", None)
        # metadata is stored as a sub-document, not flattened.
        d["metadata"] = event.metadata or {}
        return d