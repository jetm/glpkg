"""
Multiple files upload integration tests using direct module invocation.

This module tests multiple file uploads, directory uploads, file mapping,
and large file uploads by calling the CLI main() function directly.
"""

import os

import pytest

from .test_helpers_module import (
    ModuleExecutor,
    validate_json_result,
)

# Test markers for categorization
pytestmark = [
    pytest.mark.integration,  # These are integration tests
    pytest.mark.api,  # These require GitLab API access
]


@pytest.mark.timeout(180)
def test_multiple_file_upload(gitlab_client, artifact_manager, project_path):
    """
    Test multiple file upload functionality using direct module invocation.

    Args:
        gitlab_client: GitLab test client fixture
        artifact_manager: Artifact manager fixture
        project_path: Project path fixture
    """
    # Set up GitLab client with project
    gitlab_client.set_project(project_path)

    # Create multiple test files with different characteristics
    test_files = [
        artifact_manager.create_test_file("multi-module-1.txt", 512, "text"),
        artifact_manager.create_test_file("multi-module-2.json", 1024, "json"),
        artifact_manager.create_test_file("multi-module-3.bin", 2048, "binary"),
    ]

    # Create unique package name
    package_name = gitlab_client.create_test_package("multi-file-module", "1.0.0")

    file_paths = [str(f.path) for f in test_files]

    # Build argv for main() function
    executor = ModuleExecutor()
    argv = executor.build_argv(
        package_name=package_name,
        version="1.0.0",
        files=file_paths,
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

    # Validate upload execution succeeded
    assert upload_result.exit_code == 0, (
        f"Unexpected exit code: {upload_result.exit_code}"
    )

    # Verify in GitLab registry
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
def test_directory_upload(gitlab_client, artifact_manager, project_path):
    """
    Test directory upload functionality using direct module invocation.

    Args:
        gitlab_client: GitLab test client fixture
        artifact_manager: Artifact manager fixture
        project_path: Project path fixture
    """
    # Set up GitLab client with project
    gitlab_client.set_project(project_path)

    # Create test directory with files
    test_files = artifact_manager.create_test_directory("upload-dir-module", 4)
    directory_path = artifact_manager.base_dir / "upload-dir-module"

    # Create unique package name
    package_name = gitlab_client.create_test_package("directory-module", "1.0.0")

    # Build argv for main() function
    executor = ModuleExecutor()
    argv = executor.build_argv(
        package_name=package_name,
        version="1.0.0",
        directory=str(directory_path),
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

    # Validate upload execution succeeded
    assert upload_result.exit_code == 0, (
        f"Unexpected exit code: {upload_result.exit_code}"
    )

    # Verify in GitLab registry
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
def test_file_mapping_upload(gitlab_client, artifact_manager, project_path):
    """
    Test file mapping upload functionality with custom target names.

    Args:
        gitlab_client: GitLab test client fixture
        artifact_manager: Artifact manager fixture
        project_path: Project path fixture
    """
    # Set up GitLab client with project
    gitlab_client.set_project(project_path)

    # Create test files
    test_files = [
        artifact_manager.create_test_file("source1-module.txt", 1024, "text"),
        artifact_manager.create_test_file("source2-module.json", 2048, "json"),
    ]

    # Create unique package name
    package_name = gitlab_client.create_test_package("file-mapping-module", "1.0.0")

    # Build argv with file mappings
    executor = ModuleExecutor()
    argv = executor.build_argv(
        package_name=package_name,
        version="1.0.0",
        files=[str(f.path) for f in test_files],
        project_path=project_path,
        duplicate_policy="skip",
        file_mapping=[
            f"{test_files[0].path.name}:target1-module.txt",
            f"{test_files[1].path.name}:config/target2-module.json",
        ],
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
    assert "target1-module.txt" in uploaded_filenames, (
        "Mapped file target1-module.txt not found in successful uploads"
    )
    assert "config/target2-module.json" in uploaded_filenames, (
        "Mapped file config/target2-module.json not found in successful uploads"
    )

    # Validate upload execution succeeded
    assert upload_result.exit_code == 0, (
        f"Unexpected exit code: {upload_result.exit_code}"
    )

    # Verify in GitLab registry with mapped names
    target_mappings = [
        ("target1-module.txt", test_files[0].checksum),
        ("config/target2-module.json", test_files[1].checksum),
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


@pytest.mark.slow
@pytest.mark.timeout(180)
def test_large_file_upload(gitlab_client, artifact_manager, project_path):
    """
    Test upload of a larger file to ensure the module handles various file sizes.

    Args:
        gitlab_client: GitLab test client fixture
        artifact_manager: Artifact manager fixture
        project_path: Project path fixture
    """
    # Set up GitLab client with project
    gitlab_client.set_project(project_path)

    # Create a larger test file (10KB)
    test_file = artifact_manager.create_test_file(
        filename="large-test-module.bin", size_bytes=10240, content_pattern="binary"
    )

    # Create unique package name
    package_name = gitlab_client.create_test_package("large-file-module", "1.0.0")

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
    assert upload_result.json_data["statistics"]["new_uploads"] == 1
    assert upload_result.json_data["statistics"]["failed_uploads"] == 0

    # Validate upload execution succeeded
    assert upload_result.exit_code == 0, (
        f"Unexpected exit code: {upload_result.exit_code}"
    )

    # Verify in GitLab registry
    registry_verification = gitlab_client.verify_upload(
        package_name, "1.0.0", test_file.path.name, test_file.checksum
    )
    assert registry_verification, "Large file verification failed in GitLab registry"


@pytest.mark.timeout(180)
def test_multiple_files_with_different_sizes(
    gitlab_client, artifact_manager, project_path
):
    """
    Test uploading multiple files with varying sizes.

    Args:
        gitlab_client: GitLab test client fixture
        artifact_manager: Artifact manager fixture
        project_path: Project path fixture
    """
    # Set up GitLab client with project
    gitlab_client.set_project(project_path)

    # Create test files with different sizes
    test_files = [
        artifact_manager.create_test_file("size-small.txt", 256, "text"),
        artifact_manager.create_test_file("size-medium.bin", 4096, "binary"),
        artifact_manager.create_test_file("size-large.json", 8192, "json"),
    ]

    # Create unique package name
    package_name = gitlab_client.create_test_package("mixed-sizes-module", "1.0.0")

    file_paths = [str(f.path) for f in test_files]

    # Build argv for main() function
    executor = ModuleExecutor()
    argv = executor.build_argv(
        package_name=package_name,
        version="1.0.0",
        files=file_paths,
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
    assert upload_result.json_data is not None
    assert upload_result.json_data["success"] is True
    assert upload_result.json_data["statistics"]["new_uploads"] == 3
    assert upload_result.exit_code == 0

    # Verify all files in registry
    for test_file in test_files:
        assert gitlab_client.verify_upload(
            package_name, "1.0.0", test_file.path.name, test_file.checksum
        ), f"Verification failed for {test_file.path.name}"
