#!/usr/bin/env bash
set -euo pipefail

# Local setup helper for macOS. Python is pinned to the project's 3.14 runtime;
# other tools use the currently installed Homebrew versions.

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew not found. Install Homebrew first from the official website, then rerun this script."
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  brew install git
fi

if ! command -v node >/dev/null 2>&1; then
  brew install node
fi

if ! command -v python3.14 >/dev/null 2>&1; then
  brew install python@3.14
fi

if ! command -v codex >/dev/null 2>&1; then
  echo "Codex CLI not found. Install the current Codex CLI according to the official OpenAI Codex documentation."
fi

python3.14 scripts/local/check_local_environment.py
