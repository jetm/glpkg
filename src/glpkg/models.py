"""Data models, enums, and exceptions for gitlab-pkg-upload."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from gitlab import Gitlab

    from glpkg.duplicate_detector import DuplicateDetector


# Enums


class DuplicatePolicy(Enum):
    """Defines how the system should handle detected duplicates."""

    SKIP = "skip"  # Skip uploading duplicates (default)
    REPLACE = "replace"  # Delete existing and upload new
    ERROR = "error"  # Fail with error on duplicates


# Data Models - File Operations


@dataclass
class FileFingerprint:
    """Represents a unique identifier for files to enable accurate duplicate detection."""

    source_path: str
    target_filename: str
    sha256_checksum: str
    file_size: int
    timestamp: float


@dataclass
class RemoteFile:
    """Represents a file that exists in the GitLab package registry."""

    file_id: int
    filename: str
    sha256_checksum: Optional[str]
    file_size: int
    download_url: str
    package_name: str
    version: str


@dataclass
class UploadResult:
    """Enhanced upload result structure with duplicate detection information."""

    source_path: str
    target_filename: str
    success: bool
    result: str  # URL on success, error message on failure
    was_duplicate: bool = False
    duplicate_action: Optional[str] = None  # "skipped", "replaced", "error"
    existing_url: Optional[str] = None


# Data Models - Project Resolution


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


# Data Models - Configuration


@dataclass
class UploadConfig:
    """User configuration for upload operation."""

    package_name: str
    version: str
    duplicate_policy: DuplicatePolicy
    retry_count: int
    verbosity: str  # 'normal', 'verbose', 'quiet', 'debug'
    dry_run: bool
    fail_fast: bool
    json_output: bool
    plain_output: bool
    gitlab_url: str
    token: Optional[str]


@dataclass
class UploadContext:
    """Runtime context for upload operations."""

    gl: Gitlab
    config: UploadConfig
    detector: DuplicateDetector
    project_id: int
    project_path: str


# Exception Hierarchy


class GitLabUploadError(Exception):
    """Base exception for GitLab upload errors."""

    exit_code: int = 1


class AuthenticationError(GitLabUploadError):
    """Authentication failed."""

    exit_code: int = 2


class ConfigurationError(GitLabUploadError):
    """Configuration error."""

    exit_code: int = 3


class ProjectResolutionError(GitLabUploadError):
    """Project resolution failed."""

    exit_code: int = 4


class FileValidationError(GitLabUploadError):
    """File validation failed."""

    exit_code: int = 5


class NetworkError(GitLabUploadError):
    """Network error."""

    exit_code: int = 6


class ChecksumValidationError(GitLabUploadError):
    """Checksum validation failed."""

    exit_code: int = 7


# Error Enhancement Functions


def handle_project_not_found_error(project_path: str, gitlab_url: str, original_error: str) -> str:
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


def handle_authentication_error(project_path: str, gitlab_url: str, original_error: str) -> str:
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
        f"  4. Verify DNS resolution: nslookup "
        f"{gitlab_url.replace('https://', '').replace('http://', '')}\n\n"
        f"If using a corporate network:\n"
        f"  • Check proxy settings\n"
        f"  • Verify SSL certificate trust\n"
        f"  • Contact IT support if needed\n\n"
        f"Original error: {original_error}"
    )


def enhance_error_message(error: Exception, context: dict[str, str]) -> str:
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

    elif any(keyword in error_msg for keyword in ["401", "403", "authentication", "unauthorized"]):
        if "permission" in error_msg or "forbidden" in error_msg:
            return handle_permission_error(project_path, gitlab_url, operation, original_error)
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
