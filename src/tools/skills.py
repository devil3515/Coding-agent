"""
Skill Tools for Coding-Agent

Tools that allow the agent to invoke and follow skill workflows.
"""

import json
from src.core.skill_core import load_skill_manager


def activate_skill(working_directory: str, skill_name: str) -> str:
    """Activate a skill to follow its workflow for a specific task type.
    
    Args:
        working_directory: The project's working directory
        skill_name: Name of the skill to activate (e.g., 'brainstorming', 'systematic-debugging')
    
    Returns:
        Instructions for the first step of the skill workflow
    """
    skill_manager = load_skill_manager(working_directory)
    return skill_manager.activate_skill(skill_name)


def complete_skill(working_directory: str) -> str:
    """Mark the currently active skill as complete and return to normal workflow.
    
    Args:
        working_directory: The project's working directory
    
    Returns:
        Confirmation that the skill was completed
    """
    skill_manager = load_skill_manager(working_directory)
    return skill_manager.complete_current_skill()


def list_skills(working_directory: str) -> str:
    """List all available skills in the project.
    
    Args:
        working_directory: The project's working directory
    
    Returns:
        JSON string with list of available skill names and descriptions
    """
    skill_manager = load_skill_manager(working_directory)
    skills = skill_manager.get_all_skills()
    return json.dumps({"skills": skills})


def get_active_skill(working_directory: str) -> str:
    """Get the currently active skill (if any).
    
    Args:
        working_directory: The project's working directory
    
    Returns:
        Name of active skill or None
    """
    skill_manager = load_skill_manager(working_directory)
    active = skill_manager.get_active_skill()
    if active:
        return json.dumps({"active_skill": active.name, "description": active.description})
    return json.dumps({"active_skill": None})


# Tool registration dictionary for cli.py
SKILL_TOOLS = {
    "activate_skill": {
        "description": "Activate a skill to follow its workflow. Use 'brainstorming' for new features, 'systematic-debugging' for bugs, 'writing-plans' for multi-step tasks. Call this FIRST when the task type matches.",
        "parameters": {
            "type": "object",
            "properties": {
                "working_directory": {"type": "string", "description": "Project working directory"},
                "skill_name": {"type": "string", "enum": ["brainstorming", "systematic-debugging", "writing-plans"], "description": "Skill to activate"}
            },
            "required": ["working_directory", "skill_name"]
        },
        "function": activate_skill
    },
    "complete_skill": {
        "description": "Mark the currently active skill as complete. Call this AFTER completing all steps in the skill workflow.",
        "parameters": {
            "type": "object",
            "properties": {
                "working_directory": {"type": "string", "description": "Project working directory"}
            },
            "required": ["working_directory"]
        },
        "function": complete_skill
    },
    "list_skills": {
        "description": "List all available skills in the project.",
        "parameters": {
            "type": "object",
            "properties": {
                "working_directory": {"type": "string", "description": "Project working directory"}
            },
            "required": ["working_directory"]
        },
        "function": list_skills
    },
    "get_active_skill": {
        "description": "Get the currently active skill (if any).",
        "parameters": {
            "type": "object",
            "properties": {
                "working_directory": {"type": "string", "description": "Project working directory"}
            },
            "required": ["working_directory"]
        },
        "function": get_active_skill
    }
}
