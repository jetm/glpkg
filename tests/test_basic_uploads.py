"""
Basic upload functionality tests for GitLab package upload script.

This module contains tests for basic upload scenarios extracted from the
monolithic test file. It validates single file uploads, multiple file uploads,
directory uploads, and file mapping functionality using pytest framework.
"""

import os

import pytest

from .utils.test_helpers import (
    ScriptExecutor,
    UploadExecution,
    get_project_args,
    validate_json_result,
)

# Test markers for categorization
pytestmark = [
    pytest.mark.integration,  # These are integration tests
    pytest.mark.api,  # These require GitLab API access
    pytest.mark.slow,  # These tests take longer to run due to real API calls
]


def _get_gitlab_token():
    """Get GitLab token from environment with proper error handling."""
    token = os.environ.get("GITLAB_TOKEN")
    if not token:
        pytest.skip("GITLAB_TOKEN environment variable not set")
    return token


class TestBasicUploads:
    """
    Test class for basic upload functionality.

    Extracted and adapted from TestOrchestrator._test_single_file_upload,
    _test_multiple_file_upload, _test_directory_upload, and
    _test_file_mapping_upload methods.
    """

    @pytest.mark.timeout(180)
    def test_single_file_upload(self, gitlab_client, artifact_manager, project_path):
        """
        Test single file upload functionality using subprocess execution of upload script.

        Args:
            gitlab_client: GitLab test client fixture
            artifact_manager: Artifact manager fixture
            project_path: Project path fixture
        """
        # Set up GitLab client with project
        gitlab_client.set_project(project_path)

        # Create test file
        test_file = artifact_manager.create_test_file(
            filename="single-test.txt", size_bytes=1024, content_pattern="text"
        )

        # Create unique package name
        package_name = gitlab_client.create_test_package("single-file", "1.0.0")

        executor = ScriptExecutor()
        upload_execution = UploadExecution(
            command=[
                str(executor.script_path),
                "--package-name",
                package_name,
                "--package-version",
                "1.0.0",
                "--files",
                str(test_file.path),
                "--json-output",
            ]
            + get_project_args(project_path),
            expected_exit_code=0,
            expected_output_patterns=[],
            timeout=120,
            use_json_output=True,
        )

        # Add GitLab token to environment
        upload_execution.env_vars = {"GITLAB_TOKEN": _get_gitlab_token()}

        upload_result = executor.execute_upload(upload_execution)

        # Validate JSON output is present
        assert upload_result.json_data is not None, "JSON output not found in result"

        # Use helper function for structural validation
        assert validate_json_result(
            upload_result.json_data,
            expected_success=True,
            expected_files=[str(test_file.path)],
        ), "JSON validation failed"

        # Validate specific fields
        assert upload_result.json_data["success"] is True
        assert upload_result.json_data["package_name"] == package_name
        assert upload_result.json_data["version"] == "1.0.0"
        assert upload_result.json_data["statistics"]["new_uploads"] == 1
        assert upload_result.json_data["statistics"]["failed_uploads"] == 0
        assert len(upload_result.json_data["successful_uploads"]) == 1

        # Validate upload script execution succeeded
        assert upload_result.exit_code == 0, (
            f"Unexpected exit code: {upload_result.exit_code}"
        )

        registry_verification = gitlab_client.verify_upload(
            package_name, "1.0.0", test_file.path.name, test_file.checksum
        )

        assert registry_verification, (
            "Upload verification failed - file not found in GitLab registry"
        )

    @pytest.mark.timeout(180)
    def test_multiple_file_upload(self, gitlab_client, artifact_manager, project_path):
        """
        Test multiple file upload functionality using subprocess execution.

        Args:
            gitlab_client: GitLab test client fixture
            artifact_manager: Artifact manager fixture
            project_path: Project path fixture
        """
        # Set up GitLab client with project
        gitlab_client.set_project(project_path)

        # Create multiple test files with different characteristics
        test_files = [
            artifact_manager.create_test_file("multi-1.txt", 512, "text"),
            artifact_manager.create_test_file("multi-2.json", 1024, "json"),
            artifact_manager.create_test_file("multi-3.bin", 2048, "binary"),
        ]

        # Create unique package name
        package_name = gitlab_client.create_test_package("multi-file", "1.0.0")

        file_paths = [str(f.path) for f in test_files]
        executor = ScriptExecutor()
        upload_execution = UploadExecution(
            command=[
                str(executor.script_path),
                "--package-name",
                package_name,
                "--package-version",
                "1.0.0",
                "--files",
            ]
            + file_paths
            + ["--json-output"]
            + get_project_args(project_path),
            expected_exit_code=0,
            expected_output_patterns=[],
            timeout=180,
            use_json_output=True,
        )

        # Add GitLab token to environment
        upload_execution.env_vars = {"GITLAB_TOKEN": _get_gitlab_token()}

        upload_result = executor.execute_upload(upload_execution)

        # Validate JSON output is present
        assert upload_result.json_data is not None, "JSON output not found in result"

        # Use helper function for structural validation
        assert validate_json_result(
            upload_result.json_data,
            expected_success=True,
            expected_files=file_paths,
        ), "JSON validation failed"

        # Validate specific fields
        assert upload_result.json_data["success"] is True
        assert upload_result.json_data["statistics"]["new_uploads"] == 3
        assert upload_result.json_data["statistics"]["failed_uploads"] == 0
        assert len(upload_result.json_data["successful_uploads"]) == 3

        # Verify each test file appears in successful_uploads
        uploaded_filenames = [
            upload["target_filename"]
            for upload in upload_result.json_data["successful_uploads"]
        ]
        for test_file in test_files:
            assert test_file.path.name in uploaded_filenames, (
                f"File {test_file.path.name} not found in successful uploads"
            )

        # Validate upload script execution succeeded
        assert upload_result.exit_code == 0, (
            f"Unexpected exit code: {upload_result.exit_code}"
        )

        registry_failures = []
        for test_file in test_files:
            registry_verification = gitlab_client.verify_upload(
                package_name, "1.0.0", test_file.path.name, test_file.checksum
            )
            if not registry_verification:
                registry_failures.append(test_file.path.name)

        assert not registry_failures, (
            f"Registry verification failed for files: {', '.join(registry_failures)}"
        )

    @pytest.mark.timeout(180)
    def test_directory_upload(self, gitlab_client, artifact_manager, project_path):
        """
        Test directory upload functionality using subprocess execution.

        Args:
            gitlab_client: GitLab test client fixture
            artifact_manager: Artifact manager fixture
            project_path: Project path fixture
        """
        # Set up GitLab client with project
        gitlab_client.set_project(project_path)

        # Create test directory with files
        test_files = artifact_manager.create_test_directory("upload-dir", 4)
        directory_path = artifact_manager.base_dir / "upload-dir"

        # Create unique package name
        package_name = gitlab_client.create_test_package("directory", "1.0.0")

        executor = ScriptExecutor()
        upload_execution = UploadExecution(
            command=[
                str(executor.script_path),
                "--package-name",
                package_name,
                "--package-version",
                "1.0.0",
                "--directory",
                str(directory_path),
                "--json-output",
            ]
            + get_project_args(project_path),
            expected_exit_code=0,
            expected_output_patterns=[],
            timeout=180,
            use_json_output=True,
        )

        # Add GitLab token to environment
        upload_execution.env_vars = {"GITLAB_TOKEN": _get_gitlab_token()}

        upload_result = executor.execute_upload(upload_execution)

        # Validate JSON output is present
        assert upload_result.json_data is not None, "JSON output not found in result"

        # Use helper function for structural validation
        assert validate_json_result(
            upload_result.json_data,
            expected_success=True,
            expected_files=[str(f.path) for f in test_files],
        ), "JSON validation failed"

        # Validate specific fields
        assert upload_result.json_data["success"] is True
        assert upload_result.json_data["statistics"]["new_uploads"] == 4
        assert upload_result.json_data["statistics"]["failed_uploads"] == 0
        assert len(upload_result.json_data["successful_uploads"]) == 4

        # Verify all directory files appear in successful_uploads
        uploaded_filenames = [
            upload["target_filename"]
            for upload in upload_result.json_data["successful_uploads"]
        ]
        for test_file in test_files:
            assert test_file.path.name in uploaded_filenames, (
                f"File {test_file.path.name} not found in successful uploads"
            )

        # Validate upload script execution succeeded
        assert upload_result.exit_code == 0, (
            f"Unexpected exit code: {upload_result.exit_code}"
        )

        registry_failures = []
        for test_file in test_files:
            registry_verification = gitlab_client.verify_upload(
                package_name, "1.0.0", test_file.path.name, test_file.checksum
            )
            if not registry_verification:
                registry_failures.append(test_file.path.name)

        assert not registry_failures, (
            f"Registry verification failed for files: {', '.join(registry_failures)}"
        )

    @pytest.mark.timeout(180)
    def test_file_mapping_upload(self, gitlab_client, artifact_manager, project_path):
        """
        Test file mapping upload functionality with custom target names using subprocess execution.

        Args:
            gitlab_client: GitLab test client fixture
            artifact_manager: Artifact manager fixture
            project_path: Project path fixture
        """
        # Set up GitLab client with project
        gitlab_client.set_project(project_path)

        # Create test files
        test_files = [
            artifact_manager.create_test_file("source1.txt", 1024, "text"),
            artifact_manager.create_test_file("source2.json", 2048, "json"),
        ]

        # Create unique package name
        package_name = gitlab_client.create_test_package("file-mapping", "1.0.0")

        executor = ScriptExecutor()
        upload_execution = UploadExecution(
            command=[
                str(executor.script_path),
                "--package-name",
                package_name,
                "--package-version",
                "1.0.0",
                "--files",
                str(test_files[0].path),
                str(test_files[1].path),
                "--file-mapping",
                f"{test_files[0].path.name}:target1.txt",
                "--file-mapping",
                f"{test_files[1].path.name}:config/target2.json",
                "--json-output",
            ]
            + get_project_args(project_path),
            expected_exit_code=0,
            expected_output_patterns=[],
            timeout=180,
            use_json_output=True,
        )

        # Add GitLab token to environment
        upload_execution.env_vars = {"GITLAB_TOKEN": _get_gitlab_token()}

        upload_result = executor.execute_upload(upload_execution)

        # Validate JSON output is present
        assert upload_result.json_data is not None, "JSON output not found in result"

        # Use helper function for structural validation
        assert validate_json_result(
            upload_result.json_data,
            expected_success=True,
        ), "JSON validation failed"

        # Validate specific fields
        assert upload_result.json_data["success"] is True
        assert upload_result.json_data["statistics"]["new_uploads"] == 2
        assert len(upload_result.json_data["successful_uploads"]) == 2

        # Verify mapped filenames appear in successful_uploads
        uploaded_filenames = [
            upload["target_filename"]
            for upload in upload_result.json_data["successful_uploads"]
        ]
        assert "target1.txt" in uploaded_filenames, (
            "Mapped file target1.txt not found in successful uploads"
        )
        assert "config/target2.json" in uploaded_filenames, (
            "Mapped file config/target2.json not found in successful uploads"
        )

        # Validate upload script execution succeeded
        assert upload_result.exit_code == 0, (
            f"Unexpected exit code: {upload_result.exit_code}"
        )

        target_mappings = [
            ("target1.txt", test_files[0].checksum),
            ("config/target2.json", test_files[1].checksum),
        ]

        registry_failures = []
        for target_filename, expected_checksum in target_mappings:
            registry_verification = gitlab_client.verify_upload(
                package_name, "1.0.0", target_filename, expected_checksum
            )
            if not registry_verification:
                registry_failures.append(target_filename)

        assert not registry_failures, (
            f"Registry verification failed for mapped files: {', '.join(registry_failures)}"
        )


# Additional test functions for edge cases and specific scenarios


@pytest.mark.slow
@pytest.mark.timeout(180)
def test_large_file_upload(gitlab_client, artifact_manager, project_path):
    """
    Test upload of a larger file to ensure the script handles various file sizes.

    Args:
        gitlab_client: GitLab test client fixture
        artifact_manager: Artifact manager fixture
        project_path: Project path fixture
    """
    # Set up GitLab client with project
    gitlab_client.set_project(project_path)

    # Create a larger test file (10KB)
    test_file = artifact_manager.create_test_file(
        filename="large-test.bin", size_bytes=10240, content_pattern="binary"
    )

    # Create unique package name
    package_name = gitlab_client.create_test_package("large-file", "1.0.0")

    # Execute upload script
    executor = ScriptExecutor()
    upload_execution = UploadExecution(
        command=[
            str(executor.script_path),
            "--package-name",
            package_name,
            "--package-version",
            "1.0.0",
            "--files",
            str(test_file.path),
            "--json-output",
        ]
        + get_project_args(project_path),
        expected_exit_code=0,
        expected_output_patterns=[],
        timeout=180,  # Longer timeout for larger file
        use_json_output=True,
    )

    upload_execution.env_vars = {"GITLAB_TOKEN": _get_gitlab_token()}
    upload_result = executor.execute_upload(upload_execution)

    # Validate JSON output is present
    assert upload_result.json_data is not None, "JSON output not found in result"

    # Use helper function for structural validation
    assert validate_json_result(
        upload_result.json_data,
        expected_success=True,
        expected_files=[str(test_file.path)],
    ), "JSON validation failed"

    # Validate specific fields
    assert upload_result.json_data["success"] is True
    assert upload_result.json_data["statistics"]["new_uploads"] == 1
    assert upload_result.json_data["statistics"]["failed_uploads"] == 0

    # Validate results
    assert upload_result.exit_code == 0, (
        f"Unexpected exit code: {upload_result.exit_code}"
    )

    # Verify in GitLab registry
    registry_verification = gitlab_client.verify_upload(
        package_name, "1.0.0", test_file.path.name, test_file.checksum
    )
    assert registry_verification, "Large file verification failed in GitLab registry"
