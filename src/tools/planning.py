def _normalise_steps(steps: list) -> list[dict]:
    """
    Accepts steps as either plain strings or dicts with 'step' and optional 'files'.
    Always returns a list of dicts: {title: str, files: list[str], status: str}
    """
    normalised = []
    for s in steps:
        if isinstance(s, str):
            normalised.append({"title": s, "files": [], "status": "pending"})
        elif isinstance(s, dict):
            normalised.append({
                "title": s.get("step", s.get("title", "Unnamed step")),
                "files": s.get("files", []),
                "status": "pending",
            })
        else:
            normalised.append({"title": str(s), "files": [], "status": "pending"})
    return normalised


def create_project_plan(steps: list) -> list[dict]:
    """
    Creates a structured, step-by-step plan for a complex multi-file task.
    Each step can be a plain string OR a dict: {"step": "...", "files": ["path/a.py", ...]}.
    Returns the normalised plan list (stored by the Agent, not this function).
    """
    if not steps:
        return []
    return _normalise_steps(steps)


def update_project_plan(step_number: int, status: str) -> str:
    """
    Stub — the real update happens inside Agent.chat().
    Status must be 'completed', 'in_progress', or 'failed'.
    """
    valid = ['completed', 'in_progress', 'failed']
    if status not in valid:
        return f"Error: Invalid status '{status}'. Must be one of: {', '.join(valid)}"
    return f"Step {step_number} marked as {status}."


def ask_user_question(question: str, question_type: str = "text", options: list[str] = None) -> str:
    """
    Pauses execution and asks the user a clarifying question.
    The Agent intercepts this call — this return value is never used.
    """
    return f"Waiting for user input: {question}"


def update_plan_text(step_number: int, new_text: str) -> str:
    """
    Renames a step's description mid-task.
    The Agent intercepts this call — this return value is never used.
    """
    return f"Step {step_number} text updated to: {new_text}."
