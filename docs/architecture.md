# Architecture

## Directory Structure

```text
src/glpkg/
├── cli/
│   ├── main.py           # CLI entry point (glpkg command)
│   └── upload.py         # Upload subcommand
├── models.py             # Data models, exceptions, enums
├── uploader.py           # Core upload logic with retry
├── formatters.py         # Output formatting (text, JSON)
├── duplicate_detector.py # SHA256-based duplicate detection
└── validators.py         # Input validation
```

**Entry point**: `src/glpkg/cli/main.py:main`

## Core Flow

```text
CLI (main.py) → upload subcommand (upload.py)
    → validators check inputs (file existence, project ID)
    → duplicate_detector checks remote for existing files (SHA256)
    → uploader handles uploads with tenacity retry (exponential backoff)
    → formatters output results (text or JSON)
```

## Error Handling

- Custom exceptions in `models.py`:
  `ChecksumValidationError`, `DuplicatePolicy` enum
- `uploader.py` uses tenacity for retry with `wait_exponential` and `stop_after_attempt`
- Transient GitLab API errors trigger automatic retry
- `DuplicatePolicy` controls behavior on existing files: `skip`, `replace`, or `error`

## Key Models (`models.py`)

- **`UploadContext`** — Upload session state (project, package, version, files)
- **`UploadResult`** — Per-file upload outcome (success, skipped, error)
- **`RemoteFile`** — Existing file metadata from GitLab registry
- **`DuplicatePolicy`** — Enum: `SKIP`, `REPLACE`, `ERROR`
