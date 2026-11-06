"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { translateSelection } from "@/lib/api";
import type { CiteAnchor } from "@/lib/api";

type Focus = { page: number; bbox: number[] } | null;

type Props = {
  docId: string;
  anchors: CiteAnchor[];
  focus: Focus;
  onPageChange?: (page: number) => void;
};

type Selection = {
  text: string;
  x: number;
  y: number;
  loading: boolean;
  target: string;
  mode: string;
} | null;

/**
 * PDF 阅读器：Canvas 渲染 + 解析坐标叠加。
 *
 * 关键点是**同一套坐标系**：解析阶段产出的 bbox 是 PDF 用户坐标，
 * 这里只乘一个 scale，锚点就能严丝合缝地贴回原文——不需要二次 OCR 或猜测。
 */
export default function PdfReader({ docId, anchors, focus, onPageChange }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const textLayerRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const pdfRef = useRef<import("pdfjs-dist").PDFDocumentProxy | null>(null);

  const [selection, setSelection] = useState<Selection>(null);

  const [numPages, setNumPages] = useState(0);
  const [page, setPage] = useState(1);
  const [box, setBox] = useState({ w: 0, h: 0 });
  const [baseWidth, setBaseWidth] = useState(612);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const go = useCallback(
    (next: number) => {
      setPage((prev) => {
        const target = Math.min(Math.max(1, next), numPages || 1);
        if (target !== prev) onPageChange?.(target);
        return target;
      });
    },
    [numPages, onPageChange],
  );

  // 加载文档
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";
        const doc = await pdfjs.getDocument({ url: `/api/documents/${docId}/file` }).promise;
        if (cancelled) return;
        pdfRef.current = doc;
        setNumPages(doc.numPages);
        setPage(1);
      } catch (e) {
        if (!cancelled) setError((e as Error).message.slice(0, 160));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [docId]);

  // 渲染当前页
  useEffect(() => {
    const pdf = pdfRef.current;
    const canvas = canvasRef.current;
    if (!pdf || !canvas || loading) return;
    let cancelled = false;

    (async () => {
      const pdfPage = await pdf.getPage(page);
      const base = pdfPage.getViewport({ scale: 1 });
      const containerWidth = containerRef.current?.clientWidth ?? base.width;
      const scale = Math.min(1.6, Math.max(0.5, (containerWidth - 8) / base.width));
      const viewport = pdfPage.getViewport({ scale });
      const dpr = Math.min(window.devicePixelRatio || 1, 2);

      canvas.width = Math.floor(viewport.width * dpr);
      canvas.height = Math.floor(viewport.height * dpr);
      canvas.style.width = `${Math.floor(viewport.width)}px`;
      canvas.style.height = `${Math.floor(viewport.height)}px`;

      const ctx = canvas.getContext("2d");
      if (!ctx || cancelled) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, viewport.width, viewport.height);
      await pdfPage.render({ canvasContext: ctx, viewport }).promise;

      // 文本层：让 PDF 可以像网页一样划词选中（翻译、复制都依赖它）
      const layer = textLayerRef.current;
      if (layer && !cancelled) {
        layer.innerHTML = "";
        layer.style.width = `${Math.floor(viewport.width)}px`;
        layer.style.height = `${Math.floor(viewport.height)}px`;
        // pdf.js 4 用 calc(var(--scale-factor) * Npx) 定位文字，必须显式告知缩放比
        layer.style.setProperty("--scale-factor", String(scale));
        try {
          const pdfjs = await import("pdfjs-dist");
          const TextLayerCtor = (pdfjs as unknown as { TextLayer: new (opts: unknown) => { render: () => Promise<void> } })
            .TextLayer;
          const textLayer = new TextLayerCtor({
            textContentSource: await pdfPage.getTextContent(),
            container: layer,
            viewport,
          });
          await textLayer.render();
        } catch (e) {
          // 文本层失败不影响图片阅读，只是不能划词
          console.warn("text layer failed", e);
        }
      }

      if (!cancelled) {
        setBox({ w: viewport.width, h: viewport.height });
        setBaseWidth(base.width);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [page, loading, docId]);

  // 外部跳转：翻到目标页
  useEffect(() => {
    if (focus) setPage(Math.min(Math.max(1, focus.page + 1), numPages || 1));
  }, [focus, numPages]);

  // 键盘翻页
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;
      if (e.key === "ArrowLeft") go(page - 1);
      if (e.key === "ArrowRight") go(page + 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, page]);

  const pageAnchors = anchors.filter((a) => a.page === page - 1);
  const ratio = baseWidth > 0 ? box.w / baseWidth : 1;

  const handleMouseUp = useCallback(() => {
    const sel = window.getSelection();
    const layer = textLayerRef.current;
    const stage = stageRef.current;
    if (!sel || sel.isCollapsed || !layer || !stage || !sel.anchorNode) return;
    if (!layer.contains(sel.anchorNode)) return;

    const text = sel.toString().trim();
    if (text.length < 2) return;

    const rect = sel.getRangeAt(0).getBoundingClientRect();
    const stageRect = stage.getBoundingClientRect();
    const anchor = {
      x: Math.min(Math.max(rect.left - stageRect.left + rect.width / 2, 140), stageRect.width - 140),
      y: rect.bottom - stageRect.top + 8,
    };

    setSelection({ text, x: anchor.x, y: anchor.y, loading: true, target: "", mode: "" });
    translateSelection(text)
      .then((res) =>
        setSelection((prev) =>
          prev && prev.text === text
            ? { ...prev, loading: false, target: res.target, mode: res.mode }
            : prev,
        ),
      )
      .catch(() =>
        setSelection((prev) => (prev && prev.text === text ? { ...prev, loading: false, target: "翻译失败", mode: "error" } : prev)),
      );
  }, []);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 border-b border-haze bg-mist px-6 py-2 font-mono text-[11px] text-ink/60">
        <button type="button" onClick={() => go(page - 1)} className="px-2 py-1 hover:bg-ink/5" aria-label="上一页">
          ←
        </button>
        <span>
          p.{page} / {numPages || "…"}
        </span>
        <button type="button" onClick={() => go(page + 1)} className="px-2 py-1 hover:bg-ink/5" aria-label="下一页">
          →
        </button>
        <span className="ml-2 text-ink/35">{pageAnchors.length} 个引用锚点</span>
        <span className="ml-auto text-ink/35">← → 翻页</span>
      </div>

      <div ref={containerRef} className="flex-1 overflow-auto bg-[#54524c] px-2 py-3">
        {error ? (
          <p className="p-6 text-[13px] text-mist">PDF 加载失败：{error}</p>
        ) : (
          <div ref={stageRef} className="relative mx-auto" style={{ width: box.w || undefined }}>
            <canvas ref={canvasRef} className="block bg-white shadow-[0_2px_18px_rgba(0,0,0,0.35)]" />
            <div
              ref={textLayerRef}
              className="textLayer"
              onMouseUp={handleMouseUp}
              onMouseDown={() => setSelection(null)}
            />
            {pageAnchors.map((a, i) => (
              <span
                key={`${a.ref_index}-${i}`}
                title={`引用 [${a.ref_index}]`}
                className="pointer-events-none absolute rounded-[1px] border border-signal/60 bg-signal/20"
                style={{
                  left: a.bbox[0] * ratio,
                  top: a.bbox[1] * ratio,
                  width: Math.max(6, (a.bbox[2] - a.bbox[0]) * ratio),
                  height: Math.max(6, (a.bbox[3] - a.bbox[1]) * ratio),
                }}
              />
            ))}
            {focus && focus.page === page - 1 ? (
              <span
                className="pointer-events-none absolute animate-pulse rounded-[2px] border-2 border-[#1F4E63] bg-[#1F4E63]/10 transition-all"
                style={{
                  left: focus.bbox[0] * ratio,
                  top: focus.bbox[1] * ratio,
                  width: Math.max(10, (focus.bbox[2] - focus.bbox[0]) * ratio),
                  height: Math.max(10, (focus.bbox[3] - focus.bbox[1]) * ratio),
                }}
              />
            ) : null}
            {loading ? (
              <div className="absolute inset-0 flex items-center justify-center bg-white/70 font-mono text-[11px] text-ink/50">
                渲染中…
              </div>
            ) : null}

            {selection ? (
              <div
                className="absolute z-30 w-[300px] -translate-x-1/2 border border-haze bg-mist shadow-[0_6px_24px_rgba(0,0,0,0.22)]"
                style={{ left: selection.x, top: selection.y }}
                onMouseDown={(e) => e.preventDefault()}
              >
                <div className="flex items-center gap-2 border-b border-haze px-2.5 py-1.5">
                  <span className="font-mono text-[9.5px] text-ink/40">划词翻译</span>
                  <span className="ml-auto font-mono text-[9px] text-ink/30">
                    {selection.mode || "…"}
                  </span>
                  <button
                    type="button"
                    onClick={() => setSelection(null)}
                    className="px-1 text-[11px] text-ink/40 hover:text-ink"
                    aria-label="关闭"
                  >
                    ✕
                  </button>
                </div>
                <div className="max-h-[180px] overflow-y-auto px-2.5 py-2">
                  <p className="mb-1.5 line-clamp-2 text-[10.5px] leading-relaxed text-ink/45">
                    {selection.text}
                  </p>
                  <p className="text-[12px] leading-[1.75] text-ink">
                    {selection.loading ? "翻译中…" : selection.target}
                  </p>
                </div>
              </div>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}
