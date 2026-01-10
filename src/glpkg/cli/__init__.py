"""CLI package for glpkg.

This package provides the command-line interface for glpkg, organized into:
- main: Global argument parsing, logging setup, and subcommand routing
- upload: Upload subcommand implementation
- completion: Shell completion installation for bash and zsh
"""

from glpkg.cli.main import main

__all__ = ["main"]
