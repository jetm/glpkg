"""Unit tests for the list subcommand.

Tests cover URL parsing, input validation, package fetching,
output formatting, and argument registration.
"""

from __future__ import annotations

import argparse
import json
from unittest.mock import MagicMock

import pytest

from glpkg.cli.list_cmd import (
    PackageFileInfo,
    PackageListResult,
    PackageVersionSummary,
    fetch_package_files_by_id,
    fetch_package_files_by_name,
    parse_package_url,
    register_list_command,
    validate_list_flags,
)
from glpkg.formatters import OutputFormatter
from glpkg.models import ConfigurationError, ProjectResolutionError, UploadConfig

# --- URL Parsing ---


class TestParsePackageUrl:
    """Tests for parse_package_url()."""

    @pytest.mark.unit
    def test_valid_gitlab_com_url(self):
        gitlab_url, project_path, package_id = parse_package_url(
            "https://gitlab.com/group/project/-/packages/12345"
        )
        assert gitlab_url == "https://gitlab.com"
        assert project_path == "group/project"
        assert package_id == 12345

    @pytest.mark.unit
    def test_valid_nested_group_url(self):
        gitlab_url, project_path, package_id = parse_package_url(
            "https://gitlab.com/LinaroLtd/iotil/meta-onelab/-/packages/50863208"
        )
        assert gitlab_url == "https://gitlab.com"
        assert project_path == "LinaroLtd/iotil/meta-onelab"
        assert package_id == 50863208

    @pytest.mark.unit
    def test_valid_custom_instance_url(self):
        gitlab_url, project_path, package_id = parse_package_url(
            "https://gitlab.example.com/ns/proj/-/packages/999"
        )
        assert gitlab_url == "https://gitlab.example.com"
        assert project_path == "ns/proj"
        assert package_id == 999

    @pytest.mark.unit
    def test_valid_http_url(self):
        gitlab_url, project_path, package_id = parse_package_url(
            "http://gitlab.local/group/project/-/packages/1"
        )
        assert gitlab_url == "https://gitlab.local"
        assert project_path == "group/project"
        assert package_id == 1

    @pytest.mark.unit
    def test_url_with_trailing_whitespace(self):
        gitlab_url, project_path, package_id = parse_package_url(
            "  https://gitlab.com/g/p/-/packages/42  "
        )
        assert package_id == 42

    @pytest.mark.unit
    def test_invalid_url_no_packages(self):
        with pytest.raises(ConfigurationError, match="Invalid GitLab package URL"):
            parse_package_url("https://gitlab.com/group/project")

    @pytest.mark.unit
    def test_invalid_url_wrong_format(self):
        with pytest.raises(ConfigurationError, match="Invalid GitLab package URL"):
            parse_package_url("not-a-url")

    @pytest.mark.unit
    def test_invalid_url_non_numeric_id(self):
        with pytest.raises(ConfigurationError, match="Invalid GitLab package URL"):
            parse_package_url("https://gitlab.com/g/p/-/packages/abc")

    @pytest.mark.unit
    def test_invalid_url_empty(self):
        with pytest.raises(ConfigurationError, match="Invalid GitLab package URL"):
            parse_package_url("")


# --- Input Validation ---


class TestValidateListFlags:
    """Tests for validate_list_flags()."""

    def _make_args(self, **kwargs):
        args = argparse.Namespace()
        args.url = kwargs.get("url", None)
        args.package_name = kwargs.get("package_name", None)
        return args

    @pytest.mark.unit
    def test_url_mode_valid(self):
        args = self._make_args(url="https://gitlab.com/g/p/-/packages/1")
        validate_list_flags(args)  # Should not raise

    @pytest.mark.unit
    def test_name_mode_valid(self):
        args = self._make_args(package_name="my-package")
        validate_list_flags(args)  # Should not raise

    @pytest.mark.unit
    def test_both_modes_error(self):
        args = self._make_args(
            url="https://gitlab.com/g/p/-/packages/1",
            package_name="my-package",
        )
        with pytest.raises(SystemExit) as exc_info:
            validate_list_flags(args)
        assert exc_info.value.code == 3

    @pytest.mark.unit
    def test_neither_mode_error(self):
        args = self._make_args()
        with pytest.raises(SystemExit) as exc_info:
            validate_list_flags(args)
        assert exc_info.value.code == 3


# --- Package Fetching ---


def _make_mock_package_file(file_name, size=1024, sha256="abc123", created_at="2025-01-15"):
    """Create a mock package file object."""
    pf = MagicMock()
    pf.file_name = file_name
    pf.size = size
    pf.file_sha256 = sha256
    pf.created_at = created_at
    return pf


def _make_mock_package(name="test-pkg", version="1.0.0", package_id=100, created_at="2025-01-15"):
    """Create a mock package object."""
    pkg = MagicMock()
    pkg.name = name
    pkg.version = version
    pkg.id = package_id
    pkg.created_at = created_at
    return pkg


class TestFetchPackageFilesById:
    """Tests for fetch_package_files_by_id()."""

    @pytest.mark.unit
    def test_successful_fetch(self):
        gl = MagicMock(spec=["projects", "url"])
        gl.url = "https://gitlab.com"

        project = MagicMock()
        project.id = 42
        gl.projects.get.return_value = project

        package = _make_mock_package()
        project.packages.get.return_value = package

        pf1 = _make_mock_package_file("file1.tar.gz", size=2048, sha256="aaa111")
        pf2 = _make_mock_package_file("file2.bin", size=512, sha256="bbb222")
        package.package_files.list.return_value = [pf1, pf2]

        result = fetch_package_files_by_id(gl, "group/project", 100)

        assert isinstance(result, PackageListResult)
        assert result.package_name == "test-pkg"
        assert result.version == "1.0.0"
        assert result.package_id == 100
        assert len(result.files) == 2
        assert result.files[0].file_name == "file1.tar.gz"
        assert result.files[0].size == 2048
        assert "file1.tar.gz" in result.files[0].download_url

    @pytest.mark.unit
    def test_project_not_found(self):
        gl = MagicMock(spec=["projects", "url"])
        gl.projects.get.side_effect = Exception("404 Project Not Found")

        with pytest.raises(ProjectResolutionError, match="not found or not accessible"):
            fetch_package_files_by_id(gl, "nonexistent/project", 1)

    @pytest.mark.unit
    def test_package_not_found(self):
        gl = MagicMock(spec=["projects", "url"])
        project = MagicMock()
        gl.projects.get.return_value = project
        project.packages.get.side_effect = Exception("404 Package Not Found")

        with pytest.raises(ProjectResolutionError, match="Package ID .* not found"):
            fetch_package_files_by_id(gl, "group/project", 99999)


class TestFetchPackageFilesByName:
    """Tests for fetch_package_files_by_name()."""

    @pytest.mark.unit
    def test_fetch_specific_version(self):
        gl = MagicMock(spec=["projects", "url"])
        project = MagicMock()
        project.id = 42
        gl.projects.get.return_value = project

        pkg = _make_mock_package(name="my-pkg", version="2.0.0", package_id=200)
        project.packages.list.return_value = [pkg]

        pkg_obj = _make_mock_package(name="my-pkg", version="2.0.0", package_id=200)
        project.packages.get.return_value = pkg_obj

        pf = _make_mock_package_file("release.tar.gz")
        pkg_obj.package_files.list.return_value = [pf]

        result = fetch_package_files_by_name(gl, 42, "my-pkg", "2.0.0", "https://gitlab.com")

        assert isinstance(result, PackageListResult)
        assert result.package_name == "my-pkg"
        assert result.version == "2.0.0"
        assert len(result.files) == 1

    @pytest.mark.unit
    def test_fetch_version_summaries(self):
        gl = MagicMock(spec=["projects", "url"])
        project = MagicMock()
        gl.projects.get.return_value = project

        pkg1 = _make_mock_package(version="1.0.0", package_id=100)
        pkg2 = _make_mock_package(version="2.0.0", package_id=200)
        project.packages.list.return_value = [pkg1, pkg2]

        pkg_obj1 = MagicMock()
        pkg_obj1.package_files.list.return_value = [_make_mock_package_file("a.bin")]
        pkg_obj2 = MagicMock()
        pkg_obj2.package_files.list.return_value = [
            _make_mock_package_file("b.bin"),
            _make_mock_package_file("c.bin"),
        ]
        project.packages.get.side_effect = [pkg_obj1, pkg_obj2]

        result = fetch_package_files_by_name(gl, 42, "test-pkg", None, "https://gitlab.com")

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0].file_count == 1
        assert result[1].file_count == 2

    @pytest.mark.unit
    def test_package_name_not_found(self):
        gl = MagicMock(spec=["projects", "url"])
        project = MagicMock()
        gl.projects.get.return_value = project
        project.packages.list.return_value = []

        with pytest.raises(ProjectResolutionError, match="No package named"):
            fetch_package_files_by_name(gl, 42, "nonexistent", "1.0.0", "https://gitlab.com")

    @pytest.mark.unit
    def test_version_not_found(self):
        gl = MagicMock(spec=["projects", "url"])
        project = MagicMock()
        gl.projects.get.return_value = project

        pkg = _make_mock_package(version="1.0.0")
        project.packages.list.return_value = [pkg]

        with pytest.raises(ProjectResolutionError, match="version '9.9.9' not found"):
            fetch_package_files_by_name(gl, 42, "test-pkg", "9.9.9", "https://gitlab.com")


# --- Output Formatting ---


def _make_config(json_output=False, plain_output=False):
    return UploadConfig(
        package_name="",
        version="",
        duplicate_policy=None,  # type: ignore[arg-type]
        retry_count=0,
        verbosity="normal",
        dry_run=False,
        fail_fast=False,
        json_output=json_output,
        plain_output=plain_output,
        gitlab_url="",
        token=None,
    )


def _make_list_result():
    return PackageListResult(
        package_name="my-pkg",
        version="1.0.0",
        package_id=100,
        project_id=42,
        gitlab_url="https://gitlab.com",
        files=[
            PackageFileInfo(
                file_name="app.tar.gz",
                size=13002342,
                sha256="a903393463d3915d7e22219f52740056dfd26cbfe",
                download_url="https://gitlab.com/api/v4/projects/42/packages/generic/my-pkg/1.0.0/app.tar.gz",
                created_at="2025-01-15T10:00:00Z",
            ),
        ],
    )


class TestListOutputFormatting:
    """Tests for list output formatting."""

    @pytest.mark.unit
    def test_json_output_files(self, capsys):
        config = _make_config(json_output=True)
        formatter = OutputFormatter(config)
        result = _make_list_result()

        formatter.format_list_output(result)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["package_name"] == "my-pkg"
        assert data["version"] == "1.0.0"
        assert data["package_id"] == 100
        assert len(data["files"]) == 1
        assert data["files"][0]["file_name"] == "app.tar.gz"
        assert data["files"][0]["size"] == 13002342
        assert "download_url" in data["files"][0]

    @pytest.mark.unit
    def test_json_output_versions(self, capsys):
        config = _make_config(json_output=True)
        formatter = OutputFormatter(config)
        summaries = [
            PackageVersionSummary(
                version="1.0.0", package_id=100, file_count=3, created_at="2025-01-15"
            ),
            PackageVersionSummary(
                version="2.0.0", package_id=200, file_count=1, created_at="2025-02-01"
            ),
        ]

        formatter.format_list_output(summaries)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data["versions"]) == 2
        assert data["versions"][0]["version"] == "1.0.0"
        assert data["versions"][0]["file_count"] == 3

    @pytest.mark.unit
    def test_plain_output_files(self, capsys):
        config = _make_config(plain_output=True)
        formatter = OutputFormatter(config)
        result = _make_list_result()

        formatter.format_list_output(result)

        captured = capsys.readouterr()
        assert "my-pkg" in captured.out
        assert "v1.0.0" in captured.out
        assert "app.tar.gz" in captured.out
        assert "download_url" not in captured.out  # Raw URL, not the key name
        assert "api/v4/projects" in captured.out

    @pytest.mark.unit
    def test_plain_output_versions(self, capsys):
        config = _make_config(plain_output=True)
        formatter = OutputFormatter(config)
        summaries = [
            PackageVersionSummary(
                version="1.0.0", package_id=100, file_count=3, created_at="2025-01-15"
            ),
        ]

        formatter.format_list_output(summaries)

        captured = capsys.readouterr()
        assert "1.0.0" in captured.out
        assert "3 file(s)" in captured.out


# --- Argument Registration ---


class TestRegisterListCommand:
    """Tests for register_list_command()."""

    @pytest.mark.unit
    def test_list_subcommand_registered(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register_list_command(subparsers)

        args = parser.parse_args(["list", "--url", "https://gitlab.com/g/p/-/packages/1"])
        assert args.command == "list"
        assert args.url == "https://gitlab.com/g/p/-/packages/1"

    @pytest.mark.unit
    def test_list_name_mode_args(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register_list_command(subparsers)

        args = parser.parse_args(
            [
                "list",
                "--package-name",
                "my-pkg",
                "--package-version",
                "1.0.0",
                "--project-path",
                "group/project",
            ]
        )
        assert args.command == "list"
        assert args.package_name == "my-pkg"
        assert args.package_version == "1.0.0"
        assert args.project_path == "group/project"

    @pytest.mark.unit
    def test_list_has_func(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register_list_command(subparsers)

        args = parser.parse_args(["list", "--url", "https://gitlab.com/g/p/-/packages/1"])
        assert hasattr(args, "func")


# --- Human-readable size ---


class TestFormatHumanSize:
    """Tests for _format_human_size()."""

    @pytest.mark.unit
    def test_bytes(self):
        config = _make_config(plain_output=True)
        formatter = OutputFormatter(config)
        assert formatter._format_human_size(500) == "500 B"

    @pytest.mark.unit
    def test_kilobytes(self):
        config = _make_config(plain_output=True)
        formatter = OutputFormatter(config)
        assert formatter._format_human_size(2048) == "2.0 KB"

    @pytest.mark.unit
    def test_megabytes(self):
        config = _make_config(plain_output=True)
        formatter = OutputFormatter(config)
        result = formatter._format_human_size(13002342)
        assert "MB" in result

    @pytest.mark.unit
    def test_zero(self):
        config = _make_config(plain_output=True)
        formatter = OutputFormatter(config)
        assert formatter._format_human_size(0) == "0 B"
