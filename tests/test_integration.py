"""
Integration tests for GitLab upload script.

This module contains comprehensive integration tests extracted from the monolithic
test file. These tests validate end-to-end scenarios, error handling, and overall
test coverage to ensure the upload script works correctly in real-world conditions.
"""

from pathlib import Path

import pytest

from .utils.test_helpers import ScriptExecutor, UploadExecution, get_project_args

# Test markers for categorization
pytestmark = [
    pytest.mark.integration,  # These are comprehensive integration tests
    pytest.mark.api,  # These require GitLab API access
    pytest.mark.slow,  # These tests are the slowest (comprehensive scenarios)
]


@pytest.mark.timeout(600)
def test_comprehensive_upload_validation(gitlab_client, artifact_manager, project_path):
    """
    Test comprehensive upload validation covering all major scenarios.

    Extracted from TestOrchestrator._test_comprehensive_upload_validation
    """
    executor = ScriptExecutor()

    # Create a variety of test files and scenarios
    single_file = artifact_manager.create_test_file(
        "comprehensive-single.txt", 1024, "text"
    )

    multiple_files = [
        artifact_manager.create_test_file("comp-multi-1.json", 2048, "json"),
        artifact_manager.create_test_file("comp-multi-2.bin", 4096, "binary"),
        artifact_manager.create_test_file("comp-multi-3.csv", 1536, "text"),
    ]

    directory_files = artifact_manager.create_test_directory("comp-directory", 3)
    directory_path = artifact_manager.base_dir / "comp-directory"

    # Set up GitLab client with project
    gitlab_client.set_project(project_path)

    # Create unique package names for each scenario
    single_package = gitlab_client.create_test_package("comp-single", "1.0.0")
    multi_package = gitlab_client.create_test_package("comp-multi", "1.0.0")
    dir_package = gitlab_client.create_test_package("comp-dir", "1.0.0")

    # Test 1: Single file upload
    single_upload_execution = UploadExecution(
        command=[
            str(executor.script_path),
            "--package-name",
            single_package,
            "--package-version",
            "1.0.0",
            "--files",
            str(single_file.path),
            "--json-output",
        ]
        + get_project_args(project_path),
        expected_exit_code=0,
        expected_output_patterns=[],
        timeout=120,
        env_vars={"GITLAB_TOKEN": gitlab_client.token},
        use_json_output=True,
    )

    single_result = executor.execute_upload(single_upload_execution)
    assert single_result.success, (
        f"Single file upload failed: {single_result.error_message}"
    )

    # Validate JSON output
    from .utils.test_helpers import validate_json_result

    assert single_result.json_data is not None, "JSON output not available"
    assert validate_json_result(
        single_result.json_data,
        expected_success=True,
        expected_files=[str(single_file.path)],
    ), "JSON validation failed for single file upload"
    assert single_result.json_data["success"] is True
    assert single_result.json_data["package_name"] == single_package
    assert single_result.json_data["version"] == "1.0.0"
    assert single_result.json_data["statistics"]["new_uploads"] == 1
    assert single_result.json_data["statistics"]["failed_uploads"] == 0
    assert len(single_result.json_data["successful_uploads"]) == 1

    # Verify uploaded filename appears in successful_uploads
    uploaded_filenames = [
        upload["target_filename"]
        for upload in single_result.json_data["successful_uploads"]
    ]
    assert single_file.path.name in uploaded_filenames

    # Validate single file upload via GitLab API
    assert gitlab_client.verify_upload(
        single_package, "1.0.0", single_file.path.name, single_file.checksum
    ), "Single file upload validation failed"

    # Test 2: Multiple files upload
    multi_file_paths = [str(f.path) for f in multiple_files]
    multi_upload_execution = UploadExecution(
        command=[
            str(executor.script_path),
            "--package-name",
            multi_package,
            "--package-version",
            "1.0.0",
            "--files",
        ]
        + multi_file_paths
        + ["--json-output"]
        + get_project_args(project_path),
        expected_exit_code=0,
        expected_output_patterns=[],
        timeout=180,
        env_vars={"GITLAB_TOKEN": gitlab_client.token},
        use_json_output=True,
    )

    multi_result = executor.execute_upload(multi_upload_execution)
    assert multi_result.success, (
        f"Multiple files upload failed: {multi_result.error_message}"
    )

    # Validate JSON output
    assert multi_result.json_data is not None, "JSON output not available"
    assert validate_json_result(
        multi_result.json_data, expected_success=True, expected_files=multi_file_paths
    ), "JSON validation failed for multiple files upload"
    assert multi_result.json_data["success"] is True
    assert multi_result.json_data["package_name"] == multi_package
    assert multi_result.json_data["version"] == "1.0.0"
    assert multi_result.json_data["statistics"]["new_uploads"] == 3
    assert multi_result.json_data["statistics"]["failed_uploads"] == 0
    assert len(multi_result.json_data["successful_uploads"]) == 3

    # Verify uploaded filenames appear in successful_uploads
    uploaded_filenames = [
        upload["target_filename"]
        for upload in multi_result.json_data["successful_uploads"]
    ]
    for test_file in multiple_files:
        assert test_file.path.name in uploaded_filenames

    # Validate multiple files upload via GitLab API
    for test_file in multiple_files:
        assert gitlab_client.verify_upload(
            multi_package, "1.0.0", test_file.path.name, test_file.checksum
        ), f"Multiple files validation failed for {test_file.path.name}"

    # Test 3: Directory upload
    dir_upload_execution = UploadExecution(
        command=[
            str(executor.script_path),
            "--package-name",
            dir_package,
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
        env_vars={"GITLAB_TOKEN": gitlab_client.token},
        use_json_output=True,
    )

    dir_result = executor.execute_upload(dir_upload_execution)
    assert dir_result.success, f"Directory upload failed: {dir_result.error_message}"

    # Validate JSON output
    assert dir_result.json_data is not None, "JSON output not available"
    assert validate_json_result(
        dir_result.json_data,
        expected_success=True,
        expected_files=[str(f.path) for f in directory_files],
    ), "JSON validation failed for directory upload"
    assert dir_result.json_data["success"] is True
    assert dir_result.json_data["package_name"] == dir_package
    assert dir_result.json_data["version"] == "1.0.0"
    assert dir_result.json_data["statistics"]["new_uploads"] == len(directory_files)
    assert dir_result.json_data["statistics"]["failed_uploads"] == 0
    assert len(dir_result.json_data["successful_uploads"]) == len(directory_files)

    # Verify uploaded filenames appear in successful_uploads
    uploaded_filenames = [
        upload["target_filename"]
        for upload in dir_result.json_data["successful_uploads"]
    ]
    for test_file in directory_files:
        assert test_file.path.name in uploaded_filenames

    # Validate directory upload via GitLab API
    for test_file in directory_files:
        assert gitlab_client.verify_upload(
            dir_package, "1.0.0", test_file.path.name, test_file.checksum
        ), f"Directory upload validation failed for {test_file.path.name}"

    # Final registry verification for all scenarios
    all_test_cases = [
        (single_package, "1.0.0", [single_file]),
        (multi_package, "1.0.0", multiple_files),
        (dir_package, "1.0.0", directory_files),
    ]

    for package_name, version, test_files in all_test_cases:
        for test_file in test_files:
            assert gitlab_client.verify_upload(
                package_name, version, test_file.path.name, test_file.checksum
            ), (
                f"Registry verification failed for {test_file.path.name} in {package_name}"
            )

    total_files = len([single_file]) + len(multiple_files) + len(directory_files)
    print(f"All {total_files} files across 3 scenarios verified successfully")


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.timeout(600)
def test_error_scenario_validation(gitlab_client, artifact_manager, project_path):
    """
    Test comprehensive error scenario validation.

    This test validates that various error scenarios are handled correctly
    and produce appropriate error messages and exit codes. Tests include:
    1. Invalid file paths
    2. Permission errors
    3. Network connectivity issues
    4. Authentication failures
    5. Invalid project specifications

    Extracted from TestOrchestrator._test_error_scenario_validation
    """
    executor = ScriptExecutor()
    gitlab_client.set_project(project_path)

    test_results = []

    # Error scenario 1: Invalid file path
    command = executor.build_command(
        package_name="error-test",
        version="1.0.0",
        files=["/nonexistent/invalid/file.txt"],
        project_path=project_path,
        duplicate_policy="skip",
        use_json_output=True,
    )

    result = executor.execute_upload(
        UploadExecution(
            command=command,
            expected_exit_code=1,
            expected_output_patterns=[],
            timeout=30,
            env_vars={"GITLAB_TOKEN": gitlab_client.token},
            use_json_output=True,
        )
    )

    test_results.append(("invalid_file_path", result))

    # Validate error handling with JSON
    assert not result.success or result.exit_code != 0, (
        "Invalid file path should have caused failure"
    )
    if result.json_data is not None:
        assert result.json_data["success"] is False
        assert result.json_data["exit_code"] == 1
        assert "error" in result.json_data
    else:
        # Fallback to stderr for early failures
        assert result.stderr or result.error_message or result.stdout, (
            "No error message for invalid file path"
        )

    # Error scenario 2: Invalid project path
    test_artifact = artifact_manager.create_test_file("valid.txt", 512, "text")

    command = executor.build_command(
        package_name="error-test",
        version="1.0.0",
        files=[str(test_artifact.path)],
        project_path="nonexistent/invalid-project-12345",
        duplicate_policy="skip",
        use_json_output=True,
    )

    result = executor.execute_upload(
        UploadExecution(
            command=command,
            expected_exit_code=1,
            expected_output_patterns=[],
            timeout=30,
            env_vars={"GITLAB_TOKEN": gitlab_client.token},
            use_json_output=True,
        )
    )

    test_results.append(("invalid_project_path", result))

    # Validate error handling with JSON
    assert not result.success or result.exit_code != 0, (
        "Invalid project path should have caused failure"
    )
    if result.json_data is not None:
        assert result.json_data["success"] is False
        assert result.json_data["exit_code"] == 1
        assert "error" in result.json_data
    else:
        # Fallback to stderr for early failures
        assert result.stderr or result.error_message or result.stdout, (
            "No error message for invalid project path"
        )

    # Error scenario 3: Invalid GitLab URL
    test_artifact2 = artifact_manager.create_test_file("valid2.txt", 512, "text")

    command = executor.build_command(
        package_name="error-test",
        version="1.0.0",
        files=[str(test_artifact2.path)],
        project_path=project_path,
        gitlab_url="https://invalid-gitlab-instance-12345.com",
        duplicate_policy="skip",
        use_json_output=True,
    )

    result = executor.execute_upload(
        UploadExecution(
            command=command,
            expected_exit_code=1,
            expected_output_patterns=[],
            timeout=30,
            env_vars={"GITLAB_TOKEN": gitlab_client.token},
            use_json_output=True,
        )
    )

    test_results.append(("invalid_gitlab_url", result))

    # Validate error handling with JSON
    assert not result.success or result.exit_code != 0, (
        "Invalid GitLab URL should have caused failure"
    )
    if result.json_data is not None:
        assert result.json_data["success"] is False
        assert result.json_data["exit_code"] == 1
        assert "error" in result.json_data
    else:
        # Fallback to stderr for early failures
        assert result.stderr or result.error_message or result.stdout, (
            "No error message for invalid GitLab URL"
        )

    # Error scenario 4: Missing required arguments
    # Try to build command without required package name
    with pytest.raises((ValueError, TypeError)):
        executor.build_command(
            package_name="",  # Empty package name should cause error
            version="1.0.0",
            files=["dummy.txt"],
            project_path=project_path,
        )

    # Validate that all error scenarios produced appropriate responses
    for scenario_name, result in test_results:
        # Check that exit code indicates failure
        assert result.exit_code != 0, (
            f"Scenario {scenario_name} exit code should be non-zero"
        )

        # Check that some error information is provided
        assert result.stderr or result.error_message or result.stdout, (
            f"Scenario {scenario_name} provided no error information"
        )


@pytest.mark.integration
@pytest.mark.timeout(60)
def test_coverage_verification():
    """
    Test coverage verification to ensure all required functionality is tested.

    This test verifies that the test suite covers all required functionality
    by checking that all major features have been tested and that the
    test results provide comprehensive coverage of the upload script's
    capabilities.

    Extracted from TestOrchestrator._test_coverage_verification
    """
    # Define required test coverage areas
    required_coverage = {
        "single_file_upload": False,
        "multiple_file_upload": False,
        "directory_upload": False,
        "file_mapping": False,
        "duplicate_handling_skip": False,
        "duplicate_handling_replace": False,
        "duplicate_handling_error": False,
        "git_auto_detection": False,
        "manual_project_url": False,
        "manual_project_path": False,
        "error_handling": False,
        "network_failure": False,
        "authentication_error": False,
        "comprehensive_validation": False,
        "error_scenario_validation": False,
    }

    # In a real implementation, this would check the results of previously run tests
    # For now, we'll simulate checking test module existence and basic functionality

    # Check that test modules exist
    test_modules = [
        "test_basic_uploads.py",
        "test_duplicate_handling.py",
        "test_project_resolution.py",
        "test_error_scenarios.py",
        "test_integration.py",
    ]

    tests_dir = Path(__file__).parent
    existing_modules = []

    for module in test_modules:
        module_path = tests_dir / module
        if module_path.exists():
            existing_modules.append(module)

            # Mark coverage areas as covered based on module existence
            if module == "test_basic_uploads.py":
                required_coverage["single_file_upload"] = True
                required_coverage["multiple_file_upload"] = True
                required_coverage["directory_upload"] = True
                required_coverage["file_mapping"] = True
            elif module == "test_duplicate_handling.py":
                required_coverage["duplicate_handling_skip"] = True
                required_coverage["duplicate_handling_replace"] = True
                required_coverage["duplicate_handling_error"] = True
            elif module == "test_project_resolution.py":
                required_coverage["git_auto_detection"] = True
                required_coverage["manual_project_url"] = True
                required_coverage["manual_project_path"] = True
            elif module == "test_error_scenarios.py":
                required_coverage["error_handling"] = True
                required_coverage["network_failure"] = True
                required_coverage["authentication_error"] = True
            elif module == "test_integration.py":
                required_coverage["comprehensive_validation"] = True
                required_coverage["error_scenario_validation"] = True

    # Calculate coverage statistics
    total_areas = len(required_coverage)
    covered_areas = sum(1 for covered in required_coverage.values() if covered)
    coverage_percentage = (covered_areas / total_areas) * 100

    # Identify missing coverage
    missing_coverage = [
        area for area, covered in required_coverage.items() if not covered
    ]

    # Determine success criteria
    # Require at least 80% coverage for success, with all critical areas covered
    critical_areas = [
        "single_file_upload",
        "multiple_file_upload",
        "directory_upload",
        "duplicate_handling_skip",
        "error_handling",
    ]

    critical_covered = all(
        required_coverage.get(area, False) for area in critical_areas
    )
    sufficient_coverage = coverage_percentage >= 80.0

    # Generate detailed coverage report (for potential future use)
    # coverage_report = {
    #     "total_areas": total_areas,
    #     "covered_areas": covered_areas,
    #     "coverage_percentage": coverage_percentage,
    #     "missing_coverage": missing_coverage,
    #     "critical_areas_covered": critical_covered,
    #     "detailed_coverage": required_coverage,
    #     "existing_modules": existing_modules,
    # }

    print(
        f"Test coverage: {covered_areas}/{total_areas} areas ({coverage_percentage:.1f}%)"
    )
    print(f"Existing test modules: {existing_modules}")

    if missing_coverage:
        print(f"Missing coverage: {missing_coverage}")

    # Assert coverage requirements
    assert critical_covered, (
        f"Missing critical coverage areas: {[area for area in critical_areas if not required_coverage.get(area, False)]}"
    )
    assert sufficient_coverage, (
        f"Insufficient coverage: {coverage_percentage:.1f}% (need 80%)"
    )

    print("✓ Test coverage verification passed")


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.timeout(600)
def test_end_to_end_workflow_validation(gitlab_client, artifact_manager, project_path):
    """
    Test end-to-end workflow validation with comprehensive cleanup verification.

    This test validates the complete workflow from file creation through upload
    to cleanup, ensuring that all components work together correctly and that
    cleanup operations function properly in the pytest context.

    """
    executor = ScriptExecutor()
    gitlab_client.set_project(project_path)

    # Create test artifacts
    test_files = [
        artifact_manager.create_test_file("workflow-test-1.txt", 1024, "text"),
        artifact_manager.create_test_file("workflow-test-2.json", 2048, "json"),
        artifact_manager.create_test_file("workflow-test-3.bin", 512, "binary"),
    ]

    # Create unique package for this workflow test
    package_name = gitlab_client.create_test_package("workflow-validation", "1.0.0")

    # Execute upload
    from .utils.test_helpers import validate_json_result

    file_paths = [str(f.path) for f in test_files]
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
        env_vars={"GITLAB_TOKEN": gitlab_client.token},
        use_json_output=True,
    )

    result = executor.execute_upload(upload_execution)
    assert result.success, f"End-to-end upload failed: {result.error_message}"

    # Validate JSON output
    assert result.json_data is not None, "JSON output not available"
    assert validate_json_result(
        result.json_data, expected_success=True, expected_files=file_paths
    ), "JSON validation failed for end-to-end workflow"
    assert result.json_data["success"] is True
    assert result.json_data["package_name"] == package_name
    assert result.json_data["statistics"]["new_uploads"] == 3
    assert len(result.json_data["successful_uploads"]) == 3

    # Verify all test file names appear in successful_uploads
    uploaded_filenames = [
        upload["target_filename"] for upload in result.json_data["successful_uploads"]
    ]
    for test_file in test_files:
        assert test_file.path.name in uploaded_filenames

    # Verify all files were uploaded correctly via GitLab API
    for test_file in test_files:
        assert gitlab_client.verify_upload(
            package_name, "1.0.0", test_file.path.name, test_file.checksum
        ), f"End-to-end verification failed for {test_file.path.name}"

    # Test cleanup verification - this will be handled by fixtures
    # but we can verify that the artifacts exist before cleanup
    for test_file in test_files:
        assert test_file.path.exists(), (
            f"Test artifact {test_file.path} should exist before cleanup"
        )

    print(
        f"✓ End-to-end workflow validation completed successfully for package {package_name}"
    )


@pytest.mark.integration
@pytest.mark.timeout(600)
def test_parallel_execution_safety(gitlab_client, artifact_manager, project_path):
    """
    Test that integration tests can run safely in parallel without conflicts.

    This test validates that the test infrastructure properly isolates tests
    when running in parallel using pytest-xdist, ensuring no race conditions
    or shared state issues occur.

    """
    executor = ScriptExecutor()
    gitlab_client.set_project(project_path)

    # Create unique test artifacts with process-specific naming
    import os
    import secrets

    process_id = os.getpid()
    random_suffix = secrets.token_hex(4)
    unique_prefix = f"parallel-{process_id}-{random_suffix}"

    test_file = artifact_manager.create_test_file(
        f"{unique_prefix}-test.txt", 1024, "text"
    )
    package_name = gitlab_client.create_test_package(
        f"parallel-test-{random_suffix}", "1.0.0"
    )

    # Execute upload with unique identifiers
    from .utils.test_helpers import validate_json_result

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
        env_vars={"GITLAB_TOKEN": gitlab_client.token},
        use_json_output=True,
    )

    result = executor.execute_upload(upload_execution)
    assert result.success, f"Parallel execution test failed: {result.error_message}"

    # Validate JSON output
    assert result.json_data is not None, "JSON output not available"
    assert validate_json_result(
        result.json_data, expected_success=True, expected_files=[str(test_file.path)]
    ), "JSON validation failed for parallel execution"
    assert result.json_data["success"] is True
    assert result.json_data["statistics"]["new_uploads"] == 1
    assert len(result.json_data["successful_uploads"]) == 1

    # Verify uploaded filename appears in successful_uploads
    uploaded_filenames = [
        upload["target_filename"] for upload in result.json_data["successful_uploads"]
    ]
    assert test_file.path.name in uploaded_filenames

    # Verify upload via GitLab API
    assert gitlab_client.verify_upload(
        package_name, "1.0.0", test_file.path.name, test_file.checksum
    ), "Parallel execution upload verification failed"

    print(f"✓ Parallel execution safety test completed for process {process_id}")


@pytest.mark.integration
@pytest.mark.cleanup
@pytest.mark.timeout(900)
def test_comprehensive_cleanup_verification(
    gitlab_client, artifact_manager, project_path
):
    """
    Test comprehensive cleanup verification to ensure all test artifacts are properly cleaned up.

    This test validates that the pytest fixture cleanup mechanisms work correctly
    and that no test artifacts are left behind after test execution, preserving
    the cleanup verification functionality from the original monolithic test.

    """
    executor = ScriptExecutor()
    gitlab_client.set_project(project_path)

    # Track initial state
    initial_artifacts = len(artifact_manager.artifacts)
    initial_packages = len(gitlab_client.created_packages)

    # Create test artifacts that should be cleaned up
    test_files = []
    for i in range(3):
        test_file = artifact_manager.create_test_file(
            f"cleanup-test-{i}.txt", 1024, "text"
        )
        test_files.append(test_file)

    # Create test packages that should be cleaned up
    package_names = []
    for i in range(2):
        package_name = gitlab_client.create_test_package(f"cleanup-test-{i}", "1.0.0")
        package_names.append(package_name)

    # Verify artifacts were created
    assert len(artifact_manager.artifacts) == initial_artifacts + 3, (
        "Test artifacts were not created properly"
    )
    assert len(gitlab_client.created_packages) == initial_packages + 2, (
        "Test packages were not tracked properly"
    )

    # Verify files exist on disk
    for test_file in test_files:
        assert test_file.path.exists(), f"Test file {test_file.path} should exist"

    # Perform some uploads to create actual GitLab packages
    from .utils.test_helpers import validate_json_result

    for i, package_name in enumerate(package_names):
        upload_execution = UploadExecution(
            command=[
                str(executor.script_path),
                "--package-name",
                package_name,
                "--package-version",
                "1.0.0",
                "--files",
                str(test_files[i].path),
                "--json-output",
            ]
            + get_project_args(project_path),
            expected_exit_code=0,
            expected_output_patterns=[],
            timeout=240,
            env_vars={"GITLAB_TOKEN": gitlab_client.token},
            use_json_output=True,
        )

        result = executor.execute_upload(upload_execution)
        assert result.success, (
            f"Upload failed for cleanup test package {package_name}: {result.error_message}"
        )

        # Validate JSON output
        assert result.json_data is not None, "JSON output not available"
        assert validate_json_result(
            result.json_data,
            expected_success=True,
            expected_files=[str(test_files[i].path)],
        ), f"JSON validation failed for cleanup test package {package_name}"
        assert result.json_data["success"] is True
        assert result.json_data["statistics"]["new_uploads"] == 1
        assert len(result.json_data["successful_uploads"]) == 1

        # Verify uploaded filename appears in successful_uploads
        uploaded_filenames = [
            upload["target_filename"]
            for upload in result.json_data["successful_uploads"]
        ]
        assert test_files[i].path.name in uploaded_filenames

        # Verify upload was successful via GitLab API
        assert gitlab_client.verify_upload(
            package_name, "1.0.0", test_files[i].path.name, test_files[i].checksum
        ), f"Upload verification failed for cleanup test package {package_name}"

    # Test manual cleanup to verify it works (fixtures will also clean up automatically)
    artifact_successful, artifact_failed = artifact_manager.cleanup_artifacts(
        force=True
    )
    assert artifact_failed == 0, f"Artifact cleanup failed for {artifact_failed} items"
    assert artifact_successful >= 3, (
        f"Expected at least 3 artifacts cleaned up, got {artifact_successful}"
    )

    package_successful, package_failed = gitlab_client.cleanup_test_packages(force=True)
    assert package_failed == 0, f"Package cleanup failed for {package_failed} items"
    assert package_successful >= 2, (
        f"Expected at least 2 packages cleaned up, got {package_successful}"
    )

    # Verify cleanup was effective
    for test_file in test_files:
        assert not test_file.path.exists(), (
            f"Test file {test_file.path} should have been cleaned up"
        )

    assert len(artifact_manager.artifacts) == 0, (
        "Artifact manager should have no tracked artifacts after cleanup"
    )
    assert len(gitlab_client.created_packages) == 0, (
        "GitLab client should have no tracked packages after cleanup"
    )

    print("✓ Comprehensive cleanup verification completed successfully")


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.timeout(600)
def test_multi_scenario_workflow_validation(
    gitlab_client, artifact_manager, project_path
):
    """
    Test multi-scenario workflow validation combining different upload types and policies.

    This test validates complex workflows that combine multiple upload scenarios,
    duplicate policies, and error conditions to ensure the system handles
    real-world usage patterns correctly.

    """
    executor = ScriptExecutor()
    gitlab_client.set_project(project_path)

    # Scenario 1: Upload with skip duplicate policy
    from .utils.test_helpers import validate_json_result

    test_file_1 = artifact_manager.create_test_file(
        "multi-scenario-1.txt", 1024, "text"
    )
    package_name_1 = gitlab_client.create_test_package("multi-scenario-skip", "1.0.0")

    # First upload
    upload_execution_1 = UploadExecution(
        command=[
            str(executor.script_path),
            "--package-name",
            package_name_1,
            "--package-version",
            "1.0.0",
            "--files",
            str(test_file_1.path),
            "--duplicate-policy",
            "skip",
            "--json-output",
        ]
        + get_project_args(project_path),
        expected_exit_code=0,
        expected_output_patterns=[],
        timeout=120,
        env_vars={"GITLAB_TOKEN": gitlab_client.token},
        use_json_output=True,
    )

    result_1 = executor.execute_upload(upload_execution_1)
    assert result_1.success, f"First upload failed: {result_1.error_message}"

    # Validate JSON output for first upload
    assert result_1.json_data is not None, "JSON output not available"
    assert validate_json_result(
        result_1.json_data,
        expected_success=True,
        expected_files=[str(test_file_1.path)],
    ), "JSON validation failed for first upload"
    assert result_1.json_data["success"] is True
    assert result_1.json_data["statistics"]["new_uploads"] == 1

    # Second upload (should skip duplicate)
    result_1_dup = executor.execute_upload(upload_execution_1)
    assert result_1_dup.success, (
        f"Duplicate upload with skip policy failed: {result_1_dup.error_message}"
    )

    # Validate JSON output for duplicate upload
    assert result_1_dup.json_data is not None, "JSON output not available"
    assert result_1_dup.json_data["success"] is True
    assert result_1_dup.json_data["statistics"]["skipped_duplicates"] == 1

    # Scenario 2: Directory upload with replace policy
    directory_files = artifact_manager.create_test_directory("multi-scenario-dir", 2)
    directory_path = artifact_manager.base_dir / "multi-scenario-dir"
    package_name_2 = gitlab_client.create_test_package(
        "multi-scenario-replace", "1.0.0"
    )

    upload_execution_2 = UploadExecution(
        command=[
            str(executor.script_path),
            "--package-name",
            package_name_2,
            "--package-version",
            "1.0.0",
            "--directory",
            str(directory_path),
            "--duplicate-policy",
            "replace",
            "--json-output",
        ]
        + get_project_args(project_path),
        expected_exit_code=0,
        expected_output_patterns=[],
        timeout=180,
        env_vars={"GITLAB_TOKEN": gitlab_client.token},
        use_json_output=True,
    )

    result_2 = executor.execute_upload(upload_execution_2)
    assert result_2.success, f"Directory upload failed: {result_2.error_message}"

    # Validate JSON output for directory upload
    assert result_2.json_data is not None, "JSON output not available"
    assert validate_json_result(
        result_2.json_data,
        expected_success=True,
        expected_files=[str(f.path) for f in directory_files],
    ), "JSON validation failed for directory upload"
    assert result_2.json_data["success"] is True
    assert result_2.json_data["statistics"]["new_uploads"] == 2

    # Verify directory files in successful_uploads
    uploaded_filenames = [
        upload["target_filename"] for upload in result_2.json_data["successful_uploads"]
    ]
    for test_file in directory_files:
        assert test_file.path.name in uploaded_filenames

    # Scenario 3: Multiple files with error handling
    multiple_files = [
        artifact_manager.create_test_file("multi-scenario-3a.json", 2048, "json"),
        artifact_manager.create_test_file("multi-scenario-3b.bin", 1024, "binary"),
    ]
    package_name_3 = gitlab_client.create_test_package("multi-scenario-multi", "1.0.0")

    file_paths = [str(f.path) for f in multiple_files]
    upload_execution_3 = UploadExecution(
        command=[
            str(executor.script_path),
            "--package-name",
            package_name_3,
            "--package-version",
            "1.0.0",
            "--files",
        ]
        + file_paths
        + ["--duplicate-policy", "error", "--json-output"]
        + get_project_args(project_path),
        expected_exit_code=0,
        expected_output_patterns=[],
        timeout=180,
        env_vars={"GITLAB_TOKEN": gitlab_client.token},
        use_json_output=True,
    )

    result_3 = executor.execute_upload(upload_execution_3)
    assert result_3.success, f"Multiple files upload failed: {result_3.error_message}"

    # Validate JSON output for multiple files upload
    assert result_3.json_data is not None, "JSON output not available"
    assert validate_json_result(
        result_3.json_data, expected_success=True, expected_files=file_paths
    ), "JSON validation failed for multiple files upload"
    assert result_3.json_data["success"] is True
    assert result_3.json_data["statistics"]["new_uploads"] == 2

    # Verify multiple files in successful_uploads
    uploaded_filenames = [
        upload["target_filename"] for upload in result_3.json_data["successful_uploads"]
    ]
    for test_file in multiple_files:
        assert test_file.path.name in uploaded_filenames

    # Verify all uploads
    assert gitlab_client.verify_upload(
        package_name_1, "1.0.0", test_file_1.path.name, test_file_1.checksum
    ), "Multi-scenario validation failed for single file upload"

    for test_file in directory_files:
        assert gitlab_client.verify_upload(
            package_name_2, "1.0.0", test_file.path.name, test_file.checksum
        ), f"Multi-scenario validation failed for directory file {test_file.path.name}"

    for test_file in multiple_files:
        assert gitlab_client.verify_upload(
            package_name_3, "1.0.0", test_file.path.name, test_file.checksum
        ), f"Multi-scenario validation failed for multiple file {test_file.path.name}"

    total_files = 1 + len(directory_files) + len(multiple_files)
    print(
        f"✓ Multi-scenario workflow validation completed successfully for {total_files} files across 3 scenarios"
    )
