"""
Artifact factory utilities for creating test files and directories.

This module contains artifact creation methods extracted from the ArtifactManager
class in the monolithic test file. It provides utilities for generating test data
with various characteristics for upload testing.
"""

import secrets
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from gitlab_pkg_upload.validators import calculate_sha256


@dataclass
class TestArtifact:
    """
    Represents a test artifact created during testing.

    Extracted from the monolithic test file's TestArtifact class.
    """

    path: Path
    checksum: str
    size: int
    created_at: datetime
    artifact_type: str
    content_type: str = "application/octet-stream"


class ArtifactFactory:
    """
    Factory for creating test files and directories with various characteristics.

    This class contains methods extracted from the ArtifactManager class in the
    monolithic test file, focused specifically on artifact creation.
    """

    @staticmethod
    def create_test_file(
        target_dir: Path,
        filename: str,
        size_bytes: int = 1024,
        content_pattern: str = "test",
    ) -> TestArtifact:
        """
        Create a test file with specified characteristics.

        Args:
            target_dir: Directory to create the file in
            filename: Name of the file to create
            size_bytes: Size of the file in bytes
            content_pattern: Pattern to use for file content

        Returns:
            TestArtifact representing the created file
        """
        # Ensure target directory exists
        target_dir.mkdir(parents=True, exist_ok=True)

        file_path = target_dir / filename

        # Generate file content
        content = ArtifactFactory._generate_file_content(size_bytes, content_pattern)

        # Write file
        file_path.write_bytes(content)

        # Calculate checksum using validators module
        checksum = calculate_sha256(file_path)

        # Determine content type
        content_type = ArtifactFactory._determine_content_type(
            filename, content_pattern
        )

        # Create artifact record
        artifact = TestArtifact(
            path=file_path,
            checksum=checksum,
            size=size_bytes,
            created_at=datetime.now(),
            artifact_type="file",
            content_type=content_type,
        )

        return artifact

    @staticmethod
    def create_test_directory(
        target_dir: Path,
        dirname: str,
        file_count: int = 3,
        file_configs: Optional[List[tuple]] = None,
    ) -> List[TestArtifact]:
        """
        Create a test directory with multiple files.

        Args:
            target_dir: Base directory to create the test directory in
            dirname: Name of the directory to create
            file_count: Number of files to create in the directory
            file_configs: Optional list of (filename, size, pattern) tuples

        Returns:
            List of TestArtifact objects for created files
        """
        dir_path = target_dir / dirname
        dir_path.mkdir(parents=True, exist_ok=True)

        # Default file configurations if none provided
        if file_configs is None:
            file_configs = [
                ("small.txt", 512, "text"),
                ("medium.bin", 2048, "binary"),
                ("data.json", 1024, "json"),
                ("config.yaml", 256, "yaml"),
                ("unicode-content.txt", 1024, "unicode"),
            ]

        created_artifacts = []

        for i in range(min(file_count, len(file_configs))):
            filename, size, pattern = file_configs[i]
            artifact = ArtifactFactory.create_test_file(
                target_dir=dir_path,
                filename=filename,
                size_bytes=size,
                content_pattern=pattern,
            )
            created_artifacts.append(artifact)

        return created_artifacts

    @staticmethod
    def create_variety_files(target_dir: Path) -> List[TestArtifact]:
        """
        Create a variety of test files with different sizes and content types.

        Args:
            target_dir: Directory to create files in

        Returns:
            List of TestArtifact objects for all created files
        """
        variety_configs = [
            # Small files
            ("tiny.txt", 10, "text"),
            ("small.json", 256, "json"),
            ("config.yaml", 512, "yaml"),
            # Medium files
            ("data.csv", 5120, "csv"),
            ("image.bin", 10240, "binary"),
            ("log.txt", 20480, "log"),
            # Large files
            ("archive.tar", 51200, "binary"),
            ("dataset.json", 102400, "json"),
            # Special cases
            ("empty", 0, "empty"),
            ("unicode-test-file.txt", 1024, "unicode"),
            (
                "special-chars_test.txt",
                2048,
                "text",
            ),  # Changed to use only ASCII-safe characters
            ("no-extension", 1024, "text"),
        ]

        created_artifacts = []

        for filename, size, pattern in variety_configs:
            try:
                artifact = ArtifactFactory.create_test_file(
                    target_dir=target_dir,
                    filename=filename,
                    size_bytes=size,
                    content_pattern=pattern,
                )
                created_artifacts.append(artifact)
            except Exception as e:
                print(f"Warning: Failed to create test file {filename}: {e}")

        return created_artifacts

    @staticmethod
    def create_temporary_file(
        filename: str,
        size_bytes: int = 1024,
        content_pattern: str = "test",
        prefix: str = "pytest-temp-",
    ) -> TestArtifact:
        """
        Create a temporary test file that will be automatically cleaned up.

        Args:
            filename: Name of the file to create
            size_bytes: Size of the file in bytes
            content_pattern: Pattern to use for file content
            prefix: Prefix for temporary directory name

        Returns:
            TestArtifact representing the created file
        """
        temp_dir = Path(tempfile.mkdtemp(prefix=prefix))
        return ArtifactFactory.create_test_file(
            temp_dir, filename, size_bytes, content_pattern
        )

    @staticmethod
    def create_file_mapping_scenario(target_dir: Path) -> Dict[str, TestArtifact]:
        """
        Create files for testing file mapping functionality.

        Args:
            target_dir: Directory to create files in

        Returns:
            Dictionary mapping source paths to TestArtifact objects
        """
        # Create a nested directory structure for mapping tests
        mapping_dir = target_dir / "mapping-test"
        mapping_dir.mkdir(parents=True, exist_ok=True)

        # Create subdirectories
        (mapping_dir / "subdir1").mkdir(exist_ok=True)
        (mapping_dir / "subdir2").mkdir(exist_ok=True)

        # Create files in different locations
        files = {
            "root-file.txt": ArtifactFactory.create_test_file(
                mapping_dir, "root-file.txt", 1024, "text"
            ),
            "subdir1/nested-file.json": ArtifactFactory.create_test_file(
                mapping_dir / "subdir1", "nested-file.json", 512, "json"
            ),
            "subdir2/deep-file.bin": ArtifactFactory.create_test_file(
                mapping_dir / "subdir2", "deep-file.bin", 2048, "binary"
            ),
        }

        return files

    @staticmethod
    def _generate_file_content(size_bytes: int, pattern: str) -> bytes:
        """
        Generate file content based on size and pattern.

        Args:
            size_bytes: Target size in bytes
            pattern: Content pattern type

        Returns:
            Generated content as bytes
        """
        if size_bytes == 0:
            return b""

        if pattern == "empty":
            return b""
        elif pattern == "text":
            # Generate readable text content
            base_text = "This is test content for GitLab upload testing. "
            content = (base_text * ((size_bytes // len(base_text)) + 1))[:size_bytes]
            return content.encode("utf-8")
        elif pattern == "binary":
            # Generate binary content
            return secrets.token_bytes(size_bytes)
        elif pattern == "random":
            # Generate random content
            return secrets.token_bytes(size_bytes)
        elif pattern == "json":
            # Generate JSON-like content
            json_template = '{"test": "data", "index": %d, "content": "%s"}\n'
            content = ""
            index = 0
            while len(content.encode("utf-8")) < size_bytes:
                line = json_template % (index, secrets.token_hex(8))
                content += line
                index += 1
            return content.encode("utf-8")[:size_bytes]
        elif pattern == "yaml":
            # Generate YAML-like content
            yaml_template = "test_item_%d:\n  value: %s\n  timestamp: %s\n"
            content = ""
            index = 0
            while len(content.encode("utf-8")) < size_bytes:
                line = yaml_template % (
                    index,
                    secrets.token_hex(4),
                    datetime.now().isoformat(),
                )
                content += line
                index += 1
            return content.encode("utf-8")[:size_bytes]
        elif pattern == "csv":
            # Generate CSV-like content
            csv_header = "id,name,value,timestamp\n"
            content = csv_header
            index = 0
            while len(content.encode("utf-8")) < size_bytes:
                line = f"{index},test_{index},{secrets.randbelow(1000)},{datetime.now().isoformat()}\n"
                content += line
                index += 1
            return content.encode("utf-8")[:size_bytes]
        elif pattern == "log":
            # Generate log-like content
            log_template = "[%s] INFO: Test log entry %d - %s\n"
            content = ""
            index = 0
            while len(content.encode("utf-8")) < size_bytes:
                line = log_template % (
                    datetime.now().isoformat(),
                    index,
                    secrets.token_hex(8),
                )
                content += line
                index += 1
            return content.encode("utf-8")[:size_bytes]
        elif pattern == "unicode":
            # Generate Unicode content
            unicode_chars = "Hello 世界 🌍 Тест العالم 🚀 "
            content = unicode_chars * (
                (size_bytes // len(unicode_chars.encode("utf-8"))) + 1
            )
            return content.encode("utf-8")[:size_bytes]
        else:
            # Default to repeating pattern
            pattern_bytes = pattern.encode("utf-8")
            content = pattern_bytes * ((size_bytes // len(pattern_bytes)) + 1)
            return content[:size_bytes]

    @staticmethod
    def _determine_content_type(filename: str, pattern: str) -> str:
        """
        Determine MIME type based on filename and content pattern.

        Args:
            filename: Name of the file
            pattern: Content pattern type

        Returns:
            MIME type string
        """
        # Check file extension first
        suffix = Path(filename).suffix.lower()

        extension_map = {
            ".txt": "text/plain",
            ".json": "application/json",
            ".yaml": "application/x-yaml",
            ".yml": "application/x-yaml",
            ".csv": "text/csv",
            ".log": "text/plain",
            ".bin": "application/octet-stream",
            ".tar": "application/x-tar",
            ".gz": "application/gzip",
            ".zip": "application/zip",
        }

        if suffix in extension_map:
            return extension_map[suffix]

        # Fall back to pattern-based detection
        pattern_map = {
            "text": "text/plain",
            "json": "application/json",
            "yaml": "application/x-yaml",
            "csv": "text/csv",
            "log": "text/plain",
            "binary": "application/octet-stream",
            "random": "application/octet-stream",
            "unicode": "text/plain; charset=utf-8",
            "empty": "application/octet-stream",
        }

        return pattern_map.get(pattern, "application/octet-stream")


def create_test_package_name(base_name: str) -> str:
    """
    Create a unique test package name to avoid conflicts.

    Args:
        base_name: Base name for the package

    Returns:
        Unique package name with timestamp and random suffix
    """
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    random_suffix = secrets.token_hex(4)
    return f"test-{base_name}-{timestamp}-{random_suffix}"


def calculate_file_checksum(file_path: Path) -> str:
    """
    Calculate SHA256 checksum of a file.

    Args:
        file_path: Path to the file

    Returns:
        SHA256 checksum as hexadecimal string
    """
    return calculate_sha256(file_path)


def create_file_with_checksum(
    target_path: Path, content: bytes, expected_checksum: Optional[str] = None
) -> str:
    """
    Create a file with specific content and return its checksum.

    Args:
        target_path: Path where to create the file
        content: File content as bytes
        expected_checksum: Optional expected checksum for validation

    Returns:
        SHA256 checksum of the created file

    Raises:
        ValueError: If expected checksum doesn't match actual checksum
    """
    # Ensure parent directory exists
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Write content
    target_path.write_bytes(content)

    # Calculate checksum
    actual_checksum = calculate_file_checksum(target_path)

    # Validate if expected checksum provided
    if expected_checksum and actual_checksum != expected_checksum:
        raise ValueError(
            f"Checksum mismatch: expected {expected_checksum}, got {actual_checksum}"
        )

    return actual_checksum
