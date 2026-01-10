# GitLab Package Upload Test Suite

This directory contains a comprehensive pytest-based test suite for the GitLab package upload functionality. The test suite validates the `gitlab-pkg-upload` command through both unit tests and end-to-end integration testing.

## Overview

The test suite is organized into two categories:

- **Unit tests** (`tests/unit/`): Fast tests that validate individual components without external dependencies
- **Integration tests** (`tests/integration/`): End-to-end tests that execute the actual upload script and verify results against the GitLab Package Registry

## Quick Start

All test dependencies are automatically managed by uv. However, the `gitlab_pkg_upload` package must be installed in development mode before running tests.

```bash
# Install the package in development mode (required before running tests)
uv pip install -e .

# Run all tests
uv run pytest tests/

# Run only unit tests (fast, no external dependencies)
uv run pytest tests/unit/

# Run integration tests (requires GITLAB_TOKEN)
export GITLAB_TOKEN="your-token"
uv run pytest tests/integration/ -m integration

# Run with parallel execution
uv run pytest tests/ -n auto

# Run with verbose output
uv run pytest tests/ -v
```

### Using the Convenience Wrapper

The `run_tests.py` script provides convenience commands that delegate to `uv run pytest`:

```bash
# Run unit tests
./run_tests.py --unit

# Run integration tests
./run_tests.py --integration

# Run all test categories
./run_tests.py --all

# Pass-through to pytest
./run_tests.py -v -k "test_import" tests/
```

## Test Structure

```
tests/
├── conftest.py                    # Shared fixtures and configuration
├── unit/                          # Unit tests (no external dependencies)
│   ├── __init__.py
│   ├── test_cli.py                # CLI argument parsing and validation
│   ├── test_models.py             # Data models and structures
│   ├── test_uploader.py           # Upload logic and file handling
│   └── test_validators.py         # Input validation functions
├── integration/                   # Integration tests (requires GITLAB_TOKEN)
│   ├── __init__.py
│   ├── conftest.py                # Integration-specific fixtures
│   ├── test_single_file_upload.py # Single file upload tests
│   ├── test_multiple_files_upload.py # Multiple files upload tests
│   ├── test_duplicate_handling.py # Skip, replace, error policies
│   ├── test_project_resolution.py # Auto-detection and manual specification
│   ├── test_error_scenarios.py    # Network failures, auth errors
│   └── test_end_to_end.py         # Comprehensive end-to-end scenarios
├── utils/
│   ├── __init__.py
│   ├── test_helpers.py            # Common test utilities
│   ├── artifact_factory.py        # Test file creation utilities
│   ├── gitlab_helpers.py          # GitLab API interaction utilities
│   ├── rate_limiter.py            # API rate limiting utilities
│   └── performance.py             # Performance monitoring utilities
└── README.md                      # This file

../
├── run_tests.py                   # Convenience wrapper for uv run pytest
└── pyproject.toml                 # Project configuration and pytest settings
```

## Prerequisites

### Dependency Management

All test dependencies are automatically installed by uv when running `uv run pytest`. The dependencies are defined in `pyproject.toml` under `[project.optional-dependencies]`:

- pytest
- pytest-xdist (parallel execution)
- pytest-timeout (timeout management)
- pytest-sugar (progress visualization)
- pytest-instafail (instant failure reporting)

**Important**: The `gitlab_pkg_upload` package itself must be installed in development mode before running tests:

```bash
uv pip install -e .
```

Alternatively, you can use `pip install -e .` if not using uv.

### GitLab Configuration (Integration Tests Only)

Integration tests require a GitLab API token:

```bash
export GITLAB_TOKEN="your-gitlab-token"
export GITLAB_URL="https://gitlab.example.com"  # Optional, defaults to GitLab.com
export GITLAB_PROJECT_PATH="group/project"      # Optional, can auto-detect from git
```

### Required Permissions

Your GitLab token needs the following permissions:
- `api` scope for full API access
- Write access to the target project's Package Registry
- Ability to create and delete packages in the registry

## Running Tests

### Primary Method: uv run pytest

```bash
# Run all tests
uv run pytest tests/

# Run only unit tests
uv run pytest tests/unit/

# Run only integration tests
uv run pytest tests/integration/ -m integration

# Run specific test file
uv run pytest tests/unit/test_cli.py

# Run specific test function
uv run pytest tests/unit/test_cli.py::test_parse_args

# Run with verbose output
uv run pytest tests/ -v

# Run with parallel execution
uv run pytest tests/ -n auto

# Stop on first failure
uv run pytest tests/ -x

# Show 10 slowest tests
uv run pytest tests/ --durations=10
```

### Run Tests by Markers

```bash
# Run only unit tests
uv run pytest tests/ -m unit

# Run only integration tests
uv run pytest tests/ -m integration

# Run only fast tests
uv run pytest tests/ -m fast

# Skip slow tests
uv run pytest tests/ -m "not slow"

# Run API tests
uv run pytest tests/ -m api
```

### Using the Convenience Wrapper

```bash
# Run unit tests
./run_tests.py --unit

# Run integration tests (requires GITLAB_TOKEN)
./run_tests.py --integration

# Run all test categories
./run_tests.py --all

# Pass-through to pytest with custom arguments
./run_tests.py -v -k "upload" tests/
./run_tests.py -n auto tests/
./run_tests.py --durations=5 tests/
```

## Integration Test Requirements

Integration tests automatically validate their environment before running.

### Automatic Environment Validation

When you run integration tests, the test suite checks:

1. **GITLAB_TOKEN environment variable** - Must be set with a valid GitLab API token
2. **Git repository** - Must run from within a Git repository
3. **GitLab remotes** - Repository must have at least one remote pointing to a GitLab instance

### Verifying Your Setup

```bash
# Check if in Git repository
git remote -v

# Verify GitLab remote exists
git remote -v | grep gitlab

# Check token is set
echo $GITLAB_TOKEN

# Verify token is not empty
[ -n "$GITLAB_TOKEN" ] && echo "Token is set" || echo "Token is NOT set"
```

### When Validation Fails

If integration tests are skipped, the error message explains what's missing:

- **Missing GITLAB_TOKEN**: Set the environment variable with `export GITLAB_TOKEN='your-token'`
- **No Git repository**: Navigate to a Git repository or initialize one
- **No GitLab remotes**: Add a GitLab remote with `git remote add origin https://gitlab.com/namespace/project.git`

## Debugging Test Failures

### Common Debugging Commands

```bash
# Verbose output
uv run pytest tests/ -v

# Extra verbose output
uv run pytest tests/ -vv

# Stop on first failure
uv run pytest tests/ -x

# Full traceback
uv run pytest tests/ --tb=long

# Short traceback
uv run pytest tests/ --tb=short

# Maximum verbosity for specific test
uv run pytest tests/unit/test_cli.py::test_parse_args -vvv --tb=long

# Enable debug logging
uv run pytest tests/ -v --log-cli-level=DEBUG
```

### Common Issues

#### Authentication Errors
- Verify `GITLAB_TOKEN` is set and valid
- Check token has required permissions (`api` scope)
- Test with unit tests: `uv run pytest tests/unit/` (doesn't require token)

#### Timeout Errors
- Check network connectivity to GitLab
- Run sequentially: `uv run pytest tests/integration/` (without `-n auto`)
- Increase timeout: `uv run pytest tests/ --timeout=1200`

#### Parallel Execution Issues
- Run sequentially for debugging: `uv run pytest tests/` (without `-n auto`)
- Check rate limiter is working properly

## Parallel Execution

Tests are designed for safe parallel execution using pytest-xdist:

```bash
# Auto-detect CPU cores
uv run pytest tests/ -n auto

# Specify worker count
uv run pytest tests/ -n 4

# Use worksteal distribution for better load balancing
uv run pytest tests/ --dist=worksteal -n auto
```

### Parallel Execution Safety

- **Unique package names per test**: Timestamp + worker ID + random suffix
- **Thread-safe rate limiting**: For GitLab API calls across all workers
- **Isolated temporary directories**: Per worker isolation
- **Automatic cleanup**: In fixture teardown

## Test Categories

### Unit Tests (`tests/unit/`)

Fast tests that validate individual components:

- **test_cli.py**: CLI argument parsing and validation
- **test_models.py**: Data models and structures
- **test_uploader.py**: Upload logic and file handling
- **test_validators.py**: Input validation functions

### Integration Tests (`tests/integration/`)

End-to-end tests requiring GitLab API access:

- **test_single_file_upload.py**: Single file upload tests
- **test_multiple_files_upload.py**: Multiple files upload tests
- **test_duplicate_handling.py**: Skip, replace, error policies
- **test_project_resolution.py**: Auto-detection and manual specification
- **test_error_scenarios.py**: Network failures, auth errors
- **test_end_to_end.py**: Comprehensive end-to-end scenarios

## Test Execution Time

| Test Category | Duration | Requirements |
|---------------|----------|--------------|
| Unit tests | 10-30 seconds | None |
| Integration tests | 10-15 minutes | GITLAB_TOKEN |
| All tests (parallel) | 5-10 minutes | GITLAB_TOKEN |

## Adding New Tests

### Creating a New Test

1. Choose the appropriate directory (`tests/unit/` or `tests/integration/`)
2. Follow pytest naming conventions (`test_*` functions)
3. Use existing fixtures from `conftest.py`
4. Add appropriate markers for categorization

Example:
```python
import pytest

@pytest.mark.unit
def test_new_functionality():
    """Test new functionality."""
    # Test implementation
    assert True
```

### Available Fixtures

- **`gitlab_client`**: Authenticated GitLab client (integration tests)
- **`artifact_manager`**: Test file creation and cleanup
- **`temp_dir`**: Isolated temporary directory
- **`project_resolver`**: Project identification utilities
- **`rate_limiter`**: API rate limiting management

### Test Markers

- **`@pytest.mark.unit`**: Unit tests (no external dependencies)
- **`@pytest.mark.integration`**: Integration tests (requires GITLAB_TOKEN)
- **`@pytest.mark.fast`**: Quick tests
- **`@pytest.mark.slow`**: Slow tests
- **`@pytest.mark.api`**: Tests requiring API access
- **`@pytest.mark.sequential`**: Tests that must run sequentially

## Getting Help

```bash
# Show pytest help
uv run pytest --help

# Show available markers
uv run pytest --markers

# Show available fixtures
uv run pytest --fixtures
```

## Contributing

When contributing new tests:

1. Follow existing patterns for consistency
2. Add appropriate documentation and docstrings
3. Use existing fixtures to avoid duplication
4. Add proper markers for categorization
5. Ensure cleanup of any created resources
6. Test both success and failure scenarios
7. Run tests locally before submitting: `uv run pytest tests/`
