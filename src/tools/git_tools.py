"""Git command execution with cwd enforcement."""
import subprocess


def run_git(args: str, working_directory: str = None) -> str:
    """Executes a git command.
    
    Args:
        args: Git arguments, e.g. 'status', 'add .', 'commit -m "msg"'
        working_directory: Directory to run git in. If None, uses the
            process's current directory.
    """
    command = f"git {args}"
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=working_directory,
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += f"\n[STDERR]: {result.stderr}"
        if not output.strip():
            return "Git command executed successfully (no output)."
        return output
    except subprocess.TimeoutExpired:
        return "Error: Git command timed out."
    except Exception as e:
        return f"Error running git: {str(e)}"