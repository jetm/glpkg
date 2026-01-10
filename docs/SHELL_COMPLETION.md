# Shell Completion Setup

glpkg supports shell completion for bash and zsh, providing tab-completion for commands, options, and arguments.

## Overview

- Completion powered by [argcomplete](https://github.com/kislyuk/argcomplete)
- Supports bash and zsh shells
- Provides tab-completion for subcommands, flags, and option values

## Installation

### Automatic Installation (Recommended)

Use the built-in completion installer:

```bash
# For Bash
glpkg --install-completion bash

# For Zsh
glpkg --install-completion zsh
```

Follow the activation instructions printed after installation.

### Manual Installation

#### Bash

1. Generate the completion script:

   ```bash
   glpkg --install-completion bash
   ```

   Or manually create the file at `~/.bash_completion.d/glpkg`

2. Add to your `~/.bashrc`:

   ```bash
   source ~/.bash_completion.d/glpkg
   ```

3. Reload your shell:

   ```bash
   source ~/.bashrc
   ```

   Or restart your terminal.

#### Zsh

1. Generate the completion script:

   ```bash
   glpkg --install-completion zsh
   ```

   Or manually create the file at `~/.zsh/completion/_glpkg`

2. Add to your `~/.zshrc` (before `compinit`):

   ```zsh
   fpath=(~/.zsh/completion $fpath)
   ```

3. Reload completions:

   ```zsh
   autoload -Uz compinit && compinit
   ```

   Or restart your terminal.

## Usage

Once installed, use Tab to complete commands and options:

```bash
# Show available commands
glpkg <Tab>

# Show options for upload command
glpkg upload --<Tab>

# Complete long option names
glpkg upload --pack<Tab>  # completes to --package-name
```

## Verification

Test that completion is working:

1. Open a new terminal or reload your shell
2. Type `glpkg ` and press Tab twice
3. You should see available commands and options

If completion works, you'll see suggestions like:

```
upload        --help        --verbose     --json-output
```

## Troubleshooting

### Completion Not Working

1. **Verify installation**: Check that the completion script exists

   ```bash
   # Bash
   cat ~/.bash_completion.d/glpkg

   # Zsh
   cat ~/.zsh/completion/_glpkg
   ```

2. **Verify shell configuration**: Ensure your shell config sources the completion

   ```bash
   # Check bashrc
   grep -n "bash_completion" ~/.bashrc

   # Check zshrc
   grep -n "completion" ~/.zshrc
   ```

3. **Restart shell**: Close and reopen your terminal, or source your config file

### Permission Denied

If you encounter permission errors during installation:

```bash
# Create directory with appropriate permissions
mkdir -p ~/.bash_completion.d
chmod 755 ~/.bash_completion.d

# Or for zsh
mkdir -p ~/.zsh/completion
chmod 755 ~/.zsh/completion
```

Then re-run the installation command.

### Zsh Completion Not Loading

Ensure `fpath` is updated before `compinit` in your `.zshrc`:

```zsh
# This must come BEFORE compinit
fpath=(~/.zsh/completion $fpath)

# Then initialize completions
autoload -Uz compinit && compinit
```

If you've modified your `.zshrc`, rebuild the completion cache:

```zsh
rm -f ~/.zcompdump
compinit
```

## Technical Details

- **Implementation**: `src/glpkg/cli/completion.py`
- **Bash completion path**: `~/.bash_completion.d/glpkg`
- **Zsh completion path**: `~/.zsh/completion/_glpkg`
- **Library**: argcomplete for completion generation
