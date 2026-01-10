# Release Procedures

This document describes the release workflow for glpkg.

## Overview

- Project uses [semantic versioning](https://semver.org/) (major.minor.patch)
- Automated version management with [bump-my-version](https://github.com/callowayproject/bump-my-version)
- PyPI publishing via GitHub Actions on release creation
- Universal .pyz binaries built and attached to GitHub releases

## Creating a Release

### 1. Bump Version

Use `bump-my-version` based on the type of changes:

```bash
# Bug fixes: 0.1.0 → 0.1.1
uv run bump-my-version bump patch

# New features: 0.1.0 → 0.2.0
uv run bump-my-version bump minor

# Breaking changes: 0.1.0 → 1.0.0
uv run bump-my-version bump major
```

### 2. Verify Changes

Confirm the version was updated correctly:

```bash
# Check version in both files
grep -r "version" pyproject.toml src/glpkg/__init__.py | head -5

# Verify git commit and tag were created
git log -1 --oneline
git tag -l | tail -3
```

### 3. Push Changes

Push the commit and tag to GitHub:

```bash
git push && git push --tags
```

### 4. Create GitHub Release

1. Navigate to the repository's Releases page
2. Click "Create a new release"
3. Select the version tag (e.g., `v0.2.0`)
4. Add release notes describing the changes
5. Click "Publish release"

### 5. Automated Publishing

The GitHub Actions workflow (`.github/workflows/publish.yml`) automatically:

- Builds and publishes the package to PyPI
- Builds the .pyz universal binary
- Attaches the binary to the GitHub release

## Building .pyz Locally

For testing or local distribution, you can build the universal binary locally:

```bash
# Build with Shiv (recommended)
./scripts/build_pyz.sh --tool shiv

# Build with PEX
./scripts/build_pyz.sh --tool pex

# Build with both tools
./scripts/build_pyz.sh --tool both

# Test the binary
python dist/glpkg.pyz --version
```

See `scripts/build_pyz.sh` for build script details.

## Manual Release (Without GitHub Actions)

If you need to publish a release manually without relying on GitHub Actions:

### 1. Get the Current Version

```bash
# Extract version from pyproject.toml
VERSION=$(grep -m1 'version = ' pyproject.toml | cut -d'"' -f2)
echo "Version: ${VERSION}"

# Or from Python
VERSION=$(uv run python -c "import glpkg; print(glpkg.__version__)")
echo "Version: ${VERSION}"
```

### 2. Build the Package

```bash
# Install build tool if needed
uv pip install build

# Build source distribution and wheel
uv run python -m build

# Verify build artifacts
ls dist/
# Should show: glpkg_cli-${VERSION}.tar.gz and glpkg_cli-${VERSION}-py3-none-any.whl
```

### 3. Publish to PyPI

PyPI requires API token authentication (username/password is no longer supported).

**Get an API token:**

1. Log in to [PyPI](https://pypi.org/manage/account/)
2. Go to Account Settings → API tokens
3. Create a new token (scope: "Entire account" or project-specific)
4. Copy the token (starts with `pypi-`)

**Upload with the token:**

```bash
# Install twine if not already installed
uv pip install twine

# Upload to PyPI using API token
TWINE_USERNAME=__token__ TWINE_PASSWORD=pypi-<your-api-token> uv run twine upload dist/glpkg_cli-${VERSION}*
```

Alternatively, configure credentials in `~/.pypirc`:

```ini
[pypi]
username = __token__
password = pypi-<your-api-token>
```

Then upload without environment variables:

```bash
uv run twine upload dist/glpkg_cli-${VERSION}*
```

For more information, see:

- [API Tokens](https://pypi.org/help/#apitoken) - Create a token for manual uploads
- [Trusted Publishers](https://pypi.org/help/#trusted-publishers) - Configure GitHub Actions for automated publishing

### 4. Build and Upload .pyz Binary

```bash
# Build the .pyz binary
./scripts/build_pyz.sh --tool shiv

# Verify the binary works
python dist/glpkg.pyz --version
```

Upload the .pyz binary to the GitHub release:

```bash
# Using GitHub CLI (gh)
gh release upload v${VERSION} dist/glpkg.pyz

# Or manually via GitHub web interface:
# 1. Go to https://github.com/your-org/glpkg/releases/tag/v${VERSION}
# 2. Click "Edit release"
# 3. Drag and drop dist/glpkg.pyz into the "Attach binaries" area
# 4. Click "Update release"
```

## Verification Steps

After publishing a release:

1. **Check PyPI**: Visit `https://pypi.org/project/glpkg-cli/`

2. **Test PyPI installation**:

   ```bash
   uv pip install glpkg-cli==<version>
   glpkg --version
   ```

3. **Test .pyz binary**:

   ```bash
   # Download from GitHub release
   curl -L -o glpkg.pyz https://github.com/your-org/glpkg/releases/download/v<version>/glpkg.pyz
   python glpkg.pyz --version
   ```

## Troubleshooting

### PyPI Publish Fails

- Verify `PYPI_API_TOKEN` secret is configured in GitHub repository settings
- Check that trusted publishing is configured on PyPI for this repository
- Review the GitHub Actions logs for specific error messages

### .pyz Build Fails

- Ensure `shiv` or `pex` is installed: `uv pip install shiv pex`
- Check build logs in GitHub Actions for dependency issues
- Try building locally to reproduce the issue

### Version Mismatch

Preview changes before bumping:

```bash
uv run bump-my-version bump --dry-run --verbose patch
```

### Tag Already Exists

If you need to recreate a tag:

```bash
# Delete local tag
git tag -d v<version>

# Delete remote tag
git push origin :refs/tags/v<version>

# Re-run bump-my-version or create tag manually
git tag v<version>
git push --tags
```

## Release Checklist

Before creating a release, verify:

- [ ] All tests passing on main branch
- [ ] Coverage meets 90% minimum threshold
- [ ] CHANGELOG or release notes prepared
- [ ] Version bumped with bump-my-version
- [ ] Changes and tags pushed to GitHub
- [ ] GitHub release created with release notes

After release:

- [ ] PyPI package published successfully
- [ ] .pyz binary attached to release
- [ ] Installation verified from PyPI
- [ ] .pyz binary verified
