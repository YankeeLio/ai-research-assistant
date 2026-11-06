"""文件路径与标识符校验。

doc_id 由服务端生成的 uuid hex 前缀构成（12 位十六进制），因此可以用白名单
正则严格约束。这不是洁癖：在 Windows 上反斜杠也是路径分隔符，若把 URL 里的
`..%5C` 原样拼进路径，就能读到文档目录之外的文件。
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException

from .config import get_settings

_ID_RE = re.compile(r"^[0-9a-f]{6,32}$")


def validate_id(value: str, kind: str = "文档") -> str:
    if not _ID_RE.match(value or ""):
        raise HTTPException(status_code=404, detail=f"{kind}不存在")
    return value


def doc_dir(doc_id: str) -> Path:
    return get_settings().docs_dir / validate_id(doc_id)


def figure_path(figure_id: str) -> Path:
    return get_settings().data_dir / "figures" / f"{validate_id(figure_id, '图表')}.png"
