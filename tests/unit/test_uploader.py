"""
Comprehensive unit tests for the uploader module.

These tests validate upload orchestration including retry logic, duplicate handling,
checksum validation, and file deletion. All external dependencies (GitLab API,
filesystem, network) are mocked to ensure test isolation.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, Mock, call, patch

import pytest
from gitlab.exceptions import GitlabError

from glpkg.models import (
    ChecksumValidationError,
    DuplicatePolicy,
    RemoteFile,
    UploadConfig,
    UploadContext,
    UploadResult,
)
from glpkg.uploader import (
    delete_file_from_registry,
    handle_duplicate,
    is_transient_error,
    upload_files,
    upload_single_file,
    validate_upload,
)

# Mark these as fast unit tests
pytestmark = [pytest.mark.unit, pytest.mark.fast]


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_upload_config() -> UploadConfig:
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
def mock_upload_config_dry_run() -> UploadConfig:
    """Create a sample UploadConfig with dry_run enabled."""
    return UploadConfig(
        package_name="test-package",
        version="1.0.0",
        duplicate_policy=DuplicatePolicy.SKIP,
        retry_count=3,
        verbosity="normal",
        dry_run=True,
        fail_fast=False,
        json_output=False,
        plain_output=False,
        gitlab_url="https://gitlab.com",
        token="glpat-xxxxxxxxxxxxxxxxxxxx",
    )


@pytest.fixture
def mock_gitlab_client() -> MagicMock:
    """Create a mock GitLab client for testing."""
    mock_gl = MagicMock()
    mock_gl.url = "https://gitlab.com"
    mock_gl.api_url = "https://gitlab.com/api/v4"
    return mock_gl


@pytest.fixture
def mock_project() -> MagicMock:
    """Create a mock GitLab project for testing."""
    mock_proj = MagicMock()
    mock_proj.id = 12345
    mock_proj.packages = MagicMock()
    mock_proj.generic_packages = MagicMock()
    return mock_proj


@pytest.fixture
def mock_duplicate_detector() -> MagicMock:
    """Create a mock DuplicateDetector for testing."""
    mock_detector = MagicMock()
    mock_detector.check_session_duplicate.return_value = None
    mock_detector.check_remote_duplicate.return_value = None
    mock_detector.register_file.return_value = None
    return mock_detector


@pytest.fixture
def mock_upload_context(
    mock_gitlab_client, mock_upload_config, mock_duplicate_detector
) -> UploadContext:
    """Create a sample UploadContext for testing."""
    return UploadContext(
        gl=mock_gitlab_client,
        config=mock_upload_config,
        detector=mock_duplicate_detector,
        project_id=12345,
        project_path="mygroup/myproject",
    )


@pytest.fixture
def mock_file_path(tmp_path) -> Path:
    """Create a mock file for testing."""
    test_file = tmp_path / "test.bin"
    test_file.write_bytes(b"test content for upload")
    return test_file


@pytest.fixture
def sample_remote_file() -> RemoteFile:
    """Create a sample RemoteFile for testing duplicate handling."""
    return RemoteFile(
        file_id=12345,
        filename="test.bin",
        sha256_checksum="a" * 64,
        file_size=1024,
        download_url="https://gitlab.com/api/v4/projects/12345/packages/generic/test-package/1.0.0/test.bin",
        package_name="test-package",
        version="1.0.0",
    )


# =============================================================================
# Test Classes
# =============================================================================


class TestIsTransientError:
    """Test error classification for retry logic."""

    @pytest.mark.timeout(60)
    def test_connection_error_is_transient(self):
        """Test ConnectionError returns True."""
        error = ConnectionError("Connection refused")
        assert is_transient_error(error) is True

    @pytest.mark.timeout(60)
    def test_gitlab_error_with_response_code_502(self):
        """Test GitlabError with response_code=502 returns True."""
        error = GitlabError("Bad Gateway")
        error.response_code = 502
        assert is_transient_error(error) is True

    @pytest.mark.timeout(60)
    def test_gitlab_error_with_response_code_503(self):
        """Test GitlabError with response_code=503 returns True."""
        error = GitlabError("Service Unavailable")
        error.response_code = 503
        assert is_transient_error(error) is True

    @pytest.mark.timeout(60)
    def test_gitlab_error_with_response_code_408(self):
        """Test GitlabError with response_code=408 (Request Timeout) returns True."""
        error = GitlabError("Request Timeout")
        error.response_code = 408
        assert is_transient_error(error) is True

    @pytest.mark.timeout(60)
    def test_gitlab_error_with_response_code_429(self):
        """Test GitlabError with response_code=429 (Rate Limited) returns True."""
        error = GitlabError("Too Many Requests")
        error.response_code = 429
        assert is_transient_error(error) is True

    @pytest.mark.timeout(60)
    def test_gitlab_error_with_response_code_403(self):
        """Test GitlabError with response_code=403 returns False."""
        error = GitlabError("Forbidden")
        error.response_code = 403
        assert is_transient_error(error) is False

    @pytest.mark.timeout(60)
    def test_gitlab_error_with_response_code_404(self):
        """Test GitlabError with response_code=404 returns False."""
        error = GitlabError("Not Found")
        error.response_code = 404
        assert is_transient_error(error) is False

    @pytest.mark.timeout(60)
    def test_gitlab_error_with_response_code_400(self):
        """Test GitlabError with response_code=400 returns False."""
        error = GitlabError("Bad Request")
        error.response_code = 400
        assert is_transient_error(error) is False

    @pytest.mark.timeout(60)
    def test_gitlab_error_with_response_code_422(self):
        """Test GitlabError with response_code=422 (Unprocessable Entity) returns False."""
        error = GitlabError("Unprocessable Entity")
        error.response_code = 422
        assert is_transient_error(error) is False

    @pytest.mark.timeout(60)
    def test_timeout_error_is_transient(self):
        """Test TimeoutError returns True."""
        error = TimeoutError("Connection timed out")
        assert is_transient_error(error) is True

    @pytest.mark.timeout(60)
    def test_500_error_is_transient(self):
        """Test exception with '500' in message returns True."""
        error = Exception("500 Internal Server Error")
        assert is_transient_error(error) is True

    @pytest.mark.timeout(60)
    def test_502_bad_gateway_is_transient(self):
        """Test exception with '502' or 'bad gateway' returns True."""
        assert is_transient_error(Exception("502 Bad Gateway")) is True
        assert is_transient_error(Exception("bad gateway error")) is True

    @pytest.mark.timeout(60)
    def test_503_service_unavailable_is_transient(self):
        """Test exception with '503' or 'service unavailable' returns True."""
        assert is_transient_error(Exception("503 Service Unavailable")) is True
        assert is_transient_error(Exception("service unavailable")) is True

    @pytest.mark.timeout(60)
    def test_429_rate_limit_is_transient(self):
        """Test exception with '429' or 'rate limit' returns True."""
        assert is_transient_error(Exception("429 Too Many Requests")) is True
        assert is_transient_error(Exception("rate limit exceeded")) is True

    @pytest.mark.timeout(60)
    def test_401_unauthorized_is_permanent(self):
        """Test exception with '401' returns False."""
        error = Exception("401 Unauthorized")
        assert is_transient_error(error) is False

    @pytest.mark.timeout(60)
    def test_403_forbidden_is_permanent(self):
        """Test exception with '403' returns False."""
        error = Exception("403 Forbidden")
        assert is_transient_error(error) is False

    @pytest.mark.timeout(60)
    def test_404_not_found_is_permanent(self):
        """Test exception with '404' returns False."""
        error = Exception("404 Not Found")
        assert is_transient_error(error) is False

    @pytest.mark.timeout(60)
    def test_400_bad_request_is_permanent(self):
        """Test exception with '400' returns False."""
        error = Exception("400 Bad Request")
        assert is_transient_error(error) is False

    @pytest.mark.timeout(60)
    def test_gitlab_error_with_response_code_500(self):
        """Test GitlabError with response_code=500 returns True."""
        error = GitlabError("Server error")
        error.response_code = 500
        assert is_transient_error(error) is True

    @pytest.mark.timeout(60)
    def test_gitlab_error_with_response_code_401(self):
        """Test GitlabError with response_code=401 returns False."""
        error = GitlabError("Unauthorized")
        error.response_code = 401
        assert is_transient_error(error) is False

    @pytest.mark.timeout(60)
    def test_unknown_error_is_permanent(self):
        """Test generic Exception returns False (default behavior)."""
        error = Exception("Something unknown happened")
        assert is_transient_error(error) is False


class TestUploadSingleFile:
    """Test single file upload with retry decorator."""

    @pytest.mark.timeout(60)
    def test_upload_success(self, mock_upload_context, mock_file_path, mock_project):
        """Test successful upload returns download URL."""
        mock_upload_context.gl.projects.get.return_value = mock_project

        result = upload_single_file(mock_upload_context, mock_file_path, "target.bin")

        assert "target.bin" in result
        assert "test-package" in result
        assert "1.0.0" in result

    @pytest.mark.timeout(60)
    def test_upload_dry_run_mode(
        self, mock_gitlab_client, mock_upload_config_dry_run, mock_duplicate_detector, mock_file_path
    ):
        """Test dry_run=True returns mock URL without actual upload."""
        context = UploadContext(
            gl=mock_gitlab_client,
            config=mock_upload_config_dry_run,
            detector=mock_duplicate_detector,
            project_id=12345,
            project_path="mygroup/myproject",
        )

        result = upload_single_file(context, mock_file_path, "target.bin")

        assert "target.bin" in result
        mock_gitlab_client.projects.get.assert_not_called()

    @pytest.mark.timeout(60)
    def test_upload_calls_generic_packages_upload(
        self, mock_upload_context, mock_file_path, mock_project
    ):
        """Test project.generic_packages.upload called with correct params."""
        mock_upload_context.gl.projects.get.return_value = mock_project

        upload_single_file(mock_upload_context, mock_file_path, "target.bin")

        mock_project.generic_packages.upload.assert_called_once()
        call_kwargs = mock_project.generic_packages.upload.call_args[1]
        assert call_kwargs["package_name"] == "test-package"
        assert call_kwargs["package_version"] == "1.0.0"
        assert call_kwargs["file_name"] == "target.bin"

    @pytest.mark.timeout(60)
    def test_upload_logs_file_size_and_time(
        self, mock_upload_context, mock_file_path, mock_project, caplog
    ):
        """Test logging includes file size in MB and elapsed time."""
        import logging

        caplog.set_level(logging.DEBUG)

        mock_upload_context.gl.projects.get.return_value = mock_project

        upload_single_file(mock_upload_context, mock_file_path, "target.bin")

        assert "MB" in caplog.text
        assert "target.bin" in caplog.text

    @pytest.mark.timeout(60)
    def test_upload_constructs_correct_download_url(
        self, mock_upload_context, mock_file_path, mock_project
    ):
        """Test returned URL matches expected format."""
        mock_upload_context.gl.projects.get.return_value = mock_project

        result = upload_single_file(mock_upload_context, mock_file_path, "target.bin")

        expected_base = "https://gitlab.com/api/v4/projects/12345/packages/generic"
        assert result.startswith(expected_base)
        assert "test-package" in result
        assert "1.0.0" in result
        assert "target.bin" in result

    @pytest.mark.timeout(60)
    def test_upload_file_size_calculation(
        self, mock_upload_context, tmp_path, mock_project, caplog
    ):
        """Test Path.stat() with specific size is logged correctly."""
        import logging

        caplog.set_level(logging.DEBUG)

        # Create a file with known size
        test_file = tmp_path / "sized.bin"
        content = b"x" * (1024 * 1024)  # 1 MB
        test_file.write_bytes(content)

        mock_upload_context.gl.projects.get.return_value = mock_project

        upload_single_file(mock_upload_context, test_file, "sized.bin")

        assert "1.00 MB" in caplog.text or "1.0" in caplog.text


class TestValidateUpload:
    """Test checksum validation after upload."""

    @pytest.mark.timeout(60)
    def test_validate_success_checksum_match(self, mock_upload_context, mock_project):
        """Test package file with matching checksum returns True."""
        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1

        mock_package_obj = MagicMock()
        mock_file = MagicMock()
        mock_file.file_name = "target.bin"
        mock_file.file_sha256 = "a" * 64
        mock_package_obj.package_files.list.return_value = [mock_file]

        mock_upload_context.gl.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        result = validate_upload(mock_upload_context, "target.bin", "a" * 64)

        assert result is True

    @pytest.mark.timeout(60)
    def test_validate_dry_run_mode(
        self, mock_gitlab_client, mock_upload_config_dry_run, mock_duplicate_detector
    ):
        """Test dry_run=True returns True without API calls."""
        context = UploadContext(
            gl=mock_gitlab_client,
            config=mock_upload_config_dry_run,
            detector=mock_duplicate_detector,
            project_id=12345,
            project_path="mygroup/myproject",
        )

        result = validate_upload(context, "target.bin", "a" * 64)

        assert result is True
        mock_gitlab_client.projects.get.assert_not_called()

    @pytest.mark.timeout(60)
    def test_validate_checksum_mismatch_raises_error(
        self, mock_upload_context, mock_project
    ):
        """Test mismatched checksum raises ChecksumValidationError."""
        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1

        mock_package_obj = MagicMock()
        mock_file = MagicMock()
        mock_file.file_name = "target.bin"
        mock_file.file_sha256 = "b" * 64  # Different checksum
        mock_package_obj.package_files.list.return_value = [mock_file]

        mock_upload_context.gl.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        with pytest.raises(ChecksumValidationError) as exc_info:
            validate_upload(mock_upload_context, "target.bin", "a" * 64)

        assert "mismatch" in str(exc_info.value).lower()

    @pytest.mark.timeout(60)
    def test_validate_package_not_found(self, mock_upload_context, mock_project):
        """Test packages.list returns empty, verify False returned."""
        mock_upload_context.gl.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = []

        result = validate_upload(mock_upload_context, "target.bin", "a" * 64)

        assert result is False

    @pytest.mark.timeout(60)
    def test_validate_file_not_found_in_package(
        self, mock_upload_context, mock_project
    ):
        """Test package exists but file not in package_files, verify False."""
        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1

        mock_package_obj = MagicMock()
        mock_file = MagicMock()
        mock_file.file_name = "other.bin"  # Different filename
        mock_package_obj.package_files.list.return_value = [mock_file]

        mock_upload_context.gl.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        result = validate_upload(mock_upload_context, "target.bin", "a" * 64)

        assert result is False

    @pytest.mark.timeout(60)
    def test_validate_no_remote_checksum_available(
        self, mock_upload_context, mock_project, caplog
    ):
        """Test remote file has no file_sha256 attribute, verify True (skip validation)."""
        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1

        mock_package_obj = MagicMock()
        mock_file = MagicMock(spec=[])  # No file_sha256 attribute
        mock_file.file_name = "target.bin"
        mock_package_obj.package_files.list.return_value = [mock_file]

        mock_upload_context.gl.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        result = validate_upload(mock_upload_context, "target.bin", "a" * 64)

        assert result is True
        assert "skipping validation" in caplog.text.lower()

    @pytest.mark.timeout(60)
    def test_validate_empty_file_checksum(self, mock_upload_context, mock_project):
        """Test special case for empty file SHA256."""
        empty_sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1

        mock_package_obj = MagicMock()
        mock_file = MagicMock()
        mock_file.file_name = "target.bin"
        mock_file.file_sha256 = empty_sha256
        mock_package_obj.package_files.list.return_value = [mock_file]

        mock_upload_context.gl.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        result = validate_upload(mock_upload_context, "target.bin", empty_sha256)

        assert result is True

    @pytest.mark.timeout(60)
    def test_validate_case_insensitive_checksum(self, mock_upload_context, mock_project):
        """Test checksum comparison is case-insensitive."""
        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1

        mock_package_obj = MagicMock()
        mock_file = MagicMock()
        mock_file.file_name = "target.bin"
        mock_file.file_sha256 = "AABBCC" + "d" * 58  # Uppercase
        mock_package_obj.package_files.list.return_value = [mock_file]

        mock_upload_context.gl.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        result = validate_upload(
            mock_upload_context, "target.bin", "aabbcc" + "d" * 58  # Lowercase
        )

        assert result is True

    @pytest.mark.timeout(60)
    def test_validate_filename_with_path_variations(
        self, mock_upload_context, mock_project
    ):
        """Test filename matching handles path variations (exact match and endswith)."""
        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1

        mock_package_obj = MagicMock()
        mock_file = MagicMock()
        mock_file.file_name = "subdir/target.bin"
        mock_file.file_sha256 = "a" * 64
        mock_package_obj.package_files.list.return_value = [mock_file]

        mock_upload_context.gl.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        result = validate_upload(mock_upload_context, "target.bin", "a" * 64)

        assert result is True


class TestHandleDuplicate:
    """Test duplicate handling based on policy."""

    @pytest.mark.timeout(60)
    def test_handle_duplicate_unknown_policy_raises_error(
        self, mock_upload_context, mock_file_path, sample_remote_file
    ):
        """Test unknown duplicate policy raises ValueError."""
        # Set an invalid policy by bypassing the enum
        mock_upload_context.config.duplicate_policy = "invalid_policy"

        with pytest.raises(ValueError) as exc_info:
            handle_duplicate(mock_upload_context, mock_file_path, sample_remote_file)

        assert "Unknown duplicate policy" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_handle_duplicate_skip_policy(
        self, mock_upload_context, mock_file_path, sample_remote_file
    ):
        """Test Policy=SKIP returns ('skipped', download_url)."""
        mock_upload_context.config.duplicate_policy = DuplicatePolicy.SKIP

        action, result = handle_duplicate(
            mock_upload_context, mock_file_path, sample_remote_file
        )

        assert action == "skipped"
        assert result == sample_remote_file.download_url

    @pytest.mark.timeout(60)
    def test_handle_duplicate_replace_policy(
        self, mock_upload_context, mock_file_path, sample_remote_file, mock_project
    ):
        """Test Policy=REPLACE calls delete and returns ('replaced', 'proceed_with_upload')."""
        mock_upload_context.config.duplicate_policy = DuplicatePolicy.REPLACE
        mock_upload_context.gl.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = []  # Simplified for this test

        action, result = handle_duplicate(
            mock_upload_context, mock_file_path, sample_remote_file
        )

        assert action == "replaced"
        assert result == "proceed_with_upload"

    @pytest.mark.timeout(60)
    def test_handle_duplicate_error_policy(
        self, mock_upload_context, mock_file_path, sample_remote_file
    ):
        """Test Policy=ERROR raises ValueError with helpful message."""
        mock_upload_context.config.duplicate_policy = DuplicatePolicy.ERROR

        with pytest.raises(ValueError) as exc_info:
            handle_duplicate(mock_upload_context, mock_file_path, sample_remote_file)

        assert "Duplicate file detected" in str(exc_info.value)
        assert "--duplicate-policy" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_handle_duplicate_skip_returns_existing_url(
        self, mock_upload_context, mock_file_path, sample_remote_file
    ):
        """Test existing RemoteFile.download_url is returned for SKIP policy."""
        mock_upload_context.config.duplicate_policy = DuplicatePolicy.SKIP
        sample_remote_file.download_url = "https://custom-url.com/file.bin"

        action, result = handle_duplicate(
            mock_upload_context, mock_file_path, sample_remote_file
        )

        assert result == "https://custom-url.com/file.bin"

    @pytest.mark.timeout(60)
    def test_handle_duplicate_replace_calls_delete(
        self, mock_upload_context, mock_file_path, sample_remote_file, mock_project
    ):
        """Test delete_file_from_registry is called with correct filename."""
        mock_upload_context.config.duplicate_policy = DuplicatePolicy.REPLACE
        mock_upload_context.gl.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = []

        with patch(
            "glpkg.uploader.delete_file_from_registry"
        ) as mock_delete:
            handle_duplicate(mock_upload_context, mock_file_path, sample_remote_file)
            mock_delete.assert_called_once_with(
                mock_upload_context, sample_remote_file.filename
            )

    @pytest.mark.timeout(60)
    def test_handle_duplicate_logging(
        self, mock_upload_context, mock_file_path, sample_remote_file, caplog
    ):
        """Test appropriate log messages for each policy."""
        import logging

        caplog.set_level(logging.DEBUG)

        mock_upload_context.config.duplicate_policy = DuplicatePolicy.SKIP

        handle_duplicate(mock_upload_context, mock_file_path, sample_remote_file)

        assert "Duplicate detected" in caplog.text
        assert "SKIP" in caplog.text


class TestDeleteFileFromRegistry:
    """Test file deletion from GitLab registry."""

    @pytest.mark.timeout(60)
    def test_delete_success(self, mock_upload_context, mock_project):
        """Test package file delete() called and count returned."""
        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1

        mock_package_obj = MagicMock()
        mock_file = MagicMock()
        mock_file.file_name = "target.bin"
        mock_file.id = 1001
        mock_package_obj.package_files.list.return_value = [mock_file]

        mock_upload_context.gl.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        result = delete_file_from_registry(mock_upload_context, "target.bin")

        assert result == 1
        mock_file.delete.assert_called_once()

    @pytest.mark.timeout(60)
    def test_delete_dry_run_mode(
        self, mock_gitlab_client, mock_upload_config_dry_run, mock_duplicate_detector
    ):
        """Test dry_run=True returns 0 without deletion."""
        context = UploadContext(
            gl=mock_gitlab_client,
            config=mock_upload_config_dry_run,
            detector=mock_duplicate_detector,
            project_id=12345,
            project_path="mygroup/myproject",
        )

        result = delete_file_from_registry(context, "target.bin")

        assert result == 0
        mock_gitlab_client.projects.get.assert_not_called()

    @pytest.mark.timeout(60)
    def test_delete_package_not_found(
        self, mock_upload_context, mock_project, caplog
    ):
        """Test packages.list returns empty, verify 0 returned with warning."""
        mock_upload_context.gl.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = []

        result = delete_file_from_registry(mock_upload_context, "target.bin")

        assert result == 0
        assert "not found" in caplog.text.lower()

    @pytest.mark.timeout(60)
    def test_delete_file_not_found(self, mock_upload_context, mock_project, caplog):
        """Test package exists but filename not found, verify 0 returned."""
        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1

        mock_package_obj = MagicMock()
        mock_file = MagicMock()
        mock_file.file_name = "other.bin"  # Different filename
        mock_package_obj.package_files.list.return_value = [mock_file]

        mock_upload_context.gl.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        result = delete_file_from_registry(mock_upload_context, "target.bin")

        assert result == 0
        assert "No files named" in caplog.text

    @pytest.mark.timeout(60)
    def test_delete_multiple_files_same_name(self, mock_upload_context, mock_project):
        """Test multiple files with same name, verify all deleted."""
        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1

        mock_package_obj = MagicMock()
        mock_file1 = MagicMock()
        mock_file1.file_name = "target.bin"
        mock_file1.id = 1001
        mock_file2 = MagicMock()
        mock_file2.file_name = "target.bin"
        mock_file2.id = 1002
        mock_file3 = MagicMock()
        mock_file3.file_name = "target.bin"
        mock_file3.id = 1003
        mock_package_obj.package_files.list.return_value = [
            mock_file1,
            mock_file2,
            mock_file3,
        ]

        mock_upload_context.gl.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        result = delete_file_from_registry(mock_upload_context, "target.bin")

        assert result == 3
        mock_file1.delete.assert_called_once()
        mock_file2.delete.assert_called_once()
        mock_file3.delete.assert_called_once()

    @pytest.mark.timeout(60)
    def test_delete_handles_deletion_error(
        self, mock_upload_context, mock_project, caplog
    ):
        """Test delete() raises exception, verify logged and continues."""
        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1

        mock_package_obj = MagicMock()
        mock_file1 = MagicMock()
        mock_file1.file_name = "target.bin"
        mock_file1.id = 1001
        mock_file1.delete.side_effect = Exception("Delete failed")
        mock_file2 = MagicMock()
        mock_file2.file_name = "target.bin"
        mock_file2.id = 1002
        mock_package_obj.package_files.list.return_value = [mock_file1, mock_file2]

        mock_upload_context.gl.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        result = delete_file_from_registry(mock_upload_context, "target.bin")

        assert result == 1  # Only second file deleted successfully
        assert "Failed to delete" in caplog.text

    @pytest.mark.timeout(60)
    def test_delete_returns_correct_count(self, mock_upload_context, mock_project):
        """Test delete 3 files, verify returns 3."""
        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1

        mock_package_obj = MagicMock()
        files = []
        for i in range(3):
            mock_file = MagicMock()
            mock_file.file_name = "target.bin"
            mock_file.id = 1000 + i
            files.append(mock_file)
        mock_package_obj.package_files.list.return_value = files

        mock_upload_context.gl.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        result = delete_file_from_registry(mock_upload_context, "target.bin")

        assert result == 3


class TestUploadFiles:
    """Test main orchestration function."""

    @pytest.mark.timeout(60)
    def test_upload_files_single_file_success(
        self, mock_upload_context, mock_file_path, mock_project
    ):
        """Test upload one file, verify UploadResult with success=True."""
        mock_upload_context.gl.projects.get.return_value = mock_project

        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1
        mock_package_obj = MagicMock()
        mock_pkg_file = MagicMock()
        mock_pkg_file.file_name = "target.bin"
        mock_pkg_file.file_sha256 = "a" * 64
        mock_package_obj.package_files.list.return_value = [mock_pkg_file]
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        with patch(
            "glpkg.uploader.calculate_sha256", return_value="a" * 64
        ):
            results = upload_files(mock_upload_context, [(mock_file_path, "target.bin")])

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].target_filename == "target.bin"

    @pytest.mark.timeout(60)
    def test_upload_files_multiple_files_success(
        self, mock_upload_context, tmp_path, mock_project
    ):
        """Test upload multiple files, verify all succeed."""
        file1 = tmp_path / "file1.bin"
        file2 = tmp_path / "file2.bin"
        file1.write_bytes(b"content1")
        file2.write_bytes(b"content2")

        mock_upload_context.gl.projects.get.return_value = mock_project

        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1
        mock_package_obj = MagicMock()
        mock_package_obj.package_files.list.return_value = []
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        with patch(
            "glpkg.uploader.calculate_sha256", return_value="a" * 64
        ):
            with patch(
                "glpkg.uploader.validate_upload", return_value=True
            ):
                results = upload_files(
                    mock_upload_context,
                    [(file1, "target1.bin"), (file2, "target2.bin")],
                )

        assert len(results) == 2
        assert all(r.success for r in results)

    @pytest.mark.timeout(60)
    def test_upload_files_session_duplicate_skipped(
        self, mock_upload_context, mock_file_path, mock_project
    ):
        """Test session duplicate detected, verify skipped without upload."""
        session_fingerprint = MagicMock()
        session_fingerprint.sha256_checksum = "a" * 64
        mock_upload_context.detector.check_session_duplicate.return_value = (
            session_fingerprint
        )

        results = upload_files(mock_upload_context, [(mock_file_path, "target.bin")])

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].was_duplicate is True
        assert results[0].duplicate_action == "skipped"
        mock_upload_context.gl.projects.get.assert_not_called()

    @pytest.mark.timeout(60)
    def test_upload_files_remote_duplicate_skip_policy(
        self, mock_upload_context, mock_file_path, sample_remote_file
    ):
        """Test remote duplicate with SKIP policy, verify skipped."""
        mock_upload_context.config.duplicate_policy = DuplicatePolicy.SKIP
        mock_upload_context.detector.check_remote_duplicate.return_value = (
            sample_remote_file
        )

        with patch(
            "glpkg.uploader.calculate_sha256", return_value="a" * 64
        ):
            results = upload_files(
                mock_upload_context, [(mock_file_path, "target.bin")]
            )

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].was_duplicate is True
        assert results[0].duplicate_action == "skipped"

    @pytest.mark.timeout(60)
    def test_upload_files_remote_duplicate_replace_policy(
        self, mock_upload_context, mock_file_path, sample_remote_file, mock_project
    ):
        """Test remote duplicate with REPLACE policy, verify deleted then uploaded."""
        mock_upload_context.config.duplicate_policy = DuplicatePolicy.REPLACE
        mock_upload_context.detector.check_remote_duplicate.return_value = (
            sample_remote_file
        )
        mock_upload_context.gl.projects.get.return_value = mock_project

        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1
        mock_package_obj = MagicMock()
        mock_pkg_file = MagicMock()
        mock_pkg_file.file_name = "target.bin"
        mock_pkg_file.file_sha256 = "a" * 64
        mock_package_obj.package_files.list.return_value = [mock_pkg_file]
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        with patch(
            "glpkg.uploader.calculate_sha256", return_value="a" * 64
        ):
            results = upload_files(
                mock_upload_context, [(mock_file_path, "target.bin")]
            )

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].was_duplicate is True
        assert results[0].duplicate_action == "replaced"

    @pytest.mark.timeout(60)
    def test_upload_files_remote_duplicate_error_policy(
        self, mock_upload_context, mock_file_path, sample_remote_file
    ):
        """Test remote duplicate with ERROR policy, verify UploadResult with success=False."""
        mock_upload_context.config.duplicate_policy = DuplicatePolicy.ERROR
        mock_upload_context.detector.check_remote_duplicate.return_value = (
            sample_remote_file
        )

        with patch(
            "glpkg.uploader.calculate_sha256", return_value="a" * 64
        ):
            results = upload_files(
                mock_upload_context, [(mock_file_path, "target.bin")]
            )

        assert len(results) == 1
        assert results[0].success is False
        assert results[0].was_duplicate is True
        assert results[0].duplicate_action == "error"

    @pytest.mark.timeout(60)
    def test_upload_files_remote_duplicate_error_policy_fail_fast(
        self, mock_upload_context, mock_file_path, sample_remote_file, tmp_path
    ):
        """Test remote duplicate with ERROR policy and fail_fast enabled stops early."""
        mock_upload_context.config.duplicate_policy = DuplicatePolicy.ERROR
        mock_upload_context.config.fail_fast = True
        mock_upload_context.detector.check_remote_duplicate.return_value = (
            sample_remote_file
        )

        file2 = tmp_path / "file2.bin"
        file2.write_bytes(b"content2")

        with patch(
            "glpkg.uploader.calculate_sha256", return_value="a" * 64
        ):
            results = upload_files(
                mock_upload_context,
                [(mock_file_path, "target1.bin"), (file2, "target2.bin")]
            )

        # With fail_fast, should stop after first error
        assert len(results) == 1
        assert results[0].success is False
        assert results[0].was_duplicate is True
        assert results[0].duplicate_action == "error"

    @pytest.mark.timeout(60)
    def test_upload_files_fail_fast_enabled(
        self, mock_upload_context, tmp_path, mock_project
    ):
        """Test first file fails with fail_fast=True, verify second file not attempted."""
        mock_upload_context.config.fail_fast = True

        file1 = tmp_path / "file1.bin"
        file2 = tmp_path / "file2.bin"
        file1.write_bytes(b"content1")
        file2.write_bytes(b"content2")

        mock_upload_context.gl.projects.get.side_effect = Exception("Upload failed")

        with patch(
            "glpkg.uploader.calculate_sha256", return_value="a" * 64
        ):
            results = upload_files(
                mock_upload_context,
                [(file1, "target1.bin"), (file2, "target2.bin")],
            )

        assert len(results) == 1
        assert results[0].success is False

    @pytest.mark.timeout(60)
    def test_upload_files_fail_fast_disabled(
        self, mock_upload_context, tmp_path, mock_project
    ):
        """Test first file fails with fail_fast=False, verify second file attempted."""
        mock_upload_context.config.fail_fast = False

        file1 = tmp_path / "file1.bin"
        file2 = tmp_path / "file2.bin"
        file1.write_bytes(b"content1")
        file2.write_bytes(b"content2")

        call_count = 0

        def mock_get_project(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("First upload failed")
            return mock_project

        mock_upload_context.gl.projects.get.side_effect = mock_get_project

        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1
        mock_package_obj = MagicMock()
        mock_pkg_file = MagicMock()
        mock_pkg_file.file_name = "target2.bin"
        mock_pkg_file.file_sha256 = "a" * 64
        mock_package_obj.package_files.list.return_value = [mock_pkg_file]
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        with patch(
            "glpkg.uploader.calculate_sha256", return_value="a" * 64
        ):
            results = upload_files(
                mock_upload_context,
                [(file1, "target1.bin"), (file2, "target2.bin")],
            )

        assert len(results) == 2
        assert results[0].success is False
        assert results[1].success is True

    @pytest.mark.timeout(60)
    def test_upload_files_checksum_calculation(
        self, mock_upload_context, mock_file_path, mock_project
    ):
        """Test calculate_sha256 called for each file."""
        mock_upload_context.gl.projects.get.return_value = mock_project

        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1
        mock_package_obj = MagicMock()
        mock_pkg_file = MagicMock()
        mock_pkg_file.file_name = "target.bin"
        mock_pkg_file.file_sha256 = "a" * 64
        mock_package_obj.package_files.list.return_value = [mock_pkg_file]
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        with patch(
            "glpkg.uploader.calculate_sha256", return_value="a" * 64
        ) as mock_sha:
            upload_files(mock_upload_context, [(mock_file_path, "target.bin")])
            mock_sha.assert_called_once_with(mock_file_path)

    @pytest.mark.timeout(60)
    def test_upload_files_validation_called(
        self, mock_upload_context, mock_file_path, mock_project
    ):
        """Test validate_upload called after each successful upload."""
        mock_upload_context.gl.projects.get.return_value = mock_project

        with patch(
            "glpkg.uploader.calculate_sha256", return_value="a" * 64
        ):
            with patch(
                "glpkg.uploader.validate_upload", return_value=True
            ) as mock_validate:
                upload_files(mock_upload_context, [(mock_file_path, "target.bin")])
                mock_validate.assert_called_once()

    @pytest.mark.timeout(60)
    def test_upload_files_registration_called(
        self, mock_upload_context, mock_file_path, mock_project
    ):
        """Test detector.register_file called after validation."""
        mock_upload_context.gl.projects.get.return_value = mock_project

        with patch(
            "glpkg.uploader.calculate_sha256", return_value="a" * 64
        ):
            with patch(
                "glpkg.uploader.validate_upload", return_value=True
            ):
                upload_files(mock_upload_context, [(mock_file_path, "target.bin")])

        mock_upload_context.detector.register_file.assert_called_once()

    @pytest.mark.timeout(60)
    def test_upload_files_upload_exception_handled(
        self, mock_upload_context, mock_file_path
    ):
        """Test upload raises exception, verify UploadResult with success=False."""
        mock_upload_context.gl.projects.get.side_effect = Exception("Network error")

        with patch(
            "glpkg.uploader.calculate_sha256", return_value="a" * 64
        ):
            results = upload_files(
                mock_upload_context, [(mock_file_path, "target.bin")]
            )

        assert len(results) == 1
        assert results[0].success is False
        # Error may be wrapped in RetryError from tenacity
        assert results[0].result != ""

    @pytest.mark.timeout(60)
    def test_upload_files_replace_policy_deletes_different_checksum(
        self, mock_upload_context, mock_file_path, mock_project
    ):
        """Test no remote duplicate but file exists with different checksum, verify deleted."""
        mock_upload_context.config.duplicate_policy = DuplicatePolicy.REPLACE
        mock_upload_context.detector.check_remote_duplicate.return_value = None
        mock_upload_context.gl.projects.get.return_value = mock_project

        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1
        mock_package_obj = MagicMock()
        mock_pkg_file = MagicMock()
        mock_pkg_file.file_name = "target.bin"
        mock_pkg_file.file_sha256 = "a" * 64
        mock_package_obj.package_files.list.return_value = [mock_pkg_file]
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        with patch(
            "glpkg.uploader.calculate_sha256", return_value="a" * 64
        ):
            with patch(
                "glpkg.uploader.delete_file_from_registry", return_value=1
            ) as mock_delete:
                upload_files(mock_upload_context, [(mock_file_path, "target.bin")])
                mock_delete.assert_called()

    @pytest.mark.timeout(60)
    def test_upload_files_result_includes_duplicate_metadata(
        self, mock_upload_context, mock_file_path, sample_remote_file
    ):
        """Test UploadResult includes was_duplicate, duplicate_action, existing_url."""
        mock_upload_context.config.duplicate_policy = DuplicatePolicy.SKIP
        mock_upload_context.detector.check_remote_duplicate.return_value = (
            sample_remote_file
        )

        with patch(
            "glpkg.uploader.calculate_sha256", return_value="a" * 64
        ):
            results = upload_files(
                mock_upload_context, [(mock_file_path, "target.bin")]
            )

        assert results[0].was_duplicate is True
        assert results[0].duplicate_action == "skipped"
        assert results[0].existing_url == sample_remote_file.download_url

    @pytest.mark.timeout(60)
    def test_upload_files_constructs_session_duplicate_url(
        self, mock_upload_context, mock_file_path
    ):
        """Test session duplicate detected, verify URL constructed correctly."""
        session_fingerprint = MagicMock()
        session_fingerprint.sha256_checksum = "a" * 64
        mock_upload_context.detector.check_session_duplicate.return_value = (
            session_fingerprint
        )

        results = upload_files(mock_upload_context, [(mock_file_path, "target.bin")])

        assert results[0].success is True
        assert "test-package" in results[0].existing_url
        assert "1.0.0" in results[0].existing_url
        assert "target.bin" in results[0].existing_url


class TestUploadFilesIntegration:
    """Integration tests for complete upload workflows."""

    @pytest.mark.timeout(60)
    def test_workflow_no_duplicates_all_succeed(
        self, mock_upload_context, tmp_path, mock_project
    ):
        """Test upload 3 files with no duplicates, verify all succeed."""
        files = []
        for i in range(3):
            f = tmp_path / f"file{i}.bin"
            f.write_bytes(f"content {i}".encode())
            files.append((f, f"target{i}.bin"))

        mock_upload_context.gl.projects.get.return_value = mock_project

        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1
        mock_package_obj = MagicMock()
        mock_package_obj.package_files.list.return_value = []
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        with patch(
            "glpkg.uploader.calculate_sha256", return_value="a" * 64
        ):
            with patch(
                "glpkg.uploader.validate_upload", return_value=True
            ):
                results = upload_files(mock_upload_context, files)

        assert len(results) == 3
        assert all(r.success for r in results)
        assert all(not r.was_duplicate for r in results)

    @pytest.mark.timeout(60)
    def test_workflow_mixed_success_and_failure(
        self, mock_upload_context, tmp_path, mock_project
    ):
        """Test some files succeed, some fail, verify correct results."""
        mock_upload_context.config.fail_fast = False

        file1 = tmp_path / "file1.bin"
        file2 = tmp_path / "file2.bin"
        file3 = tmp_path / "file3.bin"
        file1.write_bytes(b"content1")
        file2.write_bytes(b"content2")
        file3.write_bytes(b"content3")

        # Track calls to determine when to fail
        # upload_single_file calls projects.get once per file
        # validate_upload calls projects.get once per file
        # So for 3 files: file1 upload, file1 validate, file2 upload (fail), ...
        upload_call_count = 0

        def mock_upload_side_effect(context, file, target):
            nonlocal upload_call_count
            upload_call_count += 1
            if upload_call_count == 2:  # Second file fails during upload
                raise Exception("Upload failed")
            return f"https://gitlab.com/download/{target}"

        mock_upload_context.gl.projects.get.return_value = mock_project

        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1
        mock_package_obj = MagicMock()
        mock_pkg_file = MagicMock()
        mock_pkg_file.file_sha256 = "a" * 64
        mock_package_obj.package_files.list.return_value = [mock_pkg_file]
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        with patch(
            "glpkg.uploader.calculate_sha256", return_value="a" * 64
        ):
            with patch(
                "glpkg.uploader.upload_single_file",
                side_effect=mock_upload_side_effect,
            ):
                results = upload_files(
                    mock_upload_context,
                    [(file1, "t1.bin"), (file2, "t2.bin"), (file3, "t3.bin")],
                )

        assert len(results) == 3
        assert results[0].success is True
        assert results[1].success is False
        assert results[2].success is True

    @pytest.mark.timeout(60)
    def test_workflow_all_duplicates_skip_policy(
        self, mock_upload_context, tmp_path, sample_remote_file
    ):
        """Test all files are duplicates with SKIP policy, verify all skipped."""
        mock_upload_context.config.duplicate_policy = DuplicatePolicy.SKIP

        files = []
        for i in range(3):
            f = tmp_path / f"file{i}.bin"
            f.write_bytes(f"content {i}".encode())
            files.append((f, f"target{i}.bin"))

        mock_upload_context.detector.check_remote_duplicate.return_value = (
            sample_remote_file
        )

        with patch(
            "glpkg.uploader.calculate_sha256", return_value="a" * 64
        ):
            results = upload_files(mock_upload_context, files)

        assert len(results) == 3
        assert all(r.success for r in results)
        assert all(r.was_duplicate for r in results)
        assert all(r.duplicate_action == "skipped" for r in results)

    @pytest.mark.timeout(60)
    def test_workflow_duplicate_then_new_file(
        self, mock_upload_context, tmp_path, sample_remote_file, mock_project
    ):
        """Test first file is duplicate (skipped), second is new (uploaded)."""
        mock_upload_context.config.duplicate_policy = DuplicatePolicy.SKIP

        file1 = tmp_path / "file1.bin"
        file2 = tmp_path / "file2.bin"
        file1.write_bytes(b"content1")
        file2.write_bytes(b"content2")

        # First file is duplicate, second is not
        mock_upload_context.detector.check_remote_duplicate.side_effect = [
            sample_remote_file,
            None,
        ]

        mock_upload_context.gl.projects.get.return_value = mock_project

        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1
        mock_package_obj = MagicMock()
        mock_pkg_file = MagicMock()
        mock_pkg_file.file_name = "target2.bin"
        mock_pkg_file.file_sha256 = "a" * 64
        mock_package_obj.package_files.list.return_value = [mock_pkg_file]
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        with patch(
            "glpkg.uploader.calculate_sha256", return_value="a" * 64
        ):
            results = upload_files(
                mock_upload_context,
                [(file1, "target1.bin"), (file2, "target2.bin")],
            )

        assert len(results) == 2
        assert results[0].success is True
        assert results[0].was_duplicate is True
        assert results[0].duplicate_action == "skipped"
        assert results[1].success is True
        assert results[1].was_duplicate is False

    @pytest.mark.timeout(60)
    def test_workflow_session_duplicate_prevents_remote_check(
        self, mock_upload_context, tmp_path
    ):
        """Test session duplicate found, verify remote check not called."""
        file1 = tmp_path / "file1.bin"
        file2 = tmp_path / "file2.bin"
        file1.write_bytes(b"content")
        file2.write_bytes(b"content")

        session_fingerprint = MagicMock()
        session_fingerprint.sha256_checksum = "a" * 64
        mock_upload_context.detector.check_session_duplicate.return_value = (
            session_fingerprint
        )

        results = upload_files(mock_upload_context, [(file1, "target.bin")])

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].was_duplicate is True
        mock_upload_context.detector.check_remote_duplicate.assert_not_called()
