import json
from dataclasses import asdict
from datetime import datetime
from src.memory.base import BaseMemory
from src.llm.base import Message, ToolCall
from pymongo import MongoClient
from src.models import ShortTermMemoryModel
import tiktoken


class MongoSTM(BaseMemory):
    """Persistent, MongoDB-backed short-term memory, with read-time
    compaction so large tool outputs / tool-call arguments don't get
    re-sent to the LLM at full price on every later turn."""
    COMPACT_THRESHOLD_CHARS = 2000
    PROTECT_RECENT = 6

    def __init__(
        self,
        mongo_uri: str,
        db_name: str,
        collection_name: str,
        session_id: str,
        max_messages: int = 30,
        system_prompt: str = "You are a helpful coding assistant. You have access to a shell to run commands. If the user asks you to do something that requires looking at files or running code, use the run_shell_command tool.",
        model: str = "gpt-4o",
    ):
        self.session_id = session_id
        self.max_messages = max_messages
        self.system_prompt = system_prompt

        try:
            self.client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
            self.client.admin.command('ping')
            self.db = self.client[db_name]
            self.collection = self.db[collection_name]
        except Exception as e:
            raise ConnectionError(f"Failed to connect to MongoDB: {e}")

        # Initialize session document if it does not exist using the model
        doc = self.collection.find_one({"session_id": self.session_id})
        if not doc:
            stm_model = ShortTermMemoryModel(
                session_id=self.session_id,
                system_prompt=system_prompt,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                messages=[]
            )
            self.collection.insert_one(asdict(stm_model))

        try:
            self.encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            self.encoding = tiktoken.get_encoding("cl100k_base")

    # ------------------------------------------------------------------
    # Write path — messages are added to the DB here.
    # ------------------------------------------------------------------
    def add_message(self, message: Message):
        msg_dict = asdict(message)
        self.collection.update_one(
            {"session_id": self.session_id},
            {"$push": {"messages": {"$each": [msg_dict], "$slice": -self.max_messages}},
             "$set": {"updated_at": datetime.utcnow()}},
        )

    # ------------------------------------------------------------------
    # Read path — compaction happens HERE, on the way out to the LLM.
    # ------------------------------------------------------------------
    def get_context(self) -> list[Message]:
        doc = self.collection.find_one({"session_id": self.session_id})
        if not doc:
            stm_model = ShortTermMemoryModel(
                session_id=self.session_id,
                system_prompt=self.system_prompt,
                messages=[]
            )
            return [Message(role="system", content=stm_model.system_prompt)]

        raw_messages = doc.get("messages", [])
        history = []
        for m in raw_messages:
            tool_calls = [ToolCall(**tc) for tc in m.get("tool_calls", [])] if m.get("tool_calls") else []
            history.append(Message(
                role=m["role"], content=m["content"], name=m.get("name"),
                tool_call_id=m.get("tool_call_id"), tool_calls=tool_calls
            ))

        stm_model = ShortTermMemoryModel(
            session_id=doc["session_id"],
            system_prompt=doc.get("system_prompt", self.system_prompt),
            created_at=doc.get("created_at", datetime.utcnow()),
            updated_at=doc.get("updated_at", datetime.utcnow()),
            messages=history
        )

        system_msg = Message(role="system", content=stm_model.system_prompt)
        compacted_history = self._compact_for_context(stm_model.messages)
        return [system_msg] + compacted_history


    def _compact_for_context(self, history: list[Message]) -> list[Message]:
        """Shrinks large tool results / tool-call args in everything
        OLDER than the protected recent window. Operates on the
        in-memory Message list only — never writes back to Mongo."""
        if len(history) <= self.PROTECT_RECENT:
            return history

        cutoff = len(history) - self.PROTECT_RECENT

        for i in range(cutoff):
            msg = history[i]

            # --- Compact large tool RESULT content ---
            if msg.role == "tool" and msg.content and len(msg.content) > self.COMPACT_THRESHOLD_CHARS:
                line_count = msg.content.count("\n") + 1
                msg.content = (
                    f"[Compacted tool result — {len(msg.content)} chars, "
                    f"~{line_count} lines. Already consumed in a prior "
                    f"turn; re-read the file/tool if you need it again.]"
                )

            # --- Compact large tool-call ARGUMENTS on assistant messages ---
            if msg.role == "assistant" and msg.tool_calls:
                for tc in msg.tool_calls:
                    args_str = str(tc.arguments)
                    if len(args_str) > self.COMPACT_THRESHOLD_CHARS:
                        if isinstance(tc.arguments, dict):
                            tc.arguments = {
                                k: (v if len(str(v)) < 200 else f"<{len(str(v))} chars omitted>")
                                for k, v in tc.arguments.items()
                            }
                        else:
                            # arguments is a JSON string — parse → compact → re-serialize
                            # so the result is always valid JSON (never a raw mid-string cut)
                            try:
                                args_dict = json.loads(tc.arguments)
                                tc.arguments = json.dumps({
                                    k: (v if len(str(v)) < 200 else f"<{len(str(v))} chars omitted>")
                                    for k, v in args_dict.items()
                                })
                            except (json.JSONDecodeError, AttributeError):
                                tc.arguments = json.dumps({"_note": f"<{len(args_str)} chars, unreadable>"})

        return history


    def _count_tokens(self, messages: list[Message]) -> int:
        total = 0
        for m in messages:
            total += 3
            if m.content:
                total += len(self.encoding.encode(m.content))
            if m.tool_calls:
                for tc in m.tool_calls:
                    total += len(self.encoding.encode(tc.name))
                    total += len(self.encoding.encode(str(tc.arguments)))
            if m.tool_call_id:
                total += len(self.encoding.encode(m.tool_call_id))
        return total

    def list_recent_sessions(mongo_uri: str, db_name: str, collection_name: str, limit=3):
        """Helper function for the CLI to show recent sessions."""
        try:
            client = MongoClient(mongo_uri, serverSelectionTimeoutMS=3000)
            db = client[db_name]
            cursor = db[collection_name].find(
                {},
                {"session_id": 1, "updated_at": 1, "_id": 0}
            ).sort("updated_at", -1).limit(limit)

            return list(cursor)
        except Exception:
            return []