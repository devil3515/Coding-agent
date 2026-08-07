"""Shell command execution with cwd enforcement."""
import subprocess


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