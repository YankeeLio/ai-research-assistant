"use client";

import { useRef, useState } from "react";

import {
  type ChartResult,
  type DiagramResult,
  type OutlineResult,
  generateDiagram,
  generateOutline,
  uploadCsv,
} from "@/lib/api";

type Tab = "outline" | "chart" | "diagram";

export default function WritingView() {
  const [tab, setTab] = useState<Tab>("outline");
  return (
    <div className="flex h-screen min-w-0 flex-1 flex-col">
      <header className="sheet-grid border-b border-haze bg-mist px-10 pb-4 pt-7">
        <h1 className="font-serif text-[26px] tracking-tight">写作 Copilot</h1>
        <p className="mt-1.5 text-[12px] text-ink/55">
          参考文献只从库内取，编号越界会被剔除；图表与图注由同一份数据生成。
        </p>
        <div className="mt-4 flex">
          {(
            [
              ["outline", "论文框架"],
              ["chart", "数据图表"],
              ["diagram", "架构图脚本"],
            ] as [Tab, string][]
          ).map(([key, label]) => (
            <button key={key} type="button" className="tab" data-active={tab === key} onClick={() => setTab(key)}>
              {label}
            </button>
          ))}
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto bg-paper px-10 py-6">
        {tab === "outline" ? <OutlinePanel /> : null}
        {tab === "chart" ? <ChartPanel /> : null}
        {tab === "diagram" ? <DiagramPanel /> : null}
      </div>
    </div>
  );
}

function OutlinePanel() {
  const [idea, setIdea] = useState("用检索增强的方法降低学术问答中的幻觉");
  const [result, setResult] = useState<OutlineResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const run = async () => {
    setLoading(true);
    setError("");
    try {
      setResult(await generateOutline(idea, 5));
    } catch (e) {
      setError((e as Error).message.slice(0, 200));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="grid max-w-[1100px] grid-cols-[1fr_300px] gap-6">
      <div>
        <textarea
          value={idea}
          onChange={(e) => setIdea(e.target.value)}
          rows={2}
          className="w-full resize-none border border-haze bg-mist px-3 py-2 text-[13px] outline-none focus:border-blueprint"
        />
        <button
          type="button"
          onClick={() => void run()}
          disabled={loading}
          className="mt-2 border border-blueprint px-4 py-1.5 text-[12px] text-blueprint hover:bg-blueprint hover:text-mist disabled:opacity-40"
        >
          {loading ? "生成中…" : "生成框架"}
        </button>
        {error ? <p className="mt-2 text-[12px] text-signal">{error}</p> : null}

        {result ? (
          <article className="mt-4 border border-haze bg-mist px-5 py-4">
            <div className="mb-2 flex items-center gap-2 font-mono text-[10px] text-ink/45">
              <span>模式：{result.mode === "llm" ? "大模型生成" : "结构化模板"}</span>
              <span>·</span>
              <span>引用 {result.references.length} 篇库内文献</span>
              {result.warnings.length > 0 ? (
                <span className="text-signal">⚠ {result.warnings[0]}</span>
              ) : null}
            </div>
            <div className="text-[12.5px] leading-[1.9] text-ink/85">
              {renderMarkdown(result.markdown)}
            </div>
          </article>
        ) : null}
      </div>

      <aside className="text-[12px] leading-relaxed text-ink/60">
        <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-ink/40">引用来源</p>
        <ul className="mt-2 space-y-2">
          {result?.references.map((r) => (
            <li key={r.index} className="border-l-2 border-signal/40 pl-2">
              <span className="font-mono text-[10px] text-signal">[{r.index}]</span>{" "}
              {r.title.slice(0, 46)}
            </li>
          ))}
          {!result ? <li className="text-ink/40">生成后显示被引用的库内文献</li> : null}
        </ul>
      </aside>
    </div>
  );
}

function ChartPanel() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("BLEU scores across model families");
  const [chart, setChart] = useState<ChartResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const onFile = async (file: File) => {
    setLoading(true);
    setError("");
    try {
      setChart(await uploadCsv(file, title));
    } catch (e) {
      setError((e as Error).message.slice(0, 200));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-[1100px]">
      <div className="flex items-center gap-2">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="w-[360px] border border-haze bg-mist px-3 py-1.5 text-[12.5px] outline-none focus:border-blueprint"
          placeholder="图标题"
        />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={loading}
          className="border border-blueprint px-4 py-1.5 text-[12px] text-blueprint hover:bg-blueprint hover:text-mist disabled:opacity-40"
        >
          {loading ? "绘制中…" : "上传 CSV 并绘图"}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept=".csv,.tsv,.txt"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void onFile(f);
            e.target.value = "";
          }}
        />
      </div>
      {error ? <p className="mt-2 text-[12px] text-signal">{error}</p> : null}

      {chart ? (
        <div className="mt-5 grid grid-cols-[1fr_360px] gap-6">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={chart.url} alt={title} className="w-full border border-haze bg-white" />
          <div>
            <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-ink/40">
              Figure Caption
            </p>
            <p className="mt-2 border-l-2 border-blueprint/50 pl-3 text-[12.5px] leading-[1.9] text-ink/80">
              {chart.caption}
            </p>
            <p className="mt-3 font-mono text-[10px] text-ink/40">
              {chart.chart_type} · {chart.rows} 行 · {chart.columns.length} 字段
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function DiagramPanel() {
  const [stages, setStages] = useState("PDF, Parser, Chunker, Retriever, LLM, Answer");
  const [title, setTitle] = useState("SciLoom");
  const [result, setResult] = useState<DiagramResult | null>(null);
  const [kind, setKind] = useState<"mermaid" | "tikz" | "graphviz">("mermaid");
  const [loading, setLoading] = useState(false);

  const run = async () => {
    setLoading(true);
    try {
      setResult(
        await generateDiagram(
          stages.split(/[,，]/).map((s) => s.trim()).filter(Boolean),
          title,
        ),
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-[1000px]">
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="w-[180px] border border-haze bg-mist px-3 py-1.5 text-[12.5px] outline-none focus:border-blueprint"
        />
        <input
          value={stages}
          onChange={(e) => setStages(e.target.value)}
          className="w-[520px] border border-haze bg-mist px-3 py-1.5 font-mono text-[12px] outline-none focus:border-blueprint"
          placeholder="用逗号分隔的模块名"
        />
        <button
          type="button"
          onClick={() => void run()}
          disabled={loading}
          className="border border-blueprint px-4 py-1.5 text-[12px] text-blueprint hover:bg-blueprint hover:text-mist disabled:opacity-40"
        >
          {loading ? "生成中…" : "生成脚本"}
        </button>
      </div>

      {result ? (
        <div className="mt-4">
          <div className="flex gap-1">
            {(["mermaid", "tikz", "graphviz"] as const).map((k) => (
              <button
                key={k}
                type="button"
                onClick={() => setKind(k)}
                className={`border px-3 py-1 font-mono text-[11px] ${
                  kind === k ? "border-blueprint text-blueprint" : "border-haze text-ink/50"
                }`}
              >
                {k}
              </button>
            ))}
          </div>
          <pre className="mt-2 overflow-x-auto border border-haze bg-mist px-4 py-3 font-mono text-[11.5px] leading-relaxed">
            {result[kind]}
          </pre>
        </div>
      ) : null}
    </div>
  );
}

/**
 * 极简 Markdown 渲染：只处理标题、列表与加粗。
 * 引入完整 markdown 库只为这三种语法不值当，而直接把源码铺在页面上又不像成品。
 */
function renderMarkdown(md: string) {
  const lines = md.split("\n");
  const nodes: React.ReactNode[] = [];
  let listBuffer: string[] = [];

  const flushList = () => {
    if (!listBuffer.length) return;
    nodes.push(
      <ul key={`ul-${nodes.length}`} className="my-1 list-disc space-y-1 pl-5">
        {listBuffer.map((item, i) => (
          <li key={i}>{inline(item)}</li>
        ))}
      </ul>,
    );
    listBuffer = [];
  };

  for (const raw of lines) {
    const line = raw.replace(/\s+$/, "");
    if (!line.trim()) {
      flushList();
      continue;
    }
    if (line.startsWith("### ")) {
      flushList();
      nodes.push(
        <h4 key={nodes.length} className="mt-3 font-serif text-[14px]">
          {inline(line.slice(4))}
        </h4>,
      );
    } else if (line.startsWith("## ")) {
      flushList();
      nodes.push(
        <h3 key={nodes.length} className="mt-4 font-serif text-[15.5px]">
          {inline(line.slice(3))}
        </h3>,
      );
    } else if (line.startsWith("# ")) {
      flushList();
      nodes.push(
        <h2 key={nodes.length} className="mt-2 font-serif text-[18px] tracking-tight">
          {inline(line.slice(2))}
        </h2>,
      );
    } else if (line.startsWith("- ")) {
      listBuffer.push(line.slice(2));
    } else {
      flushList();
      nodes.push(
        <p key={nodes.length} className="my-2">
          {inline(line)}
        </p>,
      );
    }
  }
  flushList();
  return nodes;
}

function inline(text: string): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={i} className="font-semibold text-ink">
        {part.slice(2, -2)}
      </strong>
    ) : (
      <span key={i}>{part}</span>
    ),
  );
}
