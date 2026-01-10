"""
Integration tests package for GitLab package upload CLI.

This package contains integration tests that use direct module invocation
instead of subprocess execution. Tests call the CLI main() function directly
to improve test isolation and reduce overhead.

Test Modules:
    - test_helpers_module: ModuleExecutor and helper utilities
    - test_single_file_upload: Single file upload tests
    - test_multiple_files_upload: Multiple files and directory upload tests
    - test_duplicate_handling: Duplicate handling policy tests
    - test_project_resolution: Project resolution tests
    - test_error_scenarios: Error handling tests
    - test_end_to_end: Comprehensive end-to-end tests

Usage:
    Run all integration tests:
        pytest tests/integration/ -v

    Run specific test file:
        pytest tests/integration/test_single_file_upload.py -v

    Run with parallel execution:
        pytest tests/integration/ -n auto

Test Markers:
    - integration: All integration tests
    - api: Tests requiring GitLab API access
    - slow: Tests that take longer to run
    - fast: Tests that run quickly
    - cleanup: Tests that verify cleanup functionality
"""
