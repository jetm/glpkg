# GitHub Workflows Documentation

This document provides comprehensive documentation for all GitHub Actions
workflows used in the glpkg project. These workflows form the CI/CD pipeline
that ensures code quality, runs tests, validates documentation, and handles
package publishing.

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

Runs unit and integration tests across Python 3.11-3.13 to ensure code
correctness and maintain test coverage standards.

**Triggers:**

- Push to any branch
- Pull requests to `main` or `master`
- Manual dispatch via `workflow_dispatch`

**Key Features:**

- Matrix testing across Python versions 3.11, 3.12, and 3.13
- Unit tests with pytest-cov providing coverage reporting
- Coverage thresholds: 95% warning level, 90% fail threshold
- Integration tests run conditionally when secrets are configured
- Coverage report upload for Python 3.11 runs
- Uses `uv` for fast, reliable dependency management

**Secrets:**

| Secret         | Required | Description                              |
| -------------- | -------- | ---------------------------------------- |
| `GITLAB_TOKEN` | Optional | GitLab API token for integration tests   |
| `GITLAB_REPO`  | Optional | GitLab repository path for integration   |

Integration tests are skipped if these secrets are not configured.

**Artifacts:**

- `coverage.xml` - XML coverage report for CI integrations
- `htmlcov/` - HTML coverage report for detailed inspection
- `pytest-results` - Test result files

**Debugging:**

- Coverage threshold failures: Check the "Check coverage threshold" step
  output for specific coverage percentages
- Integration tests skipped: Verify `GITLAB_TOKEN` and `GITLAB_REPO`
  secrets are configured in repository settings
- Manual test runs: Use `workflow_dispatch` from Actions tab
- Detailed coverage: Download the `htmlcov` artifact
- Local reproduction:
  `uv run pytest tests/unit/ --cov=src/glpkg --cov-report=term-missing`

## Lint Workflow

**File:** `.github/workflows/lint.yml`

Performs code quality checks using ruff for linting/formatting and mypy for
type checking to maintain consistent code standards.

**Triggers:**

- Push to any branch
- Pull requests to `main` or `master`
- Manual dispatch via `workflow_dispatch`

**Key Features:**

- Ruff linting: `ruff check src/` for code style and error detection
- Ruff formatting: `ruff format --check src/` for consistent formatting
- Mypy type checking: Strict mode (`--strict`) for comprehensive type safety
- Uses Python 3.11 and `uv` for consistency

**Secrets:** None required.

**Debugging:**

- Ruff lint errors: Run `uv run ruff check src/ --fix` to auto-fix issues
- Ruff format errors: Run `uv run ruff format src/` to auto-format code
- Mypy errors: Run `uv run mypy src/glpkg/ --strict` locally
- Configuration: Check `pyproject.toml` for ruff and mypy settings
- Ignore patterns: Add `# noqa` comments or configure in `pyproject.toml`

## Publish Workflow

**File:** `.github/workflows/publish.yml`

Builds and publishes the package to PyPI and creates GitHub release assets
including the universal `.pyz` binary.

**Triggers:**

- GitHub release published
- Manual dispatch via `workflow_dispatch`

**Key Features:**

- Package building: Creates wheel and sdist with `python -m build`
- Universal binary: Builds `.pyz` file using shiv for standalone execution
- GitHub release assets: Uploads `.pyz` binary to release assets
- PyPI publishing: Publishes to PyPI using OIDC trusted publishing
- Package name: Published as `glpkg-cli` on PyPI

**Secrets:**

None required. PyPI authentication uses OIDC trusted publishing configured
in the PyPI project settings.

**Artifacts:**

- `dist/` directory containing:
  - `*.whl` - Wheel package
  - `*.tar.gz` - Source distribution
  - `*.pyz` - Universal binary

**Debugging:**

- Test .pyz build locally:
  `bash scripts/build_pyz.sh --tool shiv --output-dir dist`
- Verify package builds:
  `uv pip install build --system && python -m build`
- PyPI OIDC issues: Verify trusted publishing is configured in PyPI project
  settings and workflow has `id-token: write` permission
- Build script issues: Review `scripts/build_pyz.sh` for shiv configuration
- Version conflicts: Check version in `pyproject.toml` doesn't exist on PyPI
- Local testing: Install built wheel with `pip install dist/*.whl`

## Documentation Workflow

**File:** `.github/workflows/docs.yml`

Validates markdown files for proper formatting and checks that all links
are functional.

**Triggers:**

- Push to any branch
- Pull requests to `main` or `master`
- Manual dispatch via `workflow_dispatch`

**Key Features:**

- Markdown linting with markdownlint-cli2 for consistent formatting
- Link checking with markdown-link-check for broken URL detection
- Validated files:
  - `README.md`
  - `CONTRIBUTING.md`
  - `tests/README.md`
  - `docs/RELEASING.md`
  - `docs/SHELL_COMPLETION.md`
  - `docs/WORKFLOWS.md`

**Secrets:** None required.

**Debugging:**

- Markdown lint errors: Install markdownlint-cli2 locally and run on files
- Broken links: Verify URLs are accessible
- Custom rules: Add `.markdownlint.json` to configure linting rules
- Link check config: Add `.markdown-link-check.json` for custom behavior
- False positives: Some internal links may fail in CI but work locally

## Workflow Status Badges

Add these badges to your README.md to display workflow status:

```markdown
![Tests](https://github.com/OWNER/REPO/actions/workflows/test.yml/badge.svg)
![Lint](https://github.com/OWNER/REPO/actions/workflows/lint.yml/badge.svg)
![Publish](https://github.com/OWNER/REPO/actions/workflows/publish.yml/badge.svg)
![Docs](https://github.com/OWNER/REPO/actions/workflows/docs.yml/badge.svg)
```

Replace `OWNER/REPO` with your actual GitHub repository path.

## Common Debugging Steps

1. **Check workflow logs**: Navigate to Actions tab and select failed run
2. **Manual testing**: Use `workflow_dispatch` to trigger manually
3. **Local reproduction**: Run same commands locally using `uv`
4. **Review configuration**: Check `pyproject.toml` for tool settings
5. **Secret verification**: Ensure secrets are configured in Settings
6. **Branch protection**: Verify rules aren't blocking execution
7. **Permissions**: Check `GITHUB_TOKEN` has necessary permissions

## Future Improvements

### Integration Test Secret Checking

The current condition `${{ secrets.GITLAB_TOKEN != '' }}` may not work as
expected since GitHub Actions doesn't expose secret values in expressions.
Consider these alternatives:

- Use a dedicated job with conditional execution based on repository context
- Use environment-based checks with separate environments
- Restrict integration tests to specific branches
