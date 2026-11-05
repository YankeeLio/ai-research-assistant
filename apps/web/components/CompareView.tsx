"use client";

import { useMemo, useState } from "react";

import { type CompareResult, type DocumentSummary, compareDocuments } from "@/lib/api";
import { Markdown } from "@/lib/markdown";

const PRESETS: { q: string; pick?: string[] }[] = [
  {
    q: "BERT 与 Transformer Encoder 在结构上有什么承袭与差异？",
    pick: ["BERT", "Attention Is All You Need"],
  },
  { q: "这几篇论文在训练数据规模与算力投入上如何演进？" },
  { q: "各篇论文的核心贡献与局限分别是什么？" },
];

export default function CompareView({
  docs,
  currentId,
  onOpenDoc,
}: {
  docs: DocumentSummary[];
  currentId: string;
  onOpenDoc: (docId: string, page: number) => void;
}) {
  const others = useMemo(() => docs.filter((d) => d.status === "ready"), [docs]);
  const [selected, setSelected] = useState<string[]>(() => {
    // 默认挑"承袭关系"最典型的一对：BERT 与原始 Transformer；
    // 库里没有就退化成"当前文档 + 相邻一篇"
    const bert = others.find((d) => d.title.toUpperCase().startsWith("BERT"));
    const attn = others.find(
      (d) => d.title.includes("Attention Is All You Need") && !d.is_scanned,
    );
    if (bert && attn) return [attn.doc_id, bert.doc_id];
    const rest = others.find((d) => d.doc_id !== currentId);
    return rest ? [currentId, rest.doc_id] : [currentId];
  });
  const [question, setQuestion] = useState(PRESETS[0].q);
  const [result, setResult] = useState<CompareResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const toggle = (docId: string) => {
    setSelected((prev) =>
      prev.includes(docId)
        ? prev.filter((x) => x !== docId)
        : prev.length >= 5
          ? prev
          : [...prev, docId],
    );
  };

  const run = async () => {
    if (selected.length < 2) {
      setError("至少选择两篇论文");
      return;
    }
    setLoading(true);
    setError("");
    try {
      setResult(await compareDocuments(selected, question));
    } catch (e) {
      setError((e as Error).message.slice(0, 200));
    } finally {
      setLoading(false);
    }
  };

  const grouped = useMemo(() => {
    if (!result) return [];
    const map = new Map<string, typeof result.evidence>();
    for (const ev of result.evidence) {
      const list = map.get(ev.title || ev.doc_id) ?? [];
      list.push(ev);
      map.set(ev.title || ev.doc_id, list);
    }
    return [...map.entries()];
  }, [result]);

  return (
    <div className="h-full overflow-y-auto px-10 py-6">
      <div className="max-w-[1080px]">
        <p className="mb-3 text-[12.5px] leading-relaxed text-ink/60">
          选择两到五篇论文，系统会分别检索证据、统一编号后做维度化对比。答案中的每个
          <span className="cite mx-1">[c3]</span>都对应下方某篇论文的具体页码。
        </p>

        <div className="mb-3 flex flex-wrap gap-1.5">
          {others.map((doc) => {
            const active = selected.includes(doc.doc_id);
            return (
              <button
                key={doc.doc_id}
                type="button"
                onClick={() => toggle(doc.doc_id)}
                className={`max-w-[280px] truncate border px-2.5 py-1 text-[11.5px] transition-colors ${
                  active
                    ? "border-blueprint bg-blueprint/10 text-blueprint"
                    : "border-haze text-ink/60 hover:border-ink/30"
                }`}
                title={doc.title}
              >
                {active ? "✓ " : ""}
                {doc.title.slice(0, 34)}
              </button>
            );
          })}
        </div>

        <div className="flex gap-2">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            className="flex-1 border border-haze bg-mist px-3 py-2 text-[12.5px] outline-none focus:border-blueprint"
            placeholder="要对比什么？"
          />
          <button
            type="button"
            onClick={() => void run()}
            disabled={loading}
            className="border border-blueprint px-4 py-2 text-[12px] text-blueprint hover:bg-blueprint hover:text-mist disabled:opacity-40"
          >
            {loading ? "对比中…" : `对比这 ${selected.length} 篇`}
          </button>
        </div>

        <div className="mt-2 flex flex-wrap gap-3">
          {PRESETS.map((p) => (
            <button
              key={p.q}
              type="button"
              onClick={() => {
                setQuestion(p.q);
                if (p.pick) {
                  const ids = p.pick
                    .map((kw) =>
                      others.find((d) =>
                        kw === "BERT"
                          ? d.title.toUpperCase().startsWith("BERT")
                          : d.title.includes(kw) && !d.is_scanned,
                      )?.doc_id,
                    )
                    .filter((x): x is string => Boolean(x));
                  if (ids.length >= 2) setSelected(ids);
                }
              }}
              className="font-mono text-[10.5px] text-ink/40 underline-offset-2 hover:text-ink hover:underline"
            >
              {p.q}
            </button>
          ))}
        </div>

        {error ? <p className="mt-3 text-[12px] text-signal">{error}</p> : null}

        {result ? (
          <div className="mt-5 grid grid-cols-[1fr_320px] gap-6">
            <article className="border border-haze bg-mist px-5 py-4">
              <div className="mb-2 flex flex-wrap items-center gap-x-3 font-mono text-[10px] text-ink/45">
                <span>{result.mode === "llm" ? "大模型对比" : "仅证据"}</span>
                <span>·</span>
                <span>{result.docs.length} 篇</span>
                <span>·</span>
                <span>{result.evidence.length} 条证据</span>
                {result.warnings.length > 0 ? (
                  <span className="text-signal">⚠ {result.warnings[0]}</span>
                ) : null}
              </div>
              <Markdown
                text={result.answer}
                className="text-[12.8px] leading-[1.9] text-ink/85"
              />
            </article>

            <aside>
              <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-ink/40">
                证据来源
              </p>
              <div className="mt-2 space-y-4">
                {grouped.map(([title, items]) => (
                  <div key={title}>
                    <p className="border-b border-haze pb-1 text-[11.5px] font-medium text-ink/75">
                      {title.slice(0, 40)}
                    </p>
                    <ul className="mt-1.5 space-y-2">
                      {items.map((ev) => (
                        <li key={ev.chunk_id}>
                          <button
                            type="button"
                            onClick={() => onOpenDoc(ev.doc_id, ev.page)}
                            className="w-full border-l-2 border-signal/50 pl-2 text-left hover:border-signal"
                          >
                            <span className="font-mono text-[10px] text-signal">
                              [{ev.chunk_id}]
                            </span>
                            <span className="ml-1.5 font-mono text-[9.5px] text-ink/40">
                              p.{ev.page + 1}
                            </span>
                            <span className="mt-0.5 block line-clamp-2 text-[11px] leading-relaxed text-ink/60">
                              {ev.text}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </aside>
          </div>
        ) : null}
      </div>
    </div>
  );
}
