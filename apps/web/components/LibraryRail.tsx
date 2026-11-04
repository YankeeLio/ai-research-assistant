"use client";

import { useRef } from "react";

import type { DocumentSummary } from "@/lib/api";

type Props = {
  docs: DocumentSummary[];
  activeId: string | null;
  uploading: boolean;
  error: string;
  activeView: "doc" | "graph" | "search";
  onSelect: (id: string) => void;
  onUpload: (file: File) => void;
  onOpenGraph: () => void;
  onOpenSearch: () => void;
};

export default function LibraryRail({
  docs,
  activeId,
  uploading,
  error,
  activeView,
  onSelect,
  onUpload,
  onOpenGraph,
  onOpenSearch,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <aside className="flex h-screen w-[264px] shrink-0 flex-col bg-graphite text-mist">
      <header className="border-b border-white/10 px-5 py-5">
        <div className="font-serif text-[19px] leading-none tracking-tight">SciLoom</div>
        <div className="mt-1.5 font-mono text-[10px] uppercase tracking-[0.18em] text-white/40">
          智研织机 · 文献台
        </div>
      </header>

      <div className="px-5 py-4">
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={uploading}
          className="w-full border border-white/25 px-3 py-2 text-left text-[13px] transition-colors hover:border-white/60 hover:bg-white/5 disabled:opacity-50"
        >
          {uploading ? "解析中…" : "＋ 导入 PDF"}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) onUpload(file);
            e.target.value = "";
          }}
        />
        {error ? <p className="mt-2 text-[11px] leading-relaxed text-signal">{error}</p> : null}
        <button
          type="button"
          onClick={onOpenGraph}
          disabled={docs.length === 0}
          className={`mt-2 w-full border px-3 py-2 text-left text-[13px] transition-colors disabled:opacity-40 ${
            activeView === "graph"
              ? "border-white/60 bg-white/10"
              : "border-white/20 hover:border-white/50 hover:bg-white/5"
          }`}
        >
          ◇ 引用图谱
        </button>
        <button
          type="button"
          onClick={onOpenSearch}
          className={`mt-2 w-full border px-3 py-2 text-left text-[13px] transition-colors ${
            activeView === "search"
              ? "border-white/60 bg-white/10"
              : "border-white/20 hover:border-white/50 hover:bg-white/5"
          }`}
        >
          ◈ 检索发现
        </button>
      </div>

      <nav className="min-h-0 flex-1 overflow-y-auto px-3 pb-6">
        <div className="px-2 pb-2 font-mono text-[10px] uppercase tracking-[0.16em] text-white/35">
          库 · {docs.length} 篇
        </div>
        {docs.map((doc) => {
          const active = doc.doc_id === activeId;
          return (
            <button
              key={doc.doc_id}
              type="button"
              onClick={() => onSelect(doc.doc_id)}
              className={`mb-1 block w-full border-l-2 px-3 py-2.5 text-left transition-colors ${
                active
                  ? "border-signal bg-white/8"
                  : "border-transparent hover:border-white/30 hover:bg-white/5"
              }`}
            >
              <div className="line-clamp-2 font-serif text-[13px] leading-snug">
                {doc.title || doc.file_name}
              </div>
              <div className="mt-1 flex items-center gap-2 font-mono text-[10px] text-white/40">
                <span>{doc.page_count}p</span>
                <span>·</span>
                <span>{doc.is_scanned ? "SCAN" : "TEXT"}</span>
                {doc.version_hint ? (
                  <>
                    <span>·</span>
                    <span className="text-white/60">{doc.version_hint}</span>
                  </>
                ) : null}
              </div>
              {doc.status === "failed" ? (
                <div className="mt-1 text-[10px] text-signal">解析失败</div>
              ) : null}
            </button>
          );
        })}
        {docs.length === 0 ? (
          <p className="px-2 py-6 text-[12px] leading-relaxed text-white/40">
            库里还没有文献。
            <br />
            导入一篇论文开始。
          </p>
        ) : null}
      </nav>

      <footer className="border-t border-white/10 px-5 py-3 font-mono text-[10px] text-white/30">
        OCR · RAG · GRAPH
      </footer>
    </aside>
  );
}
