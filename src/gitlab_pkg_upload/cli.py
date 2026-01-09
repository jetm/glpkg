"""CLI entry point for gitlab-pkg-upload.

This module provides the command-line interface for uploading files to GitLab's
Generic Package Registry. It handles argument parsing, validation, and
orchestrates the upload workflow.

Supported flags:
    Required:
        --package-name      Package name in the registry
        --package-version   Package version

    File input (mutually exclusive):
        --files             List of files to upload
        --directory         Directory containing files to upload

    Project specification:
        --project-url       Full GitLab project URL
        --project-path      Project path (namespace/project)
        --gitlab-url        GitLab instance URL (default: https://gitlab.com)
        --token             GitLab API token (or use GITLAB_TOKEN env var)

    Duplicate handling:
        --duplicate-policy  How to handle duplicates: skip, replace, error

    File mapping:
        --file-mapping      Rename files during upload (source:target format)

    Verbosity (mutually exclusive):
        --verbose           Enable verbose output
        --quiet             Suppress non-essential output
        --debug             Enable debug output

    Operational:
        --dry-run           Preview actions without executing
        --fail-fast         Stop on first failure
        --retry             Number of retry attempts
        --json-output       Output results as JSON
        --plain             Force plain text output (no colors)
        --version           Display version number

Usage examples:
    # Upload a single file
    gitlab-pkg-upload --package-name myapp --package-version 1.0.0 --files dist/app.tar.gz

    # Upload multiple files
    gitlab-pkg-upload --package-name myapp --package-version 1.0.0 --files dist/*.tar.gz

    # Upload from directory
    gitlab-pkg-upload --package-name myapp --package-version 1.0.0 --directory dist/

    # With file renaming
    gitlab-pkg-upload --package-name myapp --package-version 1.0.0 \\
        --files local.tar.gz --file-mapping local.tar.gz:remote.tar.gz

    # Dry run with verbose output
    gitlab-pkg-upload --package-name myapp --package-version 1.0.0 --files dist/*.tar.gz \\
        --dry-run --verbose

    # JSON output for CI/CD pipelines
    gitlab-pkg-upload --package-name myapp --package-version 1.0.0 --files dist/*.tar.gz \\
        --json-output
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import argcomplete

from gitlab_pkg_upload.models import DuplicatePolicy
from gitlab_pkg_upload.validators import DEFAULT_GITLAB_URL

if TYPE_CHECKING:
    pass


def create_argument_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser for gitlab-pkg-upload.

    Returns:
        Configured ArgumentParser instance with all supported arguments.
    """
    parser = argparse.ArgumentParser(
        prog="gitlab-pkg-upload",
        description=(
            "Upload files to GitLab's Generic Package Registry.\n\n"
            "This tool uploads one or more files to a GitLab project's package registry, "
            "with support for duplicate detection, retry handling, and various output formats."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Upload a single file
  %(prog)s --package-name myapp --package-version 1.0.0 --files dist/app.tar.gz

  # Upload multiple files
  %(prog)s --package-name myapp --package-version 1.0.0 --files file1.bin file2.bin

  # Upload all files from a directory
  %(prog)s --package-name myapp --package-version 1.0.0 --directory dist/

  # With file renaming (source:target format)
  %(prog)s --package-name myapp --package-version 1.0.0 \\
      --files local.tar.gz --file-mapping local.tar.gz:app-1.0.0.tar.gz

  # Skip duplicates (default behavior)
  %(prog)s --package-name myapp --package-version 1.0.0 --files dist/*.tar.gz \\
      --duplicate-policy skip

  # Replace existing files
  %(prog)s --package-name myapp --package-version 1.0.0 --files dist/*.tar.gz \\
      --duplicate-policy replace

  # Dry run with verbose output
  %(prog)s --package-name myapp --package-version 1.0.0 --files dist/*.tar.gz \\
      --dry-run --verbose

  # JSON output for CI/CD pipelines
  %(prog)s --package-name myapp --package-version 1.0.0 --files dist/*.tar.gz \\
      --json-output --quiet

  # Specify project explicitly
  %(prog)s --package-name myapp --package-version 1.0.0 --files dist/*.tar.gz \\
      --project-url https://gitlab.com/mygroup/myproject

  # Use custom GitLab instance
  %(prog)s --package-name myapp --package-version 1.0.0 --files dist/*.tar.gz \\
      --gitlab-url https://gitlab.example.com --project-path mygroup/myproject

Environment variables:
  GITLAB_TOKEN    GitLab API token (alternative to --token)
""",
    )

    # Required arguments (validated in validate_flags to allow --version to work alone)
    required_group = parser.add_argument_group("required arguments")
    required_group.add_argument(
        "--package-name",
        type=str,
        metavar="NAME",
        help="Package name in the GitLab registry (e.g., 'myapp', 'my-library')",
    )
    required_group.add_argument(
        "--package-version",
        type=str,
        metavar="VERSION",
        help="Package version (e.g., '1.0.0', '2.3.1-beta')",
    )

    # File input arguments (mutual exclusion validated in validate_flags for exit code 3)
    file_input_group = parser.add_argument_group(
        "file input (one required)",
        "Specify files to upload using either --files or --directory",
    )
    file_input_group.add_argument(
        "--files",
        nargs="+",
        type=str,
        metavar="FILE",
        help="List of files to upload (e.g., --files file1.tar.gz file2.tar.gz)",
    )
    file_input_group.add_argument(
        "--directory",
        type=str,
        metavar="DIR",
        help="Directory containing files to upload (uploads all top-level files)",
    )

    # Project specification arguments
    project_group = parser.add_argument_group(
        "project specification",
        "Specify the target GitLab project (auto-detected from Git remote if not provided)",
    )
    project_group.add_argument(
        "--project-url",
        type=str,
        metavar="URL",
        help="Full GitLab project URL (e.g., 'https://gitlab.com/namespace/project')",
    )
    project_group.add_argument(
        "--project-path",
        type=str,
        metavar="PATH",
        help="Project path in namespace/project format (e.g., 'mygroup/myproject')",
    )
    project_group.add_argument(
        "--gitlab-url",
        type=str,
        default=DEFAULT_GITLAB_URL,
        metavar="URL",
        help=f"GitLab instance URL (default: {DEFAULT_GITLAB_URL})",
    )
    project_group.add_argument(
        "--token",
        type=str,
        metavar="TOKEN",
        help="GitLab API token (or set GITLAB_TOKEN environment variable)",
    )

    # Duplicate handling
    parser.add_argument(
        "--duplicate-policy",
        type=str,
        choices=["skip", "replace", "error"],
        default="skip",
        metavar="POLICY",
        help=(
            "How to handle duplicate files: "
            "'skip' (default) - skip uploading, "
            "'replace' - delete existing and upload new, "
            "'error' - fail with error"
        ),
    )

    # File mapping
    parser.add_argument(
        "--file-mapping",
        action="append",
        type=str,
        metavar="SOURCE:TARGET",
        help=(
            "Rename files during upload using source:target format. "
            "Can be specified multiple times (e.g., --file-mapping local.bin:remote.bin). "
            "Only valid with --files, not --directory."
        ),
    )

    # Verbosity flags (mutual exclusion validated in validate_flags for exit code 3)
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

    # Operational flags
    operational_group = parser.add_argument_group("operational options")
    operational_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without executing uploads (shows what would be done)",
    )
    operational_group.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop immediately on first upload failure (default: continue with remaining files)",
    )
    operational_group.add_argument(
        "--retry",
        type=int,
        default=0,
        metavar="N",
        help="Number of retry attempts for failed uploads (default: 0)",
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

    # Version flag - handled early via action="version" to bypass other requirements
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {get_version()}",
        help="Display version number and exit",
    )

    return parser


def validate_flags(args: argparse.Namespace) -> None:
    """Validate flag combinations and detect conflicts.

    Checks for:
    - Required arguments (--package-name and --package-version for upload runs)
    - Conflicting file input (--files and --directory)
    - Conflicting verbosity flags (--verbose, --quiet, --debug)
    - Conflicting project specification (--project-url with --project-path)
    - File input requirement (--files or --directory must be provided)
    - File mapping constraint (--file-mapping only valid with --files)

    Args:
        args: Parsed argument namespace from argparse.

    Raises:
        SystemExit: With exit code 3 (ConfigurationError) if conflicts are detected.
    """
    errors: list[str] = []

    # Check required arguments for upload runs
    if not args.package_name:
        errors.append(
            "--package-name is required. "
            "Specify the package name in the GitLab registry."
        )
    if not args.package_version:
        errors.append(
            "--package-version is required. "
            "Specify the package version."
        )

    # Check for conflicting file input flags
    if args.files and args.directory:
        errors.append(
            "Cannot specify both --files and --directory. "
            "Use --files for explicit file list or --directory to upload all files from a directory."
        )

    # Check for conflicting verbosity flags
    verbosity_flags = []
    if args.verbose:
        verbosity_flags.append("--verbose")
    if args.quiet:
        verbosity_flags.append("--quiet")
    if args.debug:
        verbosity_flags.append("--debug")
    if len(verbosity_flags) > 1:
        errors.append(
            f"Cannot specify multiple verbosity flags: {', '.join(verbosity_flags)}. "
            "Choose one of --verbose, --quiet, or --debug."
        )

    # Check for conflicting project specification
    if args.project_url and args.project_path:
        errors.append(
            "Cannot specify both --project-url and --project-path. "
            "Use --project-url for full URLs or --project-path with --gitlab-url."
        )

    # Check that file input is provided
    if not args.files and not args.directory:
        errors.append(
            "Either --files or --directory must be provided. "
            "Use --files for explicit file list or --directory to upload all files from a directory."
        )

    # Check that file-mapping is only used with --files
    if args.file_mapping and args.directory:
        errors.append(
            "--file-mapping can only be used with --files, not with --directory. "
            "File mappings require explicit file specification."
        )

    # Check retry value is non-negative
    if args.retry < 0:
        errors.append(
            f"--retry must be a non-negative integer, got {args.retry}."
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
            module_path.parent.parent / "pyproject.toml",  # Development layout
            module_path / "pyproject.toml",  # Alternate location
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

            return get_pkg_version("gitlab-pkg-upload")
        except Exception:
            pass

        return "unknown"
    except Exception:
        return "unknown"


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse and validate command-line arguments.

    Creates the argument parser, integrates shell completion with argcomplete,
    parses arguments, and validates flag combinations.

    Args:
        argv: Command-line arguments to parse. If None, uses sys.argv[1:].

    Returns:
        Validated argument namespace.

    Raises:
        SystemExit: If argument parsing fails or flag conflicts are detected.
    """
    parser = create_argument_parser()

    # Enable shell completion via argcomplete
    argcomplete.autocomplete(parser)

    # Parse arguments
    args = parser.parse_args(argv)

    # Validate flag combinations
    validate_flags(args)

    # Convert duplicate_policy string to enum
    args.duplicate_policy = DuplicatePolicy(args.duplicate_policy)

    return args


def main(argv: list[str] | None = None) -> None:
    """Main entry point for the gitlab-pkg-upload CLI.

    Parses command-line arguments, validates configuration, and orchestrates
    the upload workflow.

    Args:
        argv: Command-line arguments. If None, uses sys.argv[1:].
    """
    # Parse arguments
    # Note: --version flag is handled automatically by argparse via action="version"
    args = parse_arguments(argv)

    # TODO: Phase 2 - Project resolution
    # - Auto-detect from Git remote if no project specified
    # - Resolve project ID from URL or path
    # - Validate project accessibility

    # TODO: Phase 3 - Context building
    # - Build UploadConfig from parsed arguments
    # - Create GitLab client connection
    # - Initialize DuplicateDetector
    # - Build UploadContext

    # TODO: Phase 4 - Upload orchestration
    # - Collect files to upload
    # - Execute uploads with retry handling
    # - Format and display results

    # Placeholder: print parsed configuration (for development/testing)
    if args.debug:
        print("Parsed arguments:", file=sys.stderr)
        print(f"  package_name: {args.package_name}", file=sys.stderr)
        print(f"  package_version: {args.package_version}", file=sys.stderr)
        print(f"  files: {args.files}", file=sys.stderr)
        print(f"  directory: {args.directory}", file=sys.stderr)
        print(f"  project_url: {args.project_url}", file=sys.stderr)
        print(f"  project_path: {args.project_path}", file=sys.stderr)
        print(f"  gitlab_url: {args.gitlab_url}", file=sys.stderr)
        print(f"  duplicate_policy: {args.duplicate_policy}", file=sys.stderr)
        print(f"  file_mapping: {args.file_mapping}", file=sys.stderr)
        print(f"  verbose: {args.verbose}", file=sys.stderr)
        print(f"  quiet: {args.quiet}", file=sys.stderr)
        print(f"  debug: {args.debug}", file=sys.stderr)
        print(f"  dry_run: {args.dry_run}", file=sys.stderr)
        print(f"  fail_fast: {args.fail_fast}", file=sys.stderr)
        print(f"  retry: {args.retry}", file=sys.stderr)
        print(f"  json_output: {args.json_output}", file=sys.stderr)
        print(f"  plain: {args.plain}", file=sys.stderr)


if __name__ == "__main__":
    main()
