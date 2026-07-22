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

if ! brew list postgresql@18 >/dev/null 2>&1; then
  brew install postgresql@18
fi

if ! brew list redis >/dev/null 2>&1; then
  brew install redis
fi

brew services start postgresql@18
brew services start redis

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
"$SCRIPT_DIR/init_local_database.sh"

if [[ ! -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  python3.14 -m venv "$PROJECT_ROOT/.venv"
fi
"$PROJECT_ROOT/.venv/bin/python" -m pip install -r "$PROJECT_ROOT/requirements.txt"
npm --prefix "$PROJECT_ROOT/apps/frontend" install

if ! command -v codex >/dev/null 2>&1; then
  echo "Codex CLI not found. Install the current Codex CLI according to the official OpenAI Codex documentation."
fi

"$PROJECT_ROOT/.venv/bin/python" "$PROJECT_ROOT/scripts/local/check_local_environment.py"
