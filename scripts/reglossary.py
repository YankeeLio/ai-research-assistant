"""对已缓存的译文重跑术语校正（不重新翻译，秒级完成）。

用法:
    python scripts/reglossary.py <doc_id>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.services.translate import _apply_glossary  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python scripts/reglossary.py <doc_id>")
        raise SystemExit(1)
    path = Path("data") / "docs" / sys.argv[1] / "translation.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    changed = 0
    for item in payload["items"]:
        fixed = _apply_glossary(item["target"])
        if fixed != item["target"]:
            item["target"] = fixed
            changed += 1
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"已更新 {changed}/{len(payload['items'])} 段的术语")


if __name__ == "__main__":
    main()
