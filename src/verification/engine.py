"""Verification engine for Phase 2 self-verification."""
from dataclasses import dataclass, field
from typing import List, Optional

from src.verification.syntax_checker import SyntaxChecker
from src.verification.test_runner import TestRunner


@dataclass
class VerificationReport:
    """Structured result of a file verification."""
    file_path: str
    read_back: str
    syntax_ok: bool
    syntax_error: Optional[str]
    tests_run: bool
    test_result: Optional[dict]
    overall_pass: bool
    details: List[str] = field(default_factory=list)


class VerificationEngine:
    """
    Phase 2 Self-Verification Engine.

    After every write_file or apply_diff:
    1. Read back the file
    2. Check syntax
    3. Run related tests
    4. Format results for LLM context injection
    """

    def __init__(self, registry, working_directory: str = ".", console=None):
        self.registry = registry
        self.working_directory = working_directory
        self.console = console
        self.syntax_checker = SyntaxChecker()
        self.test_runner = TestRunner(working_directory)

    async def verify_file(self, file_path: str, run_tests: bool = True) -> VerificationReport:
        """Run full verification on a single file."""
        if self.console:
            self.console.print(f"[dim]🔍 Verifying {file_path}...[/dim]")

        read_result = await self.registry.aexecute("read_file", {"file_path": file_path})

        syntax_ok, syntax_error = self.syntax_checker.check(file_path)

        test_result = None
        tests_run = False
        if run_tests and syntax_ok:
            if self.console:
                self.console.print(f"[dim]🧪 Running tests for {file_path}...[/dim]")
            tr = await self.test_runner.run_tests(target_file=file_path)
            tests_run = True
            test_result = {
                "passed": tr.passed,
                "stdout": tr.stdout[:3000],
                "stderr": tr.stderr[:1500],
                "command": tr.command,
                "files_tested": tr.files_tested,
            }

        overall_pass = syntax_ok and (not tests_run or test_result["passed"])

        details = []
        if not syntax_ok:
            details.append(f"Syntax error: {syntax_error}")
        if tests_run and not test_result["passed"]:
            fail_summary = test_result["stderr"][:200] if test_result["stderr"] else "See stdout"
            details.append(f"Tests failed: {fail_summary}")

        return VerificationReport(
            file_path=file_path,
            read_back=read_result[:800],
            syntax_ok=syntax_ok,
            syntax_error=syntax_error,
            tests_run=tests_run,
            test_result=test_result,
            overall_pass=overall_pass,
            details=details,
        )

    async def verify_all_pending(self, file_paths: List[str]) -> List[VerificationReport]:
        """Verify multiple files sequentially."""
        reports = []
        for fp in file_paths:
            report = await self.verify_file(fp)
            reports.append(report)
        return reports

    async def run_full_verification(self) -> List[VerificationReport]:
        """Run full test suite verification (used in VERIFYING phase)."""
        if self.console:
            self.console.print("[dim]🧪 Running full test suite...[/dim]")
        tr = await self.test_runner.run_full_suite()

        report = VerificationReport(
            file_path="[FULL SUITE]",
            read_back="",
            syntax_ok=True,
            syntax_error=None,
            tests_run=True,
            test_result={
                "passed": tr.passed,
                "stdout": tr.stdout[:4000],
                "stderr": tr.stderr[:2000],
                "command": tr.command,
                "files_tested": tr.files_tested,
            },
            overall_pass=tr.passed,
            details=[] if tr.passed else ["Full test suite failed"],
        )
        return [report]

    def format_report_for_llm(self, report: VerificationReport) -> str:
        """Format a verification report for injection into LLM context."""
        lines = [
            f"\n{'='*60}",
            f"[VERIFICATION REPORT: {report.file_path}]",
            f"{'='*60}",
            f"• Syntax Check: {'✅ PASS' if report.syntax_ok else '❌ FAIL'}",
        ]
        if report.syntax_error:
            lines.append(f"• Syntax Error: {report.syntax_error}")

        if report.tests_run:
            passed = report.test_result["passed"]
            cmd = report.test_result["command"]
            lines.append(f"• Tests: {'✅ PASS' if passed else '❌ FAIL'}")
            lines.append(f"  Command: {cmd}")
            if report.test_result.get("files_tested"):
                files = ", ".join(report.test_result["files_tested"])
                lines.append(f"  Test Files: {files}")
            if not passed:
                stderr = report.test_result.get("stderr", "")
                if stderr:
                    lines.append(f"  Test Errors:\n{stderr[:800]}")
                stdout = report.test_result.get("stdout", "")
                if stdout and not stderr:
                    lines.append(f"  Test Output:\n{stdout[:800]}")

        if report.details:
            issues = "; ".join(report.details)
            lines.append(f"• Issues: {issues}")

        overall = "✅ VERIFIED" if report.overall_pass else "❌ FAILED — Please fix before proceeding."
        lines.append(f"• Overall: {overall}")
        lines.append(f"{'='*60}\n")
        return "\n".join(lines)

    def format_reports_for_llm(self, reports: List[VerificationReport]) -> str:
        """Format multiple reports."""
        return "\n".join(self.format_report_for_llm(r) for r in reports)