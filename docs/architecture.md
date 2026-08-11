# Coding Agent Architecture Writeup

---

## 1. Agentic Loop

The core execution loop is implemented as an **asynchronous state-machine-driven loop** inside the `Agent` class in `src/core/agent.py`.

### Lifecycle & Flow Step-by-Step

```
User Input ──> chat() ──> [Append User Msg] ──> Loop Start
                                                     │
    ┌────────────────────────────────────────────────┘
    ▼
[Check Max Iterations] ──(Hit Max)──> Forced Final Response ──> Return
    │ (Ok)
    ▼
[Build Fresh Context] ──> _build_context() [Inject System, Phase, LTM, Plan]
    │
    ▼
[Filter Tools by Phase] ──> ToolRegistry.get_schemas_for_phase(self.phase)
    │
    ▼
[Call LLM] ──> self.llm.acomplete(context, tools=available_tools)
    │
    ├─────► Is Final Response? ──> Append Assistant Msg ──> Return Response
    │
    └─────► Has Tool Calls?
                │
                ▼
      For each ToolCall in response:
        1. JSON Argument Parse Check
        2. Phase Authorization Check (is_tool_allowed)
        3. Security Interception (is_safe_path / is_shell_safe)
        4. Intercept Special Tool (create_project_plan / update_plan_status / ask_user_question)
        5. Execute Normal Tool (ToolRegistry.aexecute)
        6. Log to Audit Logger & Append Tool Result to Memory
                │
                ▼
      [Auto-Verification Step] ──> Read modified files back & inject into context
                │
                ▼
      [Check Phase Transition] ──> Update Phase State (IDLE → PLANNING → EXECUTING → VERIFYING → COMPLETED)
                │
                └───────────────> Repeat Loop
```

1. **Entry Point**: The loop is initiated by calling `Agent.chat(user_input, max_iterations=10)` in `src/core/agent.py:L184`.
2. **Iteration Trigger**: A continuous `while True:` loop (`agent.py:L200`) runs until either:
   - The LLM returns a final text response without tool calls (`response.is_final`).
   - The maximum number of iterations (`max_iterations`, default 10) is reached.
3. **Context & Tool Masking**: On each iteration:
   - `_build_context()` dynamically compiles a fresh system prompt combined with message history.
   - `registry.get_schemas_for_phase(self.phase)` filters the active tool schemas sent in the LLM API payload based on the agent's current phase.
4. **LLM Invocation**: The provider executes the completion request asynchronously (`self.llm.acomplete()`).
5. **Tool Execution & Interception**: If tool calls are returned:
   - Arguments are parsed and validated via Pydantic (`ToolRegistry.aexecute()`).
   - Phase restrictions are enforced via `is_tool_allowed()` in `src/core/state.py:L75`.
   - Paths and commands are intercepted by path/shell safety guardrails (`is_safe_path`, `is_shell_safe`).
   - Tool outputs are appended to memory as `Message(role="tool")`.
6. **Auto-Verification**: Any files edited during the turn (`write_file`, `apply_diff`) are added to `self._pending_verification` and immediately read back via `_auto_verify()`.

---

## 2. Context Management

Context construction and message history are managed primarily between `Agent._build_context()` and `MongoSTM` in `src/memory/mongo_stm.py`.

### Dynamic System Prompt Assembly

Context is re-constructed from scratch on **every single iteration turn** inside `_build_context()`:

1. **Base System Prompt**: Loaded from `get_default_prompt()`.
2. **Phase Banner**: Injects `[CURRENT PHASE: <PHASE>]` and explicit instructions on permitted tools.
3. **Long-Term Memory (LTM)**: Injects up to 5 past session summaries if context budget permits (< 3000 tokens).
4. **Discovered Context Tracker**: Injects cached summaries of previous search results (`self._discovered_context`) to avoid redundant re-searching.
5. **Working Directory & Active Plan**: Injects working directory rules and a step-by-step progress checklist with a `← YOU ARE HERE` marker.

### Truncation, Compaction & Token Budgeting

```
Raw Mongo Messages ──> Read-Time Compaction ──> Token Budget Enforcer ──> Context List
```

- **Read-Time Compaction (`MongoSTM._compact_for_context()`, `mongo_stm.py:L186`)**:
  - Protects the most recent 6 messages (`PROTECT_RECENT = 6`).
  - Tool output contents older than 6 turns and exceeding 2,000 chars (`COMPACT_THRESHOLD_CHARS`) are replaced with `"[Compacted tool result — N chars...]"`.
  - Tool-call argument strings in older assistant messages exceeding 2,000 characters are truncated.
- **Hard Storage Slice (`MongoSTM.add_message()`, `mongo_stm.py:L118`)**:
  - Messages in MongoDB are stored with `$push` and `"$slice": -self.max_messages` (default 20 in `cli.py`).
- **Token Budget Trimming (`MongoSTM._enforce_token_budget()`, `mongo_stm.py:L177`)**:
  - Uses `tiktoken`. If message tokens exceed allocated budget ratios (default 65% of context window for STM), older messages are popped until within budget.

---

## 3. State Persistence

### Persisted (Survives Process Restart)

| State | Storage | Location |
|---|---|---|
| Short-Term Memory (raw messages) | MongoDB `short_term_memory` | `MongoSTM`, up to 20 messages |
| Long-Term Memory (session summaries) | MongoDB `long_term_memory` | `LongTermMemory.save_session_summary()` |
| Project Memory (architecture notes) | MongoDB `project_memory` | `ProjectMemoryManager` |
| Tool Audit Trail | `.agent-audit/audit-YYYYMMDD.jsonl` | `AuditLogger`, append-only JSONL |

### Non-Persisted (Lost on Process Restart or Crash)

| State | Location |
|---|---|
| Agent Phase (`self.phase`) | Resets to `AgentPhase.IDLE` |
| Active Project Plan (`self.current_plan`) | Step checklist and completion statuses wiped |
| Verification Queue (`self._pending_verification`) | Files awaiting auto-verification cleared |
| Search Context Cache (`self._discovered_context`) | Cached search summaries lost |
| Token Statistics | `session_input_tokens` / `session_output_tokens` reset to 0 |
| Session Identity | New random `session_{uuid.uuid4().hex[:6]}` on each run (`cli.py:L367`) |

---

## 4. Tool Execution

Tool dispatching and lifecycle are managed by `ToolRegistry` in `src/tools/registry.py`.

```
LLM Tool Request ──> ToolRegistry.aexecute()
                           │
                           ├──> 1. Pydantic Validation (schemas.py)
                           ├──> 2. Sync vs Async Function Resolution (inspect.isawaitable)
                           ├──> 3. Execution & Exception Capture
                           └──> 4. Structured Audit Log (AuditLogger)
```

### Execution Process

1. **Schema Validation**: Arguments are validated against Pydantic models registered in `ToolRegistry.pydantic_schemas`. If validation fails, a `ValidationError` string is returned directly to the agent.
2. **Async Resolution**: `ToolRegistry.aexecute()` detects coroutines with `inspect.isawaitable` and awaits them; otherwise calls synchronously.
3. **Error Handling**: Exceptions inside tool functions are caught and returned as `"Error executing tool: {str(e)}"`. The harness **does not retry**. The error string goes to the LLM as the tool result; the LLM decides what to do next.
4. **Audit Logging**: Every invocation logs timestamp, duration, arguments, working directory, and status (`success`, `error`, `blocked`) to `.agent-audit/audit-YYYYMMDD.jsonl`.

---

## 5. Task / Subtask Structure

The agent uses a **Phase-Based State Machine** combined with a **Structured Plan Checklist**, not hierarchical multi-agent sub-loops.

### Phases (`src/core/state.py`)

| Phase | Tools Available | Description |
|---|---|---|
| `IDLE` | read, search, shell, git, plan creation | Initial exploration state |
| `PLANNING` | read, search, plan creation, plan edits | File modifications disabled |
| `EXECUTING` | read, write, diff, shell, git, plan status | Active work phase |
| `VERIFYING` | read, shell, git, plan status | Modification tools disabled |
| `COMPLETED` | ask user | Terminal phase |
| `RETRYING` | read, write, diff, shell, git, plan status | Re-attempt failed steps |

### Subtask Planning Mechanism

1. **Plan Creation**: `create_project_plan` registers steps: `[{"step": "...", "files": [...]}]`.
2. **Step Tracking**: Steps are stored in `self.current_plan` with statuses `["pending", "in_progress", "completed", "failed"]`.
3. **Automatic Phase Transitions**:
   - `IDLE` → `PLANNING` when `create_project_plan` is called.
   - `PLANNING` → `EXECUTING` when step 1 is marked `in_progress`.
   - `EXECUTING` → `VERIFYING` when all steps hit `completed` or `failed`.
   - `VERIFYING` → `COMPLETED` when pending file verifications are cleared and all steps pass.
4. **Execution Model**: All subtasks execute sequentially within the single flat `while True:` loop in `Agent.chat()`.

---

## 6. Known Bugs & Architecture Flaws

### Critical Bugs (Runtime Blockers)

**1. Method Name Mismatch (`acomplete` vs `async_complete`)**
- **Location**: `src/core/agent.py:L211` and `L227`.
- **Issue**: `agent.py` calls `await self.llm.acomplete(...)`. `OpenAIProvider` defines `async_complete()`, not `acomplete()`.
- **Impact**: Crashes immediately with `AttributeError: 'OpenAIProvider' object has no attribute 'acomplete'`.

**2. Broken Anthropic Tool Result Formatting**
- **Location**: `src/llm/anthropic_provider.py:L50-L53`.
- **Issue**: `_format_messages()` has `if m.tool_call_id is not None: continue`. Tool results (`role="tool"`) are silently stripped from the Anthropic API payload.
- **Impact**: Claude models never receive tool output results; tool-use workflows fail or loop indefinitely.

**3. Context Eviction via MongoDB `$slice: -20`**
- **Location**: `src/memory/mongo_stm.py:L118`, `cli.py:L70`.
- **Issue**: At ~3 messages per tool-call turn, the 20-message slice is exhausted in 6–7 turns. The original user prompt and plan definition get permanently deleted from MongoDB.
- **Impact**: Longer tasks lose their goal statement from persistent storage.

### Design Flaws & Multi-Hour / Long-Running Task Weaknesses

**4. In-Memory State Lost on Crash**
- **Location**: `src/core/agent.py:L52-L68`.
- Phase, current plan, pending verification list, and search cache are all Python instance variables. No recovery path exists after a restart.

**5. Random Session ID — No Resume Mechanism**
- **Location**: `cli.py:L367`.
- `session_{uuid.uuid4().hex[:6]}` is regenerated on every run. Past session MongoDB documents are orphaned. No `--resume` flag exists.

**6. Token Counting Uses Wrong Tokenizer for Non-OpenAI Models**
- **Location**: `src/memory/mongo_stm.py:L76-L96` and `src/core/agent.py:L70-L81`.
- `tiktoken` (OpenAI's tokenizer) is used for Claude and Gemini models. Fallback in `Agent._count_tokens` is `len(content) // 4`. Both are wrong for non-GPT models.
- Leads to premature context clipping or overflow errors.

**7. Deadlock in `VERIFYING` Phase if Tests Fail**
- **Location**: `src/core/agent.py:L367-L372`, `src/core/state.py:L52-L58`.
- `write_file` and `apply_diff` are disabled by `PHASE_TOOL_ALLOWLIST` in `VERIFYING`. If a test fails and the LLM needs to edit code, every attempt returns `PHASE ERROR`. The only escape is the `max_iterations` kill switch, which produces an incomplete forced response.

**8. No Rate Limit Handling or Retry Backoff**
- **Location**: `src/core/agent.py:L226-L235`.
- A single `try...except Exception` immediately exits `chat()` on any API error. On multi-hour tasks, one transient HTTP 429 or network blip kills the entire session.

**9. `max_iterations=10` Too Low for Complex Tasks**
- **Location**: `src/core/agent.py:L184`.
- A multi-file task with a plan consumes iterations quickly: 1 for overview, 1 for plan creation, ~2 per file step. Complex tasks reliably hit the kill switch before completion.

**10. Blocked Tool Calls Not Logged to Audit Trail**
- **Location**: `src/core/agent.py:L289-L292`, `src/audit/logger.py`.
- Path-safety and phase-enforcement blocks set `result = block_reason` and skip `ToolRegistry.aexecute()`, so `AuditLogger.log_tool_call()` is never called.
- Security-blocked events are invisible in the audit trail.

---

## 7. Dependencies and External Calls

| Dependency | Usage |
|---|---|
| `openai` | `OpenAI` / `AsyncOpenAI` in `OpenAIProvider`. API calls via `client.chat.completions.create()`. |
| `anthropic` | `Anthropic` / `AsyncAnthropic` in `AnthropicProvider`. API calls via `client.messages.create()`. |
| `pymongo` | `MongoClient` in `MongoSTM`, `LongTermMemory`, `ProjectMemoryManager`. |
| `pydantic` | Tool argument validation in `ToolRegistry` via `BaseModel` schemas in `src/tools/schemas.py`. |
| `tiktoken` | Token counting in `MongoSTM._count_tokens()`. |
| `typer` | CLI argument parsing in `cli.py`. |
| `rich` | Terminal output formatting (Console, Panel, Table, Markdown). |
| `prompt_toolkit` | Interactive REPL with key bindings and input history in `cli.py`. |

**No agentic frameworks** (LangChain, LlamaIndex, AutoGen, CrewAI) are used. The agent loop is raw `asyncio` calling OpenAI and Anthropic SDKs directly.

---

## 8. File Map

| File | Responsibility |
|---|---|
| `cli.py` | CLI entry point. Tool registration, MongoDB session setup, prompt_toolkit interactive REPL. |
| `src/core/agent.py` | Main reasoning loop (`Agent.chat`). Context builder (`_build_context`), phase transitions, auto-verification. |
| `src/core/state.py` | `AgentPhase` enum, `PHASE_TOOL_ALLOWLIST`, and `PhaseTransition` logic. |
| `src/core/parallel_agent.py` | Parallel sub-agent variant (separate from main loop). |
| `src/memory/mongo_stm.py` | `MongoSTM`: short-term memory, read-time compaction, token budgeting, MongoDB slice persistence. |
| `src/memory/long_term.py` | `LongTermMemory`: cross-session summary storage and retrieval. |
| `src/memory/project_memory.py` | `ProjectMemoryManager`: per-project architecture notes and convention metadata. |
| `src/memory/base.py` | `BaseMemory` abstract class. |
| `src/tools/registry.py` | `ToolRegistry`: registration, Pydantic validation, sync/async execution, phase schema filtering. |
| `src/tools/schemas.py` | Pydantic argument schemas for all standard tools. |
| `src/tools/file_tools.py` | Native file tools: `read_file`, `write_file`, `apply_diff`, `get_file_tree`. |
| `src/tools/shell.py` | Async subprocess shell command execution (`run_shell_command_async`). |
| `src/tools/git_tools.py` | Git command execution (`run_git_async`). |
| `src/tools/codebase_graph.py` | AST-based codebase overview and search indexer. |
| `src/tools/planning.py` | Plan creation and update helper functions. |
| `src/llm/base.py` | Abstract `LLMProvider`, `Message`, `ToolCall`, and `LLMResponse` dataclasses. |
| `src/llm/openai_provider.py` | `OpenAIProvider`: message formatting, tool call parsing, OpenAI API calls. |
| `src/llm/anthropic_provider.py` | `AnthropicProvider`: message formatting, tool call parsing, Anthropic API calls. |
| `src/safety/guardrails.py` | `is_safe_path` (directory traversal) and `is_shell_safe` (command injection filter). |
| `src/audit/logger.py` | `AuditLogger`: append-only JSONL audit trail per day in `.agent-audit/`. |
| `src/config/settings.py` | Config loader for `config.yaml`. |
| `src/mcp/bridge.py` | `MCPBridge`: connects to external MCP servers and injects their tools into the registry. |
| `prompts/registry.py` | System prompt loader (`get_default_prompt`). |
