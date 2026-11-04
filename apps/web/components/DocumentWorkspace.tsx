"use client";

import { useMemo, useState } from "react";

import BilingualView from "@/components/BilingualView";
import PdfReader from "@/components/PdfReader";
import QaPanel from "@/components/QaPanel";
import type { Block, ParsedDocument, Section } from "@/lib/api";

type Tab = "reader" | "bilingual" | "abstract" | "sections" | "references" | "tables";
type Focus = { page: number; bbox: number[] } | null;

export default function DocumentWorkspace({ parsed }: { parsed: ParsedDocument }) {
  const [tab, setTab] = useState<Tab>("reader");
  const [focus, setFocus] = useState<Focus>(null);
  const [qaOpen, setQaOpen] = useState(true);
  const stats = parsed.stats;

  const blocksById = useMemo(() => {
    const map = new Map<string, Block>();
    for (const b of parsed.blocks) map.set(b.id, b);
    return map;
  }, [parsed.blocks]);

  const jumpToBlock = (blockId: string) => {
    const block = blocksById.get(blockId);
    if (block) setFocus({ page: block.page, bbox: block.bbox });
  };

  const jumpToRef = (refIndex: number) => {
    const anchor = parsed.cite_anchors.find((a) => a.ref_index === refIndex);
    if (anchor) setFocus({ page: anchor.page, bbox: anchor.bbox });
  };

  const jumpFromQa = (page: number, blockId?: string) => {
    const block = blockId ? blocksById.get(blockId) : undefined;
    setFocus({ page, bbox: block?.bbox ?? [0, 0, 40, 12] });
    setTab("reader");
  };

  return (
    <div className="flex h-screen min-w-0 flex-1 flex-col">
      <header className="sheet-grid border-b border-haze bg-mist px-10 pb-4 pt-7">
        <div className="max-w-[900px]">
          <h1 className="font-serif text-[26px] leading-[1.2] tracking-tight text-ink">
            {parsed.title || parsed.file_name}
          </h1>
          {parsed.authors.length > 0 ? (
            <p className="mt-2 text-[12.5px] leading-relaxed text-ink/70">
              {parsed.authors.join(" · ")}
            </p>
          ) : null}
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[10.5px] text-ink/50">
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
        <div className="flex items-center">
          {(
            [
              ["reader", "阅读"],
              ["bilingual", "对照"],
              ["abstract", "正文"],
              ["sections", `章节树 · ${stats?.heading_count ?? 0}`],
              ["references", `参考文献 · ${stats?.reference_count ?? 0}`],
              ["tables", `表格 · ${stats?.table_count ?? 0}`],
            ] as [Tab, string][]
          ).map(([key, label]) => (
            <button key={key} type="button" className="tab" data-active={tab === key} onClick={() => setTab(key)}>
              {label}
            </button>
          ))}
          {!qaOpen ? (
            <button
              type="button"
              onClick={() => setQaOpen(true)}
              className="ml-auto mb-1 border border-blueprint px-2.5 py-1 text-[11.5px] text-blueprint hover:bg-blueprint hover:text-mist"
            >
              问答
            </button>
          ) : null}
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        <main
          className={
            tab === "reader" || tab === "bilingual"
              ? "min-h-0 flex-1 overflow-hidden"
              : "min-h-0 flex-1 overflow-y-auto bg-paper px-10 py-8"
          }
        >
          {tab === "reader" ? (
            <PdfReader docId={parsed.doc_id} anchors={parsed.cite_anchors} focus={focus} />
          ) : null}
          {tab === "bilingual" ? (
            <BilingualView
              docId={parsed.doc_id}
              onJump={(page, bbox) => setFocus({ page, bbox })}
            />
          ) : null}
          {tab === "abstract" ? <AbstractPanel parsed={parsed} onJump={jumpToBlock} /> : null}
          {tab === "sections" ? <SectionsPanel parsed={parsed} onJump={jumpToBlock} /> : null}
          {tab === "references" ? <ReferencesPanel parsed={parsed} onJump={jumpToRef} /> : null}
          {tab === "tables" ? <TablesPanel parsed={parsed} /> : null}
        </main>
        {qaOpen ? (
          <QaPanel docId={parsed.doc_id} onJump={jumpFromQa} onCollapse={() => setQaOpen(false)} />
        ) : null}
      </div>
    </div>
  );
}

function Rail({ page }: { page: number }) {
  return <div className="rail">p.{page + 1}</div>;
}

function AbstractPanel({ parsed, onJump }: { parsed: ParsedDocument; onJump: (id: string) => void }) {
  const groups = useMemo(() => groupByPage(parsed.blocks.slice(0, 30)), [parsed.blocks]);
  return (
    <div className="max-w-[820px]">
      <p className="mb-6 text-[13px] leading-relaxed text-ink/55">
        以下为解析出的正文段落，左侧页码即原文坐标。点击任意段落可跳到 PDF 对应位置。
      </p>
      {groups.map(([page, blocks]) => (
        <div key={page} className="flex border-b border-haze/60 py-4 last:border-b-0">
          <Rail page={page} />
          <div className="space-y-2">
            {blocks.map((b) => (
              <button
                key={b.id}
                type="button"
                onClick={() => onJump(b.id)}
                className={`block w-full text-left text-[14px] leading-[1.85] hover:bg-mist/70 ${
                  b.kind === "formula" ? "font-mono text-[12.5px] text-ink/70" : ""
                }`}
              >
                {b.text}
              </button>
            ))}
          </div>
        </div>
      ))}
      {groups.length === 0 ? <p className="text-[13px] text-ink/50">未解析出正文段落。</p> : null}
    </div>
  );
}

function SectionsPanel({
  parsed,
  onJump,
}: {
  parsed: ParsedDocument;
  onJump: (blockId: string) => void;
}) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  return (
    <div className="max-w-[820px]">
      <p className="mb-5 text-[13px] leading-relaxed text-ink/55">
        标题树由字号、编号与位置共同判定；编号层级（1 / 2.1 / 2.1.3）优先于字号推断。点击可定位到原文。
      </p>
      <SectionNodes nodes={parsed.sections} depth={0} open={open} toggle={setOpen} onJump={onJump} />
      {parsed.sections.length === 0 ? <p className="text-[13px] text-ink/50">未识别到标题。</p> : null}
    </div>
  );
}

function SectionNodes({
  nodes,
  depth,
  open,
  toggle,
  onJump,
}: {
  nodes: Section[];
  depth: number;
  open: Record<string, boolean>;
  toggle: (v: Record<string, boolean>) => void;
  onJump: (blockId: string) => void;
}) {
  return (
    <ul className="space-y-0.5">
      {nodes.map((node) => {
        const expanded = open[node.id] ?? depth < 1;
        return (
          <li key={node.id}>
            <div className="flex items-baseline gap-2 border-b border-haze/50">
              <button
                type="button"
                onClick={() => toggle({ ...open, [node.id]: !expanded })}
                className="w-5 shrink-0 py-2 text-center font-mono text-[10px] text-ink/35"
                aria-label={expanded ? "折叠" : "展开"}
              >
                {node.children.length > 0 ? (expanded ? "−" : "+") : "·"}
              </button>
              <button
                type="button"
                onClick={() => onJump(node.block_id)}
                className="flex flex-1 items-baseline gap-3 py-2 text-left hover:bg-mist/70"
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
              </button>
            </div>
            {expanded && node.children.length > 0 ? (
              <SectionNodes
                nodes={node.children}
                depth={depth + 1}
                open={open}
                toggle={toggle}
                onJump={onJump}
              />
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

function ReferencesPanel({
  parsed,
  onJump,
}: {
  parsed: ParsedDocument;
  onJump: (refIndex: number) => void;
}) {
  return (
    <div className="max-w-[860px]">
      <p className="mb-5 text-[13px] leading-relaxed text-ink/55">
        编号与正文中的 <span className="cite">[n]</span> 一一对应；点击条目可跳到正文引用位置，锚点是字符级坐标。
      </p>
      <ol className="space-y-3">
        {parsed.references.map((ref) => (
          <li key={ref.index} className="flex gap-4 border-b border-haze/50 pb-3">
            <button
              type="button"
              onClick={() => onJump(ref.index)}
              className="w-9 shrink-0 pt-0.5 text-left font-mono text-[12px] text-signal hover:underline"
            >
              [{ref.index}]
            </button>
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
