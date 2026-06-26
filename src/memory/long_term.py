from datetime import datetime
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure


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
        self.collection.update_one(
            {"session_id": session_id},
            {"$set": {"summary": summary, "updated_at": datetime.utcnow()}},
            upsert=True
        )

    def get_recent_context(self, limit: int = 10) -> str:
        """
        Fetches the last few session summaries to inject into the system prompt.
        Returns a formatted string.
        """
        cursor = self.collection.find(
            {},
            {"_id": 0, "session_id": 1, "summary": 1, "updated_at": 1},
        ).sort("updated_at", -1).limit(limit)

        docs = list(cursor)
        if not docs:
            return ""

        context_str = "Here is what you remember from previous sessions:\n"
        for doc in docs:
            context_str += f"- [{doc['session_id']}]: {doc['summary']}\n"
        return context_str