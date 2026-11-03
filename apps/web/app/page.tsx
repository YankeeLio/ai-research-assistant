"use client";

import { useCallback, useEffect, useState } from "react";

import DocumentWorkspace from "@/components/DocumentWorkspace";
import LibraryRail from "@/components/LibraryRail";
import {
  type DocumentSummary,
  type ParsedDocument,
  getParsed,
  listDocuments,
  uploadDocument,
} from "@/lib/api";

export default function Home() {
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [parsed, setParsed] = useState<ParsedDocument | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const list = await listDocuments();
    setDocs(list);
    setActiveId((prev) => prev ?? list[0]?.doc_id ?? null);
    return list;
  }, []);

  useEffect(() => {
    refresh()
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [refresh]);

  useEffect(() => {
    if (!activeId) {
      setParsed(null);
      return;
    }
    let alive = true;
    getParsed(activeId)
      .then((p) => alive && setParsed(p))
      .catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [activeId]);

  const handleUpload = useCallback(
    async (file: File) => {
      setUploading(true);
      setError("");
      try {
        const doc = await uploadDocument(file);
        await refresh();
        setActiveId(doc.doc_id);
      } catch (e) {
        setError((e as Error).message.slice(0, 200));
      } finally {
        setUploading(false);
      }
    },
    [refresh],
  );

  return (
    <div className="flex h-screen overflow-hidden">
      <LibraryRail
        docs={docs}
        activeId={activeId}
        uploading={uploading}
        error={error}
        onSelect={setActiveId}
        onUpload={handleUpload}
      />
      {parsed ? (
        <DocumentWorkspace parsed={parsed} />
      ) : (
        <EmptyState loading={loading} error={error} />
      )}
    </div>
  );
}

function EmptyState({ loading, error }: { loading: boolean; error: string }) {
  return (
    <div className="sheet-grid flex h-screen min-w-0 flex-1 items-center justify-center bg-paper px-10">
      <div className="max-w-[520px]">
        <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-blueprint">
          文献台 · workspace
        </div>
        <h1 className="mt-4 font-serif text-[36px] leading-[1.15] tracking-tight">
          每一句结论，
          <br />
          都回到它被写下的那一页。
        </h1>
        <p className="mt-5 text-[14px] leading-[1.85] text-ink/60">
          {loading
            ? "正在读取文献库…"
            : error
              ? `读取失败：${error}`
              : "导入一篇 PDF 开始。解析器会重建标题树、参考文献与字符级引用锚点——这些坐标是后续问答溯源、双向跳转和对照阅读的地基。"}
        </p>
        <div className="mt-8 flex gap-6 font-mono text-[11px] text-ink/40">
          <span>01 解析</span>
          <span>02 检索</span>
          <span>03 溯源</span>
        </div>
      </div>
    </div>
  );
}
