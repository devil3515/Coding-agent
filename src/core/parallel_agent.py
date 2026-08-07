"""
Parallel Agent Dispatch System for Coding-Agent

This module enables parallel execution of multiple agent tasks.
Tasks are dispatched simultaneously when they are independent.
"""

from src.config.prompts import load_prompt
import asyncio
import json
from typing import Optional, Dict, List, Any, Callable
from dataclasses import dataclass, field
from rich.console import Console
from src.llm.openai_provider import OpenAIProvider
from src.tools.registry import ToolRegistry
from src.memory.base import BaseMemory
from src.memory.long_term import LongTermMemory
from src.core.agent import Agent
from src.llm.base import Message


@dataclass
class DispatchedTask:
    """A task dispatched to a sub-agent."""
    task_id: str
    agent: Agent
    task_description: str
    result: Optional[str] = None
    status: str = "pending"  # pending, running, completed, failed
    error: Optional[str] = None


class ParallelAgentManager:
    """
    Manages the dispatch and execution of multiple agents in parallel.
    """

    def __init__(
        self,
        llm: OpenAIProvider,
        base_registry: ToolRegistry,
        base_memory: BaseMemory,
        console: Console,
        ltm: Optional[LongTermMemory] = None,
        llm_config: Optional[dict] = None,
        working_directory: Optional[str] = None,
        base_session_id: str = "parallel_session"
    ):
        self.llm = llm
        self.base_registry = base_registry
        self.base_memory = base_memory
        self.console = console
        self.ltm = ltm
        self.llm_config = llm_config or {}
        self.working_directory = working_directory
        self.base_session_id = base_session_id

        self.dispatched_tasks: Dict[str, DispatchedTask] = {}
        self.task_results: Dict[str, str] = {}

    def _create_agent_for_task(
        self,
        task_id: str,
        task_description: str,
        task_context: str,
        registry_override: Optional[ToolRegistry] = None
    ) -> Agent:
        """Create a new agent instance for a specific task with isolated context."""
        from src.memory.mongo_stm import MongoSTM
        from src.config.prompts import load_prompt
        from src.memory.mongo_stm import MODEL_CONTEXT_WINDOWS
        from src.config.settings import load_settings

        config = load_settings()
        db_conf = config['database']

        model_name = self.llm_config.get('model', 'gpt-4o')
        model_context_window = config.get('memory', {}).get('model_context_window',
            MODEL_CONTEXT_WINDOWS.get(model_name, 128000))

        memory_config = config.get('memory', {}).get('short_term', {})
        memory_max_tokens = config.get('memory', {}).get('short_term', {}).get('max_tokens', 32000)
        memory_max_tokens = min(memory_max_tokens, int(model_context_window * 0.75))

        # Create isolated memory for this task
        isolated_session_id = f"{self.base_session_id}_task_{task_id}"

        isolated_memory = MongoSTM(
            mongo_uri=db_conf['mongo_uri'],
            db_name=db_conf['db_name'],
            collection_name=db_conf.get('stm_collection', db_conf.get('collection_name', 'short_term_memory')),
            session_id=isolated_session_id,
            system_prompt=self._build_task_prompt(task_description, task_context),
            max_messages=memory_config.get('max_messages', 20),
            max_tokens=memory_max_tokens,
            model=model_name,
            context_window=model_context_window
        )

        agent = Agent(
            llm=self.llm,
            registry=registry_override or self.base_registry,
            memory=isolated_memory,
            console=self.console,
            ltm=self.ltm,
            llm_config=self.llm_config,
            working_directory=self.working_directory,
            session_id=isolated_session_id
        )

        return agent

    def _build_task_prompt(self, task_description: str, task_context: str) -> str:
        """Build a focused prompt for a specific task."""
        base_prompt = load_prompt("default", "You are a helpful assistant.")

        task_prompt = f"""{base_prompt}

## TASK: {task_description}

{task_context}

## Instructions for this Task:
1. Focus ONLY on the task described above
2. Use the tools available to complete the task
3. Return a summary of what you did and the results
4. Do not attempt other tasks - stay focused on your assigned work

## Return Format:
Provide your response in this format:
{{{{"status": "DONE | BLOCKED | NEEDS_INFO", "summary": "brief summary", "results": "what you accomplished"}}}}
"""
        return task_prompt

    def dispatch_tasks(
        self,
        tasks: List[Dict[str, Any]],
        max_concurrent: int = 3,
        parallel: bool = True
    ) -> Dict[str, str]:
        """
        Dispatch multiple tasks to sub-agents.

        Args:
            tasks: List of task dicts with 'task_id', 'description', 'context'
            max_concurrent: Maximum number of concurrent agents
            parallel: If True, run agents in parallel; if False, run sequentially

        Returns:
            Dictionary mapping task_id to result
        """
        results = {}

        if parallel:
            # Run in parallel with concurrency limit
            asyncio.run(self._dispatch_parallel(tasks, max_concurrent, results))
        else:
            # Run sequentially
            for task in tasks:
                result = asyncio.run(self._dispatch_single(task))
                results[task['task_id']] = result

        return results

    async def _dispatch_parallel(
        self,
        tasks: List[Dict[str, Any]],
        max_concurrent: int,
        results: Dict[str, str]
    ) -> None:
        """Dispatch tasks in parallel with concurrency limit."""
        semaphore = asyncio.Semaphore(max_concurrent)

        async def limited_dispatch(task):
            async with semaphore:
                return await self._dispatch_single(task)

        coroutines = [limited_dispatch(task) for task in tasks]
        task_results = await asyncio.gather(*coroutines)

        for i, task_id in enumerate([t['task_id'] for t in tasks]):
            results[task_id] = task_results[i]

    async def _dispatch_single(self, task: Dict[str, Any]) -> str:
        """Dispatch a single task to a sub-agent."""
        task_id = task.get('task_id', 'unknown')
        description = task.get('description', '')
        context = task.get('context', '')

        self.console.print(f"[bold cyan]Dispatching Agent for Task {task_id}...[/bold cyan]")

        try:
            agent = self._create_agent_for_task(task_id, description, context)

            # Create a focused prompt for this task
            user_input = f"""Complete this task:
{description}

Context:
{context}

Return your results in JSON format with status, summary, and results fields."""

            result = await asyncio.to_thread(
                agent.chat,
                user_input,
                max_iterations=self.llm_config.get('max_iterations', 200)
            )

            return result or "Task completed without explicit result"

        except Exception as e:
            error_msg = f"Error in task {task_id}: {str(e)}"
            self.console.print(f"[bold red]{error_msg}[/bold red]")
            return json.dumps({"status": "FAILED", "error": error_msg})

    def dispatch_tasks_sync(
        self,
        tasks: List[Dict[str, Any]],
        max_concurrent: int = 3,
        parallel: bool = True
    ) -> Dict[str, str]:
        """
        Sync wrapper for dispatch_tasks.
        Use this in synchronous contexts like CLI.
        """
        return asyncio.run(
            self._dispatch_with_progress(tasks, max_concurrent, parallel)
        )

    async def _dispatch_with_progress(
        self,
        tasks: List[Dict[str, Any]],
        max_concurrent: int,
        parallel: bool
    ) -> Dict[str, str]:
        """Dispatch tasks with progress display."""
        results = {}

        if not parallel or len(tasks) == 1:
            # Sequential execution with progress
            for i, task in enumerate(tasks):
                task_id = task['task_id']
                self.console.print(f"\n[bold yellow]Progress: {i+1}/{len(tasks)} - Task {task_id}[/bold yellow]")
                results[task_id] = await self._dispatch_single(task)
        else:
            # Parallel execution
            semaphore = asyncio.Semaphore(max_concurrent)

            async def limited_dispatch(task):
                async with semaphore:
                    return await self._dispatch_single(task)

            coroutines = [limited_dispatch(task) for task in tasks]
            task_results = await asyncio.gather(*coroutines)

            for i, task_id in enumerate([t['task_id'] for t in tasks]):
                results[task_id] = task_results[i]

        return results


def dispatch_agents(
    working_directory: str,
    tasks: str,
    max_concurrent: int = 3,
    parallel: bool = True
) -> str:
    """
    Tool function to dispatch multiple agents for parallel task execution.

    Args:
        working_directory: Project working directory
        tasks: JSON string of tasks [{"task_id": "1", "description": "...", "context": "..."}]
        max_concurrent: Maximum concurrent agents (default: 3)
        parallel: Run in parallel if True, sequential if False

    Returns:
        JSON string of results mapping task_id to result
    """
    try:
        task_list = json.loads(tasks)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON for tasks: {str(e)}"})

    # For now, return placeholder - actual implementation needs more setup
    results = {}
    for task in task_list:
        task_id = task.get('task_id', 'unknown')
        results[task_id] = f"Task {task_id} would be dispatched: {task.get('description', '')}"

    return json.dumps(results, indent=2)


# Tool registration dictionary
PARALLEL_AGENT_TOOLS = {
    "dispatch_agents": {
        "description": "Dispatch multiple agents to work on independent tasks in parallel. Use when you have 2+ tasks that can be done simultaneously without shared state. Tasks should be independent and not depend on each other's results.",
        "parameters": {
            "type": "object",
            "properties": {
                "working_directory": {"type": "string", "description": "Project working directory"},
                "tasks": {"type": "string", "description": "JSON array of tasks: [{\"task_id\": \"1\", \"description\": \"What to do\", \"context\": \"Additional details\"}]"},
                "max_concurrent": {"type": "integer", "description": "Maximum agents to run at once (default: 3)", "default": 3},
                "parallel": {"type": "boolean", "description": "Run in parallel if True, sequential if False", "default": True}
            },
            "required": ["working_directory", "tasks"]
        },
        "function": dispatch_agents
    }
}
