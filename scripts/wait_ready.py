"""等待服务预热完成（模型加载 + 索引预热）。

用法:
    python scripts/wait_ready.py                 # 本机
    python scripts/wait_ready.py http://1.2.3.4  # 线上

退出码 0 表示 ready=true；超时退出 1。
部署脚本应当在宣布演示地址前调用它，否则评审第一次提问会撞上冷启动。
"""

from __future__ import annotations

import sys
import time

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
TIMEOUT_S = int(sys.argv[2]) if len(sys.argv) > 2 else 300


def main() -> int:
    started = time.time()
    last = ""
    while time.time() - started < TIMEOUT_S:
        try:
            h = httpx.get(f"{BASE.rstrip('/')}/api/health", timeout=10).json()
        except Exception as exc:  # noqa: BLE001 - 服务可能还没起来
            last = f"连接失败: {exc}"
        else:
            warm = h.get("warmup") or {}
            last = (
                f"ready={h.get('ready')} embedder={warm.get('embedder')} "
                f"indexed={warm.get('indexed')}/{warm.get('documents')}"
            )
            if h.get("ready"):
                print(f"就绪（{time.time() - started:.1f}s）：{last}")
                return 0
        print(f"  等待中… {last}")
        time.sleep(5)

    print(f"超时 {TIMEOUT_S}s：{last}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
