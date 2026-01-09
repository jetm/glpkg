"""Validation and utility functions for GitLab package uploads.

This module provides file validation, Git URL parsing, and configuration utilities
for the GitLab package upload workflow.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from gitlab_pkg_upload.models import ConfigurationError, FileValidationError


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


def calculate_sha256(file_path: Path) -> str:
    """
    Calculate SHA256 checksum of a file.

    Reads the file in chunks for memory efficiency, making it suitable
    for large files.

    Args:
        file_path: Path to the file to calculate checksum for

    Returns:
        Hexadecimal SHA256 digest string (64 characters)

    Raises:
        FileValidationError: If the file cannot be read

    Examples:
        >>> checksum = calculate_sha256(Path("package.tar.gz"))
        >>> print(checksum)
        'a1b2c3d4e5f6...'  # 64-character hex string
    """
    sha256_hash = hashlib.sha256()

    try:
        with open(file_path, "rb") as f:
            # Read in chunks for memory efficiency
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
    except (IOError, OSError) as e:
        raise FileValidationError(f"Failed to read file for checksum calculation: {file_path}. Error: {e}")

    return sha256_hash.hexdigest()


def parse_file_mapping(mappings: list[str], files: list[str]) -> dict[str, str]:
    """
    Parse file mapping strings into a dictionary.

    File mappings allow renaming files during upload using the format
    'source:target' where source is the local filename and target is
    the desired remote filename.

    Args:
        mappings: List of mapping strings in 'source:target' format
        files: List of file paths that mappings should reference

    Returns:
        Dictionary mapping local filenames to remote filenames

    Raises:
        ConfigurationError: If mapping format is invalid (not exactly one colon)
            or if a local name in mapping doesn't exist in the files list

    Examples:
        Valid:
            >>> parse_file_mapping(["local.bin:remote.bin"], ["path/to/local.bin"])
            {'local.bin': 'remote.bin'}

        Invalid (wrong format):
            >>> parse_file_mapping(["invalid_mapping"], ["file.bin"])
            ConfigurationError: Invalid file mapping format...

        Invalid (file not in list):
            >>> parse_file_mapping(["missing.bin:remote.bin"], ["other.bin"])
            ConfigurationError: File mapping references 'missing.bin'...
    """
    file_mappings: dict[str, str] = {}

    for mapping in mappings:
        if mapping.count(":") != 1:
            raise ConfigurationError(
                f"Invalid file mapping format '{mapping}'. "
                "Expected format: 'local.bin:remote.bin'"
            )
        local_name, remote_name = mapping.split(":", 1)
        file_mappings[local_name] = remote_name

    # Validate that file mappings reference files in the files list
    if file_mappings:
        files_set = {Path(f).name for f in files}
        for local_name in file_mappings.keys():
            if local_name not in files_set:
                raise ConfigurationError(
                    f"File mapping references '{local_name}' which is not in the files list"
                )

    return file_mappings


def collect_files(
    files: list[str] | None = None,
    directory: str | None = None,
    file_mappings: dict[str, str] | list[str] | None = None,
) -> tuple[list[tuple[Path, str]], list[dict]]:
    """
    Collect files to upload based on input mode (files list or directory).

    Supports two modes:
    - Files mode: Explicitly list files to upload, with optional renaming via file_mappings
    - Directory mode: Upload all files from a directory (top-level only)

    Validates that all filenames contain only ASCII characters supported by GitLab.
    File validation errors are collected rather than raised immediately, allowing
    batch processing to continue with valid files.

    Args:
        files: List of file paths to upload (files mode)
        directory: Directory path to upload files from (directory mode)
        file_mappings: Optional dictionary mapping local filenames to remote filenames,
            or a list of mapping strings in 'source:target' format.
            Only applicable in files mode.

    Returns:
        Tuple of (files_to_upload, file_errors) where:
        - files_to_upload: List of tuples containing (source_path, target_filename)
        - file_errors: List of dicts with keys: source_path, target_filename,
            error_message, error_type

    Raises:
        ConfigurationError: If directory doesn't exist, isn't a directory,
            duplicate target filenames are detected, both files and directory
            are provided, neither files nor directory is provided, or
            file_mappings is an unsupported type.

    Examples:
        Files mode:
            >>> files_to_upload, errors = collect_files(
            ...     files=["path/to/file1.bin", "path/to/file2.bin"],
            ...     file_mappings={"file1.bin": "renamed.bin"}
            ... )

        Directory mode:
            >>> files_to_upload, errors = collect_files(directory="/path/to/uploads")
    """
    files_to_upload: list[tuple[Path, str]] = []
    file_errors: list[dict] = []

    # Validate mutually exclusive inputs
    if files and directory:
        raise ConfigurationError(
            "Cannot specify both 'files' and 'directory'. They are mutually exclusive."
        )
    if not files and not directory:
        raise ConfigurationError(
            "Either 'files' or 'directory' must be provided."
        )

    # Handle file_mappings type conversion
    if file_mappings is None:
        file_mappings = {}
    elif isinstance(file_mappings, list):
        # Convert list of mapping strings to dict via parse_file_mapping
        file_mappings = parse_file_mapping(file_mappings, files or [])
    elif not isinstance(file_mappings, dict):
        raise ConfigurationError(
            f"file_mappings must be a dict or list of strings, got {type(file_mappings).__name__}"
        )

    if files:
        # Files mode: process each file explicitly
        for file_path_str in files:
            source_path = Path(file_path_str)

            # Determine target filename (apply mapping if exists)
            target_filename = file_mappings.get(source_path.name, source_path.name)

            # Validate file existence and type
            try:
                validate_file_exists(source_path)
            except FileValidationError as e:
                file_errors.append(
                    {
                        "source_path": str(source_path),
                        "target_filename": target_filename,
                        "error_message": str(e),
                        "error_type": "FileValidationError",
                    }
                )
                continue

            # Validate filename for GitLab API compatibility
            try:
                validate_filename(target_filename)
            except FileValidationError as e:
                file_errors.append(
                    {
                        "source_path": str(source_path),
                        "target_filename": target_filename,
                        "error_message": str(e),
                        "error_type": "FileValidationError",
                    }
                )
                continue

            files_to_upload.append((source_path, target_filename))

    elif directory:
        # Directory mode: collect all top-level files
        directory_path = Path(directory)

        if not directory_path.exists():
            raise ConfigurationError(f"Directory not found: {directory_path}")
        if not directory_path.is_dir():
            raise ConfigurationError(f"Path is not a directory: {directory_path}")

        # Collect only top-level files (not subdirectories)
        for item in directory_path.iterdir():
            if item.is_file():
                # Validate filename for GitLab API compatibility
                try:
                    validate_filename(item.name)
                except FileValidationError as e:
                    file_errors.append(
                        {
                            "source_path": str(item),
                            "target_filename": item.name,
                            "error_message": str(e),
                            "error_type": "FileValidationError",
                        }
                    )
                    continue

                files_to_upload.append((item, item.name))

        if not files_to_upload and not file_errors:
            # Log warning - no files found (caller may want to handle this)
            pass

    # Check for duplicate target filenames
    target_filenames = [target for _, target in files_to_upload]
    duplicates = [name for name in target_filenames if target_filenames.count(name) > 1]
    if duplicates:
        unique_duplicates = list(set(duplicates))
        raise ConfigurationError(
            f"Duplicate target filenames detected: {', '.join(unique_duplicates)}"
        )

    return files_to_upload, file_errors


def parse_git_url(url: str) -> tuple[str, str]:
    """
    Parse a Git remote URL and extract GitLab instance URL and project path.

    Supports both HTTPS and SSH Git URL formats. Extracts the GitLab instance
    base URL and the project path (namespace/project) from the remote URL.

    Args:
        url: Git remote URL in HTTPS or SSH format

    Returns:
        Tuple of (gitlab_url, project_path) where:
        - gitlab_url: Base URL of the GitLab instance (e.g., "https://gitlab.com")
        - project_path: Project path including namespace (e.g., "namespace/project")

    Raises:
        ConfigurationError: If the URL format is invalid or cannot be parsed

    Examples:
        HTTPS format:
            >>> parse_git_url("https://gitlab.com/namespace/project.git")
            ('https://gitlab.com', 'namespace/project')

        SSH format:
            >>> parse_git_url("git@gitlab.com:namespace/project.git")
            ('https://gitlab.com', 'namespace/project')

        Invalid format:
            >>> parse_git_url("invalid-url")
            ConfigurationError: Invalid Git URL format...
    """
    if not url or not isinstance(url, str):
        raise ConfigurationError(
            "Git URL must be a non-empty string. "
            "Expected formats: 'https://gitlab.com/namespace/project.git' or "
            "'git@gitlab.com:namespace/project.git'"
        )

    url = url.strip()

    try:
        # Detect URL format: SSH starts with 'git@', otherwise assume HTTPS
        if url.startswith("git@"):
            # SSH format: git@hostname:namespace/project.git
            if ":" not in url:
                raise ConfigurationError(
                    f"Invalid SSH Git URL format: '{url}'. "
                    "Expected format: 'git@gitlab.com:namespace/project.git'"
                )

            # Split on first ':' to separate host from path
            host_part, path_part = url.split(":", 1)

            # Extract hostname by removing 'git@' prefix
            hostname = host_part[4:]  # Remove 'git@'
            if not hostname:
                raise ConfigurationError(
                    f"Invalid SSH Git URL: missing hostname in '{url}'. "
                    "Expected format: 'git@gitlab.com:namespace/project.git'"
                )

            # Process path: strip slashes, remove .git suffix
            path = path_part.strip("/")
            if path.endswith(".git"):
                path = path[:-4]

            # Validate path has at least namespace/project
            path_components = path.split("/")
            if len(path_components) < 2 or not all(path_components[:2]):
                raise ConfigurationError(
                    f"Invalid Git URL path: '{path}'. "
                    "Path must contain at least namespace/project. "
                    "Expected format: 'git@gitlab.com:namespace/project.git'"
                )

            gitlab_url = f"https://{hostname}"
            project_path = "/".join(path_components)

            return gitlab_url, project_path

        else:
            # HTTPS format: https://gitlab.com/namespace/project.git
            parsed = urlparse(url)

            if parsed.scheme != "https":
                raise ConfigurationError(
                    f"Invalid Git URL scheme: '{parsed.scheme}'. "
                    "Expected 'https' for HTTPS Git URLs. "
                    "Example: 'https://gitlab.com/namespace/project.git'"
                )

            if not parsed.netloc:
                raise ConfigurationError(
                    f"Invalid Git URL: missing hostname in '{url}'. "
                    "Expected format: 'https://gitlab.com/namespace/project.git'"
                )

            # Process path: strip slashes, remove .git suffix
            path = parsed.path.strip("/")
            if path.endswith(".git"):
                path = path[:-4]

            # Validate path has at least namespace/project
            path_components = path.split("/")
            if len(path_components) < 2 or not all(path_components[:2]):
                raise ConfigurationError(
                    f"Invalid Git URL path: '{path}'. "
                    "Path must contain at least namespace/project. "
                    "Expected format: 'https://gitlab.com/namespace/project.git'"
                )

            gitlab_url = f"{parsed.scheme}://{parsed.netloc}"
            project_path = "/".join(path_components)

            return gitlab_url, project_path

    except ConfigurationError:
        raise
    except Exception as e:
        raise ConfigurationError(
            f"Failed to parse Git URL '{url}': {e}. "
            "Expected formats: 'https://gitlab.com/namespace/project.git' or "
            "'git@gitlab.com:namespace/project.git'"
        )


def normalize_gitlab_url(url: str) -> tuple[str, str]:
    """
    Normalize a GitLab project URL by extracting instance URL and project path.

    Standardizes GitLab project URLs by parsing and validating the URL structure,
    then returning the base instance URL and the project path.

    Args:
        url: GitLab project URL (e.g., "https://gitlab.com/namespace/project")

    Returns:
        Tuple of (gitlab_url, project_path) where:
        - gitlab_url: Base URL of the GitLab instance (e.g., "https://gitlab.com")
        - project_path: Project path including namespace (e.g., "namespace/project")

    Raises:
        ConfigurationError: If the URL format is invalid, missing required components,
            or uses an unsupported scheme

    Examples:
        Valid URL:
            >>> normalize_gitlab_url("https://gitlab.com/namespace/project")
            ('https://gitlab.com', 'namespace/project')

        With trailing slash:
            >>> normalize_gitlab_url("https://gitlab.com/namespace/project/")
            ('https://gitlab.com', 'namespace/project')

        Invalid (missing project):
            >>> normalize_gitlab_url("https://gitlab.com/namespace")
            ConfigurationError: Invalid GitLab URL path...
    """
    if not url or not isinstance(url, str):
        raise ConfigurationError(
            "GitLab URL must be a non-empty string. "
            "Expected format: 'https://gitlab.com/namespace/project'"
        )

    # Strip trailing slashes
    url = url.rstrip("/")

    try:
        parsed = urlparse(url)
    except Exception as e:
        raise ConfigurationError(
            f"Failed to parse GitLab URL '{url}': {e}. "
            "Expected format: 'https://gitlab.com/namespace/project'"
        )

    # Validate scheme
    if parsed.scheme not in ("http", "https"):
        raise ConfigurationError(
            f"Invalid GitLab URL scheme: '{parsed.scheme}'. "
            "Expected 'http' or 'https'. "
            "Example: 'https://gitlab.com/namespace/project'"
        )

    # Validate hostname
    if not parsed.netloc:
        raise ConfigurationError(
            f"Invalid GitLab URL: missing hostname in '{url}'. "
            "Expected format: 'https://gitlab.com/namespace/project'"
        )

    # Extract and validate path
    path = parsed.path.strip("/")
    if not path:
        raise ConfigurationError(
            f"Invalid GitLab URL: missing project path in '{url}'. "
            "Expected format: 'https://gitlab.com/namespace/project'"
        )

    # Split path into components
    path_components = path.split("/")
    if len(path_components) < 2:
        raise ConfigurationError(
            f"Invalid GitLab URL path: '{path}'. "
            "Path must contain at least namespace/project. "
            "Expected format: 'https://gitlab.com/namespace/project'"
        )

    namespace = path_components[0]
    project_name = path_components[1]

    # Validate namespace and project are non-empty
    if not namespace:
        raise ConfigurationError(
            f"Invalid GitLab URL: empty namespace in '{url}'. "
            "Expected format: 'https://gitlab.com/namespace/project'"
        )
    if not project_name:
        raise ConfigurationError(
            f"Invalid GitLab URL: empty project name in '{url}'. "
            "Expected format: 'https://gitlab.com/namespace/project'"
        )

    gitlab_url = f"{parsed.scheme}://{parsed.netloc}"
    project_path = f"{namespace}/{project_name}"

    return gitlab_url, project_path


def get_gitlab_token(cli_token: str | None = None) -> str:
    """
    Retrieve GitLab API token from CLI argument or environment variable.

    Token sources are checked in priority order:
    1. CLI argument (cli_token parameter)
    2. GITLAB_TOKEN environment variable

    Args:
        cli_token: Optional token provided via CLI argument. Takes precedence
            over environment variable if provided.

    Returns:
        GitLab API token string

    Raises:
        ConfigurationError: If no token is found from any source

    Examples:
        CLI token provided:
            >>> get_gitlab_token("glpat-xxxxxxxxxxxxxxxxxxxx")
            'glpat-xxxxxxxxxxxxxxxxxxxx'

        Environment variable (when cli_token is None):
            >>> os.environ["GITLAB_TOKEN"] = "glpat-yyyyyyyyyyyyyyyyyyyy"
            >>> get_gitlab_token()
            'glpat-yyyyyyyyyyyyyyyyyyyy'

        No token available:
            >>> get_gitlab_token()
            ConfigurationError: No GitLab token provided...
    """
    # CLI argument takes precedence
    if cli_token:
        return cli_token

    # Check environment variable
    env_token = os.environ.get("GITLAB_TOKEN")
    if env_token:
        return env_token

    # No token found
    raise ConfigurationError(
        "No GitLab token provided. "
        "Set GITLAB_TOKEN environment variable or use --token argument"
    )
