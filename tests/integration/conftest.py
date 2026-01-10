"""
Pytest configuration for integration tests using direct module invocation.

This module provides fixtures and configuration specific to the integration
tests that call the CLI main() function directly.

Fixtures from parent conftest.py are automatically inherited:
    - gitlab_client: GitLab test client for API verification
    - artifact_manager: Test artifact management
    - project_path: GitLab project path

Usage:
    Fixtures are automatically available to all tests in this package.
    Import additional utilities from test_helpers_module as needed.
"""

import logging

import pytest


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
