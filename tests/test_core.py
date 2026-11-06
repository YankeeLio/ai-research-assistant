"""核心服务的回归测试。

只覆盖"错了会让下游全错、但不会抛异常"的地方：解析指标、语义去重判定、
引用校验、图表类型选择、图谱角色。这些正是项目里出过真问题的地方。

运行:
    cd apps/api && .venv\\Scripts\\python -m pytest ../../tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services import dedupe, viz  # noqa: E402
from app.services.parser import PdfParser  # noqa: E402
from app.services.qa import _validate  # noqa: E402
from app.services.qa import Evidence  # noqa: E402

PDF_V7 = ROOT / "pdf" / "1706.03762v7.pdf"
PDF_V1 = ROOT / "pdf" / "1706.03762v1.pdf"
CSV = ROOT / "scripts" / "samples" / "model_bleu.csv"


@pytest.fixture(scope="module")
def parsed_v7():
    if not PDF_V7.exists():
        pytest.skip("缺少 pdf/1706.03762v7.pdf（先跑 scripts/fetch_data.py）")
    return PdfParser().parse(PDF_V7, "test-v7")


def test_parse_structure(parsed_v7):
    stats = parsed_v7.stats
    assert stats is not None
    assert stats.page_count == 15
    assert stats.reference_count >= 35, "参考文献应完整解析"
    assert stats.cite_anchor_count >= 50, "引用锚点应达到字符级"
    assert parsed_v7.title.lower().startswith("attention is all you need")
    assert len(parsed_v7.sections) >= 7, "一级章节应有 7 个"


def test_text_has_spaces(parsed_v7):
    """曾经把空格 span 当噪声过滤，整句会粘成一坨——这条断言防止回归。"""
    body = " ".join(b.text for b in parsed_v7.blocks[:40] if b.kind == "paragraph")
    assert "The dominant sequence" in body or " dominant " in body
    assert "theencoderis" not in body.lower().replace(" ", "")


def test_anchor_bbox_is_precise(parsed_v7):
    """锚点应收敛到字符级，而不是整段宽度。"""
    narrow = [a for a in parsed_v7.cite_anchors if (a.bbox[2] - a.bbox[0]) < 40]
    assert len(narrow) >= 10


def test_dedupe_same_work(parsed_v7):
    if not PDF_V1.exists():
        pytest.skip("缺少 v1")
    parsed_v1 = PdfParser().parse(PDF_V1, "test-v1")
    fp_v7 = dedupe.build_fingerprint(parsed_v7)
    fp_v1 = dedupe.build_fingerprint(parsed_v1)
    match = dedupe.compare(fp_v1, fp_v7)
    assert match.verdict == "same_work"
    assert 0.85 <= match.similarity <= 1.0
    advice = dedupe.recommend("v1", "v7", match)
    assert advice["action"] == "keep_existing"


def test_dedupe_identical(parsed_v7):
    fp = dedupe.build_fingerprint(parsed_v7)
    match = dedupe.compare(fp, fp)
    assert match.verdict == "identical"
    assert match.similarity > 0.97


def test_citation_whitelist():
    """越界引用必须被剔除，否则"不编造出处"这条防线形同虚设。"""
    evidence = [
        Evidence(chunk_id="c1", page=0, section="", text="a", score=1.0),
        Evidence(chunk_id="c2", page=0, section="", text="b", score=0.9),
    ]
    cleaned, unknown = _validate("结论一 [c1]，结论二 [c2]，可疑 [c9]", evidence)
    assert unknown == ["c9"]
    assert "[c9]" not in cleaned
    assert "[c1]" in cleaned and "[c2]" in cleaned


def test_chart_type_and_caption():
    if not CSV.exists():
        pytest.skip("缺少示例 CSV")
    result = viz.render_chart(CSV.read_text(encoding="utf-8"), title="BLEU")
    assert result["chart_type"] == "grouped_bar"
    assert len(result["caption"]) > 80
    # 量级差 20 倍以上应自动拆子图，并在图注里说明
    assert "量级" in result["caption"]


def test_graph_roles(parsed_v7):
    from app.services.graph import build_graph

    other = PdfParser().parse(PDF_V1, "test-v1") if PDF_V1.exists() else None
    docs = [parsed_v7] + ([other] if other else [])
    graph = build_graph(docs)
    assert graph.stats["nodes"] >= 5
    assert any(n.in_library for n in graph.nodes)
    assert 0.0 <= max(n.pagerank for n in graph.nodes) <= 1.0
