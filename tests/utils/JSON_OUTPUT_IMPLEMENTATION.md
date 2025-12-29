# JSON Output Support Implementation Summary

## Overview
Added JSON output support to the test helpers module (`test_helpers.py`) while maintaining backward compatibility with existing regex-based tests.

## Changes Implemented

### 1. Extended UploadExecution Dataclass
**Location:** Lines 17-40

Added `use_json_output: bool = False` field to enable JSON mode for individual test executions.

```python
@dataclass
class UploadExecution:
    command: List[str]
    expected_exit_code: int
    expected_output_patterns: List[str]
    timeout: int = 120
    env_vars: Optional[Dict[str, str]] = None
    working_directory: Optional[str] = None
    use_json_output: bool = False  # NEW FIELD
```

### 2. Extended UploadResult Dataclass
**Location:** Lines 43-86

Added `json_data: Optional[Dict] = None` field to store parsed JSON response.

```python
@dataclass
class UploadResult:
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration: float
    uploaded_files: List[str]
    upload_urls: List[str]
    error_message: Optional[str] = None
    json_data: Optional[Dict] = None  # NEW FIELD
```

### 3. Updated execute_upload Method
**Location:** Lines 113-233

Enhanced to:
- Parse JSON output when `use_json_output=True`
- Extract data from JSON structure
- Determine success using JSON fields
- Extract error messages from JSON
- Populate `json_data` field in result

Key logic:
```python
# Parse JSON output if enabled
json_data = None
if execution.use_json_output:
    json_data = self._parse_json_output(result.stdout)

# Extract uploaded files and URLs
if json_data is not None:
    uploaded_files, upload_urls = self._extract_data_from_json(json_data)
else:
    uploaded_files = self._extract_uploaded_files(result.stdout)
    upload_urls = self._extract_upload_urls(result.stdout)
```

### 4. Updated build_command Method
**Location:** Lines 235-269

Added `use_json_output` parameter and logic to append `--json-output` flag:

```python
def build_command(self, use_json_output: bool = False, **kwargs) -> List[str]:
    # ... existing parameter handling ...

    # Add JSON output flag if requested
    if use_json_output or kwargs.get("json_output", False):
        command.append("--json-output")

    return command
```

### 5. Updated Helper Methods
**Location:** Lines 271-375

Both `create_single_file_execution()` and `create_multiple_file_execution()` now:
- Accept `use_json_output: bool = False` parameter
- Pass it to `build_command()`
- Set `expected_output_patterns=[]` when JSON mode is enabled (since regex patterns don't apply)

```python
def create_single_file_execution(
    self,
    package_name: str,
    version: str,
    file_path: str,
    project_path: Optional[str] = None,
    gitlab_url: str = "https://gitlab.com",
    duplicate_policy: str = "skip",
    use_json_output: bool = False,  # NEW PARAMETER
) -> UploadExecution:
    # ...
    expected_patterns = [] if use_json_output else [
        f"Package: {package_name}, Version: {version}",
        r"✓ All files processed successfully for",
    ]
```

### 6. Updated validate_upload_result Method
**Location:** Lines 377-423

Enhanced to validate using JSON data when available:

```python
# If JSON data is available, use structured validation
if result.json_data is not None:
    if not result.json_data.get("success", False):
        return False

    # Check that expected files appear in successful_uploads
    successful_uploads = result.json_data.get("successful_uploads", [])
    uploaded_filenames = [
        upload.get("target_filename", "") for upload in successful_uploads
    ]

    for expected_file in expected_files:
        file_name = Path(expected_file).name
        if file_name not in uploaded_filenames:
            return False
else:
    # Fall back to stdout string matching
    # ... existing logic ...
```

### 7. Added _parse_json_output Method
**Location:** Lines 493-530

New private method to parse JSON from stdout:

```python
def _parse_json_output(self, stdout: str) -> Optional[Dict]:
    """Parse JSON output from script stdout."""
    import json

    if not stdout or not stdout.strip():
        return None

    try:
        # Try to parse the entire stdout as JSON
        parsed = json.loads(stdout)
        return parsed
    except json.JSONDecodeError:
        # Try to find JSON in the output (in case there's other text)
        try:
            start_idx = stdout.find("{")
            end_idx = stdout.rfind("}")
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                json_str = stdout[start_idx : end_idx + 1]
                parsed = json.loads(json_str)
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass

    return None
```

### 8. Added _extract_data_from_json Method
**Location:** Lines 532-558

New private method to extract files and URLs from JSON:

```python
def _extract_data_from_json(self, json_data: Dict) -> tuple[List[str], List[str]]:
    """Extract uploaded files and URLs from JSON data."""
    uploaded_files = []
    upload_urls = []

    if json_data.get("success", False):
        successful_uploads = json_data.get("successful_uploads", [])
        for upload in successful_uploads:
            if isinstance(upload, dict):
                target_filename = upload.get("target_filename", "")
                if target_filename:
                    uploaded_files.append(target_filename)

                download_url = upload.get("download_url", "")
                if download_url:
                    upload_urls.append(download_url)

    return uploaded_files, upload_urls
```

### 9. Added validate_json_result Function
**Location:** Lines 651-721

New module-level helper function for JSON validation:

```python
def validate_json_result(
    json_data: Dict,
    expected_success: bool,
    expected_files: Optional[List[str]] = None,
) -> bool:
    """Validate JSON output from upload script."""
    # Validate success status
    if json_data.get("success", False) != expected_success:
        return False

    # Validate exit code matches success status
    expected_exit_code = 0 if expected_success else 1
    if json_data.get("exit_code", -1) != expected_exit_code:
        return False

    # If expecting success, validate structure
    if expected_success:
        # Check required fields are present
        required_fields = ["package_name", "version", "successful_uploads", "statistics"]
        for field in required_fields:
            if field not in json_data:
                return False

        # Validate statistics consistency
        stats = json_data.get("statistics", {})
        successful_uploads = json_data.get("successful_uploads", [])
        skipped_duplicates = json_data.get("skipped_duplicates", [])

        # Validate new_uploads count
        replaced_count = sum(
            1 for u in successful_uploads
            if u.get("was_duplicate") and u.get("duplicate_action") == "replaced"
        )
        new_uploads_count = len(successful_uploads) - replaced_count
        if stats.get("new_uploads", 0) != new_uploads_count:
            return False

        # Validate expected files if provided
        if expected_files:
            uploaded_filenames = [
                upload.get("target_filename", "")
                for upload in successful_uploads
                if isinstance(upload, dict)
            ]
            for expected_file in expected_files:
                from pathlib import Path
                file_name = Path(expected_file).name
                if file_name not in uploaded_filenames:
                    return False
    else:
        # If expecting failure, check error fields
        if "error" not in json_data or "error_type" not in json_data:
            return False

    return True
```

## Usage Examples

### Basic JSON Mode Usage

```python
# Create executor
executor = ScriptExecutor()

# Create execution with JSON output enabled
execution = executor.create_single_file_execution(
    package_name="my-package",
    version="1.0.0",
    file_path="test.tar.gz",
    use_json_output=True  # Enable JSON mode
)

# Execute
result = executor.execute_upload(execution)

# Access structured data
if result.json_data:
    print(f"Success: {result.json_data['success']}")
    print(f"Package: {result.json_data['package_name']} v{result.json_data['version']}")
    print(f"Uploaded files: {len(result.json_data['successful_uploads'])}")

    for upload in result.json_data['successful_uploads']:
        print(f"  - {upload['source_path']} -> {upload['target_filename']}")
        print(f"    URL: {upload['download_url']}")
        if upload['was_duplicate']:
            print(f"    Action: {upload['duplicate_action']}")
```

### Accessing Duplicate Information

```python
result = executor.execute_upload(execution)

if result.json_data:
    # Check for skipped duplicates
    skipped = result.json_data.get('skipped_duplicates', [])
    for skip in skipped:
        print(f"Skipped: {skip['target_filename']}")
        print(f"  Existing URL: {skip['existing_url']}")
        print(f"  Action: {skip['duplicate_action']}")

    # Check for replaced duplicates
    for upload in result.json_data['successful_uploads']:
        if upload['was_duplicate'] and upload['duplicate_action'] == 'replaced':
            print(f"Replaced: {upload['target_filename']}")
            if upload['existing_url']:
                print(f"  Previous URL: {upload['existing_url']}")
```

### Using validate_json_result

```python
result = executor.execute_upload(execution)

if result.json_data:
    is_valid = validate_json_result(
        result.json_data,
        expected_success=True,
        expected_files=["file1.txt", "file2.txt"]
    )
    assert is_valid, "JSON validation failed"

    # Access statistics
    stats = result.json_data['statistics']
    print(f"Total processed: {stats['total_processed']}")
    print(f"New uploads: {stats['new_uploads']}")
    print(f"Replaced duplicates: {stats['replaced_duplicates']}")
    print(f"Skipped duplicates: {stats['skipped_duplicates']}")
```

### Backward Compatibility

Existing tests continue to work without changes:

```python
# Old style - still works
execution = executor.create_single_file_execution(
    package_name="my-package",
    version="1.0.0",
    file_path="test.tar.gz"
    # use_json_output defaults to False
)

result = executor.execute_upload(execution)
# Uses regex pattern matching as before
assert result.success
```

## JSON Output Structure

The script outputs JSON with the following structure:

### Success Case
```json
{
  "success": true,
  "exit_code": 0,
  "package_name": "my-package",
  "version": "1.0.0",
  "successful_uploads": [
    {
      "source_path": "/path/to/file.tar.gz",
      "target_filename": "file.tar.gz",
      "download_url": "https://gitlab.com/.../file.tar.gz",
      "checksum": null,
      "was_duplicate": false,
      "duplicate_action": null,
      "existing_url": null,
      "error_message": null
    }
  ],
  "skipped_duplicates": [],
  "failed_uploads": [],
  "statistics": {
    "total_processed": 1,
    "new_uploads": 1,
    "replaced_duplicates": 0,
    "skipped_duplicates": 0,
    "failed_uploads": 0
  }
}
```

### Error Case
```json
{
  "success": false,
  "exit_code": 1,
  "error": "Authentication failed",
  "error_type": "AuthenticationError"
}
```

## Field Descriptions

### Upload Result Fields

Each upload result object in `successful_uploads`, `skipped_duplicates`, and `failed_uploads` contains the following fields:

- **`source_path`**: Absolute path to the source file on local filesystem
- **`target_filename`**: Filename in the GitLab package registry (may include subdirectory paths)
- **`download_url`**: Full URL to download the file from GitLab (null for failed uploads)
- **`checksum`**: SHA256 checksum (currently always null, reserved for future use)
- **`was_duplicate`**: Boolean indicating if file was detected as duplicate
- **`duplicate_action`**: Action taken for duplicates ("skipped", "replaced", or null)
- **`existing_url`**: URL of existing file if duplicate was found (null otherwise)
- **`error_message`**: Error description for failed uploads (null for successful uploads)

### Statistics Fields

The `statistics` object contains the following fields:

- **`total_processed`**: Total number of files processed
- **`new_uploads`**: Number of new files uploaded successfully
- **`replaced_duplicates`**: Number of duplicates that were replaced
- **`skipped_duplicates`**: Number of duplicates that were skipped
- **`failed_uploads`**: Number of files that failed to upload

## Benefits

1. **Structured Data Access**: Tests can access structured data directly without regex parsing
2. **Backward Compatible**: Existing tests continue to work without modifications
3. **Easier Validation**: JSON structure makes it easier to validate specific fields
4. **Better Error Handling**: Error information is structured and typed
5. **Future-Proof**: Easy to extend with additional fields without breaking tests

## Testing

All changes have been validated:
- ✅ Python syntax check passed
- ✅ Ruff linter passed
- ✅ Backward compatibility maintained
- ✅ Type hints added for new methods
- ✅ Documentation added for all new features
