"""Upload subcommand for glpkg CLI.

This module provides the upload subcommand implementation, including:
- GitAutoDetector: Auto-detect GitLab project from Git repository
- ProjectResolver: Resolve GitLab project ID from project path
- UploadContextBuilder: Build upload context with all required components
- Upload command registration and execution logic

Supported upload-specific flags:
    Required:
        --package-name      Package name in the registry
        --package-version   Package version

    File input (mutually exclusive):
        --files             List of files to upload
        --directory         Directory containing files to upload

    Project specification:
        --project-url       Full GitLab project URL
        --project-path      Project path (namespace/project)

    Duplicate handling:
        --duplicate-policy  How to handle duplicates: skip, replace, error

    File mapping:
        --file-mapping      Rename files during upload (source:target format)

    Operational:
        --dry-run           Preview actions without executing
        --fail-fast         Stop on first failure
        --retry             Number of retry attempts
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import TYPE_CHECKING, Optional

import git
from gitlab import Gitlab
from gitlab.exceptions import GitlabAuthenticationError, GitlabGetError

from glpkg.cli.main import determine_verbosity
from glpkg.duplicate_detector import DuplicateDetector
from glpkg.formatters import OutputFormatter
from glpkg.models import (
    AuthenticationError,
    ConfigurationError,
    DuplicatePolicy,
    GitLabUploadError,
    GitRemoteInfo,
    ProjectInfo,
    ProjectResolutionError,
    UploadConfig,
    UploadContext,
    enhance_error_message,
)
from glpkg.uploader import upload_files
from glpkg.validators import (
    DEFAULT_GITLAB_URL,
    collect_files,
    get_gitlab_token,
    normalize_gitlab_url,
    parse_git_url,
)

if TYPE_CHECKING:
    pass

# Module-level logger
logger = logging.getLogger(__name__)

# Exception exit code mapping for standard Python exceptions
EXCEPTION_EXIT_CODE_MAP: dict[type, int] = {
    FileNotFoundError: 5,  # File validation failure
    PermissionError: 5,  # File validation failure
    ValueError: 3,  # Configuration error
    ConnectionError: 6,  # Network error
    TimeoutError: 6,  # Network error
}


class GitAutoDetector:
    """Auto-detect GitLab project from Git repository.

    This class handles Git repository discovery and remote parsing to
    automatically detect GitLab project information from the current
    working directory.

    Attributes:
        working_directory: Directory to search for Git repository.
    """

    def __init__(self, working_directory: str = ".") -> None:
        """Initialize GitAutoDetector.

        Args:
            working_directory: Directory to search for Git repository.
                Parent directories are also searched.
        """
        self.working_directory = working_directory

    def find_git_repository(self) -> Optional[git.Repo]:
        """Find Git repository in working directory or parent directories.

        Returns:
            Git repository object if found, None if no repository exists.

        Raises:
            ProjectResolutionError: If repository access fails due to
                permissions, corruption, or other errors.
        """
        try:
            repo = git.Repo(self.working_directory, search_parent_directories=True)
            logger.debug(f"Found Git repository at: {repo.working_dir}")
            return repo
        except git.InvalidGitRepositoryError:
            logger.debug(f"No Git repository found in {self.working_directory}")
            return None
        except PermissionError as e:
            raise ProjectResolutionError(
                f"Permission denied accessing Git repository in '{self.working_directory}': {e}\n\n"
                "SOLUTION:\n"
                "1. Check directory permissions:\n"
                f"   ls -la {self.working_directory}\n\n"
                "2. Use manual project specification:\n"
                "   --project-url https://gitlab.com/namespace/project\n"
                "   --project-path namespace/project"
            )
        except git.GitCommandError as e:
            raise ProjectResolutionError(
                f"Git command error in '{self.working_directory}': {e}\n\n"
                "SOLUTION:\n"
                "1. Check repository status:\n"
                "   git status\n\n"
                "2. Use manual project specification:\n"
                "   --project-url https://gitlab.com/namespace/project\n"
                "   --project-path namespace/project"
            )
        except OSError as e:
            raise ProjectResolutionError(
                f"OS error accessing Git repository in '{self.working_directory}': {e}\n\n"
                "SOLUTION:\n"
                "1. Verify directory exists:\n"
                f"   ls -la {self.working_directory}\n\n"
                "2. Use manual project specification:\n"
                "   --project-url https://gitlab.com/namespace/project\n"
                "   --project-path namespace/project"
            )

    def _looks_like_gitlab_url(self, url: str) -> bool:
        """Check if URL appears to be a GitLab instance.

        Args:
            url: URL to check.

        Returns:
            True if URL contains GitLab-related keywords, False otherwise.
        """
        url_lower = url.lower()
        gitlab_indicators = ["gitlab.com", "gitlab.", ".gitlab.", "git.lab"]
        return any(indicator in url_lower for indicator in gitlab_indicators)

    def _is_known_non_gitlab_host(self, host: str) -> bool:
        """Check if host is a known non-GitLab service.

        Args:
            host: Hostname to check (e.g., 'github.com', 'bitbucket.org').

        Returns:
            True if host is a known non-GitLab service, False otherwise.
        """
        host_lower = host.lower()
        # Known non-GitLab Git hosting services
        non_gitlab_hosts = [
            "github.com",
            "github.",
            ".github.",
            "bitbucket.org",
            "bitbucket.",
            ".bitbucket.",
            "codeberg.org",
            "codeberg.",
            "sr.ht",
            "sourcehut.",
            "gitea.com",
            "gitea.",
            "gogs.",
            "azure.com",
            "dev.azure.com",
            "visualstudio.com",
        ]
        return any(indicator in host_lower for indicator in non_gitlab_hosts)

    def parse_git_url(self, remote_url: str) -> Optional[tuple[str, str]]:
        """Parse a Git remote URL to extract GitLab instance URL and project path.

        Args:
            remote_url: Git remote URL (HTTPS or SSH format).

        Returns:
            Tuple of (gitlab_url, project_path) if successful, None if URL
            is not a GitLab URL or cannot be parsed.

        Raises:
            ProjectResolutionError: If URL looks like GitLab but format is unrecognized.
        """
        try:
            gitlab_url, project_path = parse_git_url(remote_url)

            # Check if this is a known non-GitLab host (GitHub, Bitbucket, etc.)
            if self._is_known_non_gitlab_host(gitlab_url):
                logger.debug(f"Ignoring known non-GitLab host: {gitlab_url}")
                return None

            # Validate this is a GitLab instance
            if self._looks_like_gitlab_url(gitlab_url):
                logger.debug(f"Parsed GitLab URL: {gitlab_url}, project: {project_path}")
                return gitlab_url, project_path

            # URL parsed but doesn't look like GitLab - return it anyway
            # (could be self-hosted GitLab without 'gitlab' in hostname)
            logger.debug(
                f"URL parsed but doesn't contain 'gitlab': {gitlab_url}, project: {project_path}"
            )
            return gitlab_url, project_path

        except Exception as e:
            # Check if URL looks like it should be GitLab
            if self._looks_like_gitlab_url(remote_url):
                raise ProjectResolutionError(
                    f"URL appears to be GitLab but format is unrecognized: '{remote_url}'\n\n"
                    f"Parse error: {e}\n\n"
                    "SOLUTION:\n"
                    "Supported Git URL formats:\n"
                    "  - HTTPS: https://gitlab.com/namespace/project.git\n"
                    "  - SSH: git@gitlab.com:namespace/project.git\n\n"
                    "Use manual project specification:\n"
                    "  --project-url https://gitlab.com/namespace/project\n"
                    "  --project-path namespace/project"
                )
            # Not GitLab URL - return None
            logger.debug(f"Could not parse URL as GitLab: {remote_url}")
            return None

    def get_gitlab_remotes(self, repo: git.Repo) -> list[GitRemoteInfo]:
        """Extract GitLab remotes from repository.

        Iterates through repository remotes, identifies GitLab instances,
        and prioritizes 'origin' remote when multiple GitLab remotes exist.

        Args:
            repo: Git repository to extract remotes from.

        Returns:
            List of GitRemoteInfo objects for GitLab remotes, sorted with
            'origin' first if present.

        Raises:
            ProjectResolutionError: If no remotes found or no GitLab remotes detected.
        """
        remotes = list(repo.remotes)

        if not remotes:
            raise ProjectResolutionError(
                "No Git remotes configured in repository.\n\n"
                "SOLUTION:\n"
                "1. Add a Git remote:\n"
                "   git remote add origin https://gitlab.com/namespace/project.git\n\n"
                "2. Or use manual project specification:\n"
                "   --project-url https://gitlab.com/namespace/project\n"
                "   --project-path namespace/project"
            )

        gitlab_remotes: list[GitRemoteInfo] = []
        all_remote_urls: list[str] = []

        for remote in remotes:
            # Get all URLs for this remote
            urls = list(remote.urls)
            all_remote_urls.extend(urls)

            for url in urls:
                parsed = self.parse_git_url(url)
                if parsed:
                    gitlab_url, project_path = parsed
                    gitlab_remotes.append(
                        GitRemoteInfo(
                            name=remote.name,
                            url=url,
                            gitlab_url=gitlab_url,
                            project_path=project_path,
                        )
                    )
                    logger.debug(f"Found GitLab remote '{remote.name}': {project_path}")
                    break  # Only use first valid URL per remote

        if not gitlab_remotes:
            remote_list = "\n".join(f"  - {url}" for url in all_remote_urls)
            raise ProjectResolutionError(
                f"No GitLab remotes found in repository.\n\n"
                f"Found remotes:\n{remote_list}\n\n"
                "SOLUTION:\n"
                "1. Add a GitLab remote:\n"
                "   git remote add origin https://gitlab.com/namespace/project.git\n\n"
                "2. Or use manual project specification:\n"
                "   --project-url https://gitlab.com/namespace/project\n"
                "   --project-path namespace/project\n\n"
                "Supported GitLab URL formats:\n"
                "  - HTTPS: https://gitlab.com/namespace/project.git\n"
                "  - SSH: git@gitlab.com:namespace/project.git"
            )

        # Prioritize 'origin' remote
        gitlab_remotes.sort(key=lambda r: (0 if r.name == "origin" else 1, r.name))

        if len(gitlab_remotes) > 1:
            logger.info(
                f"Multiple GitLab remotes found, using '{gitlab_remotes[0].name}': "
                f"{gitlab_remotes[0].project_path}"
            )

        return gitlab_remotes


class ProjectResolver:
    """Resolve GitLab project ID from project path.

    This class handles GitLab API interactions to resolve project paths
    to project IDs and validate project access.

    Attributes:
        gl: Authenticated GitLab client.
        project_cache: Cache of resolved project IDs.
    """

    def __init__(self, gitlab_client: Gitlab) -> None:
        """Initialize ProjectResolver.

        Args:
            gitlab_client: Authenticated GitLab client instance.
        """
        self.gl = gitlab_client
        self.project_cache: dict[str, int] = {}

    def parse_project_url(self, url: str) -> ProjectInfo:
        """Parse a GitLab project URL into components.

        Args:
            url: Full GitLab project URL.

        Returns:
            ProjectInfo object with parsed components.

        Raises:
            ProjectResolutionError: If URL format is invalid.
        """
        try:
            gitlab_url, project_path = normalize_gitlab_url(url)
        except Exception as e:
            raise ProjectResolutionError(
                f"Invalid GitLab project URL: '{url}'\n\n"
                f"Error: {e}\n\n"
                "SOLUTION:\n"
                "Expected URL format: https://gitlab.com/namespace/project\n\n"
                "Examples:\n"
                "  - https://gitlab.com/mycompany/my-project\n"
                "  - https://gitlab.example.com/group/subgroup/project"
            )

        # Split project_path into namespace and project_name
        path_parts = project_path.split("/")
        namespace = "/".join(path_parts[:-1])
        project_name = path_parts[-1]

        return ProjectInfo(
            gitlab_url=gitlab_url,
            namespace=namespace,
            project_name=project_name,
            project_path=project_path,
            original_url=url,
        )

    def resolve_project_id(self, gitlab_url: str, project_path: str) -> int:
        """Resolve project path to project ID via GitLab API.

        Uses caching to avoid redundant API calls for the same project.

        Args:
            gitlab_url: GitLab instance URL.
            project_path: Project path (namespace/project).

        Returns:
            Project ID.

        Raises:
            ProjectResolutionError: If project cannot be found or accessed.
        """
        cache_key = f"{gitlab_url}/{project_path}"

        # Check cache first
        if cache_key in self.project_cache:
            logger.debug(f"Using cached project ID for {project_path}")
            return self.project_cache[cache_key]

        context = {
            "project_path": project_path,
            "gitlab_url": gitlab_url,
            "operation": "project resolution",
        }

        try:
            logger.debug(f"Resolving project ID for: {project_path}")
            project = self.gl.projects.get(project_path)
            project_id = project.id

            # Cache the result
            self.project_cache[cache_key] = project_id
            logger.info(f"Resolved project '{project_path}' to ID {project_id}")

            return project_id

        except GitlabGetError as e:
            error_msg = enhance_error_message(e, context)
            raise ProjectResolutionError(error_msg)
        except GitlabAuthenticationError as e:
            error_msg = enhance_error_message(e, context)
            raise ProjectResolutionError(error_msg)
        except Exception as e:
            error_msg = enhance_error_message(e, context)
            raise ProjectResolutionError(error_msg)

    def validate_project_access(self, project_id: int) -> bool:
        """Validate that the project is accessible.

        Args:
            project_id: Project ID to validate.

        Returns:
            True if project is accessible, False otherwise.
        """
        try:
            project = self.gl.projects.get(project_id)
            # Check if we can access basic project attributes
            _ = project.name
            _ = project.path_with_namespace
            logger.debug(f"Project access validated: {project.path_with_namespace}")
            return True
        except Exception as e:
            logger.warning(f"Project access validation failed for ID {project_id}: {e}")
            return False


class UploadContextBuilder:
    """Builder for safely initializing upload context with all required components.

    This class follows the builder pattern to create an UploadContext with
    all dependencies properly initialized and validated.
    """

    def __init__(self) -> None:
        """Initialize UploadContextBuilder."""
        pass

    def build(
        self,
        args: argparse.Namespace,
        gl: Gitlab,
        project_id: int,
        project_path: str,
        gitlab_url: str,
        token: str,
    ) -> UploadContext:
        """Build an UploadContext from parsed arguments and resolved project info.

        Args:
            args: Parsed argument namespace from argparse.
            gl: Authenticated GitLab client.
            project_id: Resolved GitLab project ID.
            project_path: Resolved project path (namespace/project).
            gitlab_url: GitLab instance URL.
            token: Resolved GitLab API token (from CLI or environment).

        Returns:
            Fully initialized UploadContext ready for upload operations.

        Raises:
            ConfigurationError: If context building fails due to configuration issues.
        """
        try:
            # Determine verbosity level
            verbosity = determine_verbosity(args)

            # Create UploadConfig from parsed arguments
            config = UploadConfig(
                package_name=args.package_name,
                version=args.package_version,
                duplicate_policy=args.duplicate_policy,
                retry_count=args.retry,
                verbosity=verbosity,
                dry_run=args.dry_run,
                fail_fast=args.fail_fast,
                json_output=getattr(args, "json_output", False),
                plain_output=getattr(args, "plain", False),
                gitlab_url=gitlab_url,
                token=token,  # Resolved token (from CLI or environment)
            )

            logger.debug(f"Created UploadConfig: package={config.package_name}, version={config.version}")

            # Initialize DuplicateDetector
            detector = DuplicateDetector(gl, project_id)
            logger.debug(f"Initialized DuplicateDetector for project ID {project_id}")

            # Create and return UploadContext
            context = UploadContext(
                gl=gl,
                config=config,
                detector=detector,
                project_id=project_id,
                project_path=project_path,
            )

            logger.info(f"Built upload context for {project_path} (ID: {project_id})")
            logger.debug(
                f"Context details: package={config.package_name}, version={config.version}, "
                f"duplicate_policy={config.duplicate_policy.value}, dry_run={config.dry_run}"
            )

            return context

        except Exception as e:
            raise ConfigurationError(
                f"Failed to build upload context: {e}\n\n"
                "SOLUTION:\n"
                "  - Verify all required arguments are provided\n"
                "  - Check that project ID is valid\n"
                "  - Ensure GitLab client is properly authenticated"
            )


def auto_detect_project() -> tuple[str, str]:
    """Auto-detect GitLab project from git repository.

    Searches for a Git repository in the current directory and parent
    directories, then extracts GitLab project information from git remotes.

    Returns:
        Tuple of (gitlab_url, project_path).

    Raises:
        ProjectResolutionError: If auto-detection fails.
    """
    detector = GitAutoDetector()

    # Find git repository
    repo = detector.find_git_repository()
    if repo is None:
        raise ProjectResolutionError(
            "No Git repository found in current directory or parent directories.\n\n"
            "SOLUTION:\n"
            "1. Ensure you're in a Git repository:\n"
            "   git status\n\n"
            "2. Initialize a repository if needed:\n"
            "   git init\n"
            "   git remote add origin https://gitlab.com/namespace/project.git\n\n"
            "3. Or use manual project specification:\n"
            "   --project-url https://gitlab.com/namespace/project\n"
            "   --project-path namespace/project"
        )

    # Get GitLab remotes
    gitlab_remotes = detector.get_gitlab_remotes(repo)

    # Select first (prioritized) remote
    selected_remote = gitlab_remotes[0]
    gitlab_url = selected_remote.gitlab_url
    project_path = selected_remote.project_path

    logger.info(f"Auto-detected project: {project_path} from {gitlab_url}")

    return gitlab_url, project_path


def resolve_project_manually(
    project_url: str | None,
    project_path: str | None,
    gitlab_url: str,
) -> tuple[str, str]:
    """Resolve project from manual specification.

    Args:
        project_url: Full GitLab project URL (mutually exclusive with project_path).
        project_path: Project path in namespace/project format.
        gitlab_url: GitLab instance URL (used with project_path).

    Returns:
        Tuple of (gitlab_url, project_path).

    Raises:
        ProjectResolutionError: If project specification is invalid.
    """
    if project_url:
        # Parse full project URL
        try:
            resolved_gitlab_url, resolved_project_path = normalize_gitlab_url(project_url)
            logger.info(f"Using project URL: {project_url}")
            return resolved_gitlab_url, resolved_project_path
        except Exception as e:
            raise ProjectResolutionError(
                f"Invalid project URL: '{project_url}'\n\n"
                f"Error: {e}\n\n"
                "SOLUTION:\n"
                "Expected URL format: https://gitlab.com/namespace/project\n\n"
                "Examples:\n"
                "  - https://gitlab.com/mycompany/my-project\n"
                "  - https://gitlab.example.com/group/subgroup/project"
            )

    elif project_path:
        # Validate project path format
        path = project_path.strip().strip("/")

        if "/" not in path:
            raise ProjectResolutionError(
                f"Invalid project path format: '{project_path}'\n\n"
                "Project path must contain at least namespace/project.\n\n"
                "SOLUTION:\n"
                "Examples of valid project paths:\n"
                "  - mycompany/my-project\n"
                "  - group/subgroup/project-name\n"
                "  - username/personal-project"
            )

        # Validate path components
        path_parts = path.split("/")
        if len(path_parts) < 2 or not all(path_parts[:2]):
            raise ProjectResolutionError(
                f"Invalid project path: '{project_path}'\n\n"
                "Path must contain at least namespace and project name.\n\n"
                "SOLUTION:\n"
                "Examples of valid project paths:\n"
                "  - mycompany/my-project\n"
                "  - group/subgroup/project-name"
            )

        logger.info(f"Using project path: {path} at {gitlab_url}")
        return gitlab_url, path

    else:
        raise ProjectResolutionError(
            "No project specification provided.\n\n"
            "SOLUTION:\n"
            "Use one of the following:\n"
            "  --project-url https://gitlab.com/namespace/project\n"
            "  --project-path namespace/project --gitlab-url https://gitlab.com"
        )


def validate_upload_flags(args: argparse.Namespace) -> None:
    """Validate upload-specific flag combinations and detect conflicts.

    Checks for:
    - Required arguments (--package-name and --package-version)
    - Conflicting file input (--files and --directory)
    - Conflicting project specification (--project-url with --project-path)
    - File input requirement (--files or --directory must be provided)
    - File mapping constraint (--file-mapping only valid with --files)

    Args:
        args: Parsed argument namespace from argparse.

    Raises:
        SystemExit: With exit code 3 (ConfigurationError) if conflicts are detected.
    """
    errors: list[str] = []

    # Check required arguments for upload runs
    if not args.package_name:
        errors.append(
            "--package-name is required. "
            "Specify the package name in the GitLab registry."
        )
    if not args.package_version:
        errors.append(
            "--package-version is required. "
            "Specify the package version."
        )

    # Check for conflicting file input flags
    if args.files and args.directory:
        errors.append(
            "Cannot specify both --files and --directory. "
            "Use --files for explicit file list or --directory to upload all files from a directory."
        )

    # Check for conflicting project specification
    if args.project_url and args.project_path:
        errors.append(
            "Cannot specify both --project-url and --project-path. "
            "Use --project-url for full URLs or --project-path with --gitlab-url."
        )

    # Check that file input is provided
    if not args.files and not args.directory:
        errors.append(
            "Either --files or --directory must be provided. "
            "Use --files for explicit file list or --directory to upload all files from a directory."
        )

    # Check that file-mapping is only used with --files
    if args.file_mapping and args.directory:
        errors.append(
            "--file-mapping can only be used with --files, not with --directory. "
            "File mappings require explicit file specification."
        )

    # Check retry value is non-negative
    if args.retry < 0:
        errors.append(
            f"--retry must be a non-negative integer, got {args.retry}."
        )

    # Report all errors
    if errors:
        for error in errors:
            print(f"Error: {error}", file=sys.stderr)
        print(
            "\nUse 'glpkg upload --help' for usage information.",
            file=sys.stderr,
        )
        sys.exit(3)  # ConfigurationError exit code


def register_upload_command(subparsers: argparse._SubParsersAction) -> None:
    """Register the upload subcommand with the main argument parser.

    Args:
        subparsers: Subparsers action from the main argument parser.
    """
    upload_parser = subparsers.add_parser(
        "upload",
        help="Upload files to GitLab's Generic Package Registry",
        description=(
            "Upload one or more files to a GitLab project's package registry.\n\n"
            "Supports automatic project detection from Git remotes, duplicate handling,\n"
            "file renaming, and retry logic for reliability."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Upload a single file
  glpkg upload --package-name myapp --package-version 1.0.0 --files dist/app.tar.gz

  # Upload multiple files
  glpkg upload --package-name myapp --package-version 1.0.0 --files file1.bin file2.bin

  # Upload all files from a directory
  glpkg upload --package-name myapp --package-version 1.0.0 --directory dist/

  # With file renaming (source:target format)
  glpkg upload --package-name myapp --package-version 1.0.0 \\
      --files local.tar.gz --file-mapping local.tar.gz:app-1.0.0.tar.gz

  # Skip duplicates (default behavior)
  glpkg upload --package-name myapp --package-version 1.0.0 --files dist/*.tar.gz \\
      --duplicate-policy skip

  # Replace existing files
  glpkg upload --package-name myapp --package-version 1.0.0 --files dist/*.tar.gz \\
      --duplicate-policy replace

  # Dry run with verbose output
  glpkg --verbose upload --package-name myapp --package-version 1.0.0 --files dist/*.tar.gz \\
      --dry-run

  # Specify project explicitly
  glpkg upload --package-name myapp --package-version 1.0.0 --files dist/*.tar.gz \\
      --project-url https://gitlab.com/mygroup/myproject

  # Use custom GitLab instance
  glpkg upload --package-name myapp --package-version 1.0.0 --files dist/*.tar.gz \\
      --project-path mygroup/myproject

Environment variables:
  GITLAB_TOKEN    GitLab API token (alternative to --token)
""",
    )

    # Required arguments
    required_group = upload_parser.add_argument_group("required arguments")
    required_group.add_argument(
        "--package-name",
        type=str,
        metavar="NAME",
        help="Package name in the GitLab registry (e.g., 'myapp', 'my-library')",
    )
    required_group.add_argument(
        "--package-version",
        type=str,
        metavar="VERSION",
        help="Package version (e.g., '1.0.0', '2.3.1-beta')",
    )

    # File input arguments
    file_input_group = upload_parser.add_argument_group(
        "file input (one required)",
        "Specify files to upload using either --files or --directory",
    )
    file_input_group.add_argument(
        "--files",
        nargs="+",
        type=str,
        metavar="FILE",
        help="List of files to upload (e.g., --files file1.tar.gz file2.tar.gz)",
    )
    file_input_group.add_argument(
        "--directory",
        type=str,
        metavar="DIR",
        help="Directory containing files to upload (uploads all top-level files)",
    )

    # Project specification arguments
    project_group = upload_parser.add_argument_group(
        "project specification",
        "Specify the target GitLab project (auto-detected from Git remote if not provided)",
    )
    project_group.add_argument(
        "--project-url",
        type=str,
        metavar="URL",
        help="Full GitLab project URL (e.g., 'https://gitlab.com/namespace/project')",
    )
    project_group.add_argument(
        "--project-path",
        type=str,
        metavar="PATH",
        help="Project path in namespace/project format (e.g., 'mygroup/myproject')",
    )

    # Duplicate handling
    upload_parser.add_argument(
        "--duplicate-policy",
        type=str,
        choices=["skip", "replace", "error"],
        default="skip",
        metavar="POLICY",
        help=(
            "How to handle duplicate files: "
            "'skip' (default) - skip uploading, "
            "'replace' - delete existing and upload new, "
            "'error' - fail with error"
        ),
    )

    # File mapping
    upload_parser.add_argument(
        "--file-mapping",
        action="append",
        type=str,
        metavar="SOURCE:TARGET",
        help=(
            "Rename files during upload using source:target format. "
            "Can be specified multiple times (e.g., --file-mapping local.bin:remote.bin). "
            "Only valid with --files, not --directory."
        ),
    )

    # Operational flags
    operational_group = upload_parser.add_argument_group("operational options")
    operational_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without executing uploads (shows what would be done)",
    )
    operational_group.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop immediately on first upload failure (default: continue with remaining files)",
    )
    operational_group.add_argument(
        "--retry",
        type=int,
        default=0,
        metavar="N",
        help="Number of retry attempts for failed uploads (default: 0)",
    )

    # Set the handler function
    upload_parser.set_defaults(func=execute_upload)


def execute_upload(args: argparse.Namespace) -> None:
    """Execute the upload subcommand.

    This is the main handler for the upload subcommand, orchestrating:
    1. Flag validation
    2. Project resolution (auto-detect or manual)
    3. GitLab authentication
    4. Context building
    5. File collection
    6. Upload execution
    7. Result formatting

    Args:
        args: Parsed argument namespace from argparse.
    """
    # Validate upload-specific flags
    validate_upload_flags(args)

    # Convert duplicate_policy string to enum
    args.duplicate_policy = DuplicatePolicy(args.duplicate_policy)

    # Project resolution
    try:
        if args.project_url or args.project_path:
            # Manual specification
            gitlab_url, project_path = resolve_project_manually(
                project_url=args.project_url,
                project_path=args.project_path,
                gitlab_url=args.gitlab_url,
            )
        else:
            # Auto-detection
            gitlab_url, project_path = auto_detect_project()

        # Authenticate with GitLab
        token = get_gitlab_token(args.token)
        gl = Gitlab(gitlab_url, private_token=token)
        gl.auth()

        # Resolve project ID
        resolver = ProjectResolver(gl)
        project_id = resolver.resolve_project_id(gitlab_url, project_path)

        # Validate access
        if not resolver.validate_project_access(project_id):
            raise ProjectResolutionError(
                f"Cannot access project {project_path}. "
                f"Verify you have appropriate permissions."
            )

        # Log success
        logger.info(f"Successfully resolved project: {project_path} (ID: {project_id})")

        # Context building
        builder = UploadContextBuilder()
        context = builder.build(
            args=args,
            gl=gl,
            project_id=project_id,
            project_path=project_path,
            gitlab_url=gitlab_url,
            token=token,
        )
        logger.debug(f"Upload context built successfully for {project_path}")

    except AuthenticationError as e:
        logger.error(f"Authentication failed: {e}")
        sys.exit(e.exit_code)
    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(e.exit_code)
    except ProjectResolutionError as e:
        logger.error(f"Project resolution failed: {e}")
        sys.exit(e.exit_code)
    except GitLabUploadError as e:
        logger.error(f"GitLab error: {e}")
        sys.exit(e.exit_code)
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        sys.exit(EXCEPTION_EXIT_CODE_MAP.get(FileNotFoundError, 1))
    except PermissionError as e:
        logger.error(f"Permission denied: {e}")
        sys.exit(EXCEPTION_EXIT_CODE_MAP.get(PermissionError, 1))
    except ValueError as e:
        logger.error(f"Value error: {e}")
        sys.exit(EXCEPTION_EXIT_CODE_MAP.get(ValueError, 1))
    except ConnectionError as e:
        logger.error(f"Connection error: {e}")
        sys.exit(EXCEPTION_EXIT_CODE_MAP.get(ConnectionError, 1))
    except TimeoutError as e:
        logger.error(f"Timeout error: {e}")
        sys.exit(EXCEPTION_EXIT_CODE_MAP.get(TimeoutError, 1))
    except Exception as e:
        logger.error(f"Unexpected error during project resolution: {e}")
        sys.exit(1)

    # Upload orchestration
    try:
        # Step 1: Collect files to upload
        files_to_upload, file_errors = collect_files(
            files=args.files,
            directory=args.directory,
            file_mappings=args.file_mapping,
        )

        # Handle file collection errors
        if file_errors:
            for error in file_errors:
                logger.error(
                    f"File validation error for {error['source_path']}: {error['error_message']}"
                )
            if args.fail_fast:
                logger.error("Fail-fast enabled, stopping due to file validation errors")
                sys.exit(5)

        # Check if we have any valid files to upload
        if not files_to_upload:
            logger.error("No valid files to upload")
            sys.exit(5)

        logger.info(f"Collected {len(files_to_upload)} files to upload")

        # Step 2: Execute uploads
        results = upload_files(context, files_to_upload)

        # Step 3: Format and display results
        formatter = OutputFormatter(context.config)
        formatter.format_output(
            results,
            context.config.package_name,
            context.config.version,
        )

        # Step 4: Determine exit code based on results
        failed_count = sum(1 for r in results if not r.success)
        if failed_count > 0:
            sys.exit(1)
        else:
            sys.exit(0)

    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        sys.exit(EXCEPTION_EXIT_CODE_MAP.get(FileNotFoundError, 1))
    except PermissionError as e:
        logger.error(f"Permission denied: {e}")
        sys.exit(EXCEPTION_EXIT_CODE_MAP.get(PermissionError, 1))
    except ValueError as e:
        logger.error(f"Value error: {e}")
        sys.exit(EXCEPTION_EXIT_CODE_MAP.get(ValueError, 1))
    except ConnectionError as e:
        logger.error(f"Connection error: {e}")
        sys.exit(EXCEPTION_EXIT_CODE_MAP.get(ConnectionError, 1))
    except TimeoutError as e:
        logger.error(f"Timeout error: {e}")
        sys.exit(EXCEPTION_EXIT_CODE_MAP.get(TimeoutError, 1))
    except GitLabUploadError as e:
        logger.error(f"Upload error: {e}")
        sys.exit(e.exit_code)
    except Exception as e:
        logger.error(f"Unexpected error during upload: {e}")
        sys.exit(1)
