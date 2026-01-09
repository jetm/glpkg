"""CLI entry point for gitlab-pkg-upload.

This module provides the main() function that serves as the entry point
for the installed console script.
"""

import runpy
import sys
from pathlib import Path


def main() -> None:
    """Main entry point for the gitlab-pkg-upload CLI.

    This function runs the standalone script as the main module.
    It handles the case where the script is installed as a package.
    """
    # Locate the standalone script relative to this module
    repo_root = Path(__file__).parent.parent.parent
    script_path = repo_root / "gitlab-pkg-upload.py"

    if not script_path.exists():
        print(f"Error: Could not find gitlab-pkg-upload.py at {script_path}", file=sys.stderr)
        sys.exit(1)

    # Run the script as __main__
    runpy.run_path(str(script_path), run_name="__main__")


if __name__ == "__main__":
    main()
