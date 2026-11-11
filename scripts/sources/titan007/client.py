"""Bounded public-source HTTP acquisition shared by the copied parsers."""

from __future__ import annotations

import json
import random
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

try:
    cffi_requests: ModuleType | None = import_module("curl_cffi.requests")
except ImportError:
    cffi_requests = None

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
DEFAULT_REFERER = "https://live.titan007.com/"
PROTECTED_HOSTS = frozenset({"zq.titan007.com", "vip.titan007.com", "info.titan007.com"})
MAX_BODY_BYTES = 16 * 1024 * 1024
MAX_DAILY_REQUESTS = 100


class AcquisitionStopped(RuntimeError):
    """Stop the whole collection on a budget, cooldown, or access restriction."""


def _validated_host(url: str) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme not in {"https", "http"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 80, 443}
        or not (
            host == "titan007.com"
            or host.endswith(".titan007.com")
            or host == "webapi.sporttery.cn"
        )
    ):
        raise ValueError("采集地址必须属于已登记的 titan007 或体彩公开数据域名")
    return host


def _looks_protected(url: str) -> bool:
    return _validated_host(url) in PROTECTED_HOSTS


def decode_body(content: bytes, content_type: str = "") -> str:
    encodings = []
    if "charset=" in (content_type or "").lower():
        encodings.append(content_type.lower().split("charset=", 1)[1].split(";")[0].strip(" \"'"))
    for encoding in [*encodings, "utf-8-sig", "utf-8", "gb18030"]:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError, LookupError:
            continue
    return content.decode("utf-8", "replace")


@dataclass
class AcquisitionBudget:
    max_requests: int = 40
    state_dir: Path | None = None
    max_seconds: float = 900
    requests: int = 0
    failures: int = 0
    operation_failures: int = 0
    events: list[dict] = field(default_factory=list)
    clients: list = field(default_factory=list, repr=False)
    started: float = field(default_factory=time.monotonic)

    def _daily_usage(self) -> dict:
        today = datetime.now(UTC).date().isoformat()
        path = self.state_dir / "daily-usage.json" if self.state_dir is not None else None
        if path is None or not path.exists():
            return {"day": today, "requests": 0}
        try:
            usage = json.loads(path.read_text())
            day = date.fromisoformat(usage["day"])
            count = usage["requests"]
            if type(count) is not int or count < 0 or day.isoformat() > today:
                raise ValueError("invalid daily budget")
            return usage if day.isoformat() == today else {"day": today, "requests": 0}
        except (ValueError, KeyError, TypeError) as exc:
            raise AcquisitionStopped("每日请求账本损坏，请检查来源状态") from exc

    def check(self) -> None:
        if self.state_dir is not None:
            path = self.state_dir / "cooldown.json"
            if path.exists():
                try:
                    until = datetime.fromisoformat(json.loads(path.read_text())["until"])
                    if until.tzinfo is None:
                        raise ValueError("missing timezone")
                except (ValueError, KeyError, TypeError) as exc:
                    raise AcquisitionStopped("冷却记录损坏，请检查来源状态") from exc
                if until > datetime.now(UTC):
                    raise AcquisitionStopped(f"来源冷却中，{until.isoformat()} 后再试")
        if self.requests >= self.max_requests:
            raise AcquisitionStopped(f"本次请求预算已用完（{self.max_requests} 次）")
        if time.monotonic() - self.started >= self.max_seconds:
            raise AcquisitionStopped("本次采集已到时限")
        if self._daily_usage()["requests"] >= MAX_DAILY_REQUESTS:
            raise AcquisitionStopped(
                f"本来源缓存的每日请求上限已用完（UTC日{MAX_DAILY_REQUESTS}次）"
            )

    def reserve_request(self) -> None:
        """Called under the project cache lock, before transport, including redirects."""
        self.check()
        if self.state_dir is not None:
            usage = self._daily_usage()
            usage["requests"] += 1
            path = self.state_dir / "daily-usage.json"
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(usage) + "\n")
            temporary.replace(path)
        self.requests += 1

    def record(self, url: str, status: int | None, size: int = 0) -> None:
        parsed = urlsplit(url)
        self.events.append(
            {
                "at": datetime.now(UTC).isoformat(),
                "host": parsed.hostname,
                "path": parsed.path,
                "status": status,
                "bytes": size,
            }
        )
        if status is None or status >= 400:
            self.failures += 1

    def block(self, status: int, retry_after: str | None) -> None:
        seconds = 3600 if status == 429 else 21600
        if retry_after and retry_after.isdigit():
            seconds = max(seconds, min(int(retry_after), 86400))
        until = datetime.now(UTC) + timedelta(seconds=seconds)
        if self.state_dir is not None:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            path = self.state_dir / "cooldown.json"
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"status": status, "until": until.isoformat()}) + "\n")
            temporary.replace(path)
        raise AcquisitionStopped(f"来源返回 HTTP {status}，已暂停至 {until.isoformat()}")


_CURRENT_BUDGET: ContextVar[AcquisitionBudget | None] = ContextVar("titan007_budget", default=None)


def record_operation_failure() -> None:
    budget = _CURRENT_BUDGET.get()
    if budget is not None:
        budget.operation_failures += 1


@contextmanager
def acquisition_session(state_dir: Path, max_requests: int = 40):
    if not 1 <= max_requests <= 1000:
        raise ValueError("请求预算必须为1–1000")
    budget = AcquisitionBudget(max_requests=max_requests, state_dir=state_dir)
    token = _CURRENT_BUDGET.set(budget)
    try:
        budget.check()
        yield budget
    finally:
        for client in budget.clients:
            client.close()
        _CURRENT_BUDGET.reset(token)


class TitanClient:
    def __init__(
        self,
        delay: float = 3,
        jitter: float = 2,
        timeout: float = 20,
        impersonate: str = "chrome",
        pause_every: int = 10,
        pause_min: float = 15,
        pause_max: float = 45,
    ) -> None:
        self.delay = max(0.0, delay)
        self.jitter = max(0.0, jitter)
        self.timeout = timeout
        self.impersonate = impersonate
        self.pause_every = max(0, int(pause_every))
        self.pause_min = max(0.0, pause_min)
        self.pause_max = max(self.pause_min, pause_max)
        self._last_request = 0.0
        self._requests_since_pause = 0
        self._pause_at = self._next_pause_target()
        self.budget = _CURRENT_BUDGET.get() or AcquisitionBudget()
        self.session = httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": DEFAULT_REFERER,
            },
        )
        self.budget.clients.append(self)

    def close(self) -> None:
        self.session.close()

    def _next_pause_target(self) -> int:
        if not self.pause_every:
            return 0
        return random.randint(max(1, self.pause_every - 2), self.pause_every + 2)

    def _throttle(self) -> None:
        if self.pause_every and self._requests_since_pause >= self._pause_at:
            time.sleep(random.uniform(self.pause_min, self.pause_max))
            self._requests_since_pause = 0
            self._pause_at = self._next_pause_target()
        wait = random.uniform(self.delay, self.delay + self.jitter)
        elapsed = time.monotonic() - self._last_request
        if elapsed < wait:
            time.sleep(wait - elapsed)
        self._last_request = time.monotonic()
        self._requests_since_pause += 1

    def get(
        self,
        url: str,
        *,
        referer: str | None = None,
        encoding: str | None = None,
        force_protected: bool | None = None,
        **kwargs,
    ) -> str:
        content, content_type = self.get_bytes(
            url, referer=referer, force_protected=force_protected, **kwargs
        )
        return (
            content.decode(encoding, "replace") if encoding else decode_body(content, content_type)
        )

    def get_bytes(
        self,
        url: str,
        *,
        referer: str | None = None,
        force_protected: bool | None = None,
        _redirects: int = 0,
        **kwargs,
    ):
        protected = _looks_protected(url) if force_protected is None else force_protected
        _validated_host(url)
        self.budget.check()
        if protected and cffi_requests is None:
            raise AcquisitionStopped(
                "此接口需要可选传输依赖：pip install -r requirements-titan007.txt"
            )
        self._throttle()
        self.budget.reserve_request()
        headers = dict(self.session.headers)
        if referer:
            _validated_host(referer)
            headers["referer"] = referer
        response: Any  # The optional curl and httpx transports expose the same response operations.
        try:
            if protected:
                assert cffi_requests is not None  # Checked before reserving this request.
                response = cffi_requests.get(
                    url,
                    impersonate=self.impersonate,
                    headers=headers,
                    timeout=self.timeout,
                    allow_redirects=False,
                    **kwargs,
                )
            else:
                response = self.session.get(url, headers=headers, **kwargs)
        except Exception:
            self.budget.record(url, None)
            raise
        status = response.status_code
        self.budget.record(url, status, len(response.content))
        if status in {401, 403, 429}:
            self.budget.block(status, response.headers.get("retry-after"))
        if 300 <= status < 400:
            location = response.headers.get("location")
            target = urljoin(url, location or "")
            try:
                same_host = _validated_host(target) == _validated_host(url)
            except ValueError as exc:
                raise AcquisitionStopped("来源重定向到了未登记地址，已停止") from exc
            downgrade = urlsplit(url).scheme == "https" and urlsplit(target).scheme != "https"
            if not location or not same_host or downgrade or _redirects >= 3:
                raise AcquisitionStopped("来源重定向不符合相同域名、HTTPS和最多3次的限制")
            return self.get_bytes(
                target,
                referer=referer,
                force_protected=force_protected,
                _redirects=_redirects + 1,
                **kwargs,
            )
        response.raise_for_status()
        if len(response.content) > MAX_BODY_BYTES:
            raise AcquisitionStopped("来源响应超过16MiB，请缩小采集范围")
        return response.content, response.headers.get("content-type", "")
