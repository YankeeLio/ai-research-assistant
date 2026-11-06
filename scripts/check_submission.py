"""提交前的机械检查：把清单里能自动验证的项目跑一遍。

用法:
    python scripts/check_submission.py                    # 只查本地材料
    python scripts/check_submission.py http://<服务器IP>   # 顺带验证线上地址

退出码 0 表示"本地能自动验证的项目"全部通过；
视频与在线地址属于人工确认项，脚本会把它们标成 MANUAL 而不是假装通过。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "docs" / "SciLoom-技术文档.pdf"
VIDEO_CANDIDATES = [
    ROOT / "assets" / "video" / "demo-with-subs.mp4",
    ROOT / "assets" / "video" / "demo-with-cards.mp4",
    ROOT / "assets" / "video" / "demo-silent.mp4",
]

results: list[tuple[str, str, str]] = []


def record(name: str, status: str, detail: str = "") -> None:
    results.append((name, status, detail))
    print(f"{status:6} {name}" + (f"  —— {detail}" if detail else ""))


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8"
    ).stdout.strip()


def check_repo() -> None:
    if git("rev-parse", "--is-inside-work-tree") != "true":
        record("Git 仓库", "FAIL", "当前目录不是 git 仓库")
        return
    dirty = git("status", "--porcelain")
    record("工作区干净", "PASS" if not dirty else "WARN", dirty[:80] if dirty else "")

    remote = git("remote", "get-url", "origin")
    record("已配置远程仓库", "PASS" if remote else "FAIL", remote)

    ahead = git("rev-list", "--count", "@{u}..HEAD") if remote else ""
    if ahead.isdigit():
        record("提交已推送", "PASS" if ahead == "0" else "FAIL", f"领先远端 {ahead} 个提交")

    # 敏感信息：真实 key 不应出现在被跟踪文件里（.env.example 的占位符要排除）
    grep = git("grep", "-n", "-I", "-E", "sk-[a-zA-Z0-9]{20,}", "--", ".")
    hits = [
        line
        for line in grep.splitlines()
        if "xxxx" not in line.lower() and ".env.example" not in line
    ]
    record("无真实密钥入库", "PASS" if not hits else "FAIL", hits[0][:80] if hits else "")

    env_tracked = git("ls-files", ".env")
    record(".env 未被跟踪", "PASS" if not env_tracked else "FAIL", env_tracked)


def check_readme() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    placeholder = "填写姓名" in readme
    record("README 已填姓名", "FLAG" if placeholder else "PASS", "仍是占位符" if placeholder else "")
    record("README 有运行说明", "PASS" if "pip install" in readme or "uvicorn" in readme else "WARN")


def check_pdf() -> None:
    if not PDF.exists():
        record("技术文档存在", "FAIL", str(PDF))
        return
    try:
        import pymupdf

        pages = pymupdf.open(PDF).page_count
    except Exception as exc:  # noqa: BLE001
        record("技术文档页数", "WARN", f"无法读取: {exc}")
        return
    ok = 15 <= pages <= 30
    record("技术文档 ≤30 页", "PASS" if ok else "FAIL", f"{pages} 页")


def check_video() -> None:
    video = next((p for p in VIDEO_CANDIDATES if p.exists()), None)
    if video is None:
        record("演示视频存在", "FAIL", "assets/video/ 下没有可用成片")
        return
    size_mb = video.stat().st_size / 1024 / 1024
    record("演示视频存在", "PASS", f"{video.name} / {size_mb:.1f} MB")

    ffmpeg = ROOT / "apps" / "api" / ".venv" / "Lib" / "site-packages" / "imageio_ffmpeg" / "binaries"
    exe = next(ffmpeg.glob("ffmpeg*.exe"), None) if ffmpeg.exists() else None
    if exe is None:
        record("视频时长与分辨率", "MANUAL", "未找到 ffmpeg，请人工确认 5–8 分钟、≥1080p")
        return
    out = subprocess.run([str(exe), "-i", str(video)], capture_output=True, text=True, encoding="utf-8").stderr
    dur = re.search(r"Duration: (\d+):(\d+):(\d+)", out)
    dim = re.search(r"(\d{3,4})x(\d{3,4})", out)
    if dur:
        seconds = int(dur.group(1)) * 3600 + int(dur.group(2)) * 60 + int(dur.group(3))
        ok = 300 <= seconds <= 480
        record("视频时长 5–8 分钟", "PASS" if ok else "FAIL", f"{seconds // 60} 分 {seconds % 60} 秒")
    if dim:
        w, h = int(dim.group(1)), int(dim.group(2))
        record("视频 ≥1080p", "PASS" if h >= 1080 else "FAIL", f"{w}×{h}")
    record("视频含普通话讲解", "MANUAL", "自动成片无声，需人工确认配音")


def check_online(url: str) -> None:
    try:
        health = httpx.get(f"{url.rstrip('/')}/api/health", timeout=20).json()
    except Exception as exc:  # noqa: BLE001
        record("线上地址可访问", "FAIL", str(exc)[:60])
        return
    record("线上地址可访问", "PASS", f"ready={health.get('ready')}")
    warm = health.get("warmup") or {}
    record(
        "线上索引已预热",
        "PASS" if health.get("ready") else "WARN",
        f"indexed={warm.get('indexed')}/{warm.get('documents')}",
    )
    try:
        docs = httpx.get(f"{url.rstrip('/')}/api/documents", timeout=30).json()
        record("线上文献库非空", "PASS" if len(docs) >= 5 else "FAIL", f"{len(docs)} 篇")
    except Exception as exc:  # noqa: BLE001
        record("线上文献库非空", "FAIL", str(exc)[:60])


def main() -> int:
    print(f"检查目录: {ROOT}\n")
    check_repo()
    check_readme()
    check_pdf()
    check_video()
    if len(sys.argv) > 1 and sys.argv[1].startswith("http"):
        check_online(sys.argv[1])

    fails = [r for r in results if r[1] == "FAIL"]
    manual = [r for r in results if r[1] in ("MANUAL", "FLAG")]
    print(f"\n通过 {sum(1 for r in results if r[1] == 'PASS')} / 失败 {len(fails)} / 待人工 {len(manual)}")
    if manual:
        print("待人工确认：")
        for name, _status, detail in manual:
            print(f"  - {name}{('：' + detail) if detail else ''}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
