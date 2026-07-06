import json
import os
from datetime import datetime
from dataclasses import asdict
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from src.models import ProjectMemoryModel, ProjectMemoryContent


class ProjectMemoryManager:
    def __init__(self, mongo_uri: str, db_name: str, collection_name: str = "project_memory"):
        try:
            self.client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
            self.client.admin.command('ping')
            self.db = self.client[db_name]
            self.collection = self.db[collection_name]
        except ConnectionFailure as e:
            raise ConnectionError(f"Failed to connect to MongoDB: {e}")

    def get_project_memory(self, project_id: str) -> ProjectMemoryModel | None:
        doc = self.collection.find_one({"project_id": project_id})
        if not doc:
            return None

        # Deserialize ProjectMemoryContent
        raw_mem = doc.get("memory", {})
        memory_content = ProjectMemoryContent(
            purpose=raw_mem.get("purpose", ""),
            architecture=raw_mem.get("architecture", ""),
            decisions=raw_mem.get("decisions", []),
            errors=raw_mem.get("errors", []),
            preferences=raw_mem.get("preferences", []),
            current_status=raw_mem.get("current_status", ""),
            key_files=raw_mem.get("key_files", {})
        )

        return ProjectMemoryModel(
            project_id=doc["project_id"],
            name=doc["name"],
            path=doc["path"],
            memory=memory_content,
            recent_sessions=doc.get("recent_sessions", []),
            updated_at=doc.get("updated_at", datetime.utcnow())
        )

    def update_project_memory(self, model: ProjectMemoryModel):
        model.updated_at = datetime.utcnow()
        self.collection.update_one(
            {"project_id": model.project_id},
            {"$set": asdict(model)},
            upsert=True
        )

    def export_to_file(self, model: ProjectMemoryModel, file_path: str):
        data = asdict(model)
        if isinstance(data.get("updated_at"), datetime):
            data["updated_at"] = data["updated_at"].isoformat()
        else:
            data["updated_at"] = datetime.utcnow().isoformat()

        with open(file_path, "w") as f:
            json.dump(data, f, indent=2)

    def generate_and_update_project_memory(
        self,
        project_mem: ProjectMemoryModel,
        conversation_context: list,
        llm,
        session_id: str,
        session_summary: str,
        working_directory: str
    ) -> ProjectMemoryModel:
        """
        Uses the LLM to analyze the conversation history, updates ProjectMemoryContent fields,
        saves the model to MongoDB, and exports it to a local file .agent-memory.json.
        """
        from src.llm.base import Message

        # Convert current project memory to JSON for context
        existing_mem_json = json.dumps(asdict(project_mem.memory), indent=2)

        update_prompt = (
            f"You are a system coordinator. Analyze the session history above and update the project's memory.\n"
            f"Here is the existing project memory:\n"
            f"```json\n{existing_mem_json}\n```\n\n"
            f"Provide an updated JSON representing the project memory. Keep fields that did not change. Update/add details for fields that changed or were discovered during the session (e.g., decisions, preferences, key_files, purpose, architecture).\n"
            f"You must return ONLY a raw JSON object with the following keys, containing no markdown formatting or extra text:\n"
            f"{{\n"
            f"  \"purpose\": \"Brief description of project purpose\",\n"
            f"  \"architecture\": \"High-level tech stack/architecture\",\n"
            f"  \"decisions\": [\"List of key decisions made/updated\"],\n"
            f"  \"errors\": [\"List of main errors encountered and how they were resolved\"],\n"
            f"  \"preferences\": [\"Coding style or implementation preferences\"],\n"
            f"  \"current_status\": \"Current state or next steps\",\n"
            f"  \"key_files\": {{\n"
            f"    \"file_path\": \"Description of what the file does\"\n"
            f"  }}\n"
            f"}}\n"
        )

        # Clone context to avoid mutating the agent's main memory
        context_for_project_memory = list(conversation_context)
        context_for_project_memory.append(Message(role="user", content=update_prompt))

        pm_response = llm.complete(
            context_for_project_memory,
            tools=None,
            max_tokens=2000
        )

        # Clean and parse JSON using robust brace-matching
        clean_content = pm_response.content.strip()
        start_idx = clean_content.find('{')
        end_idx = clean_content.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            clean_content = clean_content[start_idx:end_idx + 1]

        parsed_pm = json.loads(clean_content)

        # Update project_mem model fields
        project_mem.memory = ProjectMemoryContent(
            purpose=parsed_pm.get("purpose", project_mem.memory.purpose),
            architecture=parsed_pm.get("architecture", project_mem.memory.architecture),
            decisions=parsed_pm.get("decisions", project_mem.memory.decisions),
            errors=parsed_pm.get("errors", project_mem.memory.errors),
            preferences=parsed_pm.get("preferences", project_mem.memory.preferences),
            current_status=parsed_pm.get("current_status", project_mem.memory.current_status),
            key_files=parsed_pm.get("key_files", project_mem.memory.key_files)
        )

        # Append current session to recent_sessions
        session_info = {
            "session_id": session_id,
            "summary": session_summary,
            "date": datetime.utcnow().isoformat()
        }
        project_mem.recent_sessions = [session_info] + project_mem.recent_sessions[:4]

        # Save to MongoDB
        self.update_project_memory(project_mem)

        # Export to local file
        local_mem_file = os.path.join(working_directory, ".agent-memory.json")
        self.export_to_file(project_mem, local_mem_file)

        return project_mem
