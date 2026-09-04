"""Syntax verification for written files."""
import ast
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple


class SyntaxChecker:
    """
    Per-file syntax check. Dispatches by file extension:

    - .py  → ast.parse (built-in, always available)
    - .rs  → rustc --emit=metadata to /dev/null (parse + name-resolve, no codegen)
    - .js  → node --check
    - .ts  → tsc --noEmit (uses project tsconfig if found, else single-file)
    - .go  → gofmt -l (parse is implicit; non-empty stdout = parse failure)

    Anything else (markdown, toml, json, gitignore, …) returns (True, None).

    Each language checker is best-effort: if the toolchain binary is missing on
    PATH, we skip rather than fail the run. The agent's job is to *try* to
    verify, not to refuse to operate in environments where the toolchain
    isn't installed. Surface toolchain-missing as (True, None); surface a real
    parse failure as (False, stderr).
    """

    def check(self, file_path: str) -> Tuple[bool, Optional[str]]:
        """Return (is_valid, error_message)."""
        path = Path(file_path)
        suffix = path.suffix.lower()

        if not path.exists():
            return False, f"File not found: {file_path}"

        if suffix == ".py":
            return self._check_python(path)
        if suffix == ".rs":
            return self._check_rust(path)
        if suffix == ".js":
            return self._check_js(path)
        if suffix == ".ts":
            return self._check_ts(path)
        if suffix == ".go":
            return self._check_go(path)

        # markdown, toml, json, yaml, gitignore, … — no syntax check.
        return True, None

    # -- Python ---------------------------------------------------------------
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

    # -- Rust -----------------------------------------------------------------
    def _check_rust(self, path: Path) -> Tuple[bool, Optional[str]]:
        """Parse-check a single .rs file with no manifest required.
        `rustc --emit=metadata -o /dev/null` runs only the parser + name
        resolver; no codegen, no linking. Fast and dependency-free."""
        rustc = shutil.which("rustc")
        if rustc is None:
            return True, None  # toolchain missing — don't block the agent

        try:
            proc = subprocess.run(
                [rustc, "--edition=2021", "--crate-type=lib",
                 "--emit=metadata", "-o", "/dev/null", str(path)],
                capture_output=True, text=True, timeout=20.0,
            )
        except subprocess.TimeoutExpired:
            return False, "rustc timed out after 20s"
        except Exception as e:
            return False, f"rustc invocation failed: {e}"

        if proc.returncode == 0:
            return True, None
        err = (proc.stderr or "").strip()
        return False, (err or "rustc returned non-zero")[-2000:]

    # -- JavaScript -----------------------------------------------------------
    def _check_js(self, path: Path) -> Tuple[bool, Optional[str]]:
        node = shutil.which("node")
        if node is None:
            return True, None
        try:
            proc = subprocess.run(
                [node, "--check", str(path)],
                capture_output=True, text=True, timeout=15.0,
            )
        except subprocess.TimeoutExpired:
            return False, "node --check timed out after 15s"
        except Exception as e:
            return False, f"node --check failed: {e}"
        if proc.returncode == 0:
            return True, None
        err = (proc.stderr or proc.stdout or "").strip()
        return False, (err or "node --check returned non-zero")[-2000:]

    # -- TypeScript -----------------------------------------------------------
    def _check_ts(self, path: Path) -> Tuple[bool, Optional[str]]:
        """TypeScript parse. Uses project tsconfig if found, else single-file.
        If tsc isn't on PATH at all, skip."""
        tsc = shutil.which("tsc")
        if tsc is None:
            return True, None
        tsconfig_dir = None
        for parent in [path.parent, *path.parents]:
            if (parent / "tsconfig.json").exists():
                tsconfig_dir = str(parent)
                break
        try:
            if tsconfig_dir:
                proc = subprocess.run(
                    [tsc, "--noEmit", "-p", tsconfig_dir],
                    capture_output=True, text=True, timeout=60.0,
                )
            else:
                proc = subprocess.run(
                    [tsc, "--noEmit", "--target", "esnext", "--skipLibCheck",
                     "--allowJs", str(path)],
                    capture_output=True, text=True, timeout=60.0,
                )
        except subprocess.TimeoutExpired:
            return False, "tsc --noEmit timed out after 60s"
        except Exception as e:
            return False, f"tsc invocation failed: {e}"
        if proc.returncode == 0:
            return True, None
        err = (proc.stderr or proc.stdout or "").strip()
        return False, (err or "tsc returned non-zero")[-2000:]

    # -- Go -------------------------------------------------------------------
    def _check_go(self, path: Path) -> Tuple[bool, Optional[str]]:
        """`gofmt -l <file>` prints the filename if it's not parseable Go.
        Empty stdout = parses cleanly."""
        gofmt = shutil.which("gofmt")
        if gofmt is None:
            return True, None
        try:
            proc = subprocess.run(
                [gofmt, "-l", str(path)],
                capture_output=True, text=True, timeout=10.0,
            )
        except subprocess.TimeoutExpired:
            return False, "gofmt timed out after 10s"
        except Exception as e:
            return False, f"gofmt failed: {e}"
        if proc.returncode != 0:
            err = (proc.stderr or "").strip()
            return False, (err or "gofmt returned non-zero")[-2000:]
        if proc.stdout.strip():
            return False, f"gofmt parse failure: {proc.stdout.strip()[:2000]}"
        return True, None