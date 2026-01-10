# GitLab Package Upload

A CLI tool for uploading files to GitLab's Generic Package Registry.

## Installation

### Using uv (Recommended)

```bash
# Install in development mode
uv pip install -e .

# Or run directly without installing
uv run gitlab-pkg-upload --help
```

### Using pip

```bash
pip install -e .
```

## Usage

```bash
# Upload a single file
gitlab-pkg-upload file.tar.gz --package-name my-package --version 1.0.0

# Upload multiple files
gitlab-pkg-upload file1.tar.gz file2.zip --package-name my-package --version 1.0.0

# Upload with automatic project detection from git remote
gitlab-pkg-upload file.tar.gz --package-name my-package --version 1.0.0

# Specify project explicitly
gitlab-pkg-upload file.tar.gz --package-name my-package --version 1.0.0 \
    --project-path namespace/project

# Handle duplicates (skip, replace, or error)
gitlab-pkg-upload file.tar.gz --package-name my-package --version 1.0.0 \
    --duplicate-policy replace
```

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `GITLAB_TOKEN` | GitLab personal access token with `api` scope | Yes |
| `GITLAB_URL` | GitLab instance URL | No (defaults to https://gitlab.com) |
| `GITLAB_PROJECT_PATH` | Project path (e.g., `namespace/project`) | No (auto-detected from git) |

### Token Permissions

Your GitLab token requires:
- `api` scope for full API access
- Write access to the target project's Package Registry

## Development

### Setup

```bash
# Clone the repository
git clone https://gitlab.com/your-namespace/gitlab-pkg-upload.git
cd gitlab-pkg-upload

# Install with development dependencies
uv sync --all-extras

# Or using pip
pip install -e ".[dev,test]"
```

### Running Tests

```bash
# Install the package in development mode first
uv pip install -e .

# Run all tests
uv run pytest tests/

# Run only unit tests (fast, no external dependencies)
uv run pytest tests/unit/

# Run integration tests (requires GITLAB_TOKEN)
export GITLAB_TOKEN="your-token"
uv run pytest tests/integration/ -m integration

# Run with parallel execution
uv run pytest tests/ -n auto

# Run with verbose output
uv run pytest tests/ -v
```

See [tests/README.md](tests/README.md) for detailed testing documentation.

### Code Quality

```bash
# Run linter
uv run ruff check src/

# Run type checker
uv run mypy src/

# Format code
uv run ruff format src/
```

## Project Structure

```
gitlab-pkg-upload/
├── src/
│   └── gitlab_pkg_upload/
│       ├── __init__.py
│       ├── cli.py          # Command-line interface
│       ├── models.py       # Data models
│       ├── uploader.py     # Upload logic
│       └── validators.py   # Input validation
├── tests/
│   ├── unit/               # Unit tests
│   ├── integration/        # Integration tests
│   └── utils/              # Test utilities
├── pyproject.toml          # Project configuration
└── README.md               # This file
```

## License

MIT License
