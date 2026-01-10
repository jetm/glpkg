"""Shell completion installation for glpkg.

This module provides functionality to generate and install shell completion
scripts for bash and zsh using argcomplete.
"""

from __future__ import annotations

import logging
from pathlib import Path

import argcomplete

logger = logging.getLogger(__name__)

SUPPORTED_SHELLS = ["bash", "zsh"]

COMPLETION_PATHS = {
    "bash": "~/.bash_completion.d/",
    "zsh": "~/.zsh/completion/",
}

COMPLETION_FILENAMES = {
    "bash": "glpkg",
    "zsh": "_glpkg",
}


def generate_completion_script(shell: str) -> str:
    """Generate shell completion script for the specified shell.

    Args:
        shell: The shell to generate completion for ('bash' or 'zsh').

    Returns:
        The generated completion script as a string.

    Raises:
        ValueError: If the shell is not supported.
    """
    if shell not in SUPPORTED_SHELLS:
        raise ValueError(
            f"Unsupported shell: {shell}. Supported shells: {', '.join(SUPPORTED_SHELLS)}"
        )

    # argcomplete.shellcode is not typed properly
    result: str = argcomplete.shellcode(  # type: ignore[attr-defined,no-untyped-call]
        ["glpkg"], shell=shell
    )
    return result


def get_completion_path(shell: str) -> Path:
    """Get the completion directory path for the specified shell.

    Args:
        shell: The shell to get the completion path for ('bash' or 'zsh').

    Returns:
        The expanded absolute path to the completion directory.

    Raises:
        ValueError: If the shell is not supported.
    """
    if shell not in SUPPORTED_SHELLS:
        raise ValueError(
            f"Unsupported shell: {shell}. Supported shells: {', '.join(SUPPORTED_SHELLS)}"
        )

    return Path(COMPLETION_PATHS[shell]).expanduser()


def install_completion(shell: str) -> None:
    """Install shell completion for the specified shell.

    Generates the completion script and writes it to the appropriate
    completion directory. Creates the directory if it doesn't exist.

    Args:
        shell: The shell to install completion for ('bash' or 'zsh').

    Raises:
        ValueError: If the shell is not supported.
        PermissionError: If there are insufficient permissions to write the file.
        OSError: If there are other file system errors.
    """
    if shell not in SUPPORTED_SHELLS:
        raise ValueError(
            f"Unsupported shell: {shell}. Supported shells: {', '.join(SUPPORTED_SHELLS)}"
        )

    script = generate_completion_script(shell)
    completion_dir = get_completion_path(shell)
    filename = COMPLETION_FILENAMES[shell]
    completion_file = completion_dir / filename

    try:
        completion_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError as e:
        raise PermissionError(
            f"Cannot create directory {completion_dir}: Permission denied. "
            f"Try running with appropriate permissions or create the directory manually."
        ) from e
    except OSError as e:
        raise OSError(
            f"Cannot create directory {completion_dir}: {e}. Please check the path and try again."
        ) from e

    try:
        completion_file.write_text(script)
        completion_file.chmod(0o644)
    except PermissionError as e:
        raise PermissionError(
            f"Cannot write to {completion_file}: Permission denied. "
            f"Try running with appropriate permissions."
        ) from e
    except OSError as e:
        raise OSError(
            f"Cannot write to {completion_file}: {e}. Please check the path and try again."
        ) from e

    logger.info(f"Installed {shell} completion to {completion_file}")

    # Print activation instructions
    print(f"Shell completion for {shell} installed to: {completion_file}")
    print()
    if shell == "bash":
        print("To activate completion, add the following to your ~/.bashrc:")
        print(f"  source {completion_file}")
        print()
        print("Then restart your shell or run:")
        print("  source ~/.bashrc")
    elif shell == "zsh":
        print("To activate completion, ensure ~/.zsh/completion is in your fpath.")
        print("Add the following to your ~/.zshrc (before compinit):")
        print("  fpath=(~/.zsh/completion $fpath)")
        print()
        print("Then run:")
        print("  autoload -Uz compinit && compinit")
        print()
        print("Or restart your shell.")
