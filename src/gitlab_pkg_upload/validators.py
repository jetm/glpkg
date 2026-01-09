"""File validation utilities for GitLab package uploads."""

from __future__ import annotations

import re
from pathlib import Path

from gitlab_pkg_upload.models import FileValidationError


def validate_filename(filename: str) -> None:
    """
    Validate filename contains only ASCII characters and allowed patterns for GitLab Generic Package Registry.

    GitLab's API restricts filenames to ASCII-safe characters only. This function checks
    if the provided filename complies with these restrictions.

    Args:
        filename: Target filename to validate

    Raises:
        FileValidationError: If filename contains non-ASCII or disallowed characters

    Examples:
        Valid: "package.tar.gz", "my-file_v1.0.bin", "subdir/file.txt"
        Invalid: "café.tar.gz", "文件.bin", "file™.txt"
    """
    # Check if filename is ASCII
    if not filename.isascii():
        raise FileValidationError(
            f"GitLab Generic Package Registry does not support non-ASCII characters in filenames. "
            f"Problematic filename: '{filename}'. "
            f"Allowed characters: letters (a-z, A-Z), digits (0-9), dots (.), hyphens (-), "
            f"underscores (_), and forward slashes (/) for directory paths."
        )

    # Additional validation: check for allowed characters only
    # Allowed: letters, digits, dots, hyphens, underscores, forward slashes
    allowed_pattern = re.compile(r"^[a-zA-Z0-9._/-]+$")

    if not allowed_pattern.match(filename):
        raise FileValidationError(
            f"GitLab Generic Package Registry does not support special characters in filenames. "
            f"Problematic filename: '{filename}'. "
            f"Allowed characters: letters (a-z, A-Z), digits (0-9), dots (.), hyphens (-), "
            f"underscores (_), and forward slashes (/) for directory paths."
        )


def validate_file_exists(file_path: Path) -> None:
    """
    Validate that file exists, is a regular file, and is readable.

    Args:
        file_path: Path object pointing to the file to validate

    Raises:
        FileValidationError: If file doesn't exist, is not a regular file, or is not readable

    Examples:
        Valid: Path("package.tar.gz") (existing readable file)
        Invalid: Path("nonexistent.bin"), Path("/some/directory"), Path("unreadable.txt") (no permissions)
    """
    # Check if path exists
    if not file_path.exists():
        raise FileValidationError(f"File not found: {file_path}")

    # Check if path is a file
    if not file_path.is_file():
        raise FileValidationError(f"Path is not a file: {file_path}")

    # Check if file is readable
    try:
        with open(file_path, "rb"):
            pass
    except (PermissionError, OSError):
        raise FileValidationError(
            f"File is not readable: {file_path}. Check file permissions."
        )
