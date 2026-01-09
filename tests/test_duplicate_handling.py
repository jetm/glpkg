"""
Duplicate handling policy tests for GitLab package upload script.

This module contains tests for duplicate handling policies extracted from the
monolithic test file. It validates skip, replace, and error duplicate policies
using pytest framework with real GitLab API interactions.
"""

import os
import time

import pytest

from .utils.test_helpers import (
    ScriptExecutor,
    UploadExecution,
    get_project_args,
    validate_json_result,
)


def _validate_upload_consistency(
    gitlab_client,
    package_name: str,
    version: str,
    filename: str,
    expected_checksum: str,
) -> bool:
    """
    Validate upload results using the same logic as the upload script.

    Args:
        gitlab_client: GitLab test client
        package_name: Name of the uploaded package
        version: Package version
        filename: Name of the uploaded file
        expected_checksum: Expected SHA256 checksum

    Returns:
        True if validation succeeds using upload script logic, False otherwise
    """
    try:
        # Step 1: Verify file exists in registry (same as upload script verification)
        if not gitlab_client.verify_upload(
            package_name, version, filename, expected_checksum
        ):
            return False

        # Step 2: Verify download URL is accessible (same as upload script URL generation)
        download_url = gitlab_client.get_download_url(package_name, version, filename)
        if not download_url:
            return False

        # Step 3: Verify downloaded content matches expected checksum (same as upload script validation)
        if not gitlab_client.download_and_verify(
            package_name, version, filename, expected_checksum
        ):
            return False

        return True

    except Exception:
        return False


def _validate_duplicate_behavior(
    upload_result, expected_behavior: str, json_data=None
) -> bool:
    """
    Validate that the upload result indicates the expected duplicate handling behavior.

    Args:
        upload_result: Result from script execution
        expected_behavior: Expected behavior ("skip", "replace", "error")
        json_data: Optional JSON data for structured validation

    Returns:
        True if behavior is indicated in output or JSON, False otherwise
    """
    # If JSON data is provided, use structured validation
    if json_data is not None:
        if expected_behavior == "skip":
            # Check for skip indicators in JSON
            stats = json_data.get("statistics", {})
            skipped_list = json_data.get("skipped_duplicates", [])
            successful = json_data.get("successful_uploads", [])

            # Check if any files were skipped
            if stats.get("skipped_duplicates", 0) > 0:
                return True
            if len(skipped_list) > 0:
                return True
            # Check if any successful upload was marked as skipped duplicate
            for upload in successful:
                if (
                    upload.get("was_duplicate")
                    and upload.get("duplicate_action") == "skipped"
                ):
                    return True
            return False

        elif expected_behavior == "replace":
            # Check for replace indicators in JSON
            stats = json_data.get("statistics", {})
            successful = json_data.get("successful_uploads", [])

            # Check if any files were replaced
            if stats.get("replaced_duplicates", 0) > 0:
                return True
            # Check if any successful upload was marked as replaced duplicate
            for upload in successful:
                if (
                    upload.get("was_duplicate")
                    and upload.get("duplicate_action") == "replaced"
                ):
                    return True
            return False

        elif expected_behavior == "error":
            # Check for error indicators in JSON
            failed = json_data.get("failed_uploads", [])
            success = json_data.get("success", True)

            # Check if upload failed
            if not success:
                return True
            if len(failed) > 0:
                # Check if error message mentions duplicates
                for failure in failed:
                    error_msg = failure.get("error_message", "").lower()
                    if "duplicate" in error_msg or "already exists" in error_msg:
                        return True
            return False

    # Fallback to regex matching if JSON data not provided
    output_text = (upload_result.stdout + upload_result.stderr).lower()

    if expected_behavior == "skip":
        # Look for skip indicators
        skip_patterns = ["skip", "already exists", "duplicate", "existing"]
        return any(pattern in output_text for pattern in skip_patterns)

    elif expected_behavior == "replace":
        # Look for replace indicators
        replace_patterns = ["replac", "overwrit", "updat"]
        return any(pattern in output_text for pattern in replace_patterns)

    elif expected_behavior == "error":
        # Look for error indicators
        error_patterns = [
            "duplicate",
            "error",
            "already exists",
            "file exists",
            "conflict",
        ]
        return any(pattern in output_text for pattern in error_patterns)

    return False


# Test markers for categorization
pytestmark = [
    pytest.mark.integration,  # These are integration tests
    pytest.mark.api,  # These require GitLab API access
    pytest.mark.slow,  # These tests take longer due to multiple uploads and API calls
]


def _get_gitlab_token():
    """Get GitLab token from environment with proper error handling."""
    token = os.environ.get("GITLAB_TOKEN")
    if not token:
        pytest.skip("GITLAB_TOKEN environment variable not set")
    return token


class TestDuplicateHandling:
    """
    Test class for duplicate handling policies.

    Extracted and adapted from TestOrchestrator._test_skip_duplicate_policy,
    _test_replace_duplicate_policy, and _test_error_duplicate_policy methods.
    """

    @pytest.mark.timeout(180)
    def test_skip_duplicate_policy(self, gitlab_client, artifact_manager, project_path):
        """
        Test skip duplicate policy using subprocess execution.

        Args:
            gitlab_client: GitLab test client fixture
            artifact_manager: Artifact manager fixture
            project_path: Project path fixture
        """
        # Set up GitLab client with project
        gitlab_client.set_project(project_path)

        # Create test file
        test_file = artifact_manager.create_test_file(
            filename="duplicate-skip-test.txt", size_bytes=2048, content_pattern="text"
        )

        # Create unique package name
        package_name = gitlab_client.create_test_package("skip-duplicate", "1.0.0")

        executor = ScriptExecutor()
        first_upload_execution = UploadExecution(
            command=[
                str(executor.script_path),
                "--package-name",
                package_name,
                "--package-version",
                "1.0.0",
                "--files",
                str(test_file.path),
                "--duplicate-policy",
                "skip",
                "--json-output",
            ]
            + get_project_args(project_path),
            expected_exit_code=0,
            expected_output_patterns=[],
            timeout=120,
            use_json_output=True,
        )

        # Add GitLab token to environment
        first_upload_execution.env_vars = {"GITLAB_TOKEN": _get_gitlab_token()}

        first_upload_result = executor.execute_upload(first_upload_execution)

        # Validate first upload succeeded
        assert first_upload_result.json_data is not None
        assert validate_json_result(
            first_upload_result.json_data,
            expected_success=True,
            expected_files=[str(test_file.path)],
        )
        assert first_upload_result.json_data["success"] is True
        assert first_upload_result.json_data["statistics"]["new_uploads"] == 1
        assert first_upload_result.json_data["statistics"]["skipped_duplicates"] == 0
        assert first_upload_result.success, (
            f"First upload failed: {first_upload_result.error_message}"
        )
        assert first_upload_result.exit_code == 0, (
            f"Unexpected exit code: {first_upload_result.exit_code}"
        )

        first_validation = _validate_upload_consistency(
            gitlab_client,
            package_name,
            "1.0.0",
            test_file.path.name,
            test_file.checksum,
        )
        assert first_validation, (
            "First upload validation failed using upload script consistency logic"
        )

        # Wait to ensure first upload is processed
        time.sleep(2)

        second_upload_execution = UploadExecution(
            command=[
                str(executor.script_path),
                "--package-name",
                package_name,
                "--package-version",
                "1.0.0",
                "--files",
                str(test_file.path),
                "--duplicate-policy",
                "skip",
                "--json-output",
            ]
            + get_project_args(project_path),
            expected_exit_code=0,
            expected_output_patterns=[],
            timeout=120,
            use_json_output=True,
        )

        second_upload_execution.env_vars = {"GITLAB_TOKEN": _get_gitlab_token()}

        second_upload_result = executor.execute_upload(second_upload_execution)

        # Validate second upload succeeded (skip behavior)
        assert second_upload_result.success, (
            f"Second upload failed: {second_upload_result.error_message}"
        )
        assert second_upload_result.exit_code == 0, (
            f"Unexpected exit code: {second_upload_result.exit_code}"
        )

        registry_verification = _validate_upload_consistency(
            gitlab_client,
            package_name,
            "1.0.0",
            test_file.path.name,
            test_file.checksum,
        )
        assert registry_verification, (
            "Registry verification failed after skip duplicate test using upload script consistency logic"
        )

        assert second_upload_result.json_data is not None
        assert (
            second_upload_result.json_data["statistics"]["skipped_duplicates"] >= 1
        ), "Expected at least one skipped duplicate"
        assert len(second_upload_result.json_data["skipped_duplicates"]) >= 1, (
            "Expected files in skipped_duplicates list"
        )
        skipped = second_upload_result.json_data["skipped_duplicates"][0]
        assert skipped["was_duplicate"] is True
        assert skipped["duplicate_action"] == "skipped"
        assert skipped["target_filename"] == test_file.path.name

    @pytest.mark.timeout(180)
    def test_replace_duplicate_policy(
        self, gitlab_client, artifact_manager, project_path
    ):
        """
        Test replace duplicate policy - should replace existing duplicate files.

        Args:
            gitlab_client: GitLab test client fixture
            artifact_manager: Artifact manager fixture
            project_path: Project path fixture
        """
        # Set up GitLab client with project
        gitlab_client.set_project(project_path)

        # Create first test file
        first_test_file = artifact_manager.create_test_file(
            filename="duplicate-replace-test.txt",
            size_bytes=1024,
            content_pattern="text",
        )

        # Create unique package name
        package_name = gitlab_client.create_test_package("replace-duplicate", "1.0.0")

        # First upload - should succeed
        executor = ScriptExecutor()
        first_upload_execution = UploadExecution(
            command=[
                str(executor.script_path),
                "--package-name",
                package_name,
                "--package-version",
                "1.0.0",
                "--files",
                str(first_test_file.path),
                "--duplicate-policy",
                "replace",
                "--json-output",
            ]
            + get_project_args(project_path),
            expected_exit_code=0,
            expected_output_patterns=[],
            timeout=120,
            use_json_output=True,
        )

        first_upload_execution.env_vars = {"GITLAB_TOKEN": _get_gitlab_token()}

        first_upload_result = executor.execute_upload(first_upload_execution)

        # Validate first upload succeeded
        assert first_upload_result.json_data is not None
        assert validate_json_result(
            first_upload_result.json_data,
            expected_success=True,
            expected_files=[str(first_test_file.path)],
        )
        assert first_upload_result.json_data["success"] is True
        assert first_upload_result.json_data["statistics"]["new_uploads"] == 1
        assert first_upload_result.json_data["statistics"]["skipped_duplicates"] == 0
        assert first_upload_result.success, (
            f"First upload failed: {first_upload_result.error_message}"
        )
        assert first_upload_result.exit_code == 0, (
            f"Unexpected exit code: {first_upload_result.exit_code}"
        )

        # Wait a moment to ensure the first upload is processed
        time.sleep(2)

        # Create second test file with same name but different content
        second_test_file = artifact_manager.create_test_file(
            filename="duplicate-replace-test.txt",
            size_bytes=2048,  # Different size
            content_pattern="json",  # Different content pattern
        )

        # Second upload with same filename but different content - should replace
        second_upload_execution = UploadExecution(
            command=[
                str(executor.script_path),
                "--package-name",
                package_name,
                "--package-version",
                "1.0.0",
                "--files",
                str(second_test_file.path),
                "--duplicate-policy",
                "replace",
                "--json-output",
            ]
            + get_project_args(project_path),
            expected_exit_code=0,
            expected_output_patterns=[],
            timeout=120,
            use_json_output=True,
        )

        second_upload_execution.env_vars = {"GITLAB_TOKEN": _get_gitlab_token()}

        second_upload_result = executor.execute_upload(second_upload_execution)

        # Verify that both uploads succeeded
        assert first_upload_result.success, (
            f"First upload failed: {first_upload_result.error_message}"
        )
        assert second_upload_result.success, (
            f"Second upload failed: {second_upload_result.error_message}"
        )

        # GitLab API verification - file should exist with the second file's checksum (indicating replacement)
        api_verification = _validate_upload_consistency(
            gitlab_client,
            package_name,
            "1.0.0",
            second_test_file.path.name,
            second_test_file.checksum,
        )
        assert api_verification, (
            "GitLab API verification failed - file was not replaced using upload script consistency logic"
        )

        # Additional check: download and verify content matches second file
        download_verification = gitlab_client.download_and_verify(
            package_name=package_name,
            version="1.0.0",
            filename=second_test_file.path.name,
            expected_checksum=second_test_file.checksum,
        )
        assert download_verification, (
            "Download verification failed - file content does not match second file"
        )

        assert second_upload_result.json_data is not None
        assert second_upload_result.json_data["success"] is True
        assert (
            second_upload_result.json_data["statistics"]["replaced_duplicates"] >= 1
        ), "Expected at least one replaced duplicate"
        replaced_upload = next(
            (
                u
                for u in second_upload_result.json_data["successful_uploads"]
                if u["was_duplicate"] and u["duplicate_action"] == "replaced"
            ),
            None,
        )
        assert replaced_upload is not None, (
            "Expected replaced upload in successful_uploads"
        )
        assert replaced_upload["target_filename"] == second_test_file.path.name

    @pytest.mark.timeout(180)
    def test_error_duplicate_policy(
        self, gitlab_client, artifact_manager, project_path
    ):
        """
        Test error duplicate policy - should fail when duplicate files are detected.

        Args:
            gitlab_client: GitLab test client fixture
            artifact_manager: Artifact manager fixture
            project_path: Project path fixture
        """
        # Set up GitLab client with project
        gitlab_client.set_project(project_path)

        # Create test file
        test_file = artifact_manager.create_test_file(
            filename="duplicate-error-test.txt", size_bytes=1536, content_pattern="text"
        )

        # Create unique package name
        package_name = gitlab_client.create_test_package("error-duplicate", "1.0.0")

        # First upload - should succeed
        executor = ScriptExecutor()
        first_upload_execution = UploadExecution(
            command=[
                str(executor.script_path),
                "--package-name",
                package_name,
                "--package-version",
                "1.0.0",
                "--files",
                str(test_file.path),
                "--duplicate-policy",
                "error",
                "--json-output",
            ]
            + get_project_args(project_path),
            expected_exit_code=0,
            expected_output_patterns=[],
            timeout=120,
            use_json_output=True,
        )

        first_upload_execution.env_vars = {"GITLAB_TOKEN": _get_gitlab_token()}

        first_upload_result = executor.execute_upload(first_upload_execution)

        # Validate first upload succeeded
        assert first_upload_result.json_data is not None
        assert validate_json_result(
            first_upload_result.json_data,
            expected_success=True,
            expected_files=[str(test_file.path)],
        )
        assert first_upload_result.json_data["success"] is True
        assert first_upload_result.json_data["statistics"]["new_uploads"] == 1
        assert first_upload_result.json_data["statistics"]["skipped_duplicates"] == 0
        assert first_upload_result.success, (
            f"First upload failed: {first_upload_result.error_message}"
        )
        assert first_upload_result.exit_code == 0, (
            f"Unexpected exit code: {first_upload_result.exit_code}"
        )

        # Wait a moment to ensure the first upload is processed
        time.sleep(2)

        # Second upload with same file - should fail due to error policy
        second_upload_execution = UploadExecution(
            command=[
                str(executor.script_path),
                "--package-name",
                package_name,
                "--package-version",
                "1.0.0",
                "--files",
                str(test_file.path),
                "--duplicate-policy",
                "error",
                "--json-output",
            ]
            + get_project_args(project_path),
            expected_exit_code=1,  # Expect failure
            expected_output_patterns=[],
            timeout=120,
            use_json_output=True,
        )

        second_upload_execution.env_vars = {"GITLAB_TOKEN": _get_gitlab_token()}

        second_upload_result = executor.execute_upload(second_upload_execution)

        # For error policy, we expect the second upload to fail
        assert not second_upload_result.success, (
            "Second upload should have failed with error policy but succeeded"
        )
        assert second_upload_result.exit_code != 0, (
            "Second upload should have returned non-zero exit code"
        )

        assert second_upload_result.json_data is not None, (
            "JSON output should be present even on failure"
        )
        assert second_upload_result.json_data["success"] is False
        assert second_upload_result.json_data["exit_code"] == 1
        assert len(second_upload_result.json_data["failed_uploads"]) > 0, (
            "Expected failed uploads"
        )
        failed = second_upload_result.json_data["failed_uploads"][0]
        assert "duplicate" in failed.get("error_message", "").lower(), (
            "Error message should mention duplicate"
        )

        # GitLab API verification - original file should still exist
        api_verification = _validate_upload_consistency(
            gitlab_client,
            package_name,
            "1.0.0",
            test_file.path.name,
            test_file.checksum,
        )
        assert api_verification, (
            "GitLab API verification failed - original file should still exist using upload script consistency logic"
        )


# Additional test functions for edge cases and specific duplicate scenarios


@pytest.mark.slow
@pytest.mark.timeout(180)
def test_multiple_file_skip_duplicates(gitlab_client, artifact_manager, project_path):
    """
    Test skip duplicate policy with multiple files where some are duplicates.

    Args:
        gitlab_client: GitLab test client fixture
        artifact_manager: Artifact manager fixture
        project_path: Project path fixture
    """
    # Set up GitLab client with project
    gitlab_client.set_project(project_path)

    # Create test files
    test_files = [
        artifact_manager.create_test_file("multi-skip-1.txt", 1024, "text"),
        artifact_manager.create_test_file("multi-skip-2.json", 2048, "json"),
        artifact_manager.create_test_file("multi-skip-3.bin", 512, "binary"),
    ]

    # Create unique package name
    package_name = gitlab_client.create_test_package("multi-skip-duplicate", "1.0.0")

    # First upload - all files should succeed
    executor = ScriptExecutor()
    file_paths = [str(f.path) for f in test_files]
    first_upload_execution = UploadExecution(
        command=[
            str(executor.script_path),
            "--package-name",
            package_name,
            "--package-version",
            "1.0.0",
            "--files",
        ]
        + file_paths
        + ["--duplicate-policy", "skip"]
        + ["--json-output"]
        + get_project_args(project_path),
        expected_exit_code=0,
        expected_output_patterns=[],
        timeout=180,
        use_json_output=True,
    )

    first_upload_execution.env_vars = {"GITLAB_TOKEN": _get_gitlab_token()}
    first_upload_result = executor.execute_upload(first_upload_execution)

    # Validate first upload succeeded
    assert first_upload_result.json_data is not None
    assert validate_json_result(
        first_upload_result.json_data,
        expected_success=True,
        expected_files=file_paths,
    )
    assert first_upload_result.json_data["success"] is True
    assert first_upload_result.json_data["statistics"]["new_uploads"] == 3
    assert first_upload_result.json_data["statistics"]["skipped_duplicates"] == 0
    assert first_upload_result.success, (
        f"First upload failed: {first_upload_result.error_message}"
    )

    # Wait for processing
    time.sleep(3)

    # Second upload with same files - should skip all duplicates
    second_upload_execution = UploadExecution(
        command=[
            str(executor.script_path),
            "--package-name",
            package_name,
            "--package-version",
            "1.0.0",
            "--files",
        ]
        + file_paths
        + ["--duplicate-policy", "skip"]
        + ["--json-output"]
        + get_project_args(project_path),
        expected_exit_code=0,
        expected_output_patterns=[],
        timeout=180,
        use_json_output=True,
    )

    second_upload_execution.env_vars = {"GITLAB_TOKEN": _get_gitlab_token()}
    second_upload_result = executor.execute_upload(second_upload_execution)

    # Validate second upload succeeded (skip behavior)
    assert second_upload_result.success, (
        f"Second upload failed: {second_upload_result.error_message}"
    )

    # Verify all files still exist in registry using comprehensive validation
    registry_failures = []
    for test_file in test_files:
        registry_verification = _validate_upload_consistency(
            gitlab_client,
            package_name,
            "1.0.0",
            test_file.path.name,
            test_file.checksum,
        )
        if not registry_verification:
            registry_failures.append(test_file.path.name)

    assert not registry_failures, (
        f"Registry verification failed for files: {', '.join(registry_failures)}"
    )

    # Verify skip behavior for multiple files
    assert second_upload_result.json_data is not None
    assert second_upload_result.json_data["statistics"]["skipped_duplicates"] == 3, (
        "All 3 files should be skipped as duplicates"
    )
    assert len(second_upload_result.json_data["skipped_duplicates"]) == 3
    skipped_filenames = [
        s["target_filename"]
        for s in second_upload_result.json_data["skipped_duplicates"]
    ]
    for test_file in test_files:
        assert test_file.path.name in skipped_filenames


@pytest.mark.timeout(180)
def test_mixed_duplicate_and_new_files(gitlab_client, artifact_manager, project_path):
    """
    Test skip duplicate policy with a mix of duplicate and new files.

    Args:
        gitlab_client: GitLab test client fixture
        artifact_manager: Artifact manager fixture
        project_path: Project path fixture
    """
    # Set up GitLab client with project
    gitlab_client.set_project(project_path)

    # Create initial test files
    initial_files = [
        artifact_manager.create_test_file("mixed-1.txt", 1024, "text"),
        artifact_manager.create_test_file("mixed-2.json", 2048, "json"),
    ]

    # Create unique package name
    package_name = gitlab_client.create_test_package("mixed-duplicate", "1.0.0")

    # First upload - initial files
    executor = ScriptExecutor()
    initial_file_paths = [str(f.path) for f in initial_files]
    first_upload_execution = UploadExecution(
        command=[
            str(executor.script_path),
            "--package-name",
            package_name,
            "--package-version",
            "1.0.0",
            "--files",
        ]
        + initial_file_paths
        + ["--duplicate-policy", "skip"]
        + ["--json-output"]
        + get_project_args(project_path),
        expected_exit_code=0,
        expected_output_patterns=[],
        timeout=180,
        use_json_output=True,
    )

    first_upload_execution.env_vars = {"GITLAB_TOKEN": _get_gitlab_token()}
    first_upload_result = executor.execute_upload(first_upload_execution)

    # Validate first upload succeeded
    assert first_upload_result.json_data is not None
    assert validate_json_result(
        first_upload_result.json_data,
        expected_success=True,
        expected_files=initial_file_paths,
    )
    assert first_upload_result.json_data["success"] is True
    assert first_upload_result.json_data["statistics"]["new_uploads"] == 2
    assert first_upload_result.json_data["statistics"]["skipped_duplicates"] == 0
    assert first_upload_result.success, (
        f"First upload failed: {first_upload_result.error_message}"
    )

    # Wait for processing
    time.sleep(2)

    # Create additional new files
    new_files = [
        artifact_manager.create_test_file("mixed-3.bin", 512, "binary"),
        artifact_manager.create_test_file("mixed-4.xml", 1536, "xml"),
    ]

    # Second upload with mix of duplicate and new files
    all_files = initial_files + new_files
    all_file_paths = [str(f.path) for f in all_files]

    second_upload_execution = UploadExecution(
        command=[
            str(executor.script_path),
            "--package-name",
            package_name,
            "--package-version",
            "1.0.0",
            "--files",
        ]
        + all_file_paths
        + ["--duplicate-policy", "skip"]
        + ["--json-output"]
        + get_project_args(project_path),
        expected_exit_code=0,
        expected_output_patterns=[],
        timeout=180,
        use_json_output=True,
    )

    second_upload_execution.env_vars = {"GITLAB_TOKEN": _get_gitlab_token()}
    second_upload_result = executor.execute_upload(second_upload_execution)

    # Validate second upload succeeded
    assert second_upload_result.success, (
        f"Second upload failed: {second_upload_result.error_message}"
    )

    # Verify all files exist in registry (duplicates skipped, new files uploaded) using comprehensive validation
    registry_failures = []
    for test_file in all_files:
        registry_verification = _validate_upload_consistency(
            gitlab_client,
            package_name,
            "1.0.0",
            test_file.path.name,
            test_file.checksum,
        )
        if not registry_verification:
            registry_failures.append(test_file.path.name)

    assert not registry_failures, (
        f"Registry verification failed for files: {', '.join(registry_failures)}"
    )

    # Verify mixed behavior (skip duplicates, upload new files)
    assert second_upload_result.json_data is not None
    assert second_upload_result.json_data["statistics"]["skipped_duplicates"] == 2, (
        "Initial 2 files should be skipped"
    )
    assert second_upload_result.json_data["statistics"]["new_uploads"] == 2, (
        "New 2 files should be uploaded"
    )
    skipped_filenames = [
        s["target_filename"]
        for s in second_upload_result.json_data["skipped_duplicates"]
    ]
    new_filenames = [
        u["target_filename"]
        for u in second_upload_result.json_data["successful_uploads"]
        if not u["was_duplicate"]
    ]
    for initial_file in initial_files:
        assert initial_file.path.name in skipped_filenames
    for new_file in new_files:
        assert new_file.path.name in new_filenames
