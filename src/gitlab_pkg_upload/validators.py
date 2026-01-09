"""Validation and utility functions for GitLab package uploads.

This module provides comprehensive validation capabilities for the GitLab package
upload workflow including:

- File validation (existence, readability, filename format)
- Git URL parsing and normalization
- Configuration validation (dependencies, tokens, Git installation)
- Git repository validation
- Project specification validation
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from gitlab_pkg_upload.models import ConfigurationError, FileValidationError, ProjectResolutionError

# Module-level logger
logger = logging.getLogger(__name__)

# Constants
DEFAULT_GITLAB_URL = "https://gitlab.com"


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


def validate_dependencies() -> None:
    """
    Validate that all required dependencies are available.

    Checks Python version (requires 3.11+) and required modules (gitlab, git, rich).
    Provides detailed installation instructions for missing dependencies.

    Raises:
        ConfigurationError: If Python version is insufficient or required modules
            are missing, with specific installation instructions.

    Examples:
        >>> validate_dependencies()  # Success - all dependencies available

        >>> validate_dependencies()  # Python version too low
        ConfigurationError: Python 3.11 or higher is required...

        >>> validate_dependencies()  # Missing module
        ConfigurationError: Required dependencies are not available...
    """
    logger.debug("Validating required dependencies...")

    # Check Python version
    if sys.version_info < (3, 11):
        raise ConfigurationError(
            f"Python 3.11 or higher is required. Current version: {sys.version}\n\n"
            "SOLUTION:\n"
            "1. Install Python 3.11 or higher:\n"
            "   • Ubuntu/Debian: sudo apt update && sudo apt install python3.11\n"
            "   • macOS: brew install python@3.11\n"
            "   • Windows: Download from https://python.org/downloads/\n\n"
            "2. Use pyenv to manage Python versions:\n"
            "   • Install pyenv: curl https://pyenv.run | bash\n"
            "   • Install Python: pyenv install 3.11\n"
            "   • Set local version: pyenv local 3.11\n\n"
            "3. Use uv to run with correct Python version:\n"
            "   • Install uv: pip install uv\n"
            "   • Run script: uv run --python 3.11 ./gitlab/gitlab-pkg-upload.py\n\n"
            "For more help, see: https://docs.python.org/3/installing/"
        )

    # Check required modules
    required_modules = {
        "gitlab": "python-gitlab>=4.0.0",
        "git": "GitPython>=3.1.0",
        "rich": "rich>=13.0.0",
    }

    missing_modules = []
    for module_name, package_spec in required_modules.items():
        try:
            __import__(module_name)
            logger.debug(f"Module {module_name} available")
        except ImportError:
            missing_modules.append((module_name, package_spec))
            logger.debug(f"Module {module_name} not available")

    if missing_modules:
        error_msg = "Required dependencies are not available:\n"
        for module_name, package_spec in missing_modules:
            error_msg += f"  • {module_name} (install: {package_spec})\n"

        error_msg += (
            "\nSOLUTION:\n"
            "1. If using uv (recommended):\n"
            "   • Ensure script has proper shebang: #!/usr/bin/env -S uv run --script\n"
            "   • Run directly: ./gitlab/gitlab-pkg-upload.py\n"
            "   • uv will automatically install dependencies\n\n"
            "2. Manual installation with pip:\n"
        )

        for module_name, package_spec in missing_modules:
            error_msg += f"   pip install '{package_spec}'\n"

        error_msg += (
            "\n3. Install all at once:\n"
            "   pip install python-gitlab>=4.0.0 rich>=13.0.0 GitPython>=3.1.0\n\n"
            "4. Using virtual environment (recommended):\n"
            "   python -m venv venv\n"
            "   source venv/bin/activate  # On Windows: venv\\Scripts\\activate\n"
            "   pip install python-gitlab>=4.0.0 rich>=13.0.0 GitPython>=3.1.0\n\n"
            "TROUBLESHOOTING:\n"
            "• Check Python version: python --version\n"
            "• Check pip version: pip --version\n"
            "• Update pip: pip install --upgrade pip\n"
            "• For corporate networks: pip install --trusted-host pypi.org --trusted-host pypi.python.org\n\n"
            "For more help: https://packaging.python.org/tutorials/installing-packages/"
        )

        raise ConfigurationError(error_msg)

    logger.debug("All required dependencies are available")


def validate_gitlab_token(token: str, gitlab_url: str = DEFAULT_GITLAB_URL) -> None:
    """
    Validate GitLab token availability and basic validity.

    Performs basic format validation on the token including:
    - Non-empty string check
    - Minimum length validation (20+ characters)
    - glpat- prefix token length validation (26+ characters)

    Args:
        token: GitLab authentication token to validate
        gitlab_url: GitLab instance URL for constructing help URLs

    Raises:
        ConfigurationError: If token is empty, too short, or has invalid format,
            with guidance on creating and configuring tokens.

    Examples:
        Valid token:
            >>> validate_gitlab_token("glpat-xxxxxxxxxxxxxxxxxxxx")
            # Success - no exception raised

        Empty token:
            >>> validate_gitlab_token("")
            ConfigurationError: GitLab token is required...

        Short token:
            >>> validate_gitlab_token("short")
            ConfigurationError: GitLab token appears to be invalid (too short)...
    """
    logger.debug("Validating GitLab token...")

    if not token or not isinstance(token, str):
        raise ConfigurationError(
            "GitLab token is required but not provided.\n\n"
            "SOLUTION:\n"
            "1. Create a GitLab personal access token:\n"
            f"   • Visit: {gitlab_url}/-/profile/personal_access_tokens\n"
            "   • Click 'Add new token'\n"
            "   • Name: 'Package Upload Token'\n"
            "   • Scopes: Select 'api' (required for package operations)\n"
            "   • Expiration: Set appropriate date\n"
            "   • Click 'Create personal access token'\n"
            "   • Copy the generated token immediately\n\n"
            "2. Set the token as environment variable:\n"
            "   export GITLAB_TOKEN='your-token-here'\n\n"
            "3. Or use command line argument:\n"
            "   --token your-token-here\n\n"
            "4. For CI/CD pipelines:\n"
            "   export GITLAB_TOKEN=$CI_JOB_TOKEN\n\n"
            "IMPORTANT:\n"
            "• Token must have 'api' scope (not just 'read_api')\n"
            "• Token must not be expired\n"
            "• Keep token secure and never commit to version control\n\n"
            "TROUBLESHOOTING:\n"
            "• Check token format: should be 20+ characters\n"
            "• Verify token hasn't expired\n"
            f"• Test token manually: curl -H 'PRIVATE-TOKEN: your-token' {gitlab_url}/api/v4/user\n\n"
            "For more help: https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html"
        )

    # Basic token format validation
    token = token.strip()
    if len(token) < 20:
        raise ConfigurationError(
            f"GitLab token appears to be invalid (too short: {len(token)} characters).\n\n"
            "SOLUTION:\n"
            "1. Verify you copied the complete token:\n"
            "   • GitLab personal access tokens are typically 20+ characters\n"
            "   • Ensure no whitespace or truncation occurred\n"
            "   • Check for copy/paste errors\n\n"
            "2. Generate a new token if needed:\n"
            f"   • Visit: {gitlab_url}/-/profile/personal_access_tokens\n"
            "   • Create new token with 'api' scope\n"
            "   • Copy the complete token\n\n"
            "3. Test token format:\n"
            "   echo $GITLAB_TOKEN | wc -c  # Should be 20+ characters\n\n"
            "For more help: https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html"
        )

    # Check for common token format issues
    if token.startswith("glpat-") and len(token) < 26:
        raise ConfigurationError(
            f"GitLab personal access token appears incomplete.\n"
            f"Token length: {len(token)} characters (expected 26+ for glpat- tokens)\n\n"
            "SOLUTION:\n"
            "1. Verify complete token was copied:\n"
            "   • Personal access tokens start with 'glpat-' and are 26+ characters\n"
            "   • Check for truncation during copy/paste\n"
            "   • Ensure no line breaks or extra characters\n\n"
            "2. Generate new token if corrupted:\n"
            f"   • Visit: {gitlab_url}/-/profile/personal_access_tokens\n"
            "   • Revoke old token if compromised\n"
            "   • Create new token with 'api' scope\n\n"
            "For more help: https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html"
        )

    logger.debug("GitLab token format validation passed")


def validate_git_installation() -> None:
    """
    Validate that Git is installed and accessible.

    Runs 'git --version' to verify Git is available in the system PATH
    and functioning correctly.

    Raises:
        ConfigurationError: If Git is not installed, not in PATH, command times out,
            or other unexpected errors occur, with platform-specific installation
            instructions and troubleshooting steps.

    Examples:
        Git installed:
            >>> validate_git_installation()
            # Success - no exception raised

        Git not installed:
            >>> validate_git_installation()
            ConfigurationError: Git is not installed or not available in PATH...
    """
    logger.debug("Validating Git installation...")

    try:
        result = subprocess.run(
            ["git", "--version"], capture_output=True, text=True, timeout=10
        )

        if result.returncode != 0:
            raise ConfigurationError(
                f"Git command failed with exit code {result.returncode}.\n"
                f"Error output: {result.stderr}\n\n"
                "SOLUTION:\n"
                "1. Install Git:\n"
                "   • Ubuntu/Debian: sudo apt update && sudo apt install git\n"
                "   • CentOS/RHEL: sudo yum install git\n"
                "   • macOS: brew install git (or install Xcode Command Line Tools)\n"
                "   • Windows: Download from https://git-scm.com/download/windows\n\n"
                "2. Verify installation:\n"
                "   git --version\n\n"
                "3. Check PATH configuration:\n"
                "   which git  # On Unix-like systems\n"
                "   where git  # On Windows\n\n"
                "For more help: https://git-scm.com/book/en/v2/Getting-Started-Installing-Git"
            )

        git_version = result.stdout.strip()
        logger.debug(f"Git is available: {git_version}")

    except FileNotFoundError:
        raise ConfigurationError(
            "Git is not installed or not available in PATH.\n\n"
            "SOLUTION:\n"
            "1. Install Git:\n"
            "   • Ubuntu/Debian: sudo apt update && sudo apt install git\n"
            "   • CentOS/RHEL: sudo yum install git\n"
            "   • macOS: brew install git (or install Xcode Command Line Tools)\n"
            "   • Windows: Download from https://git-scm.com/download/windows\n\n"
            "2. Add Git to PATH (if installed but not in PATH):\n"
            "   • Find Git installation directory\n"
            "   • Add to PATH environment variable\n"
            "   • Restart terminal/command prompt\n\n"
            "3. Verify installation:\n"
            "   git --version\n\n"
            "TROUBLESHOOTING:\n"
            "• Check if Git is installed: ls /usr/bin/git\n"
            "• Check PATH: echo $PATH\n"
            "• For Windows: Check 'Program Files\\Git\\bin' is in PATH\n\n"
            "For more help: https://git-scm.com/book/en/v2/Getting-Started-Installing-Git"
        )

    except subprocess.TimeoutExpired:
        raise ConfigurationError(
            "Git command timed out. This may indicate system issues.\n\n"
            "SOLUTION:\n"
            "1. Check system resources:\n"
            "   • Ensure sufficient memory and CPU available\n"
            "   • Check for system overload\n\n"
            "2. Verify Git installation:\n"
            "   git --version\n\n"
            "3. Try running Git commands manually:\n"
            "   git status\n\n"
            "If problem persists, consider reinstalling Git."
        )

    except Exception as e:
        raise ConfigurationError(
            f"Unexpected error checking Git installation: {e}\n\n"
            "SOLUTION:\n"
            "1. Verify Git is properly installed:\n"
            "   git --version\n\n"
            "2. Check system permissions:\n"
            "   • Ensure user can execute Git commands\n"
            "   • Check file permissions on Git executable\n\n"
            "3. Reinstall Git if necessary:\n"
            "   • Download from https://git-scm.com/downloads\n"
            "   • Follow installation instructions for your OS\n\n"
            "For more help: https://git-scm.com/book/en/v2/Getting-Started-Installing-Git"
        )


def validate_git_repository(working_directory: str = ".") -> None:
    """
    Validate Git repository access when Git operations are needed.

    Uses GitPython to verify the specified directory is within a valid Git
    repository and that the repository is accessible (can read config and remotes).

    Args:
        working_directory: Directory to check for Git repository. Defaults to
            current directory. Parent directories are searched for .git folder.

    Raises:
        ConfigurationError: If directory is not in a Git repository, repository
            is corrupted/inaccessible, or permission errors occur, with
            troubleshooting guidance and repair suggestions.

    Examples:
        Valid repository:
            >>> validate_git_repository("/path/to/repo")
            # Success - no exception raised

        Not a Git repository:
            >>> validate_git_repository("/tmp")
            ConfigurationError: Not a Git repository...

        Corrupted repository:
            >>> validate_git_repository("/path/to/corrupted/repo")
            ConfigurationError: Git repository found but not fully accessible...
    """
    logger.debug(f"Validating Git repository access in: {working_directory}")

    try:
        import git

        # Find Git repository (searches parent directories)
        repo = git.Repo(working_directory, search_parent_directories=True)

        logger.debug(f"Git repository found at: {repo.working_dir}")

        # Test basic repository operations
        try:
            # Try to read repository configuration
            repo.config_reader()  # Just verify it's accessible
            logger.debug("Git repository configuration accessible")

            # Try to read remotes
            remotes = list(repo.remotes)
            logger.debug(f"Git remotes accessible: {len(remotes)} remote(s)")

        except Exception as e:
            raise ConfigurationError(
                f"Git repository found but not fully accessible: {e}\n\n"
                "SOLUTION:\n"
                "1. Check repository integrity:\n"
                "   git fsck\n\n"
                "2. Check file permissions:\n"
                f"   ls -la {repo.working_dir}/.git\n"
                "   • Ensure .git directory is readable\n"
                "   • Check ownership and permissions\n\n"
                "3. Try repository repair:\n"
                "   git gc --prune=now\n"
                "   git repack -ad\n\n"
                "4. If corrupted, consider re-cloning:\n"
                "   • Backup any uncommitted changes\n"
                "   • Clone fresh copy from remote\n\n"
                "TROUBLESHOOTING:\n"
                "• Check disk space: df -h\n"
                "• Check file system errors: dmesg | grep -i error\n"
                "• Verify Git version: git --version\n\n"
                "For more help: https://git-scm.com/docs/git-fsck"
            )

    except git.InvalidGitRepositoryError:
        raise ConfigurationError(
            f"Directory '{working_directory}' is not inside a Git repository.\n\n"
            "SOLUTION:\n"
            "1. Ensure you're in a Git repository:\n"
            "   git status\n\n"
            "2. Initialize repository if needed:\n"
            "   git init\n"
            "   git remote add origin <repository-url>\n\n"
            "3. Use manual project specification if Git auto-detection isn't needed:\n"
            "   --project-url https://gitlab.com/namespace/project\n"
            "   --project-path namespace/project\n\n"
            "For more help: https://git-scm.com/docs/git-init"
        )

    except PermissionError as e:
        raise ConfigurationError(
            f"Permission denied accessing Git repository in '{working_directory}': {e}\n\n"
            "SOLUTION:\n"
            "1. Check directory permissions:\n"
            f"   ls -la {working_directory}\n"
            "   • Ensure directory is readable and accessible\n\n"
            "2. Check .git directory permissions:\n"
            f"   ls -la {working_directory}/.git\n\n"
            "3. Fix permissions if needed:\n"
            f"   chmod -R u+rw {working_directory}/.git\n\n"
            "For more help: https://git-scm.com/docs/git-init"
        )

    except git.GitCommandError as e:
        raise ConfigurationError(
            f"Git command error in '{working_directory}': {e}\n\n"
            "SOLUTION:\n"
            "1. Verify Git is installed and working:\n"
            "   git --version\n\n"
            "2. Check repository status:\n"
            "   git status\n\n"
            "3. Check for repository corruption:\n"
            "   git fsck\n\n"
            "For more help: https://git-scm.com/docs/git-fsck"
        )

    except OSError as e:
        raise ConfigurationError(
            f"OS error accessing Git repository in '{working_directory}': {e}\n\n"
            "SOLUTION:\n"
            "1. Verify directory exists and is accessible:\n"
            f"   ls -la {working_directory}\n\n"
            "2. Check disk space:\n"
            "   df -h\n\n"
            "3. Check file system health:\n"
            "   dmesg | grep -i error\n\n"
            "For more help: https://git-scm.com/docs/git-init"
        )

    except Exception as e:
        raise ConfigurationError(
            f"Unexpected error validating Git repository access: {e}\n\n"
            "SOLUTION:\n"
            "1. Ensure you're in a Git repository:\n"
            "   git status\n\n"
            "2. Initialize repository if needed:\n"
            "   git init\n"
            "   git remote add origin <repository-url>\n\n"
            "3. Check directory permissions:\n"
            f"   ls -la {working_directory}\n"
            "   • Ensure directory is readable and accessible\n\n"
            "4. Use manual project specification if Git auto-detection isn't needed:\n"
            "   --project-url https://gitlab.com/namespace/project\n"
            "   --project-path namespace/project\n\n"
            "For more help: https://git-scm.com/docs/git-init"
        )


def validate_project_specification(
    project_spec: str,
    spec_type: str = "auto",
    gitlab_url: str = DEFAULT_GITLAB_URL,
) -> tuple[str, str]:
    """
    Validate and normalize a project specification (URL or path).

    Handles both GitLab project URLs and project paths, validating format
    and extracting components.

    Args:
        project_spec: Project specification - either a full GitLab URL
            (e.g., "https://gitlab.com/namespace/project") or a project path
            (e.g., "namespace/project")
        spec_type: Type of specification - "url", "path", or "auto" (default).
            When "auto", attempts to detect the type based on the spec format.
        gitlab_url: Base URL of the GitLab instance to use for path specs.
            Defaults to DEFAULT_GITLAB_URL ("https://gitlab.com").
            Ignored when spec_type is "url" or when auto-detected as URL.

    Returns:
        Tuple of (gitlab_url, project_path) where:
        - gitlab_url: Base URL of the GitLab instance (e.g., "https://gitlab.com")
            For path specs, returns the provided gitlab_url parameter
        - project_path: Project path including namespace (e.g., "namespace/project")

    Raises:
        ProjectResolutionError: If project specification is invalid, with
            format examples and suggestions.

    Examples:
        URL specification:
            >>> validate_project_specification("https://gitlab.com/mygroup/myproject")
            ('https://gitlab.com', 'mygroup/myproject')

        Path specification:
            >>> validate_project_specification("mygroup/myproject", spec_type="path")
            ('https://gitlab.com', 'mygroup/myproject')

        Path with custom GitLab URL:
            >>> validate_project_specification("mygroup/myproject", gitlab_url="https://gitlab.example.com")
            ('https://gitlab.example.com', 'mygroup/myproject')

        Auto-detect URL:
            >>> validate_project_specification("https://gitlab.example.com/ns/proj")
            ('https://gitlab.example.com', 'ns/proj')

        Invalid path:
            >>> validate_project_specification("invalid")
            ProjectResolutionError: Invalid project path format...
    """
    if not project_spec or not isinstance(project_spec, str):
        raise ProjectResolutionError(
            "Project specification is required but not provided.\n\n"
            "SOLUTION:\n"
            "Provide a project URL or path:\n"
            "  • URL format: --project-url https://gitlab.com/namespace/project\n"
            "  • Path format: --project-path namespace/project\n\n"
            "Examples:\n"
            "  • https://gitlab.com/mycompany/my-project\n"
            "  • mycompany/my-project\n"
            "  • group/subgroup/project-name"
        )

    project_spec = project_spec.strip()

    # Auto-detect spec type if needed
    if spec_type == "auto":
        if project_spec.startswith(("http://", "https://")):
            spec_type = "url"
        else:
            spec_type = "path"

    if spec_type == "url":
        # Use existing normalize_gitlab_url function
        try:
            return normalize_gitlab_url(project_spec)
        except ConfigurationError as e:
            raise ProjectResolutionError(str(e))

    elif spec_type == "path":
        # Validate and normalize project path
        # Strip leading/trailing slashes and whitespace
        path = project_spec.strip().strip("/")

        if not path:
            raise ProjectResolutionError(
                "Project path cannot be empty.\n\n"
                "SOLUTION:\n"
                "Provide a valid project path in namespace/project format:\n"
                "  • mycompany/my-project\n"
                "  • group/subgroup/project-name\n"
                "  • username/personal-project"
            )

        # Split path into components
        path_components = path.split("/")

        # Validate path has at least namespace/project components
        if len(path_components) < 2:
            raise ProjectResolutionError(
                f"Invalid project path format: '{project_spec}'.\n"
                "Path must contain at least namespace/project.\n\n"
                "SOLUTION:\n"
                "Provide a valid project path:\n"
                "  • namespace/project (minimum required)\n"
                "  • group/subgroup/project (nested groups)\n\n"
                "Examples:\n"
                "  • mycompany/my-project\n"
                "  • group/subgroup/project-name\n"
                "  • username/personal-project"
            )

        # Validate all path components are non-empty
        for i, component in enumerate(path_components):
            if not component:
                raise ProjectResolutionError(
                    f"Invalid project path: '{project_spec}'.\n"
                    "Path contains empty component (consecutive slashes).\n\n"
                    "SOLUTION:\n"
                    "Remove consecutive slashes from the path:\n"
                    f"  • Invalid: {project_spec}\n"
                    f"  • Valid: {'/'.join(c for c in path_components if c)}"
                )

        # Return the provided GitLab URL for path specs
        return gitlab_url, path

    else:
        raise ProjectResolutionError(
            f"Unknown specification type: '{spec_type}'.\n"
            "Expected 'url', 'path', or 'auto'."
        )


def validate_configuration(
    token: Optional[str] = None,
    gitlab_url: str = DEFAULT_GITLAB_URL,
    require_git: bool = False,
    working_directory: str = ".",
) -> None:
    """
    Comprehensive configuration validation for GitLab package uploads.

    Orchestrates validation of all configuration components in sequence:
    1. Dependencies (Python version, required modules)
    2. GitLab token (format and availability)
    3. Git installation (always checked, fails only if require_git=True)
    4. Git repository access (only if require_git=True)

    Args:
        token: GitLab authentication token. If None, attempts to retrieve
            from environment variable via get_gitlab_token().
        gitlab_url: GitLab instance URL for token validation help messages.
            Defaults to "https://gitlab.com".
        require_git: Whether Git operations are required. If False, Git
            validation failures are logged as warnings but don't raise errors.
        working_directory: Working directory for Git repository validation.
            Defaults to current directory.

    Raises:
        ConfigurationError: If any required validation fails. Includes
            detailed error messages with resolution steps.

    Examples:
        Basic validation (no Git required):
            >>> validate_configuration(token="glpat-xxxx")
            # Success - dependencies and token validated

        With Git requirement:
            >>> validate_configuration(token="glpat-xxxx", require_git=True)
            # Success - all validations passed including Git

        Missing token:
            >>> validate_configuration()
            ConfigurationError: No GitLab token provided...

        Git required but not installed:
            >>> validate_configuration(require_git=True)
            ConfigurationError: Git is not installed...
    """
    logger.info("Starting configuration validation...")

    # 1. Validate dependencies
    try:
        validate_dependencies()
        logger.info("Dependencies validation passed")
    except ConfigurationError:
        logger.error("Dependencies validation failed")
        raise

    # 2. Validate GitLab token
    try:
        if token is None:
            token = get_gitlab_token(None)
        validate_gitlab_token(token, gitlab_url)
        logger.info("GitLab token validation passed")
    except ConfigurationError:
        logger.error("GitLab token validation failed")
        raise

    # 3. Validate Git installation (always check since it might be needed)
    try:
        validate_git_installation()
        logger.info("Git installation validation passed")
    except ConfigurationError as e:
        if require_git:
            logger.error("Git installation validation failed")
            raise
        else:
            logger.warning(
                "Git installation validation failed (not required for this operation)"
            )
            logger.debug(f"Git validation error: {e}")

    # 4. Validate Git repository access (only if Git operations are required)
    if require_git:
        try:
            validate_git_repository(working_directory)
            logger.info("Git repository access validation passed")
        except ConfigurationError:
            logger.error("Git repository access validation failed")
            raise

    logger.info("Configuration validation completed successfully")
