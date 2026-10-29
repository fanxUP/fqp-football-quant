"""队徽 / 球员头像的 URL 解析与下载。"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

TEAM_BASE = "https://zq.titan007.com/Image/team/"
PLAYER_BASE = "https://zq.titan007.com/Image/player/"

IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")
DEFAULT_HEADERS = {"Referer": "https://zq.titan007.com/"}


def absolute_url(path_or_url: Any, base: str) -> str | None:
    if not path_or_url:
        return None
    p = str(path_or_url).strip().replace("\\", "/")
    if not p:
        return None
    if p.startswith("//"):
        return "https:" + p
    if p.startswith("http://") or p.startswith("https://"):
        return p
    if p.startswith("/Image/") or p.startswith("/images/"):
        return "https://zq.titan007.com" + p
    if p.startswith("Image/"):
        return "https://zq.titan007.com/" + p
    return base + p.lstrip("/")


def team_logo_url(logo: Any) -> str | None:
    """teamDetail/arrTeam 里的 images/181/xxx.png → 完整地址。"""
    return absolute_url(logo, TEAM_BASE)


def player_photo_url(photo: Any) -> str | None:
    """lineup HTML 里的 /Image/player/images/166669/xxx.png → 完整地址。"""
    return absolute_url(photo, PLAYER_BASE)


def extract_player_photo(html: str, player_id: int) -> str | None:
    """从阵容/球员页 HTML 中找出该球员的头像地址。"""
    if not html:
        return None
    pat = re.compile(
        r'(?:(?:https?:)?//[^"\'\s]*)?/Image/player/(images/[^"\'\s]+?'
        + r"\.(?:png|jpe?g|gif|webp|svg))",
        re.I,
    )
    by_id = re.compile(
        rf'(?:(?:https?:)?//[^"\'\s]*)?/Image/player/(images/{player_id}/[^"\'\s]+?'
        + r"\.(?:png|jpe?g|gif|webp|svg))",
        re.I,
    )
    m = by_id.search(html) or pat.search(html)
    return player_photo_url(m.group(1)) if m else None


def extract_team_logos(teams: Iterable[Any]) -> dict[int, tuple[str | None, str | None]]:
    """arrTeam 行：[id, 名, 繁名, 英文名, ?, logo] → {id: (名称, logo)}。"""
    out: dict[int, tuple[str | None, str | None]] = {}
    for row in teams or []:
        if not isinstance(row, list) or len(row) < 2:
            continue
        try:
            team_id = int(str(row[0]).strip())
        except TypeError, ValueError:
            continue
        logo = row[5] if len(row) > 5 else None
        out[team_id] = (row[1] if len(row) > 1 else None, logo or None)
    return out


def image_ext(url: str) -> str:
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    return ext if ext in IMG_EXT else ".png"


def download_image(client, url: str, dest_dir: str, entity_id: int) -> tuple[str, int, bool]:
    """下载图片到 dest_dir/{entity_id}.ext。返回 (路径, 字节数, 是否已存在)。"""
    dest = os.path.join(dest_dir, f"{entity_id}{image_ext(url)}")
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest, os.path.getsize(dest), True

    content, content_type = client.get_bytes(url, referer=DEFAULT_HEADERS["Referer"])
    if not str(content_type).lower().startswith("image/") or len(content) < 64:
        raise ValueError(f"不是图片（{content_type or '未知类型'}，{len(content)} 字节）")

    os.makedirs(dest_dir, exist_ok=True)
    tmp = f"{dest}.part"
    with open(tmp, "wb") as fh:
        fh.write(content)
    os.replace(tmp, dest)
    return dest, len(content), False
