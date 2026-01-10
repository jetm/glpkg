# glpkg

A CLI tool for uploading files to GitLab's Generic Package Registry.

## Installation

### Using uv (Recommended)

```bash
# Install in development mode
uv pip install -e .

# Or run directly without installing
uv run glpkg --help
```

### Using pip

```bash
pip install -e .
```

## Usage

```bash
# Upload a single file
glpkg upload --package-name my-package --package-version 1.0.0 --files file.tar.gz

# Upload multiple files
glpkg upload --package-name my-package --package-version 1.0.0 --files file1.tar.gz file2.zip

# Upload with automatic project detection from git remote
glpkg upload --package-name my-package --package-version 1.0.0 --files file.tar.gz

# Specify project explicitly
glpkg upload --package-name my-package --package-version 1.0.0 \
    --project-path namespace/project --files file.tar.gz

# Handle duplicates (skip, replace, or error)
glpkg upload --package-name my-package --package-version 1.0.0 \
    --duplicate-policy replace --files file.tar.gz

# Verbose output with global flags
glpkg --verbose upload --package-name my-package --package-version 1.0.0 --files file.tar.gz

# JSON output for CI/CD pipelines
glpkg --json-output upload --package-name my-package --package-version 1.0.0 --files file.tar.gz
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
git clone https://gitlab.com/your-namespace/glpkg.git
cd glpkg

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

### Versioning

This project uses [semantic versioning](https://semver.org/) (major.minor.patch) with [bump-my-version](https://github.com/callowayproject/bump-my-version) for automated version management.

```bash
# Install dev dependencies (includes bump-my-version)
uv pip install -e ".[dev]"

# Bump patch version (bug fixes): 0.1.0 → 0.1.1
uv run bump-my-version bump patch

# Bump minor version (new features): 0.1.0 → 0.2.0
uv run bump-my-version bump minor

# Bump major version (breaking changes): 0.1.0 → 1.0.0
uv run bump-my-version bump major
```

Running `bump-my-version bump` automatically:
- Updates the version in `pyproject.toml` and `src/glpkg/__init__.py`
- Creates a git commit with the version change
- Creates a git tag (format: `v1.2.3`)

#### Release Workflow

```bash
# 1. Bump version (e.g., patch for bug fix)
uv run bump-my-version bump patch

# 2. Push changes and tags
git push && git push --tags

# 3. Create GitHub release at https://github.com/your-org/glpkg/releases/new
# 4. PyPI publication happens automatically via GitHub Actions
```

To create a GitHub release:
1. Navigate to the repository's Releases page
2. Click "Create a new release"
3. Select the version tag created by bump-my-version
4. Add release notes describing changes
5. Publish the release

Publishing a GitHub release automatically triggers the `.github/workflows/publish.yml` workflow to publish to PyPI.

#### Verification

```bash
# Check that version numbers match in both files
grep -r "0.1.0" pyproject.toml src/glpkg/__init__.py

# Test bump-my-version dry run
uv run bump-my-version bump patch --dry-run --verbose

# Verify git tags
git tag -l
```

## Project Structure

```
glpkg/
├── src/
│   └── glpkg/
│       ├── __init__.py
│       ├── cli/
│       │   ├── __init__.py
│       │   ├── main.py         # Main CLI entry point with subcommand routing
│       │   └── upload.py       # Upload subcommand implementation
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
