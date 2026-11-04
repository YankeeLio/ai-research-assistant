"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { type Translation, getTranslation, translateDocument } from "@/lib/api";

/**
 * 中英对照：左右两个独立滚动区，按"块"对齐同步。
 *
 * 为什么不用比例同步：两侧行高差异很大（英文长、中文短，或反之），按滚动比例
 * 对齐会越读越偏；按块索引对齐，任何一处拖动都能把另一侧带到同一段。
 */
export default function BilingualView({
  docId,
  onJump,
}: {
  docId: string;
  onJump: (page: number, bbox: number[]) => void;
}) {
  const [data, setData] = useState<Translation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);

  const leftRef = useRef<HTMLDivElement>(null);
  const rightRef = useRef<HTMLDivElement>(null);
  const syncing = useRef<"left" | "right" | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");
    getTranslation(docId)
      .then((t) => {
        if (!alive) return;
        if (t) setData(t);
      })
      .catch((e: Error) => alive && setError(e.message.slice(0, 160)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [docId]);

  const runTranslate = useCallback(
    async (force: boolean) => {
      setLoading(true);
      setError("");
      try {
        const result = await translateDocument(docId, force);
        setData(result);
      } catch (e) {
        setError((e as Error).message.slice(0, 200));
      } finally {
        setLoading(false);
      }
    },
    [docId],
  );

  /** 找出滚动区里第一个越过顶部的块，把另一侧带过去。 */
  const sync = useCallback((from: "left" | "right") => {
    if (syncing.current && syncing.current !== from) return;
    const src = from === "left" ? leftRef.current : rightRef.current;
    const dst = from === "left" ? rightRef.current : leftRef.current;
    if (!src || !dst) return;

    const rows = Array.from(src.querySelectorAll<HTMLElement>("[data-row]"));
    if (!rows.length) return;
    let index = 0;
    for (let i = 0; i < rows.length; i += 1) {
      if (rows[i].offsetTop - src.scrollTop <= 8) index = i;
      else break;
    }
    const target = dst.querySelector<HTMLElement>(`[data-row="${index}"]`);
    if (!target) return;

    syncing.current = from;
    dst.scrollTop = target.offsetTop;
    window.requestAnimationFrame(() => {
      syncing.current = null;
    });
    setActiveIndex(index);
  }, []);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="max-w-[420px] text-center">
          <p className="font-mono text-[11px] text-ink/45">正在翻译全文…</p>
          <p className="mt-2 text-[12px] leading-relaxed text-ink/50">
            本地模型逐段翻译，首次运行需要加载模型，约需 1-3 分钟。
          </p>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="max-w-[460px]">
          <p className="font-serif text-[17px]">还没有译文</p>
          <p className="mt-2 text-[12.5px] leading-relaxed text-ink/60">
            按段落生成中英对照。公式、参考文献不翻译；引用编号 [12] 原样保留。
          </p>
          {error ? <p className="mt-2 text-[12px] text-signal">{error}</p> : null}
          <div className="mt-4 flex gap-2">
            <button
              type="button"
              onClick={() => runTranslate(false)}
              className="border border-blueprint px-3 py-1.5 text-[12px] text-blueprint hover:bg-blueprint hover:text-mist"
            >
              生成译文
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-3 border-b border-haze bg-mist px-6 py-2 font-mono text-[10.5px] text-ink/50">
        <span>{data.count} 段</span>
        <span>·</span>
        <span>译自 {data.translator}</span>
        <span className="ml-auto flex items-center gap-3">
          <button type="button" onClick={() => runTranslate(true)} className="hover:text-ink">
            重新翻译
          </button>
        </span>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-2 divide-x divide-haze">
        <div
          ref={leftRef}
          onScroll={() => sync("left")}
          className="min-h-0 overflow-y-auto px-6 py-4"
        >
          {data.items.map((item, i) => (
            <div
              key={item.block_id}
              data-row={i}
              className={`cursor-pointer border-l-2 py-3 pl-3 pr-2 transition-colors ${
                i === activeIndex ? "border-signal/70 bg-mist/60" : "border-transparent hover:bg-mist/40"
              }`}
              onClick={() => onJump(item.page, item.bbox)}
            >
              <div className="mb-1 font-mono text-[9.5px] text-ink/35">p.{item.page + 1}</div>
              <p className="text-[13px] leading-[1.85] text-ink/80">{item.source}</p>
            </div>
          ))}
        </div>

        <div
          ref={rightRef}
          onScroll={() => sync("right")}
          className="min-h-0 overflow-y-auto bg-mist/40 px-6 py-4"
        >
          {data.items.map((item, i) => (
            <div
              key={item.block_id}
              data-row={i}
              className={`cursor-pointer border-l-2 py-3 pl-3 pr-2 transition-colors ${
                i === activeIndex ? "border-blueprint/70 bg-white/50" : "border-transparent hover:bg-white/40"
              }`}
              onClick={() => onJump(item.page, item.bbox)}
            >
              <div className="mb-1 font-mono text-[9.5px] text-ink/35">p.{item.page + 1}</div>
              <p className="text-[13.5px] leading-[1.9] text-ink">{item.target || item.source}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
