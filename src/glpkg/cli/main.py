# PYTHON_ARGCOMPLETE_OK
"""Main CLI entry point with subcommand routing for glpkg.

This module provides the command-line interface framework for glpkg,
including global argument parsing, logging configuration, and subcommand
routing via argparse subparsers.

Supported global flags:
    --verbose       Enable verbose output
    --quiet         Suppress non-essential output
    --debug         Enable debug output
    --token         GitLab API token
    --gitlab-url    GitLab instance URL
    --json-output   Output results as JSON
    --plain         Force plain text output (no colors)
    --version       Display version number
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import argcomplete
from rich.console import Console
from rich.logging import RichHandler

# Module-level logger
logger = logging.getLogger(__name__)


def get_version() -> str:
    """Get the package version from pyproject.toml.

    Returns:
        Version string from pyproject.toml, or 'unknown' if not found.
    """
    try:
        # Try to find pyproject.toml relative to this module
        module_path = Path(__file__).parent
        # Check in package location (installed)
        pyproject_paths = [
            module_path.parent.parent.parent / "pyproject.toml",  # Development layout
            module_path.parent / "pyproject.toml",  # Alternate location
        ]

        for pyproject_path in pyproject_paths:
            if pyproject_path.exists():
                content = pyproject_path.read_text()
                # Simple parsing - look for version = "x.y.z"
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith("version") and "=" in line:
                        # Extract version value
                        _, _, value = line.partition("=")
                        value = value.strip().strip('"').strip("'")
                        return value

        # Fallback: try importlib.metadata (for installed packages)
        try:
            from importlib.metadata import version as get_pkg_version

            return get_pkg_version("glpkg")
        except Exception:
            pass

        return "unknown"
    except Exception:
        return "unknown"


def determine_verbosity(args: argparse.Namespace) -> str:
    """Determine verbosity level from parsed arguments.

    Checks verbosity flags in priority order: debug > verbose > quiet > normal.

    Args:
        args: Parsed argument namespace from argparse.

    Returns:
        One of: 'debug', 'verbose', 'quiet', or 'normal'.
    """
    if getattr(args, "debug", False):
        return "debug"
    elif getattr(args, "verbose", False):
        return "verbose"
    elif getattr(args, "quiet", False):
        return "quiet"
    else:
        return "normal"


def setup_logging(args: argparse.Namespace) -> None:
    """Configure logging based on verbosity flags.

    Sets up Python's root logger with RichHandler for enhanced console output.
    When --json-output is enabled, logs go to stderr to keep stdout clean for JSON.

    Args:
        args: Parsed argument namespace containing verbosity flags.
    """
    verbosity = determine_verbosity(args)

    # Determine log level based on verbosity
    log_levels = {
        "debug": logging.DEBUG,
        "verbose": logging.INFO,
        "quiet": logging.WARNING,
        "normal": logging.INFO,
    }
    level = log_levels.get(verbosity, logging.INFO)

    # Use stderr when json_output is enabled to keep stdout clean for JSON
    stream = sys.stderr if getattr(args, "json_output", False) else sys.stdout

    # Configure RichHandler with appropriate settings
    rich_handler = RichHandler(
        console=Console(file=stream),
        show_time=True,
        show_path=False,
        markup=True,
        rich_tracebacks=True,
    )

    # Configure root logger
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[rich_handler],
        force=True,  # Reconfigure if already configured
    )

    stream = "stderr" if getattr(args, "json_output", False) else "stdout"
    logger.debug(f"Logging configured: level={verbosity}, stream={stream}")


def validate_global_flags(args: argparse.Namespace) -> None:
    """Validate global flag combinations and detect conflicts.

    Checks for:
    - Conflicting verbosity flags (--verbose, --quiet, --debug)

    Args:
        args: Parsed argument namespace from argparse.

    Raises:
        SystemExit: With exit code 3 (ConfigurationError) if conflicts are detected.
    """
    errors: list[str] = []

    # Check for conflicting verbosity flags
    verbosity_flags = []
    if getattr(args, "verbose", False):
        verbosity_flags.append("--verbose")
    if getattr(args, "quiet", False):
        verbosity_flags.append("--quiet")
    if getattr(args, "debug", False):
        verbosity_flags.append("--debug")
    if len(verbosity_flags) > 1:
        errors.append(
            f"Cannot specify multiple verbosity flags: {', '.join(verbosity_flags)}. "
            "Choose one of --verbose, --quiet, or --debug."
        )

    # Report all errors
    if errors:
        for error in errors:
            print(f"Error: {error}", file=sys.stderr)
        print(
            "\nUse --help for usage information.",
            file=sys.stderr,
        )
        sys.exit(3)  # ConfigurationError exit code


def create_argument_parser() -> argparse.ArgumentParser:
    """Create and configure the main argument parser with subparsers.

    Returns:
        Configured ArgumentParser instance with subparsers for subcommands.
    """
    from glpkg.validators import DEFAULT_GITLAB_URL

    parser = argparse.ArgumentParser(
        prog="glpkg",
        description=(
            "Upload files to GitLab's Generic Package Registry.\n\n"
            "This tool uploads one or more files to a GitLab project's package registry, "
            "with support for duplicate detection, retry handling, and various output formats."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Upload files to a package
  %(prog)s upload --package-name myapp --package-version 1.0.0 --files dist/app.tar.gz

  # Upload with verbose output
  %(prog)s --verbose upload --package-name myapp --package-version 1.0.0 --files file.bin

  # JSON output for CI/CD pipelines
  %(prog)s --json-output upload --package-name myapp --package-version 1.0.0 --files dist/*.tar.gz

For subcommand help:
  %(prog)s upload --help
""",
    )

    # Global arguments
    global_group = parser.add_argument_group("global options")
    global_group.add_argument(
        "--gitlab-url",
        type=str,
        default=DEFAULT_GITLAB_URL,
        metavar="URL",
        help=f"GitLab instance URL (default: {DEFAULT_GITLAB_URL})",
    )
    global_group.add_argument(
        "--token",
        type=str,
        metavar="TOKEN",
        help="GitLab API token (or set GITLAB_TOKEN environment variable)",
    )

    # Verbosity flags (mutual exclusion validated in validate_global_flags for exit code 3)
    verbosity_group = parser.add_argument_group(
        "verbosity",
        "Control output verbosity (mutually exclusive)",
    )
    verbosity_group.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output with detailed progress information",
    )
    verbosity_group.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress non-essential output (only show errors and final summary)",
    )
    verbosity_group.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output with full diagnostic information",
    )

    # Output format flags
    output_group = parser.add_argument_group("output format")
    output_group.add_argument(
        "--json-output",
        action="store_true",
        help="Output results as JSON (useful for CI/CD pipelines and scripting)",
    )
    output_group.add_argument(
        "--plain",
        action="store_true",
        help="Force plain text output without colors or formatting",
    )

    # Version flag
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {get_version()}",
        help="Display version number and exit",
    )

    # Shell completion installation
    parser.add_argument(
        "--install-completion",
        type=str,
        choices=["bash", "zsh"],
        metavar="SHELL",
        help="Install shell completion for the specified shell (bash or zsh)",
    )

    # Create subparsers
    subparsers = parser.add_subparsers(
        title="commands",
        description="Available subcommands",
        dest="command",
        metavar="<command>",
    )

    # Register subcommands
    from glpkg.cli.upload import register_upload_command

    register_upload_command(subparsers)

    return parser


def main(argv: list[str] | None = None) -> None:
    """Main entry point for the glpkg CLI.

    Parses command-line arguments, validates configuration, and routes
    to the appropriate subcommand handler.

    Args:
        argv: Command-line arguments. If None, uses sys.argv[1:].
    """
    parser = create_argument_parser()

    # Enable shell completion via argcomplete
    argcomplete.autocomplete(parser)

    # Parse arguments
    args = parser.parse_args(argv)

    # Handle --install-completion before checking for subcommand
    if args.install_completion:
        from glpkg.cli.completion import install_completion

        try:
            install_completion(args.install_completion)
            sys.exit(0)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(3)  # ConfigurationError
        except PermissionError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(5)  # FileValidationError
        except OSError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(5)  # FileValidationError

    # If no subcommand is provided, show help and exit
    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # Validate global flag combinations
    validate_global_flags(args)

    # Configure logging based on verbosity flags
    setup_logging(args)

    # Execute the subcommand handler
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
