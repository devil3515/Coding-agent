from datetime import datetime
from dataclasses import asdict
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from src.models import LongTermMemoryModel


class LongTermMemory:
    """Persistent, MongoDB-backed long-term memory."""
    def __init__(self, mongo_uri: str, db_name: str, collection_name: str = "long_term_memory"):
        try:
            self.client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
            self.client.admin.command('ping')
            self.db = self.client[db_name]
            self.collection = self.db[collection_name]
        except ConnectionFailure as e:
            raise ConnectionError(f"Failed to connect to MongoDB: {e}")

    def save_session_summary(self, session_id: str, summary: str):
        """Call this when a session ends to save what was accomplished."""
        ltm_model = LongTermMemoryModel(
            session_id=session_id,
            summary=summary,
            updated_at=datetime.utcnow()
        )
        self.collection.update_one(
            {"session_id": session_id},
            {"$set": asdict(ltm_model)},
            upsert=True
        )

    def get_recent_context(self, limit: int = 10) -> tuple[str, int]:
        """
        Fetches the last few session summaries to inject into the system prompt.
        Returns a tuple of (context_string, token_count).
        """
        try:
            import tiktoken
            encoding = tiktoken.get_encoding("cl100k_base")
        except:
            encoding = None

        cursor = self.collection.find(
            {},
            {"_id": 0, "session_id": 1, "summary": 1, "updated_at": 1},
        ).sort("updated_at", -1).limit(limit)

        docs = list(cursor)
        if not docs:
            return "", 0

        models = [
            LongTermMemoryModel(
                session_id=doc["session_id"],
                summary=doc["summary"],
                updated_at=doc.get("updated_at", datetime.utcnow())
            )
            for doc in docs
        ]

        context_str = "Here is what you remember from previous sessions:\n"
        for m in models:
            context_str += f"- [{m.session_id}]: {m.summary}\n"

        # Count tokens
        token_count = len(encoding.encode(context_str)) if encoding else len(context_str) // 4
        return context_str, token_count

    def check_project_in_memory(self, project_id: str) -> bool:
        doc = self.collection.find_one({"project_id": project_id})
        return doc is not None
