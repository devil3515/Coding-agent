"""Async CLI entry point for the coding agent."""
import typer
import uuid
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich.text import Text
from rich.box import ROUNDED
import os
import json
import asyncio
import hashlib
from datetime import datetime
from dataclasses import asdict
from src.config.settings import load_settings
from src.llm.openai_provider import OpenAIProvider
from src.tools.registry import ToolRegistry
from src.tools.shell import run_shell_command_async
from src.tools.git_tools import run_git_async
from src.core.agent import Agent
from src.memory.mongo_stm import MongoSTM, MODEL_CONTEXT_WINDOWS
from src.memory.long_term import LongTermMemory
from src.memory.project_memory import ProjectMemoryManager
from src.models import ShortTermMemoryModel, LongTermMemoryModel, ProjectMemoryContent, ProjectMemoryModel
from src.llm.base import Message
from src.tools.codebase_graph import search_codebase, get_codebase_overview
from src.tools.file_tools import read_file, write_file, apply_diff, get_file_tree
from src.tools.planning import create_project_plan, update_project_plan, ask_user_question, update_plan_text
from prompts.registry import get_default_prompt
from src.mcp.bridge import MCPBridge
from src.audit.logger import AuditLogger
from src.tools import schemas
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.formatted_text import HTML

app = typer.Typer()
console = Console()


def create_agent_session(
    config: dict,
    llm: OpenAIProvider,
    registry: ToolRegistry,
    session_id: str,
    ltm: LongTermMemory = None,
    llm_config: dict = None,
    working_directory: str = None,
) -> Agent:
    """Create a new agent session with the given configuration."""
    db_conf = config["database"]
    memory_config = config.get("memory", {}).get("short_term", {})
    model_name = llm_config.get("model", "gpt-4o") if llm_config else "gpt-4o"
    model_context_window = config.get("memory", {}).get(
        "model_context_window", MODEL_CONTEXT_WINDOWS.get(model_name, 128000)
    )
    memory_max_tokens = config.get("memory", {}).get("short_term", {}).get("max_tokens", 32000)
    memory_max_tokens = min(memory_max_tokens, int(model_context_window * 0.75))

    memory = MongoSTM(
        mongo_uri=db_conf["mongo_uri"],
        db_name=db_conf["db_name"],
        collection_name=db_conf.get(
            "stm_collection", db_conf.get("collection_name", "short_term_memory")
        ),
        session_id=session_id,
        system_prompt=get_default_prompt(working_dir=working_directory),
        max_messages=memory_config.get("max_messages", 20),
        model=model_name,
        context_window=model_context_window,
    )
    return Agent(
        llm=llm,
        registry=registry,
        memory=memory,
        console=console,
        ltm=ltm,
        llm_config=llm_config,
        working_directory=working_directory,
        session_id=session_id,
    )


async def async_main():
    config = load_settings()
    llm = OpenAIProvider(config["llm"])
    db_conf = config["database"]
    working_directory = os.getcwd()
    abs_path = os.path.abspath(working_directory)
    audit = AuditLogger()
    registry = ToolRegistry(
        audit_logger=audit,
        working_directory=working_directory,
    )

    project_id = hashlib.sha256(abs_path.encode()).hexdigest()[:16]

    # -- SHELL COMMAND TOOL (ASYNC) -------------------------------------------
    registry.register(
        name="run_shell_command",
        description="Executes a bash shell command on the local machine and returns the output. Use this to list files, run scripts, or check code.",
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to run.",
                }
            },
            "required": ["command"],
        },
        function=lambda command: run_shell_command_async(command, working_directory=working_directory),
        pydantic_schema=schemas.RunShellCommandArgs,
    )

    # -- CODEBASE SEARCH TOOL -------------------------------------------------
    registry.register(
        name="search_codebase",
        description="Queries the architecture of the local codebase. Use this BEFORE writing code to find where functions/classes are defined, what calls what, and how the project is structured.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The function, class, or variable name to search for (e.g., 'Agent', 'complete', 'MongoSTM').",
                }
            },
            "required": ["query"],
        },
        function=lambda query, project_dir=None: search_codebase(
            query, project_dir if (project_dir and project_dir != ".") else working_directory
        ),
        pydantic_schema=schemas.SearchCodebaseArgs,
    )

    # -- FILE TOOLS -----------------------------------------------------------
    registry.register(
        name="read_file",
        description="Reads a file's contents. ALWAYS use this to examine code before editing it. Use start_line and end_line (0-indexed) if you only need a specific chunk.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "The path to the file to read."},
                "start_line": {"type": "integer", "description": "Starting line index (default 0)."},
                "end_line": {"type": "integer", "description": "Ending line index (default -1 for all)."},
            },
            "required": ["file_path"],
        },
        function=read_file,
        pydantic_schema=schemas.ReadFileArgs,
    )

    registry.register(
        name="write_file",
        description="OVERWRITES a file entirely with new content. Use this to create new files or completely replace existing ones. Creates directories automatically.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "The path to the file to write."},
                "content": {"type": "string", "description": "The full exact content to write to the file."},
            },
            "required": ["file_path", "content"],
        },
        function=write_file,
        pydantic_schema=schemas.WriteFileArgs,
    )

    registry.register(
        name="apply_diff",
        description="Surgically edits a file by replacing an exact block of text. PREFER THIS over write_file for making small changes, fixing bugs, or updating specific functions. Do NOT use this to create new files.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "The path to the file to edit."},
                "old_string": {"type": "string", "description": "The exact block of text to find and replace. MUST match exactly, including whitespace and indentation."},
                "new_string": {"type": "string", "description": "The new text to replace the old text with."},
            },
            "required": ["file_path", "old_string", "new_string"],
        },
        function=apply_diff,
        pydantic_schema=schemas.ApplyDiffArgs,
    )

    # -- GIT TOOL (ASYNC) -----------------------------------------------------
    registry.register(
        name="run_git",
        description="Executes a git command. Use this to check status, commit changes, or view history. Pass the arguments as a single string.",
        parameters={
            "type": "object",
            "properties": {
                "args": {"type": "string", "description": "Git arguments, e.g., 'status', 'add .', 'commit -m \"fixed bug\"'"}
            },
            "required": ["args"],
        },
        function=lambda args: run_git_async(args, working_directory=working_directory),
        pydantic_schema=schemas.RunGitArgs,
    )

    # -- PROJECT PLAN TOOLS ---------------------------------------------------
    registry.register(
        name="create_project_plan",
        description=(
            "MANDATORY for any task touching more than 2 files. "
            "Call get_codebase_overview FIRST so you can populate the 'files' field on every step."
        ),
        parameters={
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step": {"type": "string", "description": "What to do in this step."},
                            "files": {"type": "array", "items": {"type": "string"}, "description": "Files to read or write in this step."},
                        },
                        "required": ["step"],
                    },
                    "description": "Ordered list of steps, each with a description and the files it will touch.",
                }
            },
            "required": ["steps"],
        },
        function=create_project_plan,
        pydantic_schema=schemas.CreateProjectPlanArgs,
    )

    registry.register(
        name="update_plan_status",
        description="Mark a plan step as in_progress, completed, or failed. Call this when you start AND finish every step.",
        parameters={
            "type": "object",
            "properties": {
                "step_number": {"type": "integer", "description": "1-based step number."},
                "status": {"type": "string", "enum": ["completed", "in_progress", "failed"], "description": "New status."},
            },
            "required": ["step_number", "status"],
        },
        function=update_project_plan,
        pydantic_schema=schemas.UpdatePlanStatusArgs,
    )

    registry.register(
        name="update_plan_text",
        description="Rename or rewrite a step's description mid-task (e.g. if scope changed).",
        parameters={
            "type": "object",
            "properties": {
                "step_number": {"type": "integer", "description": "1-based step number to update."},
                "new_text": {"type": "string", "description": "Replacement text for the step title."},
            },
            "required": ["step_number", "new_text"],
        },
        function=update_plan_text,
        pydantic_schema=schemas.UpdatePlanTextArgs,
    )

    registry.register(
        name="ask_user_question",
        description="Pause and ask the user a clarifying question before continuing. Use question_type='mcq' for multiple choice.",
        parameters={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to ask."},
                "question_type": {"type": "string", "enum": ["text", "mcq"], "description": "Free text or multiple choice."},
                "options": {"type": "array", "items": {"type": "string"}, "description": "Choices for MCQ questions."},
            },
            "required": ["question"],
        },
        function=ask_user_question,
        pydantic_schema=schemas.AskUserQuestionArgs,
    )

    # -- CODEBASE OVERVIEW TOOLS ----------------------------------------------
    registry.register(
        name="get_codebase_overview",
        description=(
            "Returns every file in the project with its functions and classes listed. "
            "Call this BEFORE create_project_plan so you know exactly which files to reference in each step."
        ),
        parameters={
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "Directory to index. Defaults to the current working directory."}
            },
        },
        function=lambda directory=None: get_codebase_overview(
            directory if (directory and directory != ".") else working_directory
        ),
        pydantic_schema=schemas.GetCodebaseOverviewArgs,
    )

    registry.register(
        name="get_file_tree",
        description=(
            "Returns a directory tree of all files (including configs, markdown, templates). "
            "Complements get_codebase_overview for non-code files."
        ),
        parameters={
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "Directory to list. Defaults to the current working directory."},
                "max_depth": {"type": "integer", "description": "Max folder depth (default 4)."},
            },
        },
        function=lambda directory=None, max_depth=4: get_file_tree(
            directory if (directory and directory != ".") else working_directory, max_depth
        ),
        pydantic_schema=schemas.GetFileTreeArgs,
    )

    # -- MCP TOOLS ------------------------------------------------------------
    mcp_bridges = []
    if "mcp_servers" in config:
        for server_name, server_conf in config["mcp_servers"].items():
            console.print(f"[bold cyan]Connecting to MCP Server: {server_name}...[/bold cyan]")
            try:
                mcp_bridge = MCPBridge(
                    url=server_conf["url"],
                    headers=server_conf.get("headers", {}),
                )
                mcp_bridge.sync_connect()
                mcp_bridges.append(mcp_bridge)

                for tool in mcp_bridge.mcp_tools:
                    def make_mcp_executor(t_name, bridge):
                        async def executor(**kwargs):
                            return bridge.call_tool(t_name, kwargs)
                        return executor

                    registry.register(
                        name=tool["name"],
                        description=tool["description"],
                        parameters=tool["inputSchema"],
                        function=make_mcp_executor(tool["name"], mcp_bridge),
                    )
                console.print(f"[green]✅ Injected {len(mcp_bridge.mcp_tools)} tools from {server_name}.[/green]")
            except Exception as e:
                console.print(f"[red]Failed to connect to {server_name}: {e}[/red]")

    ltm = LongTermMemory(
        mongo_uri=db_conf["mongo_uri"],
        db_name=db_conf["db_name"],
        collection_name=db_conf.get("ltm_collection", "long_term_memory"),
    )

    project_mem_mgr = ProjectMemoryManager(
        mongo_uri=db_conf["mongo_uri"],
        db_name=db_conf["db_name"],
        collection_name=db_conf.get("project_memory_collection", "project_memory"),
    )

    project_name = os.path.basename(abs_path)
    project_mem = project_mem_mgr.get_project_memory(project_id)
    if not project_mem:
        project_mem = ProjectMemoryModel(
            project_id=project_id,
            name=project_name,
            path=abs_path,
            memory=ProjectMemoryContent(),
            recent_sessions=[],
            updated_at=datetime.utcnow(),
        )

    current_session_id = f"session_{uuid.uuid4().hex[:6]}"
    registry.session_id = current_session_id
    agent = create_agent_session(
        config, llm, registry, current_session_id, ltm, config["llm"], working_directory=working_directory
    )

    # Startup diagnostic
    diag_msg = (
        f"[bold cyan]Session ID:[/bold cyan] {current_session_id}\n"
        f"[bold cyan]LLM Model:[/bold cyan] {config['llm'].get('model', 'Unknown')}\n"
        f"[bold cyan]MongoDB Status:[/bold cyan] Connected successfully\n"
        f"[bold cyan]STM Collection:[/bold cyan] {db_conf.get('stm_collection', db_conf.get('collection_name', 'short_term_memory'))}\n"
        f"[bold cyan]LTM Collection:[/bold cyan] {db_conf.get('ltm_collection', 'long_term_memory')}\n"
        f"[bold cyan]Project Memory Collection:[/bold cyan] {db_conf.get('project_memory_collection', 'project_memory')}\n"
        f"[bold cyan]Project Name:[/bold cyan] {project_name} (ID: {project_id})\n"
        f"[bold cyan]Project Path:[/bold cyan] {abs_path}\n"
        f"[bold cyan]Project Status:[/bold cyan] {'Recognized (has existing memory)' if project_mem.memory.purpose else 'New (uninitialized memory)'}"
    )
    console.print(Panel(diag_msg, title="🛠️ Agent Diagnostic Startup", border_style="bold green"))
    console.print(Panel(
        "[bold green]🚀 Agent Ready[/bold green]\n[dim]Type /help for commands. Use Enter to send, and Shift+Enter/Alt+Enter for newlines.[/dim]"
    ))

    bindings = KeyBindings()

    @bindings.add("enter")
    def submit(event):
        event.current_buffer.validate_and_handle()

    @bindings.add("escape", "enter")
    @bindings.add("escape", "[", "1", "3", ";", "2", "u")
    @bindings.add("c-j")
    def insert_newline(event):
        event.current_buffer.insert_text("\n")

    session = PromptSession(history=InMemoryHistory(), auto_suggest=None)

    def print_input_prompt(session_id: str, usage: dict = None):
        """Print the user input prompt with optional context usage."""
        if usage:
            pct = usage["percentage"]
            used = usage["used"]
            total = usage["total"]

            if pct < 50:
                color = "green"
            elif pct < 75:
                color = "yellow"
            elif pct < 90:
                color = "orange3"
            else:
                color = "red"

            # Use Rich Text for proper color handling
            text = Text()
            text.append("  ", style="dim")
            text.append(f"{pct:.0f}% filled ", style=color)
            text.append(f"[{used:,}/{total:,} tokens]", style="dim")
            console.print(text)

        console.print(f"[bold cyan]┌[{session_id[:6]}] You:[/bold cyan] ", end="")

    try:
        while True:
            usage = agent.get_context_usage()
            print_input_prompt(current_session_id, usage)
            user_input = await session.prompt_async(multiline=True, key_bindings=bindings)

            if not user_input.strip():
                continue

            if user_input.lower() in ["/exit", "/quit"]:
                break

            elif user_input.lower() == "/new":
                current_session_id = f"session_{uuid.uuid4().hex[:6]}"
                registry.session_id = current_session_id
                agent = create_agent_session(
                    config, llm, registry, current_session_id, ltm, config["llm"], working_directory=working_directory
                )
                console.print(f"[bold green]✨ Started new session: {current_session_id}[/bold green]")

            elif user_input.lower() == "/resume":
                console.print("[bold cyan]Fetching recent sessions...[/bold cyan]")
                sessions = MongoSTM.list_recent_sessions(
                    db_conf["mongo_uri"],
                    db_conf["db_name"],
                    db_conf.get("stm_collection", db_conf.get("collection_name", "short_term_memory")),
                )

                if not sessions:
                    console.print("[dim]No previous sessions found.[/dim]")
                    continue

                table = Table(show_header=True, header_style="bold magenta")
                table.add_column("#", style="dim", width=4)
                table.add_column("Session ID", style="cyan")
                table.add_column("Last Updated")

                for i, s in enumerate(sessions):
                    table.add_row(str(i + 1), s["session_id"], str(s.get("updated_at", "Unknown")))

                console.print(table)
                choice = await asyncio.to_thread(
                    console.input,
                    "[bold yellow]Enter session number to resume (or 'c' to cancel): [/bold yellow]",
                )

                if choice.lower() == "c":
                    continue

                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(sessions):
                        selected_id = sessions[idx]["session_id"]
                        current_session_id = selected_id
                        registry.session_id = current_session_id
                        agent = create_agent_session(
                            config, llm, registry, current_session_id, ltm, config["llm"], working_directory=working_directory
                        )
                        console.print(f"[bold green]♻️ Resumed session: {current_session_id}[/bold green]")
                    else:
                        console.print("[bold red]Invalid number.[/bold red]")
                except ValueError:
                    console.print("[bold red]Please enter a valid number.[/red]")

            elif user_input.lower() == "/help":
                console.print(Panel(
                    "[bold]/new[/bold] - Start a fresh session\n"
                    "[bold]/resume[/bold] - Pick a previous session\n"
                    "[bold]/help[/bold] - Show this menu\n"
                    "[bold]/exit[/bold] - Quit the agent\n\n"
                    "[dim]Tip: press Enter twice to send a multi-line message.[/dim]",
                    title="Commands",
                ))

            else:
                console.print("")
                console.print("")

                final_response = await agent.chat(
                    user_input, max_iterations=config["agent"]["max_iterations"]
                )

                if final_response:
                    console.print("")
                    console.print(Panel(
                        Markdown(final_response),
                        title=f"[bold magenta]Agent [{current_session_id[:6]}][/bold magenta]",
                        border_style="magenta",
                        padding=(1, 2),
                        box=ROUNDED,
                    ))
                    console.print("")

                agent.print_context_bar()
                console.print("")

    except KeyboardInterrupt:
        console.print("\n[dim yellow]Interrupted by user (Ctrl+C).[/dim yellow]")

    finally:
        console.print("[dim]Saving session summary to Long-Term Memory...[/dim]")

        summary_text = "No summary available"
        try:
            context_for_summary = agent.memory.get_context()
            context_for_summary.append(
                Message(
                    role="user",
                    content="Summarize the key accomplishments, facts learned, or code changes made in this session in 2-3 sentences.",
                )
            )

            summary_response = await llm.acomplete(
                context_for_summary,
                tools=None,
                max_tokens=config["llm"].get("max_tokens", 6000),
            )
            summary_text = summary_response.content

            ltm.save_session_summary(current_session_id, summary_text)
            console.print(f"[bold green]✅ Session {current_session_id} saved to long-term memory.[/bold green]")
        except Exception as e:
            console.print(f"[bold red]Could not save summary (API might be down): {e}[/bold red]")

        console.print("[dim]Updating Project Memory...[/dim]")
        try:
            conversation_context = agent.memory.get_context()
            project_mem = project_mem_mgr.generate_and_update_project_memory(
                project_mem=project_mem,
                conversation_context=conversation_context,
                llm=llm,
                session_id=current_session_id,
                session_summary=summary_text,
                working_directory=working_directory,
            )
            console.print("[bold green]✅ Project memory saved to MongoDB.[/bold green]")
            local_mem_file = os.path.join(working_directory, ".agent-memory.json")
            console.print(f"[bold green]✅ Exported project context to {local_mem_file}[/bold green]")
        except Exception as e:
            console.print(f"[bold red]Could not update project memory: {e}[/red]")

        if mcp_bridges:
            console.print("[dim]Shutting down MCP connections...[/dim]")
            for bridge in mcp_bridges:
                try:
                    bridge.sync_disconnect()
                except Exception:
                    pass
        console.print("[bold green]Goodbye![/bold green]")


def main():
    """Synchronous entry point — delegates to async_main via asyncio.run()."""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()