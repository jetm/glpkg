"""
Performance optimization utilities for parallel test execution.

This module provides utilities to maintain the performance optimizations
from the original monolithic test file while supporting parallel execution.
"""

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class TestMetrics:
    """Track test execution metrics for performance monitoring."""

    test_name: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration: Optional[float] = None
    api_calls: int = 0
    artifacts_created: int = 0
    packages_created: int = 0
    worker_id: str = "main"

    def finish(self) -> None:
        """Mark test as finished and calculate duration."""
        self.end_time = datetime.now()
        if self.start_time:
            self.duration = (self.end_time - self.start_time).total_seconds()


class PerformanceTracker:
    """
    Track performance metrics across parallel test execution.

    This class maintains performance statistics similar to the original
    monolithic test file while supporting pytest-xdist parallel execution.
    """

    def __init__(self):
        self._metrics: Dict[str, TestMetrics] = {}
        self._lock = threading.Lock()
        self._worker_stats: Dict[str, Dict[str, Any]] = {}

    def start_test(self, test_name: str, worker_id: str = "main") -> TestMetrics:
        """Start tracking a test execution."""
        with self._lock:
            metrics = TestMetrics(
                test_name=test_name, start_time=datetime.now(), worker_id=worker_id
            )
            self._metrics[test_name] = metrics

            # Initialize worker stats if needed
            if worker_id not in self._worker_stats:
                self._worker_stats[worker_id] = {
                    "tests_run": 0,
                    "total_duration": 0.0,
                    "api_calls": 0,
                    "artifacts_created": 0,
                }

            return metrics

    def finish_test(self, test_name: str) -> Optional[TestMetrics]:
        """Finish tracking a test execution."""
        with self._lock:
            if test_name in self._metrics:
                metrics = self._metrics[test_name]
                metrics.finish()

                # Update worker stats
                worker_stats = self._worker_stats.get(metrics.worker_id, {})
                worker_stats["tests_run"] = worker_stats.get("tests_run", 0) + 1
                worker_stats["total_duration"] = worker_stats.get(
                    "total_duration", 0.0
                ) + (metrics.duration or 0.0)
                worker_stats["api_calls"] = (
                    worker_stats.get("api_calls", 0) + metrics.api_calls
                )
                worker_stats["artifacts_created"] = (
                    worker_stats.get("artifacts_created", 0) + metrics.artifacts_created
                )

                return metrics
        return None

    def record_api_call(self, test_name: str) -> None:
        """Record an API call for performance tracking."""
        with self._lock:
            if test_name in self._metrics:
                self._metrics[test_name].api_calls += 1

    def record_artifact_creation(self, test_name: str, count: int = 1) -> None:
        """Record artifact creation for performance tracking."""
        with self._lock:
            if test_name in self._metrics:
                self._metrics[test_name].artifacts_created += count

    def record_package_creation(self, test_name: str, count: int = 1) -> None:
        """Record package creation for performance tracking."""
        with self._lock:
            if test_name in self._metrics:
                self._metrics[test_name].packages_created += count

    def get_summary(self) -> Dict[str, Any]:
        """Get performance summary across all workers."""
        with self._lock:
            total_tests = sum(
                stats.get("tests_run", 0) for stats in self._worker_stats.values()
            )
            total_duration = sum(
                stats.get("total_duration", 0.0)
                for stats in self._worker_stats.values()
            )
            total_api_calls = sum(
                stats.get("api_calls", 0) for stats in self._worker_stats.values()
            )
            total_artifacts = sum(
                stats.get("artifacts_created", 0)
                for stats in self._worker_stats.values()
            )

            return {
                "total_tests": total_tests,
                "total_duration": total_duration,
                "average_test_duration": total_duration / max(total_tests, 1),
                "total_api_calls": total_api_calls,
                "total_artifacts_created": total_artifacts,
                "worker_count": len(self._worker_stats),
                "worker_stats": dict(self._worker_stats),
            }


# Global performance tracker instance
_performance_tracker = PerformanceTracker()


def get_performance_tracker() -> PerformanceTracker:
    """Get the global performance tracker instance."""
    return _performance_tracker


class EfficientTestDataGenerator:
    """
    Efficient test data generation optimized for parallel execution.

    This class maintains the efficient test data generation patterns from
    the original monolithic test file while supporting parallel workers.
    """

    def __init__(self):
        self._cache: Dict[str, bytes] = {}
        self._lock = threading.Lock()
        self._cache_hits = 0
        self._cache_misses = 0

    def generate_content(
        self, size_bytes: int, pattern: str, cache_key: Optional[str] = None
    ) -> bytes:
        """
        Generate test content efficiently with optional caching.

        Args:
            size_bytes: Size of content to generate
            pattern: Content pattern type
            cache_key: Optional cache key for reusing content

        Returns:
            Generated content bytes
        """
        # Use cache if key provided and content exists
        if cache_key:
            with self._lock:
                if cache_key in self._cache:
                    self._cache_hits += 1
                    cached_content = self._cache[cache_key]
                    if len(cached_content) >= size_bytes:
                        return cached_content[:size_bytes]

        # Generate new content
        content = self._generate_pattern_content(size_bytes, pattern)

        # Cache if key provided and content is reasonable size (< 1MB)
        if cache_key and len(content) < 1024 * 1024:
            with self._lock:
                self._cache[cache_key] = content
                self._cache_misses += 1

        return content

    def _generate_pattern_content(self, size_bytes: int, pattern: str) -> bytes:
        """Generate content based on pattern type."""
        import secrets

        if size_bytes == 0:
            return b""

        if pattern == "text":
            base_text = "Efficient test content for parallel GitLab upload testing. "
            content = (base_text * ((size_bytes // len(base_text)) + 1))[:size_bytes]
            return content.encode("utf-8")
        elif pattern == "binary":
            return secrets.token_bytes(size_bytes)
        elif pattern == "json":
            # Efficient JSON generation
            json_template = '{"test": "data", "index": %d}\n'
            content = ""
            index = 0
            while len(content.encode("utf-8")) < size_bytes:
                line = json_template % index
                content += line
                index += 1
            return content.encode("utf-8")[:size_bytes]
        else:
            # Default pattern
            pattern_bytes = pattern.encode("utf-8")
            content = pattern_bytes * ((size_bytes // len(pattern_bytes)) + 1)
            return content[:size_bytes]

    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache performance statistics."""
        with self._lock:
            return {
                "cache_hits": self._cache_hits,
                "cache_misses": self._cache_misses,
                "cache_size": len(self._cache),
                "hit_ratio": self._cache_hits
                / max(self._cache_hits + self._cache_misses, 1),
            }

    def clear_cache(self) -> None:
        """Clear the content cache."""
        with self._lock:
            self._cache.clear()
            self._cache_hits = 0
            self._cache_misses = 0


# Global efficient data generator instance
_data_generator = EfficientTestDataGenerator()


def get_data_generator() -> EfficientTestDataGenerator:
    """Get the global efficient data generator instance."""
    return _data_generator


def optimize_for_parallel_execution(worker_count: int) -> None:
    """
    Optimize settings for parallel execution.

    Args:
        worker_count: Number of parallel workers
    """
    # Adjust cache sizes based on worker count
    # More workers = smaller individual caches to avoid memory issues
    # TODO: Implement cache size limits based on worker count
    # max_cache_size = max(10, 50 // worker_count)

    # Could implement cache size limits here if needed
    # For now, we rely on the 1MB limit per cached item


def get_test_performance_summary() -> Dict[str, Any]:
    """Get comprehensive performance summary for all tests."""
    tracker_summary = get_performance_tracker().get_summary()
    cache_stats = get_data_generator().get_cache_stats()

    return {
        "execution_summary": tracker_summary,
        "cache_performance": cache_stats,
        "efficiency_metrics": {
            "avg_api_calls_per_test": tracker_summary["total_api_calls"]
            / max(tracker_summary["total_tests"], 1),
            "avg_artifacts_per_test": tracker_summary["total_artifacts_created"]
            / max(tracker_summary["total_tests"], 1),
            "cache_efficiency": cache_stats["hit_ratio"],
        },
    }
