"""Test execution for modified files."""
import asyncio
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class TestResult:
    passed: bool
    stdout: str
    stderr: str
    returncode: int
    command: str
    files_tested: List[str]


class TestRunner:
    """
    Detects and runs tests for modified source files.
    Uses heuristics to map src files to test files.
    """

    def __init__(self, working_directory: str = "."):
        self.working_directory = Path(working_directory).resolve()

    def find_test_files(self, modified_file: str) -> List[str]:
        """
        Find test files likely related to the modified source file.
        Returns list of relative paths from working_directory.
        """
        path = Path(modified_file)
        name = path.stem
        dir_parts = path.parent.parts

        candidates = []

        patterns = [
            "tests/test_{name}.py",
            "tests/{dir}/test_{name}.py",
            "test_{name}.py",
            "tests/{name}_test.py",
        ]

        for pattern in patterns:
            formatted = pattern.format(
                name=name, dir="/".join(dir_parts) if dir_parts else ""
            )
            candidate = self.working_directory / formatted
            if candidate.exists():
                rel = str(candidate.relative_to(self.working_directory))
                if rel not in candidates:
                    candidates.append(rel)

        test_dirs = [
            self.working_directory / "tests",
            self.working_directory / "test",
        ]
        for test_dir in test_dirs:
            if not test_dir.exists():
                continue
            # ponytail: O(N) scan of all test files per lookup, reading each one.
            # Fine for small/medium projects. Upgrade: build a name->test index once.
            for test_file in test_dir.rglob("*.py"):
                if test_file.name.startswith("test_") or test_file.name.endswith("_test.py"):
                    try:
                        content = test_file.read_text(encoding="utf-8")
                        if name in content:
                            rel = str(test_file.relative_to(self.working_directory))
                            if rel not in candidates:
                                candidates.append(rel)
                    except Exception:
                        continue

        return candidates

    async def run_tests(
        self,
        test_files: Optional[List[str]] = None,
        target_file: Optional[str] = None,
        timeout: float = 120.0,
    ) -> TestResult:
        """
        Run pytest. If target_file is given, try to find and run only related tests.
        If test_files is given, run those specifically.
        Otherwise run full discovery.
        """
        cmd = [sys.executable, "-m", "pytest", "-v", "--tb=short", "--color=no"]
        files_tested: List[str] = []

        if test_files:
            cmd.extend(test_files)
            files_tested = test_files
        elif target_file:
            related = self.find_test_files(target_file)
            if related:
                cmd.extend(related)
                files_tested = related
            else:
                cmd.append(str(self.working_directory))
        else:
            cmd.append(str(self.working_directory))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.working_directory),
            )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)

            stdout = stdout_b.decode("utf-8", errors="replace")
            stderr = stderr_b.decode("utf-8", errors="replace")

            return TestResult(
                passed=proc.returncode == 0,
                stdout=stdout,
                stderr=stderr,
                returncode=proc.returncode,
                command=" ".join(cmd),
                files_tested=files_tested,
            )

        except asyncio.TimeoutError:
            return TestResult(
                passed=False,
                stdout="",
                stderr=f"Test execution timed out after {timeout}s",
                returncode=-1,
                command=" ".join(cmd),
                files_tested=files_tested,
            )
        except Exception as e:
            return TestResult(
                passed=False,
                stdout="",
                stderr=str(e),
                returncode=-1,
                command=" ".join(cmd),
                files_tested=files_tested,
            )

    async def run_full_suite(self, timeout: float = 180.0) -> TestResult:
        """Run the entire test suite."""
        return await self.run_tests(timeout=timeout)