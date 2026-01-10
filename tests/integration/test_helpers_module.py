"""
Test helper utilities for module-based test execution.

This module provides utilities for calling the CLI main() function directly
instead of using subprocess execution. It captures stdout/stderr, handles
SystemExit exceptions for exit codes, and parses JSON output.
"""

from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    pass

# Import the main function from CLI module
from glpkg.cli.main import main


@dataclass
class UploadResult:
    """
    Represents the result of an upload execution via module invocation.

    Args:
        success: Whether the execution was successful
        exit_code: Exit code from sys.exit() call
        stdout: Captured standard output
        stderr: Captured standard error
        duration: Execution duration in seconds
        uploaded_files: List of uploaded file names
        upload_urls: List of upload URLs
        error_message: Optional error message
        json_data: Parsed JSON output when --json-output is used
                   Contains structured data with fields:
                   - success: bool
                   - exit_code: int
                   - package_name: str
                   - version: str
                   - successful_uploads: list of dicts with source_path, target_filename, download_url, was_duplicate, duplicate_action
                   - skipped_duplicates: list of dicts (same structure as successful_uploads)
                   - failed_uploads: list of dicts with source_path, target_filename, error_message
                   - statistics: dict with total_processed, new_uploads, replaced_duplicates, skipped_duplicates, failed_uploads
                   - error: str (on failure)
                   - error_type: str (on failure)
    """

    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration: float
    uploaded_files: List[str]
    upload_urls: List[str]
    error_message: Optional[str] = None
    json_data: Optional[Dict] = None

    def __post_init__(self):
        if self.uploaded_files is None:
            self.uploaded_files = []
        if self.upload_urls is None:
            self.upload_urls = []


class ModuleExecutor:
    """
    Handles execution of the glpkg CLI via direct module invocation.

    This class calls the main() function from the CLI module directly instead
    of spawning a subprocess. It captures stdout/stderr via context managers
    and handles SystemExit exceptions to capture exit codes.
    """

    # Thread lock for stdout/stderr capture to ensure thread safety
    _capture_lock = threading.Lock()

    def __init__(self):
        """Initialize module executor."""
        pass

    def execute_upload(
        self,
        argv: List[str],
        env_vars: Optional[Dict[str, str]] = None,
        expected_exit_code: int = 0,
        use_json_output: bool = False,
        timeout: int = 120,
    ) -> UploadResult:
        """
        Execute upload by calling the main() function directly.

        Args:
            argv: Command-line arguments to pass to main() (without script path)
            env_vars: Optional environment variables to set during execution
            expected_exit_code: Expected exit code for success determination
            use_json_output: Whether JSON output mode is enabled
            timeout: Execution timeout in seconds (not enforced for direct calls)

        Returns:
            UploadResult with execution details

        Example:
            executor = ModuleExecutor()
            result = executor.execute_upload(
                argv=["--package-name", "test", "--package-version", "1.0.0",
                      "--files", "file.txt", "--json-output"],
                env_vars={"GITLAB_TOKEN": "token"},
                use_json_output=True
            )
            if result.json_data:
                print(result.json_data["success"])
        """
        start_time = time.time()

        # Prepare environment variables
        original_env = {}
        if env_vars:
            for key, value in env_vars.items():
                original_env[key] = os.environ.get(key)
                if value is not None:
                    os.environ[key] = value
                elif key in os.environ:
                    del os.environ[key]

        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        exit_code = 0
        error_message = None

        try:
            # Use lock to ensure thread-safe capture
            with self._capture_lock:
                with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                    try:
                        main(argv)
                        exit_code = 0  # If main() returns normally, exit code is 0
                    except SystemExit as e:
                        # Capture exit code from sys.exit()
                        exit_code = e.code if isinstance(e.code, int) else 1

        except Exception as e:
            duration = time.time() - start_time
            error_message = f"Execution failed with exception: {e}"
            return UploadResult(
                success=False,
                exit_code=-1,
                stdout=stdout_capture.getvalue(),
                stderr=stderr_capture.getvalue(),
                duration=duration,
                error_message=error_message,
                uploaded_files=[],
                upload_urls=[],
                json_data=None,
            )

        finally:
            # Restore original environment
            for key, original_value in original_env.items():
                if original_value is not None:
                    os.environ[key] = original_value
                elif key in os.environ:
                    del os.environ[key]

        duration = time.time() - start_time
        stdout_content = stdout_capture.getvalue()
        stderr_content = stderr_capture.getvalue()

        # Parse JSON output if enabled
        json_data = None
        if use_json_output:
            json_data = self._parse_json_output(stdout_content)

        # Extract uploaded files and URLs
        if json_data is not None:
            uploaded_files, upload_urls = self._extract_data_from_json(json_data)
        else:
            uploaded_files = self._extract_uploaded_files(stdout_content)
            upload_urls = self._extract_upload_urls(stdout_content)

        # Determine success
        if json_data is not None:
            # Use JSON data for success determination
            success = (
                json_data.get("success", False)
                and exit_code == expected_exit_code
                and json_data.get("exit_code", -1) == expected_exit_code
            )
        else:
            # Use exit code for success determination
            success = exit_code == expected_exit_code

        if not success:
            if json_data is not None and "error" in json_data:
                error_message = (
                    f"{json_data.get('error_type', 'Error')}: "
                    f"{json_data.get('error', 'Unknown error')}"
                )
            elif exit_code != expected_exit_code:
                error_message = (
                    f"Unexpected exit code: {exit_code} "
                    f"(expected {expected_exit_code})"
                )

            if stderr_content:
                if error_message:
                    error_message += f". Stderr: {stderr_content}"
                else:
                    error_message = f"Stderr: {stderr_content}"

        return UploadResult(
            success=success,
            exit_code=exit_code,
            stdout=stdout_content,
            stderr=stderr_content,
            duration=duration,
            error_message=error_message,
            uploaded_files=uploaded_files,
            upload_urls=upload_urls,
            json_data=json_data,
        )

    def build_argv(
        self,
        package_name: str,
        version: str,
        files: Optional[List[str]] = None,
        directory: Optional[str] = None,
        project_path: Optional[str] = None,
        project_url: Optional[str] = None,
        gitlab_url: Optional[str] = None,
        duplicate_policy: str = "skip",
        file_mapping: Optional[List[str]] = None,
        json_output: bool = False,
        dry_run: bool = False,
        fail_fast: bool = False,
        verbose: bool = False,
        quiet: bool = False,
        debug: bool = False,
        retry: int = 0,
    ) -> List[str]:
        """
        Build command line arguments for main() function.

        Args:
            package_name: Name of the package
            version: Package version
            files: List of file paths to upload
            directory: Directory containing files to upload
            project_path: GitLab project path (namespace/project)
            project_url: Full GitLab project URL
            gitlab_url: GitLab instance URL
            duplicate_policy: Policy for handling duplicates (skip, replace, error)
            file_mapping: List of file mappings in source:target format
            json_output: Enable JSON output mode
            dry_run: Enable dry run mode
            fail_fast: Enable fail fast mode
            verbose: Enable verbose output
            quiet: Enable quiet output
            debug: Enable debug output
            retry: Number of retry attempts

        Returns:
            List of command line arguments for main()

        Raises:
            ValueError: If required parameters are missing or invalid
        """
        # Validate required parameters
        if not package_name or not package_name.strip():
            raise ValueError("package_name is required and cannot be empty")

        if not version or not version.strip():
            raise ValueError("version is required and cannot be empty")

        if not files and not directory:
            raise ValueError("Either files or directory must be provided")

        # Start with the upload subcommand
        argv = ["upload"]

        # Required arguments
        argv.extend(["--package-name", package_name])
        argv.extend(["--package-version", version])

        # File input
        if files:
            argv.append("--files")
            if isinstance(files, list):
                argv.extend(files)
            else:
                argv.append(files)
        elif directory:
            argv.extend(["--directory", directory])

        # Project specification
        if project_url:
            argv.extend(["--project-url", project_url])
        elif project_path:
            argv.extend(["--project-path", project_path])
            if gitlab_url:
                argv.extend(["--gitlab-url", gitlab_url])

        # Duplicate policy
        if duplicate_policy:
            argv.extend(["--duplicate-policy", duplicate_policy])

        # File mappings
        if file_mapping:
            for mapping in file_mapping:
                argv.extend(["--file-mapping", mapping])

        # Output flags
        if json_output:
            argv.append("--json-output")

        # Operational flags
        if dry_run:
            argv.append("--dry-run")
        if fail_fast:
            argv.append("--fail-fast")
        if retry > 0:
            argv.extend(["--retry", str(retry)])

        # Verbosity flags
        if debug:
            argv.append("--debug")
        elif verbose:
            argv.append("--verbose")
        elif quiet:
            argv.append("--quiet")

        return argv

    def _parse_json_output(self, stdout: str) -> Optional[Dict]:
        """
        Parse JSON output from captured stdout.

        Args:
            stdout: Captured standard output

        Returns:
            Parsed JSON dictionary, or None if parsing fails
        """
        if not stdout or not stdout.strip():
            return None

        try:
            # Try to parse the entire stdout as JSON
            parsed = json.loads(stdout)
            return parsed
        except json.JSONDecodeError:
            # Try to find JSON in the output (in case there's other text)
            try:
                # Look for JSON object starting with { and ending with }
                start_idx = stdout.find("{")
                end_idx = stdout.rfind("}")
                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    json_str = stdout[start_idx : end_idx + 1]
                    parsed = json.loads(json_str)
                    return parsed
            except (json.JSONDecodeError, ValueError):
                pass

        return None

    def _extract_data_from_json(self, json_data: Dict) -> tuple[List[str], List[str]]:
        """
        Extract uploaded files and URLs from JSON data.

        Args:
            json_data: Parsed JSON output from script

        Returns:
            Tuple of (uploaded_files, upload_urls)
        """
        uploaded_files = []
        upload_urls = []

        # Handle success case
        if json_data.get("success", False):
            successful_uploads = json_data.get("successful_uploads", [])
            for upload in successful_uploads:
                if isinstance(upload, dict):
                    # Extract target filename
                    target_filename = upload.get("target_filename", "")
                    if target_filename:
                        uploaded_files.append(target_filename)

                    # Extract download URL
                    download_url = upload.get("download_url", "")
                    if download_url:
                        upload_urls.append(download_url)

        return uploaded_files, upload_urls

    def _extract_uploaded_files(self, stdout: str) -> List[str]:
        """
        Extract uploaded file names from output.

        Args:
            stdout: Captured standard output

        Returns:
            List of uploaded file names
        """
        import re

        uploaded_files = []

        # Pattern for successful file uploads
        upload_patterns = [
            r"✓ Uploaded: (.+)",
            r"Successfully uploaded: (.+)",
            r"File uploaded: (.+)",
        ]

        for pattern in upload_patterns:
            matches = re.findall(pattern, stdout)
            uploaded_files.extend(matches)

        return uploaded_files

    def _extract_upload_urls(self, stdout: str) -> List[str]:
        """
        Extract upload URLs from output.

        Args:
            stdout: Captured standard output

        Returns:
            List of upload URLs
        """
        import re

        url_pattern = r"https?://[^\s]+"
        matches = re.findall(url_pattern, stdout)

        return matches


def get_project_args(
    project_path: Optional[str] = None,
    gitlab_url: Optional[str] = None,
) -> List[str]:
    """
    Get project arguments for CLI invocation.

    Args:
        project_path: GitLab project path
        gitlab_url: GitLab instance URL (optional, only included if provided)

    Returns:
        List of command-line arguments for project specification
    """
    if not project_path:
        return []

    if gitlab_url is None:
        return ["--project-path", project_path]

    return ["--project-path", project_path, "--gitlab-url", gitlab_url]


def validate_json_result(
    json_data: Dict,
    expected_success: bool,
    expected_files: Optional[List[str]] = None,
) -> bool:
    """
    Validate JSON output from upload execution.

    Args:
        json_data: Parsed JSON output from execution
        expected_success: Expected success status
        expected_files: Optional list of expected uploaded files

    Returns:
        True if validation passes, False otherwise

    Example:
        result = executor.execute_upload(argv, use_json_output=True)
        if result.json_data:
            is_valid = validate_json_result(
                result.json_data,
                expected_success=True,
                expected_files=["file1.txt", "file2.txt"]
            )
    """
    # Validate success status
    if json_data.get("success", False) != expected_success:
        return False

    # Validate exit code matches success status
    expected_exit_code = 0 if expected_success else 1
    if json_data.get("exit_code", -1) != expected_exit_code:
        return False

    # If expecting success, validate structure
    if expected_success:
        # Check required fields are present
        required_fields = [
            "package_name",
            "version",
            "successful_uploads",
            "statistics",
        ]
        for field in required_fields:
            if field not in json_data:
                return False

        # Validate statistics consistency
        stats = json_data.get("statistics", {})
        successful_uploads = json_data.get("successful_uploads", [])
        # Calculate expected successful count from new_uploads + replaced_duplicates
        expected_successful = stats.get("new_uploads", 0) + stats.get(
            "replaced_duplicates", 0
        )
        if expected_successful != len(successful_uploads):
            return False

        # Validate expected files if provided
        if expected_files:
            uploaded_filenames = [
                upload.get("target_filename", "")
                for upload in successful_uploads
                if isinstance(upload, dict)
            ]
            for expected_file in expected_files:
                file_name = Path(expected_file).name
                if file_name not in uploaded_filenames:
                    return False
    else:
        # If expecting failure, check error fields
        if "error" not in json_data or "error_type" not in json_data:
            return False

    return True


def execute_with_retry(
    executor: ModuleExecutor,
    argv: List[str],
    env_vars: Optional[Dict[str, str]] = None,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    use_json_output: bool = False,
) -> UploadResult:
    """
    Execute upload with retry logic for handling transient failures.

    Args:
        executor: Module executor instance
        argv: Command-line arguments
        env_vars: Optional environment variables
        max_retries: Maximum number of retry attempts
        retry_delay: Delay between retries in seconds
        use_json_output: Whether JSON output mode is enabled

    Returns:
        UploadResult from the final attempt
    """
    last_result = None

    for attempt in range(max_retries + 1):
        result = executor.execute_upload(
            argv=argv,
            env_vars=env_vars,
            use_json_output=use_json_output,
        )

        if result.success:
            return result

        last_result = result

        # Don't retry on certain types of failures
        if result.exit_code in [2, 3]:  # Argument or configuration errors
            break

        if attempt < max_retries:
            time.sleep(retry_delay * (2**attempt))  # Exponential backoff

    return last_result or UploadResult(
        success=False,
        exit_code=-1,
        stdout="",
        stderr="",
        duration=0.0,
        error_message="All retry attempts failed",
        uploaded_files=[],
        upload_urls=[],
    )
