"use client";

import { useCallback, useRef, useState } from "react";

import { type Evidence, askStream } from "@/lib/qa";

type Turn = {
  question: string;
  answer: string;
  evidence: Evidence[];
  warnings: string[];
  mode: string;
  status: string;
  streaming: boolean;
};

const SUGGESTIONS = [
  "这篇论文用了多少块 GPU？什么型号？",
  "BLEU 分数在 WMT 2014 英德任务上是多少？",
  "注意力头数 h 与 dk、dv 的取值是多少？",
  "优化器是什么，β2 设为多少？",
];

export default function QaPanel({
  docId,
  onJump,
  onCollapse,
}: {
  docId: string;
  onJump: (page: number, blockId?: string) => void;
  onCollapse: () => void;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const ask = useCallback(
    async (question: string) => {
      const q = question.trim();
      if (!q || busy) return;
      setInput("");
      setBusy(true);

      const index = turns.length;
      setTurns((prev) => [
        ...prev,
        { question: q, answer: "", evidence: [], warnings: [], mode: "", status: "", streaming: true },
      ]);

      const patch = (fn: (t: Turn) => Turn) =>
        setTurns((prev) => prev.map((t, i) => (i === index ? fn(t) : t)));

      const controller = new AbortController();
      abortRef.current = controller;
      try {
        await askStream(
          docId,
          q,
          (e) => {
            if (e.type === "status") patch((t) => ({ ...t, status: e.message }));
            else if (e.type === "evidence") patch((t) => ({ ...t, evidence: e.items }));
            else if (e.type === "delta") patch((t) => ({ ...t, answer: t.answer + e.text }));
            else if (e.type === "done")
              patch((t) => ({ ...t, warnings: e.warnings, mode: e.mode, streaming: false }));
            else if (e.type === "error")
              patch((t) => ({ ...t, warnings: [e.message], streaming: false }));
          },
          controller.signal,
        );
      } catch (err) {
        patch((t) => ({ ...t, warnings: [(err as Error).message], streaming: false }));
      } finally {
        patch((t) => ({ ...t, streaming: false }));
        setBusy(false);
        abortRef.current = null;
      }
    },
    [busy, docId, turns.length],
  );

  return (
    <aside className="flex h-full w-[380px] shrink-0 flex-col border-l border-haze bg-paper">
      <header className="flex items-center gap-2 border-b border-haze bg-mist px-4 py-3">
        <div>
          <p className="text-[13px] font-semibold">问答 · 带溯源</p>
          <p className="mt-0.5 font-mono text-[10px] text-ink/40">混合检索 → 证据约束 → 引用校验</p>
        </div>
        <button
          type="button"
          onClick={onCollapse}
          className="ml-auto px-1 text-[13px] text-ink/40 hover:text-ink"
          aria-label="收起问答面板"
        >
          ⇥
        </button>
      </header>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-4">
        {turns.length === 0 ? (
          <div className="space-y-2">
            <p className="text-[12.5px] leading-relaxed text-ink/55">
              针对当前论文提问。回答只允许使用检索到的原文片段，并逐句标注来源编号。
            </p>
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => ask(s)}
                className="block w-full border border-haze bg-mist px-3 py-2 text-left text-[12px] text-ink/70 hover:border-blueprint hover:text-ink"
              >
                {s}
              </button>
            ))}
          </div>
        ) : null}

        {turns.map((turn, ti) => (
          <article key={ti} className="space-y-2">
            <p className="text-[12.5px] font-medium leading-relaxed text-ink/85">
              <span className="mr-1.5 font-mono text-[10px] text-blueprint">Q{ti + 1}</span>
              {turn.question}
            </p>

            {turn.answer ? (
              <AnswerBody text={turn.answer} evidence={turn.evidence} onJump={onJump} />
            ) : turn.streaming ? (
              <p className="font-mono text-[11px] text-ink/40">{turn.status || "检索与生成中…"}</p>
            ) : null}

            {turn.evidence.length > 0 ? (
              <details className="border-t border-haze/70 pt-2" open={ti === turns.length - 1}>
                <summary className="cursor-pointer font-mono text-[10.5px] text-ink/45">
                  证据 {turn.evidence.length} 条
                </summary>
                <ul className="mt-2 space-y-2">
                  {turn.evidence.map((ev) => (
                    <li key={ev.chunk_id}>
                      <button
                        type="button"
                        onClick={() => onJump(ev.page, ev.block_ids[0])}
                        className="w-full border-l-2 border-signal/50 pl-2 text-left hover:border-signal"
                      >
                        <span className="font-mono text-[10px] text-signal">[{ev.chunk_id}]</span>
                        <span className="ml-1.5 font-mono text-[10px] text-ink/40">
                          p.{ev.page + 1} · {ev.section || "正文"}
                        </span>
                        <span className="mt-0.5 block line-clamp-2 text-[11.5px] leading-relaxed text-ink/65">
                          {ev.text}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}

            {turn.warnings.length > 0 ? (
              <ul className="space-y-0.5">
                {turn.warnings.map((w) => (
                  <li key={w} className="font-mono text-[10px] text-signal/80">
                    ⚠ {w}
                  </li>
                ))}
              </ul>
            ) : null}
            {turn.mode === "extractive" ? (
              <p className="font-mono text-[10px] text-ink/35">抽取式模式（未配置模型）</p>
            ) : null}
          </article>
        ))}
      </div>

      <form
        className="border-t border-haze bg-mist p-3"
        onSubmit={(e) => {
          e.preventDefault();
          void ask(input);
        }}
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void ask(input);
            }
          }}
          rows={2}
          placeholder="问一个关于这篇论文的问题…（Enter 发送，Shift+Enter 换行）"
          className="w-full resize-none border border-haze bg-paper px-2.5 py-2 text-[12.5px] outline-none focus:border-blueprint"
        />
        <div className="mt-2 flex items-center justify-between">
          <span className="font-mono text-[10px] text-ink/35">答案绑定原文锚点</span>
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="border border-blueprint px-3 py-1 text-[12px] text-blueprint hover:bg-blueprint hover:text-mist disabled:opacity-40"
          >
            {busy ? "生成中" : "提问"}
          </button>
        </div>
      </form>
    </aside>
  );
}

/** 把 [c1] 这类引用标记渲染成可点击的芯片，点击即跳回原文。 */
function AnswerBody({
  text,
  evidence,
  onJump,
}: {
  text: string;
  evidence: Evidence[];
  onJump: (page: number, blockId?: string) => void;
}) {
  const parts = text.split(/(\[c\d+\])/g);
  const byTag = new Map(evidence.map((e) => [`[${e.chunk_id}]`, e]));

  return (
    <p className="whitespace-pre-wrap text-[12.5px] leading-[1.9] text-ink/85">
      {parts.map((part, i) => {
        const ev = byTag.get(part);
        if (!ev) return <span key={i}>{part}</span>;
        return (
          <button
            key={i}
            type="button"
            onClick={() => onJump(ev.page, ev.block_ids[0])}
            className="cite"
            title={`${ev.section || "正文"} · p.${ev.page + 1}`}
          >
            {part}
          </button>
        );
      })}
    </p>
  );
}
