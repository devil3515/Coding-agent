# Memory Management Sprint 1 Documentation

## Overview

This document describes **Sprint 1** of the memory management architecture for the Coding Agent. Sprint 1 provides foundational memory and context management capabilities while maintaining backward compatibility with existing functionality.

## What Sprint 1 Implements

### Core Features

1. **Pydantic Schemas** (`src/memory/schemas.py`)
   - `TaskState`: Tracks task progress, status, plan, and history
   - `Checkpoint`: Saves agent state after each step
   - `SessionSummary`: Compressed session information
   - `ContextSections`: Structured context assembly

2. **MongoDB Persistence** (`src/memory/mongo_memory_store.py`)
   - `TaskStore`: CRUD operations for task state
   - `CheckpointStore`: Save and retrieve checkpoints
   - Automatic index creation for performance

3. **Secret Redaction** (`src/memory/redaction.py`)
   - Detects and redacts API keys, tokens, passwords
   - Supports OpenAI, AWS, GitHub, MongoDB connection strings
   - Recursive redaction for nested data structures

4. **Context Compiler** (`src/memory/context_compiler.py`)
   - Assembles prompts with XML-tagged sections
   - Priority-based section ordering
   - Automatic truncation and redaction
   - Extension points for future retrieval features

5. **Sprint 1 Manager** (`src/memory/sprint1_manager.py`)
   - High-level API for all Sprint 1 features
   - Feature flag controlled
   - Graceful degradation on errors

### New MongoDB Collections

- `tasks`: Task state documents
- `checkpoints`: Checkpoint documents

### Configuration Options

Add to `config.yaml`:

```yaml
memory:
  sprint1:
    enabled: false                    # Feature flag (default: false)
    redact_secrets: true              # Redact secrets before persistence
    checkpoint_every_step: true       # Save checkpoint after each step
    max_checkpoint_observation_chars: 2000  # Max observation length
    max_recent_turns_in_context: 12   # Max turns in compiled context
```

## What is Intentionally Out of Scope

Sprint 1 does **NOT** implement:

- ❌ Vector search or embeddings
- ❌ Semantic memory retrieval
- ❌ Automatic LLM-based summarization
- ❌ Automatic lesson extraction
- ❌ Failure pattern learning
- ❌ Playbooks or procedural memory
- ❌ Repo profile learning
- ❌ Knowledge graphs
- ❌ Team/org memory
- ❌ Multi-user RBAC
- ❌ Advanced retrieval/reranking

These features are planned for future sprints.

## How to Enable Sprint 1

### Step 1: Create config.yaml

Copy `config.yaml.example` to `config.yaml`:

```bash
cp config.yaml.example config.yaml
```

### Step 2: Enable the Feature Flag

Edit `config.yaml` and set:

```yaml
memory:
  sprint1:
    enabled: true
```

### Step 3: Ensure MongoDB is Configured

Make sure your `database` section has a valid MongoDB URI:

```yaml
database:
  mongo_uri: "mongodb+srv://user:pass@cluster.mongodb.net/"
  db_name: "coding_agent_db"
```

### Step 4: Use in Your Code

The Sprint 1 manager can be used alongside existing code:

```python
from src.memory.sprint1_manager import Sprint1MemoryManager

# Initialize (respects feature flag)
manager = Sprint1MemoryManager()

# Operations are no-ops if disabled
task_id = manager.ensure_task_exists(
    session_id="session-123",
    goal="Fix the login bug"
)

# Save checkpoint after each step
manager.save_checkpoint(
    last_action="write_file",
    last_observation="File updated successfully",
    files_modified=["src/auth.py"]
)

# Compile structured context
messages = manager.compile_context(
    recent_turns=[...],
    task=task_state,
    checkpoint=latest_checkpoint
)
```

## How Checkpointing Works

1. **Trigger**: After each agent tool execution step
2. **Data Saved**:
   - Step number
   - Last action name
   - Last observation (truncated & redacted)
   - Next action (if known)
   - Files modified list
   - Plan state snapshot
3. **Storage**: MongoDB `checkpoints` collection
4. **Retrieval**: Latest checkpoint fetched by task ID

Example checkpoint document:

```json
{
  "checkpoint_id": "ckpt-a1b2c3d4e5f6",
  "task_id": "task-123abc",
  "session_id": "session-456def",
  "step": 5,
  "plan_state": {"current_step": 2, "total_steps": 5},
  "files_modified": ["src/auth/login.py"],
  "last_action": "write_file",
  "last_observation": "[REDACTED_API_KEY]...",
  "next_action": "Run tests",
  "created_at": "2024-01-15T10:30:00Z"
}
```

## How Redaction Works

The redaction module (`src/memory/redaction.py`) scans text for patterns:

### Detected Patterns

| Pattern Type | Example | Replacement |
|-------------|---------|-------------|
| OpenAI API Key | `sk-abc123...` | `[REDACTED_API_KEY]` |
| AWS Access Key | `AKIA...` | `[REDACTED_AWS_KEY]` |
| GitHub Token | `ghp_...` | `[REDACTED_GITHUB_TOKEN]` |
| Bearer Token | `Bearer xyz` | `Bearer [REDACTED_TOKEN]` |
| Private Key | `BEGIN RSA PRIVATE KEY` | `[REDACTED_PRIVATE_KEY_HEADER]` |
| MongoDB URI | `mongodb://u:p@host` | `mongodb://u:[REDACTED_PASSWORD]@host` |
| Password Assignment | `password=secret` | `password=[REDACTED_PASSWORD]` |

### Usage

```python
from src.memory.redaction import redact_text, redact_dict

# Redact text
safe_text = redact_text("API key: sk-1234567890abcdefghijklmnop")
# Returns: "API key: [REDACTED_API_KEY]"

# Redact dict
safe_dict = redact_dict({"api_key": "sk-...", "host": "localhost"})
# Returns: {"api_key": "[REDACTED_API_KEY]", "host": "localhost"}
```

## How ContextCompiler Works

The compiler assembles messages with tagged sections:

### Section Priority Order

1. `<system_policy>` (always included)
2. `<task>` (if available)
3. `<plan>` (if available)
4. `<checkpoint>` (if available)
5. `<session_summary>` (if available)
6. `<recent_turns>` (always included if provided)

### Example Output

```xml
<system_policy>
You are a helpful coding assistant...
</system_policy>

<task>
Goal: Fix the login bug
Status: in_progress
Completed Steps:
  1. Identified issue in password validation
</task>

<checkpoint>
Step: 5
Last Action: write_file
Last Observation: File written successfully
</checkpoint>

<recent_turns>
[{"role": "user", "content": "Hello"}, ...]
</recent_turns>
```

### Benefits

- **Clarity**: LLM can parse sections easily
- **Priority**: Important info appears first
- **Safety**: Secrets redacted before inclusion
- **Extensibility**: Easy to add new sections

## Running Tests

### Prerequisites

```bash
pip install pytest mongomock
```

### Run All Tests

```bash
cd /workspace
python -m pytest tests/ -v
```

### Run Specific Test Files

```bash
# Test schemas
python -m pytest tests/unit/test_memory_schemas.py -v

# Test redaction
python -m pytest tests/unit/test_redaction.py -v

# Test context compiler
python -m pytest tests/unit/test_context_compiler.py -v

# Test stores
python -m pytest tests/unit/test_memory_stores.py -v

# Test feature flag integration
python -m pytest tests/integration/test_agent_sprint1_flag.py -v
```

## Known Limitations

1. **No Automatic Summarization**: Old turns are dropped without summarization
2. **No Semantic Search**: Retrieval is keyword/AST-based only
3. **No Learning**: Does not automatically extract lessons from failures
4. **Single User**: No multi-user or team support
5. **No Versioning**: Checkpoints don't track schema versions
6. **Limited Observability**: No metrics on memory usage quality

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     Agent Loop                              │
└───────────────────────┬─────────────────────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
        ▼               ▼               ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ Sprint1      │ │ Existing     │ │ LLM          │
│ Memory Mgr   │ │ STM (Mongo)  │ │ Provider     │
│              │ │              │ │              │
│ - TaskStore  │ │ - Turns      │ │ - Chat       │
│ - Checkpoint │ │ - Context    │ │ - Complete   │
│ - Compiler   │ │              │ │              │
└──────┬───────┘ └──────────────┘ └──────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│                   MongoDB                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ tasks       │  │ checkpoints │  │ sessions    │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
└─────────────────────────────────────────────────────────────┘
```

## Next Sprint Preview

Sprint 2 will likely include:

- ✅ Vector embeddings for semantic search
- ✅ Automatic context summarization
- ✅ Failure pattern storage and retrieval
- ✅ Repo conventions memory
- ✅ Improved observability and metrics

## Assumptions Made

1. MongoDB is available and configured
2. Pydantic v2 is used for schemas
3. Existing agent loop structure remains unchanged
4. Feature flag defaults to `false` for safety
5. Redaction patterns cover common secret formats

## Follow-up Risks

1. **Performance**: Additional DB writes per step may slow execution
2. **Storage**: Checkpoints accumulate over time; need cleanup strategy
3. **Privacy**: Redaction may miss novel secret formats
4. **Compatibility**: Schema changes may break old checkpoints
5. **Error Handling**: Network issues could block agent progress (mitigated by graceful degradation)

---

**Version**: 1.0  
**Date**: 2024  
**Author**: AI Systems Architect
