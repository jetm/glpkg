#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "python-gitlab>=4.0.0",
#     "rich>=13.0.0",
# ]
# ///

"""
GitLab Generic Package Upload Script

A standalone uv-compatible Python script that uploads files to GitLab's generic package registry
with SHA256 checksum validation, retry logic, and rich progress output.
"""

import argparse
import hashlib
import logging
import os
import sys
import time
from pathlib import Path

from gitlab.exceptions import GitlabAuthenticationError
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from gitlab import Gitlab

# Constants
PROJECT_ID = 75761996
DEFAULT_GITLAB_URL = "https://gitlab.com"
MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]  # Exponential backoff in seconds

# Setup rich console and logging
console = Console()
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(console=console, rich_tracebacks=True)],
)
logger = logging.getLogger(__name__)


def get_gitlab_token(cli_token: str | None) -> str:
    """
    Get GitLab token from environment variable or CLI argument.

    Priority:
    1. GITLAB_TOKEN environment variable
    2. CLI argument (--token)

    Args:
        cli_token: Token provided via CLI argument

    Returns:
        GitLab authentication token

    Raises:
        ValueError: If no token is provided
    """
    token = os.environ.get("GITLAB_TOKEN")
    if token:
        logger.info("Using GitLab token from GITLAB_TOKEN environment variable")
        return token

    if cli_token:
        logger.info("Using GitLab token from CLI argument")
        return cli_token

    raise ValueError(
        "No GitLab token provided. Set GITLAB_TOKEN environment variable or use --token argument"
    )


def calculate_sha256(file_path: Path) -> str:
    """
    Calculate SHA256 checksum of a file.

    Args:
        file_path: Path to the file

    Returns:
        Hexadecimal SHA256 digest string
    """
    sha256_hash = hashlib.sha256()

    with open(file_path, "rb") as f:
        # Read in chunks for memory efficiency
        for chunk in iter(lambda: f.read(8192), b""):
            sha256_hash.update(chunk)

    checksum = sha256_hash.hexdigest()
    logger.info(f"Calculated SHA256 checksum: {checksum}")
    return checksum


def upload_file_with_retry(
    gl: Gitlab,
    project_id: int,
    file_path: Path,
    package_name: str,
    version: str,
    target_filename: str,
    max_retries: int = MAX_RETRIES,
) -> bool:
    """
    Upload file to GitLab generic package registry with retry logic.

    Args:
        gl: Authenticated GitLab client
        project_id: GitLab project ID
        file_path: Path to file to upload
        package_name: Package name in registry
        version: Package version
        target_filename: Target filename in registry
        max_retries: Maximum number of retry attempts

    Returns:
        True if upload succeeded, False otherwise
    """
    project = gl.projects.get(project_id)

    for attempt in range(max_retries):
        try:
            logger.info(
                f"Upload attempt {attempt + 1}/{max_retries} for {target_filename}"
            )

            # Create progress bar
            with Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
                console=console,
            ) as progress:
                task = progress.add_task(
                    f"Uploading {target_filename}", total=file_path.stat().st_size
                )

                # Upload file to generic packages
                project.generic_packages.upload(
                    package_name=package_name,
                    package_version=version,
                    file_name=target_filename,
                    path=file_path.as_posix(),
                )

                progress.update(task, completed=file_path.stat().st_size)

            logger.info(f"Upload successful: {target_filename}")
            return True

        except Exception as e:
            logger.error(f"Upload attempt {attempt + 1} failed: {e}")

            if attempt < max_retries - 1:
                delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                logger.info(f"Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                logger.error(f"All {max_retries} upload attempts failed")
                return False

    return False


def validate_upload(
    gl: Gitlab,
    project_id: int,
    package_name: str,
    version: str,
    filename: str,
    expected_sha256: str,
) -> bool:
    """
    Validate uploaded file by comparing checksums.

    Args:
        gl: Authenticated GitLab client
        project_id: GitLab project ID
        package_name: Package name in registry
        version: Package version
        filename: Filename in registry
        expected_sha256: Expected SHA256 checksum

    Returns:
        True if validation succeeded, False otherwise
    """
    try:
        project = gl.projects.get(project_id)

        # Get package files
        packages = project.packages.list(package_name=package_name, get_all=True)

        for package in packages:
            if package.version == version:
                # Get package files
                package_obj = project.packages.get(package.id)
                package_files = package_obj.package_files.list(get_all=True)

                for pkg_file in package_files:
                    if pkg_file.file_name == filename:
                        # Check if SHA256 is available in the response
                        remote_sha256 = getattr(pkg_file, "file_sha256", None)

                        if remote_sha256:
                            if remote_sha256.lower() == expected_sha256.lower():
                                logger.info(
                                    f"Checksum validation successful: {expected_sha256}"
                                )
                                return True
                            else:
                                logger.error(
                                    f"Checksum mismatch! Local: {expected_sha256}, "
                                    f"Remote: {remote_sha256}"
                                )
                                return False
                        else:
                            logger.warning(
                                "Remote checksum not available in API response, "
                                "skipping validation"
                            )
                            return True

        logger.warning(
            f"Could not find uploaded file {filename} in package {package_name} "
            f"version {version}"
        )
        return False

    except Exception as e:
        logger.warning(f"Checksum validation failed: {e}")
        return False


def main() -> None:
    """Main function to handle argument parsing and orchestrate the upload process."""
    parser = argparse.ArgumentParser(
        description="Upload files to GitLab generic package registry with checksum validation"
    )
    parser.add_argument("file_path", type=str, help="Path to file to upload")
    parser.add_argument("package_name", type=str, help="Package name in registry")
    parser.add_argument("version", type=str, help="Package version")
    parser.add_argument(
        "--target-filename",
        type=str,
        default=None,
        help="Target filename in registry (defaults to basename of file_path)",
    )
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="GitLab private token (overridden by GITLAB_TOKEN env var)",
    )
    parser.add_argument(
        "--gitlab-url",
        type=str,
        default=DEFAULT_GITLAB_URL,
        help=f"GitLab instance URL (default: {DEFAULT_GITLAB_URL})",
    )

    args = parser.parse_args()

    # Validate file exists
    file_path = Path(args.file_path)
    if not file_path.exists():
        logger.error(f"File not found: {file_path}")
        sys.exit(1)

    # Determine target filename
    target_filename = args.target_filename or file_path.name

    logger.info(f"Starting upload process for {file_path}")
    logger.info(f"Package: {args.package_name}, Version: {args.version}")
    logger.info(f"Target filename: {target_filename}")

    try:
        # Get authentication token
        token = get_gitlab_token(args.token)

        # Calculate local file checksum
        logger.info("Calculating local file checksum...")
        local_checksum = calculate_sha256(file_path)

        # Initialize GitLab client
        logger.info(f"Connecting to GitLab at {args.gitlab_url}")
        gl = Gitlab(args.gitlab_url, private_token=token)
        gl.auth()
        logger.info("Authentication successful")

        # Fetch project details to get human-readable path
        project = gl.projects.get(PROJECT_ID)
        project_path = project.path_with_namespace
        logger.debug(f"Project path: {project_path}")

        # Upload file with retry logic
        logger.info(f"Uploading to project {project_path}")
        upload_success = upload_file_with_retry(
            gl=gl,
            project_id=PROJECT_ID,
            file_path=file_path,
            package_name=args.package_name,
            version=args.version,
            target_filename=target_filename,
        )

        if not upload_success:
            logger.error("Upload failed after all retry attempts")
            sys.exit(1)

        # Validate upload
        logger.info("Validating upload...")
        validation_success = validate_upload(
            gl=gl,
            project_id=PROJECT_ID,
            package_name=args.package_name,
            version=args.version,
            filename=target_filename,
            expected_sha256=local_checksum,
        )

        if not validation_success:
            logger.error("Upload validation failed")
            sys.exit(1)

        # Construct download URL
        download_url = (
            f"{args.gitlab_url}/api/v4/projects/{PROJECT_ID}/packages/generic/"
            f"{args.package_name}/{args.version}/{target_filename}"
        )

        # Print download URL
        console.print(f"[bold cyan]Download URL:[/bold cyan] {download_url}")

        console.print(
            f"[bold green]✓[/bold green] Successfully uploaded {target_filename} "
            f"to {args.package_name} v{args.version}"
        )
        sys.exit(0)

    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)
    except GitlabAuthenticationError as e:
        logger.error(f"GitLab authentication failed: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
