"use client";

import { useCallback, useEffect, useState } from "react";

import { type ArxivItem, ingestArxiv, recommendPapers, searchArxiv } from "@/lib/api";

const PRESETS = ["all:vision transformer", "all:retrieval augmented generation", "all:LLM agent"];

export default function SearchView({ onIngested }: { onIngested: () => void }) {
  const [query, setQuery] = useState("all:retrieval augmented generation");
  const [items, setItems] = useState<ArxivItem[]>([]);
  const [recs, setRecs] = useState<ArxivItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [recLoading, setRecLoading] = useState(false);
  const [ingesting, setIngesting] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const run = useCallback(async (q: string) => {
    setLoading(true);
    setError("");
    try {
      const data = await searchArxiv(q, 12);
      setItems(data.items);
      if (data.filtered_in_library > 0) {
        setMessage(`已从结果中过滤 ${data.filtered_in_library} 篇库内已有论文`);
      } else {
        setMessage("");
      }
    } catch (e) {
      setError((e as Error).message.slice(0, 160));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void run(query);
    // 推荐单独按需触发：首屏同时打检索 + 推荐会让向量模型排队，前端要等 30s 以上
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadRecs = useCallback(async () => {
    setRecLoading(true);
    try {
      const data = await recommendPapers("all:retrieval augmented generation", 6);
      setRecs(data.items);
    } catch (e) {
      setError((e as Error).message.slice(0, 160));
    } finally {
      setRecLoading(false);
    }
  }, []);

  const ingest = useCallback(
    async (arxivId: string) => {
      setIngesting(arxivId);
      setError("");
      try {
        const result = await ingestArxiv(arxivId);
        setItems((prev) =>
          prev.map((p) => (p.arxiv_id === arxivId ? { ...p, in_library: true } : p)),
        );
        setMessage(
          `已入库《${result.document.title.slice(0, 40)}》，解析 ${result.document.page_count} 页`,
        );
        onIngested();
      } catch (e) {
        setError((e as Error).message.slice(0, 200));
      } finally {
        setIngesting(null);
      }
    },
    [onIngested],
  );

  return (
    <div className="flex h-screen min-w-0 flex-1 flex-col">
      <header className="sheet-grid border-b border-haze bg-mist px-10 pb-4 pt-7">
        <h1 className="font-serif text-[26px] tracking-tight">检索发现</h1>
        <p className="mt-1.5 text-[12px] text-ink/55">
          结果按"与本地文献库的相关性 + 是否附带开源代码 + 时效"重排，而不是照搬 arXiv 默认顺序。
        </p>
        <form
          className="mt-4 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void run(query);
          }}
        >
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-[420px] border border-haze bg-paper px-3 py-2 font-mono text-[12px] outline-none focus:border-blueprint"
            placeholder='检索词，支持 arXiv 语法，如 all:"retrieval augmented generation"'
          />
          <button
            type="submit"
            disabled={loading}
            className="border border-blueprint px-4 py-2 text-[12px] text-blueprint hover:bg-blueprint hover:text-mist disabled:opacity-40"
          >
            {loading ? "检索中…" : "检索"}
          </button>
          <div className="ml-2 flex items-center gap-2">
            {PRESETS.map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => {
                  setQuery(p);
                  void run(p);
                }}
                className="font-mono text-[10.5px] text-ink/40 underline-offset-2 hover:text-ink hover:underline"
              >
                {p.replace("all:", "")}
              </button>
            ))}
          </div>
        </form>
        {message ? <p className="mt-2 font-mono text-[10.5px] text-blueprint">{message}</p> : null}
        {error ? <p className="mt-2 text-[11.5px] text-signal">{error}</p> : null}
      </header>

      <div className="flex min-h-0 flex-1">
        <div className="min-h-0 flex-1 overflow-y-auto px-10 py-6">
          <p className="mb-3 font-mono text-[10px] uppercase tracking-[0.16em] text-ink/40">
            检索结果 · {items.length}
          </p>
          <ul className="space-y-3">
            {items.map((item) => (
              <li key={item.arxiv_id} className="border border-haze bg-mist px-4 py-3">
                <div className="flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="font-serif text-[14.5px] leading-snug">{item.title}</p>
                    <p className="mt-1 font-mono text-[10px] text-ink/40">
                      arXiv:{item.arxiv_id} · {item.published.slice(0, 10)} ·{" "}
                      {item.authors.slice(0, 3).join(", ")}
                      {item.authors.length > 3 ? " 等" : ""}
                    </p>
                    <p className="mt-1.5 line-clamp-2 text-[11.5px] leading-relaxed text-ink/60">
                      {item.summary}
                    </p>
                    <p className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[10px] text-ink/50">
                      <span className="text-blueprint">相关度 {item.relevance.toFixed(2)}</span>
                      {item.reasons
                        .filter((r) => !r.startsWith("与库内"))
                        .map((r) => (
                          <span key={r}>{r}</span>
                        ))}
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1.5">
                    <span className="font-mono text-[10px] text-ink/35">{item.score.toFixed(2)}</span>
                    <button
                      type="button"
                      disabled={item.in_library || ingesting === item.arxiv_id}
                      onClick={() => void ingest(item.arxiv_id)}
                      className="border border-haze px-2.5 py-1 text-[11px] text-ink/70 hover:border-blueprint hover:text-blueprint disabled:opacity-40"
                    >
                      {item.in_library ? "已入库" : ingesting === item.arxiv_id ? "下载中" : "下钻入库"}
                    </button>
                    {item.code_url ? (
                      <a
                        href={item.code_url}
                        target="_blank"
                        rel="noreferrer"
                        className="font-mono text-[10px] text-blueprint underline-offset-2 hover:underline"
                      >
                        代码
                      </a>
                    ) : null}
                  </div>
                </div>
              </li>
            ))}
          </ul>
          {!loading && items.length === 0 ? (
            <p className="text-[12px] text-ink/50">没有结果。换个关键词，或改用 arXiv 语法。</p>
          ) : null}
        </div>

        <aside className="w-[320px] shrink-0 overflow-y-auto border-l border-haze bg-mist px-5 py-4">
          <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-ink/40">
            为你推荐 · 最新
          </p>
          <button
            type="button"
            onClick={() => void loadRecs()}
            disabled={recLoading}
            className="mt-2 w-full border border-haze px-2 py-1.5 text-[11px] text-ink/70 hover:border-blueprint hover:text-blueprint disabled:opacity-40"
          >
            {recLoading ? "计算中…" : "按库内偏好刷新"}
          </button>
          <ul className="mt-3 space-y-3">
            {recs.map((item) => (
              <li key={item.arxiv_id} className="border-l-2 border-blueprint/40 pl-2">
                <p className="text-[12px] leading-snug text-ink/85">{item.title}</p>
                <p className="mt-0.5 font-mono text-[9.5px] text-ink/40">
                  {item.published.slice(0, 10)} · 相关度 {item.relevance.toFixed(2)}
                  {item.code_url ? " · 有代码" : ""}
                </p>
              </li>
            ))}
            {recs.length === 0 ? (
              <li className="text-[11.5px] text-ink/45">
                {recLoading ? "正在按库内偏好排序…" : "点击上方按钮，按库内文献偏好推荐最新论文"}
              </li>
            ) : null}
          </ul>
        </aside>
      </div>
    </div>
  );
}
