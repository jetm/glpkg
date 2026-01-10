# GitLab Package Upload Test Suite

This directory contains a comprehensive pytest-based test suite for the GitLab package upload functionality. The test suite has been refactored from a monolithic test file into focused, maintainable modules that can be run individually or as a complete suite.

## Overview

The test suite validates the [`gitlab-pkg-upload.py`](../gitlab-pkg-upload.py) script through end-to-end testing, executing the actual script and verifying results against the GitLab Package Registry. Tests use real GitLab API interactions for authentic validation without mocking.

## Quick Start

### Basic Usage

```bash
# Run all available tests (unit tests if no GITLAB_TOKEN)
./run_tests.py

# Run only unit tests (fast, no external dependencies)
./run_tests.py --unit

# Run integration tests (requires GITLAB_TOKEN, takes 10-15 minutes)
export GITLAB_TOKEN="your-token"
./run_tests.py --integration

# Run all test categories sequentially
./run_tests.py --all
```

### Advanced Usage

```bash
# Run specific test file
./run_tests.py tests/test_basic_uploads.py

# Run specific test function
./run_tests.py tests/test_basic_uploads.py::test_single_file_upload

# Run with parallel execution
./run_tests.py -n auto tests/

# Run with verbose output and stop on first failure
./run_tests.py -v -x tests/

# Filter tests by marker
./run_tests.py -m "unit and not slow"

# Show 10 slowest tests
./run_tests.py --durations=10 tests/
```

### Getting Help

```bash
# Show wrapper help
./run_tests.py --help

# Show pytest help (pass-through mode)
./run_tests.py --help
```

## Test Structure

```
tests/
├── conftest.py                    # Shared fixtures and configuration
├── conftest_performance.py        # Performance tracking plugin
├── test_basic_uploads.py          # Single file, multiple files, directory uploads
├── test_duplicate_handling.py     # Skip, replace, error policies
├── test_project_resolution.py     # Auto-detection and manual specification
├── test_error_scenarios.py        # Network failures, auth errors, validation
├── test_integration.py            # End-to-end comprehensive scenarios
├── test_fixtures.py               # Fixture validation tests
├── utils/
│   ├── __init__.py
│   ├── test_helpers.py            # Common test utilities
│   ├── artifact_factory.py       # Test file creation utilities
│   ├── gitlab_helpers.py          # GitLab API interaction utilities
│   ├── rate_limiter.py            # API rate limiting utilities
│   └── performance.py             # Performance monitoring utilities
└── README.md                      # This file

../
├── run_tests.py                   # Test runner with uv dependency management
└── pyproject.toml                 # Project configuration and pytest settings
```

## Prerequisites

### Dependency Management

All test dependencies are managed automatically by the uv package manager through the [`run_tests.py`](../run_tests.py) script. No manual installation is required.

### GitLab Configuration

Set the following environment variables:
```bash
export GITLAB_TOKEN="your-gitlab-token"
export GITLAB_URL="https://gitlab.example.com"  # Optional, defaults to GitLab.com
export GITLAB_PROJECT_PATH="group/project"      # Optional, can auto-detect from git
```

### Git Repository

Tests can auto-detect GitLab project from the current git repository, or you can specify manually via environment variables.

### Required Permissions

Your GitLab token needs the following permissions:
- `api` scope for full API access
- Write access to the target project's Package Registry
- Ability to create and delete packages in the registry

## Pytest Plugins

The test suite uses the following pytest plugins:

| Plugin | Purpose | Usage |
|--------|---------|-------|
| **pytest-xdist** | Parallel test execution | Enables running tests across multiple CPU cores with `-n auto` flag for faster execution |
| **pytest-timeout** | Test timeout management | Automatically fails tests that exceed time limits; configured with markers like `@pytest.mark.timeout(60)` |
| **pytest-sugar** | Progress visualization | Provides real-time progress bars and improved test output formatting |
| **pytest-instafail** | Instant failure reporting | Shows test failures immediately as they occur, enabled by default with `--instafail` flag |

**Note**: These plugins are automatically installed when running tests via [`run_tests.py`](../run_tests.py) using the uv package manager. Plugin configuration is defined in [`pyproject.toml`](../pyproject.toml) under `[tool.pytest.ini_options]`.

## Running Tests

### Using the Test Runner (Primary Method)

The [`run_tests.py`](../run_tests.py) script is the primary and recommended method for running tests. It automatically manages dependencies using uv and provides convenient test execution options.

```bash
# Run all available tests (auto-detects GITLAB_TOKEN)
./run_tests.py

# Run only unit tests (fast, no external dependencies)
./run_tests.py --unit

# Run only integration tests (requires GITLAB_TOKEN, takes 10-15 minutes)
./run_tests.py --integration

# Run configuration validation tests
./run_tests.py --config

# Run all test categories sequentially
./run_tests.py --all
```

### Pass-Through Mode for Advanced Usage

Any arguments not matching convenience flags are passed directly to pytest, enabling advanced usage:

```bash
# Run specific test
./run_tests.py tests/test_unit_basic.py::TestBasicFunctionality::test_import_gitlab_pkg_upload

# Filter tests by name pattern
./run_tests.py -v -k "test_import" tests/

# Run with parallel execution
./run_tests.py -n auto tests/

# Filter by marker
./run_tests.py -m "unit and not slow"

# Combine multiple pytest options
./run_tests.py -v -x -n auto tests/test_basic_uploads.py
```

### Duration Reporting

The wrapper automatically adds `--durations` flags to show test timing information:

```bash
# Show 5 slowest tests
./run_tests.py --durations=5 tests/

# Show tests taking at least 2 seconds
./run_tests.py --durations-min=2.0 tests/

# Disable duration reporting
./run_tests.py --durations=0 tests/
```

### Direct pytest Execution (Not Recommended)

Direct pytest execution requires manual dependency installation with uv and is only for advanced users who need full pytest control:

```bash
# Install dependencies manually
uv pip install -r requirements-test.txt

# Run pytest directly
pytest

# Run with verbose output
pytest -v

# Run with parallel execution
pytest -n auto
```

### Run Specific Test Modules

```bash
# Test basic upload functionality
./run_tests.py tests/test_basic_uploads.py

# Test duplicate handling policies
./run_tests.py tests/test_duplicate_handling.py

# Test project resolution
./run_tests.py tests/test_project_resolution.py

# Test error scenarios
./run_tests.py tests/test_error_scenarios.py

# Test integration scenarios
./run_tests.py tests/test_integration.py
```

### Run Tests by Markers

```bash
# Run only fast tests
./run_tests.py -m fast

# Run only integration tests
./run_tests.py -m integration

# Skip slow tests
./run_tests.py -m "not slow"

# Run only API tests
./run_tests.py -m api

# Run sequential tests only
./run_tests.py -m sequential
```

## Test Execution Time

### Expected Duration

- **Unit tests**: 10-30 seconds (no external dependencies)
- **Integration tests**: 10-15 minutes (full suite with GitLab API operations)
- **Individual integration tests**: 30-120 seconds each

### Reasons for Slow Execution

Integration tests interact with real GitLab infrastructure, which introduces several time factors:

- **Real GitLab API Operations**: Tests perform actual uploads, deletions, and verifications against the GitLab Package Registry
- **Rate Limiting**: Thread-safe rate limiter prevents API overload and respects GitLab rate limits (implemented in [`utils/rate_limiter.py`](utils/rate_limiter.py))
- **Sequential Package Operations**: Each test creates unique packages, uploads files, verifies checksums, and cleans up
- **Network Latency**: Communication with GitLab servers introduces inherent delays
- **Checksum Verification**: Post-upload validation downloads files and verifies SHA256 checksums
- **Parallel Execution Overhead**: When using `-n auto`, pytest-xdist coordination adds slight overhead

### Progress Monitoring

The test suite provides several mechanisms for monitoring progress:

- **pytest-sugar**: Provides real-time progress bars during execution
- **pytest-instafail**: Shows failures immediately as they occur
- **Duration reporting**: Shows timing for each test at the end
- **Wrapper script**: Shows elapsed time after completion

## Debugging Test Failures

### Using the Test Runner for Debugging

The [`run_tests.py`](../run_tests.py) wrapper supports all pytest debugging options:

```bash
# Verbose output
./run_tests.py -v tests/test_basic_uploads.py

# Extra verbose output
./run_tests.py -vv tests/test_basic_uploads.py

# Stop on first failure
./run_tests.py -x tests/

# Full traceback
./run_tests.py --tb=long tests/

# Short traceback (default)
./run_tests.py --tb=short tests/

# Maximum verbosity for specific test
./run_tests.py -vvv --tb=long tests/test_basic_uploads.py::test_single_file_upload
```

### Common Debugging Scenarios

#### Authentication Issues

If you encounter authentication errors:

- Check `GITLAB_TOKEN` is set and valid
- Verify token hasn't expired
- Ensure token has `api` scope and write access to Package Registry
- Test with: `./run_tests.py --unit` (doesn't require token)

#### Timeout Errors

Integration tests have extended timeouts to accommodate GitLab API operations:

- Integration tests: 600s timeout (configured in [`pyproject.toml`](../pyproject.toml))
- Slow integration tests: 900s timeout
- If tests timeout, check network connectivity to GitLab
- Consider running sequentially: `./run_tests.py -m integration` (without `-n auto`)
- For very slow networks: `./run_tests.py --timeout=1200 tests/`

#### Parallel Execution Issues

If tests fail in parallel but pass sequentially:

- May indicate a race condition or resource conflict
- Run sequentially for debugging: `./run_tests.py tests/` (without `-n auto`)
- Check rate limiter is working properly in [`utils/rate_limiter.py`](utils/rate_limiter.py)
- Verify unique package naming includes worker ID

#### Package Cleanup Failures

Tests automatically clean up packages in fixture teardown:

- If cleanup fails, packages may remain in GitLab registry
- Manual cleanup: access GitLab project → Packages & Registries → Delete test packages
- Test packages are prefixed with `test-` and include timestamps
- Run cleanup tests: `./run_tests.py -m cleanup`

### Viewing Test Logs

Control log output verbosity:

```bash
# pytest-sugar provides clean output by default
./run_tests.py tests/

# Enable debug logging
./run_tests.py --log-cli-level=DEBUG tests/

# Show INFO level logs
./run_tests.py --log-cli-level=INFO tests/

# Combine with verbose output
./run_tests.py -v --log-cli-level=DEBUG tests/test_basic_uploads.py
```

**Note**: GitLab API calls are rate-limited and logged in verbose mode.

## Parallel Execution

### Using Parallel Execution

Parallel execution uses the pytest-xdist plugin to run tests across multiple CPU cores:

```bash
# Auto-detect CPU cores
./run_tests.py -n auto tests/

# Specify worker count manually
./run_tests.py -n 4 tests/

# Use worksteal distribution for better load balancing
./run_tests.py --dist=worksteal -n auto tests/
```

### Parallel Execution Safety

Tests are designed for safe parallel execution with:

- **Unique package names per test**: Timestamp + worker ID + random suffix
- **Thread-safe rate limiting**: For GitLab API calls across all workers
- **Isolated temporary directories**: Per worker isolation
- **Automatic cleanup**: In fixture teardown

**Note**: Tests marked with `@pytest.mark.sequential` run sequentially even with `-n auto`.

### Performance Considerations

- **Parallel execution reduces total time** but increases API load
- **Rate limiter prevents API overload** across all workers
- **Optimal worker count**: `-n auto` (matches CPU cores)
- **For debugging**: Run sequentially without `-n` flag

## Test Categories

### Basic Upload Tests ([`test_basic_uploads.py`](test_basic_uploads.py))
- **Single file upload**: Tests uploading individual files
- **Multiple file upload**: Tests uploading multiple files in one command
- **Directory upload**: Tests uploading entire directories
- **File mapping**: Tests custom file-to-package mapping

### Duplicate Handling Tests ([`test_duplicate_handling.py`](test_duplicate_handling.py))
- **Skip policy**: Tests skipping existing packages
- **Replace policy**: Tests replacing existing packages
- **Error policy**: Tests error handling for duplicates

### Project Resolution Tests ([`test_project_resolution.py`](test_project_resolution.py))
- **Git auto-detection**: Tests automatic project detection from git remote
- **Manual URL specification**: Tests explicit project URL specification
- **Manual path specification**: Tests explicit project path specification

### Error Scenario Tests ([`test_error_scenarios.py`](test_error_scenarios.py))
- **Network failures**: Tests handling of network connectivity issues
- **Authentication errors**: Tests handling of invalid tokens or permissions
- **Invalid inputs**: Tests handling of invalid file paths or project specifications
- **Error message validation**: Tests that error messages are informative

### Integration Tests ([`test_integration.py`](test_integration.py))
- **End-to-end scenarios**: Tests complete upload workflows
- **Multi-scenario validation**: Tests complex scenarios with multiple operations
- **Performance validation**: Tests upload performance and reliability

## Adding New Tests

### Creating a New Test Function

1. **Choose the appropriate test module** based on functionality
2. **Follow pytest naming conventions** (`test_*` functions)
3. **Use existing fixtures** for common setup
4. **Add appropriate markers** for categorization

Example:
```python
import pytest
from utils.test_helpers import execute_upload_script
from utils.gitlab_helpers import verify_package_exists

@pytest.mark.api
@pytest.mark.fast
def test_new_upload_scenario(gitlab_client, artifact_manager, temp_dir):
    """Test a new upload scenario."""
    # Create test file
    test_file = artifact_manager.create_test_file("test.txt", size=100)

    # Execute upload script
    result = execute_upload_script(
        files=[test_file.path],
        package_name="test-package",
        version="1.0.0",
        working_dir=temp_dir
    )

    # Verify success
    assert result.exit_code == 0
    assert "Upload successful" in result.stdout

    # Verify in GitLab
    assert verify_package_exists(
        gitlab_client,
        "test-package",
        "1.0.0",
        "test.txt"
    )
```

### Creating a New Test Module

1. **Create new file** following `test_*.py` naming convention
2. **Import required fixtures** from [`conftest.py`](conftest.py)
3. **Add module docstring** describing the test category
4. **Use appropriate markers** for the entire module

Example:
```python
"""Tests for new functionality category."""

import pytest
from utils.test_helpers import execute_upload_script

# Mark all tests in this module
pytestmark = [pytest.mark.api, pytest.mark.integration]

def test_new_functionality(gitlab_client, artifact_manager):
    """Test new functionality."""
    # Test implementation
    pass
```

### Available Fixtures

The test suite provides several fixtures for common operations:

- **`gitlab_client`**: Authenticated GitLab client
- **`artifact_manager`**: Test file creation and cleanup
- **`temp_dir`**: Isolated temporary directory
- **`project_resolver`**: Project identification utilities
- **`rate_limiter`**: API rate limiting management

### Test Markers

Use these markers to categorize your tests:

- **`@pytest.mark.fast`**: Quick tests that can run in parallel
- **`@pytest.mark.slow`**: Tests that take longer to execute
- **`@pytest.mark.integration`**: End-to-end integration tests
- **`@pytest.mark.api`**: Tests requiring GitLab API access
- **`@pytest.mark.sequential`**: Tests that must run sequentially
- **`@pytest.mark.cleanup`**: Tests that perform cleanup operations

## Troubleshooting

### Common Issues

#### Authentication Errors
- Verify `GITLAB_TOKEN` is set and valid
- Check token has required permissions (`api` scope)
- Ensure token hasn't expired
- Test with unit tests: `./run_tests.py --unit` (doesn't require token)

#### Project Not Found
- Verify `GITLAB_PROJECT_PATH` is correct
- Check git remote URL is accessible
- Ensure project exists and is accessible
- Try manual specification: `export GITLAB_PROJECT_PATH="group/project"`

#### Network Timeouts
- Check network connectivity to GitLab instance
- Verify GitLab URL is correct
- Consider running tests sequentially if parallel execution fails
- Increase timeout: `./run_tests.py --timeout=1200 tests/`

#### Integration Test Timeouts
- Integration tests have extended timeouts (600-900s)
- Timeout errors indicate network issues or GitLab API slowness
- Try running sequentially: `./run_tests.py -m integration`
- For very slow networks: `./run_tests.py --timeout=1200 tests/`

#### Test Failures
- Check test output for specific error messages
- Verify all environment variables are set
- Ensure no leftover test artifacts from previous runs
- See [Debugging Test Failures](#debugging-test-failures) section

### Debug Mode

Run tests with additional debugging information using the [`run_tests.py`](../run_tests.py) wrapper:

```bash
# Enable debug logging
./run_tests.py -v --log-cli-level=DEBUG tests/

# Show local variables on failure
./run_tests.py --tb=long tests/

# Stop on first failure
./run_tests.py -x tests/

# Run specific test with maximum verbosity
./run_tests.py -vvv --tb=long tests/test_basic_uploads.py::test_single_file_upload

# Combine multiple debugging options
./run_tests.py -vvv -x --tb=long --log-cli-level=DEBUG tests/
```

### Cleanup

If tests are interrupted and leave artifacts:

```bash
# Run cleanup tests specifically
./run_tests.py -m cleanup

# Manual cleanup (if needed)
python -c "
from tests.conftest import cleanup_test_packages
cleanup_test_packages()
"
```

## Performance Considerations

### Parallel Execution

Tests are designed to run in parallel safely. See the [Parallel Execution](#parallel-execution) section for detailed information.

- Use `./run_tests.py -n auto tests/` for optimal parallel execution
- Sequential tests are marked with `@pytest.mark.sequential`
- Rate limiting prevents API overload across all workers
- Unique package names include worker ID to prevent conflicts

### Test Isolation

- Each test uses unique package names and versions
- Package names include worker ID to prevent conflicts
- Temporary directories provide file system isolation
- Automatic cleanup prevents resource leaks
- Fixtures ensure proper setup and teardown

### Resource Management

- API rate limiting prevents GitLab API overload (see [`utils/rate_limiter.py`](utils/rate_limiter.py))
- Temporary files are cleaned up automatically
- Test packages are removed from GitLab registry
- Memory usage is minimized through efficient fixtures
- Performance tracking is enabled via [`conftest_performance.py`](conftest_performance.py) plugin
- Duration reporting shows timing for each test automatically

## Test Execution Methods Summary

| Method | Use Case | Duration | Requirements |
|--------|----------|----------|--------------|
| `./run_tests.py` | Default, all available tests | 10s-15m | None (auto-detects token) |
| `./run_tests.py --unit` | Fast validation, no external deps | 10-30s | None |
| `./run_tests.py --integration` | Full GitLab API testing | 10-15m | GITLAB_TOKEN |
| `./run_tests.py --all` | Complete test suite | 15-20m | GITLAB_TOKEN (optional) |
| `./run_tests.py -n auto` | Parallel execution | 5-10m | GITLAB_TOKEN |
| `./run_tests.py -v -x` | Debugging failures | Varies | None |

## Contributing

When contributing new tests:

1. **Follow existing patterns** for consistency
2. **Add appropriate documentation** and docstrings
3. **Use existing fixtures** to avoid duplication
4. **Add proper markers** for categorization
5. **Ensure cleanup** of any created resources
6. **Test both success and failure scenarios**
7. **Run tests locally** before submitting: `./run_tests.py --all`
