"""
Pytest configuration for integration tests using direct module invocation.

This module provides fixtures and configuration specific to the integration
tests that call the CLI main() function directly.

Environment Requirements:
    Integration tests require the following environment setup:

    1. GITLAB_TOKEN environment variable must be set
       - Can be set via: export GITLAB_TOKEN="your-token"
       - Token needs 'api' scope and write access to Package Registry

    2. Must run from within a Git repository with GitLab remotes
       - The repository must have at least one remote pointing to a GitLab instance
       - Remotes are auto-detected using the GitAutoDetector class
       - Alternatively, use GITLAB_PROJECT_PATH environment variable

    If requirements aren't met, all integration tests will be skipped with
    clear, actionable error messages explaining what's missing and how to fix it.

Fixtures from parent conftest.py are automatically inherited:
    - gitlab_client: GitLab test client for API verification
    - artifact_manager: Test artifact management
    - project_path: GitLab project path

Usage:
    Fixtures are automatically available to all tests in this package.
    Import additional utilities from test_helpers_module as needed.

Example commands to verify your environment:
    # Check if in Git repository
    git remote -v

    # Verify GitLab remote exists
    git remote -v | grep gitlab

    # Check token is set
    echo $GITLAB_TOKEN
"""

import logging
import os
from typing import Tuple

import pytest

from glpkg.cli.upload import GitAutoDetector, ProjectResolutionError


def _validate_gitlab_repository() -> Tuple[bool, str, str]:
    """
    Validate that the current environment has a GitLab repository.

    Uses GitAutoDetector to find Git repository and check for GitLab remotes.

    Returns:
        Tuple of (is_valid, error_message, success_info):
            - is_valid: True if GitLab repository is properly configured
            - error_message: Detailed error message if validation fails, empty string otherwise
            - success_info: Information about the detected repository if valid
    """
    detector = GitAutoDetector()

    # Step 1: Find Git repository
    try:
        repo = detector.find_git_repository()
    except ProjectResolutionError as e:
        return (
            False,
            f"Git repository access error: {e}\n\n"
            "SOLUTION:\n"
            "1. Check directory permissions\n"
            "2. Use manual project specification:\n"
            "   export GITLAB_PROJECT_PATH='namespace/project'",
            "",
        )

    if repo is None:
        return (
            False,
            "No Git repository found in the current directory or parent directories.\n\n"
            "Integration tests require running from within a Git repository.\n\n"
            "SOLUTION:\n"
            "1. Navigate to a Git repository before running tests:\n"
            "   cd /path/to/your/git/repo\n\n"
            "2. Or initialize a Git repository:\n"
            "   git init\n"
            "   git remote add origin https://gitlab.com/namespace/project.git\n\n"
            "3. Or use manual project specification:\n"
            "   export GITLAB_PROJECT_PATH='namespace/project'",
            "",
        )

    # Step 2: Check for remotes
    remotes = list(repo.remotes)
    if not remotes:
        return (
            False,
            f"Git repository found at '{repo.working_dir}' but no remotes are configured.\n\n"
            "Integration tests require at least one GitLab remote.\n\n"
            "SOLUTION:\n"
            "1. Add a GitLab remote:\n"
            "   git remote add origin https://gitlab.com/namespace/project.git\n\n"
            "2. Or use manual project specification:\n"
            "   export GITLAB_PROJECT_PATH='namespace/project'",
            "",
        )

    # Step 3: Check for GitLab remotes
    try:
        gitlab_remotes = detector.get_gitlab_remotes(repo)
    except ProjectResolutionError:
        # No GitLab remotes found
        remote_urls = [f"  - {r.name}: {r.url}" for r in remotes]
        return (
            False,
            f"Git repository found at '{repo.working_dir}' but no GitLab remotes detected.\n\n"
            "Current remotes:\n"
            + "\n".join(remote_urls)
            + "\n\n"
            "Integration tests require at least one remote pointing to a GitLab instance.\n\n"
            "SOLUTION:\n"
            "1. Add a GitLab remote:\n"
            "   git remote add gitlab https://gitlab.com/namespace/project.git\n\n"
            "2. Or update an existing remote to point to GitLab:\n"
            "   git remote set-url origin https://gitlab.com/namespace/project.git\n\n"
            "3. Or use manual project specification:\n"
            "   export GITLAB_PROJECT_PATH='namespace/project'",
            "",
        )

    # Success - build info string
    remote_info = ", ".join(f"{r.name}={r.project_path}" for r in gitlab_remotes)
    success_info = (
        f"Git repository: {repo.working_dir}\n"
        f"GitLab remotes detected: {remote_info}"
    )

    return (True, "", success_info)


@pytest.fixture(scope="session", autouse=True)
def validate_integration_environment():
    """
    Validate that the integration test environment is properly configured.

    This session-scoped fixture runs once before any integration tests execute.
    It validates:
        1. GITLAB_TOKEN environment variable is set
        2. Current directory is within a Git repository
        3. Git repository has at least one GitLab remote

    If any requirement is not met, all integration tests are skipped with
    clear, actionable error messages.

    This fixture is marked autouse=True so it runs automatically for all
    integration tests without needing to be explicitly requested.
    """
    # Check 1: GITLAB_TOKEN environment variable
    token = os.environ.get("GITLAB_TOKEN")
    if not token:
        pytest.skip(
            "GITLAB_TOKEN environment variable not set.\n\n"
            "Integration tests require a valid GitLab API token.\n\n"
            "SOLUTION:\n"
            "1. Create a GitLab personal access token with 'api' scope:\n"
            "   GitLab → Settings → Access Tokens → Create token\n\n"
            "2. Set the environment variable:\n"
            "   export GITLAB_TOKEN='your-token-here'\n\n"
            "3. Or add it to your shell profile for persistence:\n"
            "   echo 'export GITLAB_TOKEN=\"your-token\"' >> ~/.bashrc",
            allow_module_level=True,
        )

    # Check 2 & 3: Git repository with GitLab remotes
    # Skip this check if GITLAB_PROJECT_PATH is manually specified
    if not os.environ.get("GITLAB_PROJECT_PATH"):
        is_valid, error_message, success_info = _validate_gitlab_repository()

        if not is_valid:
            pytest.skip(error_message, allow_module_level=True)

        # Log successful validation
        print(f"\nIntegration test environment validated:")
        print(f"  - GITLAB_TOKEN: [set]")
        print(f"  - {success_info}")
    else:
        # Manual project path specified
        project_path = os.environ.get("GITLAB_PROJECT_PATH")
        print(f"\nIntegration test environment validated:")
        print(f"  - GITLAB_TOKEN: [set]")
        print(f"  - GITLAB_PROJECT_PATH: {project_path} (manually specified)")

    yield


def pytest_configure(config):
    """Configure pytest for integration tests."""
    # Register custom markers
    config.addinivalue_line(
        "markers",
        "module_integration: Integration tests using direct module invocation",
    )
    config.addinivalue_line(
        "markers",
        "api: Tests requiring GitLab API access",
    )
    config.addinivalue_line(
        "markers",
        "cleanup: Tests that verify cleanup functionality",
    )
    config.addinivalue_line(
        "markers",
        "fast: Tests that run quickly",
    )


@pytest.fixture(autouse=True)
def setup_integration_logging(caplog):
    """
    Configure logging for integration tests.

    This fixture sets up appropriate logging levels for integration tests
    to capture relevant debug information while avoiding excessive output.
    """
    # Set logging level to capture warnings and errors
    caplog.set_level(logging.WARNING)

    # Set specific loggers to appropriate levels
    logging.getLogger("gitlab_pkg_upload").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    yield

    # Cleanup logging after test
    logging.getLogger("gitlab_pkg_upload").setLevel(logging.WARNING)


@pytest.fixture
def module_executor():
    """
    Provide a ModuleExecutor instance for tests.

    This fixture creates a fresh ModuleExecutor for each test that requests it.
    Most tests will create their own executor, but this fixture is available
    for tests that need a shared or pre-configured executor.

    Returns:
        ModuleExecutor instance
    """
    from .test_helpers_module import ModuleExecutor

    return ModuleExecutor()
