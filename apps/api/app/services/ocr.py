"""扫描件 OCR：页面栅格化后交给 OCR 引擎，坐标反算回 PDF 空间。

为什么锚点必须反算
------------------
阅读器的高亮、划词翻译、问答溯源都在 PDF 用户坐标系里工作，而 OCR 只认像素。
这里统一把识别框乘以 `页面尺寸 / 位图尺寸`，让扫描件产出的 block 与矢量 PDF
拥有同一套坐标语义——上层不需要区分文档是"原生的"还是"扫出来的"。
"""

from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np
import pymupdf

logger = logging.getLogger(__name__)

# OCR 置信度低于该阈值的行直接丢弃，避免把版面噪声送进 RAG
MIN_SCORE = 0.55


@lru_cache(maxsize=1)
def _engine():  # noqa: ANN202 - 第三方对象无稳定类型
    """懒加载 OCR 引擎：未安装依赖时不应影响矢量 PDF 的解析。"""
    from rapidocr_onnxruntime import RapidOCR

    logger.info("初始化 RapidOCR 引擎")
    return RapidOCR()


def ocr_page_lines(
    page: pymupdf.Page, dpi: int = 200
) -> list[tuple[tuple[float, float, float, float], str, float]]:
    """识别单页文字，返回 (PDF 坐标 bbox, 文本, 置信度) 列表。"""
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n > 3:
        img = img[:, :, :3]

    try:
        result, _elapse = _engine()(img)
    except Exception as exc:  # noqa: BLE001 - 单页 OCR 失败不应中断整篇解析
        logger.warning("第 %d 页 OCR 失败: %s", page.number + 1, exc)
        return []

    sx = page.rect.width / max(1, pix.width)
    sy = page.rect.height / max(1, pix.height)
    lines: list[tuple[tuple[float, float, float, float], str, float]] = []
    for item in result or []:
        try:
            box, text, score = item[0], str(item[1]), float(item[2])
        except (IndexError, TypeError, ValueError):
            continue
        text = text.strip()
        if not text or score < MIN_SCORE:
            continue
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        lines.append(((min(xs) * sx, min(ys) * sy, max(xs) * sx, max(ys) * sy), text, score))
    return lines
