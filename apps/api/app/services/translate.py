"""段落级中英对照翻译。

三条后端路径，按可用性自动选择：

1. **LLM**（配置了 API Key）：质量最好，能保住术语与引用编号；走 OpenAI 兼容协议。
2. **本地 MT**（Helsinki-NLP opus-mt-en-zh）：离线可用，CPU 上每段约 0.2-0.5 s，
   适合没有 Key 的环境，也是演示环境的兜底。
3. **直通**（两者都没有）：原样返回并标记 `untranslated`，前端据此提示而非假装翻译成功。

公式、参考文献、表格不参与翻译：公式保留英文是学术惯例，参考文献翻译会破坏可检索性。
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import httpx

from ..core.config import Settings, get_settings
from ..models.schema import ParsedDocument

logger = logging.getLogger(__name__)

MAX_CHARS_PER_BLOCK = 1800
SKIP_KINDS = {"formula", "reference", "table"}
CITE_PATTERN = re.compile(r"\[(\d+(?:\s*[,，\-–]\s*\d+)*)\]")


class Translator(Protocol):
    name: str

    def translate(self, texts: list[str]) -> list[str]: ...


class LLMTranslator:
    """用通用大模型翻译：保留引用编号与术语原文，是最贴近学术规范的一路。"""

    name = "llm"
    SYSTEM = (
        "你是学术论文翻译器。把用户给出的英文段落翻译成简体中文。"
        "要求：1) 严格保留所有形如 [12] 的引用编号，位置不变；"
        "2) 模型名、数据集名、指标名（如 Transformer、BLEU、WMT 2014）保留英文；"
        "3) 公式与符号原样保留；4) 只输出译文，不要解释。"
    )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def translate(self, texts: list[str]) -> list[str]:
        out: list[str] = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            return list(pool.map(self._one, texts))

    def _one(self, text: str) -> str:
        url = f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.settings.llm_model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": self.SYSTEM},
                {"role": "user", "content": text},
            ],
        }
        try:
            resp = httpx.post(
                url,
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as exc:  # noqa: BLE001 - 单段失败保留原文
            logger.warning("LLM 翻译失败，保留原文: %s", exc)
            return text


class LocalMTTranslator:
    """离线机器翻译（opus-mt-en-zh）。CPU 可跑，作为无 Key 时的兜底。"""

    name = "local-mt"

    def __init__(self, model_name: str) -> None:
        # transformers 5.x 的 AutoTokenizer 不再把 Marian 纳入自动映射，需显式指定
        from transformers import MarianMTModel, MarianTokenizer

        self.tokenizer = MarianTokenizer.from_pretrained(model_name)
        self.model = MarianMTModel.from_pretrained(model_name)
        self.model.eval()

    def translate(self, texts: list[str]) -> list[str]:
        import torch

        out: list[str] = []
        for i in range(0, len(texts), 16):
            batch = texts[i : i + 16]
            encoded = self.tokenizer(
                batch, return_tensors="pt", padding=True, truncation=True, max_length=400
            )
            with torch.no_grad():
                # beam=2 在 CPU 上比 beam=4 快近一倍，质量差异在这个模型上不明显
                generated = self.model.generate(**encoded, max_new_tokens=400, num_beams=2)
            out.extend(self.tokenizer.batch_decode(generated, skip_special_tokens=True))
        return [_apply_glossary(text) for text in out]


# 通用 MT 模型对学术术语的译法不稳定（"decoder" 被译成"编码器"、"Transformer" 被译成"变形器"），
# 这里做一次术语校正。接了大模型之后这段不会生效，属于本地兜底的补救措施。
GLOSSARY = {
    "编码器和编码器": "编码器和解码器",
    "编码器和解码器": "编码器和解码器",
    "变形器": "Transformer",
    "变异器": "Transformer",
    "自我注意": "自注意力",
    "注意机制": "注意力机制",
    "关注机制": "注意力机制",
    "点针": "逐点",
    "基模": "基础模型",
    "转换模型": "转导模型",
    "转换模式": "转导模型",
    "重复或进化神经网络": "循环或卷积神经网络",
    "重复神经网络": "循环神经网络",
    "卷变": "卷积",
    "培训": "训练",
    "可平行": "可并行",
    "最新分数": "最新得分",
    "变异模型": "模型变体",
    "谷歌脑": "Google Brain",
    "谷歌词": "Google",
    "谷歌研究": "Google Research",
}


def _apply_glossary(text: str) -> str:
    for wrong, right in sorted(GLOSSARY.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(wrong, right)
    return text


class IdentityTranslator:
    name = "none"

    def translate(self, texts: list[str]) -> list[str]:
        return texts


@lru_cache(maxsize=1)
def get_translator() -> Translator:
    settings = get_settings()
    backend = settings.translation_backend
    if backend in ("auto", "llm") and settings.llm_api_key:
        return LLMTranslator(settings)
    if backend in ("auto", "local"):
        try:
            return LocalMTTranslator(settings.translation_model)
        except Exception as exc:  # noqa: BLE001 - 模型缺失时降级
            logger.warning("本地翻译模型不可用（%s），回退为直通", exc)
    return IdentityTranslator()


def _cache_path(doc_id: str) -> Path:
    return get_settings().docs_dir / doc_id / "translation.json"


PROSE_RE = re.compile(r"[A-Za-z]{3,}\s+[A-Za-z]{3,}\s+[A-Za-z]{3,}")


def _should_translate(text: str, kind: str) -> bool:
    """只翻译真正的正文段落。

    作者与机构行、邮箱串、页眉页脚既没有翻译价值，还会显著拖慢整篇翻译
    （实测 175 段里约 40 段是这类噪声，占掉近两成耗时）。
    """
    if kind != "paragraph":
        return False
    if not 20 <= len(text) <= MAX_CHARS_PER_BLOCK:
        return False
    if "@" in text:
        return False
    if len(PROSE_RE.findall(text)) < 2:  # 至少三个连续英文词出现两次
        return False
    return True


def load_translation(doc_id: str) -> dict | None:
    path = _cache_path(doc_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def translate_document(doc_id: str, parsed: ParsedDocument, force: bool = False) -> dict:
    """翻译正文段落并落盘缓存。返回 {translator, items:[{block_id,page,source,target}]}。"""
    if not force:
        cached = load_translation(doc_id)
        if cached:
            return cached

    candidates = [b for b in parsed.blocks if _should_translate(b.text, b.kind)]
    translator = get_translator()

    texts = [block.text for block in candidates]
    targets = translator.translate(texts) if texts else []
    items = [
        {
            "block_id": block.id,
            "page": block.page,
            "bbox": block.bbox,
            "source": block.text,
            "target": target,
            "citations": CITE_PATTERN.findall(block.text),
        }
        for block, target in zip(candidates, targets)
    ]

    payload = {
        "doc_id": doc_id,
        "translator": translator.name,
        "count": len(items),
        "items": items,
    }
    path = _cache_path(doc_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload
