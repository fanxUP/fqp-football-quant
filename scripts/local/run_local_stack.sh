#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python ../../scripts/local/check_local_environment.py || python3 ../../scripts/local/check_local_environment.py
mkdir -p ../../data/postgres ../../data/redis
# Pull latest unpinned images through Docker Desktop, then build local services.
docker compose -f docker-compose.local.yml pull || true
docker compose -f docker-compose.local.yml up --build
