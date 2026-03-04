"""List subcommand for inspecting GitLab Generic Package Registry contents.

Provides two modes for listing package files:
- URL mode: parse a GitLab package page URL to list its files
- Name mode: specify package name and optional version to list files
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from dataclasses import dataclass

from gitlab import Gitlab

from glpkg.models import (
    AuthenticationError,
    ConfigurationError,
    GitLabUploadError,
    ProjectResolutionError,
)

logger = logging.getLogger(__name__)


# Data models for list output


@dataclass
class PackageFileInfo:
    """Represents a file in a GitLab package with metadata."""

    file_name: str
    size: int
    sha256: str | None
    download_url: str
    created_at: str


@dataclass
class PackageListResult:
    """Result of listing files in a package."""

    package_name: str
    version: str
    package_id: int
    project_id: int
    gitlab_url: str
    files: list[PackageFileInfo]


@dataclass
class PackageVersionSummary:
    """Summary of a package version (used when no version is specified)."""

    version: str
    package_id: int
    file_count: int
    created_at: str


# URL parsing


_PACKAGE_URL_PATTERN = re.compile(r"^https?://([^/]+)/(.+?)/-/packages/(\d+)$")


def parse_package_url(url: str) -> tuple[str, str, int]:
    """Parse a GitLab package page URL into components.

    Args:
        url: GitLab package page URL
            (e.g., https://gitlab.com/group/project/-/packages/12345).

    Returns:
        Tuple of (gitlab_url, project_path, package_id).

    Raises:
        ConfigurationError: If the URL does not match the expected pattern.
    """
    match = _PACKAGE_URL_PATTERN.match(url.strip())
    if not match:
        raise ConfigurationError(
            f"Invalid GitLab package URL: '{url}'\n\n"
            "Expected format: https://<gitlab-host>/<project-path>/-/packages/<package-id>\n\n"
            "Examples:\n"
            "  https://gitlab.com/mygroup/myproject/-/packages/12345\n"
            "  https://gitlab.example.com/group/subgroup/project/-/packages/67890"
        )

    host = match.group(1)
    project_path = match.group(2)
    package_id = int(match.group(3))

    gitlab_url = f"https://{host}"
    return gitlab_url, project_path, package_id


# Package file fetching


def _build_download_url(
    gitlab_url: str, project_id: int, package_name: str, version: str, filename: str
) -> str:
    """Build a download URL for a generic package file."""
    return (
        f"{gitlab_url}/api/v4/projects/{project_id}"
        f"/packages/generic/{package_name}/{version}/{filename}"
    )


def fetch_package_files_by_id(gl: Gitlab, project_path: str, package_id: int) -> PackageListResult:
    """Fetch package files using a package ID.

    Args:
        gl: Authenticated GitLab client.
        project_path: GitLab project path (e.g., group/project).
        package_id: Numeric package ID.

    Returns:
        PackageListResult with file metadata and download URLs.

    Raises:
        ProjectResolutionError: If the project or package is not found.
    """
    try:
        project = gl.projects.get(project_path)
    except Exception as e:
        raise ProjectResolutionError(
            f"Project '{project_path}' not found or not accessible.\n\nOriginal error: {e}"
        )

    try:
        package = project.packages.get(package_id)
    except Exception as e:
        raise ProjectResolutionError(
            f"Package ID {package_id} not found in project '{project_path}'.\n\nOriginal error: {e}"
        )

    package_name = package.name
    version = package.version
    gitlab_url = gl.url.replace("/api/v4", "") if "/api/v4" in gl.url else gl.url

    package_files = package.package_files.list(get_all=True)

    files = []
    for pf in package_files:
        download_url = _build_download_url(
            gitlab_url, project.id, package_name, version, pf.file_name
        )
        files.append(
            PackageFileInfo(
                file_name=pf.file_name,
                size=getattr(pf, "size", 0),
                sha256=getattr(pf, "file_sha256", None),
                download_url=download_url,
                created_at=getattr(pf, "created_at", ""),
            )
        )

    return PackageListResult(
        package_name=package_name,
        version=version,
        package_id=package_id,
        project_id=project.id,
        gitlab_url=gitlab_url,
        files=files,
    )


def fetch_package_files_by_name(
    gl: Gitlab,
    project_id: int,
    package_name: str,
    package_version: str | None,
    gitlab_url: str,
) -> PackageListResult | list[PackageVersionSummary]:
    """Fetch package files by name and optional version.

    Args:
        gl: Authenticated GitLab client.
        project_id: Numeric project ID.
        package_name: Package name to search for.
        package_version: Package version (if None, returns version summaries).
        gitlab_url: GitLab instance base URL.

    Returns:
        PackageListResult if version is specified, or list of
        PackageVersionSummary if version is None.

    Raises:
        ProjectResolutionError: If no matching package is found.
    """
    project = gl.projects.get(project_id)
    packages = project.packages.list(package_name=package_name, get_all=True)

    if not packages:
        raise ProjectResolutionError(
            f"No package named '{package_name}' found in project (ID: {project_id})."
        )

    if package_version is None:
        # Return version summaries
        summaries = []
        for pkg in packages:
            pkg_obj = project.packages.get(pkg.id)
            file_count = len(pkg_obj.package_files.list(get_all=True))
            summaries.append(
                PackageVersionSummary(
                    version=pkg.version,
                    package_id=pkg.id,
                    file_count=file_count,
                    created_at=getattr(pkg, "created_at", ""),
                )
            )
        return summaries

    # Find specific version
    target_package = None
    for pkg in packages:
        if pkg.version == package_version:
            target_package = pkg
            break

    if not target_package:
        available = ", ".join(pkg.version for pkg in packages)
        raise ProjectResolutionError(
            f"Package '{package_name}' version '{package_version}' not found.\n\n"
            f"Available versions: {available}"
        )

    package_obj = project.packages.get(target_package.id)
    package_files = package_obj.package_files.list(get_all=True)

    files = []
    for pf in package_files:
        download_url = _build_download_url(
            gitlab_url, project_id, package_name, package_version, pf.file_name
        )
        files.append(
            PackageFileInfo(
                file_name=pf.file_name,
                size=getattr(pf, "size", 0),
                sha256=getattr(pf, "file_sha256", None),
                download_url=download_url,
                created_at=getattr(pf, "created_at", ""),
            )
        )

    return PackageListResult(
        package_name=package_name,
        version=package_version,
        package_id=target_package.id,
        project_id=project_id,
        gitlab_url=gitlab_url,
        files=files,
    )


# Input validation


def validate_list_flags(args: argparse.Namespace) -> None:
    """Validate list-specific flag combinations.

    Args:
        args: Parsed argument namespace from argparse.

    Raises:
        SystemExit: With exit code 3 if validation fails.
    """
    errors: list[str] = []

    has_url = bool(getattr(args, "url", None))
    has_name = bool(getattr(args, "package_name", None))

    if has_url and has_name:
        errors.append(
            "--url and --package-name are mutually exclusive. "
            "Use --url for quick lookups from a GitLab package page URL, "
            "or --package-name for name-based lookups."
        )

    if not has_url and not has_name:
        errors.append(
            "One of --url or --package-name is required.\n\n"
            "Usage:\n"
            "  glpkg list --url https://gitlab.com/group/project/-/packages/12345\n"
            "  glpkg list --package-name my-package --package-version 1.0.0"
        )

    if errors:
        for error in errors:
            print(f"Error: {error}", file=sys.stderr)
        print(
            "\nUse 'glpkg list --help' for usage information.",
            file=sys.stderr,
        )
        sys.exit(3)


# Execute handler


def execute_list(args: argparse.Namespace) -> None:
    """Execute the list subcommand.

    Orchestrates:
    1. Flag validation
    2. Project resolution / URL parsing
    3. GitLab authentication
    4. Package file fetching
    5. Output formatting

    Args:
        args: Parsed argument namespace from argparse.
    """
    from glpkg.cli.upload import (
        ProjectResolver,
        auto_detect_project,
        resolve_project_manually,
    )
    from glpkg.formatters import OutputFormatter
    from glpkg.models import UploadConfig
    from glpkg.validators import get_gitlab_token

    validate_list_flags(args)

    try:
        if args.url:
            # URL mode: parse URL, connect, fetch
            gitlab_url, project_path, package_id = parse_package_url(args.url)

            token = get_gitlab_token(args.token)
            gl = Gitlab(gitlab_url, private_token=token)
            gl.auth()

            logger.info(f"Listing package {package_id} from {project_path}")
            result = fetch_package_files_by_id(gl, project_path, package_id)

        else:
            # Name mode: resolve project, then fetch by name
            if getattr(args, "project_url", None) or getattr(args, "project_path", None):
                resolved_gitlab_url, project_path = resolve_project_manually(
                    project_url=getattr(args, "project_url", None),
                    project_path=getattr(args, "project_path", None),
                    gitlab_url=args.gitlab_url,
                )
            else:
                resolved_gitlab_url, project_path = auto_detect_project()

            token = get_gitlab_token(args.token)
            gl = Gitlab(resolved_gitlab_url, private_token=token)
            gl.auth()

            resolver = ProjectResolver(gl)
            project_id = resolver.resolve_project_id(resolved_gitlab_url, project_path)

            logger.info(
                f"Listing package '{args.package_name}' from {project_path} (ID: {project_id})"
            )
            result = fetch_package_files_by_name(
                gl,
                project_id,
                args.package_name,
                getattr(args, "package_version", None),
                resolved_gitlab_url,
            )

    except AuthenticationError as e:
        logger.error(f"Authentication failed: {e}")
        sys.exit(e.exit_code)
    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(e.exit_code)
    except ProjectResolutionError as e:
        logger.error(f"Package resolution failed: {e}")
        sys.exit(e.exit_code)
    except GitLabUploadError as e:
        logger.error(f"GitLab error: {e}")
        sys.exit(e.exit_code)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)

    # Format output
    config = UploadConfig(
        package_name="",
        version="",
        duplicate_policy=None,  # type: ignore[arg-type]
        retry_count=0,
        verbosity="normal",
        dry_run=False,
        fail_fast=False,
        json_output=getattr(args, "json_output", False),
        plain_output=getattr(args, "plain", False),
        gitlab_url="",
        token=None,
    )
    formatter = OutputFormatter(config)
    formatter.format_list_output(result)
    sys.exit(0)


# Subcommand registration


def register_list_command(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> None:
    """Register the list subcommand with the main argument parser.

    Args:
        subparsers: Subparsers action from the main argument parser.
    """
    list_parser = subparsers.add_parser(
        "list",
        help="List files in a GitLab Generic Package Registry package",
        description=(
            "List files in a GitLab project's generic package registry.\n\n"
            "Supports two input modes:\n"
            "  - URL mode: paste a GitLab package page URL\n"
            "  - Name mode: specify package name and optional version"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # List files from a package URL
  glpkg list --url https://gitlab.com/group/project/-/packages/12345

  # List files by package name and version
  glpkg list --package-name my-package --package-version 1.0.0

  # List all versions of a package
  glpkg list --package-name my-package

  # With explicit project and JSON output
  glpkg --json-output list --package-name my-package --package-version 1.0.0 \\
      --project-path group/project

Environment variables:
  GITLAB_TOKEN    GitLab API token (alternative to --token)
""",
    )

    # URL mode
    url_group = list_parser.add_argument_group(
        "URL mode",
        "List files from a GitLab package page URL",
    )
    url_group.add_argument(
        "--url",
        type=str,
        metavar="URL",
        help="GitLab package page URL (e.g., https://gitlab.com/group/project/-/packages/12345)",
    )

    # Name mode
    name_group = list_parser.add_argument_group(
        "name mode",
        "List files by package name and optional version",
    )
    name_group.add_argument(
        "--package-name",
        type=str,
        metavar="NAME",
        help="Package name in the GitLab registry",
    )
    name_group.add_argument(
        "--package-version",
        type=str,
        metavar="VERSION",
        help="Package version (omit to list all versions)",
    )

    # Project specification (for name mode)
    project_group = list_parser.add_argument_group(
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

    list_parser.set_defaults(func=execute_list)
