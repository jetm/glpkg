"""
Pytest performance reporting plugin for parallel test execution.

This module provides pytest hooks for performance reporting and optimization
tracking across parallel test workers.
"""

import pytest

from .utils.performance import get_test_performance_summary


def pytest_sessionfinish(session, exitstatus):
    """
    Called after whole test run finished, right before returning the exit status.

    This hook provides performance summary for the entire test session,
    including parallel execution statistics and individual test timings.
    """
    if hasattr(session.config, "workerinput"):
        # This is a worker process in pytest-xdist, don't print summary
        return

    # Only print summary in main process
    try:
        summary = get_test_performance_summary()

        print("\n" + "=" * 60)
        print("PERFORMANCE SUMMARY")
        print("=" * 60)

        exec_summary = summary["execution_summary"]
        print(f"Total tests executed: {exec_summary['total_tests']}")
        print(f"Total execution time: {exec_summary['total_duration']:.2f}s")
        print(f"Average test duration: {exec_summary['average_test_duration']:.2f}s")
        print(f"Parallel workers used: {exec_summary['worker_count']}")

        # Add timing distribution
        if exec_summary["total_tests"] > 0:
            from .utils.performance import get_performance_tracker

            tracker = get_performance_tracker()

            # Get all test durations
            test_durations = []
            for test_id, metrics in tracker._metrics.items():
                if "duration" in metrics and metrics["duration"] > 0:
                    test_durations.append(metrics["duration"])

            if test_durations:
                test_durations.sort(reverse=True)
                min_duration = min(test_durations)
                max_duration = max(test_durations)
                median_duration = test_durations[len(test_durations) // 2]

                # Count tests by duration ranges
                very_slow = sum(1 for d in test_durations if d >= 60)
                slow = sum(1 for d in test_durations if 30 <= d < 60)
                medium = sum(1 for d in test_durations if 10 <= d < 30)
                fast = sum(1 for d in test_durations if d < 10)

                print("\nTiming Statistics:")
                print(f"Min duration: {min_duration:.2f}s")
                print(f"Max duration: {max_duration:.2f}s")
                print(f"Median duration: {median_duration:.2f}s")
                print("\nTiming Distribution:")
                if very_slow > 0:
                    print(f"  Very slow (≥60s): {very_slow} tests")
                if slow > 0:
                    print(f"  Slow (30-60s): {slow} tests")
                if medium > 0:
                    print(f"  Medium (10-30s): {medium} tests")
                if fast > 0:
                    print(f"  Fast (<10s): {fast} tests")

        print("\nAPI Efficiency:")
        print(f"Total API calls: {exec_summary['total_api_calls']}")
        print(
            f"Average API calls per test: {summary['efficiency_metrics']['avg_api_calls_per_test']:.1f}"
        )

        print("\nArtifact Management:")
        print(f"Total artifacts created: {exec_summary['total_artifacts_created']}")
        print(
            f"Average artifacts per test: {summary['efficiency_metrics']['avg_artifacts_per_test']:.1f}"
        )

        cache_perf = summary["cache_performance"]
        if cache_perf["cache_hits"] + cache_perf["cache_misses"] > 0:
            print("\nData Generation Cache:")
            print(f"Cache hit ratio: {cache_perf['hit_ratio']:.2%}")
            print(f"Cache hits: {cache_perf['cache_hits']}")
            print(f"Cache misses: {cache_perf['cache_misses']}")

        # Worker-specific stats if available
        if exec_summary["worker_count"] > 1:
            print("\nWorker Distribution:")
            for worker_id, stats in exec_summary["worker_stats"].items():
                print(
                    f"  {worker_id}: {stats['tests_run']} tests, {stats['total_duration']:.1f}s"
                )

        # Show top 10 slowest tests
        if exec_summary["total_tests"] > 0:
            from .utils.performance import get_performance_tracker

            tracker = get_performance_tracker()

            # Collect test data with durations
            test_data = []
            for test_id, metrics in tracker._metrics.items():
                if metrics.duration is not None and metrics.duration > 0:
                    test_data.append(
                        {
                            "name": test_id,
                            "duration": metrics.duration,
                            "api_calls": metrics.api_calls,
                            "worker": metrics.worker_id,
                        }
                    )

            if test_data:
                # Sort by duration (slowest first)
                test_data.sort(key=lambda x: x["duration"], reverse=True)

                # Show top 10 slowest tests
                print("\n" + "=" * 60)
                print("SLOWEST TESTS (Top 10)")
                print("=" * 60)

                for i, test in enumerate(test_data[:10], 1):
                    duration_str = _format_duration(test["duration"])
                    print(f"{i:2d}. {test['name']}")
                    print(
                        f"    Duration: {duration_str}, API calls: {test['api_calls']}, Worker: {test['worker']}"
                    )

        print("=" * 60)

    except Exception as e:
        print(f"\nWarning: Could not generate performance summary: {e}")


def _format_duration(seconds: float) -> str:
    """
    Format duration in seconds to human-readable format.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted duration string (e.g., "2m 30s", "45s", "1h 5m")
    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


def pytest_configure(config):
    """
    Called after command line options have been parsed and all plugins loaded.

    This hook sets up performance tracking configuration based on pytest-xdist settings.
    """
    # Check if we're running with pytest-xdist
    if hasattr(config, "workerinput"):
        # This is a worker process
        worker_id = config.workerinput.get("workerid", "unknown")

        # Set worker ID on current thread for tracking
        import threading

        threading.current_thread().worker_id = worker_id

        # Optimize for parallel execution
        from .utils.performance import optimize_for_parallel_execution

        # Estimate worker count (not perfect but reasonable)
        worker_count = config.getoption("numprocesses", None)
        if worker_count == "auto":
            import os

            worker_count = os.cpu_count() or 1
        elif worker_count is None:
            worker_count = 1

        optimize_for_parallel_execution(int(worker_count))


@pytest.fixture(scope="session", autouse=True)
def performance_session_setup():
    """
    Session-wide fixture to set up performance tracking.

    This fixture runs once per test session and initializes
    performance tracking for the entire test run.
    """
    # Initialize performance tracking
    from .utils.performance import get_performance_tracker

    get_performance_tracker()  # Initialize performance tracking

    yield

    # Session cleanup happens in pytest_sessionfinish hook
