"""
Duplicate handling policy integration tests using direct module invocation.

This module tests skip, replace, and error duplicate policies by calling
the CLI main() function directly.
"""

import os
import time

import pytest

from .test_helpers_module import (
    ModuleExecutor,
    validate_json_result,
)

# Test markers for categorization
pytestmark = [
    pytest.mark.integration,  # These are integration tests
    pytest.mark.api,  # These require GitLab API access
    pytest.mark.slow,  # These tests take longer due to multiple uploads and API calls
]


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

        # Step 3: Verify downloaded content matches expected checksum
        if not gitlab_client.download_and_verify(
            package_name, version, filename, expected_checksum
        ):
            return False

        return True

    except Exception:
        return False


class TestDuplicateHandling:
    """
    Test class for duplicate handling policies using direct module invocation.
    """

    @pytest.mark.timeout(180)
    def test_skip_duplicate_policy(self, gitlab_client, artifact_manager, project_path):
        """
        Test skip duplicate policy - should skip uploading existing files.

        Args:
            gitlab_client: GitLab test client fixture
            artifact_manager: Artifact manager fixture
            project_path: Project path fixture
        """
        # Set up GitLab client with project
        gitlab_client.set_project(project_path)

        # Create test file
        test_file = artifact_manager.create_test_file(
            filename="duplicate-skip-module.txt", size_bytes=2048, content_pattern="text"
        )

        # Create unique package name
        package_name = gitlab_client.create_test_package("skip-duplicate-module", "1.0.0")

        executor = ModuleExecutor()

        # First upload - should succeed as new file
        first_argv = executor.build_argv(
            package_name=package_name,
            version="1.0.0",
            files=[str(test_file.path)],
            project_path=project_path,
            duplicate_policy="skip",
            json_output=True,
        )

        first_upload_result = executor.execute_upload(
            argv=first_argv,
            env_vars={"GITLAB_TOKEN": os.environ.get("GITLAB_TOKEN")},
            use_json_output=True,
        )

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
        assert first_upload_result.exit_code == 0

        first_validation = _validate_upload_consistency(
            gitlab_client,
            package_name,
            "1.0.0",
            test_file.path.name,
            test_file.checksum,
        )
        assert first_validation, "First upload validation failed"

        # Wait to ensure first upload is processed
        time.sleep(2)

        # Second upload - should skip duplicate
        second_upload_result = executor.execute_upload(
            argv=first_argv,
            env_vars={"GITLAB_TOKEN": os.environ.get("GITLAB_TOKEN")},
            use_json_output=True,
        )

        # Validate second upload succeeded (skip behavior)
        assert second_upload_result.success, (
            f"Second upload failed: {second_upload_result.error_message}"
        )
        assert second_upload_result.exit_code == 0

        registry_verification = _validate_upload_consistency(
            gitlab_client,
            package_name,
            "1.0.0",
            test_file.path.name,
            test_file.checksum,
        )
        assert registry_verification, "Registry verification failed after skip duplicate test"

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
            filename="duplicate-replace-module.txt",
            size_bytes=1024,
            content_pattern="text",
        )

        # Create unique package name
        package_name = gitlab_client.create_test_package("replace-duplicate-module", "1.0.0")

        executor = ModuleExecutor()

        # First upload - should succeed
        first_argv = executor.build_argv(
            package_name=package_name,
            version="1.0.0",
            files=[str(first_test_file.path)],
            project_path=project_path,
            duplicate_policy="replace",
            json_output=True,
        )

        first_upload_result = executor.execute_upload(
            argv=first_argv,
            env_vars={"GITLAB_TOKEN": os.environ.get("GITLAB_TOKEN")},
            use_json_output=True,
        )

        # Validate first upload succeeded
        assert first_upload_result.json_data is not None
        assert validate_json_result(
            first_upload_result.json_data,
            expected_success=True,
            expected_files=[str(first_test_file.path)],
        )
        assert first_upload_result.json_data["success"] is True
        assert first_upload_result.json_data["statistics"]["new_uploads"] == 1
        assert first_upload_result.success

        # Wait a moment to ensure the first upload is processed
        time.sleep(2)

        # Create second test file with same name but different content
        second_test_file = artifact_manager.create_test_file(
            filename="duplicate-replace-module.txt",
            size_bytes=2048,  # Different size
            content_pattern="json",  # Different content pattern
        )

        # Second upload with same filename but different content - should replace
        second_argv = executor.build_argv(
            package_name=package_name,
            version="1.0.0",
            files=[str(second_test_file.path)],
            project_path=project_path,
            duplicate_policy="replace",
            json_output=True,
        )

        second_upload_result = executor.execute_upload(
            argv=second_argv,
            env_vars={"GITLAB_TOKEN": os.environ.get("GITLAB_TOKEN")},
            use_json_output=True,
        )

        # Verify that both uploads succeeded
        assert first_upload_result.success, (
            f"First upload failed: {first_upload_result.error_message}"
        )
        assert second_upload_result.success, (
            f"Second upload failed: {second_upload_result.error_message}"
        )

        # GitLab API verification - file should exist with the second file's checksum
        api_verification = _validate_upload_consistency(
            gitlab_client,
            package_name,
            "1.0.0",
            second_test_file.path.name,
            second_test_file.checksum,
        )
        assert api_verification, "GitLab API verification failed - file was not replaced"

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
        assert replaced_upload is not None, "Expected replaced upload in successful_uploads"
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
            filename="duplicate-error-module.txt", size_bytes=1536, content_pattern="text"
        )

        # Create unique package name
        package_name = gitlab_client.create_test_package("error-duplicate-module", "1.0.0")

        executor = ModuleExecutor()

        # First upload - should succeed
        first_argv = executor.build_argv(
            package_name=package_name,
            version="1.0.0",
            files=[str(test_file.path)],
            project_path=project_path,
            duplicate_policy="error",
            json_output=True,
        )

        first_upload_result = executor.execute_upload(
            argv=first_argv,
            env_vars={"GITLAB_TOKEN": os.environ.get("GITLAB_TOKEN")},
            use_json_output=True,
        )

        # Validate first upload succeeded
        assert first_upload_result.json_data is not None
        assert validate_json_result(
            first_upload_result.json_data,
            expected_success=True,
            expected_files=[str(test_file.path)],
        )
        assert first_upload_result.json_data["success"] is True
        assert first_upload_result.json_data["statistics"]["new_uploads"] == 1
        assert first_upload_result.success
        assert first_upload_result.exit_code == 0

        # Wait a moment to ensure the first upload is processed
        time.sleep(2)

        # Second upload with same file - should fail due to error policy
        second_upload_result = executor.execute_upload(
            argv=first_argv,
            env_vars={"GITLAB_TOKEN": os.environ.get("GITLAB_TOKEN")},
            expected_exit_code=1,  # Expect failure
            use_json_output=True,
        )

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
        assert api_verification, "Original file should still exist"


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
        artifact_manager.create_test_file("multi-skip-module-1.txt", 1024, "text"),
        artifact_manager.create_test_file("multi-skip-module-2.json", 2048, "json"),
        artifact_manager.create_test_file("multi-skip-module-3.bin", 512, "binary"),
    ]

    # Create unique package name
    package_name = gitlab_client.create_test_package("multi-skip-duplicate-module", "1.0.0")

    executor = ModuleExecutor()
    file_paths = [str(f.path) for f in test_files]

    # First upload - all files should succeed
    first_argv = executor.build_argv(
        package_name=package_name,
        version="1.0.0",
        files=file_paths,
        project_path=project_path,
        duplicate_policy="skip",
        json_output=True,
    )

    first_upload_result = executor.execute_upload(
        argv=first_argv,
        env_vars={"GITLAB_TOKEN": os.environ.get("GITLAB_TOKEN")},
        use_json_output=True,
    )

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
    assert first_upload_result.success

    # Wait for processing
    time.sleep(3)

    # Second upload with same files - should skip all duplicates
    second_upload_result = executor.execute_upload(
        argv=first_argv,
        env_vars={"GITLAB_TOKEN": os.environ.get("GITLAB_TOKEN")},
        use_json_output=True,
    )

    # Validate second upload succeeded (skip behavior)
    assert second_upload_result.success, (
        f"Second upload failed: {second_upload_result.error_message}"
    )

    # Verify all files still exist in registry
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
        artifact_manager.create_test_file("mixed-module-1.txt", 1024, "text"),
        artifact_manager.create_test_file("mixed-module-2.json", 2048, "json"),
    ]

    # Create unique package name
    package_name = gitlab_client.create_test_package("mixed-duplicate-module", "1.0.0")

    executor = ModuleExecutor()
    initial_file_paths = [str(f.path) for f in initial_files]

    # First upload - initial files
    first_argv = executor.build_argv(
        package_name=package_name,
        version="1.0.0",
        files=initial_file_paths,
        project_path=project_path,
        duplicate_policy="skip",
        json_output=True,
    )

    first_upload_result = executor.execute_upload(
        argv=first_argv,
        env_vars={"GITLAB_TOKEN": os.environ.get("GITLAB_TOKEN")},
        use_json_output=True,
    )

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
    assert first_upload_result.success

    # Wait for processing
    time.sleep(2)

    # Create additional new files
    new_files = [
        artifact_manager.create_test_file("mixed-module-3.bin", 512, "binary"),
        artifact_manager.create_test_file("mixed-module-4.xml", 1536, "text"),
    ]

    # Second upload with mix of duplicate and new files
    all_files = initial_files + new_files
    all_file_paths = [str(f.path) for f in all_files]

    second_argv = executor.build_argv(
        package_name=package_name,
        version="1.0.0",
        files=all_file_paths,
        project_path=project_path,
        duplicate_policy="skip",
        json_output=True,
    )

    second_upload_result = executor.execute_upload(
        argv=second_argv,
        env_vars={"GITLAB_TOKEN": os.environ.get("GITLAB_TOKEN")},
        use_json_output=True,
    )

    # Validate second upload succeeded
    assert second_upload_result.success, (
        f"Second upload failed: {second_upload_result.error_message}"
    )

    # Verify all files exist in registry
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
