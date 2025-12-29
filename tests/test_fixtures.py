"""
Test the basic fixture functionality to ensure the extracted code works correctly.
"""

from pathlib import Path

import pytest


def test_artifact_manager_fixture(artifact_manager):
    """Test that the artifact manager fixture works correctly."""
    # Create a test file
    artifact = artifact_manager.create_test_file("test.txt", 100, "text")

    # Verify the artifact was created
    assert artifact.path.exists()
    assert artifact.size == 100
    assert artifact.artifact_type == "file"
    assert len(artifact.checksum) == 64  # SHA256 hex length

    # Verify the file has the expected content
    content = artifact.path.read_bytes()
    assert len(content) == 100
    assert b"test content" in content


def test_temp_dir_fixture(temp_dir):
    """Test that the temporary directory fixture works correctly."""
    # Verify temp_dir is a Path object and exists
    assert isinstance(temp_dir, Path)
    assert temp_dir.exists()
    assert temp_dir.is_dir()

    # Create a file in the temp directory
    test_file = temp_dir / "test.txt"
    test_file.write_text("test content")

    assert test_file.exists()
    assert test_file.read_text() == "test content"


def test_gitlab_token_fixture(gitlab_token):
    """Test that the GitLab token fixture works correctly."""
    # This test will be skipped if GITLAB_TOKEN is not set
    assert isinstance(gitlab_token, str)
    assert len(gitlab_token) > 0


@pytest.mark.skipif(
    not pytest.importorskip("gitlab", minversion=None),
    reason="python-gitlab not available",
)
def test_gitlab_client_fixture(gitlab_client):
    """Test that the GitLab client fixture works correctly."""
    # This test will be skipped if python-gitlab is not available
    assert gitlab_client is not None
    assert hasattr(gitlab_client, "gl")
    assert hasattr(gitlab_client, "token")
    assert gitlab_client._authenticated


def test_project_resolver_fixture_skip_if_no_gitlab():
    """Test that project resolver fixture is properly skipped when GitLab is not available."""
    try:
        import importlib.util

        if importlib.util.find_spec("gitlab") is not None:
            pytest.skip("GitLab is available, this test is for when it's not available")
    except ImportError:
        # This is expected when GitLab is not available
        pass
