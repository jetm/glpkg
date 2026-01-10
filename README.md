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

### Pre-commit Hooks

Pre-commit hooks automate code quality checks locally before each commit, ensuring consistency with the CI/CD pipeline.

```bash
# Install pre-commit hooks
uv run pre-commit install

# Or using pip
pre-commit install
```

Once installed, hooks run automatically on `git commit`. You can also run them manually:

```bash
# Run all hooks on all files
uv run pre-commit run --all-files

# Update hook versions
uv run pre-commit autoupdate
```

The configured hooks include:
- **Ruff**: Linting and code formatting
- **Mypy**: Static type checking with strict mode
- **File maintenance**: Trailing whitespace removal, end-of-file fixes, YAML/TOML validation

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

Pre-commit hooks automate these checks on every commit. See [Pre-commit Hooks](#pre-commit-hooks) for setup.

To run checks manually:

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
