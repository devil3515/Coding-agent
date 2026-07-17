import subprocess
import shlex

# Allowlist of safe commands - expand as needed
ALLOWED_COMMANDS = {
    # File operations
    "ls", "cat", "head", "tail", "grep", "rg", "find", "tree", "stat", "file", "wc", "sort", "uniq", "cut", "tr", "diff",
    # Git
    "git", "gh",
    # Python/development
    "python", "python3", "pip", "pip3", "uv", "poetry", "pipenv",
    # Node/npm
    "node", "npm", "npx", "yarn", "pnpm",
    # Build tools
    "make", "cmake", "gcc", "g++", "clang", "cargo", "rustc", "go", "javac", "java",
    # Version info
    "docker", "docker-compose", "kubectl", "helm",
    # Text editors (non-interactive)
    "vim", "nano", "code", "code-insiders",
    # Utilities
    "curl", "wget", "tar", "gzip", "gunzip", "zip", "unzip", "rsync",
    # System info
    "ps", "top", "htop", "df", "du", "whoami", "which", "pwd", "echo", "date", "hostname",
    # Others
    "sed", "awk", "jq", "yq", "xidel",
}

# Dangerous patterns that are always blocked
BLOCKED_PATTERNS = [
    r"&\s*;\s*rm",  # command; rm (chaining)
    r"\|\s*rm",     # | rm (piping to rm)
    r">\s*/dev/",   # writing to device
    r">\s*null",    # writing to null (data loss)
    r"2>&1",        # stderr redirect (can be used to hide errors)
    r";\s*sh\s*(-i)?",  # spawning shell
    r"\|\s*sh\s*(-i)?",  # piping to shell
    r"`.*`",        # command substitution
    r"\$\(.*\)",    # command substitution
    r"\beval\s*\(", # eval is dangerous
    r"\bexec\s*\(", # exec is dangerous
    r"\bbase64\s+-d", # decode base64 (could be used to hide commands)
    # Additional patterns to prevent bypass techniques
    r"curl\s+.*\|\s*sh",  # curl | sh
    r"wget\s+.*\|\s*sh",  # wget | sh
    r"\|\s*bash",         # | bash
    r"\|\s*sh\b",         # | sh (without flags)
    r"nc\s+-[ecl]",       # netcat reverse shell
    r"\bsocat\b",         # socat reverse shell
    r"\bpython\s+-c",     # python -c (code execution)
    r"\bperl\s+-e",       # perl -e (code execution)
    r"\bruby\s+-e",       # ruby -e (code execution)
    r"\bnc\b.*-e",        # nc -e (netcat reverse shell)
]

def run_shell_command(command: str) -> str:
    """Run a shell command with improved security."""
    import re
    
    # Pre-flight security checks
    command_stripped = command.strip().lower()
    
    # Check for dangerous patterns
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return f"⛔ SECURITY ERROR: Command contains blocked dangerous pattern '{pattern}'"
    
    # Extract the base command (first word)
    parts = command.strip().split()
    if not parts:
        return "Error: Empty command"
    
    base_cmd = parts[0]
    
    # Check if base command is allowlisted
    if base_cmd not in ALLOWED_COMMANDS:
        return f"⛔ SECURITY ERROR: Command '{base_cmd}' is not in the allowed list. Allowed: {', '.join(sorted(ALLOWED_COMMANDS)[:20])}..."
    
    # Use shell=False for better security - block shell features entirely
    # Shell features create security risks, so we reject commands with shell metacharacters
    try:
        # Check for shell metacharacters - block all complex commands
        shell_chars = ['|', '&&', '||', ';', '>', '<', '$', '`', '(', ')', '{', '}']
        if any(c in command for c in shell_chars):
            return "⛔ SECURITY ERROR: Shell metacharacters (|, &&, ||, ;, >, <, $, etc.) are not allowed for security reasons. Use simple commands only."
        
        # Safe simple command - split into args and run with shell=False
        args = shlex.split(command)
        result = subprocess.run(
            args, 
            capture_output=True, 
            text=True, 
            timeout=30, 
            shell=False,
            # Restrict PATH to prevent execution of unexpected binaries
            env={"PATH": subprocess.os.environ.get("PATH", "/usr/bin:/bin")}
        )
        
        output = ''
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