"""Syntax verification for written files."""
import ast
from pathlib import Path
from typing import Optional, Tuple


class SyntaxChecker:
    """
    Checks file syntax for various languages.
    Currently supports Python. Extensible for JS, TS, etc.
    """

    def check(self, file_path: str) -> Tuple[bool, Optional[str]]:
        """
        Check syntax of a file.
        Returns (is_valid, error_message).
        """
        path = Path(file_path)
        if path.suffix == ".py":
            return self._check_python(path)
        return True, None

    def _check_python(self, path: Path) -> Tuple[bool, Optional[str]]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                source = f.read()
            ast.parse(source)
            return True, None
        except SyntaxError as e:
            return False, f"SyntaxError at line {e.lineno}, col {e.offset}: {e.msg}"
        except Exception as e:
            return False, f"Failed to parse: {str(e)}"