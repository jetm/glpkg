#!/usr/bin/env python3
"""
GitLab Common Module

Shared functionality for GitLab repository detection, project resolution, and error handling.
This module provides common classes and functions used by both the upload script and test script
to eliminate code duplication and ensure consistent behavior.

Classes:
    - GitAutoDetector: Handles automatic Git project detection
    - ProjectResolver: Resolves GitLab project IDs from URLs or paths
    - GitRemoteInfo: Represents Git remote information
    - ProjectInfo: Represents parsed project information

Functions:
    - parse_https_git_url: Parse HTTPS Git URLs
    - parse_ssh_git_url: Parse SSH Git URLs
    - is_gitlab_url: Check if URL is a GitLab instance
    - get_gitlab_token: Get GitLab token from environment or CLI
    - validate_project_input: Validate project input with auto-detection fallback
    - enhance_error_message: Enhance error messages with context
    - handle_*_error: Specific error handling functions
    - setup_logging: Configure consistent logging across scripts
"""

import argparse
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import git

# Constants
DEFAULT_GITLAB_URL = "https://gitlab.com"
MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]  # Exponential backoff in seconds
RATE_LIMIT_RETRY_DELAY = 60  # Seconds to wait for rate limit reset

# Setup logging
logger = logging.getLogger(__name__)


# Logging Configuration


def setup_logging(console=None, level=logging.INFO, verbose=False):
    """
    Setup consistent logging configuration across both scripts.

    Args:
        console: Rich console instance (optional)
        level: Logging level (default: INFO)
        verbose: Enable verbose logging (sets level to DEBUG)
    """
    if verbose:
        level = logging.DEBUG

    # Only configure if not already configured
    if not logging.getLogger().handlers:
        try:
            from rich.console import Console
            from rich.logging import RichHandler

            if console is None:
                console = Console()

            logging.basicConfig(
                level=level,
                format="%(message)s",
                handlers=[RichHandler(console=console, rich_tracebacks=True)],
            )
        except ImportError:
            # Fallback to basic logging if rich is not available
            logging.basicConfig(
                level=level,
                format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            )
    else:
        # Update existing logger level
        logging.getLogger().setLevel(level)

    if verbose:
        logger.debug("Verbose logging enabled")


# Data Models


@dataclass
class ProjectInfo:
    """Represents parsed project information from URLs."""

    gitlab_url: str  # Base GitLab instance URL
    namespace: str  # Project namespace/group
    project_name: str  # Project name
    project_path: str  # Full project path (namespace/project)
    original_url: str  # Original URL provided by user


@dataclass
class ProjectResolutionResult:
    """Represents the result of project ID resolution."""

    success: bool
    project_id: Optional[int]
    error_message: Optional[str]
    project_info: Optional[ProjectInfo]
    gitlab_url: str


@dataclass
class GitRemoteInfo:
    """Represents Git remote information."""

    name: str  # Remote name (e.g., 'origin')
    url: str  # Remote URL
    gitlab_url: str  # Extracted GitLab instance URL
    project_path: str  # Extracted project path


# Git Repository Detection Classes


class GitAutoDetector:
    """Handles automatic Git project detection."""

    def __init__(self, working_directory: str = "."):
        """Initialize with working directory."""
        self.working_directory = working_directory

    def find_git_repository(self) -> Optional[git.Repo]:
        """
        Find Git repository in current or parent directories.

        Returns:
            Git repository object if found, None otherwise

        Raises:
            ValueError: If Git repository access fails due to permissions or corruption
        """
        try:
            # GitPython's Repo.search_parent_directories will find the repo
            # in the current directory or any parent directory
            repo = git.Repo(self.working_directory, search_parent_directories=True)
            logger.debug(f"Found Git repository at: {repo.working_dir}")
            return repo
        except git.InvalidGitRepositoryError:
            logger.debug(
                f"No Git repository found starting from: {self.working_directory}"
            )
            return None
        except PermissionError as e:
            error_msg = (
                "Permission denied accessing Git repository.\n\n"
                "Please check the following:\n"
                "  • You have read permissions for the current directory and parent directories\n"
                "  • The .git directory is accessible\n"
                "  • No file system restrictions are blocking access\n\n"
                f"Working directory: {self.working_directory}\n"
                f"Error details: {e}\n\n"
                "To resolve this issue:\n"
                f"  1. Check directory permissions: ls -la {self.working_directory}\n"
                "  2. Ensure you can read the .git directory\n"
                "  3. Try running from a different directory with proper permissions\n"
                "  4. Use --project-url or --project-path to specify project manually"
            )
            raise ValueError(error_msg)
        except git.GitCommandError as e:
            error_msg = (
                "Git command failed while searching for repository.\n\n"
                "This may indicate:\n"
                "  • Corrupted Git repository\n"
                "  • Git is not properly installed\n"
                "  • File system issues\n\n"
                f"Working directory: {self.working_directory}\n"
                f"Git error: {e}\n\n"
                "To resolve this issue:\n"
                "  1. Verify Git installation: git --version\n"
                "  2. Check repository integrity: git fsck (from repository root)\n"
                "  3. Try re-cloning the repository if corrupted\n"
                "  4. Use --project-url or --project-path to specify project manually"
            )
            raise ValueError(error_msg)
        except OSError as e:
            error_msg = (
                "File system error while searching for Git repository.\n\n"
                "This may indicate:\n"
                "  • Network drive connectivity issues\n"
                "  • Disk space or I/O problems\n"
                "  • Path length limitations\n\n"
                f"Working directory: {self.working_directory}\n"
                f"System error: {e}\n\n"
                "To resolve this issue:\n"
                "  1. Check disk space and file system health\n"
                "  2. Verify network drive connectivity (if applicable)\n"
                "  3. Try from a local directory with shorter path\n"
                "  4. Use --project-url or --project-path to specify project manually"
            )
            raise ValueError(error_msg)
        except Exception as e:
            error_msg = (
                "Unexpected error while searching for Git repository.\n\n"
                f"Working directory: {self.working_directory}\n"
                f"Error: {e}\n\n"
                "To resolve this issue:\n"
                "  1. Ensure Git is properly installed and accessible\n"
                "  2. Check that the current directory is accessible\n"
                "  3. Try running from a different directory\n"
                "  4. Use --project-url or --project-path to specify project manually"
            )
            raise ValueError(error_msg)

    def get_gitlab_remotes(self, repo: git.Repo) -> list[GitRemoteInfo]:
        """
        Extract GitLab remotes from repository.

        Args:
            repo: Git repository object

        Returns:
            List of GitRemoteInfo objects for GitLab remotes

        Raises:
            ValueError: If remote access fails or no GitLab remotes are found
        """
        gitlab_remotes = []
        all_remotes = []

        try:
            # First, try to get all remotes
            try:
                remotes_list = list(repo.remotes)
                if not remotes_list:
                    error_msg = (
                        "No Git remotes found in repository.\n\n"
                        f"Repository location: {repo.working_dir}\n\n"
                        "This usually means:\n"
                        "  • Repository was created locally without remotes\n"
                        "  • Repository was cloned but remotes were removed\n"
                        "  • Repository is in an incomplete state\n\n"
                        "To resolve this issue:\n"
                        "  1. Add a GitLab remote: git remote add origin <gitlab-url>\n"
                        "  2. Check existing remotes: git remote -v\n"
                        "  3. Clone from GitLab if this is a local-only repository\n"
                        "  4. Use --project-url or --project-path to specify project manually\n\n"
                        "Examples of adding GitLab remotes:\n"
                        "  • git remote add origin https://gitlab.com/namespace/project.git\n"
                        "  • git remote add origin git@gitlab.com:namespace/project.git"
                    )
                    raise ValueError(error_msg)
            except git.GitCommandError as e:
                error_msg = (
                    f"Failed to read Git remotes from repository.\n\n"
                    f"Repository location: {repo.working_dir}\n"
                    f"Git error: {e}\n\n"
                    f"This may indicate:\n"
                    f"  • Corrupted Git repository\n"
                    f"  • Git configuration issues\n"
                    f"  • File system problems\n\n"
                    f"To resolve this issue:\n"
                    f"  1. Check repository integrity: git fsck\n"
                    f"  2. Verify Git configuration: git config --list\n"
                    f"  3. Try re-cloning the repository\n"
                    f"  4. Use --project-url or --project-path to specify project manually"
                )
                raise ValueError(error_msg)

            # Process each remote
            for remote in remotes_list:
                try:
                    # Get the first URL if multiple URLs exist
                    if remote.urls:
                        remote_url = next(iter(remote.urls))
                        all_remotes.append(f"{remote.name}: {remote_url}")
                        logger.debug(f"Found remote '{remote.name}': {remote_url}")

                        # Try to parse as GitLab URL
                        parsed_info = self.parse_git_url(remote_url)
                        if parsed_info:
                            gitlab_url, project_path = parsed_info
                            gitlab_remote = GitRemoteInfo(
                                name=remote.name,
                                url=remote_url,
                                gitlab_url=gitlab_url,
                                project_path=project_path,
                            )
                            gitlab_remotes.append(gitlab_remote)
                            logger.debug(
                                f"Parsed GitLab remote '{remote.name}': {gitlab_url}/{project_path}"
                            )
                        else:
                            logger.debug(
                                f"Remote '{remote.name}' is not a GitLab URL: {remote_url}"
                            )
                    else:
                        logger.warning(f"Remote '{remote.name}' has no URLs configured")
                        all_remotes.append(f"{remote.name}: <no URL configured>")

                except Exception as e:
                    logger.warning(f"Error processing remote '{remote.name}': {e}")
                    all_remotes.append(f"{remote.name}: <error reading URL>")
                    continue

            # Check if we found any GitLab remotes
            if not gitlab_remotes:
                error_msg = (
                    f"No GitLab remotes found in repository.\n\n"
                    f"Repository location: {repo.working_dir}\n"
                    f"Found {len(all_remotes)} remote(s), but none point to GitLab instances:\n"
                )

                for remote_info in all_remotes:
                    error_msg += f"  • {remote_info}\n"

                error_msg += (
                    "\nThis usually means:\n"
                    "  • Repository remotes point to GitHub, Bitbucket, or other Git services\n"
                    "  • Repository remotes point to private Git servers that aren't GitLab\n"
                    "  • Remote URLs are malformed or unrecognizable\n\n"
                    "To resolve this issue:\n"
                    "  1. Add a GitLab remote: git remote add gitlab <gitlab-url>\n"
                    "  2. Change existing remote to GitLab: git remote set-url origin <gitlab-url>\n"
                    "  3. Use --project-url or --project-path to specify project manually\n\n"
                    "Examples of supported GitLab remote formats:\n"
                    "  • HTTPS: https://gitlab.com/namespace/project.git\n"
                    "  • SSH: git@gitlab.com:namespace/project.git\n"
                    "  • Custom GitLab: https://gitlab.example.com/namespace/project.git"
                )
                raise ValueError(error_msg)

            logger.info(
                f"Found {len(gitlab_remotes)} GitLab remote(s): {[r.name for r in gitlab_remotes]}"
            )

            # Handle multiple GitLab remotes - prioritize 'origin'
            if len(gitlab_remotes) > 1:
                origin_remote = next(
                    (r for r in gitlab_remotes if r.name == "origin"), None
                )
                if origin_remote:
                    logger.info("Multiple GitLab remotes found, prioritizing 'origin'")
                    other_remotes = [
                        r.name for r in gitlab_remotes if r.name != "origin"
                    ]
                    logger.info(f"Other GitLab remotes available: {other_remotes}")
                    return [origin_remote]
                else:
                    # No 'origin' remote, use first one but warn about the choice
                    selected_remote = gitlab_remotes[0]
                    other_remotes = [r.name for r in gitlab_remotes[1:]]
                    logger.warning(
                        f"Multiple GitLab remotes found without 'origin'. "
                        f"Using '{selected_remote.name}', others available: {other_remotes}"
                    )
                    logger.info(
                        f"To specify a different remote, you can:\n"
                        f"  1. Rename your preferred remote to 'origin': git remote rename {selected_remote.name} origin\n"
                        f"  2. Use --project-url or --project-path to specify project manually"
                    )
                    return [selected_remote]

            return gitlab_remotes

        except ValueError:
            # Re-raise ValueError exceptions (our custom error messages)
            raise
        except Exception as e:
            error_msg = (
                f"Unexpected error reading Git remotes.\n\n"
                f"Repository location: {repo.working_dir}\n"
                f"Error: {e}\n\n"
                f"To resolve this issue:\n"
                f"  1. Check repository integrity: git fsck\n"
                f"  2. Verify you can access remotes: git remote -v\n"
                f"  3. Try re-cloning the repository\n"
                f"  4. Use --project-url or --project-path to specify project manually"
            )
            raise ValueError(error_msg)

    def parse_git_url(self, remote_url: str) -> Optional[tuple[str, str]]:
        """
        Parse Git URL to extract GitLab URL and project path.

        Args:
            remote_url: Git remote URL

        Returns:
            Tuple of (gitlab_url, project_path) if successful, None otherwise

        Raises:
            ValueError: If URL format is unrecognized but appears to be intended for GitLab
        """
        if not remote_url:
            return None

        logger.debug(f"Parsing Git URL: {remote_url}")

        # Try parsing as HTTPS URL first
        result = parse_https_git_url(remote_url)
        if result:
            gitlab_url, project_path = result
            if is_gitlab_url(gitlab_url):
                logger.debug(
                    f"Successfully parsed HTTPS Git URL: {gitlab_url}/{project_path}"
                )
                return result
            else:
                logger.debug(
                    f"HTTPS URL parsed but not a GitLab instance: {gitlab_url}"
                )

        # Try parsing as SSH URL
        result = parse_ssh_git_url(remote_url)
        if result:
            gitlab_url, project_path = result
            if is_gitlab_url(gitlab_url):
                logger.debug(
                    f"Successfully parsed SSH Git URL: {gitlab_url}/{project_path}"
                )
                return result
            else:
                logger.debug(f"SSH URL parsed but not a GitLab instance: {gitlab_url}")

        # Check if this looks like it might be a GitLab URL but in an unrecognized format
        if self._looks_like_gitlab_url(remote_url):
            error_msg = (
                f"Unrecognized GitLab URL format: {remote_url}\n\n"
                f"This URL appears to be for GitLab but is in an unsupported format.\n\n"
                f"Supported GitLab remote formats:\n"
                f"  • HTTPS: https://gitlab.com/namespace/project.git\n"
                f"  • HTTPS (no .git): https://gitlab.com/namespace/project\n"
                f"  • SSH: git@gitlab.com:namespace/project.git\n"
                f"  • SSH (no .git): git@gitlab.com:namespace/project\n\n"
                f"To resolve this issue:\n"
                f"  1. Update remote URL to supported format: git remote set-url origin <correct-url>\n"
                f"  2. Use --project-url or --project-path to specify project manually\n\n"
                f"Examples of correct formats:\n"
                f"  • git remote set-url origin https://gitlab.com/namespace/project.git\n"
                f"  • git remote set-url origin git@gitlab.com:namespace/project.git"
            )
            raise ValueError(error_msg)

        logger.debug(f"Could not parse Git URL as GitLab URL: {remote_url}")
        return None

    def _looks_like_gitlab_url(self, url: str) -> bool:
        """
        Check if URL looks like it might be intended for GitLab but in wrong format.

        Args:
            url: URL to check

        Returns:
            True if URL appears to be GitLab-related but unparseable
        """
        if not url:
            return False

        url_lower = url.lower()

        # Check for GitLab-related keywords in the URL
        gitlab_indicators = [
            "gitlab.com",
            "gitlab.",
            ".gitlab.",
            "git.lab",
        ]

        return any(indicator in url_lower for indicator in gitlab_indicators)


class ProjectResolver:
    """Core component responsible for parsing URLs and resolving project IDs from GitLab API."""

    def __init__(self, gitlab_client):
        """
        Initialize ProjectResolver with GitLab client.

        Args:
            gitlab_client: Authenticated GitLab client
        """
        self.gl = gitlab_client
        self.project_cache: dict[str, int] = {}

    def parse_project_url(self, url: str) -> ProjectInfo:
        """
        Parse GitLab project URL into components.

        Args:
            url: GitLab project URL to parse

        Returns:
            ProjectInfo with parsed components

        Raises:
            ValueError: If URL format is invalid
        """
        if not url or not isinstance(url, str):
            raise ValueError("URL must be a non-empty string")

        # Normalize URL - remove trailing slashes
        normalized_url = url.rstrip("/")

        try:
            parsed = urlparse(normalized_url)
        except Exception as e:
            raise ValueError(f"Invalid URL format: {e}")

        # Validate protocol
        if parsed.scheme not in ["http", "https"]:
            raise ValueError(
                f"Unsupported protocol '{parsed.scheme}'. Only HTTP and HTTPS are supported."
            )

        # Validate that we have a hostname
        if not parsed.netloc:
            raise ValueError("URL must include a hostname")

        # Extract path components
        path = parsed.path.strip("/")
        if not path:
            raise ValueError("URL must include a project path")

        # Split path into components
        path_parts = path.split("/")
        if len(path_parts) < 2:
            raise ValueError(
                "URL must include both namespace and project name (e.g., /namespace/project)"
            )

        # Extract namespace and project name
        # Handle cases where there might be additional path components after the project name
        namespace = path_parts[0]
        project_name = path_parts[1]

        if not namespace or not project_name:
            raise ValueError("Both namespace and project name must be non-empty")

        # Construct GitLab instance URL
        gitlab_url = f"{parsed.scheme}://{parsed.netloc}"

        # Construct project path
        project_path = f"{namespace}/{project_name}"

        return ProjectInfo(
            gitlab_url=gitlab_url,
            namespace=namespace,
            project_name=project_name,
            project_path=project_path,
            original_url=url,
        )

    def resolve_project_id(self, gitlab_url: str, project_path: str) -> int:
        """
        Resolve project ID from GitLab API with enhanced retry logic.

        Args:
            gitlab_url: GitLab instance URL
            project_path: Project path (namespace/project)

        Returns:
            Numeric project ID

        Raises:
            ValueError: If project cannot be resolved
        """
        # Check cache first
        cache_key = f"{gitlab_url}/{project_path}"
        if cache_key in self.project_cache:
            logger.info(f"Using cached project ID for {project_path}")
            return self.project_cache[cache_key]

        logger.info(f"Resolving project ID for {project_path} from {gitlab_url}")

        def _resolve_project():
            """Internal function to resolve project ID."""
            project = self.gl.projects.get(project_path)
            return project.id

        try:
            project_id = handle_network_error_with_retry(
                operation_name=f"Project resolution for {project_path}",
                operation_func=_resolve_project,
            )

            # Cache the result
            self.project_cache[cache_key] = project_id
            logger.info(
                f"Successfully resolved project ID {project_id} for {project_path}"
            )
            return project_id

        except Exception as e:
            # Use enhanced error handling with context
            context = {
                "project_path": project_path,
                "gitlab_url": gitlab_url,
                "operation": "project resolution",
            }
            enhanced_message = enhance_error_message(e, context)
            raise ValueError(enhanced_message)

    def validate_project_access(self, project_id: int) -> bool:
        """
        Validate that the user has access to the project.

        Args:
            project_id: GitLab project ID

        Returns:
            True if user has access, False otherwise
        """
        try:
            logger.debug(f"Validating access to project ID {project_id}")

            def _validate_access():
                """Internal function to validate project access."""
                project = self.gl.projects.get(project_id)
                # Check if we can access basic project information
                project_name = getattr(project, "name", None)
                project_path = getattr(project, "path_with_namespace", None)
                return project_name, project_path

            project_name, project_path = handle_network_error_with_retry(
                operation_name=f"Access validation for project ID {project_id}",
                operation_func=_validate_access,
            )

            if project_name and project_path:
                logger.info(
                    f"Access validated for project: {project_path} (ID: {project_id})"
                )
                return True
            else:
                logger.warning(
                    f"Project {project_id} exists but has limited metadata access"
                )
                return False

        except Exception as e:
            error_msg = str(e)
            logger.warning(
                f"Access validation failed for project ID {project_id}: {error_msg}"
            )

            # Provide specific guidance based on error type
            context = {
                "project_path": f"project ID {project_id}",
                "gitlab_url": self.gl.api_url.replace("/api/v4", ""),
                "operation": "access validation",
            }

            enhanced_message = enhance_error_message(e, context)
            logger.error(enhanced_message)

            return False


# URL Parsing Functions


def parse_https_git_url(url: str) -> Optional[tuple[str, str]]:
    """
    Parse HTTPS Git URL to extract GitLab URL and project path.

    Args:
        url: HTTPS Git URL (e.g., https://gitlab.com/namespace/project.git)

    Returns:
        Tuple of (gitlab_url, project_path) if successful, None otherwise

    Note:
        Returns None for invalid formats. For detailed error messages,
        use the GitAutoDetector.parse_git_url method which provides
        comprehensive error handling.
    """
    if not url or not isinstance(url, str):
        return None

    try:
        parsed = urlparse(url.strip())

        # Validate HTTPS protocol
        if parsed.scheme != "https":
            return None

        # Validate hostname exists
        if not parsed.netloc:
            return None

        # Extract path and remove leading/trailing slashes
        path = parsed.path.strip("/")
        if not path:
            return None

        # Remove .git suffix if present
        if path.endswith(".git"):
            path = path[:-4]

        # Split path into components
        path_parts = path.split("/")
        if len(path_parts) < 2:
            return None

        # Use all path components to construct the full project path
        # This handles multi-level paths like "LinaroLtd/iotil/meta-onelab"
        project_path = "/".join(path_parts)

        # Construct GitLab instance URL
        gitlab_url = f"{parsed.scheme}://{parsed.netloc}"

        return gitlab_url, project_path

    except Exception:
        return None


def parse_ssh_git_url(url: str) -> Optional[tuple[str, str]]:
    """
    Parse SSH Git URL to extract GitLab URL and project path.

    Args:
        url: SSH Git URL (e.g., git@gitlab.com:namespace/project.git)

    Returns:
        Tuple of (gitlab_url, project_path) if successful, None otherwise

    Note:
        Returns None for invalid formats. For detailed error messages,
        use the GitAutoDetector.parse_git_url method which provides
        comprehensive error handling.
    """
    if not url or not isinstance(url, str):
        return None

    try:
        url = url.strip()

        # Check for SSH format: git@hostname:path
        if not url.startswith("git@") or ":" not in url:
            return None

        # Split on the first colon to separate host and path
        host_part, path_part = url.split(":", 1)

        # Extract hostname from git@hostname
        if not host_part.startswith("git@"):
            return None

        hostname = host_part[4:]  # Remove "git@" prefix
        if not hostname:
            return None

        # Process path part
        path = path_part.strip("/")
        if not path:
            return None

        # Remove .git suffix if present
        if path.endswith(".git"):
            path = path[:-4]

        # Split path into components
        path_parts = path.split("/")
        if len(path_parts) < 2:
            return None

        # Use all path components to construct the full project path
        # This handles multi-level paths like "LinaroLtd/iotil/meta-onelab"
        project_path = "/".join(path_parts)

        # Construct GitLab instance URL (assume HTTPS)
        gitlab_url = f"https://{hostname}"

        return gitlab_url, project_path

    except Exception:
        return None


def is_gitlab_url(url: str) -> bool:
    """
    Check if URL is a GitLab instance.

    Args:
        url: URL to check

    Returns:
        True if URL appears to be a GitLab instance, False otherwise
    """
    if not url or not isinstance(url, str):
        return False

    try:
        parsed = urlparse(url.strip())

        # Must have valid scheme and hostname
        if parsed.scheme not in ["http", "https"] or not parsed.netloc:
            return False

        hostname = parsed.netloc.lower()

        # Explicitly exclude known non-GitLab services
        non_gitlab_services = [
            "github.com",
            "bitbucket.org",
            "sourceforge.net",
            "codeberg.org",
        ]

        for service in non_gitlab_services:
            if hostname == service or hostname.endswith(f".{service}"):
                return False

        # Check for common GitLab hostnames
        gitlab_indicators = [
            "gitlab.com",
            "gitlab.",
            ".gitlab.",
            "git.lab",
        ]

        # Check if hostname contains GitLab indicators
        for indicator in gitlab_indicators:
            if indicator in hostname:
                return True

        # If no obvious indicators, assume it could be a GitLab instance
        # This is a permissive approach since many organizations use custom domains
        return True

    except Exception:
        return False


# Utility Functions


def get_gitlab_token(cli_token: str | None) -> str:
    """
    Get GitLab token from environment variable or CLI argument.

    Priority:
    1. CLI argument (--token) - explicit user choice takes precedence
    2. GITLAB_TOKEN environment variable - fallback

    Args:
        cli_token: Token provided via CLI argument

    Returns:
        GitLab authentication token

    Raises:
        ValueError: If no token is provided
    """
    if cli_token:
        logger.info("Using GitLab token from CLI argument")
        return cli_token

    token = os.environ.get("GITLAB_TOKEN")
    if token:
        logger.info("Using GitLab token from GITLAB_TOKEN environment variable")
        return token

    raise ValueError(
        "No GitLab token provided. Set GITLAB_TOKEN environment variable or use --token argument"
    )


def validate_project_input(
    args: argparse.Namespace,
) -> tuple[Optional[str], Optional[str]]:
    """
    Validate project URL or path input and return GitLab URL and project path.
    Attempts Git auto-detection when no project is explicitly specified.

    Args:
        args: Parsed command-line arguments

    Returns:
        Tuple of (gitlab_url, project_path) or (None, None) if no project input provided and auto-detection fails

    Raises:
        ValueError: If project input is invalid
    """
    if args.project_url:
        logger.info(f"Validating project URL: {args.project_url}")
        validation_result = validate_url_format(args.project_url)

        if not validation_result.is_valid:
            raise ValueError(f"Invalid project URL: {validation_result.error_message}")

        gitlab_url = validation_result.parsed_components["gitlab_url"]
        project_path = validation_result.parsed_components["project_path"]

        logger.info(f"Parsed GitLab URL: {gitlab_url}")
        logger.info(f"Parsed project path: {project_path}")

        return gitlab_url, project_path

    elif args.project_path:
        logger.info(f"Validating project path: {args.project_path}")

        try:
            normalized_path = normalize_project_path(args.project_path)
            logger.info(f"Normalized project path: {normalized_path}")

            # Use the provided GitLab URL or default
            gitlab_url = getattr(args, "gitlab_url", DEFAULT_GITLAB_URL)
            logger.info(f"Using GitLab URL: {gitlab_url}")

            return gitlab_url, normalized_path

        except ValueError as e:
            raise ValueError(f"Invalid project path: {e}")

    else:
        # No project URL or path provided - attempt Git auto-detection
        logger.info("No project specified, attempting Git auto-detection...")

        try:
            detector = GitAutoDetector()
            repo = detector.find_git_repository()

            if not repo:
                logger.info("No Git repository found for auto-detection")
                return None, None

            logger.info(f"Found Git repository at: {repo.working_dir}")

            gitlab_remotes = detector.get_gitlab_remotes(repo)

            if not gitlab_remotes:
                logger.info("No GitLab remotes found in repository")
                return None, None

            # Use the first (prioritized) GitLab remote
            selected_remote = gitlab_remotes[0]
            logger.info(
                f"Auto-detected project from Git remote '{selected_remote.name}': {selected_remote.gitlab_url}/{selected_remote.project_path}"
            )

            return selected_remote.gitlab_url, selected_remote.project_path

        except Exception as e:
            logger.warning(f"Git auto-detection failed: {e}")
            return None, None


# Network Error Handling Functions


def is_network_error(exception: Exception) -> bool:
    """
    Determine if an exception is a network-related error that should be retried.

    Args:
        exception: Exception to check

    Returns:
        True if the exception is a network error that should be retried
    """
    try:
        from gitlab.exceptions import GitlabError

        # Check for GitLab-specific network errors
        if isinstance(exception, GitlabError):
            error_msg = str(exception).lower()
            # Network-related GitLab errors
            if any(
                keyword in error_msg
                for keyword in [
                    "connection",
                    "timeout",
                    "network",
                    "unreachable",
                    "temporary",
                    "service unavailable",
                    "502",
                    "503",
                    "504",
                ]
            ):
                return True
    except ImportError:
        # gitlab module not available, skip GitLab-specific checks
        pass

    # Check for generic network-related error messages
    error_msg = str(exception).lower()
    network_keywords = [
        "connection refused",
        "connection reset",
        "connection timeout",
        "network is unreachable",
        "temporary failure",
        "service unavailable",
        "bad gateway",
        "gateway timeout",
        "connection aborted",
        "connection error",
        "timeout",
        "dns",
    ]

    return any(keyword in error_msg for keyword in network_keywords)


def is_rate_limit_error(exception: Exception) -> bool:
    """
    Determine if an exception is a rate limiting error.

    Args:
        exception: Exception to check

    Returns:
        True if the exception is a rate limiting error
    """
    error_msg = str(exception).lower()
    rate_limit_keywords = [
        "rate limit",
        "too many requests",
        "429",
        "quota exceeded",
        "api rate limit exceeded",
        "rate limited",
    ]

    return any(keyword in error_msg for keyword in rate_limit_keywords)


def calculate_retry_delay(attempt: int, base_delays: list[int] = None) -> int:
    """
    Calculate retry delay with exponential backoff.

    Args:
        attempt: Current attempt number (0-based)
        base_delays: List of base delays for exponential backoff

    Returns:
        Delay in seconds
    """
    if base_delays is None:
        base_delays = RETRY_DELAYS

    if attempt < len(base_delays):
        return base_delays[attempt]
    else:
        # For attempts beyond the base delays, use exponential backoff
        return base_delays[-1] * (2 ** (attempt - len(base_delays) + 1))


def handle_network_error_with_retry(
    operation_name: str, operation_func, max_retries: int = MAX_RETRIES, *args, **kwargs
):
    """
    Execute an operation with comprehensive network error handling and retry logic.

    Args:
        operation_name: Human-readable name of the operation for logging
        operation_func: Function to execute
        max_retries: Maximum number of retry attempts
        *args: Arguments to pass to operation_func
        **kwargs: Keyword arguments to pass to operation_func

    Returns:
        Result of operation_func

    Raises:
        Exception: If operation fails after all retries
    """
    last_exception = None

    for attempt in range(max_retries):
        try:
            logger.debug(f"{operation_name} attempt {attempt + 1}/{max_retries}")
            return operation_func(*args, **kwargs)

        except Exception as e:
            last_exception = e
            error_msg = str(e)

            logger.warning(
                f"{operation_name} attempt {attempt + 1} failed: {error_msg}"
            )

            # Check if this is a rate limit error
            if is_rate_limit_error(e):
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Rate limit detected. Waiting {RATE_LIMIT_RETRY_DELAY} seconds before retry..."
                    )
                    time.sleep(RATE_LIMIT_RETRY_DELAY)
                    continue
                else:
                    raise ValueError(
                        f"{operation_name} failed due to rate limiting after {max_retries} attempts. "
                        f"Please wait before retrying. Last error: {error_msg}"
                    )

            # Check if this is a network error that should be retried
            elif is_network_error(e):
                if attempt < max_retries - 1:
                    delay = calculate_retry_delay(attempt)
                    logger.info(
                        f"Network error detected. Retrying {operation_name} in {delay} seconds..."
                    )
                    time.sleep(delay)
                    continue
                else:
                    raise ValueError(
                        f"{operation_name} failed due to persistent network errors after {max_retries} attempts. "
                        f"Please check your network connection and GitLab instance availability. "
                        f"Last error: {error_msg}"
                    )

            # For non-network errors, don't retry but provide context
            else:
                raise e

    # This should never be reached, but just in case
    if last_exception:
        raise last_exception
    else:
        raise RuntimeError(f"{operation_name} failed unexpectedly")


# Specific Error Handling Functions


def handle_project_not_found_error(
    project_path: str, gitlab_url: str, original_error: str
) -> str:
    """
    Generate helpful error message for project not found errors.

    Args:
        project_path: Project path that was not found
        gitlab_url: GitLab instance URL
        original_error: Original error message

    Returns:
        Enhanced error message with suggestions
    """
    return (
        f"Project '{project_path}' not found at {gitlab_url}.\n\n"
        f"Please check the following:\n"
        f"  • Project path format is correct (should be: namespace/project-name)\n"
        f"  • Project exists and is accessible at {gitlab_url}\n"
        f"  • You have permission to view the project\n"
        f"  • GitLab instance URL is correct\n"
        f"  • Project is not private (if using public access)\n\n"
        f"Examples of valid project paths:\n"
        f"  • mycompany/my-project\n"
        f"  • group/subgroup/project-name\n"
        f"  • username/personal-project\n\n"
        f"You can verify the project exists by visiting:\n"
        f"  {gitlab_url}/{project_path}\n\n"
        f"Original error: {original_error}"
    )


def handle_authentication_error(
    project_path: str, gitlab_url: str, original_error: str
) -> str:
    """
    Generate helpful error message for authentication failures.

    Args:
        project_path: Project path being accessed
        gitlab_url: GitLab instance URL
        original_error: Original error message

    Returns:
        Enhanced error message with guidance
    """
    return (
        f"Authentication failed for project '{project_path}' at {gitlab_url}.\n\n"
        f"Please check the following:\n"
        f"  • GitLab token is valid and not expired\n"
        f"  • Token has appropriate permissions (minimum: 'read_api' scope)\n"
        f"  • Token is configured for the correct GitLab instance\n"
        f"  • You have access to the project '{project_path}'\n"
        f"  • Project is not private (if token lacks permissions)\n\n"
        f"Token configuration:\n"
        f"  • Set GITLAB_TOKEN environment variable, or\n"
        f"  • Use --token command line argument\n\n"
        f"To create a new token:\n"
        f"  1. Visit: {gitlab_url}/-/profile/personal_access_tokens\n"
        f"  2. Create token with 'api' or 'read_api' scope\n"
        f"  3. Set GITLAB_TOKEN environment variable\n\n"
        f"Original error: {original_error}"
    )


def handle_permission_error(
    project_path: str, gitlab_url: str, operation: str, original_error: str
) -> str:
    """
    Generate helpful error message for permission errors.

    Args:
        project_path: Project path being accessed
        gitlab_url: GitLab instance URL
        operation: Operation that failed (e.g., "upload", "read packages")
        original_error: Original error message

    Returns:
        Enhanced error message with guidance
    """
    return (
        f"Permission denied for {operation} in project '{project_path}' at {gitlab_url}.\n\n"
        f"Please check the following:\n"
        f"  • You have the required permissions for this operation\n"
        f"  • Your GitLab token has sufficient scope (may need 'api' instead of 'read_api')\n"
        f"  • You are a member of the project with appropriate role\n"
        f"  • Project settings allow the requested operation\n\n"
        f"Required permissions for {operation}:\n"
        f"  • Package uploads: Developer role or higher\n"
        f"  • Package downloads: Reporter role or higher\n"
        f"  • Project access: Guest role or higher\n\n"
        f"To check your permissions:\n"
        f"  1. Visit: {gitlab_url}/{project_path}/-/project_members\n"
        f"  2. Verify your role and permissions\n"
        f"  3. Contact project maintainer if access is needed\n\n"
        f"Original error: {original_error}"
    )


def handle_network_connectivity_error(gitlab_url: str, original_error: str) -> str:
    """
    Generate helpful error message for network connectivity issues.

    Args:
        gitlab_url: GitLab instance URL
        original_error: Original error message

    Returns:
        Enhanced error message with troubleshooting steps
    """
    return (
        f"Network connectivity issue with GitLab instance at {gitlab_url}.\n\n"
        f"Please check the following:\n"
        f"  • Internet connection is working\n"
        f"  • GitLab instance URL is correct and accessible\n"
        f"  • No firewall or proxy blocking the connection\n"
        f"  • GitLab instance is not experiencing downtime\n\n"
        f"Troubleshooting steps:\n"
        f"  1. Test connectivity: curl -I {gitlab_url}\n"
        f"  2. Check GitLab status page (if available)\n"
        f"  3. Try accessing {gitlab_url} in a web browser\n"
        f"  4. Verify DNS resolution: nslookup {gitlab_url.replace('https://', '').replace('http://', '')}\n\n"
        f"If using a corporate network:\n"
        f"  • Check proxy settings\n"
        f"  • Verify SSL certificate trust\n"
        f"  • Contact IT support if needed\n\n"
        f"Original error: {original_error}"
    )


def enhance_error_message(error: Exception, context: dict) -> str:
    """
    Enhance error messages with context and helpful suggestions.

    Args:
        error: Original exception
        context: Context dictionary with keys like 'project_path', 'gitlab_url', 'operation'

    Returns:
        Enhanced error message
    """
    error_msg = str(error).lower()
    original_error = str(error)

    project_path = context.get("project_path", "unknown")
    gitlab_url = context.get("gitlab_url", "unknown")
    operation = context.get("operation", "operation")

    # Handle specific error types
    if "404" in error_msg or "not found" in error_msg:
        return handle_project_not_found_error(project_path, gitlab_url, original_error)

    elif any(
        keyword in error_msg
        for keyword in ["401", "403", "authentication", "unauthorized"]
    ):
        if "permission" in error_msg or "forbidden" in error_msg:
            return handle_permission_error(
                project_path, gitlab_url, operation, original_error
            )
        else:
            return handle_authentication_error(project_path, gitlab_url, original_error)

    elif any(
        keyword in error_msg
        for keyword in [
            "connection",
            "network",
            "timeout",
            "unreachable",
            "dns",
            "resolve",
        ]
    ):
        return handle_network_connectivity_error(gitlab_url, original_error)

    elif "rate limit" in error_msg or "too many requests" in error_msg:
        return (
            f"GitLab API rate limit exceeded.\n\n"
            f"Please wait a few minutes before retrying.\n"
            f"Rate limits help ensure fair usage of GitLab resources.\n\n"
            f"If you frequently hit rate limits:\n"
            f"  • Reduce the frequency of API calls\n"
            f"  • Consider using GitLab Premium for higher limits\n"
            f"  • Contact GitLab support for assistance\n\n"
            f"Original error: {original_error}"
        )

    else:
        # Generic enhancement with context
        return (
            f"Operation failed: {operation}\n"
            f"Project: {project_path}\n"
            f"GitLab URL: {gitlab_url}\n\n"
            f"Error details: {original_error}\n\n"
            f"If this error persists:\n"
            f"  • Check GitLab instance status\n"
            f"  • Verify your network connection\n"
            f"  • Review your authentication and permissions\n"
            f"  • Contact support with the error details above"
        )


# Helper functions for URL validation (used by validate_project_input)


@dataclass
class URLValidationResult:
    """Represents URL parsing and validation results."""

    is_valid: bool
    error_message: Optional[str]
    suggested_format: Optional[str]
    parsed_components: Optional[dict[str, str]]


def parse_gitlab_url(url: str) -> tuple[str, str]:
    """
    Extract GitLab instance URL and project path from full URL.

    Args:
        url: Full GitLab project URL

    Returns:
        Tuple of (gitlab_instance_url, project_path)

    Raises:
        ValueError: If URL format is invalid
    """
    if not url or not isinstance(url, str):
        raise ValueError(
            f"URL must be a non-empty string.\n"
            f"Attempted URL: '{url}'\n\n"
            f"Valid format examples:\n"
            f"  - https://gitlab.com/namespace/project\n"
            f"  - http://gitlab.example.com/group/subgroup/project"
        )

    # Normalize URL - remove trailing slashes
    normalized_url = url.rstrip("/")

    try:
        parsed = urlparse(normalized_url)
    except Exception as e:
        raise ValueError(
            f"Invalid URL format: {e}\n"
            f"Attempted URL: '{url}'\n\n"
            f"Valid format examples:\n"
            f"  - https://gitlab.com/namespace/project\n"
            f"  - http://gitlab.example.com/group/subgroup/project"
        )

    # Validate protocol
    if parsed.scheme not in ["http", "https"]:
        raise ValueError(
            f"Unsupported protocol '{parsed.scheme}'. Only HTTP and HTTPS are supported.\n"
            f"Attempted URL: '{url}'\n\n"
            f"Valid format examples:\n"
            f"  - https://gitlab.com/namespace/project\n"
            f"  - http://gitlab.example.com/group/subgroup/project"
        )

    # Validate that we have a hostname
    if not parsed.netloc:
        raise ValueError(
            f"URL must include a hostname.\n"
            f"Attempted URL: '{url}'\n\n"
            f"Valid format examples:\n"
            f"  - https://gitlab.com/namespace/project\n"
            f"  - http://gitlab.example.com/group/subgroup/project"
        )

    # Extract path components
    path = parsed.path.strip("/")
    if not path:
        raise ValueError(
            f"URL must include a project path.\n"
            f"Attempted URL: '{url}'\n\n"
            f"Valid format examples:\n"
            f"  - https://gitlab.com/namespace/project\n"
            f"  - http://gitlab.example.com/group/subgroup/project"
        )

    # Split path into components
    path_parts = path.split("/")
    if len(path_parts) < 2:
        raise ValueError(
            f"URL must include both namespace and project name.\n"
            f"Attempted URL: '{url}'\n\n"
            f"Valid format examples:\n"
            f"  - https://gitlab.com/namespace/project\n"
            f"  - http://gitlab.example.com/group/subgroup/project"
        )

    # Extract namespace and project name
    namespace = path_parts[0]
    project_name = path_parts[1]

    if not namespace or not project_name:
        raise ValueError(
            f"Both namespace and project name must be non-empty.\n"
            f"Attempted URL: '{url}'\n\n"
            f"Valid format examples:\n"
            f"  - https://gitlab.com/namespace/project\n"
            f"  - http://gitlab.example.com/group/subgroup/project"
        )

    # Construct GitLab instance URL
    gitlab_url = f"{parsed.scheme}://{parsed.netloc}"

    # Construct project path
    project_path = f"{namespace}/{project_name}"

    return gitlab_url, project_path


def validate_url_format(url: str) -> URLValidationResult:
    """
    Validate that URL follows expected GitLab project URL format.

    Args:
        url: URL to validate

    Returns:
        URLValidationResult with validation status and details
    """
    try:
        gitlab_url, project_path = parse_gitlab_url(url)
        return URLValidationResult(
            is_valid=True,
            error_message=None,
            suggested_format=None,
            parsed_components={"gitlab_url": gitlab_url, "project_path": project_path},
        )
    except ValueError as e:
        return URLValidationResult(
            is_valid=False,
            error_message=str(e),
            suggested_format="https://gitlab.com/namespace/project",
            parsed_components=None,
        )


def normalize_project_path(path: str) -> str:
    """
    Normalize project path handling URL encoding and special characters.

    Args:
        path: Project path to normalize

    Returns:
        Normalized project path

    Raises:
        ValueError: If path format is invalid
    """
    if not path or not isinstance(path, str):
        raise ValueError(
            f"Project path must be a non-empty string.\n"
            f"Attempted path: '{path}'\n\n"
            f"Valid format examples:\n"
            f"  - namespace/project\n"
            f"  - group/subgroup/project"
        )

    # Remove leading/trailing slashes and whitespace
    normalized = path.strip().strip("/")

    if not normalized:
        raise ValueError(
            f"Project path cannot be empty.\n"
            f"Attempted path: '{path}'\n\n"
            f"Valid format examples:\n"
            f"  - namespace/project\n"
            f"  - group/subgroup/project"
        )

    # Split into components
    parts = normalized.split("/")
    if len(parts) < 2:
        raise ValueError(
            f"Project path must include both namespace and project name.\n"
            f"Attempted path: '{path}'\n\n"
            f"Valid format examples:\n"
            f"  - namespace/project\n"
            f"  - group/subgroup/project"
        )

    # Validate that all parts are non-empty
    for i, part in enumerate(parts):
        if not part.strip():
            raise ValueError(
                f"Project path component {i + 1} cannot be empty.\n"
                f"Attempted path: '{path}'\n\n"
                f"Valid format examples:\n"
                f"  - namespace/project\n"
                f"  - group/subgroup/project"
            )

    return normalized


# Configuration Validation Functions


def validate_dependencies() -> None:
    """
    Validate that all required dependencies are available.

    Raises:
        ValueError: If required dependencies are missing with specific resolution steps
    """
    logger.debug("Validating required dependencies...")

    # Check Python version
    import sys

    if sys.version_info < (3, 12):
        raise ValueError(
            f"Python 3.12 or higher is required. Current version: {sys.version}\n\n"
            "SOLUTION:\n"
            "1. Install Python 3.12 or higher:\n"
            "   • Ubuntu/Debian: sudo apt update && sudo apt install python3.12\n"
            "   • macOS: brew install python@3.12\n"
            "   • Windows: Download from https://python.org/downloads/\n\n"
            "2. Use pyenv to manage Python versions:\n"
            "   • Install pyenv: curl https://pyenv.run | bash\n"
            "   • Install Python: pyenv install 3.12\n"
            "   • Set local version: pyenv local 3.12\n\n"
            "3. Use uv to run with correct Python version:\n"
            "   • Install uv: pip install uv\n"
            "   • Run script: uv run --python 3.12 ./gitlab/gitlab-pkg-upload.py\n\n"
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
            logger.debug(f"✓ Module {module_name} available")
        except ImportError:
            missing_modules.append((module_name, package_spec))
            logger.debug(f"✗ Module {module_name} not available")

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

        raise ValueError(error_msg)

    logger.debug("✓ All required dependencies are available")


def validate_gitlab_token(token: str, gitlab_url: str = DEFAULT_GITLAB_URL) -> None:
    """
    Validate GitLab token availability and basic validity.

    Args:
        token: GitLab authentication token
        gitlab_url: GitLab instance URL

    Raises:
        ValueError: If token validation fails with specific resolution steps
    """
    logger.debug("Validating GitLab token...")

    if not token or not isinstance(token, str):
        raise ValueError(
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
            "• Test token manually: curl -H 'PRIVATE-TOKEN: your-token' {gitlab_url}/api/v4/user\n\n"
            "For more help: https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html"
        )

    # Basic token format validation
    token = token.strip()
    if len(token) < 20:
        raise ValueError(
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
            f"   echo $GITLAB_TOKEN | wc -c  # Should be 20+ characters\n\n"
            "For more help: https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html"
        )

    # Check for common token format issues
    if token.startswith("glpat-") and len(token) < 26:
        raise ValueError(
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

    logger.debug("✓ GitLab token format validation passed")


def validate_git_installation() -> None:
    """
    Validate that Git is installed and accessible.

    Raises:
        ValueError: If Git installation validation fails with specific resolution steps
    """
    logger.debug("Validating Git installation...")

    try:
        import subprocess

        result = subprocess.run(
            ["git", "--version"], capture_output=True, text=True, timeout=10
        )

        if result.returncode != 0:
            raise ValueError(
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
        logger.debug(f"✓ Git is available: {git_version}")

    except FileNotFoundError:
        raise ValueError(
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
        raise ValueError(
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
        raise ValueError(
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


def validate_git_repository_access(working_directory: str = ".") -> None:
    """
    Validate Git repository access when Git operations are needed.

    Args:
        working_directory: Directory to check for Git repository

    Raises:
        ValueError: If Git repository access validation fails with specific resolution steps
    """
    logger.debug(f"Validating Git repository access in: {working_directory}")

    try:
        detector = GitAutoDetector(working_directory)
        repo = detector.find_git_repository()

        if repo:
            logger.debug(f"✓ Git repository found at: {repo.working_dir}")

            # Test basic repository operations
            try:
                # Try to read repository configuration
                repo.config_reader()  # Just verify it's accessible
                logger.debug("✓ Git repository configuration accessible")

                # Try to read remotes
                remotes = list(repo.remotes)
                logger.debug(f"✓ Git remotes accessible: {len(remotes)} remote(s)")

            except Exception as e:
                raise ValueError(
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
        else:
            logger.debug(
                "No Git repository found - this is acceptable for manual project specification"
            )

    except ValueError:
        # Re-raise ValueError exceptions (our custom error messages)
        raise
    except Exception as e:
        raise ValueError(
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


def validate_configuration(
    token: Optional[str] = None,
    gitlab_url: str = DEFAULT_GITLAB_URL,
    require_git: bool = False,
    working_directory: str = ".",
) -> None:
    """
    Comprehensive configuration validation for GitLab scripts.

    Args:
        token: GitLab authentication token (if None, will try to get from environment)
        gitlab_url: GitLab instance URL
        require_git: Whether Git operations are required
        working_directory: Working directory for Git operations

    Raises:
        ValueError: If any configuration validation fails
    """
    logger.info("Starting configuration validation...")

    # 1. Validate dependencies
    try:
        validate_dependencies()
        logger.info("✓ Dependencies validation passed")
    except ValueError:
        logger.error("✗ Dependencies validation failed")
        raise

    # 2. Validate GitLab token
    try:
        if token is None:
            token = get_gitlab_token(None)
        validate_gitlab_token(token, gitlab_url)
        logger.info("✓ GitLab token validation passed")
    except ValueError:
        logger.error("✗ GitLab token validation failed")
        raise

    # 3. Validate Git installation (always check since it might be needed)
    try:
        validate_git_installation()
        logger.info("✓ Git installation validation passed")
    except ValueError as e:
        if require_git:
            logger.error("✗ Git installation validation failed")
            raise
        else:
            logger.warning(
                "⚠ Git installation validation failed (not required for this operation)"
            )
            logger.debug(f"Git validation error: {e}")

    # 4. Validate Git repository access (only if Git operations are required)
    if require_git:
        try:
            validate_git_repository_access(working_directory)
            logger.info("✓ Git repository access validation passed")
        except ValueError:
            logger.error("✗ Git repository access validation failed")
            raise

    logger.info("✓ Configuration validation completed successfully")
