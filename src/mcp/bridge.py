import asyncio
import threading
import logging
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession

# MCP tool security configuration
ALLOWED_MCP_TOOLS = set()  # Empty means allow all - configure per deployment
BLOCKED_MCP_TOOLS = {
    "delete", "remove", "rm", "destroy", "drop",
    "exec", "execute", "run", "shell", "bash",
    "sudo", "su",
}
INPUT_MAX_LENGTH = 10000  # Max chars for tool arguments

logger = logging.getLogger(__name__)

def _validate_mcp_tool_call(tool_name: str, arguments: dict) -> tuple[bool, str]:
    """
    Validates an MCP tool call before execution.
    Returns (is_safe, error_message).
    """
    tool_name_lower = tool_name.lower()
    
    # Check if tool is explicitly blocked
    for blocked in BLOCKED_MCP_TOOLS:
        if blocked in tool_name_lower:
            return False, f"⛔ SECURITY ERROR: MCP tool '{tool_name}' is blocked (contains '{blocked}')."
    
    # Check allowlist if configured
    if ALLOWED_MCP_TOOLS and tool_name not in ALLOWED_MCP_TOOLS:
        return False, f"⛔ SECURITY ERROR: MCP tool '{tool_name}' is not in the allowed tools list."
    
    # Validate argument sizes to prevent DoS
    for key, value in arguments.items():
        if isinstance(value, str) and len(value) > INPUT_MAX_LENGTH:
            return False, f"⛔ SECURITY ERROR: Argument '{key}' exceeds maximum length of {INPUT_MAX_LENGTH}."
    
    return True, ""

class MCPBridge:
    """
    Connects to a remote HTTP MCP Server (like Google Stitch) and keeps
    the connection alive in a background thread/event loop.
    """
    def __init__(self, url: str, headers: dict):
        self.url = url
        self.headers = headers
        self.session: ClientSession = None
        self.mcp_tools: list[dict] = []

        self._loop = None
        self._ready = threading.Event()
        self._error = None
        self._stop_event = None
        self._thread = threading.Thread(target=self._run_loop, daemon=True)

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    async def _main(self):
        self._stop_event = asyncio.Event()
        try:
            async with streamablehttp_client(self.url, headers=self.headers) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self.session = session

                    tools_result = await session.list_tools()
                    self.mcp_tools = [
                        {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
                        for t in tools_result.tools
                    ]
                    self._ready.set()

                    # Keep the connection open until told to stop
                    await self._stop_event.wait()
        except Exception as e:
            self._error = e
            self._ready.set()  # unblock connect() so it can raise

    def sync_connect(self, timeout: float = 30.0):
        """Starts the background loop/thread and waits until tools are loaded."""
        self._thread.start()
        if not self._ready.wait(timeout=timeout):
            raise TimeoutError("Timed out connecting to MCP server.")
        if self._error:
            raise self._error

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Sync wrapper: runs the async call on the bridge's own loop."""
        if not self.session or not self._loop:
            return "Error: Not connected."
        
        # Security validation before execution
        is_safe, error_msg = _validate_mcp_tool_call(tool_name, arguments)
        if not is_safe:
            logger.warning(f"Blocked MCP tool call: {tool_name} - {error_msg}")
            return error_msg
        
        try:
            future = asyncio.run_coroutine_threadsafe(
                self.session.call_tool(tool_name, arguments=arguments), self._loop
            )
            result = future.result(timeout=180)
            return "".join(block.text for block in result.content if hasattr(block, "text"))
        except Exception as e:
            return f"Error calling tool '{tool_name}': {str(e)}"

    def sync_disconnect(self):
        if self._loop and self._stop_event:
            self._loop.call_soon_threadsafe(self._stop_event.set)
        self._thread.join(timeout=5)