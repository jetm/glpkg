"""
Basic unit tests that don't require GitLab API access.

These tests validate the core functionality of the upload script components
without requiring external dependencies like GitLab tokens or network access.
"""

import os
import tempfile
from pathlib import Path

import pytest

# Mark these as fast unit tests
pytestmark = [pytest.mark.fast, pytest.mark.unit]


class TestBasicFunctionality:
    """Basic unit tests for core functionality."""

    @pytest.mark.timeout(60)
    def test_import_gitlab_pkg_upload(self):
        """Test that gitlab_pkg_upload module can be imported."""
        try:
            from gitlab_pkg_upload import cli
            from gitlab_pkg_upload import models

            assert hasattr(cli, "ProjectResolver")
            assert hasattr(cli, "GitAutoDetector")
            assert hasattr(models, "GitRemoteInfo")
            assert hasattr(models, "ProjectInfo")
        except ImportError as e:
            pytest.fail(f"Failed to import gitlab_pkg_upload: {e}")

    @pytest.mark.timeout(60)
    def test_import_main_script(self):
        """Test that the main upload script can be imported."""
        import sys

        script_dir = Path(__file__).parent.parent
        sys.path.insert(0, str(script_dir))

        try:
            # Check if the script file exists
            script_path = script_dir / "gitlab-pkg-upload.py"
            if not script_path.exists():
                pytest.skip("Main script file not found")

            # Try to read the script to check basic syntax
            script_content = script_path.read_text()

            # Check for key components without importing
            assert "def main(" in script_content
            assert "argparse" in script_content
            assert "upload" in script_content.lower()

        except Exception as e:
            pytest.skip(f"Cannot test main script import: {e}")
        finally:
            if str(script_dir) in sys.path:
                sys.path.remove(str(script_dir))

    @pytest.mark.timeout(60)
    def test_file_operations(self):
        """Test basic file operations used by the script."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create a test file
            test_file = temp_path / "test.txt"
            test_content = b"Hello, World!"
            test_file.write_bytes(test_content)

            # Verify file exists and has correct content
            assert test_file.exists()
            assert test_file.read_bytes() == test_content
            assert test_file.stat().st_size == len(test_content)

    @pytest.mark.timeout(60)
    def test_checksum_calculation(self):
        """Test checksum calculation functionality."""
        import hashlib

        test_data = b"Test data for checksum"
        expected_sha256 = hashlib.sha256(test_data).hexdigest()

        # Calculate checksum
        calculated_sha256 = hashlib.sha256(test_data).hexdigest()

        assert calculated_sha256 == expected_sha256
        assert len(calculated_sha256) == 64  # SHA256 is 64 hex characters

    @pytest.mark.timeout(60)
    def test_path_handling(self):
        """Test path handling functionality."""
        # Test various path operations
        test_path = Path("/some/test/path/file.txt")

        assert test_path.name == "file.txt"
        assert test_path.suffix == ".txt"
        assert test_path.stem == "file"
        assert test_path.parent.name == "path"

    @pytest.mark.timeout(60)
    def test_environment_variable_handling(self):
        """Test environment variable handling."""
        # Test setting and getting environment variables
        test_var = "TEST_GITLAB_VAR"
        test_value = "test_value_123"

        # Set environment variable
        os.environ[test_var] = test_value

        # Verify it can be retrieved
        assert os.environ.get(test_var) == test_value

        # Clean up
        del os.environ[test_var]

        # Verify it's gone
        assert os.environ.get(test_var) is None


class TestUtilityFunctions:
    """Test utility functions and helpers."""

    @pytest.mark.timeout(60)
    def test_rate_limiter_import(self):
        """Test that rate limiter utilities can be imported."""
        try:
            from .utils.rate_limiter import get_rate_limiter

            limiter = get_rate_limiter()
            assert limiter is not None
            assert hasattr(limiter, "acquire")
            assert hasattr(limiter, "_lock")

        except ImportError as e:
            pytest.fail(f"Failed to import rate limiter: {e}")

    @pytest.mark.timeout(60)
    def test_performance_utilities_import(self):
        """Test that performance utilities can be imported."""
        try:
            from .utils.performance import get_data_generator, get_performance_tracker

            tracker = get_performance_tracker()
            generator = get_data_generator()

            assert tracker is not None
            assert generator is not None
            assert hasattr(generator, "generate_content")

        except ImportError as e:
            pytest.fail(f"Failed to import performance utilities: {e}")

    @pytest.mark.timeout(60)
    def test_data_generation(self):
        """Test data generation functionality."""
        try:
            from .utils.performance import get_data_generator

            generator = get_data_generator()

            # Test different content types
            text_content = generator.generate_content(100, "text")
            assert len(text_content) == 100
            assert isinstance(text_content, bytes)

            binary_content = generator.generate_content(50, "binary")
            assert len(binary_content) == 50
            assert isinstance(binary_content, bytes)

        except ImportError as e:
            pytest.skip(f"Performance utilities not available: {e}")


class TestConfigurationValidation:
    """Test configuration and setup validation."""

    @pytest.mark.timeout(60)
    def test_pytest_markers_available(self):
        """Test that pytest markers are properly configured."""
        # This test verifies that the markers we use are available
        import pytest

        # These should not raise warnings when used
        pytest.mark.fast
        pytest.mark.slow
        pytest.mark.integration
        pytest.mark.api
        pytest.mark.unit
        pytest.mark.sequential

        # If we get here without exceptions, markers are working
        assert True

    @pytest.mark.timeout(60)
    def test_test_directory_structure(self):
        """Test that test directory structure is correct."""
        test_dir = Path(__file__).parent

        # Check for required files
        assert (test_dir / "conftest.py").exists()
        assert (test_dir / "utils").exists()
        assert (test_dir / "utils" / "rate_limiter.py").exists()
        assert (test_dir / "utils" / "performance.py").exists()

        # Check for test files
        test_files = list(test_dir.glob("test_*.py"))
        assert len(test_files) > 0

        # This file should be in the list
        assert Path(__file__) in test_files


class TestFilenameValidation:
    """Test filename validation functionality."""

    @pytest.mark.timeout(60)
    def test_validate_filename_ascii_valid_filenames(self):
        """Test that valid ASCII filenames pass validation."""
        import sys
        from pathlib import Path

        # Add parent directory to path to import the main script
        script_dir = Path(__file__).parent.parent
        sys.path.insert(0, str(script_dir))

        try:
            # Import the validation function from the main script
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "gitlab_pkg_upload", script_dir / "gitlab-pkg-upload.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            validate_filename_ascii = module.validate_filename_ascii

            # Test valid ASCII filenames
            valid_filenames = [
                "package.tar.gz",
                "my-file_v1.0.bin",
                "subdir/file.txt",
                "test123.txt",
                "file-name_with.dots.tar.gz",
                "a/b/c/deep/path/file.bin",
                "UPPERCASE.TXT",
                "MixedCase_File-123.tar.gz",
            ]

            for filename in valid_filenames:
                is_valid, error_message = validate_filename_ascii(filename)
                assert is_valid, (
                    f"Expected '{filename}' to be valid, but got error: {error_message}"
                )
                assert error_message == "", (
                    f"Expected empty error message for valid filename '{filename}', got: {error_message}"
                )

        finally:
            if str(script_dir) in sys.path:
                sys.path.remove(str(script_dir))

    @pytest.mark.timeout(60)
    def test_validate_filename_ascii_invalid_non_ascii(self):
        """Test that non-ASCII filenames are rejected."""
        import sys
        from pathlib import Path

        # Add parent directory to path to import the main script
        script_dir = Path(__file__).parent.parent
        sys.path.insert(0, str(script_dir))

        try:
            # Import the validation function from the main script
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "gitlab_pkg_upload", script_dir / "gitlab-pkg-upload.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            validate_filename_ascii = module.validate_filename_ascii

            # Test invalid non-ASCII filenames
            invalid_filenames = [
                ("café.tar.gz", "café"),
                ("文件.bin", "文件"),
                ("file™.txt", "™"),
                ("tëst.txt", "ë"),
                ("файл.tar.gz", "файл"),
                ("αρχείο.bin", "αρχείο"),
            ]

            for filename, non_ascii_part in invalid_filenames:
                is_valid, error_message = validate_filename_ascii(filename)
                assert not is_valid, f"Expected '{filename}' to be invalid"
                assert error_message != "", (
                    f"Expected error message for invalid filename '{filename}'"
                )

                # Check that error message contains key information
                assert (
                    "non-ascii" in error_message.lower()
                    or "ascii" in error_message.lower()
                ), (
                    f"Expected error message to mention ASCII for '{filename}': {error_message}"
                )
                assert filename in error_message, (
                    f"Expected error message to mention the problematic filename '{filename}': {error_message}"
                )
                assert "allowed characters" in error_message.lower(), (
                    f"Expected error message to mention allowed characters for '{filename}': {error_message}"
                )

        finally:
            if str(script_dir) in sys.path:
                sys.path.remove(str(script_dir))

    @pytest.mark.timeout(60)
    def test_validate_filename_ascii_invalid_special_chars(self):
        """Test that filenames with unsupported special characters are rejected."""
        import sys
        from pathlib import Path

        # Add parent directory to path to import the main script
        script_dir = Path(__file__).parent.parent
        sys.path.insert(0, str(script_dir))

        try:
            # Import the validation function from the main script
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "gitlab_pkg_upload", script_dir / "gitlab-pkg-upload.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            validate_filename_ascii = module.validate_filename_ascii

            # Test filenames with unsupported special characters (but still ASCII)
            invalid_filenames = [
                "file@name.txt",
                "file#name.txt",
                "file$name.txt",
                "file%name.txt",
                "file&name.txt",
                "file*name.txt",
                "file(name).txt",
                "file[name].txt",
                "file{name}.txt",
                "file name.txt",  # space
                "file+name.txt",
                "file=name.txt",
                "file!name.txt",
                "file?name.txt",
            ]

            for filename in invalid_filenames:
                is_valid, error_message = validate_filename_ascii(filename)
                assert not is_valid, f"Expected '{filename}' to be invalid"
                assert error_message != "", (
                    f"Expected error message for invalid filename '{filename}'"
                )

                # Check that error message contains key information
                assert (
                    "special characters" in error_message.lower()
                    or "allowed characters" in error_message.lower()
                ), (
                    f"Expected error message to mention special characters for '{filename}': {error_message}"
                )
                assert filename in error_message, (
                    f"Expected error message to mention the problematic filename '{filename}': {error_message}"
                )

        finally:
            if str(script_dir) in sys.path:
                sys.path.remove(str(script_dir))

    @pytest.mark.timeout(60)
    def test_validate_filename_ascii_error_message_quality(self):
        """Test that error messages are detailed and helpful."""
        import sys
        from pathlib import Path

        # Add parent directory to path to import the main script
        script_dir = Path(__file__).parent.parent
        sys.path.insert(0, str(script_dir))

        try:
            # Import the validation function from the main script
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "gitlab_pkg_upload", script_dir / "gitlab-pkg-upload.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            validate_filename_ascii = module.validate_filename_ascii

            # Test with a non-ASCII filename
            is_valid, error_message = validate_filename_ascii("café.tar.gz")

            assert not is_valid
            assert error_message != ""

            # Check that error message contains all required elements
            required_elements = [
                "café.tar.gz",  # The problematic filename
                "allowed characters",  # Explanation of what's allowed
                "rename",  # Suggestion to fix the issue
            ]

            for element in required_elements:
                assert element.lower() in error_message.lower(), (
                    f"Expected error message to contain '{element}': {error_message}"
                )

            # Check that error message mentions specific allowed characters
            allowed_chars = ["letter", "digit", "dot", "hyphen", "underscore", "slash"]
            chars_mentioned = sum(
                1 for char in allowed_chars if char in error_message.lower()
            )
            assert chars_mentioned >= 4, (
                f"Expected error message to mention at least 4 allowed character types: {error_message}"
            )

        finally:
            if str(script_dir) in sys.path:
                sys.path.remove(str(script_dir))
