"""Helpers for extracting JavaScript literals from titan007 pages."""

from __future__ import annotations

import ast
import re
from typing import Any


def _extract_balanced(text: str, start: int, open_ch: str, close_ch: str) -> str | None:
    depth = 0
    quote = None
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def extract_balanced_at(
    text: str, start: int, open_ch: str = "[", close_ch: str = "]"
) -> str | None:
    return _extract_balanced(text, start, open_ch, close_ch)


def extract_js_array(text: str, name: str) -> str | None:
    """提取 `var name = [...]` 或 `var name = new Array(...)`。"""
    m = re.search(rf"\bvar\s+{re.escape(name)}\s*=\s*\[", text)
    if m:
        return _extract_balanced(text, m.end() - 1, "[", "]")
    m = re.search(rf"\bvar\s+{re.escape(name)}\s*=\s*(?:new\s+)?Array\s*\(", text)
    if m:
        raw = _extract_balanced(text, m.end() - 1, "(", ")")
        if raw is None:
            return None
        return "[" + raw[1:-1] + "]"
    return None


def _sanitize_js(text: str) -> str:
    text = re.sub(r"\btrue\b", "True", text)
    text = re.sub(r"\bfalse\b", "False", text)
    text = re.sub(r"\bnull\b", "None", text)
    text = re.sub(r"\bundefined\b", "None", text)
    # JS 数组空位： [a,,b] / [a, , b] / [,a] / [a,]
    for _ in range(6):
        new = re.sub(r",\s*,", ",None,", text)
        new = re.sub(r"\[\s*,", "[None,", new)
        new = re.sub(r",\s*\]", ",None]", new)
        if new == text:
            break
        text = new
    return text


def js_literal(text: str) -> Any:
    """把 JS 字面量转成 Python 对象；失败返回 None。"""
    if text is None:
        return None
    try:
        return ast.literal_eval(_sanitize_js(text))
    except ValueError, SyntaxError:
        return None


def extract_js_object(text: str, name: str) -> str | None:
    m = re.search(rf"\bvar\s+{re.escape(name)}\s*=\s*\{{", text)
    if not m:
        return None
    return _extract_balanced(text, m.end() - 1, "{", "}")


def extract_js_literal(text: str, name: str) -> Any:
    raw = extract_js_array(text, name)
    if raw is None:
        raw = extract_js_object(text, name)
    return js_literal(raw)
