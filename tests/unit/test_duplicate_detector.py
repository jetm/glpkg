"""
Comprehensive unit tests for the duplicate_detector module.

These tests validate the DuplicateDetector class and related helper functions
for session-level and remote duplicate detection. All external dependencies
(GitLab API, filesystem, network) are mocked to ensure test isolation.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from glpkg.duplicate_detector import (
    DuplicateDetector,
    calculate_sha256,
    handle_network_error_with_retry,
)
from glpkg.models import FileFingerprint, RemoteFile

# Mark these as fast unit tests
pytestmark = [pytest.mark.unit, pytest.mark.fast]


# =============================================================================
# Fixtures
# =============================================================================


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
def sample_file_path(tmp_path) -> Path:
    """Create a sample file for testing."""
    file_path = tmp_path / "test_file.txt"
    file_path.write_text("test content for hashing")
    return file_path


@pytest.fixture
def sample_checksum() -> str:
    """Return a valid SHA256 hex string (64 characters)."""
    return "a" * 64


@pytest.fixture
def mock_package_file() -> MagicMock:
    """Create a mock package file with checksum."""
    mock_file = MagicMock()
    mock_file.id = 1001
    mock_file.file_name = "test.bin"
    mock_file.file_sha256 = "a" * 64
    mock_file.size = 1024
    return mock_file


# =============================================================================
# Test Classes
# =============================================================================


class TestCalculateSHA256:
    """Test the calculate_sha256 helper function."""

    @pytest.mark.timeout(60)
    def test_calculate_sha256_text_file(self, tmp_path):
        """Test SHA256 calculation for a text file."""
        test_file = tmp_path / "test.txt"
        content = b"Hello, World!"
        test_file.write_bytes(content)

        expected = hashlib.sha256(content).hexdigest()
        result = calculate_sha256(test_file)

        assert result == expected
        assert len(result) == 64

    @pytest.mark.timeout(60)
    def test_calculate_sha256_binary_file(self, tmp_path):
        """Test SHA256 calculation for a binary file."""
        test_file = tmp_path / "binary.bin"
        content = bytes(range(256))
        test_file.write_bytes(content)

        expected = hashlib.sha256(content).hexdigest()
        result = calculate_sha256(test_file)

        assert result == expected

    @pytest.mark.timeout(60)
    def test_calculate_sha256_empty_file(self, tmp_path):
        """Test SHA256 calculation for an empty file returns expected empty file SHA256."""
        test_file = tmp_path / "empty.txt"
        test_file.write_bytes(b"")

        expected = hashlib.sha256(b"").hexdigest()
        result = calculate_sha256(test_file)

        assert result == expected
        assert result == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    @pytest.mark.timeout(60)
    def test_calculate_sha256_large_file(self, tmp_path):
        """Test SHA256 calculation reads file in chunks (8192 bytes)."""
        test_file = tmp_path / "large.bin"
        # Create a file larger than 8192 bytes to test chunked reading
        content = b"x" * 50000
        test_file.write_bytes(content)

        expected = hashlib.sha256(content).hexdigest()
        result = calculate_sha256(test_file)

        assert result == expected

    @pytest.mark.timeout(60)
    def test_calculate_sha256_file_not_found(self):
        """Test FileNotFoundError is raised for missing file."""
        nonexistent = Path("/nonexistent/path/to/file.txt")

        with pytest.raises(FileNotFoundError):
            calculate_sha256(nonexistent)

    @pytest.mark.timeout(60)
    def test_calculate_sha256_permission_error(self, tmp_path):
        """Test PermissionError is raised for unreadable file."""
        test_file = tmp_path / "unreadable.txt"
        test_file.write_bytes(b"content")

        with patch("builtins.open", side_effect=PermissionError("Permission denied")):
            with pytest.raises(PermissionError):
                calculate_sha256(test_file)


class TestHandleNetworkErrorWithRetry:
    """Test the retry logic helper function."""

    @pytest.mark.timeout(60)
    def test_retry_success_first_attempt(self):
        """Test operation succeeds immediately, no retries needed."""
        mock_operation = MagicMock(return_value="success")

        with patch("time.sleep"):
            result = handle_network_error_with_retry(
                operation_name="test op",
                operation_func=mock_operation,
            )

        assert result == "success"
        mock_operation.assert_called_once()

    @pytest.mark.timeout(60)
    def test_retry_success_after_failures(self):
        """Test operation fails twice then succeeds, verify retry count."""
        call_count = 0

        def operation_with_failures():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Network error")
            return "success"

        with patch("time.sleep"):
            result = handle_network_error_with_retry(
                operation_name="test op",
                operation_func=operation_with_failures,
                max_retries=3,
            )

        assert result == "success"
        assert call_count == 3

    @pytest.mark.timeout(60)
    def test_retry_exhausted_raises_exception(self):
        """Test all retries fail, verify last exception is raised."""
        mock_operation = MagicMock(side_effect=ConnectionError("Persistent failure"))

        with patch("time.sleep"):
            with pytest.raises(ConnectionError) as exc_info:
                handle_network_error_with_retry(
                    operation_name="test op",
                    operation_func=mock_operation,
                    max_retries=2,
                )

        assert "Persistent failure" in str(exc_info.value)
        assert mock_operation.call_count == 3  # Initial + 2 retries

    @pytest.mark.timeout(60)
    def test_retry_with_custom_delays(self):
        """Test custom retry delay list is respected."""
        mock_operation = MagicMock(side_effect=ConnectionError("Error"))
        custom_delays = [5, 10, 15]

        with patch("time.sleep") as mock_sleep:
            with pytest.raises(ConnectionError):
                handle_network_error_with_retry(
                    operation_name="test op",
                    operation_func=mock_operation,
                    max_retries=3,
                    retry_delays=custom_delays,
                )

        # Verify sleep was called with custom delays
        sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
        assert sleep_calls == [5, 10, 15]

    @pytest.mark.timeout(60)
    def test_retry_logs_attempts(self, caplog):
        """Test logging calls for each retry attempt."""
        mock_operation = MagicMock(side_effect=ConnectionError("Error"))

        with patch("time.sleep"):
            with pytest.raises(ConnectionError):
                handle_network_error_with_retry(
                    operation_name="test operation",
                    operation_func=mock_operation,
                    max_retries=2,
                )

        # Check that retry attempts were logged
        assert "test operation failed" in caplog.text
        assert "attempt" in caplog.text.lower()

    @pytest.mark.timeout(60)
    def test_retry_default_delays(self):
        """Test default delays [1, 2, 4] are used when not specified."""
        mock_operation = MagicMock(side_effect=ConnectionError("Error"))

        with patch("time.sleep") as mock_sleep:
            with pytest.raises(ConnectionError):
                handle_network_error_with_retry(
                    operation_name="test op",
                    operation_func=mock_operation,
                    max_retries=3,
                )

        sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
        assert sleep_calls == [1, 2, 4]


class TestDuplicateDetectorInit:
    """Test DuplicateDetector initialization."""

    @pytest.mark.timeout(60)
    def test_init_with_valid_params(self, mock_gitlab_client):
        """Test detector creation with mock client and project ID."""
        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        assert detector.gl is mock_gitlab_client
        assert detector.project_id == 12345
        assert isinstance(detector.session_registry, dict)

    @pytest.mark.timeout(60)
    def test_init_session_registry_empty(self, mock_gitlab_client):
        """Test session_registry starts as empty dict."""
        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        assert detector.session_registry == {}
        assert len(detector.session_registry) == 0

    @pytest.mark.timeout(60)
    def test_init_stores_gitlab_client(self, mock_gitlab_client):
        """Test GitLab client is stored correctly."""
        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        assert detector.gl is mock_gitlab_client

    @pytest.mark.timeout(60)
    def test_init_stores_project_id(self, mock_gitlab_client):
        """Test project ID is stored correctly."""
        detector = DuplicateDetector(mock_gitlab_client, project_id=99999)

        assert detector.project_id == 99999


class TestCheckSessionDuplicate:
    """Test session-level duplicate detection."""

    @pytest.mark.timeout(60)
    def test_no_session_duplicate_when_empty(self, mock_gitlab_client, sample_file_path):
        """Test empty registry returns None."""
        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        result = detector.check_session_duplicate(sample_file_path, "target.txt")

        assert result is None

    @pytest.mark.timeout(60)
    def test_session_duplicate_same_checksum(self, mock_gitlab_client, tmp_path):
        """Test file with same target name and checksum returns FileFingerprint."""
        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        # Create two files with identical content
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        content = b"identical content"
        file1.write_bytes(content)
        file2.write_bytes(content)

        checksum = hashlib.sha256(content).hexdigest()

        # Register the first file
        detector.register_file(file1, "target.txt", checksum)

        # Check for duplicate with second file
        result = detector.check_session_duplicate(file2, "target.txt")

        assert result is not None
        assert isinstance(result, FileFingerprint)
        assert result.target_filename == "target.txt"
        assert result.sha256_checksum == checksum

    @pytest.mark.timeout(60)
    def test_session_duplicate_different_checksum(self, mock_gitlab_client, tmp_path, caplog):
        """Test same target name but different checksum returns None, logs warning."""
        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        # Create two files with different content
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_bytes(b"content version 1")
        file2.write_bytes(b"content version 2")

        checksum1 = hashlib.sha256(b"content version 1").hexdigest()

        # Register the first file
        detector.register_file(file1, "target.txt", checksum1)

        # Check for duplicate with second file (different content)
        result = detector.check_session_duplicate(file2, "target.txt")

        assert result is None
        assert "different content" in caplog.text.lower()

    @pytest.mark.timeout(60)
    def test_session_duplicate_different_source_path(self, mock_gitlab_client, tmp_path):
        """Test same target name and checksum but different source path still detected as duplicate."""
        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        # Create two files with identical content in different locations
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        file1 = tmp_path / "file1.txt"
        file2 = subdir / "file2.txt"
        content = b"same content"
        file1.write_bytes(content)
        file2.write_bytes(content)

        checksum = hashlib.sha256(content).hexdigest()

        # Register the first file
        detector.register_file(file1, "target.txt", checksum)

        # Check for duplicate with second file from different location
        result = detector.check_session_duplicate(file2, "target.txt")

        assert result is not None
        assert result.sha256_checksum == checksum

    @pytest.mark.timeout(60)
    def test_session_duplicate_checksum_calculation(self, mock_gitlab_client, tmp_path):
        """Test calculate_sha256 is called with correct file path."""
        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        content = b"content"
        file1.write_bytes(content)
        file2.write_bytes(content)

        checksum = hashlib.sha256(content).hexdigest()
        detector.register_file(file1, "target.txt", checksum)

        with patch(
            "glpkg.duplicate_detector.calculate_sha256",
            return_value=checksum,
        ) as mock_calc:
            detector.check_session_duplicate(file2, "target.txt")
            mock_calc.assert_called_once_with(file2)

    @pytest.mark.timeout(60)
    def test_session_duplicate_logging(self, mock_gitlab_client, tmp_path, caplog):
        """Test appropriate log messages for duplicate detection."""
        import logging

        caplog.set_level(logging.DEBUG)

        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        content = b"content"
        file1.write_bytes(content)
        file2.write_bytes(content)

        checksum = hashlib.sha256(content).hexdigest()
        detector.register_file(file1, "target.txt", checksum)

        detector.check_session_duplicate(file2, "target.txt")

        assert "Session duplicate detected" in caplog.text


class TestCheckRemoteDuplicate:
    """Test remote duplicate detection with GitLab API."""

    @pytest.mark.timeout(60)
    def test_no_remote_duplicate_package_not_found(
        self, mock_gitlab_client, mock_project
    ):
        """Test packages.list returns empty, verify None returned."""
        mock_gitlab_client.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = []

        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        result = detector.check_remote_duplicate(
            package_name="test-pkg",
            version="1.0.0",
            filename="test.bin",
            checksum="a" * 64,
        )

        assert result is None

    @pytest.mark.timeout(60)
    def test_no_remote_duplicate_version_not_found(
        self, mock_gitlab_client, mock_project
    ):
        """Test package exists but version doesn't match, verify None."""
        mock_package = MagicMock()
        mock_package.version = "2.0.0"  # Different version
        mock_package.id = 1

        mock_gitlab_client.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = [mock_package]

        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        result = detector.check_remote_duplicate(
            package_name="test-pkg",
            version="1.0.0",
            filename="test.bin",
            checksum="a" * 64,
        )

        assert result is None

    @pytest.mark.timeout(60)
    def test_no_remote_duplicate_filename_not_found(
        self, mock_gitlab_client, mock_project, mock_package_file
    ):
        """Test package and version exist but filename doesn't match, verify None."""
        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1

        mock_package_obj = MagicMock()
        mock_package_file.file_name = "other.bin"  # Different filename
        mock_package_obj.package_files.list.return_value = [mock_package_file]

        mock_gitlab_client.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        result = detector.check_remote_duplicate(
            package_name="test-pkg",
            version="1.0.0",
            filename="test.bin",
            checksum="a" * 64,
        )

        assert result is None

    @pytest.mark.timeout(60)
    def test_remote_duplicate_checksum_match(
        self, mock_gitlab_client, mock_project, mock_package_file
    ):
        """Test package file with matching checksum, verify RemoteFile returned."""
        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1

        mock_package_obj = MagicMock()
        mock_package_file.file_name = "test.bin"
        mock_package_file.file_sha256 = "a" * 64
        mock_package_obj.package_files.list.return_value = [mock_package_file]

        mock_gitlab_client.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        result = detector.check_remote_duplicate(
            package_name="test-pkg",
            version="1.0.0",
            filename="test.bin",
            checksum="a" * 64,
        )

        assert result is not None
        assert isinstance(result, RemoteFile)
        assert result.filename == "test.bin"
        assert result.sha256_checksum == "a" * 64

    @pytest.mark.timeout(60)
    def test_remote_duplicate_checksum_mismatch(
        self, mock_gitlab_client, mock_project, mock_package_file
    ):
        """Test filename matches but checksum differs, verify None returned."""
        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1

        mock_package_obj = MagicMock()
        mock_package_file.file_name = "test.bin"
        mock_package_file.file_sha256 = "b" * 64  # Different checksum
        mock_package_obj.package_files.list.return_value = [mock_package_file]

        mock_gitlab_client.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        result = detector.check_remote_duplicate(
            package_name="test-pkg",
            version="1.0.0",
            filename="test.bin",
            checksum="a" * 64,
        )

        assert result is None

    @pytest.mark.timeout(60)
    def test_remote_duplicate_no_checksum_available(
        self, mock_gitlab_client, mock_project, caplog
    ):
        """Test remote file has no checksum attribute, verify None returned with warning."""
        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1

        mock_package_obj = MagicMock()
        mock_file = MagicMock()
        mock_file.file_name = "test.bin"
        # No file_sha256 attribute - use spec to control what attrs exist
        del mock_file.file_sha256
        mock_package_obj.package_files.list.return_value = [mock_file]

        mock_gitlab_client.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        result = detector.check_remote_duplicate(
            package_name="test-pkg",
            version="1.0.0",
            filename="test.bin",
            checksum="a" * 64,
        )

        assert result is None
        assert "checksum not available" in caplog.text.lower()

    @pytest.mark.timeout(60)
    def test_remote_duplicate_case_insensitive_checksum(
        self, mock_gitlab_client, mock_project, mock_package_file
    ):
        """Test checksum comparison is case-insensitive."""
        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1

        mock_package_obj = MagicMock()
        mock_package_file.file_name = "test.bin"
        mock_package_file.file_sha256 = "AABBCC" + "d" * 58  # Upper case
        mock_package_obj.package_files.list.return_value = [mock_package_file]

        mock_gitlab_client.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        result = detector.check_remote_duplicate(
            package_name="test-pkg",
            version="1.0.0",
            filename="test.bin",
            checksum="aabbcc" + "d" * 58,  # Lower case
        )

        assert result is not None
        assert isinstance(result, RemoteFile)

    @pytest.mark.timeout(60)
    def test_remote_duplicate_constructs_download_url(
        self, mock_gitlab_client, mock_project, mock_package_file
    ):
        """Test RemoteFile has correctly formatted download URL."""
        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1

        mock_package_obj = MagicMock()
        mock_package_file.file_name = "test.bin"
        mock_package_file.file_sha256 = "a" * 64
        mock_package_obj.package_files.list.return_value = [mock_package_file]

        mock_gitlab_client.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        result = detector.check_remote_duplicate(
            package_name="test-pkg",
            version="1.0.0",
            filename="test.bin",
            checksum="a" * 64,
        )

        assert result is not None
        assert "test-pkg" in result.download_url
        assert "1.0.0" in result.download_url
        assert "test.bin" in result.download_url
        assert "12345" in result.download_url

    @pytest.mark.timeout(60)
    def test_remote_duplicate_retry_on_network_error(self, mock_gitlab_client):
        """Test network error triggers retry logic."""
        call_count = 0

        def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Network error")
            mock_proj = MagicMock()
            mock_proj.packages.list.return_value = []
            return mock_proj

        mock_gitlab_client.projects.get.side_effect = mock_get

        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        with patch("time.sleep"):
            result = detector.check_remote_duplicate(
                package_name="test-pkg",
                version="1.0.0",
                filename="test.bin",
                checksum="a" * 64,
            )

        assert result is None
        assert call_count == 3

    @pytest.mark.timeout(60)
    def test_remote_duplicate_returns_none_on_persistent_error(
        self, mock_gitlab_client, caplog
    ):
        """Test all retries fail, verify None returned (not exception)."""
        mock_gitlab_client.projects.get.side_effect = ConnectionError("Persistent error")

        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        with patch("time.sleep"):
            result = detector.check_remote_duplicate(
                package_name="test-pkg",
                version="1.0.0",
                filename="test.bin",
                checksum="a" * 64,
            )

        assert result is None
        assert "Proceeding without duplicate detection" in caplog.text

    @pytest.mark.timeout(60)
    def test_remote_duplicate_multiple_files_same_name(
        self, mock_gitlab_client, mock_project
    ):
        """Test multiple files with same name, verify correct one matched by checksum."""
        mock_package = MagicMock()
        mock_package.version = "1.0.0"
        mock_package.id = 1

        # Create multiple files with same name but different checksums
        mock_file1 = MagicMock()
        mock_file1.file_name = "test.bin"
        mock_file1.file_sha256 = "b" * 64
        mock_file1.id = 1001
        mock_file1.size = 1024

        mock_file2 = MagicMock()
        mock_file2.file_name = "test.bin"
        mock_file2.file_sha256 = "a" * 64  # This one matches
        mock_file2.id = 1002
        mock_file2.size = 2048

        mock_package_obj = MagicMock()
        mock_package_obj.package_files.list.return_value = [mock_file1, mock_file2]

        mock_gitlab_client.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = [mock_package]
        mock_project.packages.get.return_value = mock_package_obj

        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        result = detector.check_remote_duplicate(
            package_name="test-pkg",
            version="1.0.0",
            filename="test.bin",
            checksum="a" * 64,
        )

        assert result is not None
        assert result.sha256_checksum == "a" * 64
        assert result.file_id == 1002


class TestRegisterFile:
    """Test file registration in session."""

    @pytest.mark.timeout(60)
    def test_register_file_creates_fingerprint(self, mock_gitlab_client, tmp_path):
        """Test register file creates FileFingerprint with correct attributes."""
        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        test_file = tmp_path / "test.txt"
        test_file.write_bytes(b"content")
        checksum = "a" * 64

        detector.register_file(test_file, "target.txt", checksum)

        fingerprint = detector.session_registry.get("target.txt")
        assert fingerprint is not None
        assert isinstance(fingerprint, FileFingerprint)
        assert fingerprint.target_filename == "target.txt"
        assert fingerprint.sha256_checksum == checksum

    @pytest.mark.timeout(60)
    def test_register_file_adds_to_registry(self, mock_gitlab_client, tmp_path):
        """Test file added to session_registry with target_filename as key."""
        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        test_file = tmp_path / "test.txt"
        test_file.write_bytes(b"content")

        detector.register_file(test_file, "target.txt", "a" * 64)

        assert "target.txt" in detector.session_registry
        assert len(detector.session_registry) == 1

    @pytest.mark.timeout(60)
    def test_register_file_overwrites_existing(self, mock_gitlab_client, tmp_path):
        """Test register same target_filename twice, verify second overwrites first."""
        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_bytes(b"content1")
        file2.write_bytes(b"content2")

        detector.register_file(file1, "target.txt", "a" * 64)
        detector.register_file(file2, "target.txt", "b" * 64)

        assert len(detector.session_registry) == 1
        assert detector.session_registry["target.txt"].sha256_checksum == "b" * 64

    @pytest.mark.timeout(60)
    def test_register_file_uses_file_stats(self, mock_gitlab_client, tmp_path):
        """Test Path.stat() is used to extract file size correctly."""
        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        test_file = tmp_path / "test.txt"
        content = b"test content for size verification"
        test_file.write_bytes(content)

        detector.register_file(test_file, "target.txt", "a" * 64)

        fingerprint = detector.session_registry["target.txt"]
        assert fingerprint.file_size == len(content)

    @pytest.mark.timeout(60)
    def test_register_file_uses_current_timestamp(self, mock_gitlab_client, tmp_path):
        """Test time.time() is used to record timestamp."""
        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        test_file = tmp_path / "test.txt"
        test_file.write_bytes(b"content")

        mock_time = 1704067200.0  # Fixed timestamp

        with patch("glpkg.duplicate_detector.time.time", return_value=mock_time):
            detector.register_file(test_file, "target.txt", "a" * 64)

        fingerprint = detector.session_registry["target.txt"]
        assert fingerprint.timestamp == mock_time

    @pytest.mark.timeout(60)
    def test_register_file_logging(self, mock_gitlab_client, tmp_path, caplog):
        """Test registration is logged with checksum."""
        import logging

        caplog.set_level(logging.DEBUG)

        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        test_file = tmp_path / "test.txt"
        test_file.write_bytes(b"content")
        checksum = "abcd1234" + "e" * 56

        detector.register_file(test_file, "target.txt", checksum)

        assert "Registered file in session" in caplog.text
        assert "target.txt" in caplog.text
        assert "abcd1234" in caplog.text


class TestDuplicateDetectorIntegration:
    """Integration tests for complete workflows."""

    @pytest.mark.timeout(60)
    def test_workflow_register_then_check_session(self, mock_gitlab_client, tmp_path):
        """Test register file, then check for session duplicate, verify found."""
        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        # Create two files with same content
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        content = b"identical content"
        file1.write_bytes(content)
        file2.write_bytes(content)

        checksum = hashlib.sha256(content).hexdigest()

        # Register first file
        detector.register_file(file1, "target.txt", checksum)

        # Check second file for session duplicate
        result = detector.check_session_duplicate(file2, "target.txt")

        assert result is not None
        assert result.sha256_checksum == checksum

    @pytest.mark.timeout(60)
    def test_workflow_check_remote_then_register(
        self, mock_gitlab_client, mock_project, tmp_path
    ):
        """Test check remote (not found), register, check session (found)."""
        mock_gitlab_client.projects.get.return_value = mock_project
        mock_project.packages.list.return_value = []

        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        content = b"content"
        file1.write_bytes(content)
        file2.write_bytes(content)

        checksum = hashlib.sha256(content).hexdigest()

        # Check remote - not found
        remote_result = detector.check_remote_duplicate(
            package_name="test-pkg",
            version="1.0.0",
            filename="target.txt",
            checksum=checksum,
        )
        assert remote_result is None

        # Register file
        detector.register_file(file1, "target.txt", checksum)

        # Check session - found
        session_result = detector.check_session_duplicate(file2, "target.txt")
        assert session_result is not None

    @pytest.mark.timeout(60)
    def test_workflow_multiple_files_different_names(self, mock_gitlab_client, tmp_path):
        """Test register multiple files with different names, verify all tracked."""
        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        files = []
        for i in range(5):
            f = tmp_path / f"file{i}.txt"
            f.write_bytes(f"content {i}".encode())
            files.append(f)
            detector.register_file(f, f"target{i}.txt", f"{'a' * 63}{i}")

        assert len(detector.session_registry) == 5
        for i in range(5):
            assert f"target{i}.txt" in detector.session_registry

    @pytest.mark.timeout(60)
    def test_workflow_session_registry_size(self, mock_gitlab_client, tmp_path):
        """Test register N files, verify session_registry has N entries."""
        detector = DuplicateDetector(mock_gitlab_client, project_id=12345)

        n = 10
        for i in range(n):
            f = tmp_path / f"file{i}.txt"
            f.write_bytes(f"content {i}".encode())
            detector.register_file(f, f"target{i}.txt", f"{'a' * 63}{i}")

        assert len(detector.session_registry) == n
