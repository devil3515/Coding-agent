"""
Skill System for Coding-Agent

SKILLS are pre-defined workflows that tell the agent HOW to approach tasks.

Architecture:
- SkillManager: Loads and manages skill workflows
- Skills: Define steps/tools to follow for specific task types
- Agent: Activates skills and follows their workflow

Example:
- Task: "Fix the bug in api.py"
- Skill: systematic-debugging
- Workflow:
  1. Reproduce bug (ask user for steps)
  2. Check recent changes
  3. Gather evidence
  4. Form hypothesis
  5. Test fix
  6. Verify result
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any, List


class Skill:
    """Represents a single skill with its metadata and content."""
    
    def __init__(self, name: str, description: str, content: str, steps: List[str]):
        self.name = name
        self.description = description
        self.content = content
        self.steps = steps
        self.active = False
        self.current_step = 0
    
    def start(self) -> str:
        """Start the skill and return the first step."""
        self.active = True
        self.current_step = 0
        return f"Starting skill: {self.name}\n\n{self.steps[0] if self.steps else self.content}"
    
    def next_step(self) -> Optional[str]:
        """Move to next step and return it."""
        self.current_step += 1
        if self.current_step < len(self.steps):
            return self.steps[self.current_step]
        return None
    
    def complete(self) -> str:
        """Mark skill as complete."""
        self.active = False
        self.current_step = 0
        return f"Skill '{self.name}' completed."


class SkillManager:
    """Loads and manages skill workflows for the agent."""
    
    def __init__(self, skills_dir: Optional[Path] = None):
        self.skills_dir = skills_dir or Path(__file__).parent.parent.parent / ".kimi" / "skills"
        self.skills: Dict[str, Skill] = {}
        self.active_skill: Optional[Skill] = None
        self._load_skills()
    
    def _load_skills(self):
        """Load all skills from the skills directory."""
        if not self.skills_dir.exists():
            return
        
        for skill_dir in self.skills_dir.iterdir():
            if skill_dir.is_dir():
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    self._parse_skill_file(skill_file, skill_dir.name)
    
    def _parse_skill_file(self, file_path: Path, skill_name: str):
        """Parse a SKILL.md file and extract skill information."""
        content = file_path.read_text(encoding="utf-8")
        
        # Extract metadata from YAML frontmatter
        description = ""
        steps = []
        
        if content.startswith("---"):
            # Find end of frontmatter
            end_idx = content.find("---", 3)
            if end_idx > 0:
                frontmatter = content[3:end_idx].strip()
                for line in frontmatter.split("\n"):
                    if line.startswith("description:"):
                        description = line.split(":", 1)[1].strip().strip('"\'')
        
        # Extract steps from checklist sections
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("1.") or line.startswith("2.") or line.startswith("3."):
                steps.append(line)
        
        skill = Skill(
            name=skill_name,
            description=description or "No description",
            content=content,
            steps=steps if steps else [content]
        )
        self.skills[skill_name] = skill
    
    def get_skill(self, name: str) -> Optional[Skill]:
        """Get a skill by name."""
        return self.skills.get(name)
    
    def activate_skill(self, name: str) -> str:
        """Activate a skill and return its starting instructions."""
        skill = self.get_skill(name)
        if not skill:
            return f"Skill '{name}' not found. Available skills: {list(self.skills.keys())}"
        
        self.active_skill = skill
        return skill.start()
    
    def complete_current_skill(self) -> str:
        """Complete the currently active skill."""
        if not self.active_skill:
            return "No active skill to complete."
        result = self.active_skill.complete()
        self.active_skill = None
        return result
    
    def get_active_skill(self) -> Optional[Skill]:
        """Get the currently active skill."""
        return self.active_skill
    
    def get_all_skills(self) -> List[str]:
        """Get list of all available skill names."""
        return list(self.skills.keys())


def load_skill_manager(working_directory: str) -> SkillManager:
    """Create a SkillManager with the skills directory from the working directory."""
    skills_dir = Path(working_directory) / ".coding-agent" / "skills"
    return SkillManager(skills_dir)
