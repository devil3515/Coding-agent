import subprocess

def run_git(args: str) -> str:
    """
    Executes a git command.
    Examples of 'args': 'status', 'add .', 'commit -m "my message"', 'diff', 'log --oneline -5'
    """
    command = f"git {args}"
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30
        )
        output = ""
        if result.stdout: output += result.stdout
        if result.stderr: output += f"\n[STDERR]: {result.stderr}"
        if not output.strip(): return "Git command executed successfully (no output)."
        return output
    except subprocess.TimeoutExpired:
        return "Error: Git command timed out."
    except Exception as e:
        return f"Error running git: {str(e)}"