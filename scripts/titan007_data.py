"""FQP entry for the imported football source, its private cache and acquisition.

Run ``python -m scripts.titan007_data --help`` from the project root. The SQLite
file is a raw-source staging area; records retain external IDs and never become
official matches, settlement facts or training labels through this entrypoint.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
import uuid
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data" / "sources" / "titan007"
DEFAULT_TABLES = (
    "matches",
    "league_results",
    "lineups",
    "match_injuries",
    "player_transfers",
    "league_standings",
    "odds",
    "odds_history",
)


def data_directory(value: str | Path | None = None) -> Path:
    return (
        Path(value or os.environ.get("FQP_TITAN007_DATA_DIR") or DEFAULT_DATA_DIR)
        .expanduser()
        .resolve()
    )


@contextmanager
def cache_lock(data_dir: Path):
    """Serialize collection and snapshots across FQP processes on this host."""
    data_dir.parent.mkdir(parents=True, exist_ok=True)
    with (data_dir.parent / f".{data_dir.name}.lock").open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("本机已有此来源的采集或复制任务，请等待结束") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def open_source(data_dir: str | Path | None = None):
    path = data_directory(data_dir) / "titan007.db"
    if not path.is_file():
        raise FileNotFoundError(f"来源缓存不存在：{path}")
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        yield conn
    finally:
        conn.close()


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        if re.fullmatch(r"[a-z][a-z0-9_]*", r[0])
    }


def inspect_cache(data_dir: str | Path | None = None, tables: list[str] | None = None) -> dict:
    directory = data_directory(data_dir)
    with open_source(directory) as conn:
        available = _tables(conn)
        selected = tables if tables is not None else [t for t in DEFAULT_TABLES if t in available]
        if any(t not in available for t in selected):
            raise ValueError("请求了来源缓存中不存在的表")
        if not selected:
            selected = sorted(available)
        counts = {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in selected}
        schema_version = conn.execute("PRAGMA schema_version").fetchone()[0]
    return {
        "source_id": "titan007",
        "storage_role": "raw_source_cache",
        "path": str(directory),
        "database_bytes": (directory / "titan007.db").stat().st_size,
        "checked_at": datetime.now(UTC).isoformat(),
        "sqlite_schema_version": schema_version,
        "tables": counts,
        "available_tables": sorted(available),
        "business_database_imported": False,
    }


def iter_source_rows(data_dir: str | Path | None, table: str, *, batch_size: int = 500):
    """Bounded-memory shared source reader for later canonical import adapters."""
    if not 1 <= batch_size <= 1000:
        raise ValueError("批量大小必须为1–1000")
    with open_source(data_dir) as conn:
        if table not in _tables(conn):
            raise ValueError("请求了来源缓存中不存在的表")
        columns = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        pk = sorted((c for c in columns if c["pk"]), key=lambda c: c["pk"])
        order = ",".join('"' + c["name"].replace('"', '""') + '"' for c in pk) or "rowid"
        cursor = conn.execute(f'SELECT * FROM "{table}" ORDER BY {order}')
        while rows := cursor.fetchmany(batch_size):
            yield from (dict(row) for row in rows)


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _copy_images(source: Path, target: Path) -> int:
    if not source.exists():
        return 0
    count = 0
    for base, dirs, files in os.walk(source):
        current = Path(base)
        if current.is_symlink() or any((current / d).is_symlink() for d in dirs):
            raise ValueError("图片目录含符号链接，请先核实来源")
        destination = target / current.relative_to(source)
        destination.mkdir(parents=True, exist_ok=True)
        for filename in files:
            if filename.startswith("."):
                continue
            image = current / filename
            if image.is_symlink():
                raise ValueError("图片文件含符号链接，请先核实来源")
            shutil.copy2(image, destination / filename)
            count += 1
    return count


def _hash_and_validate(database: Path, progress=None) -> tuple[str, str]:
    """Validate sealed snapshot bytes; external disks need sequential I/O first."""
    if progress:
        progress({"stage": "database_hash"})
    digest = hashlib.sha256()
    # A temporary verification file is removed before returning. It is not a
    # second runtime database. Its bytes are the same bytes being hashed here.
    with tempfile.TemporaryDirectory(prefix="fqp-titan007-verify-") as scratch:
        fast = shutil.disk_usage(scratch).free > database.stat().st_size + 64 * 1024 * 1024
        verification = Path(scratch) / "verification.db" if fast else database
        with database.open("rb") as stream:
            if fast:
                with verification.open("wb") as output:
                    while block := stream.read(8 * 1024 * 1024):
                        digest.update(block)
                        output.write(block)
            else:
                while block := stream.read(8 * 1024 * 1024):
                    digest.update(block)
        if progress:
            progress({"stage": "integrity_check"})
        # Immutable is safe only for this sealed, completed snapshot. We never
        # use it for the original or the live acquisition cache with WAL writers.
        uri = verification.as_uri() + ("?mode=ro&immutable=1" if fast else "?mode=ro")
        with closing(sqlite3.connect(uri, uri=True, timeout=3)) as copied:
            copied.execute("PRAGMA query_only=ON")
            copied.execute("PRAGMA cache_size=-65536")
            check = copied.execute("PRAGMA quick_check(1)").fetchone()[0]
            if check != "ok":
                raise RuntimeError(f"复制后的 SQLite 校验失败：{check}")
    return digest.hexdigest(), "sealed_temporary_copy" if fast else "snapshot_read_only"


def copy_source(
    source_root: str | Path,
    data_dir: str | Path | None = None,
    *,
    include_images: bool = True,
    progress=None,
) -> dict:
    """Copy a consistent committed SQLite snapshot and publish only on success."""
    source = Path(source_root).expanduser().resolve()
    source_db = source / "data" / "titan007.db"
    if not source_db.is_file():
        raise FileNotFoundError(f"原始数据库不存在：{source_db}")
    destination = data_directory(data_dir)
    if (
        destination == source
        or destination.is_relative_to(source)
        or source.is_relative_to(destination)
    ):
        raise ValueError("项目缓存与原始来源目录必须独立")
    with cache_lock(destination):
        if destination.exists():
            raise FileExistsError(f"缓存已存在，不覆盖已有采集数据：{destination}")
        needed = source_db.stat().st_size + (512 * 1024 * 1024 if include_images else 0)
        if shutil.disk_usage(destination.parent).free < needed:
            raise OSError("目标磁盘可用空间不足")
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{destination.name}-import-", dir=destination.parent)
        )
        started = datetime.now(UTC).isoformat()
        deadline = time.monotonic() + 3600
        try:

            def on_pages(status, remaining, total):
                if time.monotonic() > deadline:
                    raise TimeoutError("数据复制超过一小时，原目录和已存在缓存保持不变")
                if progress:
                    progress(
                        {"stage": "database", "remaining_pages": remaining, "total_pages": total}
                    )

            with closing(
                sqlite3.connect(source_db.as_uri() + "?mode=ro", uri=True, timeout=3)
            ) as original:
                original.execute("PRAGMA query_only=ON")
                with closing(sqlite3.connect(temporary / "titan007.db")) as copied:
                    original.backup(copied, pages=4096, progress=on_pages, sleep=0.05)
            database_finished = datetime.now(UTC).isoformat()
            digest, verification_method = _hash_and_validate(temporary / "titan007.db", progress)
            if progress:
                progress({"stage": "images"})
            images = (
                _copy_images(source / "data" / "images", temporary / "images")
                if include_images
                else 0
            )
            config = temporary / "config"
            config.mkdir()
            for filename in (
                "league_categories.json",
                "team_aliases.csv",
                "team_mapping_review.csv",
            ):
                seed = source / "config" / filename
                if seed.is_file():
                    shutil.copy2(seed, config / filename)
            manifest = {
                "version": "fqp.titan007-source-copy/v1",
                "source_root": str(source),
                "copy_started_at": started,
                "database_copy_finished_at": database_finished,
                "copy_finished_at": datetime.now(UTC).isoformat(),
                "database_bytes": (temporary / "titan007.db").stat().st_size,
                "database_sha256": digest,
                "verification_method": verification_method,
                "sqlite_quick_check": "ok",
                "images_copied": images,
                "images_transactional": False,
                "storage_role": "raw_source_cache",
                "business_database_imported": False,
                "notes": "SQLite committed-state copy. Assets are separately copied files. Original timestamps and derived facts do not certify historical prematch availability.",
            }
            _write_json(temporary / "SOURCE_SNAPSHOT.json", manifest)
            temporary.rename(destination)
            return manifest
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)


def _prepare_runtime(data_dir: Path) -> None:
    (data_dir / "config").mkdir(parents=True, exist_ok=True)
    for name in ("league_categories.json", "team_aliases.csv"):
        target = data_dir / "config" / name
        seed = ROOT / "configs" / "titan007" / name
        if not target.exists():
            shutil.copy2(seed, target)


def run_collection(
    arguments: list[str], data_dir: str | Path | None = None, *, max_requests: int = 40
) -> dict:
    from scripts.sources.titan007 import cli, store
    from scripts.sources.titan007.client import AcquisitionStopped, acquisition_session

    directory = data_directory(data_dir)
    if any(a == "--db" or a.startswith("--db=") for a in arguments):
        raise ValueError("数据库位置统一使用外层 --data-dir 参数")
    parser = cli.build_parser()
    args = parser.parse_args(arguments)
    if getattr(args, "loop", False) or (args.command == "watch" and not args.once):
        raise ValueError("FQP 来源入口只运行有限批次；watch 必须带 --once，live 不使用 --loop")
    if not 1 <= max_requests <= 1000:
        raise ValueError("请求预算必须为1–1000")
    if args.command in {"history", "lottery", "team-link"}:
        span = (cli.parse_date(args.end) - cli.parse_date(args.start)).days
        if not 0 <= span <= 30:
            raise ValueError("单批日期范围必须为1–31天；历史回填请分批执行")
    if hasattr(args, "limit"):
        args.limit = 20 if args.limit is None else args.limit
        if not 1 <= args.limit <= 500:
            raise ValueError("单批处理数量必须为1–500")
    for id_field in ("match_id", "league_id", "team_id"):
        ids = getattr(args, id_field, None)
        if ids is not None and any(i <= 0 for i in (ids if isinstance(ids, list) else [ids])):
            raise ValueError("来源 ID 必须为正整数")
    if args.command == "stats":
        return {
            "status": "ok",
            "exit_code": 0,
            "inspection": inspect_cache(directory),
            "requests": 0,
        }
    args.db = str(directory / "titan007.db")
    args.delay = max(3, args.delay or 3)
    args.jitter = max(0, args.jitter if args.jitter is not None else 2)
    args.pause_every = 10 if args.pause_every is None else max(1, args.pause_every)
    if getattr(args, "out", "") == "config/league_categories.json":
        args.out = str(directory / "config" / "league_categories.json")
    if getattr(args, "review_out", "") == "config/team_mapping_review.csv":
        args.review_out = str(directory / "config" / "team_mapping_review.csv")
    if getattr(args, "out_dir", "") == "data/images":
        args.out_dir = str(directory / "images")
    run_id = uuid.uuid4().hex
    result = {
        "version": "fqp.titan007-collection/v1",
        "run_id": run_id,
        "command": args.command,
        "started_at": datetime.now(UTC).isoformat(),
        "cache": str(directory),
        "source_id": "titan007",
        "storage_role": "raw_source_cache",
        "business_database_imported": False,
        "status": "failed",
        "exit_code": 1,
        "requests": 0,
    }
    budget = None
    with cache_lock(directory):
        _prepare_runtime(directory)
        try:
            with store.connection_scope(), acquisition_session(directory, max_requests) as budget:
                result["exit_code"] = int(args.func(args) or 0)
                result["status"] = (
                    "ok"
                    if result["exit_code"] == 0
                    and not (budget.failures or budget.operation_failures)
                    else "partial"
                )
                if (budget.failures or budget.operation_failures) and result["exit_code"] == 0:
                    result["exit_code"] = 1
        except AcquisitionStopped as exc:
            result.update(status="blocked", exit_code=3, reason=str(exc))
        except Exception as exc:
            result.update(status="failed", exit_code=1, reason=f"{type(exc).__name__}: {exc}")
        finally:
            if budget is not None:
                result.update(
                    requests=budget.requests,
                    failures=budget.failures,
                    operation_failures=budget.operation_failures,
                    http=budget.events,
                )
            result["finished_at"] = datetime.now(UTC).isoformat()
            runs = directory / "runs"
            runs.mkdir(exist_ok=True)
            _write_json(runs / f"{run_id}.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FQP 足球补充数据：复制、检查和有限采集")
    parser.add_argument("--data-dir", help="本地原始缓存目录；默认项目 data/sources/titan007")
    commands = parser.add_subparsers(dest="action", required=True)
    snapshot = commands.add_parser(
        "snapshot", help="从原采集目录一致复制已有数据（目标不得已存在）"
    )
    snapshot.add_argument("--source", required=True)
    snapshot.add_argument("--without-images", action="store_true")
    inspect = commands.add_parser("inspect", help="只读检查本地来源缓存")
    inspect.add_argument("--tables", nargs="+")
    collect = commands.add_parser("collect", help="执行原采集器命令；使用 -- 分隔参数")
    collect.add_argument("--max-requests", type=int, default=40)
    collect.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.action == "snapshot":
            last = [-1]

            def progress(item):
                if item["stage"] != "database":
                    print(
                        {
                            "database_hash": "计算数据摘要",
                            "integrity_check": "检查数据库完整性",
                            "images": "复制图片",
                        }[item["stage"]],
                        flush=True,
                    )
                    return
                percent = (
                    int(
                        100
                        * (item["total_pages"] - item["remaining_pages"])
                        / max(1, item["total_pages"])
                    )
                    // 10
                    * 10
                )
                if percent != last[0]:
                    print(f"数据库复制 {percent}%", flush=True)
                    last[0] = percent

            result = copy_source(
                args.source,
                args.data_dir,
                include_images=not args.without_images,
                progress=progress,
            )
        elif args.action == "inspect":
            result = inspect_cache(args.data_dir, args.tables)
        else:
            arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
            result = run_collection(arguments, args.data_dir, max_requests=args.max_requests)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result.get("exit_code", 0)
    except (ValueError, OSError, sqlite3.Error, RuntimeError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
