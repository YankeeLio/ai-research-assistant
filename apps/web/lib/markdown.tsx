import type { ReactNode } from "react";

/**
 * 极简 Markdown 渲染：标题、列表、加粗、行内代码。
 *
 * 引入完整 markdown 库只为这四种语法不值当（还会带来 XSS 面），
 * 而直接把源码铺在页面上又不像成品——这里做一个够用的子集。
 */
export function Markdown({ text, className = "" }: { text: string; className?: string }) {
  const lines = text.split("\n");
  const nodes: ReactNode[] = [];
  let listBuffer: string[] = [];
  let tableBuffer: string[] = [];

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

  const flushTable = () => {
    if (!tableBuffer.length) return;
    const rows = tableBuffer
      .filter((row) => !/^\|[\s:|-]+\|$/.test(row.trim()))
      .map((row) =>
        row
          .trim()
          .replace(/^\|/, "")
          .replace(/\|$/, "")
          .split("|")
          .map((cell) => cell.trim()),
      );
    tableBuffer = [];
    if (!rows.length) return;
    const [head, ...body] = rows;
    nodes.push(
      <div key={`tb-${nodes.length}`} className="my-2 overflow-x-auto">
        <table className="w-full border-collapse text-[11.5px]">
          <thead>
            <tr>
              {head.map((cell, i) => (
                <th key={i} className="border border-haze bg-ink/5 px-2 py-1 text-left">
                  {inline(cell)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.map((row, ri) => (
              <tr key={ri}>
                {row.map((cell, ci) => (
                  <td key={ci} className="border border-haze px-2 py-1 align-top">
                    {inline(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>,
    );
  };

  const flushAll = () => {
    flushList();
    flushTable();
  };

  for (const raw of lines) {
    const line = raw.replace(/\s+$/, "");
    if (line.trim().startsWith("|")) {
      flushList();
      tableBuffer.push(line);
      continue;
    }
    if (tableBuffer.length) flushTable();
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
    } else if (line.startsWith("- ") || line.startsWith("* ")) {
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
  flushAll();
  return <div className={className}>{nodes}</div>;
}

function inline(text: string): ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={i} className="font-semibold text-ink">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return (
        <code key={i} className="rounded bg-ink/5 px-1 py-[1px] font-mono text-[11.5px]">
          {part.slice(1, -1)}
        </code>
      );
    }
    return <span key={i}>{part}</span>;
  });
}
