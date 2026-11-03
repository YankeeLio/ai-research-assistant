"use client";

import { useMemo, useState } from "react";

import type { Block, ParsedDocument, Section } from "@/lib/api";

type Tab = "abstract" | "sections" | "references" | "tables";

export default function DocumentWorkspace({ parsed }: { parsed: ParsedDocument }) {
  const [tab, setTab] = useState<Tab>("abstract");
  const stats = parsed.stats;

  return (
    <div className="flex h-screen min-w-0 flex-1 flex-col">
      <header className="sheet-grid border-b border-haze bg-mist px-10 pb-5 pt-9">
        <div className="max-w-[860px]">
          <h1 className="font-serif text-[30px] leading-[1.2] tracking-tight text-ink">
            {parsed.title || parsed.file_name}
          </h1>
          {parsed.authors.length > 0 ? (
            <p className="mt-3 text-[13px] leading-relaxed text-ink/70">
              {parsed.authors.join(" · ")}
            </p>
          ) : null}
          <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[11px] text-ink/50">
            <span>{stats?.page_count ?? 0} 页</span>
            <span>{parsed.layout === "double" ? "双栏" : parsed.layout === "mixed" ? "混合版式" : "单栏"}</span>
            <span>{parsed.is_scanned ? "扫描件 OCR" : "原生文本层"}</span>
            <span>{stats?.reference_count ?? 0} 条参考文献</span>
            <span>{stats?.cite_anchor_count ?? 0} 个引用锚点</span>
            {stats?.elapsed_ms ? <span>解析 {stats.elapsed_ms} ms</span> : null}
          </div>
        </div>
      </header>

      <div className="border-b border-haze bg-mist px-10">
        <div className="flex">
          {(
            [
              ["abstract", "摘要"],
              ["sections", `章节树 · ${stats?.heading_count ?? 0}`],
              ["references", `参考文献 · ${stats?.reference_count ?? 0}`],
              ["tables", `表格 · ${stats?.table_count ?? 0}`],
            ] as [Tab, string][]
          ).map(([key, label]) => (
            <button key={key} type="button" className="tab" data-active={tab === key} onClick={() => setTab(key)}>
              {label}
            </button>
          ))}
        </div>
      </div>

      <main className="min-h-0 flex-1 overflow-y-auto bg-paper px-10 py-8">
        {tab === "abstract" ? <AbstractPanel parsed={parsed} /> : null}
        {tab === "sections" ? <SectionsPanel parsed={parsed} /> : null}
        {tab === "references" ? <ReferencesPanel parsed={parsed} /> : null}
        {tab === "tables" ? <TablesPanel parsed={parsed} /> : null}
      </main>
    </div>
  );
}

function Rail({ page }: { page: number }) {
  return <div className="rail">p.{page + 1}</div>;
}

function AbstractPanel({ parsed }: { parsed: ParsedDocument }) {
  const groups = useMemo(() => groupByPage(parsed.blocks.slice(0, 24)), [parsed.blocks]);
  return (
    <div className="max-w-[820px]">
      <p className="mb-6 text-[13px] leading-relaxed text-ink/55">
        以下为解析出的正文段落，左侧页码即原文坐标——后续问答的每条引用都会回到这条轨上。
      </p>
      {groups.map(([page, blocks]) => (
        <div key={page} className="flex border-b border-haze/60 py-4 last:border-b-0">
          <Rail page={page} />
          <div className="space-y-2">
            {blocks.map((b) => (
              <p
                key={b.id}
                className={`text-[14px] leading-[1.85] ${
                  b.kind === "formula" ? "font-mono text-[12.5px] text-ink/70" : ""
                }`}
              >
                {b.text}
              </p>
            ))}
          </div>
        </div>
      ))}
      {groups.length === 0 ? <p className="text-[13px] text-ink/50">未解析出正文段落。</p> : null}
    </div>
  );
}

function SectionsPanel({ parsed }: { parsed: ParsedDocument }) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  return (
    <div className="max-w-[820px]">
      <p className="mb-5 text-[13px] leading-relaxed text-ink/55">
        标题树由字号、编号与位置共同判定；编号层级（1 / 2.1 / 2.1.3）优先于字号推断。
      </p>
      <SectionNodes nodes={parsed.sections} depth={0} open={open} toggle={setOpen} />
      {parsed.sections.length === 0 ? <p className="text-[13px] text-ink/50">未识别到标题。</p> : null}
    </div>
  );
}

function SectionNodes({
  nodes,
  depth,
  open,
  toggle,
}: {
  nodes: Section[];
  depth: number;
  open: Record<string, boolean>;
  toggle: (v: Record<string, boolean>) => void;
}) {
  return (
    <ul className="space-y-0.5">
      {nodes.map((node) => {
        const expanded = open[node.id] ?? depth < 1;
        return (
          <li key={node.id}>
            <button
              type="button"
              onClick={() => toggle({ ...open, [node.id]: !expanded })}
              className="flex w-full items-baseline gap-3 border-b border-haze/50 py-2 text-left hover:bg-mist/70"
              style={{ paddingLeft: depth * 18 }}
            >
              <span className="w-12 shrink-0 font-mono text-[11px] text-ink/40">p.{node.page + 1}</span>
              <span
                className={
                  depth === 0
                    ? "font-serif text-[16px] leading-snug"
                    : "text-[13.5px] leading-snug text-ink/85"
                }
              >
                {node.title}
              </span>
              {node.children.length > 0 ? (
                <span className="ml-auto font-mono text-[10px] text-ink/30">
                  {expanded ? "−" : `+${node.children.length}`}
                </span>
              ) : null}
            </button>
            {expanded && node.children.length > 0 ? (
              <SectionNodes nodes={node.children} depth={depth + 1} open={open} toggle={toggle} />
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

function ReferencesPanel({ parsed }: { parsed: ParsedDocument }) {
  return (
    <div className="max-w-[860px]">
      <p className="mb-5 text-[13px] leading-relaxed text-ink/55">
        编号与正文中的 <span className="cite">[n]</span> 一一对应；锚点坐标为字符级，点击即可定位。
      </p>
      <ol className="space-y-3">
        {parsed.references.map((ref) => (
          <li key={ref.index} className="flex gap-4 border-b border-haze/50 pb-3">
            <span className="w-9 shrink-0 pt-0.5 font-mono text-[12px] text-signal">[{ref.index}]</span>
            <div className="min-w-0">
              <p className="text-[13px] leading-relaxed text-ink/85">{ref.text}</p>
              <p className="mt-1 font-mono text-[10px] text-ink/40">
                p.{ref.page + 1}
                {ref.year ? ` · ${ref.year}` : ""}
                {ref.arxiv_id ? ` · arXiv:${ref.arxiv_id}` : ""}
              </p>
            </div>
          </li>
        ))}
      </ol>
      {parsed.references.length === 0 ? <p className="text-[13px] text-ink/50">未识别到参考文献。</p> : null}
    </div>
  );
}

function TablesPanel({ parsed }: { parsed: ParsedDocument }) {
  return (
    <div className="max-w-[860px] space-y-8">
      {parsed.tables.map((table) => (
        <figure key={table.id}>
          <figcaption className="mb-2 font-mono text-[10px] uppercase tracking-[0.14em] text-ink/40">
            p.{table.page + 1} · {table.rows.length}×{table.rows[0]?.length ?? 0}
          </figcaption>
          <div className="overflow-x-auto border border-haze bg-mist">
            <table className="w-full border-collapse text-[12px]">
              <tbody>
                {table.rows.map((row, ri) => (
                  <tr key={ri} className={ri === 0 ? "bg-ink/5 font-semibold" : ""}>
                    {row.map((cell, ci) => (
                      <td key={ci} className="border-b border-haze/70 px-3 py-1.5 align-top">
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </figure>
      ))}
      {parsed.tables.length === 0 ? <p className="text-[13px] text-ink/50">未识别到表格。</p> : null}
    </div>
  );
}

function groupByPage(blocks: Block[]): [number, Block[]][] {
  const map = new Map<number, Block[]>();
  for (const b of blocks) {
    const list = map.get(b.page) ?? [];
    list.push(b);
    map.set(b.page, list);
  }
  return [...map.entries()].sort((a, b) => a[0] - b[0]);
}
