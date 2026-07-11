#!/usr/bin/env bash
set -euo pipefail

# Local latest setup helper for macOS.
# This project does not pin component versions. It uses whatever is installed;
# if a component is missing, this script installs/opens the latest package through Homebrew when possible.

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

if ! command -v python >/dev/null 2>&1 && ! command -v python3 >/dev/null 2>&1; then
  brew install python
fi

if ! command -v codex >/dev/null 2>&1; then
  echo "Codex CLI not found. Install the current Codex CLI according to the official OpenAI Codex documentation."
fi

python3 scripts/local/check_local_environment.py || python scripts/local/check_local_environment.py
