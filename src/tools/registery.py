import json
from typing import Callable, Any

class ToolRegistry:
    def __init__(self):
        self.tools: dict[str, Callable] = {}
        self.schemas: list[dict] = []

    def register(self, name: str, description: str, parameters: dict, function: Callable):
        """Registers a tool and its OpenAI-compatible schema."""
        self.tools[name] = function
        self.schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters
            }
        })

    def execute(self, tool_name: str, arguments: dict) -> str:
        """Executes a tool by name and returns the output as a string."""
        if tool_name not in self.tools:
            return f"Error: Tool '{tool_name}' not found."

        try:
            result = self.tools[tool_name](**arguments)
            return str(result)
        except Exception as e:
            return f"Error executing tool: {str(e)}"