"""
Error scenario tests for GitLab package upload script.

This module contains tests for error handling scenarios extracted from the
monolithic test file. It validates network failures, authentication errors,
error message validation, failure continuation behavior, and non-ASCII filename
rejection using pytest framework.
"""

import os
from pathlib import Path

import pytest

from .utils.test_helpers import (
    ScriptExecutor,
    UploadExecution,
    get_project_args,
)

# Test markers for categorization
pytestmark = [
    pytest.mark.integration,  # These are integration tests
    pytest.mark.api,  # These require GitLab API access
    pytest.mark.slow,  # These tests simulate failures and take longer
]


def _get_gitlab_token():
    """Get GitLab token from environment with proper error handling."""
    token = os.environ.get("GITLAB_TOKEN")
    if not token:
        pytest.skip("GITLAB_TOKEN environment variable not set")
    return token


class TestErrorScenarios:
    """
    Test class for error scenario handling.

    Extracted and adapted from TestOrchestrator._test_network_failure_simulation,
    _test_authentication_error, _test_error_message_validation, and
    _test_failure_continuation_behavior methods.
    """

    @pytest.mark.timeout(90)
    def test_network_failure_simulation(
        self, gitlab_client, artifact_manager, project_path
    ):
        """
        Test network failure simulation and recovery.

        Args:
            gitlab_client: GitLab test client fixture
            artifact_manager: Artifact manager fixture
            project_path: Project path fixture
        """
        # Set up GitLab client with project
        gitlab_client.set_project(project_path)

        # Create test file
        test_file = artifact_manager.create_test_file(
            "network-test.txt", size_bytes=1024, content_pattern="network-test"
        )

        # Create unique package name
        package_name = gitlab_client.create_test_package("network-failure", "1.0.0")

        # Get project arguments
        project_args = get_project_args(project_path, gitlab_url=None)

        # Build command with invalid GitLab URL to simulate network failure
        command = [
            "python",
            str(Path(__file__).parent.parent / "gitlab-pkg-upload.py"),
            "--package-name",
            package_name,
            "--package-version",
            "1.0.0",
            "--gitlab-url",
            "https://invalid-gitlab-url.example.com",
            "--token",
            _get_gitlab_token(),
            "--json-output",
            "--files",
            str(test_file.path),
        ] + project_args

        # Create execution configuration expecting network failure
        execution_config = UploadExecution(
            command=command,
            expected_exit_code=1,  # Expect failure
            expected_output_patterns=[],
            timeout=60,
            use_json_output=True,
            env_vars={
                "GITLAB_TOKEN": ""
            },  # Clear GITLAB_TOKEN to force use of --token argument
        )

        # Execute upload (should fail due to network issues)
        executor = ScriptExecutor()
        upload_result = executor.execute_upload(execution_config)

        # Verify that it failed as expected
        assert upload_result.exit_code == 1, (
            f"Expected exit code 1, got {upload_result.exit_code}"
        )

        # Validate JSON error fields if available
        if upload_result.json_data is not None:
            assert upload_result.json_data.get("success") is False, (
                "Expected success to be False"
            )
            assert upload_result.json_data.get("exit_code") == 1, (
                "Expected exit_code to be 1"
            )
            assert "error" in upload_result.json_data, (
                "Expected error field in JSON output"
            )
            assert "error_type" in upload_result.json_data, (
                "Expected error_type field in JSON output"
            )

            # Check for network-related keywords in error message
            error_msg = upload_result.json_data["error"].lower()
            network_keywords = [
                "network",
                "connection",
                "timeout",
                "failed to connect",
                "resolve",
                "dns",
            ]
            network_error_found = any(
                keyword in error_msg for keyword in network_keywords
            )
            assert network_error_found, (
                f"Expected network error keywords in JSON error: {upload_result.json_data['error']}"
            )
        else:
            # Fallback to stderr/stdout checking for early script errors
            error_output = upload_result.stdout + upload_result.stderr
            network_error_patterns = [
                "network",
                "connection",
                "timeout",
                "failed to connect",
            ]
            network_error_found = any(
                pattern in error_output.lower() for pattern in network_error_patterns
            )
            assert network_error_found, (
                f"Expected network error patterns in output: {error_output}"
            )

    @pytest.mark.timeout(90)
    def test_authentication_error(self, gitlab_client, artifact_manager, project_path):
        """
        Test authentication error handling with invalid token.

        Args:
            gitlab_client: GitLab test client fixture
            artifact_manager: Artifact manager fixture
            project_path: Project path fixture
        """
        # Set up GitLab client with project
        gitlab_client.set_project(project_path)

        # Create test file
        test_file = artifact_manager.create_test_file(
            filename="auth-error-test.txt", size_bytes=1024, content_pattern="text"
        )

        # Create unique package name
        package_name = gitlab_client.create_test_package("auth-error", "1.0.0")

        # Get project arguments
        project_args = get_project_args(project_path, gitlab_url=None)

        # Build command with invalid token
        invalid_token = "invalid-token-that-should-fail-authentication"
        command = [
            "python",
            str(Path(__file__).parent.parent / "gitlab-pkg-upload.py"),
            "--package-name",
            package_name,
            "--package-version",
            "1.0.0",
            "--token",
            invalid_token,
            "--json-output",
            "--files",
            str(test_file.path),
        ] + project_args

        # Create execution configuration expecting authentication failure
        execution_config = UploadExecution(
            command=command,
            expected_exit_code=1,  # Expect failure
            expected_output_patterns=[],
            timeout=60,
            use_json_output=True,
            env_vars={
                "GITLAB_TOKEN": ""
            },  # Clear GITLAB_TOKEN to force use of --token argument
        )

        # Execute upload (should fail due to authentication issues)
        executor = ScriptExecutor()
        upload_result = executor.execute_upload(execution_config)

        # Validate that the upload failed as expected
        assert upload_result.exit_code != 0, (
            f"Expected upload to fail but got exit code: {upload_result.exit_code}"
        )

        # Validate JSON error fields if available
        if upload_result.json_data is not None:
            assert upload_result.json_data.get("success") is False, (
                "Expected success to be False"
            )
            assert upload_result.json_data.get("exit_code") != 0, (
                "Expected non-zero exit_code"
            )
            assert "error" in upload_result.json_data, (
                "Expected error field in JSON output"
            )
            assert "error_type" in upload_result.json_data, (
                "Expected error_type field in JSON output"
            )

            # Check for authentication-related keywords in error message
            error_msg = upload_result.json_data["error"].lower()
            auth_keywords = [
                "authentication",
                "token",
                "unauthorized",
                "401",
                "403",
                "access denied",
            ]
            auth_error_found = any(keyword in error_msg for keyword in auth_keywords)
            assert auth_error_found, (
                f"Expected authentication error keywords in JSON error: {upload_result.json_data['error']}"
            )
        else:
            # Fallback to stderr/stdout checking for early script errors
            error_output = upload_result.stdout + upload_result.stderr
            auth_error_indicators = [
                "authentication",
                "token",
                "unauthorized",
                "401",
                "403",
                "access denied",
            ]
            auth_error_present = any(
                indicator in error_output.lower() for indicator in auth_error_indicators
            )
            assert auth_error_present, (
                f"Expected authentication error patterns in output: {error_output}"
            )

    @pytest.mark.timeout(90)
    def test_error_message_validation(
        self, gitlab_client, artifact_manager, project_path
    ):
        """
        Test error message validation for various error scenarios.

        Args:
            gitlab_client: GitLab test client fixture
            artifact_manager: Artifact manager fixture
            project_path: Project path fixture
        """
        # Set up GitLab client with project
        gitlab_client.set_project(project_path)

        # Test scenario 1: Non-existent file
        nonexistent_file = str(artifact_manager.base_dir / "nonexistent-file.txt")
        package_name = gitlab_client.create_test_package("error-msg", "1.0.0")

        # Get project arguments
        project_args = get_project_args(project_path)

        # Build command with non-existent file
        command = [
            "python",
            str(Path(__file__).parent.parent / "gitlab-pkg-upload.py"),
            "--package-name",
            package_name,
            "--package-version",
            "1.0.0",
            "--token",
            _get_gitlab_token(),
            "--json-output",
            "--files",
            nonexistent_file,
        ] + project_args

        # Create execution configuration expecting file not found error
        execution_config = UploadExecution(
            command=command,
            expected_exit_code=1,  # Expect failure
            expected_output_patterns=[],
            timeout=30,
            use_json_output=True,
        )

        # Execute upload (should fail due to missing file)
        executor = ScriptExecutor()
        upload_result = executor.execute_upload(execution_config)

        # Validate error message quality
        assert upload_result.exit_code != 0, (
            f"Expected upload to fail but got exit code: {upload_result.exit_code}"
        )

        # Validate JSON error fields if available
        if upload_result.json_data is not None:
            assert upload_result.json_data.get("success") is False, (
                "Expected success to be False"
            )
            assert "error" in upload_result.json_data, (
                "Expected error field in JSON output"
            )

            # Check for file-related keywords in error message
            error_msg = upload_result.json_data["error"].lower()
            file_keywords = ["file", "not found", "does not exist", "missing"]
            file_error_found = any(keyword in error_msg for keyword in file_keywords)
            assert file_error_found, (
                f"Expected file error keywords in JSON error: {upload_result.json_data['error']}"
            )

            # Check that error message is informative
            informative_error = (
                nonexistent_file.lower() in error_msg
                or "nonexistent-file.txt" in error_msg
                or any(word in error_msg for word in file_keywords)
            )
            assert informative_error, (
                f"Expected informative error message mentioning the file: {upload_result.json_data['error']}"
            )
        else:
            # Fallback to stderr/stdout checking for early script errors
            error_output = upload_result.stdout + upload_result.stderr
            file_error_patterns = [
                "file",
                "not found",
                "does not exist",
                "missing",
                "cannot find",
            ]
            file_error_found = any(
                pattern in error_output.lower() for pattern in file_error_patterns
            )
            assert file_error_found, (
                f"Expected file error patterns in output: {error_output}"
            )

            # Check that error message is informative
            informative_error = (
                nonexistent_file in error_output
                or "nonexistent-file.txt" in error_output
                or any(
                    word in error_output.lower()
                    for word in ["file", "path", "not found", "missing"]
                )
            )
            assert informative_error, (
                f"Expected informative error message mentioning the file: {error_output}"
            )

        # Test scenario 2: Invalid project path
        test_file = artifact_manager.create_test_file(
            filename="error-msg-test2.txt", size_bytes=512, content_pattern="text"
        )

        invalid_project_path = "invalid/nonexistent-project"

        # Build command with invalid project path
        command2 = [
            "python",
            str(Path(__file__).parent.parent / "gitlab-pkg-upload.py"),
            "--package-name",
            package_name,
            "--package-version",
            "1.0.1",
            "--project-path",
            invalid_project_path,
            "--token",
            _get_gitlab_token(),
            "--json-output",
            "--files",
            str(test_file.path),
        ]

        # Create execution configuration expecting project error
        execution_config2 = UploadExecution(
            command=command2,
            expected_exit_code=1,  # Expect failure
            expected_output_patterns=[],
            timeout=30,
            use_json_output=True,
        )

        # Execute upload (should fail due to invalid project)
        upload_result2 = executor.execute_upload(execution_config2)

        # Validate second error scenario
        assert upload_result2.exit_code != 0, (
            f"Expected upload to fail but got exit code: {upload_result2.exit_code}"
        )

        # Validate JSON error fields if available
        if upload_result2.json_data is not None:
            assert upload_result2.json_data.get("success") is False, (
                "Expected success to be False"
            )
            assert "error" in upload_result2.json_data, (
                "Expected error field in JSON output"
            )

            # Check for project-related keywords in error message
            error_msg2 = upload_result2.json_data["error"].lower()
            project_keywords = ["project", "404", "not found", "access", "invalid"]
            project_error_found = any(
                keyword in error_msg2 for keyword in project_keywords
            )
            assert project_error_found, (
                f"Expected project error keywords in JSON error: {upload_result2.json_data['error']}"
            )

            # Check that error message mentions the project path
            informative_error2 = invalid_project_path.lower() in error_msg2 or any(
                word in error_msg2 for word in project_keywords
            )
            assert informative_error2, (
                f"Expected informative error message mentioning the project: {upload_result2.json_data['error']}"
            )
        else:
            # Fallback to stderr/stdout checking for early script errors
            error_output2 = upload_result2.stdout + upload_result2.stderr
            project_error_patterns = [
                "project",
                "404",
                "not found",
                "access",
                "invalid",
            ]
            project_error_found = any(
                pattern in error_output2.lower() for pattern in project_error_patterns
            )
            assert project_error_found, (
                f"Expected project error patterns in output: {error_output2}"
            )

            # Check that error message mentions the project path
            informative_error2 = invalid_project_path in error_output2 or any(
                word in error_output2.lower()
                for word in ["project", "404", "not found", "access"]
            )
            assert informative_error2, (
                f"Expected informative error message mentioning the project: {error_output2}"
            )

    @pytest.mark.timeout(90)
    def test_failure_continuation_behavior(
        self, gitlab_client, artifact_manager, project_path
    ):
        """
        Test that the system continues processing after individual failures.

        Args:
            gitlab_client: GitLab test client fixture
            artifact_manager: Artifact manager fixture
            project_path: Project path fixture
        """
        # Set up GitLab client with project
        gitlab_client.set_project(project_path)

        # Create a mix of valid and invalid files for testing continuation behavior
        valid_file = artifact_manager.create_test_file(
            filename="valid-continuation-test.txt",
            size_bytes=1024,
            content_pattern="text",
        )

        nonexistent_file = str(
            artifact_manager.base_dir / "nonexistent-continuation-test.txt"
        )

        # Create unique package name
        package_name = gitlab_client.create_test_package(
            "failure-continuation", "1.0.0"
        )

        # Get project arguments
        project_args = get_project_args(project_path, gitlab_url=None)

        # Test multiple file upload with one invalid file
        # The upload script should handle the error gracefully and continue or report appropriately
        command = [
            "python",
            str(Path(__file__).parent.parent / "gitlab-pkg-upload.py"),
            "--package-name",
            package_name,
            "--package-version",
            "1.0.0",
            "--token",
            _get_gitlab_token(),
            "--json-output",
            "--files",
            str(valid_file.path),
            nonexistent_file,  # Mix of valid and invalid
        ] + project_args

        # Create execution configuration expecting failure but graceful handling
        execution_config = UploadExecution(
            command=command,
            expected_exit_code=1,  # Expect failure due to invalid file
            expected_output_patterns=[],
            timeout=60,
            use_json_output=True,
            env_vars={
                "GITLAB_TOKEN": ""
            },  # Clear GITLAB_TOKEN to force use of --token argument
        )

        # Execute upload (should fail but handle error gracefully)
        executor = ScriptExecutor()
        upload_result = executor.execute_upload(execution_config)

        # Validate failure continuation behavior
        assert upload_result.exit_code != 0, (
            f"Expected upload to fail but got exit code: {upload_result.exit_code}"
        )

        # Validate JSON error fields if available
        if upload_result.json_data is not None:
            assert upload_result.json_data.get("success") is False, (
                "Expected success to be False"
            )
            assert "failed_uploads" in upload_result.json_data, (
                "Expected failed_uploads field in JSON output"
            )

            # Check that the problematic file is mentioned in failed_uploads
            failed_uploads = upload_result.json_data.get("failed_uploads", [])
            file_mentioned = any(
                "nonexistent-continuation-test.txt" in str(item).lower()
                or "nonexistent" in str(item).lower()
                for item in failed_uploads
            )
            assert file_mentioned, (
                f"Expected problematic file in failed_uploads: {failed_uploads}"
            )
        else:
            # Fallback to stderr/stdout checking for early script errors
            error_output = upload_result.stdout + upload_result.stderr
            error_mentions_file = (
                "nonexistent-continuation-test.txt" in error_output
                or "nonexistent" in error_output.lower()
            )
            assert error_mentions_file, (
                f"Expected error to mention the problematic file: {error_output}"
            )

            # Check that the error is descriptive and doesn't just crash
            descriptive_error = any(
                word in error_output.lower()
                for word in ["file", "not found", "error", "failed", "missing"]
            )
            assert descriptive_error, (
                f"Expected descriptive error message: {error_output}"
            )

        # Test a second scenario: Invalid duplicate policy
        test_file2 = artifact_manager.create_test_file(
            filename="continuation-test2.txt", size_bytes=512, content_pattern="text"
        )

        # Build command with invalid duplicate policy
        command2 = [
            "python",
            str(Path(__file__).parent.parent / "gitlab-pkg-upload.py"),
            "--package-name",
            package_name,
            "--package-version",
            "1.0.1",
            "--duplicate-policy",
            "invalid-policy",  # Invalid policy
            "--token",
            _get_gitlab_token(),
            "--json-output",
            "--files",
            str(test_file2.path),
        ] + project_args

        # Create execution configuration expecting policy error
        execution_config2 = UploadExecution(
            command=command2,
            expected_exit_code=1,  # Expect failure
            expected_output_patterns=[],
            timeout=30,
            use_json_output=True,
        )

        # Execute upload (should fail due to invalid policy)
        upload_result2 = executor.execute_upload(execution_config2)

        # Validate second error scenario
        assert upload_result2.exit_code != 0, (
            f"Expected upload to fail but got exit code: {upload_result2.exit_code}"
        )

        # Validate JSON error fields if available
        if upload_result2.json_data is not None:
            assert upload_result2.json_data.get("success") is False, (
                "Expected success to be False"
            )
            assert "error" in upload_result2.json_data, (
                "Expected error field in JSON output"
            )

            # Check for policy-related keywords in error message
            error_msg2 = upload_result2.json_data["error"].lower()
            policy_keywords = ["policy", "invalid", "choice", "option"]
            policy_error_found = any(
                keyword in error_msg2 for keyword in policy_keywords
            )
            assert policy_error_found, (
                f"Expected policy error keywords in JSON error: {upload_result2.json_data['error']}"
            )
        else:
            # Fallback to stderr/stdout checking for early script errors
            error_output2 = upload_result2.stdout + upload_result2.stderr
            policy_error_mentioned = "invalid-policy" in error_output2 or any(
                word in error_output2.lower()
                for word in ["policy", "invalid", "choice", "option"]
            )
            assert policy_error_mentioned, (
                f"Expected policy error to be mentioned: {error_output2}"
            )

    @pytest.mark.timeout(90)
    def test_non_ascii_filename_rejection(
        self, gitlab_client, artifact_manager, project_path
    ):
        """
        Test that non-ASCII filenames are properly rejected with detailed error messages.

        Args:
            gitlab_client: GitLab test client fixture
            artifact_manager: Artifact manager fixture
            project_path: Project path fixture
        """
        # Set up GitLab client with project
        gitlab_client.set_project(project_path)

        # Create test file with ASCII filename
        test_file = artifact_manager.create_test_file(
            filename="unicode-名前.txt", size_bytes=1024, content_pattern="text"
        )

        # Create unique package name
        package_name = gitlab_client.create_test_package("non-ascii-test", "1.0.0")

        # Get project arguments
        project_args = get_project_args(project_path, gitlab_url=None)

        command = [
            "python",
            str(Path(__file__).parent.parent / "gitlab-pkg-upload.py"),
            "--package-name",
            package_name,
            "--package-version",
            "1.0.0",
            "--token",
            _get_gitlab_token(),
            "--json-output",
            "--files",
            f"{test_file.path}",
        ] + project_args

        # Create execution configuration expecting failure
        execution_config = UploadExecution(
            command=command,
            expected_exit_code=1,  # Expect failure
            expected_output_patterns=[],
            timeout=60,
            use_json_output=True,
            env_vars={
                "GITLAB_TOKEN": ""
            },  # Clear GITLAB_TOKEN to force use of --token argument
        )

        # Execute upload (should fail due to non-ASCII filename)
        executor = ScriptExecutor()
        upload_result = executor.execute_upload(execution_config)

        # Verify that it failed as expected
        assert upload_result.exit_code == 1, (
            f"Expected exit code 1, got {upload_result.exit_code}"
        )

        # Validate JSON error fields if available
        if upload_result.json_data is not None:
            assert upload_result.json_data.get("success") is False, (
                "Expected success to be False"
            )
            assert upload_result.json_data.get("exit_code") == 1, (
                "Expected exit_code to be 1"
            )
            assert "error" in upload_result.json_data, (
                "Expected error field in JSON output"
            )

            # Check for ASCII-related keywords in error message
            error_msg = upload_result.json_data["error"].lower()
            ascii_keywords = ["ascii", "non-ascii", "character"]
            ascii_error_found = any(keyword in error_msg for keyword in ascii_keywords)
            assert ascii_error_found, (
                f"Expected ASCII-related error keywords in JSON error: {upload_result.json_data['error']}"
            )

            # Check that error message mentions the problematic filename
            filename_mentioned = "名前" in upload_result.json_data["error"]
            assert filename_mentioned, (
                f"Expected error to mention the problematic filename: {upload_result.json_data['error']}"
            )

            # Check that error message suggests ASCII-only characters
            suggestion_keywords = [
                "letter",
                "digit",
                "dot",
                "hyphen",
                "underscore",
                "slash",
            ]
            suggestion_found = any(
                keyword in error_msg for keyword in suggestion_keywords
            )
            assert suggestion_found, (
                f"Expected error to suggest ASCII-only characters: {upload_result.json_data['error']}"
            )
        else:
            # Fallback to stderr/stdout checking for early script errors
            error_output = upload_result.stdout + upload_result.stderr
            ascii_error_patterns = ["ascii", "non-ascii", "character"]
            ascii_error_found = any(
                pattern in error_output.lower() for pattern in ascii_error_patterns
            )
            assert ascii_error_found, (
                f"Expected ASCII-related error patterns in output: {error_output}"
            )

            # Check that error message mentions the problematic filename
            filename_mentioned = "名前" in error_output
            assert filename_mentioned, (
                f"Expected error to mention the problematic filename: {error_output}"
            )


@pytest.mark.slow
@pytest.mark.timeout(90)
def test_non_ascii_filename_in_directory(gitlab_client, artifact_manager, project_path):
    """
    Test that non-ASCII filenames in directories are properly rejected.

    Args:
        gitlab_client: GitLab test client fixture
        artifact_manager: Artifact manager fixture
        project_path: Project path fixture
    """
    # Set up GitLab client with project
    gitlab_client.set_project(project_path)

    # Create a temporary directory
    test_dir = artifact_manager.base_dir / "non-ascii-dir-test"
    test_dir.mkdir(parents=True, exist_ok=True)

    # Create a file with non-ASCII filename directly
    non_ascii_filename = "unicode-测试文件.txt"
    non_ascii_file_path = test_dir / non_ascii_filename
    non_ascii_file_path.write_text("Test content with non-ASCII filename")

    # Create unique package name
    package_name = gitlab_client.create_test_package("non-ascii-dir", "1.0.0")

    # Get project arguments
    project_args = get_project_args(project_path, gitlab_url=None)

    # Build command to upload directory with non-ASCII filename
    command = [
        "python",
        str(Path(__file__).parent.parent / "gitlab-pkg-upload.py"),
        "--package-name",
        package_name,
        "--package-version",
        "1.0.0",
        "--token",
        _get_gitlab_token(),
        "--json-output",
        "--directory",
        str(test_dir),
    ] + project_args

    # Create execution configuration expecting failure
    execution_config = UploadExecution(
        command=command,
        expected_exit_code=1,  # Expect failure
        expected_output_patterns=[],
        timeout=60,
        use_json_output=True,
        env_vars={
            "GITLAB_TOKEN": ""
        },  # Clear GITLAB_TOKEN to force use of --token argument
    )

    # Execute upload (should fail due to non-ASCII filename)
    executor = ScriptExecutor()
    upload_result = executor.execute_upload(execution_config)

    # Verify that it failed as expected
    assert upload_result.exit_code == 1, (
        f"Expected exit code 1, got {upload_result.exit_code}"
    )

    # Validate JSON error fields if available
    if upload_result.json_data is not None:
        assert upload_result.json_data.get("success") is False, (
            "Expected success to be False"
        )
        assert "error" in upload_result.json_data, "Expected error field in JSON output"

        # Check that error message mentions the specific non-ASCII filename
        error_msg = upload_result.json_data["error"]
        filename_mentioned = (
            non_ascii_filename in error_msg
            or "测试文件" in error_msg
            or "unicode-" in error_msg.lower()
        )
        assert filename_mentioned, (
            f"Expected error to mention the specific non-ASCII filename: {error_msg}"
        )

        # Check for ASCII-related keywords
        ascii_keywords = ["ascii", "non-ascii", "character"]
        ascii_error_found = any(
            keyword in error_msg.lower() for keyword in ascii_keywords
        )
        assert ascii_error_found, (
            f"Expected ASCII-related error keywords in JSON error: {error_msg}"
        )
    else:
        # Fallback to stderr/stdout checking
        error_output = upload_result.stdout + upload_result.stderr
        filename_mentioned = (
            non_ascii_filename in error_output or "测试文件" in error_output
        )
        assert filename_mentioned, (
            f"Expected error to mention the specific non-ASCII filename: {error_output}"
        )


@pytest.mark.timeout(120)
def test_mixed_ascii_non_ascii_filenames(gitlab_client, artifact_manager, project_path):
    """
    Test that mixed ASCII and non-ASCII filenames are handled correctly.

    Args:
        gitlab_client: GitLab test client fixture
        artifact_manager: Artifact manager fixture
        project_path: Project path fixture
    """
    # Set up GitLab client with project
    gitlab_client.set_project(project_path)

    # Create multiple test files: some with ASCII names, some with non-ASCII names
    ascii_file1 = artifact_manager.create_test_file(
        filename="ascii-file1.txt", size_bytes=512, content_pattern="text"
    )
    ascii_file2 = artifact_manager.create_test_file(
        filename="ascii-file2.txt", size_bytes=512, content_pattern="text"
    )

    # Create files with non-ASCII names
    test_dir = artifact_manager.base_dir / "mixed-test"
    test_dir.mkdir(parents=True, exist_ok=True)

    non_ascii_file1 = test_dir / "unicode-名前.txt"
    non_ascii_file1.write_text("Non-ASCII content 1")

    non_ascii_file2 = test_dir / "unicode-测试.txt"
    non_ascii_file2.write_text("Non-ASCII content 2")

    # Create unique package name
    package_name = gitlab_client.create_test_package("mixed-ascii", "1.0.0")

    # Get project arguments
    project_args = get_project_args(project_path, gitlab_url=None)

    # Build command to upload all files together
    command = [
        "python",
        str(Path(__file__).parent.parent / "gitlab-pkg-upload.py"),
        "--package-name",
        package_name,
        "--package-version",
        "1.0.0",
        "--token",
        _get_gitlab_token(),
        "--json-output",
        "--files",
        str(ascii_file1.path),
        str(ascii_file2.path),
        str(non_ascii_file1),
        str(non_ascii_file2),
    ] + project_args

    # Create execution configuration expecting failure
    execution_config = UploadExecution(
        command=command,
        expected_exit_code=1,  # Expect failure
        expected_output_patterns=[],
        timeout=90,
        use_json_output=True,
        env_vars={
            "GITLAB_TOKEN": ""
        },  # Clear GITLAB_TOKEN to force use of --token argument
    )

    # Execute upload (should fail due to non-ASCII filenames)
    executor = ScriptExecutor()
    upload_result = executor.execute_upload(execution_config)

    # Verify that it failed as expected
    assert upload_result.exit_code == 1, (
        f"Expected exit code 1, got {upload_result.exit_code}"
    )

    # Validate JSON error fields if available
    if upload_result.json_data is not None:
        assert upload_result.json_data.get("success") is False, (
            "Expected success to be False"
        )
        assert "error" in upload_result.json_data, "Expected error field in JSON output"

        error_msg = upload_result.json_data["error"]

        # Check that error identifies non-ASCII filenames
        non_ascii_mentioned = (
            "名前" in error_msg
            or "测试" in error_msg
            or "unicode-" in error_msg.lower()
        )
        assert non_ascii_mentioned, (
            f"Expected error to identify non-ASCII filenames: {error_msg}"
        )

        # Check that ASCII files are not mentioned in the error
        # (or if mentioned, it's clear they're not the problem)
        ascii_file_names = ["ascii-file1.txt", "ascii-file2.txt"]
        if any(name in error_msg for name in ascii_file_names):
            # If ASCII files are mentioned, ensure the error is clear about which files are problematic
            clear_about_problem = any(
                keyword in error_msg.lower()
                for keyword in ["non-ascii", "invalid", "problematic"]
            )
            assert clear_about_problem, (
                f"Expected error to be clear about which files are problematic: {error_msg}"
            )
    else:
        # Fallback to stderr/stdout checking
        error_output = upload_result.stdout + upload_result.stderr
        non_ascii_mentioned = "名前" in error_output or "测试" in error_output
        assert non_ascii_mentioned, (
            f"Expected error to identify non-ASCII filenames: {error_output}"
        )
