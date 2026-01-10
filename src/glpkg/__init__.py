"""glpkg - GitLab Generic Package Upload Tool."""

__version__ = "0.1.0"

# Export key models and exceptions for convenience
from .duplicate_detector import DuplicateDetector
from .models import (
    DuplicatePolicy,
    FileFingerprint,
    RemoteFile,
    UploadResult,
    ProjectInfo,
    ProjectResolutionResult,
    GitRemoteInfo,
    UploadConfig,
    UploadContext,
    GitLabUploadError,
    AuthenticationError,
    ConfigurationError,
    ProjectResolutionError,
    FileValidationError,
    NetworkError,
    ChecksumValidationError,
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
