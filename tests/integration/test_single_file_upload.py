"""
Single file upload integration test using direct module invocation.

This module tests single file upload functionality by calling the CLI main()
function directly instead of using subprocess execution.
"""

import os

import pytest

from .test_helpers_module import (
    ModuleExecutor,
    get_project_args,
    validate_json_result,
)

# Test markers for categorization
pytestmark = [
    pytest.mark.integration,  # These are integration tests
    pytest.mark.api,  # These require GitLab API access
]


@pytest.mark.timeout(180)
def test_single_file_upload(gitlab_client, artifact_manager, project_path):
    """
    Test single file upload functionality using direct module invocation.

    This test validates that a single file can be uploaded successfully
    by calling the CLI main() function directly.

    Args:
        gitlab_client: GitLab test client fixture
        artifact_manager: Artifact manager fixture
        project_path: Project path fixture
    """
    # Set up GitLab client with project
    gitlab_client.set_project(project_path)

    # Create test file
    test_file = artifact_manager.create_test_file(
        filename="single-test-module.txt", size_bytes=1024, content_pattern="text"
    )

    # Create unique package name
    package_name = gitlab_client.create_test_package("single-file-module", "1.0.0")

    # Build argv for main() function
    executor = ModuleExecutor()
    argv = executor.build_argv(
        package_name=package_name,
        version="1.0.0",
        files=[str(test_file.path)],
        project_path=project_path,
        duplicate_policy="skip",
        json_output=True,
    )

    # Execute upload via direct module invocation
    upload_result = executor.execute_upload(
        argv=argv,
        env_vars={"GITLAB_TOKEN": os.environ.get("GITLAB_TOKEN")},
        use_json_output=True,
    )

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

    # Validate upload execution succeeded
    assert upload_result.exit_code == 0, (
        f"Unexpected exit code: {upload_result.exit_code}"
    )

    # Verify in GitLab registry
    registry_verification = gitlab_client.verify_upload(
        package_name, "1.0.0", test_file.path.name, test_file.checksum
    )

    assert registry_verification, (
        "Upload verification failed - file not found in GitLab registry"
    )


@pytest.mark.timeout(180)
def test_single_file_upload_with_verbose(gitlab_client, artifact_manager, project_path):
    """
    Test single file upload with verbose output enabled.

    Args:
        gitlab_client: GitLab test client fixture
        artifact_manager: Artifact manager fixture
        project_path: Project path fixture
    """
    # Set up GitLab client with project
    gitlab_client.set_project(project_path)

    # Create test file
    test_file = artifact_manager.create_test_file(
        filename="single-verbose-test.txt", size_bytes=512, content_pattern="text"
    )

    # Create unique package name
    package_name = gitlab_client.create_test_package("single-verbose", "1.0.0")

    # Build argv with verbose flag
    executor = ModuleExecutor()
    argv = executor.build_argv(
        package_name=package_name,
        version="1.0.0",
        files=[str(test_file.path)],
        project_path=project_path,
        duplicate_policy="skip",
        json_output=True,
        verbose=True,
    )

    # Execute upload
    upload_result = executor.execute_upload(
        argv=argv,
        env_vars={"GITLAB_TOKEN": os.environ.get("GITLAB_TOKEN")},
        use_json_output=True,
    )

    # Validate success
    assert upload_result.json_data is not None
    assert upload_result.json_data["success"] is True
    assert upload_result.exit_code == 0

    # Verify in GitLab registry
    assert gitlab_client.verify_upload(
        package_name, "1.0.0", test_file.path.name, test_file.checksum
    )


@pytest.mark.timeout(180)
def test_single_file_upload_with_quiet(gitlab_client, artifact_manager, project_path):
    """
    Test single file upload with quiet output enabled.

    Args:
        gitlab_client: GitLab test client fixture
        artifact_manager: Artifact manager fixture
        project_path: Project path fixture
    """
    # Set up GitLab client with project
    gitlab_client.set_project(project_path)

    # Create test file
    test_file = artifact_manager.create_test_file(
        filename="single-quiet-test.txt", size_bytes=512, content_pattern="text"
    )

    # Create unique package name
    package_name = gitlab_client.create_test_package("single-quiet", "1.0.0")

    # Build argv with quiet flag
    executor = ModuleExecutor()
    argv = executor.build_argv(
        package_name=package_name,
        version="1.0.0",
        files=[str(test_file.path)],
        project_path=project_path,
        duplicate_policy="skip",
        json_output=True,
        quiet=True,
    )

    # Execute upload
    upload_result = executor.execute_upload(
        argv=argv,
        env_vars={"GITLAB_TOKEN": os.environ.get("GITLAB_TOKEN")},
        use_json_output=True,
    )

    # Validate success
    assert upload_result.json_data is not None
    assert upload_result.json_data["success"] is True
    assert upload_result.exit_code == 0

    # Verify in GitLab registry
    assert gitlab_client.verify_upload(
        package_name, "1.0.0", test_file.path.name, test_file.checksum
    )


@pytest.mark.timeout(180)
def test_single_file_upload_different_content_types(
    gitlab_client, artifact_manager, project_path
):
    """
    Test single file uploads with different content types.

    Args:
        gitlab_client: GitLab test client fixture
        artifact_manager: Artifact manager fixture
        project_path: Project path fixture
    """
    # Set up GitLab client with project
    gitlab_client.set_project(project_path)

    executor = ModuleExecutor()

    # Test different file types
    file_types = [
        ("content-type-text.txt", 1024, "text"),
        ("content-type-json.json", 2048, "json"),
        ("content-type-binary.bin", 512, "binary"),
    ]

    for filename, size, pattern in file_types:
        # Create test file
        test_file = artifact_manager.create_test_file(
            filename=filename, size_bytes=size, content_pattern=pattern
        )

        # Create unique package name
        package_name = gitlab_client.create_test_package(
            f"content-type-{pattern}", "1.0.0"
        )

        # Build argv
        argv = executor.build_argv(
            package_name=package_name,
            version="1.0.0",
            files=[str(test_file.path)],
            project_path=project_path,
            duplicate_policy="skip",
            json_output=True,
        )

        # Execute upload
        upload_result = executor.execute_upload(
            argv=argv,
            env_vars={"GITLAB_TOKEN": os.environ.get("GITLAB_TOKEN")},
            use_json_output=True,
        )

        # Validate success
        assert upload_result.json_data is not None, f"JSON output not found for {filename}"
        assert upload_result.json_data["success"] is True, f"Upload failed for {filename}"
        assert upload_result.exit_code == 0, f"Non-zero exit code for {filename}"

        # Verify in GitLab registry
        assert gitlab_client.verify_upload(
            package_name, "1.0.0", test_file.path.name, test_file.checksum
        ), f"Registry verification failed for {filename}"
