"""
Comprehensive unit tests for the CLI module.

Tests cover argument parsing, flag validation, project resolution,
Git auto-detection, context building, and main orchestration.
All tests are isolated with mocked dependencies.

Test Structure:
    - TestDetermineVerbosity: Tests for verbosity flag priority
    - TestSetupLogging: Tests for logging configuration
    - TestCreateArgumentParser: Tests for argument parser creation
    - TestValidateFlags: Tests for flag validation and conflict detection
    - TestGitAutoDetector: Tests for Git repository auto-detection
    - TestProjectResolver: Tests for GitLab project resolution
    - TestUploadContextBuilder: Tests for context building
    - TestHelperFunctions: Tests for utility functions
    - TestParseArguments: Tests for argument parsing with shell completion
    - TestMainFunction: Tests for main orchestration flow
    - TestExceptionExitCodeMapping: Tests for exit code mapping
    - TestEdgeCases: Tests for edge cases and error scenarios

Running Tests:
    # Run all CLI tests
    pytest tests/unit/test_cli.py -v

    # Run specific test class
    pytest tests/unit/test_cli.py::TestDetermineVerbosity -v

    # Run tests with coverage
    pytest tests/unit/test_cli.py --cov=gitlab_pkg_upload.cli --cov-report=term-missing
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch, call

import pytest
import git
from gitlab import Gitlab
from gitlab.exceptions import GitlabAuthenticationError, GitlabGetError

from gitlab_pkg_upload.cli import (
    # Constants
    EXCEPTION_EXIT_CODE_MAP,
    # Functions
    determine_verbosity,
    setup_logging,
    create_argument_parser,
    validate_flags,
    get_version,
    parse_arguments,
    auto_detect_project,
    resolve_project_manually,
    main,
    # Classes
    GitAutoDetector,
    ProjectResolver,
    UploadContextBuilder,
)
from gitlab_pkg_upload.models import (
    DuplicatePolicy,
    GitRemoteInfo,
    ProjectInfo,
    UploadConfig,
    UploadContext,
    AuthenticationError,
    ConfigurationError,
    ProjectResolutionError,
    FileValidationError,
    NetworkError,
)

# Mark all tests as fast unit tests
pytestmark = [pytest.mark.unit, pytest.mark.fast]


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_args():
    """Create mock argument namespace with default values."""
    args = argparse.Namespace()
    args.package_name = "test-package"
    args.package_version = "1.0.0"
    args.files = ["file1.txt"]
    args.directory = None
    args.file_mapping = None
    args.project_url = None
    args.project_path = None
    args.gitlab_url = "https://gitlab.com"
    args.token = None
    args.duplicate_policy = "skip"
    args.retry = 0
    args.verbose = False
    args.quiet = False
    args.debug = False
    args.dry_run = False
    args.fail_fast = False
    args.json_output = False
    args.plain = False
    return args


@pytest.fixture
def mock_gitlab_client():
    """Create mock GitLab client."""
    mock_gl = MagicMock()
    mock_gl.url = "https://gitlab.com"
    mock_gl.api_url = "https://gitlab.com/api/v4"
    mock_gl.auth = MagicMock()
    mock_gl.user = MagicMock(username="testuser", name="Test User")
    mock_gl.projects = MagicMock()
    return mock_gl


@pytest.fixture
def mock_git_repo():
    """Create mock Git repository."""
    mock_repo = MagicMock(spec=git.Repo)
    mock_repo.working_dir = "/path/to/repo"
    return mock_repo


@pytest.fixture
def mock_git_remote():
    """Create mock Git remote."""
    mock_remote = MagicMock()
    mock_remote.name = "origin"
    mock_remote.urls = iter(["git@gitlab.com:mygroup/myproject.git"])
    return mock_remote


# =============================================================================
# Test Classes
# =============================================================================


class TestDetermineVerbosity:
    """Tests for determine_verbosity function."""

    @pytest.mark.timeout(60)
    def test_debug_flag_highest_priority(self, mock_args):
        """Test debug flag takes highest priority."""
        mock_args.debug = True
        mock_args.verbose = True
        mock_args.quiet = True
        assert determine_verbosity(mock_args) == "debug"

    @pytest.mark.timeout(60)
    def test_verbose_flag_second_priority(self, mock_args):
        """Test verbose flag takes second priority."""
        mock_args.debug = False
        mock_args.verbose = True
        mock_args.quiet = True
        assert determine_verbosity(mock_args) == "verbose"

    @pytest.mark.timeout(60)
    def test_quiet_flag_third_priority(self, mock_args):
        """Test quiet flag takes third priority."""
        mock_args.debug = False
        mock_args.verbose = False
        mock_args.quiet = True
        assert determine_verbosity(mock_args) == "quiet"

    @pytest.mark.timeout(60)
    def test_normal_default(self, mock_args):
        """Test normal is default when no flags set."""
        mock_args.debug = False
        mock_args.verbose = False
        mock_args.quiet = False
        assert determine_verbosity(mock_args) == "normal"


class TestSetupLogging:
    """Tests for setup_logging function."""

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.logging.basicConfig')
    @patch('gitlab_pkg_upload.cli.RichHandler')
    @patch('gitlab_pkg_upload.cli.Console')
    def test_logging_setup_normal(self, mock_console, mock_rich_handler, mock_basic_config, mock_args):
        """Test logging setup with normal verbosity."""
        setup_logging(mock_args)
        mock_basic_config.assert_called_once()
        call_kwargs = mock_basic_config.call_args[1]
        assert call_kwargs['level'] == logging.INFO

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.logging.basicConfig')
    @patch('gitlab_pkg_upload.cli.RichHandler')
    @patch('gitlab_pkg_upload.cli.Console')
    def test_logging_setup_debug(self, mock_console, mock_rich_handler, mock_basic_config, mock_args):
        """Test logging setup with debug verbosity."""
        mock_args.debug = True
        setup_logging(mock_args)
        call_kwargs = mock_basic_config.call_args[1]
        assert call_kwargs['level'] == logging.DEBUG

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.logging.basicConfig')
    @patch('gitlab_pkg_upload.cli.RichHandler')
    @patch('gitlab_pkg_upload.cli.Console')
    def test_logging_setup_quiet(self, mock_console, mock_rich_handler, mock_basic_config, mock_args):
        """Test logging setup with quiet verbosity."""
        mock_args.quiet = True
        setup_logging(mock_args)
        call_kwargs = mock_basic_config.call_args[1]
        assert call_kwargs['level'] == logging.WARNING

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.logging.basicConfig')
    @patch('gitlab_pkg_upload.cli.RichHandler')
    @patch('gitlab_pkg_upload.cli.Console')
    def test_logging_setup_verbose(self, mock_console, mock_rich_handler, mock_basic_config, mock_args):
        """Test logging setup with verbose verbosity."""
        mock_args.verbose = True
        setup_logging(mock_args)
        call_kwargs = mock_basic_config.call_args[1]
        assert call_kwargs['level'] == logging.INFO

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.logging.basicConfig')
    @patch('gitlab_pkg_upload.cli.RichHandler')
    @patch('gitlab_pkg_upload.cli.Console')
    def test_logging_uses_stderr_for_json_output(self, mock_console, mock_rich_handler, mock_basic_config, mock_args):
        """Test logging uses stderr when json_output is enabled."""
        mock_args.json_output = True
        setup_logging(mock_args)
        mock_console.assert_called_once()
        call_kwargs = mock_console.call_args[1]
        assert call_kwargs['file'] == sys.stderr


class TestCreateArgumentParser:
    """Tests for create_argument_parser function."""

    @pytest.mark.timeout(60)
    def test_parser_creation(self):
        """Test argument parser is created successfully."""
        parser = create_argument_parser()
        assert isinstance(parser, argparse.ArgumentParser)
        assert parser.prog == "gitlab-pkg-upload"

    @pytest.mark.timeout(60)
    def test_parser_has_required_argument_groups(self):
        """Test parser has expected argument groups and options."""
        parser = create_argument_parser()
        # Parse with no args - parser itself won't fail, but validate_flags will
        args = parser.parse_args([])
        # Verify that required argument attributes exist (even if None)
        assert hasattr(args, 'package_name')
        assert hasattr(args, 'package_version')
        assert hasattr(args, 'files')
        assert hasattr(args, 'directory')

    @pytest.mark.timeout(60)
    def test_parser_accepts_valid_arguments(self):
        """Test parser accepts valid argument combinations."""
        parser = create_argument_parser()
        args = parser.parse_args([
            '--package-name', 'test',
            '--package-version', '1.0.0',
            '--files', 'file.txt'
        ])
        assert args.package_name == 'test'
        assert args.package_version == '1.0.0'
        assert args.files == ['file.txt']

    @pytest.mark.timeout(60)
    def test_parser_duplicate_policy_choices(self):
        """Test duplicate policy accepts valid choices."""
        parser = create_argument_parser()
        for policy in ['skip', 'replace', 'error']:
            args = parser.parse_args([
                '--package-name', 'test',
                '--package-version', '1.0.0',
                '--files', 'file.txt',
                '--duplicate-policy', policy
            ])
            assert args.duplicate_policy == policy

    @pytest.mark.timeout(60)
    def test_parser_invalid_duplicate_policy(self):
        """Test invalid duplicate policy is rejected."""
        parser = create_argument_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([
                '--package-name', 'test',
                '--package-version', '1.0.0',
                '--files', 'file.txt',
                '--duplicate-policy', 'invalid'
            ])

    @pytest.mark.timeout(60)
    def test_parser_multiple_files(self):
        """Test parser accepts multiple files."""
        parser = create_argument_parser()
        args = parser.parse_args([
            '--package-name', 'test',
            '--package-version', '1.0.0',
            '--files', 'file1.txt', 'file2.txt', 'file3.txt'
        ])
        assert args.files == ['file1.txt', 'file2.txt', 'file3.txt']

    @pytest.mark.timeout(60)
    def test_parser_default_values(self):
        """Test parser has correct default values."""
        parser = create_argument_parser()
        args = parser.parse_args([
            '--package-name', 'test',
            '--package-version', '1.0.0',
            '--files', 'file.txt'
        ])
        assert args.duplicate_policy == 'skip'
        assert args.retry == 0
        assert args.verbose is False
        assert args.quiet is False
        assert args.debug is False
        assert args.dry_run is False
        assert args.fail_fast is False
        assert args.json_output is False
        assert args.plain is False

    @pytest.mark.timeout(60)
    def test_parser_directory_option(self):
        """Test parser accepts directory option."""
        parser = create_argument_parser()
        args = parser.parse_args([
            '--package-name', 'test',
            '--package-version', '1.0.0',
            '--directory', '/path/to/dir'
        ])
        assert args.directory == '/path/to/dir'
        assert args.files is None

    @pytest.mark.timeout(60)
    def test_parser_file_mapping_option(self):
        """Test parser accepts file mapping options."""
        parser = create_argument_parser()
        args = parser.parse_args([
            '--package-name', 'test',
            '--package-version', '1.0.0',
            '--files', 'file.txt',
            '--file-mapping', 'file.txt:renamed.txt',
            '--file-mapping', 'other.bin:new.bin'
        ])
        assert args.file_mapping == ['file.txt:renamed.txt', 'other.bin:new.bin']


class TestValidateFlags:
    """Tests for validate_flags function."""

    @pytest.mark.timeout(60)
    def test_missing_package_name_raises_error(self, mock_args):
        """Test missing package name raises SystemExit."""
        mock_args.package_name = None
        with pytest.raises(SystemExit) as exc_info:
            validate_flags(mock_args)
        assert exc_info.value.code == 3

    @pytest.mark.timeout(60)
    def test_missing_package_version_raises_error(self, mock_args):
        """Test missing package version raises SystemExit."""
        mock_args.package_version = None
        with pytest.raises(SystemExit) as exc_info:
            validate_flags(mock_args)
        assert exc_info.value.code == 3

    @pytest.mark.timeout(60)
    def test_both_files_and_directory_raises_error(self, mock_args):
        """Test specifying both --files and --directory raises error."""
        mock_args.files = ["file.txt"]
        mock_args.directory = "/path/to/dir"
        with pytest.raises(SystemExit) as exc_info:
            validate_flags(mock_args)
        assert exc_info.value.code == 3

    @pytest.mark.timeout(60)
    def test_multiple_verbosity_flags_raises_error(self, mock_args):
        """Test multiple verbosity flags raises error."""
        mock_args.verbose = True
        mock_args.quiet = True
        with pytest.raises(SystemExit) as exc_info:
            validate_flags(mock_args)
        assert exc_info.value.code == 3

    @pytest.mark.timeout(60)
    def test_both_project_url_and_path_raises_error(self, mock_args):
        """Test specifying both project URL and path raises error."""
        mock_args.project_url = "https://gitlab.com/group/project"
        mock_args.project_path = "group/project"
        with pytest.raises(SystemExit) as exc_info:
            validate_flags(mock_args)
        assert exc_info.value.code == 3

    @pytest.mark.timeout(60)
    def test_file_mapping_with_directory_raises_error(self, mock_args):
        """Test file mapping with directory raises error."""
        mock_args.files = None
        mock_args.directory = "/path/to/dir"
        mock_args.file_mapping = ["source:target"]
        with pytest.raises(SystemExit) as exc_info:
            validate_flags(mock_args)
        assert exc_info.value.code == 3

    @pytest.mark.timeout(60)
    def test_negative_retry_raises_error(self, mock_args):
        """Test negative retry count raises error."""
        mock_args.retry = -1
        with pytest.raises(SystemExit) as exc_info:
            validate_flags(mock_args)
        assert exc_info.value.code == 3

    @pytest.mark.timeout(60)
    def test_valid_flags_pass_validation(self, mock_args):
        """Test valid flag combination passes validation."""
        # Should not raise
        validate_flags(mock_args)

    @pytest.mark.timeout(60)
    def test_no_file_input_raises_error(self, mock_args):
        """Test no file input raises error."""
        mock_args.files = None
        mock_args.directory = None
        with pytest.raises(SystemExit) as exc_info:
            validate_flags(mock_args)
        assert exc_info.value.code == 3

    @pytest.mark.timeout(60)
    def test_all_verbosity_flags_raises_error(self, mock_args):
        """Test all three verbosity flags raises error."""
        mock_args.verbose = True
        mock_args.quiet = True
        mock_args.debug = True
        with pytest.raises(SystemExit) as exc_info:
            validate_flags(mock_args)
        assert exc_info.value.code == 3

    @pytest.mark.timeout(60)
    def test_verbose_and_debug_raises_error(self, mock_args):
        """Test verbose and debug flags raises error."""
        mock_args.verbose = True
        mock_args.debug = True
        with pytest.raises(SystemExit) as exc_info:
            validate_flags(mock_args)
        assert exc_info.value.code == 3

    @pytest.mark.timeout(60)
    def test_zero_retry_is_valid(self, mock_args):
        """Test zero retry count is valid."""
        mock_args.retry = 0
        # Should not raise
        validate_flags(mock_args)

    @pytest.mark.timeout(60)
    def test_positive_retry_is_valid(self, mock_args):
        """Test positive retry count is valid."""
        mock_args.retry = 5
        # Should not raise
        validate_flags(mock_args)


class TestGitAutoDetector:
    """Tests for GitAutoDetector class."""

    @pytest.mark.timeout(60)
    def test_initialization(self):
        """Test GitAutoDetector initialization."""
        detector = GitAutoDetector()
        assert detector.working_directory == "."

    @pytest.mark.timeout(60)
    def test_initialization_with_custom_directory(self):
        """Test GitAutoDetector with custom directory."""
        detector = GitAutoDetector("/custom/path")
        assert detector.working_directory == "/custom/path"

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.git.Repo')
    def test_find_git_repository_success(self, mock_repo_class):
        """Test finding Git repository successfully."""
        mock_repo = MagicMock()
        mock_repo.working_dir = "/path/to/repo"
        mock_repo_class.return_value = mock_repo

        detector = GitAutoDetector()
        repo = detector.find_git_repository()

        assert repo is mock_repo
        mock_repo_class.assert_called_once_with(".", search_parent_directories=True)

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.git.Repo')
    def test_find_git_repository_not_found(self, mock_repo_class):
        """Test Git repository not found returns None."""
        mock_repo_class.side_effect = git.InvalidGitRepositoryError()

        detector = GitAutoDetector()
        repo = detector.find_git_repository()

        assert repo is None

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.git.Repo')
    def test_find_git_repository_permission_error(self, mock_repo_class):
        """Test Git repository permission error raises ProjectResolutionError."""
        mock_repo_class.side_effect = PermissionError("Access denied")

        detector = GitAutoDetector()
        with pytest.raises(ProjectResolutionError) as exc_info:
            detector.find_git_repository()
        assert "Permission denied" in str(exc_info.value)

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.git.Repo')
    def test_find_git_repository_git_command_error(self, mock_repo_class):
        """Test Git command error raises ProjectResolutionError."""
        mock_repo_class.side_effect = git.GitCommandError("git status", 128, stderr="fatal: error")

        detector = GitAutoDetector()
        with pytest.raises(ProjectResolutionError) as exc_info:
            detector.find_git_repository()
        assert "Git command error" in str(exc_info.value)

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.git.Repo')
    def test_find_git_repository_os_error(self, mock_repo_class):
        """Test OS error raises ProjectResolutionError."""
        mock_repo_class.side_effect = OSError("Disk error")

        detector = GitAutoDetector()
        with pytest.raises(ProjectResolutionError) as exc_info:
            detector.find_git_repository()
        assert "OS error" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_looks_like_gitlab_url(self):
        """Test GitLab URL detection."""
        detector = GitAutoDetector()
        assert detector._looks_like_gitlab_url("https://gitlab.com/project")
        assert detector._looks_like_gitlab_url("https://my.gitlab.io/project")
        assert detector._looks_like_gitlab_url("https://gitlab.example.com/project")
        assert detector._looks_like_gitlab_url("https://git.lab.company.com/project")
        assert not detector._looks_like_gitlab_url("https://github.com/project")
        assert not detector._looks_like_gitlab_url("https://example.com/project")

    @pytest.mark.timeout(60)
    def test_is_known_non_gitlab_host(self):
        """Test known non-GitLab host detection."""
        detector = GitAutoDetector()
        assert detector._is_known_non_gitlab_host("github.com")
        assert detector._is_known_non_gitlab_host("bitbucket.org")
        assert detector._is_known_non_gitlab_host("codeberg.org")
        assert detector._is_known_non_gitlab_host("dev.azure.com")
        assert not detector._is_known_non_gitlab_host("gitlab.com")
        assert not detector._is_known_non_gitlab_host("gitlab.example.com")

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.parse_git_url')
    def test_parse_git_url_success(self, mock_parse):
        """Test parsing Git URL successfully."""
        mock_parse.return_value = ("https://gitlab.com", "group/project")

        detector = GitAutoDetector()
        result = detector.parse_git_url("git@gitlab.com:group/project.git")

        assert result == ("https://gitlab.com", "group/project")

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.parse_git_url')
    def test_parse_git_url_non_gitlab(self, mock_parse):
        """Test parsing non-GitLab URL returns None."""
        mock_parse.return_value = ("https://github.com", "group/project")

        detector = GitAutoDetector()
        result = detector.parse_git_url("git@github.com:group/project.git")

        assert result is None

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.parse_git_url')
    def test_parse_git_url_unknown_host(self, mock_parse):
        """Test parsing URL from unknown host still returns it."""
        mock_parse.return_value = ("https://git.example.com", "group/project")

        detector = GitAutoDetector()
        result = detector.parse_git_url("git@git.example.com:group/project.git")

        # Unknown hosts are returned (could be self-hosted GitLab)
        assert result == ("https://git.example.com", "group/project")

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.parse_git_url')
    def test_parse_git_url_gitlab_like_error(self, mock_parse):
        """Test parsing GitLab-like URL that fails raises error."""
        mock_parse.side_effect = Exception("Parse error")

        detector = GitAutoDetector()
        with pytest.raises(ProjectResolutionError) as exc_info:
            detector.parse_git_url("https://gitlab.com/invalid")
        assert "format is unrecognized" in str(exc_info.value)

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.parse_git_url')
    def test_parse_git_url_non_gitlab_error_returns_none(self, mock_parse):
        """Test parsing non-GitLab URL that fails returns None."""
        mock_parse.side_effect = Exception("Parse error")

        detector = GitAutoDetector()
        result = detector.parse_git_url("https://example.com/something")

        assert result is None

    @pytest.mark.timeout(60)
    def test_get_gitlab_remotes_success(self, mock_git_repo):
        """Test extracting GitLab remotes successfully."""
        mock_remote = MagicMock()
        mock_remote.name = "origin"
        mock_remote.urls = iter(["git@gitlab.com:group/project.git"])
        mock_git_repo.remotes = [mock_remote]

        detector = GitAutoDetector()
        with patch.object(detector, 'parse_git_url', return_value=("https://gitlab.com", "group/project")):
            remotes = detector.get_gitlab_remotes(mock_git_repo)

        assert len(remotes) == 1
        assert remotes[0].name == "origin"
        assert remotes[0].gitlab_url == "https://gitlab.com"
        assert remotes[0].project_path == "group/project"

    @pytest.mark.timeout(60)
    def test_get_gitlab_remotes_no_remotes(self, mock_git_repo):
        """Test no remotes raises ProjectResolutionError."""
        mock_git_repo.remotes = []

        detector = GitAutoDetector()
        with pytest.raises(ProjectResolutionError) as exc_info:
            detector.get_gitlab_remotes(mock_git_repo)
        assert "No Git remotes configured" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_get_gitlab_remotes_prioritizes_origin(self, mock_git_repo):
        """Test origin remote is prioritized."""
        mock_remote1 = MagicMock()
        mock_remote1.name = "upstream"
        mock_remote1.urls = iter(["git@gitlab.com:group/project1.git"])

        mock_remote2 = MagicMock()
        mock_remote2.name = "origin"
        mock_remote2.urls = iter(["git@gitlab.com:group/project2.git"])

        mock_git_repo.remotes = [mock_remote1, mock_remote2]

        detector = GitAutoDetector()
        with patch.object(detector, 'parse_git_url', side_effect=[
            ("https://gitlab.com", "group/project1"),
            ("https://gitlab.com", "group/project2")
        ]):
            remotes = detector.get_gitlab_remotes(mock_git_repo)

        assert remotes[0].name == "origin"
        assert remotes[0].project_path == "group/project2"

    @pytest.mark.timeout(60)
    def test_get_gitlab_remotes_no_gitlab_remotes(self, mock_git_repo):
        """Test no GitLab remotes raises ProjectResolutionError."""
        mock_remote = MagicMock()
        mock_remote.name = "origin"
        mock_remote.urls = iter(["git@github.com:group/project.git"])
        mock_git_repo.remotes = [mock_remote]

        detector = GitAutoDetector()
        with patch.object(detector, 'parse_git_url', return_value=None):
            with pytest.raises(ProjectResolutionError) as exc_info:
                detector.get_gitlab_remotes(mock_git_repo)
        assert "No GitLab remotes found" in str(exc_info.value)


class TestProjectResolver:
    """Tests for ProjectResolver class."""

    @pytest.mark.timeout(60)
    def test_initialization(self, mock_gitlab_client):
        """Test ProjectResolver initialization."""
        resolver = ProjectResolver(mock_gitlab_client)
        assert resolver.gl is mock_gitlab_client
        assert isinstance(resolver.project_cache, dict)

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.normalize_gitlab_url')
    def test_parse_project_url_success(self, mock_normalize, mock_gitlab_client):
        """Test parsing project URL successfully."""
        mock_normalize.return_value = ("https://gitlab.com", "group/project")

        resolver = ProjectResolver(mock_gitlab_client)
        result = resolver.parse_project_url("https://gitlab.com/group/project")

        assert isinstance(result, ProjectInfo)
        assert result.gitlab_url == "https://gitlab.com"
        assert result.project_path == "group/project"
        assert result.namespace == "group"
        assert result.project_name == "project"

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.normalize_gitlab_url')
    def test_parse_project_url_nested_namespace(self, mock_normalize, mock_gitlab_client):
        """Test parsing project URL with nested namespace."""
        mock_normalize.return_value = ("https://gitlab.com", "group/subgroup/project")

        resolver = ProjectResolver(mock_gitlab_client)
        result = resolver.parse_project_url("https://gitlab.com/group/subgroup/project")

        assert result.namespace == "group/subgroup"
        assert result.project_name == "project"

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.normalize_gitlab_url')
    def test_parse_project_url_invalid(self, mock_normalize, mock_gitlab_client):
        """Test parsing invalid project URL raises error."""
        mock_normalize.side_effect = Exception("Invalid URL")

        resolver = ProjectResolver(mock_gitlab_client)
        with pytest.raises(ProjectResolutionError) as exc_info:
            resolver.parse_project_url("invalid-url")
        assert "Invalid GitLab project URL" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_resolve_project_id_success(self, mock_gitlab_client):
        """Test resolving project ID successfully."""
        mock_project = MagicMock()
        mock_project.id = 12345
        mock_gitlab_client.projects.get.return_value = mock_project

        resolver = ProjectResolver(mock_gitlab_client)
        project_id = resolver.resolve_project_id("https://gitlab.com", "group/project")

        assert project_id == 12345
        mock_gitlab_client.projects.get.assert_called_once_with("group/project")

    @pytest.mark.timeout(60)
    def test_resolve_project_id_cached(self, mock_gitlab_client):
        """Test project ID resolution uses cache."""
        mock_project = MagicMock()
        mock_project.id = 12345
        mock_gitlab_client.projects.get.return_value = mock_project

        resolver = ProjectResolver(mock_gitlab_client)
        # First call
        project_id1 = resolver.resolve_project_id("https://gitlab.com", "group/project")
        # Second call should use cache
        project_id2 = resolver.resolve_project_id("https://gitlab.com", "group/project")

        assert project_id1 == project_id2
        # Should only call API once
        assert mock_gitlab_client.projects.get.call_count == 1

    @pytest.mark.timeout(60)
    def test_resolve_project_id_not_found(self, mock_gitlab_client):
        """Test project not found raises ProjectResolutionError."""
        mock_gitlab_client.projects.get.side_effect = GitlabGetError("404 Not Found")

        resolver = ProjectResolver(mock_gitlab_client)
        with pytest.raises(ProjectResolutionError):
            resolver.resolve_project_id("https://gitlab.com", "group/nonexistent")

    @pytest.mark.timeout(60)
    def test_resolve_project_id_auth_error(self, mock_gitlab_client):
        """Test authentication error raises ProjectResolutionError."""
        mock_gitlab_client.projects.get.side_effect = GitlabAuthenticationError("401 Unauthorized")

        resolver = ProjectResolver(mock_gitlab_client)
        with pytest.raises(ProjectResolutionError):
            resolver.resolve_project_id("https://gitlab.com", "group/project")

    @pytest.mark.timeout(60)
    def test_validate_project_access_success(self, mock_gitlab_client):
        """Test validating project access successfully."""
        mock_project = MagicMock()
        mock_project.name = "Test Project"
        mock_project.path_with_namespace = "group/project"
        mock_gitlab_client.projects.get.return_value = mock_project

        resolver = ProjectResolver(mock_gitlab_client)
        result = resolver.validate_project_access(12345)

        assert result is True

    @pytest.mark.timeout(60)
    def test_validate_project_access_failure(self, mock_gitlab_client):
        """Test validating project access failure."""
        mock_gitlab_client.projects.get.side_effect = Exception("Access denied")

        resolver = ProjectResolver(mock_gitlab_client)
        result = resolver.validate_project_access(12345)

        assert result is False


class TestUploadContextBuilder:
    """Tests for UploadContextBuilder class."""

    @pytest.mark.timeout(60)
    def test_initialization(self):
        """Test UploadContextBuilder initialization."""
        builder = UploadContextBuilder()
        assert builder is not None

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.DuplicateDetector')
    def test_build_context_success(self, mock_detector_class, mock_args, mock_gitlab_client):
        """Test building upload context successfully."""
        mock_detector = MagicMock()
        mock_detector_class.return_value = mock_detector
        mock_args.duplicate_policy = DuplicatePolicy.SKIP

        builder = UploadContextBuilder()
        context = builder.build(
            args=mock_args,
            gl=mock_gitlab_client,
            project_id=12345,
            project_path="group/project",
            gitlab_url="https://gitlab.com",
            token="test-token"
        )

        assert isinstance(context, UploadContext)
        assert context.gl is mock_gitlab_client
        assert context.project_id == 12345
        assert context.project_path == "group/project"
        assert isinstance(context.config, UploadConfig)
        assert context.config.package_name == "test-package"
        assert context.config.version == "1.0.0"

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.DuplicateDetector')
    def test_build_context_with_verbosity(self, mock_detector_class, mock_args, mock_gitlab_client):
        """Test context building respects verbosity settings."""
        mock_detector = MagicMock()
        mock_detector_class.return_value = mock_detector
        mock_args.verbose = True
        mock_args.duplicate_policy = DuplicatePolicy.SKIP

        builder = UploadContextBuilder()
        context = builder.build(
            args=mock_args,
            gl=mock_gitlab_client,
            project_id=12345,
            project_path="group/project",
            gitlab_url="https://gitlab.com",
            token="test-token"
        )

        assert context.config.verbosity == "verbose"

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.DuplicateDetector')
    def test_build_context_with_dry_run(self, mock_detector_class, mock_args, mock_gitlab_client):
        """Test context building with dry run enabled."""
        mock_detector = MagicMock()
        mock_detector_class.return_value = mock_detector
        mock_args.dry_run = True
        mock_args.duplicate_policy = DuplicatePolicy.SKIP

        builder = UploadContextBuilder()
        context = builder.build(
            args=mock_args,
            gl=mock_gitlab_client,
            project_id=12345,
            project_path="group/project",
            gitlab_url="https://gitlab.com",
            token="test-token"
        )

        assert context.config.dry_run is True

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.DuplicateDetector')
    def test_build_context_with_debug(self, mock_detector_class, mock_args, mock_gitlab_client):
        """Test context building with debug verbosity."""
        mock_detector = MagicMock()
        mock_detector_class.return_value = mock_detector
        mock_args.debug = True
        mock_args.duplicate_policy = DuplicatePolicy.SKIP

        builder = UploadContextBuilder()
        context = builder.build(
            args=mock_args,
            gl=mock_gitlab_client,
            project_id=12345,
            project_path="group/project",
            gitlab_url="https://gitlab.com",
            token="test-token"
        )

        assert context.config.verbosity == "debug"

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.DuplicateDetector')
    def test_build_context_with_replace_policy(self, mock_detector_class, mock_args, mock_gitlab_client):
        """Test context building with replace duplicate policy."""
        mock_detector = MagicMock()
        mock_detector_class.return_value = mock_detector
        mock_args.duplicate_policy = DuplicatePolicy.REPLACE

        builder = UploadContextBuilder()
        context = builder.build(
            args=mock_args,
            gl=mock_gitlab_client,
            project_id=12345,
            project_path="group/project",
            gitlab_url="https://gitlab.com",
            token="test-token"
        )

        assert context.config.duplicate_policy == DuplicatePolicy.REPLACE

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.DuplicateDetector')
    def test_build_context_error_handling(self, mock_detector_class, mock_args, mock_gitlab_client):
        """Test context building raises ConfigurationError on failure."""
        mock_detector_class.side_effect = Exception("Detector init failed")
        mock_args.duplicate_policy = DuplicatePolicy.SKIP

        builder = UploadContextBuilder()
        with pytest.raises(ConfigurationError) as exc_info:
            builder.build(
                args=mock_args,
                gl=mock_gitlab_client,
                project_id=12345,
                project_path="group/project",
                gitlab_url="https://gitlab.com",
                token="test-token"
            )
        assert "Failed to build upload context" in str(exc_info.value)


class TestHelperFunctions:
    """Tests for helper functions."""

    @pytest.mark.timeout(60)
    def test_get_version_returns_string(self):
        """Test get_version returns a string."""
        version = get_version()
        assert isinstance(version, str)
        # Version should not be empty
        assert len(version) > 0

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.GitAutoDetector')
    def test_auto_detect_project_success(self, mock_detector_class):
        """Test auto-detecting project successfully."""
        mock_detector = MagicMock()
        mock_repo = MagicMock()
        mock_remote = GitRemoteInfo(
            name="origin",
            url="git@gitlab.com:group/project.git",
            gitlab_url="https://gitlab.com",
            project_path="group/project"
        )
        mock_detector.find_git_repository.return_value = mock_repo
        mock_detector.get_gitlab_remotes.return_value = [mock_remote]
        mock_detector_class.return_value = mock_detector

        gitlab_url, project_path = auto_detect_project()

        assert gitlab_url == "https://gitlab.com"
        assert project_path == "group/project"

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.GitAutoDetector')
    def test_auto_detect_project_no_repo(self, mock_detector_class):
        """Test auto-detect fails when no Git repository found."""
        mock_detector = MagicMock()
        mock_detector.find_git_repository.return_value = None
        mock_detector_class.return_value = mock_detector

        with pytest.raises(ProjectResolutionError) as exc_info:
            auto_detect_project()
        assert "No Git repository found" in str(exc_info.value)

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.normalize_gitlab_url')
    def test_resolve_project_manually_with_url(self, mock_normalize):
        """Test manual project resolution with URL."""
        mock_normalize.return_value = ("https://gitlab.com", "group/project")

        gitlab_url, project_path = resolve_project_manually(
            project_url="https://gitlab.com/group/project",
            project_path=None,
            gitlab_url="https://gitlab.com"
        )

        assert gitlab_url == "https://gitlab.com"
        assert project_path == "group/project"

    @pytest.mark.timeout(60)
    def test_resolve_project_manually_with_path(self):
        """Test manual project resolution with path."""
        gitlab_url, project_path = resolve_project_manually(
            project_url=None,
            project_path="group/project",
            gitlab_url="https://gitlab.com"
        )

        assert gitlab_url == "https://gitlab.com"
        assert project_path == "group/project"

    @pytest.mark.timeout(60)
    def test_resolve_project_manually_with_nested_path(self):
        """Test manual project resolution with nested path."""
        gitlab_url, project_path = resolve_project_manually(
            project_url=None,
            project_path="group/subgroup/project",
            gitlab_url="https://gitlab.example.com"
        )

        assert gitlab_url == "https://gitlab.example.com"
        assert project_path == "group/subgroup/project"

    @pytest.mark.timeout(60)
    def test_resolve_project_manually_invalid_path(self):
        """Test manual resolution with invalid path format."""
        with pytest.raises(ProjectResolutionError) as exc_info:
            resolve_project_manually(
                project_url=None,
                project_path="invalid",  # Missing namespace
                gitlab_url="https://gitlab.com"
            )
        assert "Invalid project path format" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_resolve_project_manually_no_specification(self):
        """Test manual resolution with no specification raises error."""
        with pytest.raises(ProjectResolutionError) as exc_info:
            resolve_project_manually(
                project_url=None,
                project_path=None,
                gitlab_url="https://gitlab.com"
            )
        assert "No project specification provided" in str(exc_info.value)

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.normalize_gitlab_url')
    def test_resolve_project_manually_url_parse_error(self, mock_normalize):
        """Test manual resolution with URL parse error."""
        mock_normalize.side_effect = Exception("Invalid URL format")

        with pytest.raises(ProjectResolutionError) as exc_info:
            resolve_project_manually(
                project_url="not-a-valid-url",
                project_path=None,
                gitlab_url="https://gitlab.com"
            )
        assert "Invalid project URL" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_resolve_project_manually_strips_slashes(self):
        """Test manual resolution strips leading/trailing slashes from path."""
        gitlab_url, project_path = resolve_project_manually(
            project_url=None,
            project_path="/group/project/",
            gitlab_url="https://gitlab.com"
        )

        assert project_path == "group/project"

    @pytest.mark.timeout(60)
    def test_resolve_project_manually_empty_path_parts(self):
        """Test manual resolution with empty path parts raises error."""
        with pytest.raises(ProjectResolutionError) as exc_info:
            resolve_project_manually(
                project_url=None,
                project_path="/project",  # Empty namespace
                gitlab_url="https://gitlab.com"
            )
        assert "Invalid project path" in str(exc_info.value)


class TestParseArguments:
    """Tests for parse_arguments function."""

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.argcomplete.autocomplete')
    @patch('gitlab_pkg_upload.cli.validate_flags')
    def test_parse_arguments_success(self, mock_validate, mock_autocomplete):
        """Test parsing arguments successfully."""
        result = parse_arguments([
            '--package-name', 'test',
            '--package-version', '1.0.0',
            '--files', 'file.txt'
        ])

        assert result.package_name == "test"
        assert result.package_version == "1.0.0"
        mock_autocomplete.assert_called_once()

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.argcomplete.autocomplete')
    @patch('gitlab_pkg_upload.cli.validate_flags')
    def test_parse_arguments_converts_duplicate_policy(self, mock_validate, mock_autocomplete):
        """Test duplicate policy is converted to enum."""
        result = parse_arguments([
            '--package-name', 'test',
            '--package-version', '1.0.0',
            '--files', 'file.txt',
            '--duplicate-policy', 'replace'
        ])

        assert result.duplicate_policy == DuplicatePolicy.REPLACE

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.argcomplete.autocomplete')
    @patch('gitlab_pkg_upload.cli.validate_flags')
    def test_parse_arguments_all_policies(self, mock_validate, mock_autocomplete):
        """Test all duplicate policies are converted correctly."""
        for policy_str, policy_enum in [
            ('skip', DuplicatePolicy.SKIP),
            ('replace', DuplicatePolicy.REPLACE),
            ('error', DuplicatePolicy.ERROR)
        ]:
            result = parse_arguments([
                '--package-name', 'test',
                '--package-version', '1.0.0',
                '--files', 'file.txt',
                '--duplicate-policy', policy_str
            ])
            assert result.duplicate_policy == policy_enum


class TestMainFunction:
    """Tests for main function orchestration."""

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.parse_arguments')
    @patch('gitlab_pkg_upload.cli.setup_logging')
    @patch('gitlab_pkg_upload.cli.auto_detect_project')
    def test_main_authentication_error(self, mock_auto_detect, mock_setup_logging,
                                       mock_parse_args, mock_args):
        """Test main function handles authentication error."""
        mock_parse_args.return_value = mock_args
        mock_auto_detect.side_effect = AuthenticationError("Auth failed")

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 2

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.parse_arguments')
    @patch('gitlab_pkg_upload.cli.setup_logging')
    @patch('gitlab_pkg_upload.cli.auto_detect_project')
    def test_main_configuration_error(self, mock_auto_detect, mock_setup_logging,
                                      mock_parse_args, mock_args):
        """Test main function handles configuration error."""
        mock_parse_args.return_value = mock_args
        mock_auto_detect.side_effect = ConfigurationError("Config error")

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 3

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.parse_arguments')
    @patch('gitlab_pkg_upload.cli.setup_logging')
    @patch('gitlab_pkg_upload.cli.auto_detect_project')
    def test_main_project_resolution_error(self, mock_auto_detect, mock_setup_logging,
                                           mock_parse_args, mock_args):
        """Test main function handles project resolution error."""
        mock_parse_args.return_value = mock_args
        mock_auto_detect.side_effect = ProjectResolutionError("Project not found")

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 4

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.parse_arguments')
    @patch('gitlab_pkg_upload.cli.setup_logging')
    @patch('gitlab_pkg_upload.cli.auto_detect_project')
    def test_main_file_not_found_error(self, mock_auto_detect, mock_setup_logging,
                                       mock_parse_args, mock_args):
        """Test main function handles FileNotFoundError."""
        mock_parse_args.return_value = mock_args
        mock_auto_detect.side_effect = FileNotFoundError("File missing")

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 5

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.parse_arguments')
    @patch('gitlab_pkg_upload.cli.setup_logging')
    @patch('gitlab_pkg_upload.cli.auto_detect_project')
    def test_main_permission_error(self, mock_auto_detect, mock_setup_logging,
                                   mock_parse_args, mock_args):
        """Test main function handles PermissionError."""
        mock_parse_args.return_value = mock_args
        mock_auto_detect.side_effect = PermissionError("Access denied")

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 5

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.parse_arguments')
    @patch('gitlab_pkg_upload.cli.setup_logging')
    @patch('gitlab_pkg_upload.cli.auto_detect_project')
    def test_main_value_error(self, mock_auto_detect, mock_setup_logging,
                              mock_parse_args, mock_args):
        """Test main function handles ValueError."""
        mock_parse_args.return_value = mock_args
        mock_auto_detect.side_effect = ValueError("Invalid value")

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 3

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.parse_arguments')
    @patch('gitlab_pkg_upload.cli.setup_logging')
    @patch('gitlab_pkg_upload.cli.auto_detect_project')
    def test_main_connection_error(self, mock_auto_detect, mock_setup_logging,
                                   mock_parse_args, mock_args):
        """Test main function handles ConnectionError."""
        mock_parse_args.return_value = mock_args
        mock_auto_detect.side_effect = ConnectionError("Network error")

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 6

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.parse_arguments')
    @patch('gitlab_pkg_upload.cli.setup_logging')
    @patch('gitlab_pkg_upload.cli.auto_detect_project')
    def test_main_timeout_error(self, mock_auto_detect, mock_setup_logging,
                                mock_parse_args, mock_args):
        """Test main function handles TimeoutError."""
        mock_parse_args.return_value = mock_args
        mock_auto_detect.side_effect = TimeoutError("Timed out")

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 6

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.parse_arguments')
    @patch('gitlab_pkg_upload.cli.setup_logging')
    @patch('gitlab_pkg_upload.cli.auto_detect_project')
    def test_main_unexpected_error(self, mock_auto_detect, mock_setup_logging,
                                   mock_parse_args, mock_args):
        """Test main function handles unexpected errors."""
        mock_parse_args.return_value = mock_args
        mock_auto_detect.side_effect = RuntimeError("Unexpected error")

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.parse_arguments')
    @patch('gitlab_pkg_upload.cli.setup_logging')
    @patch('gitlab_pkg_upload.cli.resolve_project_manually')
    @patch('gitlab_pkg_upload.cli.get_gitlab_token')
    @patch('gitlab_pkg_upload.cli.Gitlab')
    @patch('gitlab_pkg_upload.cli.ProjectResolver')
    @patch('gitlab_pkg_upload.cli.UploadContextBuilder')
    @patch('gitlab_pkg_upload.cli.collect_files')
    @patch('gitlab_pkg_upload.cli.upload_files')
    @patch('gitlab_pkg_upload.cli.OutputFormatter')
    def test_main_success_flow(self, mock_formatter_class, mock_upload,
                               mock_collect, mock_builder_class,
                               mock_resolver_class, mock_gitlab_class,
                               mock_get_token, mock_resolve_manual,
                               mock_setup_logging, mock_parse_args, mock_args):
        """Test main function success flow."""
        # Setup args for manual project specification
        mock_args.project_url = "https://gitlab.com/group/project"
        mock_args.duplicate_policy = DuplicatePolicy.SKIP
        mock_parse_args.return_value = mock_args
        mock_resolve_manual.return_value = ("https://gitlab.com", "group/project")
        mock_get_token.return_value = "test-token"

        mock_gl = MagicMock()
        mock_gitlab_class.return_value = mock_gl

        mock_resolver = MagicMock()
        mock_resolver.resolve_project_id.return_value = 12345
        mock_resolver.validate_project_access.return_value = True
        mock_resolver_class.return_value = mock_resolver

        mock_builder = MagicMock()
        mock_context = MagicMock()
        mock_context.config = MagicMock()
        mock_context.config.package_name = "test-package"
        mock_context.config.version = "1.0.0"
        mock_builder.build.return_value = mock_context
        mock_builder_class.return_value = mock_builder

        mock_collect.return_value = ([MagicMock()], [])
        mock_result = MagicMock()
        mock_result.success = True
        mock_upload.return_value = [mock_result]

        mock_formatter = MagicMock()
        mock_formatter_class.return_value = mock_formatter

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        mock_setup_logging.assert_called_once()
        mock_gl.auth.assert_called_once()

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.parse_arguments')
    @patch('gitlab_pkg_upload.cli.setup_logging')
    @patch('gitlab_pkg_upload.cli.resolve_project_manually')
    @patch('gitlab_pkg_upload.cli.get_gitlab_token')
    @patch('gitlab_pkg_upload.cli.Gitlab')
    @patch('gitlab_pkg_upload.cli.ProjectResolver')
    def test_main_project_access_validation_fails(self, mock_resolver_class,
                                                   mock_gitlab_class, mock_get_token,
                                                   mock_resolve_manual, mock_setup_logging,
                                                   mock_parse_args, mock_args):
        """Test main function when project access validation fails."""
        mock_args.project_url = "https://gitlab.com/group/project"
        mock_args.duplicate_policy = DuplicatePolicy.SKIP
        mock_parse_args.return_value = mock_args
        mock_resolve_manual.return_value = ("https://gitlab.com", "group/project")
        mock_get_token.return_value = "test-token"

        mock_gl = MagicMock()
        mock_gitlab_class.return_value = mock_gl

        mock_resolver = MagicMock()
        mock_resolver.resolve_project_id.return_value = 12345
        mock_resolver.validate_project_access.return_value = False
        mock_resolver_class.return_value = mock_resolver

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 4

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.parse_arguments')
    @patch('gitlab_pkg_upload.cli.setup_logging')
    @patch('gitlab_pkg_upload.cli.resolve_project_manually')
    @patch('gitlab_pkg_upload.cli.get_gitlab_token')
    @patch('gitlab_pkg_upload.cli.Gitlab')
    @patch('gitlab_pkg_upload.cli.ProjectResolver')
    @patch('gitlab_pkg_upload.cli.UploadContextBuilder')
    @patch('gitlab_pkg_upload.cli.collect_files')
    def test_main_no_valid_files(self, mock_collect, mock_builder_class,
                                 mock_resolver_class, mock_gitlab_class,
                                 mock_get_token, mock_resolve_manual,
                                 mock_setup_logging, mock_parse_args, mock_args):
        """Test main function with no valid files to upload."""
        mock_args.project_url = "https://gitlab.com/group/project"
        mock_args.duplicate_policy = DuplicatePolicy.SKIP
        mock_parse_args.return_value = mock_args
        mock_resolve_manual.return_value = ("https://gitlab.com", "group/project")
        mock_get_token.return_value = "test-token"

        mock_gl = MagicMock()
        mock_gitlab_class.return_value = mock_gl

        mock_resolver = MagicMock()
        mock_resolver.resolve_project_id.return_value = 12345
        mock_resolver.validate_project_access.return_value = True
        mock_resolver_class.return_value = mock_resolver

        mock_builder = MagicMock()
        mock_context = MagicMock()
        mock_builder.build.return_value = mock_context
        mock_builder_class.return_value = mock_builder

        # No valid files
        mock_collect.return_value = ([], [])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 5

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.parse_arguments')
    @patch('gitlab_pkg_upload.cli.setup_logging')
    @patch('gitlab_pkg_upload.cli.resolve_project_manually')
    @patch('gitlab_pkg_upload.cli.get_gitlab_token')
    @patch('gitlab_pkg_upload.cli.Gitlab')
    @patch('gitlab_pkg_upload.cli.ProjectResolver')
    @patch('gitlab_pkg_upload.cli.UploadContextBuilder')
    @patch('gitlab_pkg_upload.cli.collect_files')
    @patch('gitlab_pkg_upload.cli.upload_files')
    @patch('gitlab_pkg_upload.cli.OutputFormatter')
    def test_main_partial_upload_failure(self, mock_formatter_class, mock_upload,
                                         mock_collect, mock_builder_class,
                                         mock_resolver_class, mock_gitlab_class,
                                         mock_get_token, mock_resolve_manual,
                                         mock_setup_logging, mock_parse_args, mock_args):
        """Test main function with partial upload failures."""
        mock_args.project_url = "https://gitlab.com/group/project"
        mock_args.duplicate_policy = DuplicatePolicy.SKIP
        mock_parse_args.return_value = mock_args
        mock_resolve_manual.return_value = ("https://gitlab.com", "group/project")
        mock_get_token.return_value = "test-token"

        mock_gl = MagicMock()
        mock_gitlab_class.return_value = mock_gl

        mock_resolver = MagicMock()
        mock_resolver.resolve_project_id.return_value = 12345
        mock_resolver.validate_project_access.return_value = True
        mock_resolver_class.return_value = mock_resolver

        mock_builder = MagicMock()
        mock_context = MagicMock()
        mock_context.config = MagicMock()
        mock_context.config.package_name = "test-package"
        mock_context.config.version = "1.0.0"
        mock_builder.build.return_value = mock_context
        mock_builder_class.return_value = mock_builder

        mock_collect.return_value = ([MagicMock(), MagicMock()], [])
        # One success, one failure
        mock_result1 = MagicMock()
        mock_result1.success = True
        mock_result2 = MagicMock()
        mock_result2.success = False
        mock_upload.return_value = [mock_result1, mock_result2]

        mock_formatter = MagicMock()
        mock_formatter_class.return_value = mock_formatter

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.parse_arguments')
    @patch('gitlab_pkg_upload.cli.setup_logging')
    @patch('gitlab_pkg_upload.cli.resolve_project_manually')
    @patch('gitlab_pkg_upload.cli.get_gitlab_token')
    @patch('gitlab_pkg_upload.cli.Gitlab')
    @patch('gitlab_pkg_upload.cli.ProjectResolver')
    @patch('gitlab_pkg_upload.cli.UploadContextBuilder')
    @patch('gitlab_pkg_upload.cli.collect_files')
    def test_main_file_errors_with_fail_fast(self, mock_collect, mock_builder_class,
                                             mock_resolver_class, mock_gitlab_class,
                                             mock_get_token, mock_resolve_manual,
                                             mock_setup_logging, mock_parse_args, mock_args):
        """Test main function with file errors and fail_fast enabled."""
        mock_args.project_url = "https://gitlab.com/group/project"
        mock_args.duplicate_policy = DuplicatePolicy.SKIP
        mock_args.fail_fast = True
        mock_parse_args.return_value = mock_args
        mock_resolve_manual.return_value = ("https://gitlab.com", "group/project")
        mock_get_token.return_value = "test-token"

        mock_gl = MagicMock()
        mock_gitlab_class.return_value = mock_gl

        mock_resolver = MagicMock()
        mock_resolver.resolve_project_id.return_value = 12345
        mock_resolver.validate_project_access.return_value = True
        mock_resolver_class.return_value = mock_resolver

        mock_builder = MagicMock()
        mock_context = MagicMock()
        mock_builder.build.return_value = mock_context
        mock_builder_class.return_value = mock_builder

        # Files with errors
        mock_collect.return_value = (
            [MagicMock()],
            [{'source_path': 'bad.txt', 'error_message': 'Invalid file'}]
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 5


class TestExceptionExitCodeMapping:
    """Tests for exception exit code mapping."""

    @pytest.mark.timeout(60)
    def test_exception_exit_code_map_structure(self):
        """Test EXCEPTION_EXIT_CODE_MAP has expected structure."""
        assert isinstance(EXCEPTION_EXIT_CODE_MAP, dict)
        assert FileNotFoundError in EXCEPTION_EXIT_CODE_MAP
        assert PermissionError in EXCEPTION_EXIT_CODE_MAP
        assert ValueError in EXCEPTION_EXIT_CODE_MAP
        assert ConnectionError in EXCEPTION_EXIT_CODE_MAP
        assert TimeoutError in EXCEPTION_EXIT_CODE_MAP

    @pytest.mark.timeout(60)
    def test_exception_exit_codes_are_integers(self):
        """Test all exit codes are integers."""
        for exc_type, exit_code in EXCEPTION_EXIT_CODE_MAP.items():
            assert isinstance(exit_code, int)
            assert exit_code > 0

    @pytest.mark.timeout(60)
    def test_file_not_found_exit_code(self):
        """Test FileNotFoundError maps to exit code 5."""
        assert EXCEPTION_EXIT_CODE_MAP[FileNotFoundError] == 5

    @pytest.mark.timeout(60)
    def test_permission_error_exit_code(self):
        """Test PermissionError maps to exit code 5."""
        assert EXCEPTION_EXIT_CODE_MAP[PermissionError] == 5

    @pytest.mark.timeout(60)
    def test_value_error_exit_code(self):
        """Test ValueError maps to exit code 3."""
        assert EXCEPTION_EXIT_CODE_MAP[ValueError] == 3

    @pytest.mark.timeout(60)
    def test_connection_error_exit_code(self):
        """Test ConnectionError maps to exit code 6."""
        assert EXCEPTION_EXIT_CODE_MAP[ConnectionError] == 6

    @pytest.mark.timeout(60)
    def test_timeout_error_exit_code(self):
        """Test TimeoutError maps to exit code 6."""
        assert EXCEPTION_EXIT_CODE_MAP[TimeoutError] == 6


class TestEdgeCases:
    """Tests for edge cases and error scenarios."""

    @pytest.mark.timeout(60)
    def test_git_auto_detector_with_empty_remotes(self, mock_git_repo):
        """Test GitAutoDetector with repository that has no remotes."""
        mock_git_repo.remotes = []

        detector = GitAutoDetector()
        with pytest.raises(ProjectResolutionError) as exc_info:
            detector.get_gitlab_remotes(mock_git_repo)
        assert "No Git remotes configured" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_project_resolver_with_nested_subgroups(self, mock_gitlab_client):
        """Test ProjectResolver with deeply nested subgroups."""
        mock_project = MagicMock()
        mock_project.id = 12345
        mock_gitlab_client.projects.get.return_value = mock_project

        resolver = ProjectResolver(mock_gitlab_client)
        project_id = resolver.resolve_project_id(
            "https://gitlab.com",
            "group/subgroup1/subgroup2/project"
        )

        assert project_id == 12345

    @pytest.mark.timeout(60)
    def test_git_auto_detector_multiple_urls_per_remote(self, mock_git_repo):
        """Test GitAutoDetector handles multiple URLs per remote."""
        mock_remote = MagicMock()
        mock_remote.name = "origin"
        # Multiple URLs - should use first valid one
        mock_remote.urls = iter([
            "git@gitlab.com:group/project.git",
            "https://gitlab.com/group/project.git"
        ])
        mock_git_repo.remotes = [mock_remote]

        detector = GitAutoDetector()
        with patch.object(detector, 'parse_git_url', return_value=("https://gitlab.com", "group/project")):
            remotes = detector.get_gitlab_remotes(mock_git_repo)

        # Should only have one remote info (uses first valid URL)
        assert len(remotes) == 1

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.normalize_gitlab_url')
    def test_project_resolver_deeply_nested_namespace(self, mock_normalize, mock_gitlab_client):
        """Test parsing URL with deeply nested namespace."""
        mock_normalize.return_value = (
            "https://gitlab.com",
            "org/team/sub1/sub2/project"
        )

        resolver = ProjectResolver(mock_gitlab_client)
        result = resolver.parse_project_url(
            "https://gitlab.com/org/team/sub1/sub2/project"
        )

        assert result.namespace == "org/team/sub1/sub2"
        assert result.project_name == "project"

    @pytest.mark.timeout(60)
    def test_validate_flags_multiple_errors_all_reported(self, mock_args, capsys):
        """Test that multiple validation errors are all reported."""
        mock_args.package_name = None
        mock_args.package_version = None
        mock_args.files = None
        mock_args.directory = None

        with pytest.raises(SystemExit) as exc_info:
            validate_flags(mock_args)

        assert exc_info.value.code == 3
        captured = capsys.readouterr()
        # Should report all errors
        assert "--package-name" in captured.err
        assert "--package-version" in captured.err

    @pytest.mark.timeout(60)
    def test_determine_verbosity_only_debug(self, mock_args):
        """Test verbosity with only debug flag set."""
        mock_args.debug = True
        mock_args.verbose = False
        mock_args.quiet = False
        assert determine_verbosity(mock_args) == "debug"

    @pytest.mark.timeout(60)
    def test_determine_verbosity_only_verbose(self, mock_args):
        """Test verbosity with only verbose flag set."""
        mock_args.debug = False
        mock_args.verbose = True
        mock_args.quiet = False
        assert determine_verbosity(mock_args) == "verbose"

    @pytest.mark.timeout(60)
    def test_determine_verbosity_only_quiet(self, mock_args):
        """Test verbosity with only quiet flag set."""
        mock_args.debug = False
        mock_args.verbose = False
        mock_args.quiet = True
        assert determine_verbosity(mock_args) == "quiet"

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.DuplicateDetector')
    def test_build_context_with_json_output(self, mock_detector_class, mock_args, mock_gitlab_client):
        """Test context building with JSON output enabled."""
        mock_detector = MagicMock()
        mock_detector_class.return_value = mock_detector
        mock_args.json_output = True
        mock_args.duplicate_policy = DuplicatePolicy.SKIP

        builder = UploadContextBuilder()
        context = builder.build(
            args=mock_args,
            gl=mock_gitlab_client,
            project_id=12345,
            project_path="group/project",
            gitlab_url="https://gitlab.com",
            token="test-token"
        )

        assert context.config.json_output is True

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.DuplicateDetector')
    def test_build_context_with_plain_output(self, mock_detector_class, mock_args, mock_gitlab_client):
        """Test context building with plain output enabled."""
        mock_detector = MagicMock()
        mock_detector_class.return_value = mock_detector
        mock_args.plain = True
        mock_args.duplicate_policy = DuplicatePolicy.SKIP

        builder = UploadContextBuilder()
        context = builder.build(
            args=mock_args,
            gl=mock_gitlab_client,
            project_id=12345,
            project_path="group/project",
            gitlab_url="https://gitlab.com",
            token="test-token"
        )

        assert context.config.plain_output is True

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.DuplicateDetector')
    def test_build_context_with_fail_fast(self, mock_detector_class, mock_args, mock_gitlab_client):
        """Test context building with fail_fast enabled."""
        mock_detector = MagicMock()
        mock_detector_class.return_value = mock_detector
        mock_args.fail_fast = True
        mock_args.duplicate_policy = DuplicatePolicy.SKIP

        builder = UploadContextBuilder()
        context = builder.build(
            args=mock_args,
            gl=mock_gitlab_client,
            project_id=12345,
            project_path="group/project",
            gitlab_url="https://gitlab.com",
            token="test-token"
        )

        assert context.config.fail_fast is True

    @pytest.mark.timeout(60)
    @patch('gitlab_pkg_upload.cli.DuplicateDetector')
    def test_build_context_with_retry_count(self, mock_detector_class, mock_args, mock_gitlab_client):
        """Test context building with custom retry count."""
        mock_detector = MagicMock()
        mock_detector_class.return_value = mock_detector
        mock_args.retry = 5
        mock_args.duplicate_policy = DuplicatePolicy.SKIP

        builder = UploadContextBuilder()
        context = builder.build(
            args=mock_args,
            gl=mock_gitlab_client,
            project_id=12345,
            project_path="group/project",
            gitlab_url="https://gitlab.com",
            token="test-token"
        )

        assert context.config.retry_count == 5
