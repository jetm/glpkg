"""
Unit tests for the shell completion module.

Tests cover completion script generation, path resolution,
installation functionality, and integration with the main CLI.

Test Structure:
    - TestGenerateCompletionScript: Tests for script generation
    - TestGetCompletionPath: Tests for completion directory paths
    - TestInstallCompletion: Tests for installation functionality
    - TestMainIntegration: Tests for CLI integration

Running Tests:
    # Run all completion tests
    pytest tests/unit/test_completion.py -v

    # Run specific test class
    pytest tests/unit/test_completion.py::TestGenerateCompletionScript -v
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from glpkg.cli.completion import (
    SUPPORTED_SHELLS,
    COMPLETION_PATHS,
    COMPLETION_FILENAMES,
    generate_completion_script,
    get_completion_path,
    install_completion,
)
from glpkg.cli.main import create_argument_parser, main

# Mark all tests as fast unit tests
pytestmark = [pytest.mark.unit, pytest.mark.fast]


# =============================================================================
# Test Classes
# =============================================================================


class TestGenerateCompletionScript:
    """Tests for generate_completion_script function."""

    @pytest.mark.timeout(60)
    def test_bash_script_generation(self):
        """Test bash completion script generation returns non-empty string."""
        script = generate_completion_script("bash")
        assert isinstance(script, str)
        assert len(script) > 0
        assert "glpkg" in script

    @pytest.mark.timeout(60)
    def test_zsh_script_generation(self):
        """Test zsh completion script generation returns non-empty string."""
        script = generate_completion_script("zsh")
        assert isinstance(script, str)
        assert len(script) > 0
        assert "glpkg" in script

    @pytest.mark.timeout(60)
    def test_unsupported_shell_raises_error(self):
        """Test unsupported shell raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            generate_completion_script("fish")
        assert "Unsupported shell" in str(exc_info.value)
        assert "fish" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_empty_shell_raises_error(self):
        """Test empty shell string raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            generate_completion_script("")
        assert "Unsupported shell" in str(exc_info.value)

    @pytest.mark.timeout(60)
    @patch('glpkg.cli.completion.argcomplete.shellcode')
    def test_shellcode_called_with_correct_args_bash(self, mock_shellcode):
        """Test argcomplete.shellcode is called with correct arguments for bash."""
        mock_shellcode.return_value = "# bash completion script"

        generate_completion_script("bash")

        mock_shellcode.assert_called_once_with(["glpkg"], shell="bash")

    @pytest.mark.timeout(60)
    @patch('glpkg.cli.completion.argcomplete.shellcode')
    def test_shellcode_called_with_correct_args_zsh(self, mock_shellcode):
        """Test argcomplete.shellcode is called with correct arguments for zsh."""
        mock_shellcode.return_value = "# zsh completion script"

        generate_completion_script("zsh")

        mock_shellcode.assert_called_once_with(["glpkg"], shell="zsh")


class TestGetCompletionPath:
    """Tests for get_completion_path function."""

    @pytest.mark.timeout(60)
    def test_bash_returns_correct_path(self):
        """Test bash returns ~/.bash_completion.d/ expanded to absolute path."""
        path = get_completion_path("bash")
        assert isinstance(path, Path)
        assert path.is_absolute()
        assert ".bash_completion.d" in str(path)

    @pytest.mark.timeout(60)
    def test_zsh_returns_correct_path(self):
        """Test zsh returns ~/.zsh/completion/ expanded to absolute path."""
        path = get_completion_path("zsh")
        assert isinstance(path, Path)
        assert path.is_absolute()
        assert ".zsh" in str(path)
        assert "completion" in str(path)

    @pytest.mark.timeout(60)
    def test_unsupported_shell_raises_error(self):
        """Test unsupported shell raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            get_completion_path("fish")
        assert "Unsupported shell" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_paths_are_path_objects(self):
        """Test returned paths are Path objects."""
        for shell in SUPPORTED_SHELLS:
            path = get_completion_path(shell)
            assert isinstance(path, Path)

    @pytest.mark.timeout(60)
    def test_paths_match_defined_constants(self):
        """Test paths match the defined COMPLETION_PATHS constants."""
        for shell in SUPPORTED_SHELLS:
            path = get_completion_path(shell)
            expected = Path(COMPLETION_PATHS[shell]).expanduser()
            assert path == expected


class TestInstallCompletion:
    """Tests for install_completion function."""

    @pytest.mark.timeout(60)
    @patch('glpkg.cli.completion.Path.chmod')
    @patch('glpkg.cli.completion.Path.write_text')
    @patch('glpkg.cli.completion.Path.mkdir')
    @patch('glpkg.cli.completion.generate_completion_script')
    def test_successful_installation_bash(
        self, mock_generate, mock_mkdir, mock_write, mock_chmod, capsys
    ):
        """Test successful installation for bash."""
        mock_generate.return_value = "# bash completion script"

        install_completion("bash")

        mock_generate.assert_called_once_with("bash")
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_write.assert_called_once_with("# bash completion script")
        mock_chmod.assert_called_once_with(0o644)

        captured = capsys.readouterr()
        assert "bash" in captured.out
        assert "installed" in captured.out.lower()

    @pytest.mark.timeout(60)
    @patch('glpkg.cli.completion.Path.chmod')
    @patch('glpkg.cli.completion.Path.write_text')
    @patch('glpkg.cli.completion.Path.mkdir')
    @patch('glpkg.cli.completion.generate_completion_script')
    def test_successful_installation_zsh(
        self, mock_generate, mock_mkdir, mock_write, mock_chmod, capsys
    ):
        """Test successful installation for zsh."""
        mock_generate.return_value = "# zsh completion script"

        install_completion("zsh")

        mock_generate.assert_called_once_with("zsh")
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_write.assert_called_once_with("# zsh completion script")
        mock_chmod.assert_called_once_with(0o644)

        captured = capsys.readouterr()
        assert "zsh" in captured.out
        assert "installed" in captured.out.lower()

    @pytest.mark.timeout(60)
    @patch('glpkg.cli.completion.Path.mkdir')
    @patch('glpkg.cli.completion.generate_completion_script')
    def test_directory_creation_permission_error(self, mock_generate, mock_mkdir):
        """Test permission error during directory creation."""
        mock_generate.return_value = "# script"
        mock_mkdir.side_effect = PermissionError("Access denied")

        with pytest.raises(PermissionError) as exc_info:
            install_completion("bash")
        assert "Permission denied" in str(exc_info.value)

    @pytest.mark.timeout(60)
    @patch('glpkg.cli.completion.Path.mkdir')
    @patch('glpkg.cli.completion.generate_completion_script')
    def test_directory_creation_os_error(self, mock_generate, mock_mkdir):
        """Test OS error during directory creation."""
        mock_generate.return_value = "# script"
        mock_mkdir.side_effect = OSError("Disk error")

        with pytest.raises(OSError) as exc_info:
            install_completion("bash")
        assert "Disk error" in str(exc_info.value)

    @pytest.mark.timeout(60)
    @patch('glpkg.cli.completion.Path.write_text')
    @patch('glpkg.cli.completion.Path.mkdir')
    @patch('glpkg.cli.completion.generate_completion_script')
    def test_file_write_permission_error(self, mock_generate, mock_mkdir, mock_write):
        """Test permission error during file write."""
        mock_generate.return_value = "# script"
        mock_write.side_effect = PermissionError("Cannot write")

        with pytest.raises(PermissionError) as exc_info:
            install_completion("bash")
        assert "Permission denied" in str(exc_info.value)

    @pytest.mark.timeout(60)
    @patch('glpkg.cli.completion.Path.write_text')
    @patch('glpkg.cli.completion.Path.mkdir')
    @patch('glpkg.cli.completion.generate_completion_script')
    def test_file_write_os_error(self, mock_generate, mock_mkdir, mock_write):
        """Test OS error during file write."""
        mock_generate.return_value = "# script"
        mock_write.side_effect = OSError("No space left")

        with pytest.raises(OSError) as exc_info:
            install_completion("bash")
        assert "No space left" in str(exc_info.value)

    @pytest.mark.timeout(60)
    def test_unsupported_shell_raises_error(self):
        """Test unsupported shell raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            install_completion("fish")
        assert "Unsupported shell" in str(exc_info.value)

    @pytest.mark.timeout(60)
    @patch('glpkg.cli.completion.Path.chmod')
    @patch('glpkg.cli.completion.Path.write_text')
    @patch('glpkg.cli.completion.Path.mkdir')
    @patch('glpkg.cli.completion.generate_completion_script')
    def test_activation_instructions_bash(
        self, mock_generate, mock_mkdir, mock_write, mock_chmod, capsys
    ):
        """Test activation instructions are printed for bash."""
        mock_generate.return_value = "# bash script"

        install_completion("bash")

        captured = capsys.readouterr()
        assert "bashrc" in captured.out.lower()
        assert "source" in captured.out

    @pytest.mark.timeout(60)
    @patch('glpkg.cli.completion.Path.chmod')
    @patch('glpkg.cli.completion.Path.write_text')
    @patch('glpkg.cli.completion.Path.mkdir')
    @patch('glpkg.cli.completion.generate_completion_script')
    def test_activation_instructions_zsh(
        self, mock_generate, mock_mkdir, mock_write, mock_chmod, capsys
    ):
        """Test activation instructions are printed for zsh."""
        mock_generate.return_value = "# zsh script"

        install_completion("zsh")

        captured = capsys.readouterr()
        assert "fpath" in captured.out
        assert "compinit" in captured.out


class TestMainIntegration:
    """Tests for integration with main CLI parser."""

    @pytest.mark.timeout(60)
    def test_parser_has_install_completion_argument(self):
        """Test argument parser has --install-completion option."""
        parser = create_argument_parser()
        args = parser.parse_args([])
        assert hasattr(args, 'install_completion')

    @pytest.mark.timeout(60)
    def test_install_completion_bash_parsing(self):
        """Test --install-completion bash argument parsing."""
        parser = create_argument_parser()
        args = parser.parse_args(['--install-completion', 'bash'])
        assert args.install_completion == 'bash'

    @pytest.mark.timeout(60)
    def test_install_completion_zsh_parsing(self):
        """Test --install-completion zsh argument parsing."""
        parser = create_argument_parser()
        args = parser.parse_args(['--install-completion', 'zsh'])
        assert args.install_completion == 'zsh'

    @pytest.mark.timeout(60)
    def test_invalid_shell_shows_error(self):
        """Test invalid shell value shows error."""
        parser = create_argument_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(['--install-completion', 'fish'])

    @pytest.mark.timeout(60)
    @patch('glpkg.cli.completion.install_completion')
    def test_main_calls_install_completion(self, mock_install):
        """Test main function calls install_completion for --install-completion."""
        with pytest.raises(SystemExit) as exc_info:
            main(['--install-completion', 'bash'])

        mock_install.assert_called_once_with('bash')
        assert exc_info.value.code == 0

    @pytest.mark.timeout(60)
    @patch('glpkg.cli.completion.install_completion')
    def test_main_handles_value_error(self, mock_install):
        """Test main function handles ValueError with exit code 3."""
        mock_install.side_effect = ValueError("Unsupported shell")

        with pytest.raises(SystemExit) as exc_info:
            main(['--install-completion', 'bash'])

        assert exc_info.value.code == 3

    @pytest.mark.timeout(60)
    @patch('glpkg.cli.completion.install_completion')
    def test_main_handles_permission_error(self, mock_install):
        """Test main function handles PermissionError with exit code 5."""
        mock_install.side_effect = PermissionError("Access denied")

        with pytest.raises(SystemExit) as exc_info:
            main(['--install-completion', 'bash'])

        assert exc_info.value.code == 5

    @pytest.mark.timeout(60)
    @patch('glpkg.cli.completion.install_completion')
    def test_main_handles_os_error(self, mock_install):
        """Test main function handles OSError with exit code 5."""
        mock_install.side_effect = OSError("Disk error")

        with pytest.raises(SystemExit) as exc_info:
            main(['--install-completion', 'bash'])

        assert exc_info.value.code == 5

    @pytest.mark.timeout(60)
    def test_install_completion_before_subcommand(self):
        """Test --install-completion is processed before subcommand requirement."""
        parser = create_argument_parser()
        # Should not require a subcommand when --install-completion is used
        args = parser.parse_args(['--install-completion', 'bash'])
        assert args.install_completion == 'bash'
        assert args.command is None


class TestConstants:
    """Tests for module constants."""

    @pytest.mark.timeout(60)
    def test_supported_shells_contains_bash(self):
        """Test SUPPORTED_SHELLS contains bash."""
        assert "bash" in SUPPORTED_SHELLS

    @pytest.mark.timeout(60)
    def test_supported_shells_contains_zsh(self):
        """Test SUPPORTED_SHELLS contains zsh."""
        assert "zsh" in SUPPORTED_SHELLS

    @pytest.mark.timeout(60)
    def test_completion_paths_defined_for_all_shells(self):
        """Test COMPLETION_PATHS has entries for all supported shells."""
        for shell in SUPPORTED_SHELLS:
            assert shell in COMPLETION_PATHS

    @pytest.mark.timeout(60)
    def test_completion_filenames_defined_for_all_shells(self):
        """Test COMPLETION_FILENAMES has entries for all supported shells."""
        for shell in SUPPORTED_SHELLS:
            assert shell in COMPLETION_FILENAMES

    @pytest.mark.timeout(60)
    def test_bash_filename_is_glpkg(self):
        """Test bash completion filename is 'glpkg'."""
        assert COMPLETION_FILENAMES["bash"] == "glpkg"

    @pytest.mark.timeout(60)
    def test_zsh_filename_is_underscored(self):
        """Test zsh completion filename follows convention with underscore."""
        assert COMPLETION_FILENAMES["zsh"] == "_glpkg"
