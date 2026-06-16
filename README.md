# glpkg

![Tests](https://github.com/jetm/glpkg/actions/workflows/test.yml/badge.svg)
![Lint](https://github.com/jetm/glpkg/actions/workflows/lint.yml/badge.svg)
![Publish](https://github.com/jetm/glpkg/actions/workflows/publish.yml/badge.svg)
![Docs](https://github.com/jetm/glpkg/actions/workflows/docs.yml/badge.svg)
![Coverage](https://img.shields.io/badge/coverage-95%25-brightgreen)

> [!IMPORTANT]
> **This repository is archived.** The `upload` and `list` functionality has been merged into [glab](https://gitlab.com/gitlab-org/cli) via [MR !3393](https://gitlab.com/gitlab-org/cli/-/merge_requests/3393). Use `glab` instead of `glpkg`.

A CLI tool for uploading and listing files in GitLab's Generic Package Registry.

## Installation

### From PyPI (Recommended)

```bash
# Using uv (recommended)
uv pip install glpkg-cli

# Or using pip
pip install glpkg-cli
```

After installation, the `glpkg` command is available in your PATH:

```bash
# Verify installation
glpkg --version

# View available commands
glpkg --help
```

### Universal Binary (.pyz)

Download the pre-built universal binary from GitHub releases.
This is a self-contained executable that requires no installation -
just Python 3.11+.

```bash
# Download the latest release (replace VERSION with desired version, e.g., v0.1.1)
curl -L -o glpkg.pyz \
  https://github.com/jetm/glpkg/releases/download/VERSION/glpkg-VERSION.pyz

# Make it executable
chmod +x glpkg.pyz

# Run directly
./glpkg.pyz --help

# Or run with Python
python glpkg.pyz --help
```

Optionally, install the binary to a location in your PATH for easier access:

```bash
# Install to ~/.local/bin (user-local)
mv glpkg.pyz ~/.local/bin/glpkg
chmod +x ~/.local/bin/glpkg

# Or install system-wide (requires sudo)
sudo mv glpkg.pyz /usr/local/bin/glpkg
sudo chmod +x /usr/local/bin/glpkg

# Now use it like a regular command
glpkg --help
```

### Development Installation

```bash
# Clone the repository
git clone https://github.com/jetm/glpkg.git
cd glpkg

# Install in development mode with uv
uv pip install -e .

# Or run directly without installing
uv run glpkg --help
```

## Usage

```bash
# Upload a single file
glpkg upload --package-name my-package --package-version 1.0.0 \
  --files file.tar.gz

# Upload multiple files
glpkg upload --package-name my-package --package-version 1.0.0 \
  --files file1.tar.gz file2.zip

# Upload with automatic project detection from git remote
glpkg upload --package-name my-package --package-version 1.0.0 \
  --files file.tar.gz

# Specify project explicitly
glpkg upload --package-name my-package --package-version 1.0.0 \
    --project-path namespace/project --files file.tar.gz

# Handle duplicates (skip, replace, or error)
glpkg upload --package-name my-package --package-version 1.0.0 \
    --duplicate-policy replace --files file.tar.gz

# Verbose output with global flags
glpkg --verbose upload --package-name my-package \
  --package-version 1.0.0 --files file.tar.gz

# JSON output for CI/CD pipelines
glpkg --json-output upload --package-name my-package \
  --package-version 1.0.0 --files file.tar.gz

# List files in a package from a GitLab URL
glpkg list --url https://gitlab.com/group/project/-/packages/12345

# List files by package name and version
glpkg list --package-name my-package --package-version 1.0.0

# List all versions of a package
glpkg list --package-name my-package

# List with JSON output
glpkg --json-output list --url https://gitlab.com/group/project/-/packages/12345
```

## Configuration

### Environment Variables

| Variable              | Description                            | Required |
| --------------------- | -------------------------------------- | -------- |
| `GITLAB_TOKEN`        | GitLab access token with api scope     | Yes      |
| `GITLAB_URL`          | GitLab URL (default: gitlab.com)       | No       |
| `GITLAB_PROJECT_PATH` | Project path (e.g., `group/project`)   | No       |

### Token Permissions

Your GitLab token requires:

- `api` scope for full API access
- Write access to the target project's Package Registry

## Development

For detailed contribution guidelines, see [CONTRIBUTING.md](CONTRIBUTING.md).

### Quick Start

```bash
# Clone and install dependencies
git clone https://github.com/jetm/glpkg.git
cd glpkg
uv sync --all-extras

# Install pre-commit hooks
uv run pre-commit install

# Run tests
uv run pytest tests/unit/
```

### Q&A

**Why not use the glab tool?**

This tool was written when `glab` did not properly support uploading to the Generic Package Registry (see [gitlab-org/cli#7421](https://gitlab.com/gitlab-org/cli/-/issues/7421)). That gap has since been closed - the functionality was merged in [MR !3393](https://gitlab.com/gitlab-org/cli/-/merge_requests/3393).

**Why not contribute this feature to glab?**

For several reasons. I wanted to gain the experience of creating a tool from
scratch, learn more about Python and its ecosystem, and understand GitHub CI
better. GitLab is too slow at reviewing changes.

### Documentation

- [CONTRIBUTING.md](CONTRIBUTING.md) - Development setup and guidelines
- [docs/SHELL_COMPLETION.md](docs/SHELL_COMPLETION.md) - Shell completion
- [docs/RELEASING.md](docs/RELEASING.md) - Release procedures
- [docs/WORKFLOWS.md](docs/WORKFLOWS.md) - GitHub Actions workflows
- [tests/README.md](tests/README.md) - Detailed testing documentation

## Project Structure

```text
glpkg/
├── src/
│   └── glpkg/
│       ├── __init__.py
│       ├── cli/
│       │   ├── __init__.py
│       │   ├── main.py         # Main CLI entry point
│       │   ├── upload.py       # Upload subcommand implementation
│       │   └── list_cmd.py     # List subcommand implementation
│       ├── models.py           # Data models
│       ├── uploader.py         # Upload logic
│       ├── formatters.py       # Output formatting
│       ├── duplicate_detector.py  # Duplicate detection
│       └── validators.py       # Input validation
├── tests/
│   ├── unit/                   # Unit tests
│   ├── integration/            # Integration tests
│   └── utils/                  # Test utilities
├── pyproject.toml              # Project configuration
└── README.md                   # This file
```

## License

MIT License
