"""Shell command execution with cwd enforcement."""
import subprocess
import asyncio


def run_shell_command(command: str, working_directory: str = None) -> str:
    """Run a shell command and return the output.

    Args:
        command: The bash command to run.
        working_directory: Directory to run the command in. If None, uses
            the process's current directory.
    """
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
        if not output:
            return "Command executed successfully but no output was returned."
        return output

    except subprocess.TimeoutExpired:
        return "Command timed out after 30 seconds."
    except Exception as e:
        return f"Error executing command: {e}"


async def run_shell_command_async(command: str, working_directory: str = None) -> str:
    """Run a shell command asynchronously and return the output."""
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
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            return "Command timed out after 30 seconds."

        output = ""
        if stdout:
            output += stdout.decode("utf-8", errors="replace")
        if stderr:
            output += f"[STDERR]: {stderr.decode('utf-8', errors='replace')}"
        if not output:
            return "Command executed successfully but no output was returned."
        return output

    except Exception as e:
        return f"Error executing command: {e}"