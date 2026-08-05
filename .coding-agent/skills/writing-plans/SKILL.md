---
name: writing-plans
description: Use when you have a spec or requirements for a multi-step task, before touching code
---

# Writing Implementation Plans for Coding-Agent

Create detailed step-by-step implementation plans before writing any code.

## Checklist

1. **Review the spec/document** — read and understand all requirements
2. **Identify key files** — locate existing files that need modification and new files needed
3. **Design file structure** — create directories/files as needed
4. **Write implementation steps** — broken into phases with clear objectives
5. **Include testing requirements** — what tests to write, where, and how to verify
6. **Review for completeness** — check nothing is missing, order is logical
7. **Get user approval** — present plan and wait for approval before coding

## Implementation Plan Format

```markdown
# Implementation Plan: [Feature/Task]
## Overview
[1-2 sentence summary]

## File Changes
### Existing Files
- `path/to/file.py` — [specific changes]

### New Files
- `path/to/new_file.py` — [description]

## Implementation Steps

### Phase 1: [Goal]
- Step 1.1
- Step 1.2

### Phase 2: [Goal]
- Step 2.1
- Step 2.2

## Testing
- Test file to create: [path]
- Test scenarios: [list]
- Verification commands: [commands]

## Dependencies
- Any new packages needed
- Any configuration changes required
```

## Coding-Agent Specific Guidelines

1. **Follow PEP 8** - Enforce style guide rigorously
2. **Type hints required** - All function signatures must have type hints
3. **Test coverage** - New code must have automated tests
4. **Documentation** - Docstrings for all public functions
5. **Module structure** - Follow existing patterns in `src/`

## Project Structure Reference

```
Coding-agent/
├── src/
│   ├── tools/         # Tool implementations
│   ├── memory/        # Memory systems
│   ├── llm/          # LLM providers
│   └── safety/       # Guardrails
├── prompts/          # System prompts
├── docs/             # Documentation
└── tests/            # Test files
```

## Related Skills

- **superpowers:brainstorming** — Use first to create spec
- **superpowers:systematic-debugging** — Use if implementation has issues
- **superpowers:test-driven-development** — For writing tests
