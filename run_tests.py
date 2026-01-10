#!/usr/bin/env python3
"""
Test Runner Wrapper for GitLab Upload Script Tests

A convenience wrapper that delegates to `uv run pytest` for test execution.
All test dependencies are automatically managed by uv.

Usage Examples:
    Basic (runs all available tests):
        ./run_tests.py
        # or directly: uv run pytest tests/

    Convenience commands:
        ./run_tests.py --unit              # Run only unit tests
        ./run_tests.py --integration       # Run integration tests (requires GITLAB_TOKEN)
        ./run_tests.py --all               # Run all test categories sequentially

    Individual test execution:
        ./run_tests.py tests/unit/test_cli.py::test_parse_args
        # or directly: uv run pytest tests/unit/test_cli.py::test_parse_args

    With pytest options:
        ./run_tests.py -v -k "test_import" tests/
        ./run_tests.py -v --tb=short tests/unit/

    Parallel execution:
        ./run_tests.py -n auto tests/
        # or directly: uv run pytest tests/ -n auto

    Specific markers:
        ./run_tests.py -m "unit and not slow"

    Duration reporting:
        ./run_tests.py --durations=5 tests/       # Show 5 slowest tests
        ./run_tests.py --durations=0 tests/       # Show all test durations

Common pytest options:
    -v, --verbose          Verbose output
    -k EXPRESSION          Run tests matching expression
    -m MARKER              Run tests with specific marker
    -x, --exitfirst        Exit on first failure
    --tb=short             Short traceback format
    -n auto                Run tests in parallel (requires pytest-xdist)
    --timeout=SECONDS      Set test timeout
    --durations=N          Show N slowest test durations (0 for all)
    --instafail            Show failures instantly (enabled by default)

Note:
    You can also run tests directly with `uv run pytest`:
        uv run pytest tests/              # All tests
        uv run pytest tests/unit/         # Unit tests only
        uv run pytest tests/integration/  # Integration tests only
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


def format_duration(seconds: float) -> str:
    """Format duration in seconds to human-readable format."""
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


def ensure_package_installed() -> bool:
    """
    Ensure the glpkg package is installed in development mode.

    Returns:
        True if package is available (already installed or successfully installed),
        False if installation failed.
    """
    try:
        import glpkg  # noqa: F401

        return True
    except ImportError:
        pass

    print("Installing glpkg package in development mode...")
    try:
        result = subprocess.run(
            ["uv", "pip", "install", "-e", "."],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            print(f"ERROR: Failed to install package: {result.stderr}")
            return False
        print("Package installed successfully.\n")
        return True
    except subprocess.TimeoutExpired:
        print("ERROR: Package installation timed out")
        return False
    except Exception as e:
        print(f"ERROR: Failed to install package: {e}")
        return False


def run_uv_pytest(
    args: list[str],
    env: dict | None = None,
    timeout: int = 900,
) -> tuple[int, float]:
    """
    Execute pytest via uv run with the given arguments.

    Args:
        args: List of pytest arguments
        env: Optional environment variables to pass to subprocess
        timeout: Timeout in seconds (default: 900)

    Returns:
        Tuple of (exit code, elapsed time in seconds)
    """
    cmd = ["uv", "run", "pytest"] + args

    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            env=env or os.environ.copy(),
            timeout=timeout,
        )
        elapsed = time.time() - start_time
        return result.returncode, elapsed

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        print(f"ERROR: Tests timed out after {timeout} seconds")
        return 1, elapsed
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"ERROR: Failed to run tests: {e}")
        return 1, elapsed


def main():
    """Main function to handle argument parsing and test execution."""
    # Check if any convenience flags are used
    convenience_flags = {"--unit", "--integration", "--all", "--help", "-h"}
    has_convenience_flag = any(arg in convenience_flags for arg in sys.argv[1:])

    if has_convenience_flag:
        # Use argparse for convenience flags
        parser = argparse.ArgumentParser(
            description="Test runner wrapper for GitLab upload script tests. "
            "Delegates to `uv run pytest` for execution.",
            epilog="Any additional arguments are passed directly to pytest. "
            "You can also run tests directly with `uv run pytest tests/`.",
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
            all = False
            pytest_args = sys.argv[1:]

        args = Args()

    # Print header
    print("GitLab Package Upload - Test Suite Runner")
    print("=" * 60)
    print("Using uv run pytest for test execution\n")

    # Change to the project directory
    project_dir = Path(__file__).parent
    os.chdir(project_dir)

    # Ensure the package is installed before running tests
    if not ensure_package_installed():
        print("\nFailed to install the glpkg package.")
        print("Please install it manually with: uv pip install -e .")
        return 1

    # Get GitLab token from environment
    gitlab_token = os.environ.get("GITLAB_TOKEN")

    # Track results for summary
    results = []
    exit_code = 0

    # Handle convenience commands
    if args.all:
        print("Running all test categories sequentially...\n")
        overall_start = time.time()

        # Run unit tests
        print("\n1. Unit Tests")
        print("=" * 60)
        unit_args = [
            "-v",
            "--tb=auto",
            "--durations=10",
            "--durations-min=1.0",
            "tests/unit/",
        ]
        unit_result, unit_time = run_uv_pytest(unit_args, timeout=120)
        results.append(("Unit Tests", unit_result == 0, unit_time))

        # Run integration tests if token available
        if gitlab_token:
            print("\n2. Integration Tests")
            print("=" * 60)
            print("This may take several minutes due to GitLab API operations...\n")
            env = os.environ.copy()
            env["GITLAB_TOKEN"] = gitlab_token
            integration_args = [
                "-m",
                "integration",
                "-v",
                "--tb=auto",
                "--durations=0",
                "--durations-min=1.0",
                "tests/integration/",
            ]
            integration_result, integration_time = run_uv_pytest(
                integration_args,
                env=env,
                timeout=900,
            )
            results.append(
                ("Integration Tests", integration_result == 0, integration_time)
            )
        else:
            print("\nSkipping integration tests (no GITLAB_TOKEN)")
            results.append(("Integration Tests", None, 0))

        overall_time = time.time() - overall_start

        # Determine overall exit code
        exit_code = 0 if all(r[1] for r in results if r[1] is not None) else 1

    elif args.unit:
        print("Running unit tests (no external dependencies)...")
        print("=" * 60 + "\n")
        unit_args = [
            "-v",
            "--tb=auto",
            "--durations=10",
            "--durations-min=1.0",
            "tests/unit/",
        ]
        exit_code, _ = run_uv_pytest(unit_args, timeout=120)

    elif args.integration:
        if not gitlab_token:
            print("ERROR: GITLAB_TOKEN environment variable not set")
            print("\nTo run integration tests:")
            print("  export GITLAB_TOKEN=your_token")
            print("  ./run_tests.py --integration")
            print("\nOr run directly with uv:")
            print("  GITLAB_TOKEN=your_token uv run pytest tests/integration/ -m integration")
            return 1

        print("Running integration tests (requires GitLab API access)...")
        print("=" * 60)
        print("This may take several minutes due to GitLab API operations...\n")
        env = os.environ.copy()
        env["GITLAB_TOKEN"] = gitlab_token
        integration_args = [
            "-m",
            "integration",
            "-v",
            "--tb=auto",
            "--durations=0",
            "--durations-min=1.0",
            "tests/integration/",
        ]
        exit_code, _ = run_uv_pytest(
            integration_args,
            env=env,
            timeout=900,
        )

    elif args.pytest_args:
        # Pass-through mode: run pytest with provided arguments
        print("Running pytest with custom arguments...")
        print(f"Arguments: {' '.join(args.pytest_args)}")
        print("=" * 60 + "\n")

        # Add duration flags if not already present
        enhanced_args = args.pytest_args.copy()
        if not any(arg.startswith("--durations") for arg in enhanced_args):
            enhanced_args.extend(["--durations=10", "--durations-min=1.0"])

        exit_code, _ = run_uv_pytest(enhanced_args)

    else:
        # Default behavior: run all available tests based on token presence
        if gitlab_token:
            print("Running all tests (unit + integration)...")
            print("=" * 60)
            print("This may take several minutes due to GitLab API operations...\n")
            env = os.environ.copy()
            env["GITLAB_TOKEN"] = gitlab_token
            exit_code, _ = run_uv_pytest(
                ["-v", "--tb=short", "--durations=10", "--durations-min=1.0", "tests/"],
                env=env,
                timeout=900,
            )
        else:
            print("Running unit tests only (no GITLAB_TOKEN set)...")
            print("=" * 60 + "\n")
            exit_code, _ = run_uv_pytest(
                [
                    "-v",
                    "--tb=short",
                    "--durations=10",
                    "--durations-min=1.0",
                    "tests/unit/",
                ],
                timeout=180,
            )

    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    if args.all:
        # Detailed summary for --all mode
        for test_name, success, duration in results:
            duration_str = format_duration(duration) if duration > 0 else "N/A"
            if success is None:
                print(f"  {test_name}: Skipped ({duration_str})")
            elif success:
                print(f"  {test_name}: Passed ({duration_str})")
            else:
                print(f"  {test_name}: Failed ({duration_str})")

        print(f"\nTotal elapsed time: {format_duration(overall_time)}")

        if exit_code == 0:
            print("\nAll tests passed!")
        else:
            print("\nSome tests failed!")

    else:
        if exit_code == 0:
            print("All tests passed!")

            # Show helpful hints
            if not gitlab_token and not args.integration:
                print("\nNote: Integration tests were skipped (no GITLAB_TOKEN)")
                print("To run integration tests:")
                print("  export GITLAB_TOKEN=your_token")
                print("  uv run pytest tests/integration/ -m integration")

        else:
            print("Some tests failed!")
            print("\nTip: Run with -v for more details")
            print("Tip: Use -x to stop on first failure")
            print("Tip: Use --tb=short for shorter tracebacks")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
