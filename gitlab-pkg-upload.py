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

A standalone uv-compatible Python script that uploads single or multiple files to GitLab's
generic package registry with SHA256 checksum validation, retry logic, and rich progress output.
Supports uploading multiple files from explicit file lists or directories.
Features copy-paste friendly URL output to avoid terminal truncation.
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
from rich.status import Status

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


def collect_files_to_upload(args: argparse.Namespace) -> list[tuple[Path, str]]:
    """
    Collect files to upload based on input mode (--files or --directory).

    Args:
        args: Parsed command-line arguments

    Returns:
        List of tuples containing (source_path, target_filename)

    Raises:
        ValueError: If file paths are invalid or file mappings are malformed
        FileNotFoundError: If specified files or directory don't exist
    """
    files_to_upload: list[tuple[Path, str]] = []

    if args.files:
        # Parse file mappings if provided
        file_mappings: dict[str, str] = {}
        if args.file_mapping:
            for mapping in args.file_mapping:
                if mapping.count(":") != 1:
                    raise ValueError(
                        f"Invalid file mapping format '{mapping}'. "
                        "Expected format: 'local.bin:remote.bin'"
                    )
                local_name, remote_name = mapping.split(":", 1)
                file_mappings[local_name] = remote_name

        # Validate that file mappings reference files in the --files list
        if file_mappings:
            files_set = {Path(f).name for f in args.files}
            for local_name in file_mappings.keys():
                if local_name not in files_set:
                    raise ValueError(
                        f"File mapping references '{local_name}' which is not in --files list"
                    )

        # Process each file
        for file_path_str in args.files:
            source_path = Path(file_path_str)
            if not source_path.exists():
                raise FileNotFoundError(f"File not found: {source_path}")
            if not source_path.is_file():
                raise ValueError(f"Path is not a file: {source_path}")

            # Apply mapping if exists, otherwise use original filename
            target_filename = file_mappings.get(source_path.name, source_path.name)
            files_to_upload.append((source_path, target_filename))

    elif args.directory:
        directory_path = Path(args.directory)
        if not directory_path.exists():
            raise FileNotFoundError(f"Directory not found: {directory_path}")
        if not directory_path.is_dir():
            raise ValueError(f"Path is not a directory: {directory_path}")

        # Collect only top-level files (not subdirectories)
        for item in directory_path.iterdir():
            if item.is_file():
                files_to_upload.append((item, item.name))

        if not files_to_upload:
            logger.warning(f"No files found in directory: {directory_path}")

    # Check for duplicate target filenames
    target_filenames = [target for _, target in files_to_upload]
    duplicates = [name for name in target_filenames if target_filenames.count(name) > 1]
    if duplicates:
        unique_duplicates = list(set(duplicates))
        raise ValueError(
            f"Duplicate target filenames detected: {', '.join(unique_duplicates)}"
        )

    return files_to_upload


def delete_existing_files(
    gl: Gitlab,
    project_id: int,
    package_name: str,
    version: str,
    filename: str,
) -> int:
    """
    Delete existing files with the same name from the package.

    This enables replacing files in the registry rather than creating duplicates.

    Args:
        gl: Authenticated GitLab client
        project_id: GitLab project ID
        package_name: Package name in registry
        version: Package version
        filename: Filename to delete

    Returns:
        Number of files deleted
    """
    deleted_count = 0

    try:
        project = gl.projects.get(project_id)
        packages = project.packages.list(package_name=package_name, get_all=True)

        target_package = next((p for p in packages if p.version == version), None)

        if not target_package:
            logger.debug(
                f"Package {package_name} v{version} not found, nothing to delete"
            )
            return 0

        # Get package files
        package_obj = project.packages.get(target_package.id)
        package_files = package_obj.package_files.list(get_all=True)

        # Find all files matching the target filename
        matching_files = [f for f in package_files if f.file_name == filename]

        if not matching_files:
            logger.debug(f"No existing files named {filename} found")
            return 0

        # Delete all matching files
        for file_obj in matching_files:
            try:
                logger.info(f"Deleting existing file: {filename} (ID: {file_obj.id})")
                file_obj.delete()
                deleted_count += 1
            except Exception as e:
                logger.warning(
                    f"Failed to delete file {filename} (ID: {file_obj.id}): {e}"
                )

        if deleted_count > 0:
            logger.info(f"Deleted {deleted_count} existing file(s) named {filename}")

    except Exception as e:
        logger.warning(f"Error checking for existing files: {e}")

    return deleted_count


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

            # Use spinner with elapsed time since GitLab API doesn't provide upload progress
            file_size_mb = file_path.stat().st_size / (1024 * 1024)
            start_time = time.time()

            with Status(
                f"[bold blue]Uploading {target_filename} ({file_size_mb:.2f} MB)...[/bold blue]",
                console=console,
                spinner="dots",
            ):
                # Upload file to generic packages
                project.generic_packages.upload(
                    package_name=package_name,
                    package_version=version,
                    file_name=target_filename,
                    path=file_path.as_posix(),
                )

            elapsed = time.time() - start_time
            speed_mbps = file_size_mb / elapsed if elapsed > 0 else 0
            console.print(
                f"[green]✓[/green] Uploaded {target_filename} "
                f"({file_size_mb:.2f} MB in {elapsed:.1f}s, {speed_mbps:.2f} MB/s)"
            )

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


def process_single_file(
    gl: Gitlab,
    project_id: int,
    source_path: Path,
    target_filename: str,
    package_name: str,
    version: str,
    gitlab_url: str,
) -> tuple[bool, str]:
    """
    Process upload and validation for a single file.

    Args:
        gl: Authenticated GitLab client
        project_id: GitLab project ID
        source_path: Path to source file
        target_filename: Target filename in registry
        package_name: Package name in registry
        version: Package version
        gitlab_url: GitLab instance URL

    Returns:
        Tuple of (success: bool, result: str) where result is either download_url on success or error_message on failure
    """
    try:
        logger.info(f"Processing file: {source_path.name} -> {target_filename}")

        # Calculate local file checksum
        logger.info(f"Calculating checksum for {source_path.name}...")
        local_checksum = calculate_sha256(source_path)

        # Delete existing files with the same name to enable replacement
        delete_existing_files(
            gl=gl,
            project_id=project_id,
            package_name=package_name,
            version=version,
            filename=target_filename,
        )

        # Upload file with retry logic
        upload_success = upload_file_with_retry(
            gl=gl,
            project_id=project_id,
            file_path=source_path,
            package_name=package_name,
            version=version,
            target_filename=target_filename,
        )

        if not upload_success:
            return False, "Upload failed after all retry attempts"

        # Validate upload
        logger.info(f"Validating upload for {target_filename}...")
        validation_success = validate_upload(
            gl=gl,
            project_id=project_id,
            package_name=package_name,
            version=version,
            filename=target_filename,
            expected_sha256=local_checksum,
        )

        if not validation_success:
            return False, "Upload validation failed"

        # Generate download URL
        download_url = (
            f"{gitlab_url}/api/v4/projects/{project_id}/packages/generic/"
            f"{package_name}/{version}/{target_filename}"
        )

        logger.info(f"Successfully uploaded {target_filename}")
        return True, download_url

    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(error_msg)
        return False, error_msg


def main() -> None:
    """Main function to handle argument parsing and orchestrate the multi-file upload process."""
    parser = argparse.ArgumentParser(
        description="Upload single or multiple files to GitLab generic package registry with checksum validation and copy-paste friendly URL reporting"
    )

    # Required arguments
    parser.add_argument(
        "--package-name",
        type=str,
        required=True,
        help="Package name in GitLab generic package registry",
    )
    parser.add_argument("--version", type=str, required=True, help="Package version")

    # Mutually exclusive file input group
    file_input_group = parser.add_mutually_exclusive_group(required=True)
    file_input_group.add_argument(
        "--files",
        type=str,
        nargs="+",
        help="One or more file paths to upload (mutually exclusive with --directory)",
    )
    file_input_group.add_argument(
        "--directory",
        type=str,
        help="Directory path to upload all top-level files (mutually exclusive with --files)",
    )

    # Optional arguments
    parser.add_argument(
        "--file-mapping",
        type=str,
        action="append",
        help="Map source file to target filename (format: local.bin:remote.bin). "
        "Can be specified multiple times. Only valid with --files.",
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

    # Validate that --file-mapping is only used with --files
    if args.file_mapping and not args.files:
        parser.error("--file-mapping can only be used with --files")

    logger.info(f"Package: {args.package_name}, Version: {args.version}")

    try:
        # Collect files to upload
        logger.info("Collecting files to upload...")
        files_to_upload = collect_files_to_upload(args)

        if not files_to_upload:
            logger.error("No files to upload")
            sys.exit(1)

        logger.info(f"Found {len(files_to_upload)} file(s) to upload")

        # Get authentication token
        token = get_gitlab_token(args.token)

        # Initialize GitLab client
        logger.info(f"Connecting to GitLab at {args.gitlab_url}")
        gl = Gitlab(args.gitlab_url, private_token=token)
        gl.auth()
        logger.info("Authentication successful")

        # Fetch project details to get human-readable path
        project = gl.projects.get(PROJECT_ID)
        project_path = project.path_with_namespace
        logger.info(f"Uploading to project {project_path}")

        # Initialize result lists
        successful_uploads: list[tuple[str, str, str]] = []  # (source, target, url)
        failed_uploads: list[tuple[str, str, str]] = []  # (source, target, error)

        # Process each file
        for source_path, target_filename in files_to_upload:
            success, result = process_single_file(
                gl=gl,
                project_id=PROJECT_ID,
                source_path=source_path,
                target_filename=target_filename,
                package_name=args.package_name,
                version=args.version,
                gitlab_url=args.gitlab_url,
            )

            if success:
                successful_uploads.append((str(source_path), target_filename, result))
            else:
                failed_uploads.append((str(source_path), target_filename, result))

        # Print summary table
        console.print("\n[bold]Upload Summary[/bold]\n")

        if successful_uploads:
            console.print("[bold green]✓ Successful Uploads[/bold green]\n")
            for source, target, url in successful_uploads:
                console.print(f"[cyan]Source File:[/cyan] {source}")
                console.print(f"[cyan]Target Filename:[/cyan] {target}")
                console.print(f"[cyan]Download URL:[/cyan] [blue]{url}[/blue]")
                console.print()  # Add blank line between entries

        if failed_uploads:
            console.print("[bold red]✗ Failed Uploads[/bold red]\n")
            for source, target, error in failed_uploads:
                console.print(f"[cyan]Source File:[/cyan] {source}")
                console.print(f"[cyan]Target Filename:[/cyan] {target}")
                console.print(f"[cyan]Error:[/cyan] [red]{error}[/red]")
                console.print()  # Add blank line between entries

        # Print final status
        console.print(
            f"\n[bold]Results:[/bold] {len(successful_uploads)} succeeded, "
            f"{len(failed_uploads)} failed out of {len(files_to_upload)} total"
        )

        # Exit with appropriate code
        if failed_uploads:
            sys.exit(1)
        else:
            console.print(
                f"\n[bold green]✓[/bold green] All files successfully uploaded to "
                f"{args.package_name} v{args.version}"
            )
            sys.exit(0)

    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)
    except FileNotFoundError as e:
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
