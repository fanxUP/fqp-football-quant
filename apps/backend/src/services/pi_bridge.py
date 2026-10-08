"""Bounded server-only JSON pipe to the pinned Pi runtime."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

BRIDGE = Path(__file__).resolve().parents[3] / "model-bridge" / "bridge.mjs"
_slots = threading.BoundedSemaphore(8)


class PiBridgeError(RuntimeError):
    def __init__(self, message: str, code: str = "MODEL_CALL_FAILED") -> None:
        super().__init__(message)
        self.code = code


def start_bridge() -> subprocess.Popen[str]:
    # Do not give Node unrelated application/database/encryption credentials.
    env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ}
    try:
        return subprocess.Popen(
            ["node", str(BRIDGE)],
            cwd=BRIDGE.parent,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
    except OSError as exc:
        raise PiBridgeError("Pi 运行环境未就绪，请安装服务器模型桥接依赖") from exc


def call_bridge(payload: dict[str, Any], timeout: float = 35) -> dict[str, Any]:
    if not _slots.acquire(timeout=1):
        raise PiBridgeError("模型请求繁忙，请稍后重试", "MODEL_RATE_LIMITED")
    process = None
    try:
        process = start_bridge()
        output, _ = process.communicate(
            json.dumps(payload, ensure_ascii=False) + "\n", timeout=timeout
        )
        if len(output) > 8_000_000 or process.returncode != 0:
            raise PiBridgeError("Pi 模型调用失败，请检查依赖或重新登录")
        value = json.loads(output)
        if not isinstance(value, dict):
            raise ValueError("Invalid bridge result")
        return value
    except subprocess.TimeoutExpired as exc:
        raise PiBridgeError("模型调用超时，请稍后重试", "MODEL_TIMEOUT") from exc
    except ValueError as exc:
        raise PiBridgeError("Pi 返回格式无效", "MODEL_INVALID_RESPONSE") from exc
    finally:
        if process:
            if process.poll() is None:
                process.kill()
            process.wait()
            for stream in (process.stdin, process.stdout):
                if stream:
                    stream.close()
        _slots.release()


@lru_cache(maxsize=1)
def pi_catalog() -> list[dict[str, Any]]:
    result = call_bridge({"operation": "catalog"}, timeout=15)
    if result.get("ok") is not True or not isinstance(result.get("providers"), list):
        raise PiBridgeError("Pi 模型目录不可用")
    return result["providers"]


def pi_provider(provider_id: str) -> dict[str, Any] | None:
    return next((item for item in pi_catalog() if item["id"] == provider_id), None)
