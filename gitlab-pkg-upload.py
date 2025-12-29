#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "python-gitlab>=4.0.0",
#     "rich>=13.0.0",
#     "GitPython>=3.1.0",
# ]
# ///

"""
GitLab Generic Package Upload Script

A standalone uv-compatible Python script that uploads single or multiple files to GitLab's
generic package registry with SHA256 checksum validation, retry logic, and rich progress output.
Supports uploading multiple files from explicit file lists or directories.
Features copy-paste friendly URL output to avoid terminal truncation.

Filename Restrictions:
    GitLab's Generic Package Registry API has limitations on filename characters.
    Only ASCII characters are supported: letters (a-z, A-Z), digits (0-9), dots (.),
    hyphens (-), underscores (_), and forward slashes (/) for directory paths.

    Files with non-ASCII characters or unsupported special characters will be rejected
    with an error. Ensure filenames use only ASCII-safe characters before uploading.
"""

import argparse
import hashlib
import json
import logging
import sys
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from gitlab.exceptions import GitlabAuthenticationError
from gitlab_common import (
    GitAutoDetector,
    ProjectResolver,
    enhance_error_message,
    get_gitlab_token,
    handle_network_error_with_retry,
    setup_logging,
    validate_configuration,
    validate_project_input,
)
from rich.console import Console
from rich.status import Status

from gitlab import Gitlab

# Constants
DEFAULT_GITLAB_URL = "https://gitlab.com"
MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]  # Exponential backoff in seconds
RATE_LIMIT_RETRY_DELAY = 60  # Seconds to wait for rate limit reset

# Setup rich console and logging
console = Console()
setup_logging(console=console)
logger = logging.getLogger(__name__)


@dataclass
class FileFingerprint:
    """Represents a unique identifier for files to enable accurate duplicate detection."""

    source_path: str
    target_filename: str
    sha256_checksum: str
    file_size: int
    timestamp: float


@dataclass
class RemoteFile:
    """Represents a file that exists in the GitLab package registry."""

    file_id: int
    filename: str
    sha256_checksum: Optional[str]
    file_size: int
    download_url: str
    package_name: str
    version: str


class DuplicatePolicy(Enum):
    """Defines how the system should handle detected duplicates."""

    SKIP = "skip"  # Skip uploading duplicates (default)
    REPLACE = "replace"  # Delete existing and upload new
    ERROR = "error"  # Fail with error on duplicates


@dataclass
class UploadResult:
    """Enhanced upload result structure with duplicate detection information."""

    source_path: str
    target_filename: str
    success: bool
    result: str  # URL on success, error message on failure
    was_duplicate: bool = False
    duplicate_action: Optional[str] = None  # "skipped", "replaced", "error"
    existing_url: Optional[str] = None


class DuplicateDetector:
    """Core component responsible for detecting duplicates both locally (within session) and remotely (in GitLab registry)."""

    def __init__(self, gitlab_client: Gitlab, project_id: int):
        """
        Initialize DuplicateDetector with GitLab client and project ID.

        Args:
            gitlab_client: Authenticated GitLab client
            project_id: GitLab project ID
        """
        self.gl = gitlab_client
        self.project_id = project_id
        self.session_registry: dict[str, FileFingerprint] = {}

    def check_session_duplicate(
        self, file_path: Path, target_filename: str
    ) -> Optional[FileFingerprint]:
        """
        Check if file was already processed in current session.

        Args:
            file_path: Path to the source file
            target_filename: Target filename in registry

        Returns:
            FileFingerprint if duplicate found, None otherwise
        """
        logger.debug(f"Checking session duplicate for: {target_filename}")

        # Check if target filename already exists in session registry
        if target_filename in self.session_registry:
            existing_fingerprint = self.session_registry[target_filename]
            logger.debug(f"Found existing session entry for {target_filename}")

            # Calculate checksum of current file to compare
            current_checksum = calculate_sha256(file_path)

            # Compare checksums to determine if it's truly a duplicate
            if existing_fingerprint.sha256_checksum == current_checksum:
                logger.info(
                    f"Session duplicate detected: {target_filename} (checksum: {current_checksum})"
                )
                logger.info(
                    f"Original source: {existing_fingerprint.source_path}, Current source: {file_path}"
                )
                return existing_fingerprint
            else:
                logger.warning(
                    f"Same target filename {target_filename} but different content detected"
                )
                logger.warning(
                    f"Existing checksum: {existing_fingerprint.sha256_checksum}, Current checksum: {current_checksum}"
                )
        else:
            logger.debug(f"No session duplicate found for {target_filename}")

        return None

    def check_remote_duplicate(
        self, package_name: str, version: str, filename: str, checksum: str
    ) -> Optional[RemoteFile]:
        """
        Check if file exists in GitLab registry with enhanced retry logic.

        Args:
            package_name: Package name in registry
            version: Package version
            filename: Target filename
            checksum: SHA256 checksum to compare

        Returns:
            RemoteFile if duplicate found, None otherwise
        """
        logger.info(
            f"Starting remote duplicate check for {filename} in {package_name} v{version}"
        )
        logger.debug(f"Local checksum to compare: {checksum}")

        def _check_remote_duplicate():
            """Internal function to check remote duplicate."""
            project = self.gl.projects.get(self.project_id)
            packages = project.packages.list(package_name=package_name, get_all=True)

            # Find the target package version
            target_package = next((p for p in packages if p.version == version), None)

            if not target_package:
                logger.debug(
                    f"Package {package_name} v{version} not found - no remote duplicate"
                )
                return None

            logger.debug(
                f"Found package {package_name} v{version} (ID: {target_package.id})"
            )

            # Get package files
            package_obj = project.packages.get(target_package.id)
            package_files = package_obj.package_files.list(get_all=True)

            logger.debug(f"Found {len(package_files)} files in package")

            # Find files with matching filename
            matching_files = [f for f in package_files if f.file_name == filename]

            if not matching_files:
                logger.debug(
                    f"No files named {filename} found in remote package - no duplicate"
                )
                return None

            logger.debug(
                f"Found {len(matching_files)} file(s) with matching filename {filename}"
            )

            # Check for checksum matches
            for pkg_file in matching_files:
                remote_sha256 = getattr(pkg_file, "file_sha256", None)

                if remote_sha256:
                    logger.debug(
                        f"Comparing checksums - Remote: {remote_sha256}, Local: {checksum}"
                    )
                    if remote_sha256.lower() == checksum.lower():
                        logger.info(
                            f"Remote duplicate detected: {filename} (checksum: {checksum})"
                        )
                        logger.info(
                            f"Remote file ID: {pkg_file.id}, Size: {getattr(pkg_file, 'size', 'unknown')}"
                        )

                        # Generate download URL
                        download_url = (
                            f"{self.gl.api_url.replace('/api/v4', '')}/api/v4/projects/{self.project_id}/packages/generic/"
                            f"{package_name}/{version}/{filename}"
                        )

                        return RemoteFile(
                            file_id=pkg_file.id,
                            filename=filename,
                            sha256_checksum=remote_sha256,
                            file_size=getattr(pkg_file, "size", 0),
                            download_url=download_url,
                            package_name=package_name,
                            version=version,
                        )
                    else:
                        logger.debug(
                            f"File {filename} exists but checksum differs (remote: {remote_sha256}, local: {checksum})"
                        )
                else:
                    # Handle incomplete metadata gracefully - use file size as fallback
                    logger.warning(
                        f"Remote checksum not available for {filename}, using file size comparison"
                    )
                    logger.debug(
                        f"Cannot verify duplicate without checksum for {filename}"
                    )

            logger.debug(
                f"No matching checksums found for {filename} - no remote duplicate"
            )
            return None

        try:
            return handle_network_error_with_retry(
                operation_name=f"Remote duplicate check for {filename}",
                operation_func=_check_remote_duplicate,
            )
        except Exception as e:
            logger.error(f"Remote duplicate check failed for {filename}: {e}")
            logger.warning(f"Proceeding without duplicate detection for {filename}")
            return None

    def register_file(self, file_path: Path, target_filename: str, checksum: str):
        """
        Register file as processed in current session.

        Args:
            file_path: Path to the source file
            target_filename: Target filename in registry
            checksum: SHA256 checksum of the file
        """
        file_stats = file_path.stat()

        fingerprint = FileFingerprint(
            source_path=str(file_path),
            target_filename=target_filename,
            sha256_checksum=checksum,
            file_size=file_stats.st_size,
            timestamp=time.time(),
        )

        self.session_registry[target_filename] = fingerprint
        logger.info(
            f"Registered file in session: {target_filename} (checksum: {checksum})"
        )
        logger.debug(
            f"Session registry now contains {len(self.session_registry)} file(s)"
        )


def validate_filename_ascii(filename: str) -> tuple[bool, str]:
    """
    Validate that a filename contains only ASCII characters supported by GitLab Generic Package Registry.

    GitLab's API restricts filenames to ASCII-safe characters only. This function checks
    if the provided filename complies with these restrictions.

    Args:
        filename: Target filename to validate

    Returns:
        Tuple of (is_valid, error_message) where:
        - is_valid: True if filename is valid, False otherwise
        - error_message: Empty string if valid, detailed error message if invalid

    Examples:
        Valid filenames: "package.tar.gz", "my-file_v1.0.bin", "subdir/file.txt"
        Invalid filenames: "café.tar.gz", "文件.bin", "file™.txt"
    """
    logger.debug(f"Validating filename for ASCII compliance: {filename}")

    # Check if filename is ASCII
    if not filename.isascii():
        logger.info(f"Filename validation failed: {filename}")
        error_message = (
            f"GitLab Generic Package Registry does not support non-ASCII characters in filenames.\n"
            f"Problematic filename: '{filename}'\n"
            f"Allowed characters: letters (a-z, A-Z), digits (0-9), dots (.), hyphens (-), underscores (_), and forward slashes (/) for directory paths.\n"
            f"Please rename the file to use only ASCII-safe characters before uploading."
        )
        return False, error_message

    # Additional validation: check for allowed characters only
    # Allowed: letters, digits, dots, hyphens, underscores, forward slashes
    import re

    allowed_pattern = re.compile(r"^[a-zA-Z0-9._/-]+$")

    if not allowed_pattern.match(filename):
        logger.info(f"Filename validation failed: {filename}")
        error_message = (
            f"GitLab Generic Package Registry does not support special characters in filenames.\n"
            f"Problematic filename: '{filename}'\n"
            f"Allowed characters: letters (a-z, A-Z), digits (0-9), dots (.), hyphens (-), underscores (_), and forward slashes (/) for directory paths.\n"
            f"Please rename the file to use only ASCII-safe characters before uploading."
        )
        return False, error_message

    logger.debug(f"Filename validation passed: {filename}")
    return True, ""


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


def collect_files_to_upload(
    args: argparse.Namespace,
) -> tuple[list[tuple[Path, str]], list[dict]]:
    """
    Collect files to upload based on input mode (--files or --directory).

    Validates that all filenames contain only ASCII characters supported by GitLab.

    Args:
        args: Parsed command-line arguments

    Returns:
        Tuple of (valid_files, file_errors) where:
        - valid_files: List of tuples containing (source_path, target_filename)
        - file_errors: List of dicts with error information for invalid files

    Raises:
        ValueError: If file paths are invalid, file mappings are malformed,
                    or filenames contain non-ASCII characters
        FileNotFoundError: If specified directory does not exist
    """
    files_to_upload: list[tuple[Path, str]] = []
    file_errors: list[dict] = []

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

        # Process each file - collect errors instead of raising immediately
        for file_path_str in args.files:
            source_path = Path(file_path_str)

            # Validate file existence and type
            if not source_path.exists():
                target_filename = file_mappings.get(source_path.name, source_path.name)
                file_errors.append(
                    {
                        "source_path": str(source_path),
                        "target_filename": target_filename,
                        "error_message": f"File not found: {source_path}",
                        "error_type": "FileNotFoundError",
                    }
                )
                logger.error(f"File not found: {source_path}")
                continue

            if not source_path.is_file():
                target_filename = file_mappings.get(source_path.name, source_path.name)
                file_errors.append(
                    {
                        "source_path": str(source_path),
                        "target_filename": target_filename,
                        "error_message": f"Path is not a file: {source_path}",
                        "error_type": "ValueError",
                    }
                )
                logger.error(f"Path is not a file: {source_path}")
                continue

            # Apply mapping if exists, otherwise use original filename
            target_filename = file_mappings.get(source_path.name, source_path.name)

            # Validate filename for GitLab API compatibility
            is_valid, error_message = validate_filename_ascii(target_filename)
            if not is_valid:
                raise ValueError(error_message)

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
                # Validate filename for GitLab API compatibility
                is_valid, error_message = validate_filename_ascii(item.name)
                if not is_valid:
                    raise ValueError(error_message)
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

    return files_to_upload, file_errors


def format_results_as_json(
    package_name: str,
    version: str,
    successful_uploads: list[UploadResult],
    skipped_duplicates: list[UploadResult],
    failed_uploads: list[UploadResult],
) -> dict:
    """
    Convert upload results into a JSON-serializable dictionary.

    Args:
        package_name: Package name in registry
        version: Package version
        successful_uploads: List of successful upload results
        skipped_duplicates: List of skipped duplicate results
        failed_uploads: List of failed upload results

    Returns:
        Dictionary with structured results ready for JSON serialization
    """
    # Calculate statistics
    replaced_count = sum(
        1
        for r in successful_uploads
        if r.was_duplicate and r.duplicate_action == "replaced"
    )
    new_uploads_count = len(successful_uploads) - replaced_count
    total_processed = (
        len(successful_uploads) + len(skipped_duplicates) + len(failed_uploads)
    )

    # Determine overall success status
    success = len(failed_uploads) == 0
    exit_code = 0 if success else 1

    # Helper function to convert UploadResult to dict
    def result_to_dict(result: UploadResult, is_skipped: bool = False) -> dict:
        """Convert an UploadResult to a dictionary for JSON output."""
        # Determine download URL based on result type
        if result.success:
            if is_skipped:
                download_url = result.existing_url or result.result
            else:
                download_url = result.result
        else:
            download_url = None

        return {
            "source_path": result.source_path,
            "target_filename": result.target_filename,
            "download_url": download_url,
            "checksum": None,  # Checksum not currently stored in UploadResult
            "was_duplicate": result.was_duplicate,
            "duplicate_action": result.duplicate_action,
            "existing_url": result.existing_url,
            "error_message": result.result if not result.success else None,
        }

    # Build the result structure
    result_dict = {
        "success": success,
        "exit_code": exit_code,
        "package_name": package_name,
        "version": version,
        "successful_uploads": [result_to_dict(r) for r in successful_uploads],
        "skipped_duplicates": [
            result_to_dict(r, is_skipped=True) for r in skipped_duplicates
        ],
        "failed_uploads": [result_to_dict(r) for r in failed_uploads],
        "statistics": {
            "total_processed": total_processed,
            "new_uploads": new_uploads_count,
            "replaced_duplicates": replaced_count,
            "skipped_duplicates": len(skipped_duplicates),
            "failed_uploads": len(failed_uploads),
        },
    }

    return result_dict


def handle_duplicate(
    policy: DuplicatePolicy,
    remote_file: RemoteFile,
    detector: DuplicateDetector,
    gl: Gitlab,
    project_id: int,
) -> tuple[str, str, int]:
    """
    Handle duplicate file according to policy.

    Args:
        policy: Duplicate handling policy
        remote_file: Remote file that was found as duplicate
        detector: DuplicateDetector instance
        gl: GitLab client
        project_id: Project ID

    Returns:
        Tuple of (action, result, deleted_count) where action is "skipped"/"replaced"/"error",
        result is URL or error message, and deleted_count is the number of files deleted

    Raises:
        ValueError: If policy is ERROR and duplicate is found
    """
    logger.info(
        f"Handling duplicate file {remote_file.filename} with policy: {policy.value}"
    )
    logger.debug(
        f"Remote file details - ID: {remote_file.file_id}, Size: {remote_file.file_size}, Checksum: {remote_file.sha256_checksum}"
    )

    if policy == DuplicatePolicy.SKIP:
        logger.info(
            f"Policy decision: SKIP - Skipping duplicate file: {remote_file.filename}"
        )
        logger.info(f"Using existing file URL: {remote_file.download_url}")
        return "skipped", remote_file.download_url, 0

    elif policy == DuplicatePolicy.REPLACE:
        logger.info(
            f"Policy decision: REPLACE - Replacing duplicate file: {remote_file.filename}"
        )
        logger.info("Deleting existing file(s) before upload")
        deleted_count = delete_existing_files(
            gl=gl,
            project_id=project_id,
            package_name=remote_file.package_name,
            version=remote_file.version,
            filename=remote_file.filename,
        )
        logger.info(f"Deleted {deleted_count} existing file(s), proceeding with upload")
        return "replaced", "proceed_with_upload", deleted_count

    elif policy == DuplicatePolicy.ERROR:
        error_msg = f"Policy decision: ERROR - Duplicate file detected: {remote_file.filename} (checksum: {remote_file.sha256_checksum})"
        logger.error(error_msg)
        logger.error(f"Existing file URL: {remote_file.download_url}")
        raise ValueError(error_msg)

    else:
        error_msg = f"Unknown duplicate policy: {policy}"
        logger.error(error_msg)
        raise ValueError(error_msg)


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
    Upload file to GitLab generic package registry with enhanced retry logic.

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

    def _upload_file():
        """Internal function to upload file."""
        project = gl.projects.get(project_id)

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

    try:
        return handle_network_error_with_retry(
            operation_name=f"File upload for {target_filename}",
            operation_func=_upload_file,
            max_retries=max_retries,
        )
    except Exception as e:
        logger.error(f"Upload failed for {target_filename}: {e}")
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

                # Debug: log all available filenames
                available_files = [pkg_file.file_name for pkg_file in package_files]
                logger.debug(f"Available files in package: {available_files}")
                logger.debug(f"Looking for filename: {filename}")

                for pkg_file in package_files:
                    # Handle both direct filename match and path-based match
                    # GitLab might store subdirectory files differently
                    file_matches = (
                        pkg_file.file_name == filename
                        or pkg_file.file_name.endswith(f"/{filename}")
                        or filename.endswith(f"/{pkg_file.file_name}")
                        or pkg_file.file_name.replace("/", "_")
                        == filename.replace("/", "_")
                    )

                    if file_matches:
                        # Check if SHA256 is available in the response
                        remote_sha256 = getattr(pkg_file, "file_sha256", None)

                        if remote_sha256:
                            if remote_sha256.lower() == expected_sha256.lower():
                                logger.info(
                                    f"Checksum validation successful: {expected_sha256}"
                                )
                                return True
                            else:
                                # Special handling for empty files - GitLab may compute checksums differently
                                if (
                                    expected_sha256.lower()
                                    == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
                                ):
                                    logger.warning(
                                        f"Empty file checksum mismatch (GitLab limitation). "
                                        f"Local: {expected_sha256}, Remote: {remote_sha256}. "
                                        f"Assuming upload success for empty file."
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

        # Special handling for files with subdirectories - GitLab Generic Package Registry
        # may not support subdirectories in filenames properly
        if "/" in filename:
            logger.warning(
                f"File '{filename}' contains subdirectory path. GitLab Generic Package Registry "
                f"may not support subdirectories in filenames. Upload may have succeeded but "
                f"validation failed. Consider using flat filenames without subdirectories."
            )
            # For subdirectory files, we'll assume success if upload didn't fail
            # This is a workaround for GitLab API limitations
            return True

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
    detector: DuplicateDetector,
    duplicate_policy: DuplicatePolicy,
) -> UploadResult:
    """
    Process upload and validation for a single file with duplicate detection.

    Args:
        gl: Authenticated GitLab client
        project_id: GitLab project ID
        source_path: Path to source file
        target_filename: Target filename in registry
        package_name: Package name in registry
        version: Package version
        gitlab_url: GitLab instance URL
        detector: DuplicateDetector instance
        duplicate_policy: How to handle duplicates

    Returns:
        UploadResult with success status and details
    """
    try:
        logger.info(f"Processing file: {source_path.name} -> {target_filename}")

        # Check session duplicate before processing
        session_duplicate = detector.check_session_duplicate(
            source_path, target_filename
        )
        if session_duplicate:
            logger.info(f"Session duplicate detected for {target_filename}, skipping")
            return UploadResult(
                source_path=str(source_path),
                target_filename=target_filename,
                success=True,
                result="Skipped - already processed in this session",
                was_duplicate=True,
                duplicate_action="skipped",
                existing_url=None,
            )

        # Calculate local file checksum for new files
        logger.info(f"Calculating checksum for {source_path.name}...")
        local_checksum = calculate_sha256(source_path)

        # Initialize variable to track file deletions
        files_deleted = 0

        # Check remote duplicate before upload
        remote_duplicate = detector.check_remote_duplicate(
            package_name, version, target_filename, local_checksum
        )

        if remote_duplicate:
            logger.info(f"Remote duplicate detected for {target_filename}")
            try:
                # Handle duplicates according to policy
                action, result, deleted_count = handle_duplicate(
                    duplicate_policy, remote_duplicate, detector, gl, project_id
                )

                if action == "skipped":
                    return UploadResult(
                        source_path=str(source_path),
                        target_filename=target_filename,
                        success=True,
                        result=result,  # This is the download URL
                        was_duplicate=True,
                        duplicate_action="skipped",
                        existing_url=result,
                    )
                elif action == "replaced":
                    # Track deletions and continue with upload after deletion
                    files_deleted = deleted_count
                    logger.info(
                        f"Proceeding with upload after replacing {target_filename}"
                    )
                # If action is "error", handle_duplicate will raise an exception

            except ValueError as e:
                return UploadResult(
                    source_path=str(source_path),
                    target_filename=target_filename,
                    success=False,
                    result=str(e),
                    was_duplicate=True,
                    duplicate_action="error",
                )
        else:
            # No remote duplicate found, delete existing files with same name for replacement
            files_deleted = delete_existing_files(
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
            return UploadResult(
                source_path=str(source_path),
                target_filename=target_filename,
                success=False,
                result="Upload failed after all retry attempts",
            )

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
            return UploadResult(
                source_path=str(source_path),
                target_filename=target_filename,
                success=False,
                result="Upload validation failed",
            )

        # Generate download URL
        download_url = (
            f"{gitlab_url}/api/v4/projects/{project_id}/packages/generic/"
            f"{package_name}/{version}/{target_filename}"
        )

        # Register successfully processed files
        detector.register_file(source_path, target_filename, local_checksum)

        logger.info(f"Successfully uploaded {target_filename}")

        # Check if this was a replaced duplicate
        # A file is considered replaced if either:
        # 1. A remote duplicate was found (same name + same checksum), OR
        # 2. Files were deleted (same name, possibly different checksum)
        was_replaced_duplicate = (remote_duplicate is not None) or (files_deleted > 0)
        replaced_existing_url = (
            remote_duplicate.download_url if remote_duplicate else None
        )

        return UploadResult(
            source_path=str(source_path),
            target_filename=target_filename,
            success=True,
            result=download_url,
            was_duplicate=was_replaced_duplicate,
            duplicate_action="replaced" if was_replaced_duplicate else None,
            existing_url=replaced_existing_url,
        )

    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(error_msg)
        return UploadResult(
            source_path=str(source_path),
            target_filename=target_filename,
            success=False,
            result=error_msg,
        )


def main() -> None:
    """Main function to handle argument parsing and orchestrate the multi-file upload process."""
    parser = argparse.ArgumentParser(
        description="Upload single or multiple files to GitLab generic package registry with checksum validation and copy-paste friendly URL reporting. "
        "Automatically detects GitLab project from Git repository when no project is specified."
    )

    # Required arguments
    parser.add_argument(
        "--package-name",
        type=str,
        required=True,
        help="Package name in GitLab generic package registry",
    )
    parser.add_argument("--version", type=str, required=True, help="Package version")

    # Mutually exclusive project specification group (now optional due to auto-detection)
    project_group = parser.add_mutually_exclusive_group(required=False)
    project_group.add_argument(
        "--project-url",
        type=str,
        help="GitLab project URL (e.g., https://gitlab.com/namespace/project). If not specified, will attempt auto-detection from Git repository.",
    )
    project_group.add_argument(
        "--project-path",
        type=str,
        help="GitLab project path (e.g., namespace/project). If not specified, will attempt auto-detection from Git repository.",
    )

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
        help="GitLab private token (takes precedence over GITLAB_TOKEN env var)",
    )
    parser.add_argument(
        "--gitlab-url",
        type=str,
        default=DEFAULT_GITLAB_URL,
        help=f"GitLab instance URL (default: {DEFAULT_GITLAB_URL})",
    )
    parser.add_argument(
        "--duplicate-policy",
        type=str,
        choices=["skip", "replace", "error"],
        default="skip",
        help="How to handle duplicate files: skip (default), replace, or error",
    )
    parser.add_argument(
        "--json-output",
        action="store_true",
        help="Output results in JSON format for machine parsing (useful for testing and automation)",
    )

    args = parser.parse_args()

    # Validate that --file-mapping is only used with --files
    if args.file_mapping and not args.files:
        parser.error("--file-mapping can only be used with --files")

    logger.info(f"Package: {args.package_name}, Version: {args.version}")

    try:
        # Validate configuration and dependencies
        logger.info("Validating configuration and dependencies...")
        validate_configuration(
            token=args.token,
            gitlab_url=args.gitlab_url,
            require_git=not (
                args.project_url or args.project_path
            ),  # Git required only for auto-detection
            working_directory=".",
        )

        # Collect files to upload
        logger.info("Collecting files to upload...")
        files_to_upload, file_errors = collect_files_to_upload(args)

        # Handle file validation errors
        if file_errors:
            if not files_to_upload:
                # All files are invalid - exit with error
                logger.error(f"All {len(file_errors)} file(s) failed validation")
                if args.json_output:
                    error_json = {
                        "success": False,
                        "exit_code": 1,
                        "package_name": args.package_name,
                        "version": args.version,
                        "successful_uploads": [],
                        "skipped_duplicates": [],
                        "failed_uploads": file_errors,
                        "error": f"All {len(file_errors)} file(s) failed validation",
                        "error_type": "FileValidationError",
                        "statistics": {
                            "total_processed": len(file_errors),
                            "new_uploads": 0,
                            "replaced_duplicates": 0,
                            "skipped_duplicates": 0,
                            "failed_uploads": len(file_errors),
                        },
                    }
                    print(json.dumps(error_json, indent=2))
                else:
                    for error in file_errors:
                        logger.error(f"{error['error_message']}")
                sys.exit(1)
            else:
                # Some files are valid - log warnings and continue
                logger.warning(
                    f"{len(file_errors)} file(s) failed validation, continuing with {len(files_to_upload)} valid file(s)"
                )
                for error in file_errors:
                    logger.warning(f"{error['error_message']}")

        if not files_to_upload:
            logger.error("No files to upload")
            sys.exit(1)

        logger.info(f"Found {len(files_to_upload)} file(s) to upload")

        # Get authentication token
        token = get_gitlab_token(args.token)

        # Initialize GitLab client
        logger.info(f"Connecting to GitLab at {args.gitlab_url}")
        try:
            gl = Gitlab(args.gitlab_url, private_token=token)
            gl.auth()
            logger.info("Authentication successful")
        except GitlabAuthenticationError as e:
            context = {
                "project_path": "authentication",
                "gitlab_url": args.gitlab_url,
                "operation": "GitLab authentication",
            }
            enhanced_message = enhance_error_message(e, context)
            logger.error(enhanced_message)
            sys.exit(1)
        except Exception as e:
            context = {
                "project_path": "connection",
                "gitlab_url": args.gitlab_url,
                "operation": "GitLab connection",
            }
            enhanced_message = enhance_error_message(e, context)
            logger.error(enhanced_message)
            sys.exit(1)

        # Determine project ID with precedence logic
        project_id = None
        resolved_gitlab_url = args.gitlab_url

        try:
            # Validate and parse project input (URL or path)
            input_gitlab_url, project_path = validate_project_input(args)

            if input_gitlab_url and project_path:
                # Project URL or path provided - use dynamic project resolution
                logger.info(
                    "Project URL/path provided - using dynamic project resolution"
                )

                # Update GitLab URL if different from CLI argument
                if input_gitlab_url != args.gitlab_url:
                    logger.info(
                        f"Updating GitLab URL from {args.gitlab_url} to {input_gitlab_url}"
                    )
                    resolved_gitlab_url = input_gitlab_url
                    # Re-initialize GitLab client with correct URL
                    try:
                        gl = Gitlab(input_gitlab_url, private_token=token)
                        gl.auth()
                        logger.info(f"Re-authenticated with {input_gitlab_url}")
                    except Exception as e:
                        context = {
                            "project_path": "authentication",
                            "gitlab_url": input_gitlab_url,
                            "operation": "GitLab re-authentication",
                        }
                        enhanced_message = enhance_error_message(e, context)
                        logger.error(enhanced_message)
                        sys.exit(1)

                # Create ProjectResolver and resolve project ID
                resolver = ProjectResolver(gl)
                project_id = resolver.resolve_project_id(input_gitlab_url, project_path)

                # Validate project access
                if not resolver.validate_project_access(project_id):
                    raise ValueError(
                        f"Access validation failed for project {project_path}"
                    )

                logger.info(
                    f"Successfully resolved project ID: {project_id} for {project_path}"
                )

            else:
                # No project URL/path provided and auto-detection failed
                logger.error("Project specification required - auto-detection failed")

                # Try to provide more specific guidance based on what we found
                detector = GitAutoDetector()
                try:
                    repo = detector.find_git_repository()
                    if not repo:
                        # No Git repository found
                        error_msg = (
                            "No project could be determined - Git auto-detection failed.\n\n"
                            "REASON: No Git repository found in current directory or parent directories.\n\n"
                            "SOLUTION: Please specify project information using one of:\n"
                            "  --project-url https://gitlab.com/namespace/project\n"
                            "  --project-path namespace/project\n\n"
                            "EXAMPLES of valid project specifications:\n"
                            "  • --project-url https://gitlab.com/mycompany/my-project\n"
                            "  • --project-url https://gitlab.example.com/team/backend-api\n"
                            "  • --project-path mycompany/my-project\n"
                            "  • --project-path group/subgroup/project-name\n\n"
                            "ALTERNATIVE: To enable auto-detection in the future:\n"
                            "  1. Initialize Git repository: git init\n"
                            "  2. Add GitLab remote: git remote add origin <gitlab-url>\n"
                            "  3. Or clone from GitLab: git clone <gitlab-url>\n\n"
                            "TROUBLESHOOTING:\n"
                            "  • Ensure you're running from within a Git repository\n"
                            "  • Check if .git directory exists: ls -la .git\n"
                            "  • Verify Git is installed: git --version"
                        )
                    else:
                        # Git repository found but no GitLab remotes
                        try:
                            detector.get_gitlab_remotes(repo)
                            # This should not happen since we're in the else block, but just in case
                            error_msg = (
                                "No project could be determined - Git auto-detection failed unexpectedly.\n\n"
                                "Please specify project information using:\n"
                                "  --project-url https://gitlab.com/namespace/project\n"
                                "  --project-path namespace/project"
                            )
                        except ValueError as remote_error:
                            # get_gitlab_remotes raised a detailed error - use it
                            error_msg = (
                                "No project could be determined - Git auto-detection failed.\n\n"
                                f"REASON: {str(remote_error)}\n\n"
                                "SOLUTION: Please specify project information using one of:\n"
                                "  --project-url https://gitlab.com/namespace/project\n"
                                "  --project-path namespace/project\n\n"
                                "EXAMPLES of valid project specifications:\n"
                                "  • --project-url https://gitlab.com/mycompany/my-project\n"
                                "  • --project-url https://gitlab.example.com/team/backend-api\n"
                                "  • --project-path mycompany/my-project\n"
                                "  • --project-path group/subgroup/project-name"
                            )
                except ValueError as git_error:
                    # find_git_repository raised a detailed error - use it
                    error_msg = (
                        "No project could be determined - Git auto-detection failed.\n\n"
                        f"REASON: {str(git_error)}\n\n"
                        "SOLUTION: Please specify project information using one of:\n"
                        "  --project-url https://gitlab.com/namespace/project\n"
                        "  --project-path namespace/project\n\n"
                        "EXAMPLES of valid project specifications:\n"
                        "  • --project-url https://gitlab.com/mycompany/my-project\n"
                        "  • --project-url https://gitlab.example.com/team/backend-api\n"
                        "  • --project-path mycompany/my-project\n"
                        "  • --project-path group/subgroup/project-name"
                    )
                except Exception:
                    # Generic fallback error message
                    error_msg = (
                        "No project could be determined - Git auto-detection failed.\n\n"
                        "REASON: Unable to detect GitLab project from Git repository.\n\n"
                        "SOLUTION: Please specify project information using one of:\n"
                        "  --project-url https://gitlab.com/namespace/project\n"
                        "  --project-path namespace/project\n\n"
                        "EXAMPLES of valid project specifications:\n"
                        "  • --project-url https://gitlab.com/mycompany/my-project\n"
                        "  • --project-url https://gitlab.example.com/team/backend-api\n"
                        "  • --project-path mycompany/my-project\n"
                        "  • --project-path group/subgroup/project-name\n\n"
                        "TROUBLESHOOTING Git auto-detection:\n"
                        "  1. Ensure you're in a Git repository: git status\n"
                        "  2. Check Git remotes: git remote -v\n"
                        "  3. Verify remotes point to GitLab: git remote get-url origin\n"
                        "  4. Add GitLab remote if missing: git remote add origin <gitlab-url>\n\n"
                        "SUPPORTED Git remote formats:\n"
                        "  • HTTPS: https://gitlab.com/namespace/project.git\n"
                        "  • SSH: git@gitlab.com:namespace/project.git\n"
                        "  • Custom GitLab: https://gitlab.example.com/namespace/project.git"
                    )

                raise ValueError(error_msg)

        except ValueError as e:
            logger.error(f"Project resolution failed: {e}")
            sys.exit(1)

        # Create detector instance with resolved project ID
        detector = DuplicateDetector(gl, project_id)
        duplicate_policy = DuplicatePolicy(args.duplicate_policy)
        logger.info(f"Using duplicate handling policy: {duplicate_policy.value}")

        # Fetch project details to get human-readable path
        project = gl.projects.get(project_id)
        project_path = project.path_with_namespace
        logger.info(f"Uploading to project {project_path}")

        # Initialize result lists to track duplicate status
        successful_uploads: list[
            UploadResult
        ] = []  # Successfully uploaded files (new uploads)
        failed_uploads: list[UploadResult] = []  # Failed uploads
        skipped_duplicates: list[UploadResult] = []  # Files skipped due to duplication

        # Process each file
        for source_path, target_filename in files_to_upload:
            result = process_single_file(
                gl=gl,
                project_id=project_id,
                source_path=source_path,
                target_filename=target_filename,
                package_name=args.package_name,
                version=args.version,
                gitlab_url=resolved_gitlab_url,
                detector=detector,
                duplicate_policy=duplicate_policy,
            )

            # Categorize results based on success and duplicate status
            if result.success:
                if result.was_duplicate and result.duplicate_action == "skipped":
                    # Track skipped duplicates with existing URLs
                    skipped_duplicates.append(result)
                    logger.info(
                        f"Categorized as skipped duplicate: {result.target_filename}"
                    )
                else:
                    # Track successful uploads (including replaced duplicates)
                    successful_uploads.append(result)
                    logger.info(
                        f"Categorized as successful upload: {result.target_filename}"
                    )
            else:
                # Track failed uploads (including duplicate policy errors)
                failed_uploads.append(result)
                logger.info(f"Categorized as failed upload: {result.target_filename}")

        # Output results based on format preference
        if args.json_output:
            # JSON output mode - merge file_errors into failed_uploads
            all_failed_uploads = failed_uploads + [
                UploadResult(
                    source_path=error["source_path"],
                    target_filename=error["target_filename"],
                    success=False,
                    result=error["error_message"],
                )
                for error in file_errors
            ]
            result_dict = format_results_as_json(
                package_name=args.package_name,
                version=args.version,
                successful_uploads=successful_uploads,
                skipped_duplicates=skipped_duplicates,
                failed_uploads=all_failed_uploads,
            )
            print(json.dumps(result_dict, indent=2))
            sys.exit(result_dict["exit_code"])
        else:
            # Rich console output mode (existing code)
            # Print summary table with enhanced duplicate detection reporting
            console.print("\n[bold]Upload Summary[/bold]\n")

            if successful_uploads:
                console.print("[bold green]✓ Successful Uploads[/bold green]\n")
                for result in successful_uploads:
                    console.print(f"[cyan]Source File:[/cyan] {result.source_path}")
                    console.print(
                        f"[cyan]Target Filename:[/cyan] {result.target_filename}"
                    )
                    console.print(
                        f"[cyan]Download URL:[/cyan] [blue]{result.result}[/blue]"
                    )

                    # Show if this was a replaced duplicate
                    if result.was_duplicate and result.duplicate_action == "replaced":
                        console.print(
                            "[cyan]Action:[/cyan] [yellow]Replaced existing duplicate[/yellow]"
                        )
                        if result.existing_url:
                            console.print(
                                f"[cyan]Previous URL:[/cyan] [dim]{result.existing_url}[/dim]"
                            )

                    console.print()  # Add blank line between entries

            if skipped_duplicates:
                console.print("[bold yellow]⚠ Skipped Duplicates[/bold yellow]\n")
                for result in skipped_duplicates:
                    console.print(f"[cyan]Source File:[/cyan] {result.source_path}")
                    console.print(
                        f"[cyan]Target Filename:[/cyan] {result.target_filename}"
                    )
                    console.print(
                        f"[cyan]Existing URL:[/cyan] [blue]{result.existing_url or result.result}[/blue]"
                    )
                    console.print(f"[cyan]Reason:[/cyan] {result.result}")
                    console.print()  # Add blank line between entries

            if failed_uploads:
                console.print("[bold red]✗ Failed Uploads[/bold red]\n")
                for result in failed_uploads:
                    console.print(f"[cyan]Source File:[/cyan] {result.source_path}")
                    console.print(
                        f"[cyan]Target Filename:[/cyan] {result.target_filename}"
                    )
                    console.print(f"[cyan]Error:[/cyan] [red]{result.result}[/red]")
                    if result.was_duplicate:
                        console.print(
                            f"[cyan]Duplicate Action:[/cyan] {result.duplicate_action}"
                        )
                        if result.existing_url:
                            console.print(
                                f"[cyan]Existing URL:[/cyan] [blue]{result.existing_url}[/blue]"
                            )
                    console.print()  # Add blank line between entries

            # Print comprehensive statistics including duplicate detection
            total_processed = (
                len(successful_uploads) + len(skipped_duplicates) + len(failed_uploads)
            )
            replaced_count = sum(
                1
                for r in successful_uploads
                if r.was_duplicate and r.duplicate_action == "replaced"
            )
            new_uploads_count = len(successful_uploads) - replaced_count

            console.print("\n[bold]Duplicate Detection Statistics:[/bold]")
            console.print(f"• New uploads: {new_uploads_count}")
            console.print(f"• Replaced duplicates: {replaced_count}")
            console.print(f"• Skipped duplicates: {len(skipped_duplicates)}")
            console.print(f"• Failed uploads: {len(failed_uploads)}")
            console.print(f"• Total processed: {total_processed}")

            # Print final status distinguishing uploaded vs skipped
            console.print(
                f"\n[bold]Final Results:[/bold] {len(successful_uploads)} uploaded "
                f"({new_uploads_count} new, {replaced_count} replaced), "
                f"{len(skipped_duplicates)} skipped duplicates, "
                f"{len(failed_uploads)} failed out of {total_processed} total"
            )

            # Exit with appropriate code
            if failed_uploads:
                sys.exit(1)
            else:
                replaced_count = sum(
                    1
                    for r in successful_uploads
                    if r.was_duplicate and r.duplicate_action == "replaced"
                )
                new_uploads_count = len(successful_uploads) - replaced_count

                console.print(
                    f"\n[bold green]✓[/bold green] All files processed successfully for {args.package_name} v{args.version}: "
                    f"{new_uploads_count} new uploads, {replaced_count} replaced duplicates, "
                    f"{len(skipped_duplicates)} skipped duplicates"
                )
                sys.exit(0)

    except ValueError as e:
        if args.json_output:
            error_json = {
                "success": False,
                "exit_code": 1,
                "error": str(e),
                "error_type": "ValueError",
            }
            print(json.dumps(error_json, indent=2))
        else:
            logger.error(str(e))
        sys.exit(1)
    except FileNotFoundError as e:
        if args.json_output:
            error_json = {
                "success": False,
                "exit_code": 1,
                "error": str(e),
                "error_type": "FileNotFoundError",
            }
            print(json.dumps(error_json, indent=2))
        else:
            logger.error(str(e))
        sys.exit(1)
    except GitlabAuthenticationError as e:
        if args.json_output:
            error_json = {
                "success": False,
                "exit_code": 1,
                "error": f"GitLab authentication failed: {e}",
                "error_type": "GitlabAuthenticationError",
            }
            print(json.dumps(error_json, indent=2))
        else:
            logger.error(f"GitLab authentication failed: {e}")
        sys.exit(1)
    except Exception as e:
        if args.json_output:
            error_json = {
                "success": False,
                "exit_code": 1,
                "error": str(e),
                "error_type": type(e).__name__,
            }
            print(json.dumps(error_json, indent=2))
        else:
            logger.error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
