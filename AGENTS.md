# Coding-Agent Project AGENTS

## Build & Development

### Running the Agent
- Start the agent: `python cli.py`
- Use `/new` to start a fresh session
- Use `/resume` to resume a previous session
- Use `/help` to see all commands
- Use `/exit` to quit

### Testing
- Run tests with: `pytest` or `python -m pytest`
- Code should be well-tested before committing

### Build Commands
- This is a Python project using `pyproject.toml`
- Install dependencies: `pip install -e .` or `uv sync`

## Code Style

### Python Conventions
- Follow PEP 8 style guide
- Use type hints on all function signatures
- Use meaningful variable names
- Keep functions focused on a single responsibility
- Use docstrings for all public functions/classes

### File Organization
- Source code: `src/` directory
- Tools: `src/tools/`
- Memory systems: `src/memory/`
- LLM providers: `src/llm/`
- Safety/guardrails: `src/safety/`

## Git Workflow

### Branching
- Main branch is protected
- Feature branches: `feature/your-feature-name`
- Bugfix branches: `fix/your-bug-name`

### Commits
- Use conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`
- Atomic commits - one change per commit
- Write clear commit messages

### Before Committing
1. Run tests: `pytest`
2. Run linting: `ruff check .` (if configured)
3. Check type hints: `mypy .` (if configured)
4. Review your diff: `git diff`

## Tools & Services

### Database
- MongoDB for memory storage (short-term and long-term)
- Free tier Atlas: https://www.mongodb.com/atlas/database

### LLM Providers
- OpenAI-compatible endpoints supported
- Default model: `gpt-4o`
- Test configuration in `config.yaml.example`

## Security

### Never Commit
- API keys in `config.yaml`
- Use environment variables: `export OPENAI_API_KEY="your-key"`
- The `.gitignore` already excludes `config.yaml` and `*.egg-info/`

### Code Review
- New features need review before merging
- Security-sensitive changes need extra scrutiny
- Run tests before merging

## Deployment

### Local Development
- No deployment needed - runs locally
- Server runs on `localhost` only

### Environment Setup
1. Copy `config.yaml.example` to `config.yaml`
2. Fill in your API keys and database credentials
3. Install dependencies: `pip install -e .`
4. Run: `python cli.py`

## Common Tasks

### Adding a New Tool
1. Create function in `src/tools/`
2. Register in `cli.py` (registry section)
3. Update prompts to document the tool
4. Add tests

### Modifying Memory System
1. Edit in `src/memory/`
2. Follow the `BaseMemory` interface
3. Ensure backward compatibility with existing sessions

### Changing LLM Behavior
1. Update system prompt in `prompts/default.md`
2. Adjust `max_iterations` in `config.yaml` if needed
3. Test thoroughly before deploying changes

## Notes

- This is an AI coding assistant that runs in the terminal
- It has access to filesystem, shell, git, codebase graph, and MCP tools
- Security is critical - never bypass sandbox checks
- Context windows are limited - optimize usage
