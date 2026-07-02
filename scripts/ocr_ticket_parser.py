"""OCR 票据识别模块。

将实票照片/截图转为结构化数据。
支持两种后端：
- tesseract (pytesseract): 免费，需安装 Tesseract-OCR 系统包
- easyocr: 深度学习，更准确但更慢，首次需下载模型

Pipeline: 图像预处理 → OCR 识别 → 文本结构化解析 → 返回 TicketData
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class TicketItem:
    """一张票据中的单场比赛。"""

    match_code: str = ""  # 比赛编号，如 "001"、"周六001"
    home_team: str = ""
    away_team: str = ""
    play_type: str = "spf"  # spf | rqspf | zjq | bf | bqc
    option_code: str = ""  # 3/1/0 或其他选项代码
    option_name: str = ""  # 胜/平/负 或具体比分等
    sp_value: float = 0.0
    handicap: str = ""  # 让球数，如 "-1"、"+1"


@dataclass
class TicketParseResult:
    """OCR 解析结果。"""

    success: bool = False
    ticket_no: str = ""  # 票号
    pass_type: str = "single"  # single | 2x1 | 3x1 | ...
    multiple: int = 1  # 倍数
    total_amount: float = 0.0  # 总金额
    items: list[TicketItem] = field(default_factory=list)

    # OCR 元数据
    raw_text: str = ""  # OCR 识别原始文本
    ocr_engine: str = ""  # 使用的 OCR 引擎
    confidence: float = 0.0  # 整体置信度 0-1
    warnings: list[str] = field(default_factory=list)
    parsed_at: str = ""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# OCR 引擎接口
# ---------------------------------------------------------------------------


def ocr_with_pytesseract(image_path: str, lang: str = "chi_sim") -> tuple[str, float]:
    """使用 Tesseract OCR 识别图片文字。

    返回 (text, confidence)。
    需要系统安装 tesseract-ocr 和中文语言包。
    """
    try:
        import pytesseract
        from PIL import Image

        img = Image.open(image_path)
        # 预处理：转灰度、增强对比度
        img = img.convert("L")  # type: ignore[assignment]  # Image.open→ImageFile, convert→Image
        text = pytesseract.image_to_string(img, lang=lang)
        # Tesseract 不直接返回每张图片的置信度，估计值
        confidence = 0.7 if len(text.strip()) > 20 else 0.3
        return text, confidence
    except ImportError as e:
        raise RuntimeError("pytesseract 未安装。运行: pip install pytesseract Pillow") from e
    except Exception as e:
        raise RuntimeError(f"Tesseract OCR 失败: {e}") from e


def ocr_with_easyocr(image_path: str, languages: list[str] | None = None) -> tuple[str, float]:
    """使用 EasyOCR 识别图片文字。

    返回 (text, confidence)。
    首次运行会下载模型（~100MB）。
    """
    try:
        import easyocr

        langs = languages or ["ch_sim", "en"]
        reader = easyocr.Reader(langs, gpu=False)
        results = reader.readtext(image_path)

        if not results:
            return "", 0.0

        # 按 y 坐标排序（从上到下），按 x 坐标排序（从左到右）
        results.sort(key=lambda r: (r[0][0][1], r[0][0][0]))

        lines: list[str] = []
        total_conf = 0.0
        for _bbox, text, conf in results:
            lines.append(text)
            total_conf += conf

        text = "\n".join(lines)
        confidence = total_conf / len(results) if results else 0.0
        return text, confidence
    except ImportError as e:
        raise RuntimeError("easyocr 未安装。运行: pip install easyocr") from e
    except Exception as e:
        raise RuntimeError(f"EasyOCR 失败: {e}") from e


def ocr_image(
    image_path: str,
    engine: str = "auto",
    lang: str = "chi_sim",
) -> tuple[str, float, str]:
    """通用 OCR 入口。engine 可选 "tesseract" | "easyocr" | "auto"。

    "auto" 模式优先尝试 tesseract（更快），失败则回退到 easyocr。
    返回 (text, confidence, engine_used)。
    """
    if engine == "tesseract":
        text, conf = ocr_with_pytesseract(image_path, lang=lang)
        return text, conf, "tesseract"

    if engine == "easyocr":
        text, conf = ocr_with_easyocr(image_path)
        return text, conf, "easyocr"

    # auto: try tesseract first
    try:
        text, conf = ocr_with_pytesseract(image_path, lang=lang)
        if conf > 0.3:
            return text, conf, "tesseract"
    except Exception:
        pass

    try:
        text, conf = ocr_with_easyocr(image_path)
        return text, conf, "easyocr"
    except Exception:
        pass

    raise RuntimeError("所有 OCR 引擎均不可用。请安装 tesseract 或 easyocr。")


# ---------------------------------------------------------------------------
# 文本解析器
# ---------------------------------------------------------------------------


def parse_ticket_text(raw_text: str) -> TicketParseResult:
    """从 OCR 识别的原始文本中解析出票据结构化数据。

    支持中文体育彩票的常见格式：
    - 竞彩足球 胜平负/让球胜平负/比分/总进球/半全场
    - 传统足彩 14场/任九
    """
    result = TicketParseResult(
        success=False,
        raw_text=raw_text,
        parsed_at=_now(),
    )

    lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
    if not lines:
        result.warnings.append("未识别到任何文字")
        return result

    full_text = raw_text

    # ---- 提取票号 ----
    ticket_no_match = re.search(r"[票单]号[：:\s]*(\d{10,20})", full_text)
    if ticket_no_match:
        result.ticket_no = ticket_no_match.group(1)

    # ---- 提取倍数 ----
    multiple_match = re.search(r"(\d+)倍", full_text)
    if multiple_match:
        result.multiple = int(multiple_match.group(1))

    # ---- 提取金额 ----
    amount_match = re.search(r"[金总]额[：:\s]*[¥￥]?\s*(\d+\.?\d*)", full_text)
    if amount_match:
        result.total_amount = float(amount_match.group(1))

    # ---- 提取过关方式 ----
    if "单关" in full_text or "单场" in full_text:
        result.pass_type = "single"
    elif "2串1" in full_text or "2x1" in full_text:
        result.pass_type = "2x1"
    elif "3串1" in full_text or "3x1" in full_text:
        result.pass_type = "3x1"
    elif "4串1" in full_text or "4x1" in full_text:
        result.pass_type = "4x1"
    elif "任九" in full_text or "任选9" in full_text:
        result.pass_type = "rx9"
    elif "14场" in full_text:
        result.pass_type = "14match"

    # ---- 提取比赛项目 ----
    # 模式1：比赛编号 + 对阵 + 玩法 + 选项 + 赔率
    # 如 "周六001 曼联vs利物浦 胜平负 胜 1.45"
    match_pattern = re.compile(
        r"(?:周[一二三四五六日])?(\d{3})\s+"
        r"(.+?)\s+"  # 对阵（贪心匹配到下一段）
        r"(胜平负|让球胜平负|比分|总进球|半全场|让球)\s*"
        r"([-+]?\d)?\s*"  # 让球数
        r"(胜|平|负|[0-9]+:[0-9]+|[0-9]+球|[0-9]+)\s+"
        r"(\d+\.?\d*)",  # 赔率
    )

    for m in match_pattern.finditer(full_text):
        item = TicketItem(
            match_code=m.group(1),
            home_team="",  # 从对阵中分离需要更多上下文
            play_type=_normalize_play_type(m.group(3)),
            option_code=m.group(5),
            sp_value=float(m.group(6)),
            handicap=m.group(4) or "",
        )
        # 尝试分离主客队
        matchup = m.group(2).strip()
        for sep in ["vs", "VS", "对", "-", "—"]:
            if sep in matchup:
                parts = matchup.split(sep, 1)
                item.home_team = parts[0].strip()
                item.away_team = parts[1].strip()
                break
        if not item.home_team:
            item.home_team = matchup
            item.away_team = ""

        result.items.append(item)

    # 模式2：简化的比赛行（传统足彩格式）
    # 如 "1 曼联 vs 利物浦 3"
    if not result.items:
        simple_pattern = re.compile(
            r"^(\d{1,2})\s+(.+?)\s+vs\s+(.+?)\s+([310])$",
            re.IGNORECASE | re.MULTILINE,
        )
        for m in simple_pattern.finditer(full_text):
            item = TicketItem(
                match_code=m.group(1),
                home_team=m.group(2).strip(),
                away_team=m.group(3).strip(),
                play_type="spf",
                option_code=m.group(4),
            )
            result.items.append(item)

    # ---- 推断 ----
    if result.total_amount == 0 and result.items:
        result.total_amount = len(result.items) * 2 * result.multiple

    if result.items:
        result.success = True
    else:
        result.warnings.append("未能从识别文字中解析出比赛项目，请手动录入")

    return result


def _normalize_play_type(raw: str) -> str:
    """将OCR识别的玩法名称标准化。"""
    mapping = {
        "胜平负": "spf",
        "让球胜平负": "rqspf",
        "让球": "rqspf",
        "比分": "bf",
        "总进球": "zjq",
        "半全场": "bqc",
    }
    return mapping.get(raw.strip(), raw.strip().lower())


# ---------------------------------------------------------------------------
# 完整 pipeline
# ---------------------------------------------------------------------------


def process_ticket_image(
    image_path: str,
    engine: str = "auto",
    lang: str = "chi_sim",
) -> TicketParseResult:
    """完整的票据图片处理 pipeline：OCR → 解析 → 结构化。

    用法：
        result = process_ticket_image("/path/to/ticket.jpg")
        if result.success:
            print(f"识别到 {len(result.items)} 场比赛")
            for item in result.items:
                print(f"  {item.match_code} {item.option_code} @{item.sp_value}")
        else:
            print(f"识别失败: {result.warnings}")
    """
    # Step 1: OCR
    raw_text, confidence, used_engine = ocr_image(image_path, engine=engine, lang=lang)
    result = parse_ticket_text(raw_text)

    # Step 2: 补充元数据
    result.confidence = confidence
    result.ocr_engine = used_engine

    if confidence < 0.3:
        result.warnings.append(f"OCR 置信度较低 ({confidence:.1%})，建议人工核对")

    return result


def result_to_dict(result: TicketParseResult) -> dict[str, Any]:
    """将 TicketParseResult 序列化为 API 响应格式。"""
    return {
        "success": result.success,
        "ticket_no": result.ticket_no,
        "pass_type": result.pass_type,
        "multiple": result.multiple,
        "total_amount": result.total_amount,
        "items": [
            {
                "match_code": item.match_code,
                "home_team": item.home_team,
                "away_team": item.away_team,
                "play_type": item.play_type,
                "option_code": item.option_code,
                "option_name": item.option_name,
                "sp_value": item.sp_value,
                "handicap": item.handicap,
            }
            for item in result.items
        ],
        "raw_text": result.raw_text[:500],  # 截断，避免过大
        "ocr_engine": result.ocr_engine,
        "confidence": round(result.confidence, 4),
        "warnings": result.warnings,
        "parsed_at": result.parsed_at,
    }
