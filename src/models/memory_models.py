from dataclasses import dataclass, field
from datetime import datetime
from src.llm.base import Message

@dataclass
class ShortTermMemoryModel:
    session_id: str
    system_prompt: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    messages: list[Message] = field(default_factory=list)


@dataclass
class LongTermMemoryModel:
    session_id: str
    summary: str
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ProjectMemoryContent:
    purpose: str = ""
    architecture: str = ""
    decisions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    preferences: list[str] = field(default_factory=list)
    current_status: str = ""
    key_files: dict[str, str] = field(default_factory=dict)


@dataclass
class ProjectMemoryModel:
    project_id: str
    name: str
    path: str
    memory: ProjectMemoryContent
    recent_sessions: list[dict] = field(default_factory=list)
    updated_at: datetime = field(default_factory=datetime.utcnow)