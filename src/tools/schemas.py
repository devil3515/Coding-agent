"""Pydantic validation schemas for all tool arguments."""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List


class ReadFileArgs(BaseModel):
    file_path: str = Field(..., description="Path to the file to read")
    start_line: int = Field(0, ge=0, description="Starting line index (0-indexed)")
    end_line: int = Field(-1, ge=-1, description="Ending line index (-1 for all)")

    @field_validator("file_path")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("file_path cannot be empty")
        return v


class WriteFileArgs(BaseModel):
    file_path: str = Field(..., description="Path to the file to write")
    content: str = Field(..., description="Full exact content to write")

    @field_validator("file_path")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("file_path cannot be empty")
        return v


class ApplyDiffArgs(BaseModel):
    file_path: str = Field(..., description="Path to the file to edit")
    old_string: str = Field(..., description="Exact block of text to find and replace")
    new_string: str = Field(..., description="New text to replace the old text with")


class RunShellCommandArgs(BaseModel):
    command: str = Field(..., description="The bash command to run", min_length=1)


class RunGitArgs(BaseModel):
    args: str = Field(..., description="Git arguments as a single string", min_length=1)


class SearchCodebaseArgs(BaseModel):
    query: str = Field(..., description="Function, class, or variable name to search", min_length=1)
    project_dir: Optional[str] = Field(".", description="Directory to search in")


class GetFileTreeArgs(BaseModel):
    directory: Optional[str] = Field(".", description="Directory to list")
    max_depth: int = Field(4, ge=1, le=10, description="Max folder depth")


class GetCodebaseOverviewArgs(BaseModel):
    directory: Optional[str] = Field(".", description="Directory to index")


class CreateProjectPlanArgs(BaseModel):
    steps: List[dict] = Field(..., description="Ordered list of steps")


class UpdatePlanStatusArgs(BaseModel):
    step_number: int = Field(..., ge=1, description="1-based step number")
    status: str = Field(..., description="New status: completed, in_progress, or failed")

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str) -> str:
        if v not in ("completed", "in_progress", "failed"):
            raise ValueError("status must be one of: completed, in_progress, failed")
        return v


class UpdatePlanTextArgs(BaseModel):
    step_number: int = Field(..., ge=1, description="1-based step number to update")
    new_text: str = Field(..., description="Replacement text for the step")


class AskUserQuestionArgs(BaseModel):
    question: str = Field(..., description="The question to ask")
    question_type: str = Field("text", description="Free text or multiple choice")
    options: Optional[List[str]] = Field(None, description="Choices for MCQ questions")
