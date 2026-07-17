import subprocess
import shlex

# Blocked git commands that could be dangerous
BLOCKED_GIT_COMMANDS = [
    "rm",
    "del",
    "filter-branch",
    "filter-branch",
    "rev-list",
    "update-ref",
]

def run_git(args: str) -> str:
    """
    Executes a git command securely.
    Examples of 'args': 'status', 'add .', 'commit -m "my message"', 'diff', 'log --oneline -5'
    """
    # Validate args - prevent shell injection
    if not args or not isinstance(args, str):
        return "Error: Invalid git arguments."

    # Check for dangerous patterns in args
    args_lower = args.lower().strip()
    for blocked in BLOCKED_GIT_COMMANDS:
        if args_lower.startswith(blocked) or f" {blocked}" in args_lower:
            return f"Error: Git command '{blocked}' is blocked for security."

    # Use shlex.split for safer argument parsing (doesn't handle all shell features but safer than shell=True)
    try:
        # Build command as list - first element is 'git', rest are parsed args
        cmd_parts = shlex.split(args)
        cmd = ["git"] + cmd_parts
    except ValueError as e:
        return f"Error: Invalid git arguments syntax: {str(e)}"

    try:
        result = subprocess.run(
            cmd,
            shell=False,
            capture_output=True,
            text=True,
            timeout=30,
            # Restrict environment to basic variables
            env={"PATH": subprocess.os.environ.get("PATH", "/usr/bin:/bin")}
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += f"\n[STDERR]: {result.stderr}"
        if result.returncode != 0 and not output.strip():
            return f"Git command failed with exit code {result.returncode}"
        if not output.strip():
            return "Git command executed successfully (no output)."
        return output
    except subprocess.TimeoutExpired:
        return "Error: Git command timed out."
    except Exception as e:
        return f"Error running git: {str(e)}"