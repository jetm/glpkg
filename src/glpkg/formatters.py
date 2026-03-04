"""Output formatting module for gitlab-pkg-upload.

Provides terminal capability detection and multiple output formats
(rich console, JSON, plain text) for upload results and error messages.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from glpkg.cli.list_cmd import PackageListResult, PackageVersionSummary

from rich.console import Console
from rich.status import Status

from .models import GitLabUploadError, UploadConfig, UploadResult, enhance_error_message

# Terminal Detection Functions


def detect_tty() -> bool:
    """Detect if stdout is connected to a TTY terminal.

    Returns:
        True if stdout is connected to a TTY terminal, False otherwise.

    Examples:
        >>> detect_tty()  # In a terminal
        True
        >>> detect_tty()  # When piped to a file
        False
    """
    try:
        if sys.stdout is None:
            return False
        if not hasattr(sys.stdout, "isatty"):
            return False
        return sys.stdout.isatty()
    except Exception:
        return False


def detect_color_support() -> bool:
    """Detect if terminal supports color output based on environment variables and platform.

    Checks environment variables in order of precedence:
    - NO_COLOR: if set (any value), returns False
    - FORCE_COLOR: if set (any value), returns True
    - COLORTERM: if set, returns True
    - TERM: if contains "color" or equals "xterm-256color", returns True

    On Windows, also checks for ANSICON and WT_SESSION environment variables.

    Returns:
        True if terminal supports color output, False otherwise.

    Examples:
        >>> os.environ['FORCE_COLOR'] = '1'
        >>> detect_color_support()
        True
        >>> os.environ['NO_COLOR'] = '1'
        >>> detect_color_support()
        False
    """
    if not detect_tty():
        return False

    # NO_COLOR takes highest precedence
    if os.environ.get("NO_COLOR") is not None:
        return False

    # FORCE_COLOR overrides other checks
    if os.environ.get("FORCE_COLOR") is not None:
        return True

    # COLORTERM indicates color support
    if os.environ.get("COLORTERM"):
        return True

    # Check TERM variable
    term = os.environ.get("TERM", "")
    if "color" in term.lower() or term == "xterm-256color":
        return True

    # Windows-specific checks
    if sys.platform == "win32":
        # Windows Terminal
        if os.environ.get("WT_SESSION"):
            return True
        # ANSICON
        if os.environ.get("ANSICON"):
            return True
        # ConEmu
        if os.environ.get("ConEmuANSI") == "ON":
            return True

    return False


def detect_unicode_support() -> bool:
    """Detect if terminal supports Unicode characters.

    Checks:
    - stdout encoding contains "utf" (case-insensitive)
    - LANG or LC_ALL environment variables for UTF-8 indicators
    - On Windows, checks if console encoding is UTF-8

    Returns:
        True if terminal supports Unicode, False otherwise.

    Examples:
        >>> detect_unicode_support()  # In a UTF-8 terminal
        True
        >>> detect_unicode_support()  # In an ASCII-only terminal
        False
    """
    if not detect_tty():
        return False

    # Check stdout encoding
    try:
        encoding = getattr(sys.stdout, "encoding", None)
        if encoding and "utf" in encoding.lower():
            return True
    except Exception:
        pass

    # Check locale environment variables
    lang = os.environ.get("LANG", "") or os.environ.get("LC_ALL", "")
    if "utf" in lang.lower() or "UTF" in lang:
        return True

    return False


# OutputFormatter Class


class OutputFormatter:
    """Formats and outputs upload results based on configuration.

    Encapsulates formatting logic with methods for different output modes,
    respecting the --plain flag override and terminal capabilities.

    Attributes:
        config: Upload configuration with output preferences.
        is_tty: Whether stdout is connected to a TTY.
        supports_color: Whether terminal supports color output.
        supports_unicode: Whether terminal supports Unicode characters.
        console: Rich Console instance for formatted output.
    """

    _logger = logging.getLogger(__name__)

    def __init__(self, config: UploadConfig) -> None:
        """Initialize OutputFormatter with configuration.

        Args:
            config: Upload configuration containing output preferences
                (json_output, plain_output flags).

        Examples:
            >>> config = UploadConfig(plain_output=True, ...)
            >>> formatter = OutputFormatter(config)
            >>> formatter.is_tty
            False
        """
        self.config = config

        # Determine terminal capabilities
        if config.plain_output:
            # Plain output mode forces all capabilities to False
            self.is_tty = False
            self.supports_color = False
            self.supports_unicode = False
        else:
            self.is_tty = detect_tty()
            self.supports_color = detect_color_support()
            self.supports_unicode = detect_unicode_support()

        # Initialize Rich Console with appropriate settings
        self.console = Console(
            force_terminal=self.is_tty and not config.plain_output,
            no_color=not self.supports_color or config.plain_output,
            legacy_windows=False,
        )

    def format_output(self, results: List[UploadResult], package_name: str, version: str) -> None:
        """Format and output upload results based on configuration.

        Determines the appropriate output format based on config.json_output
        and config.plain_output flags, then delegates to the appropriate
        formatting method.

        Args:
            results: List of upload results to format.
            package_name: Name of the package being uploaded.
            version: Version of the package.

        Examples:
            >>> formatter.format_output(results, "my-package", "1.0.0")
        """
        if self.config.json_output:
            self._format_json_output(results, package_name, version)
        elif self.config.plain_output or not self.is_tty:
            self._format_plain_output(results, package_name, version)
        else:
            self._format_rich_output(results, package_name, version)

    def _format_rich_output(
        self, results: List[UploadResult], package_name: str, version: str
    ) -> None:
        """Format output using rich console with colors and formatting.

        Args:
            results: List of upload results to format.
            package_name: Name of the package being uploaded.
            version: Version of the package.
        """
        # Categorize results into three lists
        successful_uploads: List[UploadResult] = []
        skipped_duplicates: List[UploadResult] = []
        failed_uploads: List[UploadResult] = []

        for result in results:
            if result.success and result.duplicate_action != "skipped":
                successful_uploads.append(result)
            elif result.success and result.duplicate_action == "skipped":
                skipped_duplicates.append(result)
            else:
                failed_uploads.append(result)

        # Display Upload Summary Header
        self.console.print("\n[bold]Upload Summary[/bold]\n")

        # Display Successful Uploads Section
        if successful_uploads:
            self.console.print("[bold green]✓ Successful Uploads[/bold green]\n")
            for result in successful_uploads:
                self.console.print(f"[cyan]Source File:[/cyan] {result.source_path}")
                self.console.print(f"[cyan]Target Filename:[/cyan] {result.target_filename}")
                self.console.print(f"[cyan]Download URL:[/cyan] [blue]{result.result}[/blue]")
                if result.was_duplicate and result.duplicate_action == "replaced":
                    self.console.print(
                        "[cyan]Action:[/cyan] [yellow]Replaced existing duplicate[/yellow]"
                    )
                    if result.existing_url is not None:
                        self.console.print(
                            f"[cyan]Previous URL:[/cyan] [dim]{result.existing_url}[/dim]"
                        )
                self.console.print()

        # Display Skipped Duplicates Section
        if skipped_duplicates:
            self.console.print("[bold yellow]⚠ Skipped Duplicates[/bold yellow]\n")
            for result in skipped_duplicates:
                self.console.print(f"[cyan]Source File:[/cyan] {result.source_path}")
                self.console.print(f"[cyan]Target Filename:[/cyan] {result.target_filename}")
                existing_url = result.existing_url or result.result
                self.console.print(f"[cyan]Existing URL:[/cyan] [blue]{existing_url}[/blue]")
                self.console.print(f"[cyan]Reason:[/cyan] {result.result}")
                self.console.print()

        # Display Failed Uploads Section
        if failed_uploads:
            self.console.print("[bold red]✗ Failed Uploads[/bold red]\n")
            for result in failed_uploads:
                self.console.print(f"[cyan]Source File:[/cyan] {result.source_path}")
                self.console.print(f"[cyan]Target Filename:[/cyan] {result.target_filename}")
                self.console.print(f"[cyan]Error:[/cyan] [red]{result.result}[/red]")
                if result.was_duplicate:
                    self.console.print(f"[cyan]Duplicate Action:[/cyan] {result.duplicate_action}")
                    if result.existing_url is not None:
                        self.console.print(
                            f"[cyan]Existing URL:[/cyan] [blue]{result.existing_url}[/blue]"
                        )
                self.console.print()

        # Calculate and Display Statistics
        total_processed = len(successful_uploads) + len(skipped_duplicates) + len(failed_uploads)
        replaced_count = sum(
            1 for r in successful_uploads if r.was_duplicate and r.duplicate_action == "replaced"
        )
        new_uploads_count = len(successful_uploads) - replaced_count

        self.console.print("\n[bold]Duplicate Detection Statistics:[/bold]")
        self.console.print(f"• New uploads: {new_uploads_count}")
        self.console.print(f"• Replaced duplicates: {replaced_count}")
        self.console.print(f"• Skipped duplicates: {len(skipped_duplicates)}")
        self.console.print(f"• Failed uploads: {len(failed_uploads)}")
        self.console.print(f"• Total processed: {total_processed}")

        # Display Final Results Summary
        self.console.print(
            f"\n[bold]Final Results:[/bold] {len(successful_uploads)} uploaded "
            f"({new_uploads_count} new, {replaced_count} replaced), "
            f"{len(skipped_duplicates)} skipped duplicates, "
            f"{len(failed_uploads)} failed out of {total_processed} total"
        )

        if not failed_uploads:
            self.console.print(
                f"\n[bold green]✓[/bold green] All files processed successfully "
                f"for {package_name} v{version}: {new_uploads_count} new uploads, "
                f"{replaced_count} replaced duplicates, "
                f"{len(skipped_duplicates)} skipped duplicates"
            )

    def _format_json_output(
        self, results: List[UploadResult], package_name: str, version: str
    ) -> None:
        """Format output as JSON structure.

        JSON output is printed to stdout for machine parsing.
        Any logging goes to stderr via self._logger to maintain separation.

        Args:
            results: List of upload results to format.
            package_name: Name of the package being uploaded.
            version: Version of the package.
        """
        # Categorize results into three lists
        successful_uploads: List[UploadResult] = []
        skipped_duplicates: List[UploadResult] = []
        failed_uploads: List[UploadResult] = []

        for result in results:
            if result.success and result.duplicate_action != "skipped":
                successful_uploads.append(result)
            elif result.success and result.duplicate_action == "skipped":
                skipped_duplicates.append(result)
            else:
                failed_uploads.append(result)

        # Build upload result objects for each category
        successful_uploads_data = []
        for result in successful_uploads:
            successful_uploads_data.append(
                {
                    "source_path": result.source_path,
                    "target_filename": result.target_filename,
                    "download_url": result.result,
                    "checksum": None,  # Reserved for future use
                    "was_duplicate": result.was_duplicate,
                    "duplicate_action": result.duplicate_action,
                    "existing_url": result.existing_url,
                    "error_message": None,
                }
            )

        skipped_duplicates_data = []
        for result in skipped_duplicates:
            skipped_duplicates_data.append(
                {
                    "source_path": result.source_path,
                    "target_filename": result.target_filename,
                    "download_url": result.existing_url or result.result,
                    "checksum": None,
                    "was_duplicate": result.was_duplicate,
                    "duplicate_action": result.duplicate_action,
                    "existing_url": result.existing_url,
                    "error_message": None,
                }
            )

        failed_uploads_data = []
        for result in failed_uploads:
            failed_uploads_data.append(
                {
                    "source_path": result.source_path,
                    "target_filename": result.target_filename,
                    "download_url": None,
                    "checksum": None,
                    "was_duplicate": result.was_duplicate,
                    "duplicate_action": result.duplicate_action,
                    "existing_url": result.existing_url,
                    "error_message": result.result,
                }
            )

        # Calculate statistics
        total_processed = len(successful_uploads) + len(skipped_duplicates) + len(failed_uploads)
        replaced_count = sum(
            1 for r in successful_uploads if r.was_duplicate and r.duplicate_action == "replaced"
        )
        new_uploads_count = len(successful_uploads) - replaced_count

        statistics = {
            "total_processed": total_processed,
            "new_uploads": new_uploads_count,
            "replaced_duplicates": replaced_count,
            "skipped_duplicates": len(skipped_duplicates),
            "failed_uploads": len(failed_uploads),
        }

        # Build JSON structure
        output_data: Dict[str, Any] = {
            "success": len(failed_uploads) == 0,
            "exit_code": 0 if len(failed_uploads) == 0 else 1,
            "package_name": package_name,
            "version": version,
            "successful_uploads": successful_uploads_data,
            "skipped_duplicates": skipped_duplicates_data,
            "failed_uploads": failed_uploads_data,
            "statistics": statistics,
        }

        # Add top-level error fields when failures occur
        if failed_uploads:
            failed_count = len(failed_uploads)
            if failed_count == 1:
                output_data["error"] = failed_uploads[0].result
            else:
                output_data["error"] = f"{failed_count} file(s) failed to upload"
            output_data["error_type"] = "UploadError"

        # Output JSON to stdout (not self.console.print to avoid rich formatting)
        print(json.dumps(output_data, indent=2))

    def _format_plain_output(
        self, results: List[UploadResult], package_name: str, version: str
    ) -> None:
        """Format output as plain text without colors or special characters.

        Plain text output is printed to stdout using ASCII-only characters.
        No color codes or ANSI escape sequences are used.

        Args:
            results: List of upload results to format.
            package_name: Name of the package being uploaded.
            version: Version of the package.
        """
        # Categorize results into three lists
        successful_uploads: List[UploadResult] = []
        skipped_duplicates: List[UploadResult] = []
        failed_uploads: List[UploadResult] = []

        for result in results:
            if result.success and result.duplicate_action != "skipped":
                successful_uploads.append(result)
            elif result.success and result.duplicate_action == "skipped":
                skipped_duplicates.append(result)
            else:
                failed_uploads.append(result)

        # Display Upload Summary Header
        print("\nUpload Summary\n")

        # Display Successful Uploads Section
        if successful_uploads:
            print("[OK] Successful Uploads\n")
            for result in successful_uploads:
                print(f"Source File: {result.source_path}")
                print(f"Target Filename: {result.target_filename}")
                print(f"Download URL: {result.result}")
                if result.was_duplicate and result.duplicate_action == "replaced":
                    print("Action: Replaced existing duplicate")
                    if result.existing_url is not None:
                        print(f"Previous URL: {result.existing_url}")
                print()

        # Display Skipped Duplicates Section
        if skipped_duplicates:
            print("[SKIP] Skipped Duplicates\n")
            for result in skipped_duplicates:
                print(f"Source File: {result.source_path}")
                print(f"Target Filename: {result.target_filename}")
                print(f"Existing URL: {result.existing_url or result.result}")
                print(f"Reason: {result.result}")
                print()

        # Display Failed Uploads Section
        if failed_uploads:
            print("[FAIL] Failed Uploads\n")
            for result in failed_uploads:
                print(f"Source File: {result.source_path}")
                print(f"Target Filename: {result.target_filename}")
                print(f"Error: {result.result}")
                if result.was_duplicate:
                    print(f"Duplicate Action: {result.duplicate_action}")
                    if result.existing_url is not None:
                        print(f"Existing URL: {result.existing_url}")
                print()

        # Calculate statistics
        total_processed = len(successful_uploads) + len(skipped_duplicates) + len(failed_uploads)
        replaced_count = sum(
            1 for r in successful_uploads if r.was_duplicate and r.duplicate_action == "replaced"
        )
        new_uploads_count = len(successful_uploads) - replaced_count

        # Display Statistics
        print("Duplicate Detection Statistics:")
        print(f"* New uploads: {new_uploads_count}")
        print(f"* Replaced duplicates: {replaced_count}")
        print(f"* Skipped duplicates: {len(skipped_duplicates)}")
        print(f"* Failed uploads: {len(failed_uploads)}")
        print(f"* Total processed: {total_processed}")

        # Display Final Results
        print(
            f"\nFinal Results: {len(successful_uploads)} uploaded "
            f"({new_uploads_count} new, {replaced_count} replaced), "
            f"{len(skipped_duplicates)} skipped duplicates, "
            f"{len(failed_uploads)} failed out of {total_processed} total"
        )

        if not failed_uploads:
            print(
                f"\n[OK] All files processed successfully "
                f"for {package_name} v{version}: {new_uploads_count} new uploads, "
                f"{replaced_count} replaced duplicates, "
                f"{len(skipped_duplicates)} skipped duplicates"
            )

    def format_list_output(self, result: PackageListResult | list[PackageVersionSummary]) -> None:
        """Format and output package list results.

        Args:
            result: Either a PackageListResult (files in a specific version)
                or a list of PackageVersionSummary (version overview).
        """
        if self.config.json_output:
            self._format_list_json(result)
        elif self.config.plain_output or not self.is_tty:
            self._format_list_plain(result)
        else:
            self._format_list_rich(result)

    def _format_human_size(self, size: int) -> str:
        """Format byte size as human-readable string."""
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                if unit == "B":
                    return f"{size} {unit}"
                return f"{size:.1f} {unit}"
            size /= 1024  # type: ignore[assignment]
        return f"{size:.1f} TB"

    def _format_list_rich(self, result: PackageListResult | list[PackageVersionSummary]) -> None:
        """Format list output with rich console colors."""
        if isinstance(result, list):
            # Version summaries
            self.console.print("\n[bold]Package versions[/bold]\n")
            for vs in result:
                self.console.print(
                    f"  [cyan]{vs.version}[/cyan]  "
                    f"{vs.file_count} file(s)  "
                    f"[dim]{vs.created_at}[/dim]"
                )
            self.console.print(f"\n{len(result)} version(s) found")
            return

        file_count = len(result.files)
        self.console.print(
            f"\n[bold]Package:[/bold] {result.package_name} "
            f"v{result.version} ({file_count} file(s))\n"
        )
        for f in result.files:
            sha_short = f.sha256[:12] + "..." if f.sha256 else "n/a"
            self.console.print(
                f"  [cyan]{f.file_name}[/cyan]  "
                f"{self._format_human_size(f.size)}  "
                f"[dim]{f.created_at}[/dim]  "
                f"sha256:{sha_short}"
            )
            self.console.print(f"    [blue]{f.download_url}[/blue]")

    def _format_list_plain(self, result: PackageListResult | list[PackageVersionSummary]) -> None:
        """Format list output as plain ASCII text."""
        if isinstance(result, list):
            print("\nPackage versions\n")
            for vs in result:
                print(f"  {vs.version}  {vs.file_count} file(s)  {vs.created_at}")
            print(f"\n{len(result)} version(s) found")
            return

        file_count = len(result.files)
        print(f"\nPackage: {result.package_name} v{result.version} ({file_count} file(s))\n")
        for f in result.files:
            sha_short = f.sha256[:12] + "..." if f.sha256 else "n/a"
            print(
                f"  {f.file_name}  {self._format_human_size(f.size)}  "
                f"{f.created_at}  sha256:{sha_short}"
            )
            print(f"    {f.download_url}")

    def _format_list_json(self, result: PackageListResult | list[PackageVersionSummary]) -> None:
        """Format list output as JSON."""
        if isinstance(result, list):
            data = {
                "versions": [
                    {
                        "version": vs.version,
                        "package_id": vs.package_id,
                        "file_count": vs.file_count,
                        "created_at": vs.created_at,
                    }
                    for vs in result
                ]
            }
        else:
            data = {
                "package_name": result.package_name,
                "version": result.version,
                "package_id": result.package_id,
                "files": [
                    {
                        "file_name": f.file_name,
                        "size": f.size,
                        "sha256": f.sha256,
                        "download_url": f.download_url,
                        "created_at": f.created_at,
                    }
                    for f in result.files
                ],
            }
        print(json.dumps(data, indent=2))

    def create_progress_spinner(self, message: str) -> Status:
        """Create a progress spinner for long-running operations.

        Args:
            message: Message to display alongside the spinner.

        Returns:
            A Rich Status object that can be used as a context manager.

        Examples:
            >>> with formatter.create_progress_spinner("Uploading...") as status:
            ...     upload_file()
        """
        if self.config.plain_output or not self.is_tty:
            # Return a Status that does nothing for plain output
            return Status(message, console=self.console, spinner="dots")
        return Status(message, console=self.console, spinner="dots")


# Error Formatting Function


def format_error(error: Exception, context: Optional[Dict[str, Any]] = None) -> str:
    """Format error messages with context for better debugging.

    Uses enhanced error messages from models.py when context is available.

    Args:
        error: The exception to format.
        context: Optional context dictionary with keys like:
            - 'operation': Operation that failed
            - 'project_path': Project path being accessed
            - 'gitlab_url': GitLab instance URL

    Returns:
        Formatted error string with error type, message, and context.

    Raises:
        None - this function handles all errors gracefully.

    Examples:
        >>> error = ValueError("Invalid input")
        >>> format_error(error)
        'ERROR: ValueError\\nInvalid input'

        >>> context = {'operation': 'upload', 'project_path': 'group/project'}
        >>> format_error(error, context)
        'ERROR: ValueError\\nInvalid input\\nOperation: upload\\nProject: group/project'
    """
    error_type = type(error).__name__

    # Build error message header
    lines = [f"ERROR: {error_type}"]

    # Get exit code if it's a GitLabUploadError
    if isinstance(error, GitLabUploadError):
        lines.append(f"Exit code: {error.exit_code}")

    # Use enhanced error message if context is provided
    if context:
        enhanced_message = enhance_error_message(error, context)
        lines.append(enhanced_message)
    else:
        lines.append(str(error))

    return "\n".join(lines)


# Helper Functions


def get_formatter(config: UploadConfig) -> OutputFormatter:
    """Factory function to create an OutputFormatter instance.

    Args:
        config: Upload configuration containing output preferences.

    Returns:
        Configured OutputFormatter instance.

    Examples:
        >>> config = UploadConfig(...)
        >>> formatter = get_formatter(config)
        >>> formatter.format_output(results, "pkg", "1.0.0")
    """
    return OutputFormatter(config)


def display_progress(formatter: OutputFormatter, message: str) -> Status:
    """Convenience function that wraps formatter.create_progress_spinner().

    Provides a standalone function interface for progress display,
    maintaining backward compatibility if other modules expect a function
    rather than a method.

    Args:
        formatter: OutputFormatter instance to use for progress display.
        message: Message to display alongside the spinner.

    Returns:
        A Rich Status object that can be used as a context manager.

    Examples:
        >>> formatter = get_formatter(config)
        >>> with display_progress(formatter, "Uploading...") as status:
        ...     upload_file()
        ...     status.update("Processing...")
    """
    return formatter.create_progress_spinner(message)
