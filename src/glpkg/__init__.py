"""glpkg - GitLab Generic Package Upload Tool."""

__version__ = "0.1.0"

# Export key models and exceptions for convenience
from .duplicate_detector import DuplicateDetector
from .models import (
    AuthenticationError,
    ChecksumValidationError,
    ConfigurationError,
    DuplicatePolicy,
    FileFingerprint,
    FileValidationError,
    GitLabUploadError,
    GitRemoteInfo,
    NetworkError,
    ProjectInfo,
    ProjectResolutionError,
    ProjectResolutionResult,
    RemoteFile,
    UploadConfig,
    UploadContext,
    UploadResult,
)

__all__ = [
    "__version__",
    "DuplicateDetector",
    "DuplicatePolicy",
    "FileFingerprint",
    "RemoteFile",
    "UploadResult",
    "ProjectInfo",
    "ProjectResolutionResult",
    "GitRemoteInfo",
    "UploadConfig",
    "UploadContext",
    "GitLabUploadError",
    "AuthenticationError",
    "ConfigurationError",
    "ProjectResolutionError",
    "FileValidationError",
    "NetworkError",
    "ChecksumValidationError",
]
