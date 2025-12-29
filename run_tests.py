#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "python-gitlab>=4.0.0",
#     "requests>=2.25.0",
#     "rich>=10.0.0",
#     "pytest>=7.0.0",
#     "pytest-xdist>=3.0.0",
#     "pytest-timeout>=2.1.0",
#     "pytest-sugar>=0.9.7",
#     "pytest-instafail>=0.5.0",
#     "GitPython>=3.1.0",
# ]
# ///

"""
Test Runner Wrapper for GitLab Upload Script Tests

A standalone uv-compatible Python script that wraps pytest with convenient
command-line options and pass-through support for advanced pytest usage.

Usage Examples:
    Basic (runs all available tests):
        ./run_tests.py

    Convenience commands:
        ./run_tests.py --unit              # Run only unit tests
        ./run_tests.py --integration       # Run integration tests (requires GITLAB_TOKEN)
        ./run_tests.py --config            # Run configuration validation tests
        ./run_tests.py --all               # Run all test categories sequentially

    Individual test execution:
        ./run_tests.py tests/test_unit_basic.py::test_import_gitlab_common

    With pytest options:
        ./run_tests.py -v -k "test_import" tests/
        ./run_tests.py -v --tb=short tests/test_unit_basic.py

    Parallel execution:
        ./run_tests.py -n auto tests/

    Specific markers:
        ./run_tests.py -m "unit and not slow"

    Duration reporting:
        ./run_tests.py --durations=5 tests/       # Show 5 slowest tests
        ./run_tests.py --durations=0 tests/       # Show all test durations
        ./run_tests.py --durations-min=2.0 tests/ # Only show tests >= 2 seconds

Common pytest options:
    -v, --verbose          Verbose output
    -k EXPRESSION          Run tests matching expression
    -m MARKER              Run tests with specific marker
    -x, --exitfirst        Exit on first failure
    --tb=short             Short traceback format
    -n auto                Run tests in parallel (requires pytest-xdist)
    --timeout=SECONDS      Set test timeout
    --durations=N          Show N slowest test durations (0 for all)
    --durations-min=N      Minimum duration in seconds to include in report
    --instafail            Show failures instantly (enabled by default)

Progress Reporting:
    - pytest-sugar provides real-time progress bars during execution
    - pytest-instafail shows failures immediately as they occur
    - --durations flag shows test timing information at the end
    - Performance summary is displayed automatically after test completion
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from rich.console import Console

# Setup rich console for colored output
console = Console()


def format_duration(seconds: float) -> str:
    """
    Format duration in seconds to human-readable format.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted duration string (e.g., "2m 30s", "45s", "1h 5m")
    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


def run_pytest(
    args: list[str],
    env: dict | None = None,
    timeout: int = 900,
    show_duration_context: bool = False,
) -> tuple[int, float]:
    """
    Execute pytest with the given arguments.

    Args:
        args: List of pytest arguments
        env: Optional environment variables to pass to subprocess
        timeout: Timeout in seconds (default: 900)
        show_duration_context: Whether to show duration context message

    Returns:
        Tuple of (exit code from pytest execution, elapsed time in seconds)
    """
    cmd = ["pytest"] + args

    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            env=env or os.environ.copy(),
            timeout=timeout,
        )
        elapsed = time.time() - start_time

        if show_duration_context:
            console.print(f"\n[dim]Elapsed time: {format_duration(elapsed)}[/dim]")

        return result.returncode, elapsed

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        console.print(
            f"[bold red]ERROR:[/bold red] Tests timed out after {timeout} seconds"
        )
        return 1, elapsed
    except Exception as e:
        elapsed = time.time() - start_time
        console.print(f"[bold red]ERROR:[/bold red] Failed to run tests: {e}")
        return 1, elapsed


def run_unit_tests() -> list[str]:
    """
    Build pytest arguments for unit tests.

    Returns:
        List of pytest arguments for unit tests
    """
    return [
        "-m",
        "unit or fast",
        "-v",
        "--tb=auto",
        "--durations=10",
        "--durations-min=1.0",
        "tests/test_unit_basic.py",
    ]


def run_integration_tests(gitlab_token: str) -> tuple[list[str], dict]:
    """
    Build pytest arguments and environment for integration tests.

    Args:
        gitlab_token: GitLab API token

    Returns:
        Tuple of (pytest_args, environment_dict)
    """
    env = os.environ.copy()
    env["GITLAB_TOKEN"] = gitlab_token

    args = [
        "-m",
        "integration",
        "-v",
        "--tb=auto",
        "--durations=0",
        "--durations-min=1.0",
        "tests/",
    ]

    return args, env


def run_configuration_tests() -> int:
    """
    Run configuration validation tests (not pytest-based).

    Returns:
        Exit code from configuration test execution
    """
    console.print("\n[bold]Running configuration tests...[/bold]")
    console.print("=" * 60)

    try:
        result = subprocess.run(
            ["python", "test_parallel_config.py"],
            timeout=60,
        )
        return result.returncode

    except subprocess.TimeoutExpired:
        console.print("[bold red]ERROR:[/bold red] Configuration tests timed out")
        return 1
    except Exception as e:
        console.print(
            f"[bold red]ERROR:[/bold red] Failed to run configuration tests: {e}"
        )
        return 1


def main():
    """Main function to handle argument parsing and test execution."""
    # Check if any convenience flags are used
    convenience_flags = {"--unit", "--integration", "--config", "--all", "--help", "-h"}
    has_convenience_flag = any(arg in convenience_flags for arg in sys.argv[1:])

    if has_convenience_flag:
        # Use argparse for convenience flags
        parser = argparse.ArgumentParser(
            description="Test runner wrapper for GitLab upload script tests",
            epilog="Any additional arguments are passed directly to pytest. "
            "Common pytest options: -v (verbose), -k (filter), -m (markers), "
            "-x (exit on first failure), --tb=short (short traceback), "
            "-n auto (parallel execution)",
        )

        # Convenience command flags (mutually exclusive)
        command_group = parser.add_mutually_exclusive_group()
        command_group.add_argument(
            "--unit",
            action="store_true",
            help="Run only unit tests (fast, no external dependencies)",
        )
        command_group.add_argument(
            "--integration",
            action="store_true",
            help="Run only integration tests (requires GITLAB_TOKEN)",
        )
        command_group.add_argument(
            "--config",
            action="store_true",
            help="Run configuration validation tests",
        )
        command_group.add_argument(
            "--all",
            action="store_true",
            help="Run all test categories sequentially",
        )

        args = parser.parse_args()
        args.pytest_args = []
    else:
        # Pass-through mode: treat all arguments as pytest args
        class Args:
            unit = False
            integration = False
            config = False
            all = False
            pytest_args = sys.argv[1:]

        args = Args()

    # Print header
    console.print("[bold]GitLab Upload Script - Test Suite Runner[/bold]")
    console.print("=" * 60)
    console.print("Using uv for dependency management\n")

    # Change to the gitlab directory
    gitlab_dir = Path(__file__).parent
    os.chdir(gitlab_dir)

    # Get GitLab token from environment
    gitlab_token = os.environ.get("GITLAB_TOKEN")

    # Track results for summary
    results = []
    exit_code = 0

    # Handle convenience commands
    if args.all:
        console.print("[bold]Running all test categories sequentially...[/bold]\n")
        overall_start = time.time()

        # Run unit tests
        console.print("\n[bold cyan]1. Unit Tests[/bold cyan]")
        console.print("=" * 60)
        unit_args = run_unit_tests()
        unit_result, unit_time = run_pytest(
            unit_args, timeout=120, show_duration_context=True
        )
        results.append(("Unit Tests", unit_result == 0, unit_time))

        # Run configuration tests
        console.print("\n[bold cyan]2. Configuration Tests[/bold cyan]")
        console.print("=" * 60)
        config_start = time.time()
        config_result = run_configuration_tests()
        config_time = time.time() - config_start
        results.append(("Configuration Tests", config_result == 0, config_time))

        # Run integration tests if token available
        if gitlab_token:
            console.print("\n[bold cyan]3. Integration Tests[/bold cyan]")
            console.print("=" * 60)
            console.print(
                "[dim]This may take 10-15 minutes due to GitLab API operations...[/dim]\n"
            )
            integration_args, integration_env = run_integration_tests(gitlab_token)
            integration_result, integration_time = run_pytest(
                integration_args,
                env=integration_env,
                timeout=900,
                show_duration_context=True,
            )
            results.append(
                ("Integration Tests", integration_result == 0, integration_time)
            )
        else:
            console.print(
                "\n[bold yellow]⚠ Skipping integration tests (no GITLAB_TOKEN)[/bold yellow]"
            )
            results.append(("Integration Tests", None, 0))

        overall_time = time.time() - overall_start

        # Determine overall exit code
        exit_code = 0 if all(r[1] for r in results if r[1] is not None) else 1

    elif args.unit:
        console.print("[bold]Running unit tests (no external dependencies)...[/bold]")
        console.print("=" * 60 + "\n")
        unit_args = run_unit_tests()
        exit_code, _ = run_pytest(unit_args, timeout=120, show_duration_context=True)

    elif args.integration:
        if not gitlab_token:
            console.print(
                "[bold red]ERROR:[/bold red] GITLAB_TOKEN environment variable not set"
            )
            console.print("\nTo run integration tests:")
            console.print("  export GITLAB_TOKEN=your_token")
            console.print("  ./run_tests.py --integration")
            return 1

        console.print(
            "[bold]Running integration tests (requires GitLab API access)...[/bold]"
        )
        console.print("=" * 60)
        console.print(
            "[dim]This may take 10-15 minutes due to GitLab API operations...[/dim]\n"
        )
        integration_args, integration_env = run_integration_tests(gitlab_token)
        exit_code, _ = run_pytest(
            integration_args,
            env=integration_env,
            timeout=900,
            show_duration_context=True,
        )

    elif args.config:
        exit_code = run_configuration_tests()

    elif args.pytest_args:
        # Pass-through mode: run pytest with provided arguments
        console.print("[bold]Running pytest with custom arguments...[/bold]")
        console.print(f"Arguments: {' '.join(args.pytest_args)}")
        console.print("=" * 60 + "\n")

        # Add duration flags if not already present
        enhanced_args = args.pytest_args.copy()
        if not any(arg.startswith("--durations") for arg in enhanced_args):
            enhanced_args.extend(["--durations=10", "--durations-min=1.0"])

        exit_code, _ = run_pytest(enhanced_args, show_duration_context=True)

    else:
        # Default behavior: run all available tests based on token presence
        if gitlab_token:
            console.print("[bold]Running all tests (unit + integration)...[/bold]")
            console.print("=" * 60)
            console.print(
                "[dim]This may take 10-15 minutes due to GitLab API operations...[/dim]\n"
            )
            env = os.environ.copy()
            env["GITLAB_TOKEN"] = gitlab_token
            exit_code, _ = run_pytest(
                ["-v", "--tb=short", "--durations=10", "--durations-min=1.0", "tests/"],
                env=env,
                timeout=900,
                show_duration_context=True,
            )
        else:
            console.print(
                "[bold]Running all available tests (unit tests only, no GITLAB_TOKEN)...[/bold]"
            )
            console.print("=" * 60 + "\n")
            exit_code, _ = run_pytest(
                [
                    "-v",
                    "--tb=short",
                    "--durations=10",
                    "--durations-min=1.0",
                    "tests/test_unit_basic.py",
                ],
                timeout=180,
                show_duration_context=True,
            )

    # Print summary
    console.print("\n" + "=" * 60)
    console.print("[bold]TEST SUMMARY[/bold]")
    console.print("=" * 60)

    if args.all:
        # Detailed summary for --all mode
        for test_name, success, duration in results:
            duration_str = format_duration(duration) if duration > 0 else "N/A"
            if success is None:
                console.print(
                    f"[yellow]⚠[/yellow] {test_name}: Skipped ({duration_str})"
                )
            elif success:
                console.print(f"[green]✅[/green] {test_name}: Passed ({duration_str})")
            else:
                console.print(f"[red]❌[/red] {test_name}: Failed ({duration_str})")

        console.print(
            f"\n[dim]Total elapsed time: {format_duration(overall_time)}[/dim]"
        )

        if exit_code == 0:
            console.print("[bold green]✅ All tests passed![/bold green]")
        else:
            console.print("[bold red]❌ Some tests failed![/bold red]")

    else:
        if exit_code == 0:
            console.print("[bold green]✅ All tests passed![/bold green]")

            # Show helpful hints
            if not gitlab_token and not args.integration:
                console.print(
                    "\n[dim]Note: Integration tests were skipped (no GITLAB_TOKEN)[/dim]"
                )
                console.print("[dim]To run integration tests:[/dim]")
                console.print("[dim]  export GITLAB_TOKEN=your_token[/dim]")
                console.print("[dim]  ./run_tests.py --integration[/dim]")

            # Show usage hints
            if not args.pytest_args:
                console.print("\n[dim]Tip: Run with -v for verbose output[/dim]")
                console.print("[dim]Tip: Use -n auto for parallel execution[/dim]")
                console.print(
                    "[dim]Tip: Run ./run_tests.py --help for more options[/dim]"
                )

        else:
            console.print("[bold red]❌ Some tests failed![/bold red]")
            console.print("\n[dim]Tip: Run with -v for more details[/dim]")
            console.print("[dim]Tip: Use -x to stop on first failure[/dim]")
            console.print("[dim]Tip: Use --tb=short for shorter tracebacks[/dim]")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
