"""
Test helper utilities for script execution and validation.

This module contains script execution logic extracted from the TestOrchestrator
class in the monolithic test file. It provides utilities for running the
upload script via direct module invocation and validating results.

Updated to use direct module invocation instead of subprocess execution
for better integration with the new modular structure in gitlab_pkg_upload.
"""

import contextlib
import io
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

# Import from the new modular structure
try:
    from gitlab_pkg_upload.cli import main as cli_main
    from gitlab_pkg_upload.models import (
        AuthenticationError,
        ConfigurationError,
        DuplicatePolicy,
        FileValidationError,
        GitLabUploadError,
        NetworkError,
        ProjectResolutionError,
        UploadConfig,
    )

    CLI_AVAILABLE = True
except ImportError:
    cli_main = None
    CLI_AVAILABLE = False
    # Define placeholder exit codes when module not available
    AuthenticationError = None
    ConfigurationError = None
    DuplicatePolicy = None
    FileValidationError = None
    GitLabUploadError = None
    NetworkError = None
    ProjectResolutionError = None
    UploadConfig = None


@dataclass
class UploadExecution:
    """
    Represents a single upload script execution configuration.

    Extracted from the monolithic test file's UploadExecution class.

    Args:
        command: Command line arguments to execute
        expected_exit_code: Expected exit code from script
        expected_output_patterns: Regex patterns to match in output (ignored when use_json_output=True)
        timeout: Execution timeout in seconds
        env_vars: Optional environment variables
        working_directory: Optional working directory for execution
        use_json_output: Enable JSON output mode (adds --json-output flag)
    """

    command: List[str]
    expected_exit_code: int
    expected_output_patterns: List[str]
    timeout: int = 120
    env_vars: Optional[Dict[str, str]] = None
    working_directory: Optional[str] = None
    use_json_output: bool = False


@dataclass
class UploadResult:
    """
    Represents the result of an upload script execution.

    Extracted from the monolithic test file's UploadResult class.

    Args:
        success: Whether the execution was successful
        exit_code: Script exit code
        stdout: Standard output from script
        stderr: Standard error from script
        duration: Execution duration in seconds
        uploaded_files: List of uploaded file names
        upload_urls: List of upload URLs
        error_message: Optional error message
        json_data: Parsed JSON output when use_json_output=True
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


class ScriptExecutor:
    """
    Handles execution of the gitlab-pkg-upload CLI.

    Extracted from the monolithic test file's UploadScriptInterface class.
    This class manages execution of the upload CLI via direct module invocation
    and result parsing.

    Updated to use direct module invocation instead of subprocess execution
    for better integration with the new modular structure.
    """

    def __init__(self, script_path: Optional[Path] = None):
        """
        Initialize script executor.

        Args:
            script_path: Path to the upload script. If None, uses direct module invocation.
                        This parameter is kept for backward compatibility but is
                        ignored when CLI_AVAILABLE is True.
        """
        self.script_path = script_path
        self._use_direct_invocation = CLI_AVAILABLE

        # If direct invocation is not available, fall back to subprocess
        if not self._use_direct_invocation:
            if script_path is None:
                # Default to the upload script in the same directory as the test
                script_path = Path(__file__).parent.parent.parent / "gitlab-pkg-upload.py"
            self.script_path = script_path

            if not self.script_path.exists():
                raise FileNotFoundError(f"Upload script not found at: {self.script_path}")

    def execute_upload(self, execution: UploadExecution) -> UploadResult:
        """
        Execute upload script with given configuration.

        Uses direct module invocation when available, falls back to subprocess
        when the gitlab_pkg_upload module is not importable.

        Args:
            execution: Upload execution configuration

        Returns:
            UploadResult with execution details

        Example:
            # Using JSON output mode
            execution = UploadExecution(
                command=["script.py", "--json-output"],
                expected_exit_code=0,
                expected_output_patterns=[],
                use_json_output=True
            )
            result = executor.execute_upload(execution)
            if result.json_data:
                print(result.json_data["success"])
        """
        if self._use_direct_invocation:
            return self._execute_direct(execution)
        else:
            return self._execute_subprocess(execution)

    def _execute_direct(self, execution: UploadExecution) -> UploadResult:
        """
        Execute upload via direct module invocation with timeout handling.

        Args:
            execution: Upload execution configuration

        Returns:
            UploadResult with execution details
        """
        start_time = time.time()

        # Extract argv from command (skip the script path)
        argv = execution.command[1:] if len(execution.command) > 1 else []

        # Capture stdout and stderr
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        # Save original environment and argv
        original_env = os.environ.copy()
        original_cwd = os.getcwd()

        exit_code = 0
        timed_out = False

        def run_cli():
            """Inner function to run CLI, to be executed with timeout."""
            nonlocal exit_code
            try:
                cli_main(argv)
                exit_code = 0
            except SystemExit as e:
                exit_code = e.code if isinstance(e.code, int) else 1
            except GitLabUploadError as e:
                exit_code = e.exit_code
                print(str(e), file=sys.stderr)
            except Exception as e:
                exit_code = 1
                print(f"Error: {e}", file=sys.stderr)

        try:
            # Update environment if needed
            if execution.env_vars:
                os.environ.update(execution.env_vars)

            # Change working directory if specified
            if execution.working_directory:
                os.chdir(execution.working_directory)

            # Execute CLI with captured output and timeout
            with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(run_cli)
                    try:
                        future.result(timeout=execution.timeout)
                    except FuturesTimeoutError:
                        timed_out = True
                        exit_code = -1

        finally:
            # Restore original environment
            os.environ.clear()
            os.environ.update(original_env)
            # Restore working directory
            os.chdir(original_cwd)

        duration = time.time() - start_time

        # Handle timeout case - return early with timeout error
        if timed_out:
            return UploadResult(
                success=False,
                exit_code=-1,
                stdout=stdout_capture.getvalue(),
                stderr=stderr_capture.getvalue(),
                duration=duration,
                error_message=f"Script execution timed out after {execution.timeout} seconds",
                uploaded_files=[],
                upload_urls=[],
                json_data=None,
            )

        stdout = stdout_capture.getvalue()
        stderr = stderr_capture.getvalue()

        # Parse JSON output if enabled
        json_data = None
        if execution.use_json_output:
            json_data = self._parse_json_output(stdout)

        # Extract uploaded files and URLs
        if json_data is not None:
            uploaded_files, upload_urls = self._extract_data_from_json(json_data)
        else:
            uploaded_files = self._extract_uploaded_files(stdout)
            upload_urls = self._extract_upload_urls(stdout)

        # Determine success
        if json_data is not None:
            # Use JSON data for success determination
            success = (
                json_data.get("success", False)
                and exit_code == execution.expected_exit_code
                and json_data.get("exit_code", -1) == execution.expected_exit_code
            )
        else:
            # Use traditional pattern matching
            success = (
                exit_code == execution.expected_exit_code
                and self._check_output_patterns(
                    stdout, execution.expected_output_patterns
                )
            )

        error_message = None
        if not success:
            if json_data is not None and "error" in json_data:
                error_message = f"{json_data.get('error_type', 'Error')}: {json_data.get('error', 'Unknown error')}"
            elif exit_code != execution.expected_exit_code:
                error_message = f"Unexpected exit code: {exit_code} (expected {execution.expected_exit_code})"
            else:
                error_message = "Expected output patterns not found"

            if stderr:
                error_message += f". Stderr: {stderr}"

        return UploadResult(
            success=success,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration=duration,
            error_message=error_message,
            uploaded_files=uploaded_files,
            upload_urls=upload_urls,
            json_data=json_data,
        )

    def _execute_subprocess(self, execution: UploadExecution) -> UploadResult:
        """
        Execute upload via subprocess (fallback when module not available).

        Args:
            execution: Upload execution configuration

        Returns:
            UploadResult with execution details
        """
        import subprocess

        start_time = time.time()

        try:
            # Prepare environment
            env = dict(os.environ)
            if execution.env_vars:
                env.update(execution.env_vars)

            # Execute script
            result = subprocess.run(
                execution.command,
                capture_output=True,
                text=True,
                timeout=execution.timeout,
                env=env,
                cwd=execution.working_directory,
            )

            duration = time.time() - start_time

            # Parse JSON output if enabled
            json_data = None
            if execution.use_json_output:
                json_data = self._parse_json_output(result.stdout)

            # Extract uploaded files and URLs
            if json_data is not None:
                uploaded_files, upload_urls = self._extract_data_from_json(json_data)
            else:
                uploaded_files = self._extract_uploaded_files(result.stdout)
                upload_urls = self._extract_upload_urls(result.stdout)

            # Determine success
            if json_data is not None:
                # Use JSON data for success determination
                success = (
                    json_data.get("success", False)
                    and result.returncode == execution.expected_exit_code
                    and json_data.get("exit_code", -1) == execution.expected_exit_code
                )
            else:
                # Use traditional pattern matching
                success = (
                    result.returncode == execution.expected_exit_code
                    and self._check_output_patterns(
                        result.stdout, execution.expected_output_patterns
                    )
                )

            error_message = None
            if not success:
                if json_data is not None and "error" in json_data:
                    error_message = f"{json_data.get('error_type', 'Error')}: {json_data.get('error', 'Unknown error')}"
                elif result.returncode != execution.expected_exit_code:
                    error_message = f"Unexpected exit code: {result.returncode} (expected {execution.expected_exit_code})"
                else:
                    error_message = "Expected output patterns not found"

                if result.stderr:
                    error_message += f". Stderr: {result.stderr}"

            return UploadResult(
                success=success,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                duration=duration,
                error_message=error_message,
                uploaded_files=uploaded_files,
                upload_urls=upload_urls,
                json_data=json_data,
            )

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            return UploadResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr="",
                duration=duration,
                error_message=f"Script execution timed out after {execution.timeout} seconds",
                uploaded_files=[],
                upload_urls=[],
                json_data=None,
            )
        except Exception as e:
            duration = time.time() - start_time
            return UploadResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr="",
                duration=duration,
                error_message=f"Script execution failed: {e}",
                uploaded_files=[],
                upload_urls=[],
                json_data=None,
            )

    def build_command(self, use_json_output: bool = False, **kwargs) -> List[str]:
        """
        Build command line arguments from parameters.

        Args:
            use_json_output: Enable JSON output mode (adds --json-output flag)
            **kwargs: Command line parameters

        Returns:
            List of command line arguments

        Raises:
            ValueError: If required parameters are missing or invalid
        """
        # Validate required parameters
        if "package_name" not in kwargs:
            raise ValueError("package_name is required")
        if kwargs["package_name"] is None or (
            isinstance(kwargs["package_name"], str)
            and not kwargs["package_name"].strip()
        ):
            raise ValueError("package_name is required and cannot be empty")

        if "version" not in kwargs:
            raise ValueError("version is required")
        if kwargs["version"] is None or (
            isinstance(kwargs["version"], str) and not kwargs["version"].strip()
        ):
            raise ValueError("version is required and cannot be empty")

        # Use program name for direct invocation, script path for subprocess fallback
        if self._use_direct_invocation:
            command = ["gitlab-pkg-upload"]
        else:
            command = [str(self.script_path)]

        # Add common parameters
        if "package_name" in kwargs:
            command.extend(["--package-name", kwargs["package_name"]])
        if "version" in kwargs:
            command.extend(["--package-version", kwargs["version"]])
        if "files" in kwargs:
            if isinstance(kwargs["files"], list):
                command.extend(["--files"] + kwargs["files"])
            else:
                command.extend(["--files", kwargs["files"]])
        if "project_path" in kwargs:
            command.extend(["--project-path", kwargs["project_path"]])
        if "gitlab_url" in kwargs:
            command.extend(["--gitlab-url", kwargs["gitlab_url"]])
        if "duplicate_policy" in kwargs:
            command.extend(["--duplicate-policy", kwargs["duplicate_policy"]])

        # Add JSON output flag if requested
        if use_json_output or kwargs.get("json_output", False):
            command.append("--json-output")

        return command

    def create_single_file_execution(
        self,
        package_name: str,
        version: str,
        file_path: str,
        project_path: Optional[str] = None,
        gitlab_url: str = "https://gitlab.com",
        duplicate_policy: str = "skip",
        use_json_output: bool = False,
    ) -> UploadExecution:
        """
        Create execution configuration for single file upload.

        Args:
            package_name: Name of the package
            version: Package version
            file_path: Path to file to upload
            project_path: GitLab project path
            gitlab_url: GitLab instance URL
            duplicate_policy: Policy for handling duplicates
            use_json_output: Enable JSON output mode

        Returns:
            UploadExecution configuration
        """
        command = self.build_command(
            use_json_output=use_json_output,
            package_name=package_name,
            version=version,
            files=file_path,
            project_path=project_path,
            gitlab_url=gitlab_url,
            duplicate_policy=duplicate_policy,
        )

        # When JSON mode is enabled, don't use regex patterns
        expected_patterns = (
            []
            if use_json_output
            else [
                f"Package: {package_name}, Version: {version}",
                r"✓ All files processed successfully for",
            ]
        )

        return UploadExecution(
            command=command,
            expected_exit_code=0,
            expected_output_patterns=expected_patterns,
            timeout=120,
            use_json_output=use_json_output,
        )

    def create_multiple_file_execution(
        self,
        package_name: str,
        version: str,
        file_paths: List[str],
        project_path: Optional[str] = None,
        gitlab_url: str = "https://gitlab.com",
        duplicate_policy: str = "skip",
        use_json_output: bool = False,
    ) -> UploadExecution:
        """
        Create execution configuration for multiple file upload.

        Args:
            package_name: Name of the package
            version: Package version
            file_paths: List of file paths to upload
            project_path: GitLab project path
            gitlab_url: GitLab instance URL
            duplicate_policy: Policy for handling duplicates
            use_json_output: Enable JSON output mode

        Returns:
            UploadExecution configuration
        """
        command = self.build_command(
            use_json_output=use_json_output,
            package_name=package_name,
            version=version,
            files=file_paths,
            project_path=project_path,
            gitlab_url=gitlab_url,
            duplicate_policy=duplicate_policy,
        )

        # When JSON mode is enabled, don't use regex patterns
        expected_patterns = (
            []
            if use_json_output
            else [
                f"Package: {package_name}, Version: {version}",
                r"All files processed successfully for",
            ]
        )

        return UploadExecution(
            command=command,
            expected_exit_code=0,
            expected_output_patterns=expected_patterns,
            timeout=180,
            use_json_output=use_json_output,
        )

    def validate_upload_result(
        self, result: UploadResult, expected_files: List[str], gitlab_client=None
    ) -> bool:
        """
        Validate upload result against expected outcomes.

        Args:
            result: Upload result to validate
            expected_files: List of expected uploaded files
            gitlab_client: Optional GitLab client for additional validation

        Returns:
            True if validation passes, False otherwise
        """
        # Basic validation
        if not result.success:
            return False

        # If JSON data is available, use structured validation
        if result.json_data is not None:
            if not result.json_data.get("success", False):
                return False

            # Check that expected files appear in successful_uploads
            successful_uploads = result.json_data.get("successful_uploads", [])
            uploaded_filenames = [
                upload.get("target_filename", "") for upload in successful_uploads
            ]

            for expected_file in expected_files:
                file_name = Path(expected_file).name
                if file_name not in uploaded_filenames:
                    return False
        else:
            # Fall back to stdout string matching
            for expected_file in expected_files:
                file_name = Path(expected_file).name
                if file_name not in result.stdout:
                    return False

        # Additional GitLab API validation if client provided
        if gitlab_client and hasattr(gitlab_client, "verify_upload"):
            # This would require package name, version, etc. to be passed
            # For now, just return the basic validation result
            pass

        return True

    def _extract_uploaded_files(self, stdout: str) -> List[str]:
        """
        Extract uploaded file names from script output.

        Args:
            stdout: Script standard output

        Returns:
            List of uploaded file names
        """
        uploaded_files = []

        # Look for patterns that indicate file uploads
        import re

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
        Extract upload URLs from script output.

        Args:
            stdout: Script standard output

        Returns:
            List of upload URLs
        """
        upload_urls = []

        # Look for URL patterns in output
        import re

        url_pattern = r"https?://[^\s]+"
        matches = re.findall(url_pattern, stdout)
        upload_urls.extend(matches)

        return upload_urls

    def _check_output_patterns(self, stdout: str, patterns: List[str]) -> bool:
        """
        Check if output contains expected patterns.

        Args:
            stdout: Script standard output
            patterns: List of expected patterns (regex)

        Returns:
            True if all patterns are found, False otherwise
        """
        import re

        for pattern in patterns:
            if not re.search(pattern, stdout):
                return False

        return True

    def _parse_json_output(self, stdout: str) -> Optional[Dict]:
        """
        Parse JSON output from script stdout.

        Args:
            stdout: Script standard output

        Returns:
            Parsed JSON dictionary, or None if parsing fails

        Example:
            json_data = self._parse_json_output(result.stdout)
            if json_data:
                success = json_data.get("success", False)
        """
        import json

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


def execute_script_with_retry(
    executor: ScriptExecutor,
    execution: UploadExecution,
    max_retries: int = 3,
    retry_delay: float = 1.0,
) -> UploadResult:
    """
    Execute script with retry logic for handling transient failures.

    Args:
        executor: Script executor instance
        execution: Upload execution configuration
        max_retries: Maximum number of retry attempts
        retry_delay: Delay between retries in seconds

    Returns:
        UploadResult from the final attempt
    """
    last_result = None

    for attempt in range(max_retries + 1):
        result = executor.execute_upload(execution)

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


def validate_environment() -> bool:
    """
    Validate that the test environment is properly configured.

    Returns:
        True if environment is valid, False otherwise
    """
    import os

    # Check for required environment variables
    required_vars = ["GITLAB_TOKEN"]
    missing_vars = []

    for var in required_vars:
        if not os.environ.get(var):
            missing_vars.append(var)

    if missing_vars:
        print(f"Missing required environment variables: {missing_vars}")
        return False

    return True


def get_project_args(
    project_path: Optional[str] = None, gitlab_url: Optional[str] = None
) -> List[str]:
    """
    Get project arguments for upload script execution.

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
    Validate JSON output from upload script.

    Args:
        json_data: Parsed JSON output from script
        expected_success: Expected success status
        expected_files: Optional list of expected uploaded files

    Returns:
        True if validation passes, False otherwise

    Example:
        result = executor.execute_upload(execution)
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
                from pathlib import Path

                file_name = Path(expected_file).name
                if file_name not in uploaded_filenames:
                    return False
    else:
        # If expecting failure, check error fields
        if "error" not in json_data or "error_type" not in json_data:
            return False

    return True
