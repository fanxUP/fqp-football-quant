"""Bounded EPL reference refresh; --resume reuses a pinned payload without HTTP.

Default: prepare only. --apply requires explicit loopback DATABASE_URL and uses
the existing shared PostgreSQL importer. The copied historical SQLite stays
unchanged; temporary adapter databases are deleted before publication.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import uuid
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg2
from psycopg2.extensions import parse_dsn

from scripts.league_reference_storage import import_season
from scripts.sources.titan007 import cli, store
from scripts.sources.titan007.client import (
    AcquisitionStopped,
    TitanClient,
    acquisition_session,
)
from scripts.titan007_data import _write_json, cache_lock, data_directory
from scripts.titan007_import import (
    CONFIG_PATH,
    CONTRACT,
    content_hash,
    load_season,
    season_content_hash,
)

MIN_REFRESH_INTERVAL = timedelta(hours=6)
MAX_SOURCE_AGE = timedelta(hours=24)
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024
MAX_RETAINED_PAYLOAD_BYTES = 64 * 1024 * 1024
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def now_utc() -> datetime:
    return datetime.now(UTC)


def _local_database() -> str:
    dsn = os.environ.get("DATABASE_URL", "")
    try:
        params = parse_dsn(dsn) if dsn else {}
    except psycopg2.Error:
        params = {}
    if (
        params.get("host") not in LOOPBACK
        or "service" in params
        or ("hostaddr" in params and params["hostaddr"] not in {"127.0.0.1", "::1"})
    ):
        raise ValueError("发布需要显式本机DATABASE_URL，不使用默认库、service或远程地址")
    return dsn


def publish_payload(data: dict, dsn: str) -> dict:
    params = parse_dsn(dsn)
    # Explicit numeric hostaddr prevents PGHOSTADDR or a localhost DNS override
    # from redirecting a validated loopback DSN to another machine.
    params["hostaddr"] = "::1" if params["host"] == "::1" else "127.0.0.1"
    params["connect_timeout"] = "5"
    with closing(psycopg2.connect(**params)) as conn, conn:
        report = import_season(conn, data)
        if report["unmapped_teams"] or not report["fixture_coverage_complete"]:
            raise ValueError("身份映射不完整，整个参考批次已回滚")
    return report


def _validated(data: dict, config: dict) -> None:
    if data.get("contract") != CONTRACT or data.get("config") != config:
        raise ValueError("冻结数据的契约或赛季配置不匹配")
    if data.get("content_sha256") != season_content_hash(data):
        raise ValueError("冻结数据内容摘要不匹配")
    quality = data["report"]
    if (
        not quality["fixture_coverage_complete"]
        or quality["rejected_fixtures"]
        or not all(quality["scope_complete"].get(scope) for scope in ("all", "home", "away"))
    ):
        raise ValueError("赛程、球队或总主客积分榜不完整，保留现行批次")
    for key in ("source_as_of", "source_acquired_at"):
        at = datetime.fromisoformat(data[key]) if data.get(key) else None
        if (
            at is None
            or at.tzinfo is None
            or not -timedelta(minutes=5) <= now_utc() - at <= MAX_SOURCE_AGE
        ):
            raise ValueError("来源截止或采集时间缺失、过期或在未来，保留现行批次")


def _read_json(path: Path) -> dict:
    if path.is_symlink() or path.stat().st_size > MAX_PAYLOAD_BYTES:
        raise ValueError("运行文件不是范围内的常规小型文件")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("运行文件格式无效")
    return value


def _check_interval(directory: Path) -> None:
    state = directory / "refresh-state.json"
    if state.exists():
        last = datetime.fromisoformat(_read_json(state)["last_attempt_at"])
        if last.tzinfo is None or last > now_utc():
            raise ValueError("更新间隔记录损坏，请检查来源状态")
        if now_utc() - last < MIN_REFRESH_INTERVAL:
            raise AcquisitionStopped(
                f"两次更新至少间隔6小时，可在{(last + MIN_REFRESH_INTERVAL).isoformat()}后再试；已冻结数据可resume发布"
            )


def _prepare(directory: Path, config: dict, result: dict, max_requests: int) -> dict:
    _check_interval(directory)
    runs = directory / "runs"
    if (
        sum(path.stat().st_size for path in runs.glob("refresh-*.payload.json")) + MAX_PAYLOAD_BYTES
        > MAX_RETAINED_PAYLOAD_BYTES
    ):
        raise ValueError("冻结数据接近64MiB留存上限，请核实并归档旧运行后再采集")
    _write_json(directory / "refresh-state.json", {"last_attempt_at": now_utc().isoformat()})
    budget = None
    try:
        with acquisition_session(directory, max_requests) as budget:
            # Reuse the existing parser/storage adapter, with no 6GB copy and
            # no optional scorer/detail calls capable of failing this product.
            with tempfile.TemporaryDirectory(prefix="fqp-titan007-refresh-") as scratch:
                with store.connection_scope():
                    conn = store.connect(str(Path(scratch) / "titan007.db"))
                    cli._sync_league(
                        TitanClient(delay=3, jitter=2),
                        conn,
                        config["source_league_id"],
                        config["season"],
                        include_scorers=False,
                    )
                data = load_season(scratch, config=config)
        if budget.failures or budget.operation_failures:
            raise ValueError("采集含失败请求或解析失败，未准备发布")
        data["source_acquired_at"] = now_utc().isoformat()
        result.update(
            source_as_of=data["source_as_of"],
            source_acquired_at=data["source_acquired_at"],
            quality=data["report"],
        )
        _validated(data, config)
        payload_path = runs / f"refresh-{result['run_id']}.payload.json"
        if (
            len((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode())
            > MAX_PAYLOAD_BYTES
        ):
            raise ValueError("本批冻结数据超出有界赛季大小")
        _write_json(payload_path, data)
        result.update(
            payload_sha256=content_hash(data),
            source_content_sha256=data["content_sha256"],
            source_as_of=data["source_as_of"],
            source_acquired_at=data["source_acquired_at"],
            quality=data["report"],
        )
        return data
    finally:
        if budget is not None:
            result.update(
                requests=budget.requests,
                requests_this_attempt=budget.requests,
                failures=budget.failures,
                operation_failures=budget.operation_failures,
                http=budget.events,
            )


def refresh_league(data_dir=None, *, config=None, apply=False, resume=None, max_requests=8) -> dict:
    directory = data_directory(data_dir)
    result = {
        "version": "fqp.titan007-refresh/v1",
        "run_id": uuid.uuid4().hex,
        "started_at": now_utc().isoformat(),
        "source_id": "titan007",
        "status": "failed",
        "exit_code": 1,
        "business_database_imported": False,
        "requests": 0,
        "requests_this_attempt": 0,
        "pid": os.getpid(),
    }
    try:
        config = dict(config or json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        if config["source_league_id"] != 36 or config["season"] != "2026-2027":
            raise ValueError("本轮只启用已核实的英超2026-2027配置")
        if not 1 <= max_requests <= 8:
            raise ValueError("更新请求预算必须为1–8")
        dsn = _local_database() if apply else None
        if resume is not None and re.fullmatch(r"[a-f0-9]{32}", resume) is None:
            raise ValueError("resume需要原运行的32位run_id")
        with cache_lock(directory):
            directory.mkdir(parents=True, exist_ok=True)
            runs = directory / "runs"
            if runs.is_symlink():
                raise ValueError("运行目录不能是符号链接")
            runs.mkdir(exist_ok=True)
            try:
                if resume:
                    saved = _read_json(runs / f"refresh-{resume}.json")
                    if saved.get("version") != result["version"] or saved.get("run_id") != resume:
                        raise ValueError("原运行记录不匹配")
                    data = _read_json(runs / f"refresh-{resume}.payload.json")
                    if content_hash(data) != saved.get("payload_sha256"):
                        raise ValueError("原运行的冻结数据摘要不匹配")
                    _validated(data, config)
                    result = {
                        **saved,
                        "requests_this_attempt": 0,
                        "resumed_at": now_utc().isoformat(),
                    }
                    result.pop("reason", None)
                    result.pop("error_type", None)
                else:
                    result["status"] = "collecting"
                    _write_json(runs / f"refresh-{result['run_id']}.json", result)
                    data = _prepare(directory, config, result, max_requests)
                result.update(status="ready", exit_code=0)
                # Write the complete payload receipt before any DB operation.
                _write_json(runs / f"refresh-{result['run_id']}.json", result)
                if apply:
                    try:
                        assert dsn is not None
                        report = publish_payload(data, dsn)
                        result.update(
                            status=report["status"],
                            publication=report,
                            business_database_imported=True,
                        )
                    except Exception as exc:
                        result.update(
                            status="publish_failed",
                            exit_code=1,
                            error_type=type(exc).__name__,
                            reason="数据库发布未完成；已冻结数据保留，可用同一run_id重试",
                        )
            except AcquisitionStopped as exc:
                result.update(status="blocked", exit_code=3, reason=str(exc))
            except Exception as exc:
                result.update(
                    status="failed",
                    exit_code=1,
                    error_type=type(exc).__name__,
                    reason=str(exc)[:400],
                )
            finally:
                result["finished_at"] = now_utc().isoformat()
                _write_json(runs / f"refresh-{result['run_id']}.json", result)
    except Exception as exc:
        result.update(
            status="failed",
            exit_code=1,
            error_type=type(exc).__name__,
            reason="更新参数、显式本机数据库或缓存锁核验失败",
        )
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--max-requests", type=int, default=8)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--resume", help="原run_id；不联网，仅验证/发布已冻结数据")
    args = parser.parse_args(argv)
    result = refresh_league(
        args.data_dir,
        config=json.loads(args.config.read_text(encoding="utf-8")),
        apply=args.apply,
        resume=args.resume,
        max_requests=args.max_requests,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
