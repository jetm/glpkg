"""
Quick verification test for JSON output support in test_helpers.

This test verifies that the JSON output functionality works correctly
without requiring actual GitLab API calls.
"""

import json

from .test_helpers import (
    ScriptExecutor,
    UploadResult,
    validate_json_result,
)


def test_parse_json_output():
    """Test JSON parsing from stdout."""
    executor = ScriptExecutor()

    # Test valid JSON
    json_output = json.dumps(
        {
            "success": True,
            "exit_code": 0,
            "package_name": "test-pkg",
            "version": "1.0.0",
            "successful_uploads": [
                {
                    "target_filename": "test.tar.gz",
                    "download_url": "https://example.com/test.tar.gz",
                }
            ],
            "skipped_duplicates": [],
            "failed_uploads": [],
            "statistics": {
                "total_processed": 1,
                "new_uploads": 1,
                "replaced_duplicates": 0,
                "skipped_duplicates": 0,
                "failed_uploads": 0,
            },
        }
    )

    parsed = executor._parse_json_output(json_output)
    assert parsed is not None
    assert parsed["success"] is True
    assert parsed["exit_code"] == 0
    print("✓ JSON parsing works correctly")


def test_extract_data_from_json():
    """Test extracting files and URLs from JSON."""
    executor = ScriptExecutor()

    json_data = {
        "success": True,
        "successful_uploads": [
            {
                "target_filename": "file1.tar.gz",
                "download_url": "https://example.com/file1.tar.gz",
            },
            {
                "target_filename": "file2.tar.gz",
                "download_url": "https://example.com/file2.tar.gz",
            },
        ],
    }

    files, urls = executor._extract_data_from_json(json_data)
    assert len(files) == 2
    assert "file1.tar.gz" in files
    assert "file2.tar.gz" in files
    assert len(urls) == 2
    assert "https://example.com/file1.tar.gz" in urls
    print("✓ Data extraction from JSON works correctly")


def test_validate_json_result_success():
    """Test JSON result validation for success case."""
    json_data = {
        "success": True,
        "exit_code": 0,
        "package_name": "test-pkg",
        "version": "1.0.0",
        "successful_uploads": [
            {"target_filename": "test.tar.gz", "download_url": "https://example.com"}
        ],
        "skipped_duplicates": [],
        "failed_uploads": [],
        "statistics": {
            "total_processed": 1,
            "new_uploads": 1,
            "replaced_duplicates": 0,
            "skipped_duplicates": 0,
            "failed_uploads": 0,
        },
    }

    # Test without expected files
    assert validate_json_result(json_data, expected_success=True)

    # Test with expected files
    assert validate_json_result(
        json_data, expected_success=True, expected_files=["test.tar.gz"]
    )

    # Test with missing file
    assert not validate_json_result(
        json_data, expected_success=True, expected_files=["missing.tar.gz"]
    )

    print("✓ JSON validation for success case works correctly")


def test_validate_json_result_failure():
    """Test JSON result validation for failure case."""
    json_data = {
        "success": False,
        "exit_code": 1,
        "error": "Authentication failed",
        "error_type": "AuthenticationError",
    }

    assert validate_json_result(json_data, expected_success=False)
    assert not validate_json_result(json_data, expected_success=True)

    print("✓ JSON validation for failure case works correctly")


def test_build_command_with_json_flag():
    """Test that build_command adds --json-output flag."""
    executor = ScriptExecutor()

    # Test with use_json_output=True
    command = executor.build_command(
        use_json_output=True,
        package_name="test-pkg",
        version="1.0.0",
        files="test.tar.gz",
    )

    assert "--json-output" in command
    print("✓ build_command adds --json-output flag correctly")


def test_create_execution_with_json_mode():
    """Test creating execution with JSON mode enabled."""
    executor = ScriptExecutor()

    execution = executor.create_single_file_execution(
        package_name="test-pkg",
        version="1.0.0",
        file_path="test.tar.gz",
        use_json_output=True,
    )

    assert execution.use_json_output is True
    assert "--json-output" in execution.command
    assert execution.expected_output_patterns == []  # No regex patterns in JSON mode

    print("✓ Execution creation with JSON mode works correctly")


def test_backward_compatibility():
    """Test that existing functionality still works without JSON mode."""
    executor = ScriptExecutor()

    execution = executor.create_single_file_execution(
        package_name="test-pkg",
        version="1.0.0",
        file_path="test.tar.gz",
        # use_json_output defaults to False
    )

    assert execution.use_json_output is False
    assert "--json-output" not in execution.command
    assert len(execution.expected_output_patterns) > 0  # Regex patterns present

    print("✓ Backward compatibility maintained")


def test_upload_result_with_json_data():
    """Test UploadResult with json_data field."""
    json_data = {"success": True, "exit_code": 0}

    result = UploadResult(
        success=True,
        exit_code=0,
        stdout="{}",
        stderr="",
        duration=1.0,
        uploaded_files=["test.tar.gz"],
        upload_urls=["https://example.com"],
        json_data=json_data,
    )

    assert result.json_data is not None
    assert result.json_data["success"] is True

    print("✓ UploadResult with json_data works correctly")


if __name__ == "__main__":
    print("Running JSON output support verification tests...\n")

    try:
        test_parse_json_output()
        test_extract_data_from_json()
        test_validate_json_result_success()
        test_validate_json_result_failure()
        test_build_command_with_json_flag()
        test_create_execution_with_json_mode()
        test_backward_compatibility()
        test_upload_result_with_json_data()

        print("\n✅ All verification tests passed!")
        print("\nJSON output support has been successfully implemented.")
        print("The implementation is backward compatible with existing tests.")

    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        raise
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        raise
