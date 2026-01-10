"""Duplicate detection for gitlab-pkg-upload."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from gitlab import Gitlab

from .models import FileFingerprint, RemoteFile

logger = logging.getLogger(__name__)


def calculate_sha256(file_path: Path) -> str:
    """
    Calculate SHA256 checksum of a file.

    Args:
        file_path: Path to the file

    Returns:
        SHA256 checksum as hex string
    """
    import hashlib

    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def handle_network_error_with_retry(
    operation_name: str,
    operation_func,
    max_retries: int = 3,
    retry_delays: list[int] | None = None,
):
    """
    Execute an operation with retry logic for network errors.

    Args:
        operation_name: Name of the operation for logging
        operation_func: Function to execute
        max_retries: Maximum number of retries
        retry_delays: List of delays between retries

    Returns:
        Result of operation_func

    Raises:
        Exception: If all retries are exhausted
    """
    if retry_delays is None:
        retry_delays = [1, 2, 4]

    last_exception = None
    for attempt in range(max_retries + 1):
        try:
            return operation_func()
        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                delay = retry_delays[min(attempt, len(retry_delays) - 1)]
                logger.warning(
                    f"{operation_name} failed (attempt {attempt + 1}/{max_retries + 1}): {e}"
                )
                logger.info(f"Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                logger.error(f"{operation_name} failed after {max_retries + 1} attempts: {e}")

    raise last_exception


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
