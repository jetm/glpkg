# Contributing to glpkg

Thank you for your interest in contributing to glpkg! This document provides
guidelines and instructions for development.

## Getting Started

### Prerequisites

- Python 3.11 or higher
- uv installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`)

### Development Setup

```bash
# Clone the repository
git clone https://github.com/your-org/glpkg.git
cd glpkg

# Install all dependencies (including dev and test extras)
uv sync --all-extras
```

## Development Workflow

1. Install pre-commit hooks:

   ```bash
   uv run pre-commit install
   ```

2. Create a feature branch:

   ```bash
   git checkout -b feature/your-feature-name
   ```

3. Make your changes
4. Run tests locally before committing
5. Commit your changes (pre-commit hooks run automatically)
6. Push and create a pull request

## Running Tests

### Unit Tests

Fast tests that don't require external dependencies:

```bash
uv run pytest tests/unit/
```

### Integration Tests

Require a GitLab token and opt-in via environment variable:

```bash
export RUN_INTEGRATION_TESTS=1
export GITLAB_TOKEN="your-token"
uv run pytest tests/integration/ -m integration
```

### All Tests with Coverage

```bash
uv run pytest tests/
```

### Parallel Execution

Speed up test runs with parallel execution:

```bash
uv run pytest tests/ -n auto
```

For detailed testing documentation, see [tests/README.md](tests/README.md).

## Code Quality Checks

Pre-commit hooks run automatically on every commit. To run checks manually:

### Linting

```bash
uv run ruff check src/
```

### Type Checking

```bash
uv run mypy src/
```

### Formatting

```bash
uv run ruff format src/
```

### Run All Pre-commit Hooks

```bash
uv run pre-commit run --all-files
```

## Coverage Requirements

- **Target coverage**: 95% (warning threshold in CI)
- **Minimum coverage**: 90% (tests fail below this threshold)

View coverage report locally:

```bash
uv run pytest tests/unit/ --cov=glpkg --cov-report=html
open htmlcov/index.html  # or xdg-open on Linux
```

## Pull Request Process

1. Create a feature branch from `main`
2. Make changes with clear, descriptive commits
3. Ensure all tests pass and coverage meets requirements
4. Ensure pre-commit hooks pass
5. Push your branch and create a pull request
6. Address review feedback
7. Squash commits if requested by maintainers

## Code Style Guidelines

- Follow PEP 8 conventions (enforced by ruff)
- Use type hints (checked by mypy in strict mode)
- Write descriptive docstrings for public APIs
- Keep functions focused and testable
- Avoid over-engineering; keep solutions simple

## Adding New Features

When adding new features:

1. Add unit tests in `tests/unit/`
2. Add integration tests in `tests/integration/` if the feature interacts
   with external services
3. Update documentation in README.md or relevant docs
4. Add appropriate pytest markers:
   - `@pytest.mark.unit` for unit tests
   - `@pytest.mark.integration` for integration tests

## Questions?

If you have questions about contributing, please open an issue on GitHub.
