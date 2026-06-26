# Coding Agent

A terminal-based AI coding assistant that reads, writes, and edits code, runs shell commands, searches your codebase via an AST graph, manages git, and plans multi-step tasks — all driven by an LLM tool-calling loop. Conversation history is persisted in MongoDB and summarized into long-term memory across sessions.

## Features

- **Interactive CLI** — Rich terminal UI with multi-line input and session management (`/new`, `/resume`, `/help`, `/exit`)
- **Tool-calling agent loop** — The LLM invokes tools repeatedly until it produces a final answer, with a configurable iteration cap and graceful handoff on timeout
- **File operations** — `read_file`, `write_file`, and `apply_diff` for surgical, line-level edits
- **Shell & Git** — Run bash commands and git operations directly from the agent
- **Codebase graph search** — Tree-sitter AST indexing for Python, JavaScript, and TypeScript; search functions, classes, and call relationships
- **Project planning** — Structured multi-step plan creation with per-step status tracking and live progress display
- **Human-in-the-loop** — Agent can pause and ask clarifying questions (free-text or multiple choice)
- **MCP tool bridge** — Connect any MCP-compatible server (e.g. Google Stitch) and inject its tools directly into the agent's tool registry
- **Memory**
  - **Short-term (STM)** — MongoDB-backed per-session conversation history with automatic compaction of large tool outputs
  - **Long-term (LTM)** — Session summaries injected into future runs for continuity
- **Safety guardrails** — Blocks file access outside the working directory and dangerous shell patterns
- **Token tracking** — Input, output, and cumulative session token counts shown per turn

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- MongoDB instance (local or [Atlas free tier](https://www.mongodb.com/atlas/database))
- An API key for any OpenAI-compatible LLM endpoint

## Quick Start

```bash
cd coding-agent

# Install dependencies
uv sync

# Copy the example config and fill in your credentials
cp config.yaml.example config.yaml
# Edit config.yaml — set your LLM api_key and database.mongo_uri at minimum
```

Then `cd` into the project you want to work on and launch:

```bash
cd /path/to/your/project
uv run python /path/to/coding-agent/cli.py
```

The agent sets its working directory to wherever you launched it from, so all file operations are scoped to that project.

## Configuration

Copy `config.yaml.example` to `config.yaml` and fill in your values. The file is gitignored by default — **never commit real credentials**.

```yaml
llm:
  base_url: "https://your-openai-compatible-endpoint/v1"  # omit for OpenAI default
  model: "gpt-4o"
  api_key: "YOUR_API_KEY_HERE"
  temperature: 0.1
  max_tokens: 8000
  headers:                      # optional — some providers require extra headers
    OpenAI-Project: "default"

database:
  mongo_uri: "mongodb+srv://<user>:<pass>@<cluster>.mongodb.net/"
  db_name: "coding_agent_db"
  collection_name: "short_term_memory"

agent:
  max_iterations: 100

memory:
  short_term:
    max_tokens: 15000

tools:
  shell_command_timeout: 30

# mcp_servers:                  # optional — remove if unused
#   google_stitch:
#     url: "https://stitch.googleapis.com/mcp"
#     headers:
#       X-Goog-Api-Key: "YOUR_KEY"
```

### Supported LLM providers

The agent uses an OpenAI-compatible client, so it works with any endpoint that speaks the OpenAI API:

| Provider | `base_url` |
|---|---|
| OpenAI | *(omit — uses default)* |
| AWS Bedrock Mantle | `https://bedrock-mantle.<region>.api.aws/v1` |
| Ollama (local) | `http://localhost:11434/v1` |
| Azure OpenAI | `https://<resource>.openai.azure.com/openai/deployments/<model>` |

An `AnthropicProvider` is also available in `src/llm/anthropic_provider.py` — swap the import in `cli.py` to use Claude natively.

## CLI Commands

| Command | Description |
|---|---|
| `/new` | Start a fresh session |
| `/resume` | Pick a previous session from MongoDB |
| `/help` | Show available commands |
| `/exit` | Quit (saves session summary to long-term memory) |

**Multi-line input:** press **Enter twice** (blank line) to submit a message. Single-line messages work the same way — just type and hit Enter twice.

On exit (including Ctrl+C), the agent generates a short summary of the session and stores it in long-term memory so future sessions have context.

## Available Tools

| Tool | Purpose |
|---|---|
| `read_file` | Read file contents, optionally by line range |
| `write_file` | Create or fully overwrite a file |
| `apply_diff` | Replace an exact text block in an existing file (preferred for edits) |
| `run_shell_command` | Execute a bash command |
| `run_git` | Run git commands |
| `search_codebase` | Find functions/classes and their call relationships |
| `get_codebase_overview` | List every symbol in the project grouped by file |
| `get_file_tree` | Directory tree including non-code files |
| `create_project_plan` | Create a structured, step-by-step plan for complex tasks |
| `update_plan_status` | Mark a plan step as `in_progress`, `completed`, or `failed` |
| `update_plan_text` | Rename a plan step mid-task if scope changes |
| `ask_user_question` | Pause execution and ask the user a clarifying question |

MCP server tools are injected automatically at startup alongside the built-in tools.

## Architecture

```
cli.py                      # Entry point, tool registration, REPL loop
├── src/core/agent.py       # Reasoning loop (LLM ↔ tools ↔ memory)
├── src/llm/                # LLM providers (OpenAI-compatible, Anthropic)
├── src/tools/              # Tool implementations and registry
├── src/memory/             # Short-term (MongoDB STM) and long-term memory
├── src/graph/              # Tree-sitter AST extraction and code graph
├── src/safety/             # Path sandboxing and shell command guardrails
├── src/mcp/                # MCP server bridge (connects external tool servers)
└── prompts/                # System prompt templates (Markdown + registry)
```

### Agent loop

1. User message is added to short-term memory
2. System prompt is enriched with the working directory, past session summaries (LTM), and the active project plan (if any)
3. LLM is called with the full conversation context and all tool schemas
4. If the model requests tools, each call passes through the security layer, executes, and results are appended to context
5. Steps 3–4 repeat until the model returns a final response or `max_iterations` is reached
6. On `max_iterations`, the agent forces a final summary response and returns a structured handoff JSON

### Memory compaction

To keep costs down, tool-call arguments and results older than the last 6 messages are compacted in-memory before being sent to the LLM. Large `write_file` arguments are replaced with per-key summaries; large tool results are replaced with a compact placeholder. The raw data is never modified in MongoDB — compaction only affects what gets sent to the LLM.

### Codebase graph

`search_codebase` and `get_codebase_overview` use Tree-sitter to parse `.py`, `.js`, `.jsx`, `.ts`, and `.tsx` files and build a directed graph of functions, classes, and call edges. The graph is cached per-session so repeated searches are instant.

## Project Structure

```
coding-agent/
├── cli.py
├── config.yaml             # gitignored — your real credentials go here
├── config.yaml.example     # committed — safe template with placeholder values
├── pyproject.toml
├── ARCHITECTURE.md
├── prompts/
│   ├── registry.py
│   ├── default.md
│   ├── planning.md
│   └── kill_switch.md
└── src/
    ├── config/
    │   └── settings.py
    ├── core/
    │   └── agent.py
    ├── graph/
    │   ├── extractor.py
    │   └── graph.py
    ├── llm/
    │   ├── base.py
    │   ├── openai_provider.py
    │   └── anthropic_provider.py
    ├── mcp/
    │   └── bridge.py
    ├── memory/
    │   ├── base.py
    │   ├── mongo_stm.py
    │   └── long_term.py
    ├── safety/
    │   └── guardrails.py
    └── tools/
        ├── registery.py
        ├── file_tools.py
        ├── shell.py
        ├── git_tools.py
        ├── codebase_graph.py
        └── planning.py
```

## Safety

Before any file or shell tool executes, the agent checks:

- **Path sandboxing** — File tools (`read_file`, `write_file`, `apply_diff`, `search_codebase`) can only access paths inside the current working directory
- **Shell filtering** — Blocks destructive patterns (`rm -rf /`, `mkfs`, `shutdown`, `format`, suspicious `../` traversal) before any command runs

## License

Add your license here.
