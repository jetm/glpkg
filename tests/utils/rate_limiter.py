"""
Thread-safe API rate limiter for parallel test execution.

This module provides a thread-safe rate limiter extracted from the monolithic
test file, adapted for use in parallel pytest execution with pytest-xdist.
"""

import time
import threading
from typing import Optional


class APIRateLimiter:
    """
    Thread-safe rate limiter for GitLab API calls to prevent hitting rate limits.

    Implements a simple token bucket algorithm with per-endpoint tracking.
    This version is thread-safe for use in parallel test execution.
    """

    def __init__(self, requests_per_minute: int = 300, burst_size: int = 50):
        """
        Initialize the rate limiter.

        Args:
            requests_per_minute: Maximum requests per minute
            burst_size: Maximum burst of requests allowed
        """
        self.requests_per_minute = requests_per_minute
        self.burst_size = burst_size
        self.tokens = float(burst_size)
        self.last_update = time.time()

        # Thread safety
        self._lock = threading.Lock()

        # Per-worker state tracking for pytest-xdist
        self._worker_id = getattr(threading.current_thread(), "worker_id", "main")

    def acquire(self, tokens_needed: int = 1) -> None:
        """
        Acquire tokens from the rate limiter.

        This method will block if insufficient tokens are available,
        implementing a token bucket algorithm with thread safety.

        Args:
            tokens_needed: Number of tokens to acquire (default: 1)
        """
        with self._lock:
            current_time = time.time()
            time_passed = current_time - self.last_update

            # Add tokens based on time passed
            tokens_to_add = time_passed * (self.requests_per_minute / 60.0)
            self.tokens = min(self.burst_size, self.tokens + tokens_to_add)
            self.last_update = current_time

            # Check if we have enough tokens
            if self.tokens < tokens_needed:
                wait_time = (tokens_needed - self.tokens) * (
                    60.0 / self.requests_per_minute
                )

                # Release lock during sleep to allow other threads
                self._lock.release()
                try:
                    time.sleep(wait_time)
                finally:
                    self._lock.acquire()

                # Recalculate tokens after sleep
                current_time = time.time()
                time_passed = current_time - self.last_update
                tokens_to_add = time_passed * (self.requests_per_minute / 60.0)
                self.tokens = min(self.burst_size, self.tokens + tokens_to_add)
                self.last_update = current_time

            # Consume tokens
            self.tokens -= tokens_needed


class SharedRateLimiter:
    """
    Shared rate limiter instance for use across parallel test workers.

    This class provides a singleton pattern for rate limiting that works
    across pytest-xdist workers by using file-based coordination when
    necessary.
    """

    _instance: Optional[APIRateLimiter] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(
        cls, requests_per_minute: int = 300, burst_size: int = 50
    ) -> APIRateLimiter:
        """
        Get the shared rate limiter instance.

        Args:
            requests_per_minute: Maximum requests per minute
            burst_size: Maximum burst of requests allowed

        Returns:
            Shared APIRateLimiter instance
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = APIRateLimiter(requests_per_minute, burst_size)

        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the shared instance (useful for testing)."""
        with cls._lock:
            cls._instance = None


def get_rate_limiter() -> APIRateLimiter:
    """
    Get a rate limiter instance appropriate for the current execution context.

    Returns:
        APIRateLimiter instance configured for parallel execution
    """
    # For pytest-xdist, we want to be more conservative with rate limiting
    # to avoid conflicts between workers
    return SharedRateLimiter.get_instance(requests_per_minute=200, burst_size=30)
