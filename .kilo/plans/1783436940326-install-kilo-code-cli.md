# Install Kilo Code CLI

## Goal
Install the Kilo Code CLI (`@kilocode/cli`) globally on this Windows machine so the `kilo` command is available from any terminal.

## Context
- Node v26.3.0 and npm 11.16.0 are already installed.
- `kilo` is not currently on PATH.
- The CLI is the terminal agent that powers this session and supports `kilo`, `kilo run "<task>"`, `kilo auth`, `kilo models`, etc.

## Steps
1. Install the package globally:
   ```
   npm install -g @kilocode/cli
   ```
2. Verify the binary is on PATH and reports a version:
   ```
   kilo --version
   ```
3. (Optional) Confirm Windows global npm bin is on PATH. npm global installs on Windows put the `.cmd` shim under `%APPDATA%\npm`. If `kilo --version` is not found after install, add `%APPDATA%\npm` to the user PATH (or reopen the terminal).

## Post-install (out of scope unless requested)
- Authenticate / add a provider: run `kilo` then use the `/connect` command, or `kilo auth`.
- Configure a model in `~/.config/kilo/kilo.jsonc` (e.g. `anthropic/claude-sonnet-4-20250514`).

## Validation
- `kilo --version` prints a version number (e.g. 7.x.x).
- `kilo --help` lists available commands.

## Risks
- Older CPUs without AVX may crash with "Illegal instruction"; use the `-baseline` build from GitHub Releases instead.
- PATH may need a refresh / terminal restart after global install.
