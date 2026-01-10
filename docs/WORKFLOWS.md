# GitHub Workflows Documentation

This document provides comprehensive documentation for all GitHub Actions workflows used in the glpkg project. These workflows form the CI/CD pipeline that ensures code quality, runs tests, validates documentation, and handles package publishing.

## Table of Contents

- [Test Workflow](#test-workflow)
- [Lint Workflow](#lint-workflow)
- [Publish Workflow](#publish-workflow)
- [Documentation Workflow](#documentation-workflow)
- [Workflow Status Badges](#workflow-status-badges)
- [Common Debugging Steps](#common-debugging-steps)
- [Future Improvements](#future-improvements)

## Test Workflow

**File:** `.github/workflows/test.yml`

### Purpose

Runs unit and integration tests across Python 3.11-3.13 to ensure code correctness and maintain test coverage standards.

### Triggers

- Push to any branch
- Pull requests to `main` or `master`
- Manual dispatch via `workflow_dispatch`

### Key Features

- **Matrix testing** across Python versions 3.11, 3.12, and 3.13
- **Unit tests** with pytest-cov providing coverage reporting
- **Coverage thresholds**: 95% warning level, 90% fail threshold
- **Integration tests** run conditionally when `GITLAB_TOKEN` and `GITLAB_REPO` secrets are configured
- **Coverage report upload** for Python 3.11 runs
- Uses `uv` for fast, reliable dependency management

### Required Secrets

| Secret | Required | Description |
|--------|----------|-------------|
| `GITLAB_TOKEN` | Optional | GitLab API token for integration tests |
| `GITLAB_REPO` | Optional | GitLab repository path for integration tests |

Integration tests are skipped if these secrets are not configured.

### Artifacts

- `coverage.xml` - XML coverage report for CI integrations
- `htmlcov/` - HTML coverage report for detailed inspection
- `pytest-results` - Test result files

### Debugging Tips

- **Coverage threshold failures**: Check the "Check coverage threshold" step output for specific coverage percentages
- **Integration tests skipped**: Verify `GITLAB_TOKEN` and `GITLAB_REPO` secrets are configured in repository settings
- **Manual test runs**: Use `workflow_dispatch` from the Actions tab for on-demand testing
- **Detailed coverage**: Download the `htmlcov` artifact to see line-by-line coverage
- **Local reproduction**: Run `uv run pytest tests/unit/ --cov=src/glpkg --cov-report=term-missing`

## Lint Workflow

**File:** `.github/workflows/lint.yml`

### Purpose

Performs code quality checks using ruff for linting/formatting and mypy for type checking to maintain consistent code standards.

### Triggers

- Push to any branch
- Pull requests to `main` or `master`
- Manual dispatch via `workflow_dispatch`

### Key Features

- **Ruff linting**: `ruff check src/` for code style and error detection
- **Ruff formatting**: `ruff format --check src/` for consistent code formatting
- **Mypy type checking**: Strict mode (`--strict`) for comprehensive type safety
- Uses Python 3.11 and `uv` for consistency

### Required Secrets

None

### Debugging Tips

- **Ruff lint errors**: Run locally with `uv run ruff check src/ --fix` to auto-fix issues
- **Ruff format errors**: Run `uv run ruff format src/` to auto-format code
- **Mypy errors**: Run `uv run mypy src/glpkg/ --strict` locally to see detailed type errors
- **Configuration**: Check `pyproject.toml` for ruff and mypy configuration options
- **Ignore patterns**: Add inline `# noqa` comments or configure exclusions in `pyproject.toml`

## Publish Workflow

**File:** `.github/workflows/publish.yml`

### Purpose

Builds and publishes the package to PyPI and creates GitHub release assets including the universal `.pyz` binary.

### Triggers

- GitHub release published
- Manual dispatch via `workflow_dispatch`

### Key Features

- **Package building**: Creates wheel and sdist with `python -m build`
- **Universal binary**: Builds `.pyz` file using shiv for standalone execution
- **GitHub release assets**: Uploads `.pyz` binary to release assets
- **PyPI publishing**: Publishes to PyPI using token authentication
- **Package name**: Published as `glpkg-cli` on PyPI

### Required Secrets

| Secret | Required | Description |
|--------|----------|-------------|
| `PYPI_API_TOKEN` | Yes | PyPI API token with upload permissions |

### Artifacts

- `dist/` directory containing:
  - `*.whl` - Wheel package
  - `*.tar.gz` - Source distribution
  - `*.pyz` - Universal binary

### Debugging Tips

- **Test .pyz build locally**: `bash scripts/build_pyz.sh --tool shiv --output-dir dist`
- **Verify package builds**: `uv pip install build --system && python -m build`
- **PyPI token issues**: Ensure token has "Upload packages" permission for the `glpkg-cli` project
- **Build script issues**: Review `scripts/build_pyz.sh` for shiv configuration
- **Version conflicts**: Check that the version in `pyproject.toml` doesn't already exist on PyPI
- **Local testing**: Install the built wheel with `pip install dist/*.whl` before publishing

## Documentation Workflow

**File:** `.github/workflows/docs.yml`

### Purpose

Validates markdown files for proper formatting and checks that all links are functional.

### Triggers

- Push to any branch
- Pull requests to `main` or `master`
- Manual dispatch via `workflow_dispatch`

### Key Features

- **Markdown linting** with markdownlint-cli2 for consistent formatting
- **Link checking** with markdown-link-check for broken URL detection
- **Validated files**:
  - `README.md`
  - `CONTRIBUTING.md`
  - `tests/README.md`
  - `docs/RELEASING.md`
  - `docs/SHELL_COMPLETION.md`
  - `docs/WORKFLOWS.md`

### Required Secrets

None

### Debugging Tips

- **Markdown lint errors**: Install markdownlint-cli2 locally (`npm install -g markdownlint-cli2`) and run on specific files
- **Broken links**: Verify URLs are accessible; some may be rate-limited or require authentication
- **Custom rules**: Add `.markdownlint.json` to configure or disable specific linting rules
- **Link check config**: Add `.markdown-link-check.json` for custom link checking behavior
- **False positives**: Some internal links may fail in CI but work in the repository

## Workflow Status Badges

Add these badges to your README.md to display workflow status:

```markdown
![Tests](https://github.com/OWNER/REPO/actions/workflows/test.yml/badge.svg)
![Lint](https://github.com/OWNER/REPO/actions/workflows/lint.yml/badge.svg)
![Publish](https://github.com/OWNER/REPO/actions/workflows/publish.yml/badge.svg)
![Docs](https://github.com/OWNER/REPO/actions/workflows/docs.yml/badge.svg)
```

Replace `OWNER/REPO` with your actual GitHub repository path (e.g., `your-org/glpkg`).

## Common Debugging Steps

1. **Check workflow logs**: Navigate to the Actions tab in GitHub and select the failed workflow run
2. **Manual testing**: Use `workflow_dispatch` to trigger workflows manually for debugging
3. **Local reproduction**: Run the same commands locally using `uv` before pushing
4. **Review configuration**: Check `pyproject.toml` for tool-specific settings
5. **Secret verification**: Ensure required secrets are configured in repository Settings > Secrets and variables > Actions
6. **Branch protection**: Verify branch protection rules aren't blocking workflow execution
7. **Permissions**: Check that the `GITHUB_TOKEN` has necessary permissions for the workflow

## Future Improvements

### Integration Test Secret Checking

The current condition `${{ secrets.GITLAB_TOKEN != '' }}` may not work as expected since GitHub Actions doesn't expose secret values in expressions. Consider these alternatives:

- Use a dedicated job with conditional execution based on repository context
- Use environment-based checks with separate environments for integration testing
- Restrict integration tests to specific branches: `if: github.ref == 'refs/heads/main'`

### PyPI Trusted Publishing

The current workflow uses token-based authentication (`PYPI_API_TOKEN`). Consider migrating to PyPI trusted publishing (OIDC) for enhanced security:

**Benefits:**

- Eliminates need for long-lived API tokens
- No secret rotation required
- Stronger authentication through GitHub's OIDC provider

**Migration steps:**

1. Configure the PyPI project for trusted publishing in PyPI settings
2. Add the GitHub repository as a trusted publisher
3. Update the workflow to use `pypa/gh-action-pypi-publish` with OIDC
4. Remove the `PYPI_API_TOKEN` secret after verification

See [PyPI Trusted Publishing documentation](https://docs.pypi.org/trusted-publishers/) for details.
