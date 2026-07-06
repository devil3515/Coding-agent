# import asyncio
# from mcp.client.sse import sse_client
# from mcp import ClientSession
# from typing import Any

# class MCPBridge:
#     """
#     Connects to a remote HTTP MCP Server (like Google Stitch).
#     """
#     def __init__(self, url: str, headers: dict):
#         self.url = url
#         self.headers = headers
#         self.session: ClientSession = None
#         self.mcp_tools: list[dict] = []

#     async def connect(self):
#         """Connects to the remote HTTP MCP server."""
#         # Use sse_client for remote HTTP streams
#         async with sse_client(self.url, headers=self.headers) as (read, write):
#             self.session = ClientSession(read, write)
#             await self.session.initialize()

#             # Fetch tools
#             tools_result = await self.session.list_tools()
#             self.mcp_tools = [
#                 {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
#                 for t in tools_result.tools
#             ]

#     async def call_tool(self, tool_name: str, arguments: dict) -> str:
#         """Sends a tool call to the remote server."""
#         if not self.session:
#             return "Error: Not connected."

#         try:
#             result = await self.session.call_tool(tool_name, arguments=arguments)
#             # Stitch returns unstructured JSON blocks
#             return "".join(block.text for block in result.content if hasattr(block, 'text'))
#         except Exception as e:
#             return f"Error calling tool '{tool_name}': {str(e)}"

#     def sync_connect(self):
#         asyncio.run(self.connect())

#     def sync_disconnect(self):
#         pass # SSE connections close automatically when the context manager exits




import asyncio
import threading
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession

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