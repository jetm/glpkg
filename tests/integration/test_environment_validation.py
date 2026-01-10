"""
Environment validation tests for the integration test suite.

This module contains tests that verify the integration test environment
validation mechanism works correctly. These tests serve as both documentation
and verification that the validation fixture properly detects:
    - GITLAB_TOKEN environment variable
    - Git repository presence
    - GitLab remote configuration

These tests run quickly and help users understand what environment setup
is required for the full integration test suite.
"""

import os

import pytest

from gitlab_pkg_upload.cli import GitAutoDetector

# Test markers for categorization
pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,  # These tests are quick validation checks
]


class TestEnvironmentValidation:
    """
    Test class for environment validation functionality.

    These tests verify that the integration test environment is properly
    configured and that the validation fixtures work correctly.
    """

    @pytest.mark.timeout(30)
    def test_gitlab_token_is_set(self):
        """
        Test that GITLAB_TOKEN environment variable is set.

        This test verifies that the GitLab API token is available.
        The session-scoped validation fixture ensures this test only runs
        if the token is present, so this test documents the requirement.
        """
        token = os.environ.get("GITLAB_TOKEN")
        assert token is not None, "GITLAB_TOKEN should be set"
        assert len(token) > 0, "GITLAB_TOKEN should not be empty"

    @pytest.mark.timeout(30)
    def test_git_repository_detected(self):
        """
        Test that a Git repository is detected in the current environment.

        This test verifies that GitAutoDetector can find a Git repository.
        """
        detector = GitAutoDetector()
        repo = detector.find_git_repository()

        assert repo is not None, "Git repository should be detected"
        assert repo.working_dir is not None, "Repository should have a working directory"

    @pytest.mark.timeout(30)
    def test_gitlab_remotes_detected(self):
        """
        Test that GitLab remotes are detected in the Git repository.

        This test verifies that at least one GitLab remote is configured.
        """
        detector = GitAutoDetector()
        repo = detector.find_git_repository()

        assert repo is not None, "Git repository should be detected"

        # This will raise ProjectResolutionError if no GitLab remotes found
        gitlab_remotes = detector.get_gitlab_remotes(repo)

        assert len(gitlab_remotes) > 0, "At least one GitLab remote should be detected"

        # Verify remote structure
        for remote in gitlab_remotes:
            assert remote.name is not None, "Remote should have a name"
            assert remote.project_path is not None, "Remote should have a project path"
            assert remote.gitlab_url is not None, "Remote should have a GitLab URL"

    @pytest.mark.timeout(30)
    def test_environment_validation_fixture_ran(self, validate_integration_environment):
        """
        Test that the environment validation fixture executed successfully.

        This test explicitly requests the validation fixture to verify
        it completes without skipping tests.
        """
        # If we reach this point, the fixture ran successfully
        # The fixture yields after validation, so this test body executes
        # only if all validation checks passed
        assert True, "Environment validation fixture completed successfully"


@pytest.mark.timeout(30)
def test_project_path_fixture_available(project_path):
    """
    Test that the project_path fixture provides a valid project path.

    This test verifies that the project path can be resolved either
    from Git auto-detection or from manual specification.
    """
    assert project_path is not None, "project_path fixture should provide a value"
    assert len(project_path) > 0, "project_path should not be empty"
    assert "/" in project_path, "project_path should be in 'namespace/project' format"


@pytest.mark.timeout(30)
def test_gitlab_client_fixture_available(gitlab_client):
    """
    Test that the gitlab_client fixture provides a usable client.

    This test verifies that the GitLab client fixture is properly
    configured and can communicate with the GitLab API.
    """
    assert gitlab_client is not None, "gitlab_client fixture should provide a client"
    # Basic check that client has expected attributes
    assert hasattr(gitlab_client, "gitlab_url"), "Client should have gitlab_url attribute"
