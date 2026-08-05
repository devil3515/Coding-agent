---
name: dispatching-parallel-agents
description: Use when facing 2+ independent tasks that can be worked on without shared state or sequential dependencies
---

# Dispatching Parallel Agents (for Agent)

## Overview

You delegate tasks to specialized agents with isolated context. By precisely crafting their instructions and context, you ensure they stay focused and succeed at their task. They should never inherit your session's context or history — you construct exactly what they need. This also preserves your own context for coordination work.

When you have multiple unrelated failures (different test files, different subsystems, different bugs), investigating them sequentially wastes time. Each investigation is independent and can happen in parallel.

**Core principle:** Dispatch one agent per independent problem domain. Let them work concurrently.

## When to Use

**Use when:**
- 2+ independent tasks (no shared state)
- Each task can be understood without context from others
- Tasks touch different files/modules
- No dependencies between task outcomes

**Don't use when:**
- Tasks share files or need each other's results
- Need to understand full system state
- Tasks are tightly coupled

## Example Scenarios for Agent

### Scenario 1: Multiple Test Failures
```
3 failing tests:
- test_email.py
- test_auth.py  
- test_database.py
```
→ Dispatch 3 agents, one per test file

### Scenario 2: Bug Fixes in Different Modules
```
Bugs to fix:
- src/tools/skills.py
- src/core/agent.py
- src/memory/mongo_stm.py
```
→ Dispatch 3 agents, one per file

## The Pattern

### 1. Identify Independent Domains

Group tasks by what's being worked on:
```
File A → task for Agent 1
File B → task for Agent 2
File C → task for Agent 3
```

### 2. Create Focused Agent Tasks

Each agent gets:
- **Specific scope:** One file or module
- **Clear goal:** What should be done
- **Constraints:** What NOT to change
- **Expected output:** What to return

### 3. Dispatch Agents

Each agent runs in isolation, producing independent results.

### 4. Review and Integrate

Collect results from all agents:
- Verify fixes don't conflict
- Run full test suite
- Integrate all changes

## Agent Dispatch Template

```
Task: Fix bug in {{file_path}}

Problem description:
{{error description}}

What I need you to do:
1. Read the file at {{file_path}}
2. Identify the issue based on the error
3. Fix the root cause
4. Verify the fix works
5. Return: Summary of what you found and fixed

Constraints:
- Do not change {{related_files}} unless necessary
- Keep existing code style
- Add tests if appropriate

Return format:
{
  "status": "DONE | NEEDS_MORE_INFO | BLOCKED",
  "summary": "Brief description",
  "changes": ["file1.py": "what changed"],
  "tests": ["test_passed": true/false]
}
```

## Key Differences from Kimi Code CLI Agent Swarm

| Aspect | Kimi Code AgentSwarm | Your Agent Dispatch |
|--------|---------------------|---------------------|
| Implementation | Built-in tool | Manual sub-agent creation |
| Execution | Parallel threads | Sequential or async |
| Context isolation | Automatic | Manual (clear context) |
| Results | Collected automatically | You must integrate |

## When to Use This Skill

**Use dispatching-parallel-agents skill when:**
- You have 2+ clearly independent tasks
- Each task can be completed in isolation
- You want to parallelize work for speed

**Example:**
```
 You: "Fix these 3 bugs: skills.py, agent.py, mongo_stm.py"
 Skill starts: "These are independent - dispatch parallel agents"
 Agent calls: dispatch_agents(tasks=[...])
 All work in parallel
 Results integrated
```

## How to Use

### Using the dispatch_agents Tool

When the skill indicates parallel dispatch is appropriate, use the `dispatch_agents` tool:

```json
{
  "tool": "dispatch_agents",
  "arguments": {
    "working_directory": "/path/to/project",
    "tasks": "[{\"task_id\": \"1\", \"description\": \"Fix bug in X\", \"context\": \"Details\"}, ...]",
    "max_concurrent": 3,
    "parallel": true
  }
}
```

### Task Format

Each task should have:
- `task_id`: Unique identifier
- `description`: What the agent should do
- `context`: Additional details, errors, file paths

### Example Task dispatch

```
Task 1: Fix syntax error in src/tools/skills.py
  - Error: "SyntaxError: invalid syntax on line 45"
  - Context: The closing parenthesis is missing on line 44

Task 2: Fix database connection issue in src/memory/mongo_stm.py  
  - Error: "Connection refused: 27017"
  - Context: Check connection string in config.yaml

Task 3: Update API endpoint in src/tools/api_tools.py
  - Error: "Endpoint /api/users returning 404"
  - Context: Route was removed, needs to be restored
```

### Dispatch Command

```json
{
  "task_id": "1",
  "description": "Fix syntax error in src/tools/skills.py",
  "context": "Error: SyntaxError on line 45. Check line 44 for missing closing parenthesis."
}
```

Call: `dispatch_agents(tasks=[...])`

### Expected Output

Each agent returns a summary:
```json
{
  "task_1": "Fixed syntax error - added closing parenthesis on line 44",
  "task_2": "Fixed database connection - updated connection string",
  "task_3": "Restored API endpoint /api/users route"
}
```

### After Dispatch

1. **Review all results** - Check each agent's output
2. **Look for conflicts** - Did any agents modify the same files?
3. **Run tests** - Verify all fixes work together
4. **Integrate** - Merge all changes

## Benefits

1. **Speed** - 3 problems solved in parallel vs sequentially
2. **Focus** - Each agent has narrow scope
3. **Independence** - Agents don't interfere with each other
4. **Quality** - Isolated context reduces mistakes

## Common Mistakes

**❌ Dispatching when tasks are related** - One agent's work affects another
**✅ Split the tasks first** - Make them truly independent

**❌ No isolation between agents** - Agents share context and get confused
**✅ Clear, focused prompts** - Each agent knows exactly its task

**❌ No integration step** - Results conflict or overlap
**✅ Review all results** - Check for conflicts before merging
