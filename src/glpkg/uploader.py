"""Upload orchestration for gitlab-pkg-upload using tenacity for retry handling."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from gitlab import Gitlab
from gitlab.exceptions import GitlabError
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from .duplicate_detector import calculate_sha256
from .models import (
    ChecksumValidationError,
    DuplicatePolicy,
    NetworkError,
    RemoteFile,
    UploadContext,
    UploadResult,
)

logger = logging.getLogger(__name__)


def is_transient_error(exception: Exception) -> bool:
    """
    Determine if an exception represents a transient error that should be retried.

    Transient errors include network issues, timeouts, rate limits, and server errors.
    Permanent errors include authentication failures, validation errors, and not found errors.

    Args:
        exception: The exception to classify

    Returns:
        True if the error is transient and should be retried, False otherwise
    """
    # Check for network-related exception types
    if isinstance(exception, (ConnectionError, TimeoutError)):
        logger.debug(f"Transient error detected (exception type): {type(exception).__name__}")
        return True

    error_msg = str(exception).lower()

    # Permanent errors - do not retry
    permanent_indicators = [
        "401",
        "403",
        "unauthorized",
        "forbidden",
        "400",
        "422",
        "validation",
        "404",
        "not found",
    ]
    for indicator in permanent_indicators:
        if indicator in error_msg:
            logger.debug(f"Permanent error detected (indicator: {indicator}): {exception}")
            return False

    # Transient errors - should retry
    transient_indicators = [
        "connection",
        "timeout",
        "network",
        "unreachable",
        "408",
        "429",
        "rate limit",
        "500",
        "502",
        "503",
        "504",
        "service unavailable",
        "bad gateway",
        "gateway timeout",
    ]
    for indicator in transient_indicators:
        if indicator in error_msg:
            logger.debug(f"Transient error detected (indicator: {indicator}): {exception}")
            return True

    # GitLab-specific transient errors
    if isinstance(exception, GitlabError):
        # Check response code if available
        response_code = getattr(exception, "response_code", None)
        if response_code:
            if response_code >= 500 or response_code in (408, 429):
                logger.debug(f"Transient GitLab error detected (response code: {response_code})")
                return True
            if response_code in (401, 403, 404, 400, 422):
                logger.debug(f"Permanent GitLab error detected (response code: {response_code})")
                return False

    # Default to not retrying unknown errors
    logger.debug(f"Unknown error type, not retrying: {exception}")
    return False


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception(is_transient_error),
)
def upload_single_file(context: UploadContext, file: Path, target_filename: str) -> str:
    """
    Upload a single file to the GitLab generic package registry.

    This function handles the actual upload operation with automatic retry
    for transient errors using tenacity.

    Args:
        context: Upload context containing GitLab client and configuration
        file: Path to the local file to upload
        target_filename: Target filename in the registry

    Returns:
        Download URL for the uploaded file

    Raises:
        GitlabError: If upload fails after all retry attempts
        NetworkError: If network issues persist after retries
    """
    # Handle dry-run mode
    if context.config.dry_run:
        logger.info(f"[DRY-RUN] Would upload: {file} -> {target_filename}")
        mock_url = (
            f"{context.config.gitlab_url}/api/v4/projects/{context.project_id}"
            f"/packages/generic/{context.config.package_name}/{context.config.version}/{target_filename}"
        )
        return mock_url

    # Perform actual upload
    start_time = time.time()
    file_size_mb = file.stat().st_size / (1024 * 1024)

    logger.info(f"Uploading {target_filename} ({file_size_mb:.2f} MB)...")
    logger.debug(f"Source path: {file}")

    project = context.gl.projects.get(context.project_id)
    project.generic_packages.upload(
        package_name=context.config.package_name,
        package_version=context.config.version,
        file_name=target_filename,
        path=file.as_posix(),
    )

    elapsed_time = time.time() - start_time
    logger.info(
        f"Uploaded {target_filename} ({file_size_mb:.2f} MB) in {elapsed_time:.2f}s"
    )

    # Construct download URL
    download_url = (
        f"{context.config.gitlab_url}/api/v4/projects/{context.project_id}"
        f"/packages/generic/{context.config.package_name}/{context.config.version}/{target_filename}"
    )

    return download_url


def validate_upload(
    context: UploadContext, filename: str, expected_sha256: str
) -> bool:
    """
    Validate that an uploaded file has the correct checksum in the registry.

    Args:
        context: Upload context containing GitLab client and configuration
        filename: The filename to validate in the registry
        expected_sha256: Expected SHA256 checksum of the file

    Returns:
        True if validation succeeds

    Raises:
        ChecksumValidationError: If checksum mismatch detected
    """
    # Handle dry-run mode
    if context.config.dry_run:
        logger.info(f"[DRY-RUN] Would validate checksum for: {filename}")
        return True

    logger.debug(f"Validating upload checksum for {filename}")
    logger.debug(f"Expected SHA256: {expected_sha256}")

    project = context.gl.projects.get(context.project_id)
    packages = project.packages.list(
        package_name=context.config.package_name, get_all=True
    )

    # Find the target package version
    target_package = next(
        (p for p in packages if p.version == context.config.version), None
    )

    if not target_package:
        logger.error(
            f"Package {context.config.package_name} v{context.config.version} not found during validation"
        )
        return False

    # Get package files
    package_obj = project.packages.get(target_package.id)
    package_files = package_obj.package_files.list(get_all=True)

    # Find file matching filename (handle exact match and path variations)
    matching_file = None
    for pkg_file in package_files:
        file_name = getattr(pkg_file, "file_name", "")
        if file_name == filename or file_name.endswith(f"/{filename}"):
            matching_file = pkg_file
            break

    if not matching_file:
        logger.error(f"File {filename} not found in registry during validation")
        return False

    # Extract remote checksum
    remote_sha256 = getattr(matching_file, "file_sha256", None)

    if not remote_sha256:
        logger.warning(f"Remote checksum not available for {filename}, skipping validation")
        return True

    # Handle special case for empty files
    empty_file_sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    if expected_sha256.lower() == empty_file_sha256 and remote_sha256.lower() == empty_file_sha256:
        logger.debug(f"Empty file checksum validated for {filename}")
        return True

    # Compare checksums (case-insensitive)
    if remote_sha256.lower() == expected_sha256.lower():
        logger.info(f"Checksum validated for {filename}")
        logger.debug(f"Checksum: {expected_sha256}")
        return True

    # Checksum mismatch - this is an error
    error_msg = (
        f"Checksum mismatch for {filename}: "
        f"expected {expected_sha256}, got {remote_sha256}"
    )
    logger.error(error_msg)
    raise ChecksumValidationError(error_msg)


def handle_duplicate(
    context: UploadContext, file: Path, remote: RemoteFile
) -> tuple[str, str]:
    """
    Handle a detected duplicate file based on the configured policy.

    Args:
        context: Upload context containing GitLab client and configuration
        file: Path to the local file that is a duplicate
        remote: RemoteFile information about the existing file

    Returns:
        Tuple of (action_taken, url_or_proceed_flag):
        - ("skipped", download_url) - File was skipped, returns existing URL
        - ("replaced", "proceed_with_upload") - File was deleted, proceed with upload
        - ("error", ...) - Should not reach here, raises ValueError instead

    Raises:
        ValueError: If policy is ERROR
    """
    logger.info(
        f"Duplicate detected for {file.name}: "
        f"remote file {remote.filename} (checksum: {remote.sha256_checksum})"
    )

    policy = context.config.duplicate_policy

    if policy == DuplicatePolicy.SKIP:
        logger.info(f"Skipping duplicate: {file.name} (policy: SKIP)")
        return ("skipped", remote.download_url)

    elif policy == DuplicatePolicy.REPLACE:
        logger.info(f"Replacing duplicate: {file.name} (policy: REPLACE)")
        delete_file_from_registry(context, remote.filename)
        return ("replaced", "proceed_with_upload")

    elif policy == DuplicatePolicy.ERROR:
        error_msg = (
            f"Duplicate file detected: {file.name} "
            f"(remote: {remote.filename}, checksum: {remote.sha256_checksum}). "
            f"Use --duplicate-policy=skip or --duplicate-policy=replace to handle duplicates."
        )
        logger.error(error_msg)
        raise ValueError(error_msg)

    # Should not reach here
    raise ValueError(f"Unknown duplicate policy: {policy}")


def delete_file_from_registry(context: UploadContext, filename: str) -> int:
    """
    Delete a file from the GitLab package registry.

    Args:
        context: Upload context containing GitLab client and configuration
        filename: The filename to delete from the registry

    Returns:
        Number of files deleted
    """
    # Handle dry-run mode
    if context.config.dry_run:
        logger.info(f"[DRY-RUN] Would delete: {filename} from registry")
        return 0

    logger.debug(f"Deleting {filename} from registry")

    project = context.gl.projects.get(context.project_id)
    packages = project.packages.list(
        package_name=context.config.package_name, get_all=True
    )

    # Find the target package version
    target_package = next(
        (p for p in packages if p.version == context.config.version), None
    )

    if not target_package:
        logger.warning(
            f"Package {context.config.package_name} v{context.config.version} not found, "
            f"nothing to delete"
        )
        return 0

    # Get package files
    package_obj = project.packages.get(target_package.id)
    package_files = package_obj.package_files.list(get_all=True)

    # Find and delete all files matching filename
    deleted_count = 0
    for pkg_file in package_files:
        file_name = getattr(pkg_file, "file_name", "")
        if file_name == filename:
            try:
                pkg_file.delete()
                deleted_count += 1
                logger.info(f"Deleted file from registry: {filename} (ID: {pkg_file.id})")
            except Exception as e:
                logger.warning(f"Failed to delete file {filename} (ID: {pkg_file.id}): {e}")

    if deleted_count == 0:
        logger.warning(f"No files named {filename} found to delete")

    return deleted_count


def upload_files(
    context: UploadContext, files: list[tuple[Path, str]]
) -> list[UploadResult]:
    """
    Upload multiple files to the GitLab generic package registry.

    This is the main orchestration function that handles duplicate detection,
    upload, validation, and registration for each file.

    Args:
        context: Upload context containing GitLab client and configuration
        files: List of (source_path, target_filename) tuples to upload

    Returns:
        List of UploadResult objects for each file
    """
    results: list[UploadResult] = []

    for source_path, target_filename in files:
        logger.debug(f"Processing file: {source_path} -> {target_filename}")

        try:
            # Check for session duplicate
            session_duplicate = context.detector.check_session_duplicate(
                source_path, target_filename
            )

            if session_duplicate:
                logger.info(
                    f"Session duplicate detected for {target_filename}, skipping"
                )
                # Construct URL from session duplicate info
                existing_url = (
                    f"{context.config.gitlab_url}/api/v4/projects/{context.project_id}"
                    f"/packages/generic/{context.config.package_name}/{context.config.version}/{target_filename}"
                )
                results.append(
                    UploadResult(
                        source_path=str(source_path),
                        target_filename=target_filename,
                        success=True,
                        result=existing_url,
                        was_duplicate=True,
                        duplicate_action="skipped",
                        existing_url=existing_url,
                    )
                )
                continue

            # Calculate checksum for remote duplicate check
            checksum = calculate_sha256(source_path)
            logger.debug(f"Calculated checksum for {source_path}: {checksum}")

            # Check for remote duplicate
            remote_duplicate = context.detector.check_remote_duplicate(
                context.config.package_name,
                context.config.version,
                target_filename,
                checksum,
            )

            if remote_duplicate:
                try:
                    action, result_value = handle_duplicate(
                        context, source_path, remote_duplicate
                    )

                    if action == "skipped":
                        results.append(
                            UploadResult(
                                source_path=str(source_path),
                                target_filename=target_filename,
                                success=True,
                                result=result_value,
                                was_duplicate=True,
                                duplicate_action="skipped",
                                existing_url=result_value,
                            )
                        )
                        continue
                    # If action is "replaced", proceed with upload below

                except ValueError as e:
                    # ERROR policy triggered
                    results.append(
                        UploadResult(
                            source_path=str(source_path),
                            target_filename=target_filename,
                            success=False,
                            result=str(e),
                            was_duplicate=True,
                            duplicate_action="error",
                            existing_url=remote_duplicate.download_url,
                        )
                    )
                    if context.config.fail_fast:
                        logger.error(f"Fail-fast enabled, stopping after error: {e}")
                        return results
                    continue
            else:
                # No checksum match found, but a file with the same name may exist
                # with a different checksum. Delete it if policy is REPLACE to avoid
                # upload conflicts or stale artifacts.
                if context.config.duplicate_policy == DuplicatePolicy.REPLACE:
                    deleted_count = delete_file_from_registry(context, target_filename)
                    if deleted_count > 0:
                        logger.info(
                            f"Deleted {deleted_count} existing file(s) named {target_filename} "
                            f"with different checksum (policy: REPLACE)"
                        )

            # Upload the file
            download_url = upload_single_file(context, source_path, target_filename)

            # Validate the upload
            validate_upload(context, target_filename, checksum)

            # Register file in session
            context.detector.register_file(source_path, target_filename, checksum)

            # Create success result
            was_duplicate = remote_duplicate is not None
            duplicate_action = "replaced" if was_duplicate else None

            results.append(
                UploadResult(
                    source_path=str(source_path),
                    target_filename=target_filename,
                    success=True,
                    result=download_url,
                    was_duplicate=was_duplicate,
                    duplicate_action=duplicate_action,
                    existing_url=remote_duplicate.download_url if remote_duplicate else None,
                )
            )

        except Exception as e:
            logger.error(f"Failed to upload {source_path} -> {target_filename}: {e}")
            results.append(
                UploadResult(
                    source_path=str(source_path),
                    target_filename=target_filename,
                    success=False,
                    result=str(e),
                    was_duplicate=False,
                    duplicate_action=None,
                    existing_url=None,
                )
            )

            if context.config.fail_fast:
                logger.error(f"Fail-fast enabled, stopping after error: {e}")
                return results

    return results
