"""
Error scenario integration tests using direct module invocation.

This module tests network failures, authentication errors, error message
validation, failure continuation behavior, and non-ASCII filename rejection
by calling the CLI main() function directly.
"""

import os

import pytest

from .test_helpers_module import (
    ModuleExecutor,
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
    Test class for error scenario handling using direct module invocation.
    """

    @pytest.mark.timeout(90)
    def test_network_failure_simulation(
        self, gitlab_client, artifact_manager, project_path
    ):
        """
        Test network failure simulation with invalid GitLab URL.

        Args:
            gitlab_client: GitLab test client fixture
            artifact_manager: Artifact manager fixture
            project_path: Project path fixture
        """
        # Set up GitLab client with project
        gitlab_client.set_project(project_path)

        # Create test file
        test_file = artifact_manager.create_test_file(
            "network-test-module.txt", size_bytes=1024, content_pattern="text"
        )

        # Create unique package name
        package_name = gitlab_client.create_test_package("network-failure-module", "1.0.0")

        executor = ModuleExecutor()

        # Build argv with invalid GitLab URL to simulate network failure
        argv = [
            "--package-name", package_name,
            "--package-version", "1.0.0",
            "--gitlab-url", "https://invalid-gitlab-url.example.com",
            "--project-path", project_path,
            "--token", _get_gitlab_token(),
            "--files", str(test_file.path),
            "--json-output",
        ]

        # Execute upload (should fail due to network issues)
        upload_result = executor.execute_upload(
            argv=argv,
            env_vars={"GITLAB_TOKEN": ""},  # Clear GITLAB_TOKEN to force use of --token argument
            expected_exit_code=1,
            use_json_output=True,
        )

        # Verify that it failed as expected
        assert upload_result.exit_code == 1, (
            f"Expected exit code 1, got {upload_result.exit_code}"
        )

        # Validate JSON error fields if available
        if upload_result.json_data is not None:
            assert upload_result.json_data.get("success") is False
            assert upload_result.json_data.get("exit_code") == 1
            assert "error" in upload_result.json_data
            assert "error_type" in upload_result.json_data

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
            # Fallback to stderr/stdout checking for early errors
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
            filename="auth-error-module.txt", size_bytes=1024, content_pattern="text"
        )

        # Create unique package name
        package_name = gitlab_client.create_test_package("auth-error-module", "1.0.0")

        executor = ModuleExecutor()

        # Build argv with invalid token
        invalid_token = "invalid-token-that-should-fail-authentication"
        argv = [
            "--package-name", package_name,
            "--package-version", "1.0.0",
            "--project-path", project_path,
            "--token", invalid_token,
            "--files", str(test_file.path),
            "--json-output",
        ]

        # Execute upload (should fail due to authentication issues)
        upload_result = executor.execute_upload(
            argv=argv,
            env_vars={"GITLAB_TOKEN": ""},  # Clear GITLAB_TOKEN to force use of --token argument
            expected_exit_code=1,
            use_json_output=True,
        )

        # Validate that the upload failed as expected
        assert upload_result.exit_code != 0, (
            f"Expected upload to fail but got exit code: {upload_result.exit_code}"
        )

        # Validate JSON error fields if available
        if upload_result.json_data is not None:
            assert upload_result.json_data.get("success") is False
            assert upload_result.json_data.get("exit_code") != 0
            assert "error" in upload_result.json_data
            assert "error_type" in upload_result.json_data

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
            # Fallback to stderr/stdout checking for early errors
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

        executor = ModuleExecutor()

        # Test scenario 1: Non-existent file
        nonexistent_file = str(artifact_manager.base_dir / "nonexistent-module-file.txt")
        package_name = gitlab_client.create_test_package("error-msg-module", "1.0.0")

        # Build argv with non-existent file
        argv = executor.build_argv(
            package_name=package_name,
            version="1.0.0",
            files=[nonexistent_file],
            project_path=project_path,
            json_output=True,
        )

        # Execute upload (should fail due to missing file)
        upload_result = executor.execute_upload(
            argv=argv,
            env_vars={"GITLAB_TOKEN": _get_gitlab_token()},
            expected_exit_code=1,
            use_json_output=True,
        )

        # Validate error message quality
        assert upload_result.exit_code != 0, (
            f"Expected upload to fail but got exit code: {upload_result.exit_code}"
        )

        # Validate JSON error fields if available
        if upload_result.json_data is not None:
            assert upload_result.json_data.get("success") is False
            assert "error" in upload_result.json_data

            # Check for file-related keywords in error message
            error_msg = upload_result.json_data["error"].lower()
            file_keywords = ["file", "not found", "does not exist", "missing"]
            file_error_found = any(keyword in error_msg for keyword in file_keywords)
            assert file_error_found, (
                f"Expected file error keywords in JSON error: {upload_result.json_data['error']}"
            )
        else:
            # Fallback to stderr/stdout checking for early errors
            error_output = upload_result.stdout + upload_result.stderr
            file_error_patterns = [
                "file",
                "not found",
                "does not exist",
                "missing",
            ]
            file_error_found = any(
                pattern in error_output.lower() for pattern in file_error_patterns
            )
            assert file_error_found, (
                f"Expected file error patterns in output: {error_output}"
            )

        # Test scenario 2: Invalid project path
        test_file = artifact_manager.create_test_file(
            filename="error-msg-test2-module.txt", size_bytes=512, content_pattern="text"
        )

        invalid_project_path = "invalid/nonexistent-project"

        # Build argv with invalid project path
        argv2 = executor.build_argv(
            package_name=package_name,
            version="1.0.1",
            files=[str(test_file.path)],
            project_path=invalid_project_path,
            json_output=True,
        )

        # Execute upload (should fail due to invalid project)
        upload_result2 = executor.execute_upload(
            argv=argv2,
            env_vars={"GITLAB_TOKEN": _get_gitlab_token()},
            expected_exit_code=1,
            use_json_output=True,
        )

        # Validate second error scenario
        assert upload_result2.exit_code != 0, (
            f"Expected upload to fail but got exit code: {upload_result2.exit_code}"
        )

        # Validate JSON error fields if available
        if upload_result2.json_data is not None:
            assert upload_result2.json_data.get("success") is False
            assert "error" in upload_result2.json_data

            # Check for project-related keywords in error message
            error_msg2 = upload_result2.json_data["error"].lower()
            project_keywords = ["project", "404", "not found", "access", "invalid"]
            project_error_found = any(
                keyword in error_msg2 for keyword in project_keywords
            )
            assert project_error_found, (
                f"Expected project error keywords in JSON error: {upload_result2.json_data['error']}"
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
            filename="valid-continuation-module.txt",
            size_bytes=1024,
            content_pattern="text",
        )

        nonexistent_file = str(
            artifact_manager.base_dir / "nonexistent-continuation-module.txt"
        )

        # Create unique package name
        package_name = gitlab_client.create_test_package(
            "failure-continuation-module", "1.0.0"
        )

        executor = ModuleExecutor()

        # Test multiple file upload with one invalid file
        argv = [
            "--package-name", package_name,
            "--package-version", "1.0.0",
            "--project-path", project_path,
            "--files", str(valid_file.path), nonexistent_file,
            "--json-output",
        ]

        # Execute upload (should fail due to invalid file)
        upload_result = executor.execute_upload(
            argv=argv,
            env_vars={"GITLAB_TOKEN": _get_gitlab_token()},
            expected_exit_code=1,
            use_json_output=True,
        )

        # Validate failure continuation behavior
        assert upload_result.exit_code != 0, (
            f"Expected upload to fail but got exit code: {upload_result.exit_code}"
        )

        # Validate JSON error fields if available
        if upload_result.json_data is not None:
            assert upload_result.json_data.get("success") is False
            assert "failed_uploads" in upload_result.json_data

            # Check that the problematic file is mentioned in failed_uploads
            failed_uploads = upload_result.json_data.get("failed_uploads", [])
            file_mentioned = any(
                "nonexistent-continuation-module.txt" in str(item).lower()
                or "nonexistent" in str(item).lower()
                for item in failed_uploads
            )
            assert file_mentioned, (
                f"Expected problematic file in failed_uploads: {failed_uploads}"
            )
        else:
            # Fallback to stderr/stdout checking for early errors
            error_output = upload_result.stdout + upload_result.stderr
            error_mentions_file = (
                "nonexistent-continuation-module.txt" in error_output
                or "nonexistent" in error_output.lower()
            )
            assert error_mentions_file, (
                f"Expected error to mention the problematic file: {error_output}"
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

        # Create test file with non-ASCII filename
        test_file = artifact_manager.create_test_file(
            filename="unicode-名前-module.txt", size_bytes=1024, content_pattern="text"
        )

        # Create unique package name
        package_name = gitlab_client.create_test_package("non-ascii-module", "1.0.0")

        executor = ModuleExecutor()

        # Build argv
        argv = executor.build_argv(
            package_name=package_name,
            version="1.0.0",
            files=[str(test_file.path)],
            project_path=project_path,
            json_output=True,
        )

        # Execute upload (should fail due to non-ASCII filename)
        upload_result = executor.execute_upload(
            argv=argv,
            env_vars={"GITLAB_TOKEN": _get_gitlab_token()},
            expected_exit_code=1,
            use_json_output=True,
        )

        # Verify that it failed as expected
        assert upload_result.exit_code == 1, (
            f"Expected exit code 1, got {upload_result.exit_code}"
        )

        # Validate JSON error fields if available
        if upload_result.json_data is not None:
            assert upload_result.json_data.get("success") is False
            assert upload_result.json_data.get("exit_code") == 1
            assert "error" in upload_result.json_data

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
        else:
            # Fallback to stderr/stdout checking for early errors
            error_output = upload_result.stdout + upload_result.stderr
            ascii_error_patterns = ["ascii", "non-ascii", "character"]
            ascii_error_found = any(
                pattern in error_output.lower() for pattern in ascii_error_patterns
            )
            assert ascii_error_found, (
                f"Expected ASCII-related error patterns in output: {error_output}"
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
    test_dir = artifact_manager.base_dir / "non-ascii-dir-module"
    test_dir.mkdir(parents=True, exist_ok=True)

    # Create a file with non-ASCII filename directly
    non_ascii_filename = "unicode-测试文件-module.txt"
    non_ascii_file_path = test_dir / non_ascii_filename
    non_ascii_file_path.write_text("Test content with non-ASCII filename")

    # Create unique package name
    package_name = gitlab_client.create_test_package("non-ascii-dir-module", "1.0.0")

    executor = ModuleExecutor()

    # Build argv to upload directory with non-ASCII filename
    argv = executor.build_argv(
        package_name=package_name,
        version="1.0.0",
        directory=str(test_dir),
        project_path=project_path,
        json_output=True,
    )

    # Execute upload (should fail due to non-ASCII filename)
    upload_result = executor.execute_upload(
        argv=argv,
        env_vars={"GITLAB_TOKEN": _get_gitlab_token()},
        expected_exit_code=1,
        use_json_output=True,
    )

    # Verify that it failed as expected
    assert upload_result.exit_code == 1, (
        f"Expected exit code 1, got {upload_result.exit_code}"
    )

    # Validate JSON error fields if available
    if upload_result.json_data is not None:
        assert upload_result.json_data.get("success") is False
        assert "error" in upload_result.json_data

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
        filename="ascii-module-1.txt", size_bytes=512, content_pattern="text"
    )
    ascii_file2 = artifact_manager.create_test_file(
        filename="ascii-module-2.txt", size_bytes=512, content_pattern="text"
    )

    # Create files with non-ASCII names
    test_dir = artifact_manager.base_dir / "mixed-module-test"
    test_dir.mkdir(parents=True, exist_ok=True)

    non_ascii_file1 = test_dir / "unicode-名前-module.txt"
    non_ascii_file1.write_text("Non-ASCII content 1")

    non_ascii_file2 = test_dir / "unicode-测试-module.txt"
    non_ascii_file2.write_text("Non-ASCII content 2")

    # Create unique package name
    package_name = gitlab_client.create_test_package("mixed-ascii-module", "1.0.0")

    executor = ModuleExecutor()

    # Build argv to upload all files together
    argv = [
        "--package-name", package_name,
        "--package-version", "1.0.0",
        "--project-path", project_path,
        "--files",
        str(ascii_file1.path),
        str(ascii_file2.path),
        str(non_ascii_file1),
        str(non_ascii_file2),
        "--json-output",
    ]

    # Execute upload (should fail due to non-ASCII filenames)
    upload_result = executor.execute_upload(
        argv=argv,
        env_vars={"GITLAB_TOKEN": _get_gitlab_token()},
        expected_exit_code=1,
        use_json_output=True,
    )

    # Verify that it failed as expected
    assert upload_result.exit_code == 1, (
        f"Expected exit code 1, got {upload_result.exit_code}"
    )

    # Validate JSON error fields if available
    if upload_result.json_data is not None:
        assert upload_result.json_data.get("success") is False
        assert "error" in upload_result.json_data

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
    else:
        # Fallback to stderr/stdout checking
        error_output = upload_result.stdout + upload_result.stderr
        non_ascii_mentioned = "名前" in error_output or "测试" in error_output
        assert non_ascii_mentioned, (
            f"Expected error to identify non-ASCII filenames: {error_output}"
        )
