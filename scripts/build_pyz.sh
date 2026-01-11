#!/usr/bin/env bash
#
# Build script for creating .pyz universal binaries using Shiv or PEX.
#
# Usage:
#   ./scripts/build_pyz.sh [OPTIONS]
#
# Options:
#   --tool [shiv|pex|both]   Build tool to use (default: shiv)
#   --output-dir DIR         Output directory (default: dist)
#   --help                   Show this help message
#
# Examples:
#   ./scripts/build_pyz.sh                      # Build with Shiv to dist/
#   ./scripts/build_pyz.sh --tool pex           # Build with PEX
#   ./scripts/build_pyz.sh --tool both          # Build with both tools
#   ./scripts/build_pyz.sh --output-dir build   # Output to build/
#
# Platform Compatibility Notes:
#   - .pyz files are platform-independent for pure Python packages
#   - Dependencies with C extensions (e.g., some cryptography libraries)
#     may require platform-specific builds
#   - Tested on Linux, should work on macOS and Windows with Python 3.11+
#

set -euo pipefail

# Default values
TOOL="shiv"
OUTPUT_DIR="dist"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

usage() {
    head -30 "$0" | tail -28 | sed 's/^# //' | sed 's/^#//'
    exit 0
}

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

extract_version() {
    local version
    version=$(grep -E '^version = "' "${PROJECT_ROOT}/pyproject.toml" | sed 's/version = "\([^"]*\)"/\1/')

    # Strip any leading 'v' character
    version="${version#v}"

    # Validate version contains only numbers and dots
    if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        log_error "Invalid version format: $version"
        exit 1
    fi

    echo "$version"
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --tool)
            TOOL="$2"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --help|-h)
            usage
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            ;;
    esac
done

# Validate tool option
if [[ ! "$TOOL" =~ ^(shiv|pex|both)$ ]]; then
    log_error "Invalid tool: $TOOL. Must be 'shiv', 'pex', or 'both'."
    exit 1
fi

# Create output directory
mkdir -p "${PROJECT_ROOT}/${OUTPUT_DIR}"

build_with_shiv() {
    log_info "Building .pyz with Shiv..."

    # Determine how to run shiv (uv run for local dev, direct for CI)
    local shiv_cmd="shiv"
    if command -v uv &> /dev/null && [[ -f "${PROJECT_ROOT}/uv.lock" ]]; then
        # Check if shiv is available directly first (CI environment)
        if ! command -v shiv &> /dev/null; then
            shiv_cmd="uv run shiv"
        fi
    elif ! command -v shiv &> /dev/null; then
        log_error "shiv is not installed. Install with: uv pip install shiv"
        exit 1
    fi

    local version
    version=$(extract_version)
    local output_file="${PROJECT_ROOT}/${OUTPUT_DIR}/glpkg-v${version}.pyz"
    local temp_dir
    temp_dir=$(mktemp -d)

    # Cleanup on exit
    trap "rm -rf ${temp_dir}" EXIT

    log_info "Installing package to temporary directory..."
    uv pip install "${PROJECT_ROOT}" --target "${temp_dir}" --quiet

    log_info "Creating .pyz archive..."
    ${shiv_cmd} \
        --site-packages "${temp_dir}" \
        --compressed \
        --console-script glpkg \
        --output-file "${output_file}" \
        --python "/usr/bin/env python3"

    chmod +x "${output_file}"

    local size
    size=$(du -h "${output_file}" | cut -f1)
    log_info "Successfully built: ${output_file} (${size})"
}

build_with_pex() {
    log_info "Building .pex with PEX..."

    # Determine how to run pex (uv run for local dev, direct for CI)
    local pex_cmd="pex"
    if command -v uv &> /dev/null && [[ -f "${PROJECT_ROOT}/uv.lock" ]]; then
        # Check if pex is available directly first (CI environment)
        if ! command -v pex &> /dev/null; then
            pex_cmd="uv run pex"
        fi
    elif ! command -v pex &> /dev/null; then
        log_error "pex is not installed. Install with: uv pip install pex"
        exit 1
    fi

    local version
    version=$(extract_version)
    local output_file="${PROJECT_ROOT}/${OUTPUT_DIR}/glpkg-v${version}.pex"

    log_info "Creating .pex archive..."
    ${pex_cmd} \
        "${PROJECT_ROOT}" \
        --console-script glpkg \
        --output-file "${output_file}"

    chmod +x "${output_file}"

    local size
    size=$(du -h "${output_file}" | cut -f1)
    log_info "Successfully built: ${output_file} (${size})"
}

# Main execution
cd "${PROJECT_ROOT}"

log_info "Project root: ${PROJECT_ROOT}"
log_info "Output directory: ${OUTPUT_DIR}"
log_info "Build tool: ${TOOL}"

case $TOOL in
    shiv)
        build_with_shiv
        ;;
    pex)
        build_with_pex
        ;;
    both)
        build_with_shiv
        # Reset trap for second build
        trap - EXIT
        build_with_pex
        ;;
esac

log_info "Build complete!"
echo ""
echo "To test the built binary:"
echo "  python ${OUTPUT_DIR}/glpkg-v*.pyz --version"
echo "  python ${OUTPUT_DIR}/glpkg-v*.pyz --help"
