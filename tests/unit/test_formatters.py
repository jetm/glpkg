"""
Comprehensive unit tests for the formatters module.

These tests validate the output formatting functionality including terminal
detection, rich console output, JSON output, plain text output, error
formatting, and progress display.

All Rich console/spinner dependencies are mocked to prevent real terminal
rendering and ensure all output is captured via StringIO/mocks.
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.gitlab_pkg_upload.formatters import (
    OutputFormatter,
    detect_color_support,
    detect_tty,
    detect_unicode_support,
    display_progress,
    format_error,
    get_formatter,
)
from src.gitlab_pkg_upload.models import (
    DuplicatePolicy,
    GitLabUploadError,
    UploadConfig,
    UploadResult,
)
from tests.utils.test_helpers import validate_json_result

# Mark these as fast unit tests
pytestmark = [pytest.mark.fast, pytest.mark.unit]


# =============================================================================
# Mock Console and Status Classes
# =============================================================================


class MockConsole:
    """Mock Console that captures output to a StringIO buffer without terminal rendering."""

    def __init__(self, *args, **kwargs):
        self._buffer = io.StringIO()
        self._force_terminal = kwargs.get("force_terminal", False)
        self._file = kwargs.get("file", self._buffer)

    def print(self, *args, **kwargs):
        """Capture print output to buffer."""
        text = " ".join(str(arg) for arg in args)
        self._file.write(text + "\n")

    def rule(self, title="", **kwargs):
        """Capture rule output."""
        self._file.write(f"--- {title} ---\n")

    def status(self, message, **kwargs):
        """Return a mock status context manager."""
        return MockStatus(message, console=self)

    def getvalue(self):
        """Get captured output."""
        if hasattr(self._file, "getvalue"):
            return self._file.getvalue()
        return self._buffer.getvalue()


class MockStatus:
    """Mock Status that doesn't perform real terminal rendering."""

    def __init__(self, message="", console=None, **kwargs):
        self._message = message
        self._console = console
        self._started = False

    def __enter__(self):
        self._started = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._started = False
        return False

    def start(self):
        self._started = True

    def stop(self):
        self._started = False

    def update(self, message):
        self._message = message


@pytest.fixture
def mock_rich_console():
    """Fixture that patches rich.console.Console with MockConsole."""
    with patch("rich.console.Console", MockConsole):
        with patch("src.gitlab_pkg_upload.formatters.Console", MockConsole):
            yield MockConsole


@pytest.fixture
def mock_rich_status():
    """Fixture that patches rich.status.Status with MockStatus."""
    with patch("rich.status.Status", MockStatus):
        with patch("src.gitlab_pkg_upload.formatters.Status", MockStatus):
            yield MockStatus


# =============================================================================
# Helper Functions and Fixtures
# =============================================================================


def create_upload_config(
    package_name: str = "test-package",
    version: str = "1.0.0",
    duplicate_policy: DuplicatePolicy = DuplicatePolicy.SKIP,
    retry_count: int = 3,
    verbosity: str = "normal",
    dry_run: bool = False,
    fail_fast: bool = False,
    json_output: bool = False,
    plain_output: bool = False,
    gitlab_url: str = "https://gitlab.com",
    token: Optional[str] = "test-token",
) -> UploadConfig:
    """Factory function to create UploadConfig with customizable parameters."""
    return UploadConfig(
        package_name=package_name,
        version=version,
        duplicate_policy=duplicate_policy,
        retry_count=retry_count,
        verbosity=verbosity,
        dry_run=dry_run,
        fail_fast=fail_fast,
        json_output=json_output,
        plain_output=plain_output,
        gitlab_url=gitlab_url,
        token=token,
    )


def create_upload_result(
    source_path: str = "/path/to/file.txt",
    target_filename: str = "file.txt",
    success: bool = True,
    result: str = "https://gitlab.com/api/v4/projects/1/packages/generic/test/1.0.0/file.txt",
    was_duplicate: bool = False,
    duplicate_action: Optional[str] = None,
    existing_url: Optional[str] = None,
) -> UploadResult:
    """Factory function to create UploadResult with customizable parameters."""
    return UploadResult(
        source_path=source_path,
        target_filename=target_filename,
        success=success,
        result=result,
        was_duplicate=was_duplicate,
        duplicate_action=duplicate_action,
        existing_url=existing_url,
    )


def assert_no_ansi_codes(text: str) -> None:
    """Helper to verify string contains no ANSI escape sequences."""
    # ANSI escape code pattern
    ansi_pattern = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
    matches = ansi_pattern.findall(text)
    assert not matches, f"Found ANSI escape codes in text: {matches}"


def assert_valid_json(text: str) -> Dict[str, Any]:
    """Helper to parse and validate JSON structure."""
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        pytest.fail(f"Invalid JSON: {e}\nText: {text}")


@contextmanager
def capture_stdout() -> Generator[io.StringIO, None, None]:
    """Context manager to capture stdout."""
    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    try:
        yield captured
    finally:
        sys.stdout = old_stdout


@contextmanager
def capture_stderr() -> Generator[io.StringIO, None, None]:
    """Context manager to capture stderr."""
    captured = io.StringIO()
    old_stderr = sys.stderr
    sys.stderr = captured
    try:
        yield captured
    finally:
        sys.stderr = old_stderr


@pytest.fixture
def mock_upload_config() -> UploadConfig:
    """Fixture that returns a basic UploadConfig instance with default values."""
    return create_upload_config()


@pytest.fixture
def mock_upload_results() -> List[UploadResult]:
    """Fixture that returns a list of mock UploadResult objects with various scenarios."""
    return [
        # Successful new upload
        create_upload_result(
            source_path="/path/to/file1.txt",
            target_filename="file1.txt",
            success=True,
            result="https://gitlab.com/api/v4/projects/1/packages/generic/test/1.0.0/file1.txt",
        ),
        # Successful replaced duplicate
        create_upload_result(
            source_path="/path/to/file2.txt",
            target_filename="file2.txt",
            success=True,
            result="https://gitlab.com/api/v4/projects/1/packages/generic/test/1.0.0/file2.txt",
            was_duplicate=True,
            duplicate_action="replaced",
            existing_url="https://gitlab.com/old/file2.txt",
        ),
        # Skipped duplicate
        create_upload_result(
            source_path="/path/to/file3.txt",
            target_filename="file3.txt",
            success=True,
            result="Skipped: duplicate detected",
            was_duplicate=True,
            duplicate_action="skipped",
            existing_url="https://gitlab.com/existing/file3.txt",
        ),
        # Failed upload
        create_upload_result(
            source_path="/path/to/file4.txt",
            target_filename="file4.txt",
            success=False,
            result="Upload failed: network error",
        ),
    ]


@pytest.fixture
def clean_env():
    """Fixture that provides a clean environment for terminal detection tests."""
    # Save original environment
    original_env = os.environ.copy()

    # Remove terminal-related variables
    vars_to_remove = [
        "NO_COLOR", "FORCE_COLOR", "COLORTERM", "TERM",
        "WT_SESSION", "ANSICON", "ConEmuANSI",
        "LANG", "LC_ALL",
    ]
    for var in vars_to_remove:
        os.environ.pop(var, None)

    yield

    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


# =============================================================================
# Test Classes
# =============================================================================


class TestTerminalDetection:
    """Tests for terminal detection functions."""

    @pytest.mark.timeout(60)
    def test_detect_tty_when_stdout_is_tty(self):
        """Test detect_tty returns True when stdout.isatty() returns True."""
        mock_stdout = Mock()
        mock_stdout.isatty.return_value = True

        with patch.object(sys, "stdout", mock_stdout):
            assert detect_tty() is True

    @pytest.mark.timeout(60)
    def test_detect_tty_when_stdout_is_not_tty(self):
        """Test detect_tty returns False when stdout.isatty() returns False."""
        mock_stdout = Mock()
        mock_stdout.isatty.return_value = False

        with patch.object(sys, "stdout", mock_stdout):
            assert detect_tty() is False

    @pytest.mark.timeout(60)
    def test_detect_tty_when_stdout_is_none(self):
        """Test detect_tty returns False when stdout is None."""
        with patch.object(sys, "stdout", None):
            assert detect_tty() is False

    @pytest.mark.timeout(60)
    def test_detect_tty_when_isatty_missing(self):
        """Test detect_tty returns False when stdout lacks isatty attribute."""
        mock_stdout = object()  # Object without isatty

        with patch.object(sys, "stdout", mock_stdout):
            assert detect_tty() is False

    @pytest.mark.timeout(60)
    def test_detect_tty_when_exception_raised(self):
        """Test detect_tty returns False when isatty() raises exception."""
        mock_stdout = Mock()
        mock_stdout.isatty.side_effect = OSError("Permission denied")

        with patch.object(sys, "stdout", mock_stdout):
            assert detect_tty() is False

    @pytest.mark.timeout(60)
    def test_detect_color_support_with_no_color_env(self, clean_env):
        """Test detect_color_support returns False when NO_COLOR is set."""
        os.environ["NO_COLOR"] = "1"

        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=True):
            assert detect_color_support() is False

    @pytest.mark.timeout(60)
    def test_detect_color_support_with_force_color_env(self, clean_env):
        """Test detect_color_support returns True when FORCE_COLOR is set."""
        os.environ["FORCE_COLOR"] = "1"

        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=True):
            assert detect_color_support() is True

    @pytest.mark.timeout(60)
    def test_detect_color_support_with_colorterm_env(self, clean_env):
        """Test detect_color_support returns True when COLORTERM is set."""
        os.environ["COLORTERM"] = "truecolor"

        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=True):
            assert detect_color_support() is True

    @pytest.mark.timeout(60)
    def test_detect_color_support_with_term_color(self, clean_env):
        """Test detect_color_support returns True when TERM contains color."""
        os.environ["TERM"] = "xterm-256color"

        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=True):
            assert detect_color_support() is True

    @pytest.mark.timeout(60)
    def test_detect_color_support_without_tty(self, clean_env):
        """Test detect_color_support returns False when not in a TTY."""
        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=False):
            assert detect_color_support() is False

    @pytest.mark.timeout(60)
    def test_detect_color_support_windows_wt_session(self, clean_env):
        """Test detect_color_support returns True on Windows with WT_SESSION."""
        os.environ["WT_SESSION"] = "some-session-id"

        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=True):
            with patch.object(sys, "platform", "win32"):
                assert detect_color_support() is True

    @pytest.mark.timeout(60)
    def test_detect_color_support_windows_ansicon(self, clean_env):
        """Test detect_color_support returns True on Windows with ANSICON."""
        os.environ["ANSICON"] = "1"

        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=True):
            with patch.object(sys, "platform", "win32"):
                assert detect_color_support() is True

    @pytest.mark.timeout(60)
    def test_detect_color_support_precedence(self, clean_env):
        """Test that NO_COLOR takes precedence over FORCE_COLOR."""
        os.environ["NO_COLOR"] = "1"
        os.environ["FORCE_COLOR"] = "1"

        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=True):
            assert detect_color_support() is False

    @pytest.mark.timeout(60)
    def test_detect_unicode_support_with_utf8_encoding(self, clean_env):
        """Test detect_unicode_support returns True with UTF-8 encoding."""
        mock_stdout = Mock()
        mock_stdout.encoding = "utf-8"
        mock_stdout.isatty.return_value = True

        with patch.object(sys, "stdout", mock_stdout):
            assert detect_unicode_support() is True

    @pytest.mark.timeout(60)
    def test_detect_unicode_support_with_lang_utf8(self, clean_env):
        """Test detect_unicode_support returns True with UTF-8 LANG."""
        os.environ["LANG"] = "en_US.UTF-8"
        mock_stdout = Mock()
        mock_stdout.encoding = "ascii"  # Non-UTF8
        mock_stdout.isatty.return_value = True

        with patch.object(sys, "stdout", mock_stdout):
            assert detect_unicode_support() is True

    @pytest.mark.timeout(60)
    def test_detect_unicode_support_with_lc_all_utf8(self, clean_env):
        """Test detect_unicode_support returns True with UTF-8 LC_ALL."""
        os.environ["LC_ALL"] = "en_US.UTF-8"
        mock_stdout = Mock()
        mock_stdout.encoding = "ascii"  # Non-UTF8
        mock_stdout.isatty.return_value = True

        with patch.object(sys, "stdout", mock_stdout):
            assert detect_unicode_support() is True

    @pytest.mark.timeout(60)
    def test_detect_unicode_support_without_tty(self, clean_env):
        """Test detect_unicode_support returns False when not in a TTY."""
        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=False):
            assert detect_unicode_support() is False

    @pytest.mark.timeout(60)
    def test_detect_unicode_support_with_ascii_encoding(self, clean_env):
        """Test detect_unicode_support returns False with ASCII encoding."""
        mock_stdout = Mock()
        mock_stdout.encoding = "ascii"
        mock_stdout.isatty.return_value = True

        with patch.object(sys, "stdout", mock_stdout):
            assert detect_unicode_support() is False


class TestOutputFormatterInit:
    """Tests for OutputFormatter initialization."""

    @pytest.mark.timeout(60)
    def test_init_with_plain_output_flag(self, mock_rich_console):
        """Test OutputFormatter with plain_output=True disables all capabilities."""
        config = create_upload_config(plain_output=True)
        formatter = OutputFormatter(config)

        assert formatter.is_tty is False
        assert formatter.supports_color is False
        assert formatter.supports_unicode is False

    @pytest.mark.timeout(60)
    def test_init_without_plain_output_flag(self, mock_rich_console):
        """Test OutputFormatter detects terminal capabilities when plain_output=False."""
        config = create_upload_config(plain_output=False)

        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=True):
            with patch("src.gitlab_pkg_upload.formatters.detect_color_support", return_value=True):
                with patch("src.gitlab_pkg_upload.formatters.detect_unicode_support", return_value=True):
                    formatter = OutputFormatter(config)

                    assert formatter.is_tty is True
                    assert formatter.supports_color is True
                    assert formatter.supports_unicode is True

    @pytest.mark.timeout(60)
    def test_init_console_configuration(self, mock_rich_console):
        """Test Console is initialized with correct parameters."""
        config = create_upload_config(plain_output=True)
        formatter = OutputFormatter(config)

        # Check that console was created (using MockConsole)
        assert formatter.console is not None
        assert isinstance(formatter.console, MockConsole)

    @pytest.mark.timeout(60)
    def test_init_with_json_output_flag(self, mock_rich_console):
        """Test OutputFormatter initializes correctly with json_output=True."""
        config = create_upload_config(json_output=True)

        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=True):
            formatter = OutputFormatter(config)

            assert formatter.config.json_output is True

    @pytest.mark.timeout(60)
    def test_init_stores_config(self, mock_rich_console):
        """Test that OutputFormatter stores the config reference."""
        config = create_upload_config()
        formatter = OutputFormatter(config)

        assert formatter.config is config


class TestRichOutputFormatting:
    """Tests for rich console output formatting."""

    @pytest.mark.timeout(60)
    def test_format_rich_output_successful_uploads(self, mock_rich_console):
        """Test rich output displays successful uploads correctly."""
        config = create_upload_config(plain_output=False)

        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=True):
            with patch("src.gitlab_pkg_upload.formatters.detect_color_support", return_value=True):
                with patch("src.gitlab_pkg_upload.formatters.detect_unicode_support", return_value=True):
                    formatter = OutputFormatter(config)

        results = [
            create_upload_result(
                source_path="/path/to/file.txt",
                target_filename="file.txt",
                success=True,
                result="https://gitlab.com/download/file.txt",
            )
        ]

        # Capture the console output using MockConsole
        captured = io.StringIO()
        formatter.console = MockConsole(file=captured, force_terminal=True)

        formatter._format_rich_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        assert "Successful Uploads" in output
        assert "file.txt" in output

    @pytest.mark.timeout(60)
    def test_format_rich_output_skipped_duplicates(self, mock_rich_console):
        """Test rich output displays skipped duplicates correctly."""
        config = create_upload_config(plain_output=False)

        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=True):
            formatter = OutputFormatter(config)

        results = [
            create_upload_result(
                source_path="/path/to/file.txt",
                target_filename="file.txt",
                success=True,
                result="Skipped: duplicate",
                was_duplicate=True,
                duplicate_action="skipped",
                existing_url="https://gitlab.com/existing/file.txt",
            )
        ]

        captured = io.StringIO()
        formatter.console = MockConsole(file=captured, force_terminal=True)

        formatter._format_rich_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        assert "Skipped Duplicates" in output

    @pytest.mark.timeout(60)
    def test_format_rich_output_failed_uploads(self, mock_rich_console):
        """Test rich output displays failed uploads correctly."""
        config = create_upload_config(plain_output=False)

        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=True):
            formatter = OutputFormatter(config)

        results = [
            create_upload_result(
                source_path="/path/to/file.txt",
                target_filename="file.txt",
                success=False,
                result="Upload failed: network error",
            )
        ]

        captured = io.StringIO()
        formatter.console = MockConsole(file=captured, force_terminal=True)

        formatter._format_rich_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        assert "Failed Uploads" in output
        assert "network error" in output

    @pytest.mark.timeout(60)
    def test_format_rich_output_replaced_duplicates(self, mock_rich_console):
        """Test rich output displays replaced duplicates correctly."""
        config = create_upload_config(plain_output=False)

        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=True):
            formatter = OutputFormatter(config)

        results = [
            create_upload_result(
                source_path="/path/to/file.txt",
                target_filename="file.txt",
                success=True,
                result="https://gitlab.com/download/file.txt",
                was_duplicate=True,
                duplicate_action="replaced",
                existing_url="https://gitlab.com/old/file.txt",
            )
        ]

        captured = io.StringIO()
        formatter.console = MockConsole(file=captured, force_terminal=True)

        formatter._format_rich_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        assert "Replaced existing duplicate" in output
        assert "Previous URL" in output

    @pytest.mark.timeout(60)
    def test_format_rich_output_statistics(self, mock_upload_results, mock_rich_console):
        """Test rich output displays statistics correctly."""
        config = create_upload_config(plain_output=False)

        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=True):
            formatter = OutputFormatter(config)

        captured = io.StringIO()
        formatter.console = MockConsole(file=captured, force_terminal=True)

        formatter._format_rich_output(mock_upload_results, "test-package", "1.0.0")

        output = captured.getvalue()
        assert "Duplicate Detection Statistics" in output
        assert "New uploads:" in output
        assert "Replaced duplicates:" in output
        assert "Skipped duplicates:" in output
        assert "Failed uploads:" in output
        assert "Total processed:" in output

    @pytest.mark.timeout(60)
    def test_format_rich_output_empty_results(self, mock_rich_console):
        """Test rich output handles empty results list."""
        config = create_upload_config(plain_output=False)

        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=True):
            formatter = OutputFormatter(config)

        captured = io.StringIO()
        formatter.console = MockConsole(file=captured, force_terminal=True)

        formatter._format_rich_output([], "test-package", "1.0.0")

        output = captured.getvalue()
        assert "Upload Summary" in output
        # Should show 0 in statistics
        assert "Total processed:" in output
        # MockConsole doesn't produce ANSI codes, so no stripping needed
        assert "Total processed: 0" in output

    @pytest.mark.timeout(60)
    def test_format_rich_output_all_successful(self, mock_rich_console):
        """Test rich output shows success message when all uploads succeed."""
        config = create_upload_config(plain_output=False)

        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=True):
            formatter = OutputFormatter(config)

        results = [
            create_upload_result(success=True),
            create_upload_result(
                source_path="/path/to/file2.txt",
                target_filename="file2.txt",
                success=True,
            ),
        ]

        captured = io.StringIO()
        formatter.console = MockConsole(file=captured, force_terminal=True)

        formatter._format_rich_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        assert "All files processed successfully" in output


class TestJsonOutputFormatting:
    """Tests for JSON output formatting."""

    @pytest.mark.timeout(60)
    def test_format_json_output_successful_uploads(self, mock_rich_console):
        """Test JSON output structure for successful uploads."""
        config = create_upload_config(json_output=True)
        formatter = OutputFormatter(config)

        results = [
            create_upload_result(
                source_path="/path/to/file.txt",
                target_filename="file.txt",
                success=True,
                result="https://gitlab.com/download/file.txt",
            )
        ]

        with capture_stdout() as captured:
            formatter._format_json_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        json_data = assert_valid_json(output)

        assert json_data["success"] is True
        assert len(json_data["successful_uploads"]) == 1
        assert json_data["successful_uploads"][0]["target_filename"] == "file.txt"

    @pytest.mark.timeout(60)
    def test_format_json_output_with_skipped_duplicates(self, mock_rich_console):
        """Test JSON output includes skipped duplicates array."""
        config = create_upload_config(json_output=True)
        formatter = OutputFormatter(config)

        results = [
            create_upload_result(
                source_path="/path/to/file.txt",
                target_filename="file.txt",
                success=True,
                result="Skipped: duplicate",
                was_duplicate=True,
                duplicate_action="skipped",
                existing_url="https://gitlab.com/existing/file.txt",
            )
        ]

        with capture_stdout() as captured:
            formatter._format_json_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        json_data = assert_valid_json(output)

        assert len(json_data["skipped_duplicates"]) == 1
        assert json_data["skipped_duplicates"][0]["duplicate_action"] == "skipped"
        assert json_data["skipped_duplicates"][0]["existing_url"] == "https://gitlab.com/existing/file.txt"

    @pytest.mark.timeout(60)
    def test_format_json_output_with_failed_uploads(self, mock_rich_console):
        """Test JSON output includes failed_uploads array and error fields."""
        config = create_upload_config(json_output=True)
        formatter = OutputFormatter(config)

        results = [
            create_upload_result(
                source_path="/path/to/file.txt",
                target_filename="file.txt",
                success=False,
                result="Upload failed: network error",
            )
        ]

        with capture_stdout() as captured:
            formatter._format_json_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        json_data = assert_valid_json(output)

        assert json_data["success"] is False
        assert len(json_data["failed_uploads"]) == 1
        assert "error" in json_data
        assert "error_type" in json_data

    @pytest.mark.timeout(60)
    def test_format_json_output_statistics_accuracy(self, mock_upload_results, mock_rich_console):
        """Test JSON output statistics match actual counts."""
        config = create_upload_config(json_output=True)
        formatter = OutputFormatter(config)

        with capture_stdout() as captured:
            formatter._format_json_output(mock_upload_results, "test-package", "1.0.0")

        output = captured.getvalue()
        json_data = assert_valid_json(output)

        stats = json_data["statistics"]
        # mock_upload_results has: 1 new upload, 1 replaced, 1 skipped, 1 failed
        assert stats["total_processed"] == 4
        assert stats["new_uploads"] == 1
        assert stats["replaced_duplicates"] == 1
        assert stats["skipped_duplicates"] == 1
        assert stats["failed_uploads"] == 1

    @pytest.mark.timeout(60)
    def test_format_json_output_duplicate_metadata(self, mock_rich_console):
        """Test JSON output includes duplicate detection metadata."""
        config = create_upload_config(json_output=True)
        formatter = OutputFormatter(config)

        results = [
            create_upload_result(
                source_path="/path/to/file.txt",
                target_filename="file.txt",
                success=True,
                result="https://gitlab.com/download/file.txt",
                was_duplicate=True,
                duplicate_action="replaced",
                existing_url="https://gitlab.com/old/file.txt",
            )
        ]

        with capture_stdout() as captured:
            formatter._format_json_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        json_data = assert_valid_json(output)

        upload = json_data["successful_uploads"][0]
        assert upload["was_duplicate"] is True
        assert upload["duplicate_action"] == "replaced"
        assert upload["existing_url"] == "https://gitlab.com/old/file.txt"

    @pytest.mark.timeout(60)
    def test_format_json_output_exit_code_success(self, mock_rich_console):
        """Test JSON output has exit_code=0 when no failures."""
        config = create_upload_config(json_output=True)
        formatter = OutputFormatter(config)

        results = [create_upload_result(success=True)]

        with capture_stdout() as captured:
            formatter._format_json_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        json_data = assert_valid_json(output)

        assert json_data["exit_code"] == 0

    @pytest.mark.timeout(60)
    def test_format_json_output_exit_code_failure(self, mock_rich_console):
        """Test JSON output has exit_code=1 when failures exist."""
        config = create_upload_config(json_output=True)
        formatter = OutputFormatter(config)

        results = [create_upload_result(success=False, result="Error")]

        with capture_stdout() as captured:
            formatter._format_json_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        json_data = assert_valid_json(output)

        assert json_data["exit_code"] == 1

    @pytest.mark.timeout(60)
    def test_format_json_output_required_fields(self, mock_rich_console):
        """Test JSON output contains all required fields."""
        config = create_upload_config(json_output=True)
        formatter = OutputFormatter(config)

        results = [create_upload_result()]

        with capture_stdout() as captured:
            formatter._format_json_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        json_data = assert_valid_json(output)

        required_fields = [
            "success", "exit_code", "package_name", "version",
            "successful_uploads", "statistics"
        ]
        for field in required_fields:
            assert field in json_data, f"Missing required field: {field}"

    @pytest.mark.timeout(60)
    def test_format_json_output_goes_to_stdout(self, mock_rich_console):
        """Test JSON output is printed to stdout, not stderr."""
        config = create_upload_config(json_output=True)
        formatter = OutputFormatter(config)

        results = [create_upload_result()]

        with capture_stdout() as stdout_captured:
            with capture_stderr() as stderr_captured:
                formatter._format_json_output(results, "test-package", "1.0.0")

        stdout_output = stdout_captured.getvalue()
        stderr_output = stderr_captured.getvalue()

        # JSON should be in stdout
        assert stdout_output.strip().startswith("{")
        # stderr should be empty or contain only logs
        assert "success" not in stderr_output

    @pytest.mark.timeout(60)
    def test_format_json_output_validation(self, mock_rich_console):
        """Test JSON output can be validated with validate_json_result helper."""
        config = create_upload_config(json_output=True)
        formatter = OutputFormatter(config)

        results = [
            create_upload_result(
                source_path="/path/to/file.txt",
                target_filename="file.txt",
                success=True,
            )
        ]

        with capture_stdout() as captured:
            formatter._format_json_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        json_data = json.loads(output)

        # Use the helper from test_helpers
        is_valid = validate_json_result(
            json_data,
            expected_success=True,
            expected_files=["file.txt"]
        )
        assert is_valid

    @pytest.mark.timeout(60)
    def test_format_json_output_multiple_failures_error_message(self, mock_rich_console):
        """Test JSON output error message for multiple failures."""
        config = create_upload_config(json_output=True)
        formatter = OutputFormatter(config)

        results = [
            create_upload_result(
                source_path="/path/to/file1.txt",
                target_filename="file1.txt",
                success=False,
                result="Error 1",
            ),
            create_upload_result(
                source_path="/path/to/file2.txt",
                target_filename="file2.txt",
                success=False,
                result="Error 2",
            ),
        ]

        with capture_stdout() as captured:
            formatter._format_json_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        json_data = assert_valid_json(output)

        assert "2 file(s) failed" in json_data["error"]


class TestPlainTextOutputFormatting:
    """Tests for plain text output formatting."""

    @pytest.mark.timeout(60)
    def test_format_plain_output_successful_uploads(self, mock_rich_console):
        """Test plain output displays successful uploads with [OK] prefix."""
        config = create_upload_config(plain_output=True)
        formatter = OutputFormatter(config)

        results = [
            create_upload_result(
                source_path="/path/to/file.txt",
                target_filename="file.txt",
                success=True,
            )
        ]

        with capture_stdout() as captured:
            formatter._format_plain_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        assert "[OK] Successful Uploads" in output
        assert "file.txt" in output

    @pytest.mark.timeout(60)
    def test_format_plain_output_skipped_duplicates(self, mock_rich_console):
        """Test plain output displays skipped duplicates with [SKIP] prefix."""
        config = create_upload_config(plain_output=True)
        formatter = OutputFormatter(config)

        results = [
            create_upload_result(
                success=True,
                result="Skipped",
                was_duplicate=True,
                duplicate_action="skipped",
            )
        ]

        with capture_stdout() as captured:
            formatter._format_plain_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        assert "[SKIP] Skipped Duplicates" in output

    @pytest.mark.timeout(60)
    def test_format_plain_output_failed_uploads(self, mock_rich_console):
        """Test plain output displays failed uploads with [FAIL] prefix."""
        config = create_upload_config(plain_output=True)
        formatter = OutputFormatter(config)

        results = [
            create_upload_result(
                success=False,
                result="Network error",
            )
        ]

        with capture_stdout() as captured:
            formatter._format_plain_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        assert "[FAIL] Failed Uploads" in output
        assert "Network error" in output

    @pytest.mark.timeout(60)
    def test_format_plain_output_no_color_codes(self, mock_rich_console):
        """Test plain output contains no ANSI escape sequences."""
        config = create_upload_config(plain_output=True)
        formatter = OutputFormatter(config)

        results = [
            create_upload_result(success=True),
            create_upload_result(success=False, result="Error"),
        ]

        with capture_stdout() as captured:
            formatter._format_plain_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        assert_no_ansi_codes(output)

    @pytest.mark.timeout(60)
    def test_format_plain_output_no_unicode_characters(self, mock_rich_console):
        """Test plain output uses only ASCII characters."""
        config = create_upload_config(plain_output=True)
        formatter = OutputFormatter(config)

        results = [
            create_upload_result(success=True),
            create_upload_result(success=False, result="Error"),
        ]

        with capture_stdout() as captured:
            formatter._format_plain_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        # Check that all characters are ASCII
        try:
            output.encode("ascii")
        except UnicodeEncodeError as e:
            pytest.fail(f"Plain output contains non-ASCII characters: {e}")

    @pytest.mark.timeout(60)
    def test_format_plain_output_statistics(self, mock_rich_console):
        """Test plain output displays statistics with asterisk bullets."""
        config = create_upload_config(plain_output=True)
        formatter = OutputFormatter(config)

        results = [create_upload_result(success=True)]

        with capture_stdout() as captured:
            formatter._format_plain_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        assert "Duplicate Detection Statistics:" in output
        assert "* New uploads:" in output
        assert "* Replaced duplicates:" in output
        assert "* Skipped duplicates:" in output
        assert "* Failed uploads:" in output

    @pytest.mark.timeout(60)
    def test_format_plain_output_replaced_duplicates(self, mock_rich_console):
        """Test plain output displays replacement action in plain text."""
        config = create_upload_config(plain_output=True)
        formatter = OutputFormatter(config)

        results = [
            create_upload_result(
                success=True,
                was_duplicate=True,
                duplicate_action="replaced",
                existing_url="https://gitlab.com/old/file.txt",
            )
        ]

        with capture_stdout() as captured:
            formatter._format_plain_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        assert "Action: Replaced existing duplicate" in output
        assert "Previous URL:" in output


class TestErrorFormatting:
    """Tests for error formatting functions."""

    @pytest.mark.timeout(60)
    def test_format_error_basic(self):
        """Test basic error formatting with error type and message."""
        error = ValueError("Invalid input")
        result = format_error(error)

        assert "ERROR: ValueError" in result
        assert "Invalid input" in result

    @pytest.mark.timeout(60)
    def test_format_error_with_context(self):
        """Test error formatting with context dictionary."""
        error = ValueError("Not found")
        context = {
            "operation": "upload",
            "project_path": "group/project",
            "gitlab_url": "https://gitlab.com",
        }
        result = format_error(error, context)

        assert "ERROR: ValueError" in result
        # Context should be included via enhance_error_message

    @pytest.mark.timeout(60)
    def test_format_error_gitlab_upload_error(self):
        """Test error formatting includes exit code for GitLabUploadError."""
        error = GitLabUploadError("Upload failed")
        result = format_error(error)

        assert "ERROR: GitLabUploadError" in result
        assert "Exit code:" in result

    @pytest.mark.timeout(60)
    def test_format_error_without_context(self):
        """Test error formatting without context uses basic formatting."""
        error = RuntimeError("Something went wrong")
        result = format_error(error)

        assert "ERROR: RuntimeError" in result
        assert "Something went wrong" in result

    @pytest.mark.timeout(60)
    def test_format_error_uses_enhance_error_message(self):
        """Test that enhance_error_message is called when context is provided."""
        error = ValueError("404 not found")
        context = {
            "operation": "fetch",
            "project_path": "group/project",
            "gitlab_url": "https://gitlab.com",
        }

        with patch("src.gitlab_pkg_upload.formatters.enhance_error_message") as mock_enhance:
            mock_enhance.return_value = "Enhanced error message"
            result = format_error(error, context)

            mock_enhance.assert_called_once_with(error, context)
            assert "Enhanced error message" in result

    @pytest.mark.timeout(60)
    def test_format_error_handles_exceptions_gracefully(self):
        """Test format_error doesn't crash on unusual exceptions."""
        # Create an exception with unusual attributes
        class CustomError(Exception):
            pass

        error = CustomError("Custom error message")
        result = format_error(error)

        assert "ERROR: CustomError" in result
        assert "Custom error message" in result


class TestProgressDisplay:
    """Tests for progress display functionality."""

    @pytest.mark.timeout(60)
    def test_create_progress_spinner_returns_status(self, mock_rich_console, mock_rich_status):
        """Test create_progress_spinner returns a Status-like object."""
        config = create_upload_config()

        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=True):
            formatter = OutputFormatter(config)

        spinner = formatter.create_progress_spinner("Loading...")
        # MockStatus should be returned
        assert spinner is not None
        assert hasattr(spinner, "__enter__")  # Should be a context manager
        assert hasattr(spinner, "__exit__")

    @pytest.mark.timeout(60)
    def test_create_progress_spinner_with_message(self, mock_rich_console, mock_rich_status):
        """Test create_progress_spinner accepts custom message."""
        config = create_upload_config()

        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=True):
            formatter = OutputFormatter(config)

        message = "Uploading files..."
        spinner = formatter.create_progress_spinner(message)

        # The Status object should have been created with our message
        assert spinner is not None

    @pytest.mark.timeout(60)
    def test_create_progress_spinner_plain_output_mode(self, mock_rich_console, mock_rich_status):
        """Test spinner is created but doesn't display in plain output mode."""
        config = create_upload_config(plain_output=True)
        formatter = OutputFormatter(config)

        spinner = formatter.create_progress_spinner("Loading...")
        # Should still return a Status-like object, just won't display
        assert spinner is not None

    @pytest.mark.timeout(60)
    def test_create_progress_spinner_non_tty(self, mock_rich_console, mock_rich_status):
        """Test spinner creation when is_tty is False."""
        config = create_upload_config(plain_output=False)

        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=False):
            formatter = OutputFormatter(config)

        spinner = formatter.create_progress_spinner("Loading...")
        assert spinner is not None

    @pytest.mark.timeout(60)
    def test_create_progress_spinner_as_context_manager(self, mock_rich_console, mock_rich_status):
        """Test spinner works as a context manager."""
        config = create_upload_config(plain_output=True)
        formatter = OutputFormatter(config)

        # Use MockConsole to avoid actual output
        formatter.console = MockConsole(file=io.StringIO(), force_terminal=False)

        # Should not raise an exception
        with formatter.create_progress_spinner("Loading..."):
            pass

    @pytest.mark.timeout(60)
    def test_display_progress_function(self, mock_rich_console, mock_rich_status):
        """Test standalone display_progress function delegates to formatter."""
        config = create_upload_config()

        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=True):
            formatter = OutputFormatter(config)

        spinner = display_progress(formatter, "Processing...")
        # Should return a Status-like object
        assert spinner is not None
        assert hasattr(spinner, "__enter__")


class TestOutputFormatSelection:
    """Tests for output format selection logic."""

    @pytest.mark.timeout(60)
    def test_format_output_selects_json_when_json_output_true(self, mock_rich_console):
        """Test format_output calls JSON formatter when json_output=True."""
        config = create_upload_config(json_output=True)
        formatter = OutputFormatter(config)

        results = [create_upload_result()]

        with patch.object(formatter, "_format_json_output") as mock_json:
            with patch.object(formatter, "_format_plain_output") as mock_plain:
                with patch.object(formatter, "_format_rich_output") as mock_rich:
                    formatter.format_output(results, "test-package", "1.0.0")

                    mock_json.assert_called_once()
                    mock_plain.assert_not_called()
                    mock_rich.assert_not_called()

    @pytest.mark.timeout(60)
    def test_format_output_selects_plain_when_plain_output_true(self, mock_rich_console):
        """Test format_output calls plain formatter when plain_output=True."""
        config = create_upload_config(plain_output=True)
        formatter = OutputFormatter(config)

        results = [create_upload_result()]

        with patch.object(formatter, "_format_json_output") as mock_json:
            with patch.object(formatter, "_format_plain_output") as mock_plain:
                with patch.object(formatter, "_format_rich_output") as mock_rich:
                    formatter.format_output(results, "test-package", "1.0.0")

                    mock_json.assert_not_called()
                    mock_plain.assert_called_once()
                    mock_rich.assert_not_called()

    @pytest.mark.timeout(60)
    def test_format_output_selects_plain_when_not_tty(self, mock_rich_console):
        """Test format_output calls plain formatter when not in TTY."""
        config = create_upload_config(plain_output=False, json_output=False)

        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=False):
            formatter = OutputFormatter(config)

        results = [create_upload_result()]

        with patch.object(formatter, "_format_json_output") as mock_json:
            with patch.object(formatter, "_format_plain_output") as mock_plain:
                with patch.object(formatter, "_format_rich_output") as mock_rich:
                    formatter.format_output(results, "test-package", "1.0.0")

                    mock_json.assert_not_called()
                    mock_plain.assert_called_once()
                    mock_rich.assert_not_called()

    @pytest.mark.timeout(60)
    def test_format_output_selects_rich_when_tty(self, mock_rich_console):
        """Test format_output calls rich formatter when in TTY."""
        config = create_upload_config(plain_output=False, json_output=False)

        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=True):
            with patch("src.gitlab_pkg_upload.formatters.detect_color_support", return_value=True):
                formatter = OutputFormatter(config)

        results = [create_upload_result()]

        with patch.object(formatter, "_format_json_output") as mock_json:
            with patch.object(formatter, "_format_plain_output") as mock_plain:
                with patch.object(formatter, "_format_rich_output") as mock_rich:
                    formatter.format_output(results, "test-package", "1.0.0")

                    mock_json.assert_not_called()
                    mock_plain.assert_not_called()
                    mock_rich.assert_called_once()

    @pytest.mark.timeout(60)
    def test_format_output_json_takes_precedence(self, mock_rich_console):
        """Test JSON output takes precedence over plain output."""
        config = create_upload_config(json_output=True, plain_output=True)
        formatter = OutputFormatter(config)

        results = [create_upload_result()]

        with patch.object(formatter, "_format_json_output") as mock_json:
            with patch.object(formatter, "_format_plain_output") as mock_plain:
                formatter.format_output(results, "test-package", "1.0.0")

                mock_json.assert_called_once()
                mock_plain.assert_not_called()


class TestOutputFormatterIntegration:
    """Integration tests for OutputFormatter end-to-end workflows."""

    @pytest.mark.timeout(60)
    def test_full_workflow_rich_output(self, mock_upload_results, mock_rich_console):
        """Test complete rich output workflow."""
        config = create_upload_config(plain_output=False)

        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=True):
            with patch("src.gitlab_pkg_upload.formatters.detect_color_support", return_value=True):
                formatter = OutputFormatter(config)

        captured = io.StringIO()
        formatter.console = MockConsole(file=captured, force_terminal=True)

        formatter.format_output(mock_upload_results, "test-package", "1.0.0")

        output = captured.getvalue()

        # Verify all sections are present
        assert "Upload Summary" in output
        assert "Successful Uploads" in output
        assert "Skipped Duplicates" in output
        assert "Failed Uploads" in output
        assert "Duplicate Detection Statistics" in output

    @pytest.mark.timeout(60)
    def test_full_workflow_json_output(self, mock_upload_results, mock_rich_console):
        """Test complete JSON output workflow."""
        config = create_upload_config(json_output=True)
        formatter = OutputFormatter(config)

        with capture_stdout() as captured:
            formatter.format_output(mock_upload_results, "test-package", "1.0.0")

        output = captured.getvalue()
        json_data = assert_valid_json(output)

        # Verify JSON structure
        assert "success" in json_data
        assert "exit_code" in json_data
        assert "package_name" in json_data
        assert json_data["package_name"] == "test-package"
        assert "version" in json_data
        assert json_data["version"] == "1.0.0"

    @pytest.mark.timeout(60)
    def test_full_workflow_plain_output(self, mock_upload_results, mock_rich_console):
        """Test complete plain text output workflow."""
        config = create_upload_config(plain_output=True)
        formatter = OutputFormatter(config)

        with capture_stdout() as captured:
            formatter.format_output(mock_upload_results, "test-package", "1.0.0")

        output = captured.getvalue()

        # Verify plain text format
        assert_no_ansi_codes(output)
        assert "Upload Summary" in output
        assert "[OK]" in output or "[SKIP]" in output or "[FAIL]" in output

    @pytest.mark.timeout(60)
    def test_formatter_factory_function(self, mock_rich_console):
        """Test get_formatter factory function returns correct instance."""
        config = create_upload_config()
        formatter = get_formatter(config)

        assert isinstance(formatter, OutputFormatter)
        assert formatter.config is config

    @pytest.mark.timeout(60)
    def test_multiple_format_calls(self, mock_rich_console):
        """Test multiple format_output calls work correctly."""
        config = create_upload_config(json_output=True)
        formatter = OutputFormatter(config)

        results1 = [create_upload_result(target_filename="file1.txt")]
        results2 = [create_upload_result(target_filename="file2.txt")]

        with capture_stdout() as captured1:
            formatter.format_output(results1, "package1", "1.0.0")

        json1 = assert_valid_json(captured1.getvalue())
        assert json1["package_name"] == "package1"

        with capture_stdout() as captured2:
            formatter.format_output(results2, "package2", "2.0.0")

        json2 = assert_valid_json(captured2.getvalue())
        assert json2["package_name"] == "package2"


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.mark.timeout(60)
    def test_empty_results_list(self, mock_rich_console):
        """Test handling of empty results list in all format methods."""
        config = create_upload_config(json_output=True)
        formatter = OutputFormatter(config)

        with capture_stdout() as captured:
            formatter.format_output([], "test-package", "1.0.0")

        json_data = assert_valid_json(captured.getvalue())
        assert json_data["success"] is True
        assert json_data["statistics"]["total_processed"] == 0

    @pytest.mark.timeout(60)
    def test_very_long_filenames(self, mock_rich_console):
        """Test handling of extremely long filenames."""
        config = create_upload_config(plain_output=True)
        formatter = OutputFormatter(config)

        long_name = "a" * 500 + ".txt"
        results = [create_upload_result(target_filename=long_name)]

        with capture_stdout() as captured:
            formatter.format_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        # Should not crash and should contain the filename (possibly truncated)
        assert "a" in output

    @pytest.mark.timeout(60)
    def test_special_characters_in_paths(self, mock_rich_console):
        """Test handling of special characters in file paths."""
        config = create_upload_config(json_output=True)
        formatter = OutputFormatter(config)

        special_path = '/path/with spaces/and "quotes"/file.txt'
        results = [create_upload_result(source_path=special_path)]

        with capture_stdout() as captured:
            formatter.format_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        json_data = assert_valid_json(output)
        # JSON should properly escape special characters
        assert json_data["successful_uploads"][0]["source_path"] == special_path

    @pytest.mark.timeout(60)
    def test_unicode_in_error_messages(self, mock_rich_console):
        """Test handling of Unicode characters in error messages."""
        config = create_upload_config(json_output=True)
        formatter = OutputFormatter(config)

        unicode_error = "Error: файл не найден (file not found) 文件未找到"
        results = [create_upload_result(success=False, result=unicode_error)]

        with capture_stdout() as captured:
            formatter.format_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        json_data = assert_valid_json(output)
        # Unicode should be preserved in JSON
        assert unicode_error in json_data["failed_uploads"][0]["error_message"]

    @pytest.mark.timeout(60)
    def test_large_number_of_results(self, mock_rich_console):
        """Test handling of many upload results."""
        config = create_upload_config(json_output=True)
        formatter = OutputFormatter(config)

        # Create 100 results
        results = [
            create_upload_result(
                source_path=f"/path/to/file{i}.txt",
                target_filename=f"file{i}.txt",
            )
            for i in range(100)
        ]

        with capture_stdout() as captured:
            formatter.format_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        json_data = assert_valid_json(output)

        assert json_data["statistics"]["total_processed"] == 100
        assert len(json_data["successful_uploads"]) == 100

    @pytest.mark.timeout(60)
    def test_result_with_none_values(self, mock_rich_console):
        """Test handling of results with None optional fields."""
        config = create_upload_config(json_output=True)
        formatter = OutputFormatter(config)

        results = [
            create_upload_result(
                was_duplicate=False,
                duplicate_action=None,
                existing_url=None,
            )
        ]

        with capture_stdout() as captured:
            formatter.format_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        json_data = assert_valid_json(output)

        upload = json_data["successful_uploads"][0]
        assert upload["was_duplicate"] is False
        assert upload["duplicate_action"] is None
        assert upload["existing_url"] is None

    @pytest.mark.timeout(60)
    def test_mixed_success_and_failure_results(self, mock_rich_console):
        """Test proper categorization of mixed results."""
        config = create_upload_config(json_output=True)
        formatter = OutputFormatter(config)

        results = [
            create_upload_result(success=True, target_filename="success1.txt"),
            create_upload_result(success=False, target_filename="fail1.txt", result="Error 1"),
            create_upload_result(success=True, target_filename="success2.txt"),
            create_upload_result(success=False, target_filename="fail2.txt", result="Error 2"),
            create_upload_result(
                success=True,
                target_filename="skipped.txt",
                was_duplicate=True,
                duplicate_action="skipped",
            ),
        ]

        with capture_stdout() as captured:
            formatter.format_output(results, "test-package", "1.0.0")

        output = captured.getvalue()
        json_data = assert_valid_json(output)

        assert len(json_data["successful_uploads"]) == 2
        assert len(json_data["failed_uploads"]) == 2
        assert len(json_data["skipped_duplicates"]) == 1
        assert json_data["statistics"]["total_processed"] == 5

    @pytest.mark.timeout(60)
    def test_empty_package_name_and_version(self, mock_rich_console):
        """Test handling of empty package name and version."""
        config = create_upload_config(json_output=True)
        formatter = OutputFormatter(config)

        results = [create_upload_result()]

        with capture_stdout() as captured:
            formatter.format_output(results, "", "")

        output = captured.getvalue()
        json_data = assert_valid_json(output)

        assert json_data["package_name"] == ""
        assert json_data["version"] == ""

    @pytest.mark.timeout(60)
    def test_console_file_output_isolation(self, mock_rich_console):
        """Test that console output doesn't interfere with stdout capture."""
        config = create_upload_config(plain_output=False)

        with patch("src.gitlab_pkg_upload.formatters.detect_tty", return_value=True):
            formatter = OutputFormatter(config)

        # Redirect console to a separate buffer using MockConsole
        console_buffer = io.StringIO()
        formatter.console = MockConsole(file=console_buffer, force_terminal=True)

        results = [create_upload_result()]

        with capture_stdout() as stdout_buffer:
            formatter._format_rich_output(results, "test-package", "1.0.0")

        # Rich output should go to console_buffer, not stdout_buffer
        assert console_buffer.getvalue()  # Console got output
        assert not stdout_buffer.getvalue()  # stdout is empty
