"""Git command execution with cwd enforcement."""
import subprocess
import asyncio

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


async def run_git_async(args: str, working_directory: str = None) -> str:
    """Executes a git command asynchronously."""
    command = f"git {args}"
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_directory,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return "Error: Git command timed out."

        output = ""
        if stdout:
            output += stdout.decode("utf-8", errors="replace")
        if stderr:
            output += f"[STDERR]: {stderr.decode('utf-8', errors='replace')}"
        if not output.strip():
            return "Git command executed successfully (no output)."
        return output
    except Exception as e:
        return f"Error running git: {str(e)}"