"""
Comprehensive unit tests for the validators module.

These tests validate file validation, Git URL parsing, configuration validation,
token handling, and dependency checking functions. All external dependencies
(filesystem, subprocess, GitPython) are mocked to ensure test isolation.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, Mock, mock_open, patch

import pytest

from glpkg.models import (
    ConfigurationError,
    FileValidationError,
    ProjectResolutionError,
)
from glpkg.validators import (
    DEFAULT_GITLAB_URL,
    calculate_sha256,
    collect_files,
    get_gitlab_token,
    normalize_gitlab_url,
    parse_file_mapping,
    parse_git_url,
    validate_configuration,
    validate_dependencies,
    validate_file_exists,
    validate_filename,
    validate_git_installation,
    validate_git_repository,
    validate_gitlab_token,
    validate_project_specification,
)

# Mark these as fast unit tests
pytestmark = [pytest.mark.unit, pytest.mark.fast]


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_path_exists():
    """Create a mock Path that exists."""
    mock_path = MagicMock(spec=Path)
    mock_path.exists.return_value = True
    mock_path.is_file.return_value = True
    mock_path.is_dir.return_value = False
    mock_path.name = "test_file.txt"
    mock_path.__str__ = lambda self: "/path/to/test_file.txt"
    return mock_path


@pytest.fixture
def mock_path_not_exists():
    """Create a mock Path that does not exist."""
    mock_path = MagicMock(spec=Path)
    mock_path.exists.return_value = False
    mock_path.is_file.return_value = False
    mock_path.__str__ = lambda self: "/path/to/nonexistent.txt"
    return mock_path


@pytest.fixture
def mock_path_directory():
    """Create a mock Path that is a directory."""
    mock_path = MagicMock(spec=Path)
    mock_path.exists.return_value = True
    mock_path.is_file.return_value = False
    mock_path.is_dir.return_value = True
    mock_path.__str__ = lambda self: "/path/to/directory"
    return mock_path


@pytest.fixture
def mock_git_repo():
    """Create a mock Git repository."""
    mock_repo = MagicMock()
    mock_repo.working_dir = "/path/to/repo"
    mock_repo.config_reader.return_value = MagicMock()
    mock_repo.remotes = [MagicMock(name="origin")]
    return mock_repo


# =============================================================================
# Test Classes
# =============================================================================


class TestFilenameValidation:
    """Tests for validate_filename function."""

    @pytest.mark.timeout(60)
    def test_valid_ascii_filename(self):
        """Test valid ASCII filename passes validation."""
        # Should not raise
        validate_filename("package.tar.gz")
        validate_filename("my-file_v1.0.bin")
        validate_filename("subdir/file.txt")
        validate_filename("a.b.c.d")

    @pytest.mark.timeout(60)
    def test_valid_filename_with_numbers(self):
        """Test filename with numbers passes validation."""
        validate_filename("file123.txt")
        validate_filename("v1.2.3.tar.gz")
        validate_filename("2024-01-01-backup.zip")

    @pytest.mark.timeout(60)
    def test_valid_filename_with_hyphens_underscores(self):
        """Test filename with hyphens and underscores passes validation."""
        validate_filename("my-file.txt")
        validate_filename("my_file.txt")
        validate_filename("my-file_v1.0.txt")

    @pytest.mark.timeout(60)
    def test_valid_filename_with_slashes(self):
        """Test filename with forward slashes (directory paths) passes validation."""
        validate_filename("subdir/file.txt")
        validate_filename("a/b/c/file.txt")
        validate_filename("deeply/nested/path/file.bin")

    @pytest.mark.timeout(60)
    def test_non_ascii_filename_rejected(self):
        """Test non-ASCII characters in filename are rejected."""
        with pytest.raises(FileValidationError) as exc_info:
            validate_filename("café.tar.gz")
        assert "non-ASCII" in str(exc_info.value)
        assert "café.tar.gz" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_chinese_characters_rejected(self):
        """Test Chinese characters in filename are rejected."""
        with pytest.raises(FileValidationError) as exc_info:
            validate_filename("文件.bin")
        assert "non-ASCII" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_emoji_rejected(self):
        """Test emoji in filename are rejected."""
        with pytest.raises(FileValidationError) as exc_info:
            validate_filename("file📦.txt")
        assert "non-ASCII" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_special_characters_rejected(self):
        """Test special characters are rejected."""
        special_chars = ["@", "#", "$", "%", " ", "!", "&", "(", ")", "+", "="]
        for char in special_chars:
            with pytest.raises(FileValidationError) as exc_info:
                validate_filename(f"file{char}name.txt")
            assert "special characters" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_space_in_filename_rejected(self):
        """Test space in filename is rejected."""
        with pytest.raises(FileValidationError) as exc_info:
            validate_filename("file name.txt")
        assert "special characters" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_error_message_includes_allowed_characters(self):
        """Test error message includes list of allowed characters."""
        with pytest.raises(FileValidationError) as exc_info:
            validate_filename("bad@file.txt")
        error_msg = str(exc_info.value)
        assert "letters" in error_msg or "a-z" in error_msg
        assert "digits" in error_msg or "0-9" in error_msg


class TestFileExistsValidation:
    """Tests for validate_file_exists function."""

    @pytest.mark.timeout(60)
    def test_existing_file_passes(self, tmp_path):
        """Test existing readable file passes validation."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        # Should not raise
        validate_file_exists(test_file)

    @pytest.mark.timeout(60)
    def test_nonexistent_file_raises(self):
        """Test non-existent file raises FileValidationError."""
        nonexistent = Path("/path/to/definitely/not/existing/file.txt")
        with pytest.raises(FileValidationError) as exc_info:
            validate_file_exists(nonexistent)
        assert "not found" in str(exc_info.value).lower()

    @pytest.mark.timeout(60)
    def test_directory_path_raises(self, tmp_path):
        """Test directory path raises FileValidationError."""
        with pytest.raises(FileValidationError) as exc_info:
            validate_file_exists(tmp_path)
        assert "not a file" in str(exc_info.value).lower()

    @pytest.mark.timeout(60)
    def test_unreadable_file_raises(self, tmp_path):
        """Test unreadable file raises FileValidationError."""
        test_file = tmp_path / "unreadable.txt"
        test_file.write_text("content")

        # Mock the open function to raise PermissionError
        with patch("builtins.open", side_effect=PermissionError("Permission denied")):
            with pytest.raises(FileValidationError) as exc_info:
                validate_file_exists(test_file)
            assert "not readable" in str(exc_info.value).lower()


class TestSHA256Calculation:
    """Tests for calculate_sha256 function."""

    @pytest.mark.timeout(60)
    def test_calculate_sha256_basic(self, tmp_path):
        """Test SHA256 calculation for a basic file."""
        test_file = tmp_path / "test.txt"
        content = b"Hello, World!"
        test_file.write_bytes(content)

        expected = hashlib.sha256(content).hexdigest()
        result = calculate_sha256(test_file)

        assert result == expected
        assert len(result) == 64  # SHA256 hex digest is 64 characters

    @pytest.mark.timeout(60)
    def test_calculate_sha256_empty_file(self, tmp_path):
        """Test SHA256 calculation for empty file."""
        test_file = tmp_path / "empty.txt"
        test_file.write_bytes(b"")

        expected = hashlib.sha256(b"").hexdigest()
        result = calculate_sha256(test_file)

        assert result == expected

    @pytest.mark.timeout(60)
    def test_calculate_sha256_binary_file(self, tmp_path):
        """Test SHA256 calculation for binary file."""
        test_file = tmp_path / "binary.bin"
        content = bytes(range(256))
        test_file.write_bytes(content)

        expected = hashlib.sha256(content).hexdigest()
        result = calculate_sha256(test_file)

        assert result == expected

    @pytest.mark.timeout(60)
    def test_calculate_sha256_large_file(self, tmp_path):
        """Test SHA256 calculation handles larger files correctly."""
        test_file = tmp_path / "large.bin"
        # Create a file larger than the 8192 byte chunk size
        content = b"x" * 50000
        test_file.write_bytes(content)

        expected = hashlib.sha256(content).hexdigest()
        result = calculate_sha256(test_file)

        assert result == expected

    @pytest.mark.timeout(60)
    def test_calculate_sha256_read_error(self):
        """Test SHA256 calculation raises on read error."""
        with patch("builtins.open", side_effect=IOError("Read error")):
            with pytest.raises(FileValidationError) as exc_info:
                calculate_sha256(Path("/some/file.txt"))
            assert "Failed to read file" in str(exc_info.value)


class TestFileMappingParsing:
    """Tests for parse_file_mapping function."""

    @pytest.mark.timeout(60)
    def test_valid_mapping(self):
        """Test parsing valid file mapping."""
        mappings = ["local.bin:remote.bin"]
        files = ["path/to/local.bin"]

        result = parse_file_mapping(mappings, files)

        assert result == {"local.bin": "remote.bin"}

    @pytest.mark.timeout(60)
    def test_multiple_mappings(self):
        """Test parsing multiple file mappings."""
        mappings = ["file1.txt:renamed1.txt", "file2.bin:renamed2.bin"]
        files = ["path/to/file1.txt", "path/to/file2.bin"]

        result = parse_file_mapping(mappings, files)

        assert result == {
            "file1.txt": "renamed1.txt",
            "file2.bin": "renamed2.bin",
        }

    @pytest.mark.timeout(60)
    def test_empty_mappings(self):
        """Test parsing empty mappings list returns empty dict."""
        result = parse_file_mapping([], ["file.txt"])
        assert result == {}

    @pytest.mark.timeout(60)
    def test_invalid_mapping_no_colon(self):
        """Test invalid mapping without colon raises error."""
        with pytest.raises(ConfigurationError) as exc_info:
            parse_file_mapping(["invalid_mapping"], ["file.txt"])
        assert "Invalid file mapping format" in str(exc_info.value)
        assert "local.bin:remote.bin" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_invalid_mapping_multiple_colons(self):
        """Test invalid mapping with multiple colons raises error."""
        with pytest.raises(ConfigurationError) as exc_info:
            parse_file_mapping(["a:b:c"], ["a"])
        assert "Invalid file mapping format" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_mapping_file_not_in_list(self):
        """Test mapping referencing non-existent file raises error."""
        with pytest.raises(ConfigurationError) as exc_info:
            parse_file_mapping(["missing.bin:remote.bin"], ["other.bin"])
        assert "not in the files list" in str(exc_info.value)


class TestFileCollection:
    """Tests for collect_files function."""

    @pytest.mark.timeout(60)
    def test_files_mode_basic(self, tmp_path):
        """Test collecting files in files mode."""
        # Create test files
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("content1")
        file2.write_text("content2")

        files_to_upload, errors = collect_files(
            files=[str(file1), str(file2)]
        )

        assert len(files_to_upload) == 2
        assert len(errors) == 0

    @pytest.mark.timeout(60)
    def test_files_mode_with_mapping(self, tmp_path):
        """Test collecting files with file mappings."""
        file1 = tmp_path / "local.txt"
        file1.write_text("content")

        files_to_upload, errors = collect_files(
            files=[str(file1)],
            file_mappings={"local.txt": "remote.txt"},
        )

        assert len(files_to_upload) == 1
        assert files_to_upload[0][1] == "remote.txt"

    @pytest.mark.timeout(60)
    def test_directory_mode_basic(self, tmp_path):
        """Test collecting files from directory."""
        # Create test files in directory
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.txt").write_text("content2")

        files_to_upload, errors = collect_files(directory=str(tmp_path))

        assert len(files_to_upload) == 2
        assert len(errors) == 0

    @pytest.mark.timeout(60)
    def test_directory_mode_ignores_subdirectories(self, tmp_path):
        """Test directory mode only collects top-level files."""
        (tmp_path / "file.txt").write_text("content")
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "nested.txt").write_text("nested content")

        files_to_upload, errors = collect_files(directory=str(tmp_path))

        # Should only find the top-level file, not the nested one
        assert len(files_to_upload) == 1
        assert files_to_upload[0][1] == "file.txt"

    @pytest.mark.timeout(60)
    def test_mutually_exclusive_inputs_error(self, tmp_path):
        """Test error when both files and directory are provided."""
        with pytest.raises(ConfigurationError) as exc_info:
            collect_files(
                files=["file.txt"],
                directory=str(tmp_path),
            )
        assert "mutually exclusive" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_missing_inputs_error(self):
        """Test error when neither files nor directory is provided."""
        with pytest.raises(ConfigurationError) as exc_info:
            collect_files()
        assert "must be provided" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_nonexistent_file_collected_as_error(self, tmp_path):
        """Test non-existent file is collected as error, not raised."""
        existing = tmp_path / "exists.txt"
        existing.write_text("content")

        files_to_upload, errors = collect_files(
            files=[str(existing), "/nonexistent/file.txt"]
        )

        assert len(files_to_upload) == 1
        assert len(errors) == 1
        assert "FileValidationError" in errors[0]["error_type"]

    @pytest.mark.timeout(60)
    def test_invalid_filename_collected_as_error(self, tmp_path):
        """Test file with invalid filename is collected as error."""
        # Create file with valid local name, but map to invalid remote name
        valid_file = tmp_path / "valid.txt"
        valid_file.write_text("content")

        files_to_upload, errors = collect_files(
            files=[str(valid_file)],
            file_mappings={"valid.txt": "invalid file.txt"},  # Space is invalid
        )

        assert len(files_to_upload) == 0
        assert len(errors) == 1

    @pytest.mark.timeout(60)
    def test_duplicate_target_filenames_error(self, tmp_path):
        """Test duplicate target filenames raise error."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("content1")
        file2.write_text("content2")

        with pytest.raises(ConfigurationError) as exc_info:
            collect_files(
                files=[str(file1), str(file2)],
                file_mappings={
                    "file1.txt": "same.txt",
                    "file2.txt": "same.txt",
                },
            )
        assert "Duplicate target filenames" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_nonexistent_directory_error(self):
        """Test error for non-existent directory."""
        with pytest.raises(ConfigurationError) as exc_info:
            collect_files(directory="/nonexistent/directory")
        assert "Directory not found" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_file_path_as_directory_error(self, tmp_path):
        """Test error when file path is provided as directory."""
        file_path = tmp_path / "file.txt"
        file_path.write_text("content")

        with pytest.raises(ConfigurationError) as exc_info:
            collect_files(directory=str(file_path))
        assert "not a directory" in str(exc_info.value).lower()

    @pytest.mark.timeout(60)
    def test_file_mappings_as_list(self, tmp_path):
        """Test file_mappings can be provided as list of strings."""
        file1 = tmp_path / "local.txt"
        file1.write_text("content")

        files_to_upload, errors = collect_files(
            files=[str(file1)],
            file_mappings=["local.txt:remote.txt"],
        )

        assert len(files_to_upload) == 1
        assert files_to_upload[0][1] == "remote.txt"

    @pytest.mark.timeout(60)
    def test_invalid_file_mappings_type_error(self, tmp_path):
        """Test error for invalid file_mappings type."""
        file1 = tmp_path / "file.txt"
        file1.write_text("content")

        with pytest.raises(ConfigurationError) as exc_info:
            collect_files(
                files=[str(file1)],
                file_mappings=123,  # Invalid type
            )
        assert "must be a dict or list" in str(exc_info.value)


class TestGitUrlParsing:
    """Tests for parse_git_url function."""

    @pytest.mark.timeout(60)
    def test_https_url_basic(self):
        """Test parsing basic HTTPS Git URL."""
        gitlab_url, project_path = parse_git_url(
            "https://gitlab.com/namespace/project.git"
        )
        assert gitlab_url == "https://gitlab.com"
        assert project_path == "namespace/project"

    @pytest.mark.timeout(60)
    def test_https_url_without_git_suffix(self):
        """Test parsing HTTPS URL without .git suffix."""
        gitlab_url, project_path = parse_git_url(
            "https://gitlab.com/namespace/project"
        )
        assert gitlab_url == "https://gitlab.com"
        assert project_path == "namespace/project"

    @pytest.mark.timeout(60)
    def test_ssh_url_basic(self):
        """Test parsing basic SSH Git URL."""
        gitlab_url, project_path = parse_git_url(
            "git@gitlab.com:namespace/project.git"
        )
        assert gitlab_url == "https://gitlab.com"
        assert project_path == "namespace/project"

    @pytest.mark.timeout(60)
    def test_ssh_url_without_git_suffix(self):
        """Test parsing SSH URL without .git suffix."""
        gitlab_url, project_path = parse_git_url(
            "git@gitlab.com:namespace/project"
        )
        assert gitlab_url == "https://gitlab.com"
        assert project_path == "namespace/project"

    @pytest.mark.timeout(60)
    def test_nested_namespace(self):
        """Test parsing URL with nested namespace (subgroups)."""
        gitlab_url, project_path = parse_git_url(
            "https://gitlab.com/group/subgroup/project.git"
        )
        assert gitlab_url == "https://gitlab.com"
        assert project_path == "group/subgroup/project"

    @pytest.mark.timeout(60)
    def test_self_hosted_gitlab(self):
        """Test parsing URL for self-hosted GitLab instance."""
        gitlab_url, project_path = parse_git_url(
            "https://gitlab.example.com/namespace/project.git"
        )
        assert gitlab_url == "https://gitlab.example.com"
        assert project_path == "namespace/project"

    @pytest.mark.timeout(60)
    def test_ssh_self_hosted(self):
        """Test parsing SSH URL for self-hosted GitLab."""
        gitlab_url, project_path = parse_git_url(
            "git@gitlab.example.com:namespace/project.git"
        )
        assert gitlab_url == "https://gitlab.example.com"
        assert project_path == "namespace/project"

    @pytest.mark.timeout(60)
    def test_empty_url_error(self):
        """Test error for empty URL."""
        with pytest.raises(ConfigurationError) as exc_info:
            parse_git_url("")
        assert "non-empty string" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_none_url_error(self):
        """Test error for None URL."""
        with pytest.raises(ConfigurationError) as exc_info:
            parse_git_url(None)
        assert "non-empty string" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_invalid_ssh_url_no_colon(self):
        """Test error for SSH URL without colon."""
        with pytest.raises(ConfigurationError) as exc_info:
            parse_git_url("git@gitlab.com/namespace/project.git")
        assert "Invalid SSH Git URL" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_invalid_https_scheme(self):
        """Test error for non-HTTPS scheme."""
        with pytest.raises(ConfigurationError) as exc_info:
            parse_git_url("http://gitlab.com/namespace/project.git")
        assert "Invalid Git URL scheme" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_missing_project_path(self):
        """Test error for URL missing project path."""
        with pytest.raises(ConfigurationError) as exc_info:
            parse_git_url("https://gitlab.com/namespace")
        assert "Path must contain at least namespace/project" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_url_with_trailing_whitespace(self):
        """Test URL with whitespace is trimmed."""
        gitlab_url, project_path = parse_git_url(
            "  https://gitlab.com/namespace/project.git  "
        )
        assert gitlab_url == "https://gitlab.com"
        assert project_path == "namespace/project"


class TestNormalizeGitlabUrl:
    """Tests for normalize_gitlab_url function."""

    @pytest.mark.timeout(60)
    def test_basic_url(self):
        """Test normalizing basic GitLab URL."""
        gitlab_url, project_path = normalize_gitlab_url(
            "https://gitlab.com/namespace/project"
        )
        assert gitlab_url == "https://gitlab.com"
        assert project_path == "namespace/project"

    @pytest.mark.timeout(60)
    def test_url_with_trailing_slash(self):
        """Test URL with trailing slash is normalized."""
        gitlab_url, project_path = normalize_gitlab_url(
            "https://gitlab.com/namespace/project/"
        )
        assert gitlab_url == "https://gitlab.com"
        assert project_path == "namespace/project"

    @pytest.mark.timeout(60)
    def test_http_url(self):
        """Test HTTP URL is accepted."""
        gitlab_url, project_path = normalize_gitlab_url(
            "http://gitlab.example.com/namespace/project"
        )
        assert gitlab_url == "http://gitlab.example.com"
        assert project_path == "namespace/project"

    @pytest.mark.timeout(60)
    def test_empty_url_error(self):
        """Test error for empty URL."""
        with pytest.raises(ConfigurationError) as exc_info:
            normalize_gitlab_url("")
        assert "non-empty string" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_invalid_scheme_error(self):
        """Test error for invalid scheme."""
        with pytest.raises(ConfigurationError) as exc_info:
            normalize_gitlab_url("ftp://gitlab.com/namespace/project")
        assert "Invalid GitLab URL scheme" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_missing_path_error(self):
        """Test error for URL missing path."""
        with pytest.raises(ConfigurationError) as exc_info:
            normalize_gitlab_url("https://gitlab.com")
        assert "missing project path" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_incomplete_path_error(self):
        """Test error for URL with incomplete path."""
        with pytest.raises(ConfigurationError) as exc_info:
            normalize_gitlab_url("https://gitlab.com/namespace")
        assert "Path must contain at least namespace/project" in str(exc_info.value)


class TestTokenHandling:
    """Tests for get_gitlab_token function."""

    @pytest.mark.timeout(60)
    def test_cli_token_takes_precedence(self, monkeypatch):
        """Test CLI token takes precedence over environment variable."""
        monkeypatch.setenv("GITLAB_TOKEN", "env-token")

        result = get_gitlab_token("cli-token")

        assert result == "cli-token"

    @pytest.mark.timeout(60)
    def test_environment_token_used(self, monkeypatch):
        """Test environment variable token is used when CLI token is None."""
        monkeypatch.setenv("GITLAB_TOKEN", "env-token")

        result = get_gitlab_token(None)

        assert result == "env-token"

    @pytest.mark.timeout(60)
    def test_missing_token_error(self, monkeypatch):
        """Test error when no token is available."""
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)

        with pytest.raises(ConfigurationError) as exc_info:
            get_gitlab_token(None)
        assert "No GitLab token provided" in str(exc_info.value)
        assert "GITLAB_TOKEN" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_empty_cli_token_falls_through(self, monkeypatch):
        """Test empty CLI token falls through to environment."""
        monkeypatch.setenv("GITLAB_TOKEN", "env-token")

        result = get_gitlab_token("")

        assert result == "env-token"


class TestTokenValidation:
    """Tests for validate_gitlab_token function."""

    @pytest.mark.timeout(60)
    def test_valid_token(self):
        """Test valid token passes validation."""
        # Should not raise
        validate_gitlab_token("glpat-xxxxxxxxxxxxxxxxxxxx")
        validate_gitlab_token("x" * 20)

    @pytest.mark.timeout(60)
    def test_empty_token_error(self):
        """Test empty token raises error."""
        with pytest.raises(ConfigurationError) as exc_info:
            validate_gitlab_token("")
        assert "token is required" in str(exc_info.value).lower()

    @pytest.mark.timeout(60)
    def test_none_token_error(self):
        """Test None token raises error."""
        with pytest.raises(ConfigurationError) as exc_info:
            validate_gitlab_token(None)
        assert "token is required" in str(exc_info.value).lower()

    @pytest.mark.timeout(60)
    def test_short_token_error(self):
        """Test token too short raises error."""
        with pytest.raises(ConfigurationError) as exc_info:
            validate_gitlab_token("short")
        assert "too short" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_incomplete_glpat_token_error(self):
        """Test incomplete glpat- token raises error."""
        # glpat- tokens should be 26+ characters, use one that's 20-25 chars
        # This is caught by the glpat- specific check, not the general short check
        with pytest.raises(ConfigurationError) as exc_info:
            validate_gitlab_token("glpat-12345678901234")  # 20 chars total
        assert "incomplete" in str(exc_info.value).lower()

    @pytest.mark.timeout(60)
    def test_token_with_whitespace_trimmed(self):
        """Test token with whitespace is trimmed before validation."""
        # Should not raise - whitespace is stripped
        validate_gitlab_token("  " + "x" * 20 + "  ")

    @pytest.mark.timeout(60)
    def test_error_includes_help_url(self):
        """Test error message includes help URL."""
        with pytest.raises(ConfigurationError) as exc_info:
            validate_gitlab_token("")
        assert "personal_access_tokens" in str(exc_info.value)


class TestDependencyValidation:
    """Tests for validate_dependencies function."""

    @pytest.mark.timeout(60)
    def test_dependencies_available(self):
        """Test validation passes when all dependencies are available."""
        with patch.object(sys, "version_info", (3, 11, 0)):
            with patch("builtins.__import__") as mock_import:
                mock_import.return_value = MagicMock()
                # Should not raise
                validate_dependencies()

    @pytest.mark.timeout(60)
    def test_python_version_too_low(self):
        """Test error when Python version is too low."""
        with patch.object(sys, "version_info", (3, 10, 0)):
            with patch.object(sys, "version", "3.10.0"):
                with pytest.raises(ConfigurationError) as exc_info:
                    validate_dependencies()
                assert "Python 3.11" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_missing_module_error(self):
        """Test error when required module is missing."""
        def mock_import(name, *args, **kwargs):
            if name == "gitlab":
                raise ImportError("No module named 'gitlab'")
            return MagicMock()

        with patch.object(sys, "version_info", (3, 11, 0)):
            with patch("builtins.__import__", side_effect=mock_import):
                with pytest.raises(ConfigurationError) as exc_info:
                    validate_dependencies()
                assert "gitlab" in str(exc_info.value)
                assert "python-gitlab" in str(exc_info.value)


class TestGitInstallationValidation:
    """Tests for validate_git_installation function."""

    @pytest.mark.timeout(60)
    def test_git_installed(self):
        """Test validation passes when Git is installed."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "git version 2.40.0"

        with patch("subprocess.run", return_value=mock_result):
            # Should not raise
            validate_git_installation()

    @pytest.mark.timeout(60)
    def test_git_not_installed(self):
        """Test error when Git is not installed."""
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            with pytest.raises(ConfigurationError) as exc_info:
                validate_git_installation()
            assert "Git is not installed" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_git_command_failed(self):
        """Test error when Git command fails."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "git: command not found"

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(ConfigurationError) as exc_info:
                validate_git_installation()
            assert "Git command failed" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_git_command_timeout(self):
        """Test error when Git command times out."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 10)):
            with pytest.raises(ConfigurationError) as exc_info:
                validate_git_installation()
            assert "timed out" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_error_includes_installation_instructions(self):
        """Test error includes platform-specific installation instructions."""
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            with pytest.raises(ConfigurationError) as exc_info:
                validate_git_installation()
            error_msg = str(exc_info.value)
            assert "apt" in error_msg or "brew" in error_msg or "Windows" in error_msg


class TestGitRepositoryValidation:
    """Tests for validate_git_repository function."""

    @pytest.mark.timeout(60)
    def test_valid_repository(self, mock_git_repo):
        """Test validation passes for valid Git repository."""
        with patch("git.Repo", return_value=mock_git_repo):
            # Should not raise
            validate_git_repository(".")

    @pytest.mark.timeout(60)
    def test_not_a_git_repository(self):
        """Test error when directory is not a Git repository."""
        import git

        with patch("git.Repo", side_effect=git.InvalidGitRepositoryError()):
            with pytest.raises(ConfigurationError) as exc_info:
                validate_git_repository("/tmp")
            assert "not inside a Git repository" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_permission_denied(self):
        """Test error when permission is denied."""
        with patch("git.Repo", side_effect=PermissionError("Access denied")):
            with pytest.raises(ConfigurationError) as exc_info:
                validate_git_repository("/protected/repo")
            assert "Permission denied" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_repository_not_accessible(self, mock_git_repo):
        """Test error when repository is not fully accessible."""
        mock_git_repo.config_reader.side_effect = Exception("Config not readable")

        with patch("git.Repo", return_value=mock_git_repo):
            with pytest.raises(ConfigurationError) as exc_info:
                validate_git_repository(".")
            assert "not fully accessible" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_error_includes_repair_guidance(self):
        """Test error includes repository repair guidance."""
        import git

        with patch("git.Repo", side_effect=git.InvalidGitRepositoryError()):
            with pytest.raises(ConfigurationError) as exc_info:
                validate_git_repository("/tmp")
            error_msg = str(exc_info.value)
            assert "git init" in error_msg or "git status" in error_msg


class TestProjectSpecValidation:
    """Tests for validate_project_specification function."""

    @pytest.mark.timeout(60)
    def test_url_spec_auto_detected(self):
        """Test URL specification is auto-detected."""
        gitlab_url, project_path = validate_project_specification(
            "https://gitlab.com/mygroup/myproject"
        )
        assert gitlab_url == "https://gitlab.com"
        assert project_path == "mygroup/myproject"

    @pytest.mark.timeout(60)
    def test_path_spec_auto_detected(self):
        """Test path specification is auto-detected."""
        gitlab_url, project_path = validate_project_specification(
            "mygroup/myproject"
        )
        assert gitlab_url == DEFAULT_GITLAB_URL
        assert project_path == "mygroup/myproject"

    @pytest.mark.timeout(60)
    def test_url_spec_explicit(self):
        """Test explicit URL specification type."""
        gitlab_url, project_path = validate_project_specification(
            "https://gitlab.example.com/ns/proj",
            spec_type="url",
        )
        assert gitlab_url == "https://gitlab.example.com"
        assert project_path == "ns/proj"

    @pytest.mark.timeout(60)
    def test_path_spec_explicit(self):
        """Test explicit path specification type."""
        gitlab_url, project_path = validate_project_specification(
            "mygroup/myproject",
            spec_type="path",
        )
        assert project_path == "mygroup/myproject"

    @pytest.mark.timeout(60)
    def test_path_spec_with_custom_gitlab_url(self):
        """Test path specification with custom GitLab URL."""
        gitlab_url, project_path = validate_project_specification(
            "mygroup/myproject",
            spec_type="path",
            gitlab_url="https://gitlab.example.com",
        )
        assert gitlab_url == "https://gitlab.example.com"
        assert project_path == "mygroup/myproject"

    @pytest.mark.timeout(60)
    def test_empty_spec_error(self):
        """Test error for empty specification."""
        with pytest.raises(ProjectResolutionError) as exc_info:
            validate_project_specification("")
        assert "required" in str(exc_info.value).lower()

    @pytest.mark.timeout(60)
    def test_none_spec_error(self):
        """Test error for None specification."""
        with pytest.raises(ProjectResolutionError) as exc_info:
            validate_project_specification(None)
        assert "required" in str(exc_info.value).lower()

    @pytest.mark.timeout(60)
    def test_invalid_path_format(self):
        """Test error for invalid path format (missing namespace)."""
        with pytest.raises(ProjectResolutionError) as exc_info:
            validate_project_specification("myproject", spec_type="path")
        assert "namespace/project" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_path_with_consecutive_slashes(self):
        """Test error for path with consecutive slashes."""
        with pytest.raises(ProjectResolutionError) as exc_info:
            validate_project_specification("group//project", spec_type="path")
        assert "empty component" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_nested_namespace_path(self):
        """Test nested namespace path is accepted."""
        gitlab_url, project_path = validate_project_specification(
            "group/subgroup/project",
            spec_type="path",
        )
        assert project_path == "group/subgroup/project"

    @pytest.mark.timeout(60)
    def test_unknown_spec_type_error(self):
        """Test error for unknown specification type."""
        with pytest.raises(ProjectResolutionError) as exc_info:
            validate_project_specification(
                "mygroup/myproject",
                spec_type="unknown",
            )
        assert "Unknown specification type" in str(exc_info.value)


class TestConfigurationValidation:
    """Tests for validate_configuration orchestration function."""

    @pytest.mark.timeout(60)
    def test_successful_validation(self, monkeypatch):
        """Test successful configuration validation."""
        monkeypatch.setenv("GITLAB_TOKEN", "x" * 26)

        with patch("glpkg.validators.validate_dependencies"):
            with patch("glpkg.validators.validate_git_installation"):
                # Should not raise
                validate_configuration(token="x" * 26, require_git=False)

    @pytest.mark.timeout(60)
    def test_validation_with_require_git(self, monkeypatch):
        """Test validation with Git requirement."""
        monkeypatch.setenv("GITLAB_TOKEN", "x" * 26)

        with patch("glpkg.validators.validate_dependencies"):
            with patch("glpkg.validators.validate_git_installation"):
                with patch("glpkg.validators.validate_git_repository"):
                    # Should not raise
                    validate_configuration(
                        token="x" * 26,
                        require_git=True,
                    )

    @pytest.mark.timeout(60)
    def test_dependencies_failure_propagates(self):
        """Test dependencies validation failure propagates."""
        with patch(
            "glpkg.validators.validate_dependencies",
            side_effect=ConfigurationError("Missing dependency"),
        ):
            with pytest.raises(ConfigurationError) as exc_info:
                validate_configuration(token="x" * 26)
            assert "Missing dependency" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_token_validation_failure_propagates(self):
        """Test token validation failure propagates."""
        with patch("glpkg.validators.validate_dependencies"):
            with pytest.raises(ConfigurationError):
                validate_configuration(token="short")

    @pytest.mark.timeout(60)
    def test_git_failure_ignored_when_not_required(self, monkeypatch):
        """Test Git validation failure is ignored when not required."""
        monkeypatch.setenv("GITLAB_TOKEN", "x" * 26)

        with patch("glpkg.validators.validate_dependencies"):
            with patch(
                "glpkg.validators.validate_git_installation",
                side_effect=ConfigurationError("Git not found"),
            ):
                # Should not raise - Git is not required
                validate_configuration(
                    token="x" * 26,
                    require_git=False,
                )

    @pytest.mark.timeout(60)
    def test_git_failure_propagates_when_required(self, monkeypatch):
        """Test Git validation failure propagates when required."""
        monkeypatch.setenv("GITLAB_TOKEN", "x" * 26)

        with patch("glpkg.validators.validate_dependencies"):
            with patch(
                "glpkg.validators.validate_git_installation",
                side_effect=ConfigurationError("Git not found"),
            ):
                with pytest.raises(ConfigurationError) as exc_info:
                    validate_configuration(
                        token="x" * 26,
                        require_git=True,
                    )
                assert "Git not found" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_token_from_environment(self, monkeypatch):
        """Test token is retrieved from environment when not provided."""
        monkeypatch.setenv("GITLAB_TOKEN", "x" * 26)

        with patch("glpkg.validators.validate_dependencies"):
            with patch("glpkg.validators.validate_git_installation"):
                # Should not raise - token from environment
                validate_configuration(token=None, require_git=False)
