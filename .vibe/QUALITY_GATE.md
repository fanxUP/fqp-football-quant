# P111-01 本地质量门禁

- 固定样本：`.venv/bin/python -m pytest -q tests/test_scripts/test_dynamic_team_challenger.py tests/test_scripts/test_training_manifest.py tests/test_scripts/test_mle_trainer.py`
- Lint/格式/差异：`.venv/bin/ruff check scripts/dynamic_team_challenger.py tests/test_scripts/test_dynamic_team_challenger.py && .venv/bin/ruff format --check scripts/dynamic_team_challenger.py tests/test_scripts/test_dynamic_team_challenger.py && git diff --check`
- 类型：`.venv/bin/mypy scripts/dynamic_team_challenger.py --explicit-package-bases`
- V4 scope/budget 和状态门禁。
- 不运行生产、供应商或部署命令。完整 A111 还需要接入共同 manifest/artifact/run/evaluation 与影子观察。
