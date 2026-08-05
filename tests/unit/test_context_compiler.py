"""Unit tests for context compiler."""

import pytest

from src.memory.context_compiler import ContextCompiler
from src.memory.schemas import TaskState, Checkpoint, SessionSummary


class TestContextCompiler:
    """Tests for ContextCompiler."""

    def test_compile_with_minimal_inputs(self):
        """Test compiling context with only system prompt."""
        compiler = ContextCompiler(system_prompt="You are helpful.")
        
        messages = compiler.compile()
        
        assert len(messages) >= 1
        assert messages[0]["role"] == "system"
        assert "<system_policy>" in messages[0]["content"]
        assert "You are helpful." in messages[0]["content"]

    def test_compile_with_task(self):
        """Test compiling context with task state."""
        compiler = ContextCompiler(system_prompt="Policy")
        task = TaskState(
            task_id="task-1",
            session_id="session-1",
            goal="Fix bug",
            status="in_progress",
            completed_steps=["Step 1"],
        )
        
        messages = compiler.compile(task=task)
        
        system_content = messages[0]["content"]
        assert "<task>" in system_content
        assert "Fix bug" in system_content
        assert "Step 1" in system_content

    def test_compile_with_checkpoint(self):
        """Test compiling context with checkpoint."""
        compiler = ContextCompiler(system_prompt="Policy")
        checkpoint = Checkpoint(
            checkpoint_id="ckpt-1",
            task_id="task-1",
            session_id="session-1",
            step=5,
            last_action="write_file",
            last_observation="File written",
        )
        
        messages = compiler.compile(checkpoint=checkpoint)
        
        system_content = messages[0]["content"]
        assert "<checkpoint>" in system_content
        assert "Step: 5" in system_content
        assert "write_file" in system_content

    def test_compile_with_session_summary(self):
        """Test compiling context with session summary."""
        compiler = ContextCompiler(system_prompt="Policy")
        summary = SessionSummary(
            summary="Working on bug fix",
            important_decisions=["Use bcrypt"],
            files_touched=["src/auth.py"],
        )
        
        messages = compiler.compile(session_summary=summary)
        
        system_content = messages[0]["content"]
        assert "<session_summary>" in system_content
        assert "Working on bug fix" in system_content
        assert "Use bcrypt" in system_content

    def test_compile_with_recent_turns(self):
        """Test compiling context with recent turns."""
        compiler = ContextCompiler(system_prompt="Policy")
        turns = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        
        messages = compiler.compile(recent_turns=turns)
        
        # Should have system + 2 turns
        assert len(messages) == 3
        assert messages[1]["role"] == "user"
        assert messages[2]["role"] == "assistant"

    def test_limit_recent_turns(self):
        """Test that recent turns are limited to max."""
        compiler = ContextCompiler(system_prompt="Policy", max_recent_turns=3)
        turns = [
            {"role": "user", "content": f"Message {i}"}
            for i in range(10)
        ]
        
        messages = compiler.compile(recent_turns=turns)
        
        # Should have system + 3 turns (last 3)
        assert len(messages) == 4
        assert messages[-1]["content"] == "Message 9"

    def test_omit_empty_sections(self):
        """Test that empty sections are omitted."""
        compiler = ContextCompiler(system_prompt="Policy")
        
        messages = compiler.compile()
        
        system_content = messages[0]["content"]
        assert "<system_policy>" in system_content
        assert "<task>" not in system_content
        assert "<plan>" not in system_content
        assert "<checkpoint>" not in system_content
        assert "<session_summary>" not in system_content

    def test_section_order(self):
        """Test that sections appear in correct order."""
        compiler = ContextCompiler(system_prompt="Policy")
        task = TaskState(
            task_id="task-1",
            session_id="session-1",
            goal="Goal",
            plan=["Step 1", "Step 2"],
        )
        checkpoint = Checkpoint(
            checkpoint_id="ckpt-1",
            task_id="task-1",
            session_id="session-1",
            step=1,
        )
        
        messages = compiler.compile(task=task, checkpoint=checkpoint)
        
        system_content = messages[0]["content"]
        
        # Check order: system_policy < task < plan < checkpoint
        policy_pos = system_content.find("<system_policy>")
        task_pos = system_content.find("<task>")
        plan_pos = system_content.find("<plan>")
        checkpoint_pos = system_content.find("<checkpoint>")
        
        assert policy_pos < task_pos < plan_pos < checkpoint_pos

    def test_redaction_in_checkpoint(self):
        """Test that secrets are redacted in checkpoint observations."""
        compiler = ContextCompiler(system_prompt="Policy")
        checkpoint = Checkpoint(
            checkpoint_id="ckpt-1",
            task_id="task-1",
            session_id="session-1",
            step=1,
            last_observation="API key: sk-1234567890abcdefghijklmnop",
        )
        
        messages = compiler.compile(checkpoint=checkpoint)
        
        system_content = messages[0]["content"]
        assert "[REDACTED_API_KEY]" in system_content
        assert "sk-1234567890abcdefghijklmnop" not in system_content

    def test_truncate_long_observation(self):
        """Test that long observations are truncated."""
        compiler = ContextCompiler(
            system_prompt="Policy",
            max_checkpoint_observation_chars=20,
        )
        checkpoint = Checkpoint(
            checkpoint_id="ckpt-1",
            task_id="task-1",
            session_id="session-1",
            step=1,
            last_observation="This is a very long observation that exceeds the limit",
        )
        
        messages = compiler.compile(checkpoint=checkpoint)
        
        system_content = messages[0]["content"]
        assert "[truncated]" in system_content
        assert len(system_content) < 500  # Reasonable bound
