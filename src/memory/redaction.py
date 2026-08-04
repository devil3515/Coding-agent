"""Secret redaction module for memory persistence."""

import re
from typing import Any, Dict, List, Union


# Patterns for common secret formats
SECRET_PATTERNS = [
    # OpenAI-style API keys: sk-...
    (r"sk-[a-zA-Z0-9]{20,}", "[REDACTED_API_KEY]"),
    # AWS Access Key IDs
    (r"AKIA[0-9A-Z]{16}", "[REDACTED_AWS_KEY]"),
    (r"ASIA[0-9A-Z]{16}", "[REDACTED_AWS_TEMP_KEY]"),
    # GitHub tokens
    (r"ghp_[a-zA-Z0-9]{36}", "[REDACTED_GITHUB_TOKEN]"),
    (r"gho_[a-zA-Z0-9]{36}", "[REDACTED_GITHUB_OAUTH]"),
    (r"github_pat_[a-zA-Z0-9]{22}_[a-zA-Z0-9]{59}", "[REDACTED_GITHUB_PAT]"),
    # Bearer tokens
    (r"Bearer\s+[a-zA-Z0-9\-_\.]+", "Bearer [REDACTED_TOKEN]"),
    # Private keys
    (r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----", "[REDACTED_PRIVATE_KEY_HEADER]"),
    (r"-----BEGIN\s+OPENSSH\s+PRIVATE\s+KEY-----", "[REDACTED_SSH_KEY_HEADER]"),
    (r"-----END\s+(?:RSA\s+)?PRIVATE\s+KEY-----", "[REDACTED_PRIVATE_KEY_FOOTER]"),
    (r"-----END\s+OPENSSH\s+PRIVATE\s+KEY-----", "[REDACTED_SSH_KEY_FOOTER]"),
    # Connection strings with passwords
    (
        r"(mongodb(?:\+srv)?://[^:]+):([^@]+)@",
        r"\1:[REDACTED_PASSWORD]@",
    ),
    (
        r"(postgres(?:ql)?://[^:]+):([^@]+)@",
        r"\1:[REDACTED_PASSWORD]@",
    ),
    (
        r"(mysql://[^:]+):([^@]+)@",
        r"\1:[REDACTED_PASSWORD]@",
    ),
    (
        r"(redis://[^:]+):([^@]+)@",
        r"\1:[REDACTED_PASSWORD]@",
    ),
    # Generic key/value assignments for secrets
    (r"(?i)(api_key|apikey)\s*=\s*[\"']?[^\"'\s]+[\"']?", r"\1=[REDACTED_API_KEY]"),
    (r"(?i)(token)\s*=\s*[\"']?[^\"'\s]+[\"']?", r"\1=[REDACTED_TOKEN]"),
    (r"(?i)(secret)\s*=\s*[\"']?[^\"'\s]+[\"']?", r"\1=[REDACTED_SECRET]"),
    (r"(?i)(password|passwd)\s*=\s*[\"']?[^\"'\s]+[\"']?", r"\1=[REDACTED_PASSWORD]"),
    (r"(?i)(authorization)\s*=\s*[\"']?[^\"'\s]+[\"']?", r"\1=[REDACTED_AUTH]"),
]

# Compile patterns for efficiency
COMPILED_PATTERNS = [(re.compile(pattern), replacement) for pattern, replacement in SECRET_PATTERNS]


def redact_text(text: str) -> str:
    """
    Redact sensitive information from a text string.

    Args:
        text: The input text that may contain secrets.

    Returns:
        The text with secrets replaced by placeholders.
    """
    if not text:
        return text

    result = text
    for pattern, replacement in COMPILED_PATTERNS:
        result = pattern.sub(replacement, result)

    return result


def redact_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively redact sensitive information from a dictionary.

    Args:
        data: The input dictionary that may contain secrets.

    Returns:
        A new dictionary with secrets replaced by placeholders.
    """
    if not data:
        return data

    result = {}
    for key, value in data.items():
        if isinstance(value, str):
            result[key] = redact_text(value)
        elif isinstance(value, dict):
            result[key] = redact_dict(value)
        elif isinstance(value, list):
            result[key] = redact_list(value)
        else:
            result[key] = value

    return result


def redact_list(items: List[Any]) -> List[Any]:
    """
    Recursively redact sensitive information from a list.

    Args:
        items: The input list that may contain secrets.

    Returns:
        A new list with secrets replaced by placeholders.
    """
    if not items:
        return items

    result = []
    for item in items:
        if isinstance(item, str):
            result.append(redact_text(item))
        elif isinstance(item, dict):
            result.append(redact_dict(item))
        elif isinstance(item, list):
            result.append(redact_list(item))
        else:
            result.append(item)

    return result


def redact_value(value: Any) -> Any:
    """
    Redact sensitive information from any value.

    Args:
        value: The input value that may contain secrets.

    Returns:
        The value with secrets replaced by placeholders.
    """
    if isinstance(value, str):
        return redact_text(value)
    elif isinstance(value, dict):
        return redact_dict(value)
    elif isinstance(value, list):
        return redact_list(value)
    else:
        return value
