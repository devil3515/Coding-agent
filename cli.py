import typer
import uuid
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.box import DOUBLE, ROUNDED, HEAVY, SQUARE, MINIMAL
from rich.syntax import Syntax
from rich.text import Text
from rich.markdown import Markdown
from rich.spinner import Spinner
import os
import json
import asyncio
import hashlib
from datetime import datetime
from dataclasses import asdict
from src.config.settings import load_settings
from src.llm.openai_provider import OpenAIProvider
from src.tools.registery import ToolRegistry
from src.tools.shell import run_shell_command
from src.core.agent import Agent
from src.memory.mongo_stm import MongoSTM
from src.memory.long_term import LongTermMemory
from src.memory.project_memory import ProjectMemoryManager
from src.models import ShortTermMemoryModel, LongTermMemoryModel, ProjectMemoryContent, ProjectMemoryModel
from src.llm.base import Message
from src.tools.codebase_graph import search_codebase, get_codebase_overview
from src.tools.file_tools import read_file, write_file, apply_diff, get_file_tree, find_files
from src.tools.planning import create_project_plan, update_project_plan, ask_user_question, update_plan_text
from src.core.skill_core import load_skill_manager
from src.tools.git_tools import run_git
from src.tools.skills import SKILL_TOOLS
from src.core.parallel_agent import PARALLEL_AGENT_TOOLS
from prompts.registry import get_default_prompt
from src.mcp.bridge import MCPBridge
from src.memory.mongo_stm import MODEL_CONTEXT_WINDOWS
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.formatted_text import HTML

app = typer.Typer()
console = Console()


def create_agent_session(config: dict, llm: OpenAIProvider, registry: ToolRegistry, session_id: str, ltm: LongTermMemory = None, llm_config: dict = None, working_directory: str = None, skill_manager = None) -> Agent:
    """Create a new agent session with the given configuration."""
    db_conf = config['database']
    memory_config = config.get('memory', {}).get('short_term', {})

    # Get model name from LLM config
    model_name = llm_config.get('model', 'gpt-4o') if llm_config else 'gpt-4o'

    # Extract model context window from config or use default
    model_context_window = config.get('memory', {}).get('model_context_window', MODEL_CONTEXT_WINDOWS.get(model_name, 128000))

    # Memory context budget - leaving 25% for response generation
    # Default is memory_config.max_tokens, but cap at 75% of context window to leave room for response
    memory_max_tokens = config.get('memory', {}).get('short_term', {}).get('max_tokens', 32000)
    memory_max_tokens = min(memory_max_tokens, int(model_context_window * 0.75))  # Max 75% of context window

    memory = MongoSTM(
        mongo_uri=db_conf['mongo_uri'],
        db_name=db_conf['db_name'],
        collection_name=db_conf.get('stm_collection', db_conf.get('collection_name', 'short_term_memory')),
        session_id=session_id,
        system_prompt=get_default_prompt(working_dir=working_directory),
        max_messages=memory_config.get('max_messages', 20),
        max_tokens=memory_max_tokens,
        model=model_name,
        context_window=model_context_window
    )
    return Agent(llm=llm, registry=registry, memory=memory, console=console, ltm=ltm, llm_config=llm_config, working_directory=working_directory, session_id=session_id, skill_manager=skill_manager)


def print_typing_indicator(session_id: str):
    """Print a Kimi Code-style typing indicator."""
    from rich.live import Live
    from rich.spinner import Spinner
    spinner = Spinner("dots12", " Thinking...")
    panel = Panel(
        spinner,
        title=f"[bold cyan]Agent [{session_id[:6]}]...",
        border_style="cyan",
        padding=(1, 2),
        box=ROUNDED
    )
    return panel



def main():
    config = load_settings()
    llm = OpenAIProvider(config['llm'])
    db_conf = config['database']
    registry = ToolRegistry()
    working_directory = os.getcwd()
    abs_path = os.path.abspath(working_directory)

    project_id = hashlib.sha256(abs_path.encode()).hexdigest()[:16]


    #-- SHELL COMMAND TOOL -----------------------------------------------------
    registry.register(
        name="run_shell_command",
        description="Executes a bash shell command on the local machine and returns the output. Use this to list files, run scripts, or check code.",
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to run."
                }
            },
            "required": ["command"]
        },
        function=run_shell_command
    )

    #-- CODEBASE SEARCH TOOL ---------------------------------------------------
    registry.register(
       name="search_codebase",
        description="Queries the architecture of the local codebase. Use this BEFORE writing code to find where functions/classes are defined, what calls what, and how the project is structured.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The function, class, or variable name to search for (e.g., 'Agent', 'complete', 'MongoSTM')."
                }
            },
            "required": ["query"]
        },
        function=search_codebase
    )

    #-- FILE TOOLS -------------------------------------------------------------
    registry.register(
        name="read_file",
        description="Reads a file's contents. ALWAYS use this to examine code before editing it. Use start_line and end_line (0-indexed) if you only need a specific chunk.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "The path to the file to read."},
                "start_line": {"type": "integer", "description": "Starting line index (default 0)."},
                "end_line": {"type": "integer", "description": "Ending line index (default -1 for all)."}
            },
            "required": ["file_path"]
        },
        function=read_file
    )

    registry.register(
        name="write_file",
        description="OVERWRITES a file entirely with new content. Use this to create new files or completely replace existing ones. Creates directories automatically.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "The path to the file to write."},
                "content": {"type": "string", "description": "The full exact content to write to the file."}
            },
            "required": ["file_path", "content"]
        },
        function=write_file
    )

    #-- APPLY DIFF TOOL --------------------------------------------------------
    registry.register(
        name="apply_diff",
        description="Surgically edits a file by replacing an exact block of text. PREFER THIS over write_file for making small changes, fixing bugs, or updating specific functions. Do NOT use this to create new files.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "The path to the file to edit."},
                "old_string": {"type": "string", "description": "The exact block of text to find and replace. MUST match exactly, including whitespace and indentation."},
                "new_string": {"type": "string", "description": "The new text to replace the old text with."}
            },
            "required": ["file_path", "old_string", "new_string"]
        },
        function=apply_diff
    )

    #-- GIT TOOLS -------------------------------------------------------------
    registry.register(
        name="run_git",
        description="Executes a git command. Use this to check status, commit changes, or view history. Pass the arguments as a single string.",
        parameters={
            "type": "object",
            "properties": {
                "args": {"type": "string", "description": "Git arguments, e.g., 'status', 'add .', 'commit -m \"fixed bug\"'"}
            },
            "required": ["args"]
        },
        function=run_git
    )

    #-- PROJECT PLAN TOOLS -----------------------------------------------------
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
                            "step":  {"type": "string", "description": "What to do in this step."},
                            "files": {"type": "array", "items": {"type": "string"}, "description": "Files to read or write in this step."}
                        },
                        "required": ["step"]
                    },
                    "description": "Ordered list of steps, each with a description and the files it will touch."
                }
            },
            "required": ["steps"]
        },
        function=create_project_plan
    )

    registry.register(
        name="update_plan_status",
        description="Mark a plan step as in_progress, completed, or failed. Call this when you start AND finish every step.",
        parameters={
            "type": "object",
            "properties": {
                "step_number": {"type": "integer", "description": "1-based step number."},
                "status": {"type": "string", "enum": ["completed", "in_progress", "failed"], "description": "New status."}
            },
            "required": ["step_number", "status"]
        },
        function=update_project_plan
    )

    registry.register(
        name="update_plan_text",
        description="Rename or rewrite a step's description mid-task (e.g. if scope changed).",
        parameters={
            "type": "object",
            "properties": {
                "step_number": {"type": "integer", "description": "1-based step number to update."},
                "new_text": {"type": "string", "description": "Replacement text for the step title."}
            },
            "required": ["step_number", "new_text"]
        },
        function=update_plan_text
    )

    registry.register(
        name="ask_user_question",
        description="Pause and ask the user a clarifying question before continuing. Use question_type='mcq' for multiple choice.",
        parameters={
            "type": "object",
            "properties": {
                "question":      {"type": "string", "description": "The question to ask."},
                "question_type": {"type": "string", "enum": ["text", "mcq"], "description": "Free text or multiple choice."},
                "options":       {"type": "array", "items": {"type": "string"}, "description": "Choices for MCQ questions."}
            },
            "required": ["question"]
        },
        function=ask_user_question
    )

    # Register skill tools
    for tool_name, tool_config in SKILL_TOOLS.items():
        registry.register(
            name=tool_name,
            description=tool_config["description"],
            parameters=tool_config["parameters"],
            function=tool_config["function"]
        )

    #-- CODEBASE OVERVIEW TOOLS ------------------------------------------------
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
            }
        },
        function=lambda directory=None: get_codebase_overview(directory or working_directory)
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
                "max_depth":  {"type": "integer", "description": "Max folder depth (default 4)."}
            }
        },
        function=lambda directory=None, max_depth=4: get_file_tree(directory or working_directory, max_depth)
    )

    registry.register(
        name="find_files",
        description=(
            "Searches for files matching a glob pattern within the project directory. "
            "Use this to find files by name or pattern when you know roughly what you're looking for. "
            "Supports patterns like '*.py', '**/models/*.py', 'test_*.py'. "
            "Returns up to 50 results by default."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern to match files (e.g., '*.py', '**/*.md', 'config.{json,yaml}')"},
                "directory": {"type": "string", "description": "Directory to search in (default: current working directory)"},
                "max_results": {"type": "integer", "description": "Maximum number of results to return (default: 50, max: 100)"}
            },
            "required": ["pattern"]
        },
        function=lambda pattern, directory=None, max_results=50: find_files(pattern, directory or working_directory, max_results)
    )

    # Register parallel agent tools
    for tool_name, tool_config in PARALLEL_AGENT_TOOLS.items():
        registry.register(
            name=tool_name,
            description=tool_config["description"],
            parameters=tool_config["parameters"],
            function=tool_config["function"]
        )

    #-- MCP TOOLS -------------------------------------------------------------

    mcp_bridges = []  # keep references to ALL bridges for clean shutdown
    if "mcp_servers" in config:
        for server_name, server_conf in config["mcp_servers"].items():
            console.print(f"[bold cyan]Connecting to MCP Server: {server_name}...[/bold cyan]")
            try:
                mcp_bridge = MCPBridge(
                    url=server_conf["url"],
                    headers=server_conf.get("headers", {})
                )
                mcp_bridge.sync_connect()  # blocks until tools are listed (or raises)
                mcp_bridges.append(mcp_bridge)

                # Inject MCP tools into our local registry!
                for tool in mcp_bridge.mcp_tools:
                    # Generic closure to route this specific tool to its bridge
                    def make_mcp_executor(t_name, bridge):
                        def executor(**kwargs):
                            return bridge.call_tool(t_name, kwargs)  # already sync now
                        return executor

                    registry.register(
                        name=tool["name"],
                        description=tool["description"],
                        parameters=tool["inputSchema"],  # MCP uses standard JSON schema!
                        function=make_mcp_executor(tool["name"], mcp_bridge)
                    )
                console.print(f"[green]✅ Injected {len(mcp_bridge.mcp_tools)} tools from {server_name}.[/green]")
            except Exception as e:
                console.print(f"[red]Failed to connect to {server_name}: {e}[/red]")



    ltm = LongTermMemory(
        mongo_uri=db_conf['mongo_uri'],
        db_name=db_conf['db_name'],
        collection_name=db_conf.get('ltm_collection', 'long_term_memory')
    )

    project_mem_mgr = ProjectMemoryManager(
        mongo_uri=db_conf['mongo_uri'],
        db_name=db_conf['db_name'],
        collection_name=db_conf.get('project_memory_collection', 'project_memory')
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
            updated_at=datetime.utcnow()
        )

    # Initialize skill manager
    skill_manager = load_skill_manager(working_directory)

    current_session_id = f"session_{uuid.uuid4().hex[:6]}"
    agent = create_agent_session(config, llm, registry, current_session_id, ltm, config['llm'], working_directory=working_directory, skill_manager=skill_manager)

    # PRINT startup diagnostic panel - Kimi Code style
    diag_msg = (
        f"[bold cyan]Session:[/bold cyan] {current_session_id[:6]}\n"
        f"[bold magenta]Model:[/bold magenta] {config['llm'].get('model', 'Unknown')}\n"
        f"[bold green]Mongo:[/bold green] Connected\n"
        f"[bold yellow]Project:[/bold yellow] {project_name}"
    )
    console.print(Panel(diag_msg, title="🤖 Kimi Code Agent", border_style="bold purple", style="bold", padding=(1, 2), box=DOUBLE))
    console.print(Panel(
        f"[bold green]Ready! Type your request below.[/bold green]\n"
        f"Use [bold]/help[/bold] for commands • [bold]/exit[/bold] to quit",
        border_style="green",
        padding=(0, 2)
    ))
    console.print("")

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

    # Print input prompt with context info
    def print_input_prompt(session_id: str, usage: dict = None):
        # Print context usage if available (on its own line first)
        if usage:
            pct = usage['percentage']
            color = "green" if pct < 50 else "yellow" if pct < 90 else "red"
            used = usage['used']
            total = usage['total']
            console.print(f"  [dim]{color}{pct:.0f}% filled [{used}/{total} tokens][/dim]")

        # Print the input prompt on the same line
        prompt_line = f"[bold cyan]┌[{session_id[:6]}] You:[/bold cyan] "
        console.print(prompt_line, end="")

    # --- WRAP IN TRY/FINALLY FOR SAFE EXIT ---
    try:
        while True:
            # Get current usage for prompt
            usage = agent.get_context_usage()

            # Print input prompt
            print_input_prompt(current_session_id, usage)
            user_input = session.prompt(multiline=True, key_bindings=bindings)

            if not user_input.strip():
                continue

            if user_input.lower() in ["/exit", "/quit"]:
                break

            elif user_input.lower() == "/new":
                current_session_id = f"session_{uuid.uuid4().hex[:6]}"
                agent = create_agent_session(config, llm, registry, current_session_id, ltm, config['llm'], working_directory=working_directory)
                console.print(Panel(f"[bold green]✨ Started new session: {current_session_id[:6]}[/bold green]", border_style="green", padding=(0, 1)))

            elif user_input.lower() == "/resume":
                console.print("[bold cyan]Fetching recent sessions...[/bold cyan]")
                sessions = MongoSTM.list_recent_sessions(db_conf['mongo_uri'], db_conf['db_name'], db_conf.get('stm_collection', db_conf.get('collection_name', 'short_term_memory')))

                if not sessions:
                    console.print("[dim]No previous sessions found.[/dim]")
                    continue

                table = Table(box=MINIMAL, show_header=True, header_style="bold magenta")
                table.add_column("#", style="dim", width=4)
                table.add_column("Session ID", style="cyan")
                table.add_column("Last Updated")

                for i, s in enumerate(sessions):
                    table.add_row(str(i+1), s['session_id'][:6], str(s.get('updated_at', 'Unknown')).split('.')[0])

                console.print(table)
                choice = console.input("[bold yellow]Enter session number to resume (or 'c' to cancel): [/bold yellow]")

                if choice.lower() == 'c':
                    continue

                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(sessions):
                        selected_id = sessions[idx]['session_id']
                        current_session_id = selected_id
                        agent = create_agent_session(config, llm, registry, current_session_id, ltm, config['llm'], working_directory=working_directory)
                        console.print(Panel(f"[bold green]♻️  Resumed session: {current_session_id[:6]}[/bold green]", border_style="green", padding=(0, 1)))
                    else:
                        console.print("[bold red]Invalid number.[/bold red]")
                except ValueError:
                    console.print("[bold red]Please enter a valid number.[/red]")

            elif user_input.lower() == "/help":
                help_content = "\n".join([
                    "[bold]/new[/bold]       Start a fresh session",
                    "[bold]/resume[/bold]    Pick a previous session",
                    "[bold]/help[/bold]      Show this help menu",
                    "[bold]/exit[/bold]      Quit the agent",
                    "",
                    "[dim]Tip: Press Enter twice to send a multi-line message.[/dim]"
                ])
                console.print(Panel(help_content, title="Commands", border_style="cyan", padding=(0, 2)))

            else:
                # Process the user input - show line break after input
                console.print("")
                console.print("")

                final_response = agent.chat(user_input, max_iterations=config['agent']['max_iterations'])

                if final_response:
                    # Print agent response with nice formatting
                    console.print("")
                    console.print(Panel(
                        Markdown(final_response),
                        title=f"[bold magenta]Agent [{current_session_id[:6]}][/bold magenta]",
                        border_style="magenta",
                        padding=(1, 2),
                        box=ROUNDED
                    ))
                    console.print("")

                    # Show updated context bar
                    agent.print_context_bar()
                    console.print("")

    except KeyboardInterrupt:
        console.print("\n[dim yellow]Interrupted by user (Ctrl+C).[/dim yellow]")

    finally:
        # Print final status panel
        console.print("")
        console.print(Panel(
            "[bold green]Session saved to long-term memory.[/bold green]\n"
            "[bold green]Project memory updated.[/bold green]",
            border_style="green",
            padding=(1, 2),
            box=MINIMAL
        ))


if __name__ == "__main__":
    main()