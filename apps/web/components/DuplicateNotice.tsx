"use client";

import { useEffect, useState } from "react";

import { type DocumentSummary, type VersionDiff, getDiff } from "@/lib/api";

/**
 * 入库重复提示：对应赛题"主动向用户发出去重预警，并支持覆盖/保留"。
 * 文案直接给出判断依据，避免用户只看到一个相似度数字。
 */
export function DuplicateNotice({
  doc,
  onResolve,
  onDismiss,
}: {
  doc: DocumentSummary;
  onResolve: (action: "keep_existing" | "replace" | "keep_both") => void;
  onDismiss: () => void;
}) {
  const isIdentical = doc.duplicate_verdict === "identical";
  return (
    <div className="pointer-events-auto w-[420px] border border-signal/40 bg-mist shadow-[0_8px_30px_rgba(0,0,0,0.18)]">
      <div className="flex items-start gap-2 border-b border-haze px-4 py-3">
        <span className="mt-0.5 inline-block h-2 w-2 shrink-0 rounded-full bg-signal" />
        <div className="min-w-0">
          <p className="text-[13px] font-semibold">
            {isIdentical ? "库中已存在完全相同的论文" : "疑似重复：同一篇论文的另一个版本"}
          </p>
          <p className="mt-1 text-[12px] leading-relaxed text-ink/65">{doc.duplicate_message}</p>
        </div>
        <button
          type="button"
          onClick={onDismiss}
          className="ml-auto shrink-0 px-1 text-[13px] text-ink/40 hover:text-ink"
          aria-label="关闭"
        >
          ✕
        </button>
      </div>

      <dl className="grid grid-cols-3 gap-2 px-4 py-3 font-mono text-[10.5px] text-ink/55">
        <div>
          <dt className="text-ink/35">判定</dt>
          <dd>{doc.duplicate_verdict || "—"}</dd>
        </div>
        <div>
          <dt className="text-ink/35">正文重合度</dt>
          <dd>{(doc.duplicate_similarity * 100).toFixed(1)}%</dd>
        </div>
        <div>
          <dt className="text-ink/35">本次版本</dt>
          <dd>{doc.version_hint || "—"}</dd>
        </div>
      </dl>

      <div className="flex gap-2 border-t border-haze px-4 py-3">
        <button
          type="button"
          onClick={() => onResolve("keep_existing")}
          className="border border-blueprint px-3 py-1.5 text-[12px] text-blueprint hover:bg-blueprint hover:text-mist"
        >
          保留库中版本
        </button>
        <button
          type="button"
          onClick={() => onResolve("replace")}
          className="border border-haze px-3 py-1.5 text-[12px] text-ink/70 hover:border-ink/40"
        >
          用本次替换
        </button>
        <button
          type="button"
          onClick={() => onResolve("keep_both")}
          className="ml-auto px-2 py-1.5 text-[12px] text-ink/45 hover:text-ink"
        >
          两个都留
        </button>
      </div>
    </div>
  );
}

const STATUS_LABEL: Record<string, string> = {
  added: "新增",
  removed: "删除",
  modified: "修改",
  unchanged: "未变",
};

export function DiffPanel({
  oldId,
  newId,
  onClose,
}: {
  oldId: string;
  newId: string;
  onClose: () => void;
}) {
  const [diff, setDiff] = useState<VersionDiff | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    getDiff(oldId, newId)
      .then((d) => alive && setDiff(d))
      .catch((e: Error) => alive && setError(e.message.slice(0, 160)));
    return () => {
      alive = false;
    };
  }, [oldId, newId]);

  return (
    <div className="pointer-events-auto w-[460px] border border-haze bg-mist shadow-[0_8px_30px_rgba(0,0,0,0.18)]">
      <div className="flex items-center border-b border-haze px-4 py-3">
        <p className="font-serif text-[15px]">版本修订差异</p>
        <button
          type="button"
          onClick={onClose}
          className="ml-auto px-1 text-[13px] text-ink/40 hover:text-ink"
          aria-label="关闭"
        >
          ✕
        </button>
      </div>
      <div className="max-h-[360px] overflow-y-auto px-4 py-3">
        {error ? <p className="text-[12px] text-signal">{error}</p> : null}
        {!diff && !error ? <p className="text-[12px] text-ink/50">对比中…</p> : null}
        {diff ? (
          <>
            <p className="text-[12.5px] leading-relaxed text-ink/75">{diff.summary}</p>
            <ul className="mt-3 space-y-1">
              {diff.sections
                .filter((s) => s.status !== "unchanged")
                .map((s, i) => (
                  <li key={`${s.title}-${i}`} className="flex items-baseline gap-2 text-[12px]">
                    <span
                      className={`w-8 shrink-0 font-mono text-[10px] ${
                        s.status === "added"
                          ? "text-blueprint"
                          : s.status === "removed"
                            ? "text-signal"
                            : "text-ink/45"
                      }`}
                    >
                      {STATUS_LABEL[s.status] ?? s.status}
                    </span>
                    <span className="min-w-0 flex-1 truncate">{s.title}</span>
                    <span className="shrink-0 font-mono text-[10px] text-ink/40">
                      +{s.added_sentences}/-{s.removed_sentences}
                    </span>
                  </li>
                ))}
            </ul>
          </>
        ) : null}
      </div>
    </div>
  );
}
