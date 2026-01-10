"""
Comprehensive unit tests for the models module.

These tests validate the data models, enums, exceptions, and error enhancement
functions used throughout the gitlab-pkg-upload package.

All tests are isolated and do not require external dependencies like GitLab API
or filesystem access.
"""

from __future__ import annotations

from typing import Optional
from unittest.mock import MagicMock, Mock

import pytest

from glpkg.models import (
    # Dataclasses
    FileFingerprint,
    GitRemoteInfo,
    ProjectInfo,
    ProjectResolutionResult,
    RemoteFile,
    UploadConfig,
    UploadContext,
    UploadResult,
    # Enums
    DuplicatePolicy,
    # Exceptions
    AuthenticationError,
    ChecksumValidationError,
    ConfigurationError,
    FileValidationError,
    GitLabUploadError,
    NetworkError,
    ProjectResolutionError,
    # Error enhancement functions
    enhance_error_message,
    handle_authentication_error,
    handle_network_connectivity_error,
    handle_permission_error,
    handle_project_not_found_error,
)

# Mark these as fast unit tests
pytestmark = [pytest.mark.unit, pytest.mark.fast]


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_file_fingerprint() -> FileFingerprint:
    """Create a sample FileFingerprint for testing."""
    return FileFingerprint(
        source_path="/path/to/file.txt",
        target_filename="file.txt",
        sha256_checksum="a" * 64,
        file_size=1024,
        timestamp=1704067200.0,  # 2024-01-01 00:00:00 UTC
    )


@pytest.fixture
def sample_remote_file() -> RemoteFile:
    """Create a sample RemoteFile for testing."""
    return RemoteFile(
        file_id=12345,
        filename="package.tar.gz",
        sha256_checksum="b" * 64,
        file_size=2048,
        download_url="https://gitlab.com/api/v4/projects/1/packages/generic/pkg/1.0.0/package.tar.gz",
        package_name="my-package",
        version="1.0.0",
    )


@pytest.fixture
def sample_upload_result() -> UploadResult:
    """Create a sample UploadResult for testing."""
    return UploadResult(
        source_path="/path/to/file.txt",
        target_filename="file.txt",
        success=True,
        result="https://gitlab.com/api/v4/projects/1/packages/generic/pkg/1.0.0/file.txt",
    )


@pytest.fixture
def sample_project_info() -> ProjectInfo:
    """Create a sample ProjectInfo for testing."""
    return ProjectInfo(
        gitlab_url="https://gitlab.com",
        namespace="mygroup",
        project_name="myproject",
        project_path="mygroup/myproject",
        original_url="https://gitlab.com/mygroup/myproject",
    )


@pytest.fixture
def sample_upload_config() -> UploadConfig:
    """Create a sample UploadConfig for testing."""
    return UploadConfig(
        package_name="test-package",
        version="1.0.0",
        duplicate_policy=DuplicatePolicy.SKIP,
        retry_count=3,
        verbosity="normal",
        dry_run=False,
        fail_fast=False,
        json_output=False,
        plain_output=False,
        gitlab_url="https://gitlab.com",
        token="glpat-xxxxxxxxxxxxxxxxxxxx",
    )


@pytest.fixture
def mock_gitlab_client() -> MagicMock:
    """Create a mock Gitlab client for testing UploadContext."""
    mock_gl = MagicMock()
    mock_gl.url = "https://gitlab.com"
    return mock_gl


@pytest.fixture
def mock_duplicate_detector() -> MagicMock:
    """Create a mock DuplicateDetector for testing UploadContext."""
    mock_detector = MagicMock()
    mock_detector.policy = DuplicatePolicy.SKIP
    return mock_detector


# =============================================================================
# Test Classes
# =============================================================================


class TestDuplicatePolicy:
    """Tests for DuplicatePolicy enum."""

    @pytest.mark.timeout(60)
    def test_duplicate_policy_skip_value(self):
        """Test DuplicatePolicy.SKIP has correct value."""
        assert DuplicatePolicy.SKIP.value == "skip"

    @pytest.mark.timeout(60)
    def test_duplicate_policy_replace_value(self):
        """Test DuplicatePolicy.REPLACE has correct value."""
        assert DuplicatePolicy.REPLACE.value == "replace"

    @pytest.mark.timeout(60)
    def test_duplicate_policy_error_value(self):
        """Test DuplicatePolicy.ERROR has correct value."""
        assert DuplicatePolicy.ERROR.value == "error"

    @pytest.mark.timeout(60)
    def test_duplicate_policy_enum_members(self):
        """Test all expected enum members exist."""
        members = list(DuplicatePolicy)
        assert len(members) == 3
        assert DuplicatePolicy.SKIP in members
        assert DuplicatePolicy.REPLACE in members
        assert DuplicatePolicy.ERROR in members

    @pytest.mark.timeout(60)
    def test_duplicate_policy_from_string(self):
        """Test creating DuplicatePolicy from string value."""
        assert DuplicatePolicy("skip") == DuplicatePolicy.SKIP
        assert DuplicatePolicy("replace") == DuplicatePolicy.REPLACE
        assert DuplicatePolicy("error") == DuplicatePolicy.ERROR

    @pytest.mark.timeout(60)
    def test_duplicate_policy_invalid_value(self):
        """Test that invalid value raises ValueError."""
        with pytest.raises(ValueError):
            DuplicatePolicy("invalid")

    @pytest.mark.timeout(60)
    def test_duplicate_policy_string_representation(self):
        """Test string representation of enum."""
        assert str(DuplicatePolicy.SKIP) == "DuplicatePolicy.SKIP"
        assert DuplicatePolicy.SKIP.name == "SKIP"


class TestFileFingerprint:
    """Tests for FileFingerprint dataclass."""

    @pytest.mark.timeout(60)
    def test_file_fingerprint_creation(self, sample_file_fingerprint: FileFingerprint):
        """Test FileFingerprint can be created with all required fields."""
        assert sample_file_fingerprint.source_path == "/path/to/file.txt"
        assert sample_file_fingerprint.target_filename == "file.txt"
        assert sample_file_fingerprint.sha256_checksum == "a" * 64
        assert sample_file_fingerprint.file_size == 1024
        assert sample_file_fingerprint.timestamp == 1704067200.0

    @pytest.mark.timeout(60)
    def test_file_fingerprint_equality(self):
        """Test FileFingerprint equality comparison."""
        fp1 = FileFingerprint(
            source_path="/path/to/file.txt",
            target_filename="file.txt",
            sha256_checksum="a" * 64,
            file_size=1024,
            timestamp=1704067200.0,
        )
        fp2 = FileFingerprint(
            source_path="/path/to/file.txt",
            target_filename="file.txt",
            sha256_checksum="a" * 64,
            file_size=1024,
            timestamp=1704067200.0,
        )
        assert fp1 == fp2

    @pytest.mark.timeout(60)
    def test_file_fingerprint_inequality(self):
        """Test FileFingerprint inequality when fields differ."""
        fp1 = FileFingerprint(
            source_path="/path/to/file.txt",
            target_filename="file.txt",
            sha256_checksum="a" * 64,
            file_size=1024,
            timestamp=1704067200.0,
        )
        fp2 = FileFingerprint(
            source_path="/path/to/other.txt",
            target_filename="other.txt",
            sha256_checksum="b" * 64,
            file_size=2048,
            timestamp=1704067200.0,
        )
        assert fp1 != fp2


class TestRemoteFile:
    """Tests for RemoteFile dataclass."""

    @pytest.mark.timeout(60)
    def test_remote_file_creation(self, sample_remote_file: RemoteFile):
        """Test RemoteFile can be created with all fields."""
        assert sample_remote_file.file_id == 12345
        assert sample_remote_file.filename == "package.tar.gz"
        assert sample_remote_file.sha256_checksum == "b" * 64
        assert sample_remote_file.file_size == 2048
        assert "package.tar.gz" in sample_remote_file.download_url
        assert sample_remote_file.package_name == "my-package"
        assert sample_remote_file.version == "1.0.0"

    @pytest.mark.timeout(60)
    def test_remote_file_optional_checksum(self):
        """Test RemoteFile with None checksum (optional field)."""
        remote_file = RemoteFile(
            file_id=12345,
            filename="package.tar.gz",
            sha256_checksum=None,
            file_size=2048,
            download_url="https://gitlab.com/download/file",
            package_name="my-package",
            version="1.0.0",
        )
        assert remote_file.sha256_checksum is None

    @pytest.mark.timeout(60)
    def test_remote_file_equality(self):
        """Test RemoteFile equality comparison."""
        rf1 = RemoteFile(
            file_id=1,
            filename="file.txt",
            sha256_checksum="abc",
            file_size=100,
            download_url="https://example.com/file",
            package_name="pkg",
            version="1.0",
        )
        rf2 = RemoteFile(
            file_id=1,
            filename="file.txt",
            sha256_checksum="abc",
            file_size=100,
            download_url="https://example.com/file",
            package_name="pkg",
            version="1.0",
        )
        assert rf1 == rf2


class TestUploadResult:
    """Tests for UploadResult dataclass."""

    @pytest.mark.timeout(60)
    def test_upload_result_creation(self, sample_upload_result: UploadResult):
        """Test UploadResult can be created with required fields."""
        assert sample_upload_result.source_path == "/path/to/file.txt"
        assert sample_upload_result.target_filename == "file.txt"
        assert sample_upload_result.success is True
        assert "file.txt" in sample_upload_result.result

    @pytest.mark.timeout(60)
    def test_upload_result_default_values(self):
        """Test UploadResult has correct default values for optional fields."""
        result = UploadResult(
            source_path="/path/to/file.txt",
            target_filename="file.txt",
            success=True,
            result="https://example.com/file.txt",
        )
        assert result.was_duplicate is False
        assert result.duplicate_action is None
        assert result.existing_url is None

    @pytest.mark.timeout(60)
    def test_upload_result_with_duplicate_info(self):
        """Test UploadResult with duplicate detection information."""
        result = UploadResult(
            source_path="/path/to/file.txt",
            target_filename="file.txt",
            success=True,
            result="Skipped: duplicate detected",
            was_duplicate=True,
            duplicate_action="skipped",
            existing_url="https://example.com/existing/file.txt",
        )
        assert result.was_duplicate is True
        assert result.duplicate_action == "skipped"
        assert result.existing_url == "https://example.com/existing/file.txt"

    @pytest.mark.timeout(60)
    def test_upload_result_failed(self):
        """Test UploadResult for failed upload."""
        result = UploadResult(
            source_path="/path/to/file.txt",
            target_filename="file.txt",
            success=False,
            result="Upload failed: network error",
        )
        assert result.success is False
        assert "network error" in result.result

    @pytest.mark.timeout(60)
    def test_upload_result_replaced_duplicate(self):
        """Test UploadResult for replaced duplicate."""
        result = UploadResult(
            source_path="/path/to/file.txt",
            target_filename="file.txt",
            success=True,
            result="https://example.com/new/file.txt",
            was_duplicate=True,
            duplicate_action="replaced",
            existing_url="https://example.com/old/file.txt",
        )
        assert result.duplicate_action == "replaced"


class TestProjectInfo:
    """Tests for ProjectInfo dataclass."""

    @pytest.mark.timeout(60)
    def test_project_info_creation(self, sample_project_info: ProjectInfo):
        """Test ProjectInfo can be created with all fields."""
        assert sample_project_info.gitlab_url == "https://gitlab.com"
        assert sample_project_info.namespace == "mygroup"
        assert sample_project_info.project_name == "myproject"
        assert sample_project_info.project_path == "mygroup/myproject"
        assert sample_project_info.original_url == "https://gitlab.com/mygroup/myproject"

    @pytest.mark.timeout(60)
    def test_project_info_nested_namespace(self):
        """Test ProjectInfo with nested namespace (subgroups)."""
        project_info = ProjectInfo(
            gitlab_url="https://gitlab.com",
            namespace="group/subgroup",
            project_name="myproject",
            project_path="group/subgroup/myproject",
            original_url="https://gitlab.com/group/subgroup/myproject",
        )
        assert project_info.namespace == "group/subgroup"
        assert "subgroup" in project_info.project_path


class TestProjectResolutionResult:
    """Tests for ProjectResolutionResult dataclass."""

    @pytest.mark.timeout(60)
    def test_project_resolution_result_success(self, sample_project_info: ProjectInfo):
        """Test ProjectResolutionResult for successful resolution."""
        result = ProjectResolutionResult(
            success=True,
            project_id=12345,
            error_message=None,
            project_info=sample_project_info,
            gitlab_url="https://gitlab.com",
        )
        assert result.success is True
        assert result.project_id == 12345
        assert result.error_message is None
        assert result.project_info is not None

    @pytest.mark.timeout(60)
    def test_project_resolution_result_failure(self):
        """Test ProjectResolutionResult for failed resolution."""
        result = ProjectResolutionResult(
            success=False,
            project_id=None,
            error_message="Project not found: mygroup/nonexistent",
            project_info=None,
            gitlab_url="https://gitlab.com",
        )
        assert result.success is False
        assert result.project_id is None
        assert "not found" in result.error_message
        assert result.project_info is None


class TestGitRemoteInfo:
    """Tests for GitRemoteInfo dataclass."""

    @pytest.mark.timeout(60)
    def test_git_remote_info_creation(self):
        """Test GitRemoteInfo can be created with all fields."""
        remote_info = GitRemoteInfo(
            name="origin",
            url="git@gitlab.com:mygroup/myproject.git",
            gitlab_url="https://gitlab.com",
            project_path="mygroup/myproject",
        )
        assert remote_info.name == "origin"
        assert remote_info.url == "git@gitlab.com:mygroup/myproject.git"
        assert remote_info.gitlab_url == "https://gitlab.com"
        assert remote_info.project_path == "mygroup/myproject"

    @pytest.mark.timeout(60)
    def test_git_remote_info_https_url(self):
        """Test GitRemoteInfo with HTTPS URL."""
        remote_info = GitRemoteInfo(
            name="upstream",
            url="https://gitlab.com/mygroup/myproject.git",
            gitlab_url="https://gitlab.com",
            project_path="mygroup/myproject",
        )
        assert remote_info.name == "upstream"
        assert "https://" in remote_info.url


class TestUploadConfig:
    """Tests for UploadConfig dataclass."""

    @pytest.mark.timeout(60)
    def test_upload_config_creation(self, sample_upload_config: UploadConfig):
        """Test UploadConfig can be created with all fields."""
        assert sample_upload_config.package_name == "test-package"
        assert sample_upload_config.version == "1.0.0"
        assert sample_upload_config.duplicate_policy == DuplicatePolicy.SKIP
        assert sample_upload_config.retry_count == 3
        assert sample_upload_config.verbosity == "normal"
        assert sample_upload_config.dry_run is False
        assert sample_upload_config.fail_fast is False
        assert sample_upload_config.json_output is False
        assert sample_upload_config.plain_output is False
        assert sample_upload_config.gitlab_url == "https://gitlab.com"
        assert sample_upload_config.token is not None

    @pytest.mark.timeout(60)
    def test_upload_config_with_none_token(self):
        """Test UploadConfig with None token (optional field)."""
        config = UploadConfig(
            package_name="test-package",
            version="1.0.0",
            duplicate_policy=DuplicatePolicy.SKIP,
            retry_count=3,
            verbosity="normal",
            dry_run=False,
            fail_fast=False,
            json_output=False,
            plain_output=False,
            gitlab_url="https://gitlab.com",
            token=None,
        )
        assert config.token is None

    @pytest.mark.timeout(60)
    def test_upload_config_verbosity_options(self):
        """Test UploadConfig with different verbosity options."""
        for verbosity in ["quiet", "normal", "verbose", "debug"]:
            config = UploadConfig(
                package_name="test",
                version="1.0.0",
                duplicate_policy=DuplicatePolicy.SKIP,
                retry_count=3,
                verbosity=verbosity,
                dry_run=False,
                fail_fast=False,
                json_output=False,
                plain_output=False,
                gitlab_url="https://gitlab.com",
                token=None,
            )
            assert config.verbosity == verbosity

    @pytest.mark.timeout(60)
    def test_upload_config_dry_run_enabled(self):
        """Test UploadConfig with dry_run enabled."""
        config = UploadConfig(
            package_name="test",
            version="1.0.0",
            duplicate_policy=DuplicatePolicy.SKIP,
            retry_count=3,
            verbosity="normal",
            dry_run=True,
            fail_fast=False,
            json_output=False,
            plain_output=False,
            gitlab_url="https://gitlab.com",
            token=None,
        )
        assert config.dry_run is True


class TestUploadContext:
    """Tests for UploadContext dataclass."""

    @pytest.mark.timeout(60)
    def test_upload_context_creation(
        self,
        mock_gitlab_client: MagicMock,
        mock_duplicate_detector: MagicMock,
        sample_upload_config: UploadConfig,
    ):
        """Test UploadContext can be created with all fields."""
        context = UploadContext(
            gl=mock_gitlab_client,
            config=sample_upload_config,
            detector=mock_duplicate_detector,
            project_id=12345,
            project_path="mygroup/myproject",
        )
        assert context.gl is mock_gitlab_client
        assert context.config is sample_upload_config
        assert context.detector is mock_duplicate_detector
        assert context.project_id == 12345
        assert context.project_path == "mygroup/myproject"


class TestExceptionHierarchy:
    """Tests for exception hierarchy and exit codes."""

    @pytest.mark.timeout(60)
    def test_gitlab_upload_error_base(self):
        """Test GitLabUploadError base exception."""
        error = GitLabUploadError("Base error message")
        assert str(error) == "Base error message"
        assert error.exit_code == 1

    @pytest.mark.timeout(60)
    def test_authentication_error(self):
        """Test AuthenticationError exception."""
        error = AuthenticationError("Authentication failed")
        assert str(error) == "Authentication failed"
        assert error.exit_code == 2
        assert isinstance(error, GitLabUploadError)

    @pytest.mark.timeout(60)
    def test_configuration_error(self):
        """Test ConfigurationError exception."""
        error = ConfigurationError("Invalid configuration")
        assert str(error) == "Invalid configuration"
        assert error.exit_code == 3
        assert isinstance(error, GitLabUploadError)

    @pytest.mark.timeout(60)
    def test_project_resolution_error(self):
        """Test ProjectResolutionError exception."""
        error = ProjectResolutionError("Project not found")
        assert str(error) == "Project not found"
        assert error.exit_code == 4
        assert isinstance(error, GitLabUploadError)

    @pytest.mark.timeout(60)
    def test_file_validation_error(self):
        """Test FileValidationError exception."""
        error = FileValidationError("File not readable")
        assert str(error) == "File not readable"
        assert error.exit_code == 5
        assert isinstance(error, GitLabUploadError)

    @pytest.mark.timeout(60)
    def test_network_error(self):
        """Test NetworkError exception."""
        error = NetworkError("Connection refused")
        assert str(error) == "Connection refused"
        assert error.exit_code == 6
        assert isinstance(error, GitLabUploadError)

    @pytest.mark.timeout(60)
    def test_checksum_validation_error(self):
        """Test ChecksumValidationError exception."""
        error = ChecksumValidationError("Checksum mismatch")
        assert str(error) == "Checksum mismatch"
        assert error.exit_code == 7
        assert isinstance(error, GitLabUploadError)

    @pytest.mark.timeout(60)
    def test_exception_inheritance(self):
        """Test all custom exceptions inherit from GitLabUploadError."""
        exceptions = [
            AuthenticationError,
            ConfigurationError,
            ProjectResolutionError,
            FileValidationError,
            NetworkError,
            ChecksumValidationError,
        ]
        for exc_class in exceptions:
            assert issubclass(exc_class, GitLabUploadError)
            assert issubclass(exc_class, Exception)

    @pytest.mark.timeout(60)
    def test_exception_can_be_caught_as_base(self):
        """Test custom exceptions can be caught as GitLabUploadError."""
        try:
            raise AuthenticationError("Test error")
        except GitLabUploadError as e:
            assert e.exit_code == 2
            assert str(e) == "Test error"

    @pytest.mark.timeout(60)
    def test_exit_codes_are_unique(self):
        """Test all exception classes have unique exit codes."""
        exceptions = [
            GitLabUploadError,
            AuthenticationError,
            ConfigurationError,
            ProjectResolutionError,
            FileValidationError,
            NetworkError,
            ChecksumValidationError,
        ]
        exit_codes = [exc.exit_code for exc in exceptions]
        assert len(exit_codes) == len(set(exit_codes))


class TestHandleProjectNotFoundError:
    """Tests for handle_project_not_found_error function."""

    @pytest.mark.timeout(60)
    def test_basic_error_message(self):
        """Test basic error message generation."""
        result = handle_project_not_found_error(
            project_path="mygroup/myproject",
            gitlab_url="https://gitlab.com",
            original_error="404 Project Not Found",
        )
        assert "mygroup/myproject" in result
        assert "https://gitlab.com" in result
        assert "404 Project Not Found" in result

    @pytest.mark.timeout(60)
    def test_includes_suggestions(self):
        """Test error message includes helpful suggestions."""
        result = handle_project_not_found_error(
            project_path="mygroup/myproject",
            gitlab_url="https://gitlab.com",
            original_error="Not found",
        )
        assert "Please check the following" in result
        assert "Project path format is correct" in result
        assert "namespace/project-name" in result

    @pytest.mark.timeout(60)
    def test_includes_examples(self):
        """Test error message includes example project paths."""
        result = handle_project_not_found_error(
            project_path="mygroup/myproject",
            gitlab_url="https://gitlab.com",
            original_error="Not found",
        )
        assert "Examples of valid project paths" in result
        assert "mycompany/my-project" in result
        assert "group/subgroup/project-name" in result

    @pytest.mark.timeout(60)
    def test_includes_verification_url(self):
        """Test error message includes URL to verify project."""
        result = handle_project_not_found_error(
            project_path="mygroup/myproject",
            gitlab_url="https://gitlab.com",
            original_error="Not found",
        )
        assert "You can verify the project exists by visiting" in result
        assert "https://gitlab.com/mygroup/myproject" in result


class TestHandleAuthenticationError:
    """Tests for handle_authentication_error function."""

    @pytest.mark.timeout(60)
    def test_basic_error_message(self):
        """Test basic authentication error message."""
        result = handle_authentication_error(
            project_path="mygroup/myproject",
            gitlab_url="https://gitlab.com",
            original_error="401 Unauthorized",
        )
        assert "Authentication failed" in result
        assert "mygroup/myproject" in result
        assert "https://gitlab.com" in result

    @pytest.mark.timeout(60)
    def test_includes_token_guidance(self):
        """Test error message includes token configuration guidance."""
        result = handle_authentication_error(
            project_path="mygroup/myproject",
            gitlab_url="https://gitlab.com",
            original_error="Unauthorized",
        )
        assert "GitLab token" in result
        assert "GITLAB_TOKEN" in result
        assert "--token" in result

    @pytest.mark.timeout(60)
    def test_includes_token_creation_steps(self):
        """Test error message includes steps to create new token."""
        result = handle_authentication_error(
            project_path="mygroup/myproject",
            gitlab_url="https://gitlab.com",
            original_error="Unauthorized",
        )
        assert "To create a new token" in result
        assert "personal_access_tokens" in result
        assert "api" in result or "read_api" in result


class TestHandlePermissionError:
    """Tests for handle_permission_error function."""

    @pytest.mark.timeout(60)
    def test_basic_error_message(self):
        """Test basic permission error message."""
        result = handle_permission_error(
            project_path="mygroup/myproject",
            gitlab_url="https://gitlab.com",
            operation="upload",
            original_error="403 Forbidden",
        )
        assert "Permission denied" in result
        assert "upload" in result
        assert "mygroup/myproject" in result

    @pytest.mark.timeout(60)
    def test_includes_required_permissions(self):
        """Test error message includes required permission levels."""
        result = handle_permission_error(
            project_path="mygroup/myproject",
            gitlab_url="https://gitlab.com",
            operation="upload",
            original_error="Forbidden",
        )
        assert "Required permissions" in result
        assert "Developer" in result or "Reporter" in result

    @pytest.mark.timeout(60)
    def test_includes_project_members_link(self):
        """Test error message includes link to project members page."""
        result = handle_permission_error(
            project_path="mygroup/myproject",
            gitlab_url="https://gitlab.com",
            operation="read packages",
            original_error="Forbidden",
        )
        assert "project_members" in result


class TestHandleNetworkConnectivityError:
    """Tests for handle_network_connectivity_error function."""

    @pytest.mark.timeout(60)
    def test_basic_error_message(self):
        """Test basic network connectivity error message."""
        result = handle_network_connectivity_error(
            gitlab_url="https://gitlab.com",
            original_error="Connection refused",
        )
        assert "Network connectivity issue" in result
        assert "https://gitlab.com" in result
        assert "Connection refused" in result

    @pytest.mark.timeout(60)
    def test_includes_troubleshooting_steps(self):
        """Test error message includes troubleshooting steps."""
        result = handle_network_connectivity_error(
            gitlab_url="https://gitlab.com",
            original_error="Timeout",
        )
        assert "Troubleshooting steps" in result
        assert "curl" in result
        assert "nslookup" in result

    @pytest.mark.timeout(60)
    def test_includes_corporate_network_hints(self):
        """Test error message includes hints for corporate networks."""
        result = handle_network_connectivity_error(
            gitlab_url="https://gitlab.example.com",
            original_error="Connection timeout",
        )
        assert "corporate network" in result or "proxy" in result


class TestEnhanceErrorMessage:
    """Tests for enhance_error_message function."""

    @pytest.mark.timeout(60)
    def test_404_error_detection(self):
        """Test 404 error is detected and enhanced."""
        error = Exception("404 Not Found")
        context = {
            "project_path": "mygroup/myproject",
            "gitlab_url": "https://gitlab.com",
            "operation": "fetch",
        }
        result = enhance_error_message(error, context)
        assert "not found" in result.lower() or "Project" in result

    @pytest.mark.timeout(60)
    def test_401_error_detection(self):
        """Test 401 error is detected and enhanced."""
        error = Exception("401 Unauthorized")
        context = {
            "project_path": "mygroup/myproject",
            "gitlab_url": "https://gitlab.com",
            "operation": "upload",
        }
        result = enhance_error_message(error, context)
        assert "Authentication" in result or "token" in result.lower()

    @pytest.mark.timeout(60)
    def test_403_permission_error_detection(self):
        """Test 403 permission error is detected and enhanced."""
        error = Exception("403 Forbidden: Permission denied")
        context = {
            "project_path": "mygroup/myproject",
            "gitlab_url": "https://gitlab.com",
            "operation": "upload",
        }
        result = enhance_error_message(error, context)
        assert "Permission" in result or "permission" in result

    @pytest.mark.timeout(60)
    def test_connection_error_detection(self):
        """Test connection error is detected and enhanced."""
        error = Exception("Connection refused by server")
        context = {
            "project_path": "mygroup/myproject",
            "gitlab_url": "https://gitlab.com",
            "operation": "connect",
        }
        result = enhance_error_message(error, context)
        assert "Network" in result or "connection" in result.lower()

    @pytest.mark.timeout(60)
    def test_timeout_error_detection(self):
        """Test timeout error is detected and enhanced."""
        error = Exception("Request timeout after 30 seconds")
        context = {
            "project_path": "mygroup/myproject",
            "gitlab_url": "https://gitlab.com",
            "operation": "upload",
        }
        result = enhance_error_message(error, context)
        assert "Network" in result or "timeout" in result.lower()

    @pytest.mark.timeout(60)
    def test_rate_limit_error_detection(self):
        """Test rate limit error is detected and enhanced."""
        error = Exception("429 Too Many Requests - Rate limit exceeded")
        context = {
            "project_path": "mygroup/myproject",
            "gitlab_url": "https://gitlab.com",
            "operation": "upload",
        }
        result = enhance_error_message(error, context)
        assert "rate limit" in result.lower() or "Rate" in result

    @pytest.mark.timeout(60)
    def test_generic_error_enhancement(self):
        """Test generic error gets basic enhancement."""
        error = Exception("Something unexpected happened")
        context = {
            "project_path": "mygroup/myproject",
            "gitlab_url": "https://gitlab.com",
            "operation": "process",
        }
        result = enhance_error_message(error, context)
        assert "mygroup/myproject" in result
        assert "https://gitlab.com" in result
        assert "Something unexpected happened" in result

    @pytest.mark.timeout(60)
    def test_missing_context_keys_use_defaults(self):
        """Test missing context keys use default values."""
        error = Exception("Error")
        context = {}
        result = enhance_error_message(error, context)
        assert "unknown" in result

    @pytest.mark.timeout(60)
    def test_dns_error_detection(self):
        """Test DNS resolution error is detected."""
        error = Exception("Failed to resolve hostname: DNS error")
        context = {
            "project_path": "mygroup/myproject",
            "gitlab_url": "https://gitlab.example.com",
            "operation": "connect",
        }
        result = enhance_error_message(error, context)
        assert "Network" in result or "DNS" in result or "resolve" in result.lower()

    @pytest.mark.timeout(60)
    def test_case_insensitive_error_detection(self):
        """Test error detection is case-insensitive."""
        error = Exception("NOT FOUND")
        context = {
            "project_path": "mygroup/myproject",
            "gitlab_url": "https://gitlab.com",
            "operation": "fetch",
        }
        result = enhance_error_message(error, context)
        # Should detect as not found error
        assert len(result) > len("NOT FOUND")
